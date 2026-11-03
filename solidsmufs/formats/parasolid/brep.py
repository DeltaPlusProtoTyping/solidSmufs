"""Parasolid topology → STEP B-rep.

BODY → REGION ('S' solid / 'V' void) → SHELL → FACE → LOOP → HALFEDGE → EDGE / VERTEX. Facts this relies on
(all checked on real files):
* A face's back shell (FACE.shell) is on the solid side, its front shell on the void side; its normal is the
  surface's natural normal times the surface node's sense times the face's sense, and points out of the solid.
  Loops run with the face on their left, seen from that normal (as in STEP).
* A halfedge runs from its mate's vertex to its own, in its curve's direction times the curve's sense times
  its own sense; EDGE.halfedge is the '+' one, so the edge runs like it. A TRIMMED_CURVE runs from parm_1 to
  parm_2 in the direction of whatever uses it (an edge, or a halfedge for SP-curves of edges without a curve).

Edges on lines, circles, ellipses and B-curves (trimmed or not) are written exactly, as are SP-curves that
are iso-parameter lines of their surface (or lie on a plane). Other SP-curves are fitted with cubic Hermite
B-splines (FIT_TOL), intersections with C2 splines through their chart points, refined onto both surfaces;
an edge with no usable curve is rebuilt where its two faces' surfaces meet. Polylines are the last resort.
"""

from collections import Counter

import numpy as np

from . import appearance
from . import nurbs as N
from .blend import Blend, on_intersection
from .geom import (BSpline, BSurface, ChartCurve, Circle, Ellipse, Factory, GeomError, Line, Offset, SPCurve,
                   Spun, Swept, TWO_PI)

FIT_TOL = 1e-7  # m: how far an approximated edge may stray from the true curve (0.1 µm)
POLY_TOL = 1e-6  # m: for polylines, the last resort


