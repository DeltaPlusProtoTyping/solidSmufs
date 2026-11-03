"""Remembered between runs: recent files, preferences and each part's Align Part orientation, in %APPDATA%\\SolidSmufs."""

import json
import os
import threading
from pathlib import Path

_lock = threading.Lock()
DEFAULTS = {"recent": [], "ui": {}, "orient": {}}


def folder():
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / "SolidSmufs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _file():
    return folder() / "settings.json"


def load():
    with _lock:
        try:
            data = json.loads(_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in data.items() if k in DEFAULTS})
    out["recent"] = [r for r in out["recent"] if isinstance(r, dict) and r.get("path")]
    return out


def save(data):
    with _lock:
        tmp = _file().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, _file())


def add_recent(path, name=None):
    data = load()
    path = str(path)
    rec = [r for r in data["recent"] if os.path.normcase(r["path"]) != os.path.normcase(path)]
    rec.insert(0, {"path": path, "name": name or Path(path).name})
    data["recent"] = rec[:15]
    save(data)
    return data["recent"]


def _key(path):
    try:
        return os.path.normcase(str(Path(path).resolve()))
    except OSError:
        return os.path.normcase(str(path))


def get_orient(path):
    """The 3x3 rotation Align Part last left this file in, or None (as modelled)."""
    rot = load()["orient"].get(_key(path))
    return rot if isinstance(rot, list) and len(rot) == 3 else None


def set_orient(path, rot):
    """Remember (or with None forget) the file's Align Part orientation; the 500 most recent are kept."""
    data = load()
    turns = {k: v for k, v in data.get("orient", {}).items() if k != _key(path)}
    if rot is not None:
        turns[_key(path)] = [[float(x) for x in row] for row in rot]
    data["orient"] = dict(list(turns.items())[-500:])
    save(data)


def set_ui(ui):
    data = load()
    data["ui"] = {**data.get("ui", {}), **ui}
    save(data)
    return data["ui"]
