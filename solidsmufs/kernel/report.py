"""The inspection report: an inspection list (kernel/balloonops.py keeps it) laid out as an Excel workbook.

build(data, drawing, parts, layout, footer) gives the sheets for kernel/xlsx.py. Two layouts:
- "sheet", the one to print and fill in at the machine: the job across the top, then a table of every balloon (its
  number, what it is, the gage, nominal and limits) with five blank part columns, the table again for each further
  five parts. A result typed into the workbook instead turns red when it's outside its limits.
- "list": "Inspection", who and what at the top, then a row for each balloon with its requirement and limits, a
  column for each part's result, and a Pass / Fail the workbook works out itself as results are typed in; and
  "AS9102 Form 3", the same characteristics in the first article form's layout, its results following the first
  part's. What the Inspection sheet holds is a layout, not code: LAYOUT names its columns, COLUMNS says what each is.
"""

import datetime

from . import balloons, xlsx

# what's asked about the job, kept with the list in the PDF: (key, label, AS9102 Form 3's field or None)
INFO = [("part", "Part number", "1. Part Number"), ("name", "Part name", "2. Part Name"), ("rev", "Revision", None),
        ("customer", "Customer", None), ("job", "Job number", None), ("lot", "Lot / serial number", "3. Serial Number"),
        ("fai", "Report number", "4. FAI Report Number"), ("inspector", "Inspected by", None),
        ("frequency", "Inspection frequency", None)]
MAX_PARTS = 50
PER = 5  # part columns in one table of the sheet layout
LAYOUTS = [["sheet", "Inspection sheet, five parts to a table"], ["list", "List with Pass / Fail, and AS9102 Form 3"]]
MEASURED = ("dim", "angle", "chamfer")

# a column: its heading, its width, and what goes in it for a characteristic c (o: the report's settings)
COLUMNS = {
    "n": ("Balloon", 9, lambda c, o: (_n(c), "center")),
    "sheet": ("Sheet", 7, lambda c, o: (c["page"] + 1, "center")),
    "kind": ("Type", 20, lambda c, o: (balloons.KIND_LABEL.get(c["kind"], c["kind"]), "box")),
    "text": ("Requirement", 36, lambda c, o: (c["text"], "box")),
    "count": ("Qty", 6, lambda c, o: (c.get("count") or 1, "center")),
    "nominal": ("Nominal", 11, lambda c, o: _num(c, "nominal", o)),
    "plus": ("+ Tol", 9, lambda c, o: _num(c, "plus", o)),
    "minus": ("- Tol", 9, lambda c, o: _num(c, "minus", o)),
    "lo": ("Lower limit", 12, lambda c, o: _num(c, "lo", o)),
    "hi": ("Upper limit", 12, lambda c, o: _num(c, "hi", o)),
    "from": ("Tolerance from", 14, lambda c, o: ({"print": "Print", "default": "Title block"}.get(c.get("tol"), ""), "box")),
    "desc": ("Description", 24, lambda c, o: (describe(c), "box")),
    "gage": ("Gage", 16, lambda c, o: (c.get("gage") or "", "box")),
    "comments": ("Comments", 28, lambda c, o: ("", "box")),
}
# "results" stands for a column for each part, "status" for the Pass / Fail worked out from them
LAYOUT = {"name": "Inspection", "title": "Inspection report",
          "columns": ["n", "sheet", "kind", "text", "count", "nominal", "plus", "minus", "lo", "hi", "from", "results", "status",
                      "gage", "comments"]}


def describe(c):
    """What a characteristic is, in words: what was typed for it, else a plain name for it."""
    if c.get("desc"):
        return c["desc"]
    text = c.get("text") or ""
    if c.get("kind") in MEASURED:
        name = {"angle": "Angle", "chamfer": "Chamfer"}.get(c["kind"]) or ("Diameter" if "Ø" in text else "Radius" if text.lstrip("0123456789Xx ").startswith("R") else "Dimension")
    else:
        name = balloons.KIND_LABEL.get(c.get("kind"), "")
    return f"{c['count']}X {name}" if (c.get("count") or 1) > 1 else name


def _n(c):
    return balloons.label(c) if c.get("sub") else c["n"]


