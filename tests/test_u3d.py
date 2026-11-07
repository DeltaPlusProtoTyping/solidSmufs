"""The U3D reader: its coder and its rules on small made-up data, and on real files where this PC has some."""

import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from solidsmufs.formats import u3d  # noqa: E402
from solidsmufs.formats.u3d import rhadobe, stream  # noqa: E402
from solidsmufs.kernel import meshio  # noqa: E402
from solidsmufs.kernel.worker import Session  # noqa: E402

# the public samples aren't in the project, since they carry no stated license: point this at a folder holding them
SAMPLES = Path(os.environ.get("SOLIDSMURFS_U3D_SAMPLES", ""))


def sample(name):
    p = SAMPLES / name
    return p if os.environ.get("SOLIDSMURFS_U3D_SAMPLES") and p.is_file() else None


def string(text):
    raw = text.encode()
    return struct.pack("<H", len(raw)) + raw


def block(kind, body):
    pad = bytes(-len(body) & 3)
    return struct.pack("<III", kind, len(body), 0) + body + pad


def header(profile=0, units=None):
    body = struct.pack("<hhIIQI", 0, 0, profile | (8 if units else 0), 0, 0, 106)
    if units:
        body += struct.pack("<d", units)
    return block(0x00443355, body)


def declaration(name, faces, points, shadings=((0, 0),)):
    body = string(name) + struct.pack("<II", 0, 1) + struct.pack("<6I", faces, points, 0, 0, 0, 0) + struct.pack("<I", len(shadings))
    for attributes, layers in shadings:
        body += struct.pack("<II", attributes, layers) + struct.pack(f"<{layers}I", *[2] * layers) + struct.pack("<I", 0)
    body += struct.pack("<II", points, points) + struct.pack("<III", 0, 0, 0) + struct.pack("<5f", 0.5, 1, 1, 1, 1)
    return block(u3d.MESH_DECLARATION, body + struct.pack("<3f", 0.9, 0.5, 0.98) + struct.pack("<I", 0))


def base_plain(name, points, faces):
    """A base mesh in "no compression mode", where every field is plain. Normals are excluded by the declaration flag."""
    body = string(name) + struct.pack("<I", 0) + struct.pack("<6I", len(faces), len(points), 0, 0, 0, 0)
    for p in points:
        body += struct.pack("<3f", *p)
    for shading, *corners in faces:
        body += struct.pack("<I", shading) + struct.pack("<3I", *corners)
    return block(u3d.BASE_MESH, body)


def node(name, resource=None, parents=(("", None),), visible=1):
    body = string(name) + struct.pack("<I", len(parents))
    for parent, m in parents:
        m = np.eye(4) if m is None else m
        body += string(parent) + struct.pack("<16f", *m.T.reshape(-1))
    if resource is None:
        return block(u3d.GROUP_NODE, body)
    return block(u3d.MODEL_NODE, body + string(resource) + struct.pack("<I", visible))


def move(x=0.0, y=0.0, z=0.0):
    m = np.eye(4)
    m[:3, 3] = x, y, z
    return m


SQUARE = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))
SQUARE_FACES = ((0, 0, 1, 2), (0, 0, 2, 3))


def plain_file(*blocks, units=None):
    return b"U3D\0" + header(4, units)[4:] + b"".join(blocks)


