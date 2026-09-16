from __future__ import annotations

import unittest

import numpy as np

from tools.terrain_math import tri_radius, zt_curvature


class ZtCurvatureTests(unittest.TestCase):
    """Zevenbergen & Thorne curvature checked against analytic surfaces.

    np.roll wraps the one-cell border, so every assertion targets a fully
    interior cell (row/col 3 of a 7x7 grid).
    """

    def _grid(self, func, n=7, cell=1.0):
        xs = np.arange(n, dtype=float) * cell
        ys = np.arange(n, dtype=float) * cell
        z = np.empty((n, n), dtype=float)
        for i in range(n):
            for j in range(n):
                z[i, j] = func(xs[j], ys[i])
        return z

    def test_flat_surface_has_zero_curvature(self):
        z = np.full((7, 7), 42.0)
        profile, plan = zt_curvature(z, 1.0)
        self.assertAlmostEqual(profile[3, 3], 0.0, places=9)
        self.assertAlmostEqual(plan[3, 3], 0.0, places=9)

    def test_tilted_plane_has_zero_curvature(self):
        # A planar ramp z = 3x + 2y curves nowhere.
        z = self._grid(lambda x, y: 3.0 * x + 2.0 * y)
        profile, plan = zt_curvature(z, 1.0)
        self.assertAlmostEqual(profile[3, 3], 0.0, places=9)
        self.assertAlmostEqual(plan[3, 3], 0.0, places=9)

    def test_valley_along_x_has_unit_profile_curvature(self):
        # z = 0.5 x^2 -> d2z/dx2 = 1; profile curvature = 1, plan = 0.
        z = self._grid(lambda x, y: 0.5 * x * x)
        profile, plan = zt_curvature(z, 1.0)
        self.assertAlmostEqual(profile[3, 3], 1.0, places=6)
        self.assertAlmostEqual(plan[3, 3], 0.0, places=6)

    def test_bowl_has_opposite_profile_and_plan(self):
        # Symmetric paraboloid z = 0.5 (x^2 + y^2): profile 1, plan -1.
        z = self._grid(lambda x, y: 0.5 * (x * x + y * y))
        profile, plan = zt_curvature(z, 1.0)
        self.assertAlmostEqual(profile[3, 3], 1.0, places=6)
        self.assertAlmostEqual(plan[3, 3], -1.0, places=6)

    def test_curvature_is_cell_size_invariant(self):
        # Curvature is a physical property: the same surface sampled on a
        # coarser grid yields the same value.
        z1 = self._grid(lambda x, y: 0.5 * x * x, n=9, cell=1.0)
        z2 = self._grid(lambda x, y: 0.5 * x * x, n=9, cell=2.5)
        p1, _ = zt_curvature(z1, 1.0)
        p2, _ = zt_curvature(z2, 2.5)
        self.assertAlmostEqual(p1[4, 4], 1.0, places=6)
        self.assertAlmostEqual(p2[4, 4], 1.0, places=6)

    def test_flat_patch_yields_zero_not_nan(self):
        # Where slope is ~0 the denominator guard must return 0, never NaN.
        z = np.zeros((7, 7))
        profile, plan = zt_curvature(z, 1.0)
        self.assertFalse(np.isnan(profile).any())
        self.assertFalse(np.isnan(plan).any())

    def test_convex_and_concave_have_opposite_profile_sign(self):
        hill = self._grid(lambda x, y: -0.5 * x * x)  # ridge
        valley = self._grid(lambda x, y: 0.5 * x * x)  # channel
        p_hill, _ = zt_curvature(hill, 1.0)
        p_valley, _ = zt_curvature(valley, 1.0)
        self.assertLess(p_hill[3, 3], 0.0)
        self.assertGreater(p_valley[3, 3], 0.0)
        self.assertAlmostEqual(p_hill[3, 3], -p_valley[3, 3], places=6)




