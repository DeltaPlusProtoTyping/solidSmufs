"""Colours, appearances and the material that a part carries.

* Colours: the Parasolid attributes ``SDL/TYSA_COLOUR_2`` (r, g, b from 0 to 1) on bodies and faces, and
  ``SDL/TYSA_TRANSLUCENCY_2`` (0 to 1) on bodies. They are standard Parasolid, so .x_t files exported
  with colours carry them too. SolidWorks sets them to the colour of the appearance it shows.
* SolidWorks parts also keep: the material of each configuration in ``swXmlContents/KeyWords``
  (``Material="AISI 304"``); its density in kg/m³, a double 24 bytes after the ``moDensityParameter_c`` tag
  in ``Contents/Config-<n>`` (checked against SolidWorks' own library values for twenty materials); and the
  appearances in use, by file name (``satin finish stainless steel.p2m``), in the same stream.
"""

import re
import struct

COLOUR = "SDL/TYSA_COLOUR_2"
TRANSLUCENCY = "SDL/TYSA_TRANSLUCENCY_2"
DENSITY_TAG = b"moDensityParameter_c"
DENSITY_OFFSET = 44  # from the start of the tag
DENSITY_RANGE = (100.0, 25000.0)  # kg/m³: foams to tungsten; anything else isn't a density
NOT_SET = "Material <not specified>"
# appearances that aren't a look of the part: a plain colour, and scene floors saved with the part
NOT_A_FINISH = ("color.p2m", "texture.p2m", "shadow floor", "reflective shadow floor")


def colours(model):
    """({BODY index: (r, g, b)}, {FACE index: (r, g, b)}, {BODY index: translucency}) from a transmit."""
    bodies, faces, clear = {}, {}, {}
    for a in model.of_type("ATTRIBUTE"):
        d = model[a["definition"]]
        idn = model[d["identifier"]] if d is not None else None
        name = "".join(idn.get("string") or ()) if idn is not None else ""
        if name not in (COLOUR, TRANSLUCENCY):
            continue
        owner = model[a.get("owner", 0)]
        values = _reals(model, a)
        if owner is None or not values:
            continue
        if name == COLOUR and len(values) >= 3:
            rgb = tuple(min(max(float(v), 0.0), 1.0) for v in values[:3])
            if owner.type == "BODY":
                bodies[owner.idx] = rgb
            elif owner.type == "FACE":
                faces[owner.idx] = rgb
        elif name == TRANSLUCENCY and owner.type == "BODY":
            clear[owner.idx] = min(max(float(values[0]), 0.0), 1.0)
    return bodies, faces, clear


def _reals(model, attribute):
    for fi in attribute.get("fields") or ():
        f = model[fi]
        if f is not None and f.type == "REAL_VALUES":
            return list(f.get("values") or ())
    return []


def solidworks(path, config=None):
    """{"material": name or None, "density": kg/m³ or None, "appearances": [names]} of a SolidWorks part's
    configuration `config` (its Config-<n> id; else the first). Empty values when the file has none."""
    from .containers import sw_streams

    out = {"material": None, "density": None, "appearances": [], "configurations": []}
    try:
        streams = sw_streams(path, keep=lambda n: n == "swXmlContents/KeyWords"
                             or re.fullmatch(r"Contents/Config-\d+", n) is not None)
    except Exception:  # not a SolidWorks file we can open: no material, the colours still count
        return out
    out["material"] = _material(streams.get("swXmlContents/KeyWords", b""), config)
    out["configurations"] = configurations(streams.get("swXmlContents/KeyWords", b""))
    ids = sorted(int(n.rsplit("-", 1)[1]) for n in streams if n.startswith("Contents/Config-"))
    if not ids:
        return out
    cid = config if config in ids else ids[0]
    data = streams[f"Contents/Config-{cid}"]
    if out["material"]:
        out["density"] = density_for(out["material"], _density(data))
    out["appearances"] = _appearances(data)
    return out


