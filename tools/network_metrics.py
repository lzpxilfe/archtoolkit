# -*- coding: utf-8 -*-
"""QGIS-free social-network-analysis metrics on plain adjacency lists.

Weighted variants (Dijkstra) drive the cost network; unweighted variants
(BFS) drive the spatial/visibility network.  Both share the Wasserman-Faust
closeness correction (r/sum_d)*(r/(n-1)) and Brandes betweenness with the
undirected 0.5 normalization.  Keeping them here, free of QGIS, lets both
tools call one tested implementation instead of drifting copies.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from typing import List, Tuple


def dijkstra_weighted(*, start: int, adj: List[List[Tuple[int, float]]]) -> List[float]:
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
            try:
                ww = float(weight)
            except Exception:
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
    """
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
    """Brandes betweenness for weighted undirected graphs (no external deps)."""
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
                try:
                    ww = float(weight)
                except Exception:
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
