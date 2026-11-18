"""Finding a print's callouts on the 3D model (kernel/callouts.py), and reading them off the print (op_callouts).

    .venv\\Scripts\\python -m unittest tests.test_callouts -v

The part is built in OpenCASCADE: a 4 x 2 x 1 in block, its four upright corners rounded R.125, four Ø.250 holes
through it, a #7 drill (a 1/4-20 tap drill) in the middle, and a Ø1.000 boss .5 tall on top.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidsmufs.kernel import callouts  # noqa: E402

IN = 25.4


def _build(path):
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("block")
    occ = gmsh.model.occ
    box = occ.addBox(0, 0, 0, 4 * IN, 2 * IN, 1 * IN)
    occ.synchronize()
    upright = [c for _, c in gmsh.model.getBoundary([(3, box)], combined=False, oriented=False, recursive=True)
               if False] or []
    edges = []
    for _, e in gmsh.model.occ.getEntities(1):
        x0, y0, z0, x1, y1, z1 = occ.getBoundingBox(1, e)
        if abs(x1 - x0) < 1e-6 and abs(y1 - y0) < 1e-6:
            edges.append(e)
    (blk,) = [t for _, t in occ.fillet([box], edges, [0.125 * IN])]
    holes = [(3, occ.addCylinder(x * IN, y * IN, -1, 0, 0, IN + 2, 0.125 * IN)) for x, y in ((0.5, 0.5), (3.5, 0.5), (0.5, 1.5), (3.5, 1.5))]
    holes.append((3, occ.addCylinder(2 * IN, 0.5 * IN, -1, 0, 0, IN + 2, 0.201 * IN / 2)))
    (cut,), _ = occ.cut([(3, blk)], holes)
    boss = occ.addCylinder(2 * IN, 1.2 * IN, IN, 0, 0, 0.5 * IN, 0.5 * IN)
    occ.fuse([cut], [(3, boss)])
    occ.synchronize()
    gmsh.write(path)
    gmsh.finalize()
    del upright


def _make(path):
    import multiprocessing as mp

    p = mp.get_context("spawn").Process(target=_build, args=(str(path),))
    p.start()
    p.join(180)
    if p.exitcode != 0 or not Path(path).is_file():
        raise RuntimeError("could not build the test part")


def size(text, nominal, lo=None, hi=None, kind="dim", typ="Linear", count=1, places=3, **more):
    return {"kind": kind, "type": typ, "text": text, "nominal": nominal, "lo": lo, "hi": hi, "count": count, "places": places,
            "tol": "print" if lo is not None else None, **more}


class OnTheModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from solidsmufs.kernel.worker import Session

        cls.dir = Path(tempfile.mkdtemp(prefix="solidsmufs-test-"))
        step = cls.dir / "block.step"
        _make(step)
        cls.s = Session()
        cls.s.load(str(step), "normal")
        cls.m = cls.s.model

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def run_on(self, items, unit="in"):
        return self.s.callouts(items, unit)

    def faces_of(self, typ, radius, inside=True):
        """Faces of that radius away from the block's corners (the holes), or at them (the rounds)."""
        def corner(f):
            x, y = self.m.face_params[f]["center"][:2]
            return min(x, 4 * IN - x) < 0.2 * IN and min(y, 2 * IN - y) < 0.2 * IN
        return sorted(f for f, t in enumerate(self.m.face_type) if t == typ and abs(self.m.face_params[f]["radius"] - radius) < 1e-3
                      and corner(f) != inside)

    def test_sizes(self):
        items = [size("4X Ø.250 ±.002", 0.25, 0.248, 0.252, typ="Diameter", count=4),
                 size("Ø1.000 ±.001", 1.0, 0.999, 1.001, typ="Diameter"),
                 size("1/4-20 UNC", None, kind="thread", typ="Thread", places=0),
                 size("R.125", 0.125, typ="Radius"),
                 size("4.000 ±.005", 4.0, 3.995, 4.005),
                 size("1.000", 1.0, 0.995, 1.005),
                 {"kind": "gdt", "type": "Position", "text": "⌖|Ø.010 Ⓜ|A|B", "with": 0},
                 {"kind": "note", "type": "Note", "text": "BREAK ALL SHARP EDGES"}]
        r = self.run_on(items)
        self.assertEqual(r["unit"], "in")
        holes, boss, tapped, fillet, length, thick, frame, note = r["results"]
        self.assertEqual(holes["status"], "one")
        self.assertEqual(holes["choices"][0]["count"], 4)
        self.assertEqual(holes["choices"][0]["faces"], self.faces_of("cylinder", 0.125 * IN))
        self.assertEqual(boss["status"], "one")
        self.assertIn("boss", boss["choices"][0]["what"])
        self.assertEqual(tapped["status"], "one")
        self.assertEqual(tapped["choices"][0]["faces"], self.faces_of("cylinder", 0.201 * IN / 2))
        self.assertEqual(fillet["status"], "one")
        self.assertEqual(fillet["choices"][0]["faces"], self.faces_of("cylinder", 0.125 * IN, inside=False))
        self.assertEqual(length["status"], "one")  # only the block's ends are 4.000 apart
        self.assertEqual(thick["status"], "choices")  # its thickness, and the rows of holes 1.000 apart
        self.assertIn("parallel faces", thick["choices"][0]["what"])
        self.assertEqual(frame["status"], "one")
        self.assertEqual(frame["choices"], holes["choices"])
        self.assertAlmostEqual(frame["band"], 0.010)
        self.assertAlmostEqual(holes["band"], 0.004)
        self.assertEqual(note["status"], "skip")
        self.assertIsNotNone(holes["choices"][0]["at"])

    def test_unit_found_when_the_print_doesnt_say(self):
        r = self.run_on([size("Ø6.35", 6.35, 6.33, 6.37, typ="Diameter"), size("101.6", 101.6, 101.5, 101.7)], unit=None)
        self.assertEqual(r["unit"], "mm")
        self.assertEqual([x["status"] for x in r["results"]], ["one", "one"])

    def test_metric_sizes_on_a_print_that_says_inches(self):
        r = self.run_on([size("Ø6.35", 6.35, 6.33, 6.37, typ="Diameter"), size("101.6", 101.6, 101.5, 101.7)], unit="in")
        self.assertEqual(r["unit"], "mm")
        self.assertEqual([x["status"] for x in r["results"]], ["one", "one"])

    def test_no_length_smaller_than_its_tolerance(self):  # ".005" with the title block's ±.005: a flatness, not a length
        self.assertEqual(self.run_on([size(".005", 0.005, 0.0, 0.010)])["results"][0]["status"], "none")

    def test_plain_length_across_a_hole(self):  # a diameter dimensioned in a side view, or its Ø not read
        r = self.run_on([size(".250", 0.25, 0.248, 0.252)])["results"][0]
        self.assertEqual(r["status"], "one")
        self.assertEqual(r["choices"][0]["faces"], self.faces_of("cylinder", 0.125 * IN))
        self.assertIn("across", r["choices"][0]["what"])

    def test_min_length(self):  # at least 3.900: the block's 4.000, not the holes 3.000 apart
        r = self.run_on([size("3.900 MIN", 3.9, 3.9, None)])["results"][0]
        self.assertEqual(r["status"], "one")
        self.assertAlmostEqual(r["choices"][0]["size"], 4 * IN, places=3)

    def test_decimal_point_lost(self):  # OCR's "Ø 250" on an inch print: no part has a 250 in hole
        r = self.run_on([size("4X Ø 250", 250, typ="Diameter", count=4, places=0)])["results"][0]
        self.assertEqual(r["status"], "one")
        self.assertIn("read as .250", r["choices"][0]["what"])

    def test_nothing_that_size(self):
        r = self.run_on([size("Ø.500", 0.5, 0.499, 0.501, typ="Diameter")])
        self.assertEqual(r["results"][0]["status"], "none")


