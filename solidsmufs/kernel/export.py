"""save_step(): write the open model as a STEP file (File > Save As STEP).

A SolidWorks or Parasolid part already has a STEP translation in the cache, with its colors and body names,
so that is copied. Anything else (assemblies, IGES, BREP) is written by OpenCASCADE, which drops colors and
names; the colors are added back from the model (one per solid, in the order OpenCASCADE writes them).
"""

import re
import shutil
from pathlib import Path

from ..formats.parasolid.step import Step
from .formats import CAD_FORMATS, PARASOLID_FORMATS


def save_step(session, out):
    m = session.model
    if m is None or m.kind != "brep":
        raise ValueError("Only CAD models can be saved as STEP; a mesh has no exact surfaces to write.")
    src = Path(session.path)
    ext = src.suffix.lower()
    out = Path(out)
    turned = session.orient is not None  # realigned: write the turned geometry, not the file as it came
    if CAD_FORMATS.get(ext) == "STEP" and not turned:
        shutil.copyfile(src, out)
    elif ext in PARASOLID_FORMATS and not turned:
        step, _info, cleanup = session._parasolid_step(str(src), ext, lambda *a: None)
        try:
            shutil.copyfile(step, out)
        finally:
            cleanup()
    else:
        session.ensure_exact()
        import gmsh

        tmp = out.with_name(out.name + ".tmp.step")
        try:
            gmsh.write(str(tmp))
            text = tmp.read_text(encoding="latin-1")
        finally:
            tmp.unlink(missing_ok=True)
        out.write_text(_dress(text, m, src.stem), encoding="latin-1", newline="\n")
    return {"path": str(out)}


def _dress(text, model, name):
    """OpenCASCADE's STEP with the products named after the file and its bodies, and each solid in its
    model color."""
    looks = [b for b in model.bodies if b.get("kind") == "solid"]
    # OpenCASCADE writes one product for the whole model, then (with several solids) one per solid, in order
    names = iter([name] + [b.get("name") or name for b in looks])
    text = re.sub(r"PRODUCT\(\s*'[^']*'\s*,\s*'[^']*'",
                  lambda _m: "PRODUCT('{0}','{0}'".format(_ascii(next(names, name))), text)
    solids = re.findall(r"^#(\d+)\s*=\s*(?:MANIFOLD_SOLID_BREP|BREP_WITH_VOIDS)\b", text, re.M)
    ctx = re.search(r"^#(\d+)\s*=\s*\(\s*GEOMETRIC_REPRESENTATION_CONTEXT", text, re.M)
    if not ctx or len(solids) != len(looks):  # can't pair solids with bodies safely: leave it uncolored
        return text
    styles = []
    for ref, b in zip(solids, looks):
        finish = b.get("finish") or {}
        rgb = finish.get("tint") if b.get("color") is None else b.get("color")
        if rgb is not None:
            styles.append((f"#{ref}", rgb, round(1 - float(finish.get("opacity", 1.0)), 3)))
    if not styles:
        return text
    w = Step()
    w.n = max(int(n) for n in re.findall(r"^#(\d+)\s*=", text, re.M))
    w._styles(styles, f"#{ctx.group(1)}")
    end = text.rindex("ENDSEC;")
    return text[:end] + "\n".join(w.lines) + "\n" + text[end:]


def _ascii(name):
    return "".join(ch for ch in name if 32 <= ord(ch) < 127 and ch not in "'\\") or "part"
