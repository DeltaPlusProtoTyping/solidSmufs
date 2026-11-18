"""A big part's slow sums worked out on all cores before it's written (convert.py).

Most of the time converting a big part goes into a few sums: an intersection edge's points refined onto both its
surfaces, and the B-splines fitted to blend (fillet) and offset faces. Each depends only on what it's worked out
from, so helper processes each read the part and go through a share of its faces, keeping those results by
exactly what they came from (BodyWriter.memo). Three rounds, each shared out so no two helpers work the same thing
out: the blends' spines (the ball centre's path, which every edge and face near a blend needs), then the edges (each
on two faces), then the faces (the blend and offset fits). The STEP is then written here, in order, as before,
finding them ready. A result whose inputs don't match exactly isn't used (it's worked out again), so the STEP is the same as
without the helpers.
"""

import logging
import math
import multiprocessing as mp
import os
import time
from concurrent.futures import ProcessPoolExecutor

MIN_FACES = 250  # fewer than this: starting the helpers costs more than they save
_THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")


def helpers():
    """How many helper processes: one a core. (os.cpu_count() counts each core's two threads where it has them,
    and a second helper on a core gains nothing: 6 helpers on a 6-core, 12-thread laptop were quicker than 11.)"""
    try:  # SOLIDSMUFS_HELPERS=n sets it (1: none)
        return max(1, int(os.environ["SOLIDSMUFS_HELPERS"]))
    except (KeyError, ValueError):
        return max(1, min((os.cpu_count() or 2) // 2, 8))


def precompute(src_path, config, chosen, workers=None):
    """{model number: memo} for convert(); {} for a small part, one core, or when the helpers can't run."""
    faces = [[f.idx for f in m.of_type("FACE")] for _name, m in chosen]
    total = sum(len(fs) for fs in faces)
    n = helpers() if workers is None else int(workers)
    timings.clear()
    if n < 2 or total < MIN_FACES:
        return {}
    size = max(8, math.ceil(total / (n * 3)))  # several runs of faces per helper (a few are slow: blends)
    tasks = [(k, fs[i:i + size]) for k, fs in enumerate(faces) for i in range(0, len(fs), size)]
    blends = [[b.idx for b in m.of_type("BLENDED_EDGE") if (m[b["spine"]] is not None and m[b["spine"]].type == "INTERSECTION")]
              for _name, m in chosen]
    edges = [[e.idx for e in m.of_type("EDGE")] for _name, m in chosen]
    memos = {k: {} for k in range(len(chosen))}
    me = mp.current_process()
    daemon = me._config.get("daemon")  # (a document's worker is a daemon, and they may not start processes)
    saved = {v: os.environ.get(v) for v in _THREAD_VARS}
    try:
        me._config["daemon"] = False
        for v in _THREAD_VARS:  # one thread each: the helpers already fill the cores
            os.environ[v] = "1"
        t = time.perf_counter()
        with ProcessPoolExecutor(min(n, len(tasks)), mp_context=mp.get_context("spawn"), initializer=_start,
                                 initargs=(str(src_path), config)) as pool:
            jobs = [(k, bs[i::4 * n]) for k, bs in enumerate(blends) for i in range(4 * n) if bs[i::4 * n]]  # (small: spines vary)
            for k, got in pool.map(_spines, jobs):
                memos[k].update(got)
            t = _lap("spines (and starting the helpers)", t)
            known = {k: dict(v) for k, v in memos.items()}
            jobs = [(k, es[i::2 * n], known[k]) for k, es in enumerate(edges) for i in range(2 * n) if es[i::2 * n]]
            for k, got in pool.map(_edges, jobs):
                memos[k].update(got)
            t = _lap("edges", t)
            known = {k: dict(v) for k, v in memos.items()}
            for k, got in pool.map(_work, [(k, fs, known[k]) for k, fs in tasks]):
                memos[k].update(got)
            t = _lap("faces", t)
    except Exception:  # (anything wrong with the helpers: the part is still converted, on one core)
        logging.getLogger(__name__).warning("helper processes failed; converting on one core", exc_info=True)
        return {}
    finally:
        me._config["daemon"] = daemon
        for v, old in saved.items():
            if old is None:
                os.environ.pop(v, None)
            else:
                os.environ[v] = old
    return memos


timings = {}  # the last run's rounds, in seconds (for timing it)


def _lap(name, t):
    now = time.perf_counter()
    timings[name] = round(now - t, 2)
    return now


_writers = None


def _start(src_path, config):
    global _writers
    from .brep import BodyWriter
    from .convert import load
    from .step import Step
    _src, chosen, _note = load(src_path, config)
    _writers = [BodyWriter(m, Step()) for _name, m in chosen]


def _spines(task):
    """Blend spines worked out: {key: spine}."""
    k, blend_ids = task
    bw = _writers[k]
    bw.fresh.clear()
    for b in blend_ids:
        try:
            sp = bw.F.surface(b).spine
            if sp.curve is None and sp.P is None:
                sp._build()
        except Exception:
            pass
    got = {key: v for key, v in bw.fresh.items() if key[0] == "spine"}
    bw.fresh.clear()
    return k, got


def _edges(task):
    """Edges worked out (their slow sums: {key: result})."""
    k, edge_ids, known = task
    bw = _writers[k]
    bw.memo.update(known)
    bw.fresh.clear()
    for e in edge_ids:
        try:
            bw.edge(e)
        except Exception:
            pass
    got = dict(bw.fresh)
    bw.fresh.clear()
    return k, got


def _work(task):
    k, face_ids, spines = task
    bw = _writers[k]
    bw.memo.update(spines)
    bw.fresh.clear()
    for fid in face_ids:
        f = bw.m[fid]
        try:
            bw.face(f, False)
        except Exception:  # (written out here, it fails the same way and says why)
            pass
    got = dict(bw.fresh)
    bw.fresh.clear()
    return k, got
