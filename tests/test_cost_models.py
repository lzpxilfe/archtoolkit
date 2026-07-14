from __future__ import annotations

import math
import unittest

from tools.cost_models import (
    MODEL_CONOLLY_LAKE,
    MODEL_HERZOG_METABOLIC,
    MODEL_HERZOG_WHEELED,
    MODEL_NAISMITH,
    MODEL_PANDOLF,
    MODEL_TOBLER,
    edge_cost,
    isochrone_levels_minutes,
    isoenergy_levels_kcal,
    naismith_time_s,
    tobler_speed_mps,
)

_V = 5.0 * 1000.0 / 3600.0  # default Pandolf speed, m/s


class ToblerTests(unittest.TestCase):
    def test_peak_speed_is_at_minus_offset_slope(self):
        # Tobler's function peaks (exp term = 1) at slope = -offset.
        v = tobler_speed_mps(-0.05, 6.0, 3.5, 0.05, 0.05)
        self.assertAlmostEqual(v, 6.0 * 1000.0 / 3600.0, places=6)

    def test_flat_speed_matches_formula(self):
        v = tobler_speed_mps(0.0, 6.0, 3.5, 0.05, 0.05)
        expected = 6.0 * math.exp(-3.5 * 0.05) * 1000.0 / 3600.0
        self.assertAlmostEqual(v, expected, places=6)

    def test_speed_never_below_floor(self):
        v = tobler_speed_mps(10.0, 6.0, 3.5, 0.05, 0.2)
        self.assertEqual(v, 0.2)

    def test_uphill_is_slower_than_downhill(self):
        up = tobler_speed_mps(0.3, 6.0, 3.5, 0.05, 0.01)
        down = tobler_speed_mps(-0.3, 6.0, 3.5, 0.05, 0.01)
        self.assertLess(up, down)


class NaismithTests(unittest.TestCase):
    def test_flat_time_is_distance_over_speed(self):
        # 1 km at 5 km/h = 0.2 h = 720 s.
        self.assertAlmostEqual(naismith_time_s(1000.0, 0.0, 5.0, 600.0), 720.0, places=6)

    def test_ascent_adds_time(self):
        # +600 m of ascent at 600 m/h adds exactly one hour.
        self.assertAlmostEqual(
            naismith_time_s(1000.0, 600.0, 5.0, 600.0), 720.0 + 3600.0, places=6
        )

    def test_descent_adds_no_time_classic_naismith(self):
        # Classic Naismith ignores descent (max(0, dz)).
        self.assertAlmostEqual(naismith_time_s(1000.0, -600.0, 5.0, 600.0), 720.0, places=6)


class EdgeCostDispatchTests(unittest.TestCase):
    def test_zero_distance_is_zero_cost(self):
        self.assertEqual(edge_cost(MODEL_TOBLER, 0.0, 0.0, {}), 0.0)

    def test_tobler_edge_is_distance_over_speed(self):
        cost = edge_cost(MODEL_TOBLER, 100.0, 0.0, {})
        speed = tobler_speed_mps(0.0, 6.0, 3.5, 0.05, 0.05)
        self.assertAlmostEqual(cost, 100.0 / speed, places=6)

    def test_naismith_edge_delegates_to_formula(self):
        cost = edge_cost(MODEL_NAISMITH, 1000.0, 600.0, {})
        self.assertAlmostEqual(cost, naismith_time_s(1000.0, 600.0, 5.0, 600.0), places=6)

    def test_conolly_never_faster_than_flat(self):
        # The slope factor is clamped to >= 1, so a gentle slope is never cheaper
        # than the flat traverse over the same distance.
        flat = edge_cost(MODEL_CONOLLY_LAKE, 100.0, 0.0, {})
        gentle = edge_cost(MODEL_CONOLLY_LAKE, 100.0, 1.0, {})
        self.assertGreaterEqual(gentle, flat)

    def test_herzog_metabolic_flat_uses_base_speed(self):
        cost = edge_cost(MODEL_HERZOG_METABOLIC, 100.0, 0.0, {"herzog_base_kmh": 5.0})
        base_mps = 5.0 * 1000.0 / 3600.0
        self.assertAlmostEqual(cost, 100.0 / base_mps, places=6)

    def test_wheeled_beyond_max_slope_is_impassable(self):
        # 60% grade well exceeds the 45 deg default limit.
        cost = edge_cost(MODEL_HERZOG_WHEELED, 100.0, 200.0, {})
        self.assertTrue(math.isinf(cost))