class OffThePrint(unittest.TestCase):
    def test_read_without_changing_it(self):
        import pymupdf

        from solidsmufs.kernel.pdfdoc import PdfFile
        from solidsmufs.kernel.pdfedit import PdfEditor

        d = Path(tempfile.mkdtemp(prefix="ss-co-"))
        self.addCleanup(shutil.rmtree, d, True)
        path = d / "print.pdf"
        doc = pymupdf.open()
        pg = doc.new_page(width=792, height=612)
        pg.insert_text((100, 100), "4X Ø.250 ±.002", fontsize=10, fontname="helv")
        pg.insert_text((300, 200), "4.000 ±.005", fontsize=10, fontname="helv")
        doc.save(path)
        doc.close()
        before = path.read_bytes()
        pdf = PdfFile(str(path))
        self.addCleanup(pdf.close)
        r = PdfEditor(pdf, path).run("callouts", {"extra": {"unit": "in", "pages": {}}})
        self.assertFalse(r["ballooned"])
        texts = [c["text"] for c in r["callouts"]]
        self.assertTrue(any("4.000" in t for t in texts), texts)
        hole = next(c for c in r["callouts"] if c["nominal"] == 0.25)
        self.assertEqual((hole["type"], hole["count"], hole["lo"], hole["hi"]), ("Diameter", 4, 0.248, 0.252))
        self.assertEqual(path.read_bytes(), before)


