"""Autosave for PDF edits, as recovery copies (Word's AutoRecover, in effect).

A PDF with edits not saved is written, a little after each change, to %LOCALAPPDATA%\\SolidSmufs\\recovery: the PDF
as it is with the edits, and beside it what it's a copy of. The print itself changes only when it's saved. Saving,
closing with Don't Save, or undoing back to what was saved clears the copy; so if one is still there when the PDF is
opened again, the app (or the computer) stopped before the edits were saved, and the window offers them back.
"""

import datetime
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

AFTER_S = 15.0  # seconds after an edit that the copy is written (edits in between go with it)
KEEP_DAYS = 30  # copies older than this are let go


def folder():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SolidSmufs" / "recovery"


def _files(path):
    key = hashlib.sha1(os.path.normcase(os.path.abspath(str(path))).encode("utf-8")).hexdigest()[:20]
    base = folder() / key
    return base.with_suffix(".pdf"), base.with_suffix(".json")


def stamp(path):
    """(modified time, size) of the file, to tell later whether it changed; None when it isn't there."""
    try:
        st = os.stat(path)
        return [st.st_mtime, st.st_size]
    except OSError:
        return None


def write(path, data, original):
    """Keep `data` (the PDF with its edits, bytes) as the recovery copy of `path`. original: stamp() of the file as
    it was when the edits began."""
    pdf, info = _files(path)
    pdf.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".~", suffix=".pdf", dir=str(pdf.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, pdf)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    info.write_text(json.dumps({"path": str(path), "name": Path(path).name, "saved": time.time(), "original": original}),
                    encoding="utf-8")


def find(path):
    """The recovery copy of `path`: {"name", "saved" (local time, as text), "changed": the file changed since}, or
    None."""
    pdf, info = _files(path)
    if not (pdf.is_file() and info.is_file()):
        return None
    try:
        meta = json.loads(info.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if os.path.normcase(os.path.abspath(meta.get("path", ""))) != os.path.normcase(os.path.abspath(str(path))):
        return None
    when = datetime.datetime.fromtimestamp(meta.get("saved", pdf.stat().st_mtime))
    today = when.date() == datetime.date.today()
    said = when.strftime("%I:%M %p").lstrip("0") if today else when.strftime("%b %d at %I:%M %p").replace(" 0", " ")
    now = stamp(path)
    orig = meta.get("original")
    changed = bool(orig and now and (abs(now[0] - orig[0]) > 1 or now[1] != orig[1]))
    return {"name": meta.get("name") or Path(path).name, "saved": said, "changed": changed}


def read(path):
    pdf, _info = _files(path)
    return pdf.read_bytes()


def clear(path):
    for f in _files(path):
        try:
            f.unlink()
        except OSError:
            pass


def tidy():
    """Let go of copies older than KEEP_DAYS (a file opened from a zip or a temporary folder is never reopened)."""
    try:
        old = time.time() - KEEP_DAYS * 86400
        for f in folder().iterdir():
            if f.stat().st_mtime < old:
                f.unlink()
    except OSError:
        pass
