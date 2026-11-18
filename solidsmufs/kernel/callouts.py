"""Where a print's callouts are on the 3D model: which faces each size, thread, angle and chamfer on the PDF is about.

match(model, callouts, unit, holes) takes the print's callouts as ballooning reads them (kernel/balloons.py:
{"kind", "type", "text", "count", "nominal", "lo", "hi", "places", "tol", ...}) and gives, for each,
{"status": "one" | "choices" | "none" | "skip", "choices": [{"faces", "what", "at", "size"}], "total": how many
places on the model fit}:
  - a diameter: the round holes and bosses of that size (all of them: they're one feature as far as the print goes);
  - a radius: the fillets and arcs of that radius;
  - a thread: the holes modelled or drilled for it (tap drill, minor or major diameter), or a shaft of its major size;
  - a length: two parallel faces that far apart, a face and a hole's axis, or two holes' axes, along a direction a
    face of the part faces. Most often there are several, so the user picks;
  - an angle: a countersink or cone of that angle, or two faces meeting at it;
  - a chamfer: the cones and flats of that size and angle;
  - a feature control frame: what the size it's attached to matched (the caller says which: "with");
  - notes and surface finishes: "skip", as they're not about a face that can be found by its size.
Everything on the model is in mm; unit says what the print is in ("in", "mm", or None to try both).

This is a first pass, by size alone: what it finds is for the user to check, and to pick from when it can't tell.
"""

import math
import re

import numpy as np

from . import threads
from .geom import unit as _unit

IN = 25.4
MAX_CHOICES = 12
FULL = 300  # degrees round its axis a cylinder covers to be a whole hole or boss


# ---------------------------------------------------------------------------------------------- the model
class Shapes:
    """The model's faces sorted by what a print can call out on them."""

    def __init__(self, m, holes=None):
        self.m = m
        self.cyl, self.planes, self.cones, self.tori, self.spheres = [], [], [], [], []
        self.near = {}  # face → the faces it shares an edge with
        for fs in m.edge_faces:
            for a in fs:
                self.near.setdefault(a, set()).update(b for b in fs if b != a)
        self._centroids = {}
        for f, t in enumerate(m.face_type):
            p = m.face_params[f] if f < len(m.face_params) else None
            if not p:
                continue
            if t == "plane":
                n = _unit(p["normal"])
                self.planes.append({"face": f, "n": n, "off": float(np.asarray(p["origin"], np.float64) @ n)})
            elif t == "cylinder":
                self._add_cylinder(f, p)
            elif t == "cone" and p.get("half_angle") is not None:
                self.cones.append({"face": f, **p})
            elif t == "torus":
                self.tori.append({"face": f, "r": float(p["minor_radius"])})
            elif t == "sphere":
                self.spheres.append({"face": f, "r": float(p["radius"])})
        for c in self.cyl:
            ang = np.sort(np.asarray(sorted(c.pop("bins")), np.float64))
            gap = float(np.max(np.diff(np.concatenate([ang, ang[:1] + 360])))) if len(ang) else 360.0
            c["full"] = 360 - gap >= FULL
        self.threads = [g for g in (holes or {}).get("groups", []) if g.get("thread")]

    def _add_cylinder(self, f, p):
        m = self.m
        pts, tri = m.face_triangles(f)
        if not len(tri):
            return
        v0 = m.face_vstart[f]
        nrm = np.asarray(m.normals[v0:v0 + m.face_vcount[f]], np.float64)
        c, a = np.asarray(p["center"], np.float64), _unit(p["axis"])
        if a[np.argmax(np.abs(a))] < 0:
            a = -a
        rel = pts - c
        radial = rel - np.outer(rel @ a, a)
        hole = float(np.einsum("ij,ij->i", radial, nrm).mean()) < 0  # normals toward the axis: material around it
        x = _unit(np.cross(a, [1, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1, 0]))
        bins = set(np.round(np.degrees(np.arctan2(radial @ np.cross(a, x), radial @ x)) % 360, 1).tolist())  # angles round it
        r = float(p["radius"])
        for g in self.cyl:  # coaxial faces of one radius are one feature (SolidWorks splits a hole in two halves)
            d = c - g["c"]
            if abs(r - g["r"]) < 1e-4 and abs(abs(a @ g["a"]) - 1) < 1e-6 and np.linalg.norm(d - (d @ g["a"]) * g["a"]) < 1e-4:
                g["faces"].append(f)
                g["bins"] |= bins
                return
        self.cyl.append({"r": r, "c": c, "a": a, "faces": [f], "bins": bins, "hole": hole})

    def centroid(self, f):
        if f not in self._centroids:
            from .measure import face_centroid
            c = face_centroid(self.m, f)
            self._centroids[f] = None if c is None else [float(v) for v in c]
        return self._centroids[f]

    def at(self, faces):
        pts = [p for p in (self.centroid(f) for f in faces[:1]) if p is not None]
        return pts[0] if pts else None

    def width(self, f):
        """A flat face's narrow width (mm): its extent across, the short way."""
        pts, _ = self.m.face_triangles(f)
        if len(pts) < 3:
            return 0.0
        q = pts - pts.mean(axis=0)
        _, _, vt = np.linalg.svd(q, full_matrices=False)
        return float(np.ptp(q @ vt[1]))

    def directions(self):
        """The directions the part's flat faces face (one per pair of opposite ones)."""
        out = []
        for p in self.planes:
            n = p["n"]
            if not any(abs(n @ d) > 1 - 1e-6 for d in out):
                out.append(n)
        return out


