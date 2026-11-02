"""How a body should look: a physically based finish (metalness, roughness, clear coat, opacity) from what
the file says about it: a SolidWorks appearance ("satin finish stainless steel"), else its material
("AISI 304"), else nothing (the viewer's plain look).

SolidWorks keeps appearances as files we can't read here, but their names say what they are; the exact
colour comes from the part itself (Parasolid colour attributes), so only the finish is decided by name.
"""

import re

# finish name -> physically based values for the viewer (MeshPhysicalMaterial)
FINISHES = {
    "Polished metal": {"metal": 1.0, "rough": 0.1},
    "Satin metal": {"metal": 1.0, "rough": 0.3},
    "Brushed metal": {"metal": 1.0, "rough": 0.38},
    "Rough metal": {"metal": 1.0, "rough": 0.55},
    "Metallic paint": {"metal": 0.55, "rough": 0.3, "coat": 0.6},
    "High gloss plastic": {"metal": 0.0, "rough": 0.16, "coat": 0.7},
    "Medium gloss plastic": {"metal": 0.0, "rough": 0.36, "coat": 0.25},
    "Low gloss plastic": {"metal": 0.0, "rough": 0.62},
    "Matte rubber": {"metal": 0.0, "rough": 0.92},
    "Glossy rubber": {"metal": 0.0, "rough": 0.45, "coat": 0.2},
    "Clear plastic": {"metal": 0.0, "rough": 0.06, "coat": 0.8, "opacity": 0.4},
    "Glass": {"metal": 0.0, "rough": 0.03, "coat": 1.0, "opacity": 0.3},
    "Wood": {"metal": 0.0, "rough": 0.6, "coat": 0.15},
    "Painted": {"metal": 0.0, "rough": 0.42, "coat": 0.15},
}

METAL = r"steel|stainless|chrom|nickel|alumin|brass|bronze|copper|gold|silver|iron|zinc|titanium|galvaniz|pewter|tin\b|magnesium|metal\b"
PLASTIC = r"plastic|abs\b|nylon|pvc|pbt|polyprop|polyeth|acetal|delrin|peek|pom\b|polyamide"
WOOD = r"\bash\b|oak|wood|maple|pine|walnut|cherry|birch|beech|mahogany|teak"
CLEAR = r"\bclear|transparent|glass|acrylic|polycarbonate|plexi"
COLOURS = {  # what a colour word in an appearance name looks like (sRGB 0-1), to pair appearances with bodies
    "black": (0.05, 0.05, 0.05), "white": (0.95, 0.95, 0.95), "light grey": (0.78, 0.78, 0.78),
    "dark grey": (0.3, 0.3, 0.3), "grey": (0.55, 0.55, 0.55), "gray": (0.55, 0.55, 0.55),
    "red": (0.85, 0.1, 0.1), "blue": (0.1, 0.35, 0.85), "green": (0.15, 0.6, 0.2), "yellow": (0.98, 0.85, 0.1),
    "orange": (0.95, 0.5, 0.1), "purple": (0.5, 0.2, 0.6), "brown": (0.45, 0.28, 0.15), "pink": (0.95, 0.6, 0.7),
}
SOLIDWORKS_DEFAULT = (0.792, 0.82, 0.933)  # the pale blue-grey of a part with no appearance
METAL_TINTS = {  # base colours for metals named in an appearance or material, when the part has none
    "brass": (0.86, 0.72, 0.38), "bronze": (0.75, 0.5, 0.3), "copper": (0.88, 0.52, 0.38),
    "gold": (1.0, 0.8, 0.36), "chrom": (0.8, 0.82, 0.84), "alumin": (0.82, 0.83, 0.85),
    "titanium": (0.62, 0.6, 0.57), "iron": (0.42, 0.42, 0.43), "steel": (0.68, 0.7, 0.72),
}


def finish_of_appearance(name):
    """Finish name for a SolidWorks appearance name, or None when the name says nothing usable."""
    n = (name or "").lower()
    if not n or re.match(r"pw-|texture|color$", n):
        return None
    if re.search(CLEAR, n) and not re.search(r"opaque|frosted", n):
        return "Glass" if "glass" in n else "Clear plastic"
    if "rubber" in n:
        return "Matte rubber" if re.search(r"matte|textured|rough", n) else "Glossy rubber"
    if "metallic" in n and not re.search(METAL, n):
        return "Metallic paint"  # "metallic cool grey": a paint with metal flake, not a metal
    if re.search(METAL, n):
        if re.search(r"polish|chrom|mirror|plate|gold|silver", n):
            return "Polished metal"
        if re.search(r"brush|satin|nickel", n):
            return "Brushed metal" if "brush" in n else "Satin metal"
        if re.search(r"cast|wrought|rough|sand|galvaniz|carbon steel|forged|knurl|iron", n):
            return "Rough metal"
        return "Satin metal"
    if re.search(WOOD, n):
        return "Wood"
    if re.search(PLASTIC, n) or re.search(r"gloss", n):
        if re.search(r"high gloss|polished", n):
            return "High gloss plastic"
        if re.search(r"low gloss|matte|textured|satin|eroded", n):
            return "Low gloss plastic"
        return "Medium gloss plastic"
    if re.search(r"paint|powder|enamel|lacquer", n):
        return "Painted"
    return None


