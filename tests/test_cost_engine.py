"""QGIS-free unit and property tests for tools/cost_engine.py (V1, V2)."""

from __future__ import annotations

import math
import unittest

import numpy as np

from tools.cost_engine import (
    astar_path,
    dijkstra_full,
    neighbors,
    reconstruct_path,
)
from tools.cost_models import (
    MODEL_CONOLLY_LAKE,
    MODEL_HERZOG_METABOLIC,
    MODEL_HERZOG_WHEELED,
    MODEL_NAISMITH,
    MODEL_PANDOLF,
    MODEL_TOBLER,
    edge_cost,
)


class NeighborsAndReconstructTests(unittest.TestCase):
    def test_4_and_8_neighbor_moves(self):
        self.assertEqual(
            neighbors(False, 5.0, 5.0),
            [(-1, 0, 5.0), (1, 0, 5.0), (0, -1, 5.0), (0, 1, 5.0)],
        )
        m8 = neighbors(True, 5.0, 5.0)
        self.assertEqual(len(m8), 8)
        self.assertAlmostEqual(m8[-1][2], math.hypot(5.0, 5.0), places=12)

    def test_reconstruct_path_connected_trivial_and_disconnected(self):
        prev = np.array([-1, 0, 1, 2], dtype=np.int32)
        self.assertEqual(reconstruct_path(prev, (0, 0), (1, 1), 2, 2), [0, 1, 2, 3])
        self.assertEqual(reconstruct_path(prev, (0, 1), (0, 1), 2, 2), [1])
        prev_disc = np.array([-1, 0, -1, 2], dtype=np.int32)
        self.assertEqual(reconstruct_path(prev_disc, (0, 0), (1, 1), 2, 2), [])


class DijkstraKernelTests(unittest.TestCase):
    def test_reverse_dijkstra_equals_forward_cost_to_target(self):
        rng = np.random.default_rng(7)
        dem = 100.0 + rng.normal(0.0, 8.0, size=(7, 7))
        nodata = np.zeros_like(dem, dtype=bool)
        end_rc = (5, 5)
        for model_key in (MODEL_TOBLER, MODEL_HERZOG_METABOLIC, MODEL_NAISMITH):
            dist_rev, _ = dijkstra_full(
                dem, nodata, end_rc, 10.0, 10.0, True,
                model_key, {}, cost_mode="time_s", reverse=True,
            )
            for start_rc in ((0, 0), (1, 4), (6, 2)):
                dist_fwd, _ = dijkstra_full(
                    dem, nodata, start_rc, 10.0, 10.0, True,
                    model_key, {}, cost_mode="time_s", reverse=False,
                )
                self.assertAlmostEqual(
                    float(dist_fwd[end_rc[0] * 7 + end_rc[1]]),
                    float(dist_rev[start_rc[0] * 7 + start_rc[1]]),
                    places=9,
                )

    def test_midpoint_friction_and_barrier_exclusion(self):
        dem = np.full((3, 3), 100.0, dtype=np.float64)
        nodata = np.zeros_like(dem, dtype=bool)
        nodata[0, 1] = True
        friction = np.array([
            [1.0, 1.0, 1.0],
            [2.0, 0.0, 2.0],   # (1,1) = 0 friction acts as hard barrier
            [2.0, 4.0, 2.0],
        ], dtype=np.float64)
        dist, _ = dijkstra_full(
            dem, nodata, (0, 0), 10.0, 10.0, False,
            MODEL_TOBLER, {}, cost_mode="time_s", friction=friction,
        )
        # Cell (1, 1) must remain unreachable
        self.assertTrue(math.isinf(dist[1 * 3 + 1]))
        # Path (0,0)->(1,0)->(2,0)->(2,1)->(2,2)->(1,2)->(0,2)
        c_flat = edge_cost(MODEL_TOBLER, 10.0, 0.0, {})
        expected_1_0 = c_flat * 0.5 * (1.0 + 2.0)
        self.assertAlmostEqual(float(dist[1 * 3 + 0]), expected_1_0, places=9)
        expected_2_1 = expected_1_0 + c_flat * 2.0 + c_flat * 0.5 * (2.0 + 4.0)
        self.assertAlmostEqual(float(dist[2 * 3 + 1]), expected_2_1, places=9)


class AstarAdmissibilityTests(unittest.TestCase):
    def test_astar_matches_dijkstra_across_all_models_and_20_seeded_dems(self):
        cases = (
            (MODEL_TOBLER, {}, "time_s"),
            (MODEL_NAISMITH, {}, "time_s"),
            (MODEL_HERZOG_METABOLIC, {}, "time_s"),
            (MODEL_CONOLLY_LAKE, {}, "time_s"),
            (MODEL_HERZOG_WHEELED, {"wheeled_max_slope_deg": 80.0}, "time_s"),
            (MODEL_PANDOLF, {"pandolf_load_kg": 15.0}, "energy_j"),
        )
        for seed in range(20):
            rng = np.random.default_rng(100 + seed)
            dem = 100.0 + rng.normal(0.0, 12.0, size=(15, 15))
            friction = rng.uniform(0.5, 3.0, size=(15, 15))
            nodata = np.zeros_like(dem, dtype=bool)
            nodata[7, 4:10] = True  # wall forcing detour
            start_rc, end_rc = (1, 1), (13, 13)
            for model_key, params, cost_mode in cases:
                prev, a_cost = astar_path(
                    dem, nodata, start_rc, end_rc, 10.0, 10.0, True,
                    model_key, params, cost_mode=cost_mode, friction=friction,
                )
                dist, _ = dijkstra_full(
                    dem, nodata, start_rc, 10.0, 10.0, True,
                    model_key, params, cost_mode=cost_mode, friction=friction,
                )
                d_cost = float(dist[end_rc[0] * 15 + end_rc[1]])
                self.assertIsNotNone(a_cost, f"seed={seed} model={model_key}")
                self.assertTrue(math.isclose(float(a_cost), d_cost, rel_tol=1e-9, abs_tol=1e-9),
                                f"seed={seed} model={model_key}: a*={a_cost} vs dijkstra={d_cost}")
                path = reconstruct_path(prev, start_rc, end_rc, 15, 15)
                self.assertGreaterEqual(len(path), 2)

    def test_admissible_with_floor_exceeding_base_speed_and_tiny_friction(self):
        rng = np.random.default_rng(999)
        dem = 100.0 + rng.normal(0.0, 10.0, size=(11, 11))
        friction = rng.uniform(1e-6, 5e-5, size=(11, 11))
        nodata = np.zeros_like(dem, dtype=bool)
        params = {"herzog_base_kmh": 0.1, "min_speed_mps": 0.5}
        _, a_cost = astar_path(
            dem, nodata, (0, 0), (10, 10), 10.0, 10.0, True,
            MODEL_HERZOG_METABOLIC, params, cost_mode="time_s", friction=friction,
        )
        dist, _ = dijkstra_full(
            dem, nodata, (0, 0), 10.0, 10.0, True,
            MODEL_HERZOG_METABOLIC, params, cost_mode="time_s", friction=friction,
        )
        self.assertTrue(math.isclose(float(a_cost), float(dist[10 * 11 + 10]), rel_tol=1e-9, abs_tol=1e-9))


if __name__ == "__main__":
    unittest.main()
