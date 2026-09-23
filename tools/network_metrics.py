# -*- coding: utf-8 -*-
"""QGIS-free social-network-analysis metrics on plain adjacency lists.

Weighted variants (Dijkstra) drive the cost network; unweighted variants
(BFS) drive the spatial/visibility network.  Both share the Wasserman-Faust
closeness correction (r/sum_d)*(r/(n-1)) and Brandes betweenness with the
undirected 0.5 normalization.  Keeping them here, free of QGIS, lets both
tools call one tested implementation instead of drifting copies.

Edge weights (weighted variants): every weight must be a finite number > 0.
The centrality functions REJECT anything else with ValueError instead of
dropping the edge.  Dropping a zero-weight edge used to be silent, and it made
two co-located sites (a 0-cost link) look unconnected: degree 1 and a shared
component, yet closeness 0 and no betweenness through the link.  A zero cost
is a caller-side modelling problem (the cost network gives same-cell sites a
straight-line cost instead), not something a metric should quietly repair.
``dijkstra_weighted`` keeps its historical lenient mode (non-positive weights
skipped) by default for direct callers; pass ``strict=True`` to reject.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from typing import List, Tuple
from .swallow_log import log_swallowed


def validate_positive_weights(adj: List[List[Tuple[int, float]]]) -> None:
    """Raise ValueError unless every edge weight is a finite number > 0.

    Used by the weighted centralities so an edge is never dropped silently
    (see the module docstring for why zero weights are rejected).
    """
    for v, nbrs in enumerate(adj):
        for w, weight in nbrs:
            try:
                ww = float(weight)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"edge {v}-{w}: weight {weight!r} is not a number") from exc
            if not math.isfinite(ww) or ww <= 0:
                raise ValueError(
                    f"edge {v}-{w}: weight {ww!r} must be finite and > 0 "
                    "(zero/negative weights are rejected, not dropped)"
                )


def dijkstra_weighted(*, start: int, adj: List[List[Tuple[int, float]]], strict: bool = False) -> List[float]:
    """Single-source shortest weighted distances (inf = unreachable).

    strict=False (default, historical behaviour pinned by tests): edges with a
    non-numeric, non-finite or non-positive weight are skipped.  strict=True
    raises ValueError for such an edge instead of dropping it.
    """
    if strict:
        validate_positive_weights(adj)
    n = int(len(adj))
    dist = [math.inf] * n
    s = int(start)
    if not (0 <= s < n):
        return dist
    dist[s] = 0.0
    heap: List[Tuple[float, int]] = [(0.0, s)]
    eps = 1e-12
    while heap:
        dv, v = heapq.heappop(heap)
        if dv > dist[v] + eps:
            continue
        for w, weight in adj[v]:
            _skip_33 = False
            try:
                ww = float(weight)
            except Exception as _exc:
                log_swallowed("tools/network_metrics.py:35 (dijkstra_weighted)", _exc)
                _skip_33 = True
            if _skip_33:
                continue
            if not math.isfinite(ww) or ww <= 0:
                continue
            nd = dv + ww
            if nd < dist[w] - eps:
                dist[w] = nd
                heapq.heappush(heap, (nd, int(w)))
    return dist


def closeness_centrality_weighted(*, n: int, adj: List[List[Tuple[int, float]]]) -> List[float]:
    """Closeness with the Wasserman–Faust component-size correction.

    Plain reachable/sum(dist) rewards nodes in tiny isolated components (a
    2-node pair scores the maximum) — backwards for disconnected graphs, which
    k-NN networks routinely are. Scaling by reachable/(n-1) weights the score
    by how much of the whole network the node can actually reach.

    Raises ValueError if any weight is not finite and > 0 (never drops an edge).
    """
    validate_positive_weights(adj)
    out = [0.0] * int(n)
    if n <= 1:
        return out
    for s in range(int(n)):
        dist = dijkstra_weighted(start=s, adj=adj)
        reachable = [d for d in dist if 0.0 < float(d) < math.inf]
        if not reachable:
            out[s] = 0.0
        else:
            r = float(len(reachable))
            out[s] = (r / float(sum(reachable))) * (r / float(n - 1))
    return out


def betweenness_centrality_weighted(*, n: int, adj: List[List[Tuple[int, float]]]) -> List[float]:
    """Brandes betweenness for weighted undirected graphs (no external deps).

    Raises ValueError if any weight is not finite and > 0 (never drops an edge).
    """
    validate_positive_weights(adj)
    bc = [0.0] * int(n)
    eps = 1e-12
    for s in range(int(n)):
        stack: List[int] = []
        pred: List[List[int]] = [[] for _ in range(int(n))]
        sigma = [0.0] * int(n)
        sigma[s] = 1.0
        dist = [math.inf] * int(n)
        dist[s] = 0.0

        heap: List[Tuple[float, int]] = [(0.0, int(s))]
        while heap:
            dv, v = heapq.heappop(heap)
            if dv > dist[v] + eps:
                continue
            stack.append(int(v))
            for w, weight in adj[v]:
                _skip_87 = False
                try:
                    ww = float(weight)
                except Exception as _exc:
                    log_swallowed("tools/network_metrics.py:89 (betweenness_centrality_weighted)", _exc)
                    _skip_87 = True
                if _skip_87:
                    continue
                if not math.isfinite(ww) or ww <= 0:
                    continue
                nd = dv + ww
                if nd < dist[w] - eps:
                    dist[w] = nd
                    heapq.heappush(heap, (nd, int(w)))
                    sigma[w] = sigma[v]
                    pred[w] = [int(v)]
                elif abs(nd - dist[w]) <= eps:
                    sigma[w] += sigma[v]
                    pred[w].append(int(v))

        delta = [0.0] * int(n)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                if sigma[w] > 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                bc[w] += delta[w]

    # Undirected normalization: each shortest path counted twice.
    for i in range(int(n)):
        bc[i] = bc[i] * 0.5
    return bc


def closeness_centrality_unweighted(*, n: int, adj: List[List[int]]) -> List[float]:
    """Closeness with the Wasserman–Faust component-size correction:
    (r/Σd)·(r/(n−1)). Without it a node in an isolated 2-node pair scores
    the maximum 1.0, which is backwards for the disconnected graphs
    (threshold/LOS) this tool routinely produces."""
    out = [0.0] * int(n)
    if n <= 1:
        return out
    for s in range(int(n)):
        dist = [-1] * int(n)
        dist[s] = 0
        q = deque([s])
        while q:
            v = q.popleft()
            for w in adj[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    q.append(w)
        reachable = [d for d in dist if d > 0]
        if not reachable:
            out[s] = 0.0
        else:
            r = float(len(reachable))
            out[s] = (r / float(sum(reachable))) * (r / float(n - 1))
    return out

def betweenness_centrality_unweighted(*, n: int, adj: List[List[int]]) -> List[float]:
    """Brandes betweenness for unweighted undirected graphs (no external deps)."""
    bc = [0.0] * int(n)
    for s in range(int(n)):
        stack: List[int] = []
        pred: List[List[int]] = [[] for _ in range(int(n))]
        sigma = [0.0] * int(n)
        sigma[s] = 1.0
        dist = [-1] * int(n)
        dist[s] = 0
        q = deque([s])

        while q:
            v = q.popleft()
            stack.append(v)
            for w in adj[v]:
                if dist[w] < 0:
                    q.append(w)
                    dist[w] = dist[v] + 1
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)

        delta = [0.0] * int(n)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                if sigma[w] > 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                bc[w] += delta[w]

    # Undirected normalization: each shortest path counted twice.
    for i in range(int(n)):
        bc[i] = bc[i] * 0.5
    return bc
