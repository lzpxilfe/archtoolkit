from __future__ import annotations

import unittest

from tools.cost_budget import (
    ALWAYS_ALLOW_CELLS,
    MAX_BATCH_SECONDS,
    assess_batch,
    assess_windows,
    LEVEL_OK,
    LEVEL_REFUSE,
    LEVEL_WARN,
    MEMORY_SAFETY_FRACTION,
    PER_CELL_BYTES,
    CostBudgetError,
    assess,
    available_memory_bytes,
    cell_budget,
    estimate_bytes,
    estimate_seconds,
    suggested_pixel_size,
)

GB = 1024 ** 3


class EstimateTests(unittest.TestCase):
    def test_estimates_scale_linearly(self):
        self.assertEqual(estimate_bytes(1_000_000), 1_000_000 * PER_CELL_BYTES)
        self.assertAlmostEqual(estimate_seconds(2_000_000),
                               2 * estimate_seconds(1_000_000), places=6)

    def test_measured_reference_point_is_in_the_right_ballpark(self):
        # The loop was measured at 1,000,000 cells: ~10.2 s, ~128 MB. The
        # constants carry headroom, so the estimate must be at least that and
        # not wildly above it - if either drifts an order of magnitude the
        # warning text stops being useful.
        self.assertGreaterEqual(estimate_seconds(1_000_000), 10.0)
        self.assertLess(estimate_seconds(1_000_000), 30.0)
        self.assertGreaterEqual(estimate_bytes(1_000_000), 128 * 10 ** 6)
        self.assertLess(estimate_bytes(1_000_000), 512 * 10 ** 6)

    def test_zero_and_negative_cells(self):
        self.assertEqual(estimate_bytes(0), 0)
        self.assertEqual(estimate_bytes(-5), 0)


