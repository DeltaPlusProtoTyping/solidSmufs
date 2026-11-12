"""Geometric tolerances on a print (ASME Y14.5 / ISO 1101 feature control frames, true position above all): what
the symbol means in plain words, and how hard it is to hold and to measure, each from 1 (easy) to 10 (very hard).

A frame reads: symbol | (Ø) tolerance (modifier) | datum | datum | datum. It's found three ways:
  - the symbol itself in the PDF's text (⌖ ⏥ ⊥ ...);
  - a CAD GD&T font, whose symbols come out of the PDF as letters (j is position, n is Ø, m is MMC: the AutoCAD
    and SolidWorks GDT fonts share this lettering);
  - OCR, which can't read the symbols: a small tolerance followed by datum letters is a frame, and one with a Ø
    zone is almost always position (said so in the tip, as a guess);
and from the words TRUE POSITION / TP in a note.

THE SCORES ARE A FIRST GUESS, TO BE TUNED: everything they come from is in the tables below.
"""

import math
import re

# ---------------------------------------------------------------------------------------------- tuning
# The score starts from the tolerance alone: TIGHT mm scores 10, and every tenfold looser takes PER_DECADE off.
# Set for a good machine shop, where most callouts are routine:
#   0.0002 in -> 10   0.0005 in -> 8   0.001 in -> 7   0.002 in -> 5   0.005 in -> 3   0.010 in -> 2   0.020 in -> 1
TIGHT_MM = 0.00508
PER_DECADE = 5.0
# then each kind of tolerance adds to it: (to hold, to measure)
KIND_ADDS = {
    "position": (0, 0),
    "profile of a surface": (1, 2),  # every point of the surface counts; needs a CMM scan
    "profile of a line": (0.5, 1),
    "flatness": (0, 0),
    "straightness": (0, 0),
    "circularity": (0.5, 1),
    "cylindricity": (1, 2),  # roundness, straightness and taper at once; needs a roundness machine or CMM scan
    "perpendicularity": (0, 0),
    "parallelism": (0, 0),
    "angularity": (0.5, 0.5),
    "concentricity": (1, 2),  # median points: slow to measure, usually better called out as position or runout
    "symmetry": (1, 2),
    "circular runout": (0, -1),  # an indicator and a spin
    "total runout": (1, 0),
    "geometric tolerance": (0, 0),  # the symbol wasn't read
}
TAPPED = (3, 3)  # position of a tapped hole: it's the thread's pitch diameter that's located, hard to hold when
#                  tapping and only measured with a threaded gauge pin (added to: to hold, to measure)
TAPPED_AT_LEAST = (8, 8)  # and it's never easier than this, however loose the tolerance
MMC_HOLD = -1  # at MMC or LMC the tolerance grows as the feature leaves that size (bonus tolerance)
MMC_MEASURE = -1  # and a fixed gauge can check it
NO_DATUMS_POSITION = 0  # (a position with no datums is a pattern's spacing only)
MEASURE_OFFSET = -1  # measuring a tolerance is a little easier than holding it, before the adds above
WORDS = {1: "easy", 2: "easy", 3: "routine", 4: "routine", 5: "takes care", 6: "takes care", 7: "hard", 8: "hard",
         9: "very hard", 10: "very hard"}

# The whole part's difficulty, from every geometric tolerance on the print, 1 to 10. Each callout gives points:
#   points = its kind's multiplier x (PART_MACHINING x its machining score + PART_MEASURING x its measuring score)
# (the two weights are shares of one: a callout gives 10 points at most, before its multiplier), and callouts scoring
# PART_IGNORE or less give none: routine ones don't make a part hard, however many there are. The points are totalled;
# PART_HALF points is a 5/10 part, twice that 7.5, and so on (each further PART_HALF halves what's left to 10).
# One very hard callout makes a hard part on its own: the part is never easier than its hardest callout less
# PART_BELOW_HARDEST.
PART_MACHINING, PART_MEASURING = 0.6, 0.4
PART_KIND = {  # multipliers by kind of tolerance (the rest are 1)
    "tapped position": 1.5,
    "profile of a surface": 1.2,
    "cylindricity": 1.2,
}
PART_IGNORE = 2
PART_HALF = 20.0
PART_BELOW_HARDEST = 1

