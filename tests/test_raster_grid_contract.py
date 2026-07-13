from __future__ import annotations

import math
import unittest

from tools.raster_grid_contract import (
    Extent,
    GridContractError,
    GridMismatchError,
    GridTolerances,
    RasterGrid,
    canonical_gdal_target_grid,
    grid_mismatches,
    validate_grid,
)


class RasterGridContractTests(unittest.TestCase):
    @staticmethod
    def _expected_grid() -> RasterGrid:
        return canonical_gdal_target_grid(
            Extent(0.2, 10.45, -1.3, 6.9),
            1.7,
            1.7,
        )

    def test_nonmultiple_extent_uses_rounded_size_and_upper_left_anchor(self):
        grid = self._expected_grid()

        self.assertEqual((grid.width, grid.height), (6, 5))
        self.assertEqual(grid.extent.xmin, 0.2)
        self.assertAlmostEqual(grid.extent.xmax, 10.4)
        self.assertAlmostEqual(grid.extent.ymin, -1.6)
        self.assertEqual(grid.extent.ymax, 6.9)
        self.assertEqual((grid.resolution_x, grid.resolution_y), (1.7, 1.7))

    def test_half_cell_ties_round_up(self):
        cases = (
            (9.49, 9),
            (9.5, 10),
            (10.5, 11),
        )
        for span, expected_width in cases:
            with self.subTest(span=span):
                grid = canonical_gdal_target_grid(
                    Extent(0.0, span, 0.0, 1.0),
                    1.0,
                    1.0,
                )
                self.assertEqual(grid.width, expected_width)

    def test_subpixel_extent_still_produces_one_cell(self):
        grid = canonical_gdal_target_grid(
            Extent(5.0, 5.49, 9.51, 10.0),
            1.0,
            1.0,
        )

        self.assertEqual((grid.width, grid.height), (1, 1))
        self.assertEqual(grid.extent, Extent(5.0, 6.0, 9.0, 10.0))

    def test_x_and_y_resolutions_are_independent(self):
        grid = canonical_gdal_target_grid(
            Extent(0.0, 5.1, 0.0, 5.1),
            2.0,
            1.0,
        )

        self.assertEqual((grid.width, grid.height), (3, 5))
        self.assertEqual((grid.extent.xmin, grid.extent.xmax), (0.0, 6.0))
        self.assertAlmostEqual(grid.extent.ymin, 0.1)
        self.assertEqual(grid.extent.ymax, 5.1)
        self.assertEqual((grid.resolution_x, grid.resolution_y), (2.0, 1.0))

    def test_numeric_differences_within_absolute_tolerance_are_accepted(self):
        expected = self._expected_grid()
        tolerance = GridTolerances(1e-6, 1e-6)
        actual = RasterGrid(
            width=expected.width,
            height=expected.height,
            extent=Extent(
                expected.extent.xmin + 5e-7,
                expected.extent.xmax - 5e-7,
                expected.extent.ymin + 5e-7,
                expected.extent.ymax - 5e-7,
            ),
            resolution_x=expected.resolution_x + 5e-7,
            resolution_y=expected.resolution_y - 5e-7,
        )

        self.assertEqual(grid_mismatches(actual, expected, tolerances=tolerance), ())
        self.assertIsNone(validate_grid(actual, expected, tolerances=tolerance))

    def test_dimension_mismatch_is_exact(self):
        expected = self._expected_grid()
        actual = RasterGrid(
            width=expected.width + 1,
            height=expected.height - 1,
            extent=expected.extent,
            resolution_x=expected.resolution_x,
            resolution_y=expected.resolution_y,
        )

        self.assertEqual(grid_mismatches(actual, expected), ("width", "height"))
        with self.assertRaises(GridMismatchError) as caught:
            validate_grid(actual, expected)
        self.assertEqual(caught.exception.fields, ("width", "height"))

    def test_origin_mismatch_is_rejected(self):
        expected = self._expected_grid()
        shift = 0.02 * expected.resolution_x
        actual = RasterGrid(
            width=expected.width,
            height=expected.height,
            extent=Extent(
                expected.extent.xmin + shift,
                expected.extent.xmax + shift,
                expected.extent.ymin,
                expected.extent.ymax,
            ),
            resolution_x=expected.resolution_x,
            resolution_y=expected.resolution_y,
        )

        self.assertEqual(grid_mismatches(actual, expected), ("xmin", "xmax"))

    def test_resolution_mismatch_is_rejected(self):
        expected = self._expected_grid()
        actual = RasterGrid(
            width=expected.width,
            height=expected.height,
            extent=expected.extent,
            resolution_x=expected.resolution_x + 0.001,
            resolution_y=expected.resolution_y - 0.001,
        )

        self.assertEqual(
            grid_mismatches(actual, expected),
            ("resolution_x", "resolution_y"),
        )

    def test_tolerance_must_distinguish_one_percent_of_a_cell(self):
        expected = canonical_gdal_target_grid(
            Extent(0.0, 10.0, 0.0, 10.0),
            1.0,
            2.0,
        )

        for tolerance in (
            GridTolerances(0.01, 1e-9),
            GridTolerances(1e-9, 0.01),
        ):
            with self.subTest(tolerance=tolerance):
                with self.assertRaisesRegex(GridContractError, "less than 1%"):
                    grid_mismatches(expected, expected, tolerances=tolerance)

    def test_invalid_extent_is_rejected(self):
        invalid_values = (
            (math.nan, 1.0, 0.0, 1.0),
            (0.0, math.inf, 0.0, 1.0),
            (1.0, 1.0, 0.0, 1.0),
            (2.0, 1.0, 0.0, 1.0),
            (0.0, 1.0, 1.0, 1.0),
            (0.0, 1.0, 2.0, 1.0),
        )
        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(GridContractError):
                    Extent(*values)

    def test_invalid_resolution_is_rejected(self):
        extent = Extent(0.0, 1.0, 0.0, 1.0)
        for resolution in (0.0, -1.0, math.nan, math.inf, True):
            with self.subTest(resolution=resolution):
                with self.assertRaises(GridContractError):
                    canonical_gdal_target_grid(extent, resolution)

    def test_invalid_dimensions_and_tolerances_are_rejected(self):
        extent = Extent(0.0, 1.0, 0.0, 1.0)
        for width in (0, -1, 1.0, True):
            with self.subTest(width=width):
                with self.assertRaises(GridContractError):
                    RasterGrid(width, 1, extent, 1.0, 1.0)
        for value in (-1.0, math.nan, math.inf):
            with self.subTest(tolerance=value):
                with self.assertRaises(GridContractError):
                    GridTolerances(value, 0.0)


if __name__ == "__main__":
    unittest.main()
