"""Ballooning a print: what there is to inspect on a page (its characteristics), and where each one's balloon goes.

read(lines, ...) takes a page's lines of text, each {"text", "box": (x0, y0, x1, y1), "vert": bool} in points as the
page is shown ("vert": the line runs up the page, or with "down" too, down it), and the feature control frames already
found on it, and gives
[{"kind": "dim" | "angle" | "chamfer" | "thread" | "finish" | "gdt" | "note", "text": the requirement as written,
  "count": 4 for "4X", "nominal", "plus", "minus", "lo", "hi": numbers or None, "places": decimals written,
  "tol": "print" | "default" | "ref" | "basic" | None (where the limits came from, or why there are none),
  "box": [x, y, w, h] of the callout, "group": the same number for one callout's several characteristics}, ...]
in reading order. A size's tolerance may be written beside it (±, +/-, limits), stacked over two lines, or left to
the title block's table by the number of decimals (defaults(): ".XXX ±.005"). A reference size (in brackets, or with
REF or STOCK beside or beneath it) and a basic one (BSC, or drawn in a box of its own) have no limits: they come out
as "ref" and "basic", for the caller to balloon or leave out (read()'s `want`).
A flag note (a note's number in a triangle or flag drawn by a feature, saying that note applies there) comes out as a
"note" with "flag": its number, and the note's words when the page has that numbered note.

This is rules, not a model: what it gives is a first pass to check against the print.
"""

import math
import re
import statistics

NUM = r"(?:\d+[.,]\d+|[.,]\d+|\d+)"
DEC = r"(?:\d*[.,]\d+)"
_PRE = r"(?:[⌴⌵↧]\s*(?:Ø|R(?=[\d.,]))?|SØ|SR(?=[\d.,])|Ø|R(?=[\d.,])|□)"
THREAD = re.compile(r"(?<![\w.])(?:(?:#\d{1,2}|\d+/\d+|\d*\.\d+|\d+)\s*-\s*\d{1,2}(?:\.\d)?\s*(?:UNJC|UNJF|UNEF|UNC|UNF|UNS|UN|NPTF|NPT)"
                    r"(?:\s*-\s*[123][AB])?|M\d+(?:[.,]\d+)?(?:\s*X\s*\d+(?:[.,]\d+)?)?(?:\s*-\s*\d[a-hA-H]\d?[a-hA-H]?)?(?![\w]))")
FINISH = re.compile(r"(?<![\w.])(?:(?:Ra|RA|RMS)\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*(?:Ra|RA|RMS|µin|μin|µm|μm)(?!\w)|\d+\s*√|√\s*\d+(?:[.,]\d+)?)")
CHAMFER = re.compile(rf"(?<![\w.,/:#])(?P<num>{NUM})\s*X\s*(?P<ang>{NUM})\s*°")
ANGLE = re.compile(rf"(?<![\w.,/:#])(?P<num>{NUM})\s*°(?:\s*(?P<pm>±\s*{NUM})\s*°?)?")
LIMITS = re.compile(rf"(?<![\w.,/:#+±-])(?P<pre>{_PRE})?\s*(?P<a>{DEC})\s*[-–/]\s*(?P<b>{DEC})(?![\w.,/:°])")
DIM = re.compile(rf"(?<![\w.,/:#+±-])(?P<pre>{_PRE})?\s*(?P<num>{NUM})"
                 rf"(?:\s*(?P<pm>±\s*{NUM})|\s*(?P<up>\+\s*{NUM})(?:\s*/?\s*(?P<dn>[-–]\s*{NUM}))?)?(?:\s*(?P<lim>MAX|MIN)\b)?(?![\w,/:°]|\.\d)")
SIGNED = re.compile(rf"^(?P<sign>[+\-–±])\s*(?P<num>{NUM})$")
SIGNED2 = re.compile(rf"^\+\s*(?P<up>{NUM})\s*/?\s*[-–]\s*(?P<dn>{NUM})$")
COUNT = re.compile(r"^(?P<n>\d{1,3})\s*X(?:\s+|(?=[Ø⌴⌵↧R.#M\d]))")
PLACES = re.compile(r"\(?\b(?P<n>\d{1,3})\s*(?:PLACES|PLCS|PLC|PL|HOLES)\b\.?\)?")
NOTE = re.compile(r"^\(?(?P<n>\d{1,2})[.)]\s+(?=\S)")
NOT_INSPECTED = re.compile(r"\b(?:REF|REFERENCE|BSC|BASIC|STOCK)\b\.?", re.I)  # a size with no limits of its own
MODIFIER = re.compile(r"^\(?\s*(REF|REFERENCE|BSC|BASIC|STOCK)\.?\s*\)?$", re.I)  # one of those words alone on its line
SIZES = ("dim", "angle", "chamfer")
# words a callout may hold without being a sentence
CALLOUT_WORDS = {"THRU", "THROUGH", "ALL", "DEEP", "DEPTH", "TYP", "TYPICAL", "MAX", "MIN", "PLACES", "PLCS", "PLC", "HOLES", "HOLE",
                 "EQ", "SP", "EQL", "SPACED", "DIA", "RAD", "UNC", "UNF", "UNEF", "UNJC", "UNJF", "UNS", "NPT", "NPTF", "RMS", "TAP",
                 "DRILL", "CBORE", "CSK", "FAR", "SIDE", "NEAR", "BOTH", "SIDES", "MIN.", "FULL", "THD", "THREAD", "CHAM", "CHAMFER"}
ANCHOR = re.compile(r"\b(?:SCALE|SHEET|DWG|DRAWN|CHECKED|APPROVED|TITLE|CAGE|WEIGHT|UNLESS OTHERWISE|TOLERANCES?|THIRD ANGLE|"
                    r"DO NOT SCALE|PART N|SIZE|MATERIAL|FINISH|INTERPRET|PROPRIETARY)\b", re.I)
