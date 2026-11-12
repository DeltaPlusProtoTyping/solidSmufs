"""A print's part difficulty with no window, for other programs (a quoting system):

    python -m solidsmufs --difficulty print.pdf [--out result.json] [--password word] [--no-ocr]
    SolidSmurfs.exe --difficulty print.pdf --out result.json      (the built app has no console to print to)

or from Python: solidsmufs.difficulty.read("print.pdf"). The print (a PDF, a picture or a scan) is read the way
the window reads it for hovering: its own text, then Windows OCR and the drawn symbols, every page; the geometric
tolerances found are scored and totalled by kernel/gdt.py, where the tables to tune are.

The answer (FORMAT 1; fields may be added, these stay):
    {"format": 1, "file", "score": 1 to 10 or null when no geometric tolerance was found, "points", "count",
     "units": "in" | "mm" | null, "pages", "complete": every page read through (OCR and all),
     "ocr": "done" | "off" | "error", "callouts": [{"callout", "machining", "measuring", "multiplier", "points"}, ...]
     hardest first}
"""

import json
import sys
import time
from pathlib import Path

FORMAT = 1


def read(path, password="", ocr=True, timeout=300.0):
    """The part difficulty of the print at `path`, as the dict above. ValueError when the file can't be read (or
    isn't a print: a PDF or a picture)."""
    from .kernel import printmarks
    from .kernel.formats import PDF_FORMATS, PICTURE_FORMATS
    path = Path(path)
    if path.suffix.lower() not in {**PDF_FORMATS, **PICTURE_FORMATS}:
        raise ValueError("Part difficulty is read from a print: a PDF, a picture or a scan.")
    if not path.is_file():
        raise ValueError(f"There's no file at {path}.")
    available = printmarks.ocr_available
    if not ocr:
        printmarks.ocr_available = lambda: False
    try:
        return _read(path, password, timeout)
    finally:
        printmarks.ocr_available = available


def _read(path, password, timeout):
    from .kernel import printmarks
    from .kernel.worker import Session
    s = Session()
    s.open(str(path), password=password or None)
    if s.pdf is None:
        raise ValueError("That file has no pages to read.")
    pages = len(s.pdf.pages())
    end, last, complete = time.monotonic() + timeout, None, True
    for page in range(pages):
        while True:
            last = s.pdf_marks(page)
            if not last["reading"] and last["ocr"] != "pending":
                break
            if time.monotonic() > end:
                complete = False
                break
            if not last["reading"]:
                time.sleep(0.05)  # Windows OCR is reading the page on its own thread
        if not complete:
            break
    last = s.pdf_marks(max(pages - 1, 0)) if last is None else s.pdf_marks(min(page, pages - 1))
    part = last.get("part") or {}
    states = {e["ocr"] for e in s._marks.values()}
    texts = [t for e in s._marks.values() for t in e["texts"]]
    marks = [m for e in s._marks.values() for m in e["marks"]]
    out = {"format": FORMAT, "file": str(path), "score": part.get("score"), "points": part.get("points", 0.0),
           "count": part.get("count", 0), "units": printmarks.units(texts, marks), "pages": pages, "complete": complete,
           "ocr": "error" if "error" in states else "off" if states <= {"off"} else "done",
           "callouts": [{"callout": i["head"], "machining": i["machining"], "measuring": i["measuring"],
                         "multiplier": i["mult"], "points": i["points"]} for i in part.get("items", [])]}
    s.pdf.close()
    return out


def main(argv):
    """--difficulty FILE [--out FILE] [--password WORD] [--no-ocr]: the answer as JSON, printed or written to --out.
    Returns the exit code: 0, or 2 with {"error": "..."} when the print couldn't be read."""
    def value(flag):
        i = argv.index(flag)
        if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
            raise ValueError(f"{flag} needs a value after it.")
        return argv[i + 1]
    out_path, code = None, 0
    try:
        out_path = value("--out") if "--out" in argv else None
        result = read(value("--difficulty"), password=value("--password") if "--password" in argv else "",
                      ocr="--no-ocr" not in argv)
    except Exception as e:  # whatever went wrong, the caller gets it as JSON
        result, code = {"format": FORMAT, "error": str(e) or type(e).__name__}, 2
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
    elif sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
        print(text)
    return code
