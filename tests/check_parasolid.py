"""Convert every SolidWorks / Parasolid sample on this PC with solidsmufs.formats.parasolid and check the STEP
with gmsh (OpenCASCADE): solids, faces, volume, exact vs approximated edges, round edges gmsh sees as circles,
and for parts with an independent export (STEP / IGES / x_t) the volume difference.

    python tests/check_parasolid.py [--jobs N] [--filter TEXT] [--out DIR] [file ...]

Each file is checked in its own process (a crash inside OpenCASCADE can't stop the run).
"""

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DOWNLOADS = r"C:\Users\BEN.PAUZA\Downloads"
PARTMAKER = r"C:\Users\Public\Documents\Autodesk\PartMaker"
SCRATCH = os.path.join(os.environ.get("TEMP", r"C:\Temp"), "solidsmufs_check_parasolid")
EXTS = (".sldprt", ".x_t", ".xmt_txt", ".x_b", ".xmt_bin")

# independent exports of the same part (reference loaded with gmsh, or with our converter for .x_t)
PAIRS = {
    "v_base23.SLDPRT": "v_base23.igs",
    "v_guide26.SLDPRT": "v_guide26.STEP",
    "9D8560-1(2).stp.SLDPRT": "9D8560-1(2).stp",
}


def samples():
    out = [f for f in glob.glob(os.path.join(DOWNLOADS, "*")) if f.lower().endswith(EXTS)]
    out += [f for f in glob.glob(os.path.join(PARTMAKER, "**", "*"), recursive=True) if f.lower().endswith(EXTS)]
    return sorted(set(out), key=lambda p: (os.path.dirname(p).lower(), os.path.basename(p).lower()))


def reference_for(path):
    d, name = os.path.split(path)
    if name in PAIRS:
        ref = os.path.join(d, PAIRS[name])
        return ref if os.path.exists(ref) else None
    if name.lower().endswith(".sldprt"):  # PartMaker: the same part saved as Parasolid text
        stem = os.path.splitext(name)[0].lower()
        for f in os.listdir(d):
            s, e = os.path.splitext(f)
            if e.lower() in (".x_t", ".x_b") and s.lower() == stem:
                return os.path.join(d, f)
    return None


# ------------------------------------------------------------------ one file (child process)
def _gmsh_stats(gmsh, path, sew=False):
    gmsh.clear()
    gmsh.model.occ.importShapes(path)
    gmsh.model.occ.synchronize()
    vols = gmsh.model.getEntities(3)
    if not vols and sew:  # IGES: faces only; sew them into a volume
        surfs = [t for _, t in gmsh.model.getEntities(2)]
        loop = gmsh.model.occ.addSurfaceLoop(surfs, sewing=True)
        gmsh.model.occ.addVolume([loop])
        gmsh.model.occ.synchronize()
        vols = gmsh.model.getEntities(3)
    volume = sum(gmsh.model.occ.getMass(3, t) for _, t in vols)
    neg = sum(1 for _, t in vols if gmsh.model.occ.getMass(3, t) <= 0)
    types = {}
    for _, t in gmsh.model.getEntities(1):
        k = gmsh.model.getType(1, t)
        types[k] = types.get(k, 0) + 1
    return {"solids": len(vols), "faces": len(gmsh.model.getEntities(2)), "volume": volume, "neg": neg,
            "types": types}


def check_one(path, out_dir):
    from solidsmufs.formats.parasolid import UnsupportedFile, to_step
    import gmsh

    res = {"file": path}
    tag = hashlib.md5(os.path.abspath(path).lower().encode()).hexdigest()[:6]  # same names in other folders
    out = os.path.join(out_dir, f"{tag}_{os.path.basename(path)}.stp")
    t0 = time.perf_counter()
    try:
        r = to_step(path, out)
    except UnsupportedFile as e:
        res.update(ok=False, error=f"UnsupportedFile: {e}", seconds=time.perf_counter() - t0)
        return res
    except Exception as e:  # a bug
        import traceback
        res.update(ok=False, error=f"{type(e).__name__}: {e}", trace=traceback.format_exc(),
                   seconds=time.perf_counter() - t0)
        return res
    res["seconds"] = time.perf_counter() - t0
    res["result"] = r
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        res["gmsh"] = _gmsh_stats(gmsh, out)
        ref = reference_for(path)
        if ref:
            res["ref"] = ref
            if ref.lower().endswith((".x_t", ".x_b")):
                rout = os.path.join(out_dir, f"{tag}_{os.path.basename(ref)}.ref.stp")
                to_step(ref, rout)
                res["ref_stats"] = _gmsh_stats(gmsh, rout)
            else:
                res["ref_stats"] = _gmsh_stats(gmsh, ref, sew=ref.lower().endswith((".igs", ".iges")))
    except Exception as e:
        res["gmsh_error"] = f"{type(e).__name__}: {e}"
    finally:
        gmsh.finalize()
    g = res.get("gmsh")
    lost = [x for x in r["warnings"] if "skipped" in x or "written as surfaces" in x]
    res["ok"] = bool(g and g["solids"] > 0 and g["neg"] == 0 and not lost)
    return res