class Coder(unittest.TestCase):
    def test_plain_values_are_the_bytes_as_they_lie(self):
        s = stream.Stream(struct.pack("<BHIf", 7, 513, 70000, 1.5) + string("hi"))
        self.assertEqual((s.u8(), s.u16(), s.u32(), s.f32(), s.string()), (7, 513, 70000, 1.5, "hi"))

    def test_a_first_adaptive_value_is_an_escape_then_a_plain_value(self):
        s = stream.Stream(struct.pack("<I", 12345) + bytes(8))
        self.assertEqual(s.cu32("c"), 12345)

    def test_an_adaptive_context_counts_what_it_has_seen(self):
        h = stream._Adaptive()
        for v in (34, 34, 34, 7, 6, 35, 6):
            h.add(v)
        self.assertEqual((h.symbols, h.counts, h.total), ([0, 6, 7, 34, 35], [1, 2, 1, 3, 1], 8))

    def test_counts_halve_at_the_limit_keeping_the_escape(self):
        h = stream._Adaptive()
        h.symbols, h.counts, h.total = [0, 5], [1, stream.ELEPHANT - 1], stream.ELEPHANT
        h.add(5)
        self.assertEqual(h.counts, [1, (stream.ELEPHANT - 1) // 2 + 1])
        self.assertEqual(h.total, sum(h.counts))

    def test_symbols_too_big_for_a_histogram_are_never_counted(self):
        h = stream._Adaptive()
        h.add(stream.MAX_ADAPTIVE_SYMBOL)
        self.assertEqual(h.symbols, [0])

    def test_a_range_too_wide_is_a_plain_value(self):
        s = stream.Stream(struct.pack("<I", 99))
        self.assertEqual(s.ranged(stream.STATIC_LIMIT), 99)

    def test_a_range_of_one_holds_nothing_to_read(self):
        s = stream.Stream(bytes(8))
        self.assertEqual(s.ranged(1), 0)
        self.assertEqual(s.pos, 0)

    def test_no_compression_mode_reads_compressed_fields_plain(self):
        s = stream.Stream(struct.pack("<IHB", 5, 6, 7) + struct.pack("<I", 8), plain=True)
        self.assertEqual((s.cu32("a"), s.cu16("b"), s.cu8("c"), s.ranged(100)), (5, 6, 7, 8))


class Predicting(unittest.TestCase):
    def go(self, corners, left=(), right=(), moved=(), stayed=()):
        return u3d._predict(corners, 1, set(left), set(right), set(moved), set(stayed))

    def test_a_new_face_along_an_edge_says_which_side_moves(self):
        self.assertEqual(self.go((1, 2, 3), right=[2]), u3d.MOVE_BY_THIRD)
        self.assertEqual(self.go((1, 2, 3), right=[3]), u3d.STAY_BY_THIRD)
        self.assertEqual(self.go((1, 2, 3), left=[2]), u3d.STAY_BY_THIRD)
        self.assertEqual(self.go((1, 2, 3), left=[3]), u3d.MOVE_BY_THIRD)

    def test_it_goes_by_where_the_split_is_in_the_face(self):
        self.assertEqual(self.go((3, 1, 2), right=[2]), u3d.MOVE_BY_THIRD)
        self.assertEqual(self.go((2, 3, 1), right=[2]), u3d.MOVE_BY_THIRD)

    def test_right_winding_new_faces_are_looked_at_first(self):
        self.assertEqual(self.go((1, 2, 3), left=[2], right=[2]), u3d.MOVE_BY_THIRD)

    def test_failing_that_a_face_follows_what_its_neighbours_did(self):
        self.assertEqual(self.go((1, 2, 3), moved=[3]), u3d.MOVE_BY_NEIGHBOUR)
        self.assertEqual(self.go((1, 2, 3), stayed=[3]), u3d.STAY_BY_NEIGHBOUR)
        self.assertEqual(self.go((1, 2, 3), moved=[2], stayed=[3]), u3d.MOVE_BY_NEIGHBOUR)
        self.assertEqual(self.go((1, 2, 3)), u3d.NO_PREDICTION)


class Scene(unittest.TestCase):
    def read(self, *nodes, units=None):
        mesh = plain_file(declaration("m", 2, 4), base_plain("m", SQUARE, SQUARE_FACES), *nodes, units=units)
        return u3d.read_u3d(mesh)

    def at(self, r):
        return [one.matrix[:3, 3].tolist() for one in r.placed]

    def test_a_base_mesh_comes_through(self):
        r = self.read(node("n", "m"))
        self.assertEqual(len(r.placed), 1)
        np.testing.assert_allclose(sorted(map(tuple, r.placed[0].piece.points)), sorted(map(tuple, np.array(SQUARE, float))))
        self.assertEqual(len(r.placed[0].piece.triangles), 2)

    def test_matrices_multiply_from_the_world_down(self):
        r = self.read(node("g", parents=(("", move(x=1)),)), node("n", "m", parents=(("g", move(y=2)),)))
        self.assertEqual(self.at(r), [[1, 2, 0]])

    def test_a_matrix_is_stored_a_column_at_a_time(self):
        m = np.eye(4)
        m[0, 3] = 5  # translation is the last column
        r = u3d.read_u3d(plain_file(declaration("m", 2, 4), base_plain("m", SQUARE, SQUARE_FACES), node("n", "m", parents=(("", m),))))
        self.assertEqual(self.at(r), [[5, 0, 0]])

    def test_a_node_with_two_parents_is_in_two_places(self):
        r = self.read(node("n", "m", parents=(("", move(x=1)), ("", move(x=5)))))
        self.assertEqual(self.at(r), [[1, 0, 0], [5, 0, 0]])
        self.assertIs(r.placed[0].piece, r.placed[1].piece)

    def test_a_group_reached_twice_doubles_what_is_under_it(self):
        r = self.read(node("g", parents=(("", move(x=1)), ("", move(x=5)))), node("n", "m", parents=(("g", move(z=1)),)))
        self.assertEqual(self.at(r), [[1, 0, 1], [5, 0, 1]])

    def test_no_parents_means_not_in_the_scene_and_not_visible_means_not_shown(self):
        self.assertEqual(self.read(node("n", "m", parents=())).placed, [])
        self.assertEqual(self.read(node("n", "m", visible=0)).placed, [])

    def test_a_loop_is_an_error_not_a_hang(self):
        with self.assertRaises(u3d.U3dError):
            self.read(node("a", parents=(("b", None),)), node("b", "m", parents=(("a", None),)))

    def test_a_mesh_no_node_shows_is_still_shown(self):
        self.assertEqual(self.at(self.read()), [[0, 0, 0]])

    def test_units(self):
        self.assertEqual(self.read(node("n", "m"), units=0.0254).unit_mm, 25.4)
        with_units = self.read(node("n", "m"), units=0.001)
        self.assertEqual(with_units.notices, [])
        without = self.read(node("n", "m"))
        self.assertEqual(without.unit_mm, 1.0)
        self.assertEqual(len(without.notices), 1)

    def test_colours_come_through_shader_and_material(self):
        out = u3d.U3d()
        out.shaders, out.materials = {"s": "mat"}, {"mat": (1.0, 0.5, 0.0)}
        self.assertEqual(u3d._color(out, [["s"]], 0), (1.0, 0.5, 0.0))
        self.assertIsNone(u3d._color(out, [["s"]], 1))
        self.assertIsNone(u3d._color(out, [["other"]], 0))
        self.assertIsNone(u3d._color(out, None, 0))

    def test_a_piece_is_split_when_its_shadings_differ_in_colour(self):
        shader = block(u3d.SHADER, string("s0") + struct.pack("<If4I", 1, 0, 0, 0, 1, 0) + struct.pack("<I", 0) + string("m0"))
        out = plain_file(declaration("m", 2, 4, ((0, 0), (0, 0))), base_plain("m", SQUARE, ((0, 0, 1, 2), (1, 0, 2, 3))),
                         self.shading("n", [["s0"], ["s1"]]), node("n", "m"), shader,
                         block(u3d.SHADER, string("s1") + struct.pack("<If4I", 1, 0, 0, 0, 1, 0) + struct.pack("<I", 0) + string("m1")),
                         self.material("m0", (1, 0, 0)), self.material("m1", (0, 1, 0)))
        r = u3d.read_u3d(out)
        self.assertEqual(sorted(one.color for one in r.placed), [(0.0, 1.0, 0.0), (1.0, 0.0, 0.0)])
        self.assertEqual([len(one.piece.triangles) for one in r.placed], [1, 1])

    @staticmethod
    def shading(name, lists):
        body = string(name) + struct.pack("<III", 0, 1, len(lists))
        for shaders in lists:
            body += struct.pack("<I", len(shaders)) + b"".join(string(x) for x in shaders)
        return block(u3d.SHADING_MODIFIER, body)

    @staticmethod
    def material(name, diffuse):
        return block(u3d.MATERIAL, string(name) + struct.pack("<I", 2) + struct.pack("<3f", 0, 0, 0) + struct.pack("<3f", *diffuse))

    def test_what_isnt_triangles_is_noted(self):
        r = self.read(node("n", "m"), block(u3d.LINE_SET, string("l")), block(0x00000101, string("x")))
        self.assertEqual(r.skipped, {"line sets": 1, "objects in a vendor's own format": 1})
        self.assertEqual(len(r.warnings), 2)

    def test_it_isnt_u3d(self):
        with self.assertRaises(u3d.U3dError):
            u3d.read_u3d(b"PRC" + bytes(40))

    def test_a_damaged_mesh_is_noted_and_the_rest_is_kept(self):
        good = base_plain("m", SQUARE, SQUARE_FACES)
        bad = block(u3d.PROGRESSIVE_MESH, string("m") + struct.pack("<III", 0, 9, 99))  # updates that don't follow on
        r = u3d.read_u3d(plain_file(declaration("m", 2, 4), good, bad, node("n", "m")))
        self.assertEqual(r.damaged, 1)
        self.assertEqual(len(r.placed), 1)
        self.assertTrue(any("couldn't be read to the end" in w for w in r.warnings))

    def test_a_continuation_of_nothing_declared_says_so(self):
        with self.assertRaises(u3d.U3dError):
            u3d.read_u3d(plain_file(base_plain("m", SQUARE, SQUARE_FACES)))


class ThinTriangles(unittest.TestCase):
    """A sheet with a crease down it, and a sliver on one side whose rounded point tips its normal well over."""
    SLIVER_POINTS = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [5, 0.01, 0.05],
                              [0, -10, 10], [10, -10, 10]], float)
    SLIVER_TRIS = np.array([[0, 4, 1], [0, 1, 2], [0, 2, 3], [1, 4, 6], [4, 0, 5], [4, 5, 6]])

    def regions(self, slack):
        regions, _w, _p, _e, _c = meshio._segment(self.SLIVER_POINTS, self.SLIVER_TRIS, slack)
        return regions

    def test_without_slack_a_sliver_is_a_region_of_its_own(self):
        self.assertEqual(len(set(self.regions(0.0).tolist())), 3)

    def test_with_slack_it_joins_a_neighbour_and_the_real_crease_stays(self):
        regions = self.regions(0.1)
        self.assertEqual(len(set(regions.tolist())), 2)
        self.assertEqual(regions[1], regions[2])  # the flat
        self.assertEqual(regions[4], regions[5])  # the steep side
        self.assertNotEqual(regions[1], regions[4])

    def test_a_long_thin_triangle_doesnt_split_a_flat_face(self):
        points = np.array([[0, 0, 0], [10, 0, 0], [10, 0.01, 0.002], [0, 0.01, 0.002], [10, 5, 0], [0, 5, 0], [10, -5, 0], [0, -5, 0]], float)
        tris = np.array([[0, 1, 2], [0, 2, 3], [3, 2, 4], [3, 4, 5], [7, 6, 1], [7, 1, 0]])
        regions, _w, _p, _e, _c = meshio._segment(points, tris, 0.1)
        self.assertEqual(len(set(regions.tolist())), 1)

    def test_a_mesh_of_nothing_but_thin_triangles_is_left_as_it_is(self):
        a, b, c = self.SLIVER_POINTS[[0, 0]], self.SLIVER_POINTS[[1, 1]], self.SLIVER_POINTS[[2, 2]]
        self.assertFalse(meshio._thin_triangles(a, b, c, 100.0).any())