class BodyWriter:
    def __init__(self, model, w):
        self.m, self.w = model, w
        self.F = Factory(model)
        self.verts, self.edges, self.surfs = {}, {}, {}
        self.edge_pts = {}  # edge index -> points along it (start to end)
        self.n_exact = self.n_fit = self.n_poly = 0
        self.notes = Counter()  # warnings, by message
        self.n_faces = 0
        # colours from the part's Parasolid attributes, written as STEP styles: [(item ref, rgb, translucency)]
        self.body_rgb, self.face_rgb, self.body_clear = appearance.colours(model)
        self.styles = []
        self.body_colours = []  # one per written solid / sheet, in order: (r, g, b) or None
        self.body_clears = []  # and its translucency (0 opaque .. 1 clear)

    # ------------------------------------------------------------------ bodies
    def bodies(self):
        """[(kind, step ref)] for the model's bodies: ('solid', ...) or ('sheet', ...); solids first."""
        m = self.m
        body_shells = {}
        for sh in m.of_type("SHELL"):
            body_shells.setdefault(sh["body"], []).append(sh)
        region_type = {r.idx: r["type"] for r in m.of_type("REGION")}
        faces_back, faces_front = {}, {}
        for f in m.of_type("FACE"):
            faces_back.setdefault(f["shell"], []).append(f)
            if f["front_shell"]:
                faces_front.setdefault(f["front_shell"], []).append(f)
        solids, sheets = [], []
        for body in m.of_type("BODY"):
            shells = body_shells.get(body.idx, [])
            by_region = {}
            for sh in shells:
                if region_type.get(sh["region"]) == "S":
                    by_region.setdefault(sh["region"], []).append(sh)
            if by_region:
                for _reg, shs in sorted(by_region.items()):
                    written = self._solid(shs, faces_back, faces_front, region_type)
                    solids += written
                    for _kind, ref in written:
                        self._style_body(ref, body)
            else:
                faces = [f for sh in shells for f in faces_back.get(sh.idx, [])]
                if faces:
                    sheets.append((body, faces))
        out = list(solids)
        if not solids:  # a model of surfaces only
            for body, faces in sheets:
                ref = self._sheet(faces)
                if ref:
                    out.append(("sheet", ref))
                    self._style_body(ref, body)
        return out

    def _style_body(self, ref, body):
        rgb = self.body_rgb.get(body.idx)
        self.body_colours.append(rgb)
        self.body_clears.append(self.body_clear.get(body.idx, 0.0))
        if rgb is not None:
            self.styles.append((ref, rgb, self.body_clear.get(body.idx, 0.0)))

    def _solid(self, shells, faces_back, faces_front, region_type):
        """[(kind, ref)] for a solid region's shells: each shell not inside another is a solid of its own
        (regions can hold several lumps); the shells inside it are its cavities."""
        written = []  # (face refs, all faces ok, bounding box, faces)
        for sh in shells:
            fl = [(f, False) for f in faces_back.get(sh.idx, [])]
            fl += [(f, True) for f in faces_front.get(sh.idx, []) if region_type.get(self._region(f["shell"])) != "S"]
            if not fl:
                continue
            refs, ok = [], True
            for f, rev in fl:
                r = self.face(f, rev)
                if r is None:
                    ok = False
                else:
                    refs.append(r)
            if not refs:
                continue
            written.append((refs, ok, self._bbox([f for f, _ in fl]), fl))
        if not written:
            return []
        if not all(ok for _r, ok, _b, _f in written):
            refs = [r for rr, _ok, _b, _f in written for r in rr]
            shell = self.w.add(f"OPEN_SHELL('',({','.join(refs)}))")
            self.notes["a solid with faces that couldn't be converted was written as surfaces"] += 1
            return [("sheet", self.w.add(f"SHELL_BASED_SURFACE_MODEL('',({shell}))"))]
        written.sort(key=lambda x: -float(np.linalg.norm(x[2][1] - x[2][0])))
        groups = []  # [outer, [cavities]]
        for item in written:
            lo, hi = item[2]
            for g in groups:
                glo, ghi = g[0][2]
                tol = 1e-6 + 1e-6 * float(np.linalg.norm(ghi - glo))
                if np.all(lo >= glo - tol) and np.all(hi <= ghi + tol):
                    g[1].append(item)
                    break
            else:
                groups.append([item, []])
        out = []
        for outer_item, cavities in groups:
            outer = self.w.add(f"CLOSED_SHELL('',({','.join(outer_item[0])}))")
            if not cavities:
                out.append(("solid", self.w.add(f"MANIFOLD_SOLID_BREP('',{outer})")))
                continue
            voids = []
            for _refs, _ok, _b, fl in cavities:  # cavities: faces again, turned inside out for STEP
                vrefs = [self.face(f, not rev, cache=False) for f, rev in fl]
                vs = self.w.add(f"CLOSED_SHELL('',({','.join(r for r in vrefs if r)}))")
                voids.append(self.w.add(f"ORIENTED_CLOSED_SHELL('',*,{vs},.F.)"))
            out.append(("solid", self.w.add(f"BREP_WITH_VOIDS('',{outer},({','.join(voids)}))")))
        return out

    def _region(self, shell_idx):
        sh = self.m[shell_idx]
        return sh["region"] if sh else 0

    def _sheet(self, faces):
        refs = [r for r in (self.face(f, False) for f in faces) if r]
        if not refs:
            return None
        shell = self.w.add(f"OPEN_SHELL('',({','.join(refs)}))")
        return self.w.add(f"SHELL_BASED_SURFACE_MODEL('',({shell}))")

    def _bbox(self, faces):
        """(min, max) corners of the faces' edges (sampled along them)."""
        pts = []
        for f in faces:
            for lp in self._loops(f):
                for h in self._halfedges(lp):
                    if h["edge"] in self.edge_pts:
                        pts.append(np.asarray(self.edge_pts[h["edge"]], float))
                    p = self._vpoint(h["vertex"])
                    if p is not None:
                        pts.append(p[None])
        if not pts:
            return np.zeros(3), np.zeros(3)
        pts = np.vstack(pts)
        return pts.min(axis=0), pts.max(axis=0)

    # ------------------------------------------------------------------ faces
    def _loops(self, f):
        out, lp, seen = [], f["loop"], set()
        while lp and lp not in seen:
            seen.add(lp)
            node = self.m[lp]
            if node is None:
                break
            out.append(node)
            lp = node["next"]
        return out

    def _halfedges(self, lp):
        out, h, seen = [], lp["halfedge"], set()
        while h and h not in seen:
            seen.add(h)
            node = self.m[h]
            if node is None:
                break
            out.append(node)
            h = node["forward"]
        return out

    def face(self, f, reverse, cache=True):
        """ADVANCED_FACE for a face (reverse: its normal points into the solid), or None if it can't be written."""
        snode = self.m[f["surface"]]
        if snode is None:
            return None
        bounds, edges_used = [], []
        bound_ok = not reverse
        for lp in self._loops(f):
            oes = []
            for h in self._halfedges(lp):
                if not h["edge"]:
                    continue  # a vertex loop (the tip of a cone): STEP readers rebuild those
                eref = self.edge(h["edge"])
                if eref is None:
                    return None
                edges_used.append(h["edge"])
                oes.append(self.w.add(f"ORIENTED_EDGE('',*,*,{eref},{'.T.' if h['sense'] == '+' else '.F.'})"))
            if oes:
                loop = self.w.add(f"EDGE_LOOP('',({','.join(oes)}))")
                bounds.append(self.w.add(f"FACE_BOUND('',{loop},{'.T.' if bound_ok else '.F.'})"))
        if not bounds:
            return None
        s = self.surface(f["surface"], f, edges_used)
        if s is None:
            return None
        sref, flip = s
        same = ((f["sense"] == "+") == (snode["sense"] == "+")) != flip
        if reverse:
            same = not same
        if cache:
            self.n_faces += 1
        ref = self.w.add(f"ADVANCED_FACE('',({','.join(bounds)}),{sref},{'.T.' if same else '.F.'})")
        if f.idx in self.face_rgb:
            self.styles.append((ref, self.face_rgb[f.idx], 0.0))
        return ref

    def surface(self, idx, face=None, edges=()):
        """(STEP surface, flip) for a face's surface; blends are fitted to the part a face uses."""
        node = self.m[idx]
        per_face = node is not None and node.type in ("BLENDED_EDGE", "OFFSET_SURF") and face is not None
        key = (idx, face.idx) if per_face else idx
        if key in self.surfs:
            return self.surfs[key]
        out = None
        kind = node.type.lower().replace("_", " ") if node else "missing"
        try:
            S = self.F.surface(idx)
            if isinstance(S, Blend):
                out = self._blend(S, edges)
            elif isinstance(S, Offset) and isinstance(S.basis, (BSurface, Swept, Spun, Offset)):
                # OpenCASCADE can hang on offsets of free-form surfaces (singular where the offset exceeds a
                # radius of curvature): the part the face uses, fitted
                out = self._offset_fit(S, edges)
            else:
                out = S.step(self.w)
        except GeomError as e:
            self.notes[f"faces skipped ({e})"] += 1
        except (ValueError, ArithmeticError, np.linalg.LinAlgError) as e:
            self.notes[f"faces skipped ({kind} surface: {e})"] += 1
        self.surfs[key] = out
        return out

    def _offset_fit(self, S, edges, tol=1e-6):
        """A B-spline fitted to an offset surface over the parameters the face's edges cover (the basis's
        parameters, so the natural normal is the basis's, as for the offset)."""
        pts = [self.edge_pts[e] for e in edges if e in self.edge_pts]
        if not pts:
            raise GeomError("offset face without edges")
        uv, _ = S.basis.closest(np.vstack(pts))
        box = S.basis.uv_box()
        u0, u1 = float(uv[:, 0].min()), float(uv[:, 0].max())
        v0, v1 = float(uv[:, 1].min()), float(uv[:, 1].max())
        mu, mv = 0.03 * (u1 - u0) + 1e-9, 0.03 * (v1 - v0) + 1e-9
        u0, u1, v0, v1 = u0 - mu, u1 + mu, v0 - mv, v1 + mv
        if box is not None:
            u0, u1 = max(u0, box[0]), min(u1, box[1])
            v0, v1 = max(v0, box[2]), min(v1, box[3])
        if u1 - u0 <= 1e-12 or v1 - v0 <= 1e-12:
            raise GeomError("degenerate offset face")

        def grid(us, vs):
            uu, vv = np.repeat(us, len(vs)), np.tile(vs, len(us))
            return S.eval(uu, vv).reshape(len(us), len(vs), 3)

        r = N.fit_surface_grid(grid, u0, u1, v0, v1, tol, max_n=49)
        if r is None:
            raise GeomError("offset surface fit failed")
        du, dv, U, V, P, _err = r
        self.notes["offset surfaces approximated as B-splines"] += 1
        return self.w.bspline_surface(du, dv, U, V, P), False

    def _blend(self, B, edges):
        """A blend face's surface: a B-spline fitted over the part of the blend its edges bound. Its flip says
        whether its natural normal (d/dt x d/db) points towards the ball centre (Parasolid's blend normal
        points away from it)."""
        pts = [self.edge_pts[e] for e in edges if e in self.edge_pts]
        if not pts:
            raise GeomError("blend face without edges")
        samples = np.vstack(pts)
        du, dv, U, V, P, _err = B.fit(samples)
        nu, nv = P.shape[:2]
        # the fitted surface's natural normal at its middle vs. the direction away from the ball centre
        uc, vc = (U[du] + U[nu]) / 2, (V[dv] + V[nv]) / 2
        h = 1e-6 * max(U[nu] - U[du], V[nv] - V[dv])
        Pc = N.eval_surface(du, dv, U, V, P, [uc, uc + h, uc], [vc, vc, vc + h])
        n_fit = np.cross(Pc[1] - Pc[0], Pc[2] - Pc[0])
        away = B.normal_at(Pc[:1])[0]
        return self.w.bspline_surface(du, dv, U, V, P), bool(np.dot(n_fit, away) < 0)

    # ------------------------------------------------------------------ vertices and edges
    def _vpoint(self, vidx):
        v = self.m[vidx]
        if v is None:
            return None
        p = self.m[v["point"]]
        return np.asarray(p["pvec"], float) if p is not None else None

    def vertex(self, vidx):
        if vidx not in self.verts:
            self.verts[vidx] = self.w.add(f"VERTEX_POINT('',{self.w.point(self._vpoint(vidx))})")
        return self.verts[vidx]

    def edge(self, eidx):
        if eidx in self.edges:
            return self.edges[eidx]
        ref = None
        try:
            ref = self._edge(eidx)
        except (GeomError, ValueError, ArithmeticError, np.linalg.LinAlgError) as e:
            self.notes[f"edges skipped ({e})"] += 1
        self.edges[eidx] = ref
        return ref

    def _edge(self, eidx):
        m = self.m
        e = m[eidx]
        hp = m[e["halfedge"]]
        if hp is None:
            raise GeomError("edge without halfedges")
        if hp["sense"] != "+":  # EDGE.halfedge is always the '+' one in practice; be safe
            mate = m[hp["other"]]
            if mate is not None and mate["sense"] == "+":
                hp = mate
        vs_idx = self._start_vertex(hp)
        ve_idx = hp["vertex"]
        ps, pe = self._vpoint(vs_idx), self._vpoint(ve_idx)
        try:
            piece = self._edge_curve(e, hp, ps, pe)
        except GeomError as err:
            try:
                piece = self._between_faces(hp, ps, pe, err)
            except (GeomError, ValueError, np.linalg.LinAlgError):
                if ps is None or pe is None or float(np.linalg.norm(pe - ps)) < 1e-9:
                    raise err from None
                # last resort: straight from vertex to vertex (keeps the shell closed)
                self.notes["edges couldn't be computed and were drawn straight between their vertices"] += 1
                piece = ("poly", [ps, pe])
        kind, data = piece
        if kind == "poly":
            self.edge_pts[eidx] = np.array(data)
        else:
            self.edge_pts[eidx] = data[3]
            data = data[:3]
        w = self.w
        if kind == "exact":
            cref, same, p_from = data
            self.n_exact += 1
        elif kind == "fit":
            cref, same, p_from = data
            self.n_fit += 1
        else:
            pts = data
            if ps is not None:
                pts[0], pts[-1] = ps, pe
            cref, same, p_from = w.polyline(pts), True, pts[0]
            self.n_poly += 1
        if ve_idx and vs_idx:
            v0, v1 = self.vertex(vs_idx), self.vertex(ve_idx)
        else:  # a ring edge: one vertex of our own, where the curve starts
            v0 = v1 = w.add(f"VERTEX_POINT('',{w.point(p_from)})")
        return w.add(f"EDGE_CURVE('',{v0},{v1},{cref},{'.T.' if same else '.F.'})")

    def _start_vertex(self, hp):
        """The vertex a halfedge starts at: where the one before it in its loop ends. Some files leave the
        backward link out (seen in sheet bodies); then the mate halfedge, which runs the other way and so
        ends there, or the loop walked forwards to whichever halfedge leads into this one."""
        m = self.m
        back = m[hp["backward"]]
        if back is not None and back["vertex"]:
            return back["vertex"]
        mate = m[hp["other"]]
        if mate is not None and mate.idx != hp.idx and mate["vertex"]:
            return mate["vertex"]
        lp = m[hp["loop"]]
        if lp is not None:
            for h in self._halfedges(lp):
                if h["forward"] == hp.idx and h["vertex"]:
                    return h["vertex"]
        return 0

    def _edge_curve(self, e, hp, ps, pe):
        """('exact' | 'fit', (STEP curve, same sense, start point)) or ('poly', points)."""
        m = self.m
        c = m[e["curve"]]
        if c is not None:
            if c.type == "TRIMMED_CURVE":
                return self._piece(self.F.curve(c["basis_curve"]), m[c["basis_curve"]], ps, pe,
                                   trim=(c["parm_1"], c["parm_2"]))
            return self._piece(self.F.curve(e["curve"]), c, ps, pe, sense=c["sense"] == "+")
        # no curve of its own: the SP-curves of its halfedges (each runs like its halfedge)
        err = None
        for h, rev in ((hp, False), (m[hp["other"]], True)):
            if h is None:
                continue
            hc = m[h["curve"]]
            if hc is None:
                continue
            a, b = (pe, ps) if rev else (ps, pe)
            try:
                if hc.type == "TRIMMED_CURVE":
                    kind, data = self._piece(self.F.curve(hc["basis_curve"]), m[hc["basis_curve"]], a, b,
                                             trim=(hc["parm_1"], hc["parm_2"]))
                else:
                    kind, data = self._piece(self.F.curve(h["curve"]), hc, a, b, sense=hc["sense"] == "+")
            except GeomError as e:  # e.g. an SP-curve on a surface we can't evaluate: try the other side
                err = e
                continue
            if rev:
                if kind == "poly":
                    data = data[::-1]
                else:
                    cref, same, _p, smp = data
                    data = (cref, not same, ps if ps is not None else smp[-1], smp[::-1])
            return kind, data
        raise err or GeomError("edge with no curve")

    def _piece(self, curve, node, ps, pe, trim=None, sense=True):
        """The part of curve from ps to pe (trim: its parameters there; otherwise found by projection, the
        direction being the curve's own if sense else reversed)."""
        w = self.w
        closed = ps is None or pe is None or float(np.linalg.norm(ps - pe)) < 1e-9
        if trim is not None:
            t0, t1 = trim
        else:
            t0, t1 = self._params(curve, ps, pe, closed, sense)
        if isinstance(curve, (Line, Circle, Ellipse)):
            p_from = ps if ps is not None else curve.point(t0)
            return "exact", (curve.step(w), t1 > t0, p_from, curve.eval(np.linspace(t0, t1, 9)))
        if isinstance(curve, BSpline):
            lo, hi = min(t0, t1), max(t0, t1)
            if hi - lo <= 1e-14:
                raise GeomError("degenerate spline edge")
            p_from = ps if ps is not None else curve.point(t0)
            return "exact", (curve.step(w, lo, hi), t1 > t0, p_from, curve.eval(np.linspace(t0, t1, 9)))
        if isinstance(curve, SPCurve):
            ex = curve.exact_piece(t0, t1)
            if ex is not None:
                c2, a, b = ex
                return self._piece(c2, None, ps, pe, trim=(a, b))
            return self._fit(curve, t0, t1, ps, pe)
        if isinstance(curve, ChartCurve):
            return self._chart(curve, node, ps, pe, trim, sense)
        return self._fit(curve, t0, t1, ps, pe)

    def _between_faces(self, hp, ps, pe, err):
        """An edge rebuilt as the meeting curve of its two faces' surfaces, from vertex to vertex."""
        m = self.m
        hm = m[hp["other"]]
        if hm is None or ps is None or pe is None or float(np.linalg.norm(pe - ps)) < 1e-9:
            raise err
        fa, fb = m[m[hp["loop"]]["face"]], m[m[hm["loop"]]["face"]]
        A, B = self.F.surface(fa["surface"]), self.F.surface(fb["surface"])
        X = ps + (pe - ps) * np.linspace(0.0, 1.0, 9)[:, None]
        X[1:-1] = on_intersection(A, B, X[1:-1])
        d = (X - ps) @ (pe - ps)
        if np.any(np.diff(d) <= 0):  # not a simple arc between the vertices
            raise err
        pts = self._refine_on((A, B), X)
        deg, U, Pc = N.interp_points(pts)
        self.notes["edges rebuilt from their faces' surfaces"] += 1
        return "fit", (self.w.bspline_curve(deg, U, Pc), True, pts[0], pts)

    def _params(self, curve, ps, pe, closed, sense):
        if isinstance(curve, ChartCurve):
            return 0.0, 0.0
        if closed:
            if curve.period:
                t0 = curve.project(ps) if ps is not None else 0.0
                return (t0, t0 + TWO_PI) if sense else (t0, t0 - TWO_PI)
            lo, hi = curve.domain()
            return (lo, hi) if sense else (hi, lo)
        t0, t1 = curve.project(ps), curve.project(pe)
        if curve.period:
            if sense:
                while t1 <= t0 + 1e-12:
                    t1 += TWO_PI
                while t1 - t0 > TWO_PI + 1e-12:
                    t1 -= TWO_PI
            else:
                while t1 >= t0 - 1e-12:
                    t1 -= TWO_PI
                while t0 - t1 > TWO_PI + 1e-12:
                    t1 += TWO_PI
        return t0, t1

    def _fit(self, curve, t0, t1, ps, pe):
        """A cubic B-spline through the curve from t0 to t1, its ends on the vertices."""
        r = N.fit_curve(curve.eval, t0, t1, FIT_TOL, breaks=curve.breaks())
        if r is None:
            return "poly", self._trace(curve.eval, t0, t1)
        deg, U, P, _err = r
        if ps is not None:  # land exactly on the vertices
            P = P.copy()
            P[0], P[-1] = ps, pe
        ref = self.w.bspline_curve(deg, U, P)
        return "fit", (ref, True, P[0], N.eval_curve(deg, U, P, np.linspace(U[0], U[-1], 9)))

    def _chart(self, curve, node, ps, pe, trim, sense):
        """An intersection: a cubic through its chart points between the vertices."""
        fwd = sense if trim is None else trim[1] >= trim[0]
        P, S = curve.pts, curve.s
        L = float(S[-1])
        ring = float(np.linalg.norm(P[0] - P[-1])) < 1e-8
        if ps is None or pe is None:  # a ring edge: all the way round from the chart's start
            if not ring:
                raise GeomError("ring edge on an open intersection")
            ps = pe = P[0]
        s0, s1 = curve.project(ps), curve.project(pe)
        closed = float(np.linalg.norm(ps - pe)) < 1e-9
        if closed and not ring:
            raise GeomError("closed edge on an open intersection")
        if not ring or (not closed and (s1 > s0) == fwd):
            mid, _ = curve.points_between(s0, s1)
        else:  # across the seam of a closed chart (or all the way round)
            if fwd:
                if closed or s1 <= s0:
                    a, _ = curve.points_between(s0, L)
                    b, _ = curve.points_between(0.0, s1 if not closed else s0)
                    mid = np.vstack([a, P[-1:], b])
                else:
                    mid, _ = curve.points_between(s0, s1)
            else:
                if closed or s1 >= s0:
                    a, _ = curve.points_between(s0, 0.0)
                    b, _ = curve.points_between(L, s1 if not closed else s0)
                    mid = np.vstack([a, P[:1], b])
                else:
                    mid, _ = curve.points_between(s0, s1)
        pts = np.vstack([ps, mid, pe])
        keep = [0]
        for i in range(1, len(pts)):  # drop points (nearly) on top of the previous one
            if float(np.linalg.norm(pts[i] - pts[keep[-1]])) > 1e-8:
                keep.append(i)
        if keep[-1] != len(pts) - 1:
            keep[-1] = len(pts) - 1  # end exactly on the end vertex
        pts = pts[keep]
        if len(pts) < 2 or float(np.linalg.norm(pts[-1] - pts[0])) < 1e-10 and len(pts) < 4:
            raise GeomError("degenerate intersection edge")
        surfs = None
        if node is not None and node.type == "INTERSECTION":
            try:
                surfs = tuple(self.F.surface(i) for i in node["surface"])
            except GeomError:
                surfs = None
        if surfs:
            pts = self._refine_on(surfs, pts)
        if len(pts) == 2:
            return "fit", (self.w.bspline_curve(1, [0, 0, 1, 1], pts), True, pts[0], pts)
        deg, U, Pc = N.interp_points(pts)
        return "fit", (self.w.bspline_curve(deg, U, Pc), True, pts[0], pts)

    def _refine_on(self, surfs, pts, rounds=5):
        """Points along an intersection of two surfaces, made dense enough that a C2 spline through them stays
        within FIT_TOL of the true curve (new points: spline midpoints moved onto both surfaces)."""
        pts = np.asarray(pts, float)
        for _ in range(rounds):
            if len(pts) < 2:
                break
            t = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
            if t[-1] <= 0:
                break
            t /= t[-1]
            if len(pts) >= 3:
                deg, U, Pc = N.interp_points(pts)
                M = N.eval_curve(deg, U, Pc, (t[:-1] + t[1:]) / 2)
            else:
                M = (pts[:-1] + pts[1:]) / 2
            M2 = on_intersection(*surfs, M)
            err = np.linalg.norm(M2 - M, axis=1)
            seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
            if np.any(err > 0.25 * seg + 1e-7):  # the projections went somewhere else: keep what we have
                break
            bad = err > FIT_TOL * 0.5
            if not bad.any():
                break
            out = [pts[0]]
            for i in range(len(M2)):
                if bad[i]:
                    out.append(M2[i])
                out.append(pts[i + 1])
            pts = np.array(out)
            if len(pts) > 4000:
                break
        return pts

    def _trace(self, f, t0, t1):
        """Points along f from t0 to t1, each chord within POLY_TOL of the curve."""
        ts = list(np.linspace(t0, t1, 9))
        for _ in range(12):
            arr = np.array(ts)
            mids = (arr[:-1] + arr[1:]) / 2
            p = f(arr)
            pm = f(mids)
            dev = np.linalg.norm(pm - (p[:-1] + p[1:]) / 2, axis=1)
            bad = dev > POLY_TOL
            if not bad.any() or len(ts) > 5000:
                break
            ts = sorted(ts + list(mids[bad]), reverse=t1 < t0)
        return list(f(np.array(ts)))