# ---------------------------------------------------------------------------------------------- reading
SYMBOLS = {  # the characters themselves
    "⌖": "position", "⊕": "position", "⏥": "flatness", "▱": "flatness", "⏤": "straightness", "⎯": "straightness",
    "○": "circularity", "◯": "circularity", "⌭": "cylindricity", "⊥": "perpendicularity", "⟂": "perpendicularity",
    "∥": "parallelism", "⫽": "parallelism", "∠": "angularity", "⌒": "profile of a line", "⌓": "profile of a surface",
    "◎": "concentricity", "⌯": "symmetry", "↗": "circular runout", "⌰": "total runout",
}
FONT = {  # a GD&T font's letters
    "a": "angularity", "b": "perpendicularity", "c": "flatness", "d": "profile of a surface", "e": "circularity",
    "f": "parallelism", "g": "cylindricity", "h": "circular runout", "i": "symmetry", "j": "position",
    "k": "profile of a line", "r": "concentricity", "t": "total runout", "u": "straightness",
}
MEANING = {  # short: it's read at a glance, on hover
    "position": "True position: center vs. where the basic dims put it",
    "flatness": "Flatness: surface between two parallel planes; no datum",
    "straightness": "Straightness: a line of the surface, or the axis",
    "circularity": "Roundness: each cross-section between two circles",
    "cylindricity": "Cylindricity: round, straight and no taper, all at once",
    "perpendicularity": "Perpendicularity: square (90°) to the datum",
    "parallelism": "Parallelism: parallel to the datum",
    "angularity": "Angularity: at the basic angle to the datum",
    "profile of a line": "Profile of a line: each cross-section vs. its true shape",
    "profile of a surface": "Profile of a surface: whole surface vs. its true shape",
    "concentricity": "Concentricity: median points about the datum axis",
    "symmetry": "Symmetry: median points about the datum's center plane",
    "circular runout": "Circular runout: indicator reading per cross-section, turned on the datum axis",
    "total runout": "Total runout: indicator reading over the whole surface, turned on the datum axis",
    "geometric tolerance": "Feature control frame: symbol not read, check the print",
}
SIGN = {v: k for k, v in reversed(list(SYMBOLS.items()))}
MODIFIERS = {  # what a circled letter after the tolerance does
    "M": "Ⓜ MMC: bonus tolerance as the feature leaves MMC; gauge-able",
    "L": "Ⓛ LMC: bonus tolerance as the feature leaves LMC",
    "S": "Ⓢ Regardless of feature size: no bonus",
    "P": "Ⓟ Projected tolerance zone: stands above the surface by the height given",
    "F": "Ⓕ Free state: checked unrestrained",
    "T": "Ⓣ Tangent plane: the high points only",
    "U": "Ⓤ Unequally disposed: the number is how much lies outside the material",
    "ST": "ST Statistical tolerance",
    "CF": "CF Continuous feature: interrupted surfaces as one",
    "?": "Circled modifier (Ⓜ Ⓛ or Ⓢ) not read: check the print",
}
DATUM_MOD = {"M": "at MMB (may shift)", "L": "at LMB", "S": "regardless of size", "?": "modifier not read"}
CIRCLED = {"M": "Ⓜ", "L": "Ⓛ", "S": "Ⓢ", "P": "Ⓟ", "F": "Ⓕ", "T": "Ⓣ", "U": "Ⓤ", "?": "(?)"}
_UNCIRCLE = {v: k for k, v in CIRCLED.items() if k != "?"}
HOLES = {  # the symbols in a hole callout: (name, what it is)
    "⌴": ("Counterbore", "a wider, flat-bottomed hole at the top, so a socket head screw's head sits below the surface"),
    "⌵": ("Countersink", "a cone-shaped opening for a flat head screw; the Ø is across it at the surface"),
    "↧": ("Depth", "how deep, measured from the surface down"),
    "⌳": ("Slope", "flat taper: rise over run"), "⌲": ("Conical taper", "the change in diameter per length"),
    "□": ("Square", "the size is across the flats of a square feature"),
}
HOLE_FONT = {"v": "⌴", "w": "⌵", "x": "↧", "y": "⌲", "z": "⌳", "o": "□"}

