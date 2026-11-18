# -*- coding: utf-8 -*-
"""QGIS-free unit and invariant tests for tools/ppa_filters.py (V11)."""

from __future__ import annotations

import builtins
import importlib
import itertools
import random
import sys
import unittest


class PpaFiltersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools import ppa_filters as pf

        cls.pf = pf

    def test_imports_without_qgis(self):
        real_import = builtins.__import__
        saved = sys.modules.pop("tools.ppa_filters", None)

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "qgis" or name.startswith("qgis."):
                raise AssertionError(f"tools.ppa_filters must not import {name}")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = guarded_import
        try:
            mod = importlib.import_module("tools.ppa_filters")
            self.assertTrue(hasattr(mod, "ppa_filter_gabriel"))
        finally:
            builtins.__import__ = real_import
            if saved is not None:
                sys.modules["tools.ppa_filters"] = saved

    def test_obtuse_vs_equilateral_triangle_and_rng_subset_of_gabriel(self):
        # Obtuse triangle: (0,0)-(10,0) with (5,2) -> (5,2) lies inside diametral disk of (0,10),
        # AND is strictly closer (< 10) to both (0,0) and (10,0). Both Gabriel and RNG drop (0, 1).
        pts = [(0.0, 0.0), (10.0, 0.0), (5.0, 2.0)]
        complete = [(0, 1), (0, 2), (1, 2)]
        self.assertEqual(self.pf.ppa_filter_gabriel(pts, complete), [(0, 2), (1, 2)])
        self.assertEqual(self.pf.ppa_filter_rng(pts, complete), [(0, 2), (1, 2)])

        # Equilateral-ish triangle where third point is slightly > 60 deg away from hypotenuse:
        # Height h=6 -> d(0,2)=sqrt(25+36)=sqrt(61) < 10 -> (5,6) outside disk (61+61=122 > 100),
        # so Gabriel keeps all 3! Meanwhile RNG drops (0,1) since sqrt(61) < 10 to both endpoints.
        pts2 = [(0.0, 0.0), (10.0, 0.0), (5.0, 6.0)]
        self.assertEqual(self.pf.ppa_filter_gabriel(pts2, complete), [(0, 1), (0, 2), (1, 2)])
        self.assertEqual(self.pf.ppa_filter_rng(pts2, complete), [(0, 2), (1, 2)])

    def test_cocircular_square_grid_rejects_diagonals_in_strict_gabriel(self):
        pts = [(0.0, 0.0), (10.0, 0.0), (0.0, 10.0), (10.0, 10.0)]
        all_edges = list(itertools.combinations(range(4), 2))
        gab = self.pf.ppa_filter_gabriel(pts, all_edges)
        rng = self.pf.ppa_filter_rng(pts, all_edges)
        perimeter = [(0, 1), (0, 2), (1, 3), (2, 3)]
        self.assertEqual(gab, perimeter)
        self.assertEqual(rng, perimeter)

    def test_colocated_sites_stay_joined_and_rng_subset_gabriel_invariant(self):
        pts_coloc = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0), (5.0, 8.0)]
        edges_coloc = list(itertools.combinations(range(4), 2))
        self.assertIn((2, 3), self.pf.ppa_filter_gabriel(pts_coloc, edges_coloc))
        self.assertIn((2, 3), self.pf.ppa_filter_rng(pts_coloc, edges_coloc))

        rng = random.Random(42)
        rand_pts = [(rng.uniform(0.0, 1000.0), rng.uniform(0.0, 1000.0)) for _ in range(18)]
        all_e = list(itertools.combinations(range(len(rand_pts)), 2))
        g_set = set(self.pf.ppa_filter_gabriel(rand_pts, all_e))
        r_set = set(self.pf.ppa_filter_rng(rand_pts, all_e))
        self.assertTrue(r_set.issubset(g_set))
        self.assertGreaterEqual(len(r_set), len(rand_pts) - 1)


if __name__ == "__main__":
    unittest.main()
