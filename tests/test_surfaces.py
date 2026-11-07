"""Turning exact surfaces into triangles, on shapes whose answers are known."""

import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from solidsmufs.formats import surfaces as sf  # noqa: E402


def area_of(points, triangles):
    a, b, c = points[triangles[:, 0]], points[triangles[:, 1]], points[triangles[:, 2]]
    return float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2)


def circle(radius, n=64, cx=0.0, cy=0.0, backwards=False):
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    if backwards:
        t = t[::-1]
    return np.column_stack([cx + radius * np.cos(t), cy + radius * np.sin(t)])


class Basis(unittest.TestCase):
    def test_a_partition_of_one(self):
        knots = sf.expand_knots([0, 1, 2, 3], [4, 1, 2, 4])
        _span, n = sf.basis(knots, 3, np.linspace(0, 3, 41))
        np.testing.assert_allclose(n.sum(axis=1), 1.0)

    def test_a_bezier_arc_ends_at_its_end_points(self):
        knots = [0, 0, 0, 1, 1, 1]
        control = [[0, 0], [1, 2], [2, 0]]
        p = sf.curve_points(knots, 2, control, [0.0, 0.5, 1.0])
        np.testing.assert_allclose(p, [[0, 0], [1, 1], [2, 0]])

    def test_a_rational_quarter_is_a_true_circle(self):
        w = [1, math.sqrt(0.5), 1]
        p = sf.curve_points([0, 0, 0, 1, 1, 1], 2, [[1, 0], [1, 1], [0, 1]], np.linspace(0, 1, 21), w)
        np.testing.assert_allclose(np.linalg.norm(p, axis=1), 1.0)

    def test_the_last_knot_is_reached_not_passed(self):
        p = sf.curve_points([0, 0, 1, 2, 2], 1, [[0, 0], [1, 1], [2, 0]], [2.0, 5.0, -1.0])
        np.testing.assert_allclose(p, [[2, 0], [2, 0], [0, 0]])

    def test_a_surface_matches_its_curves(self):
        c = np.array([[[x, y, x * y] for y in range(3)] for x in range(3)], float)
        k = [0, 0, 0, 1, 1, 1]
        p = sf.surface_points(k, 2, k, 2, c, [0, 1, 0.5], [0, 1, 0.5])
        np.testing.assert_allclose(p, [[0, 0, 0], [2, 2, 4], [1, 1, 1]])

    def test_a_rational_surface_is_a_true_cylinder(self):
        s = math.sqrt(0.5)
        c = np.array([[[1, 0, z], [1, 1, z], [0, 1, z]] for z in (0.0, 5.0)])
        w = np.array([[1, s, 1], [1, s, 1]])
        p = sf.surface_points([0, 0, 1, 1], 1, [0, 0, 0, 1, 1, 1], 2, c, [0.3, 0.7, 1.0], [0.1, 0.5, 0.9], w)
        np.testing.assert_allclose(np.hypot(p[:, 0], p[:, 1]), 1.0)