FORM_DECLARATION, FORM_CONTINUATION = 0x101, 0x102


def form_type():
    guid = struct.pack("<IHH", 0x0095467DF, 0xEE24, 0x4C59) + bytes((0x9A, 0xA5, 0x76, 0x8E, 0x39, 0xE2, 0x68, 0xDE))
    return block(u3d.NEW_OBJECT_TYPE, string("Free-Form Object") + struct.pack("<I", 1) + guid + struct.pack("<I", FORM_DECLARATION)
                 + struct.pack("<II", 1, FORM_CONTINUATION) + string("Ecma International") + struct.pack("<I", 0) + string(""))


def form_declaration(name):
    return block(FORM_DECLARATION, string(name) + struct.pack("<II", 0, 0) + struct.pack("<III", 1, 1, 0)
                 + struct.pack("<I", 1) + struct.pack("<III", 0, 0, 0) + struct.pack("<I", 0))


def plain_knots(values, multiplicities):
    out = struct.pack("<I", len(values))
    for v, m in zip(values, multiplicities):
        out += struct.pack("<If", m, v)
    return out


def bilinear(corners):
    """A flat, non-rational patch, degree 1 each way."""
    out = struct.pack("<II", 1, 0) + struct.pack("<II", 1, 1)
    out += plain_knots([0, 1], [2, 2]) * 2 + struct.pack("<II", 2, 2)
    for x, y, z in corners:
        out += struct.pack("<3f", x, y, z)
    return out


