"""Printing: the command line, page picking, and a real job printed to a PDF file (no paper)."""

import os
import tempfile
import unittest
from pathlib import Path

from solidsmufs import printing
from solidsmufs.printing import PrintError, parse_job, parse_pages, pick_pages


class CommandLine(unittest.TestCase):
    def test_acrobat_t(self):
        j = parse_job(["/t", r"C:\a b\print.pdf", r"\\extra\KONICA MINOLTA", "KONICA C368SeriesPCL", "IP_1"])
        self.assertEqual((j["mode"], j["printer"], j["files"]), ("named", r"\\extra\KONICA MINOLTA", [r"C:\a b\print.pdf"]))

    def test_acrobat_t_default(self):
        self.assertEqual(parse_job(["/T", "x.pdf"])["mode"], "default")

    def test_acrobat_p_h_is_silent(self):
        j = parse_job(["/p", "/h", "x.pdf"])
        self.assertEqual((j["mode"], j["files"]), ("default", ["x.pdf"]))

    def test_acrobat_p_asks(self):
        self.assertEqual(parse_job(["/p", "x.pdf"])["mode"], "dialog")

    def test_print_options(self):
        j = parse_job(["--print", "a.step", "b.pdf", "--printer", "HP", "--copies", "3", "--pages", "2-3"])
        self.assertEqual((j["mode"], j["printer"], j["copies"], j["files"]), ("named", "HP", 3, ["a.step", "b.pdf"]))
        self.assertEqual(j["pages"], [(2, 3)])

    def test_print_to_isnt_a_file_to_print(self):
        j = parse_job(["--print-to", "out.pdf", "in.pdf"])
        self.assertEqual((j["mode"], j["out"], j["files"]), ("pdf", "out.pdf", ["in.pdf"]))

    def test_acrobat_form_takes_the_other_options(self):
        j = parse_job(["/t", "x.pdf", "Some Printer", "--print-to", "out.pdf", "--pages", "2", "--copies", "2"])
        self.assertEqual((j["mode"], j["out"], j["pages"], j["copies"], j["files"]), ("pdf", "out.pdf", [(2, 2)], 2, ["x.pdf"]))

    def test_no_job(self):
        self.assertIsNone(parse_job(["part.step"]))

    def test_mistakes(self):
        for argv in (["--print"], ["/t"], ["--print", "a.pdf", "--copies", "two"], ["--print", "a.pdf", "--pages", "x"]):
            with self.assertRaises(PrintError, msg=argv):
                parse_job(argv)


class Pages(unittest.TestCase):
    def test_pick(self):
        self.assertEqual(pick_pages(parse_pages("1-4,9"), 10), [0, 1, 2, 3, 8])
        self.assertEqual(pick_pages(parse_pages("3,1,3"), 5), [2, 0])
        self.assertEqual(pick_pages(parse_pages("8-"), 10), [7, 8, 9])
        self.assertEqual(pick_pages(parse_pages("-2"), 10), [8, 9])
        self.assertEqual(pick_pages(parse_pages("1-4,-2"), 6), [0, 1, 2, 3, 4, 5])
        self.assertEqual(pick_pages(parse_pages("20"), 5), [])
        self.assertEqual(pick_pages(None, 3), [0, 1, 2])


def _qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _Doc:
    """Stands in for a document: pages from a real PDF, through the same tile call the worker answers."""

    def __init__(self, pdf):
        self.pdf = pdf

    def request(self, cmd, timeout=None, **kw):
        assert cmd == "pdf_tile"
        return self.pdf.tile(**kw)