class DrawnSymbols(unittest.TestCase):
    """Symbols some CAD exports draw as lines, not text: read into the callout they're in."""

    def test_read(self):
        import pymupdf

        from solidsmufs.kernel.pdfdoc import PdfFile
        from solidsmufs.kernel.pdfedit import PdfEditor

        d = Path(tempfile.mkdtemp(prefix="ss-sym-"))
        self.addCleanup(shutil.rmtree, d, True)
        path = d / "print.pdf"
        doc = pymupdf.open()
        pg = doc.new_page(width=792, height=612)

        def text(x, y, s):
            pg.insert_text((x, y), s, fontsize=10, fontname="helv")
            return x + pymupdf.get_text_length(s, fontname="helv", fontsize=10)

        def pm(x, y):  # ± as two flats and an upright, 4.6 wide
            sh = pg.new_shape()
            sh.draw_line((x, y - 5.5), (x + 4.6, y - 5.5))
            sh.draw_line((x + 2.3, y - 7.8), (x + 2.3, y - 3.2))
            sh.draw_line((x, y), (x + 4.6, y))
            sh.finish(width=0.5, color=(0, 0, 0))
            sh.commit()
            return x + 4.6

        def dia(x, y):  # Ø as a circle and a slash
            sh = pg.new_shape()
            sh.draw_circle((x + 3.5, y - 3.5), 3.2)
            sh.draw_line((x + 0.5, y + 1), (x + 6.5, y - 8))
            sh.finish(width=0.5, color=(0, 0, 0))
            sh.commit()
            return x + 7

        x = text(100, 100, "15.00")
        x = pm(x + 3, 100)
        text(x + 3, 100, "0.25")
        x = dia(100, 200)
        text(x + 3, 200, "3.20")
        x = text(300, 300, "10.00")
        text(x + 3, 295, "0.00")
        text(x + 3, 305, "-0.36")
        doc.save(path)
        doc.close()
        pdf = PdfFile(str(path))
        self.addCleanup(pdf.close)
        r = PdfEditor(pdf, path).run("callouts", {"extra": {"unit": "mm", "pages": {}}})
        got = {c["nominal"]: c for c in r["callouts"] if c["kind"] == "dim"}
        self.assertEqual((got[15.0]["lo"], got[15.0]["hi"]), (14.75, 15.25), r["callouts"])
        self.assertIn("Ø", got[3.2]["text"])
        self.assertEqual(got[3.2]["type"], "Diameter")
        self.assertAlmostEqual(got[10.0]["lo"], 9.64)
        self.assertAlmostEqual(got[10.0]["hi"], 10.0)
        self.assertNotIn(0.25, got)  # the tolerance isn't a size of its own

    def test_parse(self):
        from solidsmufs.kernel import balloons

        kinds = lambda t: [(i["kind"], i["nominal"], i["plus"]) for i in balloons.parse(t, "mm")]  # noqa: E731
        self.assertEqual(kinds("0.50 ±0.25 X 45°"), [("chamfer", 0.5, 0.25)])
        self.assertEqual(kinds("Ø 4.20 ±0.20 X 90° ± 5°"), [("dim", 4.2, 0.2), ("angle", 90.0, 5.0)])  # a countersink


