"""Tests for reading the SpaceMouse: report parsing and dropping stray reports.

    .venv\\Scripts\\python -m unittest tests.test_spacemouse -v
"""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidsmufs.spacemouse import Despike, parse  # noqa: E402


class Reports(unittest.TestCase):
    def test_one_report_with_all_six_axes(self):
        state = [0] * 6
        self.assertTrue(parse(struct.pack("<B6h", 1, 1, -2, 3, -4, 5, -6), state))
        self.assertEqual(state, [1, -2, 3, -4, 5, -6])

    def test_older_devices_split_translation_and_rotation(self):
        state = [0] * 6
        self.assertTrue(parse(struct.pack("<B3h", 1, 1, 2, 3), state))
        self.assertTrue(parse(struct.pack("<B3h", 2, 4, 5, 6), state))
        self.assertEqual(state, [1, 2, 3, 4, 5, 6])

    def test_other_reports_are_ignored(self):
        state = [9] * 6
        self.assertFalse(parse(struct.pack("<B6h", 23, 1, 2, 3, 4, 5, 6), state))  # battery
        self.assertEqual(state, [9] * 6)


class Strays(unittest.TestCase):
    def run_through(self, reports):
        d = Despike()
        return [d.push(r) for r in reports]

    def test_a_flipped_report_never_reverses_the_motion(self):
        # as logged from a real wireless SpaceMouse on a slow move
        reports = [[0, -20, 0, -30, 0, 0], [0, -22, 0, -32, 0, 0], [0, 24, 0, 30, 0, 0],
                   [0, -14, 0, -27, 0, 0], [0, -15, 0, -28, 0, 0]]
        for out in self.run_through(reports):
            self.assertLess(out[1], 0)
            self.assertLess(out[3], 0)

    def test_steady_values_pass_unchanged(self):
        self.assertEqual(self.run_through([[5, 0, 0, 0, 0, 0]] * 4)[-1], [5, 0, 0, 0, 0, 0])

    def test_letting_go_stops_at_once(self):
        # the last report may be the only zero the device sends: it can't wait for two more
        out = self.run_through([[50, 0, 0, 0, 0, 0], [50, 0, 0, 0, 0, 0], [50, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]])
        self.assertEqual(out[-1], [0] * 6)

    def test_a_real_change_comes_through(self):
        out = self.run_through([[10, 0, 0, 0, 0, 0], [10, 0, 0, 0, 0, 0], [80, 0, 0, 0, 0, 0], [80, 0, 0, 0, 0, 0]])
        self.assertEqual(out[-1][0], 80)


if __name__ == "__main__":
    unittest.main()
