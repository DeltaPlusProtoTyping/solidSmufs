"""Thread sizes: tapped holes and threaded shafts.

A thread shows up in a CAD file one of two ways:

- Modelled: helical faces (B-spline or swept surfaces) winding round an axis. The pitch is read off
  the helix (the radius repeats every pitch along the axis, turning with the angle) and the size from
  the diameters, so the answer is definite: "1/4-20 UNC".
- Plain: a cylinder at the tap drill or the thread's minor diameter (SolidWorks Hole Wizard holes,
  Inventor tapped holes, cosmetic threads, STEP exports). The diameter alone can only suggest sizes,
  so these are offered as "could be" matches alongside clearance holes and drill sizes.

All sizes here are in mm unless a name says otherwise.
"""

import numpy as np

from .geom import unit

IN = 25.4

# Unified inch threads: size, major diameter (in), coarse TPI and tap drill, fine TPI and tap drill
_UN = [
    ("#0", 0.060, None, None, 80, ("3/64", 0.0469)),
    ("#1", 0.073, 64, ("#53", 0.0595), 72, ("#53", 0.0595)),
    ("#2", 0.086, 56, ("#50", 0.0700), 64, ("#50", 0.0700)),
    ("#3", 0.099, 48, ("#47", 0.0785), 56, ("#45", 0.0820)),
    ("#4", 0.112, 40, ("#43", 0.0890), 48, ("#42", 0.0935)),
    ("#5", 0.125, 40, ("#38", 0.1015), 44, ("#37", 0.1040)),
    ("#6", 0.138, 32, ("#36", 0.1065), 40, ("#33", 0.1130)),
    ("#8", 0.164, 32, ("#29", 0.1360), 36, ("#29", 0.1360)),
    ("#10", 0.190, 24, ("#25", 0.1495), 32, ("#21", 0.1590)),
    ("#12", 0.216, 24, ("#16", 0.1770), 28, ("#14", 0.1820)),
    ("1/4", 0.250, 20, ("#7", 0.2010), 28, ("#3", 0.2130)),
    ("5/16", 0.3125, 18, ("F", 0.2570), 24, ("I", 0.2720)),
    ("3/8", 0.375, 16, ("5/16", 0.3125), 24, ("Q", 0.3320)),
    ("7/16", 0.4375, 14, ("U", 0.3680), 20, ("25/64", 0.3906)),
    ("1/2", 0.500, 13, ("27/64", 0.4219), 20, ("29/64", 0.4531)),
    ("9/16", 0.5625, 12, ("31/64", 0.4844), 18, ("33/64", 0.5156)),
    ("5/8", 0.625, 11, ("17/32", 0.5312), 18, ("37/64", 0.5781)),
    ("3/4", 0.750, 10, ("21/32", 0.6562), 16, ("11/16", 0.6875)),
    ("7/8", 0.875, 9, ("49/64", 0.7656), 14, ("13/16", 0.8125)),
    ("1", 1.000, 8, ("7/8", 0.8750), 12, ("59/64", 0.9219)),
]
# ISO metric: major diameter, pitch, tap drill (coarse first, then the common fine pitches)
_METRIC = [
    (1.6, 0.35, 1.25), (2, 0.4, 1.6), (2.5, 0.45, 2.05), (3, 0.5, 2.5), (3.5, 0.6, 2.9), (4, 0.7, 3.3), (5, 0.8, 4.2),
    (6, 1.0, 5.0), (8, 1.25, 6.8), (10, 1.5, 8.5), (12, 1.75, 10.2), (14, 2.0, 12.0), (16, 2.0, 14.0), (20, 2.5, 17.5),
    (24, 3.0, 21.0),
    (8, 1.0, 7.0), (10, 1.25, 8.8), (10, 1.0, 9.0), (12, 1.5, 10.5), (12, 1.25, 10.8), (14, 1.5, 12.5), (16, 1.5, 14.5),
    (20, 1.5, 18.5), (24, 2.0, 22.0),
]
_METRIC_COARSE = {1.6: 0.35, 2: 0.4, 2.5: 0.45, 3: 0.5, 3.5: 0.6, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75,
                  14: 2.0, 16: 2.0, 20: 2.5, 24: 3.0}
