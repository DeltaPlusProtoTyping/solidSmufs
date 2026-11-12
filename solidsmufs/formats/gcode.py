"""G-code (Fanuc / Haas style ISO programs, as most CAM posts write them), read into the moves the machine makes.

Understood: G0 / G1 / G2 / G3 (arcs by I J K or R, helical too, in the G17 / G18 / G19 planes), G90 / G91,
G20 / G21, the drilling cycles G73 / G74 / G76 / G81-G89 (with G98 / G99 and G80), tool changes (T, M6) and the
tool notes CAM writes in comments. G28 / G30 / G53 moves (to machine positions) aren't drawn, and lines that use
macro variables (#) or call subprograms (M98) are skipped and counted. Positions are in program units; `unit_mm`
says how big one is.
"""

import math
import re
from collections import Counter

import numpy as np


class GcodeError(ValueError):
    pass


class Move:
    __slots__ = ("kind", "tool", "points", "arc", "line", "feed")

    def __init__(self, kind, tool, points, arc=None, line=0, feed=None):
        self.kind = kind  # "rapid", "feed" or "arc"
        self.tool, self.points, self.arc, self.line, self.feed = tool, points, arc, line, feed


class Program:
    def __init__(self):
        self.moves = []
        self.unit_mm = 25.4
        self.units = None  # "inches" / "millimeters", or None when the program doesn't say
        self.tools = {}  # tool number -> its description from the comments ("" when there's none)
        self.name = ""  # the program's number or first comment
        self.skipped = Counter()  # what wasn't followed, and how often
        self.lathe = False
        self.per_rev = False  # feeds per revolution (G95): no cutting time
        self.lines = 0


WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
COMMENT = re.compile(r"\(([^)]*)\)|;(.*)$")
PLANES = {17: (0, 1, 2), 18: (2, 0, 1), 19: (1, 2, 0)}  # (first axis, second axis, the axis square to them)
CYCLES = {73, 74, 76, 81, 82, 83, 84, 85, 86, 87, 88, 89}
ARC_STEP = math.radians(3.0)


def _arc_points(center, r, a0, sweep, c0, c1, plane, tol):
    """Points along an arc in the plane `plane`: (n, 3)."""
    a, b, c = plane
    step = ARC_STEP
    if r > tol:
        step = min(step, 2 * math.acos(max(-1.0, 1 - tol / r)))
    n = int(min(max(math.ceil(abs(sweep) / step), 2), 2000))
    t = np.linspace(0.0, 1.0, n + 1)
    ang = a0 + sweep * t
    pts = np.zeros((n + 1, 3))
    pts[:, a] = center[0] + r * np.cos(ang)
    pts[:, b] = center[1] + r * np.sin(ang)
    pts[:, c] = c0 + (c1 - c0) * t
    return pts