class TriRadiusTests(unittest.TestCase):
    """Ruggedness over a window wider than gdaldem's fixed 3x3.

    The showcase model's strongest predictor is ruggedness within 65 m; at 5 m
    cells a 3x3 window covers 15 m, which is a different variable rather than a
    coarser one.
    """

    def test_flat_terrain_is_zero(self):
        result = tri_radius(np.full((11, 11), 30.0), 2)
        self.assertAlmostEqual(result[5, 5], 0.0, places=12)

    def test_matches_the_closed_form_on_a_plane(self):
        # On z = a*x, the RMS difference from the centre over a (2r+1)^2 window
        # is a * sqrt(mean(dx^2)) where dx runs over the window offsets.
        a, r, n = 3.0, 2, 13
        xs = np.arange(n, dtype=float)
        z = np.tile(a * xs, (n, 1))
        offsets = [(dr, dc) for dr in range(-r, r + 1) for dc in range(-r, r + 1)
                   if not (dr == 0 and dc == 0)]
        expected = a * np.sqrt(np.mean([dc ** 2 for _dr, dc in offsets]))
        self.assertAlmostEqual(tri_radius(z, r)[6, 6], expected, places=10)

    def test_radius_one_relates_to_riley_by_sqrt_n(self):
        # Riley (1999) sums the squared differences; this returns their RMS, so
        # on a full 3x3 window the two differ by exactly sqrt(8).
        rng = np.random.default_rng(1234)
        z = rng.normal(100.0, 5.0, size=(9, 9))
        centre = z[4, 4]
        neighbours = [z[4 + dr, 4 + dc] for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                      if not (dr == 0 and dc == 0)]
        riley = np.sqrt(sum((centre - v) ** 2 for v in neighbours))
        self.assertAlmostEqual(tri_radius(z, 1)[4, 4], riley / np.sqrt(8), places=10)

    def test_larger_radius_sees_broader_relief(self):
        # A broad ridge that a 3x3 window sits flat on top of.
        xs = np.arange(41, dtype=float)
        z = np.tile(np.abs(xs - 20.0), (41, 1))
        narrow = tri_radius(z, 1)[20, 20]
        broad = tri_radius(z, 8)[20, 20]
        self.assertGreater(broad, narrow)

    def test_border_is_nan_not_wrapped(self):
        # np.roll would wrap the far edge in and invent a cliff at the border.
        rng = np.random.default_rng(7)
        z = rng.normal(0.0, 10.0, size=(9, 9))
        result = tri_radius(z, 2)
        self.assertTrue(np.all(np.isnan(result[:2, :])))
        self.assertTrue(np.all(np.isnan(result[-2:, :])))
        self.assertTrue(np.all(np.isnan(result[:, :2])))
        self.assertTrue(np.all(np.isnan(result[:, -2:])))
        self.assertFalse(np.isnan(result[4, 4]))

    def test_nodata_neither_contributes_nor_receives(self):
        z = np.full((9, 9), 10.0)
        z[4, 5] = 9999.0
        mask = np.zeros(z.shape, dtype=bool)
        mask[4, 5] = True
        result = tri_radius(z, 1, nodata_mask=mask)
        self.assertTrue(np.isnan(result[4, 5]), "NoData cell must not get a value")
        # The 9999 must not leak into its neighbour's ruggedness.
        self.assertAlmostEqual(result[4, 4], 0.0, places=12)

    def test_nan_in_the_array_is_treated_as_nodata(self):
        z = np.full((9, 9), 10.0)
        z[4, 5] = np.nan
        result = tri_radius(z, 1)
        self.assertTrue(np.isnan(result[4, 5]))
        self.assertAlmostEqual(result[4, 4], 0.0, places=12)

    def test_rejects_bad_arguments(self):
        with self.assertRaises(ValueError):
            tri_radius(np.zeros((5, 5)), 0)
        with self.assertRaises(ValueError):
            tri_radius(np.zeros(5), 1)
        with self.assertRaises(ValueError):
            tri_radius(np.zeros((5, 5)), 3)   # window wider than the array


if __name__ == "__main__":
    unittest.main()