# NPT pipe threads (tapered 1:16 on diameter): size, outside diameter (in), TPI, tap drill
_NPT = [
    ("1/16", 0.3125, 27, ("D", 0.2460)), ("1/8", 0.405, 27, ("R", 0.3390)), ("1/4", 0.540, 18, ("7/16", 0.4375)),
    ("3/8", 0.675, 18, ("37/64", 0.5781)), ("1/2", 0.840, 14, ("23/32", 0.7188)), ("3/4", 1.050, 14, ("59/64", 0.9219)),
    ("1", 1.315, 11.5, ("1-5/32", 1.1562)),
]
NPT_HALF_ANGLE = 1.7899  # degrees: the 3/4 in per foot taper

# Clearance holes for screws: close and free (normal) fit
_CLEAR_IN = [("#4", 0.116, 0.120), ("#6", 0.144, 0.150), ("#8", 0.169, 0.177), ("#10", 0.196, 0.201), ("1/4", 0.257, 0.266),
             ("5/16", 0.323, 0.332), ("3/8", 0.386, 0.397), ("1/2", 0.516, 0.531), ("5/8", 0.641, 0.656)]
_CLEAR_MM = [("M3", 3.2, 3.4), ("M4", 4.3, 4.5), ("M5", 5.3, 5.5), ("M6", 6.4, 6.6), ("M8", 8.4, 9.0), ("M10", 10.5, 11.0),
             ("M12", 13.0, 13.5)]
_NUMBER_DRILLS = [0.228, 0.221, 0.213, 0.209, 0.2055, 0.204, 0.201, 0.199, 0.196, 0.1935, 0.191, 0.189, 0.185, 0.182, 0.18,
                  0.177, 0.173, 0.1695, 0.166, 0.161, 0.159, 0.157, 0.154, 0.152, 0.1495, 0.147, 0.144, 0.1405, 0.136, 0.1285,
                  0.12, 0.116, 0.113, 0.111, 0.11, 0.1065, 0.104, 0.1015, 0.0995, 0.098, 0.096, 0.0935, 0.089, 0.086, 0.082,
                  0.081, 0.0785, 0.076, 0.073, 0.07, 0.067, 0.0635, 0.0595, 0.055, 0.052, 0.0465, 0.043, 0.042, 0.041, 0.04]
_LETTER_DRILLS = [0.234, 0.238, 0.242, 0.246, 0.25, 0.257, 0.261, 0.266, 0.272, 0.277, 0.281, 0.29, 0.295, 0.302, 0.316,
                  0.323, 0.332, 0.339, 0.348, 0.358, 0.368, 0.377, 0.386, 0.397, 0.404, 0.413]


def _table():
    out = []
    for size, major, ctpi, ctap, ftpi, ftap in _UN:
        for tpi, tap, series in ((ctpi, ctap, "UNC"), (ftpi, ftap, "UNF")):
            if tpi:
                out.append({"callout": f"{size}-{tpi} {series}", "series": series, "major": major * IN, "pitch": IN / tpi,
                            "tpi": tpi, "tap_name": f"{tap[0]} ({tap[1]:.4f} in)", "tap": tap[1] * IN, "inch": True})
    for d, p, tap in _METRIC:
        coarse = _METRIC_COARSE.get(d) == p
        out.append({"callout": f"M{d:g}x{p:g}", "series": "ISO metric coarse" if coarse else "ISO metric fine", "major": float(d),
                    "pitch": p, "tpi": None, "tap_name": f"{tap:g} mm", "tap": tap, "inch": False})
    for size, od, tpi, tap in _NPT:
        out.append({"callout": f"{size}-{tpi:g} NPT", "series": "NPT", "major": od * IN, "pitch": IN / tpi, "tpi": tpi,
                    "tap_name": f"{tap[0]} ({tap[1]:.4f} in)", "tap": tap[1] * IN, "inch": True, "taper": True})
    for t in out:  # the internal thread's minor diameter, from basic up to about its largest allowed size
        base = t["major"] - 1.082532 * t["pitch"]
        slop = 0.0005 * IN if t["inch"] else 0.02
        t["minor"] = (base - slop, base + 0.25 * t["pitch"] + slop)
    return out


