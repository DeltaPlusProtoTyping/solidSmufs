"""HP-GL and HP-GL/2 plot files (.plt), read into a drawing: each pen a layer, its moves lines and arcs, and its
labels text. Plotter units are 0.025 mm (1016 to the inch).

Understood: IN / DF, SP, PU / PD / PA / PR, PE (HP-GL/2's packed polylines), CI, AA / AR, EA / ER / RA / RR, BZ / BR,
LB with SI / SR / DI / DT, PC (pen colors) and NP. PCL and PJL wrapping (as printer drivers write) is skipped.
"""

import math
import re
from collections import Counter

import numpy as np

from .dxf import Conic, Drawing, Layer, Poly, Text

PLU_MM = 0.025

# HP-GL/2's default pen colors: 0 white, 1 black (the drawing's ink), 2 red, 3 green, 4 yellow, 5 blue, 6 magenta, 7 cyan
PEN_COLORS = {1: None, 2: (0.9, 0.1, 0.1), 3: (0.1, 0.65, 0.2), 4: (0.85, 0.7, 0.0), 5: (0.15, 0.35, 0.95),
              6: (0.8, 0.15, 0.8), 7: (0.0, 0.7, 0.75), 0: (0.75, 0.75, 0.75)}


class HpglError(ValueError):
    pass


def _strip_wrapping(data):
    """The HP-GL from a file that may be wrapped in PCL / PJL (as Windows plotter drivers write them)."""
    data = re.sub(rb"@PJL[^\n]*\n", b"", data)
    data = data.replace(b"\x1b%-12345X", b"")
    # PCL escapes: ESC then a parameterised group (ESC % 1 B, ESC & l 0 O, ESC * c 100 G, ...) or a single letter
    data = re.sub(rb"\x1b[%&*()][a-z]?[-+]?\d*(?:\.\d+)?[@A-Z]", b"", data)
    data = re.sub(rb"\x1b[A-Za-z]", b"", data)
    return data.decode("latin-1")


NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _pe_numbers(text, i):
    """Decode a PE (polyline encoded) body starting at text[i]: (list of ops, index after the closing ';')."""
    ops, base7, frac = [], False, 0
    up_next, abs_next = False, False
    n = len(text)

    def number(j):
        val, mult = 0, 1
        while j < n:
            b = ord(text[j])
            if base7:
                if 63 <= b <= 94:
                    val += (b - 63) * mult
                    mult *= 32
                elif 95 <= b <= 126:
                    val += (b - 95) * mult
                    return val, j + 1
                else:
                    return None, j
            else:
                if 63 <= b <= 126:
                    val += (b - 63) * mult
                    mult *= 64
                elif 191 <= b <= 254:
                    val += (b - 191) * mult
                    return val, j + 1
                else:
                    return None, j
            j += 1
        return None, j

    def signed(v):
        return -(v >> 1) if v & 1 else v >> 1

    while i < n:
        c = text[i]
        if c == ";":
            return ops, i + 1
        if c == "7":
            base7 = True
            i += 1
        elif c == ":":
            v, i = number(i + 1)
            if v is not None:
                ops.append(("pen", signed(v)))
        elif c == ">":
            v, i = number(i + 1)
            if v is not None:
                frac = signed(v)
        elif c == "<":
            up_next = True
            i += 1
        elif c == "=":
            abs_next = True
            i += 1
        else:
            vx, j = number(i)
            if vx is None:
                i += 1  # a stray character (a line break): skip it
                continue
            vy, j = number(j)
            if vy is None:
                i = j
                continue
            scale = 2.0 ** -frac if frac else 1.0
            ops.append(("abs" if abs_next else "rel", signed(vx) * scale, signed(vy) * scale, up_next))
            up_next = abs_next = False
            i = j
    return ops, n


