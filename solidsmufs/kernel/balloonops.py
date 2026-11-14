"""Balloons on a PDF print and the inspection list behind them: the PDF editor's part (PdfEditor's balloon_* edits).

What there is to inspect is read by kernel/balloons.py. Here it's kept in the PDF itself, two ways at once:
- the list (every characteristic's requirement, limits and balloon number) as JSON in a stream the document's
  catalog names (/SolidSmurfsInspection): no other program shows it, and it comes back when the file is opened again;
- each balloon as a real circle comment with its number drawn in it, so the saved print shows its balloons in any
  PDF reader, and prints with them.
Several characteristics of one callout share a number and are told apart by a sub-number: 2.1, 2.2, 2.3 ("n" and
"sub" in the list; a balloon alone under its number has no sub).
The parts inspected and what each measured are kept with the list too: "samples" ([{"id", "name"}], a part by
its serial number or what it's called) and "results" ({row: {sample id: result}}, a row being a characteristic's id,
or id.2 for the second place of a multiplied one; a result as balloons.result() keeps it).
Views ("views": [{"id", "name", "page", "rect": [x0, y0, x1, y1], "color": "#rrggbb", "start"}]) are boxes drawn
around the drawing's views, each held to its page by a hidden square comment (/NM ssv-<id>), so it goes where its
page goes as a balloon does: a balloon whose callout is in one is drawn in its color, and Renumber numbers view by
view, from its start number when it has one.
A characteristic that applies in several places ("count": 4 for 4X) may be multiplied ("mult"): it's still one entry
with one balloon, but the list and the report give it a row for each place, 3.1 to 3.4, to inspect each one. Detached,
its places become entries of their own, each with its balloon.
The comments are made again from the list after every change. A balloon whose comment is gone (its page was deleted,
or it was removed in another program) leaves the list; one whose page moved follows it.
Places in the list are in the page's own points (not turned); the window gets and gives them as the page is shown.
Each characteristic may carry inspection tags ("tags": some of TAGS, in that order): how it's inspected, for sorting
and finding, not printed.
The list has a sheet id ("sid", SS-XXXXXX) of its own from when it's first written, that nothing edited changes; a list
carried over from a last revision's says which it came from ("from"). A job detail changed once it was filled in needs
a change note: each change is kept in "log" ([{"at", "who", "field", "old", "new", "note"}]).
Production issues ("issues") are what has to be dialed in before a part runs, or while it does: each has a number
("n", 1, 2, 3 on this sheet), the balloon it's about ("char", a characteristic's id, and "label", its number when last
seen), a title, notes, tags (ISSUE_TAGS), the job number, and a status: "open", "fixed" (a machinist says it's fixed,
ready for a lead) or "resolved", with how ("route": "machinist", a machinist's fix, or "troubleshooting", moved there).
Hidden ones are out of the way but kept; one asked to be deleted ("delete": {"reason", "who", "at"}) is hidden and
waits for someone to delete it for good, or to switch it back to hidden. Each has its history ("history").
A list is a "draft" until it's released ("status"): released, its balloons and characteristics are fixed (the parts'
results, the production issues and the job's details are still filled in); superseded by the next revision, nothing
in it changes. Back to draft is how either is changed again, with a change note; each change of status is logged.
Photos ("photos": [{"id", "on": "char" or "issue", "of": its id, "name", "w", "h", "at", "by", "marks"}]) are kept in
the PDF as embedded files (ssp-<id>.jpg, no more than 1920 pixels along), each on a characteristic or an issue. What's
drawn on one ("marks": lines, arrows, ovals, boxes, freehand, text, in its pixels) is kept beside it, never in the
picture, so it can be shown, hidden or changed again.
"""

import base64
import datetime
import getpass
import json
import math
import re
import secrets
import statistics
from pathlib import Path

from . import balloons

KEY, FONT_KEY, SUBJECT, VIEW = "SolidSmurfsInspection", "SolidSmurfsBalloonFont", "Balloon", "Balloon view"
RED = (0.82, 0.07, 0.07)
VIEW_COLORS = ["#1f77b4", "#e67e22", "#2a9d48", "#8e44ad", "#00838f", "#b8860b", "#c2185b", "#5d6d7e"]
ORDERS = ("list", "rows", "columns", "clockwise")


def _rgb(color):
    try:
        h = str(color).lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return RED
FIELDS = ("kind", "text", "count", "nominal", "plus", "minus", "lo", "hi", "places", "tol", "desc", "gage", "note", "reviewed", "zone", "mult", "tags")
# how a characteristic is inspected: as many as apply, or none (not printed)
TAGS = ("Visual", "Measured", "Dimension", "Finish", "Deburring", "Spot check", "100% check", "Custom gage")


def _tags(given):
    given = {str(t) for t in (given or [])}
    return [t for t in TAGS if t in given] or None


def who():
    """Who's at this computer, First Last from their sign-in name (ben.pauza: Ben Pauza)."""
    try:
        name = getpass.getuser()
    except Exception:
        return ""
    return " ".join(w.capitalize() for w in re.split(r"[._\s]+", name) if w)


# what's changed by each edit: the characteristics (fixed once released), or the work on them (fixed once superseded)
FIXED_RELEASED = {"auto", "add", "move", "edit", "sub", "multiply", "detach", "carry", "tag", "reviewed", "delete", "renumber",
                  "view_add", "view_edit", "view_delete", "clear", "tols"}
FIXED_SUPERSEDED = FIXED_RELEASED | {"part_add", "sample", "part_edit", "part_delete", "result", "import", "results_clear",
                                     "issue_add", "issue_edit", "issue_act", "info", "photo_add", "photo_marks", "photo_delete"}
PHOTO_MOST = 1920  # pixels along a photo's longer side
MARK_KINDS = ("pen", "line", "arrow", "oval", "rect", "lasso", "text", "stamp")
MARK_FILLS = ("none", "solid", "blur")  # (a box, an oval or a lasso shape: filled with its color, or the photo blurred)
STATUSES = ("draft", "released", "superseded")
ISSUE_TAGS = ("OK / watch", "Improve", "Out of tolerance", "Dimension", "Finish", "Deburring")
ISSUE_ACTS = ("fixed", "resolve", "reopen", "hide", "show", "delete", "keep", "purge")


def _issue_tags(given):
    given = {str(t) for t in (given or [])}
    return [t for t in ISSUE_TAGS if t in given]


def _stamp():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _sid():
    return "SS-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))


