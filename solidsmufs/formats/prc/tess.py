"""PRC's highly compressed tessellation (PRC_TYPE_TESS_3D_Compressed, ISO 14739-1 clause 7.8.9): triangles
grown one from another across their edges, each new corner stored as a small offset in a frame built on
the edge it grew from.

The standard's text has known errors. The rules here come from the PDF Association's errata threads
(github.com/pdf-association/pdf-issues, issues 436, 727, 773, 774, 775) and from studying how nanoPRC reads
real files; a wrong rule shows at once, since every bit of the file must be used up and the surface come out
closed:

* Which edge comes next: a triangle pushes its right edge, then its left, if it has a neighbour there. An edge
  with no neighbour is noted as closed. Edges are popped last-in-first-out, and only after a triangle that
  pushed nothing can the popped edge be one already closed: those are skipped. An empty stack starts a new
  triangle from scratch, which is not the end of the mesh.
* A new corner sits in a frame on its edge: X from the lower-numbered end's side, Z square to the edge and the
  triangle behind it, Y = Z x X, both Y and Z turned over if Y leads away from that triangle. An axis shorter
  than single precision's epsilon is no axis: Z is then X x (0, 1, 0), or X x (1, 0, 0).
* Normals are listed per vertex. The first time a vertex is met, a bit says whether it has several. If so, each
  later use reads a bit: reuse one (an index counted back from the newest), or read a new one.
* A planar face has one normal: at its first triangle, that of the first corner, by the same rules.
* A triangle's normal (at its first corner) says which way it faces, and that swaps its left and right. So the
  normals have to be read in step with the triangles, even though they aren't otherwise needed to draw them.
"""

import math
import struct

import numpy as np

from .bits import PrcError

HALF_PI = math.pi / 2
QUARTER_PI = math.pi / 4
FLT_EPSILON = 1.1920928955078125e-07


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _neg(a):
    return (-a[0], -a[1], -a[2])


_F = struct.Struct("<f")
_E = struct.Struct("<I")


