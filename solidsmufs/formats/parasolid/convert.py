"""to_step(): pick the transmits that hold the part, read them, and write their bodies as STEP."""

import os
import re

from . import UnsupportedFile, appearance
from .brep import BodyWriter
from .containers import open_source, parasolid_version
from .nodes import read_transmit
from .step import Step


def _is_deltas(t):
    head = t[:120] if isinstance(t, (bytes, bytearray)) else t[:120].encode("latin-1", "replace")
    return b"(deltas)" in head


def _has(model, solid):
    """Does the model have bodies with faces (solid ones if solid)?"""
    regions = {r.idx: r["type"] for r in model.of_type("REGION")}
    if not model.of_type("FACE"):
        return False
    if not solid:
        return True
    return any(t == "S" for t in regions.values())


def convert(src_path, out_path, config=None):
    src = open_source(src_path)
    models, errors = [], []
    for name, t in _for_config(src.transmits, config):
        if _is_deltas(t):
            continue
        try:
            models.append((name, read_transmit(t)))
        except UnsupportedFile as e:
            errors.append(str(e))
    if not models:
        raise UnsupportedFile(errors[0] if errors else "No Parasolid data was found in this file.")

    chosen, choice_note = _choose(models)
    if not chosen:
        raise UnsupportedFile("This file has no solid or surface bodies.")

    w = Step()
    items, notes, styles, colours, clears = [], {}, [], [], []
    n_exact = n_fit = n_poly = n_faces = 0
    for _name, m in chosen:
        bw = BodyWriter(m, w)
        items += bw.bodies()
        styles += bw.styles
        colours += bw.body_colours
        clears += bw.body_clears
        n_exact, n_fit, n_poly = n_exact + bw.n_exact, n_fit + bw.n_fit, n_poly + bw.n_poly
        n_faces += bw.n_faces
        for k, v in bw.notes.items():
            notes[k] = notes.get(k, 0) + v
    if not items:
        why = "; ".join(notes) or "no faces could be converted"
        raise UnsupportedFile(f"No geometry could be produced from this file ({why}).")
    pad = len(items) - len(colours)
    paired = list(zip(items, colours + [None] * pad, clears + [0.0] * pad))
    if any(kind == "solid" for kind, _ in items):
        paired = [p for p in paired if p[0][0] == "solid"] + [p for p in paired if p[0][0] != "solid"]
    items, colours, clears = [p[0] for p in paired], [p[1] for p in paired], [p[2] for p in paired]
    w.write(out_path, items, os.path.splitext(os.path.basename(src_path))[0], styles)

    warnings = [choice_note] if choice_note else []
    if n_fit:
        warnings.append(f"{n_fit} edge{'s' if n_fit != 1 else ''} approximated as B-splines "
                        f"(curves on surfaces / intersections)")
    if n_poly:
        warnings.append(f"{n_poly} edge{'s' if n_poly != 1 else ''} approximated as polylines")
    for k, v in notes.items():
        warnings.append(f"{v} {k}")
    if not any(kind == "solid" for kind, _ in items):
        warnings.append("no solid bodies: written as surfaces")
    fmt = src.format
    if fmt.startswith("Parasolid"):
        ver = parasolid_version(chosen[0][1].version, src.header)
        if ver:
            fmt = f"{fmt} ({ver})"
    looks = {"material": None, "density": None, "appearances": [], "configurations": [], "hole_wizard": []}
    shown = config  # the SolidWorks configuration shown: the one asked for, else the first that has the part
    if shown is None:
        ids = [int(m.group(1)) for n, _m in chosen for m in [re.search(r"Config-(\d+)-", n)] if m]
        shown = ids[0] if ids else None
    if fmt.startswith("SolidWorks"):
        looks = appearance.solidworks(src_path, shown)
    return {"bodies": len(items), "faces": n_faces, "format": fmt, "app": src.app, "warnings": warnings,
            "edges_exact": n_exact, "edges_approx": n_fit, "edges_polyline": n_poly,
            "colours": [list(c) if c else None for c in colours], "translucency": clears, "config": shown, **looks}


def _for_config(transmits, config):
    """The transmits of SolidWorks configuration `config` (streams Contents/Config-<config>-...) when the
    file has them; all transmits otherwise (no configuration asked for, a Parasolid file, an old part)."""
    if config is None:
        return transmits
    mine = [(n, t) for n, t in transmits if re.search(rf"Config-{int(config)}-", n)]
    return mine or transmits


def _choose(models):
    """(transmits to convert, note). SolidWorks: the partition (the finished part) when it has solids, else
    the feature bodies (LocalBodies, one transmit per body); a Parasolid file has one transmit. A part saved
    flattened (a sheet-metal flat pattern in the partition) is shown folded, from its feature bodies."""
    part = [(n, m) for n, m in models if not n.endswith("/LocalBodies")]
    local = [(n, m) for n, m in models if n.endswith("/LocalBodies")]
    for solid in (True, False):
        hits = [(n, m) for n, m in part if _has(m, solid)]
        if hits:
            first = hits[0][0]  # one configuration: the first that has the part
            hits = [(n, m) for n, m in hits if n == first]
            flat = any("flat-pattern" in name.lower() for _n, m in hits for name in body_names(m).values())
            folded = [(n, m) for n, m in local if _has(m, True)]
            if flat and folded:
                return folded, "the part was saved flattened (sheet-metal flat pattern): showing it folded"
            return hits, None
        hits = [(n, m) for n, m in local if _has(m, solid)]
        if hits:
            return hits, None
    return [], None


def body_names(m):
    """{BODY index: the name SolidWorks gave it} (its SWIMPLICITBODYNAME_ID_U attribute)."""
    names = {}
    for b in m.of_type("BODY"):
        a, seen = m[b["attributes_features"]], set()
        while a is not None and a.idx not in seen:
            seen.add(a.idx)
            if a.type == "ATTRIBUTE":
                d = m[a["definition"]]
                idn = m[d["identifier"]] if d is not None else None
                if idn is not None and "".join(idn.get("string") or ()) == "SWIMPLICITBODYNAME_ID_U":
                    for fi in a.get("fields") or ():
                        fv = m[fi]
                        if fv is not None and fv.type == "UNICODE_VALUES":
                            names[b.idx] = "".join(chr(x) for x in fv.get("values") or () if x > 0)
            a = m[a.get("next", 0)]
    return names