def line_segment(a, b):
    return struct.pack("<II", 1 | 4, 1) + plain_knots([0, 1], [2, 2]) + struct.pack("<I", 2) + struct.pack("<4f", *a, *b)


def square_loop(a0, a1):
    corners = [(a0, a0), (a1, a0), (a1, a1), (a0, a1)]
    return struct.pack("<I", 4) + b"".join(line_segment(corners[i], corners[(i + 1) % 4]) for i in range(4))


CORNERS = ((0, 0, 0), (0, 10, 0), (10, 0, 0), (10, 10, 0))  # the V index runs first


class FreeForms(unittest.TestCase):
    def read(self, *faces, corners=CORNERS, placed=True):
        body = string("f") + struct.pack("<I", 0) + struct.pack("<II", 0, 1) + bilinear(corners) + struct.pack("<I", len(faces)) + b"".join(faces)
        items = [form_type(), form_declaration("f"), block(FORM_CONTINUATION, body)]
        if placed:
            items.append(node("n", "f", parents=(("", move(z=5)),)))
        return u3d.read_u3d(plain_file(*items))

    def area(self, piece):
        p, t = piece.points, piece.triangles
        return float(np.linalg.norm(np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]]), axis=1).sum() / 2)

    def test_the_whole_surface_when_a_face_has_no_trim(self):
        r = self.read(struct.pack("<II", 0, 0))
        self.assertEqual(len(r.placed), 1)
        self.assertAlmostEqual(self.area(r.placed[0].piece), 100.0, places=3)
        self.assertEqual(r.placed[0].matrix[2, 3], 5)

    def test_a_trim_loop_cuts_the_surface(self):
        r = self.read(struct.pack("<I", 1) + square_loop(0.25, 0.75) + struct.pack("<I", 0))
        self.assertAlmostEqual(self.area(r.placed[0].piece), 25.0, places=3)

    def test_a_second_loop_is_a_hole(self):
        r = self.read(struct.pack("<I", 2) + square_loop(0, 1) + square_loop(0.25, 0.75) + struct.pack("<I", 0))
        self.assertAlmostEqual(self.area(r.placed[0].piece), 75.0, places=3)

    def test_natural_sides_run_around_the_surface(self):
        sides = struct.pack("<I", 4) + b"".join(struct.pack("<I", side) for side in (32, 16, 64, 8))
        r = self.read(struct.pack("<I", 1) + sides + struct.pack("<I", 0))
        self.assertAlmostEqual(self.area(r.placed[0].piece), 100.0, places=3)

    def test_each_trimmed_face_is_its_own_face(self):
        one = struct.pack("<I", 1) + square_loop(0, 0.5) + struct.pack("<I", 0)
        two = struct.pack("<I", 1) + square_loop(0.5, 1) + struct.pack("<I", 0)
        r = self.read(one, two)
        self.assertEqual(len(set(r.placed[0].piece.faces.tolist())), 2)

    def test_an_object_no_node_shows_is_still_shown(self):
        r = self.read(struct.pack("<II", 0, 0), placed=False)
        self.assertEqual(len(r.placed), 1)

    def test_bezier_knots_repeat_inside(self):
        from solidsmufs.formats.u3d import freeform
        np.testing.assert_allclose(freeform._full_knots(([0, 1, 2], [1, 1, 1]), 2, 5, True), [0, 0, 0, 1, 1, 2, 2, 2])

    def test_uniform_knots_are_spaced_between_full_ends(self):
        from solidsmufs.formats.u3d import freeform
        np.testing.assert_allclose(freeform._full_knots(([0, 3], None), 2, 5, False), [0, 0, 0, 1, 2, 3, 3, 3])

    def test_knots_that_dont_suit_the_control_points_say_so(self):
        from solidsmufs.formats.u3d import freeform
        with self.assertRaises(u3d.U3dError):
            freeform._full_knots(([0, 1], [2, 2]), 1, 7, False)


