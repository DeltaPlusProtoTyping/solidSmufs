"""Remembered between runs: recent files and the viewer's preferences, in %APPDATA%\\SolidSmufs."""

import json
import os
import threading
from pathlib import Path

_lock = threading.Lock()
DEFAULTS = {"recent": [], "ui": {}}


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


def set_ui(ui):
    data = load()
    data["ui"] = {**data.get("ui", {}), **ui}
    save(data)
    return data["ui"]
