"""What hovering the words on a print shows: a metric size in inches, an ISO fit's limits (H is a hole, h a shaft),
French in English. From the Quote Board's preview/printmarks.py, with the PDF's text read through QtPdf.

Marks are boxes on a page, in points from the top left of the page as shown (a picture's pixel is 0.75 point):
{"x", "y", "w", "h", "kind": "dim" | "fit" | "fr", "text", "tip", "ocr": bool}
A PDF's own text is exact and instant (text_marks); Windows' own OCR finds what's drawn as lines (ocr_marks). Both
run on this computer only: nothing is sent anywhere.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import fits, french

OCR_SCRIPT = Path(__file__).with_name("ocr.ps1")
OCR_MAX = 9800  # px: Windows OCR's largest image side is 10000
OCR_DPI = 400  # a page is drawn this sharp for OCR: 0.1" text is 40 px tall

_NUM = r"\d+(?:[.,]\d+)?|[.,]\d+"
_CLS = r"(?:JS|js|[A-HKMNPRSTUa-hkmnprstu])\d{1,2}"
DIM = re.compile(rf"^(?P<count>\d+\s*[xX×]\s*)?(?P<pre>[Ø⌀∅øΦφ]|R|r)?\s*(?P<num>{_NUM})\s*(?:mm)?\s*"
                 rf"(?P<fit>{_CLS}(?:\s*/\s*{_CLS})?)?\s*"
                 rf"(?:(?P<pm>±\s*(?:{_NUM}))|(?P<up>\+\s*(?:{_NUM}))\s*/?\s*(?P<dn>-\s*(?:{_NUM})))?$")
SIGNED = re.compile(r"^(?P<sign>[+\-±])\s?(?P<num>\d*[.,]\d+)$")  # a stacked tolerance has its decimals
_OCR_DIA = re.compile(rf"^[0O@Q]\s?(?=[1-9]\d*(?:[.,]\d+)?(?:\s*{_CLS})?$)")  # OCR reads Ø as 0, O or @
METRIC = re.compile(r"\b(mm|millim[eè]tres?|millimeters?|metric|m[eé]trique|iso\s*2768|iso\s*286|din\s*\d|nf\s*e)\b", re.I)
ALLOYS = {"1045", "1100", "2011", "2017", "2024", "3003", "4140", "4340", "5052", "5083", "5754", "6060", "6061", "6063", "6082", "7050", "7075"}
INCH = re.compile(r"\b(inch|inches|pouces|unc|unf|ansi|asme\s*y14)\b", re.I)


def _f(text):
    return float(text.replace(" ", "").replace(",", "."))


def _in(mm, signed=False):
    return f"{mm / 25.4:+.4f}" if signed else f"{mm / 25.4:.4f}"


def _um(v):
    return "0" if not v else f"{v:+g}"


def _trim(mm):
    return f"{mm:.3f}"


def describe(text, ocr=False):
    """(kind, tip) for a size on a print, or None if it isn't one. Kinds: 'fit' has an ISO class, 'dim' is a plain size."""
    t = re.sub(r"\s*\([a-zA-Z]\)$", "", text.strip())  # 14,5(a): the size changed at revision a
    t = re.sub(r"^=\s*|\s*=$", "", t)  # =30=: centered about the axis
    t = re.sub(r"\s*\([+\-±][\d.,\s/+\-]*\)$", "", t)  # 25 H7 (+0.021): the print's own limit beside the class
    t = re.sub(r"^P(?=\d)", "Ø", t)  # some CAD fonts give Ø as P
    if ocr:  # how OCR misreads these: Ø25 as 025, H7 as 1-17, H11 as Hli
        t = re.sub(r"(?<![\w-])[1lI]-+[1lI](\d{1,2})$", r"H\1", t)
        t = re.sub(r"(?<![\w-])([A-Za-z])[lIi1]{2}$", r"\g<1>11", t)
        t = re.sub(r"(\d)[1lI]-+[14](\d{1,2})$", r"\1H\2", t)  # 701-47: 70H7
        t = _OCR_DIA.sub("Ø", t)
    m = SIGNED.match(t)
    if m:  # one line of a stacked tolerance
        v = _f(m.group("num"))
        return "dim", f"{m.group('sign')}{_in(v)} in"
    m = DIM.match(t)
    if not m:
        return None
    size = _f(m.group("num"))
    if size <= 0 or size > 6000 or re.match(r"0\d", m.group("num")) or (not m.group("pre") and not m.group("fit") and m.group("num") in ALLOYS):
        return None
    head = f"{m.group('pre') or ''}{m.group('num')}"
    if m.group("fit"):
        lines = []
        for cls in re.split(r"\s*/\s*", m.group("fit")):
            lim = fits.limits(size, cls)
            if lim is None:
                lines.append(f"{head} {cls}: {_in(size)} in nominal (this class isn't in the fit table)")
                continue
            lines += [f"{head} {cls}  ·  {lim['kind']}  ·  {_um(lim['lo_um'])} / {_um(lim['hi_um'])} µm",
                      f"{_trim(lim['min_mm'])} to {_trim(lim['max_mm'])} mm",
                      f"{lim['min_in']:.4f} to {lim['max_in']:.4f} in"]
        if ocr:
            lines.append("Read by OCR: check H vs h on the print")
        return "fit", "\n".join(lines)
    if m.group("pm"):
        d = _f(m.group("pm")[1:])
        return "dim", f"{_in(size)} ±{_in(d)} in\n{_in(size - d)} to {_in(size + d)} in"
    if m.group("up"):
        up, dn = _f(m.group("up")[1:]), _f(m.group("dn")[1:])
        return "dim", f"{_in(size)} +{_in(up)} / -{_in(dn)} in\n{_in(size - dn)} to {_in(size + up)} in"
    return "dim", f"{m.group('pre') or ''}{_in(size)} in"


