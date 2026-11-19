# -*- coding: utf-8 -*-
"""Comprehensive honest-data regression suite for ArchToolkit 0.1.7 (V15-V24).

Covers every P0/P1 scientific, geospatial, statistical, and reliability fix
introduced in the 0.1.7 full-codebase audit:

- V15: Web Mercator (EPSG:3857) metric rejection & CRS transform fail-closed
- V16: Native-dtype precision-safe NoData sentinels (Float32/Int32/UInt32)
- V17: Cost models (Herzog Joules, 70° cliff barrier, Pandolf loaded standing
       floor) & cost engine diagonal 1-px NoData / high-friction non-tunneling
- V18: Kriging OK matrix equilibration (1500 m DEM), collocated points with
       nugget > 0 (positive variance & exact LOOCV 2*c0), direct Cressie WLS
- V19: Weighted betweenness (no double-pop, 30 km ties, tiny weights 2e-13) &
       PPA RNG scale-invariant 5 km equilateral triangle rotation invariance
- V20: Covariate stats scale-invariant VIF, constant-column guard, and
       circular-linear R^2 df>=4 + exact F-test p-value
- V21: AHP hierarchy methodology report (no flat seed CR, group/local CR table,
       dynamic ±delta%), fractional gap rejection, group strip, OAT bounds
- V22: GeoChem Segment 0 JPEG-noisy Navy survival + mid-grey rejection + dark
       palette protection + CP949 CSV; Geology ZIP CP949 화천/홍천 decoding,
       CRS-less RuntimeError propagation, string LITHO label/conflict tracking
- V23: Trench SAT cell-box overlap catches 5 m/10 m edge cliffs + axial 2θ
       ridge bearing; Viewshed non-square DEM NoData mask alignment; Map Styling
       mixed-geometry filtering in aggregate_features
- V24: Atomic multi-file rollback + sticky-bit 0o1777 safe mode; raster
       semantics distance_geology & 41-class landcover; North-Up GeoTransform
       validator; TPI min_valid_fraction masking.
"""

from __future__ import annotations

import math
import os
import shutil
import stat
import tempfile
import unittest
import zipfile
from unittest import mock

import numpy as np

from tools import ahp_core
from tools import atomic_output
from tools import cost_engine
from tools import cost_models
from tools import covariate_stats
from tools import geochem_legend
from tools import kriging_math
from tools import network_metrics
from tools import ppa_filters
from tools import raster_grid_contract
from tools import raster_semantics
from tools import terrain_math

QGIS_AVAILABLE = False
QGIS_IMPORT_ERROR = None
try:
    from osgeo import gdal, osr
    from qgis.PyQt import QtWidgets
    from qgis.core import (
        QgsApplication,
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsFeature,
        QgsField,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsVectorLayer,
    )
    from qgis.gui import QgsMapCanvas
    from tools.qtcompat import FT_INT, FT_STRING
    from tools import utils as atk_utils
    from tools import geology_zip_dialog as GZD
    from tools import map_styling_dialog as MSD
    from tools import trench_suggestion_dialog as TSD
    from tools import viewshed_dialog as VSD
    from tools import ai_aoi_summary

    QGIS_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - dependency-free CI lane
    QGIS_IMPORT_ERROR = exc


class _FakeBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, title, text, level=0, duration=0):
        self.messages.append((str(title), str(text), int(getattr(level, "value", level))))


class _FakeIface:
    def __init__(self, canvas=None):
        self._bar = _FakeBar()
        self._canvas = canvas

    def messageBar(self):
        return self._bar

    def mainWindow(self):
        if not hasattr(self, "_win"):
            self._win = QtWidgets.QMainWindow()
        return self._win

    def mapCanvas(self):
        return self._canvas


# ===========================================================================
# Pure-Python / NumPy Verification Tracks (V16-V22a, V24)
# ===========================================================================


class V16NoDataPrecisionTests(unittest.TestCase):
    """V16: Native-dtype precision-safe NoData matching."""

    def test_nodata_equals_float32_and_int32_sentinels(self):
        # Float32 FLT_MAX negative sentinel upcasted to float64 by GDAL
        arr_f32 = np.array([-3.4028235e38, -9999.9, 0.0, 12.5, -9998.0], dtype=np.float32)
        m_fmax = raster_semantics.nodata_equals(arr_f32, float(np.float32(-3.4028235e38)))
        self.assertEqual(m_fmax.tolist(), [True, False, False, False, False])

        # Float32 -9999.9 declared as float64 -9999.9 (differs at ~1e-4 in float64)
        m_9999 = raster_semantics.nodata_equals(arr_f32, -9999.9)
        self.assertEqual(m_9999.tolist(), [False, True, False, False, False])

        # Int32 / UInt32 exact matching (no float32 24-bit mantissa collision)
        arr_i32 = np.array([-2147483647, -2147483646, 0, 5], dtype=np.int32)
        m_i32 = raster_semantics.nodata_equals(arr_i32, -2147483647)
        self.assertEqual(m_i32.tolist(), [True, False, False, False])

        arr_u32 = np.array([4294967295, 4294967294, 1], dtype=np.uint32)
        m_u32 = raster_semantics.nodata_equals(arr_u32, 4294967295)
        self.assertEqual(m_u32.tolist(), [True, False, False])

    def test_undeclared_nodata_mask_catches_float32_and_int32_sentinels(self):
        arr = np.array([[-3.4028235e38, -9999.9], [0.0, 150.0]], dtype=np.float32)
        nd_mask, count = raster_semantics.undeclared_nodata_mask(arr, None)
        self.assertEqual(count, 2)
        self.assertTrue(nd_mask[0, 0])
        self.assertTrue(nd_mask[0, 1])
        self.assertFalse(nd_mask[1, 0])
        self.assertFalse(nd_mask[1, 1])


