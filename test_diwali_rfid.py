"""Offline checks for separate RFID light dispatch and Card Play coexistence."""

import json
import io
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import diwali_rfid as bridge

IDS = [f"{number:014x}" for number in range(1, 8)]


def light_config():
    return {
        "host": "192.0.2.1",
        "brightness": 25,
        "effects_by_id": dict(zip(IDS[:5], bridge.EFFECTS)),
        "toggle_id": IDS[5],
    }


class ConfigTests(unittest.TestCase):
    def test_private_log_filter_redacts_card_ids(self):
        record = logging.LogRecord("card-play", logging.WARNING, __file__, 1,
                                   "Unknown card %s", (IDS[0],), None)
        bridge.RedactCardIds().filter(record)
        self.assertEqual(record.getMessage(), "Unknown card [card-id]")

    def test_accepts_complete_private_mapping_and_rejects_collisions(self):
        data = {
            "wled_host": "192.0.2.1",
            "brightness": 25,
            "effect_cards": dict(zip(bridge.EFFECTS, IDS[:5])),
            "start_stop_card": IDS[5],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cards.json"
            path.write_text(json.dumps(data))
            loaded = bridge.load_lights(path, (IDS[6],))
            self.assertEqual(loaded["effects_by_id"][IDS[0]], "diya")
            with self.assertRaisesRegex(ValueError, "already used"):
                bridge.load_lights(path, (IDS[0],))
            data["start_stop_card"] = IDS[0]
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "unique"):
                bridge.load_lights(path)

    def test_rejects_placeholders_and_non_ipv4_host(self):
        data = {
            "wled_host": "YOUR_WLED_IP",
            "effect_cards": dict(zip(bridge.EFFECTS, IDS[:5])),
            "start_stop_card": IDS[5],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cards.json"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "IPv4"):
                bridge.load_lights(path)
            data["wled_host"] = "192.0.2.1"
            data["effect_cards"]["diya"] = "REPLACE_DIYA_ID"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "14 lowercase"):
                bridge.load_lights(path)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.music = Mock()
        self.music.shutdown_arm = ("shutdown-card", 0)
        self.lights = Mock()
        self.lights.running.return_value = False
        self.clock = Mock(return_value=10.0)
        self.controller = bridge.CombinedController(
            self.music, self.lights, light_config(), lambda value: value,
            clock=self.clock,
        )

    def test_effect_switch_and_toggle_restore_last_without_touching_music(self):
        self.controller.scan(IDS[0])
        self.lights.start.assert_called_once_with("diya")
        self.assertIsNone(self.music.shutdown_arm)
        self.music.scan.assert_not_called()
        self.clock.return_value = 12.0
        self.controller.scan(IDS[1])
        self.lights.start.assert_called_with("bloom")
        self.clock.return_value = 14.0
        self.lights.running.return_value = True
        self.controller.scan(IDS[5])
        self.lights.pause.assert_called_once()
        self.lights.stop.assert_not_called()
        self.clock.return_value = 16.0
        self.lights.running.return_value = False
        self.controller.scan(IDS[5])
        self.lights.start.assert_called_with("bloom")
        self.music.stop.assert_not_called()

    def test_music_cards_forward_while_lights_continue(self):
        self.controller.scan(IDS[0])
        self.lights.reset_mock()
        self.controller.scan(IDS[6])
        self.music.scan.assert_called_once_with(IDS[6])
        self.lights.assert_not_called()
        self.controller.tick()
        self.music.tick.assert_called_once()
        self.controller.stop()
        self.music.stop.assert_called_once()
        self.lights.stop.assert_called_once()

    def test_duplicate_light_tap_is_ignored_but_later_tap_works(self):
        self.controller.scan(IDS[0])
        self.clock.return_value = 10.5
        self.controller.scan(IDS[0])
        self.assertEqual(self.lights.start.call_count, 1)
        self.clock.return_value = 12.0
        self.controller.scan(IDS[0])
        self.assertEqual(self.lights.start.call_count, 2)

    def test_music_recovery_error_does_not_stop_lights(self):
        self.controller.scan(IDS[0])
        self.music.tick.side_effect = ValueError("speaker missing")
        with patch.object(bridge.LOG, "error"):
            self.controller.tick()
        self.music.stop.assert_called_once()
        self.lights.running.assert_called_once()
        self.lights.stop.assert_not_called()

    def test_failed_light_show_restarts_with_backoff_but_stays_off_after_toggle(self):
        self.controller.scan(IDS[1])
        self.assertEqual(self.lights.start.call_count, 1)
        self.clock.return_value = 14.0
        self.controller.tick()
        self.assertEqual(self.lights.start.call_count, 1)
        self.clock.return_value = 15.0
        self.controller.tick()
        self.assertEqual(self.lights.start.call_count, 2)
        self.lights.start.assert_called_with("bloom")
        self.clock.return_value = 20.0
        self.controller.tick()
        self.assertEqual(self.lights.start.call_count, 2)
        self.clock.return_value = 25.0
        self.controller.tick()
        self.assertEqual(self.lights.start.call_count, 3)
        self.clock.return_value = 26.0
        self.controller.scan(IDS[5])
        self.clock.return_value = 200.0
        self.controller.tick()
        self.assertEqual(self.lights.start.call_count, 3)

    def test_spawn_error_retries_without_stopping_music(self):
        self.lights.start.side_effect = [OSError("temporary failure"), None]
        self.controller.scan(IDS[1])
        self.clock.return_value = 15.0
        self.controller.tick()
        self.assertEqual(self.lights.start.call_count, 2)
        self.music.stop.assert_not_called()


class LightRunnerTests(unittest.TestCase):
    def test_switches_effects_in_one_process_without_power_cycle(self):
        child = Mock()
        child.pid = 123
        child.poll.return_value = None
        child.stdout = io.StringIO("")
        runner = bridge.LightRunner(Path("diwali_animations.py"), "192.0.2.1", 25)
        with patch.object(bridge.subprocess, "Popen", return_value=child) as spawn:
            runner.start("diya")
            runner.start("bloom")
            spawn.assert_called_once()
            self.assertIn("--control-stdin", spawn.call_args.args[0])
            child.stdin.write.assert_called_once_with("bloom\n")
            child.stdin.flush.assert_called_once()
            child.terminate.assert_not_called()
            runner.pause()
            child.stdin.write.assert_called_with("off\n")
            self.assertEqual(child.stdin.write.call_count, 2)
            child.terminate.assert_not_called()
            runner.stop()
            child.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
