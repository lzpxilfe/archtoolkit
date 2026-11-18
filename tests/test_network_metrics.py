from __future__ import annotations

import math
import unittest

from tools.network_metrics import (
    betweenness_centrality_unweighted,
    betweenness_centrality_weighted,
    closeness_centrality_unweighted,
    closeness_centrality_weighted,
    dijkstra_weighted,
    validate_positive_weights,
    validate_symmetric_adjacency,
)


def _unit(adj):
    """Turn an unweighted adjacency list into a unit-weight weighted one."""
    return [[(w, 1.0) for w in nbrs] for nbrs in adj]


# Reusable topologies.
PATH = [[1], [0, 2], [1]]                 # 0-1-2
STAR = [[1, 2, 3], [0], [0], [0]]         # 0 is the hub
TRIANGLE = [[1, 2], [0, 2], [0, 1]]       # every pair adjacent
# 0-1 isolated pair; 2-3-4 triangle
DISCONNECTED = [[1], [0], [3, 4], [2, 4], [2, 3]]


class DijkstraTests(unittest.TestCase):
    def test_path_distances(self):
        self.assertEqual(dijkstra_weighted(start=0, adj=_unit(PATH)), [0.0, 1.0, 2.0])

    def test_unequal_weights(self):
        adj = [[(1, 2.0)], [(0, 2.0), (2, 3.0)], [(1, 3.0)]]
        self.assertEqual(dijkstra_weighted(start=0, adj=adj), [0.0, 2.0, 5.0])

    def test_unreachable_is_infinite(self):
        adj = [[(1, 1.0)], [(0, 1.0)], []]  # node 2 isolated
        dist = dijkstra_weighted(start=0, adj=adj)
        self.assertEqual(dist[1], 1.0)
        self.assertTrue(math.isinf(dist[2]))

    def test_start_out_of_range_returns_all_inf(self):
        dist = dijkstra_weighted(start=9, adj=_unit(PATH))
        self.assertTrue(all(math.isinf(d) for d in dist))

    def test_nonpositive_weights_are_ignored(self):
        adj = [[(1, 0.0), (2, -3.0)], [(0, 0.0)], [(0, -3.0)]]
        dist = dijkstra_weighted(start=0, adj=adj)
        self.assertTrue(math.isinf(dist[1]) and math.isinf(dist[2]))


class ClosenessTests(unittest.TestCase):
    def test_single_node_is_zero(self):
        self.assertEqual(closeness_centrality_unweighted(n=1, adj=[[]]), [0.0])
        self.assertEqual(closeness_centrality_weighted(n=1, adj=[[]]), [0.0])

    def test_path_wf_values(self):
        cl = closeness_centrality_unweighted(n=3, adj=PATH)
        self.assertAlmostEqual(cl[0], 2.0 / 3.0, places=9)
        self.assertAlmostEqual(cl[1], 1.0, places=9)
        self.assertAlmostEqual(cl[2], 2.0 / 3.0, places=9)

    def test_star_hub_scores_one(self):
        cl = closeness_centrality_unweighted(n=4, adj=STAR)
        self.assertAlmostEqual(cl[0], 1.0, places=9)
        # Leaf: distances 1,2,2 -> (3/5)*(3/3) = 0.6.
        self.assertAlmostEqual(cl[1], 0.6, places=9)

    def test_wasserman_faust_penalizes_small_components(self):
        # An isolated pair must NOT beat a node in the larger component.
        cl = closeness_centrality_unweighted(n=5, adj=DISCONNECTED)
        self.assertAlmostEqual(cl[0], 0.25, places=9)  # in the 2-node pair
        self.assertAlmostEqual(cl[2], 0.5, places=9)   # in the 3-node triangle
        self.assertGreater(cl[2], cl[0])

    def test_weighted_matches_unweighted_on_unit_weights(self):
        for topo in (PATH, STAR, TRIANGLE, DISCONNECTED):
            n = len(topo)
            uw = closeness_centrality_unweighted(n=n, adj=topo)
            wt = closeness_centrality_weighted(n=n, adj=_unit(topo))
            for a, b in zip(uw, wt):
                self.assertAlmostEqual(a, b, places=9)


