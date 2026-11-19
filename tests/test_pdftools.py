"""The PDF tools' kernel side (kernel/pdfedit.py, kernel/pdfdoc.py), one test per thing that once went wrong: text
edited onto the wrong line, symbols turned to dots, marks on turned pages, stamps a third of the size, steps to undo
that undid nothing. All on PDFs made here."""

import base64
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pymupdf  # noqa: E402

from solidsmufs.kernel import pdfedit, roles  # noqa: E402
from solidsmufs.kernel.pdfdoc import PdfFile  # noqa: E402
from solidsmufs.kernel.pdfedit import PdfEditor  # noqa: E402

SYMBOLS = pdfedit._font("seguisym.ttf") is not None or pdfedit._font("DejaVuSans.ttf") is not None


def _png(w=120, h=40, rgb=(200, 30, 30)):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), 0)
    pix.set_rect(pix.irect, rgb)
    return "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode()


def _size(url):
    pix = pymupdf.Pixmap(base64.b64decode(url.split(",", 1)[1]))
    return pix.width, pix.height


class Tools(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ss-tools-"))
        self.open = []

    def tearDown(self):
        for pdf in self.open:
            pdf.close()

    def make(self, build=None, name="doc.pdf", pages=1):
        """An editor on a new PDF: `build(doc)` puts in what the test needs (after `pages` blank Letter pages)."""
        d = pymupdf.open()
        for _ in range(pages):
            d.new_page(width=612, height=792)
        if build:
            build(d)
        path = self.dir / name
        d.save(path)
        d.close()
        pdf = PdfFile(str(path))
        self.open.append(pdf)
        return PdfEditor(pdf, path)

    @staticmethod
    def notes(d):
        """Three lines of a note, set solid as notes are: each line's box reaches into the next one's."""
        for k, words in enumerate(("FIRST LINE", "SECOND LINE", "THIRD LINE")):
            d[0].insert_text((72, 100 + 12 * k), words, fontsize=12)

    @staticmethod
    def lines(pg):
        """{its words: (where its baseline starts, which way it runs, its first run)} for each line of a page."""
        out = {}
        for b in pg.get_text("dict", flags=0)["blocks"]:
            for ln in b.get("lines", []):
                s = ln["spans"][0]
                out["".join(x["text"] for x in ln["spans"]).strip()] = ([round(v, 1) for v in s["origin"]], [round(v, 2) for v in ln["dir"]], s)
        return out

    def annot(self, e, page, id):
        pg = e.fz[page]
        self._pg = pg  # (an annotation lives only as long as its page is held)
        return next(a for a in pg.annots() if a.xref == id)

    # ------------------------------------------------------------------ the pages' own text
    def test_edited_text_stays_on_its_own_line(self):
        for back in (True, False):  # with what text_at said sent back, and from the box alone
            e = self.make(self.notes, f"lines{back}.pdf")
            line = e.run("text_at", {"page": 0, "at": [80, 110]})
            self.assertEqual((line["text"], line["origin"]), ("SECOND LINE", [72, 112]))
            more = {"origin": line["origin"], "dir": line["dir"]} if back else {}
            e.run("text_replace", {"page": 0, "rect": line["rect"], "text": "CHANGED", "size": 12, **more})
            got = self.lines(e.fz[0])
            self.assertEqual({k: v[0] for k, v in got.items()},
                             {"FIRST LINE": [72, 100], "CHANGED": [72, 112], "THIRD LINE": [72, 124]}, back)

    def test_a_click_between_two_lines_takes_the_nearer(self):
        e = self.make(self.notes)
        # (y 105 is inside the first line's box and the second's: nearer the first's middle; 109 nearer the second's)
        self.assertEqual(e.run("text_at", {"page": 0, "at": [80, 102]})["text"], "FIRST LINE")
        self.assertEqual(e.run("text_at", {"page": 0, "at": [80, 109]})["text"], "SECOND LINE")

    @unittest.skipUnless(SYMBOLS, "no font with drawing symbols on this machine")
    def test_symbols_outside_latin_1_are_kept(self):
        e = self.make(lambda d: d[0].insert_text((72, 300), "DIA 5.0 HERE", fontsize=12))
        said = "\u2300 5.0 \u00b10.1 \u2264 \u03a9 45\u00b0 \u00d8 \u2014 \u201cq\u201d \u2022"
        r = e.run("text_add", {"page": 0, "at": [72, 200], "text": said, "size": 12})["result"]
        self.assertEqual(r["at"], [72, 200])
        text = e.fz[0].get_text()
        for c in said.replace(" ", ""):
            self.assertIn(c, text, f"U+{ord(c):04X}")
        self.assertNotIn("\u00b7", text)  # (what a standard font draws for what it lacks)
        line = e.run("text_at", {"page": 0, "at": [80, 296]})
        e.run("text_replace", {"page": 0, "rect": line["rect"], "origin": line["origin"], "dir": line["dir"],
                               "text": "\u2300 5.0 HERE", "size": 12})
        got = self.lines(e.fz[0])
        self.assertIn("\u2300 5.0 HERE", got)
        self.assertEqual(got["\u2300 5.0 HERE"][0], [72, 300])
        # all on one baseline, the standard font's run following the symbol's
        spans = [s for b in e.fz[0].get_text("dict", flags=0)["blocks"] for ln in b["lines"] for s in ln["spans"] if abs(s["origin"][1] - 300) < 0.1]
        self.assertGreater(len(spans), 0)
        self.assertEqual(sorted(round(s["origin"][1], 1) for s in spans), [300.0] * len(spans))
        # one no font has: said, nothing written, no step to undo
        steps = e.state()["undoSteps"]
        with self.assertRaisesRegex(ValueError, "U\\+F0000"):
            e.run("text_add", {"page": 0, "at": [72, 400], "text": "bad \U000f0000 one", "size": 12})
        self.assertEqual(e.state()["undoSteps"], steps)

    @unittest.skipUnless(SYMBOLS, "no font with drawing symbols on this machine")
    def test_symbols_on_a_turned_page_read_across_it(self):
        def build(d):
            d[0].set_rotation(90)
        e = self.make(build)
        e.run("text_add", {"page": 0, "at": [100, 200], "text": "PLAIN", "size": 12})
        e.run("text_add", {"page": 0, "at": [100, 300], "text": "\u2300 12", "size": 12})
        got = self.lines(e.fz[0])
        self.assertEqual(got["\u2300 12"][1], got["PLAIN"][1])
        shown = pymupdf.Point(got["\u2300 12"][0]) * e.fz[0].rotation_matrix
        self.assertEqual([round(shown.x), round(shown.y)], [100, 300])

    def test_text_on_a_slant_keeps_its_angle(self):
        def build(d):
            at = pymupdf.Point(200, 400)
            d[0].insert_text(at, "12.50 REF", fontsize=12, morph=(at, pymupdf.Matrix(30)))
            d[0].insert_text((72, 100), "level words stay", fontsize=12)
        e = self.make(build)
        line = e.run("text_at", {"page": 0, "at": [215, 390]})
        self.assertEqual(line["text"], "12.50 REF")
        e.run("text_replace", {"page": 0, "rect": line["rect"], "origin": line["origin"], "dir": line["dir"],
                               "text": "13.75 REF", "size": 12})
        got = self.lines(e.fz[0])
        self.assertNotIn("12.50 REF", got)
        self.assertEqual(got["13.75 REF"][:2], ([200, 400], [0.87, -0.5]))
        self.assertIn("level words stay", got)

    def test_one_run_of_a_line_edited_leaves_the_others_look(self):
        def build(d):
            d[0].insert_text((72, 200), "NOTE: ", fontsize=12, fontname="hebo", color=(1, 0, 0))
            w = pymupdf.get_text_length("NOTE: ", "hebo", 12)
            d[0].insert_text((72 + w, 200), "break all edges", fontsize=12, fontname="tiro")
        e = self.make(build)
        line = e.run("text_at", {"page": 0, "at": [150, 197]})
        self.assertTrue(line["mixed"])
        self.assertEqual([(s["text"].strip(), s["bold"], s["serif"], s["color"]) for s in line["spans"]],
                         [("NOTE:", True, False, "#ff0000"), ("break all edges", False, True, "#000000")])
        s = line["spans"][line["span"]]
        self.assertEqual(s["text"], "break all edges")
        e.run("text_replace", {"page": 0, "rect": s["rect"], "origin": s["origin"], "dir": line["dir"], "text": "deburr all edges",
                               **{k: s[k] for k in ("size", "color", "bold", "italic", "serif", "mono")}})
        spans = {x["text"].strip(): x for b in e.fz[0].get_text("dict", flags=0)["blocks"] for ln in b["lines"] for x in ln["spans"]}
        self.assertEqual((spans["NOTE:"]["font"], spans["NOTE:"]["color"]), ("Helvetica-Bold", 0xff0000))
        self.assertEqual((spans["deburr all edges"]["font"], [round(v, 2) for v in spans["deburr all edges"]["origin"]]), ("Times-Roman", s["origin"]))
        self.assertNotIn("break all edges", spans)

    def test_text_added_stays_on_the_page(self):
        e = self.make()
        r = e.run("text_add", {"page": 0, "at": [590, 300], "text": "a line too long for there", "size": 12})["result"]
        self.assertLessEqual(r["rect"][0] + r["rect"][2], 612)
        box = pymupdf.Rect(e.fz[0].get_text("dict")["blocks"][0]["bbox"])
        self.assertLessEqual(box.x1, 612)
        with self.assertRaisesRegex(ValueError, "off the page"):
            e.run("text_add", {"page": 0, "at": [700, 900], "text": "nowhere"})
        self.assertEqual(e.state()["undoSteps"], 1)

    # ------------------------------------------------------------------ marks on words
    def test_marks_on_a_turned_page_run_along_the_words(self):
        def build(d):
            d[0].insert_text((72, 100), "Hxxxx quick brown fox", fontsize=14)
            d[0].set_rotation(90)
        e = self.make(build)
        sel = e.pdf.select(0, 700, 80, 700, 200)  # (as shown the line runs down the sheet, near its right edge)
        self.assertIn("quick", sel["text"])
        (x, y, w, h), quad = sel["rects"][0], sel["quads"][0]
        self.assertGreater(h, 3 * w)
        # reading down the sheet: its top is the right side, its baseline the left
        self.assertTrue(quad[1][1] - quad[0][1] > 50 and abs(quad[1][0] - quad[0][0]) < 0.1 and quad[2][0] < quad[0][0])
        for how in ("rects", "quads"):
            a = e.run("annot_add", {"page": 0, "kind": "underline", how: sel[how], "quote": sel["text"]})["result"]
            self.assertEqual([[round(v) for v in p] for p in a["quads"][0]], [[round(v) for v in p] for p in quad], how)
            e.run("annot_delete", {"page": 0, "ids": [a["id"]]})
        a = e.run("annot_add", {"page": 0, "kind": "underline", "rects": sel["rects"]})["result"]
        ap = e.fz.xref_stream(int(e.fz.xref_get_key(a["id"], "AP/N")[1].split()[0])).decode()
        w, x0, y0, x1, y1 = [float(v) for v in re.search(r"([\d.]+) w\s+([\d.]+) ([\d.]+) m\s+([\d.]+) ([\d.]+) l", ap).groups()]
        self.assertLess(w, 2)  # a thin line under the words, their whole length: not a fat bar across one letter
        self.assertGreater(abs(x1 - x0) + abs(y1 - y0), 50)

    def test_marks_on_words_that_read_up_the_page(self):
        e = self.make(lambda d: d[0].insert_text((300, 500), "12.50 TYP", fontsize=12, rotate=90))
        sel = e.pdf.select(0, 297, 495, 297, 460)
        q = sel["quads"][0]
        self.assertTrue(q[1][1] < q[0][1] - 20 and q[2][0] > q[0][0])  # reads upward: the baseline is its right side
        a = e.run("annot_add", {"page": 0, "kind": "strikeout", "rects": sel["rects"]})["result"]
        (p, q2, half), = a["segs"]
        self.assertTrue(abs(p[0] - q2[0]) < 0.1 and abs(p[1] - q2[1]) > 20)  # the line runs up through the words

    def test_strike_shows_on_a_page_cropped_and_turned(self):
        def build(d):
            d[0].insert_text((72, 700), "Hxxxx struck", fontsize=12)
            d[0].set_cropbox(pymupdf.Rect(50, 60, 500, 760))
        for turn in (0, 90, 180, 270):
            e = self.make(lambda d: (build(d), d[0].set_rotation(turn)), f"crop{turn}.pdf")
            pg = e.fz[0]
            word = pymupdf.Rect(pg.get_text("words")[0][:4])
            a = e.run("annot_add", {"page": 0, "kind": "strike", "rects": [PdfEditor._out(pg, word)], "opacity": 0.3})["result"]
            form = int(e.fz.xref_get_key(a["id"], "AP/N")[1].split()[0])
            box = [float(v) for v in e.fz.xref_get_key(form, "BBox")[1].strip("[]").split()]
            ap = e.fz.xref_stream(form).decode()
            x0, y0, x1, y1 = [float(v) for v in re.search(r"w ([\d.-]+) ([\d.-]+) m ([\d.-]+) ([\d.-]+) l S", ap).groups()]
            for x, y in ((x0, y0), (x1, y1)):
                self.assertTrue(box[0] - 1 <= x <= box[2] + 1 and box[1] - 1 <= y <= box[3] + 1, (turn, ap, box))
            self.assertIn("/H gs", ap)  # and as faint as it says it is
            self.assertIn(".3", e.fz.xref_get_key(form, "Resources/ExtGState/H")[1])

    def test_a_mark_knows_its_lines_and_stays_on_them(self):
        def build(d):
            for k, words in enumerate(("Alpha beta gamma delta", "epsilon zeta eta theta", "iota kappa lambda mu")):
                d[0].insert_text((72, 100 + 20 * k), words, fontsize=12)
        e = self.make(build)
        sel = e.pdf.select(0, 180, 97, 100, 137)  # the end of line one to the start of line three
        self.assertEqual(len(sel["rects"]), 3)
        a = e.run("annot_add", {"page": 0, "kind": "highlight", "rects": sel["rects"], "quote": sel["text"]})["result"]
        self.assertEqual((len(a["parts"]), len(a["quads"]), a["quote"], a["contents"]), (3, 3, sel["text"], ""))
        self.assertEqual([[round(v) for v in p] for p in a["parts"]], [[round(v) for v in r] for r in sel["rects"]])
        # the unmarked start of line one is inside its "rect", and inside none of its parts
        inside = lambda r, x, y: r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3]  # noqa: E731
        self.assertTrue(inside(a["rect"], 80, 97) and not any(inside(r, 80, 97) for r in a["parts"]))
        # marking the same words again adds nothing
        steps = e.state()["undoSteps"]
        again = e.run("annot_add", {"page": 0, "kind": "highlight", "rects": sel["rects"], "quote": sel["text"]})
        self.assertEqual((again["result"]["id"], again["result"]["existing"], e.state()["undoSteps"]), (a["id"], True, steps))
        self.assertEqual(len(e.run("annots", {"page": 0})), 1)
        # and it can't be dragged off its words
        with self.assertRaisesRegex(ValueError, "stays on"):
            e.run("annot_set", {"page": 0, "id": a["id"], "rect": [200, 300, a["rect"][2], a["rect"][3]]})
        self.assertEqual(e.state()["undoSteps"], steps)
        # sent the old way (the words as "text"), they're its note as before
        old = e.run("annot_add", {"page": 0, "kind": "underline", "rects": sel["rects"][:1], "text": "gamma delta"})["result"]
        self.assertEqual((old["contents"], old["quote"]), ("gamma delta", "gamma delta"))

    def test_selecting_past_the_last_line_keeps_the_selection(self):
        def build(d):
            for k, words in enumerate(("Alpha beta gamma delta", "epsilon zeta eta theta")):
                d[0].insert_text((72, 100 + 20 * k), words, fontsize=12)
        e = self.make(build)
        sel = e.pdf.select(0, 80, 97, 130, 400)  # dragged down into the white under the note: to the word above there
        self.assertEqual(sel["text"], "Alpha beta gamma delta\nepsilon zeta")
        self.assertEqual(e.pdf.select(0, 80, 97, 130, 117)["text"], "Alpha beta gamma delta\nepsilon zeta")
        self.assertEqual(e.pdf.select(0, 80, 97, 600, 700)["text"], "Alpha beta gamma delta\nepsilon zeta eta theta")
        # a drag that starts on blank paper far from the words takes none of them
        self.assertEqual(e.pdf.select(0, 450, 97, 455, 99), {"text": "", "rects": [], "quads": []})
        self.assertEqual(e.pdf.select(0, 300, 500, 305, 502)["rects"], [])
        self.assertEqual(e.pdf.select(0, 200, 97, 204, 99)["text"], "delta")  # just past a line's end is its end

    # ------------------------------------------------------------------ stamps and signatures
    def test_stamps_on_a_turned_page_are_the_size_asked(self):
        for turn in (90, 270):
            e = self.make(lambda d: d[0].set_rotation(turn), f"stamp{turn}.pdf")
            for how in ({"stamp": "Approved"}, {"image": _png(120, 40)}):
                a = e.run("annot_add", {"page": 0, "kind": "stamp", "rect": [150, 450, 120, 40], **how})["result"]
                near = lambda got, want: all(abs(g - w) <= 1.5 for g, w in zip(got, want))  # noqa: E731
                if "image" in how:
                    self.assertTrue(near(a["rect"], [150, 450, 120, 40]), (turn, a["rect"]))
                else:  # (a standard stamp keeps its own shape inside the box)
                    self.assertTrue(a["rect"][2] > 100 and a["rect"][3] > 20 and a["rect"][0] >= 149 and a["rect"][1] >= 449, (turn, a["rect"]))
                size = a["rect"][2:]
                moved = e.run("annot_set", {"page": 0, "id": a["id"], "rect": [300, 100, *size]})["result"]
                self.assertTrue(near(moved["rect"], [300, 100, *size]), (turn, moved["rect"]))
                for opacity in (0.9, 0.8):  # (anything else changed after: it once jumped and turned on its side)
                    again = e.run("annot_set", {"page": 0, "id": a["id"], "opacity": opacity})["result"]
                    self.assertTrue(near(again["rect"], [300, 100, *size]), (turn, again["rect"]))
                # the picture carried while it's dragged is the way the page is shown: wide, not on its side
                w, h = _size(e.run("annot_image", {"page": 0, "id": a["id"]}))
                self.assertGreater(w, 2 * h)

    def test_a_picture_stamp_is_upright_on_a_turned_page(self):
        # a picture red on its left half, blue on its right: as shown it must still be red left, blue right
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 40), 0)
        pix.set_rect(pymupdf.IRect(0, 0, 60, 40), (255, 0, 0))
        pix.set_rect(pymupdf.IRect(60, 0, 120, 40), (0, 0, 255))
        url = "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode()
        for turn in (0, 90, 180, 270):
            e = self.make(lambda d: d[0].set_rotation(turn), f"up{turn}.pdf")
            e.run("annot_add", {"page": 0, "kind": "stamp", "rect": [200, 300, 120, 40], "image": url})
            shot = e.fz[0].get_pixmap()
            self.assertEqual((shot.pixel(215, 320), shot.pixel(305, 320)), ((255, 0, 0), (0, 0, 255)), turn)

    # ------------------------------------------------------------------ steps to undo
    def test_what_changes_nothing_is_no_step_to_undo(self):
        def build(d):
            d[0].insert_text((72, 100), "some words", fontsize=12)
        e = self.make(build, pages=2)
        note = e.run("annot_add", {"page": 0, "kind": "note", "at": [300, 300], "contents": "kept"})["result"]
        e.run("save", {})
        fails = [("annot_add", {"page": 0, "kind": "highlight", "rects": []}),
                 ("annot_add", {"page": 9, "kind": "rect", "rect": [10, 10, 50, 50]}),
                 ("annot_add", {"page": 0, "kind": "rect", "rect": [10, 10, 0, 0]}),
                 ("annot_add", {"page": 0, "kind": "polygon", "points": [[10, 10]]}),
                 ("annot_add", {"page": 0, "kind": "stamp", "rect": [10, 10, 90, 30], "image": "data:image/png;base64,AAAA"}),
                 ("annot_add", {"page": 0, "kind": "redact", "rects": []}),
                 ("annot_add", {"page": 0, "kind": "rect", "rect": [10, 10, 50, 50], "color": "red"}),
                 ("annot_add", {"page": 0, "kind": "line", "points": [[10, 10], [10, 10]]}),
                 ("annot_add", {"page": 0, "kind": "nonsense"}),
                 ("annot_set", {"page": 0, "id": 99999, "color": "#00ff00"}),
                 ("annot_set", {"page": 0, "id": note["id"], "rect": [10, 10, 0, 0]}),
                 ("annot_reply", {"page": 0, "id": 99999, "contents": "x"}),
                 ("annot_paste", {"page": 0, "clip": None}),
                 ("image_delete", {"page": 0, "id": 99999}),
                 ("image_add", {"page": 0, "rect": [10, 10, 50, 50], "image": "data:image/png;base64,AAAA"}),
                 ("pages_rotate", {"pages": [17]}),
                 ("flatten", {"annots": "not", "fields": {"a": 1}, "more": 1})]
        for op, args in fails:
            with self.assertRaises(ValueError, msg=(op, args)) as c, mock.patch("traceback.print_exc"):
                e.run(op, args)
            said = str(c.exception)
            # words for a person, not a library's: none of these
            for raw in ("rect is", "bad ", "code=", "invalid literal", "local variable", "unexpected keyword", "xref"):
                self.assertNotIn(raw, said, (op, said))
            self.assertEqual(e.state()["dirty"], False, (op, args))
        quiet = [("annot_delete", {"page": 0, "ids": [99999]}),
                 ("annot_set", {"page": 0, "id": note["id"], "contents": "kept"}),
                 ("annot_set", {"page": 0, "id": note["id"]}),
                 ("annot_set_many", {"items": [{"page": 0, "id": note["id"], "contents": "kept"}]}),
                 ("text_add", {"page": 0, "at": [100, 100], "text": "  "}),
                 ("text_replace", {"page": 0, "rect": [300, 600, 50, 12], "text": ""})]
        for op, args in quiet:
            e.run(op, args)
            self.assertEqual((e.state()["dirty"], e.state()["undoSteps"]), (False, 1), (op, args))
        self.assertEqual([a["contents"] for a in e.run("annots", {})], ["kept"])

    def test_an_edit_that_fails_part_way_leaves_the_document_and_redo_as_they_were(self):
        e = self.make()
        a = e.run("annot_add", {"page": 0, "kind": "rect", "rect": [100, 100, 50, 50]})["result"]
        e.run("annot_add", {"page": 0, "kind": "rect", "rect": [200, 100, 50, 50]})
        e.run("undo", {})
        before = (e.state()["undoSteps"], e.state()["redoSteps"], e.gen, e.next_gen)

        def broken(pg, a, o):  # (it changes the document, and then fails)
            pg.delete_annot(a)
            raise RuntimeError("code=7: something inside")
        with mock.patch.object(e, "_annot_set", broken), mock.patch("traceback.print_exc"):
            with self.assertRaisesRegex(ValueError, "couldn't be done"):
                e.run("annot_set", {"page": 0, "id": a["id"], "color": "#00ff00"})
        self.assertEqual((e.state()["undoSteps"], e.state()["redoSteps"], e.gen, e.next_gen), before)
        self.assertEqual([x["id"] for x in e.run("annots", {})], [a["id"]])
        e.run("redo", {})
        self.assertEqual(len(e.run("annots", {})), 2)

    def test_undo_draws_again_in_place_unless_the_pages_changed(self):
        e = self.make(pages=3)
        e.run("annot_add", {"page": 0, "kind": "rect", "rect": [100, 100, 50, 50]})
        r = e.run("undo", {})
        self.assertEqual((r["structure"], r["text"], r["changed"]), (False, True, None))
        self.assertFalse(e.run("redo", {})["structure"])
        for op, args in (("pages_delete", {"pages": [2]}), ("pages_rotate", {"pages": [0]}), ("pages_order", {"order": [1, 0, 2]})):
            e.run(op, args)
            self.assertTrue(e.run("undo", {})["structure"], op)
            self.assertTrue(e.run("redo", {})["structure"], op)
            e.run("undo", {})

    def test_undo_goes_deep_on_a_large_file(self):
        e = self.make()
        with mock.patch.object(pdfedit, "UNDO_BYTES", 2000):  # (every snapshot here is bigger: all but the newest wait in files)
            for k in range(12):
                e.run("annot_add", {"page": 0, "kind": "rect", "rect": [20 + 40 * k, 100, 30, 30]})
            kept = [d for d, _ in e.undo if not isinstance(d, bytes)]
            self.assertEqual((len(e.undo), len(kept)), (12, 11))
            self.assertTrue(all(os.path.exists(d.path) for d in kept))
            folder = e._spill
            del kept
            for k in range(12):
                e.run("undo", {})
            self.assertEqual((len(e.run("annots", {})), e.state()["undoTrimmed"]), (0, False))
            for k in range(12):
                e.run("redo", {})
            self.assertEqual(len(e.run("annots", {})), 12)
            # a step that's gone takes its file with it
            e.run("undo", {})
            e.run("annot_add", {"page": 0, "kind": "rect", "rect": [20, 300, 30, 30]})
            self.assertEqual(len(os.listdir(folder)), sum(1 for d, _ in e.undo + e.redo if not isinstance(d, bytes)))
            # past what the files may hold the oldest steps go, and the window is told
            with mock.patch.object(pdfedit, "UNDO_DISK", 3000):
                e.run("annot_add", {"page": 0, "kind": "rect", "rect": [20, 400, 30, 30]})
            self.assertTrue(e.state()["undoTrimmed"])
            self.assertLess(e.state()["undoSteps"], 5)
            while e.state()["undo"]:
                e.run("undo", {})
            with self.assertRaisesRegex(ValueError, "as far back"):
                e.run("undo", {})

    def test_undo_past_a_release_is_a_leads(self):
        def build(d):
            d[0].insert_text((100, 200), "12.50 \u00b10.05", fontsize=12)
        e = self.make(build)
        e.run("balloon_add", {"page": 0, "rect": [95, 188, 80, 16]})
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"APPDATA": home, "SOLIDSMUFS_APP": "1"}):
            roles.set_password("lead", "1234")
            roles.unlock("1234")
            e.run("balloon_status", {"status": "released"})
            roles.lock()
            steps = e.state()["undoSteps"]
            with self.assertRaisesRegex(ValueError, "lead"):
                e.run("undo", {})  # (once this put a released list back to draft for anyone)
            self.assertEqual((e._list_status(), e.state()["undoSteps"], e.state()["redo"]), ("released", steps, False))
            self.assertEqual(e.run("balloons", {})["status"], "released")
            roles.unlock("1234")
            e.run("undo", {})
            self.assertEqual(e._list_status(), "draft")
            roles.lock()
            with self.assertRaisesRegex(ValueError, "lead"):
                e.run("redo", {})
            self.assertEqual(e._list_status(), "draft")
        e.run("redo", {})  # (with no roles in use, anyone)
        self.assertEqual(e._list_status(), "released")

    # ------------------------------------------------------------------ comments
    def test_new_comments_are_dated_and_print(self):
        e = self.make()
        made = [e.run("annot_add", {"page": 0, "kind": "rect", "rect": [100, 100, 50, 50]})["result"],
                e.run("annot_add", {"page": 0, "kind": "note", "at": [300, 300], "contents": "n"})["result"]]
        made.append(e.run("annot_reply", {"page": 0, "id": made[1]["id"], "contents": "r"})["result"])
        made.append(e.run("annot_clone", {"page": 0, "id": made[0]["id"]})["result"])
        for a in made:
            self.assertRegex(a["date"], r"^D:\d{14}[+-]\d\d'\d\d'$")
            self.assertEqual(e.fz.xref_get_key(a["id"], "CreationDate")[0], "string")
        self.assertTrue(made[0]["print"])
        off = e.run("annot_set", {"page": 0, "id": made[0]["id"], "print": False})["result"]
        self.assertEqual((off["print"], self.annot(e, 0, off["id"]).flags & 4), (False, 0))
        self.assertTrue(e.run("annot_set", {"page": 0, "id": made[0]["id"], "print": True})["result"]["print"])
        red = e.run("annot_add", {"page": 0, "kind": "redact", "rects": [[100, 300, 50, 12]]})["result"]
        self.assertEqual(e.fz.xref_get_key(red["id"], "M")[0], "string")

    def test_a_text_boxs_background_is_its_fill(self):
        e = self.make()
        box = e.run("annot_add", {"page": 0, "kind": "text", "rect": [100, 100, 150, 40], "text": "words", "fill": "#ffff00", "align": 1})["result"]
        self.assertEqual((box["fill"], box["align"], box["subject"], box["fitted"]), ("#ffff00", 1, "Text Box", False))
        copy = e.run("annot_clone", {"page": 0, "id": box["id"]})["result"]
        self.assertEqual((copy["fill"], copy["align"], copy["contents"], copy["subject"]), ("#ffff00", 1, "words", "Text Box"))
        self.assertEqual(e.run("annot_set", {"page": 0, "id": box["id"], "textColor": "#ff0000"})["result"]["fill"], "#ffff00")
        self.assertEqual(e.run("annot_set", {"page": 0, "id": box["id"], "fill": "#00ff00"})["result"]["fill"], "#00ff00")
        self.assertIsNone(e.run("annot_set", {"page": 0, "id": box["id"], "fill": None})["result"]["fill"])
        shape = e.run("annot_add", {"page": 0, "kind": "rect", "rect": [100, 300, 80, 40], "fill": "#00ff00"})["result"]
        self.assertEqual(shape["fill"], "#00ff00")
        cleared = e.run("annot_set", {"page": 0, "id": shape["id"], "fill": None})["result"]
        self.assertEqual((cleared["fill"], cleared["color"]), (None, shape["color"]))
        note = e.run("annot_add", {"page": 0, "kind": "note", "at": [300, 300], "contents": "n", "icon": "Help"})["result"]
        self.assertEqual(e.run("annot_clone", {"page": 0, "id": note["id"]})["result"]["icon"], "Help")

    def test_typed_text_is_always_the_size_of_its_words(self):
        e = self.make()
        t = e.run("annot_add", {"page": 0, "kind": "text", "rect": [72, 400, 0, 0], "fit": True, "text": "abc", "fontsize": 12,
                                "subject": "Typewriter"})["result"]
        self.assertTrue(t["fitted"] and t["rect"][2] < 40)
        long = e.run("annot_set", {"page": 0, "id": t["id"], "text": "a much longer line of typed words than before"})["result"]
        self.assertTrue(long["rect"][2] > 200 and long["rect"][3] < 24, long["rect"])  # wider, still one row
        big = e.run("annot_set", {"page": 0, "id": t["id"], "fontsize": 24})["result"]
        self.assertTrue(big["rect"][2] > 400 and 30 < big["rect"][3] < 40, big["rect"])
        small = e.run("annot_set", {"page": 0, "id": t["id"], "fontsize": 8})["result"]
        self.assertTrue(small["rect"][2] < 200 and small["rect"][3] < 16, small["rect"])
        # emptied, it goes (it would be there and invisible); a note's words can be cleared
        gone = e.run("annot_set", {"page": 0, "id": t["id"], "text": ""})["result"]
        self.assertTrue(gone["deleted"])
        self.assertEqual(e.run("annots", {}), [])
        e.run("undo", {})
        self.assertEqual(len(e.run("annots", {})), 1)
        note = e.run("annot_add", {"page": 0, "kind": "note", "at": [300, 300], "contents": "say"})["result"]
        self.assertEqual(e.run("annot_set", {"page": 0, "id": note["id"], "contents": ""})["result"]["contents"], "")
        # a text box keeps the width it was given, and is never dragged narrower than its longest word
        box = e.run("annot_add", {"page": 0, "kind": "text", "rect": [100, 200, 200, 30], "text": "Hello there\nthree four", "fontsize": 18,
                                  "fill": "#ffffff"})["result"]
        thin = e.run("annot_set", {"page": 0, "id": box["id"], "rect": [100, 200, 2, 30]})["result"]
        self.assertTrue(40 < thin["rect"][2] < 80 and thin["rect"][3] < 200, thin["rect"])

    def test_comments_stay_on_the_page(self):
        e = self.make(pages=2)
        W, H = 612, 792
        on = lambda r: r[0] >= -0.5 and r[1] >= -0.5 and r[0] + r[2] <= W + 0.5 and r[1] + r[3] <= H + 0.5  # noqa: E731
        typed = e.run("annot_add", {"page": 0, "kind": "text", "rect": [590, 780, 0, 0], "fit": True, "fontsize": 12,
                                    "text": "typed right at the corner", "subject": "Typewriter"})["result"]
        self.assertTrue(on(typed["rect"]), typed["rect"])
        shape = e.run("annot_add", {"page": 0, "kind": "rect", "rect": [560, 740, 50, 50]})["result"]
        copy = e.run("annot_clone", {"page": 0, "id": shape["id"], "dy": 100})["result"]
        self.assertTrue(on(copy["rect"]) and round(copy["rect"][2]) == 50, copy["rect"])
        self.assertTrue(on(e.run("annot_add", {"page": 0, "kind": "note", "at": [700, 900], "contents": "n"})["result"]["rect"]))
        moved = e.run("annot_set", {"page": 0, "id": shape["id"], "rect": [-200, -200, 50, 50]})["result"]
        self.assertEqual([round(v) for v in moved["rect"]], [0, 0, 50, 50])
        dragged = e.run("annot_add", {"page": 0, "kind": "rect", "rect": [560, 700, 150, 200]})["result"]  # out past the corner: cut at it
        self.assertEqual([round(v) for v in dragged["rect"]], [560, 700, 52, 92])
        pen = e.run("annot_add", {"page": 0, "kind": "ink", "points": [[[500, 700], [807, 760], [650, 900]]]})["result"]
        self.assertTrue(all(0 <= x <= W and 0 <= y <= H for x, y in pen["points"][0]), pen["points"])
        placed = e.run("annot_add", {"page": 0, "kind": "stamp", "rect": [580, 770, 160, 52], "stamp": "Draft"})["result"]
        self.assertTrue(on(placed["rect"]), placed["rect"])

    def test_a_moved_pen_stroke_is_still_the_same_comment(self):
        e = self.make()
        made = {"ink": e.run("annot_add", {"page": 0, "kind": "ink", "points": [[[140, 90], [200, 140], [260, 90]]], "width": 8})["result"],
                "line": e.run("annot_add", {"page": 0, "kind": "arrow", "points": [[100, 300], [200, 340]]})["result"],
                "polygon": e.run("annot_add", {"page": 0, "kind": "polygon", "points": [[300, 300], [360, 300], [330, 350]], "fill": "#00ff00"})["result"],
                "strike": e.run("annot_add", {"page": 0, "kind": "strike", "free": True, "quads": [[[100, 500], [200, 500], [100, 510], [200, 510]]]})["result"]}
        reply = e.run("annot_reply", {"page": 0, "id": made["ink"]["id"], "contents": "r"})["result"]
        for kind, a in made.items():
            x, y, w, h = a["rect"]
            moved = e.run("annot_set", {"page": 0, "id": a["id"], "rect": [x + 30, y + 40, w, h]})["result"]
            self.assertEqual(moved["id"], a["id"], kind)
            self.assertEqual([round(v, 1) for v in moved["rect"]], [round(v, 1) for v in (x + 30, y + 40, w, h)], kind)
            self.assertEqual((moved["color"], moved["subject"], moved.get("arrow")), (a["color"], a["subject"], a.get("arrow")), kind)
        self.assertEqual(next(a for a in e.run("annots", {}) if a["id"] == reply["id"])["replyTo"], made["ink"]["id"])
        # stretched by its box, it lands on the box asked for (its border's room isn't stretched with it)
        for kind in ("ink", "polygon"):
            sized = e.run("annot_set", {"page": 0, "id": made[kind]["id"], "rect": [100, 600, 200, 100]})["result"]
            self.assertEqual([round(v) for v in sized["rect"]], [100, 600, 200, 100], kind)
        d = pymupdf.open(stream=e.fz.tobytes(), filetype="pdf")  # and it's written so: read again, it's the same
        self.assertEqual(sorted(round(a.rect.x0) for a in d[0].annots() if a.type[1] in ("Ink", "Polygon")), [100, 100])
        # a level line has no height to stretch
        flat = e.run("annot_add", {"page": 0, "kind": "line", "points": [[100, 700], [200, 700]]})["result"]
        x, y, w, h = flat["rect"]
        wide = e.run("annot_set", {"page": 0, "id": flat["id"], "rect": [x, y - 50, w + 100, h]})["result"]
        self.assertEqual([[round(v) for v in p] for p in wide["points"]], [[100, 650], [300, 650]])

    def test_a_tap_of_the_pen_is_a_dot(self):
        e = self.make()
        dot = e.run("annot_add", {"page": 0, "kind": "ink", "points": [[[100, 100]]], "width": 3})["result"]
        self.assertEqual(len(dot["points"][0]), 2)
        shot = e.fz[0].get_pixmap()
        self.assertLess(sum(shot.pixel(100, 100)), 600)  # (drawn: not white there)

    def test_a_copy_stands_by_itself(self):
        def build(d):
            d.new_page(width=300, height=200)
            d[0].insert_text((72, 100), "Alpha beta gamma", fontsize=12)
        e = self.make(build)
        made = [("rect", {"rect": [100, 400, 80, 40], "width": 3, "fill": "#00ff00"}), ("cloud", {"rect": [100, 460, 80, 40]}),
                ("arrow", {"points": [[100, 520], [200, 560]]}), ("ink", {"points": [[[100, 600], [150, 650]]]}),
                ("polyline", {"points": [[300, 600], [350, 650], [400, 600]]}),
                ("note", {"at": [400, 400], "contents": "n", "icon": "Help"}),
                ("text", {"rect": [300, 500, 120, 30], "text": "words", "fill": "#ffff00"}),
                ("highlight", {"rects": [[72, 88, 100, 16]], "quote": "Alpha beta"}),
                ("stamp", {"rect": [400, 680, 150, 50], "stamp": "Draft"}), ("stamp", {"rect": [400, 600, 120, 40], "image": _png()})]
        for kind, args in made:
            a = e.run("annot_add", {"page": 0, "kind": kind, **args})["result"]
            clip = e.run("annot_copy", {"page": 0, "id": a["id"]})["clip"]
            clip = json.loads(json.dumps(clip))  # (plain data: it goes to the window and comes back)
            e.run("annot_delete", {"page": 0, "ids": [a["id"]]})  # a cut: the original is gone
            b = e.run("annot_paste", {"page": 0, "clip": clip})["result"]
            self.assertEqual((b["page"], b["kind"], b["subject"], b["contents"], b["color"], b["fill"], b["clouds"]),
                             (0, a["kind"], a["subject"], a["contents"], a["color"], a["fill"], a["clouds"]), kind)
            self.assertTrue(all(abs(x - y) < 1.5 for x, y in zip(b["rect"], a["rect"])), (kind, a["rect"], b["rect"]))
            for key in ("arrow", "ends", "icon", "quote", "align", "fontsize"):
                self.assertEqual(b.get(key), a.get(key), (kind, key))
            # onto a smaller page: wholly on it, wherever it was
            c = e.run("annot_paste", {"page": 1, "clip": clip})["result"]
            self.assertTrue(c["page"] == 1 and c["rect"][0] >= -0.5 and c["rect"][1] >= -0.5
                            and c["rect"][0] + c["rect"][2] <= 300.5 and c["rect"][1] + c["rect"][3] <= 200.5, (kind, c["rect"]))
            # centered where asked
            at = e.run("annot_paste", {"page": 0, "clip": clip, "at": [300, 250]})["result"]
            self.assertTrue(abs(at["rect"][0] + at["rect"][2] / 2 - 300) < 2 and abs(at["rect"][1] + at["rect"][3] / 2 - 250) < 2, (kind, at["rect"]))
        # and into another document
        other = self.make(name="other.pdf")
        pasted = other.run("annot_paste", {"page": 0, "clip": clip, "dx": 12, "dy": 12})["result"]
        self.assertEqual((pasted["kind"], [round(v) for v in pasted["rect"]]), ("stamp", [412, 612, 120, 40]))

    def test_several_comments_changed_in_one_step(self):
        e = self.make(pages=2)
        a = e.run("annot_add", {"page": 0, "kind": "rect", "rect": [100, 100, 50, 50]})["result"]
        b = e.run("annot_add", {"page": 1, "kind": "ink", "points": [[[100, 100], [150, 150]]]})["result"]
        steps = e.state()["undoSteps"]
        r = e.run("annot_set_many", {"items": [{"page": 0, "id": a["id"], "rect": [130, 140, 50, 50], "color": "#0000ff"},
                                               {"page": 1, "id": b["id"], "rect": [b["rect"][0] + 30, b["rect"][1] + 40, *b["rect"][2:]]}]})
        self.assertEqual((r["changed"], e.state()["undoSteps"]), ([0, 1], steps + 1))
        self.assertEqual([(x["page"], x["id"], round(x["rect"][0])) for x in r["result"]], [(0, a["id"], 130), (1, b["id"], round(b["rect"][0] + 30))])
        e.run("undo", {})
        self.assertEqual([round(x["rect"][0]) for x in e.run("annots", {})], [100, round(b["rect"][0])])
        e.run("annot_delete_many", {"items": [{"page": 0, "ids": [a["id"]]}, {"page": 1, "ids": [b["id"]]}]})
        self.assertEqual((e.run("annots", {}), e.state()["undoSteps"]), ([], steps + 1))
        e.run("undo", {})
        self.assertEqual(len(e.run("annots", {})), 2)

    def test_which_comment_lies_over_which(self):
        e = self.make()
        red, green, blue = (e.run("annot_add", {"page": 0, "kind": "rect", "rect": [100 + 10 * k, 100 + 10 * k, 80, 80], "color": c,
                                                "fill": c})["result"]["id"] for k, c in enumerate(("#ff0000", "#00ff00", "#0000ff")))
        top = lambda: e.fz[0].get_pixmap().pixel(150, 150)  # noqa: E731  (a spot all three cover)
        self.assertEqual((top(), [a["id"] for a in e.run("annots", {})]), ((0, 0, 255), [red, green, blue]))
        steps = e.state()["undoSteps"]
        r = e.run("annot_order", {"page": 0, "ids": [red], "to": "front"})
        self.assertEqual((r["result"]["order"], r["changed"], top(), e.state()["undoSteps"]), ([green, blue, red], [0], (255, 0, 0), steps + 1))
        self.assertEqual([a["id"] for a in e.run("annots", {})], [green, blue, red])
        self.assertEqual(e.run("annot_order", {"page": 0, "ids": [red], "to": "backward"})["result"]["order"], [green, red, blue])
        self.assertEqual(e.run("annot_order", {"page": 0, "ids": [blue, red], "to": "back"})["result"]["order"], [red, blue, green])
        self.assertEqual(top(), (0, 255, 0))
        self.assertEqual(e.run("annot_order", {"page": 0, "ids": [red], "to": "forward"})["result"]["order"], [blue, red, green])
        steps = e.state()["undoSteps"]
        same = e.run("annot_order", {"page": 0, "ids": [green], "to": "front"})  # already there: no step to undo
        self.assertEqual((same["changed"], e.state()["undoSteps"]), ([], steps))
        with self.assertRaisesRegex(ValueError, "isn't there"):
            e.run("annot_order", {"page": 0, "ids": [99999]})
        self.assertEqual(e.state()["undoSteps"], steps)
        e.run("annot_set", {"page": 0, "id": red, "opacity": 0.5})  # (still the comments they were, to change after)
        e.run("undo", {})
        e.run("undo", {})
        self.assertEqual([a["id"] for a in e.run("annots", {})], [red, blue, green])

    # ------------------------------------------------------------------ flatten, find
    def test_flatten_waits_for_redactions(self):
        e = self.make(lambda d: d[0].insert_text((72, 140), "SECRET 555-1234 here", fontsize=12))
        e.run("annot_add", {"page": 0, "kind": "redact", "rects": [[72, 128, 110, 16]]})
        steps = e.state()["undoSteps"]
        with self.assertRaisesRegex(ValueError, "redaction"):
            e.run("flatten", {})
        self.assertEqual(e.state()["undoSteps"], steps)
        e.run("flatten", {"annots": False})  # (filled-in fields alone can be)
        e.run("redact_apply", {})
        self.assertNotIn("SECRET", e.fz[0].get_text())
        e.run("flatten", {})

    def test_find_on_a_page_with_a_user_unit(self):
        def build(d):
            d[0].insert_text((72, 100), "Hxxxx quick brown fox", fontsize=14)
            d.xref_set_key(d[0].xref, "UserUnit", "2")
        e = self.make(build)
        self.assertEqual(e.pdf.pages()[0]["w"], 1224)
        word = next(w for w in e.fz[0].get_text("words") if w[4] == "quick")
        (x, y, w, h), = e.pdf.find("quick")[0]["rects"]
        self.assertTrue(abs(x - word[0]) < 4 and abs(x + w - word[2]) < 4 and word[1] - 4 < y + h / 2 < word[3] + 4, ([x, y, w, h], word[:4]))


if __name__ == "__main__":
    unittest.main()
