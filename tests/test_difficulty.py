"""A print's part difficulty with no window (solidsmufs/difficulty.py): the answer's shape, and errors as JSON."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pymupdf  # noqa: E402

from solidsmufs import difficulty  # noqa: E402
from solidsmufs.kernel import printmarks  # noqa: E402


class Difficulty(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ss-diff-"))
        self.path = self.dir / "print.pdf"
        d = pymupdf.open()
        d.new_page().insert_text((72, 100), "DIMENSIONS ARE IN INCHES", fontsize=12)
        d.new_page().insert_text((72, 100), "Second sheet", fontsize=12)
        d.save(self.path)
        d.close()

    def test_a_print_with_no_callouts(self):
        before = printmarks.ocr_available
        r = difficulty.read(self.path, ocr=False)
        self.assertIs(printmarks.ocr_available, before)
        self.assertEqual({k: r[k] for k in ("format", "score", "count", "points", "units", "pages", "complete", "ocr", "callouts")},
                         {"format": 1, "score": None, "count": 0, "points": 0.0, "units": "in", "pages": 2,
                          "complete": True, "ocr": "off", "callouts": []})

    def test_the_command_writes_json(self):
        out = self.dir / "result.json"
        self.assertEqual(difficulty.main(["--difficulty", str(self.path), "--no-ocr", "--out", str(out)]), 0)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["pages"], 2)

    def test_errors_come_back_as_json(self):
        for argv, word in ((["--difficulty", str(self.dir / "none.pdf")], "no file"),
                           (["--difficulty", str(self.dir / "part.step")], "print"),
                           (["--difficulty"], "needs a value")):
            got = io.StringIO()
            with redirect_stdout(got):
                self.assertEqual(difficulty.main(argv), 2)
            self.assertIn(word, json.loads(got.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()
