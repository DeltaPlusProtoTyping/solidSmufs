"""The local web server the viewer's window talks to.

Serves the page (web/) and a small JSON / binary API on 127.0.0.1. Every API call must carry the
session token (header X-Token), so other pages in a browser can't drive it.
"""

import functools
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import tempfile
import threading
import zlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, archive, settings
from .documents import Documents, WorkerGone
from .kernel.formats import ALL_FORMATS

WEB = Path(__file__).with_name("web")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


class Native:
    """What only the desktop window can do (file dialogs, Explorer). The Qt app replaces this."""

    available = False

    def open_dialog(self, start_dir=None):
        return None

    def save_image(self, data, suggested):
        return None

    def save_file(self, title, suggested, file_filter):
        """Ask where to save a file; the chosen path, or None."""
        return None

    def reveal(self, path):
        os.startfile(str(Path(path).parent)) if hasattr(os, "startfile") else None

    def set_title(self, title):
        pass


class App:
    def __init__(self, native=None):
        self.token = secrets.token_urlsafe(18)
        self.docs = Documents()
        self.native = native or Native()
        self.upload_dir = Path(tempfile.mkdtemp(prefix="solidsmufs-up-"))
        self.httpd = None
        self.browse_first = None  # a zip given at launch that holds several files: the page shows them

    def start(self, port=0):
        app = self

        class Handler(_Handler):
            ctx = app

        # the same port every launch keeps the page's address the same, so the browser's caches of the
        # scripts (and saved dialog positions) carry over; any free port if that one is taken
        tries = [port] if port else [_preferred_port(), 0]
        for i, p in enumerate(tries):
            try:
                self.httpd = _Server(("127.0.0.1", p), Handler)
                break
            except OSError:
                if i == len(tries) - 1:
                    raise
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="solidsmufs-http").start()
        self.docs.warm(3.0)  # a spare worker for the next file, once the window is up
        return self.httpd.server_address[1]

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v{self.web_stamp:x}/?t={self.token}"

    @functools.cached_property
    def web_stamp(self):
        """Newest change to the page's files. The page is served under /v<stamp>/, so the browser can
        keep its files without asking again, and any edit gives them new addresses."""
        return max((f.stat().st_mtime_ns for f in WEB.rglob("*") if f.is_file()), default=0)

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
        self.docs.close_all()
        shutil.rmtree(self.upload_dir, ignore_errors=True)

    def open(self, path, quality=None):
        """Open a file (or one inside a zip). A zip holding several files raises archive.ChooseInArchive."""
        path = str(Path(path))
        if Path(path).suffix.lower() not in ALL_FORMATS:
            raise ValueError(f"SolidSmufs can't open {Path(path).suffix or 'this kind of'} files.")
        real, shown = archive.resolve(path)
        if not Path(real).is_file():
            raise FileNotFoundError(f"Can't find {path}")
        q = quality or settings.load()["ui"].get("quality", "normal")
        doc = self.docs.open(real, q, shown)
        if not str(path).startswith(str(self.upload_dir)):
            settings.add_recent(path)
        return doc


