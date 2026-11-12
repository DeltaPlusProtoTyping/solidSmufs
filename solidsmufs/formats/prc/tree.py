"""PRC's structure tree and global data: which part goes where, and in what color.

A file structure's tree lists parts (representation items, each pointing at a tessellation) and product occurrences
(a part or children, a location, perhaps a prototype to look through, perhaps in another file structure). Nothing can
be skipped, as the fields carry no lengths, so everything is stepped over in order. A wrong step shows at once: tags
stop matching, or the section doesn't end where it should.
"""

import numpy as np

from .bits import PrcError
from .schema import extend

TYPE_BASE_WITH_GRAPHICS = 2
TYPE_MISC_ATTRIBUTE = 201
TYPE_CARTESIAN, TYPE_ENTITY_REF, TYPE_LINKED_ITEM, TYPE_REF_PRC_BASE, TYPE_REF_TOPOLOGY, TYPE_GENERAL = 202, 203, 204, 205, 206, 207
TYPE_RI_REPRESENTATION, TYPE_RI_BREP, TYPE_RI_CURVE, TYPE_RI_DIRECTION, TYPE_RI_PLANE, TYPE_RI_POINTS = 231, 232, 233, 234, 235, 236
TYPE_RI_POLY_BREP, TYPE_RI_POLY_WIRE, TYPE_RI_SET, TYPE_RI_COORDS = 237, 238, 239, 240
TYPE_INTERNAL, TYPE_GLOBALS, TYPE_TREE, TYPE_PRODUCT, TYPE_PART, TYPE_FILTER = 302, 303, 304, 310, 311, 320
TYPE_VIEW, TYPE_MARKUP, TYPE_LEADER, TYPE_ANNOTATION_ITEM, TYPE_ANNOTATION_SET, TYPE_ANNOTATION_REF = 501, 502, 503, 504, 505, 506
TYPE_STYLE, TYPE_MATERIAL, TYPE_PICTURE, TYPE_TEXTURE_APPLICATION, TYPE_TEXTURE, TYPE_TEXTURE_TRANSFORM = 701, 702, 703, 711, 712, 713
TYPE_TESS_MARKUP = 176
TYPE_LINE_PATTERN, TYPE_DOTTING, TYPE_HATCHING, TYPE_SOLID, TYPE_VPICTURE = 721, 723, 724, 725, 726
TYPE_LIGHT_AMBIENT, TYPE_LIGHT_POINT, TYPE_LIGHT_DIRECTIONAL, TYPE_LIGHT_SPOT, TYPE_SCENE, TYPE_CAMERA = 731, 732, 733, 734, 741, 742
TYPE_SURF_PLANE = 75 + 11

TRANSLATE, ROTATE, MIRROR, SCALE, NON_UNIFORM, NON_ORTHO, HOMOGENEOUS = 1, 2, 4, 8, 16, 32, 64
MAX_DEPTH = 64
MAX_INSTANCES = 100000


def attributes(b):
    """Skip a list of attributes."""
    for _ in range(b.u()):
        b.u()  # its type tag
        _attribute_title(b)
        for _ in range(b.u()):
            _attribute_title(b)
            kind = b.u()
            if kind in (1, 3):
                b.u()
            elif kind == 2:
                b.double()
            elif kind == 4:
                b.string()
            elif kind == 5:
                b.u()
                b.u()


def _attribute_title(b):
    if b.bit():
        b.u()
    else:
        b.string()


def name_of(b):
    """An entity's name, which may be the same as the last one read."""
    if b.bit():
        return getattr(b, "last_name", "")
    b.last_name = b.string()
    return b.last_name


def _base(b):
    attributes(b)
    return name_of(b)


def _ref_base(b):
    name = _base(b)
    b.u(), b.u(), b.u()
    return name


def _graphics_base(b):
    """(name, line style: biased index in the global styles, or 0)."""
    name = _ref_base(b)
    if not b.bit():  # otherwise as the last ones read
        b.u()  # layer
        b.last_style = b.u()
        b.read(16)
    extend(b, TYPE_BASE_WITH_GRAPHICS)
    return name, getattr(b, "last_style", 0)


