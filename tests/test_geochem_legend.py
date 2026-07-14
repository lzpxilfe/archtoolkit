from __future__ import annotations

import unittest

import numpy as np

from tools.geochem_legend import (
    LegendPoint,
    interp_rgb_to_value,
    mask_black_lines,
    points_to_breaks,
)


def _bands(colors):
    """Split a list of (r, g, b) tuples into three 1-D float arrays."""
    a = np.asarray(colors, dtype=float)
    return a[:, 0], a[:, 1], a[:, 2]


# Black -> white ramp carrying value 0 -> 10.
RAMP = [LegendPoint(0.0, (0, 0, 0)), LegendPoint(10.0, (255, 255, 255))]
# A three-colour legend with non-collinear colours.
LEGEND3 = [
    LegendPoint(0.0, (204, 204, 204)),
    LegendPoint(3.1, (0, 38, 115)),
    LegendPoint(12.0, (230, 0, 0)),
]


class InterpRgbToValueTests(unittest.TestCase):
    def test_exact_legend_colours_return_exact_values(self):
        r, g, b = _bands([(204, 204, 204), (0, 38, 115), (230, 0, 0)])
        out = interp_rgb_to_value(r=r, g=g, b=b, points=LEGEND3)
        for got, exp in zip(out, [0.0, 3.1, 12.0]):
            self.assertAlmostEqual(float(got), exp, places=4)

    def test_segment_midpoint_interpolates_value(self):
        r, g, b = _bands([(127.5, 127.5, 127.5)])
        out = interp_rgb_to_value(r=r, g=g, b=b, points=RAMP)
        self.assertAlmostEqual(float(out[0]), 5.0, places=4)

    def test_off_segment_colour_projects_onto_nearest_point(self):
        # Pure red against a grey ramp projects to t = 1/3 along the segment.
        r, g, b = _bands([(255, 0, 0)])
        out = interp_rgb_to_value(r=r, g=g, b=b, points=RAMP)
        self.assertAlmostEqual(float(out[0]), 10.0 / 3.0, places=3)

    def test_value_is_bounded_by_the_legend_range(self):
        # A colour past white still clamps to the ramp's top value (t clipped).
        r, g, b = _bands([(300, 300, 300)])
        out = interp_rgb_to_value(r=r, g=g, b=b, points=RAMP)
        self.assertAlmostEqual(float(out[0]), 10.0, places=4)

    def test_snap_last_saturates_the_top_segment(self):
        # 60% up the ramp is grey (153,153,153); with snap_last_t=0.5 the last
        # segment's t>0.5 snaps to 1.0, saturating the value to the top.
        r, g, b = _bands([(153, 153, 153)])
        plain = interp_rgb_to_value(r=r, g=g, b=b, points=RAMP)
        snapped = interp_rgb_to_value(r=r, g=g, b=b, points=RAMP, snap_last_t=0.5)
        self.assertAlmostEqual(float(plain[0]), 6.0, places=4)
        self.assertAlmostEqual(float(snapped[0]), 10.0, places=4)

    def test_shape_mismatch_raises(self):
        with self.assertRaises(ValueError):
            interp_rgb_to_value(
                r=np.zeros(3), g=np.zeros(2), b=np.zeros(3), points=RAMP
            )

    def test_needs_at_least_two_points(self):
        with self.assertRaises(ValueError):
            interp_rgb_to_value(
                r=np.zeros(1), g=np.zeros(1), b=np.zeros(1),
                points=[LegendPoint(1.0, (0, 0, 0))],
            )

    def test_preserves_input_shape(self):
        r, g, b = np.zeros((2, 2)), np.zeros((2, 2)), np.zeros((2, 2))
        out = interp_rgb_to_value(r=r, g=g, b=b, points=RAMP)
        self.assertEqual(out.shape, (2, 2))


class PointsToBreaksTests(unittest.TestCase):
    def test_sorted_unique_values(self):
        pts = [LegendPoint(12.0, (0, 0, 0)), LegendPoint(0.0, (1, 1, 1)), LegendPoint(12.0, (2, 2, 2))]
        self.assertEqual(points_to_breaks(pts), [0.0, 12.0])


class MaskBlackLinesTests(unittest.TestCase):
    def test_dark_neutral_pixels_are_masked(self):
        r, g, b = _bands([(10, 10, 10), (70, 72, 68)])
        self.assertTrue(mask_black_lines(r, g, b).all())

    def test_coloured_or_light_pixels_are_not_masked(self):
        # intense red, dark-but-coloured, and a light grey — none are linework.
        r, g, b = _bands([(230, 0, 0), (10, 60, 10), (100, 100, 100)])
        self.assertFalse(mask_black_lines(r, g, b).any())


if __name__ == "__main__":
    unittest.main()