class V17CostModelsAndEngineTests(unittest.TestCase):
    """V17: Cost model physics honesty & diagonal barrier non-tunneling."""

    def test_herzog_metabolic_energy_j_is_true_joules(self):
        # On flat ground (s = 0), Minetti/Herzog polynomial C(0) = 1.64 J/(kg*m).
        # For herzog_body_kg = 70 kg over 10 m -> 70 * 1.64 * 10 = 1148 J.
        j70 = cost_models.edge_cost(
            cost_models.MODEL_HERZOG_METABOLIC,
            10.0,
            0.0,
            {"herzog_body_kg": 70.0},
            cost_mode="energy_j",
        )
        j140 = cost_models.edge_cost(
            cost_models.MODEL_HERZOG_METABOLIC,
            10.0,
            0.0,
            {"herzog_body_kg": 140.0},
            cost_mode="energy_j",
        )
        self.assertAlmostEqual(j70, 70.0 * 1.64 * 10.0, places=4)
        self.assertAlmostEqual(j140, 2.0 * j70, places=4)

    def test_pedestrian_cliff_barrier_and_3d_surface_penalty(self):
        # 500 m cliff over 10 m (~88.9 deg) must be impassable (inf), not 10 / 0.05 = 200 s!
        for model in (
            cost_models.MODEL_TOBLER,
            cost_models.MODEL_NAISMITH,
            cost_models.MODEL_HERZOG_METABOLIC,
        ):
            c = cost_models.edge_cost(model, 10.0, 500.0, {}, cost_mode="time_s")
            self.assertTrue(math.isinf(c), f"{model} allowed 500 m cliff climb: {c}")

        # Steep 65 deg slope (dz = 21.445 m over 10 m, 3D dist ~23.66 m) must incur
        # 3D distance penalty at min_speed_mps instead of flat horiz/min_speed.
        dz_65 = 10.0 * math.tan(math.radians(65.0))
        c_65 = cost_models.edge_cost(
            cost_models.MODEL_TOBLER, 10.0, dz_65, {"min_speed_mps": 0.05}, cost_mode="time_s"
        )
        surf_len = math.hypot(10.0, dz_65)
        self.assertGreaterEqual(c_65, surf_len / 0.05 - 1e-6)

    def test_pandolf_downhill_floors_at_loaded_standing_rate(self):
        W, L = 70.0, 20.0
        loaded_stand_w = 1.5 * W + 2.0 * (W + L) * ((L / W) ** 2)
        # Steep downhill (-30%) at 1.0 m/s over 10 m -> 10 s * loaded_stand_w
        e_j = cost_models.edge_cost(
            cost_models.MODEL_PANDOLF,
            10.0,
            -3.0,
            {
                "pandolf_body_kg": W,
                "pandolf_load_kg": L,
                "pandolf_speed_mps": 1.0,
                "pandolf_terrain_factor": 1.0,
            },
            cost_mode="energy_j",
        )
        self.assertGreaterEqual(e_j, 10.0 * loaded_stand_w - 1e-6)
        self.assertGreater(e_j, 10.0 * (1.5 * W) + 50.0)

    def test_diagonal_1px_nodata_wall_cannot_be_tunneled(self):
        # 4x4 flat DEM with an anti-diagonal 1-px NoData barrier from (0,3) to (3,0).
        dem = np.full((4, 4), 100.0, dtype=np.float32)
        nd = np.zeros((4, 4), dtype=bool)
        for k in range(4):
            nd[k, 3 - k] = True
        # Start (0,0) and End (3,3) are separated by the 1-px diagonal wall.
        prev, cost = cost_engine.astar_path(
            dem, nd, (0, 0), (3, 3), 10.0, 10.0, True, cost_models.MODEL_TOBLER, {}
        )
        self.assertTrue(
            cost is None or math.isinf(cost),
            f"A* tunneled diagonally through 1-px NoData wall: cost={cost}",
        )
        self.assertEqual(int(prev[3 * 4 + 3]), -1)

        cost_flat, _prev = cost_engine.dijkstra_full(
            dem, nd, (0, 0), 10.0, 10.0, True, cost_models.MODEL_TOBLER, {}
        )
        self.assertTrue(math.isinf(float(cost_flat[3 * 4 + 3])), "Dijkstra tunneled through 1-px NoData wall")

    def test_diagonal_1px_high_friction_river_cannot_be_bypassed(self):
        # 5x5 flat DEM with a 1-px anti-diagonal river of friction 10000x.
        dem = np.full((5, 5), 100.0, dtype=np.float32)
        nd = np.zeros((5, 5), dtype=bool)
        fric = np.ones((5, 5), dtype=np.float32)
        for k in range(5):
            fric[k, 4 - k] = 10000.0

        prev, cost = cost_engine.astar_path(
            dem, nd, (0, 0), (4, 4), 10.0, 10.0, True, cost_models.MODEL_TOBLER, {},
            friction=fric, friction_min=1.0,
        )
        self.assertGreaterEqual(int(prev[4 * 5 + 4]), 0)
        # Crossing a 10,000x river must cost orders of magnitude more than ~40 m flat walk (~30 s).
        self.assertGreater(cost, 10000.0, f"A* tunneled diagonally across 10,000x river: cost={cost}")

        cost_flat, _ = cost_engine.dijkstra_full(
            dem, nd, (0, 0), 10.0, 10.0, True, cost_models.MODEL_TOBLER, {}, friction=fric
        )
        self.assertGreater(float(cost_flat[4 * 5 + 4]), 10000.0)


