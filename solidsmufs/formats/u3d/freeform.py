"""U3D's free-form surfaces (ECMA-363, clause 11): NURBS and Bezier surfaces, trimmed by loops in their parameter space."""

import numpy as np

from .. import surfaces
from .stream import U3dError

GUID = (0x095467DF, 0xEE24, 0x4C59, bytes((0x9A, 0xA5, 0x76, 0x8E, 0x39, 0xE2, 0x68, 0xDE)))
DOUBLE_KNOTS, DOUBLE_WEIGHTS, DOUBLE_TRIM_POINTS = 1, 2, 4
NON_RATIONAL, BEZIER, UNIFORM_U, UNIFORM_V, INDEPENDENT = 1, 2, 4, 8, 16
SEG_NON_RATIONAL, SEG_BEZIER = 1, 2
NATURAL_MIN_U, NATURAL_MAX_U, NATURAL_MIN_V, NATURAL_MAX_V, SEG_UNIFORM = 8, 16, 32, 64, 0x800
TRIM_SAMPLES_PER_SPAN = 12
MAX_POINTS = 16_000_000
MAX_LIST = 1 << 24


class Face:
    def __init__(self, surface, loops):
        self.surface, self.loops = surface, loops  # loops: of segments; a segment is points (n, 2), or a natural side's name


class Surface:
    def __init__(self, shading, knots_u, degree_u, knots_v, degree_v, control, weights):
        self.shading = shading
        self.knots_u, self.degree_u, self.knots_v, self.degree_v = knots_u, degree_u, knots_v, degree_v
        self.control, self.weights = control, weights
        self.faces = []

    def __call__(self, u, v):
        return surfaces.surface_points(self.knots_u, self.degree_u, self.knots_v, self.degree_v, self.control, u, v, self.weights)

    def domain(self):
        return (self.knots_u[self.degree_u], self.knots_u[-self.degree_u - 1],
                self.knots_v[self.degree_v], self.knots_v[-self.degree_v - 1])


class FreeForm:
    def __init__(self, name):
        self.name = name
        self.attributes = 0
        self.shadings = []  # (uses diffuse, uses specular, texture coordinate dimension per layer)
        self.surfaces = []
        self.face_count = 0  # the faces so far: an edge's second face is chosen from among them


def read_declaration(s):
    form = FreeForm(s.string())
    s.u32()  # its place in the chain
    form.attributes = s.u32()
    s.u32(), s.u32(), s.u32()  # how many surfaces, faces and edges it'll hold
    for _ in range(s.u32()):
        attributes = s.u32()
        dims = [s.u32() for _ in range(s.u32())]
        s.u32()
        form.shadings.append((bool(attributes & 1), bool(attributes & 2), dims))
    return form


def _value(s, double):
    return s.f64() if double else s.f32()


def _knot_array(s, form, uniform, suffix):
    """(unique values, multiplicities); a uniform array is just its two ends."""
    double = form.attributes & DOUBLE_KNOTS
    if uniform:
        return [_value(s, double), _value(s, double)], None
    count = s.cu32(f"cKnotCnt{suffix}")
    if count > MAX_LIST:
        raise U3dError("The U3D data is damaged: a knot array is too long.")
    values, multiplicity = [], []
    for _ in range(count):
        multiplicity.append(s.cu32(f"cKnotMult{suffix}"))
        values.append(_value(s, double))
    return values, multiplicity


def _full_knots(array, degree, control_count, bezier):
    """The whole knot vector, whichever way the file put it."""
    values, multiplicity = array
    if multiplicity is None:  # uniform: full ends, evenly spaced between
        inner = control_count - degree - 1
        if inner < 0:
            raise U3dError("The U3D data is damaged: too few control points for a surface's degree.")
        steps = np.linspace(values[0], values[1], inner + 2)
        return np.concatenate([np.full(degree, values[0]), steps, np.full(degree, values[1])])
    if bezier:  # pieces that each span `degree` control points
        repeat = [degree + 1] + [degree] * (len(values) - 2) + [degree + 1]
        knots = surfaces.expand_knots(values, repeat)
    else:
        knots = surfaces.expand_knots(values, multiplicity)
    if len(knots) != control_count + degree + 1:
        raise U3dError("The U3D data is damaged: a knot array doesn't suit its control points.")
    return knots


