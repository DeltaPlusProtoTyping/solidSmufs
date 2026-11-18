"""Finding a PDF's watermarks and taking them out (Edit > Remove watermark, in kernel/pdfedit.py).

Three kinds, each found the way the program that made it marks it:
- "annot": watermark comments (an annotation of subtype /Watermark), which most viewers can't select;
- "tagged": what the page itself draws inside marked content that says it's a watermark: Acrobat's Add Watermark and
  Word's (/Artifact <</Subtype /Watermark ...>> BDC ... EMC), or a layer named watermark (/OC naming an optional content
  group called "Watermark"). The whole marked block is cut out of the content stream, whatever it draws (text, outlines,
  pictures), on the page and in the forms (XObjects) it draws;
- "text": large or tilted words repeated on the pages (DRAFT, CONFIDENTIAL, COPY), with nothing saying it's a
  watermark. They're taken out letter by letter as a redaction does; a page where they overlap other words keeps them
  there (taking them out would take those words too), and is said.
Nothing else on the page changes.
"""

import math
import re

WS = b" \t\r\n\f\x00"
DELIM = b"()<>[]{}/%"


def _tokens(data):
    """The content stream's operators in order: (operands start, operator start, operator end, operator)."""
    i, n, start = 0, len(data), 0
    while i < n:
        c = data[i:i + 1]
        if c in (b" ", b"\t", b"\r", b"\n", b"\f", b"\x00"):
            i += 1
        elif c == b"%":
            while i < n and data[i:i + 1] not in (b"\r", b"\n"):
                i += 1
        elif c == b"(":
            depth, i = 1, i + 1
            while i < n and depth:
                ch = data[i:i + 1]
                if ch == b"\\":
                    i += 2
                    continue
                depth += 1 if ch == b"(" else -1 if ch == b")" else 0
                i += 1
        elif data[i:i + 2] in (b"<<", b">>"):
            i += 2
        elif c == b"<":
            j = data.find(b">", i)
            i = n if j < 0 else j + 1
        elif c in (b"[", b"]", b"{", b"}"):
            i += 1
        elif c == b"/":
            i += 1
            while i < n and data[i] not in WS and data[i] not in DELIM:
                i += 1
        else:
            j = i
            while j < n and data[j] not in WS and data[j] not in DELIM:
                j += 1
            word = data[i:j]
            if j == i:
                i += 1
                continue
            if re.fullmatch(rb"[+-]?(\d+\.?\d*|\.\d+)", word) or word in (b"true", b"false", b"null"):
                i = j
                continue
            if word == b"BI":  # an inline picture: its data runs to EI on its own
                m = re.compile(rb"\sID\s").search(data, j)
                k = m.end() if m else n
                e = re.compile(rb"\sEI(?=[\s]|$)").search(data, k)
                end = e.end() if e else n
                yield start, i, end, b"BI"
                i = start = end
                continue
            yield start, i, j, word
            i = start = j


def _resolve(doc, val):
    """A PDF value as text, an indirect one looked up."""
    m = re.fullmatch(r"\s*(\d+)\s+0\s+R\s*", val or "")
    return doc.xref_object(int(m.group(1))) if m else (val or "")


def _value(text, key):
    """The value of /key in a dictionary written out as text: a dictionary (nested ones and all), a reference, or a
    single token. "" when there's none."""
    m = re.search(rf"/{re.escape(key)}(?=[\s/<\[(])\s*", text or "")
    if not m:
        return ""
    rest = text[m.end():]
    if rest.startswith("<<"):
        depth, i = 0, 0
        while i < len(rest):
            if rest.startswith("<<", i):
                depth, i = depth + 1, i + 2
            elif rest.startswith(">>", i):
                depth, i = depth - 1, i + 2
                if not depth:
                    return rest[:i]
            else:
                i += 1
        return rest
    r = re.match(r"\d+\s+0\s+R|/?[^\s/<>\[\]()]+", rest)
    return r.group(0) if r else ""


def _named(doc, res, kind, name):
    """The object a resource dictionary names (`kind` /Properties or /XObject), as text, or ""."""
    table = _resolve(doc, _value(res, kind))
    return _resolve(doc, _value(table, name)) if table else ""


def _is_mark(doc, res, operands):
    """Does a BDC's operands (its tag and properties) say a watermark is inside?"""
    text = operands.decode("latin-1")
    m = re.match(r"\s*/(\w+)\s*(.*)$", text, re.S)
    if not m:
        return False
    tag, props = m.group(1), m.group(2).strip()
    if props.startswith("/"):
        props = _named(doc, res, "Properties", props[1:].split()[0])
    if tag == "Artifact":
        return bool(re.search(r"/Subtype\s*/Watermark\b", props))
    if tag == "OC":
        return bool(re.search(r"/Name\s*\(([^)]*watermark[^)]*)\)", props, re.I))
    return False


def cut(doc, data, res):
    """The content stream without its watermark blocks: (new bytes, how many were cut). A block whose q and Q don't
    balance is left (cutting it would change how the rest is drawn)."""
    out, last, cuts, stack = [], 0, 0, []
    ops = list(_tokens(data))
    for k, (s, o, e, op) in enumerate(ops):
        if op in (b"BDC", b"BMC"):
            stack.append((s, k, op == b"BDC" and _is_mark(doc, res, data[s:o])))
        elif op == b"EMC" and stack:
            s0, k0, mark = stack.pop()
            if mark and not any(m for _, _, m in stack):
                inner = [x[3] for x in ops[k0 + 1:k]]
                if inner.count(b"q") == inner.count(b"Q") and s0 >= last:
                    out.append(data[last:s0])
                    last, cuts = e, cuts + 1
    out.append(data[last:])
    return b"".join(out), cuts


