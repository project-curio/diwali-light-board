#!/usr/bin/env python3
"""Animate the 100-pixel Diwali board through WLED.

Live frames use DDP over UDP, avoiding an HTTP reply for every frame.
Use --transport http for comparison with the older playback path.
"""

import argparse
import json
import math
import os
import random
import select
import signal
import socket
import struct
import sys
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PIXELS = 100
HAPPY = (1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14)
DIWALI = (33, 34, 35, 36, 37, 38, 43, 45, 46, 47, 53, 54, 55)
# Clockwise from the top of the board.
DIAMONDS = (
    (23, 24, 25, 26), (28, 29, 30, 31), (39, 40, 41, 42),
    (48, 49, 50, 51), (59, 60, 61, 62), (64, 65, 66, 67),
    (69, 70, 71, 72), (74, 75, 76, 77), (17, 18, 19, 20),
)
RING = tuple(range(78, 93))
TRIANGLE = tuple(range(94, 101))
LETTERS = HAPPY + DIWALI
OUTER = sum(DIAMONDS, ())
MAPPED = frozenset(LETTERS + OUTER + RING + TRIANGLE)
ZONES = (
    ("HAPPY", HAPPY), ("DIWALI", DIWALI), ("triangle", TRIANGLE),
    ("ring", RING), ("diamonds", OUTER),
)

BLACK = (0, 0, 0)
GOLD = (255, 157, 42)
IVORY = (255, 233, 170)
FLAME = (255, 116, 20)
RUBY = (205, 18, 48)
CORAL = (255, 105, 90)
FUCHSIA = (255, 48, 148)
PEACH = (255, 178, 110)
LIME = (130, 255, 55)
MAGENTA = (225, 35, 190)
ICE = (105, 225, 255)
ROSE = (255, 85, 165)
JADE = (25, 220, 115)
AQUA = (30, 230, 200)
SAPPHIRE = (25, 85, 215)
ROYAL = (75, 35, 170)
LETTER_PALETTES = {
    # Both words start at the same palette position and use the same timing.
    # The map gives bulb order within each word, not individual letter bounds.
    "diya": (GOLD, IVORY),
    "bloom": (CORAL, LIME, FUCHSIA, AQUA),
    "orbit": (ICE, GOLD),
    "sparkle": (IVORY, ROSE),
    "peacock": (JADE, AQUA, SAPPHIRE, GOLD),
}
DESCRIPTIONS = {
    "diya": "Warm orange flame, ruby halo, and gold/ivory lettering.",
    "bloom": "Triangle, circle, diamonds, words; all fade out and repeat.",
    "orbit": "Video-style green/blue arc and pink/gold petal chase.",
    "sparkle": "Warm center, green/blue ring, and sparse colorful petal glints.",
    "peacock": "A colorful fan opens and closes around a moving ring.",
}


def clamp(value):
    return max(0.0, min(1.0, value))


def mix(first, second, amount):
    amount = clamp(amount)
    return tuple(round(a * (1 - amount) + b * amount) for a, b in zip(first, second))


def paint(frame, bulbs, color, level=1.0):
    rgb = tuple(round(channel * clamp(level)) for channel in color)
    for bulb in bulbs:
        frame[bulb - 1] = rgb


def pulse(t, period, low=0.2, high=1.0, offset=0.0):
    return low + (high - low) * (0.5 - 0.5 * math.cos(2 * math.pi * (t / period + offset)))


def trail(position, index, length, width):
    distance = (position - index) % length
    return max(0.0, 1.0 - distance / width)


def lettering(frame, name, elapsed, level=1.0):
    """Give HAPPY and DIWALI the same repeating color and brightness pattern."""
    palette = LETTER_PALETTES[name]
    for group in (HAPPY, DIWALI):
        for index, bulb in enumerate(group):
            base = pulse(elapsed + index * 0.10, 3.4, 0.56, 0.90)
            glint = 0.12 * pulse(elapsed + index * 0.21, 1.7, 0, 1)
            paint(frame, (bulb,), palette[index % len(palette)],
                  (base + glint) * level)