def _user_data(b):
    n = b.u()
    if b.i + n > len(b.s):
        raise PrcError("The PRC tree ended early.")
    b.i += n


def _vector(b):
    return b.double(), b.double(), b.double()


def _unique_id(b):
    return b.u(), b.u(), b.u(), b.u()


def _expect(b, tag, what):
    got = b.u()
    if got != tag:
        raise PrcError(f"The PRC tree isn't as expected at {what} ({got}, not {tag}).")


def _transform_3d(b):
    """The matrix of a Cartesian transformation (4 x 4, column vectors)."""
    m = np.eye(4)
    how = b.read(8)
    if how & TRANSLATE:
        m[:3, 3] = _vector(b)
    if how & NON_ORTHO:
        m[:3, 0], m[:3, 1], m[:3, 2] = _vector(b), _vector(b), _vector(b)
    if how & ROTATE:
        x, y = np.array(_vector(b)), np.array(_vector(b))
        m[:3, 0], m[:3, 1] = x, y
        m[:3, 2] = np.cross(y, x) if how & MIRROR else np.cross(x, y)
    if how & NON_UNIFORM:
        m[:3, :3] = m[:3, :3] @ np.diag(_vector(b))
    if how & SCALE:
        m[:3, :3] *= b.double()
    if how & HOMOGENEOUS:
        for k in range(4):
            m[3, k] = b.double()
        if m[3, 3] not in (0.0, 1.0):
            m = m / m[3, 3]
    return m


def _transformation(b):
    tag = b.u()
    if tag == TYPE_CARTESIAN:
        return _transform_3d(b)
    if tag == TYPE_GENERAL:
        return np.array([b.double() for _ in range(16)]).reshape(4, 4).T  # stored column by column
    raise PrcError(f"An unknown transformation in the PRC tree ({tag}).")


# ---------------------------------------------------------------------------------------------- markups, views...
def _ref_on_prc_base_body(b):
    b.u()
    if not b.bit():
        _unique_id(b)
    b.u()


def _ref_on_prc_base(b):
    _expect(b, TYPE_REF_PRC_BASE, "a reference")
    _ref_on_prc_base_body(b)
    extend(b, TYPE_REF_PRC_BASE)


def _reference_data(b):
    tag = b.u()
    if tag == TYPE_REF_TOPOLOGY:
        b.u()
        if b.bit():
            if not b.bit():
                _unique_id(b)
            b.u(), b.u()
            for _ in range(b.u()):
                b.u()
    elif tag == TYPE_REF_PRC_BASE:
        _ref_on_prc_base_body(b)
    else:
        raise PrcError(f"An unknown reference in the PRC tree ({tag}).")


def _entity_reference_content(b):
    _graphics_base(b)
    b.u()
    if b.bit():
        _reference_data(b)


def _entity_reference(b):
    _expect(b, TYPE_ENTITY_REF, "an entity reference")
    _entity_reference_content(b)
    extend(b, TYPE_ENTITY_REF)
    _user_data(b)


def _annotation(b, depth=0):
    if depth > MAX_DEPTH:
        raise PrcError("The PRC annotations nest too deep.")
    tag = b.u()
    _graphics_base(b)
    if tag == TYPE_ANNOTATION_ITEM:
        _ref_on_prc_base(b)
    elif tag == TYPE_ANNOTATION_SET:
        for _ in range(b.u()):
            _annotation(b, depth + 1)
    elif tag == TYPE_ANNOTATION_REF:
        for _ in range(b.u()):
            _ref_on_prc_base(b)
    else:
        raise PrcError(f"An unknown annotation in the PRC tree ({tag}).")
    _user_data(b)


