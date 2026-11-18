# -*- coding: utf-8 -*-
"""QGIS-free unit tests for tools/viewshed_math.py (V12)."""

from __future__ import annotations

import builtins
import importlib
import sys
import unittest


class ViewshedMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools import viewshed_math as vm

        cls.vm = vm

    def test_imports_without_qgis(self):
        real_import = builtins.__import__
        saved = sys.modules.pop("tools.viewshed_math", None)

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "qgis" or name.startswith("qgis."):
                raise AssertionError(f"tools.viewshed_math must not import {name}")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = guarded_import
        try:
            mod = importlib.import_module("tools.viewshed_math")
            self.assertTrue(hasattr(mod, "calculate_gdal_viewshed_cc"))
        finally:
            builtins.__import__ = real_import
            if saved is not None:
                sys.modules["tools.viewshed_math"] = saved

    def test_calculate_gdal_viewshed_cc(self):
        self.assertEqual(self.vm.calculate_gdal_viewshed_cc(False, False, 0.13), 0.0)
        self.assertEqual(self.vm.calculate_gdal_viewshed_cc(True, False, 0.13), 1.0)
        self.assertAlmostEqual(self.vm.calculate_gdal_viewshed_cc(True, True, 0.13), 0.87, places=12)
        # Refraction forces curvature on.
        self.assertAlmostEqual(self.vm.calculate_gdal_viewshed_cc(False, True, 0.13), 0.87, places=12)
        # Clamping bounds [0, 1].
        self.assertEqual(self.vm.calculate_gdal_viewshed_cc(True, True, 2.0), 0.0)
        self.assertEqual(self.vm.calculate_gdal_viewshed_cc(True, True, -0.5), 1.0)

    def test_higuchi_pair_ordering_and_resolution(self):
        self.assertEqual(self.vm.order_higuchi_pair(150.0, 1000.0), (150.0, 1000.0))
        self.assertEqual(self.vm.order_higuchi_pair(1000.0, 150.0), (150.0, 1000.0))
        self.assertEqual(self.vm.order_higuchi_pair(500.0, 500.0), (500.0, 501.0))

        self.assertEqual(self.vm.resolve_higuchi_thresholds(None, None), (150.0, 1000.0))
        self.assertEqual(self.vm.resolve_higuchi_thresholds(2000.0, None), (1000.0, 2000.0))
        self.assertEqual(self.vm.resolve_higuchi_thresholds(None, 50.0), (50.0, 150.0))

    def test_format_higuchi_distance(self):
        self.assertEqual(self.vm.format_higuchi_distance(500.0), "500m")
        self.assertEqual(self.vm.format_higuchi_distance(1000.0), "1km")
        self.assertEqual(self.vm.format_higuchi_distance(2500.0), "2.5km")
        self.assertEqual(self.vm.format_higuchi_distance("bad"), "bad")


if __name__ == "__main__":
    unittest.main()
