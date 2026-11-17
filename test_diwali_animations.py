"""Offline checks for the board map and WLED DDP wire format."""

import struct
import unittest
import colorsys
import os
from unittest.mock import Mock, patch

import diwali_animations as show


class AnimationTests(unittest.TestCase):
    def test_map_is_exactly_the_board_design(self):
        self.assertEqual(len(show.MAPPED), 83)
        self.assertEqual(len(show.LETTERS), 25)
        self.assertEqual(len(show.OUTER), 36)
        self.assertEqual(show.RING, tuple(range(78, 93)))
        self.assertEqual(show.TRIANGLE, tuple(range(94, 101)))
        self.assertTrue(all(1 <= bulb <= show.PIXELS for bulb in show.MAPPED))

    def test_all_effects_animate_both_words_without_lighting_spare_bulbs(self):
        for name in show.DESCRIPTIONS:
            with self.subTest(effect=name):
                frames = [show.animation(name, t) for t in (0.5, 1.25, 2.5, 4.0)]
                self.assertTrue(any(a != b for a, b in zip(frames, frames[1:])))
                for frame in frames:
                    self.assertEqual(len(frame), show.PIXELS)
                    if name != "bloom":
                        self.assertTrue(all(frame[bulb - 1] != show.BLACK
                                            for bulb in show.LETTERS))
                    self.assertTrue(all(frame[bulb - 1] == show.BLACK
                                        for bulb in range(1, show.PIXELS + 1)
                                        if bulb not in show.MAPPED))
                    self.assertTrue(all(0 <= channel <= 255
                                        for pixel in frame for channel in pixel))

    def test_effects_have_distinct_word_colors_and_diya_has_contrasting_zones(self):
        frames = {name: show.animation(name, 8.0) for name in show.DESCRIPTIONS}
        for bulb in (show.HAPPY[0], show.DIWALI[0]):
            self.assertEqual(len({frame[bulb - 1] for frame in frames.values()}),
                             len(frames))
        diya = frames["diya"]
        flame = diya[show.TRIANGLE[0] - 1]
        halo = diya[show.RING[0] - 1]
        self.assertGreater(flame[1], flame[2])
        self.assertGreater(halo[2], halo[1])
        bloom = frames["bloom"]
        self.assertGreater(bloom[show.RING[0] - 1][1],
                           bloom[show.RING[0] - 1][2])
        orbit = show.animation("orbit", 0.5)
        self.assertGreater(orbit[show.RING[0] - 1][1],
                           orbit[show.RING[0] - 1][0])
        self.assertGreater(orbit[show.OUTER[0] - 1][0],
                           orbit[show.OUTER[0] - 1][1])

    def test_words_share_the_same_multicolor_pattern(self):
        for name in show.DESCRIPTIONS:
            frame = show.animation(name, 8.0)
            self.assertEqual([frame[bulb - 1] for bulb in show.HAPPY],
                             [frame[bulb - 1] for bulb in show.DIWALI[:len(show.HAPPY)]])
            self.assertGreater(len({frame[bulb - 1] for bulb in show.HAPPY}), 3)

    def test_bloom_reveals_four_zones_then_goes_dark_and_repeats(self):
        groups = (show.TRIANGLE, show.RING, show.OUTER, show.LETTERS)
        for elapsed, expected in (
            (1.0, (True, False, False, False)),
            (3.0, (True, True, False, False)),
            (5.0, (True, True, True, False)),
            (7.0, (True, True, True, True)),
            (9.8, (False, False, False, False)),
        ):
            with self.subTest(elapsed=elapsed):
                frame = show.animation("bloom", elapsed)
                visible = tuple(any(frame[bulb - 1] != show.BLACK for bulb in group)
                                for group in groups)
                self.assertEqual(visible, expected)
        self.assertEqual(show.animation("bloom", 1.0),
                         show.animation("bloom", 11.0))
        self.assertEqual(show.animation("bloom", 7.0),
                         show.animation("bloom", 17.0))

    def test_all_effects_show_contrasting_hues_at_once(self):
        for name in show.DESCRIPTIONS:
            frame = show.animation(name, 2.5)
            hues = set()
            for bulb in show.MAPPED:
                rgb = frame[bulb - 1]
                if max(rgb) >= 80:
                    hue, _, _ = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
                    hues.add(int(hue * 12) % 12)
            self.assertGreaterEqual(len(hues), 3 if name == "diya" else 4,
                                    name)

    def test_peacock_fan_opens_and_closes_visibly(self):
        first = show.animation("peacock", 0.2)
        open_frame = show.animation("peacock", 2.5)
        closing = show.animation("peacock", 5.5)
        def lit_diamonds(frame):
            return sum(any(max(frame[bulb - 1]) >= 100 for bulb in diamond)
                       for diamond in show.DIAMONDS)
        self.assertEqual(lit_diamonds(first), 1)
        self.assertGreaterEqual(lit_diamonds(open_frame), 8)
        self.assertLess(lit_diamonds(closing), lit_diamonds(open_frame))
        changed = sum(first[bulb - 1] != open_frame[bulb - 1]
                      for bulb in show.RING + show.OUTER)
        self.assertGreater(changed, 25)

    def test_orbit_moves_a_bright_sector_around_the_petals(self):
        def brightest_diamond(elapsed):
            frame = show.animation("orbit", elapsed)
            totals = [sum(sum(frame[bulb - 1]) for bulb in diamond)
                      for diamond in show.DIAMONDS]
            return totals.index(max(totals))
        self.assertNotEqual(brightest_diamond(0.5),
                            brightest_diamond(2.5))

    def test_sparkle_keeps_outer_flashes_sparse(self):
        for elapsed in (0.5, 1.5, 2.5, 4.0):
            frame = show.animation("sparkle", elapsed)
            bright = sum(max(frame[bulb - 1]) >= 90 for bulb in show.OUTER)
            self.assertGreater(bright, 0)
            self.assertLess(bright, len(show.OUTER) // 3)
            center = frame[show.TRIANGLE[0] - 1]
            ring = frame[show.RING[0] - 1]
            self.assertGreater(center[0], center[2])
            self.assertGreater(ring[1], ring[0])

    def test_ddp_packet_uses_wled_rgb24_header_and_physical_order(self):
        frame = [show.BLACK] * show.PIXELS
        show.paint(frame, (1, 77, 100), (1, 2, 3))
        packet = show.ddp_packet(frame, 17)
        self.assertEqual(len(packet), 310)
        self.assertEqual(struct.unpack(">BBBBIH", packet[:10]),
                         (0x41, 1, 0x0B, 1, 0, 300))
        self.assertEqual(packet[10:13], bytes((1, 2, 3)))
        self.assertEqual(packet[10 + 76 * 3:10 + 77 * 3], bytes((1, 2, 3)))
        self.assertEqual(packet[-3:], bytes((1, 2, 3)))

    def test_ddp_sends_without_http_and_advances_sequence(self):
        class FakeSocket:
            def __init__(self):
                self.sent = []
            def sendto(self, packet, address):
                self.sent.append((packet, address))
            def close(self):
                pass

        fake = FakeSocket()
        with patch.object(show.socket, "socket", return_value=fake):
            board = show.Wled("192.0.2.1")
            board.show([show.BLACK] * show.PIXELS)
            board.show([show.BLACK] * show.PIXELS)
            board.close()
        self.assertEqual([item[1] for item in fake.sent],
                         [("192.0.2.1", 4048)] * 2)
        self.assertEqual([item[0][1] for item in fake.sent], [0, 1])

    def test_wled_health_check_restores_power_after_reboot_and_tolerates_outage(self):
        board = show.Wled("192.0.2.1")
        with patch.object(board, "request", return_value={
                "on": False, "seg": [{"id": 0, "on": True}]}), \
                patch.object(board, "power") as power:
            self.assertTrue(board.restore_power_if_needed(25))
            power.assert_called_once_with(True, 25)
        with patch.object(board, "request", side_effect=TimeoutError("offline")), \
                patch.object(board, "power") as power:
            self.assertFalse(board.restore_power_if_needed(25))
            power.assert_not_called()

    def test_effect_commands_keep_rapid_card_switches_in_order(self):
        read_fd, write_fd = os.pipe()
        try:
            with os.fdopen(read_fd, "rb", buffering=0) as stream:
                commands = show.EffectCommands(stream)
                os.write(write_fd, b"bloom\noff\npeacock\n")
                self.assertEqual(commands.poll(), "bloom")
                self.assertEqual(commands.poll(), "off")
                self.assertEqual(commands.poll(), "peacock")
                self.assertIsNone(commands.poll())
                os.close(write_fd)
                write_fd = None
                self.assertEqual(commands.poll(), "")
        finally:
            if write_fd is not None:
                os.close(write_fd)

    def test_play_switches_animation_without_restarting_board(self):
        class Finished(Exception):
            pass

        read_fd, write_fd = os.pipe()
        frames = []
        try:
            with os.fdopen(read_fd, "rb", buffering=0) as stream:
                def show_frame(frame, **_):
                    frames.append(frame)
                    if len(frames) == 1:
                        os.write(write_fd, b"off\nbloom\n")
                    if len(frames) == 4:
                        raise Finished

                board = Mock()
                board.show.side_effect = show_frame
                with patch.object(show, "animation", side_effect=lambda name, _: name), \
                        patch.object(show.time, "sleep", return_value=None):
                    with self.assertRaises(Finished):
                        show.play(board, "diya", None, 20, "ddp",
                                  control_stream=stream)
                self.assertEqual(frames, ["diya", [show.BLACK] * show.PIXELS,
                                          "bloom", "bloom"])
                board.restore_power_if_needed.assert_not_called()
        finally:
            os.close(write_fd)


if __name__ == "__main__":
    unittest.main()