def _look(c):
    """How a characteristic's numbers are written: an angle as it is, a size to three places, or four if the print has."""
    return "box" if c.get("kind") == "angle" else "num4" if (c.get("places") or 0) >= 4 else "num3"


def _num(c, key, o):
    v = c.get(key)
    return (v, _look(c)) if v is not None else ("", "box")


def clean_info(info):
    """What was typed about the job, as it's kept: known fields only, and how many parts' results the report holds."""
    info = info or {}
    out = {k: str(info[k]).strip()[:200] for k, _, _ in INFO if str(info.get(k) or "").strip()}
    try:
        out["parts"] = min(max(int(info.get("parts") or 1), 1), MAX_PARTS)
    except (TypeError, ValueError):
        out["parts"] = 1
    return out


def _tols_said(tols):
    return ", ".join(f"{'angles' if k == 'angle' else '.' + 'X' * int(k) if int(k) else 'X'} ±{balloons._show(v)}{'°' if k == 'angle' else ''}"
                     for k, v in sorted(tols.items(), key=lambda kv: (kv[0] == "angle", kv[0]))) or "none found on the print"


def _status(rng, lo, hi):
    """Pass / Fail for a row from its results (cells rng): any Fail typed there, or any number outside lo..hi (cell
    names or numbers; None: no such limit), fails it. Nothing there yet: empty."""
    bad = [f'COUNTIF({rng},"Fail")']
    if lo is not None:
        bad.append(f'COUNTIF({rng},"<"&{lo})')
    if hi is not None:
        bad.append(f'COUNTIF({rng},">"&{hi})')
    return f'IF(COUNTA({rng})=0,"",IF({"+".join(bad)}>0,"Fail","Pass"))'


def inspection(data, drawing, parts=1, layout=None):
    """The Inspection sheet, and where its results are: (sheet, {"first": row, "last": row, "result": column of the
    first part's results or None})."""
    layout = layout or LAYOUT
    info, unit, chars = data.get("info") or {}, data.get("unit"), data["chars"]
    o = {}
    cols = []  # (key, heading, width)
    for key in layout["columns"]:
        if key == "results":
            cols += [("result", f"Part {i}" if parts > 1 else "Result", 11) for i in range(1, parts + 1)]
        elif key == "status":
            cols.append(("status", "Pass / Fail", 11))
        else:
            cols.append((key, COLUMNS[key][0], COLUMNS[key][1]))
    keys = [k for k, _, _ in cols]
    at = {k: keys.index(k) for k in set(keys)}  # (for "result": the first part's)
    res = [i for i, k in enumerate(keys) if k == "result"]
    value = min(3, len(cols) - 1)  # the column the answers at the top are written in

    def line(label, v):
        row = [None] * (value + 1)
        row[0], row[value] = (label, "label"), v
        return row

    head = [[(layout.get("title") or "Inspection report", "title")], line("Drawing", drawing)]
    head += [line(label, info.get(k, "")) for k, label, _ in INFO]
    head += [line("Date", datetime.date.today().isoformat()),
             line("Units", {"in": "inches", "mm": "millimeters"}.get(unit, "not stated on the print")),
             line("Title block tolerances", _tols_said(data.get("tols") or {}))]
    counts = len(head)  # the totals go here, once the rows they count are known
    head += [None, None, None, None]
    if res:
        head.append(line("How to fill it in", "Type each measurement under its part. For a characteristic that isn't measured, type Pass or Fail."))
    head.append([])
    first = len(head) + 2
    last = first + len(chars) - 1
    rows = head + [[(title, "head") for _, title, _ in cols]]
    for r, c in enumerate(chars, first):
        row = []
        rng = f"{xlsx.col(res[0])}{r}:{xlsx.col(res[-1])}{r}" if res else None
        for key in keys:
            if key == "result":
                row.append(("", "center"))
            elif key == "status":
                lim = {}
                for k in ("lo", "hi"):
                    lim[k] = None if c.get(k) is None else f"{xlsx.col(at[k])}{r}" if k in at else repr(float(c[k]))
                row.append(({"f": _status(rng, lim["lo"], lim["hi"])} if rng else "", "status"))
            else:
                row.append(COLUMNS[key][2](c, o))
        rows.append(row)
    if "status" in at and res:
        s = f"{xlsx.col(at['status'])}{first}:{xlsx.col(at['status'])}{last}"
        totals = [("Characteristics", len(chars)), ("Passed", {"f": f'COUNTIF({s},"Pass")'}), ("Failed", {"f": f'COUNTIF({s},"Fail")'}),
                  ("Not inspected yet", {"f": f'{len(chars)}-COUNTIF({s},"Pass")-COUNTIF({s},"Fail")'})]
    else:
        totals = [("Characteristics", len(chars))]
    for i in range(4):
        rows[counts + i] = line(*totals[i]) if i < len(totals) else []
    color = []
    if res:
        a = f"{xlsx.col(res[0])}{first}"
        out = [f"AND(ISNUMBER(${xlsx.col(at[k])}{first}),{a}{op}${xlsx.col(at[k])}{first})" for k, op in (("lo", "<"), ("hi", ">")) if k in at]
        when = f'{a}="Fail"' if not out else f'OR({a}="Fail",AND(ISNUMBER({a}),OR({",".join(out)})))'
        color.append({"range": f"{a}:{xlsx.col(res[-1])}{last}", "when": when, "as": "bad"})
        if "status" in at:
            s = f"{xlsx.col(at['status'])}{first}"
            rng = f"{s}:{xlsx.col(at['status'])}{last}"
            color += [{"range": rng, "when": f'{s}="Fail"', "as": "bad"}, {"range": rng, "when": f'{s}="Pass"', "as": "good"}]
    sheet = {"name": layout.get("name") or "Inspection", "rows": rows, "widths": [w for _, _, w in cols], "freeze": first - 1,
             "color": color, "landscape": True, "repeat": (first - 1, first - 1)}
    return sheet, {"first": first, "last": last, "result": res[0] if res else None}


