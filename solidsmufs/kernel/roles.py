"""Who may do what in Ballooning mode, on this PC: operators, leads and an admin, told apart by a lead password (and,
if one is set, an admin password). Entering one unlocks its actions for four hours, and every lead action starts the
four hours again. With no password set there are no roles: everyone may do everything.

A lead's actions: releasing a list, putting it back to draft, marking it superseded, resolving or reopening a production
issue, and deleting one for good. Anyone does the rest (marking an issue fixed, hiding it, asking for it to be
deleted). An admin may do what a lead does, and change either password.

The passwords are kept hashed (PBKDF2) in %APPDATA%\\SolidSmufs\\roles.json, the unlocking beside them in unlock.json.
It keeps honest people from the wrong button, not a determined one from the files.
Only in the app (SOLIDSMUFS_APP is set when it starts): tests and scripts see no roles.
"""

import datetime
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from .. import settings

HOURS = 4
ROLES = ("lead", "admin")
LEAD_OPS = {"status"}  # (and some of what's done to an issue: see need_for)
LEAD_ISSUE_ACTS = {"resolve", "reopen", "purge"}


def _on():
    return bool(os.environ.get("SOLIDSMUFS_APP"))


def _path(name):
    return Path(settings.folder()) / name


def _read(name):
    try:
        out = json.loads(_path(name).read_text(encoding="utf-8"))
        return out if isinstance(out, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(name, data):
    p = _path(name)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, p)


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()


def _matches(role, password):
    entry = _read("roles.json").get(role)
    return bool(entry and password and hmac.compare_digest(_hash(password, entry["salt"]), entry["hash"]))


def _now():
    return datetime.datetime.now().astimezone()


def level():
    """What's unlocked now: "admin", "lead" or None."""
    u = _read("unlock.json")
    try:
        if u.get("level") in ROLES and datetime.datetime.fromisoformat(u["until"]) > _now():
            return u["level"]
    except (KeyError, ValueError, TypeError):
        pass
    return None


def status():
    """{"on": roles in use, "lead"/"admin": that password is set, "level": what's unlocked, "until": till when}."""
    if not _on():
        return {"on": False, "lead": False, "admin": False, "level": None, "until": None}
    have = _read("roles.json")
    lv = level()
    return {"on": bool(have), "lead": "lead" in have, "admin": "admin" in have, "level": lv,
            "until": _read("unlock.json").get("until") if lv else None}


def unlock(password):
    """Unlock with the admin password or the lead password, for HOURS. Returns the level."""
    for role in ("admin", "lead"):
        if _matches(role, password):
            _write("unlock.json", {"level": role, "until": (_now() + datetime.timedelta(hours=HOURS)).isoformat(timespec="seconds")})
            return role
    raise ValueError("That isn't the lead or admin password.")


def lock():
    try:
        _path("unlock.json").unlink()
    except OSError:
        pass


def set_password(role, new, current=None):
    """Set (or with new empty, take away) the lead or admin password. One that's set is changed only with itself, or
    by an admin unlocked; the lead password is set first only with no admin password, or by an admin."""
    if role not in ROLES:
        raise ValueError(f"There's no {role} password.")
    have = _read("roles.json")
    admin_in = level() == "admin"
    if role in have:
        if not (admin_in or _matches(role, current or "")):
            raise ValueError(f"Changing the {role} password takes the {role} password now (or an admin's unlocking).")
    elif role == "lead" and "admin" in have and not admin_in:
        raise ValueError("With an admin password set, an admin sets the lead password: unlock as admin first.")
    new = str(new or "")
    if new and len(new) < 4:
        raise ValueError("A password needs at least 4 characters.")
    if new:
        salt = secrets.token_hex(16)
        have[role] = {"salt": salt, "hash": _hash(new, salt)}
    else:
        have.pop(role, None)
    _write("roles.json", have)
    if not have:
        lock()
    return status()


def need_for(op, args):
    """Refuse a lead's action while no lead (or admin) is unlocked; each one done starts the four hours again."""
    if not _on():
        return
    what = op[len("balloon_"):] if op.startswith("balloon_") else None
    if not (what in LEAD_OPS or (what == "issue_act" and args.get("act") in LEAD_ISSUE_ACTS)):
        return
    if not _read("roles.json"):
        return  # (no passwords: no roles)
    lv = level()
    if lv is None:
        raise ValueError("That's a lead's to do: unlock with the lead password first (the lock beside the status).")
    _write("unlock.json", {"level": lv, "until": (_now() + datetime.timedelta(hours=HOURS)).isoformat(timespec="seconds")})