KIND_LABEL = {"dim": "Dimension", "angle": "Angle", "chamfer": "Chamfer", "thread": "Thread", "finish": "Surface finish",
              "gdt": "Geometric tolerance", "note": "Note", "other": "Other"}
_WORD_PLACES = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4}


def _f(s):
    return float(s.replace(" ", "").replace(",", ".").replace("–", "-"))


def _show(v):
    """A tolerance the way inch prints write it: .005, not 0.005."""
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return (s[1:] if s.startswith("0.") else s) or "0"


def _places(s):
    s = s.replace(",", ".")
    return len(s.split(".")[1]) if "." in s else 0


def clean(text):
    """A line's text with the marks this reads spelled one way."""
    t = re.sub(r"[⌀∅øΦφ]", "Ø", text)
    t = t.replace("×", "X").replace("+/-", "±").replace("+-", "±")
    t = re.sub(r"(?<=\d)\s?(?:\"|”|″|'')(?![A-Za-z\d])", "", t)  # an inch mark after a size: .470" ±.010
    t = re.sub(r"(?<=\d)\s*x\s*(?=[\dØ.MR⌴⌵↧#])", " X ", t)  # 4x Ø.250, .030 x 45°
    t = re.sub(r"(?<![A-Za-z\d])[.,][\doO]{2,}(?![A-Za-z])", lambda m: m.group().replace("o", "0").replace("O", "0"), t)  # OCR's .OOO
    return re.sub(r"\s+", " ", t).strip()


def defaults(texts):
    """The title block's tolerances by the number of decimals: {"1": 0.03, "2": 0.01, "3": 0.005, "angle": 0.5}
    (only what the print says)."""
    out = {}
    text = clean(" ".join(texts)).upper()
    for m in re.finditer(rf"(?<![\w.])X?[.,](X{{1,4}})\s*[=:]?\s*±\s*({NUM})", text):
        out.setdefault(str(len(m.group(1))), _f(m.group(2)))
    for m in re.finditer(rf"\b(ONE|TWO|THREE|FOUR)\s+PLACES?(?:\s+DECIMALS?)?\s*[=:]?\s*±\s*({NUM})", text):
        out.setdefault(str(_WORD_PLACES[m.group(1)]), _f(m.group(2)))
    m = re.search(rf"\bANG(?:LES?|ULAR)\s*[=:]?\s*±\s*({NUM})", text)
    if m:
        out["angle"] = _f(m.group(1))
    # one tolerance for every size: "TOLERANCES: ±.5mm UNLESS NOTED" (what a table says for some decimals stands)
    m = re.search(rf"\b(?:GENERAL\s+)?TOL(?:ERANCES?|\.)?\s*[=:]?\s*±\s*({NUM})\s*(?:MM|IN(?:CH(?:ES)?)?)?\s*(?:\(?UNLESS|$|[^\dX.,°])", text)
    if m and _f(m.group(1)) > 0:
        for k in "01234":
            out.setdefault(k, _f(m.group(1)))
    return out


def is_prose(t):
    """Is this line a sentence (a note, the title block's small print), not a callout?"""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z.]{2,}", t) if w.upper().rstrip(".") not in CALLOUT_WORDS]
    # (a size told in a sentence, "Hole is .470 ±.010", is the drawing's callout said again)
    return len(words) >= 3 or re.search(r"\b(?:is|are|be|was|the|should|must|will)\b", t, re.I) is not None


def parse(text, unit=None):
    """The characteristics in one line of a print: [{"kind", "text", "span": (a, b) in the cleaned line, ...}].
    A size given only for reference ("(3.000)", "3.000 REF", "Ø.625 STOCK") or as basic ("1.000 BSC") has "tol":
    "ref" or "basic", and no limits."""
    t = clean(text)
    if not t or t.startswith("[") or is_prose(t):
        return []
    line, mark = t, None
    if re.match(r"^(?:\d{1,3}\s*X\s*)?\(.*\)$", t):  # (3.000), 2X (Ø.250)
        mark = "ref"
    for m in NOT_INSPECTED.finditer(t):  # (blanked, not cut: where things are in the line stays true)
        mark = mark or ("basic" if m.group()[0] in "Bb" else "ref")
        t = t[:m.start()] + " " * (m.end() - m.start()) + t[m.end():]
    if mark:
        t = t.replace("(", " ").replace(")", " ")
    count, lead = 1, 0
    m = COUNT.match(t)
    if m and not CHAMFER.match(t):
        count, lead = int(m.group("n")), m.end()
    m = PLACES.search(t)
    if m:
        count = max(count, int(m.group("n")))
        t = t[:m.start()] + " " * (m.end() - m.start()) + t[m.end():]
    out, taken = [], []

    def free(a, b):
        return a >= lead and not any(a < y and x < b for x, y in taken)

    def add(m, kind, **more):
        a, b = m.span()
        while a < b and t[a] == " ":
            a += 1
        taken.append((a, b))
        item = {"kind": kind, "text": t[a:b].strip(), "span": (a, b), "count": count, "nominal": None, "plus": None,
                "minus": None, "lo": None, "hi": None, "places": 0, "tol": None, **more}
        out.append(item)
        return item

    for m in THREAD.finditer(t):
        if free(*m.span()):
            add(m, "thread")
    for m in FINISH.finditer(t):
        if free(*m.span()):
            add(m, "finish")
    for m in CHAMFER.finditer(t):
        if free(*m.span()):
            add(m, "chamfer", nominal=_f(m.group("num")), places=_places(m.group("num")))
    for m in ANGLE.finditer(t):
        if free(*m.span()):
            it = add(m, "angle", nominal=_f(m.group("num")), places=_places(m.group("num")))
            if m.group("pm"):
                d = _f(m.group("pm")[1:])
                it.update(plus=d, minus=d, tol="print")
    for m in LIMITS.finditer(t):
        a, b = _f(m.group("a")), _f(m.group("b"))
        if free(*m.span()) and a != b and abs(a - b) <= 0.2 * max(a, b):
            add(m, "dim", lo=min(a, b), hi=max(a, b), tol="print", places=max(_places(m.group("a")), _places(m.group("b"))),
                pre=m.group("pre") or "")
    whole = t[lead:].strip()
    for m in DIM.finditer(t):
        if not free(*m.span()):
            continue
        num, pre = m.group("num"), m.group("pre") or ""
        toleranced = m.group("pm") or m.group("up") or m.group("lim")
        if re.match(r"0\d", num) or _f(num) <= 0:
            continue
        if not (pre or toleranced or _places(num)):  # a bare whole number: a size only on a metric print, alone on its line
            if not (unit == "mm" and m.group(0).strip() == whole and len(num) <= 4):
                continue
        it = add(m, "dim", nominal=_f(num), places=_places(num), pre=pre)
        if m.group("pm"):
            d = _f(m.group("pm")[1:])
            it.update(plus=d, minus=d, tol="print")
        elif m.group("up"):
            it.update(plus=_f(m.group("up")[1:]), minus=_f(m.group("dn")[1:]) if m.group("dn") else 0.0, tol="print")
            if not m.group("dn"):
                it["open"] = True  # its minus may be on the line beneath
        elif m.group("lim"):
            it.update(tol="print", **({"hi": it["nominal"]} if m.group("lim") == "MAX" else {"lo": it["nominal"]}))
    out.sort(key=lambda i: i["span"][0])
    if count > 1:
        for it in out:
            it["text"] = f"{count}X {it['text']}"
    if mark:
        for it in out:
            it.update(plus=None, minus=None, lo=None, hi=None, tol=mark)
            it.pop("open", None)
            if len(out) == 1:
                it.update(text=line, span=(0, len(line)))  # as the print writes it, brackets and all
            else:
                it["text"] += " REF" if mark == "ref" else " BSC"
    return out


