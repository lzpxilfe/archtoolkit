# -*- coding: utf-8 -*-
"""QGIS-free unit and mathematical property tests for tools/kriging_math.py (V3)."""

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
class KrigingMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools import kriging_math as km

        cls.km = km

    def test_imports_without_qgis(self):
        real_import = builtins.__import__
        saved_mod = sys.modules.pop("tools.kriging_math", None)

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "qgis" or name.startswith("qgis."):
                raise AssertionError(f"tools.kriging_math must not import {name}")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = guarded_import
        try:
            mod = importlib.import_module("tools.kriging_math")
            self.assertTrue(hasattr(mod, "build_ok_system"))
        finally:
            builtins.__import__ = real_import
            if saved_mod is not None:
                sys.modules["tools.kriging_math"] = saved_mod

    def test_semivariogram_and_covariance_identities(self):
        nugget = 0.25
        partial_sill = 2.0
        rng = 20.0
        total_sill = nugget + partial_sill
        for model in ("exponential", "spherical", "gaussian"):
            self.assertEqual(
                self.km.semivariogram_value(0.0, model=model, nugget=nugget, partial_sill=partial_sill, rng=rng),
                0.0,
            )
            self.assertAlmostEqual(
                self.km.covariance_value(0.0, model=model, nugget=nugget, partial_sill=partial_sill, rng=rng),
                total_sill,
                places=12,
            )
            hs = np.array([1.0, 10.0, 20.0, 50.0])
            gam = self.km.semivariogram_value(hs, model=model, nugget=nugget, partial_sill=partial_sill, rng=rng)
            cov = self.km.covariance_value(hs, model=model, nugget=nugget, partial_sill=partial_sill, rng=rng)
            np.testing.assert_allclose(gam + cov, total_sill, atol=1e-12)
            self.assertTrue(bool(np.all(np.diff(gam) >= -1e-12)))

        # Spherical model reaches total sill at range.
        self.assertAlmostEqual(
            self.km.semivariogram_value(20.0, model="spherical", nugget=nugget, partial_sill=partial_sill, rng=rng),
            total_sill,
            places=12,
        )
        self.assertAlmostEqual(
            self.km.covariance_value(25.0, model="spherical", nugget=nugget, partial_sill=partial_sill, rng=rng),
            0.0,
            places=12,
        )

    def test_ok_exact_reproduction_zero_and_nonzero_nugget(self):
        coords = np.array(
            [
                [0.0, 0.0],
                [10.0, 0.0],
                [0.0, 10.0],
                [10.0, 10.0],
                [5.0, 5.0],
            ],
            dtype=float,
        )
        values = np.array([10.0, 12.0, 14.0, 16.0, 25.0], dtype=float)
        for model in ("exponential", "spherical", "gaussian"):
            for nugget in (0.0, 0.5):
                A = self.km.build_ok_system(coords, partial_sill=4.0, rng=15.0, nugget=nugget, model=model)
                inv = self.km.invert_ok_system(A, partial_sill=4.0, nugget=nugget)
                self.assertIsNotNone(inv)
                for idx, xy in enumerate(coords):
                    zhat, vv = self.km.solve_ok(
                        inv,
                        coords,
                        values,
                        (float(xy[0]), float(xy[1])),
                        partial_sill=4.0,
                        rng=15.0,
                        nugget=nugget,
                        model=model,
                    )
                    self.assertAlmostEqual(zhat, float(values[idx]), places=7)
                    self.assertAlmostEqual(vv, 0.0, places=7)

                # Unsampled center near (2.5, 2.5): strictly positive variance and finite prediction.
                z_mid, v_mid = self.km.solve_ok(
                    inv,
                    coords,
                    values,
                    (2.5, 2.5),
                    partial_sill=4.0,
                    rng=15.0,
                    nugget=nugget,
                    model=model,
                )
                self.assertTrue(math.isfinite(z_mid))
                self.assertGreater(v_mid, 0.0)

    def test_ok_reproduces_constant_field_and_regularizes_duplicates(self):
        coords = np.array(
            [
                [0.0, 0.0],
                [0.0, 0.0],  # exact duplicate causes singular covariance when nugget=0
                [10.0, 0.0],
                [0.0, 10.0],
                [10.0, 10.0],
            ],
            dtype=float,
        )
        values = np.full(5, 42.5, dtype=float)
        A = self.km.build_ok_system(coords, partial_sill=2.0, rng=15.0, nugget=0.0)
        inv = self.km.invert_ok_system(A, partial_sill=2.0, nugget=0.0)
        self.assertIsNotNone(inv)
        zhat, vv = self.km.solve_ok(inv, coords, values, (4.0, 6.0), partial_sill=2.0, rng=15.0, nugget=0.0)
        self.assertAlmostEqual(zhat, 42.5, places=6)
        self.assertGreaterEqual(vv, 0.0)

    def test_collocated_nonzero_nugget_uses_partial_sill_off_diagonal(self):
        coords = np.array(
            [
                [0.0, 0.0],
                [0.0, 0.0],
                [10.0, 0.0],
                [0.0, 10.0],
            ],
            dtype=float,
        )
        A = self.km.build_ok_system(coords, partial_sill=3.0, rng=15.0, nugget=0.5, model="exponential")
        self.assertAlmostEqual(float(A[0, 0]), 3.5, places=12)
        self.assertAlmostEqual(float(A[0, 1]), 3.0, places=12)
        self.assertAlmostEqual(float(A[1, 0]), 3.0, places=12)
        # Invertible directly without Tikhonov ridge because nugget differentiates C(0) on diagonal.
        inv = self.km.invert_ok_system(A, partial_sill=3.0, nugget=0.5)
        self.assertIsNotNone(inv)
        np.testing.assert_allclose(A @ inv, np.eye(5), atol=1e-10)

    def test_empirical_semivariogram_exact_4pt_calculation(self):
        # 4 collinear points at x = 0, 1, 2, 3 with z = 0, 2, 4, 6.
        coords = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0]], dtype=float)
        values = np.array([0.0, 2.0, 4.0, 6.0], dtype=float)
        emp = self.km.empirical_semivariogram(coords, values, n_lags=2, max_lag=2.0, min_pairs=1)
        # Bins on (0, 2]: (0, 1] -> h=1 has 3 pairs each with dz=2 -> 0.5*4 = 2.0
        # (1, 2] -> h=2 has 2 pairs each with dz=4 -> 0.5*16 = 8.0
        self.assertEqual(emp["pair_counts"], [3, 2])
        self.assertAlmostEqual(emp["lag_centers"][0], 1.0, places=9)
        self.assertAlmostEqual(emp["semivariance"][0], 2.0, places=9)
        self.assertAlmostEqual(emp["lag_centers"][1], 2.0, places=9)
        self.assertAlmostEqual(emp["semivariance"][1], 8.0, places=9)

    def test_fit_variogram_wls_recovers_correlated_field_and_handles_degenerate(self):
        # Degenerate flat terrain refuses WLS fit honestly.
        flat_xy = np.array([[float(i), float(j)] for i in range(5) for j in range(5)])
        flat_z = np.full(len(flat_xy), 100.0)
        flat_fit = self.km.fit_variogram_wls(flat_xy, flat_z)
        self.assertFalse(flat_fit["fitted"])
        self.assertEqual(flat_fit["variogram_source"], "heuristic_fallback")

        # Synthetic spatially correlated Gaussian field from exponential covariance.
        rng = np.random.default_rng(7)
        xs = np.linspace(0.0, 100.0, 10)
        ys = np.linspace(0.0, 100.0, 10)
        grid = np.array([(x, y) for x in xs for y in ys], dtype=float)
        dx = grid[:, 0][:, None] - grid[:, 0][None, :]
        dy = grid[:, 1][:, None] - grid[:, 1][None, :]
        dist = np.sqrt(dx * dx + dy * dy)
        C = self.km.covariance_value(dist, model="exponential", nugget=0.2, partial_sill=5.0, rng=25.0)
        np.fill_diagonal(C, 5.2 + 1e-6)
        L = np.linalg.cholesky(C)
        vals = 50.0 + L @ rng.standard_normal(len(grid))

        fit = self.km.fit_variogram_wls(grid, vals, n_lags=10, min_pairs=10)
        self.assertTrue(fit["fitted"])
        self.assertEqual(fit["variogram_source"], "empirical_wls")
        self.assertIn(fit["model"], self.km.SUPPORTED_VARIOGRAM_MODELS)
        self.assertGreaterEqual(fit["nugget"], 0.0)
        self.assertGreater(fit["partial_sill"], 0.5)
        self.assertGreater(fit["range"], 1.0)
        # Total sill stays physically in the ballpark of the true 5.2 variance.
        total_sill = fit["nugget"] + fit["partial_sill"]
        self.assertGreater(total_sill, 1.5)
        self.assertLess(total_sill, 15.0)

        loocv = self.km.loocv_ordinary_kriging(
            grid,
            vals,
            model=fit["model"],
            nugget=fit["nugget"],
            partial_sill=fit["partial_sill"],
            rng=fit["range"],
            neighbors=16,
        )
        self.assertEqual(loocv["n_evaluated"], len(grid))
        self.assertGreater(loocv["rmse"], 0.0)
        self.assertGreaterEqual(loocv["rmse"], loocv["mae"])
        self.assertIsNotNone(loocv["msdr"])
        # Well-calibrated variogram should have MSDR of order 1 (here within 0.25..4.0).
        self.assertGreater(loocv["msdr"], 0.25)
        self.assertLess(loocv["msdr"], 4.0)


if __name__ == "__main__":
    unittest.main()