class V18KrigingMathTests(unittest.TestCase):
    """V18: OK equilibration, collocated points + nugget > 0, direct Cressie WLS."""

    def test_mountain_dem_high_sill_ok_system_equilibrated(self):
        # 1500 m mountain DEM -> huge sill (~2.5e5) vs Lagrange multiplier 1.0
        rng = np.random.default_rng(42)
        coords = rng.uniform(0.0, 1000.0, size=(20, 2))
        values = 500.0 + 1.0 * coords[:, 0] + 0.5 * coords[:, 1]
        A = kriging_math.build_ok_system(
            coords, partial_sill=250000.0, rng=500.0, nugget=100.0, model="spherical"
        )
        inv = kriging_math.invert_ok_system(A, partial_sill=250000.0, nugget=100.0)
        self.assertIsNotNone(inv, "High-sill mountain DEM OK system collapsed")
        self.assertTrue(np.all(np.isfinite(inv)))
        pred, var = kriging_math.solve_ok(
            inv, coords, values, (float(coords[0, 0]), float(coords[0, 1])),
            partial_sill=250000.0, rng=500.0, nugget=100.0, model="spherical",
        )
        self.assertAlmostEqual(pred, float(values[0]), places=3)
        self.assertGreaterEqual(var, 0.0)

    def test_collocated_points_with_nugget_positive_variance_and_loocv(self):
        coords = np.array([
            [0.0, 0.0],
            [0.0, 0.0],
            [100.0, 0.0],
            [0.0, 100.0],
            [100.0, 100.0],
        ], dtype=np.float64)
        values = np.array([10.0, 20.0, 15.0, 15.0, 15.0], dtype=np.float64)
        c0 = 4.0
        ps = 16.0
        A = kriging_math.build_ok_system(coords, partial_sill=ps, rng=80.0, nugget=c0, model="exponential")
        inv = kriging_math.invert_ok_system(A, partial_sill=ps, nugget=c0)
        self.assertIsNotNone(inv)

        pred, var = kriging_math.solve_ok(
            inv, coords, values, (0.0, 0.0), partial_sill=ps, rng=80.0, nugget=c0, model="exponential"
        )
        self.assertAlmostEqual(pred, 15.0, places=3)
        self.assertGreater(var, 0.0, "Collocated prediction with nugget > 0 must have positive variance")

        # LOOCV leaves out one of the two collocated points at (0,0):
        # predicting the left-out measurement given the collocated twin has
        # minimum variance ~ 2*c0 (nugget of twin + nugget of new measurement).
        cv = kriging_math.loocv_ordinary_kriging(
            coords, values, model="exponential", nugget=c0, partial_sill=ps, rng=80.0, neighbors=5
        )
        self.assertEqual(cv["n_evaluated"], 5)
        self.assertTrue(math.isfinite(cv["rmse"]))
        self.assertIsNotNone(cv["msdr"])
        self.assertGreater(cv["msdr"], 0.0)
        # Verify single-twin leave-one-out variance at collocated point exceeds c0
        # (combining new measurement nugget c0 with conditional process variance > 0,
        # never collapsing to 0.0) and stays bounded by 2*c0.
        A_loo = kriging_math.build_ok_system(coords[1:], partial_sill=ps, rng=80.0, nugget=c0, model="exponential")
        inv_loo = kriging_math.invert_ok_system(A_loo, partial_sill=ps, nugget=c0)
        _zhat_loo, var_loo = kriging_math.solve_ok(
            inv_loo, coords[1:], values[1:], (0.0, 0.0),
            partial_sill=ps, rng=80.0, nugget=c0, model="exponential",
            include_nugget_at_zero=False,
        )
        self.assertGreater(var_loo, c0)
        self.assertLessEqual(var_loo, 2.0 * c0 + 1e-6)
        # Exact closed-form OK variance in the uncorrelated limit (N=4, c0=4, ps=16):
        # 20*w1 + mu = 16, 20*wj + mu = 0 (j=2..4), sum(w)=1 -> mu=-1, w1=0.85
        # sigma^2 = (c0 + ps) - (w1 * ps + mu) = 20 - (0.85*16 - 1) = 7.4 exactly!
        A_lim = kriging_math.build_ok_system(coords[1:], partial_sill=ps, rng=1e-3, nugget=c0, model="exponential")
        inv_lim = kriging_math.invert_ok_system(A_lim, partial_sill=ps, nugget=c0)
        _z_lim, var_lim = kriging_math.solve_ok(
            inv_lim, coords[1:], values[1:], (0.0, 0.0),
            partial_sill=ps, rng=1e-3, nugget=c0, model="exponential",
            include_nugget_at_zero=False,
        )
        self.assertAlmostEqual(var_lim, 7.4, places=6)

    def test_fit_variogram_wls_produces_valid_cressie_fit(self):
        rng = np.random.default_rng(7)
        coords = rng.uniform(0.0, 200.0, size=(60, 2))
        # Spatially smooth field + modest nugget noise
        z = 50.0 + 10.0 * np.sin(coords[:, 0] / 40.0) * np.cos(coords[:, 1] / 40.0) + rng.normal(0.0, 0.8, size=60)
        fit = kriging_math.fit_variogram_wls(coords, z)
        self.assertTrue(fit.get("fitted"), fit)
        self.assertGreater(fit["partial_sill"], 0.0)
        self.assertGreater(fit["range"], 0.0)
        self.assertGreaterEqual(fit["nugget"], 0.0)
        self.assertTrue(math.isfinite(fit["wls_loss"]))


