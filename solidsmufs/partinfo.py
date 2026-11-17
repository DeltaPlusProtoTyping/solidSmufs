"""A part's quoting numbers with no window, for other programs (a quoting system): what Tools > Quote Summary shows.

    python -m solidsmufs --part part.step [--out result.json] [--material "6061-T6 Aluminum" | --density 2.7]
    SolidSmurfs.exe --part part.sldprt --out result.json      (the built app has no console to print to)

or from Python: solidsmufs.partinfo.read("part.step", material=None, density=None). The part is opened the way the
window opens it (exact CAD geometry; a mesh from its triangles). Its weight uses, in order: --density, --material (a
name from the material list, solidsmufs/web/js/consts.js), the material the file names, else none (no weight).

The answer (FORMAT 1; fields may be added, these stay). Lengths in mm and in, both, so the caller needn't convert:
    {"format": 1, "file", "kind": "cad" | "mesh", "exact": True for CAD surfaces,
     "material": {"name", "density" g/cm³ or null for each body its own, "from": "density" | "list" | "file"} or null,
     "volume": {"mm3", "in3"}, "area": {"mm2", "in2"}, "weight": {"g", "kg", "lb"} or null (no material),
     "size": {"mm": [x, y, z], "in": [...]}  (along the model's X, Y, Z),
     "envelope": {"mm": [l, w, t], "in": [...]}  (the best-fit box, longest first: the stock it fits in),
     "bodies", "faces", "holes": {"count", "groups": [{"diameter": {"mm", "in"}, "count", "through", "depth": {"mm", "in"}
     (the deepest), "thread", "likely"}]}}
"""

import json
import re
import sys
from pathlib import Path

FORMAT = 1
MM_PER_IN = 25.4


def materials():
    """{name: density g/cm³} from the app's material list (consts.js), the one list the window shows."""
    src = Path(__file__).resolve().parent / "web" / "js" / "consts.js"
    text = src.read_text(encoding="utf-8")
    block = text[text.index("export const MATERIALS"):]
    block = block[:block.index("];")]
    return {name: float(d) for name, d in re.findall(r"\['([^']+)',\s*([\d.]+)\]", block)}


def _material(model, material, density):
    if density is not None:
        density = float(density)
        if density <= 0:
            raise ValueError("--density is in g/cm³ and must be more than 0.")
        return {"name": material or "Given density", "density": density, "from": "density"}
    if material:
        known = materials()
        hit = known.get(material) or next((d for n, d in known.items() if n.lower() == material.lower()), None)
        if hit is None:
            raise ValueError(f"{material!r} isn't in the material list. Give --density in g/cm³ instead.")
        name = next(n for n in known if n.lower() == material.lower())
        return {"name": name, "density": hit, "from": "list"}
    own = getattr(model, "material", None)
    if own:
        return {"name": own["name"], "density": own.get("density"), "from": "file"}
    return None


def _both(mm, power=1):
    return {"mm" if power == 1 else f"mm{power}": round(mm, 6), "in" if power == 1 else f"in{power}": round(mm / MM_PER_IN ** power, 6)}


def _box(size):
    return {"mm": [round(float(x), 4) for x in size], "in": [round(float(x) / MM_PER_IN, 5) for x in size]}


def read(path, material=None, density=None):
    """The quoting numbers of the part at `path`, as the dict above. ValueError when it can't be read (or isn't a
    part: a print or a picture)."""
    from .kernel.formats import ASSEMBLY_FORMATS, CAD_FORMATS, MESH_FORMATS, PARASOLID_FORMATS
    from .kernel.worker import Session
    path = Path(path)
    if path.suffix.lower() not in {**CAD_FORMATS, **PARASOLID_FORMATS, **ASSEMBLY_FORMATS, **MESH_FORMATS}:
        raise ValueError("Quoting numbers are read from a part: STEP, IGES, SolidWorks, Parasolid or a mesh (STL...).")
    if not path.is_file():
        raise ValueError(f"There's no file at {path}.")
    s = Session()
    opened = s.open(str(path))
    if not opened.get("exact"):
        s.ensure_exact(str(path))
    m = s.model
    if m is None or not m.bodies:
        raise ValueError("That file has no solid bodies to measure.")
    mat = _material(m, material, density)
    rho = 1.0 if mat is None else mat["density"]  # (None: each body its own)
    mp = s.massprops(None, rho)
    world, best = s.bbox(None, "world"), s.bbox(None, "oriented")
    holes = s.holes() if m.kind == "brep" else {"groups": [], "holes": 0}
    weight = None
    if mat is not None:
        g = float(mp["mass"])
        weight = {"g": round(g, 4), "kg": round(g / 1000, 6), "lb": round(g / 453.59237, 6)}
    return {
        "format": FORMAT, "file": str(path), "kind": "cad" if m.kind == "brep" else "mesh", "exact": bool(mp.get("exact")),
        "material": mat, "volume": _both(float(mp["volume"]), 3), "area": _both(float(mp["area"]), 2), "weight": weight,
        "size": _box(world["size"]), "envelope": _box(sorted(best["size"], reverse=True)),
        "bodies": len(m.bodies), "faces": len(m.face_type) if hasattr(m, "face_type") else None,
        "holes": {"count": sum(g["count"] for g in holes["groups"]),
                  "groups": [{"diameter": _both(float(g["diameter"])), "count": g["count"], "through": bool(g["through"]),
                              "depth": _both(float(g["depth_max"])), "thread": g["thread"] or None,
                              "likely": list(g["likely"] or [])} for g in holes["groups"]]},
    }


def main(argv):
    """--part FILE [--out FILE] [--material NAME | --density G_CM3]: the answer as JSON, printed or written to --out.
    Returns the exit code: 0, or 2 with {"error": "..."} when the part couldn't be read."""
    def value(flag):
        i = argv.index(flag)
        if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
            raise ValueError(f"{flag} needs a value after it.")
        return argv[i + 1]
    out_path, code = None, 0
    try:
        out_path = value("--out") if "--out" in argv else None
        result = read(value("--part"), material=value("--material") if "--material" in argv else None,
                      density=value("--density") if "--density" in argv else None)
    except Exception as e:  # whatever went wrong, the caller gets it as JSON
        result, code = {"format": FORMAT, "error": str(e) or type(e).__name__}, 2
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
    elif sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
        print(text)
    return code
