from __future__ import annotations

import math
import unittest

from tools.network_metrics import (
    betweenness_centrality_unweighted,
    betweenness_centrality_weighted,
    closeness_centrality_unweighted,
    closeness_centrality_weighted,
    dijkstra_weighted,
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


if __name__ == "__main__":
    unittest.main()
