"""Open documents, each backed by its own worker process (see kernel/worker.py).

A worker that crashes (OpenCASCADE can, on a broken file) only fails its own document; the next
request for it says so instead of hanging.
"""

import itertools
import logging
import multiprocessing as mp
import threading
import time
from pathlib import Path

from . import recovery

from . import settings
from .kernel.formats import PASSWORD_NEEDED, PASSWORD_WRONG

log = logging.getLogger("solidsmufs")
_ctx = mp.get_context("spawn")


def worker_main(conn):
    """Worker process entry. The geometry code (numpy, gmsh) is imported here, in the worker only,
    so the window process starts without it."""
    from .kernel.worker import main
    main(conn)


def _spawn_worker():
    conn, child = _ctx.Pipe()
    proc = _ctx.Process(target=worker_main, args=(child,), daemon=True, name="solidsmufs-worker")
    proc.start()
    child.close()
    return proc, conn
_ids = itertools.count(1)
PREVIEW_EXTS = (".sldprt", ".sldasm", ".slddrw")  # files SolidWorks saves a picture in


class WorkerGone(RuntimeError):
    pass


class Document:
    def __init__(self, path, quality="normal", display_name=None, worker=None):
        self.id = f"d{next(_ids)}"
        self.path = str(path)
        self.name = display_name or Path(path).name
        self.quality = quality
        self.config = None  # SolidWorks part configuration to show; None: the file's first
        self.orient = settings.get_orient(path)  # 3x3 rotation from Align Part (remembered per file); None: as modelled
        self.state, self.stage, self.fraction, self.error = "loading", "Starting the geometry engine", 0.0, None
        self.meta, self.blob = None, None
        self.exact = False  # exact geometry loaded (a cached tessellation can show before it is)
        self.rev = 0  # bumps whenever meta / blob are replaced
        self.password = None  # what the user gave to open a protected PDF
        self.locked = None  # why a PDF is waiting for a password: PASSWORD_NEEDED or PASSWORD_WRONG
        self.opened = time.time()
        self._rids = itertools.count(1)
        self._pending = {}
        self._send_lock = threading.Lock()
        self._busy = threading.Lock()
        self.preview = None  # the picture SolidWorks saved with the file: PNG bytes, shown while it opens
        # autosave (recovery.py): a copy found when the PDF opened, offered back until it's answered; the timer that
        # writes ours a little after an edit; and whether one of ours is kept
        self.recovery, self._checked, self._autosave, self._kept = None, False, None, False
        self.pdf_dirty = False
        self.proc, self._conn = worker or _spawn_worker()
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._load, args=("load",), daemon=True).start()
        if Path(path).suffix.lower() in PREVIEW_EXTS:
            threading.Thread(target=self._find_preview, daemon=True).start()

    def _find_preview(self):
        from .formats.parasolid.containers import preview_png
        self.preview = preview_png(self.path)

    # ------------------------------------------------------------------ status
    def status(self):
        return {"id": self.id, "name": self.name, "path": self.path, "state": self.state, "stage": self.stage,
                "fraction": round(self.fraction, 3), "error": self.error, "quality": self.quality,
                "elapsed": round(time.time() - self.opened, 1), "exact": self.exact, "rev": self.rev, "locked": self.locked,
                "preview": self.preview is not None, "recovery": self.recovery}

    # ------------------------------------------------------------------ autosave (recovery.py)
    def edited(self, state):
        """After an edit to the PDF ({"dirty", ...}): its recovery copy written a little later (or let go)."""
        if self.recovery is not None:  # (an earlier copy is waiting for an answer: it isn't written over)
            return
        if (state.get("dirty") or self._kept) and self._autosave is None:
            t = threading.Timer(recovery.AFTER_S, self._autosave_now)
            t.daemon = True
            self._autosave = t
            t.start()

    def _autosave_now(self):
        self._autosave = None
        try:
            self._kept = bool(self.request("pdf_edit", timeout=300, op="recover_write", args={}).get("kept"))
        except Exception as e:
            log.warning("autosave of %s failed: %s", self.name, e)

    def answered_recovery(self):
        self.recovery = None

    def _publish(self, meta, blob):
        meta["id"] = self.id
        meta["name"] = self.name
        if meta.get("pdf") is not None and not self._checked:  # edits that weren't saved last time?
            self._checked = True
            self.recovery = recovery.find(self.path)
        self.meta, self.blob = meta, blob
        self.rev += 1
        self.state, self.stage, self.fraction = "ready", "Ready", 1.0

    def _load(self, cmd):
        try:
            if cmd == "load":  # first open: show a cached tessellation at once, then load the exact geometry
                r = self.request("open", path=self.path, quality=self.quality, config=self.config, orient=self.orient,
                                 password=self.password)
                log.info("[timing] %s tessellation ready (cached=%s)", self.name, not r["exact"])
                self._publish(r["meta"], r["blob"])
                self.exact = r["exact"]
                if not self.exact:
                    try:
                        r = self.request("ensure_exact", path=self.path, quality=self.quality)
                        if r.get("changed"):
                            self._publish(r["meta"], r["blob"])
                    except Exception:  # the model is already on screen; measuring will try again
                        pass
                    self.exact = True
                    log.info("[timing] %s exact geometry ready", self.name)
            else:
                meta, blob = self.request(cmd, path=self.path, quality=self.quality, config=self.config, orient=self.orient)
                self._publish(meta, blob)
                self.exact = True
        except WorkerGone:
            self.state, self.error = "error", ("The geometry engine stopped while reading this file. "
                                               "It may be damaged, or use something OpenCASCADE can't handle.")
        except Exception as e:
            if str(e) in (PASSWORD_NEEDED, PASSWORD_WRONG):
                self.state, self.locked, self.stage = "password", str(e), "Waiting for the password"
            else:
                self.state, self.error = "error", str(e)

    def unlock(self, password):
        """Try again with the password the user gave."""
        self.password = password
        self.locked, self.error = None, None
        self.state, self.stage, self.fraction = "loading", "Opening the PDF", 0.0
        self.opened = time.time()
        threading.Thread(target=self._load, args=("load",), daemon=True).start()

    def reload(self, quality, config="keep", orient="keep"):
        """Read the file again (at another tessellation quality, showing another configuration, or turned
        to another orientation)."""
        self.quality = quality
        if config != "keep":
            self.config = config
        if orient != "keep":
            self.orient = orient
            settings.set_orient(self.path, orient)
        self.exact = False
        self.state, self.stage, self.fraction, self.error = "loading", "Reloading", 0.0, None
        self.opened = time.time()
        threading.Thread(target=self._load, args=("reload",), daemon=True).start()

    # ------------------------------------------------------------------ requests
    def request(self, cmd, timeout=None, **kw):
        """Send one command to the worker and wait for its answer (one at a time per document)."""
        with self._busy:
            if not self.proc.is_alive():
                raise WorkerGone()
            rid = next(self._rids)
            slot = {"event": threading.Event()}
            self._pending[rid] = slot
            with self._send_lock:
                self._conn.send((rid, cmd, kw))
            if not slot["event"].wait(timeout):
                self._pending.pop(rid, None)
                raise TimeoutError(f"{cmd} took too long")
            kind, payload = slot["result"]
            if kind == "gone":
                raise WorkerGone()
            if kind == "error":
                raise ValueError(payload.get("message") or "Failed")
            return payload

    def _reader(self):
        while True:
            try:
                rid, kind, payload = self._conn.recv()
            except (EOFError, OSError):
                for slot in list(self._pending.values()):
                    slot["result"] = ("gone", None)
                    slot["event"].set()
                self._pending.clear()
                if self.state == "loading":
                    self.state, self.error = "error", "The geometry engine stopped while reading this file."
                return
            if kind == "progress":
                self.stage, self.fraction = payload["stage"], payload["fraction"]
                continue
            slot = self._pending.pop(rid, None)
            if slot is not None:
                slot["result"] = (kind, payload)
                slot["event"].set()

    def close(self):
        if self._autosave is not None:
            self._autosave.cancel()
        # closed on purpose (saved, or Don't Save): its copy let go; kept if its engine stopped (that's what it's for)
        if (self.pdf_dirty or self._kept) and self.recovery is None and self.proc.is_alive():
            recovery.clear(self.path)
        try:
            with self._send_lock:
                self._conn.send((0, "quit", {}))
        except Exception:
            pass
        self.proc.join(1.0)
        if self.proc.is_alive():
            self.proc.terminate()
        self.meta = self.blob = None


