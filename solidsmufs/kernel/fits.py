"""ISO 286 limits and fits: 'H7' on 25 mm -> 25.000 to 25.021 mm. Capital letters are holes, small letters shafts.

Sizes up to 500 mm, grades IT1 to IT16, the letters A-H, JS, K, M, N, P, R, S, T, U (and a-h, js, k, m, n, p, r, s, t, u).
limits(25, "H7") -> {"cls", "kind", "lo_um", "hi_um", "min_mm", "max_mm", "min_in", "max_in"}, or None if it can't be worked out.
"""

import re

_IT_TOPS = (3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500)
_IT = {  # micrometers
    1: (0.8, 1, 1, 1.2, 1.5, 1.5, 2, 2.5, 3.5, 4.5, 6, 7, 8),
    2: (1.2, 1.5, 1.5, 2, 2.5, 2.5, 3, 4, 5, 7, 8, 9, 10),
    3: (2, 2.5, 2.5, 3, 4, 4, 5, 6, 8, 10, 12, 13, 15),
    4: (3, 4, 4, 5, 6, 7, 8, 10, 12, 14, 16, 18, 20),
    5: (4, 5, 6, 8, 9, 11, 13, 15, 18, 20, 23, 25, 27),
    6: (6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40),
    7: (10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63),
    8: (14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97),
    9: (25, 30, 36, 43, 52, 62, 74, 87, 100, 115, 130, 140, 155),
    10: (40, 48, 58, 70, 84, 100, 120, 140, 160, 185, 210, 230, 250),
    11: (60, 75, 90, 110, 130, 160, 190, 220, 250, 290, 320, 360, 400),
    12: (100, 120, 150, 180, 210, 250, 300, 350, 400, 460, 520, 570, 630),
    13: (140, 180, 220, 270, 330, 390, 460, 540, 630, 720, 810, 890, 970),
    14: (250, 300, 360, 430, 520, 620, 740, 870, 1000, 1150, 1300, 1400, 1550),
    15: (400, 480, 580, 700, 840, 1000, 1200, 1400, 1600, 1850, 2100, 2300, 2500),
    16: (600, 750, 900, 1100, 1300, 1600, 1900, 2200, 2500, 2900, 3200, 3600, 4000),
}
_DEV_TOPS = (3, 6, 10, 14, 18, 24, 30, 40, 50, 65, 80, 100, 120, 140, 160, 180, 200, 225, 250, 280, 315, 355, 400, 450, 500)
_UPPER = {  # shafts a-h: es, the upper deviation (holes A-H: EI is the same, opposite sign)
    "a": (-270, -270, -280, -290, -290, -300, -300, -310, -320, -340, -360, -380, -410, -460, -520, -580, -660, -740, -820, -920, -1050, -1200, -1350, -1500, -1650),
    "b": (-140, -140, -150, -150, -150, -160, -160, -170, -180, -190, -200, -220, -240, -260, -280, -310, -340, -380, -420, -480, -540, -600, -680, -760, -840),
    "c": (-60, -70, -80, -95, -95, -110, -110, -120, -130, -140, -150, -170, -180, -200, -210, -230, -240, -260, -280, -300, -330, -360, -400, -440, -480),
    "d": (-20, -30, -40, -50, -50, -65, -65, -80, -80, -100, -100, -120, -120, -145, -145, -145, -170, -170, -170, -190, -190, -210, -210, -230, -230),
    "e": (-14, -20, -25, -32, -32, -40, -40, -50, -50, -60, -60, -72, -72, -85, -85, -85, -100, -100, -100, -110, -110, -125, -125, -135, -135),
    "f": (-6, -10, -13, -16, -16, -20, -20, -25, -25, -30, -30, -36, -36, -43, -43, -43, -50, -50, -50, -56, -56, -62, -62, -68, -68),
    "g": (-2, -4, -5, -6, -6, -7, -7, -9, -9, -10, -10, -12, -12, -14, -14, -14, -15, -15, -15, -17, -17, -18, -18, -20, -20),
    "h": (0,) * 25,
}
_LOWER = {  # shafts k-u: ei, the lower deviation (k's is for grades 4 to 7; other grades are 0)
    "k": (0, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 5, 5),
    "m": (2, 4, 6, 7, 7, 8, 8, 9, 9, 11, 11, 13, 13, 15, 15, 15, 17, 17, 17, 20, 20, 21, 21, 23, 23),
    "n": (4, 8, 10, 12, 12, 15, 15, 17, 17, 20, 20, 23, 23, 27, 27, 27, 31, 31, 31, 34, 34, 37, 37, 40, 40),
    "p": (6, 12, 15, 18, 18, 22, 22, 26, 26, 32, 32, 37, 37, 43, 43, 43, 50, 50, 50, 56, 56, 62, 62, 68, 68),
    "r": (10, 15, 19, 23, 23, 28, 28, 34, 34, 41, 43, 51, 54, 63, 65, 68, 77, 80, 84, 94, 98, 108, 114, 126, 132),
    "s": (14, 19, 23, 28, 28, 35, 35, 43, 43, 53, 59, 71, 79, 92, 100, 108, 122, 130, 140, 158, 170, 190, 208, 232, 252),
    "t": (None, None, None, None, None, None, 41, 48, 54, 66, 75, 91, 104, 122, 134, 146, 166, 180, 196, 218, 240, 268, 294, 330, 360),
    "u": (18, 23, 28, 33, 33, 41, 48, 60, 70, 87, 102, 124, 144, 170, 190, 210, 236, 258, 284, 315, 350, 390, 435, 490, 540),
}
CLASS = re.compile(r"^(JS|js|[A-HKMNPRSTU]|[a-hkmnprstu])(\d{1,2})$")


