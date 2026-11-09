"""French on a print, in English, on this computer: a glossary of the words drawings use, longest phrase first.

It isn't a general translator: a word it doesn't know stays in French, and word order stays as written.
"""

import re
import unicodedata

PHRASES = {  # without accents, lower case
    "tolerances generales": "general tolerances", "tolerance generale": "general tolerance", "cotes non tolerancees": "untoleranced dimensions",
    "cotes en mm": "dimensions in mm", "cotes en millimetres": "dimensions in millimeters", "dimensions en mm": "dimensions in mm",
    "sauf indication contraire": "unless otherwise stated", "sauf indication": "unless stated", "sauf specification contraire": "unless otherwise specified",
    "casser les angles": "break edges", "casser les angles vifs": "break sharp edges", "angles vifs": "sharp edges", "aretes vives": "sharp edges",
    "casser les aretes": "break edges", "casser les aretes vives": "break sharp edges", "sans bavure": "free of burrs", "sans bavures": "free of burrs",
    "etat de surface": "surface finish", "traitement thermique": "heat treatment", "traitement de surface": "surface treatment",
    "trempe et revenu": "quenched and tempered", "anodisation dure": "hard anodize", "anodisation noire": "black anodize", "oxydation anodique": "anodizing",
    "oxydation anodique dure": "hard anodizing", "nickelage chimique": "electroless nickel", "zingage": "zinc plating", "brunissage": "black oxide",
    "noir mat": "matte black", "acier inoxydable": "stainless steel", "acier inox": "stainless steel", "acier traite": "heat-treated steel", "acier doux": "mild steel",
    "acier a outils": "tool steel", "fonte grise": "gray cast iron", "alliage d'aluminium": "aluminum alloy", "alliage aluminium": "aluminum alloy",
    "plan de": "drawing of", "numero de plan": "drawing number", "n de plan": "drawing number", "numero de piece": "part number", "reference piece": "part reference",
    "ne pas mettre a l'echelle": "do not scale", "ne pas mesurer sur le plan": "do not scale from the drawing", "ne pas": "do not",
    "dessine par": "drawn by", "verifie par": "checked by", "approuve par": "approved by", "date de creation": "date created", "date de modification": "date modified",
    "indice de revision": "revision", "feuille": "sheet", "format": "size", "vue de face": "front view", "vue de dessus": "top view", "vue de dessous": "bottom view",
    "vue de cote": "side view", "vue de gauche": "left view", "vue de droite": "right view", "vue en coupe": "section view", "vue de detail": "detail view",
    "vue isometrique": "isometric view", "coupe": "section", "taraudage traversant": "through tapped hole", "trou traversant": "through hole", "trou taraude": "tapped hole",
    "trou lisse": "plain hole", "trou borgne": "blind hole", "trou de centrage": "center hole", "lamage": "counterbore", "fraisure": "countersink", "contre-percage": "counterbore",
    "rainure de clavette": "keyway", "bout d'arbre": "shaft end", "sur plat": "across flats", "entre plats": "across flats", "hauteur de": "height of", "profondeur de": "depth of",
    "soudure continue": "continuous weld", "tous les": "all", "toutes les": "all", "pieces par": "pieces per", "pas de": "pitch of", "a droite": "right hand", "a gauche": "left hand",
    "tolerances selon": "tolerances per", "selon norme": "per standard", "suivant norme": "per standard", "selon": "per", "suivant": "per", "voir plan": "see drawing", "voir": "see",
    "certificat matiere": "material certificate", "certificat de conformite": "certificate of conformity", "non cotee": "undimensioned", "non cotees": "undimensioned",
    "non cote": "undimensioned", "brut de": "as-", "tous angles": "all angles", "rayon non cote": "undimensioned radius", "rayons non cotes": "undimensioned radii",
    "ce plan est la propriete de": "this drawing is the property of", "et ne peut etre reproduit ou": "and may not be reproduced or",
    "communique sans son autorisation": "communicated without its", "formelle ecrite": "formal written authorization", "objet de la modification": "reason for change",
    "version initiale": "initial release", "pour courroie": "for belt", "traitement bichromatage": "chromate conversion coating",
    "mise a jour": "update", "zingues blanc": "clear zinc plated", "zingue blanc": "clear zinc plated", "ne peut etre": "may not be",
    "matiere": "material", "ebauche": "rough", "ebavurer": "deburr", "ebavure": "deburred",
}
WORDS = {
    "rainure": "groove", "rainures": "grooves", "centree": "centered", "centrees": "centered", "centre": "centered", "reprise": "rework", "ajout": "added", "ajustement": "fit", "modele": "model",
    "alesages": "bores", "zingue": "zinc plated", "zingues": "zinc plated", "blanc": "white", "noir": "black", "marquages": "markings", "annotation": "note", "propriete": "property", "reproduit": "reproduced",
    "communique": "shared", "autorisation": "authorization", "formelle": "formal", "ecrite": "written", "est": "is", "son": "its",
    "bichromatage": "chromate conversion coating", "flasque": "flange", "flasques": "flanges", "poulie": "pulley", "courroie": "belt", "dents": "teeth", "dent": "tooth", "alu": "aluminum", "larg": "width",
    "lame": "counterbored", "debit": "cut size", "auteur": "author", "site": "site", "modif": "change", "acier": "steel", "inox": "stainless", "inoxydable": "stainless", "aluminium": "aluminum", "laiton": "brass", "bronze": "bronze", "cuivre": "copper", "fonte": "cast iron",
    "titane": "titanium", "plastique": "plastic", "alliage": "alloy", "materiau": "material", "nuance": "grade", "etat": "condition", "brut": "raw", "trempe": "hardened", "revenu": "tempered",
    "recuit": "annealed", "cemente": "case hardened", "rectifie": "ground", "rectification": "grinding", "alese": "reamed", "alesage": "bore", "percage": "drilling", "perce": "drilled",
    "taraudage": "tapped hole", "taraude": "tapped", "filetage": "thread", "filete": "threaded", "tournage": "turning", "fraisage": "milling", "usinage": "machining", "usine": "machined",
    "soudure": "weld", "souder": "weld", "soude": "welded", "pliage": "bend", "plier": "bend", "decoupe": "cut", "decoupage": "cutting", "sciage": "sawing", "laser": "laser", "polissage": "polishing", "poli": "polished",
    "peinture": "paint", "anodise": "anodized", "anodisation": "anodizing", "chromage": "chrome plating", "traitement": "treatment", "revetement": "coating", "durete": "hardness", "rugosite": "roughness",
    "chanfrein": "chamfer", "chanfreins": "chamfers", "conge": "fillet", "conges": "fillets", "rayon": "radius", "rayons": "radii", "diametre": "diameter", "epaisseur": "thickness", "largeur": "width", "longueur": "length",
    "hauteur": "height", "profondeur": "depth", "angle": "angle", "angles": "angles", "cote": "dimension", "cotes": "dimensions", "tolerance": "tolerance", "tolerances": "tolerances", "planeite": "flatness",
    "parallelisme": "parallelism", "perpendicularite": "perpendicularity", "concentricite": "concentricity", "coaxialite": "coaxiality", "symetrie": "symmetry", "battement": "runout", "circularite": "roundness", "cylindricite": "cylindricity",
    "trou": "hole", "trous": "holes", "arbre": "shaft", "axe": "axis", "clavette": "key", "rainure": "groove", "plaque": "plate", "plat": "flat", "barre": "bar", "tube": "tube", "piece": "part", "pieces": "parts", "ensemble": "assembly", "sous-ensemble": "subassembly",
    "assemblage": "assembly", "nomenclature": "parts list", "designation": "description", "description": "description", "repere": "item", "rep": "item", "quantite": "quantity", "qte": "qty", "qt": "qty", "masse": "mass", "poids": "weight", "reference": "reference",
    "ref": "ref", "plan": "drawing", "dessin": "drawing", "dessine": "drawn", "echelle": "scale", "indice": "revision", "revision": "revision", "modification": "change", "modifications": "changes", "client": "customer", "fournisseur": "supplier", "projet": "project",
    "titre": "title", "date": "date", "nom": "name", "verifie": "checked", "approuve": "approved", "controle": "inspected", "visa": "sign-off", "remarque": "note", "remarques": "notes", "note": "note", "notes": "notes", "vue": "view", "detail": "detail",
    "ebavurer": "deburr", "nettoyer": "clean", "graisser": "grease", "marquage": "marking", "marquer": "mark", "gravure": "engraving", "graver": "engrave", "unite": "unit", "unites": "units", "millimetres": "millimeters", "pouces": "inches", "degres": "degrees",
    "generale": "general", "generales": "general", "general": "general", "maxi": "max", "mini": "min", "max": "max", "min": "min", "selon": "per", "norme": "standard", "non": "not", "sans": "without", "avec": "with", "sur": "on", "sous": "under", "pour": "for", "par": "by", "ou": "or", "et": "and", "de": "of", "du": "of the", "des": "of the",
    "le": "the", "la": "the", "les": "the", "l": "the", "d": "of", "un": "a", "une": "a", "a": "at", "au": "to the", "aux": "to the", "en": "in", "dans": "in", "tous": "all", "toutes": "all", "tout": "all", "toute": "all", "ces": "these", "cette": "this", "ce": "this",
}
GRADES = {  # French alloy names, with what they're called here
    "au4g1": "2024", "au4g": "2017A", "az5gu": "7075", "ag3": "5754", "42cd4": "4140", "35cd4": "4135", "xc48": "1045",
    "z2cn18-10": "304L", "z6cn18-09": "304", "z2cnd17-12": "316L", "z6cnd17-12": "316",
}
STRONG = ("matiere", "tolerances generales", "cotes", "ebavurer", "echelle", "indice", "acier", "quantite", "designation", "repere", "filetage", "taraudage",
          "percage", "alesage", "rectifie", "chanfrein", "rugosite", "traitement", "etat de surface", "nomenclature", "dessine", "aluminium", "angles vifs",
          "aretes vives", "non cotees", "sauf indication", "feuille", "piece", "epaisseur", "diametre", "traitement thermique", "planeite", "conge")
