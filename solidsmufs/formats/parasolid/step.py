"""A small STEP (ISO 10303-21, AP214) writer. Geometry comes in metres and is written in millimetres."""

import os

import numpy as np

MM = 1000.0


def num(x):
    s = repr(float(x))
    if "e" in s:
        m, e = s.split("e")
        if "." not in m:
            m += "."
        return m + "E" + e
    if "." not in s:
        s += "."
    return s


def _unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


class Step:
    def __init__(self):
        self.lines = []
        self.n = 0

    def add(self, text):
        self.n += 1
        self.lines.append(f"#{self.n}={text};")
        return f"#{self.n}"

    # ---- basic geometry (metres in)
    def point(self, p):
        return self.add(f"CARTESIAN_POINT('',({num(p[0] * MM)},{num(p[1] * MM)},{num(p[2] * MM)}))")

    def point2(self, p):
        return self.add(f"CARTESIAN_POINT('',({num(p[0])},{num(p[1])}))")

    def direction(self, v):
        u = _unit(v)
        return self.add(f"DIRECTION('',({num(u[0])},{num(u[1])},{num(u[2])}))")

    def axis2(self, origin, axis, ref):
        a = _unit(axis)
        r = np.asarray(ref, float) - np.dot(ref, a) * a
        if np.linalg.norm(r) < 1e-12:
            r = np.cross(a, (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0))
        return self.add(f"AXIS2_PLACEMENT_3D('',{self.point(origin)},{self.direction(a)},{self.direction(r)})")

    def axis1(self, origin, axis):
        return self.add(f"AXIS1_PLACEMENT('',{self.point(origin)},{self.direction(axis)})")

    def length(self, x):
        return num(x * MM)

    # ---- curves
    def line(self, p, d):
        vec = self.add(f"VECTOR('',{self.direction(d)},{num(MM)})")
        return self.add(f"LINE('',{self.point(p)},{vec})")

    def circle(self, c, n, x, r):
        return self.add(f"CIRCLE('',{self.axis2(c, n, x)},{self.length(r)})")

    def ellipse(self, c, n, x, r1, r2):
        return self.add(f"ELLIPSE('',{self.axis2(c, n, x)},{self.length(r1)},{self.length(r2)})")

    def polyline(self, pts):
        return self.add("POLYLINE('',(" + ",".join(self.point(p) for p in pts) + "))")

    def bspline_curve(self, deg, U, P, rational=False):
        """P: (n, 3) cartesian or (n, 4) homogeneous when rational (metres)."""
        P = np.asarray(P, float)
        ks, ms = _knots(U)
        if rational:
            w = P[:, 3]
            cart = P[:, :3] / w[:, None]
        else:
            cart = P[:, :3]
        cps = "(" + ",".join(self.point(p) for p in cart) + ")"
        kn = f"({','.join(map(str, ms))}),({','.join(num(k) for k in ks)}),.UNSPECIFIED."
        if rational and not np.allclose(w, w[0], rtol=1e-14, atol=0):
            return self.add(f"(BOUNDED_CURVE()B_SPLINE_CURVE({deg},{cps},.UNSPECIFIED.,.F.,.F.)"
                            f"B_SPLINE_CURVE_WITH_KNOTS({kn})CURVE()GEOMETRIC_REPRESENTATION_ITEM()"
                            f"RATIONAL_B_SPLINE_CURVE(({','.join(num(x) for x in w)}))REPRESENTATION_ITEM(''))")
        return self.add(f"B_SPLINE_CURVE_WITH_KNOTS('',{deg},{cps},.UNSPECIFIED.,.F.,.F.,{kn})")

    # ---- surfaces
    def bspline_surface(self, du, dv, U, V, P, rational=False):
        """P: (nu, nv, 3) or homogeneous (nu, nv, 4) (metres)."""
        P = np.asarray(P, float)
        if rational:
            w = P[..., 3]
            cart = P[..., :3] / w[..., None]
        else:
            cart = P[..., :3]
        rows = ["(" + ",".join(self.point(p) for p in row) + ")" for row in cart]
        uk, um = _knots(U)
        vk, vm = _knots(V)
        kn = (f"({','.join(map(str, um))}),({','.join(map(str, vm))}),"
              f"({','.join(num(k) for k in uk)}),({','.join(num(k) for k in vk)}),.UNSPECIFIED.")
        cps = "(" + ",".join(rows) + ")"
        if rational and not np.allclose(w, w.flat[0], rtol=1e-14, atol=0):
            wts = "(" + ",".join("(" + ",".join(num(x) for x in row) + ")" for row in w) + ")"
            return self.add(f"(BOUNDED_SURFACE()B_SPLINE_SURFACE({du},{dv},{cps},.UNSPECIFIED.,.F.,.F.,.F.)"
                            f"B_SPLINE_SURFACE_WITH_KNOTS({kn})GEOMETRIC_REPRESENTATION_ITEM()"
                            f"RATIONAL_B_SPLINE_SURFACE({wts})REPRESENTATION_ITEM('')SURFACE())")
        return self.add(f"B_SPLINE_SURFACE_WITH_KNOTS('',{du},{dv},{cps},.UNSPECIFIED.,.F.,.F.,.F.,{kn})")

    # ---- file
    def write(self, path, items, name, styles=()):
        """items: solid / surface-model refs for one ADVANCED_BREP or MANIFOLD_SURFACE shape representation;
        styles: [(solid, sheet or face ref, (r, g, b), translucency)] written as STEP colours."""
        s = self
        app = s.add("APPLICATION_CONTEXT('automotive design')")
        s.add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{app})")
        pc = s.add(f"PRODUCT_CONTEXT('',{app},'mechanical')")
        nm = "".join(ch for ch in name if 32 <= ord(ch) < 127 and ch not in "'\\") or "part"
        prod = s.add(f"PRODUCT('{nm}','{nm}','',({pc}))")
        pdf = s.add(f"PRODUCT_DEFINITION_FORMATION('','',{prod})")
        pdc = s.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',{app},'design')")
        pd = s.add(f"PRODUCT_DEFINITION('design','',{pdf},{pdc})")
        pds = s.add(f"PRODUCT_DEFINITION_SHAPE('','',{pd})")
        mm = s.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
        rad = s.add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
        sr = s.add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
        unc = s.add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-05),{mm},'distance_accuracy_value','')")
        ctx = s.add(f"(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({unc}))"
                    f"GLOBAL_UNIT_ASSIGNED_CONTEXT(({mm},{rad},{sr}))REPRESENTATION_CONTEXT('',''))")
        solids = [r for kind, r in items if kind == "solid"]
        sheets = [r for kind, r in items if kind == "sheet"]
        if solids and sheets:  # both kinds: a plain shape representation (readers take any item there)
            rep = s.add(f"SHAPE_REPRESENTATION('',({','.join(solids + sheets)}),{ctx})")
        elif solids:
            rep = s.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('',({','.join(solids)}),{ctx})")
        else:
            rep = s.add(f"MANIFOLD_SURFACE_SHAPE_REPRESENTATION('',({','.join(sheets)}),{ctx})")
        s.add(f"SHAPE_DEFINITION_REPRESENTATION({pds},{rep})")
        self._styles(styles, ctx)
        head =("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('SolidWorks / Parasolid part converted by solidsmufs'),'2;1');\n"
                f"FILE_NAME('{nm}.stp','',(''),(''),'solidsmufs','solidsmufs','');\n"
                "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n")
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="ascii", newline="\n") as fh:
            fh.write(head)
            fh.write("\n".join(s.lines))
            fh.write("\nENDSEC;\nEND-ISO-10303-21;\n")
        os.replace(tmp, path)


    def _styles(self, styles, ctx):
        """Colours the way STEP AP214 carries them (and OpenCASCADE reads them): a STYLED_ITEM per coloured
        solid or face, gathered in one MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION. Translucency
        rides along as SURFACE_STYLE_TRANSPARENT; readers that don't know it keep the colour."""
        if not styles:
            return
        s, assignments, items = self, {}, []
        for ref, rgb, clear in styles:
            key = (tuple(round(float(c), 4) for c in rgb), round(float(clear), 3))
            if key not in assignments:
                col = s.add(f"COLOUR_RGB('',{num(key[0][0])},{num(key[0][1])},{num(key[0][2])})")
                fill_colour = s.add(f"FILL_AREA_STYLE_COLOUR($,{col})")
                fill_style = s.add(f"FILL_AREA_STYLE($,({fill_colour}))")
                parts = [s.add(f"SURFACE_STYLE_FILL_AREA({fill_style})")]
                if key[1] > 0:
                    clear = s.add(f"SURFACE_STYLE_TRANSPARENT({num(key[1])})")
                    parts.append(s.add(f"SURFACE_STYLE_RENDERING_WITH_PROPERTIES(.NORMAL_SHADING.,{col},({clear}))"))
                side = s.add(f"SURFACE_SIDE_STYLE('',({','.join(parts)}))")
                usage = s.add(f"SURFACE_STYLE_USAGE(.BOTH.,{side})")
                assignments[key] = s.add(f"PRESENTATION_STYLE_ASSIGNMENT(({usage}))")
            items.append(s.add(f"STYLED_ITEM('color',({assignments[key]}),{ref})"))
        s.add(f"MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',({','.join(items)}),{ctx})")


def _knots(U):
    ks, ms = [], []
    for u in np.asarray(U, float):
        if ks and u == ks[-1]:
            ms[-1] += 1
        else:
            ks.append(float(u))
            ms.append(1)
    return ks, ms