def _preferred_port():
    import getpass
    return 41000 + zlib.crc32(getpass.getuser().lower().encode()) % 2000


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # on Windows that would let a second server share the port

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _Handler(BaseHTTPRequestHandler):
    ctx: App = None
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True  # headers and body go out as separate writes: don't hold the second one

    def log_message(self, fmt, *args):  # quiet
        pass

    # ------------------------------------------------------------------ plumbing
    def _send(self, status, body=b"", ctype="application/json", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if "Cache-Control" not in (extra or {}):
            self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(status, json.dumps(obj, separators=(",", ":")).encode())

    def _error(self, msg, status=400):
        self._json({"error": msg}, status)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _jbody(self):
        raw = self._body()
        return json.loads(raw) if raw else {}

    def _authorised(self):
        return secrets.compare_digest(self.headers.get("X-Token", ""), self.ctx.token)

    # ------------------------------------------------------------------ routing
    def do_GET(self):
        url = urlparse(self.path)
        if url.path.startswith("/api/"):
            return self._api("GET", url)
        return self._static(url.path)

    do_HEAD = do_GET

    def do_POST(self):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return self._error("Not found", 404)
        return self._api("POST", url)

    def _static(self, path):
        version = re.match(r"/v([0-9a-f]+)(/.*)", path)
        if version:
            path = version.group(2)
        rel = unquote(path).lstrip("/") or "index.html"
        target = (WEB / rel).resolve()
        if WEB.resolve() not in target.parents and target != WEB.resolve() or not target.is_file():
            return self._send(404, b"Not found", "text/plain")
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        # under this launch's version folder: kept by the browser for good; otherwise (an older
        # version, or a file edited since the app started) cached but checked every time
        st = target.stat()
        etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
        current = version and version.group(1) == f"{self.ctx.web_stamp:x}" and st.st_mtime_ns <= self.ctx.web_stamp
        headers = {"Cache-Control": "max-age=31536000, immutable" if current else "no-cache", "ETag": etag}
        if rel == "index.html":  # its address carries this launch's token: never worth keeping
            headers = {"Cache-Control": "no-store"}
        if self.headers.get("If-None-Match") == etag:
            return self._send(304, b"", ctype, headers)
        self._send(200, target.read_bytes(), ctype, headers)

    def _api(self, method, url):
        if not self._authorised():
            return self._error("Forbidden", 403)
        parts = [p for p in url.path.split("/")[2:] if p]
        try:
            if parts == ["hello"]:
                s = settings.load()
                browse, self.ctx.browse_first = self.ctx.browse_first, None
                return self._json({"app": "SolidSmufs", "version": __version__, "native": self.ctx.native.available,
                                   "recent": s["recent"], "ui": s["ui"], "formats": sorted(ALL_FORMATS),
                                   "docs": [d.status() for d in self.ctx.docs.all()], "browse": browse})
            if parts == ["open"] and method == "POST":
                b = self._jbody()
                try:
                    doc = self.ctx.open(b["path"], b.get("quality"))
                except archive.ChooseInArchive as e:  # the page shows what's in the zip, to pick from
                    return self._json({"browse": e.path})
                return self._json(doc.status())
            if parts == ["upload"] and method == "POST":
                q = parse_qs(url.query)
                name = Path(q.get("name", ["upload.step"])[0]).name
                name = re.sub(r"[^\w.\- ()]", "_", name) or "upload.step"
                folder = Path(tempfile.mkdtemp(dir=self.ctx.upload_dir))
                (folder / name).write_bytes(self._body())
                try:
                    doc = self.ctx.open(folder / name)
                except archive.ChooseInArchive as e:
                    return self._json({"browse": e.path})
                return self._json(doc.status())
            if parts == ["settings"]:
                if method == "POST":
                    return self._json({"ui": settings.set_ui(self._jbody())})
                return self._json(settings.load())
            if parts == ["recent", "remove"] and method == "POST":
                path = self._jbody().get("path")
                s = settings.load()
                s["recent"] = [r for r in s["recent"] if r["path"] != path]
                settings.save(s)
                return self._json({"recent": s["recent"]})
            if parts == ["dialog", "open"] and method == "POST":
                return self._json({"path": self.ctx.native.open_dialog(self._jbody().get("dir"))})
            if parts == ["dialog", "save-image"] and method == "POST":
                b = self._jbody()
                return self._json({"path": self.ctx.native.save_image(b["data"], b.get("name", "view.png"))})
            if parts == ["reveal"] and method == "POST":
                self.ctx.native.reveal(self._jbody()["path"])
                return self._json({"ok": True})
            if parts == ["dev", "snapshot"] and method == "POST":  # for checking the view during development
                import base64
                data = self._jbody()["data"]
                out = Path(tempfile.gettempdir()) / "solidsmufs-snapshot.png"
                out.write_bytes(base64.b64decode(data.split(",", 1)[1]))
                return self._json({"path": str(out)})
            if parts == ["title"] and method == "POST":
                self.ctx.native.set_title(self._jbody().get("title", "SolidSmurfs"))
                return self._json({"ok": True})
            if parts == ["dwg-setup"] and method == "POST":  # the user asked: fetch the DWG converter (no admin)
                from . import oda
                self._jbody()  # read, so it doesn't stay in the connection ahead of the next request
                return self._json({"path": str(oda.setup())})
            if parts == ["fs", "roots"]:
                return self._json(_fs_roots())
            if parts == ["fs", "list"] and method == "POST":
                return self._json(_fs_list(self._jbody().get("path") or str(Path.home())))
            if len(parts) >= 2 and parts[0] == "docs":
                return self._doc_api(method, parts[1], parts[2:])
        except (FileNotFoundError, ValueError, KeyError) as e:
            return self._error(str(e))
        except WorkerGone:
            return self._error("The geometry engine for this document stopped. Reopen the file.", 410)
        except Exception as e:  # anything unexpected still answers, so the page never hangs
            return self._error(f"{type(e).__name__}: {e}", 500)
        return self._error("Not found", 404)

    def _doc_api(self, method, doc_id, rest):
        doc = self.ctx.docs.get(doc_id)
        if doc is None:
            return self._error("No such document", 404)
        if not rest:
            return self._json(doc.status())
        what = rest[0]
        if what == "meta":
            if doc.state != "ready":
                return self._error("Not ready", 409)
            return self._json(doc.meta)
        if what == "mesh":
            if doc.state != "ready":
                return self._error("Not ready", 409)
            return self._send(200, doc.blob, "application/octet-stream")
        if method != "POST":
            return self._error("Not found", 404)
        b = self._jbody()
        if what == "close":
            self.ctx.docs.close(doc_id)
            return self._json({"ok": True})
        if what == "unlock":  # never logged or stored: it lives in the document's memory
            doc.unlock(str(b.get("password", "")))
            return self._json(doc.status())
        if what == "reload":
            doc.reload(b.get("quality", doc.quality), b["config"] if "config" in b else "keep",
                       b["orient"] if "orient" in b else "keep")
            settings.set_ui({"quality": doc.quality})
            return self._json(doc.status())
        if what == "pdf-tile":  # raw RGBA pixels of a piece of a page
            return self._send(200, doc.request("pdf_tile", timeout=120, page=int(b["page"]), scale=float(b["scale"]),
                                               x=int(b["x"]), y=int(b["y"]), w=int(b["w"]), h=int(b["h"]),
                                               turns=int(b.get("turns", 0))), "application/octet-stream")
        if what == "pdf-select":
            return self._json(doc.request("pdf_select", timeout=60, page=int(b["page"]), ax=b["ax"], ay=b["ay"],
                                          bx=b["bx"], by=b["by"]))
        if what == "pdf-find":
            return self._json(doc.request("pdf_find", timeout=120, query=str(b.get("query", ""))))
        if what == "facing":  # which way each Align Part pick faces, for its arrow
            return self._json(doc.request("facing", timeout=60, refs=b.get("refs", [])))
        if what == "align-preview":  # the turn Align would make, without making it
            return self._json(doc.request("align", timeout=60, refs=b.get("refs", []), targets=b.get("targets", [])))
        if what == "align":  # turn the part so the picked faces face the chosen views, then read it again
            r = doc.request("align", timeout=120, refs=b.get("refs", []), targets=b.get("targets", []))
            doc.reload(doc.quality, orient=r["orient"])
            return self._json(doc.status())
        if what == "measure":
            return self._json(doc.request("measure", timeout=120, selection=b.get("selection", []),
                                          options=b.get("options", {})))
        if what == "massprops":
            return self._json(doc.request("massprops", timeout=300, bodies=b.get("bodies"),
                                          density=b.get("density", 1.0)))
        if what == "bbox":
            return self._json(doc.request("bbox", timeout=300, bodies=b.get("bodies"), mode=b.get("mode", "world"),
                                          refs=b.get("refs")))
        if what == "sectionprops":
            return self._json(doc.request("section_props", timeout=120, faces=b.get("faces", [])))
        if what == "holes":
            return self._json(doc.request("holes", timeout=120))
        if what == "save-step":
            out = self.ctx.native.save_file("Save as STEP", Path(doc.path or doc.name).stem + ".step",
                                            "STEP file (*.step *.stp)")
            if not out:
                return self._json({"path": None})
            return self._json(doc.request("save_step", timeout=600, out=out))
        return self._error("Not found", 404)


# ---------------------------------------------------------------------------------------------- file explorer
def _fs_roots():
    home = Path.home()
    places = []
    for name, p in (("Desktop", home / "Desktop"), ("Downloads", home / "Downloads"), ("Documents", home / "Documents"),
                    ("Home", home)):
        if p.is_dir():
            places.append({"name": name, "path": str(p)})
    for od in sorted(home.glob("OneDrive*")):
        if od.is_dir():
            places.append({"name": od.name, "path": str(od)})
    drives = []
    if os.name == "nt":
        import string
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                drives.append({"name": root, "path": root})
    else:
        drives.append({"name": "/", "path": "/"})
    seen, recent_dirs = set(), []
    for r in settings.load()["recent"]:
        d = str(Path(r["path"]).parent)
        if d.lower() not in seen and Path(d).is_dir():
            seen.add(d.lower())
            recent_dirs.append({"name": Path(d).name or d, "path": d})
    return {"places": places, "drives": drives, "recentDirs": recent_dirs[:8]}


def _fs_list(path):
    inside = archive.split(str(Path(path).expanduser()))
    if inside is not None:  # a zip, or a folder in one: browsed like a folder
        return archive.listing(*inside)
    p = Path(path).expanduser()
    if not p.is_dir():
        raise ValueError(f"Not a folder: {path}")
    dirs, files = [], []
    try:
        entries = list(os.scandir(p))
    except PermissionError:
        raise ValueError(f"No permission to open {p}") from None
    for e in entries[:5000]:
        name = e.name
        if name.startswith(("$", ".")) or name in ("desktop.ini", "Thumbs.db"):
            continue
        try:
            if e.is_dir():
                dirs.append({"name": name, "path": e.path})
            elif archive.is_archive(name):
                dirs.append({"name": name, "path": e.path, "zip": True})
            elif Path(name).suffix.lower() in ALL_FORMATS:
                files.append({"name": name, "path": e.path, "size": e.stat().st_size})
        except OSError:
            continue
    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda f: f["name"].lower())
    parent = str(p.parent) if p.parent != p else None
    return {"path": str(p.resolve()), "parent": parent, "dirs": dirs[:2000], "files": files[:2000]}
