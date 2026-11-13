"""Results from another program's export (a CMM's, a gage's, a spreadsheet): a table of rows, read from CSV, tab or
semicolon separated text, or an Excel workbook's first sheet, and matched to the balloons by their numbers.

table(path) gives the file's rows as lists of strings. guess(rows, labels) says which row is the heading, which
column holds the balloon numbers and which hold measurements, as a first pass for the person to check:
  {"head": row index or None, "key": column, "values": [columns], "part": column or None, "matched": rows that match}
Two shapes are understood. Wide: a row for each characteristic, a column for each part. Long: a row for each
measurement, with a column saying which part it was (a serial number) and one with the value.
label(cell) is the balloon number a cell names: "5", "#5", "DIM 5", "Char 2.1", "005" all name 5 or 2.1.
"""

import csv
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_BYTES = 30_000_000
MAX_ROWS = 20000
_NAME = re.compile(r"^\s*(?:#|no\.?|nr\.?|dim(?:ension)?|char(?:acteristic)?|balloon|item|feat(?:ure)?|bln|ch)\s*[#:.\-_ ]?\s*0*(\d{1,4}(?:\.\d{1,2}){0,2})\s*$", re.I)
_BARE = re.compile(r"^\s*0*(\d{1,4}(?:\.\d{1,2})?)\s*$")  # a number alone: 5, 005, 2.1 (not .005 or 5.000: those are sizes)
_SKIP = re.compile(r"\b(?:nom(?:inal)?|tol(?:erance)?|upper|lower|usl|lsl|min|max|limit|dev(?:iation)?|bonus|out(?:tol)?|"
                   r"spec|plus|minus|\+tol|-tol|req(?:uirement)?|desc(?:ription)?|unit|axis|type|gage|gauge|note|date|time)\b", re.I)
_WANT = re.compile(r"\b(?:meas(?:ured|urement)?|actual|value|result|reading|obs(?:erved)?|part|sample|s/?n|serial|piece|pc)\b", re.I)
_PART = re.compile(r"^\s*(?:part|sample|serial|s/?n|piece|pc|lot\s*/?\s*serial)\b", re.I)
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def label(cell):
    """The balloon number a cell names ("" for none)."""
    m = _NAME.match(str(cell or "")) or _BARE.match(str(cell or ""))
    return m.group(1) if m else ""


def _number(cell):
    try:
        float(str(cell).strip().replace(",", "."))
        return True
    except ValueError:
        return False


def _word(cell):
    return str(cell).strip().upper() in {"PASS", "FAIL", "OK", "NG", "P", "F", "ACCEPT", "REJECT", "GO", "NO GO", "NOGO"}


def table(path):
    """The file's rows, each a list of strings (an Excel workbook: its first sheet)."""
    p = Path(path)
    if p.stat().st_size > MAX_BYTES:
        raise ValueError(f"{p.name} is too big to read as results (over 30 MB).")
    raw = p.read_bytes()
    if raw[:2] == b"PK":
        return _xlsx(raw)
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = text.splitlines()[:MAX_ROWS]
    sample = "\n".join(lines[:50])
    counts = {d: sample.count(d) for d in ("\t", ";", ",")}
    sep = max(counts, key=counts.get) if any(counts.values()) else ","
    if sep == "," and counts[";"] and counts[";"] >= counts[","] * 0.5:
        sep = ";"  # (European numbers: 2,375 inside ; separated rows)
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=sep))
    return [[c.strip() for c in r] for r in rows if any(c.strip() for c in r)]


def _xlsx(raw):
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ValueError("That file isn't a table this can read: save it as CSV, text or an Excel workbook (.xlsx).") from None
    names = set(z.namelist())
    strings = []
    if "xl/sharedStrings.xml" in names:
        for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            strings.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
    sheet = "xl/worksheets/sheet1.xml"
    try:  # the first sheet as the workbook lists it
        wb = ElementTree.fromstring(z.read("xl/workbook.xml"))
        first = wb.find("m:sheets/m:sheet", _NS)
        rid = first.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        rels = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for rel in rels:
            if rel.get("Id") == rid:
                target = rel.get("Target").lstrip("/")
                sheet = target if target.startswith("xl/") else f"xl/{target}"
    except Exception:
        pass
    if sheet not in names:
        raise ValueError("That workbook has no sheet this can read.")
    rows = []
    for row in ElementTree.fromstring(z.read(sheet)).iter(f"{{{_NS['m']}}}row"):
        cells = {}
        for c in row.findall("m:c", _NS):
            ref, kind = c.get("r") or "", c.get("t")
            col = 0
            for ch in re.match(r"[A-Z]*", ref).group():
                col = col * 26 + ord(ch) - 64
            col = (col or len(cells) + 1) - 1
            if kind == "inlineStr":
                v = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            else:
                node = c.find("m:v", _NS)
                v = "" if node is None or node.text is None else node.text
                if kind == "s" and v.isdigit() and int(v) < len(strings):
                    v = strings[int(v)]
                elif kind not in ("str", "s", "b", "e") and _number(v):
                    f = float(v)  # (Excel keeps 2.375 as 2.3750000000000004 now and then)
                    v = repr(round(f, 9)).rstrip("0").rstrip(".") if "." in repr(round(f, 9)) else str(int(f))
            cells[col] = v.strip()
        if cells and any(cells.values()):
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        if len(rows) >= MAX_ROWS:
            break
    return rows


def guess(rows, labels):
    """Which row is the heading and which columns hold what (see the top of this file). labels: the balloons' numbers
    as the list shows them ("1", "2.1"...)."""
    labels = set(labels)
    width = max((len(r) for r in rows), default=0)
    out = {"head": None, "key": None, "values": [], "part": None, "matched": 0}
    if not rows or not width:
        return out
    cell = lambda r, c: rows[r][c] if c < len(rows[r]) else ""  # noqa: E731
    hits = [sum(1 for r in range(len(rows)) if label(cell(r, c)) in labels) for c in range(width)]
    key = max(range(width), key=lambda c: (hits[c], -c))
    if not hits[key]:
        return out
    body = [r for r in range(len(rows)) if label(cell(r, key)) in labels]
    first = body[0]
    head = next((r for r in range(first - 1, -1, -1) if sum(1 for c in range(width) if cell(r, c) and not _number(cell(r, c))) >= 2), None)
    name = lambda c: cell(head, c) if head is not None else ""  # noqa: E731
    out.update(head=head, key=key, matched=len(body))
    # a part column (long shape): one named so, or the one whose values repeat across the balloons
    for c in range(width):
        if c != key and head is not None and _PART.match(name(c)) and not _number(cell(body[0], c)) or \
                (c != key and head is not None and _PART.match(name(c)) and len({cell(r, c) for r in body}) < len(body)):
            vals = {cell(r, c) for r in body}
            keys = [label(cell(r, key)) for r in body]
            if 1 < len(vals) < len(body) and len(set(keys)) < len(keys):
                out["part"] = c
                break
    scored = []
    for c in range(width):
        if c in (key, out["part"]):
            continue
        filled = [cell(r, c) for r in body if cell(r, c)]
        fit = sum(1 for v in filled if _number(v) or _word(v))
        if not filled or fit < 0.6 * len(filled):
            continue
        n = name(c)
        if n and _SKIP.search(n) and not _WANT.search(n):
            continue
        scored.append((2 if n and _WANT.search(n) else 1, c))
    if scored:
        best = max(s for s, _ in scored)
        out["values"] = [c for s, c in scored if s == best]
        if out["part"] is not None:
            out["values"] = out["values"][:1]
    return out