class V19NetworkAndPpaTests(unittest.TestCase):
    """V19: Weighted betweenness precision & PPA RNG scale-invariant tolerance."""

    def test_betweenness_weighted_30km_ties_and_tiny_weights(self):
        # Diamond graph 0 -> {1, 2} -> 3 at 30 km scale with equal total path length
        # Path 0-1-3 = 15000.0 + 15000.000000000002 = 30000.0 (within relative 1e-12)
        # Path 0-2-3 = 15000.0 + 15000.0 = 30000.0
        w_a = 15000.0
        w_b = 15000.0 + 1e-11
        adj_30k = [
            [(1, w_a), (2, w_a)],
            [(0, w_a), (3, w_b)],
            [(0, w_a), (3, w_a)],
            [(1, w_b), (2, w_a)],
        ]
        bc_30k = network_metrics.betweenness_centrality_weighted(n=4, adj=adj_30k)
        self.assertAlmostEqual(bc_30k[1], 0.5, places=6)
        self.assertAlmostEqual(bc_30k[2], 0.5, places=6)

        # Tiny positive weights (2e-13): must NOT collapse to 0-cost cycle!
        eps_w = 2e-13
        adj_tiny = [
            [(1, eps_w), (2, eps_w)],
            [(0, eps_w), (3, eps_w)],
            [(0, eps_w), (3, eps_w)],
            [(1, eps_w), (2, eps_w)],
        ]
        bc_tiny = network_metrics.betweenness_centrality_weighted(n=4, adj=adj_tiny)
        self.assertAlmostEqual(bc_tiny[1], 0.5, places=6)
        self.assertAlmostEqual(bc_tiny[2], 0.5, places=6)

        # Graph with a suboptimal route that triggers stale heap entries (no double-pop)
        adj_stale = [
            [(1, 1.0), (2, 10.0)],
            [(0, 1.0), (2, 1.0)],
            [(0, 10.0), (1, 1.0), (3, 1.0)],
            [(2, 1.0)],
        ]
        bc_stale = network_metrics.betweenness_centrality_weighted(n=4, adj=adj_stale)
        # Unique shortest path 0-1-2-3 -> node 1 sits on (0,2),(0,3)=2 pairs; node 2 sits on (0,3),(1,3)=2 pairs.
        self.assertAlmostEqual(bc_stale[1], 2.0, places=6)
        self.assertAlmostEqual(bc_stale[2], 2.0, places=6)

    def test_ppa_rng_5km_equilateral_triangle_72_rotations(self):
        side = 5000.0
        base = np.array([
            [0.0, 0.0],
            [side, 0.0],
            [side * 0.5, side * math.sqrt(3.0) / 2.0],
        ])
        all_edges = [(0, 1), (1, 2), (0, 2)]
        for deg in range(0, 360, 5):
            th = math.radians(deg)
            rot = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
            pts = (base @ rot.T) + np.array([200000.0, 500000.0])
            kept = ppa_filters.ppa_filter_rng(pts.tolist(), all_edges)
            self.assertEqual(len(kept), 3, f"RNG dropped equilateral edge at {deg} deg: {kept}")


class V20CovariateStatsTests(unittest.TestCase):
    """V20: Constant guard, scale-invariant VIF, circular-linear R^2 F-test."""

    def test_pearson_constant_shifted_column_is_nan(self):
        n = 50
        x = np.linspace(0.0, 10.0, n)
        almost_const = 10000.0 + 1e-13 * np.arange(n, dtype=np.float64)
        R = covariate_stats.compute_pearson_matrix(np.column_stack([x, almost_const]))
        self.assertTrue(math.isnan(float(R[0, 1])), f"Expected NaN for constant shifted column, got {R[0, 1]}")

    def test_vif_mixed_scale_collinear_columns_detected(self):
        rng = np.random.default_rng(123)
        base = rng.normal(0.0, 1.0, size=100)
        x_tiny = base * 1e-3
        x_huge = base * 1e8 + 5.0e7
        x_indep = rng.normal(0.0, 1.0, size=100)
        vifs = covariate_stats.compute_vif(np.column_stack([x_tiny, x_huge, x_indep]))
        self.assertTrue(math.isinf(vifs[0]) or vifs[0] > 1e6, f"Mixed-scale collinear VIF missed: {vifs}")
        self.assertTrue(math.isinf(vifs[1]) or vifs[1] > 1e6, f"Mixed-scale collinear VIF missed: {vifs}")
        self.assertLess(vifs[2], 2.0)

    def test_circular_linear_r2_requires_df_and_exact_pvalue(self):
        # n=3 is underdetermined (3 parameters: intercept, sin, cos) -> NaN
        res3 = covariate_stats.circular_linear_r2([0.0, 90.0, 180.0], [1.0, 2.0, 3.0])
        self.assertTrue(math.isnan(res3["r2"]))
        self.assertTrue(math.isnan(res3["p_value"]))

        # n=40 strong sinusoidal dependence -> R^2 ~ 1.0, p ~ 0
        angles = np.linspace(0.0, 351.0, 40)
        y = 10.0 + 5.0 * np.cos(np.deg2rad(angles - 45.0))
        res = covariate_stats.circular_linear_r2(angles, y)
        self.assertAlmostEqual(res["r2"], 1.0, places=6)
        self.assertAlmostEqual(res["r2_adj"], 1.0, places=6)
        self.assertLess(res["p_value"], 1e-12)

        # Verify exact closed-form p = (1 - R^2)^((n-3)/2)
        rng = np.random.default_rng(9)
        y_noisy = y + rng.normal(0.0, 4.0, size=40)
        res_n = covariate_stats.circular_linear_r2(angles, y_noisy)
        expected_p = (1.0 - res_n["r2"]) ** ((40 - 3) / 2.0)
        self.assertAlmostEqual(res_n["p_value"], expected_p, places=10)


