"""G-code toolpaths, pictures (and the preview pictures in SolidWorks drawings, eDrawings and DWG files), and
zip archives. Every file is made here, so each test knows exactly what's in it."""

import io
import math
import os
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

from solidsmufs import archive
from solidsmufs.formats import gcode
from solidsmufs.kernel import toolpath


def prog(*lines):
    return ("\n".join(lines) + "\n").encode()


def moves(*lines):
    return gcode.read_gcode(prog(*lines)).moves


class GcodeTest(unittest.TestCase):
    def test_straight_moves_and_units(self):
        p = gcode.read_gcode(prog("G21 G90", "G0 X0 Y0 Z5", "G1 Z-1 F100", "X10", "Y10"))
        self.assertEqual(p.unit_mm, 1.0)
        self.assertEqual(p.units, "millimetres")
        self.assertEqual([m.kind for m in p.moves], ["feed", "feed", "feed"])
        np.testing.assert_allclose(p.moves[-1].points[-1], [10, 10, -1])

    def test_inches_when_not_said(self):
        p = gcode.read_gcode(prog("G0 X0 Y0 Z1", "G1 X1"))
        self.assertIsNone(p.units)
        self.assertEqual(p.unit_mm, 25.4)

    def test_incremental(self):
        m = moves("G0 X1 Y1 Z1", "G91", "G1 X2", "Y-1")
        np.testing.assert_allclose(m[-1].points[-1], [3, 0, 1])

    def test_arc_by_ijk(self):
        m = moves("G0 X10 Y0 Z0", "G3 X0 Y10 I-10 J0")[-1]
        self.assertEqual(m.kind, "arc")
        np.testing.assert_allclose(m.arc["center"], [0, 0, 0], atol=1e-12)
        self.assertAlmostEqual(m.arc["sweep"], math.pi / 2)
        self.assertTrue(np.allclose(np.linalg.norm(m.points[:, :2], axis=1), 10))

    def test_clockwise_and_full_circle(self):
        m = moves("G0 X10 Y0 Z0", "G2 X10 Y0 I-10 J0")[-1]
        self.assertAlmostEqual(m.arc["sweep"], -2 * math.pi)
        self.assertTrue(m.arc["full"])
        # going clockwise from (10, 0), the next points are below the X axis
        self.assertLess(m.points[1][1], 0)

    def test_arc_by_radius(self):
        short = moves("G0 X0 Y0 Z0", "G2 X10 Y0 R5")[-1]
        np.testing.assert_allclose(short.arc["center"], [5, 0, 0], atol=1e-9)
        long_way = moves("G0 X0 Y0 Z0", "G3 X10 Y10 R-10")[-1]  # negative R: the arc over 180 degrees
        self.assertGreater(abs(long_way.arc["sweep"]), math.pi)
        small = moves("G0 X0 Y0 Z0", "G3 X10 Y10 R10")[-1]
        self.assertLess(abs(small.arc["sweep"]), math.pi)

    def test_helix(self):
        m = moves("G0 X5 Y0 Z0", "G3 X5 Y0 Z-2 I-5 J0")[-1]
        self.assertTrue(m.arc["helical"])
        self.assertAlmostEqual(m.points[-1][2], -2)
        self.assertAlmostEqual(m.points[len(m.points) // 2][2], -1, places=1)

    def test_other_planes(self):
        m = moves("G18", "G0 X0 Y0 Z10", "G2 X10 Z0 I0 K-10")[-1]  # in the ZX plane, around Y
        np.testing.assert_allclose(m.arc["center"], [0, 0, 0], atol=1e-9)
        np.testing.assert_allclose(m.arc["normal"], [0, 1, 0])
        self.assertTrue(np.allclose(m.points[:, 1], 0))

    def test_drilling_cycle(self):
        m = moves("G0 X0 Y0 Z1", "G98 G81 X1 Y1 Z-0.5 R0.1 F5", "X2", "G80", "G0 Z2")
        holes = [x for x in m if x.kind == "feed"]
        self.assertEqual(len(holes), 2)
        np.testing.assert_allclose(holes[0].points, [[1, 1, 0.1], [1, 1, -0.5]])
        np.testing.assert_allclose(holes[1].points[0], [2, 1, 0.1])
        # G98: back up to where the cycle started, Z1
        self.assertEqual(m[3].kind, "rapid")
        self.assertAlmostEqual(m[3].points[-1][2], 1)

    def test_machine_home_moves_arent_drawn(self):
        m = moves("G0 X0 Y0 Z1", "G1 Z0 F10", "G28 G91 Z0", "G90", "G0 X5 Y5", "Z1", "G1 Z0")
        # after going home Z isn't known, so nothing is drawn until it is
        ends = [tuple(x.points[-1]) for x in m]
        self.assertEqual(ends, [(0, 0, 0), (5, 5, 0)])

    def test_tools_and_comments(self):
        p = gcode.read_gcode(prog("O1234 (BRACKET)", "(T3 D=0.25 - BALL END MILL)", "T3 M6", "G0 X0 Y0 Z1", "G1 Z0 F10",
                                  "T5 M6", "G0 X1 Y1 Z1", "G1 Z0"))
        self.assertEqual(sorted(p.tools), [3, 5])
        self.assertIn("BALL", p.tools[3])
        self.assertEqual(p.moves[0].tool, 3)
        self.assertEqual(p.moves[-1].tool, 5)

    def test_macros_and_subprograms_are_counted(self):
        p = gcode.read_gcode(prog("G0 X0 Y0 Z0", "#100=5", "M98 P2000", "G1 X1 F10"))
        self.assertEqual(p.skipped["lines using macro variables"], 1)
        self.assertEqual(p.skipped["subprogram calls (M98)"], 1)

    def test_not_gcode(self):
        with self.assertRaises(gcode.GcodeError):
            gcode.read_gcode(b"0 BEGIN PGM 12 MM\n")
        with self.assertRaises(gcode.GcodeError):
            gcode.read_gcode(b"hello there\n")


class ToolpathModelTest(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.nc"
            p.write_bytes(text)
            return toolpath.load(str(p), "x.nc")

    def test_bodies_edges_and_info(self):
        m = self.load(prog("G20", "(T1 D=0.5 FLAT)", "T1 M6", "G0 X0 Y0 Z1", "G1 Z0 F10", "G2 X1 Y1 I1 J0", "G0 Z1"))
        self.assertEqual([b["name"] for b in m.bodies], ["T1  D=0.5 FLAT", "Rapid moves"])
        self.assertEqual(m.edge_type, ["line", "circle", "line"])
        self.assertEqual(m.edge_body, [0, 0, 1])
        arc = m.edge_params[1]
        self.assertAlmostEqual(arc["radius"], 25.4)  # in mm
        self.assertAlmostEqual(arc["angle"], 90)
        self.assertEqual(m.info["Units"], "inches")
        self.assertIn("Cutting time (at the programmed feeds)", m.info)
        meta, _blob = m.payload()
        self.assertTrue(meta["drawing"] and meta["toolpath"])

    def test_big_programs_join_straight_runs(self):
        old = toolpath.EACH_MOVE
        toolpath.EACH_MOVE = 10
        try:
            lines = ["G0 X0 Y0 Z1", "G1 Z0 F10"] + [f"X{i} Y{i % 2}" for i in range(1, 30)] + ["G0 Z1"]
            m = self.load(prog(*lines))
        finally:
            toolpath.EACH_MOVE = old
        self.assertEqual(m.edge_type, ["path", "path"])
        self.assertTrue(any("joined" in n for n in m.notices))


def png_bytes(w=40, h=30, color=0xFF3366CC):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage
    from solidsmufs.kernel.pdfdoc import _qt
    _qt()
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(color)
    for x in range(w // 2):  # a black left half, so turns can be told apart
        for y in range(h):
            img.setPixel(x, y, 0xFF000000)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


class PictureTest(unittest.TestCase):
    def test_tiles_and_turns(self):
        from solidsmufs.kernel.pictures import POINTS_PER_PX, Picture
        pic = Picture("x.png", png_bytes(), "x.png")
        self.assertEqual(pic.pages()[0]["w"], 40 * POINTS_PER_PX)
        scale = 1 / POINTS_PER_PX  # one drawn pixel per picture pixel
        px = np.frombuffer(pic.tile(0, scale, 0, 0, 40, 30), np.uint8).reshape(30, 40, 4)
        self.assertLess(px[15, 5, :3].max(), 10)  # black on the left
        self.assertGreater(px[15, 35, 2], 150)  # blue-ish on the right
        turned = np.frombuffer(pic.tile(0, scale, 0, 0, 30, 40, 1), np.uint8).reshape(40, 30, 4)
        self.assertLess(turned[5, 15, :3].max(), 10)  # a quarter turn clockwise: the left half is now on top
        self.assertGreater(turned[35, 15, 2], 150)
        self.assertEqual(pic.find("x"), [])

    def test_dwg_preview(self):
        from solidsmufs.kernel.pictures import dwg_preview
        png = png_bytes()
        head = bytearray(b"AC1032" + b"\0" * 0x80)
        start = len(head)
        struct.pack_into("<I", head, 0x0D, start)
        section = b"\x1f" * 16 + struct.pack("<I", 0) + bytes([1]) + bytes([6]) + struct.pack("<II", start + 30, len(png))
        data = bytes(head) + section + png
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.dwg"
            p.write_bytes(data)
            self.assertEqual(dwg_preview(str(p)), png)

    def test_edrawings_preview(self):
        from solidsmufs.kernel.pictures import PictureError, edrawings_preview
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("eModel", b";; HSF V19.10 ")
            z.writestr("preview.jpg", b"\xff\xd8\xffJPEG")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.eprt"
            p.write_bytes(b"[\x01\x00\x00\x00\xbe\r2008+ archive" + b"\0" * 40 + buf.getvalue())
            self.assertEqual(edrawings_preview(str(p)), b"\xff\xd8\xffJPEG")
            p.write_bytes(b";; HSF V10.00 \nI\0\0")
            with self.assertRaises(PictureError):
                edrawings_preview(str(p))


def pe(*values, seven=False):
    """HP-GL/2 PE numbers: the sign in the lowest bit, then base 64 (or 32) digits, the last one marked."""
    out = ""
    for v in values:
        n = -2 * v + 1 if v < 0 else 2 * v
        base, end = (32, 95) if seven else (64, 191)
        while n >= base:
            out += chr(63 + n % base)
            n //= base
        out += chr(end + n)
    return out


class HpglTest(unittest.TestCase):
    def load(self, data, ext=".plt"):
        from solidsmufs.kernel import drawing
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / f"x{ext}"
            p.write_bytes(data)
            return drawing.load(str(p), p.name)

    def test_pens_lines_arcs_and_labels(self):
        m = self.load(b"IN;SP1;PU0,0;PD4000,0,4000,2000;PU2000,1000;CI400;SP2;PU1000,1000;PD;AA2000,1000,90;PU;"
                      b"PU0,3000;SI0.4,0.5;LBHELLO\x03;")
        self.assertEqual([b["name"] for b in m.bodies], ["Pen 1", "Pen 2"])
        self.assertEqual(m.edge_type, ["line", "line", "circle", "circle"])
        self.assertAlmostEqual(m.edge_length[0], 100.0)  # 4000 plotter units: 100 mm
        self.assertAlmostEqual(m.edge_params[2]["radius"], 10.0)
        self.assertAlmostEqual(m.edge_params[3]["angle"], 90.0)
        np.testing.assert_allclose(m.edge_params[3]["center"], [50, 25, 0])
        self.assertEqual(m.texts[0]["lines"], ["HELLO"])
        self.assertAlmostEqual(m.texts[0]["height"], 5.0)
        self.assertIsNone(m.edge_color[0])  # pen 1: the drawing's ink
        self.assertEqual(tuple(m.edge_color[3]), (0.9, 0.1, 0.1))  # pen 2: red

    def test_relative_moves(self):
        m = self.load(b"IN;PA;PU100,100;PR;PD400,0,0,400;")
        np.testing.assert_allclose(m.segments[-1][1], [12.5, 12.5, 0])

    def test_polyline_encoded(self):
        body = "<=" + pe(0, 0) + pe(4000, 0) + pe(0, 2000) + "<" + pe(1000, 1000) + pe(-200, 0)
        m = self.load(f"IN;SP1;PE{body};".encode("latin-1"))
        ends = [tuple(np.round(s[1], 3)) for s in m.segments]
        self.assertEqual(ends, [(100, 0, 0), (100, 50, 0), (120, 75, 0)])
        seven = self.load(f"IN;SP1;PE7<={pe(0, 0, seven=True)}{pe(400, 0, seven=True)};".encode("latin-1"))
        self.assertAlmostEqual(seven.edge_length[0], 10.0)

    def test_pcl_wrapped(self):
        m = self.load(b"\x1b%-12345X@PJL ENTER LANGUAGE=HPGL2\n\x1bE\x1b%1BIN;SP1;PD1000,0;\x1b%0A\x1bE\x1b%-12345X")
        self.assertEqual(len(m.edge_type), 1)

    def test_not_a_plot(self):
        from solidsmufs.formats.hpgl import HpglError
        with self.assertRaises(HpglError):
            self.load(b"\x00\x01\x02 just bytes")


class SvgTest(unittest.TestCase):
    def load(self, text):
        from solidsmufs.kernel import drawing
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.svg"
            p.write_text(text)
            return drawing.load(str(p), p.name)

    def test_units_layers_and_y_up(self):
        m = self.load('<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
                      'width="100mm" height="50mm" viewBox="0 0 200 100">'
                      '<g inkscape:label="Cut" stroke="red" fill="none"><circle cx="20" cy="20" r="10"/><line x1="0" y1="0" x2="200" y2="0"/></g>'
                      '<g id="Marks"><rect x="0" y="0" width="10" height="10"/></g></svg>')
        self.assertEqual([b["name"] for b in m.bodies], ["Cut", "Marks"])
        self.assertEqual(m.info["Units"], "millimetres")
        circle = m.edge_params[0]
        self.assertAlmostEqual(circle["radius"], 5.0)  # 200 user units across 100 mm
        np.testing.assert_allclose(circle["center"], [10, 40, 0])  # y flipped: 20 down from the top of 50 mm
        self.assertEqual(m.edge_color[0], [1.0, 0.0, 0.0] if isinstance(m.edge_color[0], list) else (1.0, 0.0, 0.0))
        self.assertAlmostEqual(m.edge_length[1], 100.0)

    def test_pixels_transforms_and_arcs(self):
        m = self.load('<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96">'
                      '<g transform="translate(48 48) rotate(90)"><path d="M0 0 L48 0"/></g>'
                      '<path d="M0 48 A24 24 0 0 1 48 48" stroke="black" fill="none"/></svg>')
        self.assertIn("pixels", m.info["Units"])
        line = m.edge_params[0]
        np.testing.assert_allclose(line["start"], [12.7, 12.7, 0], atol=1e-9)  # 48 px is half an inch
        np.testing.assert_allclose(line["end"], [12.7, 0, 0], atol=1e-9)  # turned to point down the page
        arc = m.edge_params[1]
        self.assertAlmostEqual(arc["radius"], 6.35)
        self.assertAlmostEqual(arc["angle"], 180.0)

    def test_curves_are_one_piece_each(self):
        m = self.load('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><path d="M0 0 C 2 5 8 5 10 0 Q 5 -5 0 0 z"/></svg>')
        self.assertEqual(m.edge_type, ["spline", "spline"])

    def test_text(self):
        m = self.load('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
                      '<text x="10" y="50" font-size="10">PART <tspan>42</tspan></text></svg>')
        self.assertEqual(m.texts[0]["lines"], ["PART 42"])
        self.assertAlmostEqual(m.texts[0]["height"], 7.0)

    def test_not_svg(self):
        with self.assertRaises(ValueError):
            self.load("<html></html>")


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(self.dir / "cache")  # unpacked copies go here, not in the real cache

    def tearDown(self):
        if self._old is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._old
        self.tmp.cleanup()

    def zip(self, name, files):
        p = self.dir / name
        with zipfile.ZipFile(p, "w") as z:
            for n, data in files.items():
                z.writestr(n, data)
        return p

    def test_one_file_opens_it(self):
        z = self.zip("one.zip", {"op1.nc": "G0 X0", "notes.txt": "hi"})
        path, name = archive.resolve(str(z))
        self.assertEqual(name, "op1.nc")
        self.assertEqual(Path(path).read_text(), "G0 X0")

    def test_several_files_ask(self):
        z = self.zip("job.zip", {"a/one.step": "x", "b/two.dxf": "y", "../evil.step": "z"})
        with self.assertRaises(archive.ChooseInArchive):
            archive.resolve(str(z))
        top = archive.listing(str(z))
        self.assertEqual([d["name"] for d in top["dirs"]], ["a", "b"])  # the ../ name isn't shown
        inner = archive.listing(*archive.split(str(z / "a")))
        self.assertEqual([f["name"] for f in inner["files"]], ["one.step"])
        path, name = archive.resolve(inner["files"][0]["path"])
        self.assertEqual(name, "one.step")
        self.assertFalse((self.dir / "cache" / "evil.step").exists())
        self.assertFalse(any(p.name == "evil.step" for p in self.dir.rglob("*")))

    def test_nothing_to_open(self):
        z = self.zip("empty.zip", {"notes.txt": "hi"})
        with self.assertRaises(ValueError) as e:
            archive.resolve(str(z))
        self.assertNotIsInstance(e.exception, archive.ChooseInArchive)


if __name__ == "__main__":
    unittest.main()