class ToPdf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = _qt()
        cls.dir = Path(tempfile.mkdtemp(prefix="ss-print-"))
        # a two-page source: a landscape page with a black box, then a portrait one
        from PySide6.QtCore import QMarginsF, QRectF
        from PySide6.QtGui import QColor, QPageLayout, QPageSize, QPainter, QPdfWriter
        cls.src = cls.dir / "src.pdf"
        w = QPdfWriter(str(cls.src))
        w.setResolution(72)
        w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.Letter), QPageLayout.Orientation.Landscape, QMarginsF()))
        p = QPainter(w)
        p.fillRect(QRectF(36, 36, 720, 540), QColor("black"))
        w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.Letter), QPageLayout.Orientation.Portrait, QMarginsF()))
        w.newPage()
        p.fillRect(QRectF(36, 36, 100, 100), QColor("black"))
        p.end()

    def _read(self, path):
        from solidsmufs.kernel.pdfdoc import PdfFile
        return PdfFile(str(path))

    def test_pages_fit_and_turn(self):
        src = self._read(self.src)
        out = self.dir / "pages.pdf"
        printer = printing.make_printer(out=out, title="pages")
        from PySide6.QtGui import QPageLayout, QPageSize
        printer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.Letter), QPageLayout.Orientation.Portrait,
                                          printer.pageLayout().margins()))
        job = printing.Job(printer)
        job.add_pages(_Doc(src), src.pages())
        self.assertEqual(job.finish(), 2)
        got = self._read(out)
        self.assertEqual(len(got.pages()), 2)
        page = got.pages()[0]
        self.assertGreater(page["w"], page["h"])  # a landscape page on landscape paper
        self.assertLess(got.pages()[1]["w"], got.pages()[1]["h"])  # and the portrait one on portrait
        # the page fills the sheet: mostly black
        import numpy as np
        s = 0.5
        w, h = round(page["w"] * s), round(page["h"] * s)
        px = np.frombuffer(got.tile(0, s, 0, 0, w, h), np.uint8).reshape(h, w, 4)
        self.assertGreater((px[..., 0] < 60).mean(), 0.6)

    def test_turned_pages_keep_their_shape(self):
        """Rotate View's turned pages, whole or a tile at a time, are the page itself turned (not squashed)."""
        import numpy as np
        src = self._read(self.src)
        s = 0.25
        pg = src.pages()[0]
        W, H = round(pg["w"] * s), round(pg["h"] * s)
        flat = np.frombuffer(src.tile(0, s, 0, 0, W, H), np.uint8).reshape(H, W, 4)
        for turns in (1, 2, 3):
            want = np.rot90(flat, -turns)
            h, w = want.shape[:2]
            whole = np.frombuffer(src.tile(0, s, 0, 0, w, h, turns), np.uint8).reshape(h, w, 4)
            self.assertLess(np.abs(whole.astype(int) - want).mean(), 2, turns)
            x, y, tw, th = w // 3, h // 2, w - w // 3, h - h // 2  # a tile reaching the far corner
            tile = np.frombuffer(src.tile(0, s, x, y, tw, th, turns), np.uint8).reshape(th, tw, 4).astype(int)
            # QtPdf rounds a clipped piece's place to the pixel, unturned pieces too: allow a pixel either way
            off = min(np.abs(tile[2:-2, 2:-2] - want[y + dy + 2:y + dy + th - 2, x + dx + 2:x + dx + tw - 2]).mean()
                      for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            self.assertLess(off, 2, turns)

    def test_page_pick(self):
        src = self._read(self.src)
        out = self.dir / "one.pdf"
        job = printing.Job(printing.make_printer(out=out))
        job.add_pages(_Doc(src), src.pages(), pick_pages(parse_pages("2"), 2))
        self.assertEqual(job.finish(), 1)
        self.assertEqual(len(self._read(out).pages()), 1)

    def test_through_the_gui_bridge(self):
        """The window hands printer calls to its GUI thread through a bridge that swallows errors: they still come back."""
        calls = []

        def bridge(fn, *args):
            calls.append(fn)
            try:
                return fn(*args)
            except Exception:
                return None
        src = self._read(self.src)
        job = printing.Job(printing.make_printer(out=self.dir / "bridged.pdf"), bridge)
        job.add_pages(_Doc(src), src.pages())
        self.assertEqual(job.finish(), 2)
        self.assertGreaterEqual(len(calls), 5)  # two sheets, two drawings, the end
        bad = printing.Job(printing.make_printer(out=self.dir / "no-such-folder" / "x" / "out.pdf"), bridge)
        with self.assertRaises(PrintError):
            bad.add_pages(_Doc(src), src.pages())
        self.assertEqual(bad.finish(), 0)

    def test_no_such_pages(self):
        src = self._read(self.src)
        job = printing.Job(printing.make_printer(out=self.dir / "none.pdf"))
        with self.assertRaises(PrintError):
            job.add_pages(_Doc(src), src.pages(), [])
        self.assertEqual(job.finish(), 0)

    def test_picture_on_white(self):
        import base64
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PySide6.QtGui import QImage
        img = QImage(400, 200, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        white = printing.image_from_data_url("data:image/png;base64," + base64.b64encode(bytes(ba)).decode())
        self.assertEqual(white.pixelColor(10, 10).name(), "#ffffff")
        job = printing.Job(printing.make_printer(out=self.dir / "pic.pdf"))
        job.add_image(white)
        self.assertEqual(job.finish(), 1)

    def test_unknown_printer(self):
        with self.assertRaises(PrintError):
            printing.make_printer("no printer has this name 7f3a")

    def test_part_of_a_name_isnt_enough(self):
        """Never a printer nobody named: part of a real printer's name is refused (checked without printing)."""
        names = printing.printer_names()
        long = [n for n in names if len(n) > 6]
        if not long:
            self.skipTest("no printers here")
        with self.assertRaises(PrintError):
            printing.make_printer(long[0][:-3], copies=1)
        self.assertEqual(printing.make_printer(long[0].upper()).printerName(), long[0])  # any case, not printed


if __name__ == "__main__":
    unittest.main()
