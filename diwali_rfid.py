#!/usr/bin/env python3
"""Run light and music cards from one RFID reader without changing Card Play.

This process imports the installed Card Play player for its reader, decoder,
music controller, and music backend. Stop curio-player.service before starting
it: the two processes cannot grab the same reader simultaneously.
"""

import argparse
import fcntl
import importlib.util
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

LOG = logging.getLogger("diwali-rfid")
EFFECTS = ("diya", "bloom", "orbit", "sparkle", "peacock")
CARD_ID = re.compile(r"[0-9a-f]{14}")


class RedactCardIds(logging.Filter):
    def filter(self, record):
        record.msg = CARD_ID.sub("[card-id]", record.getMessage())
        record.args = ()
        return True


def configure_logging(home):
    handlers = [logging.StreamHandler()]
    log_dir = home / ".local/state/diwali-lights"
    file_handler = None
    try:
        log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        log_dir.chmod(0o700)
        log_path = log_dir / "reader.log"
        file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000,
                                           backupCount=2)
        log_path.chmod(0o600)
        handlers.append(file_handler)
    except OSError as error:
        if file_handler is not None:
            file_handler.close()
        print(f"Private log unavailable: {error}", file=sys.stderr)
    for handler in handlers:
        handler.addFilter(RedactCardIds())
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=handlers, force=True)


def load_lights(path, music_ids=()):
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Light config must be a JSON object")
    try:
        raw_host = data["wled_host"]
        if not isinstance(raw_host, str):
            raise ValueError("not a string")
        host = str(ipaddress.IPv4Address(raw_host))
    except (KeyError, ValueError) as error:
        raise ValueError("wled_host must be WLED's home-network IPv4 address") from error
    brightness = data.get("brightness", 25)
    if type(brightness) is not int or not 1 <= brightness <= 255:
        raise ValueError("brightness must be an integer from 1 to 255")
    cards = data.get("effect_cards")
    if not isinstance(cards, dict) or set(cards) != set(EFFECTS):
        raise ValueError("effect_cards must name all five effects")
    toggle = data.get("start_stop_card")
    ids = [cards[effect] for effect in EFFECTS] + [toggle]
    if any(not isinstance(card_id, str) or not CARD_ID.fullmatch(card_id)
           for card_id in ids):
        raise ValueError("Each light card ID must be 14 lowercase hex characters")
    if len(set(ids)) != len(ids):
        raise ValueError("Light card IDs must be unique")
    if set(ids) & set(music_ids):
        raise ValueError("A light card ID is already used by Card Play")
    return {
        "host": host,
        "brightness": brightness,
        "effects_by_id": {cards[effect]: effect for effect in EFFECTS},
        "toggle_id": toggle,
    }