def _read_surface(s, form):
    attributes = s.u32()
    shading = s.cu32("cShading")
    if shading >= len(form.shadings):
        raise U3dError("The U3D data is damaged: a surface uses a shading the object doesn't have.")
    uses_diffuse, uses_specular, dims = form.shadings[shading]
    degree_u, degree_v = s.u32(), s.u32()
    array_u = _knot_array(s, form, attributes & UNIFORM_U, "U")
    array_v = _knot_array(s, form, attributes & UNIFORM_V, "V")
    count_u, count_v = s.u32(), s.u32()
    if count_u * count_v > MAX_POINTS or count_u <= degree_u or count_v <= degree_v:
        raise U3dError("The U3D data is damaged: a surface's control points don't suit its degree.")
    rational = not attributes & NON_RATIONAL
    control = np.zeros((count_u, count_v, 3))
    weights = np.ones((count_u, count_v)) if rational else None
    for i in range(count_u):
        for j in range(count_v):
            control[i, j] = s.floats(3)
            if uses_diffuse:
                s.floats(4)
            if uses_specular:
                s.floats(4)
            for dim in dims:
                s.floats(dim)
            if rational:
                weights[i, j] = _value(s, form.attributes & DOUBLE_WEIGHTS)
    if attributes & INDEPENDENT:  # other components may run on other knots: only the position's matter to the shape
        flags = s.cu32("cKnotAttr")
        array_u = _knot_array(s, form, flags & 1, "UPosition")
        array_v = _knot_array(s, form, flags & 2, "VPosition")
        if uses_diffuse:
            _knot_array(s, form, flags & 4, "UDiffuse"), _knot_array(s, form, flags & 8, "VDiffuse")
        if uses_specular:
            _knot_array(s, form, flags & 16, "USpecular"), _knot_array(s, form, flags & 32, "VSpecular")
        if dims:
            flags = s.cu32("cTCKnotAttr")
            _knot_array(s, form, flags & 1, "UTexCoord"), _knot_array(s, form, flags & 2, "VTexCoord")
    bezier = bool(attributes & BEZIER)
    return Surface(shading, _full_knots(array_u, degree_u, count_u, bezier), degree_u,
                   _full_knots(array_v, degree_v, count_v, bezier), degree_v, control, weights)


def _read_segment(s, form):
    attributes = s.cu32("cTCSAttr")
    for side in (NATURAL_MIN_U, NATURAL_MAX_U, NATURAL_MIN_V, NATURAL_MAX_V):
        if attributes & side:
            return side
    degree = s.cu32("cCDegrT")
    array = _knot_array(s, form, attributes & SEG_UNIFORM, "T")
    count = s.cu32("cCPCountT")
    if count > MAX_POINTS or count <= degree:
        raise U3dError("The U3D data is damaged: a trim curve's control points don't suit its degree.")
    double = form.attributes & DOUBLE_TRIM_POINTS
    rational = not attributes & SEG_NON_RATIONAL
    control, weights = np.zeros((count, 2)), np.ones(count) if rational else None
    for i in range(count):
        control[i] = _value(s, double), _value(s, double)
        if rational:
            weights[i] = _value(s, form.attributes & DOUBLE_WEIGHTS)
    knots = _full_knots(array, degree, count, bool(attributes & SEG_BEZIER))
    spans = np.unique(knots[degree:count + 1])
    if degree == 1:
        t = spans
    else:
        t = np.concatenate([np.linspace(a, b, TRIM_SAMPLES_PER_SPAN, endpoint=False) for a, b in zip(spans[:-1], spans[1:])] + [spans[-1:]])
    return surfaces.curve_points(knots, degree, control, t, weights)


