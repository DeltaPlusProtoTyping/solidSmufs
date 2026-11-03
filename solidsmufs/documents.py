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


class WorkerGone(RuntimeError):
    pass


class Document:
    def __init__(self, path, quality="normal", display_name=None, worker=None):
        self.id = f"d{next(_ids)}"
        self.path = str(path)
        self.name = display_name or Path(path).name
        self.quality = quality
        self.config = None  # SolidWorks part configuration to show; None: the file's first
        self.orient = None  # 3x3 rotation from Align Part; None: as modelled
        self.state, self.stage, self.fraction, self.error = "loading", "Starting the geometry engine", 0.0, None
        self.meta, self.blob = None, None
        self.exact = False  # exact geometry loaded (a cached tessellation can show before it is)
        self.rev = 0  # bumps whenever meta / blob are replaced
        self.opened = time.time()
        self._rids = itertools.count(1)
        self._pending = {}
        self._send_lock = threading.Lock()
        self._busy = threading.Lock()
        self.proc, self._conn = worker or _spawn_worker()
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._load, args=("load",), daemon=True).start()

    # ------------------------------------------------------------------ status
    def status(self):
        return {"id": self.id, "name": self.name, "path": self.path, "state": self.state, "stage": self.stage,
                "fraction": round(self.fraction, 3), "error": self.error, "quality": self.quality,
                "elapsed": round(time.time() - self.opened, 1), "exact": self.exact, "rev": self.rev}

    def _publish(self, meta, blob):
        meta["id"] = self.id
        meta["name"] = self.name
        self.meta, self.blob = meta, blob
        self.rev += 1
        self.state, self.stage, self.fraction = "ready", "Ready", 1.0

    def _load(self, cmd):
        try:
            if cmd == "load":  # first open: show a cached tessellation at once, then load the exact geometry
                r = self.request("open", path=self.path, quality=self.quality, config=self.config, orient=self.orient)
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
            self.state, self.error = "error", str(e)

    def reload(self, quality, config="keep", orient="keep"):
        """Read the file again (at another tessellation quality, showing another configuration, or turned
        to another orientation)."""
        self.quality = quality
        if config != "keep":
            self.config = config
        if orient != "keep":
            self.orient = orient
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
