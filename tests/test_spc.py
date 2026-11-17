"""SPC across lots (kernel/spc.py), and the lots kept by Ballooning (kernel/balloonops.py) and its report's Lots sheet."""

import os
import sys
import tempfile
import unittest
import zipfile

from solidsmufs.kernel import spc

sys.path.insert(0, os.path.dirname(__file__))
from test_balloons import _print  # noqa: E402

C = {"lo": 0.995, "hi": 1.005}


class Chart(unittest.TestCase):
    def test_xbar_r(self):
        groups = [{"name": "A", "values": ["1.000", "1.002", "0.999"]}, {"name": "B", "values": ["1.001", "1.003", "1.000"]},
                  {"name": "C", "values": ["0.998", "1.000", "1.001"]}]
        ch = spc.chart(C, groups)
        self.assertEqual((ch["kind"], ch["lots"], ch["n"]), ("xbar_r", 3, 9))
        ranges = [0.003, 0.003, 0.003]
        sigma = sum(r / 1.693 for r in ranges) / 3
        self.assertAlmostEqual(ch["sigma"], sigma, places=9)
        center = (3.001 + 3.004 + 2.999) / 9
        self.assertAlmostEqual(ch["center"], center, places=9)
        p = ch["points"][0]
        self.assertAlmostEqual(p["ucl"], center + 3 * sigma / 3 ** 0.5, places=9)
        self.assertAlmostEqual(p["rucl"], 1.693 * sigma + 3 * 0.888 * sigma, places=9)
        self.assertEqual(p["rlcl"], 0.0)
        self.assertAlmostEqual(ch["cp"], 0.010 / (6 * sigma), places=6)
        self.assertEqual(ch["signals"], 0)
        self.assertIsNotNone(ch["ppk"])

    def test_signals(self):
        steady = [{"name": f"L{i}", "values": ["1.000", "1.001"]} for i in range(6)]
        ch = spc.chart(C, steady + [{"name": "off", "values": ["1.004", "1.005"]}])
        self.assertIn("beyond", ch["points"][-1]["flags"])
        self.assertEqual(ch["signals"], 1)
        # a run: seven lots in a row above the mean
        low = [{"name": f"a{i}", "values": ["0.9990", "1.0000"]} for i in range(5)]
        high = [{"name": f"b{i}", "values": ["1.0005", "1.0010"]} for i in range(7)]
        ch = spc.chart(C, low + high)
        self.assertEqual([("run" in p["flags"]) for p in ch["points"]], [False] * 11 + [True])
        # a part out of its limits is said, but isn't a control signal
        ch = spc.chart(C, [{"name": "a", "values": ["1.000", "1.006"]}, {"name": "b", "values": ["1.000", "1.001"]}])
        self.assertIn("spec", ch["points"][0]["flags"])

    def test_one_a_lot_and_too_few(self):
        ch = spc.chart(C, [{"name": str(i), "values": [v]} for i, v in enumerate(["1.000", "1.002", "1.001", "0.999"])])
        self.assertEqual(ch["kind"], "i_mr")
        mr = (0.002 + 0.001 + 0.002) / 3
        self.assertAlmostEqual(ch["sigma"], mr / 1.128, places=9)
        self.assertIsNone(ch["points"][0]["rcl"])
        self.assertAlmostEqual(ch["points"][1]["rucl"], 3.267 * mr, places=9)
        self.assertIsNone(spc.chart(C, [{"name": "only", "values": ["1.0", "1.001"]}, {"name": "words", "values": ["Pass"]}]))


