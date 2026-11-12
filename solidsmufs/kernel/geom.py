"""Small vector helpers shared by the kernel modules."""

import math

import numpy as np


def unit(v):
    v = np.asarray(v, np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def unit_rows(v):
    v = np.asarray(v, np.float64)
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return np.divide(v, n, out=np.zeros_like(v), where=n > 0)


def circumcircle(a, b, c):
    """(center, radius, unit normal) of the circle through three points, or None if they're in a line."""
    a, b, c = (np.asarray(p, np.float64) for p in (a, b, c))
    ab, ac = b - a, c - a
    n = np.cross(ab, ac)
    nn = float(n @ n)
    if nn <= 1e-30 * max(float(ab @ ab), float(ac @ ac), 1e-30) ** 2:
        return None
    center = a + (float(ac @ ac) * np.cross(n, ab) + float(ab @ ab) * np.cross(ac, n)) / (2 * nn)
    return center, float(np.linalg.norm(a - center)), n / math.sqrt(nn)


def vertex_normals(pts, tri):
    """Area-weighted normals at each point of a triangle mesh (zero where no triangle touches it)."""
    a, b, c = pts[tri[:, 0]], pts[tri[:, 1]], pts[tri[:, 2]]
    fn = np.cross(b - a, c - a)
    flat = tri.ravel()
    vn = np.empty_like(pts)
    for k in range(3):
        vn[:, k] = np.bincount(flat, weights=np.repeat(fn[:, k], 3), minlength=len(pts))
    return unit_rows(vn)


def line_line(p1, d1, p2, d2):
    """Closest points (q1 on line 1, q2 on line 2) between two infinite lines."""
    d1, d2 = unit(d1), unit(d2)
    w = np.asarray(p1, np.float64) - np.asarray(p2, np.float64)
    b = float(d1 @ d2)
    den = 1 - b * b
    if den < 1e-12:  # parallel: any point on line 1 and its foot on line 2
        q1 = np.asarray(p1, np.float64)
        return q1, np.asarray(p2, np.float64) + d2 * float((q1 - p2) @ d2)
    d, e = float(d1 @ w), float(d2 @ w)
    s, t = (b * e - d) / den, (e - b * d) / den
    return p1 + s * d1, p2 + t * d2


def point_line(p, a, d):
    """Foot of the perpendicular from p to the line through a along d."""
    d = unit(d)
    return np.asarray(a, np.float64) + d * float((np.asarray(p, np.float64) - a) @ d)


def angle_deg(u, v):
    c = float(np.clip(unit(u) @ unit(v), -1.0, 1.0))
    return math.degrees(math.acos(c))