_SYMS = "".join(SYMBOLS)
_NUMBER = r"\d*[.,]\d+|\d+"
# in the PDF's own text (the symbols themselves, or a GD&T font's letters: n is Ø, m l s p are the circled letters)
BODY = re.compile(
    r"^(?P<dia>S?\s?[Ø⌀∅øΦφ]|S?\s?n(?=\s?[.,\d]))?\s*(?P<tol>" + _NUMBER + r")"
    r"(?P<mod>(?:\s*(?:[ⓂⓁⓈⓅⒻⓉⓊ]|\((?:ST|CF|[MLSPFTU])\)|[mlsp](?![a-z])|ST(?![A-Za-z])|CF(?![A-Za-z]))(?:\s*(?:" + _NUMBER + r")(?![A-Za-z\d]))?)*)"
    r"(?P<datums>(?:\s*[A-Z](?:\s*-\s*[A-Z])?(?:\s*(?:[ⓂⓁⓈ]|\([MLS]\)|[mls](?![a-z])))?){0,3})$")
# as OCR reads it: Ø as Ø, @, Q or O (00.005 is Ø0.005, but 0.005 is itself: plenty of prints keep the zero); 0.002 as O.002; a circled letter as @, ®, ©, 0, O or the letter; datums in
# either case, their circled letters stuck to them (A@)
BODY_OCR = re.compile(
    r"^(?P<dia>[Ø⌀∅øΦφ]|[@Q](?=\s?[0O]?[.,]\d)|O(?=\s?[.,]\d)|[0O]\s?(?=0[.,]\d))?\s?(?P<tol>[0O]?[.,]\d{1,4})"
    r"(?P<mod>\s*(?:\([MLSPFTU]\)|[ⓂⓁⓈ]|[@®©]|[MS0O](?=\s+[A-Za-z](?![A-Za-z]))))?"
    r"(?P<datums>(?:\s+[A-Za-z](?:\s*-\s*[A-Za-z])?(?:\s*(?:\([MLS]\)|[@®©]))?){0,3})$")
_JUNK = re.compile(r"^(?:[^\s\dA-Za-z.,ØO@Q]{1,2}|[A-Za-z4]|\+)\s+(?=\S)")  # what OCR leaves where the symbol was
SAID = re.compile(r"^(?:TRUE\s+POS(?:ITION)?\.?|T\.?P\.?|POS(?:ITION)?\.?)\s*(?:OF|WITHIN|TOL\.?|:)?\s*(?P<dia>[Ø⌀∅ø])?\s*"
                  r"(?P<tol>\d*[.,]\d+)\s*(?P<unit>mm|in|\")?$", re.I)
SAID_ALONE = re.compile(r"^(?:TRUE\s+POSITION|T\.P\.)$", re.I)
HOLE = re.compile(r"^(?P<sym>[" + "".join(HOLES) + r"])\s*(?P<dia>[Ø⌀∅ø])?\s*(?P<num>" + _NUMBER + r")?(?:\s*[xX×]\s*(?P<angle>\d+(?:[.,]\d+)?)\s*°)?$")
HOLE_FONT_RE = re.compile(r"^(?P<sym>[" + "".join(HOLE_FONT) + r"])\s*(?P<dia>n)?\s*(?P<num>[.,]\d+|\d+[.,]\d+)(?:\s*[xX×]\s*(?P<angle>\d+(?:[.,]\d+)?)\s*°)?$")


def _clean(text):
    """A frame's cells without their walls."""
    return re.sub(r"\s+", " ", re.sub(r"[|\[\]¦│┃]", " ", text)).strip()


def _mods(found, ocr):
    """The circled letters in what followed the tolerance (or a datum): "M", "L", ..., or "?" where OCR can't say."""
    out = []
    for tok in re.findall(r"[ⓂⓁⓈⓅⒻⓉⓊ]|\((?:ST|CF|[MLSPFTU])\)|ST|CF|[@®©]|[A-Za-z0]", found or ""):
        if tok in _UNCIRCLE:
            out.append(_UNCIRCLE[tok])
        elif tok.startswith("("):
            out.append(tok[1:-1])
        elif tok in ("ST", "CF"):
            out.append(tok)
        elif tok in "@®©" or (ocr and tok in "0O"):
            out.append("?")
        elif tok.upper() in "MLSPFTU":
            out.append(tok.upper())
    return out


