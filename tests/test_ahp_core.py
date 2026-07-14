from __future__ import annotations

import math
import unittest

import numpy as np

from tools.ahp_core import (
    RI_TABLE,
    ahp_weights_from_matrix,
    compute_hierarchy_summary,
    matrix_from_pairs,
    sanitize_pair_values,
)


def _consistent_matrix(weights):
    w = np.asarray(weights, dtype=float)
    return w[:, None] / w[None, :]


class AhpWeightsTests(unittest.TestCase):
    def test_empty_matrix_returns_nan(self):
        w, lam, cr = ahp_weights_from_matrix(np.zeros((0, 0)))
        self.assertEqual(w, [])
        self.assertTrue(math.isnan(lam))
        self.assertTrue(math.isnan(cr))

    def test_single_criterion_is_trivially_consistent(self):
        w, lam, cr = ahp_weights_from_matrix(np.ones((1, 1)))
        self.assertEqual(w, [1.0])
        self.assertEqual(lam, 1.0)
        self.assertEqual(cr, 0.0)

    def test_two_by_two_has_zero_consistency_ratio(self):
        # A 2x2 reciprocal matrix is always perfectly consistent.
        w, lam, cr = ahp_weights_from_matrix(np.array([[1.0, 4.0], [0.25, 1.0]]))
        self.assertEqual(cr, 0.0)
        self.assertAlmostEqual(sum(w), 1.0, places=9)
        self.assertAlmostEqual(w[0] / w[1], 4.0, places=6)

    def test_consistent_matrix_recovers_weights_and_zero_cr(self):
        w_true = [0.6, 0.3, 0.1]
        w, lam, cr = ahp_weights_from_matrix(_consistent_matrix(w_true))
        for got, exp in zip(w, w_true):
            self.assertAlmostEqual(got, exp, places=6)
        self.assertAlmostEqual(lam, 3.0, places=6)
        self.assertAlmostEqual(cr, 0.0, places=9)

    def test_larger_consistent_matrix_has_zero_cr(self):
        w_true = [0.4, 0.25, 0.15, 0.12, 0.08]
        w, lam, cr = ahp_weights_from_matrix(_consistent_matrix(w_true))
        self.assertAlmostEqual(lam, 5.0, places=6)
        self.assertAlmostEqual(cr, 0.0, places=9)
        self.assertAlmostEqual(sum(w), 1.0, places=9)

    def test_weights_are_positive_and_sum_to_one(self):
        mat = np.array([[1, 3, 5], [1.0 / 3, 1, 2], [0.2, 0.5, 1]], dtype=float)
        w, _lam, _cr = ahp_weights_from_matrix(mat)
        self.assertAlmostEqual(sum(w), 1.0, places=9)
        self.assertTrue(all(x > 0 for x in w))

    def test_strongly_inconsistent_matrix_has_large_cr(self):
        # A cyclic "rock-paper-scissors" preference is maximally inconsistent.
        mat = np.array(
            [[1, 9, 1.0 / 9], [1.0 / 9, 1, 9], [9, 1.0 / 9, 1]], dtype=float
        )
        _w, _lam, cr = ahp_weights_from_matrix(mat)
        self.assertGreater(cr, 0.1)

    def test_cr_increases_with_inconsistency(self):
        near = np.array([[1, 2, 4], [0.5, 1, 2.2], [0.25, 1.0 / 2.2, 1]], dtype=float)
        far = np.array([[1, 2, 4], [0.5, 1, 6.0], [0.25, 1.0 / 6.0, 1]], dtype=float)
        _wn, _ln, cr_near = ahp_weights_from_matrix(near)
        _wf, _lf, cr_far = ahp_weights_from_matrix(far)
        self.assertLess(cr_near, cr_far)

    def test_consistency_ratio_undefined_beyond_ri_table(self):
        n = max(RI_TABLE) + 1  # 16: no random index published
        w, _lam, cr = ahp_weights_from_matrix(_consistent_matrix([1.0] * n))
        self.assertEqual(len(w), n)
        # NaN is honest here; 0.0 would falsely certify consistency.
        self.assertTrue(math.isnan(cr))


