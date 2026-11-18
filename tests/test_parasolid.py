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


@unittest.skipUnless((MOUSE / "Main Housing.SLDPRT").is_file(), "SolidWorks 2025 sample files are not installed")
class Helpers(unittest.TestCase):
    """A big part's slow sums worked out by helper processes first (parallel.py): the STEP is byte for byte what one
    process writes. (Small parts don't start them: MIN_FACES is lowered here to make them.)"""

    def test_same_step(self):
        import tempfile
        from solidsmufs.formats.parasolid import parallel
        from solidsmufs.formats.parasolid.convert import convert
        out = Path(tempfile.mkdtemp(prefix="ss-par-"))
        old = parallel.MIN_FACES
        parallel.MIN_FACES = 0
        try:
            for name in ("Main Housing", "Mouse Buttons", "Mouse Wheel"):
                one, two = out / f"{name}-1.step", out / f"{name}-3.step"
                a = convert(str(MOUSE / f"{name}.SLDPRT"), str(one), workers=1)
                b = convert(str(MOUSE / f"{name}.SLDPRT"), str(two), workers=3)
                self.assertTrue(parallel.timings, name)  # (the helpers did run)
                self.assertEqual(one.read_bytes(), two.read_bytes(), name)
                self.assertEqual({k: v for k, v in a.items()}, {k: v for k, v in b.items()}, name)
        finally:
            parallel.MIN_FACES = old


class Preview(unittest.TestCase):
    """The picture SolidWorks saves with a file, shown on the loading card while the part is worked out."""

    @unittest.skipUnless((MOUSE / "Mouse Wheel.SLDPRT").is_file(), "SolidWorks 2025 sample files are not installed")
    def test_saved_picture(self):
        import struct
        from solidsmufs.formats.parasolid.containers import preview_png
        png = preview_png(str(MOUSE / "Mouse Wheel.SLDPRT"))
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", png[16:24]), (640, 480))

    def test_none(self):
        import tempfile
        from solidsmufs.formats.parasolid.containers import preview_png
        f = Path(tempfile.mkdtemp(prefix="ss-pv-")) / "x.SLDPRT"
        f.write_bytes(b"not a SolidWorks file" * 10)
        self.assertIsNone(preview_png(str(f)))
        self.assertIsNone(preview_png(str(f.with_name("missing.SLDPRT"))))


class Pieces(unittest.TestCase):
    """A SolidWorks 2015+ partition's model is zlib pieces, each [raw size][compressed size] + zlib. A 27 MB part
    once took a minute just to read, handing zlib the whole rest of the stream for every piece."""

    def stream(self, text, piece=4096, bad_size=False):
        import struct
        import zlib
        from solidsmufs.formats.parasolid.containers import GEO_MAGIC
        out = [b"junk" * 10, GEO_MAGIC]
        for i in range(0, len(text), piece):
            z = zlib.compress(text[i:i + piece])
            out.append(struct.pack("<II", len(text[i:i + piece]), 7 if bad_size else len(z)) + z)
        return b"".join(out) + b"\x00" * 12

    def test_pieces(self):
        import time
        from solidsmufs.formats.parasolid.containers import _zlib_transmits
        text = b"PS" + bytes(range(256)) * 2000 + b"the end"
        self.assertEqual(_zlib_transmits(self.stream(text)), [text])
        self.assertEqual(_zlib_transmits(self.stream(text, bad_size=True)), [text])  # (sizes it can't trust)
        big = b"PS" + np.random.default_rng(1).integers(0, 40, 6_000_000, dtype=np.uint8).tobytes()
        t = time.perf_counter()
        self.assertEqual(_zlib_transmits(self.stream(big) * 2), [big, big])
        self.assertLess(time.perf_counter() - t, 5)


if __name__ == "__main__":
    unittest.main()