# ---------------------------------------------------------------------------------------------- sizes
def window(c, unit):
    """(lo, hi) in mm the model's size may be to be this callout's, or None. Modelled at nominal or anywhere within
    the limits; a size with none is good to half its last decimal place. A MIN size is good up to a quarter over, a MAX
    one down to a quarter under (any size past it would match every bigger or smaller pair of faces)."""
    nom = c.get("nominal")
    if nom is None:
        return None
    k = IN if unit == "in" else 1.0
    lo, hi = c.get("lo"), c.get("hi")
    if lo is not None and hi is not None and hi >= lo:
        a, b = min(lo, nom), max(hi, nom)
    elif lo is not None and hi is None:  # MIN
        a, b = lo, lo * 1.25
    elif hi is not None and lo is None:  # MAX
        a, b = hi * 0.75, hi
    else:
        places = c.get("places") or 0
        half = min(0.5 * 10 ** -places, 0.005 * abs(nom) + (0.0005 if unit == "in" else 0.01))
        a, b = nom - half, nom + half
    slack = 2e-4 + 1e-5 * abs(nom * k)
    return a * k - slack, b * k + slack


def band_in(c, unit):
    """How wide the callout's tolerance is, in inches (None: it gives none). A feature control frame's is its zone."""
    k = 1.0 if unit == "in" else 1 / IN
    if c.get("kind") == "gdt":
        m = re.search(r"\|\s*[Ø⌀]?\s*(\d*\.\d+|\d+)", c.get("text") or "")
        return float(m.group(1)) * k if m else None
    lo, hi = c.get("lo"), c.get("hi")
    if lo is None or hi is None or c.get("tol") in ("ref", "basic"):
        return None
    return max(hi - lo, 0.0) * k


def _in(v, w):
    return w is not None and w[0] <= v <= w[1]


def _show(mm, unit):
    return f"{mm / IN:.4f} in" if unit == "in" else f"{mm:.3f} mm"


# ---------------------------------------------------------------------------------------------- matching
def _diameter(S, c, unit):
    w = window(c, unit)
    sphere = (c.get("text") or "").lstrip().upper().startswith("S")
    if sphere:
        found = [s for s in S.spheres if _in(2 * s["r"], w)]
        return [{"faces": [s["face"] for s in found], "what": f"{len(found)} sphere(s)", "size": 2 * found[0]["r"]}] if found else []
    for full in (True, False):
        found = [g for g in S.cyl if g["full"] == full and _in(2 * g["r"], w)]
        if found:
            holes = sum(g["hole"] for g in found)
            kind = ("hole" if holes == len(found) else "boss" if not holes else "round feature") + ("" if full else " (partial)")
            return [{"faces": sorted(f for g in found for f in g["faces"]), "count": len(found),
                     "what": f"{len(found)} {kind}{'s' if len(found) > 1 else ''} Ø{_show(2 * found[0]['r'], unit)}", "size": 2 * found[0]["r"]}]
    return []


def _across(S, c, unit):
    """A plain length that's the diameter of a whole round feature."""
    w = window(c, unit)
    found = [g for g in S.cyl if g["full"] and _in(2 * g["r"], w)]
    if not found:
        return []
    holes = sum(g["hole"] for g in found)
    kind = "hole" if holes == len(found) else "boss" if not holes else "round feature"
    return [{"faces": sorted(f for g in found for f in g["faces"]), "count": len(found),
             "what": f"across {len(found)} {kind}{'s' if len(found) > 1 else ''} Ø{_show(2 * found[0]['r'], unit)}", "size": 2 * found[0]["r"]}]


def _radius(S, c, unit):
    w = window(c, unit)
    faces = [f for g in S.cyl if not g["full"] and _in(g["r"], w) for f in g["faces"]]
    faces += [t["face"] for t in S.tori if _in(t["r"], w)]
    faces += [s["face"] for s in S.spheres if _in(s["r"], w)]
    if not faces:
        faces = [f for g in S.cyl if _in(g["r"], w) for f in g["faces"]]
    return [{"faces": sorted(faces), "count": len(faces), "what": f"{len(faces)} face{'s' if len(faces) > 1 else ''} of R{_show((w[0] + w[1]) / 2, unit)}",
             "size": (w[0] + w[1]) / 2}] if faces else []