class SanitizePairValuesTests(unittest.TestCase):
    def test_missing_pairs_default_to_one(self):
        out = sanitize_pair_values({}, ["a", "b", "c"])
        self.assertEqual(
            out, {("a", "b"): 1.0, ("a", "c"): 1.0, ("b", "c"): 1.0}
        )

    def test_reversed_pair_is_ordered_and_inverted(self):
        out = sanitize_pair_values({("b", "a"): 3.0}, ["a", "b"])
        self.assertAlmostEqual(out[("a", "b")], 1.0 / 3.0, places=9)

    def test_values_are_clamped_to_saaty_scale(self):
        out = sanitize_pair_values(
            {("a", "b"): 100.0, ("a", "c"): 0.0001}, ["a", "b", "c"]
        )
        self.assertEqual(out[("a", "b")], 9.0)
        self.assertAlmostEqual(out[("a", "c")], 1.0 / 9.0, places=9)

    def test_unknown_keys_are_dropped(self):
        out = sanitize_pair_values({("a", "z"): 5.0}, ["a", "b"])
        self.assertEqual(out, {("a", "b"): 1.0})

    def test_self_pairs_and_bad_values_are_dropped(self):
        out = sanitize_pair_values(
            {("a", "a"): 3.0, ("a", "b"): 0.0, ("b", "c"): -2.0}, ["a", "b", "c"]
        )
        # All three inputs are invalid, so only defaults survive.
        self.assertEqual(
            out, {("a", "b"): 1.0, ("a", "c"): 1.0, ("b", "c"): 1.0}
        )

    def test_non_finite_and_non_numeric_values_dropped(self):
        out = sanitize_pair_values(
            {("a", "b"): float("nan"), ("a", "c"): "oops"}, ["a", "b", "c"]
        )
        self.assertEqual(out[("a", "b")], 1.0)
        self.assertEqual(out[("a", "c")], 1.0)

    def test_json_list_form_with_group_keys(self):
        out = sanitize_pair_values(
            [{"left_group": "a", "right_group": "b", "value": 4}], ["a", "b"]
        )
        self.assertEqual(out[("a", "b")], 4.0)

    def test_json_list_form_with_layer_id_keys(self):
        out = sanitize_pair_values(
            [{"left_layer_id": "b", "right_layer_id": "a", "value": 2}], ["a", "b"]
        )
        self.assertAlmostEqual(out[("a", "b")], 0.5, places=9)


class MatrixFromPairsTests(unittest.TestCase):
    def test_reciprocal_structure(self):
        mat = matrix_from_pairs(["a", "b"], {("a", "b"): 3.0})
        self.assertAlmostEqual(mat[0, 1], 3.0, places=9)
        self.assertAlmostEqual(mat[1, 0], 1.0 / 3.0, places=9)
        self.assertEqual(mat[0, 0], 1.0)
        self.assertEqual(mat[1, 1], 1.0)

    def test_empty_keys_return_none(self):
        self.assertIsNone(matrix_from_pairs([], {}))

    def test_invalid_values_are_skipped(self):
        mat = matrix_from_pairs(["a", "b"], {("a", "b"): 0.0})
        # 0 is skipped, so the entry stays at the identity default of 1.
        self.assertEqual(mat[0, 1], 1.0)
        self.assertEqual(mat[1, 0], 1.0)


class HierarchySummaryTests(unittest.TestCase):
    def _rows(self, ids):
        return [(i, i.upper()) for i in ids]

    def test_global_weights_are_group_times_local_normalized(self):
        summary = compute_hierarchy_summary(
            criteria_rows=self._rows(["c1", "c2", "c3"]),
            criterion_groups={"c1": "G1", "c2": "G1", "c3": "G2"},
            group_pairs={("G1", "G2"): 2.0},  # G1 twice as important as G2
            local_pairs={"G1": {("c1", "c2"): 3.0}},  # within G1, c1:c2 = 3:1
        )
        gw = summary["global_weights"]
        self.assertAlmostEqual(sum(gw.values()), 1.0, places=9)
        # G1 gets 2/3, G2 gets 1/3; inside G1 c1:c2 = 3:1 -> 0.75/0.25.
        self.assertAlmostEqual(gw["c1"], (2.0 / 3.0) * 0.75, places=4)
        self.assertAlmostEqual(gw["c2"], (2.0 / 3.0) * 0.25, places=4)
        self.assertAlmostEqual(gw["c3"], 1.0 / 3.0, places=4)

    def test_group_order_and_consistency_reported(self):
        summary = compute_hierarchy_summary(
            criteria_rows=self._rows(["c1", "c2"]),
            criterion_groups={"c1": "G1", "c2": "G2"},
            group_pairs={("G1", "G2"): 1.0},
            local_pairs={},
        )
        self.assertEqual(summary["group_order"], ["G1", "G2"])
        # A single member per group -> local weight 1, no inconsistency.
        self.assertIn("group_weights", summary)

    def test_global_pairwise_is_clamped(self):
        summary = compute_hierarchy_summary(
            criteria_rows=self._rows(["c1", "c2"]),
            criterion_groups={"c1": "G1", "c2": "G2"},
            group_pairs={("G1", "G2"): 9.0},
            local_pairs={},
        )
        for ratio in summary["global_pairwise"].values():
            self.assertLessEqual(ratio, 9.0)
            self.assertGreaterEqual(ratio, 1.0 / 9.0)

    def test_empty_criteria_returns_empty_structures(self):
        summary = compute_hierarchy_summary(
            criteria_rows=[],
            criterion_groups={},
            group_pairs={},
            local_pairs={},
        )
        self.assertEqual(summary["group_order"], [])
        self.assertEqual(summary["global_weights"], {})
        self.assertEqual(summary["global_pairwise"], {})


if __name__ == "__main__":
    unittest.main()
