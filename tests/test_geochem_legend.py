from __future__ import annotations

import os
import tempfile
import unittest

import numpy as np

from tools.geochem_legend import (
    LegendCsvError,
    LegendPoint,
    interp_rgb_to_value,
    legend_points_from_csv,
    legend_sample_rows,
    mask_black_lines,
    parse_legend_csv_rows,
    points_to_breaks,
    sampled_legend_problem,
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

    def test_snap_does_not_count_as_colour_mismatch(self):
        # The grey pixel sits exactly ON the ramp (true residual 0). Snapping
        # its t to 1.0 moves the projection ~100 RGB units away, and that
        # distance must not be what the tolerance test sees, or on-ramp
        # high-value pixels become NoData.
        r, g, b = _bands([(153, 153, 153)])
        out, residual = interp_rgb_to_value(
            r=r, g=g, b=b, points=RAMP, snap_last_t=0.5, max_distance=5.0, return_residual=True
        )
        self.assertAlmostEqual(float(residual[0]), 0.0, places=3)
        self.assertAlmostEqual(float(out[0]), 10.0, places=4)

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


class LegendCsvParserTests(unittest.TestCase):
    def test_unit_range_rgb_is_scaled_by_255_and_reported(self):
        # matplotlib / R / QGIS ramp exports write 0-1 channels. int(float())
        # used to truncate them to an all-black legend.
        res = parse_legend_csv_rows([
            ["value", "r", "g", "b"],
            ["0", "0.80", "0.80", "0.80"],
            ["3.1", "0.00", "0.15", "0.45"],
            ["51", "0.45", "0.05", "0.05"],
        ])
        self.assertTrue(res.scaled_from_unit)
        self.assertEqual([p.rgb for p in res.points], [(204, 204, 204), (0, 38, 115), (115, 13, 13)])
        self.assertEqual([p.value for p in res.points], [0.0, 3.1, 51.0])
        self.assertTrue(any("0~1" in n for n in res.notes))

    def test_integer_rgb_is_not_rescaled(self):
        res = parse_legend_csv_rows([["0", "204", "204", "204"], ["12", "230", "0", "0"]])
        self.assertFalse(res.scaled_from_unit)
        self.assertEqual([p.rgb for p in res.points], [(204, 204, 204), (230, 0, 0)])

    def test_all_zero_or_one_channels_are_treated_as_0_255(self):
        # Pure black/white/red written as 0/1 is ambiguous; without a fractional
        # channel the file is left alone (0-255 convention).
        res = parse_legend_csv_rows([["0", "0", "0", "0"], ["1", "1", "1", "1"]])
        self.assertFalse(res.scaled_from_unit)
        self.assertEqual([p.rgb for p in res.points], [(0, 0, 0), (1, 1, 1)])

    def test_out_of_range_channel_rejects_file_and_names_rows(self):
        rows = [
            ["value", "r", "g", "b"],
            ["0", "204", "204", "204"],
            ["3.1", "0", "38", "300"],
            ["12", "230", "0", "0"],
            ["51", "-4", "12", "12"],
        ]
        with self.assertRaises(LegendCsvError) as cm:
            parse_legend_csv_rows(rows)
        self.assertEqual(cm.exception.code, "range")
        self.assertEqual(cm.exception.rows, [3, 5])
        self.assertIn("3, 5", str(cm.exception))

    def test_mis_columned_file_is_rejected_not_clamped(self):
        # A Pb legend written as r,g,b,value: the 1363 ppm maximum lands in the
        # "b" column. The old parser clamped it to 255 and accepted the file.
        with self.assertRaises(LegendCsvError) as cm:
            parse_legend_csv_rows([["204", "204", "204", "0"], ["0", "38", "115", "18"], ["115", "12", "12", "1363"]])
        self.assertEqual(cm.exception.code, "range")
        self.assertEqual(cm.exception.rows, [3])

    def test_identical_colours_are_rejected(self):
        with self.assertRaises(LegendCsvError) as cm:
            parse_legend_csv_rows([["0", "0", "0", "0"], ["3.1", "0", "0", "0"], ["51", "0", "0", "0"]])
        self.assertEqual(cm.exception.code, "same_colour")

    def test_too_few_points_is_rejected_and_lists_skipped_rows(self):
        with self.assertRaises(LegendCsvError) as cm:
            parse_legend_csv_rows([["0", "204", "204", "204"], ["abc", "1", "2", "3"], ["x"]])
        self.assertEqual(cm.exception.code, "too_few")
        self.assertEqual(cm.exception.rows, [2, 3])

    def test_skipped_rows_are_reported_and_duplicates_keep_last(self):
        res = parse_legend_csv_rows([
            ["# comment"],
            ["0", "204", "204", "204"],
            ["oops", "1", "2", "3"],
            ["12", "230", "0", "0"],
            ["12", "115", "12", "12"],
            ["51, 10, 20, 30"],
        ])
        self.assertEqual(res.skipped_rows, [3])
        self.assertEqual([p.value for p in res.points], [0.0, 12.0, 51.0])
        self.assertEqual(res.points[1].rgb, (115, 12, 12))
        self.assertEqual(res.points[2].rgb, (10, 20, 30))
        self.assertTrue(any("1행" in n for n in res.notes))

    def test_reads_a_utf8_bom_file_with_header(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "legend.csv")
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write("value,r,g,b\n0,0.8,0.8,0.8\n51,0.45,0.05,0.05\n")
            res = legend_points_from_csv(path)
        self.assertTrue(res.scaled_from_unit)
        self.assertEqual(len(res.points), 2)
        self.assertEqual(res.points[0].rgb, (204, 204, 204))


class LegendImageSamplingTests(unittest.TestCase):
    def test_rows_sit_at_band_centres_not_image_edges(self):
        # 220 px tall bar with 11 anchors: 20 px bands, centres at 10, 30, ...
        rows = legend_sample_rows(11, 220, low_at_bottom=False)
        self.assertEqual(rows[0], 10)
        self.assertEqual(rows[-1], 210)
        self.assertEqual(len(rows), 11)
        self.assertTrue(all(0 < r < 219 for r in rows))
        self.assertEqual(rows, sorted(rows))

    def test_low_at_bottom_reverses_the_order(self):
        rows = legend_sample_rows(11, 220, low_at_bottom=True)
        self.assertEqual(rows[0], 210)
        self.assertEqual(rows[-1], 9)
        self.assertEqual(rows, sorted(rows, reverse=True))

    def test_rows_are_clamped_for_tiny_images(self):
        rows = legend_sample_rows(5, 2)
        self.assertTrue(all(0 <= r <= 1 for r in rows))

    def test_white_or_black_or_transparent_endpoints_are_flagged(self):
        good = [LegendPoint(0, (204, 204, 204)), LegendPoint(3.1, (0, 38, 115)), LegendPoint(51, (115, 12, 12))]
        self.assertIsNone(sampled_legend_problem(good))
        self.assertEqual(sampled_legend_problem([LegendPoint(0, (255, 255, 255))] + good[1:]), "endpoint_white")
        self.assertEqual(sampled_legend_problem(good[:-1] + [LegendPoint(51, (0, 0, 0))]), "endpoint_black")
        self.assertEqual(sampled_legend_problem(good, alphas=[255, 255, 0]), "endpoint_transparent")
        self.assertIsNone(sampled_legend_problem(good, alphas=[255, 255, 255]))

    def test_all_identical_samples_are_flagged(self):
        same = [LegendPoint(v, (90, 90, 90)) for v in (0, 1, 2)]
        self.assertEqual(sampled_legend_problem(same), "all_identical")
        # One repeated swatch in the middle is tolerated.
        mixed = [LegendPoint(0, (10, 20, 30)), LegendPoint(1, (10, 20, 30)), LegendPoint(2, (90, 90, 90))]
        self.assertIsNone(sampled_legend_problem(mixed))


if __name__ == "__main__":
    unittest.main()