def finish_of_material(material):
    """Finish name a material suggests when no appearance says otherwise (SolidWorks does the same)."""
    m = (material or "").lower()
    if not m:
        return None
    if re.search(r"rubber|neoprene|silicone", m):
        return "Matte rubber"
    if "glass" in m:
        return "Glass"
    if re.search(r"acrylic|polycarbonate|\bpc\b", m):
        return "Clear plastic"
    if re.search(r"brass|bronze|copper|gold|silver|chrom", m):
        return "Polished metal"
    if re.search(r"cast|ductile|gray iron|grey iron|malleable|galvaniz|plain carbon|hot rolled|wrought iron", m):
        return "Rough metal"
    if re.search(METAL, m) or re.search(r"aisi|sae|alloy|^\d{4}([- ]|$)|\d{4}-[ot]\d", m):
        return "Satin metal"
    if re.search(PLASTIC, m) or re.search(r"pp\b|pe\b|ptfe|teflon", m):
        return "Medium gloss plastic"
    if re.search(WOOD, m):
        return "Wood"
    return None


def tint_of(name):
    n = (name or "").lower()
    return next((rgb for word, rgb in METAL_TINTS.items() if word in n), None)


def appearance_colour(name):
    """The colour an appearance name implies (colour words first, then metals), or None."""
    n = (name or "").lower()
    for word in sorted(COLOURS, key=len, reverse=True):  # "light grey" before "grey"
        if re.search(rf"\b{word}\b", n):
            return COLOURS[word]
    if "rubber" in n:
        return COLOURS["black"]
    return tint_of(n)


def pick_appearance(colour, appearances):
    """Which of a part's appearances a body of this colour wears: the only one, else the one whose name
    fits the colour best."""
    usable = [a for a in appearances if finish_of_appearance(a)]
    if len(usable) <= 1 or colour is None:
        return usable[0] if usable else None
    scored = [(sum((x - y) ** 2 for x, y in zip(colour, appearance_colour(a))), i, a)
              for i, a in enumerate(usable) if appearance_colour(a) is not None]
    return min(scored)[2] if scored else usable[0]


def look(colour, appearances, material, plain=None):
    """{"finish": name, "appearance": name or None, **values} for one body; `plain` is the finish when the
    file names neither appearance nor material (None: nothing known, the viewer's own look)."""
    appearance = pick_appearance(colour, appearances or [])
    name = finish_of_appearance(appearance) or finish_of_material(material) or plain
    if not name:
        return None
    out = {"finish": name, "appearance": appearance, **FINISHES[name]}
    # SolidWorks' default part colour means "no appearance chosen"; SolidWorks then shows the material's
    # own look, so a metal shows in its metal colour rather than that pale blue
    plain = colour is None or all(abs(c - d) < 0.01 for c, d in zip(colour, SOLIDWORKS_DEFAULT))
    if plain:
        tint = tint_of(appearance) or tint_of(material)
        if tint is None and FINISHES[name]["metal"] >= 1.0:
            tint = METAL_TINTS["steel"]
        if tint:
            out["tint"] = list(tint)
    return out


def apply(model, info, bodies=None):
    """Give model bodies (all, or the given indices) the look, material and density a translated part's
    info describes; bodies without a colour of their own get the part's colour for their position."""
    material, density = info.get("material"), info.get("density")
    colours, clears = info.get("colours") or [], info.get("translucency") or []
    # SolidWorks draws its plain colour appearance as smooth painted plastic
    plain = "Painted" if str(info.get("format", "")).startswith("SolidWorks") else None
    indices = list(range(len(model.bodies))) if bodies is None else list(bodies)
    for k, bi in enumerate(indices):
        b = model.bodies[bi]
        if b.get("color") is None and k < len(colours) and colours[k]:
            b["color"] = [float(c) for c in colours[k]]
        lk = look(b.get("color"), info.get("appearances"), material, plain)
        clear =float(clears[k]) if k < len(clears) and clears[k] else 0.0
        if clear > 0:  # the part itself is see-through (SolidWorks' transparency)
            lk = {**(lk or {"finish": "Painted", "appearance": None, **FINISHES["Painted"]}), "opacity": round(1 - clear, 3)}
        if lk:
            b["finish"] = lk
        if material:
            b["material"] = material
        if density:
            b["density"] = round(float(density) / 1000.0, 6)  # kg/m³ -> g/cm³, as the viewer uses
