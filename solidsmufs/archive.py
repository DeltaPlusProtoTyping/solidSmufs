"""Zip archives: their files can be browsed like a folder, and opened. A file opened from a zip is opened from a
copy of the whole archive, unpacked once into the cache, so an assembly finds its parts beside it.

Paths inside a zip are written as the zip's path and then the file's place in it: C:\\jobs\\quote.zip\\parts\\a.step
"""

import hashlib
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from .kernel.formats import ALL_FORMATS, ARCHIVE_FORMATS

MAX_UNPACKED = 4 << 30  # bytes: an archive bigger than this unpacked isn't (a zip bomb, or not a job's files)


class ChooseInArchive(ValueError):
    """A zip holds more than one file to open: the user picks one."""

    def __init__(self, path):
        super().__init__("Pick a file in the zip to open.")
        self.path = path


def is_archive(path):
    return Path(path).suffix.lower() in ARCHIVE_FORMATS


def split(path):
    """(zip path, place inside it as 'a/b.step') when `path` points inside a zip; else None."""
    p = Path(path)
    for parent in [p, *p.parents]:
        if parent.suffix.lower() in ARCHIVE_FORMATS and parent.is_file():
            inner = p.relative_to(parent).as_posix()
            return str(parent), "" if inner == "." else inner
    return None


def _openable(name):
    ext = PurePosixPath(name).suffix.lower()
    return ext in ALL_FORMATS and ext not in ARCHIVE_FORMATS


def _safe(name):
    """A name that stays inside the zip's folder when unpacked (not ../x, /x or C:x), and isn't Mac clutter."""
    parts = name.replace("\\", "/").split("/")
    return not (name.startswith(("/", "\\", "__MACOSX/")) or ":" in name or ".." in parts)


def _names(zip_path):
    try:
        with zipfile.ZipFile(zip_path) as z:
            return [i.filename for i in z.infolist() if not i.is_dir() and _safe(i.filename)]
    except (zipfile.BadZipFile, OSError) as e:
        raise ValueError(f"This zip can't be read: {e}") from None


def openable(zip_path):
    """The files in a zip that can be opened, as 'a/b.step'."""
    return [n for n in _names(zip_path) if _openable(n)]


def listing(zip_path, inner=""):
    """The folders and openable files at one place in a zip, as the file explorer lists a folder."""
    inner = inner.strip("/")
    prefix = inner + "/" if inner else ""
    dirs, files = {}, []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if not name.startswith(prefix) or not _safe(name) or name == prefix:
                continue
            rest = name[len(prefix):]
            if "/" in rest.rstrip("/"):
                top = rest.split("/", 1)[0]
                dirs.setdefault(top, os.path.join(zip_path, *(prefix + top).split("/")))
            elif rest.endswith("/"):
                top = rest.rstrip("/")
                dirs.setdefault(top, os.path.join(zip_path, *(prefix + top).split("/")))
            elif _openable(rest):
                files.append({"name": rest, "path": os.path.join(zip_path, *name.split("/")), "size": info.file_size})
    here = os.path.join(zip_path, *inner.split("/")) if inner else zip_path
    parent = str(Path(here).parent)
    return {"path": here, "parent": parent,
            "dirs": [{"name": k, "path": v} for k, v in sorted(dirs.items(), key=lambda kv: kv[0].lower())],
            "files": sorted(files, key=lambda f: f["name"].lower())}


def _cache_root():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "SolidSmufs" / "unzipped"


def unpacked(zip_path, inner):
    """The path of `inner` in an unpacked copy of the zip (unpacked now if it isn't already)."""
    st = Path(zip_path).stat()
    key = hashlib.sha1(f"{Path(zip_path).resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]
    root = _cache_root() / f"{Path(zip_path).stem[:40]}-{key}"
    done = root / ".complete"
    if not done.is_file():
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            infos = [i for i in z.infolist() if not i.is_dir() and _safe(i.filename)]
            if sum(i.file_size for i in infos) > MAX_UNPACKED:
                raise ValueError("This zip is too big to open (over 4 GB unpacked).")
            for info in infos:
                target = (root / info.filename).resolve()
                if root.resolve() not in target.parents:  # a name like ../../x mustn't land outside the folder
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
        done.write_text("")
        _prune(keep=root)
    out = (root / inner).resolve()
    if not out.is_file():
        raise FileNotFoundError(f"There's no {inner} in {Path(zip_path).name}.")
    return out


def _prune(keep, max_folders=20):
    """Keep the cache of unpacked zips to the most recent few."""
    try:
        folders = sorted((p for p in _cache_root().iterdir() if p.is_dir() and p != keep), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in folders[max_folders - 1:]:
        shutil.rmtree(old, ignore_errors=True)


def resolve(path):
    """What to open for `path`: (file path, name to show), or ChooseInArchive when the user must pick in a zip."""
    inside = split(path)
    if inside is None:
        return path, None
    zip_path, inner = inside
    if not inner:  # the zip itself
        names = openable(zip_path)
        if not names:
            raise ValueError(f"There's nothing in {Path(zip_path).name} that SolidSmurfs can open.")
        if len(names) > 1:
            raise ChooseInArchive(zip_path)
        inner = names[0]
    elif not _openable(inner):
        raise ChooseInArchive(os.path.join(zip_path, *inner.split("/")))  # a folder in the zip
    return str(unpacked(zip_path, inner)), PurePosixPath(inner).name