# Typical densities (kg/m³) by material family, for a part whose stored density is missing or left at
# SolidWorks' unset value of 1000 although its material is something else (seen in sample files).
FAMILY_DENSITY = (
    (r"rubber|water|neoprene|silicone", 1000), (r"gold", 19300), (r"silver", 10500), (r"tungsten", 19250),
    (r"brass", 8500), (r"bronze", 8800), (r"copper", 8900), (r"nickel|inconel|monel", 8400),
    (r"titanium|ti-6al", 4430), (r"magnesium", 1800), (r"zinc", 7130), (r"lead", 11340), (r"tin\b", 7300),
    (r"stainless|aisi 3|aisi 4\d\d\b|17-4|15-5|aisi 2\d\d\b", 8000),
    (r"cast iron|gray iron|grey iron|ductile|malleable", 7200),
    (r"steel|aisi|sae|iron|a36|1018|1020|1045|4130|4140|4340", 7850),
    (r"alumin|^\d{4}([- ]|$)|\d{4} alloy|\d{4}-[ot]\d", 2700),
    (r"nylon|pa6|pa66", 1140), (r"abs", 1050), (r"polycarbonate|\bpc\b", 1200), (r"acrylic|pmma", 1190),
    (r"pbt", 1300), (r"pvc", 1380), (r"acetal|delrin|pom", 1410), (r"peek", 1300), (r"ptfe|teflon", 2200),
    (r"polypropylene|\bpp\b", 900), (r"polyethylene|hdpe|ldpe|\bpe\b", 950), (r"glass", 2500),
    (r"oak|ash|maple|walnut|cherry|wood|pine|balsa", 700),
)


def family_density(material):
    name = (material or "").lower()
    return next((d for pattern, d in FAMILY_DENSITY if re.search(pattern, name)), None)


def density_for(material, stored):
    """The density to use for a material (kg/m³): the stored one, unless it is the unset 1000 for a
    material that is clearly not ~1000 (then its family's typical value)."""
    family = family_density(material)
    if stored is None or (stored == 1000.0 and family is not None and abs(family - 1000) > 100):
        return float(family) if family else stored
    return stored


def configurations(keywords):
    """[{"id": Config-<n> id, "name": "LONG"}, ...]: a part's configurations, in the file's order."""
    text = keywords.decode("utf-8", "replace")
    found = re.findall(r'<Configuration id="(\d+)" Name="([^"]*)"[^>]*Type="ConfigurationManager"', text)
    unescape = lambda s: s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")
    return [{"id": int(cid), "name": unescape(name)} for cid, name in found]


def _material(keywords, config):
    text = keywords.decode("utf-8", "replace")
    found = re.findall(r'<Configuration id="(\d+)"[^>]*Type="ConfigurationManager" Material="([^"]*)"', text)
    if not found:
        return None
    pick = next((m for cid, m in found if config is not None and int(cid) == config), found[0][1])
    name = pick.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"').strip()
    if not name or name == NOT_SET or re.match(r"PW\d", name):  # PW...: an old PhotoWorks code, not a material
        return None
    return name


def _density(data):
    i = data.find(DENSITY_TAG)
    if i < 0 or i + DENSITY_OFFSET + 8 > len(data):
        return None
    value = struct.unpack_from("<d", data, i + DENSITY_OFFSET)[0]
    return value if DENSITY_RANGE[0] <= value <= DENSITY_RANGE[1] else None


def _appearances(data):
    """Appearance names in use, most used first: "satin finish stainless steel", ..."""
    counts = {}
    for raw in re.findall(rb"(?:[\x20-\x7e]\x00){4,}", data):
        text = raw.decode("utf-16-le")
        if not text.lower().endswith(".p2m"):
            continue
        name = re.split(r"[\\/]", text)[-1][:-4].strip().lower()
        if name and not any(name == s or name + ".p2m" == s for s in NOT_A_FINISH):
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts, key=lambda n: -counts[n])