def is_metric(lines, marks=()):
    """Does this print look like it's in millimeters? (A fit class, a French print or decimal commas say yes.)"""
    text = " ".join(lines)
    if INCH.search(text) and not METRIC.search(text):
        return False
    return bool(METRIC.search(text) or french.looks_french(lines) or any(m["kind"] == "fit" for m in marks)
                or re.search(r"(?<![\d.,])\d{1,3},\d{1,3}(?![\d.,])", text))


def _box(words):
    x0, y0 = min(w[1] for w in words), min(w[2] for w in words)
    return {"x": x0, "y": y0, "w": max(w[3] for w in words) - x0, "h": max(w[4] for w in words) - y0}


def _scan(words, ocr):
    """Marks for one line of (text, x0, y0, x1, y1) words: the longest run of words that reads as a size, left to right."""
    out, i = [], 0
    while i < len(words):
        for k in range(min(5, len(words) - i), 0, -1):
            run = words[i:i + k]
            text = " ".join(w[0] for w in run)
            hit = describe(text, ocr)
            before = words[i - 1][0].upper() if i else ""
            after = words[i + k][0] if i + k < len(words) else ""
            if hit and (before in ("ISO", "NF", "DIN", "EN", "N°", "NO", "TEL", "TÉL") or after.startswith("°")):
                hit = None  # a standard's number, or an angle
            if hit:
                out.append({**_box(run), "kind": hit[0], "text": text, "tip": hit[1], "ocr": ocr})
                i += k
                break
        else:
            i += 1
    return out


def _fr(words, ocr):
    """A French line's English, over the whole line."""
    text = " ".join(w[0] for w in words)
    en = french.changed(re.sub(r"\bIes\b", "les", text) if ocr else text)  # OCR's I for l
    if not en:
        return []
    return [{**_box(words), "kind": "fr", "text": text, "tip": _wrap(en), "ocr": ocr}]


def _wrap(text, width=64):
    out, line = [], ""
    for w in text.split():
        if line and len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    return "\n".join(out + [line])


def lines_marks(lines, ocr):
    """lines: [[word box, ...], ...]. (Size marks, then English for the lines of a French print; the lines' texts.)"""
    texts = [" ".join(w[0] for w in ln) for ln in lines]
    marks = [m for ln in lines for m in _scan(ln, ocr)]
    if french.looks_french(texts):
        marks += [m for ln in lines for m in _fr(ln, ocr)]
    return marks, texts


