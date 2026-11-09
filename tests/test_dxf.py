"""DXF drawings: the reader (geometry, blocks, colours, text, units) and the model the viewer gets.

The drawings are written here, pair by pair, so each test knows exactly what's in its file.
"""

import math
import os
import tempfile
import unittest

import numpy as np

from solidsmufs.formats import dxf
from solidsmufs.kernel import drawing


def pairs(*items):
    """DXF text from (code, value) pairs."""
    return "".join(f"{c:>3}\n{v}\n" for c, v in items)


def file(entities, header=(), layers=(), blocks=""):
    """A whole DXF: a header with the given variables, a layer table, blocks, and entities."""
    head = pairs((0, "SECTION"), (2, "HEADER")) + "".join(pairs((9, name), *vals) for name, vals in header) + pairs((0, "ENDSEC"))
    table = pairs((0, "SECTION"), (2, "TABLES"), (0, "TABLE"), (2, "LAYER"))
    for name, color, flags in layers:
        table += pairs((0, "LAYER"), (2, name), (70, flags), (62, color), (6, "CONTINUOUS"))
    table += pairs((0, "ENDTAB"), (0, "ENDSEC"))
    return (head + table + pairs((0, "SECTION"), (2, "BLOCKS")) + blocks + pairs((0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES"))
            + entities + pairs((0, "ENDSEC"), (0, "EOF"))).encode()


def line(x0, y0, x1, y1, layer="0", color=None):
    extra = [(62, color)] if color is not None else []
    return pairs((0, "LINE"), (8, layer), *extra, (10, x0), (20, y0), (30, 0), (11, x1), (21, y1), (31, 0))


INCHES = [("$INSUNITS", [(70, 1)])]
MM = [("$INSUNITS", [(70, 4)])]


def read(entities, **kw):
    return dxf.read_dxf(file(entities, **kw))


def conics(d):
    return [c for _l, _c, c in d.curves if isinstance(c, dxf.Conic)]


def polys(d):
    return [c for _l, _c, c in d.curves if isinstance(c, dxf.Poly)]


class Geometry(unittest.TestCase):
    def test_line_circle_arc(self):
        d = read(line(0, 0, 10, 0)
                 + pairs((0, "CIRCLE"), (8, "0"), (10, 5), (20, 5), (30, 0), (40, 2))
                 + pairs((0, "ARC"), (8, "0"), (10, 0), (20, 0), (30, 0), (40, 3), (50, 350), (51, 10)), header=MM)
        (p,) = polys(d)
        np.testing.assert_allclose(p.points, [[0, 0, 0], [10, 0, 0]])
        circle, arc = conics(d)
        self.assertTrue(circle.closed)
        self.assertEqual(circle.round()[0], 2)
        np.testing.assert_allclose(math.degrees(arc.t1 - arc.t0), 20)  # 350° round to 10°: through 0
        np.testing.assert_allclose(arc.at([arc.t0])[0], [3 * math.cos(math.radians(350)), 3 * math.sin(math.radians(350)), 0], atol=1e-12)

    def test_mirrored_arc(self):
        """An arc with its extrusion pointing down (as mirrored sketches export) lies mirrored in X."""
        d = read(pairs((0, "ARC"), (8, "0"), (10, 5), (20, 0), (30, 0), (40, 1), (50, 0), (51, 90), (210, 0), (220, 0), (230, -1)))
        (arc,) = conics(d)
        np.testing.assert_allclose(arc.center, [-5, 0, 0], atol=1e-12)
        ends = arc.at([arc.t0, arc.t1])
        np.testing.assert_allclose(ends, [[-6, 0, 0], [-5, 1, 0]], atol=1e-12)  # its own X runs the other way

    def test_lwpolyline_bulges(self):
        """A slot: two straight sides and two half circles made by bulge 1, closed."""
        d = read(pairs((0, "LWPOLYLINE"), (8, "0"), (90, 4), (70, 1),
                       (10, 0), (20, 0), (10, 10), (20, 0), (42, 1), (10, 10), (20, 4), (10, 0), (20, 4), (42, 1)))
        self.assertEqual(len(polys(d)), 2)
        arcs = conics(d)
        self.assertEqual(len(arcs), 2)
        for a, centre in zip(arcs, ([10, 2, 0], [0, 2, 0])):
            np.testing.assert_allclose(a.center, centre, atol=1e-12)
            self.assertAlmostEqual(a.round()[0], 2)
            self.assertAlmostEqual(a.t1 - a.t0, math.pi)
        # the right end bulges out to the right, the left end to the left
        self.assertAlmostEqual(arcs[0].at([(arcs[0].t0 + arcs[0].t1) / 2])[0][0], 12)
        self.assertAlmostEqual(arcs[1].at([(arcs[1].t0 + arcs[1].t1) / 2])[0][0], -2)

    def test_clockwise_bulge(self):
        """Going left to right, a positive bulge (anticlockwise) dips below the chord, a negative one rises above."""
        for sign in (1, -1):
            d = read(pairs((0, "LWPOLYLINE"), (8, "0"), (90, 2), (70, 0), (10, 0), (20, 0), (42, sign * math.tan(math.pi / 8)), (10, 2), (20, 0)))
            (a,) = conics(d)
            self.assertAlmostEqual(a.t1 - a.t0, math.pi / 2)
            mid = a.at([(a.t0 + a.t1) / 2])[0]
            self.assertAlmostEqual(mid[1], -sign * (math.sqrt(2) - 1))
        ends = a.at([a.t0, a.t1])
        self.assertTrue(any(np.allclose(e, [0, 0, 0], atol=1e-12) for e in ends) and any(np.allclose(e, [2, 0, 0], atol=1e-12) for e in ends))

    def test_ellipse_and_spline(self):
        d = read(pairs((0, "ELLIPSE"), (8, "0"), (10, 0), (20, 0), (30, 0), (11, 4), (21, 0), (31, 0), (40, 0.5), (41, 0), (42, 2 * math.pi))
                 + pairs((0, "SPLINE"), (8, "0"), (70, 8), (71, 2), (72, 6), (73, 3), (74, 0),
                         (40, 0), (40, 0), (40, 0), (40, 1), (40, 1), (40, 1), (10, 0), (20, 0), (30, 0), (10, 1), (20, 2), (30, 0), (10, 2), (20, 0), (30, 0)))
        (e,) = conics(d)
        self.assertIsNone(e.round())
        np.testing.assert_allclose(e.v, [0, 2, 0])
        (s,) = polys(d)
        self.assertEqual(s.kind, "spline")
        np.testing.assert_allclose(s.points[0], [0, 0, 0])
        np.testing.assert_allclose(s.points[-1], [2, 0, 0])
        # a quadratic's middle is halfway to its control point
        np.testing.assert_allclose(dxf._de_boor(0.5, 2, np.array([0, 0, 0, 1, 1, 1.0]), np.array([[0, 0, 0], [1, 2, 0], [2, 0, 0.0]]), np.ones(3)),
                                   [1, 1, 0], atol=1e-12)
        self.assertLess(np.abs(s.points[:, 1]).max(), 1 + 1e-9)

    def test_block_insert(self):
        """A block of one line, inserted turned 90°, scaled by 2 and moved, with its base point honoured."""
        block = pairs((0, "BLOCK"), (8, "0"), (2, "TICK"), (70, 0), (10, 1), (20, 0), (30, 0), (3, "TICK")) + line(1, 0, 2, 0) + pairs((0, "ENDBLK"))
        d = read(pairs((0, "INSERT"), (8, "0"), (2, "TICK"), (10, 10), (20, 10), (30, 0), (41, 2), (42, 2), (43, 2), (50, 90)), blocks=block)
        (p,) = polys(d)
        np.testing.assert_allclose(p.points, [[10, 10, 0], [10, 12, 0]], atol=1e-12)

    def test_block_array_and_nesting(self):
        inner = pairs((0, "BLOCK"), (8, "0"), (2, "DOT"), (70, 0), (10, 0), (20, 0), (30, 0)) + pairs((0, "CIRCLE"), (8, "0"), (10, 0), (20, 0), (30, 0), (40, 1)) + pairs((0, "ENDBLK"))
        outer = pairs((0, "BLOCK"), (8, "0"), (2, "ROW"), (70, 0), (10, 0), (20, 0), (30, 0)) + pairs((0, "INSERT"), (8, "0"), (2, "DOT"), (10, 0), (20, 0), (30, 0), (70, 3), (44, 5)) + pairs((0, "ENDBLK"))
        d = read(pairs((0, "INSERT"), (8, "0"), (2, "ROW"), (10, 0), (20, 100), (30, 0), (71, 2), (45, 10)), blocks=inner + outer)
        centres = sorted(tuple(np.round(c.center, 9)) for c in conics(d))
        self.assertEqual(centres, sorted((x, y, 0.0) for x in (0.0, 5.0, 10.0) for y in (100.0, 110.0)))

    def test_self_insert_stops(self):
        loop = pairs((0, "BLOCK"), (8, "0"), (2, "LOOP"), (70, 0), (10, 0), (20, 0), (30, 0)) + line(0, 0, 1, 0) + pairs((0, "INSERT"), (8, "0"), (2, "LOOP"), (10, 1), (20, 0), (30, 0)) + pairs((0, "ENDBLK"))
        d = read(pairs((0, "INSERT"), (8, "0"), (2, "LOOP"), (10, 0), (20, 0), (30, 0)), blocks=loop)
        self.assertEqual(len(polys(d)), 1)
        self.assertTrue(d.skipped)

    def test_dimension_draws_its_block(self):
        block = pairs((0, "BLOCK"), (8, "0"), (2, "*D1"), (70, 1), (10, 0), (20, 0), (30, 0)) + line(0, 0, 10, 0) + pairs((0, "MTEXT"), (8, "0"), (10, 5), (20, 1), (30, 0), (40, 2.5), (71, 8), (1, "10.00")) + pairs((0, "ENDBLK"))
        d = read(pairs((0, "DIMENSION"), (8, "DIMS"), (2, "*D1"), (10, 10), (20, 0), (30, 0), (11, 5), (21, 1), (31, 0), (70, 32)), blocks=block,
                 layers=[("DIMS", 3, 0)])
        self.assertEqual(len(polys(d)), 1)
        (t,) = [t for _l, _c, t in d.texts]
        self.assertEqual(t.lines, ["10.00"])
        self.assertEqual(d.curves[0][0], "DIMS")  # layer 0 inside the block takes the dimension's layer


class Properties(unittest.TestCase):
    def test_colours_and_layers(self):
        block = pairs((0, "BLOCK"), (8, "0"), (2, "B"), (70, 0), (10, 0), (20, 0), (30, 0)) + line(0, 0, 1, 0, color=0) + pairs((0, "ENDBLK"))
        d = read(line(0, 0, 1, 0, "RED") + line(0, 0, 1, 0, "RED", color=5) + line(0, 0, 1, 0, "INK")
                 + pairs((0, "INSERT"), (8, "RED"), (62, 3), (2, "B"), (10, 0), (20, 0), (30, 0))
                 + line(0, 0, 1, 0, "OFF") + line(0, 0, 1, 0, "FROZEN"),
                 layers=[("RED", 1, 0), ("INK", 7, 0), ("OFF", -2, 0), ("FROZEN", 4, 1)], blocks=block)
        got = [(layer, color) for layer, color, _c in d.curves]
        self.assertEqual(got[0], ("RED", (1.0, 0.0, 0.0)))  # BYLAYER
        self.assertEqual(got[1], ("RED", (0.0, 0.0, 1.0)))  # its own colour
        self.assertEqual(got[2], ("INK", None))  # colour 7: the drawing's ink
        self.assertEqual(got[3], ("RED", (0.0, 1.0, 0.0)))  # BYBLOCK: the insert's colour
        self.assertFalse(d.layers["OFF"].on)
        self.assertTrue(d.layers["FROZEN"].frozen)

    def test_aci_shades(self):
        self.assertEqual(dxf.aci(1), (1.0, 0.0, 0.0))
        np.testing.assert_allclose(dxf.aci(11), (1.0, 0.5, 0.5), atol=0.01)  # FF7F7F
        np.testing.assert_allclose(dxf.aci(12), (0.8, 0.0, 0.0), atol=0.01)  # CC0000
        np.testing.assert_allclose(dxf.aci(150), (0.0, 0.5, 1.0), atol=0.01)  # 007FFF
        self.assertIsNone(dxf.aci(7))

    def test_units(self):
        self.assertEqual(read(line(0, 0, 1, 0), header=INCHES).unit_mm, 25.4)
        self.assertEqual(read(line(0, 0, 1, 0), header=MM).unit_mm, 1.0)
        self.assertEqual(read(line(0, 0, 1, 0), header=[("$MEASUREMENT", [(70, 1)])]).units, "millimetres")
        unknown = read(line(0, 0, 1, 0))
        self.assertIsNone(unknown.units)
        self.assertEqual(unknown.unit_mm, 25.4)

    def test_r12_without_header(self):
        """Old files are often just an ENTITIES section."""
        d = dxf.read_dxf((pairs((0, "SECTION"), (2, "ENTITIES")) + line(0, 0, 1, 1) + pairs((0, "ENDSEC"), (0, "EOF"))).encode())
        self.assertEqual(len(polys(d)), 1)

    def test_not_dxf_and_binary(self):
        with self.assertRaises(dxf.DxfError):
            dxf.read_dxf(b"solid cube\nfacet normal 0 0 1\n")
        with self.assertRaises(dxf.DxfError):
            dxf.read_dxf(dxf.BINARY_SENTINEL + b"\r\n\x1a\x00rest")

    def test_paper_space_when_model_is_empty(self):
        d = read(pairs((0, "LINE"), (8, "0"), (67, 1), (10, 0), (20, 0), (30, 0), (11, 1), (21, 0), (31, 0)))
        self.assertEqual(d.space, "paper")
        self.assertEqual(len(polys(d)), 1)

    def test_skipped_are_counted(self):
        d = read(line(0, 0, 1, 0) + pairs((0, "HATCH"), (8, "0")) + pairs((0, "3DSOLID"), (8, "0")))
        self.assertEqual(d.skipped["hatching"], 1)
        self.assertEqual(d.skipped["3D solids and surfaces"], 1)


class Text(unittest.TestCase):
    def test_special_characters(self):
        self.assertEqual(dxf.plain_text("%%c10 %%p0.1 45%%d %%uunder%%u 100%%%"), "Ø10 ±0.1 45° under 100%")
        self.assertEqual(dxf.plain_text("\\U+00D8"), "Ø")

    def test_mtext_formatting(self):
        s = "{\\fArial|b1|i0|c0|p34;\\C1;BIG} \\H2.5x;text\\Pline two\\P\\S1/2;\\~in\\\\out"
        self.assertEqual(dxf.mtext_lines(s), ["BIG text", "line two", "1/2 in\\out"])

    def test_text_alignment(self):
        d = read(pairs((0, "TEXT"), (8, "0"), (10, 0), (20, 0), (30, 0), (40, 2), (1, "MID"), (50, 90), (72, 1), (11, 5), (21, 5), (31, 0), (73, 2)))
        (t,) = [t for _l, _c, t in d.texts]
        np.testing.assert_allclose(t.origin, [5, 5, 0])
        np.testing.assert_allclose(t.xdir, [0, 1, 0], atol=1e-12)
        np.testing.assert_allclose(t.ydir, [-1, 0, 0], atol=1e-12)
        self.assertEqual((t.halign, t.valign, t.height), ("center", "middle", 2))

    def test_text_in_scaled_block(self):
        block = pairs((0, "BLOCK"), (8, "0"), (2, "LBL"), (70, 0), (10, 0), (20, 0), (30, 0)) + pairs((0, "TEXT"), (8, "0"), (10, 0), (20, 0), (30, 0), (40, 1), (1, "A")) + pairs((0, "ENDBLK"))
        d = read(pairs((0, "INSERT"), (8, "0"), (2, "LBL"), (10, 0), (20, 0), (30, 0), (41, 3), (42, 2), (43, 1)), blocks=block)
        (t,) = [t for _l, _c, t in d.texts]
        self.assertAlmostEqual(t.height, 2)
        self.assertAlmostEqual(t.width, 1.5)  # stretched: 3 along, 2 up

    def test_attributes_shown_unless_invisible(self):
        block = pairs((0, "BLOCK"), (8, "0"), (2, "TB"), (70, 2), (10, 0), (20, 0), (30, 0)) + pairs((0, "ENDBLK"))
        ins = (pairs((0, "INSERT"), (8, "0"), (66, 1), (2, "TB"), (10, 0), (20, 0), (30, 0))
               + pairs((0, "ATTRIB"), (8, "0"), (10, 1), (20, 1), (30, 0), (40, 1), (1, "PART-42"), (2, "PN"), (70, 0))
               + pairs((0, "ATTRIB"), (8, "0"), (10, 1), (20, 3), (30, 0), (40, 1), (1, "secret"), (2, "X"), (70, 1))
               + pairs((0, "SEQEND"), (8, "0")))
        d = read(ins, blocks=block)
        self.assertEqual([t.lines for _l, _c, t in d.texts], [["PART-42"]])


class Model(unittest.TestCase):
    def test_model_for_the_viewer(self):
        data = file(line(0, 0, 1, 0, "A") + pairs((0, "CIRCLE"), (8, "B"), (10, 0), (20, 0), (30, 0), (40, 0.5))
                    + pairs((0, "TEXT"), (8, "B"), (10, 0), (20, 0), (30, 0), (40, 0.1), (1, "HI")), header=INCHES,
                    layers=[("A", 1, 0), ("B", 7, 0), ("EMPTY", 2, 0)])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.dxf")
            with open(path, "wb") as f:
                f.write(data)
            m = drawing.load(path, "t.dxf")
        meta, blob = m.payload()
        self.assertEqual(meta["kind"], "drawing")
        self.assertTrue(meta["drawing"])
        self.assertEqual([b["name"] for b in meta["bodies"]], ["A", "B"])  # empty layers left out
        self.assertEqual(meta["edges"]["type"], ["line", "circle"])
        self.assertEqual(meta["edges"]["body"], [0, 1])
        self.assertEqual(meta["edges"]["color"], [(1.0, 0.0, 0.0), None])
        self.assertAlmostEqual(meta["edges"]["length"][0], 25.4)  # in millimetres
        self.assertAlmostEqual(meta["edges"]["params"][1]["radius"], 12.7)
        self.assertAlmostEqual(meta["edges"]["length"][1], math.pi * 25.4, delta=0.01)
        (t,) = meta["texts"]
        self.assertEqual((t["lines"], t["body"]), (["HI"], 1))
        self.assertAlmostEqual(t["height"], 2.54)
        self.assertEqual(len(m.vertices), 2)  # the line's ends; a whole circle has none
        self.assertEqual(meta["stats"]["faces"], 0)
        self.assertTrue(blob)


if __name__ == "__main__":
    unittest.main()