class V21AhpCoreTests(unittest.TestCase):
    """V21: AHP hierarchy report, fractional gap rejection, group strip, OAT bounds."""

    def test_hierarchy_report_hides_flat_seed_and_renders_group_cr(self):
        hier = {
            "groups": ["지형", "수문"],
            "group_cr": 0.042,
            "local_crs": {"지형": 0.015, "수문": None},
            "group_weights": {"지형": 0.6, "수문": 0.4},
            "local_weights": {"지형": {"경사": 0.7, "고도": 0.3}, "수문": {"하천거리": 1.0}},
            "consistency_ratio_group": 0.042,
            "consistency_ratio_local_max": 0.015,
        }
        sens = ahp_core.oat_weight_sensitivity([0.42, 0.18, 0.40], delta=0.15)
        rep = ahp_core.format_ahp_methodology_report(
            criteria=["경사", "고도", "하천거리"],
            weights=[0.42, 0.18, 0.40],
            matrix=[[1, 2, 1], [0.5, 1, 0.5], [1, 2, 1]],
            cr=0.0,
            weights_source="hierarchy",
            hierarchy=hier,
            sensitivity=sens,
        )
        self.assertIn("±15%", rep)
        self.assertIn("0.0420", rep)
        self.assertIn("N/A", rep)
        self.assertIn("계층", rep)
        # Must NOT print the flat matrix's bogus CR=0.0000 as the hierarchy's CR
        self.assertNotIn("0.0000 (PASS)", rep)

    def test_validated_score_ranges_fractional_gaps_and_oat_bounds(self):
        # Continuous fractional gap [0.0, 0.3] -> [0.5, 1.0] must fail
        with self.assertRaises(Exception):
            ahp_core.validated_score_ranges(
                [{"min": 0.0, "max": 0.3, "score": 1.0}, {"min": 0.5, "max": 1.0, "score": 0.5}]
            )

        # Sparse integer codes allowed only when explicitly opted in
        out_sparse = ahp_core.validated_score_ranges(
            [{"min": 100.0, "max": 100.0, "score": 1.0}, {"min": 200.0, "max": 200.0, "score": 0.5}],
            allow_sparse_codes=True,
        )
        self.assertEqual(len(out_sparse), 2)

        # OAT rejects negative / NaN weights and keeps positive others when w*(1+d) >= 1
        with self.assertRaises(ValueError):
            ahp_core.oat_weight_sensitivity([0.5, -0.1, 0.6], delta=0.1)
        sens_hi = ahp_core.oat_weight_sensitivity([0.95, 0.05], delta=0.2)
        self.assertTrue(sens_hi[0]["plus_clamped"])
        for row in sens_hi:
            for w in row["plus_weights"]:
                self.assertGreater(w, 0.0)
            self.assertAlmostEqual(sum(row["plus_weights"]), 1.0, places=9)


class V22aGeoChemLegendTests(unittest.TestCase):
    """V22a: GeoChem Segment 0 absent-grey isolation, dark palette protection, CP949 CSV."""

    FE2O3 = [
        geochem_legend.LegendPoint(0.0, (204, 204, 204)),
        geochem_legend.LegendPoint(3.1, (0, 38, 115)),
        geochem_legend.LegendPoint(3.5, (0, 112, 255)),
        geochem_legend.LegendPoint(12.0, (230, 0, 0)),
        geochem_legend.LegendPoint(51.0, (115, 12, 12)),
    ]

    def test_segment0_preserves_jpeg_noisy_navy_and_rejects_mid_grey(self):
        # JPEG-noisy Navy (3, 41, 118) must map cleanly to 3.1 (not interpolated toward 0.0!).
        # Unrelated mid-grey-blue (110, 120, 150) halfway between (204,204,204) and (0,38,115)
        # must be rejected as NaN!
        r = np.array([3, 110, 204], dtype=np.uint8)
        g = np.array([41, 120, 204], dtype=np.uint8)
        b = np.array([118, 150, 204], dtype=np.uint8)
        out = geochem_legend.interp_rgb_to_value(
            r=r, g=g, b=b, points=self.FE2O3, max_distance=48.0
        )
        self.assertGreaterEqual(float(out[0]), 3.09, f"JPEG-noisy Navy pulled into absent range: {out[0]}")
        self.assertTrue(math.isnan(float(out[1])), f"Unrelated mid-grey accepted via synthetic seg 0: {out[1]}")
        self.assertAlmostEqual(float(out[2]), 0.0, places=4)

    def test_mask_black_lines_protects_dark_palette_stop(self):
        dark_stop = (25, 25, 30)
        r = np.array([[0, dark_stop[0]]], dtype=np.uint8)
        g = np.array([[0, dark_stop[1]]], dtype=np.uint8)
        b = np.array([[0, dark_stop[2]]], dtype=np.uint8)
        mask = geochem_legend.mask_black_lines(r, g, b, palette=[dark_stop])
        self.assertTrue(mask[0, 0], "Pure black line should still be masked")
        self.assertFalse(mask[0, 1], "Dark palette stop must be protected from line masking")

    def test_csv_interior_empty_cells_and_cp949_encoding(self):
        # Row with interior empty cell must NOT shift G/B columns into wrong positions
        rows = [
            ["value", "r", "g", "b"],
            ["3.1", "0", "", "115"],       # malformed missing G -> skipped, not shifted!
            ["3.5", "0", "112", "255"],
            ["12.0", "230", "0", "0"],
        ]
        res = geochem_legend.parse_legend_csv_rows(rows)
        self.assertEqual(len(res.points), 2)
        self.assertEqual(len(res.skipped_rows), 1)

        tmp = tempfile.mkdtemp(prefix="archt_v22_csv_")
        self.addCleanup(shutil.rmtree, tmp, True)
        csv_path = os.path.join(tmp, "legend_cp949.csv")
        with open(csv_path, "wb") as fh:
            fh.write("농도,R,G,B\r\n3.1,0,38,115\r\n12.0,230,0,0\r\n".encode("cp949"))
        res2 = geochem_legend.legend_points_from_csv(csv_path)
        self.assertEqual(len(res2.points), 2)
        self.assertAlmostEqual(res2.points[0].value, 3.1)