def _markup_data(b):
    for _ in range(b.u()):  # linked items
        _expect(b, TYPE_LINKED_ITEM, "a linked item")
        _entity_reference_content(b)
        if b.bit():
            _reference_data(b)
        b.read(4)
        extend(b, TYPE_LINKED_ITEM)
        _user_data(b)
    for _ in range(b.u()):  # leaders
        _expect(b, TYPE_LEADER, "a leader")
        _graphics_base(b)
        if b.bit():
            _ref_on_prc_base(b)
        if b.bit():
            _ref_on_prc_base(b)
        b.u()
        _user_data(b)
    for _ in range(b.u()):  # markups
        _expect(b, TYPE_MARKUP, "a markup")
        _graphics_base(b)
        b.u(), b.u()
        for _ in range(b.u()):
            _ref_on_prc_base(b)
        for _ in range(b.u()):
            _ref_on_prc_base(b)
        b.u()
        extend(b, TYPE_MARKUP)
        _user_data(b)
    for _ in range(b.u()):
        _annotation(b)


def _plane(b):
    _expect(b, TYPE_SURF_PLANE, "a plane")
    if b.bit():
        attributes(b)
        name_of(b)
        b.u()
    b.u()  # extension
    _transform_3d(b)
    for _ in range(8):  # parameterisation: its domain, then its coefficients
        b.double()


def _light(b, version):
    tag = b.u()
    _ref_base(b)
    b.u(), b.u(), b.u(), b.u()
    if tag == TYPE_LIGHT_POINT:
        _vector(b)
        b.double(), b.double(), b.double()
    elif tag == TYPE_LIGHT_DIRECTIONAL:
        _vector(b)
        if version >= 8030:
            b.double()
    elif tag == TYPE_LIGHT_SPOT:
        _vector(b)
        b.double(), b.double(), b.double()
        _vector(b)
        b.double(), b.double()
    elif tag != TYPE_LIGHT_AMBIENT:
        raise PrcError(f"An unknown light in the PRC tree ({tag}).")


def _scene(b, version):
    _expect(b, TYPE_SCENE, "scene parameters")
    _ref_base(b)
    b.bit()
    for _ in range(b.u()):
        _light(b, version)
    if b.bit():
        _expect(b, TYPE_CAMERA, "a camera")
        _ref_base(b)
        b.bit()
        _vector(b), _vector(b), _vector(b)
        for _ in range(6):
            b.double()
        extend(b, TYPE_CAMERA)
    if b.bit():
        _vector(b)
    for _ in range(b.u()):
        _plane(b)
    b.u(), b.u()
    for _ in range(b.u() * 2):
        b.u()
    b.bit()
    extend(b, TYPE_SCENE)


def _filter(b):
    _expect(b, TYPE_FILTER, "a filter")
    _ref_base(b)
    b.bit()
    b.bit()
    for _ in range(b.u()):
        b.u()
    b.bit()
    for _ in range(b.u()):
        _entity_reference(b)
    extend(b, TYPE_FILTER)
    _user_data(b)


def _view(b, version):
    _expect(b, TYPE_VIEW, "a view")
    _graphics_base(b)
    for _ in range(b.u()):
        _ref_on_prc_base(b)
    _plane(b)
    if version >= 7046 and b.bit():
        _scene(b, version)
    if version >= 7309:
        b.bit()
    if version >= 8016:
        b.bit(), b.bit()
        for _ in range(b.u()):
            _ref_on_prc_base(b)
        for _ in range(b.u()):
            _filter(b)
    extend(b, TYPE_VIEW)
    _user_data(b)


# ---------------------------------------------------------------------------------------------- the tree proper
class Item:
    """A representation item that may hold a tessellation."""

    def __init__(self, name, style, local, tess, children=(), exact=None):
        self.name, self.style, self.local, self.tess, self.children = name, style, local, tess, children
        self.exact = exact  # (context, body), both biased: its exact geometry, if it has any