class _Plotter:
    def __init__(self):
        self.d = Drawing()
        self.d.unit_mm = 1.0
        self.d.units = "plotter units (0.025 mm each)"
        self.pos = np.zeros(2)
        self.down = False
        self.absolute = True
        self.pen = 1
        self.colors = dict(PEN_COLORS)
        self.run = []  # points of the line being drawn
        self.char = (0.285 * 10, 0.375 * 10)  # character width, height in mm (SI's default, in cm)
        self.direction = 0.0
        self.terminator = "\x03"
        self.skipped = Counter()

    # -------------------------------------------------------------- output
    def _layer(self):
        key = f"PEN {self.pen}"
        if key not in self.d.layers:
            self.d.layers[key] = Layer(f"Pen {self.pen}", self.colors.get(self.pen))
        return key

    def _color(self):
        """The pen's color; None for black (the drawing's ink)."""
        c = self.colors.get(self.pen)
        return None if c is None or max(c) < 0.08 else c

    def flush(self):
        if len(self.run) >= 2:
            pts = np.array([[x * PLU_MM, y * PLU_MM, 0.0] for x, y in self.run])
            self.d.curves.append((self._layer(), self._color(), Poly(pts)))
        self.run = []

    def move_to(self, x, y, down):
        p = np.array([x, y], float)
        if down:
            if not self.run:
                self.run = [tuple(self.pos)]
            self.run.append(tuple(p))
        else:
            self.flush()
        self.pos = p

    def arc(self, center, sweep_deg, down):
        """An arc about `center` from where the pen is, `sweep_deg` anticlockwise (negative: clockwise)."""
        c = np.asarray(center, float)
        r_vec = self.pos - c
        r = float(np.hypot(*r_vec))
        a0 = math.atan2(r_vec[1], r_vec[0])
        sweep = math.radians(sweep_deg)
        end = c + r * np.array([math.cos(a0 + sweep), math.sin(a0 + sweep)])
        if down and r > 0 and sweep:
            self.flush()
            t0, t1 = (a0, a0 + sweep) if sweep > 0 else (a0 + sweep, a0)
            u, v = np.array([r * PLU_MM, 0, 0]), np.array([0, r * PLU_MM, 0])
            self.d.curves.append((self._layer(), self._color(), Conic([c[0] * PLU_MM, c[1] * PLU_MM, 0], u, v, t0, t1)))
        self.pos = end

    def label(self, text):
        if not text.strip():
            return
        w, h = self.char
        x = np.array([math.cos(self.direction), math.sin(self.direction), 0.0])
        y = np.array([-x[1], x[0], 0.0])
        origin = np.array([self.pos[0] * PLU_MM, self.pos[1] * PLU_MM, 0.0])
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.d.texts.append((self._layer(), self._color(), Text(lines, origin, x, y, h, width=(w / h) / 0.75 if h else 1.0)))

    # -------------------------------------------------------------- commands
    def points(self, args):
        return [(args[k], args[k + 1]) for k in range(0, len(args) - 1, 2)]

    def go(self, args):
        for x, y in self.points(args):
            if not self.absolute:
                x, y = self.pos[0] + x, self.pos[1] + y
            self.move_to(x, y, self.down)

    def command(self, cmd, args):
        if cmd in ("IN", "DF"):
            self.flush()
            self.down, self.absolute = False, True
            self.char, self.direction, self.terminator = (2.85, 3.75), 0.0, "\x03"
            if cmd == "IN":
                self.pos = np.zeros(2)
        elif cmd == "SP":
            self.flush()
            self.pen = int(args[0]) if args else 0
        elif cmd in ("PU", "PD"):
            self.down = cmd == "PD"
            if not self.down:
                self.flush()
            self.go(args)
        elif cmd in ("PA", "PR"):
            self.absolute = cmd == "PA"
            self.go(args)
        elif cmd == "CI" and args:
            r = args[0]
            here = self.pos.copy()
            self.flush()
            self.d.curves.append((self._layer(), self._color(), Conic([here[0] * PLU_MM, here[1] * PLU_MM, 0], [abs(r) * PLU_MM, 0, 0],
                                                            [0, abs(r) * PLU_MM, 0], 0.0, 2 * math.pi)))
        elif cmd in ("AA", "AR") and len(args) >= 3:
            cx, cy = args[0], args[1]
            if cmd == "AR":
                cx, cy = self.pos[0] + cx, self.pos[1] + cy
            self.arc((cx, cy), args[2], self.down)
        elif cmd in ("EA", "ER", "RA", "RR") and len(args) >= 2:
            x, y = args[0], args[1]
            if cmd in ("ER", "RR"):
                x, y = self.pos[0] + x, self.pos[1] + y
            x0, y0 = self.pos
            self.flush()
            corners = [(x0, y0), (x, y0), (x, y), (x0, y), (x0, y0)]
            self.d.curves.append((self._layer(), self._color(), Poly([[a * PLU_MM, b * PLU_MM, 0] for a, b in corners])))
        elif cmd in ("BZ", "BR"):
            for k in range(0, len(args) - 5, 6):
                p0 = self.pos.copy()
                c1, c2, p3 = (np.array(args[k + j:k + j + 2], float) for j in (0, 2, 4))
                if cmd == "BR":
                    c1, c2, p3 = p0 + c1, p0 + c2, p0 + p3
                t = np.linspace(0, 1, 17)[1:, None]
                pts = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t ** 2 * c2 + t ** 3 * p3
                for q in pts:
                    self.move_to(q[0], q[1], self.down)
        elif cmd == "SI" and len(args) >= 2:
            self.char = (args[0] * 10, args[1] * 10)
        elif cmd == "DI":
            self.direction = math.atan2(args[1], args[0]) if len(args) >= 2 and (args[0] or args[1]) else 0.0
        elif cmd == "PC" and len(args) >= 4:
            self.colors[int(args[0])] = tuple(min(max(v / 255.0, 0.0), 1.0) for v in args[1:4])
        elif cmd in ("EW", "WG", "FP", "EP", "SC", "RO", "IP", "IW"):
            if cmd in ("SC", "RO") and any(args):
                self.skipped[{"SC": "scaling (SC)", "RO": "rotation (RO)"}[cmd]] += 1
            elif cmd in ("EW", "WG"):
                self.skipped["wedges"] += 1