class Lots(unittest.TestCase):
    def setUp(self):
        from solidsmufs.kernel.pdfdoc import PdfFile
        from solidsmufs.kernel.pdfedit import PdfEditor
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "print.pdf")
        _print(self.path)
        self.pdf = PdfFile(self.path)
        self.ed = PdfEditor(self.pdf, self.path)
        res = self.ed.run("balloon_auto", {"extra": {"unit": "in", "pages": {}}, "want": {"ref": False, "plain": False}})["result"]
        self.c = res["chars"][0]  # 5.000 ±.005

    def tearDown(self):
        self.pdf.close()
        self.dir.cleanup()

    def lot(self, values, name=None, clear=True):
        for v in values:
            res = self.ed.run("balloon_part_add", {})["result"]
            self.ed.run("balloon_result", {"key": str(self.c["id"]), "part": res["samples"][-1]["id"], "value": v})
        if clear:
            return self.ed.run("balloon_results_clear", {"name": name})["result"]

    def test_lots_kept_charted_and_reported(self):
        self.lot(["5.001", "5.002", "4.999"], "Lot A")
        res = self.lot(["5.000", "5.003", "5.001"])
        self.assertEqual([x["name"] for x in res["lots"]], ["Lot A", "Lot 2"])
        self.assertEqual((res["samples"], res["results"]), ([], {}))
        self.lot(["4.998", "5.000"], clear=False)  # this lot, still being measured: the last point
        spc_ = self.ed.run("balloon_spc", {})
        self.assertEqual(spc_["key"], str(self.c["id"]))
        self.assertEqual([r["key"] for r in spc_["rows"]], [str(self.c["id"])])
        ch = spc_["chart"]
        self.assertEqual([p["name"] for p in ch["points"]], ["Lot A", "Lot 2", "This lot"])
        self.assertEqual([p["n"] for p in ch["points"]], [3, 3, 2])
        self.assertEqual(ch["kind"], "xbar_r")
        # the report's Lots sheet
        out = os.path.join(self.dir.name, "report.xlsx")
        self.ed.run("balloon_report", {"path": out, "layout": "list"})
        with zipfile.ZipFile(out) as z:
            book = z.read("xl/workbook.xml").decode("utf-8")
            self.assertIn('name="Lots"', book)
            shared = z.read("xl/sharedStrings.xml").decode("utf-8") if "xl/sharedStrings.xml" in z.namelist() else ""
            sheets = "".join(z.read(n).decode("utf-8") for n in z.namelist() if n.startswith("xl/worksheets/"))
            self.assertIn("Lot A", shared + sheets)
            self.assertIn("Each lot", shared + sheets)
        # renamed, undone, and deleted out of the history
        lot_a = res["lots"][0]["id"]
        res = self.ed.run("balloon_lot_edit", {"id": lot_a, "name": "Lot 4471"})["result"]
        self.assertEqual(res["lots"][0]["name"], "Lot 4471")
        res = self.ed.run("balloon_lot_delete", {"id": lot_a})["result"]
        self.assertEqual([x["name"] for x in res["lots"]], ["Lot 2"])
        self.ed.run("undo", {})
        self.assertEqual(len(self.ed.run("balloons", {})["lots"]), 2)

    def test_kept_in_the_saved_pdf(self):
        from solidsmufs.kernel.pdfdoc import PdfFile
        from solidsmufs.kernel.pdfedit import PdfEditor
        self.lot(["5.001", "5.002"], "First")
        out = os.path.join(self.dir.name, "saved.pdf")
        self.ed.run("save", {"path": out})
        pdf = PdfFile(out)
        try:
            self.assertEqual([x["name"] for x in PdfEditor(pdf, out).run("balloons", {})["lots"]], ["First"])
        finally:
            pdf.close()

    def test_auto_balloon_again_keeps_the_sheet(self):
        self.lot(["5.001", "5.002"], "First")
        self.ed.run("balloon_leaders", {"on": False})
        issue = self.ed.run("balloon_issue_add", {"title": "Chatter on the bore"})["result"]
        sid = issue["sid"]
        res = self.ed.run("balloon_auto", {"extra": {"unit": "in", "pages": {}}, "want": {"ref": False, "plain": False}})["result"]
        self.assertEqual([x["name"] for x in res["lots"]], ["First"])
        self.assertFalse(res["leaders"])
        self.assertEqual(res["sid"], sid)
        self.assertEqual([i["title"] for i in res["issues"]], ["Chatter on the bore"])

    def test_not_kept_when_asked_or_empty(self):
        self.ed.run("balloon_part_add", {})
        res = self.ed.run("balloon_results_clear", {})["result"]  # a part with nothing measured: no lot to keep
        self.assertEqual(res["lots"], [])
        res = self.lot(["5.001"], clear=False)
        res = self.ed.run("balloon_results_clear", {"keep": False})["result"]
        self.assertEqual(res["lots"], [])


if __name__ == "__main__":
    unittest.main()