class BalloonOps:
    def _balloon_guard(self, op, args):
        """A released list's characteristics aren't changed, and nothing in a superseded one is. A lead's actions wait
        for a lead to unlock (kernel/roles.py)."""
        if not op.startswith("balloon_"):
            return
        from . import roles
        roles.need_for(op, args)
        what = op[len("balloon_"):]
        if what not in FIXED_SUPERSEDED or (what == "import" and args.get("preview")):
            return
        status = self._insp().get("status") or "draft"
        if status == "superseded":
            raise ValueError("This revision is superseded: nothing in it changes. Back to draft (Status) to change it.")
        if status == "released" and what in FIXED_RELEASED:
            raise ValueError("This list is released: its balloons and characteristics are fixed. Back to draft (Status) to change them.")

    # ================================================================== the list, kept in the PDF
    def _insp(self):
        import pymupdf
        doc, data = self.fz, None
        kind, val = doc.xref_get_key(doc.pdf_catalog(), KEY)
        if kind == "xref":
            try:
                data = json.loads(doc.xref_stream(int(val.split()[0])).decode("utf-8"))
            except Exception:
                data = None
        if not isinstance(data, dict) or not isinstance(data.get("chars"), list):
            return {"v": 1, "chars": [], "tols": {}, "unit": None, "next": 1, "samples": [], "results": {}, "snext": 1, "views": [], "vnext": 1}
        where = {}
        for i, pg in enumerate(doc):
            for a in pg.annots(types=[pymupdf.PDF_ANNOT_CIRCLE]):
                name = a.info.get("id", "")
                if a.info.get("subject") == SUBJECT and name.startswith("ssb-"):
                    where.setdefault(name[4:], i)  # (a copy of its page has the same comments: the first one is its balloon)
        data["chars"] = [{**c, "page": where[str(c["id"])]} for c in data["chars"] if str(c["id"]) in where]
        data["chars"].sort(key=lambda c: (c["n"], c.get("sub") or 0))
        views = {}
        for i, pg in enumerate(doc):
            for a in pg.annots(types=[pymupdf.PDF_ANNOT_SQUARE]):
                name = a.info.get("id", "")
                if a.info.get("subject") == VIEW and name.startswith("ssv-"):
                    views.setdefault(name[4:], i)
        data["views"] = [v for v in data.get("views") or [] if isinstance(v, dict) and 0 <= v.get("page", -1) < doc.page_count]
        if views or data.get("vmarks"):  # (a view goes where its page went, and with it; a list from before they had marks keeps them where they were)
            data["views"] = [{**v, "page": views[str(v["id"])]} for v in data["views"] if str(v["id"]) in views]
        data.setdefault("vnext", max([v["id"] for v in data["views"]], default=0) + 1)
        return self._results_kept(data)

    @staticmethod
    def _results_kept(data):
        """Results stay with their rows and their parts: those of a balloon or a part that's gone go with it."""
        rows = {k for c in data["chars"] for k in balloons.row_keys(c)}
        data["samples"] = [s for s in data.get("samples") or [] if isinstance(s, dict) and "id" in s]
        parts = {str(s["id"]) for s in data["samples"]}
        data["results"] = {k: {p: v for p, v in r.items() if p in parts and v != ""} for k, r in (data.get("results") or {}).items() if k in rows}
        data["results"] = {k: r for k, r in data["results"].items() if r}
        data.setdefault("snext", max([int(s["id"]) for s in data["samples"]], default=0) + 1)
        return data

    @staticmethod
    def _groups(chars):
        """The balloons in order, those sharing a number together."""
        out = []
        for c in sorted(chars, key=lambda c: (c["n"], c.get("sub") or 0)):
            if out and out[-1][0]["n"] == c["n"]:
                out[-1].append(c)
            else:
                out.append([c])
        return out

    @staticmethod
    def _numbered(groups, starts=None):
        """Number the groups 1, 2, 3 and those within one .1, .2, .3: the list in that order. starts: {group's
        place: the number it's to have}, when that's further on than the next one."""
        chars, n = [], 0
        for k, g in enumerate(groups):
            n = max(n + 1, (starts or {}).get(k, 0))
            for j, c in enumerate(g, 1):
                c["n"], c["sub"] = n, j if len(g) > 1 else None
                chars.append(c)
        return chars

    def _insp_write(self, data):
        doc = self.fz
        data.setdefault("sid", _sid())  # (once, for good)
        if data.get("views"):
            data["vmarks"] = True  # (its views have their marks on their pages, drawn with it)
        cat = doc.pdf_catalog()
        kind, val = doc.xref_get_key(cat, KEY)
        if kind == "xref":
            x = int(val.split()[0])
        else:
            x = doc.get_new_xref()
            doc.update_object(x, "<<>>")
            doc.xref_set_key(cat, KEY, f"{x} 0 R")
        doc.update_stream(x, json.dumps(data, separators=(",", ":")).encode("utf-8"))

    def _select(self, order):
        """Put the pages in this order (a page may be left out, or come twice), keeping the inspection list: the
        rearranging drops from the document's catalog what it doesn't know."""
        doc = self.fz
        mine = {k: doc.xref_get_key(doc.pdf_catalog(), k) for k in (KEY, FONT_KEY)}
        doc.select(order)
        cat = doc.pdf_catalog()
        for k, (kind, val) in mine.items():
            if kind == "xref" and doc.xref_get_key(cat, k)[0] != "xref":
                doc.xref_set_key(cat, k, val)

    def _balloon_font(self):
        doc = self.fz
        cat = doc.pdf_catalog()
        kind, val = doc.xref_get_key(cat, FONT_KEY)
        if kind == "xref":
            return int(val.split()[0])
        x = doc.get_new_xref()
        doc.update_object(x, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold/Encoding/WinAnsiEncoding>>")
        doc.xref_set_key(cat, FONT_KEY, f"{x} 0 R")
        return x

    def _balloon_strip(self):
        """Take every balloon's and view's comment off the pages (the list stays)."""
        import pymupdf
        for pg in self.fz:
            for a in [a for a in pg.annots(types=[pymupdf.PDF_ANNOT_CIRCLE, pymupdf.PDF_ANNOT_SQUARE]) if a.info.get("subject") in (SUBJECT, VIEW)]:
                pg.delete_annot(a)

    def _balloon_tidy(self, new=()):
        """After pages are copied or brought in from another file: a balloon or view whose comment is on a copy of its
        page stays on the first one, and pages from elsewhere (`new`) keep none of theirs (they're another list's)."""
        import pymupdf
        seen, new = set(), {int(i) for i in new}
        for i, pg in enumerate(self.fz):
            gone = []
            for a in pg.annots(types=[pymupdf.PDF_ANNOT_CIRCLE, pymupdf.PDF_ANNOT_SQUARE]):
                if a.info.get("subject") not in (SUBJECT, VIEW):
                    continue
                name = a.info.get("id", "")
                if i in new or name in seen:
                    gone.append(a)
                else:
                    seen.add(name)
            for a in gone:
                pg.delete_annot(a)

    @staticmethod
    def _view_of(data, c):
        """The view a characteristic's callout is in (the first that holds it), or None."""
        bx = c["box"]
        cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
        for v in data.get("views") or []:
            x0, y0, x1, y1 = v["rect"]
            if v["page"] == c["page"] and x0 <= cx <= x1 and y0 <= cy <= y1:
                return v
        return None

    def _balloon_sync(self, data, pages):
        """Make the balloons' comments on these pages again from the list."""
        import pymupdf
        from .pdfedit import author
        doc, font, who = self.fz, self._balloon_font(), author()
        for i in sorted({int(p) for p in pages if 0 <= int(p) < doc.page_count}):
            pg = doc[i]
            for a in [a for a in pg.annots(types=[pymupdf.PDF_ANNOT_CIRCLE, pymupdf.PDF_ANNOT_SQUARE]) if a.info.get("subject") in (SUBJECT, VIEW)]:
                pg.delete_annot(a)
            for v in data.get("views") or []:  # each view's hidden mark, that holds it to its page
                if v["page"] != i:
                    continue
                a = pg.add_rect_annot(pymupdf.Rect(v["rect"]))
                a.set_info(title=who, subject=VIEW, content=v["name"])
                a.set_flags(pymupdf.PDF_ANNOT_IS_HIDDEN)
                a.update()
                doc.xref_set_key(a.xref, "NM", f"(ssv-{v['id']})")
            for c in data["chars"]:
                if c["page"] != i:
                    continue
                (x, y), r = c["at"], c["r"]
                view = self._view_of(data, c)
                color = _rgb(view["color"]) if view else RED
                a = pg.add_circle_annot(pymupdf.Rect(x - r, y - r, x + r, y + r))
                a.set_colors(stroke=color, fill=(1, 1, 1))
                a.set_border(width=round(max(r * 0.13, 0.7), 2))
                a.set_info(title=who, subject=SUBJECT, content=f"{balloons.label(c)}: {c['text']}")
                a.update()
                doc.xref_set_key(a.xref, "NM", f"(ssb-{c['id']})")
                kind, val = doc.xref_get_key(a.xref, "AP/N")
                if kind != "xref":
                    continue
                ap = int(val.split()[0])
                box = [float(v) for v in re.findall(r"-?\d*\.?\d+", doc.xref_get_key(ap, "BBox")[1])]
                if len(box) != 4:
                    continue
                # its number, in the circle's middle, upright on the page as it's shown
                text = balloons.label(c)
                fs = r * (1.25 if len(text) < 2 else 1.08 if len(text) == 2 else 0.8 if len(text) == 3 else 0.64)
                tw = pymupdf.get_text_length(text, "hebo", fs)
                t = math.radians(pg.rotation)
                cos, sin = math.cos(t), math.sin(t)
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                sx = cx - tw / 2 * cos + 0.36 * fs * sin
                sy = cy - tw / 2 * sin - 0.36 * fs * cos
                more = (f"\nBT /Helv {fs:.2f} Tf {color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg {cos:.5f} {sin:.5f} {-sin:.5f} {cos:.5f} "
                        f"{sx:.2f} {sy:.2f} Tm ({text}) Tj ET\n")
                doc.update_stream(ap, b"q\n" + doc.xref_stream(ap) + b"Q" + more.encode("ascii"))
                doc.xref_set_key(ap, "Resources", f"<</Font<</Helv {font} 0 R>>>>")

    def _balloon_out(self, data):
        chars = []
        for c in data["chars"]:
            pg = self.fz[c["page"]]
            view = self._view_of(data, c)
            chars.append({"view": view["id"] if view else None, "color": view["color"] if view else None, "id": c["id"], "n": c["n"], "sub": c.get("sub"), "label": balloons.label(c), "page": c["page"], "r": c["r"], "box": self._out(pg, c["box"]),
                          "type": balloons.type_of(c), "where": f"S{c['page'] + 1}" + (f"-{c['zone']}" if c.get("zone") else ""),
                          "at": self._pt_out(pg, c["at"]), **{k: c.get(k) for k in FIELDS}})
        from . import report
        labels = {c["id"]: balloons.label(c) for c in data["chars"]}
        issues = [{**i, "label": labels.get(i.get("char"), i.get("label")), "gone": i.get("char") is not None and i.get("char") not in labels}
                  for i in data.get("issues") or []]
        return {"sid": data.get("sid"), "from": data.get("from"), "log": data.get("log") or [], "tags": list(TAGS), "who": who(),
                "status": data.get("status") or "draft", "photos": data.get("photos") or [],
                "issues": issues, "issueTags": list(ISSUE_TAGS),
                "chars": chars, "tols": data.get("tols") or {}, "unit": data.get("unit"), "labels": balloons.KIND_LABEL,
                "info": data.get("info") or {}, "fields": [[k, label] for k, label, _ in report.INFO], "layouts": report.LAYOUTS,
                "samples": data.get("samples") or [], "results": data.get("results") or {},
                "views": [{**v, "rect": self._out(self.fz[v["page"]], v["rect"]), "count": sum(1 for c in chars if c["view"] == v["id"])}
                          for v in data.get("views") or []]}

    def _balloon_item(self, pg, it, at, r):
        import pymupdf
        x, y, w, h = it["box"]
        box = pymupdf.Rect(x, y, x + w, y + h) * pg.derotation_matrix
        box.normalize()
        p = self._pt(pg, at)
        return {**{k: it.get(k) for k in FIELDS}, "r": r, "box": [round(v, 2) for v in box], "at": [round(p.x, 2), round(p.y, 2)]}

    # ================================================================== reading a page
    @staticmethod
    def _balloon_rects(pg):
        """Where the page's balloons are now, as it's shown: they're read back as text and linework like the rest of
        the page, and are no part of the print."""
        import pymupdf
        out = []
        for a in pg.annots(types=[pymupdf.PDF_ANNOT_CIRCLE]):
            if a.info.get("subject") == SUBJECT:
                b = a.rect * pg.rotation_matrix
                b.normalize()
                out.append((b.x0 - 1.5, b.y0 - 1.5, b.x1 + 1.5, b.y1 + 1.5))
        return out

    def _balloon_lines(self, pg, extra=None):
        """A page's lines of text for kernel/balloons.py, in points as the page is shown: its own text, then what OCR
        read where it has none."""
        import pymupdf
        rot, lines, own = pg.rotation_matrix, [], self._balloon_rects(pg)
        for block in pg.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                dx, dy = line.get("dir", (1, 0))
                d = pymupdf.Point(dx, dy) * pymupdf.Matrix(rot.a, rot.b, rot.c, rot.d, 0, 0)
                vert = abs(d.y) > abs(d.x)
                down = vert and d.y > 0
                pieces = []
                for s in line.get("spans", []):  # spans far apart on one baseline are callouts of their own
                    b = pymupdf.Rect(s["bbox"]) * rot
                    b.normalize()
                    if not s["text"].strip():
                        continue
                    if own and re.fullmatch(r"\d+(?:\.\d+)?", s["text"].strip()) and any(
                            o[0] <= (b.x0 + b.x1) / 2 <= o[2] and o[1] <= (b.y0 + b.y1) / 2 <= o[3] for o in own):
                        continue  # a balloon's own number
                    h = min(b.width, b.height) or 1.0
                    last = pieces[-1] if pieces else None
                    gap = None if last is None else (b.y0 - last["box"][3] if down else last["box"][1] - b.y1 if vert else b.x0 - last["box"][2])
                    if last is not None and -h <= gap <= 1.4 * h:
                        joined = last["text"] + ("" if gap < 0.12 * h or last["text"].endswith(" ") or s["text"].startswith(" ") else " ") + s["text"]
                        last.update(text=joined, box=balloons._union(last["box"], [b.x0, b.y0, b.x1, b.y1]))
                    else:
                        pieces.append({"text": s["text"], "box": [b.x0, b.y0, b.x1, b.y1], "vert": vert, "down": down})
                lines += [p for p in pieces if p["text"].strip()]
        for text, x0, y0, x1, y1 in (extra or {}).get("ocr", []):
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if any(ln["box"][0] - 2 <= cx <= ln["box"][2] + 2 and ln["box"][1] - 2 <= cy <= ln["box"][3] + 2 for ln in lines):
                continue
            lines.append({"text": text, "box": [x0, y0, x1, y1], "vert": len(text.strip()) > 1 and (y1 - y0) > 1.6 * (x1 - x0), "ocr": True})
        return lines

    @staticmethod
    def _balloon_shapes(pg):
        """The page's small closed outlines of straight sides, as the page is shown: (x0, y0, x1, y1, sides). A flag
        note's triangle or flag is one."""
        import pymupdf
        rot, out = pg.rotation_matrix, []
        try:
            paths = pg.get_drawings()
        except Exception:
            return out
        for path in paths:
            items = path.get("items", [])
            if not 3 <= len(items) <= 8 or any(it[0] != "l" for it in items):
                continue
            r = pymupdf.Rect(path["rect"]) * rot
            r.normalize()
            if not (2 < r.width < 60 and 2 < r.height < 60):
                continue
            first, last = items[0][1], items[-1][2]
            closed = path.get("closePath") or abs(first.x - last.x) + abs(first.y - last.y) < 0.5
            if closed:
                sides = len(items) + (1 if path.get("closePath") and abs(first.x - last.x) + abs(first.y - last.y) >= 0.5 else 0)
                out.append((r.x0, r.y0, r.x1, r.y1, sides))
        return out

    @staticmethod
    def _balloon_marks(pg):
        """What a balloon shouldn't sit on besides text, in points as the page is shown: the page's linework as
        segments [(x0, y0, x1, y1)] (curves as chords) and its pictures as boxes (not one that is the whole page: a
        scan)."""
        import pymupdf
        rot, segs, pics, own = pg.rotation_matrix, [], [], BalloonOps._balloon_rects(pg)
        try:
            paths = pg.get_drawings()
        except Exception:
            paths = []
        for path in paths:
            if len(segs) > 40000:
                break
            for it in path.get("items", []):
                if it[0] == "l":
                    pts = [it[1], it[2]]
                elif it[0] == "re":
                    q = it[1].quad
                    pts = [q.ul, q.ur, q.lr, q.ll, q.ul]
                elif it[0] == "qu":
                    q = it[1]
                    pts = [q.ul, q.ur, q.lr, q.ll, q.ul]
                elif it[0] == "c":
                    a, b, c, d = it[1:5]
                    pts = [pymupdf.Point(*[(1 - t) ** 3 * a[k] + 3 * (1 - t) ** 2 * t * b[k] + 3 * (1 - t) * t * t * c[k] + t ** 3 * d[k] for k in (0, 1)])
                           for t in (0, .2, .4, .6, .8, 1)]
                else:
                    continue
                pts = [pymupdf.Point(p) * rot for p in pts]
                segs += [(a.x, a.y, b.x, b.y) for a, b in zip(pts, pts[1:])
                         if not any(o[0] <= a.x <= o[2] and o[1] <= a.y <= o[3] and o[0] <= b.x <= o[2] and o[1] <= b.y <= o[3] for o in own)]
        area = abs(pg.rect.width * pg.rect.height) or 1.0
        try:
            for im in pg.get_image_info():
                b = pymupdf.Rect(im["bbox"]) * rot
                b.normalize()
                if 0 < b.width * b.height < 0.5 * area:
                    pics.append((b.x0, b.y0, b.x1, b.y1))
        except Exception:
            pass
        return segs, pics

    @staticmethod
    def _extra_page(extra, i):
        return ((extra or {}).get("pages") or {}).get(str(i)) or {}

    # ================================================================== the edits
    def op_balloons(self):
        """The inspection list: {"chars": [{"id", "n", "sub", "label" (what the balloon says: 2, or 2.1), "type" (Linear,
        Diameter, Angular…), "where" (the sheet and the border's zone: S1-A4), "reviewed", "note", "desc", "gage", "page", "r", "at": [x, y], "box": [x, y, w, h], "kind",
        "text", "count", "nominal", "plus", "minus", "lo", "hi", "places", "tol"}], "tols", "unit", "labels",
        "info": what the report says about the job, "fields": [[key, label]] it can say}."""
        return self._balloon_out(self._insp())

    def op_balloon_auto(self, extra=None, notes=True, pages=None, want=None, split=False):
        """Read the print and balloon what's found, in place of the balloons on the pages read.
        pages: the pages to read, counted from 0 (None: every one); the balloons on the others stay, and the numbers
        then run through the sheets in order. want: what to balloon, each True unless said ({"ref", "basic",
        "general", "finish", "title"}: see balloons.read). notes: the numbered notes too. split: one callout's
        several characteristics share a number, as 2.1, 2.2.
        extra (from the worker): {"unit", "pages": {"0": {"frames": [{"box", "text"}], "ocr": [[text, x0, y0, x1, y1]]}}}."""
        old = self._insp()
        count = self.fz.page_count
        which = list(range(count)) if pages is None else sorted({int(p) for p in pages if 0 <= int(p) < count})
        part = len(which) < count
        read, texts = {}, []
        for i, pg in enumerate(self.fz):
            ex = self._extra_page(extra, i)
            lines = self._balloon_lines(pg, ex)
            texts += [ln["text"] for ln in lines]
            if i in which:
                read[i] = (pg, lines, ex.get("frames") or [])
        stay = [c for c in old["chars"] if c["page"] not in which]
        unit = (extra or {}).get("unit") or (old.get("unit") if stay else None)
        tols = old["tols"] if stay and old.get("tols") else balloons.defaults(texts)
        data = {"v": 1, "chars": list(stay), "tols": tols, "unit": unit, "next": old.get("next", 1) if stay else 1, "info": old.get("info") or {},
                "samples": old.get("samples") or [], "snext": old.get("snext", 1), "views": old.get("views") or [], "vnext": old.get("vnext", 1),
                # (the balloons read again are new ones: what was measured against the old ones doesn't carry over)
                "results": {k: r for k, r in (old.get("results") or {}).items() if k.split(".")[0] in {str(c["id"]) for c in stay}}}
        n = max([c["n"] for c in stay], default=0)
        for i in which:
            pg, lines, frames = read[i]
            size = (pg.rect.width, pg.rect.height)
            segs, pics = self._balloon_marks(pg)
            items = balloons.read(lines, frames, unit, tols, size, notes=notes, segs=segs, want=want, shapes=self._balloon_shapes(pg))
            if not items:
                continue
            zones = balloons.grid(lines, size)
            r = balloons.radius(items)
            obstacles = [tuple(ln["box"]) for ln in lines] + [(f["box"][0], f["box"][1], f["box"][0] + f["box"][2], f["box"][1] + f["box"][3]) for f in frames]
            numbers, fresh = {}, []
            for it, at in zip(items, balloons.place(items, obstacles, size, r, segs, pics)):
                group = it.get("group") if split else None
                if group is None or group not in numbers:
                    n += 1
                    numbers[group if group is not None else ("alone", n)] = n
                fresh.append({"id": data["next"], "n": numbers[group] if group is not None else n, "page": i, **self._balloon_item(pg, it, at, r),
                              "zone": balloons.zone_at(zones, it["box"][0] + it["box"][2] / 2, it["box"][1] + it["box"][3] / 2)})
                data["next"] += 1
            for c in fresh:  # those of one callout are .1, .2 in the order they were read
                mates = [x for x in fresh if x["n"] == c["n"]]
                if len(mates) > 1:
                    c["sub"] = mates.index(c) + 1
            data["chars"] += fresh
        found = len(data["chars"]) - len(stay)
        gone = [c for c in old["chars"] if c["page"] in which]
        if not found and not gone:
            return self._answer([], result={**self._balloon_out(old if stay else data), "found": 0})
        if stay or data["views"]:  # the numbers run through the sheets in order, and view by view
            order, groups = sorted(data["chars"], key=lambda c: (c["page"], c["n"], c.get("sub") or 0)), []
            for c in order:
                if groups and (groups[-1][0]["page"], groups[-1][0]["n"]) == (c["page"], c["n"]):
                    groups[-1].append(c)
                else:
                    groups.append([c])
            if data["views"]:
                groups = self._ordered(data, groups, "list")
            data["chars"] = self._numbered(groups, self._starts(data, groups))
        self._snapshot()
        self._insp_write(data)
        touched = {c["page"] for c in data["chars"]} | {c["page"] for c in old["chars"]}
        self._balloon_sync(data, touched)
        return self._answer(sorted(touched), result={**self._balloon_out(data), "found": found})

    def _balloon_done(self, data, pages, result=None):
        self._insp_write(self._results_kept(data))
        self._balloon_sync(data, pages)
        return self._answer(sorted(set(pages)), result={**self._balloon_out(data), **(result or {})})

    def _balloon_find(self, data, id):
        for c in data["chars"]:
            if c["id"] == int(id):
                return c
        raise ValueError("That balloon isn't there any more.")

    def op_balloon_add(self, page, rect, extra=None):
        """Balloon what's inside a rectangle drawn on the page ([x, y, w, h] as shown); a click (no size) leaves an
        empty one there to fill in."""
        pg, data = self._page(page), self._insp()
        ex = self._extra_page(extra, int(page))
        x, y, w, h = [float(v) for v in rect]
        size = (pg.rect.width, pg.rect.height)
        lines = self._balloon_lines(pg, ex)
        mine = [c for c in data["chars"] if c["page"] == int(page)]
        r = statistics.median(c["r"] for c in mine) if mine else None
        obstacles = [tuple(ln["box"]) for ln in lines]
        for c in mine:
            p = self._pt_out(pg, c["at"])
            obstacles.append((p[0] - 1.3 * c["r"], p[1] - 1.3 * c["r"], p[0] + 1.3 * c["r"], p[1] + 1.3 * c["r"]))
        if w < 3 or h < 3:
            r = r or 8.0
            items, ats = [{"kind": "other", "text": "", "count": 1, "places": 0, "box": [x + r + 2, y - r, 2 * r, 2 * r]}], [[x, y]]
        else:
            inside = [ln for ln in lines if x <= (ln["box"][0] + ln["box"][2]) / 2 <= x + w and y <= (ln["box"][1] + ln["box"][3]) / 2 <= y + h]
            frames = [f for f in ex.get("frames") or [] if x <= f["box"][0] + f["box"][2] / 2 <= x + w and y <= f["box"][1] + f["box"][3] / 2 <= y + h]
            items = balloons.read(inside, frames, data.get("unit"), data.get("tols") or {}, size, notes=False, segs=self._balloon_marks(pg)[0])
            if not items:  # asked for by hand: a reference or basic size is ballooned all the same
                bare = [{**ln, "text": re.sub(r"[()\[\]]|\b(?:REF|REFERENCE|BSC|BASIC)\b\.?", " ", ln["text"], flags=re.I)} for ln in inside]
                items = balloons.read(bare, frames, data.get("unit"), data.get("tols") or {}, size, notes=False)
            if not items:  # nothing it knows: what's written there, as it is
                text = balloons.clean(" ".join(ln["text"] for ln in sorted(inside, key=lambda ln: (ln["box"][1], ln["box"][0]))))
                items = [{"kind": "note" if text else "other", "text": text, "count": 1, "places": 0, "box": [x, y, w, h]}]
            r = r or balloons.radius(items)
            ats = balloons.place(items, obstacles, size, r, *self._balloon_marks(pg))
        self._snapshot()
        n, ids, zones = max([c["n"] for c in data["chars"]], default=0), [], balloons.grid(lines, size)
        for it, at in zip(items, ats):
            n += 1
            data["chars"].append({"id": data["next"], "n": n, "page": int(page), **self._balloon_item(pg, it, at, r),
                                  "zone": balloons.zone_at(zones, it["box"][0] + it["box"][2] / 2, it["box"][1] + it["box"][3] / 2)})
            ids.append(data["next"])
            data["next"] += 1
        return self._balloon_done(data, [int(page)], {"ids": ids})

    def op_balloon_move(self, id, at):
        data = self._insp()
        c = self._balloon_find(data, id)
        self._snapshot()
        p = self._pt(self.fz[c["page"]], at)
        c["at"] = [round(p.x, 2), round(p.y, 2)]
        return self._balloon_done(data, [c["page"]])

    def op_balloon_edit(self, id, **o):
        """Change a characteristic: kind, text, count, desc (what it is, in words), gage (what it's checked with), note,
        reviewed (it has been checked against the print), nominal, plus, minus, lo, hi (numbers or None), tol ("ref"
        or "basic": a reference or basic size, with no limits; anything else: an ordinary one again), or n, its balloon
        number: 4 moves it to be the fourth (the others move along), "4.2" puts it second under number 4 with what's
        there."""
        data = self._insp()
        c = self._balloon_find(data, id)
        self._snapshot()
        pages = [c["page"]]
        for k in ("kind", "text", "count", "desc", "gage", "note"):
            if k in o and o[k] is not None:
                c[k] = max(int(o[k]), 1) if k == "count" else str(o[k]).strip()[:400 if k == "note" else 200]
        if (c.get("count") or 1) < 2:
            c["mult"] = None  # (one place: nothing to multiply)
        if o.get("reviewed") is not None:
            c["reviewed"] = bool(o["reviewed"])
        if "tags" in o:
            c["tags"] = _tags(o["tags"])
        if o.get("tol") is not None:
            if o["tol"] in ("ref", "basic"):
                c.update(plus=None, minus=None, lo=None, hi=None, tol=o["tol"])
            elif c.get("tol") in ("ref", "basic"):
                c["tol"] = None
                balloons.limits(c, data.get("tols") or {})
        given = [k for k in ("nominal", "plus", "minus", "lo", "hi") if k in o]
        if given:
            for k in given:
                c[k] = None if o[k] in (None, "") else float(o[k])
            if o.get("places") is not None:
                c["places"] = int(o["places"])
            if not ("lo" in o or "hi" in o):
                c["lo"] = c["hi"] = None  # they follow the nominal and its tolerance
            if c["plus"] is not None and c["minus"] is None:
                c["minus"] = c["plus"]
            has = c["plus"] is not None or c["lo"] is not None or c["hi"] is not None
            if has and not (c.get("tol") == "default" and given == ["nominal"]):  # (a new nominal alone keeps the title block's)
                c["tol"] = "print"
            elif not has and c.get("tol") not in ("ref", "basic"):  # (and a reference or basic size stays one)
                c["tol"] = None
            if c["kind"] not in ("dim", "angle", "chamfer") and c["nominal"] is not None:
                c["kind"] = "dim"
            balloons.limits(c, data.get("tols") or {})
            if "text" not in o:  # what the requirement says follows (a changed nominal, tolerance or limits)
                c["text"] = balloons.restate(c, c.get("text"))
        if o.get("count") is not None and "text" not in o:
            c["text"] = balloons.recount(c.get("text"), c["count"])
        if o.get("n") is not None:
            m = re.fullmatch(r"\s*(\d+)(?:\s*\.\s*(\d+))?\s*", str(o["n"]))
            if not m:
                raise ValueError("A balloon's number is like 4, or 4.2 for the second one under 4.")
            n, sub = int(m[1]), int(m[2]) if m[2] else None
            groups = self._groups(data["chars"])
            under = next((g for g in groups if g[0]["n"] == n), None) if sub else None
            for g in groups:
                g[:] = [x for x in g if x is not c]
            groups = [g for g in groups if g]
            if under:
                under.insert(min(max(sub - 1, 0), len(under)), c)
            else:
                groups.insert(min(max(n - 1, 0), len(groups)), [c])
            data["chars"] = self._numbered(groups)
            pages = [x["page"] for x in data["chars"]]
        return self._balloon_done(data, pages)

    def op_balloon_sub(self, id):
        """Another characteristic of the same callout: an empty balloon under this one's number (2 becomes 2.1, the
        new one 2.2), beside the last of them."""
        data = self._insp()
        c = self._balloon_find(data, id)
        self._snapshot()
        group = [x for x in data["chars"] if x["n"] == c["n"]]
        for i, x in enumerate(group, 1):
            x["sub"] = x.get("sub") or i
        last = max(group, key=lambda x: x["sub"])
        pg = self.fz[c["page"]]
        p = self._pt_out(pg, last["at"])
        p = self._pt(pg, [p[0] + 2.15 * c["r"], p[1]])
        new = {**{k: None for k in FIELDS}, "id": data["next"], "n": c["n"], "sub": last["sub"] + 1, "page": c["page"], "kind": "other", "text": "",
               "count": 1, "places": 0, "r": c["r"], "box": list(c["box"]), "at": [round(p.x, 2), round(p.y, 2)], "zone": c.get("zone")}
        data["chars"].append(new)
        data["next"] += 1
        data["chars"].sort(key=lambda x: (x["n"], x.get("sub") or 0))
        return self._balloon_done(data, [c["page"]], {"ids": [new["id"]]})

    def op_balloon_multiply(self, ids=None, on=True):
        """Multiply: a characteristic that applies in several places (4X) is inspected in each. It keeps its one
        balloon, and the list and the report give it a row for each place: 3.1 to 3.4. on False: back to its one row.
        ids None: every characteristic it can be done to."""
        data = self._insp()
        want = None if ids is None else {int(i) for i in ids}
        mine = [c for c in data["chars"] if (c.get("count") or 1) > 1 and bool(c.get("mult")) != bool(on) and (want is None or c["id"] in want)]
        if not mine:
            return self._answer([], result={**self._balloon_out(data), "did": 0})
        self._snapshot()
        res = data["results"]
        for c in mine:
            one, first = str(c["id"]), f"{c['id']}.1"  # its results are its first place's, and back again
            if on and one in res:
                res[first] = res.pop(one)
            elif not on and first in res:
                res[one] = res.pop(first)
            c["mult"] = bool(on) or None
        return self._balloon_done(data, [], {"did": len(mine), "rows": sum(c["count"] for c in mine)})

    def op_balloon_detach(self, ids=None):
        """Detach a multiplied characteristic's places from one another: 3 (4X) becomes 3.1 to 3.4, each an entry of
        its own with its own balloon (to put by its own feature), description, gage and note. The new balloons go
        around the callout, clear of what's there. ids None: every multiplied characteristic."""
        data = self._insp()
        want = None if ids is None else {int(i) for i in ids}
        mine = [c for c in data["chars"] if c.get("mult") and (c.get("count") or 1) > 1 and (want is None or c["id"] in want)]
        if not mine:
            return self._answer([], result={**self._balloon_out(data), "made": 0})
        self._snapshot()
        groups, seen, made = self._groups(data["chars"]), {}, 0
        for c in mine:
            pg = self.fz[c["page"]]
            if c["page"] not in seen:  # the page's text, linework and the balloons on it: what a new balloon keeps off
                segs, pics = self._balloon_marks(pg)
                taken = [tuple(ln["box"]) for ln in self._balloon_lines(pg)]
                for x in data["chars"]:
                    if x["page"] == c["page"]:
                        p = self._pt_out(pg, x["at"])
                        taken.append((p[0] - 1.3 * x["r"], p[1] - 1.3 * x["r"], p[0] + 1.3 * x["r"], p[1] + 1.3 * x["r"]))
                seen[c["page"]] = (segs, pics, taken)
            segs, pics, taken = seen[c["page"]]
            places = [{"box": self._out(pg, c["box"]), "kind": c["kind"], "vert": False} for _ in range(c["count"] - 1)]
            text, new = balloons.single(c.get("text") or ""), []
            res = data["results"]
            if f"{c['id']}.1" in res:  # each place's results go with it
                res[str(c["id"])] = res.pop(f"{c['id']}.1")
            for k, at in enumerate(balloons.place(places, taken, (pg.rect.width, pg.rect.height), c["r"], segs, pics), 2):
                p = self._pt(pg, at)
                if f"{c['id']}.{k}" in res:
                    res[str(data["next"])] = res.pop(f"{c['id']}.{k}")
                new.append({**c, "id": data["next"], "count": 1, "mult": None, "text": text, "at": [round(p.x, 2), round(p.y, 2)]})
                taken.append((at[0] - 1.3 * c["r"], at[1] - 1.3 * c["r"], at[0] + 1.3 * c["r"], at[1] + 1.3 * c["r"]))
                data["next"] += 1
            c.update(count=1, mult=None, text=text)
            group = next(g for g in groups if any(x is c for x in g))
            i = next(i for i, x in enumerate(group) if x is c)
            group[i + 1:i + 1] = new
            for k, x in enumerate(group, 1):
                x["sub"] = k
            made += len(new)
        data["chars"] = [x for g in groups for x in g]
        return self._balloon_done(data, {c["page"] for c in mine}, {"made": made})

    # ================================================================== the parts inspected, and what they measured
    def op_balloon_part_add(self, name=None):
        """Another part to inspect, by its serial number or what it's called (else the next number)."""
        data = self._insp()
        self._snapshot()
        names = {s["name"] for s in data["samples"]}
        at = len(data["samples"]) + 1  # (the third part is 3, unless something's called that already)
        name = str(name or "").strip()[:40] or next(str(i) for i in range(at, at + len(names) + 1) if str(i) not in names)
        data["samples"].append({"id": data["snext"], "name": name})
        data["snext"] += 1
        return self._balloon_done(data, [], {"part": data["samples"][-1]["id"]})

    def op_balloon_sample(self, lot, how="every", n=None, last=True):
        """The parts of a lot to inspect (balloons.sample): a part for each, named by its place in the lot (#1, #6...),
        and the job's inspection frequency and number of parts said so. Parts already there by those names stay."""
        from . import report
        places = balloons.sample(lot, how, n, last)
        data = self._insp()
        names = {s["name"] for s in data["samples"]}
        new = [f"#{k}" for k in places if f"#{k}" not in names]
        if len(names) + len(new) > report.MAX_PARTS:
            raise ValueError(f"That's {len(places)} parts to inspect: the report holds up to {report.MAX_PARTS}. Sample fewer.")
        self._snapshot()
        for name in new:
            data["samples"].append({"id": data["snext"], "name": name})
            data["snext"] += 1
        info = data.setdefault("info", {})
        info["frequency"] = balloons.frequency(lot, how, n, last)
        info["parts"] = max(int(info.get("parts") or 0), len(data["samples"]))
        return self._balloon_done(data, [], {"places": places, "added": len(new)})

    def op_balloon_part_edit(self, id, name):
        data = self._insp()
        s = next((s for s in data["samples"] if s["id"] == int(id)), None)
        if s is None or not str(name or "").strip():
            raise ValueError("That part isn't there any more." if s is None else "A part needs a name or a number.")
        self._snapshot()
        s["name"] = str(name).strip()[:40]
        return self._balloon_done(data, [])

    def op_balloon_part_delete(self, id):
        """Take a part out, with what it measured."""
        data = self._insp()
        if not any(s["id"] == int(id) for s in data["samples"]):
            return self._answer([], result=self._balloon_out(data))
        self._snapshot()
        data["samples"] = [s for s in data["samples"] if s["id"] != int(id)]
        for r in data["results"].values():
            r.pop(str(int(id)), None)
        return self._balloon_done(data, [])

    def op_balloon_result(self, key, part, value):
        """What a part measured for a characteristic. key: the row (a characteristic's id, or id.2 for the second
        place of a multiplied one); value: a number, Pass or Fail, a few words, or "" to take it out."""
        data = self._insp()
        key, part = str(key), str(int(part))
        if key not in {k for c in data["chars"] for k in balloons.row_keys(c)} or part not in {str(s["id"]) for s in data["samples"]}:
            raise ValueError("That balloon or that part isn't there any more.")
        value = balloons.result(value)
        if (data["results"].get(key) or {}).get(part, "") == value:
            return self._answer([], result=self._balloon_out(data))
        self._snapshot()
        row = data["results"].setdefault(key, {})
        if value == "":
            row.pop(part, None)
        else:
            row[part] = value
        return self._balloon_done(data, [])

    def _labels(self, data):
        """Each results row by the number it's known by: 2, 2.1, or 3.2 for the second place of a multiplied 3."""
        out = {}
        for c in data["chars"]:
            keys = balloons.row_keys(c)
            if len(keys) == 1:
                out[balloons.label(c)] = keys[0]
            else:
                for k, key in enumerate(keys, 1):
                    out[f"{balloons.label(c)}.{k}"] = key
        return out

    def op_balloon_import(self, path, head=None, key=None, values=None, part=None, preview=False, into=None):
        """Results from another program's export (kernel/resultsfile.py), matched to the balloons by number.
        preview: the file's first rows and a guess at which columns are what, to check: {"rows", "guess", "labels"}.
        Else key (the balloon number column), values (columns of measurements: in the wide shape each is a part,
        named by its heading; in the long shape, the one value column) and part (the long shape's part column) say
        how to read it. A part already in the list by that name gets the results; another is added. into: a part's id,
        for the one value column of the wide shape to go into it (whatever the column is called)."""
        from . import resultsfile
        data = self._insp()
        if not data["chars"]:
            raise ValueError("There are no balloons to match results to yet.")
        rows = resultsfile.table(path)
        labels = self._labels(data)
        if preview:
            return {"rows": rows[:400], "count": len(rows), "guess": resultsfile.guess(rows, labels), "name": Path(path).name}
        if key is None or not values:
            raise ValueError("Say which column has the balloon numbers and which have the measurements.")
        key, values = int(key), [int(v) for v in values]
        head = None if head is None else int(head)
        part = None if part is None else int(part)
        cell = lambda r, c: r[c] if c < len(r) else ""  # noqa: E731
        body = [r for i, r in enumerate(rows) if i != head and resultsfile.label(cell(r, key)) in labels]
        unmatched = sorted({resultsfile.label(cell(r, key)) or cell(r, key) for i, r in enumerate(rows)
                            if i != head and (head is None or i > head) and cell(r, key) and resultsfile.label(cell(r, key)) not in labels})
        if not body:
            raise ValueError("None of the rows name a balloon on this print. Check which column has the balloon numbers.")
        self._snapshot()
        names = {s["name"]: s for s in data["samples"]}

        def part_id(name):
            name = (str(name).strip() or "?")[:40]
            if name not in names:
                names[name] = {"id": data["snext"], "name": name}
                data["samples"].append(names[name])
                data["snext"] += 1
            return str(names[name]["id"])

        count, parts = 0, set()
        for r in body:
            row = labels[resultsfile.label(cell(r, key))]
            for c in values[:1] if part is not None else values:
                v = balloons.result(cell(r, c))
                if v == "":
                    continue
                if into is not None and part is None and len(values) == 1 and any(s["id"] == int(into) for s in data["samples"]):
                    pid = str(int(into))
                else:
                    name = cell(r, part) if part is not None else (cell(rows[head], c) if head is not None and cell(rows[head], c) else f"Column {c + 1}")
                    pid = part_id(name)
                parts.add(pid)
                data["results"].setdefault(row, {})[pid] = v
                count += 1
        return self._balloon_done(data, [], {"imported": count, "parts": len(parts), "unmatched": unmatched[:40], "unmatched_count": len(unmatched)})

    def op_balloon_results_clear(self, parts=True):
        """Start over for another lot: every result out, and (parts) the parts they were measured on."""
        data = self._insp()
        if not data["results"] and not (parts and data["samples"]):
            return self._answer([], result=self._balloon_out(data))
        self._snapshot()
        data["results"] = {}
        if parts:
            data["samples"], data["snext"] = [], 1
        return self._balloon_done(data, [])

    # ================================================================== a new revision of the print
    def _other_list(self, path):
        """The inspection list kept in another PDF (the print's last revision, ballooned): its characteristics, each
        with "page" and "at": where its callout's middle is, as a share of the sheet as it's shown (0 to 1); its sheet
        id, production issues and photos ("pictures": {photo id: the picture's bytes})."""
        import pymupdf
        if Path(path).resolve() == Path(self.path).resolve():
            raise ValueError("That's this print. Choose the last revision's ballooned PDF.")
        try:
            doc = pymupdf.open(path)
        except Exception:
            raise ValueError(f"{Path(path).name} can't be opened as a PDF.") from None
        try:
            if doc.needs_pass:
                raise ValueError(f"{Path(path).name} needs a password.")
            kind, val = doc.xref_get_key(doc.pdf_catalog(), KEY)
            data = None
            if kind == "xref":
                try:
                    data = json.loads(doc.xref_stream(int(val.split()[0])).decode("utf-8"))
                except Exception:
                    data = None
            if not isinstance(data, dict) or not data.get("chars"):
                raise ValueError(f"{Path(path).name} has no balloons from SolidSmurfs to carry over.")
            where = {}
            for i, pg in enumerate(doc):
                for a in pg.annots(types=[pymupdf.PDF_ANNOT_CIRCLE]):
                    name = a.info.get("id", "")
                    if a.info.get("subject") == SUBJECT and name.startswith("ssb-"):
                        where.setdefault(name[4:], i)
            out = []
            for c in data["chars"]:
                page = where.get(str(c["id"]), c.get("page"))
                if page is None or not 0 <= page < doc.page_count:
                    continue
                pg = doc[page]
                x, y, w, h = self._out(pg, c["box"])
                out.append({**c, "page": page, "at": ((x + w / 2) / pg.rect.width, (y + h / 2) / pg.rect.height)})
            pictures = {}
            for p in data.get("photos") or []:
                try:
                    pictures[p["id"]] = doc.embfile_get(f"ssp-{p['id']}")
                except Exception:
                    pass
            return {"chars": out, "info": data.get("info") or {}, "views": data.get("views") or [], "sid": data.get("sid"),
                    "issues": data.get("issues") or [], "photos": [p for p in data.get("photos") or [] if p["id"] in pictures],
                    "pictures": pictures}
        finally:
            doc.close()

    def op_balloon_carry(self, path, extra=None, notes=True, want=None, split=False):
        """A new revision of a print, ballooned from the last one's (path: its ballooned PDF): this print is read again
        as Auto Balloon does, and each characteristic found that the last revision has keeps its balloon number, its
        description, gage and note. Found the same: unchanged. Found where it was, written otherwise: changed (its
        note says what it was, and it's to be reviewed). New ones are numbered after the last revision's highest;
        the numbers of those that are gone are left out. The job's details come over too. One step to undo."""
        old = self._other_list(path)
        before = len(self.undo)
        self.op_balloon_auto(extra=extra, notes=notes, want=want, split=split)
        data = self._insp()
        if not data["chars"]:
            return self._answer([], result={**self._balloon_out(data), "carried": None})
        if len(self.undo) == before:
            self._snapshot()
        norm = lambda t: re.sub(r"\s+", "", str(t or "")).upper()  # noqa: E731
        place = {}
        for c in data["chars"]:
            pg = self.fz[c["page"]]
            x, y, w, h = self._out(pg, c["box"])
            place[c["id"]] = ((x + w / 2) / pg.rect.width, (y + h / 2) / pg.rect.height)
        dist = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1])  # noqa: E731
        pairs, used_new, used_old = [], set(), set()
        # the same requirement on the same sheet, nearest first; then one of the same kind where it was
        for same, reach in ((True, 0.35), (False, 0.06)):
            cands = sorted((dist(place[n["id"]], o["at"]), k, j) for k, o in enumerate(old["chars"]) for j, n in enumerate(data["chars"])
                           if o["page"] == n["page"] and (norm(o["text"]) == norm(n["text"]) if same else o.get("kind") == n.get("kind"))
                           and dist(place[n["id"]], o["at"]) <= reach)
            for d, k, j in cands:
                if k in used_old or j in used_new:
                    continue
                used_old.add(k)
                used_new.add(j)
                pairs.append((old["chars"][k], data["chars"][j], same))
        kept, changed = [], []
        for o, n, same in pairs:
            n["n"], n["sub"] = o["n"], o.get("sub")
            for k in ("desc", "gage", "note", "tags"):
                if o.get(k):
                    n[k] = o[k]
            if o.get("mult") and (o.get("count") or 1) == (n.get("count") or 1):
                n["mult"] = True
            if same:
                n["reviewed"] = o.get("reviewed")
                kept.append(n)
            else:
                n["reviewed"] = None
                n["note"] = (f"{n['note']}  " if n.get("note") else "") + f"Was {o['text']} on the last revision"
                changed.append((o, n))
        top = max(o["n"] for o in old["chars"])
        added = [n for j, n in enumerate(data["chars"]) if j not in used_new]
        for k, n in enumerate(sorted(added, key=lambda c: (c["page"], c["n"], c.get("sub") or 0)), 1):
            n["n"], n["sub"], n["reviewed"] = top + k, None, None
            n["note"] = "New on this revision"
        # two balloons can't share a number unless they're one callout's: the second such keeps going after the top
        seen = set()
        for c in sorted(data["chars"], key=lambda c: (c["n"], c.get("sub") or 0)):
            key = (c["n"], c.get("sub"))
            if key in seen:
                top = max(top, max(x["n"] for x in data["chars"])) + 1
                c["n"], c["sub"] = top, None
            seen.add(key)
        removed = [o for k, o in enumerate(old["chars"]) if k not in used_old]
        data["chars"].sort(key=lambda c: (c["n"], c.get("sub") or 0))
        info = {**old["info"], **{k: v for k, v in (data.get("info") or {}).items() if v}}
        data["info"] = info
        if old.get("sid") and not data.get("from"):
            data["from"] = old["sid"]
        carried = self._carry_issues(data, old, {o["id"]: n for o, n, _ in pairs}, Path(path).name)
        label = lambda c: balloons.label(c)  # noqa: E731
        report = {"from": Path(path).name, "kept": len(kept),
                  "changed": [{"n": label(n), "was": o["text"], "now": n["text"]} for o, n in changed],
                  "added": [{"n": label(n), "now": n["text"]} for n in added],
                  "removed": [{"n": label(o), "was": o["text"]} for o in removed], "issues": carried}
        return self._balloon_done(data, {c["page"] for c in data["chars"]}, {"carried": report})

    def _carry_issues(self, data, old, same, name):
        """The last revision's production issues not yet resolved (nor hidden) come over, on the balloon that's the
        same one now (or on none, saying which it was), with their photos; and the photos of the characteristics that
        are the same. Returns how many issues came."""
        me, at = who(), _stamp()
        issues, photos = data.setdefault("issues", []), data.setdefault("photos", [])
        nid = max([i["id"] for i in issues], default=0)
        nn = max([i["n"] for i in issues], default=0)
        pid = max([p["id"] for p in photos], default=0)
        moved = {}
        count = 0
        for i in old.get("issues") or []:
            if i.get("hidden") or i.get("status") == "resolved":
                continue
            nid, nn = nid + 1, nn + 1
            now = same.get(i.get("char"))
            moved[i["id"]] = nid
            history = list(i.get("history") or []) + [{"at": at, "who": me, "what": f"Carried over from {old.get('sid') or name} (#{i['n']} there)"}]
            issues.append({**i, "id": nid, "n": nn, "char": now["id"] if now else None,
                           "label": balloons.label(now) if now else (f"was {i['label']}" if i.get("label") else None),
                           "history": history, "delete": None})
            count += 1
        for p in old.get("photos") or []:
            if p["on"] == "issue" and p["of"] in moved:
                of = moved[p["of"]]
            elif p["on"] == "char" and p["of"] in same:
                of = same[p["of"]]["id"]
            else:
                continue
            pid += 1
            self.fz.embfile_add(f"ssp-{pid}", old["pictures"][p["id"]], filename=f"ssp-{pid}.jpg", desc="SolidSmurfs inspection photo")
            photos.append({**p, "id": pid, "of": of})
        return count

    def op_balloon_tag(self, ids, tag, on=True):
        """Put an inspection tag on these characteristics, or take it off."""
        if tag not in TAGS:
            raise ValueError(f"There's no tag {tag}.")
        data = self._insp()
        want = {int(i) for i in ids}
        self._snapshot()
        for c in data["chars"]:
            if c["id"] in want:
                c["tags"] = _tags(set(c.get("tags") or []) | {tag} if on else set(c.get("tags") or []) - {tag})
        return self._balloon_done(data, [])

    def op_balloon_reviewed(self, ids, on=True):
        """Mark these characteristics as checked against the print, or not."""
        data = self._insp()
        want = {int(i) for i in ids}
        mine = [c for c in data["chars"] if c["id"] in want and bool(c.get("reviewed")) != bool(on)]
        if not mine:
            return self._answer([], result=self._balloon_out(data))
        self._snapshot()
        for c in mine:
            c["reviewed"] = bool(on)
        return self._balloon_done(data, [])

    def op_balloon_delete(self, ids):
        data = self._insp()
        gone = {int(i) for i in ids}
        pages = [c["page"] for c in data["chars"] if c["id"] in gone]
        if not pages:
            return self._answer([], result=self._balloon_out(data))
        self._snapshot()
        data["chars"] = [c for c in data["chars"] if c["id"] not in gone]
        return self._balloon_done(data, pages)

    def op_balloon_renumber(self, order="list"):
        """Number the balloons 1, 2, 3, closing the gaps deleted ones left; those sharing a number stay together as
        .1, .2, .3 (one left alone under its number loses its sub-number). order: "list" keeps the order they're in;
        "rows" goes across the sheet a row at a time, "columns" down it a column at a time, "clockwise" round from
        twelve o'clock about the middle of the view. With views, the sheet is numbered view by view in their order
        (the balloons in none after them), each from its start number if that's further on."""
        if order not in ORDERS:
            raise ValueError(f"Renumber in which order? One of {', '.join(ORDERS)}.")
        data = self._insp()
        self._snapshot()
        groups = self._groups(data["chars"])
        if order != "list" or data["views"]:
            groups = self._ordered(data, groups, order)
        data["chars"] = self._numbered(groups, self._starts(data, groups))
        return self._balloon_done(data, [c["page"] for c in data["chars"]])

    def _ordered(self, data, groups, order):
        """The groups (one callout's balloons each) sheet by sheet, view by view, then in the order asked for, by
        where their first balloon is on the sheet as it's shown."""
        views = {v["id"]: k for k, v in enumerate(data["views"])}
        rank = {id(g): k for k, g in enumerate(groups)}
        where = {}
        for g in groups:
            c = g[0]
            view = self._view_of(data, c)
            x, y = self._pt_out(self.fz[c["page"]], c["at"])
            where[id(g)] = (c["page"], views[view["id"]] if view else len(views), view, x, y, c["r"])
        out = []
        for key in sorted({w[:2] for w in where.values()}):
            mine = [g for g in groups if where[id(g)][:2] == key]
            if order == "list":
                out += sorted(mine, key=lambda g: rank[id(g)])
                continue
            r = statistics.median(where[id(g)][5] for g in mine)
            band = 4.0 * r
            if order in ("rows", "columns"):
                a, b = (4, 3) if order == "rows" else (3, 4)  # (across: y bands then x; down: x bands then y)
                mine.sort(key=lambda g: (where[id(g)][a], where[id(g)][b]))
                lines, last = [], None
                for g in mine:
                    if last is None or where[id(g)][a] - last > band:
                        lines.append([])
                        last = where[id(g)][a]
                    lines[-1].append(g)
                out += [g for ln in lines for g in sorted(ln, key=lambda g: where[id(g)][b])]
            else:
                view = where[id(mine[0])][2]
                if view:
                    vx, vy, vw, vh = self._out(self.fz[key[0]], view["rect"])
                    cx, cy = vx + vw / 2, vy + vh / 2
                else:
                    cx = statistics.fmean(where[id(g)][3] for g in mine)
                    cy = statistics.fmean(where[id(g)][4] for g in mine)
                angle = lambda g: (math.atan2(where[id(g)][3] - cx, cy - where[id(g)][4]) + 2 * math.pi) % (2 * math.pi)  # noqa: E731
                out += sorted(mine, key=lambda g: (round(angle(g), 3), math.hypot(where[id(g)][3] - cx, where[id(g)][4] - cy)))
        return out

    def _starts(self, data, groups):
        """The number each group's view asks to start from, given to the view's first group."""
        out, seen = {}, set()
        for k, g in enumerate(groups):
            view = self._view_of(data, g[0])
            if view and view["id"] not in seen:
                seen.add(view["id"])
                if view.get("start"):
                    out[k] = int(view["start"])
        return out

    # ================================================================== views
    def op_balloon_view_add(self, page, rect, name=None):
        """A view: a box ([x, y, w, h] as the page is shown) around one of the drawing's views. Its balloons take its
        color, and Renumber numbers it on its own."""
        import pymupdf
        pg, data = self._page(page), self._insp()
        x, y, w, h = [float(v) for v in rect]
        if w < 6 or h < 6:
            raise ValueError("Drag a box around the view.")
        box = pymupdf.Rect(x, y, x + w, y + h) * pg.derotation_matrix
        box.normalize()
        self._snapshot()
        k = len(data["views"])
        view = {"id": data["vnext"], "name": str(name or "").strip()[:60] or f"View {k + 1}", "page": int(page),
                "rect": [round(v, 2) for v in box], "color": VIEW_COLORS[k % len(VIEW_COLORS)], "start": None}
        data["views"].append(view)
        data["vnext"] += 1
        return self._balloon_done(data, [int(page)], {"view": view["id"]})

    def op_balloon_view_edit(self, id, name=None, color=None, start=None, rect=None, move=None):
        """Change a view: its name, color ("#rrggbb"), start number ("" or 0: none), box ([x, y, w, h] as shown), or
        its place among the views (move: -1 up, 1 down)."""
        import pymupdf
        data = self._insp()
        v = next((v for v in data["views"] if v["id"] == int(id)), None)
        if v is None:
            raise ValueError("That view isn't there any more.")
        self._snapshot()
        if name is not None and str(name).strip():
            v["name"] = str(name).strip()[:60]
        if color is not None and re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
            v["color"] = str(color).lower()
        if start is not None:
            v["start"] = int(start) if str(start).strip() not in ("", "0") else None
        if rect is not None:
            x, y, w, h = [float(t) for t in rect]
            box = pymupdf.Rect(x, y, x + w, y + h) * self.fz[v["page"]].derotation_matrix
            box.normalize()
            v["rect"] = [round(t, 2) for t in box]
        if move:
            i = data["views"].index(v)
            j = min(max(i + int(move), 0), len(data["views"]) - 1)
            data["views"].insert(j, data["views"].pop(i))
        return self._balloon_done(data, [v["page"]])

    def op_balloon_view_delete(self, id):
        data = self._insp()
        v = next((v for v in data["views"] if v["id"] == int(id)), None)
        if v is None:
            return self._answer([], result=self._balloon_out(data))
        self._snapshot()
        data["views"].remove(v)
        return self._balloon_done(data, [v["page"]])

    def op_balloon_clear(self):
        data = self._insp()
        pages = [c["page"] for c in data["chars"]]
        if not pages:
            return self._answer([], result=self._balloon_out(data))
        self._snapshot()
        data["chars"] = []
        return self._balloon_done(data, pages)

    def op_balloon_tols(self, tols):
        """The title block's tolerances by decimals ({"1": .03, "2": .01, "3": .005, "4": .0005, "angle": .5}), applied
        to every size with none of its own."""
        data = self._insp()
        self._snapshot()
        data["tols"] = {k: float(v) for k, v in (tols or {}).items() if k in ("0", "1", "2", "3", "4", "angle") and v not in (None, "") and float(v) > 0}
        for c in data["chars"]:
            balloons.limits(c, data["tols"])
        return self._balloon_done(data, [])

    def op_balloon_status(self, status, note=None):
        """Release the list ("released"), mark it superseded by the next revision ("superseded"), or put it back to
        "draft" to change it (which needs a note saying why). Each change is logged."""
        if status not in STATUSES:
            raise ValueError(f"A list is {', '.join(STATUSES)}, not {status}.")
        data = self._insp()
        was = data.get("status") or "draft"
        if status == was:
            return self._balloon_done(data, [])
        if status == "draft" and not str(note or "").strip():
            raise ValueError("Say why it goes back to draft: a change note is needed.")
        if status == "released" and not data["chars"]:
            raise ValueError("There's nothing to release: balloon the print first.")
        self._snapshot()
        data["status"] = status
        data["log"] = (data.get("log") or []) + [{"at": _stamp(), "who": who(), "field": "status", "old": was, "new": status,
                                                 "note": str(note or "").strip()[:1000]}]
        return self._balloon_done(data, [])

    # ================================================================== production issues
    @staticmethod
    def _issue(data, id):
        for i in data.get("issues") or []:
            if i["id"] == int(id):
                return i
        raise ValueError("That issue is gone.")

    def op_balloon_issue_add(self, char=None, title="", notes="", tags=None, job=None):
        """A new production issue, about a balloon (char: its characteristic's id) or none. Its job number is the
        sheet's unless another is given."""
        data = self._insp()
        if char is not None:
            c = self._balloon_find(data, char)
        self._snapshot()
        issues = data.setdefault("issues", [])
        id = max([i["id"] for i in issues], default=0) + 1
        n = max([i["n"] for i in issues], default=0) + 1
        me, at = who(), _stamp()
        issues.append({"id": id, "n": n, "char": c["id"] if char is not None else None, "label": balloons.label(c) if char is not None else None,
                       "title": str(title or "").strip()[:200], "notes": str(notes or "").strip()[:4000], "tags": _issue_tags(tags),
                       "job": str(job if job is not None else (data.get("info") or {}).get("job", "")).strip()[:60],
                       "status": "open", "route": None, "hidden": False, "delete": None, "by": me, "at": at,
                       "history": [{"at": at, "who": me, "what": "Added"}]})
        return self._balloon_done(data, [], {"issue": id})

    def op_balloon_issue_edit(self, id, **o):
        """Change an issue's title, notes, tags, job number, or the balloon it's about (char: an id, or None)."""
        data = self._insp()
        i = self._issue(data, id)
        if o.get("char") is not None:
            c = self._balloon_find(data, o["char"])
        self._snapshot()
        said = []
        for k, most in (("title", 200), ("notes", 4000), ("job", 60)):
            if k in o and o[k] is not None and str(o[k]).strip() != i.get(k, ""):
                i[k] = str(o[k]).strip()[:most]
                said.append({"title": "Title", "notes": "Notes", "job": "Job number"}[k])
        if "tags" in o and _issue_tags(o["tags"]) != i.get("tags"):
            i["tags"] = _issue_tags(o["tags"])
            said.append("Tags")
        if "char" in o and (o["char"] if o["char"] is None else int(o["char"])) != i.get("char"):
            i["char"], i["label"] = (c["id"], balloons.label(c)) if o["char"] is not None else (None, None)
            said.append("Balloon")
        if said:
            i["history"].append({"at": _stamp(), "who": who(), "what": "Changed " + ", ".join(said).lower()})
        return self._balloon_done(data, [])

    def op_balloon_issue_act(self, id, act, route=None, reason=None):
        """What's done with an issue: "fixed" (a machinist's fixed it: ready for a lead), "resolve" (route: "machinist",
        a machinist's fix, or "troubleshooting", moved there), "reopen", "hide", "show", "delete" (hidden and asked to
        be deleted for good, with a reason), "keep" (just hidden again: no longer to be deleted), "purge" (deleted for
        good: only one asked to be deleted)."""
        if act not in ISSUE_ACTS:
            raise ValueError(f"Nothing is done to an issue by {act}.")
        data = self._insp()
        i = self._issue(data, id)
        self._snapshot()
        me, at = who(), _stamp()
        what = None
        if act == "fixed":
            if i["status"] == "resolved":
                raise ValueError("It's resolved already.")
            i["status"], what = "fixed", "Fixed, ready for lead"
        elif act == "resolve":
            if route not in ("machinist", "troubleshooting"):
                raise ValueError("Say how it's resolved: a machinist's fix, or moved to troubleshooting.")
            i["status"], i["route"] = "resolved", route
            what = "Resolved: machinist fix" if route == "machinist" else "Resolved: moved to troubleshooting"
        elif act == "reopen":
            i["status"], i["route"], what = "open", None, "Reopened"
        elif act == "hide":
            i["hidden"], what = True, "Hidden"
        elif act == "show":
            i["hidden"], i["delete"], what = False, None, "Shown again"
        elif act == "delete":
            if not str(reason or "").strip():
                raise ValueError("Say why it's to be deleted.")
            i["hidden"], i["delete"] = True, {"reason": str(reason).strip()[:500], "who": me, "at": at}
            what = f"Asked to delete: {i['delete']['reason']}"
        elif act == "keep":
            i["delete"], what = None, "Switched to hidden: not to be deleted"
        elif act == "purge":
            if not i.get("delete"):
                raise ValueError("Only an issue asked to be deleted is deleted for good: Delete it first.")
            data["issues"] = [x for x in data["issues"] if x is not i]
            for p in [p for p in data.get("photos") or [] if p["on"] == "issue" and p["of"] == i["id"]]:
                self._photo_drop(data, p)
        if what:
            i["history"].append({"at": at, "who": me, "what": what})
        return self._balloon_done(data, [])

    # ================================================================== roles
    def op_balloon_roles(self, action="status", password=None, role=None, new=None, current=None):
        """The roles on this PC (kernel/roles.py): "status"; "unlock" (password); "lock"; "set" (role, new, current)."""
        from . import roles
        if action == "unlock":
            roles.unlock(str(password or ""))
        elif action == "lock":
            roles.lock()
        elif action == "set":
            return roles.set_password(role, new, current)
        return roles.status()

    # ================================================================== searching
    def op_balloon_search(self, query, here=False):
        """Characteristics and production issues matching every word of the query: on this print (here), or on
        every ballooned print saved on this computer, this one as it is now first (kernel/inspindex.py)."""
        from . import inspindex
        hits = inspindex.search(query, self._insp(), self.path)
        return [x for x in hits if x["here"]] if here else hits

    # ================================================================== photos
    def _photo_drop(self, data, p):
        try:
            self.fz.embfile_del(f"ssp-{p['id']}")
        except Exception:
            pass
        data["photos"] = [x for x in data.get("photos") or [] if x is not p]

    def _photo(self, data, id):
        for p in data.get("photos") or []:
            if p["id"] == int(id):
                return p
        raise ValueError("That photo is gone.")

    def op_balloon_photo_add(self, on, of, image, name=""):
        """A photo on a characteristic (on "char") or an issue (on "issue"), of: its id; image: the picture as a data URL
        or base64. It's kept as a JPEG no more than PHOTO_MOST pixels along."""
        import pymupdf
        data = self._insp()
        if on == "char":
            self._balloon_find(data, of)
        elif on == "issue":
            self._issue(data, of)
        else:
            raise ValueError("A photo goes on a characteristic or an issue.")
        raw = base64.b64decode(str(image).split(",", 1)[-1])
        try:
            pix = pymupdf.Pixmap(raw)
        except Exception:
            raise ValueError("That isn't a picture this can read (a JPEG, PNG, GIF, BMP or TIFF).")
        if pix.alpha or pix.n not in (1, 3):
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)  # (no transparency in a JPEG)
            if pix.alpha:
                pix = pymupdf.Pixmap(pix, 0)
        k = PHOTO_MOST / max(pix.width, pix.height)
        if k < 1:
            pix = pymupdf.Pixmap(pix, round(pix.width * k), round(pix.height * k), None)
        jpg = pix.tobytes("jpg", jpg_quality=85)
        self._snapshot()
        photos = data.setdefault("photos", [])
        id = max([p["id"] for p in photos], default=0) + 1
        self.fz.embfile_add(f"ssp-{id}", jpg, filename=f"ssp-{id}.jpg", desc="SolidSmurfs inspection photo")
        photos.append({"id": id, "on": on, "of": int(of), "name": str(name or "")[:120], "w": pix.width, "h": pix.height,
                       "at": _stamp(), "by": who(), "marks": []})
        return self._balloon_done(data, [], {"photo": id})

    def op_balloon_photo(self, id):
        """A photo's picture, as a data URL (it isn't changed)."""
        data = self._insp()
        p = self._photo(data, id)
        jpg = self.fz.embfile_get(f"ssp-{p['id']}")
        return {**p, "url": "data:image/jpeg;base64," + base64.b64encode(jpg).decode("ascii")}

    def op_balloon_photo_marks(self, id, marks):
        """What's drawn on a photo, all of it (in its pixels): [{"t": pen, line, arrow, oval, rect or text, "c": color,
        "w": width, "pts" / "a", "b" / "at", "s", "size"}]."""
        data = self._insp()
        p = self._photo(data, id)
        out = []
        for m in marks or []:
            if not isinstance(m, dict) or m.get("t") not in MARK_KINDS:
                continue
            keep = {"t": m["t"], "c": str(m.get("c") or "#e02020")[:9], "w": max(min(float(m.get("w") or 4), 60), 1)}
            num = lambda q: [round(float(q[0]), 1), round(float(q[1]), 1)]  # noqa: E731
            if m["t"] in ("oval", "rect", "lasso") and m.get("fill") in MARK_FILLS[1:]:
                keep["fill"] = m["fill"]
            if m["t"] in ("pen", "lasso"):
                keep["pts"] = [num(q) for q in (m.get("pts") or [])[:4000]]
            elif m["t"] in ("text", "stamp"):
                keep.update(at=num(m["at"]), s=str(m.get("s") or "")[:300], size=max(min(float(m.get("size") or 48), 400), 6))
            else:
                keep.update(a=num(m["a"]), b=num(m["b"]))
            out.append(keep)
        self._snapshot()
        p["marks"] = out
        return self._balloon_done(data, [])

    def op_balloon_photo_delete(self, id):
        data = self._insp()
        p = self._photo(data, id)
        self._snapshot()
        self._photo_drop(data, p)
        return self._balloon_done(data, [])

    # ================================================================== the inspection report
    def op_balloon_info(self, info, note=None):
        """What the report says about the job ({"part", "name", "rev", "customer", "job", "lot", "fai", "inspector",
        "parts": how many parts' results it has room for}), kept with the list. A detail that was filled in and is
        changed (or emptied) needs a note saying why: each change is logged with it, who and when."""
        from . import report
        data = self._insp()
        was, now = data.get("info") or {}, report.clean_info(info)
        changed = [(k, str(was[k]), str(now.get(k, ""))) for k, _, _ in report.INFO if was.get(k) not in (None, "") and str(was[k]) != str(now.get(k, ""))]
        if changed and not str(note or "").strip():
            raise ValueError("A job detail that was filled in has changed: a change note is needed.")
        self._snapshot()
        data["info"] = now
        at = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        data["log"] = (data.get("log") or []) + [{"at": at, "who": who(), "field": k, "old": o, "new": n, "note": str(note).strip()[:1000]}
                                                 for k, o, n in changed]
        return self._balloon_done(data, [])

    def _printing(self, data, printing):
        """The report PDF's settings from the window's, with the photos' and the logo's pictures."""
        o = dict(printing or {})
        if o.get("photos") in ("small", "medium", "large"):
            o["pictures"] = {}
            for p in data.get("photos") or []:
                try:
                    o["pictures"][p["id"]] = self.fz.embfile_get(f"ssp-{p['id']}")
                except Exception:
                    pass
        if o.get("logo"):
            try:
                o["logo"] = base64.b64decode(str(o["logo"]).split(",", 1)[-1])
            except Exception:
                o["logo"] = None
        o["who"] = who()
        return o

    def op_balloon_report_preview(self, parts=None, footer="", printing=None, most=8, info=None):
        """The report's PDF as it would be printed, as pictures of its pages to look at (no more than `most`):
        {"pages": [data URLs], "count": how many pages in all}. info: the job's details as typed, not saved yet."""
        import os
        import tempfile
        import pymupdf
        from . import reportpdf
        data = self._insp()
        if not data["chars"]:
            raise ValueError("There are no balloons to report yet.")
        if info:
            from . import report
            data["info"] = report.clean_info(info)
        parts = parts or (data.get("info") or {}).get("parts") or 1
        fd, tmp = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            count = reportpdf.write(tmp, data, Path(self.path).name, parts, footer, self._printing(data, printing))
            doc = pymupdf.open(tmp)
            try:
                pages = ["data:image/png;base64," + base64.b64encode(doc[i].get_pixmap(dpi=60).tobytes("png")).decode("ascii")
                         for i in range(min(count, int(most)))]
            finally:
                doc.close()
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return {"pages": pages, "count": count}

    def op_balloon_report(self, path, parts=None, layout=None, footer="", printing=None):
        """Write the inspection report as an Excel workbook (kernel/report.py). layout: "sheet", the page to print
        and fill in (five parts to a table), or "list", the list with its limits, a column for each part's results
        with Pass / Fail worked out from them, and AS9102 Form 3. parts: how many parts' results to make room for
        (else what the list's details say). footer: the shop's own lines for the bottom of the sheet.
        The inspection sheet is written as a PDF too (kernel/reportpdf.py), beside the workbook under its name.
        printing: what else the PDF has ({"header", "issues", "photos": "small" / "medium" / "large", "logo": a picture
        as a data URL}): see reportpdf.write."""
        from . import report, xlsx
        data = self._insp()
        if not data["chars"]:
            raise ValueError("There are no balloons to report yet.")
        parts = parts or (data.get("info") or {}).get("parts") or 1
        try:
            xlsx.write(path, report.build(data, Path(self.path).name, parts, layout if layout in ("sheet", "list") else None, footer,
                                          with_issues=bool((printing or {}).get("issues"))))
        except PermissionError:
            raise ValueError(f"{Path(path).name} can't be written: it's open in Excel, or the folder is read-only.") from None
        from . import reportpdf
        pdf = Path(path).with_suffix(".pdf")
        if pdf.resolve() == Path(self.path).resolve():
            raise ValueError(f"The report's PDF would take the print's own name, {pdf.name}. Save the report under another name.")
        try:
            pages = reportpdf.write(str(pdf), data, Path(self.path).name, parts, footer, self._printing(data, printing))
        except (PermissionError, OSError) as e:
            if not isinstance(e, PermissionError) and "ermission" not in str(e) and "open" not in str(e):
                raise
            raise ValueError(f"The workbook was written, but {pdf.name} can't be: it's open in another program.") from None
        return {"path": str(path), "pdf": str(pdf), "pages": pages, "count": len(data["chars"]), "parts": int(parts)}