def _pandolf_energy(horiz, dz, *, W=70.0, L=0.0, eta=1.0, V=_V):
    """Independent reimplementation of Pandolf et al. (1977) for cross-checking."""
    grade = (dz / horiz) * 100.0
    lr = L / W
    M = (1.5 * W) + (2.0 * (W + L) * lr ** 2) + eta * (W + L) * (1.5 * V * V + 0.35 * V * grade)
    M = max(1.5 * W, M)
    return (M * horiz) / V


class PandolfTests(unittest.TestCase):
    def test_time_mode_is_distance_over_speed(self):
        cost = edge_cost(MODEL_PANDOLF, 100.0, 10.0, {}, cost_mode="time_s")
        self.assertAlmostEqual(cost, 100.0 / _V, places=6)

    def test_flat_energy_matches_independent_formula(self):
        cost = edge_cost(MODEL_PANDOLF, 100.0, 0.0, {}, cost_mode="energy_j")
        self.assertAlmostEqual(cost, _pandolf_energy(100.0, 0.0), places=3)

    def test_uphill_energy_matches_independent_formula(self):
        cost = edge_cost(MODEL_PANDOLF, 100.0, 15.0, {}, cost_mode="energy_j")
        self.assertAlmostEqual(cost, _pandolf_energy(100.0, 15.0), places=3)

    def test_load_increases_energy(self):
        light = edge_cost(MODEL_PANDOLF, 100.0, 0.0, {"pandolf_load_kg": 0.0}, cost_mode="energy_j")
        heavy = edge_cost(MODEL_PANDOLF, 100.0, 0.0, {"pandolf_load_kg": 30.0}, cost_mode="energy_j")
        self.assertGreater(heavy, light)

    def test_steep_descent_is_clamped_to_standing_floor(self):
        # Without the max(1.5W, M) floor the grade term drives M negative on
        # steep descents, making cliffs "cheapest". The clamp keeps a steep
        # descent at exactly the standing-metabolism floor 1.5*W.
        cost = edge_cost(MODEL_PANDOLF, 100.0, -50.0, {}, cost_mode="energy_j")
        floor = (1.5 * 70.0) * 100.0 / _V
        self.assertAlmostEqual(cost, floor, places=3)
        self.assertGreater(cost, 0.0)


class LevelGeneratorTests(unittest.TestCase):
    def test_isochrone_tiers(self):
        self.assertEqual(isochrone_levels_minutes(50), [15.0, 30.0, 45.0])
        self.assertEqual(isochrone_levels_minutes(70), [15.0, 30.0, 45.0, 60.0])
        self.assertEqual(
            isochrone_levels_minutes(200),
            [15.0, 30.0, 45.0, 60.0, 90.0, 120.0, 150.0, 180.0],
        )

    def test_isochrone_rejects_nonpositive_and_bad_input(self):
        self.assertEqual(isochrone_levels_minutes(0), [])
        self.assertEqual(isochrone_levels_minutes(-5), [])
        self.assertEqual(isochrone_levels_minutes("nope"), [])
        self.assertEqual(isochrone_levels_minutes(float("nan")), [])

    def test_isochrone_levels_are_sorted_unique_and_bounded(self):
        for mx in (10, 55, 130, 400, 5000):
            lv = isochrone_levels_minutes(mx)
            self.assertEqual(lv, sorted(set(lv)))
            self.assertTrue(all(0 < x <= mx + 1e-6 for x in lv))

    def test_isochrone_contour_count_is_capped(self):
        # A huge extent must not emit an unbounded number of contours.
        self.assertLessEqual(len(isochrone_levels_minutes(1_000_000)), 60)

    def test_isoenergy_tiers(self):
        self.assertEqual(
            isoenergy_levels_kcal(300),
            [50.0, 100.0, 150.0, 200.0, 250.0, 300.0],
        )

    def test_isoenergy_rejects_nonpositive(self):
        self.assertEqual(isoenergy_levels_kcal(0), [])
        self.assertEqual(isoenergy_levels_kcal(-1), [])

    def test_isoenergy_levels_are_sorted_unique_bounded_and_capped(self):
        for mx in (30, 300, 1500, 9000):
            lv = isoenergy_levels_kcal(mx)
            self.assertEqual(lv, sorted(set(lv)))
            self.assertTrue(all(0 < x <= mx + 1e-6 for x in lv))
        self.assertLessEqual(len(isoenergy_levels_kcal(10_000_000)), 80)


if __name__ == "__main__":
    unittest.main()