ADOBE = 0x103


def adobe_type():
    guid = struct.pack("<IHH", 0x96A804A6, 0x3FB9, 0x43C5) + bytes((0xB2, 0xDF, 0x2A, 0x31, 0xB5, 0x56, 0x93, 0x40))
    return block(u3d.NEW_OBJECT_TYPE, string("RHAdobeMeshResource") + struct.pack("<I", 1) + guid + struct.pack("<II", ADOBE, 0)
                 + string("Right Hemisphere Adobe Systems") + struct.pack("<I", 0) + string("version 1.0"))


def adobe_mesh(name, points, triangles, encoding=3):
    """Adobe's layout at its plainest: one material, raw floats stored a coordinate at a time, U8 indices."""
    body = string(name) + bytes([0]) + bytes([0, 0, 0]) + bytes([0b11, len(triangles), len(points)])
    body += bytes([0]) + b"".join(struct.pack(f"<{len(points)}f", *[p[k] for p in points]) for k in range(3))
    flat = [i for t in triangles for i in t]
    body += bytes([encoding, len(flat)]) + bytes(flat)
    return block(ADOBE, body)


@unittest.skipUnless(rhadobe.available(), "the third-party decoder isn't installed")
class AdobeMeshes(unittest.TestCase):
    def test_an_adobe_mesh_comes_through_like_any_other(self):
        r = u3d.read_u3d(plain_file(adobe_type(), adobe_mesh("PartResource", SQUARE, [t[1:] for t in SQUARE_FACES]),
                                    node("Part", "PartResource", parents=(("", move(x=3)),))))
        self.assertEqual(r.adobe, 1)
        self.assertEqual(len(r.placed), 1)
        self.assertEqual(len(r.placed[0].piece.triangles), 2)
        self.assertEqual(r.placed[0].matrix[0, 3], 3)
        np.testing.assert_allclose(r.placed[0].piece.points.max(axis=0), [1, 1, 0])

    def test_names_can_be_any_language(self):
        name, *_rest = rhadobe.decode(adobe_mesh("Pièce", SQUARE, [(0, 1, 2)])[12:])
        self.assertEqual(name, "Pièce")

    def test_an_encoding_it_cant_decode_is_noted_not_fatal(self):
        r = u3d.read_u3d(plain_file(adobe_type(), adobe_mesh("A", SQUARE, [(0, 1, 2)], encoding=8),
                                    declaration("m", 2, 4), base_plain("m", SQUARE, SQUARE_FACES), node("n", "m")))
        self.assertEqual(r.adobe, 0)
        self.assertEqual(len(r.placed), 1)  # the rest of the model still shows
        self.assertTrue(any("Adobe" in w and "8" in w for w in r.warnings))

    def test_a_triangle_off_the_end_of_the_points_is_refused(self):
        with self.assertRaises(u3d.U3dError):
            rhadobe.decode(adobe_mesh("A", SQUARE, [(0, 1, 9)])[12:])