THREADS = _table()
PITCHES = sorted({t["pitch"] for t in THREADS})


# ---------------------------------------------------------------------------------------------- plain holes
def _fraction(n64):
    n, d = n64, 64
    while n % 2 == 0 and d > 1:
        n //= 2
        d //= 2
    whole, rest = divmod(n, d)
    return f"{whole}-{rest}/{d}" if whole and rest else str(whole) if whole else f"{rest}/{d}"


def drill_name(d):
    """The standard drill this diameter (mm) is, or None: fractional, number, letter or metric."""
    inch = d / IN
    n64 = round(inch * 64)
    if n64 > 0 and abs(n64 / 64 - inch) < 0.0006:
        return f'{_fraction(n64)}" drill'
    for i, x in enumerate(_NUMBER_DRILLS):
        if abs(x - inch) < 0.0006:
            return f"#{i + 1} drill ({x:.4f} in)"
    for i, x in enumerate(_LETTER_DRILLS):
        if abs(x - inch) < 0.0006:
            return f"Letter {chr(65 + i)} drill ({x:.4f} in)"
    mm = round(d * 10) / 10
    if abs(mm - d) < 0.002:  # metric holes come out of CAD exact
        return f"{mm:g} mm drill"
    return None


def thread_matches(d, internal=True):
    """Threads a plain hole (internal) or shaft (external) of diameter d could be, closest first:
    [{"callout", "how", "thread"}]. Holes match a tap drill or the minor diameter; both match the
    major diameter (cosmetic threads are often modelled there)."""
    out = []
    for t in THREADS:
        if t.get("taper"):
            continue
        if internal and abs(d - t["tap"]) <= max(0.03, 0.004 * d):
            out.append((abs(d - t["tap"]), 0, {"callout": t["callout"], "how": f"tap drill {t['tap_name']}", "thread": t}))
        elif internal and t["minor"][0] <= d <= t["minor"][1]:
            mid = (t["minor"][0] + t["minor"][1]) / 2
            out.append((abs(d - mid), 1, {"callout": t["callout"], "how": "minor diameter", "thread": t}))
        elif abs(d - t["major"]) <= max(0.02, 0.002 * d):
            out.append((abs(d - t["major"]), 2, {"callout": t["callout"], "how": "major diameter", "thread": t}))
    out.sort(key=lambda x: (x[1], x[0], x[2]["thread"]["series"] not in ("UNC", "ISO metric coarse")))
    return [x[2] for x in out]


def clearance(d):
    """("1/4", "close") when d (mm) is a clearance hole for a screw, else None: from just under the close
    fit size to a little over the free fit (clearance holes are never drilled under size)."""
    for name, a, b in [(n, a * IN, b * IN) for n, a, b in _CLEAR_IN] + _CLEAR_MM:
        if a - 0.03 <= d <= b + 0.08:
            return name, "close" if abs(d - a) <= abs(d - b) else "free"
    return None


def likely(d, internal=True):
    """What a plain hole (or shaft) of this diameter most likely is, best guess first, as phrases:
    "Tap drill for 1/4-20 UNC", "Clearance for 1/4 screw (close fit)", "#7 drill (0.2010 in)", …"""
    out = []
    threads = thread_matches(d, internal)
    for m in threads:
        if m["how"].startswith("tap drill"):
            out.append(f"Tap drill for {m['callout']}")
    name = drill_name(d) if internal else None
    c = clearance(d) if internal else None
    # an exact standard drill reads better than a clearance guess, unless the hole is the chart's own size
    on_chart = c and any(abs(d - x) <= 0.01 for n, a, b in [(n, a * IN, b * IN) for n, a, b in _CLEAR_IN] + _CLEAR_MM
                         if n == c[0] for x in (a, b))
    if name and not on_chart:
        out.append(name)
        name = None
    if c:
        out.append(f"Clearance for {c[0]} screw ({c[1]} fit)")
    for m in threads:
        if m["how"] == "minor diameter":
            out.append(f"{m['callout']} tapped (minor diameter)")
    if name:
        out.append(name)
    for m in threads:
        if m["how"] == "major diameter":
            out.append(f"{m['callout']} thread (major diameter)")
    if not out and internal:
        out.append("Bored / non-standard")
    return out


