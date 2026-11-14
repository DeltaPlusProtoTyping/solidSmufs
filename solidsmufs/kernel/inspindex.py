"""What every ballooned print saved on this computer says, to search across jobs: its characteristics (balloon
number, requirement, description, gage, tags) and its production issues (title, notes, how they were resolved), with the
job's details. Kept in %APPDATA%\\SolidSmufs\\inspections.json, one entry a sheet (by its sheet id), written when the print
is saved. Nothing here leaves the computer.

record(path, data): put a saved print's list in (or take it out, when it has nothing left).
search(query, data=None, path=None): every characteristic, issue or job matching all the query's words (any case);
data and path: the open print's list as it is now, searched in place of what was saved of it.
"""

import json
import os
import re
from pathlib import Path

from .. import settings
from . import balloons

MOST = 300  # hits back from one search


def _file():
    return Path(settings.folder()) / "inspections.json"


def _load():
    try:
        out = json.loads(_file().read_text(encoding="utf-8"))
        return out if isinstance(out, dict) else {}
    except (OSError, ValueError):
        return {}


def _entry(path, data):
    info = data.get("info") or {}
    labels = {c["id"]: balloons.label(c) for c in data.get("chars") or []}
    return {"path": str(path), "sid": data.get("sid"), "status": data.get("status") or "draft",
            "info": {k: info.get(k, "") for k in ("part", "name", "rev", "customer", "job", "lot")},
            "chars": [{"label": balloons.label(c), "text": c.get("text") or "", "desc": c.get("desc") or "", "gage": c.get("gage") or "",
                       "tags": c.get("tags") or [], "note": c.get("note") or ""} for c in data.get("chars") or []],
            "issues": [{"n": i["n"], "label": labels.get(i.get("char"), i.get("label") or ""), "title": i.get("title") or "", "notes": i.get("notes") or "",
                        "status": i.get("status"), "route": i.get("route"), "tags": i.get("tags") or [], "job": i.get("job") or ""}
                       for i in data.get("issues") or [] if not i.get("hidden")]}


def record(path, data):
    """Keep what a saved print's list says (never stopping a save: it's only for searching). Only in the app (which
    sets SOLIDSMUFS_APP), so tests and scripts leave the computer's index alone."""
    if not os.environ.get("SOLIDSMUFS_APP"):
        return
    try:
        key = data.get("sid") or str(Path(path).resolve()).lower()
        all_ = _load()
        for k in [k for k, e in all_.items() if k != key and str(Path(e.get("path", "")).resolve()).lower() == str(Path(path).resolve()).lower()]:
            del all_[k]  # (the same file under another sheet: it's this one now)
        if data.get("chars") or data.get("issues"):
            all_[key] = {**_entry(path, data), "saved": os.path.getmtime(path) if os.path.exists(path) else None}
        else:
            all_.pop(key, None)
        f = _file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(all_, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, f)
    except Exception:
        pass


def search(query, data=None, path=None):
    """[{"path", "sid", "status", "part", "rev", "job", "kind": "char" / "issue", "label", "text", "here"}] for every
    characteristic and issue all the query's words are found in (with its sheet's details), this print's first."""
    words = [w for w in re.split(r"\s+", str(query or "").lower()) if w]
    if not words:
        return []
    sheets = dict(_load())
    here = None
    if data is not None:
        here = data.get("sid") or str(Path(path or "").resolve()).lower()
        sheets[here] = _entry(path or "", data)
    hits = []
    for key, e in sorted(sheets.items(), key=lambda kv: (kv[0] != here, kv[1].get("info", {}).get("part", ""))):
        info = e.get("info") or {}
        head = " ".join(str(v) for v in info.values()).lower()
        base = {"path": e.get("path"), "sid": e.get("sid"), "status": e.get("status"), "part": info.get("part", ""), "rev": info.get("rev", ""),
                "job": info.get("job", ""), "here": key == here, "missing": key != here and not os.path.exists(e.get("path") or "")}
        for c in e.get("chars") or []:
            hay = " ".join([c["label"], c["text"], c["desc"], c["gage"], c["note"], " ".join(c["tags"]), head]).lower()
            if all(w in hay for w in words):
                hits.append({**base, "kind": "char", "label": c["label"], "text": c["text"], "more": " · ".join(x for x in (c["desc"], c["gage"]) if x)})
        for i in e.get("issues") or []:
            hay = " ".join([f"#{i['n']}", i["label"], i["title"], i["notes"], " ".join(i["tags"]), i["job"], head]).lower()
            if all(w in hay for w in words):
                said = {"resolved": "resolved", "fixed": "fixed, ready for lead"}.get(i.get("status"), "open")
                hits.append({**base, "kind": "issue", "label": f"#{i['n']}" + (f" on {i['label']}" if i["label"] else ""), "text": i["title"],
                             "more": f"{said}{': machinist fix' if i.get('route') == 'machinist' else ': moved to troubleshooting' if i.get('route') == 'troubleshooting' else ''}"
                                     + (f" · {i['notes'][:120]}" if i["notes"] else "")})
        if len(hits) >= MOST:
            break
    return hits[:MOST]
