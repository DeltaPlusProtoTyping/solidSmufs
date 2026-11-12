"""Ballooning a print: what there is to inspect on a page (its characteristics), and where each one's balloon goes.

read(lines, ...) takes a page's lines of text, each {"text", "box": (x0, y0, x1, y1), "vert": bool} in points as the
page is shown ("vert": the line runs up the page, or with "down" too, down it), and the feature control frames already
found on it, and gives
[{"kind": "dim" | "angle" | "chamfer" | "thread" | "finish" | "gdt" | "note", "text": the requirement as written,
  "count": 4 for "4X", "nominal", "plus", "minus", "lo", "hi": numbers or None, "places": decimals written,
  "tol": "print" | "default" | None (where the limits came from), "box": [x, y, w, h] of the callout}, ...]
in reading order. A size's tolerance may be written beside it (±, +/-, limits), stacked over two lines, or left to
the title block's table by the number of decimals (defaults(): ".XXX ±.005"). Reference sizes (in brackets, REF) and
basic ones marked BSC aren't inspected and are left out; a basic size shown only by its box can't be told from the
text and comes out as a plain one, to delete.

This is rules, not a model: what it gives is a first pass to check against the print.
"""

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
NOT_INSPECTED = re.compile(r"\b(?:REF|REFERENCE|BSC|BASIC)\b\.?")
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
    return out


def is_prose(t):
    """Is this line a sentence (a note, the title block's small print), not a callout?"""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z.]{2,}", t) if w.upper().rstrip(".") not in CALLOUT_WORDS]
    return len(words) >= 3


def parse(text, unit=None):
    """The characteristics in one line of a print: [{"kind", "text", "span": (a, b) in the cleaned line, ...}]."""
    t = clean(text)
    if not t or (t.startswith("(") and t.endswith(")")) or t.startswith("[") or NOT_INSPECTED.search(t.upper()) or is_prose(t):
        return []
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


def read(lines, frames=(), unit=None, tols=None, size=(612.0, 792.0), notes=True):
    """A page's characteristics, in reading order (see the top of this file). frames: [{"box": [x, y, w, h], "text"}]
    the feature control frames found on the page; tols: the title block's table, or None to read it from the lines."""
    lines = [{**ln, "text": clean(ln["text"])} for ln in lines if ln["text"].strip()]
    if tols is None:
        tols = defaults([ln["text"] for ln in lines])
    block = title_block(lines, size)
    fboxes = [(f["box"][0], f["box"][1], f["box"][0] + f["box"][2], f["box"][1] + f["box"][3]) for f in frames]
    items, signed = [], []
    for ln in lines:
        t, box = ln["text"], ln["box"]
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
        for it in parse(t, unit):
            it["box"] = _sub(ln, t, it.pop("span"))
            it["vert"] = (bool(ln.get("vert")), bool(ln.get("down")))
            it["alone"] = it["text"] == t
            items.append(it)
    # a tolerance stacked beside its size: +.005 over -.000, each a line of its own
    for ln, tol in signed:
        u0, v0, u1, v1 = _local(ln)
        h, best = max(v1 - v0, 1.0), None
        for it in items:
            if it["kind"] not in ("dim", "angle") or it["vert"] != (bool(ln.get("vert")), bool(ln.get("down"))) \
                    or (it["tol"] == "print" and "stack" not in it and not it.get("open")):
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
    for it in items:
        limits(it, tols)
    for f in frames:
        x, y, w, hh = f["box"]
        items.append({"kind": "gdt", "text": f["text"], "count": 1, "nominal": None, "plus": None, "minus": None, "lo": None,
                      "hi": None, "places": 0, "tol": None, "box": [x, y, x + w, y + hh], "vert": (False, False)})
    if notes:
        items += _notes(lines)
    band = max(size[1] / 14, 1.0)  # rows across the sheet, left to right
    items.sort(key=lambda it: (it["kind"] == "note", int(it["box"][1] // band), it["box"][0]))
    for it in items:
        b = it["box"]
        it["box"] = [round(b[0], 2), round(b[1], 2), round(b[2] - b[0], 2), round(b[3] - b[1], 2)]
        it.pop("alone", None)
        it.pop("core", None)
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
def radius(items):
    """A balloon's radius for a page, from the height of its sizes' text."""
    hs = [min(it["box"][2], it["box"][3]) for it in items if it["kind"] in ("dim", "angle", "thread", "chamfer") and min(it["box"][2], it["box"][3]) > 0]
    return round(min(max(0.8 * statistics.median(hs), 5.5), 10.0), 1) if hs else 8.0


def place(items, obstacles, size, r):
    """A center [x, y] for each item's balloon: beside its callout, clear of the page's text and of the balloons
    already placed. obstacles: boxes (x0, y0, x1, y1)."""
    W, H = size
    taken, out = [], []
    for it in items:
        x, y, w, h = it["box"]
        cx, cy, d = x + w / 2, y + h / 2, r + 2.0
        near = [o for o in obstacles if o[0] < x + w + 8 * r and o[2] > x - 8 * r and o[1] < y + h + 8 * r and o[3] > y - 8 * r]
        near += [o for o in taken if abs(o[0] - cx) < w + 10 * r and abs(o[1] - cy) < h + 10 * r]
        spots = []
        for k in (1.0, 3.0, 5.0):
            e = d + (k - 1) * r
            sides = [(x - e, cy), (x + w + e, cy), (cx, y - e), (cx, y + h + e)]
            if it.get("vert") or it["kind"] == "note":
                sides = [sides[2], sides[3], sides[0], sides[1]] if it.get("vert") else sides
            spots += sides + [(x - e, y - e * 0.6), (x + w + e, y - e * 0.6), (x - e, y + h + e * 0.6), (x + w + e, y + h + e * 0.6)]
        best = None
        for sx, sy in spots:
            if not (r + 1 <= sx <= W - r - 1 and r + 1 <= sy <= H - r - 1):
                continue
            if best is None:
                best = (sx, sy)
            if not any(sx - r < o[2] and o[0] < sx + r and sy - r < o[3] and o[1] < sy + r for o in near):
                best = (sx, sy)
                break
        sx, sy = best or (min(max(x - d, r + 1), W - r - 1), min(max(cy, r + 1), H - r - 1))
        taken.append((sx - r, sy - r, sx + r, sy + r))
        out.append([round(sx, 2), round(sy, 2)])
    return out


def fmt(v, places=3):
    """A number the way a print writes it: at least `places` decimals, no more than it needs past them."""
    if v is None:
        return ""
    s = f"{v:.{max(places, 0)}f}"
    return s if abs(float(s) - v) < 1e-9 else f"{v:.6f}".rstrip("0")