def _size_key(text):
    """"1/4-20", "#10-32", "M10x1.5" from a callout or a SolidWorks Hole Wizard type, numbers tidied so
    "M6x1.0" and "M6x1" agree; None when it names no thread size."""
    import re
    m = re.match(r"\s*(#?\d+(?:/\d+)?)\s*-\s*(\d+(?:\.\d+)?)", text)
    if m:
        return f"{m.group(1)}-{float(m.group(2)):g}"
    m = re.match(r"\s*M\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)", text)
    if m:
        return f"M{float(m.group(1)):g}x{float(m.group(2)):g}"
    return None


def hole_wizard_thread(model, d, internal=True):
    """The tapped size a plain hole of diameter d is, when the part's SolidWorks Hole Wizard says it has
    tapped holes of a size the diameter fits (tap drill, minor or major diameter): the THREADS entry, or None."""
    names = [t for t in getattr(model, "hole_wizard", []) or [] if "tap" in t.lower() or "thread" in t.lower()]
    keys = {_size_key(t) for t in names} - {None}
    if not keys or not internal:
        return None
    for m in thread_matches(d, internal):
        if _size_key(m["callout"]) in keys:
            return m["thread"]
    return None


def npt_size(d_large):
    """The NPT size a tapered hole whose large end is d_large (mm) fits, or None."""
    for t in THREADS:
        if t.get("taper") and t["tap"] - 0.3 <= d_large <= t["major"] + 0.3:
            return t
    return None


# ---------------------------------------------------------------------------------------------- modelled threads
FREEFORM = {"bspline", "bezier", "surface", "revolution", "mesh"}


def _frame(n):
    x = unit(np.cross(n, [1, 0, 0]) if abs(n[0]) < 0.9 else np.cross(n, [0, 1, 0]))
    return x, np.cross(n, x)


def _circle_fit(q):
    a = np.c_[2 * q, np.ones(len(q))]
    sol, *_ = np.linalg.lstsq(a, (q ** 2).sum(1), rcond=None)
    return sol[:2]


def _axis_dirs(m, pts):
    dirs = [np.eye(3)[i] for i in range(3)]
    for f, t in enumerate(m.face_type):
        p = m.face_params[f] or {}
        if t in ("cylinder", "cone") and p.get("axis") is not None:
            dirs.append(unit(np.asarray(p["axis"], np.float64)))
    if len(pts) > 3:
        _, vecs = np.linalg.eigh(np.cov((pts - pts.mean(0)).T))
        dirs += [vecs[:, i] for i in range(3)]
    uniq = []
    for d in dirs:
        if all(abs(float(d @ u)) < 0.99999 for u in uniq):
            uniq.append(d)
    return uniq


def _fit_axis(m, pts):
    """(roundness, center point, axis, radii) of the axis the points wind round best."""
    best = None
    for n in _axis_dirs(m, pts):
        x, y = _frame(n)
        q = np.c_[pts @ x, pts @ y]
        c = _circle_fit(q)
        r = np.linalg.norm(q - c, axis=1)
        score = float(r.std() / max(r.mean(), 1e-9))
        if best is None or score < best[0]:
            best = (score, c[0] * x + c[1] * y, n, r, x, y, q - c)
    return best


def _pitch(pts, center, n, r, q):
    """(misfit, pitch, hand) of the standard pitch the radius repeats at along the helix; misfit is the
    share of the radius's spread the helix doesn't explain (0 = a perfect thread)."""
    th = np.arctan2(q[:, 1], q[:, 0])
    z = (pts - center) @ n
    tot = float(r.var())
    if tot <= 0:
        return None
    best = None
    for p in PITCHES:
        for hand in (1, -1):
            ph = np.mod(z - hand * p * th / (2 * np.pi), p) / p
            b = np.minimum((ph * 24).astype(int), 23)
            cnt = np.bincount(b, minlength=24)
            s1 = np.bincount(b, r, 24)
            s2 = np.bincount(b, r * r, 24)
            ok = cnt > 0
            within = float((s2[ok] - s1[ok] ** 2 / cnt[ok]).sum()) / len(r)
            mis = within / tot
            if best is None or mis < best[0]:
                best = (mis, p, hand)
    return best