def merge(have, new, words=()):
    """OCR's marks that aren't over a mark already there, or over the PDF's own text (which is exact; OCR's reading of it isn't)."""
    out = list(have)
    boxes = [(o["x"], o["y"], o["x"] + o["w"], o["y"] + o["h"]) for o in have] + list(words)
    for m in new:
        x0, y0, x1, y1 = m["x"], m["y"], m["x"] + m["w"], m["y"] + m["h"]
        if not any(x0 < b[2] and b[0] < x1 and y0 < b[3] and b[1] < y1 for b in boxes):
            out.append(m)
            boxes.append((x0, y0, x1, y1))
    return out


# ---------------------------------------------------------------------------------------------- the PDF's own text
def word_lines(chars):
    """A page's letters [(text, x0, y0, x1, y1)] (points, y down, in the PDF's text order, as PDFium reads it with its
    spaces and line breaks) as lines of word boxes [(word, x0, y0, x1, y1)]. A letter with no box (a space PDFium
    put in) has x1 <= x0. When a CAD export has left PDFium one letter per line, lines are rebuilt from where the
    letters sit instead (level text only: OCR's turned pass finds what runs up the page)."""
    lines, line, word = [], [], []

    def end_word():
        nonlocal word
        boxed = [c for c in word if c[3] > c[1]]
        if boxed:
            line.append(("".join(c[0] for c in word), min(c[1] for c in boxed), min(c[2] for c in boxed),
                         max(c[3] for c in boxed), max(c[4] for c in boxed)))
        word = []

    for c in chars:
        if c[0] in "\r\n":
            end_word()
            if line:
                lines.append(line)
            line = []
        elif not c[0].strip():
            end_word()
        else:
            word.append(c)
    end_word()
    if line:
        lines.append(line)
    letters = sum(len(w[0]) for ln in lines for w in ln)
    if lines and letters / len(lines) >= 3:  # real lines: PDFium's reading holds
        return lines
    return _rebuilt_lines(chars)


def _rebuilt_lines(chars):
    """Lines rebuilt from where each letter sits, for PDFs whose text runs one letter at a time."""
    spaced, pieces = set(), []
    for c in chars:
        if c[0] in "\r\n":  # PDFium's line breaks (here, often one between every letter) aren't spaces
            continue
        if not c[0].strip():
            if pieces:
                spaced.add(len(pieces) - 1)  # the PDF puts a space after this letter, however small the gap
            continue
        x0, y0, x1, y1 = c[1:]
        if x1 > x0 and y1 > y0 and (x1 - x0) < 3 * (y1 - y0):  # a letter on a level line (not one turned up the page)
            pieces.append(c)
    rows = []
    for n, p in sorted(enumerate(pieces), key=lambda q: ((q[1][2] + q[1][4]) / 2, q[1][1])):
        mid, h = (p[2] + p[4]) / 2, max(p[4] - p[2], 1)
        row = next((rw for rw in rows if abs(rw["mid"] - mid) < 0.45 * max(h, rw["h"])), None)
        if row is None:
            rows.append({"mid": mid, "h": h, "ps": [(n, p)]})
        else:
            row["ps"].append((n, p))
    lines = []
    for rw in rows:
        ps = sorted(rw["ps"], key=lambda q: q[1][1])
        line, word, last, last_n = [], [], None, None
        for n, p in ps:
            gap = None if last is None else p[1] - last
            if gap is not None and gap > 1.2 * rw["h"]:  # a column apart: another line of the title block
                if word:
                    line.append(word)
                if line:
                    lines.append(line)
                line, word = [], []
            elif gap is not None and word and (gap > 0.2 * rw["h"] or (gap > 0.04 * rw["h"] and last_n in spaced)):
                line.append(word)
                word = []
            word.append(p)
            last, last_n = p[3], n
        if word:
            line.append(word)
        if line:
            lines.append(line)
    return [[("".join(c[0] for c in w), min(c[1] for c in w), min(c[2] for c in w), max(c[3] for c in w), max(c[4] for c in w))
             for w in line] for line in lines]


def text_marks(chars):
    """(marks, lines' texts, word boxes) from a page's own letters. Exact, instant."""
    return _from_lines(word_lines(chars))


def _from_lines(lines):
    marks, texts = lines_marks(lines, False)
    return marks, texts, [w[1:] for ln in lines for w in ln]


