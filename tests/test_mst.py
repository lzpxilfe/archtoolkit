# -*- coding: utf-8 -*-
"""QGIS-free unit tests for tools/mst.py (V13)."""

from __future__ import annotations

import builtins
import importlib
import math
import sys
import unittest


class MstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools import mst

        cls.mst = mst

    def test_imports_without_qgis(self):
        real_import = builtins.__import__
        saved = sys.modules.pop("tools.mst", None)

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "qgis" or name.startswith("qgis."):
                raise AssertionError(f"tools.mst must not import {name}")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = guarded_import
        try:
            mod = importlib.import_module("tools.mst")
            self.assertTrue(hasattr(mod, "kruskal_mst"))
        finally:
            builtins.__import__ = real_import
            if saved is not None:
                sys.modules["tools.mst"] = saved

    def test_known_weighted_mst(self):
        # 4 nodes: triangle (0,1,2) with weights 1, 2, 5 + tail (2,3) weight 3 -> MST total=6.
        edges = [(1.0, 0, 1), (2.0, 1, 2), (5.0, 0, 2), (3.0, 2, 3), (math.nan, 0, 3), (4.0, 1, 1)]
        res = self.mst.kruskal_mst(4, edges)
        self.assertTrue(res["complete"])
        self.assertEqual(res["components"], 1)
        self.assertEqual(res["edges"], [(0, 1), (1, 2), (2, 3)])
        self.assertAlmostEqual(res["total_weight"], 6.0, places=12)

    def test_disconnected_graph_reports_incomplete_and_component_count(self):
        # 5 nodes forming two components {0,1,2} and {3,4}.
        edges = [(2.0, 0, 1), (3.0, 1, 2), (4.0, 0, 2), (1.5, 3, 4)]
        res = self.mst.kruskal_mst(5, edges)
        self.assertFalse(res["complete"])
        self.assertEqual(res["components"], 2)
        self.assertEqual(res["edges"], [(3, 4), (0, 1), (1, 2)])
        self.assertAlmostEqual(res["total_weight"], 6.5, places=12)

    def test_empty_and_singleton_graphs(self):
        r0 = self.mst.kruskal_mst(0, [])
        self.assertTrue(r0["complete"])
        self.assertEqual(r0["components"], 0)
        self.assertEqual(r0["edges"], [])

        r1 = self.mst.kruskal_mst(1, [(10.0, 0, 0)])
        self.assertTrue(r1["complete"])
        self.assertEqual(r1["components"], 1)
        self.assertEqual(r1["edges"], [])


if __name__ == "__main__":
    unittest.main()