def read_gcode(data, tol=None):
    """A Program from the bytes of a G-code file."""
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    if "BEGIN PGM" in text[:2000]:
        raise GcodeError("This is a Heidenhain conversational program, not G-code, so it can't be drawn.")
    if "\0" in text[:4096]:
        raise GcodeError("This doesn't look like a G-code program (it's a binary file).")
    p = Program()
    pos = [None, None, None]
    mode, plane, absolute, tool, feed = 0, PLANES[17], True, 0, None
    cycle_r, cycle_z, cycle_init, cycle_return = None, None, None, 98
    any_m6, pending_t = False, None
    words_seen = 0
    tools_comment = {}
    tol = tol or 0.0005

    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line[0] in "%":
            continue
        comments = [m.group(1) if m.group(1) is not None else m.group(2) for m in COMMENT.finditer(line)]
        code = COMMENT.sub(" ", line).upper()
        if code.startswith("/"):  # block delete: the machine runs it unless the switch is on
            code = code[1:]
        for cm in comments:
            cm = (cm or "").strip()
            if not cm:
                continue
            if not p.name and number <= 5:
                p.name = cm
            t = re.search(r"\bT\s*0*(\d+)\b", cm.upper())
            if t:
                tools_comment.setdefault(int(t.group(1)), cm)
        if not code.strip():
            continue
        if code.lstrip().startswith("O") and re.match(r"\s*O\d+", code):
            if not p.name:
                p.name = code.strip().split()[0]
            continue
        if "#" in code or "[" in code:
            p.skipped["lines using macro variables"] += 1
            continue
        words = WORD.findall(code)
        if not words:
            continue
        words_seen += 1
        g = [round(float(v), 1) for k, v in words if k == "G"]
        m = [int(float(v)) for k, v in words if k == "M"]
        val = {}
        for k, v in words:
            if k not in "GMN":
                val[k] = float(v)
        if 98 in m:
            p.skipped["subprogram calls (M98)"] += 1
        if 6 in m:
            any_m6 = True
            if "T" in val:
                pending_t = int(val["T"])
            if pending_t is not None:
                tool = pending_t
        elif "T" in val:
            pending_t = int(val["T"])
            if not any_m6:  # a control that changes tools on T alone (lathes, routers)
                tool = pending_t
        if "F" in val:
            feed = val["F"]
        skip_axes = False
        for code_g in g:
            gi = int(code_g)
            if code_g in (0, 1, 2, 3):
                mode = gi
            elif code_g in (17, 18, 19):
                plane = PLANES[gi]
            elif code_g == 20:
                p.unit_mm, p.units = 25.4, "inches"
            elif code_g == 21:
                p.unit_mm, p.units = 1.0, "millimeters"
            elif code_g == 90:
                absolute = True
            elif code_g == 91:
                absolute = False
            elif code_g == 80:
                mode = 0 if mode in CYCLES else mode
                cycle_init = None
            elif gi in CYCLES and code_g == gi:
                if mode not in CYCLES:
                    cycle_init = pos[2]
                mode = gi
            elif code_g in (98, 99):
                cycle_return = gi
            elif code_g == 95:
                p.per_rev = True
            elif code_g == 96:  # constant surface speed: a lathe
                p.lathe = True
            elif gi in (4, 10, 28, 30, 52, 53, 65, 92):
                skip_axes = True  # dwell time, machine positions, offsets: not moves to draw
                if gi in (52, 92):
                    p.skipped["offset changes (G52/G92)"] += 1
                if gi in (28, 30, 53):  # gone to a machine position: where that is in the program isn't known
                    for k, i in (("X", 0), ("Y", 1), ("Z", 2)):
                        if k in val:
                            pos[i] = None
        if skip_axes:
            continue
        axes = {"X": 0, "Y": 1, "Z": 2}
        if not any(k in val for k in axes):
            continue
        target = list(pos)
        for k, i in axes.items():
            if k in val:
                if absolute or target[i] is None:
                    target[i] = val[k] if absolute else None
                else:
                    target[i] = target[i] + val[k]

        if mode in CYCLES:
            if "R" in val:
                cycle_r = val["R"]
            if "Z" in val:
                cycle_z = val["Z"]
            if cycle_init is None:
                cycle_init = pos[2]
            if cycle_r is None or cycle_z is None or target[0] is None or target[1] is None:
                continue
            top = cycle_init if cycle_init is not None else cycle_r
            here = [target[0], target[1], top if pos[2] is None else pos[2]]
            if None not in pos:
                p.moves.append(Move("rapid", tool, np.array([pos, here], float), line=number))
            hole = [
                ("rapid", here, [target[0], target[1], cycle_r]),
                ("feed", [target[0], target[1], cycle_r], [target[0], target[1], cycle_z]),
                ("rapid", [target[0], target[1], cycle_z], [target[0], target[1], top if cycle_return == 98 else cycle_r]),
            ]
            for kind, a_, b_ in hole:
                if a_ != b_:
                    p.moves.append(Move(kind, tool, np.array([a_, b_], float), line=number, feed=feed))
            pos = [target[0], target[1], top if cycle_return == 98 else cycle_r]
            continue

        if None in pos or None in target:
            pos = [t if t is not None else q for t, q in zip(target, pos)]
            continue
        start = np.array(pos, float)
        end = np.array(target, float)
        if mode in (2, 3):
            a, b, c = plane
            s2, e2 = np.array([start[a], start[b]]), np.array([end[a], end[b]])
            ijk = ("I", "J", "K")
            if "R" in val:
                r = val["R"]
                d = float(np.linalg.norm(e2 - s2))
                if d == 0 or abs(r) < d / 2 - 1e-9:
                    if d == 0:
                        p.skipped["arcs with no length"] += 1
                        continue
                    r = math.copysign(d / 2, r)
                h = math.sqrt(max(r * r - d * d / 4, 0.0))
                left = np.array([-(e2 - s2)[1], (e2 - s2)[0]]) / d
                side = 1.0 if (mode == 3) == (r > 0) else -1.0
                center = (s2 + e2) / 2 + left * h * side
                full = False
            else:
                off = np.zeros(3)
                for k, i in zip(ijk, range(3)):
                    off[i] = val.get(k, 0.0)
                center = s2 + np.array([off[a], off[b]])
                full = float(np.linalg.norm(e2 - s2)) < 1e-9
            radius = float(np.linalg.norm(s2 - center))
            if radius < 1e-12:
                p.skipped["arcs with no radius"] += 1
                pos = target
                continue
            a0 = math.atan2(s2[1] - center[1], s2[0] - center[0])
            a1 = math.atan2(e2[1] - center[1], e2[0] - center[0])
            if mode == 3:
                sweep = (a1 - a0) % (2 * math.pi)
                if full or sweep < 1e-12:
                    sweep = 2 * math.pi if full else sweep
            else:
                sweep = -((a0 - a1) % (2 * math.pi))
                if full or sweep > -1e-12:
                    sweep = -2 * math.pi if full else sweep
            if abs(sweep) < 1e-12:
                pos = target
                continue
            pts = _arc_points(center, radius, a0, sweep, start[c], end[c], plane, tol)
            pts[-1] = end
            c3 = np.zeros(3)
            c3[a], c3[b], c3[c] = center[0], center[1], start[c]
            normal = np.zeros(3)
            normal[c] = 1.0
            p.moves.append(Move("arc", tool, pts, arc={"center": c3, "radius": radius, "normal": normal, "sweep": sweep,
                                                      "full": abs(abs(sweep) - 2 * math.pi) < 1e-9,
                                                      "helical": abs(end[c] - start[c]) > 1e-9}, line=number, feed=feed))
        elif not np.allclose(start, end):
            p.moves.append(Move("rapid" if mode == 0 else "feed", tool, np.array([start, end]), line=number, feed=feed))
        pos = target

    if not words_seen:
        raise GcodeError("This file has no G-code in it.")
    if not p.moves:
        raise GcodeError("This program has no moves that can be drawn.")
    used = sorted({mv.tool for mv in p.moves})
    p.tools = {t: tools_comment.get(t, "") for t in used}
    p.lines = number
    return p