def _helix(m, f):
    """Thread geometry of one face if it's helical: dict or None."""
    if m.face_type[f] not in FREEFORM:
        return None
    pts, _ = m.face_triangles(f)
    pts = np.asarray(pts, np.float64)
    if len(pts) < 60:
        return None
    if len(pts) > 6000:
        pts = pts[np.linspace(0, len(pts) - 1, 6000).astype(int)]
    score, center, n, r, _x, _y, q = _fit_axis(m, pts)
    if score > 0.3:
        return None
    res = _pitch(pts, center, n, r, q)
    if res is None:
        return None
    mis, p, hand = res
    depth = float(r.max() - r.min())
    if mis > 0.15 or not (0.25 * p <= depth <= 1.1 * p):
        return None
    z = (pts - center) @ n
    center = center + n * float(z.min() + z.max()) / 2  # the middle of the thread along its axis
    return {"face": f, "pitch": p, "hand": hand, "axis": n, "center": center, "major": float(2 * r.max()),
            "minor": float(2 * r.min()), "z": (float(z.min()), float(z.max())), "misfit": mis}


def _adjacency(m):
    adj = getattr(m, "_face_adj", None)
    if adj is None:
        adj = [set() for _ in m.face_type]
        for fs in m.edge_faces:
            for a in fs:
                adj[a].update(g for g in fs if g != a)
        m._face_adj = adj
    return adj


def _internal(m, f, center, n):
    """Does the face's material wrap round the axis (a hole) rather than sit inside it (a shaft)?"""
    pts, _ = m.face_triangles(f)
    v0 = m.face_vstart[f]
    nrm = np.asarray(m.normals[v0:v0 + m.face_vcount[f]], np.float64)
    if len(nrm) != len(pts) or not len(pts):
        return None
    rel = np.asarray(pts, np.float64) - center
    radial = rel - np.outer(rel @ n, n)
    return float(np.einsum("ij,ij->i", radial, nrm).mean()) < 0


def _standard(major, minor, pitch, internal):
    """The standard thread with this pitch whose size fits the measured diameters best, or None."""
    best = None
    for t in THREADS:
        if abs(t["pitch"] - pitch) > 0.012 * pitch:
            continue
        # a modelled internal thread's root runs at or past the major diameter, an external crest at or under it
        err = abs(major - t["major"]) / t["major"]
        if internal and t["minor"][0] - 0.05 * t["major"] <= minor <= t["minor"][1] + 0.05 * t["major"]:
            err = min(err, abs(minor - sum(t["minor"]) / 2) / t["major"])
        if err < 0.12 and (best is None or err < best[0]):
            best = (err, t)
    return best[1] if best else None