def _resources(doc, xref):
    """A page's or form's /Resources as text (a page's maybe from its parents)."""
    seen = 0
    while xref and seen < 32:
        kind, val = doc.xref_get_key(xref, "Resources")
        if kind != "null":
            return _resolve(doc, val)
        kind, val = doc.xref_get_key(xref, "Parent")
        xref = int(val.split()[0]) if kind == "xref" else 0
        seen += 1
    return ""


def _forms(doc, res):
    """The forms (XObjects of subtype /Form) a resource dictionary names: [xref]."""
    table = _resolve(doc, _value(res, "XObject"))
    if not table:
        return []
    out = []
    for x in re.findall(r"/[^\s/<>\[\]()]+\s+(\d+)\s+0\s+R", table):
        x = int(x)
        if doc.xref_get_key(x, "Subtype")[1] == "/Form":
            out.append(x)
    return out


def tagged(doc, page, apply=False):
    """The tagged watermark blocks on a page and in the forms it draws: how many (cut out when `apply`)."""
    pg = doc[page]
    res = _resources(doc, pg.xref)
    total = 0
    xrefs = pg.get_contents()
    if xrefs:
        data = b"\n".join(doc.xref_stream(x) or b"" for x in xrefs)
        new, n = cut(doc, data, res)
        total += n
        if apply and n:
            doc.update_stream(xrefs[0], new)
            if len(xrefs) > 1:
                pg.set_contents(xrefs[0])
    seen, todo = set(), list(_forms(doc, res))
    while todo:
        x = todo.pop()
        if x in seen:
            continue
        seen.add(x)
        fres = _resources(doc, x) or res
        new, n = cut(doc, doc.xref_stream(x) or b"", fres)
        total += n
        if apply and n:
            doc.update_stream(x, new)
        todo += _forms(doc, fres)
    return total


def annots(doc, page, apply=False):
    """Watermark comments on a page: how many (taken off when `apply`)."""
    pg = doc[page]
    kind, val = doc.xref_get_key(pg.xref, "Annots")
    if kind == "null":
        return 0
    arr = _resolve(doc, val) if kind == "xref" else val
    refs = re.findall(r"(\d+)\s+0\s+R", arr)
    gone = [r for r in refs if doc.xref_get_key(int(r), "Subtype")[1] == "/Watermark"]
    if apply and gone:
        keep = [r for r in refs if r not in gone]
        new = "[" + " ".join(f"{r} 0 R" for r in keep) + "]"
        if kind == "xref":
            doc.update_object(int(val.split()[0]), new)
        else:
            doc.xref_set_key(pg.xref, "Annots", new)
    return len(gone)


def _key(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _lines(pg):
    """The page's lines of text with their letters: [{"key", "text", "size", "tilted", "alpha", "chars": [Rect]}]."""
    import pymupdf
    out = []
    for b in pg.get_text("rawdict", flags=0)["blocks"]:
        for ln in b.get("lines", []):
            dx, dy = ln["dir"]
            chars = [c for s in ln["spans"] for c in s["chars"] if c["c"].strip()]
            if not chars:
                continue
            text = "".join(c["c"] for s in ln["spans"] for c in s["chars"])
            out.append({"key": _key(text), "text": text.strip(), "size": max(s["size"] for s in ln["spans"]),
                        "tilted": abs(dx) > 0.05 and abs(dy) > 0.05, "alpha": min(s.get("alpha", 255) for s in ln["spans"]),
                        "chars": [pymupdf.Rect(c["bbox"]) for c in chars]})
    return out


def words(doc):
    """Large or tilted words repeated on the pages, as a watermark is: {key: {"text", "pages": [page]}}. On a single
    page, tilted words of 24 points or more."""
    pages = doc.page_count
    seen = {}
    for i in range(pages):
        for ln in _lines(doc[i]):
            if len(ln["key"]) < 3:
                continue
            big = ln["tilted"] and ln["size"] >= 18 or ln["size"] >= 48 or (ln["alpha"] < 255 and ln["size"] >= 24)
            if big:
                hit = seen.setdefault(ln["key"], {"text": ln["text"], "pages": [], "tilted": ln["tilted"], "size": ln["size"]})
                if i not in hit["pages"]:
                    hit["pages"].append(i)
    need = 1 if pages == 1 else max(2, math.ceil(pages / 2))
    return {k: v for k, v in seen.items() if len(v["pages"]) >= need and (pages > 1 or (v["tilted"] and v["size"] >= 24))}


def word_boxes(pg, keys):
    """The letters of these watermark words on a page, to take out: (boxes, kept) where kept says the words left
    because they overlap the page's other words."""
    lines = _lines(pg)
    mine = [ln for ln in lines if ln["key"] in keys]
    others = [r for ln in lines if ln["key"] not in keys for r in ln["chars"]]
    boxes, kept = [], []
    for ln in mine:
        clash = any(c.intersects(o) and (c & o).get_area() > 0.05 * min(c.get_area(), o.get_area()) for c in ln["chars"] for o in others)
        if clash:
            kept.append(ln["text"])
        else:
            boxes += ln["chars"]
    return boxes, kept