class InAPdf(unittest.TestCase):
    def pdf(self, data, flate):
        body = zlib.compress(data) if flate else data
        extra = b"/Filter/FlateDecode" if flate else b""
        return b"%PDF-1.6\n5 0 obj\n<</Type/3D/Subtype/U3D/Length " + str(len(body)).encode() + extra + b">>stream\n" + body + b"\nendstream\nendobj\n"

    def test_streams_plain_and_compressed(self):
        data = b"U3D\0something"
        self.assertEqual(u3d.streams_in_pdf(self.pdf(data, False)), [data])
        self.assertEqual(u3d.streams_in_pdf(self.pdf(data, True)), [data])

    def test_other_streams_are_left_alone(self):
        self.assertEqual(u3d.streams_in_pdf(b"<</Length 3/Subtype/PRC>>stream\nabc\nendstream"), [])
        self.assertEqual(u3d.streams_in_pdf(self.pdf(b"not it", False)), [])


class ThroughTheWorker(unittest.TestCase):
    def test_a_bare_file_opens_in_mm(self):
        data = plain_file(declaration("m", 2, 4), base_plain("m", SQUARE, SQUARE_FACES), node("n", "m"), units=0.0254)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "square.u3d"
            p.write_bytes(data)
            s = Session()
            meta = s.open(str(p))["meta"]
        self.assertEqual(s.model.kind, "mesh")
        self.assertEqual(meta["stats"]["triangles"], 2)
        np.testing.assert_allclose(s.model.positions.reshape(-1, 3).max(axis=0), [25.4, 25.4, 0], atol=1e-4)