def twinkle(bulb, elapsed, speed=1.0, width=0.16):
    """A stable per-bulb glint; patterns do not jump between frames."""
    seed = random.Random(bulb * 7919)
    period = seed.uniform(1.5, 3.5) / speed
    phase = (elapsed / period + seed.random()) % 1.0
    return max(0.0, 1.0 - abs(phase - 0.5) / width)


def animation(name, elapsed):
    if name not in DESCRIPTIONS:
        raise ValueError(f"Unknown animation: {name}")
    frame = [BLACK] * PIXELS
    if name != "bloom":
        lettering(frame, name, elapsed)
    if name == "diya":
        # Restore the simpler warm look that preceded the all-over color mix.
        paint(frame, RING, RUBY, pulse(elapsed, 2.4, 0.40, 0.86))
        for index, bulb in enumerate(TRIANGLE):
            movement = 0.16 * math.sin(elapsed * 9 + index * 1.7)
            movement += 0.10 * math.sin(elapsed * 15 - index * 2.1)
            paint(frame, (bulb,), mix(FLAME, PEACH, index / len(TRIANGLE)),
                  0.70 + movement)
        for bulb in OUTER:
            paint(frame, (bulb,), RUBY, 0.10 + 0.25 * twinkle(bulb, elapsed, 0.7))
    elif name == "bloom":
        # Four cumulative reveals, a full-board hold, one fade-out, and a
        # dark pause. HAPPY and DIWALI arrive together as the final stage.
        phase = elapsed % 10.0
        fade_out = 1.0 if phase < 9.0 else clamp((9.5 - phase) / 0.5)
        triangle_level = clamp(phase / 0.4) * fade_out
        ring_level = clamp((phase - 2.0) / 0.4) * fade_out
        diamonds_level = clamp((phase - 4.0) / 0.4) * fade_out
        words_level = clamp((phase - 6.0) / 0.4) * fade_out
        for index, bulb in enumerate(TRIANGLE):
            paint(frame, (bulb,), (PEACH, CORAL, IVORY)[index % 3],
                  triangle_level)
        for index, bulb in enumerate(RING):
            paint(frame, (bulb,), (LIME, AQUA)[index % 2], ring_level)
        for diamond in DIAMONDS:
            for petal, bulb in enumerate(diamond):
                paint(frame, (bulb,), (FUCHSIA, CORAL, MAGENTA, PEACH)[petal],
                      diamonds_level)
        lettering(frame, name, phase, words_level)
    elif name == "orbit":
        # Video-inspired Chase: a bright sector travels across the green/blue
        # inner arc and the pink/yellow outer petals together.
        for index, bulb in enumerate(TRIANGLE):
            paint(frame, (bulb,), (GOLD, FLAME)[index % 2],
                  pulse(elapsed + index * 0.08, 2.8, 0.52, 0.80))
        cycle = (elapsed / 4.5) % 1.0
        ring_position = cycle * len(RING)
        for index, bulb in enumerate(RING):
            color = (JADE, JADE, SAPPHIRE)[index % 3]
            paint(frame, (bulb,), color,
                  0.07 + 0.93 * trail(ring_position, index, len(RING), 5))
        diamond_position = cycle * len(DIAMONDS)
        for index, diamond in enumerate(DIAMONDS):
            level = 0.07 + 0.93 * trail(diamond_position, index, len(DIAMONDS), 3)
            for petal, bulb in enumerate(diamond):
                paint(frame, (bulb,), (MAGENTA, CORAL, GOLD, ROSE)[petal],
                      level)
    elif name == "sparkle":
        # The video keeps a warm center and green/blue inner arc while just a
        # few outer points flare up. Dark petals leave room for each sparkle.
        for index, bulb in enumerate(TRIANGLE):
            paint(frame, (bulb,), (GOLD, FLAME)[index % 2],
                  pulse(elapsed + index * 0.10, 2.9, 0.52, 0.78))
        for index, bulb in enumerate(RING):
            color = (JADE, JADE, SAPPHIRE)[index % 3]
            glint = twinkle(bulb, elapsed, 0.75, 0.10)
            paint(frame, (bulb,), color, 0.32 + 0.48 * glint)
        for index, bulb in enumerate(OUTER):
            color = (MAGENTA, CORAL, GOLD, ROSE)[index % 4]
            glint = twinkle(bulb, elapsed, 1.2, 0.08)
            paint(frame, (bulb,), color, 0.04 + 0.96 * glint)
    elif name == "peacock":
        # Light whole diamonds in sequence, hold, then darken them in reverse.
        # The near-black inactive feathers make the opening obvious at low brightness.
        phase = elapsed % 6.0
        if phase < 3.0:
            visible = min(len(DIAMONDS), int(phase * 3) + 1)
        elif phase < 4.0:
            visible = len(DIAMONDS)
        else:
            visible = max(0, len(DIAMONDS) - int((phase - 4.0) * 4.5))
        feather_colors = (JADE, GOLD, SAPPHIRE, ROYAL)
        for index, diamond in enumerate(DIAMONDS):
            for feather, bulb in enumerate(diamond):
                paint(frame, (bulb,), feather_colors[feather],
                      0.95 if index < visible else 0.0)
        ring_position = (-elapsed * 5.5) % len(RING)
        for index, bulb in enumerate(RING):
            wave = trail(ring_position, index, len(RING), 4)
            paint(frame, (bulb,), (JADE, AQUA, SAPPHIRE)[index % 3],
                  0.10 + 0.90 * wave)
        for index, bulb in enumerate(TRIANGLE):
            paint(frame, (bulb,), (GOLD, JADE, ROYAL)[index % 3],
                  pulse(elapsed + index * 0.22, 2.2, 0.36, 0.86))
    return frame