class BetweennessTests(unittest.TestCase):
    def test_path_middle_node_bridges(self):
        bc = betweenness_centrality_unweighted(n=3, adj=PATH)
        self.assertAlmostEqual(bc[0], 0.0, places=9)
        self.assertAlmostEqual(bc[1], 1.0, places=9)
        self.assertAlmostEqual(bc[2], 0.0, places=9)

    def test_star_hub_bridges_all_leaf_pairs(self):
        # 3 leaf pairs each route through the hub.
        bc = betweenness_centrality_unweighted(n=4, adj=STAR)
        self.assertAlmostEqual(bc[0], 3.0, places=9)
        for leaf in (1, 2, 3):
            self.assertAlmostEqual(bc[leaf], 0.0, places=9)

    def test_triangle_has_no_betweenness(self):
        # Every pair is directly adjacent, so nobody is an intermediary.
        bc = betweenness_centrality_unweighted(n=3, adj=TRIANGLE)
        for x in bc:
            self.assertAlmostEqual(x, 0.0, places=9)

    def test_weighted_matches_unweighted_on_unit_weights(self):
        for topo in (PATH, STAR, TRIANGLE, DISCONNECTED):
            n = len(topo)
            uw = betweenness_centrality_unweighted(n=n, adj=topo)
            wt = betweenness_centrality_weighted(n=n, adj=_unit(topo))
            for a, b in zip(uw, wt):
                self.assertAlmostEqual(a, b, places=9)

    def test_weighted_shortest_path_diverts_betweenness(self):
        # Triangle where the direct 0-2 edge is expensive, so 0<->2 routes
        # through 1; node 1 gains betweenness the unweighted graph never gives it.
        adj = [[(1, 1.0), (2, 5.0)], [(0, 1.0), (2, 1.0)], [(0, 5.0), (1, 1.0)]]
        bc = betweenness_centrality_weighted(n=3, adj=adj)
        self.assertAlmostEqual(bc[1], 1.0, places=9)


class WeightValidationTests(unittest.TestCase):
    """Zero/negative/non-finite weights are rejected, never dropped silently.

    Dropping a 0-weight edge made two co-located sites look unconnected in
    closeness/betweenness while degree/component still counted the link.
    """

    ZERO = [[(1, 0.0), (2, 1.0)], [(0, 0.0)], [(0, 1.0)]]

    def test_centralities_reject_zero_weight(self):
        with self.assertRaises(ValueError):
            closeness_centrality_weighted(n=3, adj=self.ZERO)
        with self.assertRaises(ValueError):
            betweenness_centrality_weighted(n=3, adj=self.ZERO)

    def test_centralities_reject_negative_and_nonfinite(self):
        for bad in (-1.0, math.inf, math.nan, "x"):
            adj = [[(1, bad)], [(0, bad)]]
            with self.assertRaises(ValueError, msg=repr(bad)):
                closeness_centrality_weighted(n=2, adj=adj)
            with self.assertRaises(ValueError, msg=repr(bad)):
                betweenness_centrality_weighted(n=2, adj=adj)

    def test_strict_dijkstra_rejects_lenient_default_skips(self):
        with self.assertRaises(ValueError):
            dijkstra_weighted(start=0, adj=self.ZERO, strict=True)
        dist = dijkstra_weighted(start=0, adj=self.ZERO)
        self.assertTrue(math.isinf(dist[1]))
        self.assertEqual(dist[2], 1.0)

    def test_positive_weights_pass_validation(self):
        validate_positive_weights(_unit(STAR))
        validate_positive_weights([[(1, 1e-9)], [(0, 1e-9)]])


class SymmetryValidationTests(unittest.TestCase):
    ASYM = [[1], [0, 2], []]  # 1->2 without 2->1

    def test_asymmetric_adjacency_raises(self):
        with self.assertRaises(ValueError):
            validate_symmetric_adjacency(self.ASYM)
        with self.assertRaises(ValueError):
            betweenness_centrality_unweighted(n=3, adj=self.ASYM)
        with self.assertRaises(ValueError):
            betweenness_centrality_weighted(n=3, adj=_unit(self.ASYM))

    def test_symmetric_adjacency_passes(self):
        validate_symmetric_adjacency(PATH)
        bc = betweenness_centrality_unweighted(n=3, adj=PATH)
        self.assertAlmostEqual(bc[1], 1.0)  # 0.5 normalization: the middle node
        bc_w = betweenness_centrality_weighted(n=3, adj=_unit(PATH))
        self.assertAlmostEqual(bc_w[1], 1.0)