def _thread(S, c):
    key = threads._size_key(re.sub(r"^\s*\d+\s*X\s*", "", c.get("text") or "", flags=re.I))
    if key is None:
        return []
    specs = [t for t in threads.THREADS if threads._size_key(t["callout"]) == key]
    found = [g for g in S.threads if threads._size_key(g["thread"]) == key]
    if found:
        faces = sorted(f for g in found for f in g["faces"])
        n = sum(g["count"] for g in found)
        return [{"faces": faces, "count": n, "what": f"{n} hole{'s' if n > 1 else ''} with a modelled or Hole Wizard {key} thread"}]
    drilled, major, shafts = [], [], []  # a hole drilled for it (tap drill, minor diameter); one drawn at its major
    for g in S.cyl:
        if not g["full"]:
            continue
        d = 2 * g["r"]
        if g["hole"]:
            hows = [m["how"] for m in threads.thread_matches(d) if threads._size_key(m["callout"]) == key]
            if any(not h.startswith("major") for h in hows):
                drilled.append(g)
            elif hows:
                major.append(g)
        elif any(abs(d - t["major"]) <= max(0.05, 0.01 * d) for t in specs):
            shafts.append(g)
    out = drilled or major or shafts
    if not out:
        return []
    holes = sum(g["hole"] for g in out)
    return [{"faces": sorted(f for g in out for f in g["faces"]), "count": len(out),
             "what": f"{len(out)} {'hole' if holes else 'shaft'}{'s' if len(out) > 1 else ''} sized for {key}"}]


def _levels(S, d):
    """Along direction d: the flat faces facing along it and the axes across it, by how far along they are."""
    lv = []
    for p in S.planes:
        if abs(p["n"] @ d) > 1 - 1e-6:
            lv.append(("face", float(p["off"] * (p["n"] @ d)), [p["face"]]))
    for g in S.cyl:
        if g["full"] and abs(g["a"] @ d) < 1e-6:
            lv.append(("axis", float(g["c"] @ d), g["faces"]))
    merged = []
    for kind, off, faces in sorted(lv, key=lambda x: x[1]):
        same = next((x for x in merged if x["kind"] == kind and abs(x["off"] - off) < 1e-4), None)
        if same:
            same["faces"] += faces
            same["n"] += 1
        else:
            merged.append({"kind": kind, "off": off, "faces": list(faces), "n": 1})
    return merged


def _linear(S, c, unit):
    w = window(c, unit)
    lo, hi = c.get("lo"), c.get("hi")
    if lo is not None and hi is not None and c["nominal"] <= hi - lo:  # no bigger than its tolerance: a flatness or a
        return []                                                          # note's number read as a size, not a length
    nom = c["nominal"] * (IN if unit == "in" else 1.0)
    found = []
    for d in S.directions():
        lv = _levels(S, d)
        for i, a in enumerate(lv):
            for b in lv[i + 1:]:
                gap = b["off"] - a["off"]
                if gap > w[1]:
                    break
                if gap < w[0]:
                    continue
                rank = {("face", "face"): 0, ("axis", "face"): 1, ("face", "axis"): 1}.get((a["kind"], b["kind"]), 2)
                what = {0: "2 parallel faces", 1: "a face and a hole's axis", 2: "two holes' axes"}[rank]
                pa, pb = S.at(a["faces"]), S.at(b["faces"])
                at = pa if a["kind"] == "face" else pb if b["kind"] == "face" else pa  # on a face (between them is in the part)
                found.append((rank, abs(gap - nom), {"faces": sorted(set(a["faces"] + b["faces"])), "what": f"{what} {_show(gap, unit)} apart",
                                                     "size": gap, "at": at, "ends": [pa, pb]}))
    found.sort(key=lambda x: (x[0], x[1]))
    return [x[2] for x in found]