def _qt_box(doc, page, start, length):
    """(x0, y0, x1, y1) in points around a run of a page's text (QtPdf), or None."""
    rects = [poly.boundingRect() for poly in doc.getSelectionAtIndex(page, start, length).bounds()]
    rects = [r for r in rects if r.width() > 0 and r.height() > 0]
    if not rects:
        return None
    return (min(r.x() for r in rects), min(r.y() for r in rects), max(r.x() + r.width() for r in rects),
            max(r.y() + r.height() for r in rects))


def pdf_text_marks(doc, page, text):
    """(marks, lines' texts, word boxes) for a page of a QPdfDocument whose text (getAllText) is `text`: a box per
    word, as asking for every letter's box is slow on a busy sheet."""
    lines = []
    for m in re.finditer(r"[^\r\n]+", text):
        line = []
        for w in re.finditer(r"\S+", m.group()):
            box = _qt_box(doc, page, m.start() + w.start(), len(w.group()))
            if box:
                line.append((w.group(), *box))
        if line:
            lines.append(line)
    letters = sum(len(w[0]) for ln in lines for w in ln)
    if lines and letters / len(lines) < 3:  # one letter at a time (some CAD exports): rebuild from each letter's place
        chars = []
        for i, ch in enumerate(text):
            box = _qt_box(doc, page, i, 1) if ch.strip() else None
            chars.append((ch, *(box or (0, 0, 0, 0))))
        lines = _rebuilt_lines(chars)
    return _from_lines(lines)


# ---------------------------------------------------------------------------------------------- OCR
def ocr_available():
    return sys.platform == "win32" and OCR_SCRIPT.is_file()


def ocr_images(imgs):
    """Windows OCR on QImages: a list (one per image) of lines {"text", "x", "y", "w", "h", "words": [...]}, in pixels."""
    from PySide6.QtGui import QImage
    tmp = tempfile.mkdtemp(prefix="solidsmufs-ocr-")
    files = []
    try:
        for i, img in enumerate(imgs):
            f = os.path.join(tmp, f"{i}.png")
            # grey: OCR doesn't use colour, and a grey PNG of a big sheet saves 3x faster
            if not img.convertToFormat(QImage.Format.Format_Grayscale8).save(f, "PNG"):
                raise ValueError("Couldn't prepare the page for reading.")
            files.append(f)
        run = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(OCR_SCRIPT), *files],
                             capture_output=True, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        results = [None] * len(files)
        for line in run.stdout.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line.startswith("{"):
                res = json.loads(line)
                if "lines" in res:
                    lines = res.get("lines") or []
                    results[res["i"]] = [lines] if isinstance(lines, dict) else lines
        if run.returncode != 0 or any(r is None for r in results):
            err = run.stderr.decode("utf-8", "replace").strip().splitlines()
            raise ValueError("Windows OCR couldn't read it: " + (next((e for e in err if e.strip()), "") or "no answer")[:200])
        return results
    finally:
        for f in files:
            try:
                os.remove(f)
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass


def ocr_marks(img, k=1.0):
    """(marks, lines' texts) from a QImage by Windows OCR, level and turned a quarter turn. k: points per image pixel."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QPainter, QTransform

    if max(img.width(), img.height()) > OCR_MAX:
        f = OCR_MAX / max(img.width(), img.height())
        img = img.scaledToWidth(int(img.width() * f), Qt.TransformationMode.SmoothTransformation)
        k /= f
    H = img.height()
    level = ocr_images([img])[0] or []
    # the level text whited out, then turned: OCR gives up on a page that's mostly sideways lines to it
    blank = img.copy()
    p = QPainter(blank)
    for ln in level:
        p.fillRect(QRect(ln["x"] - 2, ln["y"] - 2, ln["w"] + 4, ln["h"] + 4), Qt.GlobalColor.white)
    p.end()
    res = [level, ocr_images([blank.transformed(QTransform().rotate(90))])[0]]
    lines = []
    for n, page in enumerate(res):
        for ln in page or []:
            words = ln.get("words") or []
            words = [words] if isinstance(words, dict) else words
            boxes = []
            for w in words:
                x, y, ww, hh = w["x"], w["y"], w["w"], w["h"]
                if n == 1:  # turned 90° clockwise: (x, y) on the turned picture was (y, H - x) on the page
                    x, y, ww, hh = y, H - x - ww, hh, ww
                boxes.append((w["text"], x * k, y * k, (x + ww) * k, (y + hh) * k))
            if boxes:
                lines.append(boxes)
    return lines_marks(lines, True)
