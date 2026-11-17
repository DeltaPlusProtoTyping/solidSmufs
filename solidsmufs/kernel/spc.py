"""Statistical process control across lots: how one characteristic ran from lot to lot (kernel/balloonops.py keeps
each lot's results when a new lot is started).

Each lot is a subgroup: its parts' measurements. chart(c, groups) gives
- an X̄ and R chart when any lot has two or more measurements: each lot's mean and range against control limits from
  the spread within lots (σ = the average of each lot's range over d2 for its size), so lots of different sizes each
  get their own limits (X̄̄ ± 3σ/√n, and d2σ ± 3d3σ for the range);
- otherwise an individuals and moving range chart (one measurement a lot): σ = the average moving range / 1.128.
Points are flagged: beyond a control limit, or the seventh in a row on one side of the center line (a run).
Capability over every lot: Cp and Cpk from σ within lots (what the process can do), Pp and Ppk from the overall
standard deviation (what it did). Standard tables (AIAG SPC manual): d2 and d3 for subgroups of 2 to 25.
"""

import math

# subgroup size: (d2, d3)
D = {2: (1.128, 0.853), 3: (1.693, 0.888), 4: (2.059, 0.880), 5: (2.326, 0.864), 6: (2.534, 0.848), 7: (2.704, 0.833),
     8: (2.847, 0.820), 9: (2.970, 0.808), 10: (3.078, 0.797), 11: (3.173, 0.787), 12: (3.258, 0.778), 13: (3.336, 0.770),
     14: (3.407, 0.763), 15: (3.472, 0.756), 16: (3.532, 0.750), 17: (3.588, 0.744), 18: (3.640, 0.739), 19: (3.689, 0.734),
     20: (3.735, 0.729), 21: (3.778, 0.724), 22: (3.819, 0.720), 23: (3.858, 0.716), 24: (3.895, 0.712), 25: (3.931, 0.708)}
RUN = 7  # points in a row on one side of the center line that flag a run


def _d(n):
    return D[min(max(n, 2), 25)]


def numbers(values):
    out = []
    for v in values:
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x):
            out.append(x)
    return out


def _capability(c, mean, sigma):
    lo, hi = c.get("lo"), c.get("hi")
    if not sigma or sigma <= 1e-12:
        return None, None
    cp = (hi - lo) / (6 * sigma) if lo is not None and hi is not None else None
    sides = [s for s in ((hi - mean) if hi is not None else None, (mean - lo) if lo is not None else None) if s is not None]
    return cp, (min(sides) / (3 * sigma) if sides else None)


def _runs(points, center, key):
    """Flags the point that makes RUN in a row on one side of the center line, and each one after it in that run."""
    side, count = 0, 0
    for p in points:
        x = p[key]
        s = 0 if x is None or abs(x - center) < 1e-12 else (1 if x > center else -1)
        count = count + 1 if s and s == side else (1 if s else 0)
        side = s
        if count >= RUN:
            p["flags"].append("run")


def chart(c, groups):
    """How characteristic c ran over its lots. groups: [{"id", "name", "values": [...]}] oldest first, results as kept
    (numbers as text; Pass, Fail and words are left out). None when fewer than two lots have a number."""
    lots = [{"id": g.get("id"), "name": g.get("name") or "", "xs": numbers(g.get("values") or [])} for g in groups]
    lots = [g for g in lots if g["xs"]]
    if len(lots) < 2:
        return None
    every = [x for g in lots for x in g["xs"]]
    lo, hi = c.get("lo"), c.get("hi")
    sub = any(len(g["xs"]) >= 2 for g in lots)
    points = []
    for g in lots:
        xs = g["xs"]
        points.append({"id": g["id"], "name": g["name"], "n": len(xs), "mean": sum(xs) / len(xs),
                       "range": (max(xs) - min(xs)) if len(xs) >= 2 else None, "min": min(xs), "max": max(xs), "flags": []})
    if sub:
        kind = "xbar_r"
        withs = [p for p in points if p["n"] >= 2]
        sigma = sum(p["range"] / _d(p["n"])[0] for p in withs) / len(withs)
        center = sum(p["mean"] * p["n"] for p in points) / sum(p["n"] for p in points)
        for p in points:
            k = 3 * sigma / math.sqrt(p["n"])
            p["ucl"], p["lcl"] = center + k, center - k
            if p["n"] >= 2:
                d2, d3 = _d(p["n"])
                p["rcl"], p["rucl"], p["rlcl"] = d2 * sigma, d2 * sigma + 3 * d3 * sigma, max(d2 * sigma - 3 * d3 * sigma, 0.0)
            else:
                p["rcl"] = p["rucl"] = p["rlcl"] = None
    else:
        kind = "i_mr"
        for a, b in zip(points, points[1:]):
            b["range"] = abs(b["mean"] - a["mean"])  # (the moving range)
        mrs = [p["range"] for p in points[1:]]
        mrbar = sum(mrs) / len(mrs)
        sigma = mrbar / 1.128
        center = sum(p["mean"] for p in points) / len(points)
        for i, p in enumerate(points):
            p["ucl"], p["lcl"] = center + 3 * sigma, center - 3 * sigma
            p["rcl"], p["rucl"], p["rlcl"] = (mrbar, 3.267 * mrbar, 0.0) if i else (None, None, None)
    for p in points:
        if p["mean"] > p["ucl"] + 1e-12 or p["mean"] < p["lcl"] - 1e-12:
            p["flags"].append("beyond")
        if p.get("rucl") is not None and p["range"] is not None and p["range"] > p["rucl"] + 1e-12:
            p["flags"].append("range")
        if (lo is not None and p["min"] < lo - 1e-9) or (hi is not None and p["max"] > hi + 1e-9):
            p["flags"].append("spec")  # (a part out of its limits: not a control rule, said beside them)
    _runs(points, center, "mean")
    n = len(every)
    overall = (sum((x - sum(every) / n) ** 2 for x in every) / (n - 1)) ** 0.5 if n >= 2 else None
    mean = sum(every) / n
    cp, cpk = _capability(c, mean, sigma)
    pp, ppk = _capability(c, mean, overall)
    return {"kind": kind, "points": points, "center": center, "sigma": sigma, "overall": overall, "mean": mean, "n": n,
            "lots": len(points), "lo": lo, "hi": hi, "cp": cp, "cpk": cpk, "pp": pp, "ppk": ppk,
            "signals": sum(1 for p in points if set(p["flags"]) - {"spec"})}