def _datums(found, ocr):
    """[(letter(s), modifier or None), ...] from what followed the tolerance and its modifiers."""
    out = []
    for name, mod in re.findall(r"([A-Za-z](?:\s*-\s*[A-Za-z])?)\s*([ⓂⓁⓈ]|\([MLS]\)|[@®©]|[mls](?![a-z]))?", found or ""):
        m = _mods(mod, ocr)
        out.append((re.sub(r"\s", "", name).upper() if ocr else re.sub(r"\s", "", name), m[0] if m else None))
    return out


def read(text, ocr=False, loose=False):
    """A geometric tolerance read from a run of words, or None:
    {"kind", "dia", "sphere", "tol" (as written), "mods": ["M", ...], "mmc": "M" | "L" | None, "datums": [...],
     "dmods": [modifier or None for each datum], "guess": bool (OCR saw no symbol), "unit"}.
    `loose`: for OCR, take even a bare tolerance (the caller has other reasons to think it's in a frame)."""
    t = _clean(text)
    if not t:
        return None
    m = SAID.match(t)
    if m:
        return {"kind": "position", "dia": bool(m.group("dia")), "sphere": False, "tol": m.group("tol"), "mods": [], "mmc": None,
                "datums": [], "dmods": [], "guess": False, "unit": (m.group("unit") or "").lower().replace('"', "in") or None}
    kind, guess, font = None, False, False
    if t.startswith("//"):  # how some CAD systems write the parallelism symbol into the PDF's text
        kind, body = "parallelism", t[2:].strip()
    elif t[0] in SYMBOLS:
        kind, body = SYMBOLS[t[0]], t[1:].strip()
    elif not ocr and t[0] in FONT and re.match(r"^[a-z]\s*(?:S?\s?n\s?)?[.,\d]", t):
        kind, body, font = FONT[t[0]], t[1:].strip(), True
    elif ocr:
        body, guess = _JUNK.sub("", t.replace("ØO", "Ø0").replace("øO", "ø0")), True
    else:
        return None
    m = (BODY_OCR if guess else BODY).match(body)
    if not m:
        return None
    tol = m.group("tol").replace("O", "0")
    mods = _mods(m.group("mod"), guess)
    datums = _datums(m.group("datums"), guess)
    if font and not (m.group("dia") or mods or datums or tol.startswith((".", ","))):
        return None  # "a 0.5" is words
    if guess and not loose:
        raw = m.group("datums") or ""
        if raw.strip() and raw == raw.lower() and not re.search(r"[@®©(]", raw) and not m.group("dia"):
            return None  # all lower case and no Ø: words, not datums
        if not m.group("dia") and len(datums) < 2:
            return None  # ".25 A" alone is too little to call a frame
        if not datums and not mods:
            return None  # a bare Ø size
    dia = m.group("dia") or ""
    return {"kind": kind or ("position" if dia else "geometric tolerance"), "dia": bool(dia), "sphere": dia.strip().startswith("S") and len(dia.strip()) > 1,
            "tol": tol, "mods": mods, "mmc": next((x for x in mods if x in ("M", "L")), None),
            "datums": [d for d, _ in datums], "dmods": [x for _, x in datums], "guess": guess, "unit": None}


_LAYER_TOL = re.compile(r"^(?P<dia>S?[Ø⌀∅øΦφ])?(?P<tol>\d*[.,]\d+)$")
_LAYER_MODS = ("M", "L", "S", "P", "F", "T", "U", "ST", "CF")