def _length(a):
    """The standard's vector length: the root, by Newton's method, of the square rounded to single precision.
    Exact matters: on a triangle rounded flat, these last digits are what give the sign its side."""
    raw = _F.pack(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    squared = _F.unpack(raw)[0]
    if squared == 0.0:
        return 0.0
    bits = _E.unpack(raw)[0]
    exponent = (bits >> 23) & 255
    guess = squared
    if exponent > 127:  # a closer start, halving the exponent
        guess = _F.unpack(_E.pack((bits & 0x807FFFFF) | ((((exponent - 127) // 2 + 127) & 255) << 23)))[0]
    for _ in range(100):
        better = (guess + squared / guess) / 2
        if better == guess:
            return better
        guess = better
    return -1.0  # it never settled: as the standard's, too short to use


def _unit(a):
    """a made unit length, or None when it's too short to have a direction."""
    n = _length(a)
    if n < FLT_EPSILON:
        return None
    return (a[0] / n, a[1] / n, a[2] / n)


def _square_to(x):
    """A unit vector square to unit x, the way the format chooses it when a triangle gives no frame of its own."""
    return (_unit(_cross(x, (0.0, 1.0, 0.0))) or _unit(_cross(x, (1.0, 0.0, 0.0))) or (0.0, 0.0, 1.0))


def _sin(x):
    """The format's own series for 0 to pi / 2: what the file was written with, to the last bit."""
    if x > QUARTER_PI:
        return _cos(HALF_PI - x)
    return x - (x * x * x) / 6.0 + (x * x * x * x * x) / 120.0 - (x * x * x * x * x * x * x) / 5040.0


def _cos(x):
    if x > QUARTER_PI:
        return _sin(HALF_PI - x)
    return 1.0 - (x * x) / 2.0 + (x * x * x * x) / 24.0 - (x * x * x * x * x * x) / 720.0


def _off_square(a, b):
    """How far the angle between two unit vectors is from a right angle (a straight line counting as furthest)."""
    a, b = _unit(a), _unit(b)
    d = _dot(a, b)
    if abs(d) > 1.0 - 1e-12:
        return HALF_PI
    return abs(math.acos(d) - HALF_PI)


def _apex(a, b, far, ix, iy, iz, tol):
    """The new corner on edge (a, b), with `far` the third corner of the triangle behind that edge."""
    o = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
    x = _unit(_sub(a, b))
    if x is None:
        raise PrcError("A PRC triangle has an edge of no length.")
    z = _unit(_cross(_sub(far, o), x))
    y = _unit(_cross(z, x)) if z is not None else None
    if y is None:
        z = _square_to(x)
        y = _unit(_cross(z, x)) or (0.0, 0.0, 0.0)
    if _dot(y, _sub(o, far)) > 0.0:
        y, z = _neg(y), _neg(z)
    fx, fy, fz = ix * tol, iy * tol, iz * tol
    return (o[0] + fx * x[0] + fy * y[0] + fz * z[0],
            o[1] + fx * x[1] + fy * y[1] + fz * z[1],
            o[2] + fx * x[2] + fy * y[2] + fz * z[2])


def _reference_bits(top):
    """Bits in a reference to one of a vertex's normals, numbered up to `top`."""
    bits, reach = 1, 1
    while top > reach:
        reach *= 2
        bits += 1
    return bits


class _Normals:
    """The stored normals: flags in one array, two angles each in another, read in step with the triangles."""

    def __init__(self, bits, angles, width, planar):
        self.bits, self.i = bits.tolist(), 0
        mask = (1 << width) - 1  # stored sign-extended, but they run from 0 to 2^width - 1
        self.angles, self.a = [(v & mask) * HALF_PI / mask for v in angles] if width else [], 0
        self.planar = planar
        self.vertices = {}  # vertex: [has several normals, its normals so far]
        self.faces = {}  # planar face: its normal

    def _bit(self):
        if self.i >= len(self.bits):
            raise PrcError("The PRC normals ended early.")
        self.i += 1
        return self.bits[self.i - 1]

    def _new(self, p0, p1, p2):
        flip, flip_x, flip_y = self._bit(), self._bit(), self._bit()
        if self.a + 1 >= len(self.angles):
            raise PrcError("The PRC normal angles ended early.")
        theta, phi = self.angles[self.a], self.angles[self.a + 1]
        self.a += 2
        v1, v2, v3 = _unit(_sub(p1, p0)), _unit(_sub(p2, p0)), _unit(_sub(p2, p1))
        if v1 is None or v2 is None or v3 is None:  # corners rounded onto each other: no frame, and no area to show
            return (0.0, 0.0, 1.0)
        d1, d2, d3 = _off_square(v1, v2), _off_square(v3, _neg(v1)), _off_square(_neg(v2), _neg(v3))
        if d1 < d2 and d1 < d3:  # the frame is on the triangle's squarest corner
            x, z = v1, _cross(v1, v2)
        elif d2 < d3:
            x, z = v3, _cross(_neg(v3), v1)
        else:
            x, z = _neg(v2), _cross(v2, v3)
        z = _unit(z) or _square_to(x)
        if flip:
            z = _neg(z)
        y = _unit(_cross(z, x)) or (0.0, 0.0, 0.0)
        if flip_x:
            x = _neg(x)
        if flip_y:
            y = _neg(y)
        f1, f2, f3 = _cos(theta) * _cos(phi), _sin(theta) * _cos(phi), _sin(phi)
        return _unit((f1 * x[0] + f2 * y[0] + f3 * z[0],
                      f1 * x[1] + f2 * y[1] + f3 * z[1],
                      f1 * x[2] + f2 * y[2] + f3 * z[2])) or (0.0, 0.0, 1.0)

    def _at_vertex(self, v, p0, p1, p2):
        rec = self.vertices.get(v)
        if rec is None:
            several = self._bit()
            n = self._new(p0, p1, p2)
            self.vertices[v] = [several, [n]]
            return n
        several, known = rec
        if not several:
            return known[0]
        if self._bit():
            top = len(known) - 1
            read = 0
            for k in range(_reference_bits(top)):
                if self._bit():
                    read |= 1 << k
            return known[top - read] if read <= top else known[0]
        n = self._new(p0, p1, p2)
        known.append(n)
        return n

    def of_triangle(self, face, a, b, c, p0, p1, p2):
        """The normals at corners a, b, c."""
        if self.planar[face]:
            n = self.faces.get(face)
            if n is None:
                n = self.faces[face] = self._at_vertex(a, p0, p1, p2)
            return n, n, n
        return self._at_vertex(a, p0, p1, p2), self._at_vertex(b, p0, p1, p2), self._at_vertex(c, p0, p1, p2)


def rebuild(tol, origin, ints, edges, tri_face, is_ref, refs, reversed_flags=None, normal_bits=None, angles=None,
            angle_width=0, planar=None):
    """(points (n, 3), triangles (m, 3), corner normals (m, 3, 3) or None, what was left unread) from one
    tessellation's arrays. Each triangle comes out running counter-clockwise seen from its normal's side."""
    normals = _Normals(normal_bits, angles or [], angle_width, planar) if normal_bits is not None else None
    is_ref = is_ref.tolist()
    n_ints, n_flags, n_refs = len(ints), len(is_ref), len(refs)
    pts, tris, corner_normals = [], [], []
    stack, closed = [], set()
    pi = ri = ki = 0  # next integer triple, reference, is-a-reference flag
    pushed = 1  # edges the last triangle pushed

    def corner(predict):
        """The next corner's index: an existing point, or a new one at predict(ix, iy, iz)."""
        nonlocal pi, ri, ki
        if ki >= n_flags:
            raise PrcError("The PRC point flags ended early.")
        flag = is_ref[ki]
        ki += 1
        if flag:
            if ri >= n_refs or not 0 <= refs[ri] < len(pts):
                raise PrcError("A PRC point refers to one that doesn't exist.")
            ri += 1
            return refs[ri - 1]
        if pi + 3 > n_ints:
            raise PrcError("The PRC points ended early.")
        pts.append(predict(ints[pi], ints[pi + 1], ints[pi + 2]))
        pi += 3
        return len(pts) - 1

    for t in range(len(tri_face)):
        gate = None
        if stack:
            gate = stack.pop()
            while pushed == 0 and gate is not None and (gate[0], gate[1]) in closed:
                gate = stack.pop() if stack else None
        if gate is None:  # a new start: three corners, each predicted from the ones before
            a = corner(lambda x, y, z: (origin[0] + x * tol, origin[1] + y * tol, origin[2] + z * tol))
            pa = pts[a]
            b = corner(lambda x, y, z: (pa[0] + x * tol, pa[1] + y * tol, pa[2] + z * tol))
            pb = pts[b]
            mid = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2, (pa[2] + pb[2]) / 2)
            c = corner(lambda x, y, z: (mid[0] + x * tol, mid[1] + y * tol, mid[2] + z * tol))
            if a > b:
                a, b = b, a
        else:
            a, b, far = gate
            pa, pb, pf = pts[a], pts[b], pts[far]
            c = corner(lambda x, y, z: _apex(pa, pb, pf, x, y, z, tol))
        p0, p1, p2 = pts[a], pts[b], pts[c]

        if normals is None:
            ns = None
            reverse = bool(reversed_flags[t])
        else:
            ns = normals.of_triangle(tri_face[t], a, b, c, p0, p1, p2)
            mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, (p0[2] + p1[2]) / 2)
            reverse = _dot(_cross(_sub(p2, mid), _sub(p1, p0)), ns[0]) < 0.0

        right, left = (b, c, a), (a, c, b)
        if reverse:
            right, left = left, right
        status = edges[t] & 3
        pushed = 0
        for has, (u, v, far) in ((status & 1, right), (status & 2, left)):
            low, high = (u, v) if u < v else (v, u)
            if has:
                stack.append((low, high, far))
                pushed += 1
            else:
                closed.add((low, high))
        tris.append((a, b, c) if reverse else (a, c, b))
        if ns is not None:
            corner_normals.append(ns if reverse else (ns[0], ns[2], ns[1]))
    unread = {"normal_bits": len(normals.bits) - normals.i if normals else 0,
              "angles": len(normals.angles) - normals.a if normals else 0,
              "points": n_ints - pi, "references": n_refs - ri, "flags": n_flags - ki}
    return (np.array(pts, np.float64).reshape(-1, 3), np.array(tris, np.int64).reshape(-1, 3),
            np.array(corner_normals, np.float64) if corner_normals else None, unread)
