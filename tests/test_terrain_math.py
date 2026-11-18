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

    def test_progress_is_reported_per_offset(self):
        seen = []
        tri_radius(np.zeros((9, 9)), 2, progress_cb=lambda d, t: seen.append((d, t)))
        self.assertEqual(seen[-1], (24, 24))          # (2r+1)^2 - 1 offsets
        self.assertEqual([d for d, _ in seen], list(range(1, 25)))

    def test_cancel_returns_none_and_stops_early(self):
        calls = []
        result = tri_radius(np.zeros((9, 9)), 2,
                            progress_cb=lambda d, t: calls.append(d),
                            cancel_check=lambda: len(calls) >= 3)
        self.assertIsNone(result)
        self.assertEqual(len(calls), 3)

    def test_rejects_bad_arguments(self):
        with self.assertRaises(ValueError):
            tri_radius(np.zeros((5, 5)), 0)
        with self.assertRaises(ValueError):
            tri_radius(np.zeros(5), 1)
        with self.assertRaises(ValueError):
            tri_radius(np.zeros((5, 5)), 3)   # window wider than the array


class ZtCurvatureCrossTermTests(unittest.TestCase):
    """Cross-term F = d^2z/(dx dy) pin on north-up grids (V5)."""

    def test_cross_term_north_up_square_and_nonsquare_pixels(self):
        from tools.terrain_math import zt_curvature

        rows, cols = 12, 14
        for dx, dy in ((10.0, 10.0), (10.0, 5.0)):
            # North-up grid: row 0 is northernmost (largest y), increasing row goes south.
            xc = (np.arange(cols, dtype=float) + 0.5) * dx
            yc = -(np.arange(rows, dtype=float) + 0.5) * dy
            gx, gy = np.meshgrid(xc, yc)
            # z(x, y) = 0.01*x*y + 0.5*x - 0.3*y -> D=0, E=0, F=0.01
            f_true = 0.01
            z = f_true * gx * gy + 0.5 * gx - 0.3 * gy
            prof, plan = zt_curvature(z, dx, cell_y=dy)

            sl = (slice(2, rows - 2), slice(2, cols - 2))
            g_exact = f_true * gy[sl] + 0.5
            h_exact = f_true * gx[sl] - 0.3
            denom = g_exact * g_exact + h_exact * h_exact
            expected_prof = 2.0 * (f_true * g_exact * h_exact) / denom
            expected_plan = 2.0 * (f_true * g_exact * h_exact) / denom

            np.testing.assert_allclose(prof[sl], expected_prof, atol=1e-11, err_msg=f"dx={dx}, dy={dy}")
            np.testing.assert_allclose(plan[sl], expected_plan, atol=1e-11, err_msg=f"dx={dx}, dy={dy}")
            # Confirm curvature actually reflects cross-term sign (not F=0 or -F).
            self.assertGreater(float(np.max(np.abs(prof[sl]))), 1e-4)


class FocalTpiStripsTests(unittest.TestCase):
    def test_strip_processing_matches_full_grid_with_nodata(self):
        from tools.terrain_math import focal_tpi, focal_tpi_strips

        rng = np.random.default_rng(19)
        grid = 100.0 + 10.0 * rng.standard_normal((15, 17))
        nodata_val = -9999.0
        grid[3, 5] = nodata_val
        grid[8, 9] = nodata_val

        out = np.empty_like(grid)
        calls = []

        def read_rows(lo, hi):
            return grid[lo:hi, :]

        def write_rows(first, block):
            out[first:first + block.shape[0], :] = block

        focal_tpi_strips(
            grid.shape[0],
            grid.shape[1],
            2,
            read_rows,
            write_rows,
            nodata=nodata_val,
            block_rows=3,
            progress_cb=lambda d, tot: calls.append((d, tot)),
        )
        expected = focal_tpi(grid, 2, nodata_mask=(grid == nodata_val))
        np.testing.assert_allclose(out, expected, rtol=1e-12, atol=1e-12, equal_nan=True)
        self.assertEqual(calls[-1], (grid.shape[0], grid.shape[0]))


if __name__ == "__main__":
    unittest.main()
