from __future__ import annotations

import unittest

import numpy as np

from tools.terrain_math import zt_curvature


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


if __name__ == "__main__":
    unittest.main()