class Documents:
    def __init__(self):
        self._docs = {}
        self._lock = threading.Lock()
        # one worker started ahead of time, so opening a file doesn't wait for Python, numpy and gmsh
        self._spare = None
        self._spare_lock = threading.Lock()
        self._closed = False
        threading.Thread(target=recovery.tidy, daemon=True).start()  # (autosaved copies a month old let go)

    def open(self, path, quality="normal", display_name=None):
        doc = Document(path, quality, display_name, self._take_spare())
        with self._lock:
            self._docs[doc.id] = doc
        return doc

    def warm(self, delay=0.0):
        """Start the spare worker after `delay` seconds (out of the way of the window starting)."""
        t = threading.Timer(delay, self._refill)
        t.daemon = True
        t.start()

    def _take_spare(self):
        with self._spare_lock:
            spare, self._spare = self._spare, None
        self.warm(1.0)
        if spare is not None and spare[0].is_alive():
            return spare
        return None

    def _refill(self):
        with self._spare_lock:
            if self._spare is None and not self._closed:
                self._spare = _spawn_worker()

    def get(self, doc_id):
        with self._lock:
            return self._docs.get(doc_id)

    def all(self):
        with self._lock:
            return list(self._docs.values())

    def close(self, doc_id):
        with self._lock:
            doc = self._docs.pop(doc_id, None)
        if doc:
            threading.Thread(target=doc.close, daemon=True).start()

    def close_all(self):
        with self._spare_lock:
            self._closed = True
            spare, self._spare = self._spare, None
        if spare is not None:
            spare[0].terminate()
        for d in self.all():
            d.close()