def _item(b, depth=0):
    if depth > MAX_DEPTH:
        raise PrcError("The PRC items nest too deep.")
    tag = b.u()
    name, style = _graphics_base(b)
    local, tess = b.u(), b.u()
    children = ()
    exact = None
    if tag in (TYPE_RI_BREP, TYPE_RI_CURVE, TYPE_RI_PLANE):
        if b.bit():
            where = b.u(), b.u()
            if tag == TYPE_RI_BREP and where[0] and where[1]:
                exact = where
        if tag == TYPE_RI_BREP:
            b.bit()
    elif tag == TYPE_RI_DIRECTION:
        if b.bit():
            b.u(), b.u()
        _user_data(b)
        if b.bit():
            _vector(b)
        _vector(b)
    elif tag == TYPE_RI_POINTS:
        for _ in range(b.u()):
            _vector(b)
    elif tag == TYPE_RI_POLY_BREP:
        b.bit()
    elif tag == TYPE_RI_SET:
        children = [_item(b, depth + 1) for _ in range(b.u())]
    elif tag == TYPE_RI_COORDS:
        _transformation(b)
    elif tag != TYPE_RI_POLY_WIRE:
        raise PrcError(f"An unknown representation item in the PRC tree ({tag}).")
    _user_data(b)
    return Item(name, style, local, tess, children, exact)


def _part(b, version):
    _expect(b, TYPE_PART, "a part")
    name, style = _graphics_base(b)
    for _ in range(6):
        b.double()  # bounding box
    items = [_item(b) for _ in range(b.u())]
    _markup_data(b)
    for _ in range(b.u()):
        _view(b, version)
    extend(b, TYPE_PART)
    _user_data(b)
    return {"name": name, "style": style, "items": items}


def _file_identifier(b):
    """The file structure named, or None for this one."""
    return None if b.bit() else _unique_id(b)


def _product(b, version):
    _expect(b, TYPE_PRODUCT, "a product occurrence")
    name, style = _graphics_base(b)
    part = b.u()
    prototype = b.u()
    prototype_file = _file_identifier(b) if prototype else None
    external = b.u()
    external_file = _file_identifier(b) if external else None
    children = [b.u() for _ in range(b.u())]
    b.read(8)  # behaviour
    b.bit()
    b.double()  # unit
    b.read(8)
    b.u()  # load status
    location = _transformation(b) if b.bit() else None
    for _ in range(b.u()):
        _entity_reference(b)
    _markup_data(b)
    for _ in range(b.u()):
        _view(b, version)
    if b.bit():
        _filter(b)
    for _ in range(b.u()):
        _filter(b)
    for _ in range(b.u()):
        _scene(b, version)
    extend(b, TYPE_PRODUCT)
    _user_data(b)
    return {"name": name, "style": style, "part": part, "prototype": prototype, "prototype_file": prototype_file,
            "external": external, "external_file": external_file, "children": children, "location": location}


def read_tree(b, version):
    """(parts, products) of one file structure's tree section."""
    _expect(b, TYPE_TREE, "the tree")
    _base(b)
    parts = [_part(b, version) for _ in range(b.u())]
    products = [_product(b, version) for _ in range(b.u())]
    _expect(b, TYPE_INTERNAL, "the tree's end")
    _base(b)
    b.u(), b.u()
    extend(b, TYPE_INTERNAL)
    _user_data(b)
    if b"1" in b.s[b.i:]:  # only zero padding may follow
        raise PrcError(f"The PRC tree ended before its section did ({len(b.s) - b.i} bits left).")
    return parts, products


