"""Tests for thread recognition: modelled threads read off helical faces, and plain holes matched to tap
drills, minor diameters and clearance holes.

    .venv\\Scripts\\python -m unittest tests.test_threads -v

The modelled threads are built in OpenCASCADE: a triangular profile swept along a helix, cut into a
block (an M6 x 1 tapped hole) and added to a rod (a 1/4-20 shaft), saved as STEP and opened the way
the viewer opens any file.
"""

import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidsmufs.kernel import threads  # noqa: E402

IN = 25.4


def _make(path, kind):
    """Write the threaded part as STEP, built in a process of its own so its gmsh session can't disturb
    the viewer's."""
    import multiprocessing as mp

    p = mp.get_context("spawn").Process(target=_build, args=(str(path), kind))
    p.start()
    p.join(180)
    if p.exitcode != 0 or not Path(path).is_file():
        raise RuntimeError(f"could not build the {kind} test part")


def _thread(occ, r_root, pitch, depth, length, outward):
    """A 60° thread ridge swept along a helix of radius r_root, pointing out (shaft) or in (hole)."""
    turns = length / pitch
    n = int(turns * 24) + 1
    pts = [occ.addPoint(r_root * math.cos(2 * math.pi * i / 24), r_root * math.sin(2 * math.pi * i / 24), pitch * i / 24)
           for i in range(n)]
    helix = occ.addBSpline(pts)
    wire = occ.addWire([helix])
    s = 1 if outward else -1
    half = pitch * 0.45  # a little under half a pitch, so neighbouring turns don't touch
    a = occ.addPoint(r_root, 0, -half)
    b = occ.addPoint(r_root + s * depth, 0, 0)
    c = occ.addPoint(r_root, 0, half)
    loop = occ.addCurveLoop([occ.addLine(a, b), occ.addLine(b, c), occ.addLine(c, a)])
    prof = occ.addPlaneSurface([loop])
    return occ.addPipe([(2, prof)], wire, "Frenet")


def _build(path, kind):
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add(kind)
    occ = gmsh.model.occ
    if kind == "m6":  # block with an M6 x 1 hole: bore at the minor diameter, thread ridges cut outwards
        p, minor = 1.0, 6.0 - 1.0825 * 1.0
        box = occ.addBox(-10, -10, 0, 20, 20, 12)
        bore = occ.addCylinder(0, 0, -1, 0, 0, 14, minor / 2)
        ridge = _thread(occ, minor / 2 - 0.05, p, 0.6, 9, True)
        occ.cut([(3, box)], [(3, bore)] + ridge)
    else:  # a 1/4-20 shaft: core at the minor diameter, ridges out to the major
        p = IN / 20
        core = occ.addCylinder(0, 0, 0, 0, 0, 14, (0.25 * IN - 1.226 * p) / 2)
        ridge = _thread(occ, (0.25 * IN - 1.226 * p) / 2 - 0.05, p, 0.6 * p + 0.05, 10, True)
        occ.fuse([(3, core)], ridge)
    occ.synchronize()
    gmsh.write(path)
    gmsh.finalize()


class Tables(unittest.TestCase):
    def test_tap_drills_and_minor_diameters(self):
        self.assertEqual(threads.likely(0.201 * IN)[0], "Tap drill for 1/4-20 UNC")
        self.assertEqual(threads.likely(5.0)[0], "Tap drill for M6x1")
        self.assertEqual(threads.likely(0.207 * IN)[0], "1/4-20 UNC tapped (minor diameter)")  # Inventor / SolidWorks style

    def test_clearance_and_drills(self):
        self.assertEqual(threads.likely(0.266 * IN)[0], "Clearance for 1/4 screw (free fit)")
        self.assertIn('3/8" drill', threads.likely(0.375 * IN))
        self.assertEqual(threads.likely(7.77), ["Bored / non-standard"])

    def test_shaft_at_a_major_diameter(self):
        self.assertIn("1/2-13 UNC thread (major diameter)", threads.likely(0.5 * IN, internal=False))

    def test_npt_taper(self):
        self.assertEqual(threads.npt_size(0.45 * IN)["callout"], "1/4-18 NPT")


class HoleWizard(unittest.TestCase):
    """A SolidWorks part's Hole Wizard types settle what a plain hole is."""

    def test_keywords(self):
        from solidsmufs.formats.parasolid.appearance import hole_wizard
        xml = (b'<HoleWizard id="56" Name="M10x1.5 Tapped Hole1" Type="M10x1.5 Tapped Hole"/>'
               b'<HoleWizard id="128" Name="M5x0.8 Tapped Hole1" Dissectable="true"/>')
        self.assertEqual(hole_wizard(xml), ["M10x1.5 Tapped Hole", "M5x0.8 Tapped Hole"])

    def test_plain_hole_named_by_the_hole_wizard(self):
        class Part:
            hole_wizard = ["M8x1.0 Tapped Hole", "M5 Clearance Hole"]
        self.assertEqual(threads.hole_wizard_thread(Part, 7.0)["callout"], "M8x1")  # its tap drill
        self.assertEqual(threads.hole_wizard_thread(Part, 8.0)["callout"], "M8x1")  # cosmetic thread at the major
        self.assertIsNone(threads.hole_wizard_thread(Part, 4.2))  # an M5 tap drill, but this part taps no M5


class ModelledThreads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from solidsmufs.kernel.worker import Session

        cls.dir = Path(tempfile.mkdtemp(prefix="solidsmufs-test-"))
        cls.parts = {}
        for kind in ("m6", "quarter"):
            step = cls.dir / f"{kind}.step"
            _make(step, kind)
            s = Session()
            s.load(str(step), "normal")
            cls.parts[kind] = s

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def thread_of(self, kind):
        s = self.parts[kind]
        m = s.model
        for f, t in enumerate(m.face_type):
            if t in threads.FREEFORM:
                res = threads.identify(m, f)
                if res and res["modelled"]:
                    return s, f, res
        self.fail(f"no modelled thread found in the {kind} part")

    def test_tapped_hole(self):
        s, f, res = self.thread_of("m6")
        self.assertEqual(res["callout"], "M6x1")
        self.assertTrue(res["internal"])
        self.assertAlmostEqual(res["pitch"], 1.0)
        rows = {r["label"]: r["value"] for r in s.measure([{"kind": "face", "index": f}])["rows"]}
        self.assertEqual(rows["Thread"], "M6x1 tapped hole")
        self.assertEqual(rows["Tap drill"], "5 mm")

    def test_threaded_shaft(self):
        s, f, res = self.thread_of("quarter")
        self.assertEqual(res["callout"], "1/4-20 UNC")
        self.assertFalse(res["internal"])
        self.assertEqual(res["hand"], "right")

    def test_hole_report_names_the_thread(self):
        groups = self.parts["m6"].holes()["groups"]
        self.assertIn("M6x1", [g["thread"] for g in groups])


if __name__ == "__main__":
    unittest.main()
