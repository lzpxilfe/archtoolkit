# -*- coding: utf-8 -*-
"""QGIS-free Kruskal Minimum Spanning Tree (MST) / Forest builder.

Reference:
- Kruskal, J. B. (1956). On the shortest spanning subtree of a graph and the
  traveling salesman problem. Proceedings of the AMS, 7(1), 48-50.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple


class UnionFind:
    """Disjoint-set (Union-Find) structure with path halving and union by rank."""

    def __init__(self, n: int):
        self.parent = list(range(max(0, int(n))))
        self.rank = [0] * max(0, int(n))

    def find(self, a: int) -> int:
        a = int(a)
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a: int, b: int) -> bool:
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return False
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1
        return True


def kruskal_mst(
    n_nodes: int,
    weighted_edges: Sequence[Tuple[float, int, int]],
) -> Dict[str, Any]:
    """Compute Kruskal MST/MSF over `n_nodes` vertices indexed 0..n_nodes-1.

    Returns ``{"edges": [(u, v), ...], "total_weight": float, "complete": bool,
    "components": int}`` where ``complete`` is True iff all vertices lie in a
    single spanning tree. Non-finite weights, out-of-range vertex indices, and
    self-loops are ignored cleanly.
    """
    n = max(0, int(n_nodes))
    if n == 0:
        return {"edges": [], "total_weight": 0.0, "complete": True, "components": 0}

    cleaned: List[Tuple[float, int, int]] = []
    for raw_w, raw_u, raw_v in weighted_edges:
        bad_row = False
        try:
            w = float(raw_w)
            u = int(raw_u)
            v = int(raw_v)
        except (TypeError, ValueError):
            bad_row = True
            w, u, v = 0.0, -1, -1
        if bad_row or (not math.isfinite(w)) or u == v or not (0 <= u < n and 0 <= v < n):
            continue
        a, b = (u, v) if u < v else (v, u)
        cleaned.append((w, a, b))

    cleaned.sort(key=lambda t: (t[0], t[1], t[2]))
    uf = UnionFind(n)
    chosen: List[Tuple[int, int]] = []
    total_weight = 0.0
    for w, a, b in cleaned:
        if uf.union(a, b):
            chosen.append((a, b))
            total_weight += float(w)
            if len(chosen) >= n - 1:
                break

    components = len({uf.find(i) for i in range(n)})
    return {
        "edges": chosen,
        "total_weight": float(total_weight),
        "complete": bool(components <= 1),
        "components": int(components),
    }