class V24InfraAndSemanticsTests(unittest.TestCase):
    """V24: Atomic rollback, sticky-bit modes, raster semantics, North-Up GT, TPI validity."""

    def test_atomic_publish_files_rolls_back_on_partial_failure(self):
        tmp = tempfile.mkdtemp(prefix="archt_v24_atom_")
        self.addCleanup(shutil.rmtree, tmp, True)
        d1 = os.path.join(tmp, "a.tif")
        d2 = os.path.join(tmp, "b.tif")
        s1 = os.path.join(tmp, "a.stage")
        s2 = os.path.join(tmp, "b.stage")
        with open(d1, "wb") as f:
            f.write(b"ORIG_A")
        with open(d2, "wb") as f:
            f.write(b"ORIG_B")
        with open(s1, "wb") as f:
            f.write(b"NEW_A")
        with open(s2, "wb") as f:
            f.write(b"NEW_B")

        real_replace = os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            if os.path.abspath(dst) == os.path.abspath(d2) and os.path.abspath(src) == os.path.abspath(s2):
                raise PermissionError("simulated lock on second destination")
            return real_replace(src, dst)

        with mock.patch("tools.atomic_output.os.replace", side_effect=flaky_replace):
            with self.assertRaises(PermissionError):
                atomic_output.atomic_publish_files([(s1, d1), (s2, d2)])

        with open(d1, "rb") as f:
            self.assertEqual(f.read(), b"ORIG_A", "First destination was NOT rolled back after second failed")
        with open(d2, "rb") as f:
            self.assertEqual(f.read(), b"ORIG_B")

    def test_sticky_bit_shared_modes_never_grant_world_or_group_write(self):
        sticky_dir = 0o1777
        dm = atomic_output._shared_directory_mode(sticky_dir)
        fm = atomic_output._shared_file_mode(sticky_dir)
        self.assertEqual(dm & stat.S_IWOTH, 0)
        self.assertEqual(dm & stat.S_IWGRP, 0)
        self.assertEqual(fm & stat.S_IWOTH, 0)
        self.assertEqual(fm & stat.S_IWGRP, 0)

    def test_raster_semantics_distance_geology_and_41_class_landcover(self):
        # Continuous distance raster named after geology must NOT be categorical!
        self.assertFalse(
            raster_semantics.is_categorical_meta(
                {"tool_id": "distance_raster", "kind": "distance_geology", "units": "m"}
            )
        )
        # Korea 41-class landcover fits inside CLASS_CODE_MAX_DISTINCT = 64
        self.assertTrue(raster_semantics.looks_like_class_codes("Int16", list(range(1, 42))))

    def test_validate_north_up_geotransform(self):
        err_good = raster_grid_contract.validate_north_up_geotransform((200000.0, 10.0, 0.0, 500000.0, 0.0, -10.0))
        self.assertIsNone(err_good)
        err_south = raster_grid_contract.validate_north_up_geotransform((200000.0, 10.0, 0.0, 500000.0, 0.0, 10.0))
        self.assertIsNotNone(err_south)
        err_rot = raster_grid_contract.validate_north_up_geotransform((200000.0, 10.0, 0.5, 500000.0, 0.0, -10.0))
        self.assertIsNotNone(err_rot)

    def test_terrain_math_tpi_min_valid_fraction(self):
        # 7x7 DEM, radius=2 -> 5x5 neighborhood has 24 neighbors.
        # Mask out 10 of 24 neighbors (valid fraction 14/24 = 58.3% < 75%).
        z = np.full((7, 7), 100.0, dtype=np.float64)
        z[3, 3] = 110.0
        nd = np.zeros((7, 7), dtype=bool)
        nd[1, 1:6] = True
        nd[2, 1:6] = True  # 10 neighbors masked -> 14/24 < 0.75
        tpi_strict = terrain_math.focal_tpi(z, radius=2, nodata_mask=nd, min_valid_fraction=0.75)
        self.assertTrue(math.isnan(float(tpi_strict[3, 3])))
        tpi_loose = terrain_math.focal_tpi(z, radius=2, nodata_mask=nd, min_valid_fraction=0.5)
        self.assertAlmostEqual(float(tpi_loose[3, 3]), 10.0, places=6)


# ===========================================================================
# PyQGIS / GDAL Verification Tracks (V15, V22b, V23)
# ===========================================================================


