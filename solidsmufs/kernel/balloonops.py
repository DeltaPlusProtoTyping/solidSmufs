"""Balloons on a PDF print and the inspection list behind them: the PDF editor's part (PdfEditor's balloon_* edits).

What there is to inspect is read by kernel/balloons.py. Here it's kept in the PDF itself, two ways at once:
- the list (every characteristic's requirement, limits and balloon number) as JSON in a stream the document's
  catalog names (/SolidSmurfsInspection): no other program shows it, and it comes back when the file is opened again;
- each balloon as a real circle comment with its number drawn in it, so the saved print shows its balloons in any
  PDF reader, and prints with them.
Several characteristics of one callout share a number and are told apart by a sub-number: 2.1, 2.2, 2.3 ("n" and
"sub" in the list; a balloon alone under its number has no sub).
The comments are made again from the list after every change. A balloon whose comment is gone (its page was deleted,
or it was removed in another program) leaves the list; one whose page moved follows it.
Places in the list are in the page's own points (not turned); the window gets and gives them as the page is shown.
"""

import json
import math
import re
import statistics
from pathlib import Path

from . import balloons

KEY, FONT_KEY, SUBJECT = "SolidSmurfsInspection", "SolidSmurfsBalloonFont", "Balloon"
RED = (0.82, 0.07, 0.07)
FIELDS = ("kind", "text", "count", "nominal", "plus", "minus", "lo", "hi", "places", "tol", "desc", "gage")