def ddp_packet(frame, sequence=0):
    """One RGB24 DDP push packet, with unused pixels explicitly black."""
    if len(frame) != PIXELS:
        raise ValueError(f"Expected {PIXELS} pixels, got {len(frame)}")
    rgb = bytes(channel for pixel in frame for channel in pixel)
    return struct.pack(">BBBBIH", 0x41, sequence & 0x0F, 0x0B, 1, 0, len(rgb)) + rgb


class Wled:
    def __init__(self, host):
        self.base = host.rstrip("/")
        if "://" not in self.base:
            self.base = "http://" + self.base
        parsed = urlsplit(self.base)
        if parsed.scheme != "http" or not parsed.hostname or parsed.path:
            raise ValueError("--host must be a local WLED hostname or HTTP URL")
        self.udp_host = parsed.hostname
        self.sequence = 0
        self.sock = None

    def request(self, endpoint, payload=None, *, operation=None, attempts=3, timeout=5):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.base + "/json/" + endpoint, data=data,
                          headers={"Content-Type": "application/json"})
        label = operation or f"GET /json/{endpoint}"
        for attempt in range(1, attempts + 1):
            try:
                with urlopen(request, timeout=timeout) as response:
                    result = json.load(response)
                if payload is not None and (result.get("error") or result.get("success") is False):
                    raise ValueError(f"{label}: controller rejected the request")
                return result
            except (TimeoutError, URLError) as error:
                reason = error.reason if isinstance(error, URLError) else error
                if not isinstance(reason, TimeoutError):
                    raise ValueError(f"{label}: {error}") from error
                if attempt == attempts:
                    raise TimeoutError(f"{label} timed out after {attempts} attempt(s)") from error
                print(f"{label} timed out. Retrying ({attempt + 1}/{attempts}).",
                      file=sys.stderr, flush=True)
                time.sleep(0.4)

    def verify(self):
        info = self.request("info")
        if info.get("leds", {}).get("count") != PIXELS:
            raise ValueError("WLED must report 100 LEDs. Check the working IO2 output.")
        state = self.request("state")
        segments = [seg for seg in state.get("seg", []) if seg["stop"] > seg["start"]]
        if len(segments) != 1 or segments[0]["id"] != 0:
            raise ValueError("Use one active WLED segment (Segment 0) for this script.")
        segment = segments[0]
        if (segment["start"], segment["stop"]) != (0, PIXELS):
            raise ValueError("Set Segment 0 Start to 0 and Stop to 100 in WLED.")
        if (segment.get("grp", 1) != 1 or segment.get("spc", 0)
                or segment.get("of", 0) or segment.get("rev") or segment.get("mi")):
            raise ValueError("Use grouping 1, spacing/offset 0, and no reverse/mirror.")
        return info

    def power(self, on, brightness=25):
        payload = {"on": on, "tt": 0}
        if on:
            payload.update(bri=brightness, seg={"id": 0, "on": True, "bri": 255,
                                               "fx": 0, "col": [[0, 0, 0]]})
        else:
            payload["live"] = False
        self.request("state", payload, operation="Turn WLED on" if on else "Turn WLED off")

    def restore_power_if_needed(self, brightness):
        """Rearm WLED after a controller restart without interrupting DDP frames."""
        try:
            state = self.request("state", attempts=1, timeout=0.5)
            segment_on = any(seg.get("id") == 0 and seg.get("on", True)
                             for seg in state.get("seg", []))
            if not state.get("on") or not segment_on:
                self.power(True, brightness)
                print("WLED power restored; resuming realtime frames.",
                      file=sys.stderr, flush=True)
            return True
        except (OSError, TimeoutError, ValueError) as error:
            print(f"WLED health check failed: {error}; will retry.",
                  file=sys.stderr, flush=True)
            return False

    def show(self, frame, *, transport="ddp", label=None):
        if transport == "ddp":
            if self.sock is None:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            packet = ddp_packet(frame, self.sequence)
            self.sequence = (self.sequence + 1) & 0x0F
            self.sock.sendto(packet, (self.udp_host, 4048))
        else:
            colors = ["%02x%02x%02x" % rgb for rgb in frame]
            self.request("state", {"seg": {"id": 0, "i": [0, *colors]}},
                         operation=f"Light {label}" if label else "Send animation frame",
                         attempts=3 if label else 1, timeout=5 if label else 1.5)

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None