def load_music_module(path):
    if not path.is_file():
        raise ValueError(f"Card Play runtime is missing: {path}")
    spec = importlib.util.spec_from_file_location("installed_card_play", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("load_config", "Backend", "Controller", "listen", "normalize_scan"):
        if not hasattr(module, name):
            raise ValueError(f"Installed Card Play lacks {name}; inspect its version")
    return module


class LightRunner:
    """Own only the light animation process; music remains Card Play's job."""

    def __init__(self, script, host, brightness, dry_run=False):
        self.script = script
        self.host = host
        self.brightness = brightness
        self.dry_run = dry_run
        self.child = None
        self.effect = None

    def running(self):
        if self.dry_run:
            return self.effect is not None
        if self.child is not None and self.child.poll() is not None:
            LOG.warning("Light show %s exited with code %s; reader will retry",
                        self.effect, self.child.returncode)
            if self.child.stdin is not None:
                self.child.stdin.close()
            self.child = None
            self.effect = None
        return self.child is not None

    @staticmethod
    def forward_output(child):
        for line in child.stdout:
            LOG.info("show: %s", line.rstrip())
        child.stdout.close()

    def start(self, effect):
        if effect not in EFFECTS:
            raise ValueError(f"Unknown light effect: {effect}")
        if self.dry_run:
            self.effect = effect
            LOG.info("SIMULATED light effect %s", effect)
            return
        if self.running():
            try:
                self.child.stdin.write(effect + "\n")
                self.child.stdin.flush()
            except (OSError, ValueError) as error:
                LOG.warning("Could not switch light effect in place: %s", error)
                self.stop()
            else:
                self.effect = effect
                LOG.info("Switched light effect to %s (pid %s)", effect, self.child.pid)
                return
        self.stop()
        args = [sys.executable, "-B", str(self.script), effect,
                "--host", self.host, "--brightness", str(self.brightness),
                "--control-stdin"]
        self.child = subprocess.Popen(args, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True,
                                      bufsize=1, start_new_session=True)
        threading.Thread(target=self.forward_output, args=(self.child,),
                         daemon=True).start()
        LOG.info("Started light effect %s (pid %s)", effect, self.child.pid)
        self.effect = effect

    def pause(self):
        if self.dry_run:
            self.effect = "off"
            return
        if not self.running():
            return
        try:
            self.child.stdin.write("off\n")
            self.child.stdin.flush()
        except (OSError, ValueError) as error:
            LOG.warning("Could not pause light renderer: %s", error)
            self.stop()
        else:
            self.effect = "off"
            LOG.info("Paused light renderer (pid %s)", self.child.pid)

    def stop(self):
        child = self.child
        if child is not None:
            if child.poll() is None:
                child.terminate()  # diwali_animations.py handles SIGTERM and turns WLED off.
                try:
                    child.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    LOG.warning("Light show did not stop in 6 seconds; killing it")
                    child.kill()
                    child.wait()
            else:
                child.wait()
            if child.stdin is not None:
                child.stdin.close()
        if self.effect is not None:
            LOG.info("Stopped light effect %s", self.effect)
        self.child = None
        self.effect = None


class CombinedController:
    """Dispatch only enrolled light cards here; forward every other scan."""

    def __init__(self, music, lights, light_config, normalize, clock=time.monotonic):
        self.music = music
        self.lights = lights
        self.config = light_config
        self.normalize = normalize
        self.clock = clock
        self.last_effect = None
        self.lights_enabled = False
        self.retry_at = 0.0
        self.retry_delay = 5.0
        self.running_since = None
        self.last_light_id = None
        self.last_light_time = -100.0

    def start_lights(self, effect, now):
        try:
            self.lights.start(effect)
        except (OSError, subprocess.SubprocessError) as error:
            LOG.warning("Could not start %s: %s; retrying shortly", effect, error)
            self.running_since = None
        else:
            self.running_since = now
        self.retry_at = now + self.retry_delay
        self.retry_delay = min(self.retry_delay * 2, 60.0)

    def scan(self, token):
        token = self.normalize(token) or token.strip().lower()
        effect = self.config["effects_by_id"].get(token)
        is_toggle = token == self.config["toggle_id"]
        if effect is None and not is_toggle:
            self.music.scan(token)
            return
        now = self.clock()
        if token == self.last_light_id and now - self.last_light_time < 1.5:
            return
        # A light scan cancels an armed music shutdown, as another card scan does.
        self.music.shutdown_arm = None
        if effect is not None:
            LOG.info("Light card selected %s", effect)
            self.last_effect = effect
            self.lights_enabled = True
            self.retry_delay = 5.0
            self.start_lights(effect, now)
        elif self.lights_enabled:
            LOG.info("Light toggle requested off")
            self.lights_enabled = False
            self.running_since = None
            self.lights.pause()
        elif self.last_effect is not None:
            LOG.info("Light toggle requested on: %s", self.last_effect)
            self.lights_enabled = True
            self.retry_delay = 5.0
            self.start_lights(self.last_effect, now)
        else:
            LOG.info("Select a light effect before using Start / Stop")
        self.last_light_id, self.last_light_time = token, now

    def tick(self):
        try:
            self.music.tick()
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            LOG.error("Music recovery failed: %s", error)
            self.music.stop()
        if self.lights_enabled:
            now = self.clock()
            if self.lights.running():
                if self.running_since is not None and now - self.running_since >= 60:
                    self.retry_delay = 5.0
                    self.running_since = None
            elif now >= self.retry_at:
                LOG.warning("Restarting light effect %s", self.last_effect)
                self.start_lights(self.last_effect, now)

    def stop(self):
        self.lights_enabled = False
        try:
            self.lights.stop()
        finally:
            self.music.stop()


def main(argv=None):
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lights-config", type=Path,
                        default=home / ".config/diwali-lights/cards.json")
    parser.add_argument("--music-config", type=Path,
                        default=home / ".config/curio-player/cards.json")
    parser.add_argument("--music-player", type=Path,
                        default=home / ".local/share/curio-player/pi_player.py")
    parser.add_argument("--check", action="store_true", help="validate both configs; no hardware")
    parser.add_argument("--simulate", action="store_true", help="read card IDs from stdin; no hardware")
    args = parser.parse_args(argv)
    os.umask(0o077)
    if args.check or args.simulate:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s",
                            force=True)
    else:
        configure_logging(home)
    LOG.info("Combined reader starting")
    try:
        music_module = load_music_module(args.music_player.expanduser())
        music_config = music_module.load_config(args.music_config.expanduser().resolve())
        light_config = load_lights(args.lights_config.expanduser().resolve(),
                                   music_config["cards"])
        script = Path(__file__).with_name("diwali_animations.py")
        if not script.is_file():
            raise ValueError(f"Light script is missing: {script}")
        if args.check:
            print(f"Valid: {len(music_config['cards'])} music cards, "
                  "five light effects, and Start / Stop. Hardware not checked.")
            return 0
        if not args.simulate and sys.platform != "linux":
            raise ValueError("Real RFID listening requires the Pi; use --simulate here")
        lights = LightRunner(script, light_config["host"], light_config["brightness"],
                             dry_run=args.simulate)

        class MusicBackend(music_module.Backend):
            def shutdown(self):
                lights.stop()
                return super().shutdown()

        backend = MusicBackend(music_config, args.simulate)
        music = music_module.Controller(music_config, backend)
        controller = CombinedController(music, lights, light_config,
                                        music_module.normalize_scan)
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        lock = None
        if not args.simulate:
            lock_path = home / ".local/share/curio-player/controller.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock = lock_path.open("w")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("Card Play still owns the reader; stop curio-player.service") from error
        try:
            if args.simulate:
                for line in sys.stdin:
                    token = line.strip()
                    if token == "quit":
                        break
                    if token:
                        controller.scan(token)
                        controller.tick()
            else:
                music_module.listen(controller)
        finally:
            controller.stop()
            if lock is not None:
                lock.close()
            LOG.info("Combined reader stopped")
        return 0
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, ImportError, subprocess.SubprocessError) as error:
        LOG.error("%s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