def read_layer(text):
    """A frame as a CAD system's PDF holds it in its text: the tolerance, then letters, with the symbol, the Ø and
    the circles drawn as lines and so not there ("0.005 P .270 M A B M" is Ø0.005 Ⓟ .270 Ⓜ | A | B Ⓜ). Letters right
    after the tolerance are its modifiers (P and U take the number after them), then come up to three datums, each
    with its own M, L or S. The same shape as read()'s, its kind unknown ("guess") until the picture is looked at;
    None when the words aren't that."""
    toks = _clean(text).split()
    if not toks:
        return None
    m = _LAYER_TOL.match(toks[0])
    if not m:
        return None
    i, mods, extra = 1, [], {}
    while i < len(toks) and toks[i] in _LAYER_MODS:
        mods.append(toks[i])
        i += 1
        if mods[-1] in ("P", "U") and i < len(toks) and re.fullmatch(_NUMBER, toks[i]):
            extra[mods[-1]] = toks[i]
            i += 1
    datums = []
    while i < len(toks) and len(datums) < 3 and re.fullmatch(r"[A-Z](?:-[A-Z])?", toks[i]):
        name, mod = toks[i], None
        i += 1
        if i < len(toks) and toks[i] in ("M", "L", "S"):
            mod = toks[i]
            i += 1
        datums.append((name, mod))
    if i < len(toks):
        return None
    dia = m.group("dia") or ""
    return {"kind": "geometric tolerance", "dia": bool(dia), "sphere": dia.startswith("S") and len(dia) > 1, "tol": m.group("tol"),
            "mods": mods, "mmc": next((x for x in mods if x in ("M", "L")), None), "datums": [d for d, _ in datums],
            "dmods": [x for _, x in datums], "guess": True, "unit": None, "extra": extra}


def tol_unit(tol, unit=None, metric=None):
    """"in" or "mm": the unit a tolerance is in. What's written with it comes first, then what the print says its
    units are (`metric`: True, False, or None when it doesn't say), then how it's written: inch prints leave the
    leading zero off (.005) and metric ones keep it (0,05), Y14.5's own rule. (0.002 is inches all the same: no
    print asks for two microns.)"""
    if unit in ("mm", "in"):
        return unit
    if metric is not None:
        return "mm" if metric else "in"
    v = float(tol.replace(",", "."))
    decimals = len(tol.replace(",", ".").split(".")[-1]) if re.search(r"[.,]", tol) else 0
    return "in" if tol.startswith((".", ",")) or decimals >= 4 or (decimals == 3 and v < 0.01) else "mm"


def tol_mm(tol, unit=None, metric=None):
    """The tolerance in mm."""
    v = float(tol.replace(",", "."))
    return v * 25.4 if tol_unit(tol, unit, metric) == "in" else v


def both(mm, inch_first):
    """A length in both units, the print's own first."""
    return f"{mm / 25.4:.4f} in ({mm:.3f} mm)" if inch_first else f"{mm:.3f} mm ({mm / 25.4:.4f} in)"


def scores(kind, mm, mmc=None, tapped=False):
    """(to machine, to measure), each 1 to 10."""
    base = 10 - PER_DECADE * math.log10(max(mm, 1e-6) / TIGHT_MM)
    hold_add, measure_add = KIND_ADDS.get(kind, (0, 0))
    hold = base + hold_add + (MMC_HOLD if mmc else 0) + (TAPPED[0] if tapped else 0)
    measure = base + MEASURE_OFFSET + measure_add + (MMC_MEASURE if mmc else 0) + (TAPPED[1] if tapped else 0)
    if tapped:
        hold, measure = max(hold, TAPPED_AT_LEAST[0]), max(measure, TAPPED_AT_LEAST[1])
    return tuple(int(min(10, max(1, round(x)))) for x in (hold, measure))


