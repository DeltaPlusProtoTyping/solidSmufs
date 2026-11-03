"""Tests for the SolidWorks / Parasolid reader's geometry: spline trimming, and sample parts that once failed.

    .venv\\Scripts\\python -m unittest tests.test_parasolid -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidsmufs.formats.parasolid import nurbs as N  # noqa: E402

MOUSE = Path(r"C:\Users\Public\Documents\SOLIDWORKS\SOLIDWORKS 2025\samples\learn\Mouse")


class Trimming(unittest.TestCase):
    """segment() must give back the same curve, clamped, over its domain or any part of it. Parasolid's
    periodic splines are unclamped, often with every knot doubled; the domain's end is then a knot
    already, which knot insertion once raised in the wrong span (0.1 mm off on the Mouse parts)."""

    def check(self, U, a=None, b=None):
        deg = 3
        P = np.random.default_rng(7).normal(size=(len(U) - deg - 1, 3))
        lo, hi = (U[deg], U[len(P)]) if a is None else (a, b)
        ts = np.linspace(lo, hi, 41)
        K, Q = N.segment(deg, U, P, a, b)
        self.assertLess(np.abs(N.eval_curve(deg, K, Q, ts) - N.eval_curve(deg, U, P, ts)).max(), 1e-12)

    def test_unclamped_single_knots(self):
        self.check(np.concatenate([[-0.3, -0.2, -0.1], np.linspace(0, 1, 9), [1.1, 1.2, 1.3]]))

    def test_unclamped_doubled_knots(self):
        self.check(np.concatenate([[-0.25, -0.25], np.repeat(np.linspace(0, 1, 9), 2), [1.25, 1.25]]))

    def test_part_of_a_curve(self):
        self.check(np.concatenate([[-0.25, -0.25], np.repeat(np.linspace(0, 1, 9), 2), [1.25, 1.25]]), 0.2, 0.7)

    def test_clamped(self):
        self.check(np.concatenate([[0] * 3, np.linspace(0, 1, 9), [1] * 3]))


@unittest.skipUnless((MOUSE / "Mouse Master.SLDPRT").is_file(), "SolidWorks 2025 sample files are not installed")
class MouseParts(unittest.TestCase):
    """Two Mouse sample parts that used to fail: Mouse Master (edges whose start vertex is only reachable
    through the mate halfedge) and Mouse Battery Cover (a periodic wall clamped 0.13 mm off)."""

    def load(self, name):
        from solidsmufs.kernel.worker import Session

        s = Session()
        s.load(str(MOUSE / f"{name}.SLDPRT"), "normal")
        return s

    def test_mouse_master(self):
        self.assertEqual(len(self.load("Mouse Master").model.face_type), 12)

    def test_battery_cover(self):
        s = self.load("Mouse Battery Cover")
        self.assertAlmostEqual(s.massprops(None, 1.0)["volume"], 4266.0, delta=5)


if __name__ == "__main__":
    unittest.main()