class EffectCommands:
    """Read complete commands from the bridge without blocking DDP frames."""

    def __init__(self, stream):
        self.fd = stream.fileno()
        self.pending = bytearray()

    def poll(self):
        if b"\n" not in self.pending and select.select([self.fd], [], [], 0)[0]:
            chunk = os.read(self.fd, 4096)
            if not chunk:
                return ""  # Parent closed the pipe; turn the lights off.
            self.pending.extend(chunk)
        if b"\n" not in self.pending:
            return None
        command, _, rest = self.pending.partition(b"\n")
        self.pending = bytearray(rest)
        effect = command.decode("ascii", errors="replace").strip()
        if effect not in DESCRIPTIONS and effect != "off":
            print(f"Ignoring unknown effect command: {effect!r}", file=sys.stderr)
            return None
        return effect


def play(board, action, seconds, fps, transport, brightness=25, control_stream=None):
    commands = EffectCommands(control_stream) if control_stream is not None else None
    show_started = time.monotonic()
    effect_started = show_started
    deadline = show_started
    next_health_check = show_started + 60.0 if transport == "ddp" else float("inf")
    missed = 0
    sent = False
    while True:
        now = time.monotonic()
        if seconds is not None and now - show_started >= seconds:
            if not sent:
                raise TimeoutError("No animation frame was sent before the test ended")
            return
        next_action = commands.poll() if commands is not None else None
        if next_action == "":
            return
        if next_action is not None:
            action = next_action
            effect_started = now
            print(f"Switched to {action} without restarting WLED.", flush=True)
        elapsed = now - effect_started
        if now >= next_health_check:
            board.restore_power_if_needed(brightness)
            next_health_check = time.monotonic() + 60.0
        try:
            frame = [BLACK] * PIXELS if action == "off" else animation(action, elapsed)
            board.show(frame, transport=transport)
        except TimeoutError as error:
            missed += 1
            if missed >= 3:
                raise TimeoutError("WLED stopped replying for 3 consecutive HTTP frames") from error
            print(f"HTTP frame timed out; skipping it ({missed}/3).", file=sys.stderr)
        else:
            missed = 0
            sent = True
        deadline += 1 / fps
        time.sleep(max(0, deadline - time.monotonic()))
        if deadline < time.monotonic() - 1 / fps:
            deadline = time.monotonic()