def _band(size, tops):
    if not 0 < size <= tops[-1]:
        return None
    return next(i for i, top in enumerate(tops) if size <= top)


def it(size, grade):
    """The tolerance width in micrometers, or None."""
    i = _band(size, _IT_TOPS)
    return None if i is None or grade not in _IT else _IT[grade][i]


def deviations(size, cls):
    """(lower, upper) in micrometers from the nominal size, or None if the class isn't known."""
    m = CLASS.match(cls)
    if not m:
        return None
    letter, grade = m.group(1), int(m.group(2))
    w, d = it(size, grade), _band(size, _DEV_TOPS)
    if w is None:
        return None
    if letter in ("JS", "js"):
        return -w / 2, w / 2
    low = letter.lower()
    hole = letter.isupper()
    if low in _UPPER:
        es = _UPPER[low][d]
        return (-es, -es + w) if hole else (es - w, es)
    ei = _LOWER[low][d]
    if low == "k" and (hole and grade > 8 or not hole and not 4 <= grade <= 7):
        ei = 0
    if ei is None:
        return None
    if not hole:
        return ei, ei + w
    if low == "n" and grade > 8 and size > 3:  # N9 and coarser: upper limit on the nominal size
        return -w, 0
    # holes K to U: the shaft's deviation turned over, plus delta (the step between this grade and the next finer)
    fine = 8 if low in ("k", "m", "n") else 7
    delta = 0
    if grade <= fine and size > 3:
        finer = it(size, grade - 1)
        if finer is None:
            return None
        delta = w - finer
    es = -ei + delta
    return es - w, es


def limits(size, cls):
    dev = deviations(size, cls)
    if dev is None:
        return None
    lo, hi = dev
    return {"cls": cls, "kind": "hole" if cls[0].isupper() else "shaft", "lo_um": lo, "hi_um": hi,
            "min_mm": size + lo / 1000, "max_mm": size + hi / 1000,
            "min_in": (size + lo / 1000) / 25.4, "max_in": (size + hi / 1000) / 25.4}