def limits(it, tols=None):
    """Fill in an item's lo and hi from its tolerance, or (when it has none of its own) from the title block's
    table `tols`. Changes and returns it."""
    if it.get("tol") == "default":
        it.update(plus=None, minus=None, lo=None, hi=None, tol=None)
    if it.get("nominal") is None or it["kind"] not in ("dim", "angle", "chamfer"):
        return it
    if it.get("plus") is None and it.get("tol") is None and tols:
        d = tols.get("angle") if it["kind"] == "angle" else tols.get(str(it.get("places") or 0))
        if d:
            it.update(plus=float(d), minus=float(d), tol="default")
    if it.get("plus") is not None:
        digits = max(it.get("places") or 0, 4) + 2
        it["hi"], it["lo"] = round(it["nominal"] + it["plus"], digits), round(it["nominal"] - (it.get("minus") or 0), digits)
    return it


# ------------------------------------------------------------------------------------------------ a page
def _local(ln):
    """A line's box along its own reading: (u0, v0, u1, v1), u the way it reads, v down from it."""
    x0, y0, x1, y1 = ln["box"]
    if ln.get("vert"):
        return (y0, -x1, y1, -x0) if ln.get("down") else (-y1, x0, -y0, x1)
    return (x0, y0, x1, y1)


def _sub(ln, t, span):
    """The box of a stretch of a line's (cleaned) text, by its share of the letters."""
    x0, y0, x1, y1 = ln["box"]
    a, b = span[0] / max(len(t), 1), span[1] / max(len(t), 1)
    if ln.get("vert") and ln.get("down"):
        return [x0, y0 + (y1 - y0) * a, x1, y0 + (y1 - y0) * b]
    if ln.get("vert"):  # reads up the page: its start is at the bottom
        return [x0, y1 - (y1 - y0) * b, x1, y1 - (y1 - y0) * a]
    return [x0 + (x1 - x0) * a, y0, x0 + (x1 - x0) * b, y1]