class RealFiles(unittest.TestCase):
    """Whether the block's data ran out where it should is what proves a read: one wrong rule and the coder drifts."""

    def check(self, name, faces, points):
        p = sample(name)
        if p is None:
            self.skipTest("the public U3D samples aren't on this PC")
        r = u3d.read_u3d(p.read_bytes())
        self.assertEqual(r.damaged, 0)
        for m in r.meshes.values():
            self.assertEqual((len(m.faces), len(m.points)), m.declared)
            self.assertLess(m.leftover, 16)
        return r

    def test_progressive_box_is_closed(self):
        r = self.check("box.u3d", 12, 8)
        f = np.array(next(iter(r.meshes.values())).faces)
        edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
        _u, counts = np.unique(edges, axis=0, return_counts=True)
        self.assertTrue((counts == 2).all())

    def test_progressive_part_is_closed(self):
        r = self.check("pdf3d.stream-11.u3d", 6940, 3464)
        m = next(iter(r.meshes.values()))
        self.assertEqual(len(m.faces), 6940)
        self.assertEqual(m.updates, 3464)

    def test_base_meshes_under_a_node_tree(self):
        r = self.check("OD30-04P850-S064459.stream-8.u3d", 0, 0)
        self.assertEqual(len(r.meshes), 127)
        self.assertEqual(len(r.placed), 127)


if __name__ == "__main__":
    unittest.main()
