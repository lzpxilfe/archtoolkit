# -*- coding: utf-8 -*-
"""QGIS-free unit tests for tools/covariate_stats.py (V10 + Spearman + Circular-Linear R^2)."""

from __future__ import annotations

import builtins
import importlib
import math
import sys
import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


@unittest.skipIf(np is None, "numpy unavailable")
class CovariateStatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools import covariate_stats as cs

        cls.cs = cs

    def test_imports_without_qgis(self):
        real_import = builtins.__import__
        saved = sys.modules.pop("tools.covariate_stats", None)

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "qgis" or name.startswith("qgis."):
                raise AssertionError(f"tools.covariate_stats must not import {name}")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = guarded_import
        try:
            mod = importlib.import_module("tools.covariate_stats")
            self.assertTrue(hasattr(mod, "compute_vif"))
        finally:
            builtins.__import__ = real_import
            if saved is not None:
                sys.modules["tools.covariate_stats"] = saved

    def test_vif_matches_analytic_two_var_and_intercept_ols(self):
        rng = np.random.default_rng(13)
        x1 = rng.normal(100.0, 15.0, 120)
        x2 = 2.0 * x1 + 50.0 + rng.normal(0.0, 5.0, 120)
        X2 = np.column_stack([x1, x2])
        r = float(self.cs.compute_pearson_matrix(X2)[0, 1])
        expected_vif = 1.0 / (1.0 - r * r)
        vifs = self.cs.compute_vif(X2)
        self.assertAlmostEqual(vifs[0], expected_vif, places=9)
        self.assertAlmostEqual(vifs[1], expected_vif, places=9)

        # Affine collinearity with intercept offset: x3 = 3*x1 + 25 -> exact VIF = inf.
        X_col = np.column_stack([x1, 3.0 * x1 + 25.0, rng.normal(0.0, 1.0, 120)])
        v_col = self.cs.compute_vif(X_col)
        self.assertTrue(math.isinf(v_col[0]))
        self.assertTrue(math.isinf(v_col[1]))
        self.assertLess(v_col[2], 1.2)

        # Zero-variance column: inf by default, nan when configured.
        X_const = np.column_stack([x1, np.full_like(x1, 42.0), x2])
        self.assertTrue(math.isinf(self.cs.compute_vif(X_const)[1]))
        self.assertTrue(math.isnan(self.cs.compute_vif(X_const, constant_value=math.nan)[1]))

    def test_rankdata_average_and_spearman_monotonic(self):
        ranks = self.cs.rankdata_average([10.0, 20.0, 20.0, 40.0])
        np.testing.assert_allclose(ranks, [1.0, 2.5, 2.5, 4.0], atol=1e-12)

        x = np.linspace(0.5, 6.0, 50)
        y = np.exp(x)
        X = np.column_stack([x, y])
        pearson = self.cs.compute_pearson_matrix(X)[0, 1]
        spearman = self.cs.compute_spearman_matrix(X)[0, 1]
        self.assertLess(pearson, 0.9)
        self.assertAlmostEqual(spearman, 1.0, places=12)

    def test_mardia_circular_linear_r2_wraparound_and_flat_exclusion(self):
        angles = np.linspace(0.0, 355.0, 72)
        rad = np.deg2rad(angles)
        linear = 3.0 * np.cos(rad) + 4.0 * np.sin(rad) + 10.0

        res = self.cs.circular_linear_r2(angles, linear)
        self.assertAlmostEqual(res["r2"], 1.0, places=10)
        self.assertAlmostEqual(res["r"], 1.0, places=10)
        self.assertEqual(res["n_valid"], 72)
        self.assertEqual(res["n_flat_excluded"], 0)

        # Invariance to 360-degree phase shift + flat cell (-1.0) filtering.
        shifted = (angles + 125.0) % 360.0
        with_flat = np.concatenate([shifted, [-1.0, -1.0, -1.0]])
        lin_flat = np.concatenate([linear, [999.0, -500.0, 0.0]])
        res_flat = self.cs.circular_linear_r2(with_flat, lin_flat)
        self.assertAlmostEqual(res_flat["r2"], 1.0, places=10)
        self.assertEqual(res_flat["n_valid"], 72)
        self.assertEqual(res_flat["n_flat_excluded"], 3)

        # Insufficient valid pairs returns NaN.
        res_small = self.cs.circular_linear_r2([10.0, -1.0, 20.0], [1.0, 2.0, 3.0])
        self.assertTrue(math.isnan(res_small["r2"]))
        self.assertEqual(res_small["n_valid"], 2)


if __name__ == "__main__":
    unittest.main()