ALLOY = re.compile(r"[1-7]\d{3}(?:-?[TtHh]\d+)?", re.I)
_MAX = max(len(k.split()) for k in PHRASES)
_TOKEN = re.compile(r"[A-Za-zÀ-ÿ0-9]+(?:-[A-Za-z0-9]+)*|[^A-Za-zÀ-ÿ0-9]+")


def fix_accents(text):
    """Some CAD PDFs' fonts give é as Ġ, è as ğ, ê as ġ: Latin letters shifted up by 0x37."""
    return "".join(chr(ord(c) - 0x37) if 0x11B <= ord(c) <= 0x136 else c for c in text)


def plain(text):
    """Lower case without accents, ' as a space: 'Matière' -> 'matiere', d'acier -> d acier."""
    t = unicodedata.normalize("NFD", fix_accents(text))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower().replace("’", "'")


def looks_french(lines):
    """Two or more drafting words French only uses, across a print's lines."""
    text = " " + re.sub(r"[^a-z0-9' -]+", " ", plain(" ".join(lines))) + " "
    return sum(1 for w in STRONG if f" {w} " in text) >= 2


def _case(english, original):
    letters = [c for c in original if c.isalpha()]
    return english.upper() if len(letters) > 1 and all(c.isupper() for c in letters) else english