class BalloonOps:
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
            return {"v": 1, "chars": [], "tols": {}, "unit": None, "next": 1}
        where = {}
        for i, pg in enumerate(doc):
            for a in pg.annots(types=[pymupdf.PDF_ANNOT_CIRCLE]):
                name = a.info.get("id", "")
                if a.info.get("subject") == SUBJECT and name.startswith("ssb-"):
                    where[name[4:]] = i
        data["chars"] = [{**c, "page": where[str(c["id"])]} for c in data["chars"] if str(c["id"]) in where]
        data["chars"].sort(key=lambda c: (c["n"], c.get("sub") or 0))
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
    def _numbered(groups):
        """Number the groups 1, 2, 3 and those within one .1, .2, .3: the list in that order."""
        chars = []
        for i, g in enumerate(groups, 1):
            for j, c in enumerate(g, 1):
                c["n"], c["sub"] = i, j if len(g) > 1 else None
                chars.append(c)
        return chars

    def _insp_write(self, data):
        doc = self.fz
        cat = doc.pdf_catalog()
        kind, val = doc.xref_get_key(cat, KEY)
        if kind == "xref":
            x = int(val.split()[0])
        else:
            x = doc.get_new_xref()
            doc.update_object(x, "<<>>")
            doc.xref_set_key(cat, KEY, f"{x} 0 R")
        doc.update_stream(x, json.dumps(data, separators=(",", ":")).encode("utf-8"))

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

    def _balloon_sync(self, data, pages):
        """Make the balloons' comments on these pages again from the list."""
        import pymupdf
        from .pdfedit import author
        doc, font, who = self.fz, self._balloon_font(), author()
        for i in sorted({int(p) for p in pages if 0 <= int(p) < doc.page_count}):
            pg = doc[i]
            for a in [a for a in pg.annots(types=[pymupdf.PDF_ANNOT_CIRCLE]) if a.info.get("subject") == SUBJECT]:
                pg.delete_annot(a)
            for c in data["chars"]:
                if c["page"] != i:
                    continue
                (x, y), r = c["at"], c["r"]
                a = pg.add_circle_annot(pymupdf.Rect(x - r, y - r, x + r, y + r))
                a.set_colors(stroke=RED, fill=(1, 1, 1))
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
                more = (f"\nBT /Helv {fs:.2f} Tf {RED[0]} {RED[1]} {RED[2]} rg {cos:.5f} {sin:.5f} {-sin:.5f} {cos:.5f} "
                        f"{sx:.2f} {sy:.2f} Tm ({text}) Tj ET\n")
                doc.update_stream(ap, b"q\n" + doc.xref_stream(ap) + b"Q" + more.encode("ascii"))
                doc.xref_set_key(ap, "Resources", f"<</Font<</Helv {font} 0 R>>>>")

    def _balloon_out(self, data):
        chars = []
        for c in data["chars"]:
            pg = self.fz[c["page"]]
            chars.append({"id": c["id"], "n": c["n"], "sub": c.get("sub"), "label": balloons.label(c), "page": c["page"], "r": c["r"], "box": self._out(pg, c["box"]),
                          "at": self._pt_out(pg, c["at"]), **{k: c.get(k) for k in FIELDS}})
        from . import report
        return {"chars": chars, "tols": data.get("tols") or {}, "unit": data.get("unit"), "labels": balloons.KIND_LABEL,
                "info": data.get("info") or {}, "fields": [[k, label] for k, label, _ in report.INFO], "layouts": report.LAYOUTS}

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
        """The inspection list: {"chars": [{"id", "n", "sub", "label" (what the balloon says: 2, or 2.1), "page", "r", "at": [x, y], "box": [x, y, w, h], "kind",
        "text", "count", "nominal", "plus", "minus", "lo", "hi", "places", "tol"}], "tols", "unit", "labels",
        "info": what the report says about the job, "fields": [[key, label]] it can say}."""
        return self._balloon_out(self._insp())

    def op_balloon_auto(self, extra=None, notes=True):
        """Read every page and balloon what's found, in place of any balloons there are. extra (from the worker):
        {"unit", "pages": {"0": {"frames": [{"box", "text"}], "ocr": [[text, x0, y0, x1, y1]]}}}."""
        old = self._insp()
        read, texts = [], []
        for i, pg in enumerate(self.fz):
            ex = self._extra_page(extra, i)
            lines = self._balloon_lines(pg, ex)
            read.append((pg, lines, ex.get("frames") or []))
            texts += [ln["text"] for ln in lines]
        unit = (extra or {}).get("unit")
        tols = balloons.defaults(texts)
        data = {"v": 1, "chars": [], "tols": tols, "unit": unit, "next": 1, "info": old.get("info") or {}}
        for i, (pg, lines, frames) in enumerate(read):
            size = (pg.rect.width, pg.rect.height)
            items = balloons.read(lines, frames, unit, tols, size, notes=notes)
            if not items:
                continue
            r = balloons.radius(items)
            obstacles = [tuple(ln["box"]) for ln in lines] + [(f["box"][0], f["box"][1], f["box"][0] + f["box"][2], f["box"][1] + f["box"][3]) for f in frames]
            for it, at in zip(items, balloons.place(items, obstacles, size, r, *self._balloon_marks(pg))):
                data["chars"].append({"id": data["next"], "n": data["next"], "page": i, **self._balloon_item(pg, it, at, r)})
                data["next"] += 1
        if not data["chars"] and not old["chars"]:
            return self._answer([], result={**self._balloon_out(data), "found": 0})
        self._snapshot()
        self._insp_write(data)
        pages = {c["page"] for c in data["chars"]} | {c["page"] for c in old["chars"]}
        self._balloon_sync(data, pages)
        return self._answer(sorted(pages), result={**self._balloon_out(data), "found": len(data["chars"])})

    def _balloon_done(self, data, pages, result=None):
        self._insp_write(data)
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
            items = balloons.read(inside, frames, data.get("unit"), data.get("tols") or {}, size, notes=False)
            if not items:  # asked for by hand: a reference or basic size is ballooned all the same
                bare = [{**ln, "text": re.sub(r"[()\[\]]|\b(?:REF|REFERENCE|BSC|BASIC)\b\.?", " ", ln["text"], flags=re.I)} for ln in inside]
                items = balloons.read(bare, frames, data.get("unit"), data.get("tols") or {}, size, notes=False)
            if not items:  # nothing it knows: what's written there, as it is
                text = balloons.clean(" ".join(ln["text"] for ln in sorted(inside, key=lambda ln: (ln["box"][1], ln["box"][0]))))
                items = [{"kind": "note" if text else "other", "text": text, "count": 1, "places": 0, "box": [x, y, w, h]}]
            r = r or balloons.radius(items)
            ats = balloons.place(items, obstacles, size, r, *self._balloon_marks(pg))
        self._snapshot()
        n, ids = max([c["n"] for c in data["chars"]], default=0), []
        for it, at in zip(items, ats):
            n += 1
            data["chars"].append({"id": data["next"], "n": n, "page": int(page), **self._balloon_item(pg, it, at, r)})
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
        """Change a characteristic: kind, text, count, desc (what it is, in words), gage (what it's checked with),
        nominal, plus, minus, lo, hi (numbers or None), or n, its balloon number: 4 moves it to be the fourth (the
        others move along), "4.2" puts it second under number 4 with what's there."""
        data = self._insp()
        c = self._balloon_find(data, id)
        self._snapshot()
        pages = [c["page"]]
        for k in ("kind", "text", "count", "desc", "gage"):
            if k in o and o[k] is not None:
                c[k] = int(o[k]) if k == "count" else str(o[k]).strip()[:200]
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
            if c.get("tol") != "default" or given != ["nominal"]:  # (a new nominal alone keeps the title block's)
                c["tol"] = "print" if c["plus"] is not None or c["lo"] is not None or c["hi"] is not None else None
            if c["kind"] not in ("dim", "angle", "chamfer") and c["nominal"] is not None:
                c["kind"] = "dim"
            balloons.limits(c, data.get("tols") or {})
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
               "count": 1, "places": 0, "r": c["r"], "box": list(c["box"]), "at": [round(p.x, 2), round(p.y, 2)]}
        data["chars"].append(new)
        data["next"] += 1
        data["chars"].sort(key=lambda x: (x["n"], x.get("sub") or 0))
        return self._balloon_done(data, [c["page"]], {"ids": [new["id"]]})

    def op_balloon_delete(self, ids):
        data = self._insp()
        gone = {int(i) for i in ids}
        pages = [c["page"] for c in data["chars"] if c["id"] in gone]
        if not pages:
            return self._answer([], result=self._balloon_out(data))
        self._snapshot()
        data["chars"] = [c for c in data["chars"] if c["id"] not in gone]
        return self._balloon_done(data, pages)

    def op_balloon_renumber(self):
        """Number the balloons 1, 2, 3 in the order they're in, closing the gaps deleted ones left; those sharing a
        number stay together as .1, .2, .3 (one left alone under its number loses its sub-number)."""
        data = self._insp()
        self._snapshot()
        data["chars"] = self._numbered(self._groups(data["chars"]))
        return self._balloon_done(data, [c["page"] for c in data["chars"]])

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

    # ================================================================== the inspection report
    def op_balloon_info(self, info):
        """What the report says about the job ({"part", "name", "rev", "customer", "job", "lot", "fai", "inspector",
        "parts": how many parts' results it has room for}), kept with the list."""
        from . import report
        data = self._insp()
        self._snapshot()
        data["info"] = report.clean_info(info)
        return self._balloon_done(data, [])

    def op_balloon_report(self, path, parts=None, layout=None, footer=""):
        """Write the inspection report as an Excel workbook (kernel/report.py). layout: "sheet", the page to print
        and fill in (five parts to a table), or "list", the list with its limits, a column for each part's results
        with Pass / Fail worked out from them, and AS9102 Form 3. parts: how many parts' results to make room for
        (else what the list's details say). footer: the shop's own lines for the bottom of the sheet.
        The inspection sheet is written as a PDF too (kernel/reportpdf.py), beside the workbook under its name."""
        from . import report, xlsx
        data = self._insp()
        if not data["chars"]:
            raise ValueError("There are no balloons to report yet.")
        parts = parts or (data.get("info") or {}).get("parts") or 1
        try:
            xlsx.write(path, report.build(data, Path(self.path).name, parts, layout if layout in ("sheet", "list") else None, footer))
        except PermissionError:
            raise ValueError(f"{Path(path).name} can't be written: it's open in Excel, or the folder is read-only.") from None
        from . import reportpdf
        pdf = Path(path).with_suffix(".pdf")
        if pdf.resolve() == Path(self.path).resolve():
            raise ValueError(f"The report's PDF would take the print's own name, {pdf.name}. Save the report under another name.")
        try:
            pages = reportpdf.write(str(pdf), data, Path(self.path).name, parts, footer)
        except (PermissionError, OSError) as e:
            if not isinstance(e, PermissionError) and "ermission" not in str(e) and "open" not in str(e):
                raise
            raise ValueError(f"The workbook was written, but {pdf.name} can't be: it's open in another program.") from None
        return {"path": str(path), "pdf": str(pdf), "pages": pages, "count": len(data["chars"]), "parts": int(parts)}