@unittest.skipUnless(QGIS_AVAILABLE, f"PyQGIS/GDAL unavailable: {QGIS_IMPORT_ERROR}")
class V15V22V23QgisHonestDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if QgsApplication.instance() is None:
            prefix = os.environ.get("QGIS_PREFIX_PATH", "").strip()
            if prefix:
                QgsApplication.setPrefixPath(prefix, True)
            cls.app = QgsApplication([], True)
            cls.app.initQgis()
        else:
            cls.app = QgsApplication.instance()
        cls.canvas = QgsMapCanvas()
        cls.canvas.resize(400, 300)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="archt_v017_qgis_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.iface = _FakeIface(self.canvas)
        QgsProject.instance().removeAllMapLayers()
        self.addCleanup(QgsProject.instance().removeAllMapLayers)

    # -- V15 -----------------------------------------------------------------
    def test_v15_pseudo_mercator_rejected_and_transform_fails_closed(self):
        c3857 = QgsCoordinateReferenceSystem("EPSG:3857")
        c5186 = QgsCoordinateReferenceSystem("EPSG:5186")
        c4326 = QgsCoordinateReferenceSystem("EPSG:4326")
        cinvalid = QgsCoordinateReferenceSystem()

        self.assertTrue(atk_utils.is_pseudo_mercator(c3857))
        self.assertFalse(atk_utils.is_metric_crs(c3857))
        self.assertTrue(atk_utils.is_metric_crs(c3857, allow_web_mercator=True))
        self.assertTrue(atk_utils.is_metric_crs(c5186))
        self.assertFalse(atk_utils.is_metric_crs(c4326))
        self.assertFalse(atk_utils.is_metric_crs(cinvalid))
        self.assertIn("3857", atk_utils.describe_non_metric_crs(c3857))

        # Invalid transform must raise, not silently pass through untransformed coords
        ct_bad = QgsCoordinateTransform(cinvalid, c5186, QgsProject.instance())
        with self.assertRaises(RuntimeError):
            atk_utils.transform_point(QgsPointXY(127.0, 37.5), cinvalid, c5186)
        with self.assertRaises(RuntimeError):
            atk_utils.transform_geometry(QgsGeometry.fromPointXY(QgsPointXY(127.0, 37.5)), ct_bad)

    # -- V22b (Geology ZIP) --------------------------------------------------
    def test_v22_geology_cp949_hwacheon_hongcheon_zip_decoding(self):
        # Construct synthetic ZipInfos matching Korean Windows ZIP (no 0x800 flag):
        # CP949 bytes for "화천" (\xc8\xad\xc3\xb5) and "홍천" (\xc8\xab\xc3\xb5)
        # are accidentally valid UTF-8 ("ȭõ", "ȫõ").
        infos = []
        for ko in ("화천/Litho.shp", "홍천/Litho.shp"):
            zi = zipfile.ZipInfo(ko.encode("cp949").decode("cp437"))
            zi.flag_bits = 0
            infos.append(zi)
        # Also test unflagged UTF-8 Korean name (must still decode as Korean, not crash)
        zi_u8 = zipfile.ZipInfo("춘천/Litho.shp".encode("utf-8").decode("cp437"))
        zi_u8.flag_bits = 0
        infos.append(zi_u8)

        changed = GZD._decode_zip_member_names(infos)
        self.assertEqual(changed, 3)
        self.assertEqual([i.filename for i in infos], ["화천/Litho.shp", "홍천/Litho.shp", "춘천/Litho.shp"])

    def test_v22_geology_crsless_rasterize_raises_and_string_code_conflicts(self):
        # 1) CRS-less layer must raise RuntimeError directly in _rasterize_layer
        lyr_nocrs = QgsVectorLayer("Polygon", "NoCrsSheet", "memory")
        lyr_nocrs.setCrs(QgsCoordinateReferenceSystem())
        lyr_nocrs.dataProvider().addAttributes([QgsField("ATK_VAL", FT_INT)])
        lyr_nocrs.updateFields()
        f = QgsFeature(lyr_nocrs.fields())
        f.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 100 0, 100 100, 0 100, 0 0))"))
        f.setAttributes([1])
        lyr_nocrs.dataProvider().addFeatures([f])
        lyr_nocrs.updateExtents()

        dlg = GZD.GeologyZipDialog(self.iface)
        self.addCleanup(dlg.close)
        with self.assertRaises(RuntimeError):
            dlg._rasterize_layer(lyr_nocrs, "ATK_VAL", os.path.join(self.tmp, "out.tif"), 10.0, -9999.0)

        # 2) String LITHO field must collect LITHONAME labels & detect cross-sheet conflicts
        def _sheet(name, rows):
            l = QgsVectorLayer("Polygon?crs=EPSG:5186", name, "memory")
            l.dataProvider().addAttributes([QgsField("LITHO", FT_STRING), QgsField("LITHONAME", FT_STRING)])
            l.updateFields()
            feats = []
            for code, lname in rows:
                ft = QgsFeature(l.fields())
                ft.setGeometry(QgsGeometry.fromWkt("POLYGON((200000 500000,200100 500000,200100 500100,200000 500100,200000 500000))"))
                ft.setAttributes([code, lname])
                feats.append(ft)
            l.dataProvider().addFeatures(feats)
            return l

        s1 = _sheet("S1", [("Qa", "충적층"), ("Kgr", "흑운모화강암")])
        s2 = _sheet("S2", [("Qa", "하성퇴적층"), ("Kgr", "흑운모화강암")])
        mapping, labels, _lall, conflicts = dlg._build_shared_code_mapping([s1, s2], "LITHO", numeric=False)
        self.assertEqual(labels.get("Kgr"), "흑운모화강암")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0][0], "Qa")
        self.assertIn("Qa::충적층", mapping)
        self.assertIn("Qa::하성퇴적층", mapping)

    # -- V23 (Trench SAT, Viewshed Non-Square Mask, Map Styling Mixed Geom) --
    def test_v23_trench_sat_edge_cliff_and_axial_ridge(self):
        # 5 m DEM: column 1 (x=[200005, 200010]) is a 50 deg cliff; col 0 & 2 are 2 deg flat.
        slope_arr = np.full((6, 6), 2.0, dtype=np.float64)
        slope_arr[:, 1] = 50.0
        gt = (200000.0, 5.0, 0.0, 500030.0, 0.0, -5.0)
        win = {"arr": slope_arr, "gt": gt}

        # Narrow 2 m wide trench centered at x=200004.5 (center inside col 0,
        # east edge at x=200005.5 overlaps col 1 by 0.5 m WITHOUT covering col 1's center x=200007.5!)
        trench = QgsGeometry.fromWkt(
            "POLYGON((200003.5 500010, 200005.5 500010, 200005.5 500020, 200003.5 500020, 200003.5 500010))"
        )
        c5186 = QgsCoordinateReferenceSystem("EPSG:5186")
        dlg = TSD.TrenchSuggestionDialog(self.iface)
        self.addCleanup(dlg.close)
        smax, missing = dlg._footprint_slope_max(
            win, trench, QgsPointXY(200004.5, 500015.0), src_crs=c5186, dst_crs=c5186
        )
        self.assertFalse(missing)
        self.assertIsNotNone(smax)
        self.assertGreaterEqual(float(smax), 49.9, f"SAT missed overlapped edge cliff cell: {smax}")

        # Symmetric ridge: col 0..4 aspect=270 deg, crest col 5 flat (-1), col 6..10 aspect=90 deg!
        # Centered on col 5 (x=200027.5), 1st-harmonic vector mean cancels to R=0;
        # axial 2θ fallback must return ~90 or 270 deg with high axial coherence!
        asp_arr = np.full((11, 11), 270.0, dtype=np.float64)
        asp_arr[:, 5] = -1.0
        asp_arr[:, 6:] = 90.0
        slp_arr = np.full((11, 11), 15.0, dtype=np.float64)
        slp_arr[:, 5] = 0.0
        gt_r = (200000.0, 5.0, 0.0, 500055.0, 0.0, -5.0)
        bearing, coh, _ = dlg._footprint_downslope_bearing(
            aspect_win={"arr": asp_arr, "gt": gt_r},
            slope_win={"arr": slp_arr, "gt": gt_r},
            raster_crs=c5186,
            pt=QgsPointXY(200027.5, 500027.5),
            src_crs=c5186,
            radius_m=10.0,
        )
        self.assertIsNotNone(bearing, "Axial 2-theta fallback failed on symmetric ridge")
        self.assertGreater(coh, 0.5)

    def test_v23_viewshed_nonsquare_dem_nodata_mask(self):
        # Non-square DEM: 20 cols (px_x=10) x 10 rows (px_y=20)
        dem_path = os.path.join(self.tmp, "nonsq_dem.tif")
        arr = np.full((10, 20), 100.0, dtype=np.float32)
        arr[8, 12] = -9999.0  # near bottom row!
        ds = gdal.GetDriverByName("GTiff").Create(dem_path, 20, 10, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((200000.0, 10.0, 0.0, 500200.0, 0.0, -20.0))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5186)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(-9999.0)
        band.WriteArray(arr)
        band = None
        ds = None

        dem_lyr = QgsRasterLayer(dem_path, "NonSqDEM", "gdal")
        self.assertTrue(dem_lyr.isValid())
        dlg = VSD.ViewshedDialog(self.iface)
        self.addCleanup(dlg.close)
        # Window covering rows 5..9, cols 10..15 -> (8,12) maps to local row 3, col 2
        win_gt = (200100.0, 10.0, 0.0, 500100.0, 0.0, -20.0)
        nd_mask = dlg._dem_nodata_mask(dem_lyr, win_gt, 6, 5)
        self.assertIsNotNone(nd_mask)
        self.assertEqual(nd_mask.shape, (5, 6))
        self.assertTrue(bool(nd_mask[3, 2]), "Non-square DEM bottom-row NoData was shifted/lost")
        self.assertEqual(int(np.count_nonzero(nd_mask)), 1)

    def test_v23_map_styling_aggregate_features_filters_mixed_geometries(self):
        # Layer 1: LineString road A0023215 (2 lines)
        # Layer 2: Point label with the SAME road code A0023215 (must be skipped, not abort batch!)
        l_lines = QgsVectorLayer("LineString?crs=EPSG:5186", "roads_line", "memory")
        l_lines.dataProvider().addAttributes([QgsField("Layer", FT_STRING)])
        l_lines.updateFields()
        f1 = QgsFeature(l_lines.fields())
        f1.setGeometry(QgsGeometry.fromWkt("LINESTRING(200000 500000, 200100 500000)"))
        f1.setAttributes(["A0023215"])
        f2 = QgsFeature(l_lines.fields())
        f2.setGeometry(QgsGeometry.fromWkt("LINESTRING(200100 500000, 200200 500000)"))
        f2.setAttributes(["A0023215"])
        l_lines.dataProvider().addFeatures([f1, f2])

        l_pts = QgsVectorLayer("Point?crs=EPSG:5186", "roads_pt", "memory")
        l_pts.dataProvider().addAttributes([QgsField("Layer", FT_STRING)])
        l_pts.updateFields()
        fp = QgsFeature(l_pts.fields())
        fp.setGeometry(QgsGeometry.fromWkt("POINT(200050 500000)"))
        fp.setAttributes(["A0023215"])
        l_pts.dataProvider().addFeatures([fp])

        dlg = MSD.MapStylingDialog(self.iface)
        self.addCleanup(dlg.close)
        # Put Point layer FIRST to guarantee the bad geometry hits before the lines!
        out = dlg.aggregate_features([l_pts, l_lines], ["A0023215"], "Style: 도로", dest_geom="line")
        self.assertIsNotNone(out)
        self.assertEqual(out.featureCount(), 2, "Mixed Point feature aborted LineString batch!")

    def test_v20_ai_aoi_summary_circular_aspect_stats(self):
        # Aspect raster with 355 deg and 5 deg -> arithmetic mean = 180 deg (SOUTH - WRONG!),
        # true circular mean = 0 deg (NORTH)! Plus -1 flat cells excluded from direction mean.
        asp_path = os.path.join(self.tmp, "aspect_circ.tif")
        arr = np.full((10, 10), 355.0, dtype=np.float32)
        arr[:, 5:] = 5.0
        arr[0, :] = -1.0  # 10% flat
        ds = gdal.GetDriverByName("GTiff").Create(asp_path, 10, 10, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((200000.0, 10.0, 0.0, 500100.0, 0.0, -10.0))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5186)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(-9999.0)
        band.WriteArray(arr)
        band = None
        ds = None

        geom = QgsGeometry.fromWkt("POLYGON((200000 500000, 200100 500000, 200100 500100, 200000 500100, 200000 500000))")
        st = ai_aoi_summary._raster_stats_in_geom(asp_path, geom, circular=True)
        self.assertIsNotNone(st)
        self.assertTrue(st["circular"])
        self.assertNotIn("mean", st)
        # Circular mean near 0 deg (or 360 deg), NOT 180 deg!
        cdeg = float(st["circular_mean_deg"])
        dist_to_north = min(cdeg, 360.0 - cdeg)
        self.assertLess(dist_to_north, 0.5, f"Circular mean should be near 0 deg (N), got {cdeg}")
        self.assertAlmostEqual(float(st["flat_pct"]), 10.0, places=3)


if __name__ == "__main__":
    unittest.main()