class Misreads(unittest.TestCase):
    def test_countersink_diameter(self):
        from types import SimpleNamespace
        S = SimpleNamespace(spheres=[], cyl=[], cones=[{"face": 7, "radius_min": 1.6, "radius_max": 2.1}])
        found = callouts._diameter(S, size("Ø4.20 ±0.20", 4.2, 4.0, 4.4, typ="Diameter"), "mm")
        self.assertEqual(found[0]["faces"], [7])

    def test_too_many_places(self):
        r = callouts._result(None, [{"faces": [i], "at": [0, 0, 0]} for i in range(callouts.TOO_MANY + 1)])
        self.assertEqual(r["status"], "none")
        self.assertIn("too many", r["why"])


class Bands(unittest.TestCase):
    def test_band(self):
        self.assertAlmostEqual(callouts.band_in({"kind": "dim", "lo": 0.248, "hi": 0.252}, "in"), 0.004)
        self.assertAlmostEqual(callouts.band_in({"kind": "dim", "lo": 9.9, "hi": 10.1}, "mm"), 0.2 / IN)
        self.assertIsNone(callouts.band_in({"kind": "dim", "lo": 1, "hi": 1, "tol": "basic"}, "in"))

    def test_min_and_max_windows(self):
        lo, hi = callouts.window({"nominal": 3.0, "lo": 3.0, "hi": None}, "mm")
        self.assertTrue(lo < 3.0 < 3.7 < hi < 3.8)
        lo, hi = callouts.window({"nominal": 4.0, "lo": None, "hi": 4.0}, "mm")
        self.assertTrue(2.9 < lo < 3.1 and 3.99 < hi < 4.01)


class Depths(unittest.TestCase):
    def test_depth_to_where_a_countersink_ends(self):  # an end face, and a countersink 4.2 into it (no flat face there)
        import numpy as np
        from types import SimpleNamespace
        d = np.array([1.0, 0, 0])
        S = SimpleNamespace(planes=[{"face": 0, "n": d, "off": 0.0}], cyl=[], cones=[{"face": 1, "axis": [1, 0, 0]}],
                            directions=lambda: [d], ends=lambda f, dd: (4.2, 5.0), at=lambda faces: [0, 0, 0])
        found = callouts._linear(S, size("4.20", 4.2), "mm")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["faces"], [0, 1])
        self.assertIn("depth", found[0]["what"])


class Angles(unittest.TestCase):
    def test_chamfer_angle_from_the_face(self):  # a 22.5° chamfer on a head is a cone 67.5° off its axis
        from types import SimpleNamespace
        S = SimpleNamespace(cones=[{"face": 3, "half_angle": 67.5}, {"face": 5, "half_angle": 59.0}], planes=[], near={})
        found = callouts._angle(S, {"nominal": 22.5}, "mm")
        self.assertEqual(found[0]["faces"], [3])


if __name__ == "__main__":
    unittest.main()