def card(g, metric=None):
    """What hovering a frame shows, in pieces: {"head", "lines": [...], "notes": [...], "machining", "measuring"}
    (the two difficulties, 1 to 10, drawn as gauges under the rest)."""
    mm = tol_mm(g["tol"], g.get("unit"), metric)
    inch = tol_unit(g["tol"], g.get("unit"), metric) == "in"
    kind = g["kind"]
    zone = f"{'SØ' if g.get('sphere') else 'Ø' if g['dia'] else ''}{g['tol']}"
    head = " | ".join([f"{SIGN.get(kind, '▯')} {kind.capitalize()}", " ".join([zone, *(CIRCLED.get(x, x) for x in g["mods"])]),
                       *(f"{d} {CIRCLED[x]}" if x else d for d, x in zip(g["datums"], g["dmods"]))])
    lines = [MEANING[kind]]
    size = both(mm, inch)
    if g.get("sphere"):
        lines.append(f"Zone SØ{size} sphere")
    elif kind == "position" and g["dia"]:
        lines.append(f"Zone Ø{size} · center within {both(mm / 2, inch)}")
    elif kind == "position":
        lines.append(f"Zone {size} wide · half each side")
    elif g["dia"]:
        lines.append(f"Zone Ø{size} about the true axis")
    else:
        lines.append(f"Zone {size} total")
    if g["datums"]:
        named = [f"{d} {CIRCLED[x]} {DATUM_MOD[x]}" if x else d for d, x in zip(g["datums"], g["dmods"])]
        lines.append(f"Datum{'s' if len(named) > 1 else ''} {', '.join(named)}" + (" · in that order" if len(named) > 1 else ""))
    for x in g["mods"]:
        height = (g.get("extra") or {}).get(x)
        lines.append(MODIFIERS[x] + (f" ({height})" if height else ""))
    notes = []
    tapped_hole = bool(g.get("by_thread")) and kind == "position"
    if tapped_hole:
        notes.append("Tapped hole: very hard. The thread's pitch diameter is what's located; needs a threaded gauge pin.")
    if g["guess"]:
        notes.append("OCR can't see the symbol: " + ("a Ø zone with datums is almost always position" if kind == "position" else "check the print"))
    elif g.get("seen"):
        notes.append("Symbol read from the picture: check the print")
    if metric is None and not g.get("unit"):
        notes.append(f"Units weren't found on the print: taken as {'inches' if inch else 'mm'}")
    machining, measuring = scores(kind, mm, g["mmc"], tapped_hole)
    return {"head": head, "lines": lines, "notes": notes, "machining": machining, "measuring": measuring}


def part(frames, metric=None):
    """The whole part's difficulty from its geometric tolerances: `frames` are the read frames (as read() gives them).
    {"score": 1 to 10 (one decimal), "points", "count", "items": [{"head", "machining", "measuring", "points"}, ...]
    hardest first} or None when there are none."""
    items = []
    for g in frames:
        c = card(g, metric)
        tapped_hole = bool(g.get("by_thread")) and g["kind"] == "position"
        mult = PART_KIND.get("tapped position" if tapped_hole else g["kind"], 1.0)
        each = PART_MACHINING * c["machining"] + PART_MEASURING * c["measuring"]
        points = 0.0 if each <= PART_IGNORE else mult * each
        items.append({"head": c["head"] + (" (tapped)" if tapped_hole else ""), "machining": c["machining"], "measuring": c["measuring"],
                      "each": round(each, 1), "mult": mult, "points": round(points, 1)})
    if not items:
        return None
    total = sum(i["points"] for i in items)
    score = 10 * (1 - 0.5 ** (total / PART_HALF))
    score = max(score, max(i["each"] for i in items) - PART_BELOW_HARDEST, 1)
    items.sort(key=lambda i: -i["points"])
    return {"score": round(min(score, 10), 1), "points": round(total, 1), "count": len(items), "items": items}


def tip(g, metric=None):
    """The same as plain words (where a card can't be drawn)."""
    c = card(g, metric)
    return "\n".join([c["head"], *c["lines"], *c["notes"], f"Machining {c['machining']}/10 · Measuring {c['measuring']}/10"])


# a thread callout: 1/4-20, #10-32, .250-20 UNC, M6x1.0, or the words
THREAD = re.compile(r"(?:\d+/\d+|#\s?\d+|\d*\.\d+|\b\d{1,2})\s?-\s?\d{1,2}(?:\.\d+)?\s*(?:UN[CFSJ]?[CF]?|UNEF|NPTF?|NC|NF)(?![A-Za-z])"
                    r"|(?:\d+/\d+|#\s?\d+)\s?-\s?\d{2}(?!\d)|(?<![A-Za-z])M\d{1,2}(?:[.,]\d+)?\s?[xX×]\s?\d(?:[.,]\d+)?"
                    r"|\b(?:TAP(?:PED)?|THREAD(?:ED|S)?|THD|HELI-?COIL|STI)\b", re.I)


def tapped(marks, lines):
    """Mark the position frames that sit under (or beside) a thread callout: a tapped hole's position is far harder.
    lines: the page's lines of (text, x0, y0, x1, y1) words."""
    rows = []
    for ln in lines:
        if ln:
            rows.append((" ".join(w[0] for w in ln), min(w[1] for w in ln), min(w[2] for w in ln), max(w[3] for w in ln), max(w[4] for w in ln)))
    for m in marks:
        g = m.get("g")
        if not g or g.get("by_thread"):
            continue  # (noted on any frame: whether it's a position may only be known once the picture is looked at)
        h = max(m["h"], 1)
        x0, y0, x1, y1 = m["x"] - 2 * h, m["y"] - 5.5 * h, m["x"] + m["w"] + 6 * h, m["y"] + m["h"] + 0.5 * h
        for text, a0, b0, a1, b1 in rows:
            if a0 < x1 and x0 < a1 and b0 < y1 and y0 < b1 and THREAD.search(text):
                g["by_thread"] = True
                m["tip"] = tip(g)
                break