def _angle(S, c, unit):
    nom = c["nominal"]
    lo, hi = c.get("lo"), c.get("hi")
    tol = max(0.5, (hi - lo) / 2 if lo is not None and hi is not None else 0.5)
    ok = lambda a: abs(a - nom) <= tol + 1e-6  # noqa: E731
    # a cone's angle across (countersinks, points), from its axis, or from the face it's cut into (chamfers)
    cones = [k for k in S.cones if ok(2 * k["half_angle"]) or ok(k["half_angle"]) or ok(90 - k["half_angle"])]
    out = []
    if cones:
        out.append({"faces": sorted(k["face"] for k in cones), "count": len(cones),
                    "what": f"{len(cones)} cone{'s' if len(cones) > 1 else ''} (countersinks, chamfers, points)"})
    planes = {p["face"]: p for p in S.planes}
    seen = set()
    for f, p in planes.items():
        for g in S.near.get(f, ()):
            q = planes.get(g)
            if q is None or (g, f) in seen:
                continue
            seen.add((f, g))
            between = math.degrees(math.acos(max(-1.0, min(1.0, float(p["n"] @ q["n"])))))
            if ok(between) or ok(180 - between):
                pa, pb = S.centroid(f), S.centroid(g)
                at = None if pa is None or pb is None else [(x + y) / 2 for x, y in zip(pa, pb)]
                out.append({"faces": [f, g], "what": f"2 faces at {180 - between:.2f}°", "at": at})
    return out


def _chamfer(S, c, unit):
    leg = c["nominal"] * (IN if unit == "in" else 1.0)
    m = re.search(r"X\s*(\d+(?:\.\d+)?)\s*°", c.get("text") or "", re.I)
    ang = float(m.group(1)) if m else 45.0
    near = lambda v, want: abs(v - want) <= 0.15 * want + 0.03  # noqa: E731
    faces = []
    for k in S.cones:
        h = k["half_angle"]
        if min(abs(h - ang), abs(h - (90 - ang))) > 1.0:
            continue
        radial = k.get("radius_max", 0) - k.get("radius_min", 0)
        axial = radial / math.tan(math.radians(h)) if h > 0.5 else 0
        if near(radial, leg) or near(axial, leg):
            faces.append(k["face"])
    planes = {p["face"]: p for p in S.planes}
    for f, p in planes.items():
        for g in S.near.get(f, ()):
            q = planes.get(g)
            if q is None:
                continue
            between = math.degrees(math.acos(max(-1.0, min(1.0, abs(float(p["n"] @ q["n"]))))))
            if min(abs(between - ang), abs(between - (90 - ang))) <= 1.0:
                wd = S.width(f)
                if near(wd, leg / math.cos(math.radians(ang))) or near(wd, leg / math.sin(math.radians(ang))):
                    faces.append(f)
                    break
    return [{"faces": sorted(set(faces)), "count": len(set(faces)), "what": f"{len(set(faces))} chamfer face{'s' if len(set(faces)) > 1 else ''}"}] if faces else []


def _one(S, c, unit):
    kind, typ = c.get("kind"), c.get("type") or ""
    if kind == "thread":
        return _thread(S, c)
    if c.get("nominal") is None:
        return None
    if kind == "dim":
        if typ == "Diameter" or "Ø" in (c.get("text") or ""):
            return _diameter(S, c, unit)
        if typ == "Radius":
            return _radius(S, c, unit)
        # no two faces that far apart: a diameter dimensioned across a side view (or its Ø not read)
        return _linear(S, c, unit) or _across(S, c, unit)
    if kind == "angle":
        return _angle(S, c, unit)
    if kind == "chamfer":
        return _chamfer(S, c, unit)
    return None


def _result(S, found):
    if found is None:
        return {"status": "skip", "choices": [], "total": 0}
    for ch in found:
        if ch.get("at") is None:
            ch["at"] = S.at(ch["faces"])
    status = "none" if not found else "one" if len(found) == 1 else "choices"
    return {"status": status, "choices": found[:MAX_CHOICES], "total": len(found)}


def match(m, callouts, unit=None, holes=None):
    """{"unit": the print's unit used, "results": [one per callout, in order]} (see the module's notes)."""
    S = Shapes(m, holes)
    best = None
    # the print's unit first; the other too, as a print's notes can say inches over metric sizes (or OCR misread them)
    for u in ([unit, "mm" if unit == "in" else "in"] if unit in ("in", "mm") else ["in", "mm"]):
        res = [None if c.get("kind") == "gdt" else _result(S, _one(S, c, u)) for c in callouts]
        for c, r in zip(callouts, res):
            if r is not None:
                r["band"] = band_in(c, u)
        score = (sum(r is not None and r["status"] == "one" for r in res), sum(r is not None and r["status"] == "choices" for r in res))
        if best is None or score > best[0]:
            best = (score, u, res)
    _, u, res = best
    for i, c in enumerate(callouts):  # a frame goes where the size it's attached to went
        if res[i] is None:
            j = c.get("with")
            r = res[j] if j is not None and 0 <= j < len(res) and res[j] is not None else None
            res[i] = ({**r, "band": band_in(c, u), "via": j} if r and r["status"] in ("one", "choices")
                      else {"status": "none", "choices": [], "total": 0, "band": band_in(c, u)})
    return {"unit": u, "results": res}