# ---------------------------------------------------------------------------------------------- global data
def read_globals(b, version):
    """What the tree needs from a file structure's globals: {"colors", "styles", "materials", "coords"}. The section's
    schema has been read already."""
    out = {"colors": [], "styles": [], "materials": [], "coords": []}
    _expect(b, TYPE_GLOBALS, "the globals")
    _base(b)
    for _ in range(b.u()):
        _unique_id(b)
    b.double(), b.double()  # tessellation chord height and angle
    b.string()  # default font
    for _ in range(b.u()):
        b.string()
        b.u()
        for _ in range(b.u()):
            b.u()
            b.read(8)
    out["colors"] = [_vector(b) for _ in range(b.u())]
    for _ in range(b.u()):
        _expect(b, TYPE_PICTURE, "a picture")
        _base(b)
        b.u(), b.u(), b.u(), b.u()
        extend(b, TYPE_PICTURE)
    for _ in range(b.u()):
        _texture(b)
    for _ in range(b.u()):
        tag = b.u()
        _ref_base(b)
        if tag == TYPE_MATERIAL:
            b.u()
            diffuse = b.u()
            b.u(), b.u()
            for _ in range(5):
                b.double()
            out["materials"].append((False, diffuse))
        elif tag == TYPE_TEXTURE_APPLICATION:
            under = b.u()  # the material beneath the texture
            b.u(), b.u(), b.u()
            out["materials"].append((True, under))
        else:
            raise PrcError(f"An unknown material in the PRC globals ({tag}).")
    for _ in range(b.u()):
        _expect(b, TYPE_LINE_PATTERN, "a line pattern")
        _ref_base(b)
        for _ in range(b.u()):
            b.double()
        b.double()
        b.bit()
        extend(b, TYPE_LINE_PATTERN)
    for _ in range(b.u()):
        _expect(b, TYPE_STYLE, "a style")
        _ref_base(b)
        b.double()
        b.bit()
        b.u()
        is_material = b.bit()
        color = b.u()
        for _ in range(4):
            if b.bit():
                b.read(8)
        extend(b, TYPE_STYLE)
        out["styles"].append((is_material, color))
    for _ in range(b.u()):
        _fill(b)
    for _ in range(b.u()):
        _expect(b, TYPE_RI_COORDS, "a coordinate system")
        _graphics_base(b)
        b.u(), b.u()
        out["coords"].append(_transformation(b))
        extend(b, TYPE_RI_COORDS)
        _user_data(b)
    return out


def _texture(b):
    """Step over a texture definition."""
    _expect(b, TYPE_TEXTURE, "a texture")
    _ref_base(b)
    b.u()  # its picture
    dimension = b.read(8)
    if b.i32() == 3:  # a mapping that names an operator
        b.i32()
        if b.bit():
            _simple_transform(b)
    b.u()
    for _ in range(b.u()):
        b.double()
    for _ in range(b.u()):
        b.read(8)
    if b.i32() == 3:  # a blend
        for _ in range(4):
            b.double()
    if b.i32():
        b.i32()
    if b.i32():
        b.i32()
    if b.read(8) & 0x2:  # alpha test
        b.i32()
        b.double()
    b.i32()
    if dimension > 1:
        b.i32()
    if dimension > 2:
        b.i32()
    if b.bit():
        _expect(b, TYPE_TEXTURE_TRANSFORM, "a texture's transformation")
        b.bit(), b.bit(), b.bit()
        how = b.read(8)
        for flag, doubles in ((TRANSLATE, 2), (ROTATE, 4), (SCALE, 1), (NON_UNIFORM, 2), (NON_ORTHO, 4), (HOMOGENEOUS, 3)):
            if how & flag:
                for _ in range(doubles):
                    b.double()
        extend(b, TYPE_TEXTURE_TRANSFORM)
    extend(b, TYPE_TEXTURE)


def _simple_transform(b):
    """A transformation of one kind, named by its flag."""
    how = b.u()
    if how in (TRANSLATE, NON_UNIFORM):
        _vector(b)
    elif how in (ROTATE, MIRROR):
        _vector(b), _vector(b)
    elif how == SCALE:
        b.double()
    elif how:
        raise PrcError(f"An unknown texture transformation in the PRC globals ({how}).")


def _fill(b):
    tag = b.u()
    _ref_base(b)
    b.u()
    if tag == TYPE_DOTTING:
        b.double()
        b.bit()
        b.u()
    elif tag == TYPE_HATCHING:
        for _ in range(b.u()):
            for _ in range(5):
                b.double()
            b.u()
    elif tag == TYPE_SOLID:
        b.bit()
        b.u()
    elif tag == TYPE_VPICTURE:
        b.double(), b.double()
        _expect(b, TYPE_TESS_MARKUP, "a picture pattern's markup")
        b.bit()
        for _ in range(b.u()):
            b.double()
        for _ in range(b.u()):
            b.u()
        for _ in range(b.u()):
            b.string()
        b.string()
        b.read(8)
        extend(b, TYPE_TESS_MARKUP)
    else:
        raise PrcError(f"This PRC file's fill pattern isn't handled ({tag}).")