def read_hpgl(data):
    """A Drawing (in mm) from the bytes of an HP-GL or HP-GL/2 file."""
    text = _strip_wrapping(data)
    plot = _Plotter()
    i, n, commands = 0, len(text), 0
    while i < n:
        c = text[i]
        if not c.isalpha():
            i += 1
            continue
        cmd = text[i:i + 2].upper()
        if len(cmd) < 2 or not cmd[1].isalpha():
            i += 1
            continue
        i += 2
        commands += 1
        if cmd == "LB":
            end = text.find(plot.terminator, i)
            end = n if end < 0 else end
            plot.label(text[i:end])
            i = end + 1
            continue
        if cmd == "DT":
            if i < n and text[i] not in ";":
                plot.terminator = text[i]
                i += 1
            continue
        if cmd == "PE":
            ops, i = _pe_numbers(text, i)
            for op in ops:
                if op[0] == "pen":
                    plot.flush()
                    plot.pen = op[1]
                    continue
                _kind, x, y, up = op
                if _kind == "rel":
                    x, y = plot.pos[0] + x, plot.pos[1] + y
                plot.move_to(x, y, not up)
            plot.down = False
            continue
        # parameters: numbers up to the next command letter or ';'
        j = i
        while j < n and not text[j].isalpha() and text[j] != ";":
            j += 1
        args = [float(v) for v in NUM.findall(text[i:j])]
        plot.command(cmd, args)
        i = j + 1 if j < n and text[j] == ";" else j
    plot.flush()
    if not commands or (not plot.d.curves and not plot.d.texts):
        raise HpglError("This plot file has nothing in it that can be drawn (it may not be HP-GL, or may hold only a raster picture).")
    plot.d.skipped.update(plot.skipped)
    return plot.d