def stop_on_signal(signum, frame):
    """Run the normal lights-off cleanup when a player stops this process."""
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "check", "map", "off", "diya-native", *DESCRIPTIONS))
    parser.add_argument("--host", help="WLED IP address or hostname")
    parser.add_argument("--seconds", type=float, help="stop after this many seconds")
    parser.add_argument("--fps", type=int, default=20, help="frames per second (default: 20)")
    parser.add_argument("--brightness", type=int, default=25, help="WLED brightness 1-255 (default: 25)")
    parser.add_argument("--transport", choices=("ddp", "http"), default="ddp")
    parser.add_argument("--control-stdin", action="store_true",
                        help="accept effect switches from the RFID bridge on stdin")
    args = parser.parse_args(argv)
    if args.action == "list":
        for name, description in DESCRIPTIONS.items():
            print(f"{name:9} {description}")
        return 0
    if not args.host:
        parser.error("--host is required")
    if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds <= 0):
        parser.error("--seconds must be positive")
    if not 1 <= args.fps <= 40:
        parser.error("--fps must be between 1 and 40")
    if not 1 <= args.brightness <= 255:
        parser.error("--brightness must be between 1 and 255")
    if args.control_stdin and args.action not in DESCRIPTIONS:
        parser.error("--control-stdin requires a mapped light effect")
    signal.signal(signal.SIGTERM, stop_on_signal)
    try:
        board = Wled(args.host)
        if args.action == "off":
            board.power(False)
            return 0
        info = board.verify()
        print(f"Connected to {info.get('name', 'WLED')} (100 LEDs).", flush=True)
        if args.action == "check":
            return 0
        if args.action == "diya-native":
            effects = board.request("eff")
            candle = next((index for index, effect in enumerate(effects)
                           if effect.lower() == "candle"), None)
            if candle is None:
                raise ValueError("This WLED build has no Candle effect")
            board.request("state", {"on": True, "bri": args.brightness,
                                    "seg": {"id": 0, "on": True, "fx": candle,
                                            "col": [list(FLAME), [0, 0, 0], [0, 0, 0]]}},
                          operation="Start native Candle")
            print("Native Candle is running on all 100 pixels. Use 'off' to stop.")
            return 0
        try:
            board.power(True, args.brightness)
            if args.action == "map":
                for label, bulbs in ZONES:
                    print(f"Lighting {label}: {', '.join(map(str, bulbs))}", flush=True)
                    frame = [BLACK] * PIXELS
                    paint(frame, bulbs, GOLD)
                    # Repeat DDP frames so a dropped packet cannot erase a zone test.
                    repeats = 15 if args.transport == "ddp" else 1
                    for _ in range(repeats):
                        board.show(frame, transport=args.transport, label=label)
                        time.sleep(0.2 if args.transport == "ddp" else 3)
            else:
                print(f"Playing {args.action} via {args.transport}. Press Ctrl+C to stop.", flush=True)
                play(board, args.action, args.seconds, args.fps, args.transport,
                     args.brightness, sys.stdin if args.control_stdin else None)
        finally:
            original_error = sys.exc_info()[0]
            cleanup_error = None
            if args.transport == "ddp":
                try:
                    board.show([BLACK] * PIXELS)
                except OSError as error:
                    cleanup_error = error
            try:
                board.power(False)
            except (OSError, ValueError) as error:
                cleanup_error = error
            finally:
                board.close()
            if cleanup_error is not None:
                if original_error is None:
                    raise cleanup_error
                print(f"Could not turn WLED off: {cleanup_error}. Use Power in WLED.",
                      file=sys.stderr)
    except KeyboardInterrupt:
        return 0
    except (URLError, OSError, ValueError, KeyError) as error:
        print(f"WLED error: {error}. If the board is still lit, use Power in WLED.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
