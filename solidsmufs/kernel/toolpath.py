"""A G-code program as a model the viewer can show: its moves as coloured lines, one body per tool and one for
the rapid moves, so each can be shown and hidden from the tree. Arcs are their own edges, so the measure tool
gives their radius and centre. Everything is in millimetres."""

import re
from pathlib import Path

import numpy as np

from ..formats import gcode
from .geom import unit
from .model import Model

RAPID = [0.86, 0.33, 0.22]
TOOL_COLORS = [[0.10, 0.45, 0.90], [0.10, 0.62, 0.30], [0.62, 0.25, 0.80], [0.90, 0.55, 0.05], [0.05, 0.62, 0.68],
               [0.80, 0.20, 0.45], [0.45, 0.50, 0.10], [0.35, 0.35, 0.80]]
EACH_MOVE = 40000  # up to this many moves, each its own edge; past it, runs of straight moves join up


def load(path, name, progress=lambda *a: None):
    progress("Reading the program", 0.2)
    p = gcode.read_gcode(Path(path).read_bytes())
    s = p.unit_mm
    m = Model(name, path, "G-code")
    m.kind = "drawing"

    progress("Laying out the moves", 0.5)
    tools = sorted(p.tools)
    body_of = {}
    for i, t in enumerate(tools):
        body_of[t] = len(m.bodies)
        label = f"T{t}" if t else "No tool"
        note = re.sub(rf"^T\s*0*{t}\b[\s:=-]*", "", p.tools[t], flags=re.I).strip()  # CAM notes often start with the T number
        if note:
            label += f"  {note}"
        m.bodies.append({"name": label, "path": [label], "kind": "layer", "color": TOOL_COLORS[i % len(TOOL_COLORS)], "faces": (0, 0)})
    rapid_body = len(m.bodies)
    m.bodies.append({"name": "Rapid moves", "path": ["Rapid moves"], "kind": "layer", "color": RAPID, "faces": (0, 0)})

    segs, colors, bodies, types, params, lengths, ends = [], [], [], [], [], [], []
    each = len(p.moves) <= EACH_MOVE

    def edge(pts, typ, prm, body, color):
        pts = np.asarray(pts, np.float64) * s
        steps = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        if len(pts) < 2 or not steps.sum() > 0:
            return
        segs.append(np.stack([pts[:-1], pts[1:]], axis=1))
        lengths.append(float(steps.sum()))
        types.append(typ)
        params.append(prm)
        bodies.append(body)
        colors.append(color)
        if each:
            ends.extend([pts[0], pts[-1]])

    run, run_key = [], None

    def flush():
        nonlocal run, run_key
        if run:
            kind, tool = run_key
            body = rapid_body if kind == "rapid" else body_of[tool]
            pts = np.concatenate([run[0][:1], *[r[1:] for r in run]])
            edge(pts, "path", {"start": pts[0] * s, "end": pts[-1] * s}, body, m.bodies[body]["color"])
        run, run_key = [], None

    feed_len, rapid_len, minutes = 0.0, 0.0, 0.0
    for mv in p.moves:
        length = float(np.linalg.norm(np.diff(mv.points, axis=0), axis=1).sum())
        if mv.kind == "rapid":
            rapid_len += length
        else:
            feed_len += length
            if mv.feed and not p.per_rev:
                minutes += length / mv.feed
        body = rapid_body if mv.kind == "rapid" else body_of[mv.tool]
        color = m.bodies[body]["color"]
        if mv.kind == "arc" and (each or not mv.arc["helical"]):
            flush()
            a, (st, en) = mv.arc, (mv.points[0] * s, mv.points[-1] * s)
            normal = a["normal"] if a["sweep"] > 0 else -a["normal"]
            if a["helical"]:
                edge(mv.points, "helix", {"start": st, "end": en, "center": a["center"] * s, "radius": a["radius"] * s,
                                          "normal": normal}, body, color)
            else:
                edge(mv.points, "circle", {"center": a["center"] * s, "radius": a["radius"] * s, "normal": normal, "closed": a["full"],
                                           "angle": float(np.degrees(abs(a["sweep"]))), "start": st, "end": en}, body, color)
        elif each:
            a, b = mv.points[0] * s, mv.points[-1] * s
            edge(mv.points, "line", {"start": a, "end": b, "dir": unit(b - a)}, body, color)
        else:
            key = (mv.kind if mv.kind == "rapid" else "cut", mv.tool)
            if key != run_key or (run and not np.allclose(run[-1][-1], mv.points[0])):
                flush()
                run_key = key
            run.append(mv.points)
    flush()

    m.segments = np.concatenate(segs).astype(np.float32) if segs else np.zeros((0, 2, 3), np.float32)
    counts = [len(x) for x in segs]
    m.edge_sstart = list(np.concatenate([[0], np.cumsum(counts)[:-1]]).astype(int)) if counts else []
    m.edge_scount = counts
    m.edge_type, m.edge_params, m.edge_length = types, params, lengths
    m.edge_faces = [[] for _ in types]
    m.edge_seam = [False] * len(types)
    m.edge_color, m.edge_body = colors, bodies
    if ends:
        pts = np.array(ends)
        key = np.round(pts / 1e-4).astype(np.int64)
        _u, first = np.unique(key, axis=0, return_index=True)
        m.vertices = pts[np.sort(first)]
    m.texts = []
    m.drawing = True
    m.toolpath = True

    # what the document panel and the notices say
    u = "in" if s == 25.4 else "mm"
    allpts = np.concatenate([mv.points for mv in p.moves if mv.kind != "rapid"] or [mv.points for mv in p.moves])
    lo, hi = allpts.min(axis=0), allpts.max(axis=0)
    if p.name:
        m.info["Program"] = p.name
    m.info["Units"] = p.units or "not given (shown as inches)"
    m.info["Tools"] = ", ".join(f"T{t}" for t in tools) or "none"
    m.info["Moves"] = f"{len(p.moves):,}"
    for axis, i in (("X", 0), ("Y", 1), ("Z", 2)):
        m.info[f"Cutting {axis}"] = f"{lo[i]:.4f} to {hi[i]:.4f} {u}"
    m.info["Cutting length"] = f"{feed_len:,.2f} {u}"
    m.info["Rapid length"] = f"{rapid_len:,.2f} {u}"
    if minutes and not p.per_rev:
        h, mins = divmod(minutes, 60)
        m.info["Cutting time (at the programmed feeds)"] = f"{int(h)} h {mins:.1f} min" if h else f"{mins:.1f} min"
    if p.units is None:
        m.notices.append("This program doesn't say whether it's in inches or millimetres (no G20 / G21), so it's shown in inches.")
    if p.lathe:
        m.notices.append("This looks like a lathe program: X is shown as programmed, which on most lathes is a diameter.")
    if p.skipped:
        what = "; ".join(f"{k} ({n})" for k, n in p.skipped.most_common())
        m.notices.append(f"Some of this program isn't drawn: {what}.")
    if not each:
        m.notices.append(f"This program has {len(p.moves):,} moves, so runs of straight moves are joined into one line each.")
    m.stats["drawing"] = True
    return m