class CellBudgetTests(unittest.TestCase):
    def test_budget_is_the_safety_share_of_available_memory(self):
        self.assertEqual(cell_budget(8 * GB),
                         int(8 * GB * MEMORY_SAFETY_FRACTION // PER_CELL_BYTES))

    def test_more_memory_means_a_bigger_budget(self):
        self.assertGreater(cell_budget(16 * GB), cell_budget(4 * GB))

    def test_a_typical_laptop_clears_the_old_flat_cap(self):
        # The whole point of the change: 4M cells was a constant unrelated to
        # the machine. 4 GB free should comfortably beat it.
        self.assertGreater(cell_budget(4 * GB), ALWAYS_ALLOW_CELLS)

    def test_degenerate_memory_values(self):
        self.assertEqual(cell_budget(0), 0)
        self.assertEqual(cell_budget(-1), 0)


class AssessTests(unittest.TestCase):
    def test_small_runs_are_never_interrupted(self):
        verdict = assess(500_000, available_bytes=8 * GB)
        self.assertEqual(verdict.level, LEVEL_OK)

    def test_the_old_cap_now_passes_without_a_prompt(self):
        # 4M cells is ~42 s and ~0.6 GB: it used to be refused outright.
        verdict = assess(4_000_000, available_bytes=8 * GB)
        self.assertEqual(verdict.level, LEVEL_OK)

    def test_a_long_but_fitting_run_warns_rather_than_refusing(self):
        # The Chungju 5 m grid: ~38.3M cells. On a machine with room, this is a
        # choice the user is allowed to make.
        verdict = assess(38_300_000, available_bytes=32 * GB)
        self.assertEqual(verdict.level, LEVEL_WARN)
        self.assertGreater(verdict.minutes, 1.0)

    def test_confirmation_turns_a_warning_into_a_go(self):
        verdict = assess(38_300_000, available_bytes=32 * GB, confirmed=True)
        self.assertEqual(verdict.level, LEVEL_OK)

    def test_confirmation_cannot_override_a_refusal(self):
        # Refusal means it does not fit in memory; agreeing to wait does not
        # create RAM, and the failure mode is the session dying.
        verdict = assess(500_000_000, available_bytes=2 * GB, confirmed=True)
        self.assertEqual(verdict.level, LEVEL_REFUSE)

    def test_refusal_carries_a_pixel_size_that_would_fit(self):
        verdict = assess(38_300_000, available_bytes=1 * GB, current_pixel_size=5.0)
        self.assertEqual(verdict.level, LEVEL_REFUSE)
        self.assertIsNotNone(verdict.suggested_pixel)
        self.assertGreater(verdict.suggested_pixel, 5.0)

    def test_the_same_extent_can_pass_on_a_bigger_machine(self):
        # This is what "raise the cap" actually has to mean: the answer depends
        # on the machine, not on a constant.
        cells = 20_000_000
        self.assertEqual(assess(cells, available_bytes=1 * GB).level, LEVEL_REFUSE)
        self.assertIn(assess(cells, available_bytes=32 * GB).level,
                      (LEVEL_OK, LEVEL_WARN))

    def test_negative_cells_rejected(self):
        with self.assertRaises(CostBudgetError):
            assess(-1, available_bytes=GB)

    def test_memory_known_flag_is_carried_through(self):
        self.assertTrue(assess(1000, available_bytes=GB).memory_known)
        self.assertFalse(assess(1000, available_bytes=GB, memory_known=False).memory_known)


class BatchTests(unittest.TestCase):
    """A least-cost network repeats the accumulation once per directed pair."""

    def test_a_single_run_batch_matches_a_plain_assessment(self):
        single = assess(2_000_000, available_bytes=16 * GB, confirmed=True)
        batch = assess_batch(2_000_000, 1, available_bytes=16 * GB)
        self.assertAlmostEqual(batch.seconds, single.seconds, places=6)

    def test_time_accumulates_across_runs(self):
        one = assess_batch(1_000_000, 1, available_bytes=16 * GB)
        fifty = assess_batch(1_000_000, 50, available_bytes=16 * GB)
        self.assertAlmostEqual(fifty.seconds, one.seconds * 50, places=3)

    def test_a_window_that_is_fine_alone_is_refused_when_repeated_enough(self):
        # The regression this exists to prevent: raising the per-window limit
        # without counting the repeats turns an instant refusal into an
        # overnight run.
        alone = assess_batch(4_000_000, 1, available_bytes=32 * GB)
        self.assertNotEqual(alone.level, LEVEL_REFUSE)
        repeated = assess_batch(4_000_000, 400, available_bytes=32 * GB)
        self.assertEqual(repeated.level, LEVEL_REFUSE)
        self.assertGreater(repeated.seconds, MAX_BATCH_SECONDS)

    def test_memory_refusal_still_wins(self):
        verdict = assess_batch(500_000_000, 1, available_bytes=2 * GB,
                               current_pixel_size=5.0)
        self.assertEqual(verdict.level, LEVEL_REFUSE)

    def test_time_refusal_suggests_a_pixel_size(self):
        verdict = assess_batch(4_000_000, 400, available_bytes=32 * GB,
                               current_pixel_size=5.0)
        self.assertEqual(verdict.level, LEVEL_REFUSE)
        self.assertIsNotNone(verdict.suggested_pixel)
        self.assertGreater(verdict.suggested_pixel, 5.0)

    def test_a_modest_batch_still_warns_rather_than_refusing(self):
        verdict = assess_batch(1_000_000, 20, available_bytes=32 * GB)
        self.assertEqual(verdict.level, LEVEL_WARN)

    def test_zero_runs_treated_as_one(self):
        self.assertEqual(assess_batch(1000, 0, available_bytes=GB).level,
                         assess_batch(1000, 1, available_bytes=GB).level)


class WindowsTests(unittest.TestCase):
    """The network's windows differ per pair; the batch is judged once, up front."""

    def test_mixed_windows_are_not_refused_by_their_largest_member(self):
        # Review case: k-NN over 60 sites, most windows small, one far pair
        # at 2M cells. Extrapolating 2M across 360 directed paths refused a
        # run whose real total is a few minutes.
        windows = [50_000] * 359 + [2_000_000]
        verdict = assess_windows(windows, available_bytes=16 * GB)
        self.assertNotEqual(verdict.level, LEVEL_REFUSE)
        self.assertLess(verdict.seconds, MAX_BATCH_SECONDS)

    def test_time_is_the_sum_and_memory_is_the_largest(self):
        windows = [1_000_000, 3_000_000, 2_000_000]
        verdict = assess_windows(windows, available_bytes=16 * GB)
        self.assertAlmostEqual(verdict.seconds, sum(estimate_seconds(c) for c in windows), places=6)
        self.assertEqual(verdict.cells, 3_000_000)

    def test_a_batch_too_long_in_total_is_still_refused(self):
        windows = [3_000_000] * 300
        verdict = assess_windows(windows, available_bytes=32 * GB, current_pixel_size=5.0)
        self.assertEqual(verdict.level, LEVEL_REFUSE)
        self.assertIsNotNone(verdict.suggested_pixel)

    def test_one_window_that_does_not_fit_in_memory_refuses(self):
        verdict = assess_windows([1_000, 500_000_000], available_bytes=2 * GB)
        self.assertEqual(verdict.level, LEVEL_REFUSE)

    def test_empty_batch_is_ok(self):
        self.assertEqual(assess_windows([], available_bytes=GB).level, LEVEL_OK)

    def test_time_can_be_downgraded_to_a_warning(self):
        # The network's pairs run A* over a corridor, so its estimate is an
        # upper bound; a caller may ask for time to warn rather than refuse.
        # Memory must still refuse regardless.
        windows = [3_000_000] * 300
        self.assertEqual(assess_windows(windows, available_bytes=32 * GB).level, LEVEL_REFUSE)
        relaxed = assess_windows(windows, available_bytes=32 * GB, time_refuses=False)
        self.assertEqual(relaxed.level, LEVEL_WARN)
        self.assertGreater(relaxed.seconds, MAX_BATCH_SECONDS)
        self.assertEqual(
            assess_windows([500_000_000], available_bytes=2 * GB, time_refuses=False).level,
            LEVEL_REFUSE)


class SuggestedPixelTests(unittest.TestCase):
    def test_returns_none_when_it_already_fits(self):
        self.assertIsNone(suggested_pixel_size(5.0, 1_000_000, 10_000_000))

    def test_scales_with_the_square_root_of_the_overshoot(self):
        # 4x the cells needs 2x the pixel size; rounded up to a round number.
        suggested = suggested_pixel_size(5.0, 4_000_000, 1_000_000)
        self.assertIsNotNone(suggested)
        self.assertGreaterEqual(suggested, 10.0)

    def test_suggestion_actually_fits(self):
        for cells, budget, px in ((38_300_000, 3_000_000, 5.0),
                                  (100_000_000, 8_000_000, 1.0),
                                  (9_000_000, 1_000_000, 2.0)):
            suggested = suggested_pixel_size(px, cells, budget)
            self.assertIsNotNone(suggested)
            # Cell count falls with the square of pixel size.
            resulting = cells * (px / suggested) ** 2
            self.assertLessEqual(resulting, budget,
                                 msg=f"{px}->{suggested} still yields {resulting:.0f} cells")

    def test_suggestions_are_round_numbers(self):
        for cells, budget, px in ((38_300_000, 3_000_000, 5.0),
                                  (50_000_000, 4_000_000, 5.0)):
            suggested = suggested_pixel_size(px, cells, budget)
            mantissa = suggested / 10 ** (len(str(int(suggested))) - 1)
            self.assertIn(round(mantissa, 6), (1.0, 2.0, 5.0, 10.0),
                          msg=f"{suggested} is not a round step")

    def test_degenerate_inputs(self):
        self.assertIsNone(suggested_pixel_size(0, 10, 1))
        self.assertIsNone(suggested_pixel_size(-5, 10, 1))
        self.assertIsNone(suggested_pixel_size(None, 10, 1))
        self.assertIsNone(suggested_pixel_size(5.0, 10, 0))


class AvailableMemoryTests(unittest.TestCase):
    def test_returns_a_plausible_value_or_none(self):
        value = available_memory_bytes()
        if value is not None:
            self.assertGreater(value, 0)
            # Anything under 16 MB or over a petabyte means we misread a unit.
            self.assertGreater(value, 16 * 1024 ** 2)
            self.assertLess(value, 1024 ** 5)


if __name__ == "__main__":
    unittest.main()