def translate(line):
    """The line in English; words the glossary doesn't know stay as they are, numbers too."""
    parts = _TOKEN.findall(fix_accents(line))
    words = [i for i, p in enumerate(parts) if p[0].isalnum()]
    out, i, n = [], 0, 0
    while n < len(parts):
        if i < len(words) and words[i] == n:
            for k in range(min(_MAX, len(words) - i), 0, -1):  # the longest phrase starting here
                last = words[i + k - 1]
                key = re.sub(r"\s+", " ", plain("".join(parts[n:last + 1])).replace("'", " ")).strip()
                alt = plain("".join(parts[n:last + 1])).strip()
                hit = PHRASES.get(alt) or PHRASES.get(key)
                if hit:
                    out.append(_case(hit, "".join(parts[n:last + 1])))
                    n, i = last + 1, i + k
                    break
            else:
                w = parts[n]
                p = plain(w)
                if p == "a" and w not in ("à", "À"):  # a letter (a revision, a size), not the word
                    out.append(w)
                elif p in GRADES:
                    out.append(f"{w} ({GRADES[p]})")
                else:
                    out.append(_case(WORDS[p], w) if p in WORDS else w)
                n, i = n + 1, i + 1
        else:
            out.append(parts[n])
            n += 1
    return "".join(out)


def changed(line):
    """The English if the glossary knew a real word of it, else None."""
    if not re.search(r"[A-Za-zÀ-ÿ]{3}", line):
        return None
    en = translate(line)
    return en if plain(en) != plain(line) else None


def english_pages(pages):
    """A French print's lines with their English added (so a parser finds both); any other print as it is."""
    if not looks_french([ln for p in pages for ln in p]):
        return pages
    out = []
    for p in pages:
        lines = [x for ln in p for x in (ln, changed(ln)) if x]
        for i, ln in enumerate(p):  # a parts table read bottom up: the alloy sits just above its MATIERE heading
            if plain(ln).strip() == "matiere":
                hit = next((x for x in reversed(p[max(0, i - 8):i]) if ALLOY.fullmatch(x.strip())), None)
                if hit:
                    lines.append(f"MATERIAL: {'ALUMINUM ' if hit.strip()[0] in '23567' else ''}{hit.strip()}")
        out.append(lines)
    return out