def _union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _border(lines, size):
    """The border's zone labels (1 2 3 … along the top and bottom, A B C … down the sides), edge by edge (top, bottom,
    left, right): [(place in `lines`, where along the edge, label)]. A label is a number or a letter alone, in the
    page's margin, three or more in a row along an edge."""
    W, H = size
    margin = 0.08 * min(W, H)
    out = []
    for edge in range(4):
        found = []
        for i, ln in enumerate(lines):
            t = ln["text"].strip()
            if not re.fullmatch(r"\d{1,2}|[A-Za-z]", t):
                continue
            x0, y0, x1, y1 = ln["box"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            depth = (cy, H - cy, cx, W - cx)[edge]  # how far in from this edge
            if depth < margin:
                found.append((i, depth, min(x1 - x0, y1 - y0) or 1.0, t.upper(), cx if edge < 2 else cy))
        row = []
        if len(found) >= 3:
            mid = statistics.median(f[1] for f in found)
            row = [f for f in found if abs(f[1] - mid) <= 1.5 * f[2]]
            if len(row) < 3 or len({f[3] for f in row}) < 3:
                row = []
        out.append([(f[0], f[4], f[3]) for f in row])
    return out


def zones(lines, size):
    """The lines that are the border's zone labels, by their place in `lines`: no part of what's inspected."""
    return {i for edge in _border(lines, size) for i, _, _ in edge}


def grid(lines, size):
    """The border's zones, to say where on the sheet something is: {"cols": [(x, label)], "rows": [(y, label)]}, each
    label where its zone's middle is. Empty lists on a sheet with no zones marked."""
    top, bottom, left, right = _border(lines, size)
    return {"cols": sorted((at, t) for _, at, t in (top or bottom)), "rows": sorted((at, t) for _, at, t in (left or right))}


def zone_at(g, x, y):
    """The zone a point is in, as a print gives it: the side's label then the top's ("A4"). "" with no zones."""
    col = min(g["cols"], key=lambda c: abs(c[0] - x))[1] if g.get("cols") else ""
    row = min(g["rows"], key=lambda r: abs(r[0] - y))[1] if g.get("rows") else ""
    return f"{row}{col}"


def type_of(c):
    """A characteristic's type as an inspector names it: a size is Linear, a Diameter or a Radius; a feature control
    frame goes by what it controls (Position, Flatness)."""
    kind, text = c.get("kind"), c.get("text") or ""
    if kind == "dim":
        return "Diameter" if "Ø" in text else "Radius" if re.match(r"(?:\d+\s*X\s*)?S?R\s*[\d.]", text) else "Linear"
    if kind == "gdt":
        return re.sub(r"[^A-Za-z ]", "", text.split("|")[0]).strip() or "GD&T"
    return {"angle": "Angular", "finish": "Surface Finish"}.get(kind) or KIND_LABEL.get(kind, "")


def title_block(lines, size):
    """(x0, y0, x1, y1) around the title block, from the words every one has; None when it isn't clear."""
    W, H = size
    hits = [ln["box"] for ln in lines if ANCHOR.search(ln["text"])]
    if len(hits) < 4:
        return None
    cx = statistics.median((b[0] + b[2]) / 2 for b in hits)
    cy = statistics.median((b[1] + b[3]) / 2 for b in hits)
    near = [b for b in hits if abs((b[0] + b[2]) / 2 - cx) < 0.3 * W and abs((b[1] + b[3]) / 2 - cy) < 0.25 * H]
    if len(near) < 4:
        return None
    box = (min(b[0] for b in near) - 8, min(b[1] for b in near) - 8, max(b[2] for b in near) + 8, max(b[3] for b in near) + 8)
    if (box[2] - box[0]) * (box[3] - box[1]) > 0.35 * W * H:
        return None
    return box


def _inside(box, outer, slack=0.0):
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return outer[0] - slack <= cx <= outer[2] + slack and outer[1] - slack <= cy <= outer[3] + slack


def boxed(box, lines):
    """Is this text in a frame of its own, the way a basic size is drawn: four lines closing a box close around it?
    lines: the page's level and upright segments (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = box
    h = max(min(x1 - x0, y1 - y0), 1.0)
    m, e = 1.4 * h, 0.3 * h
    tops, bottoms, lefts, rights = [], [], [], []
    for sx0, sy0, sx1, sy1 in lines:
        if abs(sy1 - sy0) <= 0.08 * h:
            a, b = min(sx0, sx1), max(sx0, sx1)
            if x0 - m <= a <= x0 + e and x1 - e <= b <= x1 + m:
                if y0 - m <= sy0 <= y0 + e:
                    tops.append((sy0, a, b))
                elif y1 - e <= sy0 <= y1 + m:
                    bottoms.append((sy0, a, b))
        elif abs(sx1 - sx0) <= 0.08 * h:
            a, b = min(sy0, sy1), max(sy0, sy1)
            if y0 - m <= a <= y0 + e and y1 - e <= b <= y1 + m:
                if x0 - m <= sx0 <= x0 + e:
                    lefts.append((sx0, a, b))
                elif x1 - e <= sx0 <= x1 + m:
                    rights.append((sx0, a, b))
    # (the lines of a dimension stand around its text too, but run on past it: a frame's meet at its corners)
    return any(abs(ta - lx) <= e and abs(ba - lx) <= e and abs(tb - rx) <= e and abs(bb - rx) <= e
               and abs(la - ty) <= e and abs(ra - ty) <= e and abs(lb - by) <= e and abs(rb - by) <= e
               for ty, ta, tb in tops for by, ba, bb in bottoms for lx, la, lb in lefts for rx, ra, rb in rights)


def _callouts(items):
    """Give each item its callout's "group" number: those written on one line, or stacked right under one another
    (a hole's size over its depth, a size over its feature control frame), are one callout's."""
    root = list(range(len(items)))

    def find(i):
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    loc = [_local({"box": it["box"], "vert": it["vert"][0], "down": it["vert"][1]}) for it in items]
    for i, a in enumerate(items):
        for j in range(i + 1, len(items)):
            b = items[j]
            if a["vert"] != b["vert"]:
                continue
            (a0, b0, a1, b1), (c0, d0, c1, d1) = loc[i], loc[j]
            h = max(min(b1 - b0, d1 - d0), 1.0)
            gap, over = max(d0 - b1, b0 - d1), min(a1, c1) - max(a0, c0)
            same = a.get("li") is not None and a.get("li") == b.get("li")
            if same or (-0.4 * h <= gap <= 0.8 * h and (over > 0.4 * min(a1 - a0, c1 - c0) or abs(a0 - c0) < h)):
                root[find(j)] = find(i)
    for i, it in enumerate(items):
        it["group"] = find(i)


def flags(lines, shapes):
    """The flag notes on a page: a note's number (1 to 99) alone in a closed outline of three, five or six sides drawn
    close round it (a triangle, a flag: not a box, which is a basic size's). shapes: the page's closed outlines,
    (x0, y0, x1, y1, sides). [(place in lines, number, outline's box)]."""
    out = []
    for i, ln in enumerate(lines):
        t = ln["text"].strip()
        if not re.fullmatch(r"\d{1,2}", t) or int(t) < 1:
            continue
        x0, y0, x1, y1 = ln["box"]
        cx, cy, h = (x0 + x1) / 2, (y0 + y1) / 2, max(min(x1 - x0, y1 - y0), max(x1 - x0, y1 - y0) / max(len(t), 1), 1.0)
        for sx0, sy0, sx1, sy1, sides in shapes:
            if sides not in (3, 5, 6) or not (sx0 <= cx <= sx1 and sy0 <= cy <= sy1):
                continue
            if sx1 - sx0 <= 6 * h and sy1 - sy0 <= 6 * h and sx1 - sx0 >= (x1 - x0) * 0.9 and sy1 - sy0 >= (y1 - y0) * 0.9:
                out.append((i, int(t), (sx0, sy0, sx1, sy1)))
                break
    return out


def read(lines, frames=(), unit=None, tols=None, size=(612.0, 792.0), notes=True, segs=(), want=None, shapes=()):
    """A page's characteristics, in reading order (see the top of this file). frames: [{"box": [x, y, w, h], "text"}]
    the feature control frames found on the page; tols: the title block's table, or None to read it from the lines;
    segs: the page's linework (x0, y0, x1, y1), to tell a basic size by its box; shapes: its closed outlines (x0, y0,
    x1, y1, sides), to find the flag notes. want: what to give, each True unless said: "ref" and "basic" sizes,
    "general" (sizes with no tolerance of their own), "finish" (surface finishes), "flags" (flag notes), and "title"
    (leave out what's in the title block)."""
    want = {"ref": True, "basic": True, "general": True, "finish": True, "title": True, "flags": True, **(want or {})}
    lines = [{**ln, "text": clean(ln["text"])} for ln in lines if ln["text"].strip()]
    if tols is None:
        tols = defaults([ln["text"] for ln in lines])
    block = title_block(lines, size) if want["title"] else None
    border = zones(lines, size)
    fboxes = [(f["box"][0], f["box"][1], f["box"][0] + f["box"][2], f["box"][1] + f["box"][3]) for f in frames]
    items, signed, marks = [], [], []
    flagged = flags(lines, shapes) if shapes else []
    skip = border | {i for i, _, _ in flagged}  # (a flag's number is no size)
    for i, ln in enumerate(lines):
        t, box = ln["text"], ln["box"]
        if i in skip:
            continue
        if any(_inside(box, fb, 1.0) for fb in fboxes):
            continue  # a frame's own tolerance and datums
        m2, m1 = SIGNED2.match(t), SIGNED.match(t)
        if m2:
            signed.append((ln, {"plus": _f(m2.group("up")), "minus": _f(m2.group("dn")), "ps": m2.group("up"), "ms": m2.group("dn")}))
            continue
        if m1:
            d, raw = _f(m1.group("num")), m1.group("num")
            signed.append((ln, {"plus": d, "minus": d, "ps": raw, "ms": raw, "pm": True} if m1.group("sign") == "±"
                           else {"plus": d, "ps": raw} if m1.group("sign") == "+" else {"minus": d, "ms": raw}))
            continue
        if is_prose(t):
            continue
        if block and _inside(box, block):
            continue
        m = MODIFIER.match(t)
        if m:  # REF, BSC or STOCK on a line of its own: said of the size it's written by
            marks.append((ln, "basic" if m.group(1)[0] in "Bb" else "ref"))
            continue
        for it in parse(t, unit):
            it["box"] = _sub(ln, t, it.pop("span"))
            it["vert"] = (bool(ln.get("vert")), bool(ln.get("down")))
            it["alone"] = it["text"] == t
            it["li"] = i
            items.append(it)
    # a tolerance stacked beside its size: +.005 over -.000, each a line of its own
    for ln, tol in signed:
        u0, v0, u1, v1 = _local(ln)
        h, best = max(v1 - v0, 1.0), None
        for it in items:
            if it["kind"] not in ("dim", "angle") or it["vert"] != (bool(ln.get("vert")), bool(ln.get("down"))) \
                    or it["tol"] in ("ref", "basic") or (it["tol"] == "print" and "stack" not in it and not it.get("open")):
                continue
            a0, b0, a1, b1 = _local({"box": it.get("core", it["box"]), "vert": it["vert"][0], "down": it["vert"][1]})
            gap = u0 - a1
            if -0.6 * h <= gap <= 3.0 * h and b0 - 1.2 * h <= (v0 + v1) / 2 <= b1 + 1.2 * h and (best is None or gap < best[0]):
                best = (gap, it)
        if best:
            it = best[1]
            it.setdefault("stack", {}).update(tol)
            it.setdefault("core", it["box"])  # the size itself: the next line of its tolerance is beside this
            it["tol"] = "print"
            it["box"] = _union(it["box"], ln["box"])
    for it in items:
        st, opened = it.pop("stack", None), it.pop("open", False)
        if st and opened:
            it["minus"] = st.get("minus", 0.0)
            it["text"] += f"/-{st.get('ms', '0')}"
        elif st:
            it["plus"], it["minus"] = st.get("plus", 0.0), st.get("minus", 0.0)
            it["text"] += f" ±{st['ps']}" if st.get("pm") else f" +{st.get('ps', '0')}/-{st.get('ms', '0')}"
    # limits stacked: the larger over the smaller, each a line of its own
    gone = set()
    for i, a in enumerate(items):
        if i in gone or not (a["kind"] == "dim" and a["alone"] and a["tol"] is None and a["places"] >= 2):
            continue
        a0, a1v, a2, a3 = _local({"box": a["box"], "vert": a["vert"][0], "down": a["vert"][1]})
        h = max(a3 - a1v, 1.0)
        for j, b in enumerate(items):
            if j == i or j in gone or not (b["kind"] == "dim" and b["alone"] and b["tol"] is None and b["places"] == a["places"] and b["vert"] == a["vert"]):
                continue
            b0, b1v, b2, b3 = _local({"box": b["box"], "vert": b["vert"][0], "down": b["vert"][1]})
            if abs(b0 - a0) < 0.7 * h and -0.35 * h <= b1v - a3 < 0.7 * h and a["nominal"] != b["nominal"] \
                    and abs(a["nominal"] - b["nominal"]) <= 0.1 * max(a["nominal"], b["nominal"]):
                a.update(lo=min(a["nominal"], b["nominal"]), hi=max(a["nominal"], b["nominal"]), tol="print",
                         text=f"{a['text']} / {b['text']}", box=_union(a["box"], b["box"]), nominal=None)
                gone.add(j)
                break
    items = [it for i, it in enumerate(items) if i not in gone]
    # REF, BSC or STOCK written under a size, or after it: that size has no limits
    for ln, mark in marks:
        u0, v0, u1, v1 = _local(ln)
        h, best = max(v1 - v0, 1.0), None
        for it in items:
            if it["kind"] not in SIZES or it["vert"] != (bool(ln.get("vert")), bool(ln.get("down"))):
                continue
            a0, b0, a1, b1 = _local({"box": it["box"], "vert": it["vert"][0], "down": it["vert"][1]})
            under = -0.4 * h <= v0 - b1 <= 1.0 * h and u0 < a1 + h and u1 > a0 - h
            after = -0.5 * h <= u0 - a1 <= 2.5 * h and b0 - 0.6 * h <= (v0 + v1) / 2 <= b1 + 0.6 * h
            d = abs(v0 - b1) if under else abs(u0 - a1) if after else None
            if d is not None and (best is None or d < best[0]):
                best = (d, it)
        if best:
            best[1].update(plus=None, minus=None, lo=None, hi=None, tol=mark, text=f"{best[1]['text']} {ln['text']}",
                           box=_union(best[1]["box"], ln["box"]))
    # a size in a box of its own is basic
    frame = [s for s in segs if (abs(s[0] - s[2]) < 0.6 or abs(s[1] - s[3]) < 0.6) and abs(s[0] - s[2]) + abs(s[1] - s[3]) < 400]
    for it in items:
        if frame and it["kind"] in ("dim", "angle") and it["tol"] is None and boxed(it["box"], frame):
            it["tol"] = "basic"
    for it in items:
        limits(it, tols)
    for f in frames:
        x, y, w, hh = f["box"]
        items.append({"kind": "gdt", "text": f["text"], "count": 1, "nominal": None, "plus": None, "minus": None, "lo": None,
                      "hi": None, "places": 0, "tol": None, "box": [x, y, x + w, y + hh], "vert": (False, False)})
    items = [it for it in items if (want[it["tol"]] if it["tol"] in ("ref", "basic") else want["finish"] if it["kind"] == "finish"
                                    else want["general"] if it["kind"] in SIZES and it["tol"] in (None, "default") else True)]
    _callouts(items)
    if flagged and want["flags"]:
        said = {}
        for nt in _notes(lines):
            m = NOTE.match(nt["text"])
            said.setdefault(int(m.group("n")), nt["text"][m.end():].strip())
        for _, n, (x0, y0, x1, y1) in flagged:
            items.append({"kind": "note", "text": f"Flag note {n}" + (f": {said[n]}" if n in said else ""), "count": 1, "nominal": None,
                          "plus": None, "minus": None, "lo": None, "hi": None, "places": 0, "tol": None, "box": [x0, y0, x1, y1],
                          "vert": (False, False), "flag": n})
    if notes:
        items += _notes(lines)
    band = max(size[1] / 14, 1.0)  # rows across the sheet, left to right
    items.sort(key=lambda it: (it["kind"] == "note", int(it["box"][1] // band), it["box"][0]))
    for it in items:
        b = it["box"]
        it["box"] = [round(b[0], 2), round(b[1], 2), round(b[2] - b[0], 2), round(b[3] - b[1], 2)]
        it.pop("alone", None)
        it.pop("core", None)
        it.pop("li", None)
        it.setdefault("group", None)
        it["vert"] = it["vert"][0]
        it.pop("pre", None)
    return items


def _notes(lines):
    """The numbered notes on a page, each with the lines that carry it on."""
    rows = sorted((ln for ln in lines if not ln.get("vert")), key=lambda ln: ln["box"][1])
    out = []
    for i, ln in enumerate(rows):
        if not (NOTE.match(ln["text"]) and is_prose(ln["text"])):
            continue
        text, box, h = ln["text"], list(ln["box"]), max(ln["box"][3] - ln["box"][1], 1.0)
        for nx in rows[i + 1:]:
            gap, dx = nx["box"][1] - box[3], nx["box"][0] - ln["box"][0]
            if gap > 0.9 * h:
                break
            if not (-2 <= dx < 6 * h) or nx["box"][1] < box[3] - 0.6 * h:
                continue  # another column, or beside it
            if NOTE.match(nx["text"]):
                break  # the next note
            text, box = f"{text} {nx['text']}", _union(box, nx["box"])
        out.append({"kind": "note", "text": text, "count": 1, "nominal": None, "plus": None, "minus": None, "lo": None,
                    "hi": None, "places": 0, "tol": None, "box": box, "vert": (False, False)})
    return out


# ------------------------------------------------------------------------------------------------ where balloons go
_PASS = {"P", "PASS", "OK", "A", "ACC", "ACCEPT", "ACCEPTED", "Y", "YES", "GO", "GOOD", "✓"}
_FAIL = {"F", "FAIL", "NG", "R", "REJ", "REJECT", "REJECTED", "N", "NO", "NO GO", "NOGO", "BAD", "X"}


def result(text):
    """A measured result as it's kept: a number the way it was typed ("2.3751"), "Pass" or "Fail" (for what isn't
    measured: P, OK, accept; F, NG, reject), or a few words as they are. "" for none."""
    s = str(text or "").strip()
    word = s.upper().rstrip(".")
    if word in _PASS or word in _FAIL:
        return "Pass" if word in _PASS else "Fail"
    try:
        float(s.replace(",", "."))
    except ValueError:
        return s[:40]
    return s.replace(",", ".").lstrip("+")


def judge(c, value):
    """Does a result meet its characteristic? True, False, or None when that can't be said: nothing entered, words,
    or a number for something with no limits."""
    if value == "Pass" or value == "Fail":
        return value == "Pass"
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    lo, hi = c.get("lo"), c.get("hi")
    if lo is None and hi is None:
        return None
    return (lo is None or x >= lo - 1e-9) and (hi is None or x <= hi + 1e-9)


def stats(c, values):
    """How a characteristic's measurements spread, from two or more of them: {"n", "mean", "min", "max", "range",
    "sd" (the sample's standard deviation), "cp", "cpk"}; Cp needs both limits, Cpk one; neither with no spread at
    all. None with fewer than two numbers."""
    xs = []
    for v in values:
        try:
            xs.append(float(v))
        except (TypeError, ValueError):
            pass
    if len(xs) < 2:
        return None
    n, mean = len(xs), sum(xs) / len(xs)
    sd = (sum((x - mean) ** 2 for x in xs) / (n - 1)) ** 0.5
    lo, hi = c.get("lo"), c.get("hi")
    cp = (hi - lo) / (6 * sd) if sd > 1e-12 and lo is not None and hi is not None else None
    sides = [s for s in ((hi - mean) if hi is not None else None, (mean - lo) if lo is not None else None) if s is not None]
    cpk = min(sides) / (3 * sd) if sd > 1e-12 and sides else None
    return {"n": n, "mean": mean, "min": min(xs), "max": max(xs), "range": max(xs) - min(xs), "sd": sd, "cp": cp, "cpk": cpk}


def sample(lot, how="every", n=None, last=True):
    """Which parts of a lot to inspect, by their place in it (1 is the first made): how "every" (all of them),
    "ends" (the first and the last), "thirds" (the first, the middle one and the last), "one_in" (the first, then
    every n-th after it, and the last too when `last`), "percent" (n percent of them, at least one, spread through
    the lot)."""
    lot = int(lot)
    if lot < 1:
        raise ValueError("A lot has at least one part.")
    if how == "every":
        out = range(1, lot + 1)
    elif how == "ends":
        out = {1, lot}
    elif how == "thirds":
        out = {1, (lot + 1) // 2, lot}
    elif how == "one_in":
        step = int(n or 0)
        if step < 1:
            raise ValueError("1 in how many?")
        out = set(range(1, lot + 1, step)) | ({lot} if last else set())
    elif how == "percent":
        share = float(n or 0)
        if not 0 < share <= 100:
            raise ValueError("What percent of the lot, from more than 0 to 100?")
        k = min(max(math.ceil(lot * share / 100), 1), lot)
        out = {1} if k == 1 else {round(1 + i * (lot - 1) / (k - 1)) for i in range(k)}
    else:
        raise ValueError(f"Sample how? {how}")
    return sorted(out)


def frequency(lot, how="every", n=None, last=True):
    """How a sampling is said on the inspection sheet's Inspection Frequency line."""
    return {"every": "Every part", "ends": "First and last part", "thirds": "First, middle and last part",
            "one_in": f"1 in {n}" + (", and the last" if last else ""), "percent": f"{n}% of the lot"}[how] + f" (lot of {lot})"


def row_keys(c):
    """What a characteristic's results are kept under: its id, or for a multiplied one, id.1, id.2 … for each place."""
    n = c.get("count") or 1
    return [f"{c['id']}.{k}" for k in range(1, n + 1)] if c.get("mult") and n > 1 else [str(c["id"])]


def restate(c, text):
    """A size's requirement written again after its nominal, tolerance or limits were changed: the size and its
    tolerance as they are now, what's around them (4X, Ø, R, THRU) as it was. Anything else, or a reference or basic
    size, as it was."""
    t = clean(text or "")
    if c.get("kind") not in ("dim", "angle") or c.get("tol") in ("ref", "basic") or not t:
        return text
    lead = COUNT.match(t).end() if COUNT.match(t) and not CHAMFER.match(t) else 0
    if c["kind"] == "angle":
        m = ANGLE.search(t, lead)
        old, at = (m.group("num"), m.start("num")) if m else (None, None)
    else:
        m = LIMITS.search(t, lead)
        if m:
            old, at = m.group("a"), m.start("a")
        else:
            m = DIM.search(t, lead)
            old, at = (m.group("num"), m.start("num")) if m else (None, None)
    if m is None:
        return text
    places = c.get("places") or 0
    inch = old.startswith(".")  # (.375 or 0.375, as the print writes it)
    said_tol = re.search(r"[±+\-–]\s*([.,]?)\d", t[m.start():m.end()] if m.re is not LIMITS else "")
    dot = bool(said_tol.group(1)) if said_tol else (inch or places >= 3)  # (±.005 or ±0.1, as the print writes it)

    def num(v):
        s = fmt(v, places)
        return s[1:] if inch and s.startswith("0.") else s[0] + s[2:] if inch and s.startswith("-0.") else s

    def tol(v):
        s = fmt(v, places if c["kind"] == "angle" else max(places, 1))
        return s[1:] if dot and s.startswith("0.") else s
    deg = "°" if c["kind"] == "angle" else ""
    nom, plus, minus, lo, hi = (c.get(k) for k in ("nominal", "plus", "minus", "lo", "hi"))
    if plus is not None and nom is not None and c.get("tol") == "print":
        said = f"{num(nom)}{deg} ±{tol(plus)}{deg}" if abs(plus - (minus or 0)) < 1e-12 else f"{num(nom)}{deg} +{tol(plus)}{deg}/-{tol(minus or 0)}{deg}"
    elif lo is not None and hi is not None and plus is None:
        if m.re is LIMITS:  # the way the print wrote them: which first, and what between
            a, b = (hi, lo) if float(m.group("a").replace(",", ".")) > float(m.group("b").replace(",", ".")) else (lo, hi)
            said = f"{num(a)}{t[m.end('a'):m.start('b')]}{num(b)}"
        else:
            said = f"{num(lo)}-{num(hi)}"
    elif hi is not None and lo is None:
        said = f"{num(hi)}{deg} MAX"
    elif lo is not None and hi is None:
        said = f"{num(lo)}{deg} MIN"
    elif nom is not None:
        said = f"{num(nom)}{deg}"
    else:
        return text
    return (t[:at] + said + t[m.end():]).strip()


def recount(text, count):
    """A requirement with its count (4X) as it is now."""
    t = (text or "").strip()
    m = COUNT.match(t)
    bare = t[m.end():] if m and not CHAMFER.match(t) else t
    return f"{count}X {bare}" if count and count > 1 else bare


def single(text):
    """A requirement without its count: "4X Ø.250 ±.005" as it applies to one of the four."""
    t = text or ""
    return t if CHAMFER.match(clean(t)) else re.sub(r"^\s*\d{1,3}\s*[Xx×]\s*(?=\S)", "", t)


def label(c):
    """What a balloon says: its number, or number.sub (2.1, 2.2) for one of several under the same number."""
    return f"{c['n']}.{c['sub']}" if c.get("sub") else str(c["n"])


def radius(items):
    """A balloon's radius for a page, from the height of its sizes' text."""
    hs = [min(it["box"][2], it["box"][3]) for it in items if it["kind"] in ("dim", "angle", "thread", "chamfer") and min(it["box"][2], it["box"][3]) > 0]
    return round(min(max(0.8 * statistics.median(hs), 5.5), 10.0), 1) if hs else 8.0


def _seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / n))
    return math.hypot(px - x0 - t * dx, py - y0 - t * dy)


def _box_dist(px, py, o):
    return math.hypot(max(o[0] - px, 0.0, px - o[2]), max(o[1] - py, 0.0, py - o[3]))


def place(items, obstacles, size, r, segs=(), pics=()):
    """A center [x, y] for each item's balloon: the best of the spots around its callout. A spot is better the nearer
    it is, and worse for what it sits on or crowds: text (obstacles: boxes (x0, y0, x1, y1)), a balloon already
    placed, the drawing's linework (segs: (x0, y0, x1, y1), the part's edges and the dimension and leader lines) and
    its pictures (pics: boxes). Nothing is ruled out but the page's edge, so a crowded callout still gets the least
    bad spot."""
    W, H = size
    taken, out = [], []
    rings = (0.0, 0.75, 1.5, 2.5, 4.0, 6.0)
    reach = (rings[-1] + 3.5) * r
    for it in items:
        x, y, w, h = it["box"]
        cx, cy, d = x + w / 2, y + h / 2, r + 0.3 * r + 1.0
        zone = (x - reach, y - reach, x + w + reach, y + h + reach)
        text = [o for o in obstacles if o[0] < zone[2] and o[2] > zone[0] and o[1] < zone[3] and o[3] > zone[1]] + [(x, y, x + w, y + h)]
        lines = [s for s in segs if min(s[0], s[2]) < zone[2] and max(s[0], s[2]) > zone[0] and min(s[1], s[3]) < zone[3] and max(s[1], s[3]) > zone[1]]
        others = [t for t in taken if zone[0] - r < t[0] < zone[2] + r and zone[1] - r < t[1] < zone[3] + r]
        spots = []  # (x, y, how far out in r, how much the side is second choice)
        for k in rings:
            e = d + k * r
            # the side a callout is read from first: its left, or for one running up or down the page, above and below
            first, second = [(x - e, cy), (x + w + e, cy)], [(cx, y - e), (cx, y + h + e)]
            if w > 4 * r:  # a long callout: along it too, toward its ends
                second += [(x + r, y - e), (x + w - r, y - e), (x + r, y + h + e), (x + w - r, y + h + e)]
            if h > 4 * r:
                first += [(x - e, y + r), (x - e, y + h - r), (x + w + e, y + r), (x + w + e, y + h - r)]
            if it.get("vert"):
                first, second = second, first
            c = e * 0.72
            corners = [(x - c, y - c), (x + w + c, y - c), (x - c, y + h + c), (x + w + c, y + h + c)]
            spots += [(sx, sy, k, 0.12 * n) for n, (sx, sy) in enumerate(first[:2])] + [(sx, sy, k, 0.3) for sx, sy in first[2:]]
            spots += [(sx, sy, k, 0.35) for sx, sy in second] + [(sx, sy, k, 0.55) for sx, sy in corners]
        best, least = None, None
        for sx, sy, k, side in spots:
            if not (r + 1 <= sx <= W - r - 1 and r + 1 <= sy <= H - r - 1):
                continue
            cost = k + side
            for o in text:
                g = _box_dist(sx, sy, o) - r
                if g < 0:
                    cost += 40 + 10 * min(-g / r, 1.0)
                elif g < 0.35 * r:
                    cost += 2 * (1 - g / (0.35 * r))
            for bx, by in others:
                g = math.hypot(sx - bx, sy - by) - 2 * r
                if g < 0:
                    cost += 60
                elif g < 0.6 * r:
                    cost += 3 * (1 - g / (0.6 * r))
            if least is not None and cost >= least:
                continue
            on = 0.0
            for s in lines:
                g = _seg_dist(sx, sy, *s)
                if g < r:
                    on += 2 - g / r  # (through its middle is worse than across its rim)
                elif g < 1.25 * r:
                    on += 0.3
                if on >= 8:
                    break
            cost += min(on * 3, 24)
            if any(o[0] < sx < o[2] and o[1] < sy < o[3] for o in pics):
                cost += 5
            if least is None or cost < least:
                best, least = (sx, sy), cost
        sx, sy = best or (min(max(x - d, r + 1), W - r - 1), min(max(cy, r + 1), H - r - 1))
        taken.append((sx, sy))
        out.append([round(sx, 2), round(sy, 2)])
    return out


def fmt(v, places=3):
    """A number the way a print writes it: at least `places` decimals, no more than it needs past them."""
    if v is None:
        return ""
    s = f"{v:.{max(places, 0)}f}"
    return s if abs(float(s) - v) < 1e-9 else f"{v:.6f}".rstrip("0")