def modelled(m, f):
    """The modelled thread a face belongs to (the face itself, or helical faces next to it on the same
    axis), or None."""
    cache = m.__dict__.setdefault("_threads", {})
    if f in cache:
        return cache[f]
    adj = _adjacency(m)
    seeds = [f] + [g for g in adj[f] if m.face_type[g] in FREEFORM]
    seeds += [h for g in list(seeds[1:]) for h in adj[g] if m.face_type[h] in FREEFORM and h not in seeds]
    found = None
    for g in seeds:
        hx = _helix(m, g)
        if hx is None:
            continue
        if g != f and m.face_type[f] in ("cylinder", "cone"):  # a neighbour only counts when it shares the hole's axis
            p = m.face_params[f] or {}
            a = unit(np.asarray(p.get("axis", hx["axis"]), np.float64))
            d = np.asarray(p.get("center", hx["center"]), np.float64) - hx["center"]
            if abs(abs(float(a @ hx["axis"])) - 1) > 1e-3 or np.linalg.norm(d - (d @ hx["axis"]) * hx["axis"]) > 0.05 * hx["major"]:
                continue
        found = hx
        break
    if found is None:
        cache[f] = None
        return None
    # the whole run of thread: every face joined to it round the same axis (the other flank, crest and root
    # strips, the run-out), measured along the axis
    axis, center = found["axis"], found["center"]

    def coaxial(c, a):
        d = np.asarray(c, np.float64) - center
        return abs(abs(float(unit(np.asarray(a, np.float64)) @ axis)) - 1) < 1e-3 and             np.linalg.norm(d - (d @ axis) * axis) < 0.05 * found["major"]

    faces, todo = {found["face"]}, [found["face"]]
    z0, z1 = found["z"][0] - sum(found["z"]) / 2, found["z"][1] - sum(found["z"]) / 2
    major, minor = found["major"], found["minor"]
    while todo:
        for g in adj[todo.pop()]:
            if g in faces:
                continue
            t, p = m.face_type[g], m.face_params[g] or {}
            if t in FREEFORM:
                hx = _helix(m, g)
                if hx is None or abs(hx["pitch"] - found["pitch"]) > 1e-6 or not coaxial(hx["center"], hx["axis"]):
                    continue
                major, minor = max(major, hx["major"]), min(minor, hx["minor"])
            elif t == "cylinder" and p.get("axis") is not None and coaxial(p["center"], p["axis"])                     and 0.45 * found["minor"] <= p["radius"] <= 0.55 * found["major"]:
                pass
            else:
                continue
            faces.add(g)
            todo.append(g)
            pts, _ = m.face_triangles(g)
            if len(pts):
                z = (np.asarray(pts, np.float64) - center) @ axis
                z0, z1 = min(z0, float(z.min())), max(z1, float(z.max()))
    internal = _internal(m, found["face"], found["center"], found["axis"])
    std = _standard(major, minor, found["pitch"], internal is not False)
    res = {"modelled": True, "internal": internal, "callout": std["callout"] if std else None, "thread": std,
           "pitch": found["pitch"], "hand": "right" if found["hand"] > 0 else "left", "major": major, "minor": minor,
           "length": z1 - z0, "center": center + axis * (z0 + z1) / 2, "axis": axis, "faces": sorted(faces)}
    for g in faces | {f}:
        cache[g] = res
    return res


# ---------------------------------------------------------------------------------------------- one face
def identify(m, f):
    """What thread a face is, for the measure tool: a modelled thread's size, or for a plain round hole
    or shaft the sizes it could be. None when the face isn't round."""
    t, p = m.face_type[f], m.face_params[f] or {}
    if t in FREEFORM or t in ("cylinder", "cone"):
        res = modelled(m, f)
        if res is not None:
            return res
    if t == "cylinder" and p.get("radius"):
        c, a = np.asarray(p["center"], np.float64), unit(np.asarray(p["axis"], np.float64))
        d = 2 * float(p["radius"])
        internal = _internal(m, f, c, a)
        hw = hole_wizard_thread(m, d, internal is not False)
        if hw is not None:  # the part's Hole Wizard has a tapped hole of a size this fits: say so outright
            return {"modelled": False, "hole_wizard": True, "internal": True, "diameter": d, "callout": hw["callout"],
                    "thread": hw, "likely": [f"{hw['callout']} tapped (Hole Wizard)"], "matches": []}
        return {"modelled": False, "internal": internal, "diameter": d, "likely": likely(d, internal is not False),
                "matches": [{"callout": x["callout"], "how": x["how"]} for x in thread_matches(d, internal is not False)]}
    if t == "cone" and p.get("half_angle") is not None and abs(float(p["half_angle"]) - NPT_HALF_ANGLE) < 0.05:
        std = npt_size(2 * float(p.get("radius_max", 0)))
        if std:
            return {"modelled": False, "internal": True, "taper": True, "callout": std["callout"], "thread": std,
                    "likely": [f"{std['callout']} tapped (pipe taper)"], "matches": [{"callout": std["callout"], "how": "pipe taper"}]}
    return None


def describe(t):
    """Short text for a thread: '20 TPI (1.270 mm)' / '1.25 mm' for its pitch."""
    if t.get("tpi"):
        return f"{t['tpi']:g} TPI ({t['pitch']:.3f} mm)"
    return f"{t['pitch']:g} mm"
