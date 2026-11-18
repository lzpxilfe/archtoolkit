# -*- coding: utf-8 -*-
"""Pin every numerical worked example published in docs/AHP_GUIDE.md (V8)."""

from __future__ import annotations

import os
import unittest

import numpy as np

from tools.ahp_core import (
    ahp_weights_from_matrix,
    compute_hierarchy_summary,
    matrix_from_pairs,
)


class AhpGuideExamplesTests(unittest.TestCase):
    def test_guide_document_exists(self):
        guide_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "AHP_GUIDE.md")
        self.assertTrue(os.path.isfile(guide_path))

    def test_section4_perfectly_consistent_8421(self):
        keys = ["경사", "하천", "지질", "일사"]
        pairs = {
            ("경사", "하천"): 2.0,
            ("경사", "지질"): 4.0,
            ("경사", "일사"): 8.0,
            ("하천", "지질"): 2.0,
            ("하천", "일사"): 4.0,
            ("지질", "일사"): 2.0,
        }
        w, lam, cr = ahp_weights_from_matrix(matrix_from_pairs(keys, pairs))
        # Published: 경사 53.3% 하천 26.7% 지질 13.3% 일사 6.7% CR = 0.000
        pct = [round(100.0 * x, 1) for x in w]
        self.assertEqual(pct, [53.3, 26.7, 13.3, 6.7])
        self.assertAlmostEqual(lam, 4.0, places=9)
        self.assertAlmostEqual(cr, 0.0, places=3)

    def test_section4_realistic_expert_example(self):
        keys = ["경사", "하천", "지질", "일사"]
        pairs = {
            ("경사", "하천"): 2.0,
            ("경사", "지질"): 5.0,
            ("경사", "일사"): 7.0,
            ("하천", "지질"): 3.0,
            ("하천", "일사"): 5.0,
            ("지질", "일사"): 2.0,
        }
        w, _lam, cr = ahp_weights_from_matrix(matrix_from_pairs(keys, pairs))
        # Published: 경사 52.7% 하천 30.1% 지질 11.0% 일사 6.3% CR = 0.007
        pct = [round(100.0 * x, 1) for x in w]
        self.assertEqual(pct, [52.7, 30.1, 11.0, 6.3])
        self.assertAlmostEqual(round(cr, 3), 0.007, places=3)

    def test_section5_cyclic_contradiction_example(self):
        keys = ["경사", "하천", "지질", "일사"]
        pairs = {
            ("경사", "하천"): 5.0,
            ("하천", "지질"): 5.0,
            ("경사", "지질"): 1.0 / 5.0,
            ("경사", "일사"): 3.0,
            ("하천", "일사"): 3.0,
            ("지질", "일사"): 3.0,
        }
        w, _lam, cr = ahp_weights_from_matrix(matrix_from_pairs(keys, pairs))
        # Published: 경사 31.5% 하천 31.5% 지질 31.5% 일사 5.5% CR = 1.009
        pct = [round(100.0 * x, 1) for x in w]
        self.assertEqual(pct, [31.5, 31.5, 31.5, 5.5])
        self.assertAlmostEqual(round(cr, 3), 1.009, places=3)

    def test_section6_hierarchy_9x9_clamped_flat_seed_example(self):
        summary = compute_hierarchy_summary(
            criteria_rows=[("A1", "A1"), ("A2", "A2"), ("B1", "B1"), ("B2", "B2")],
            criterion_groups={"A1": "GA", "A2": "GA", "B1": "GB", "B2": "GB"},
            group_pairs={("GA", "GB"): 9.0},
            local_pairs={"GA": {("A1", "A2"): 9.0}, "GB": {("B1", "B2"): 9.0}},
        )
        gw = [round(100.0 * summary["global_weights"][k], 1) for k in ("A1", "A2", "B1", "B2")]
        self.assertEqual(gw, [81.0, 9.0, 9.0, 1.0])
        self.assertTrue(summary["global_pairwise_clamped"])
        self.assertEqual(summary["global_pairwise_clamped_count"], 1)
        self.assertEqual(summary["global_pairwise_clamped_pairs"], [("A1", "B2")])

        mat_flat = matrix_from_pairs(["A1", "A2", "B1", "B2"], summary["global_pairwise"])
        w_flat, _lam_flat, cr_flat = ahp_weights_from_matrix(mat_flat)
        pct_flat = [round(100.0 * x, 1) for x in w_flat]
        # Published: A1 71.1% A2 13.0% B1 13.0% B2 2.9% CR = 0.243
        self.assertEqual(pct_flat, [71.1, 13.0, 13.0, 2.9])
        self.assertAlmostEqual(round(cr_flat, 3), 0.243, places=3)

    def test_section9_bronze_age_settlement_worked_example(self):
        keys = ["경사", "하천", "일사", "지질"]
        pairs = {
            ("경사", "하천"): 2.0,
            ("경사", "일사"): 5.0,
            ("경사", "지질"): 4.0,
            ("하천", "일사"): 3.0,
            ("하천", "지질"): 3.0,
            ("일사", "지질"): 1.0,
        }
        w, lam, cr = ahp_weights_from_matrix(matrix_from_pairs(keys, pairs))
        # Published: 경사 50.2%, 하천 29.0%, 지질 10.7%, 일사 10.1%, lambda_max = 4.0155, CR = 0.006
        by_key = {k: round(100.0 * v, 1) for k, v in zip(keys, w)}
        self.assertEqual(by_key, {"경사": 50.2, "하천": 29.0, "지질": 10.7, "일사": 10.1})
        self.assertAlmostEqual(round(lam, 4), 4.0155, places=4)
        self.assertAlmostEqual(round(cr, 3), 0.006, places=3)


if __name__ == "__main__":
    unittest.main()