def style_color(global_data, style):
    """The color of a biased style index: (r, g, b) from 0 to 1, or None."""
    if not global_data or not style or style > len(global_data["styles"]):
        return None
    is_material, index = global_data["styles"][style - 1]
    for _ in range(8 if is_material else 0):  # a texture's material may be another's
        if not 0 < index <= len(global_data["materials"]):
            return None
        is_texture, index = global_data["materials"][index - 1]
        if not is_texture:
            break
    if not index:
        return None
    # indices count the colors' separate components
    at = (index - 1) // 3
    colors = global_data["colors"]
    return tuple(colors[at]) if at < len(colors) else None


# ---------------------------------------------------------------------------------------------- walking it
def placements(files, by_id, roots=()):
    """Where each tessellation goes: [(file number, tessellation number, 4 x 4 matrix, name, color)]; an item with only exact
    geometry has ("exact", context, body), counting from 0, for its tessellation number. `files` holds, per
    file structure, {"parts", "products", "globals"}; `by_id` its number from its id. It starts at the model's active
    roots; a file naming none starts at the last product of the last file structure."""
    out = []
    stack = []
    for uid, index, active in reversed(roots):
        f = by_id.get(uid)
        if active and f is not None and 0 < index <= len(files[f]["products"]):
            stack.append((f, files[f]["products"][index - 1], np.eye(4), "", None, 0))
    if not stack:
        f = len(files) - 1
        if not files[f]["products"]:
            return out
        stack = [(f, files[f]["products"][-1], np.eye(4), "", None, 0)]
    while stack:
        f, product, matrix, name, style, depth = stack.pop()
        if depth > MAX_DEPTH or len(out) > MAX_INSTANCES:
            raise PrcError("The PRC assembly nests too deep.")
        here = f
        for other in (product["prototype_file"], product["external_file"]):
            if other is not None and other in by_id:
                here = by_id[other]
        if product["location"] is not None:
            matrix = matrix @ product["location"]
        name = name or product["name"]
        style = product["style"] or style
        if product["prototype"] and not product["children"]:
            protos = files[here]["products"]
            if 0 < product["prototype"] <= len(protos):
                stack.append((here, protos[product["prototype"] - 1], matrix, name, style, depth + 1))
                continue
        if product["external"] and not product["part"] and not product["prototype"]:
            # what's held in another file structure: this occurrence's own children come on top of it
            elsewhere = files[here]["products"]
            if 0 < product["external"] <= len(elsewhere):
                stack.append((here, elsewhere[product["external"] - 1], matrix, name, style, depth + 1))
        if product["part"]:
            parts = files[here]["parts"]
            if 0 < product["part"] <= len(parts):
                part = parts[product["part"] - 1]
                _place_items(part["items"], here, files, matrix, name or part["name"], part["style"] or style, out)
        for child in reversed(product["children"]):
            products = files[f]["products"]
            if 0 <= child < len(products):
                stack.append((f, products[child], matrix, "", style, depth + 1))
    return out


def _place_items(items, f, files, matrix, name, style, out, depth=0):
    data = files[f]["globals"]
    for item in items:
        m = matrix
        if item.local and data and item.local <= len(data["coords"]):
            m = matrix @ data["coords"][item.local - 1]
        s = item.style or style
        if item.tess:
            out.append((f, item.tess - 1, m, item.name or name, style_color(data, s)))
        elif item.exact:
            out.append((f, ("exact", item.exact[0] - 1, item.exact[1] - 1), m, item.name or name, style_color(data, s)))
        if item.children and depth < MAX_DEPTH:
            _place_items(item.children, f, files, m, name, s, out, depth + 1)