# ------------------------------------------------------------------ the run
def run_child(path, out_dir, timeout=600):
    cmd = [sys.executable, os.path.abspath(__file__), "--child", path, "--out", out_dir]
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"file": path, "ok": False, "error": f"timed out after {timeout} s"}
    for line in reversed(p.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    return {"file": path, "ok": False, "error": f"crashed (exit {p.returncode}): {p.stderr.strip()[-300:]}"}


def fmt_row(r):
    name = os.path.relpath(r["file"], PARTMAKER) if r["file"].startswith(PARTMAKER) else os.path.basename(r["file"])
    name = name if len(name) <= 58 else "…" + name[-57:]
    if not r.get("result"):
        return f"FAIL {name:58s} {r.get('seconds', 0):5.2f}s  {r.get('error', '')}"
    res, g = r["result"], r.get("gmsh") or {}
    types = g.get("types", {})
    circ = types.get("Circle", 0)
    diff = ""
    rs = r.get("ref_stats")
    if rs and rs.get("volume"):
        diff = f"{100.0 * (g.get('volume', 0) - rs['volume']) / rs['volume']:+8.4f}%"
    elif r.get("ref"):
        diff = "  ref?   "
    warn = "; ".join(res["warnings"])
    status = "OK  " if r.get("ok") else "FAIL"
    extra = f" gmsh: {r['gmsh_error']}" if r.get("gmsh_error") else ""
    return (f"{status} {name:58s} {r['seconds']:5.2f}s solids={g.get('solids', 0):2d} faces={g.get('faces', 0):4d} "
            f"vol={g.get('volume', 0):14.3f} {diff:9s} exact={res['edges_exact']:4d} approx={res['edges_approx']:4d} "
            f"poly={res['edges_polyline']:3d} circles={circ:4d} | {res['format']} | {warn}{extra}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--jobs", type=int, default=max(1, min(6, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--filter", default="")
    ap.add_argument("--out", default=SCRATCH)
    ap.add_argument("--child", default=None)
    ap.add_argument("--json", default=None, help="also write all results to this JSON file")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.child:
        print(json.dumps(check_one(a.child, a.out)))
        return
    files = a.files or samples()
    files = [f for f in files if a.filter.lower() in f.lower()]
    print(f"{len(files)} files; STEP output in {a.out}")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(a.jobs) as ex:
        results = list(ex.map(lambda f: run_child(f, a.out), files))
    for r in results:
        print(fmt_row(r), flush=True)
    n_ok = sum(1 for r in results if r.get("ok"))
    paired = [r for r in results if r.get("ref_stats") and r["ref_stats"].get("volume") and r.get("gmsh")]
    within = sum(1 for r in paired
                 if abs(r["gmsh"]["volume"] - r["ref_stats"]["volume"]) <= 1e-3 * abs(r["ref_stats"]["volume"]))
    ex_ = sum(r["result"]["edges_exact"] for r in results if r.get("result"))
    ap_ = sum(r["result"]["edges_approx"] for r in results if r.get("result"))
    po_ = sum(r["result"]["edges_polyline"] for r in results if r.get("result"))
    print(f"\n{n_ok}/{len(results)} OK; {within}/{len(paired)} paired volumes within 0.1%; "
          f"edges: {ex_} exact, {ap_} approximated, {po_} polylines; {time.perf_counter() - t0:.0f} s")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(results, fh, indent=1)


if __name__ == "__main__":
    main()