def form3(data, drawing, source=None, where=None):
    """AS9102 Form 3. source: the Inspection sheet's name and where: its rows, for the results to follow the first
    part's there."""
    info, unit = data.get("info") or {}, data.get("unit")
    cols = ["5. Char. No.", "6. Reference Location", "7. Characteristic Designator", "8. Requirement", "9. Results",
            "10. Designed / Qualified Tooling", "11. Nonconformance Number", "Additional Data / Comments"]
    fields = [(field, info.get(k, "")) for k, _, field in INFO if field]
    rows = [[("AS9102 Form 3: Characteristic Accountability, Verification and Compatibility Evaluation", "title")],
            [(field, "head") for field, _ in fields], [(v, "center") for _, v in fields],
            [("Drawing", "label"), drawing, ("Revision", "label"), info.get("rev", "")], [],
            [(c, "head") for c in cols]]
    for i, c in enumerate(data["chars"]):
        req = c["text"]
        if c.get("lo") is not None and c.get("hi") is not None:
            p = max(c.get("places") or 0, 3 if unit != "mm" else 2)
            req += f"  ({balloons.fmt(c['lo'], p)} to {balloons.fmt(c['hi'], p)})"
        result = ""
        if source and where and where.get("result") is not None:
            cell = f"{xlsx.ref(source)}!{xlsx.col(where['result'])}{where['first'] + i}"
            result = {"f": f'IF({cell}="","",{cell})'}
        rows.append([(_n(c), "center"), (f"Sheet {c['page'] + 1}", "box"), ("", "box"), (req, "box"), (result, "center"),
                     ("", "box"), ("", "box"), ("", "box")])
    return {"name": "AS9102 Form 3", "rows": rows, "widths": [18, 22, 24, 44, 18, 24, 22, 30], "freeze": 6, "landscape": True, "repeat": (6, 6)}