class TiedShortestPathAndExtendedMetricTests(unittest.TestCase):
    """V6 tied shortest paths plus clustering, transitivity, harmonic centrality & summary."""

    def test_tied_shortest_paths_c4_and_weighted_diamond(self):
        # 4-cycle C4: 0-1-2-3-0. Opposite pairs (0,2) and (1,3) have 2 equal paths each.
        c4 = [[1, 3], [0, 2], [1, 3], [0, 2]]
        bc_u = betweenness_centrality_unweighted(n=4, adj=c4)
        for v in bc_u:
            self.assertAlmostEqual(v, 0.5, places=12)

        bc_w = betweenness_centrality_weighted(n=4, adj=_unit(c4))
        for v in bc_w:
            self.assertAlmostEqual(v, 0.5, places=12)

        # Weighted diamond: 0-1 (1.0), 1-2 (1.0), 0-3 (1.0), 3-2 (1.0); pairs (0,2) split 0.5 each.
        # Plus distinct asymmetry (weights 1.0+1.0 vs 1.0+1.001) puts 100% of (0,2) through node 1.
        asym_diamond = [
            [(1, 1.0), (3, 1.0)],
            [(0, 1.0), (2, 1.0)],
            [(1, 1.0), (3, 1.001)],
            [(0, 1.0), (2, 1.001)],
        ]
        bc_asym = betweenness_centrality_weighted(n=4, adj=asym_diamond)
        self.assertGreater(bc_asym[1], bc_asym[3])
        self.assertAlmostEqual(bc_asym[1], 1.0, places=9)

    def test_clustering_and_transitivity_on_bowtie_and_star(self):
        from tools.network_metrics import global_transitivity, local_clustering_coefficients

        # Star 0 connected to {1, 2, 3}: zero triangles.
        star = [[1, 2, 3], [0], [0], [0]]
        self.assertEqual(local_clustering_coefficients(n=4, adj=star), [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(global_transitivity(n=4, adj=star), 0.0)

        # Bow-tie: triangle {0,1,2} + triangle {2,3,4} sharing node 2.
        # Nodes 0,1,3,4 have k=2 with 1 edge -> C=1.0; node 2 has k=4 with 2 edges / 6 pairs -> C=1/3.
        # Total wedges = 1+1+6+1+1 = 10; closed wedges = 1+1+2+1+1 = 6 -> transitivity = 0.6.
        bowtie = [[1, 2], [0, 2], [0, 1, 3, 4], [2, 4], [2, 3]]
        cc = local_clustering_coefficients(n=5, adj=bowtie)
        self.assertAlmostEqual(cc[0], 1.0, places=12)
        self.assertAlmostEqual(cc[1], 1.0, places=12)
        self.assertAlmostEqual(cc[2], 1.0 / 3.0, places=12)
        self.assertAlmostEqual(cc[3], 1.0, places=12)
        self.assertAlmostEqual(cc[4], 1.0, places=12)
        self.assertAlmostEqual(global_transitivity(n=5, adj=bowtie), 0.6, places=12)

    def test_harmonic_centrality_unweighted_weighted_and_graph_summary(self):
        from tools.network_metrics import (
            graph_summary,
            harmonic_centrality_unweighted,
            harmonic_centrality_weighted,
        )

        # Disconnected: triangle {0,1,2} + isolate {3}.
        # For nodes in triangle: 1/d=1 to two nodes, inf to node 3 -> sum=2, norm=(2/3). Isolate -> 0.0.
        adj = [[1, 2], [0, 2], [0, 1], []]
        hc_u = harmonic_centrality_unweighted(n=4, adj=adj)
        self.assertAlmostEqual(hc_u[0], 2.0 / 3.0, places=12)
        self.assertAlmostEqual(hc_u[3], 0.0, places=12)

        w_adj = [[(1, 2.0), (2, 2.0)], [(0, 2.0), (2, 2.0)], [(0, 2.0), (1, 2.0)], []]
        hc_w = harmonic_centrality_weighted(n=4, adj=w_adj)
        # sum of 1/2 + 1/2 = 1.0 divided by (4 - 1) = 1/3
        self.assertAlmostEqual(hc_w[0], 1.0 / 3.0, places=12)
        self.assertAlmostEqual(hc_w[3], 0.0, places=12)

        summary = graph_summary(n=4, adj=adj)
        self.assertEqual(summary["n_nodes"], 4)
        self.assertEqual(summary["n_edges"], 3)
        self.assertAlmostEqual(summary["density"], 0.5, places=12)
        self.assertEqual(summary["n_components"], 2)
        self.assertEqual(summary["largest_component_size"], 3)
        self.assertAlmostEqual(summary["avg_clustering"], 0.75, places=12)
        self.assertAlmostEqual(summary["transitivity"], 1.0, places=12)


if __name__ == "__main__":
    unittest.main()