def _read_edge(s, form):
    s.cu32("cLoopIndex"), s.cu32("cTCSIndex"), s.f32(), s.f32()
    s.ranged(form.face_count, "cFaceZero")
    s.cu32("cLoopIndex"), s.cu32("cTCSIndex"), s.f32(), s.f32()


def read_continuation(forms, s):
    name = s.string()
    form = forms.get(name)
    if form is None:
        raise U3dError(f"The U3D data continues an object it hasn't declared ({name}).")
    s.u32()  # its place in the chain
    start, end = s.u32(), s.u32()
    if end < start or end - start > MAX_LIST:
        raise U3dError("The U3D data is damaged: a free-form block's range is wrong.")
    for _ in range(end - start):
        surface = _read_surface(s, form)
        form.surfaces.append(surface)
        for _ in range(s.u32()):
            loops = [[_read_segment(s, form) for _ in range(s.cu32("cTCSCount"))] for _ in range(s.cu32("cTCLCount"))]
            surface.faces.append(Face(surface, loops))
            for _ in range(s.u32()):
                _read_edge(s, form)
            form.face_count += 1


# ---------------------------------------------------------------------------------------------- to triangles
def _natural_side(side, domain):
    u0, u1, v0, v1 = domain
    t = np.linspace(0.0, 1.0, 9)
    if side == NATURAL_MIN_U:
        return np.column_stack([np.full(9, u0), v0 + (v1 - v0) * t])
    if side == NATURAL_MAX_U:
        return np.column_stack([np.full(9, u1), v0 + (v1 - v0) * t])
    if side == NATURAL_MIN_V:
        return np.column_stack([u0 + (u1 - u0) * t, np.full(9, v0)])
    return np.column_stack([u0 + (u1 - u0) * t, np.full(9, v1)])


def loop_points(segments, domain):
    """A loop's points in order. A natural side doesn't say which way it runs: it follows on from what came before."""
    runs = [_natural_side(seg, domain) if isinstance(seg, int) else seg for seg in segments]
    if len(runs) > 1:
        first = runs[0]
        gap_start = min(np.linalg.norm(first[0] - runs[1][0]), np.linalg.norm(first[0] - runs[1][-1]))
        gap_end = min(np.linalg.norm(first[-1] - runs[1][0]), np.linalg.norm(first[-1] - runs[1][-1]))
        if gap_start < gap_end:
            runs[0] = first[::-1]
    out = []
    for run in runs:
        if out and np.linalg.norm(out[-1][-1] - run[0]) > np.linalg.norm(out[-1][-1] - run[-1]):
            run = run[::-1]
        out.append(run[:-1])
    return np.vstack(out) if out else np.zeros((0, 2))


def tessellate(form, shading=None):
    """(points, triangles, face of each triangle) of a free-form object, or of the part with one shading."""
    control = [c.control.reshape(-1, 3) for c in form.surfaces if shading is None or c.shading == shading]
    if not control:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros(0, np.int64)
    every = np.vstack(control)
    tolerance = max(float(np.linalg.norm(np.ptp(every, axis=0))) * 2e-4, 1e-12)
    points, triangles, faces, base, number = [], [], [], 0, 0
    for surface in form.surfaces:
        if shading is not None and surface.shading != shading:
            continue
        domain = surface.domain()
        for face in surface.faces or [Face(surface, [])]:
            loops = [loop_points(segments, domain) for segments in face.loops]
            if not loops:  # nothing to trim it by: the whole of its parameter space
                loops = [surfaces.box_loop(*domain)]
            p, t = surfaces.mesh_surface(surface, loops, tolerance)
            if len(t):
                points.append(p)
                triangles.append(t + base)
                faces.append(np.full(len(t), number, np.int64))
                base += len(p)
                number += 1
    if not points:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros(0, np.int64)
    return np.vstack(points), np.vstack(triangles), np.concatenate(faces)