def hole_tip(text):
    """What a hole callout's symbol says (counterbore, countersink, depth, taper, square), or None."""
    t = _clean(text)
    m = HOLE.match(t) or HOLE_FONT_RE.match(t)
    if not m:
        return None
    sym = HOLE_FONT.get(m.group("sym"), m.group("sym"))
    name, what = HOLES[sym]
    num = m.group("num")
    head = f"{sym} {name}" + (f" {'Ø' if m.group('dia') else ''}{num}" if num else "") + (f" × {m.group('angle')}°" if m.group("angle") else "")
    lines = [head, f"{name}: {what}."]
    if num:
        mm = tol_mm(num)
        lines.append(f"{'Ø' if m.group('dia') else ''}{mm:.3f} mm ({mm / 25.4:.4f} in)")
    if m.group("angle"):
        lines.append(f"{m.group('angle')}° is the cone's included angle.")
    return "\n".join(lines)


def rows(words):
    """Words (text, x0, y0, x1, y1) from anywhere on a page, put back into rows: OCR gives each cell of a frame as
    a line of its own, and a frame is read across its cells. Words level with each other and no further apart than
    a few letter heights are a row."""
    out = []
    for w in sorted(words, key=lambda w: ((w[2] + w[4]) / 2, w[1])):
        mid, h = (w[2] + w[4]) / 2, max(w[4] - w[2], 1e-6)
        for row in out:
            last = row[-1]
            lh = max(last[4] - last[2], 1e-6)
            if abs((last[2] + last[4]) / 2 - mid) < 0.45 * max(h, lh) and max(h, lh) < 2.2 * min(h, lh):
                row.append(w)
                break
        else:
            out.append([w])
    split = []
    for row in out:
        row.sort(key=lambda w: w[1])
        cur = [row[0]]
        for w in row[1:]:
            if w[1] - cur[-1][3] > 3.5 * max(w[4] - w[2], cur[-1][4] - cur[-1][2]):
                split.append(cur)
                cur = []
            cur.append(w)
        split.append(cur)
    return split


PENDING = "gdt?"  # a mark's kind while it waits for the picture


def mark(run, text, tip_text, ocr, g=None):
    x0, y0 = min(w[1] for w in run), min(w[2] for w in run)
    m = {"x": x0, "y": y0, "w": max(w[3] for w in run) - x0, "h": max(w[4] for w in run) - y0,
         "kind": "gdt", "text": text, "tip": tip_text, "ocr": ocr}
    if g is not None:
        m["g"] = g  # kept with the mark: its tip is worded again once the print's units are known
        m["_run"] = list(run)  # for a look at the picture (kernel/gdtsee.py); taken off before it's sent
    return m


def scan(words, ocr=False):
    """Marks for one line of (text, x0, y0, x1, y1) words: each feature control frame, position note or hole
    callout symbol on it."""
    out, i = [], 0
    while i < len(words):
        for k in range(min(12, len(words) - i), 0, -1):
            run = words[i:i + k]
            text = " ".join(w[0] for w in run)
            g = None
            if SAID_ALONE.match(_clean(text)):
                t = "⌖ True position\n" + MEANING["position"] + "\nHover the frame or the tolerance beside it for its size and difficulty."
            else:
                g = read(text, ocr)
                t = tip(g) if g else (None if ocr else hole_tip(text))
            if not t and not ocr:
                g = read_layer(text)
                if g:  # a frame without its symbol: not shown until the picture confirms it's in a drawn frame
                    waiting = mark(run, text, "", ocr, g)
                    waiting["kind"] = PENDING
                    out.append(waiting)
                    i += k
                    break
            if not t:
                continue
            out.append(mark(run, text, t, ocr, g))
            i += k
            break
        else:
            i += 1
    return out