class Flat(unittest.TestCase):
    def test_a_plate_with_a_hole_has_the_right_area(self):
        outer = sf.box_loop(-5, 5, -5, 5, 4)
        points, tris = sf.triangulate([outer, circle(2.0, 128)])
        xyz = np.column_stack([points, np.zeros(len(points))])
        self.assertAlmostEqual(area_of(xyz, tris), 100 - sf.signed_area(circle(2.0, 128)), delta=1e-9)

    def test_the_biggest_loop_is_outside_whichever_comes_first(self):
        points, tris = sf.triangulate([circle(2.0, 64), sf.box_loop(-5, 5, -5, 5, 4)])
        xyz = np.column_stack([points, np.zeros(len(points))])
        self.assertAlmostEqual(area_of(xyz, tris), 100 - sf.signed_area(circle(2.0, 64)), delta=1e-9)

    def test_loops_keep_exactly_their_own_points(self):
        loop = sf.box_loop(0, 4, 0, 4, 3)
        points, _tris = sf.triangulate([loop])
        self.assertEqual(len(points), len(loop))

    def test_two_holes(self):
        holes = [circle(1, 64, 3, 3), circle(1, 64, 7, 7)]
        points, tris = sf.triangulate([sf.box_loop(0, 10, 0, 10, 2), *holes])
        xyz = np.column_stack([points, np.zeros(len(points))])
        self.assertAlmostEqual(area_of(xyz, tris), 100 - 2 * sf.signed_area(holes[0]), delta=1e-9)

    def test_nothing_to_mesh(self):
        for loops in ([], [np.zeros((2, 2))], [np.zeros((5, 2))]):
            _points, tris = sf.triangulate(loops)
            self.assertEqual(len(tris), 0)

    def test_a_loop_crossing_itself_still_finishes(self):
        bow_tie = np.array([[0, 0], [4, 4], [4, 0], [0, 4], [-1, 2.0]])
        tangle = np.random.default_rng(3).random((200, 2))
        for loop in (bow_tie, tangle):
            sf.triangulate([loop])  # what comes out is for the caller's area check: it just mustn't hang

    def test_long_runs_in_a_straight_line_make_no_slivers(self):
        along = np.linspace(0, 10, 40, endpoint=False)
        loop = np.vstack([np.column_stack([along, np.zeros(40)]), np.column_stack([10 - along, np.ones(40)])])
        points, tris = sf.triangulate([loop])
        xyz = np.column_stack([points, np.zeros(len(points))])
        self.assertAlmostEqual(area_of(xyz, tris), 9.75 + (10 - 9.75) * 1.0, delta=0.3)
        spans = np.ptp(points[tris][:, :, 0], axis=1)
        self.assertLess(float(spans.max()), 1.0)  # each triangle reaches across the strip, not along it


class OnSurfaces(unittest.TestCase):
    def test_a_trimmed_plane_needs_no_inside_points(self):
        def plane(u, v):
            return np.column_stack([u, v, np.zeros(len(u))])
        points, tris = sf.mesh_surface(plane, [sf.box_loop(0, 10, 0, 10, 4)], 0.01)
        self.assertEqual(len(points), 16)
        self.assertAlmostEqual(area_of(points, tris), 100.0, places=6)

    def test_a_sphere_comes_out_within_tolerance_and_about_the_right_area(self):
        def sphere(u, v):
            return np.column_stack([np.cos(v) * np.cos(u), np.cos(v) * np.sin(u), np.sin(v)])
        box = sf.box_loop(0, 2 * math.pi, -1.2, 1.2, 24)
        points, tris = sf.mesh_surface(sphere, [box], 0.002)
        np.testing.assert_allclose(np.linalg.norm(points, axis=1), 1.0)
        exact = 4 * math.pi * math.sin(1.2)
        self.assertAlmostEqual(area_of(points, tris) / exact, 1.0, delta=0.01)

    def test_a_cylinder_gets_more_cells_around_than_along(self):
        def cylinder(u, v):
            return np.column_stack([np.cos(u), np.sin(u), v])
        cu, cv, _su, _sv = sf.resolution(cylinder, (0, 2 * math.pi, 0, 5), 0.001)
        self.assertGreater(cu, 10)
        self.assertEqual(cv, 1)

    def test_refining_leaves_the_boundary_alone(self):
        def cylinder(u, v):
            return np.column_stack([np.cos(u), np.sin(u), v])
        u = np.linspace(0, 3, 4)
        loop = np.vstack([np.column_stack([u, np.zeros(4)]), np.column_stack([u[::-1], np.full(4, 2.0)])])
        uv, points, tris = sf.mesh_surface_uv(cylinder, [loop], 1e-4)
        self.assertGreater(len(uv), len(loop))  # it did refine
        edges = np.sort(np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1)
        pairs, counts = np.unique(edges, axis=0, return_counts=True)
        outside = pairs[counts == 1]
        self.assertEqual(len(outside), len(loop))
        self.assertTrue((outside < len(loop)).all())

    def test_it_faces_the_way_the_parameters_run(self):
        def plane(u, v):
            return np.column_stack([u, v, np.zeros(len(u))])
        for loop in (sf.box_loop(0, 1, 0, 1, 2), sf.box_loop(0, 1, 0, 1, 2)[::-1]):
            points, tris = sf.mesh_surface(plane, [loop], 0.01)
            a, b, c = points[tris[:, 0]], points[tris[:, 1]], points[tris[:, 2]]
            self.assertTrue((np.cross(b - a, c - a)[:, 2] > 0).all())


if __name__ == "__main__":
    unittest.main()