def sheet(data, drawing, parts=PER, footer=""):
    """The inspection sheet: one page to print and fill in. Columns: number, description, gage, nominal, lower and
    upper limit, then PER parts; the table comes again for every further PER parts. footer: the shop's own lines
    for the bottom (its form number, its policy), one to a line."""
    info, chars = data.get("info") or {}, data["chars"]
    last_col = 5 + PER
    A = xlsx.col
    rows, merge, color = [], [], []

    def put(cells, look=None):
        """A row from {column: value or (value, look)}; look: every other cell's, for its border."""
        row = [("", look) if look else None for _ in range(last_col + 1)]
        for i, v in cells.items():
            row[i] = v
        rows.append(row)
        return len(rows)

    spans = [("Part Number:", "part", 0, 1), ("Revision:", "rev", 2, 2), ("Part Name:", "name", 3, 5), ("Customer:", "customer", 6, 8),
             ("Job #:", "job", 9, last_col)]
    r = put({a: (label, "head") for label, _, a, _ in spans}, "head")
    merge += [f"{A(a)}{r}:{A(b)}{r}" for _, _, a, b in spans if b > a]
    r = put({a: (info.get(k, ""), "center") for _, k, a, _ in spans}, "center")
    put({}, "center")
    merge += [f"{A(a)}{r}:{A(b)}{r + 1}" for _, _, a, b in spans]
    r = put({0: "☐ PROD Inspection Sheet     ☐ FINAL Inspection Sheet", 3: ("Inspection Frequency:", "label"), 6: (info.get("frequency", ""), "center"),
             **{i: ("", "center") for i in range(7, last_col + 1)}})
    merge += [f"{A(3)}{r}:{A(5)}{r}", f"{A(6)}{r}:{A(last_col)}{r}"]
    parts_blank = {i: ("", "center") for i in range(6, last_col + 1)}
    r = put({**{i: ("", "box") for i in range(5)}, 0: (f"Drawing: {drawing}", "box"), 5: ("Time   →", "label"), **parts_blank})
    put({**{i: ("", "box") for i in range(5)}, 5: ("Date   →", "label"), **parts_blank})
    put({**{i: ("", "box") for i in range(5)}, 5: ("Initial  →", "label"), **parts_blank})
    merge.append(f"{A(0)}{r}:{A(4)}{r + 2}")
    tables = -(-min(max(int(parts or 1), 1), MAX_PARTS) // PER)
    for t in range(tables):
        if t:
            put({})
            put({5: ("Initial  →", "label"), **parts_blank})
        r = put({0: ("DIMENSION DESCRIPTION", "head"), 2: ("GAGE", "head"), 3: ("Nominal", "head"), 4: ("Lower Limit", "head"), 5: ("Upper Limit", "head"),
                 **{i: ("Part # ____", "head") for i in range(6, last_col + 1)}}, "head")
        merge.append(f"{A(0)}{r}:{A(1)}{r}")
        first = r + 1
        for c in chars:
            cells = {0: (_n(c), "center"), 1: (describe(c), "box"), 2: (c.get("gage") or "", "box"), **parts_blank}
            if c.get("lo") is None and c.get("hi") is None:  # nothing to measure against: what the print says, across the three
                r = put({**cells, 3: (c.get("text") or "", "center"), 4: ("", "center"), 5: ("", "center")})
                merge.append(f"{A(3)}{r}:{A(5)}{r}")
            else:
                put({**cells, **{i: (c.get(k), _look(c)) if c.get(k) is not None else ("", "box") for i, k in ((3, "nominal"), (4, "lo"), (5, "hi"))}})
        if chars:
            a = f"{A(6)}{first}"
            color.append({"range": f"{a}:{A(last_col)}{len(rows)}", "as": "bad",
                          "when": f"AND(ISNUMBER({a}),OR(AND(ISNUMBER(${A(4)}{first}),{a}<${A(4)}{first}),AND(ISNUMBER(${A(5)}{first}),{a}>${A(5)}{first})))"})
    lines = [ln.strip() for ln in str(footer or "").splitlines() if ln.strip()]
    if lines:
        put({})
        for ln in lines:
            put({0: ln})
    return {"name": "Inspection Report", "rows": rows, "widths": [6, 26, 20, 10, 10, 10] + [10] * PER, "merge": merge, "color": color, "landscape": True}


def build(data, drawing, parts=1, layout=None, footer=""):
    """The workbook's sheets for an inspection list. layout: "sheet" (the page to fill in), "list" (Pass / Fail
    worked out, and AS9102 Form 3), or a list layout of your own like LAYOUT."""
    parts = min(max(int(parts or 1), 1), MAX_PARTS)
    if layout in (None, "sheet"):
        return [sheet(data, drawing, parts, footer)]
    page, where = inspection(data, drawing, parts, None if layout == "list" else layout)
    return [page, form3(data, drawing, page["name"], where)]
