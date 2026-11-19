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


def validate_symmetric_adjacency(adj) -> None:
    """Raise ValueError unless every edge v-w has a reciprocal w-v (with matching weight when weighted).

    Betweenness normalizes by 0.5 because each shortest path is counted twice
    on an undirected graph; on a directed (asymmetric) adjacency that factor
    silently halves every score. Checked strictly, like the weights above,
    instead of trusting the caller.
    """
    seen = set()
    weights = {}
    for v, nbrs in enumerate(adj):
        for entry in nbrs:
            if isinstance(entry, tuple):
                w = int(entry[0])
                ww = float(entry[1])
                weights.setdefault((int(v), w), []).append(ww)
            else:
                w = int(entry)
            seen.add((int(v), w))
    for v, w in seen:
        if (w, v) not in seen:
            raise ValueError(
                f"adjacency is not symmetric: edge {v}-{w} has no {w}-{v} "
                "(betweenness assumes undirected edges)"
            )
        w_vw = weights.get((v, w))
        w_wv = weights.get((w, v))
        if w_vw and w_wv and (min(w_vw) != min(w_wv) and not math.isclose(min(w_vw), min(w_wv), rel_tol=1e-9, abs_tol=1e-12)):
            raise ValueError(
                f"adjacency weights are not symmetric: edge {v}-{w} ({min(w_vw)!r}) != {w}-{v} ({min(w_wv)!r})"
            )


def _dedupe_weighted_adj(adj: List[List[Tuple[int, float]]]) -> List[List[Tuple[int, float]]]:
    """Collapse parallel edges (v, w) keeping the minimum finite positive weight."""
    out: List[List[Tuple[int, float]]] = []
    for _v, nbrs in enumerate(adj):
        best = {}
        for w, weight in nbrs:
            wi = int(w)
            ww = float(weight)
            if wi not in best or ww < best[wi]:
                best[wi] = ww
        out.append([(w, best[w]) for w in sorted(best)])
    return out


def _dedupe_unweighted_adj(adj: List[List[int]]) -> List[List[int]]:
    """Collapse parallel neighbor entries in unweighted adjacency lists."""
    return [sorted({int(w) for w in nbrs}) for nbrs in adj]


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
    settled = [False] * n
    s = int(start)
    if not (0 <= s < n):
        return dist
    dist[s] = 0.0
    heap: List[Tuple[float, int]] = [(0.0, s)]
    while heap:
        dv, v = heapq.heappop(heap)
        if settled[v]:
            continue
        settled[v] = True
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
            wi = int(w)
            if settled[wi]:
                continue
            nd = dv + ww
            tol = 1e-12 * max(1.0, abs(nd), abs(dist[wi]) if math.isfinite(dist[wi]) else 0.0)
            if nd < dist[wi] - tol:
                dist[wi] = nd
                heapq.heappush(heap, (nd, wi))
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

    Raises ValueError if any weight is not finite and > 0 (never drops an edge)
    or if the adjacency is not symmetric (the 0.5 undirected normalization
    would silently halve every score on a directed graph).
    """
    validate_positive_weights(adj)
    validate_symmetric_adjacency(adj)
    adj = _dedupe_weighted_adj(adj)
    bc = [0.0] * int(n)
    n_int = int(n)
    for s in range(n_int):
        stack: List[int] = []
        pred: List[List[int]] = [[] for _ in range(n_int)]
        sigma = [0.0] * n_int
        sigma[s] = 1.0
        dist = [math.inf] * n_int
        dist[s] = 0.0
        settled = [False] * n_int

        heap: List[Tuple[float, int]] = [(0.0, int(s))]
        while heap:
            dv, v = heapq.heappop(heap)
            if settled[v]:
                continue
            settled[v] = True
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
                wi = int(w)
                if settled[wi]:
                    continue
                nd = dv + ww
                ref_scale = max(1.0, abs(nd), abs(dist[wi]) if math.isfinite(dist[wi]) else 0.0)
                tol = 1e-12 * ref_scale
                if nd < dist[wi] - tol:
                    dist[wi] = nd
                    heapq.heappush(heap, (nd, wi))
                    sigma[wi] = sigma[v]
                    pred[wi] = [int(v)]
                elif abs(nd - dist[wi]) <= tol:
                    sigma[wi] += sigma[v]
                    pred[wi].append(int(v))

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
    """Brandes betweenness for unweighted undirected graphs (no external deps).

    Raises ValueError on an asymmetric adjacency: the 0.5 undirected
    normalization would silently halve every score on a directed graph.
    """
    validate_symmetric_adjacency(adj)
    adj = _dedupe_unweighted_adj(adj)
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


def _clean_simple_nbr_sets(*, n: int, adj: List[List[int]]) -> List[set]:
    validate_symmetric_adjacency(adj)
    clean = _dedupe_unweighted_adj(adj)
    return [{int(v) for v in clean[i] if int(v) != i and 0 <= int(v) < int(n)} for i in range(int(n))]


def local_clustering_coefficients(*, n: int, adj: List[List[int]]) -> List[float]:
    """Watts & Strogatz (1998) local clustering coefficient per node: C_i = 2 e_i / (k_i (k_i - 1))."""
    nn = int(n)
    if nn <= 0:
        return []
    nbr_sets = _clean_simple_nbr_sets(n=nn, adj=adj)
    out = [0.0] * nn
    for i in range(nn):
        nbrs = nbr_sets[i]
        k = len(nbrs)
        if k < 2:
            continue
        doubled_edges = 0
        for u in nbrs:
            doubled_edges += len(nbrs & nbr_sets[u])
        out[i] = float(doubled_edges) / float(k * (k - 1))
    return out


def global_transitivity(*, n: int, adj: List[List[int]]) -> float:
    """Global graph transitivity: 3 * triangles / connected_triples."""
    nn = int(n)
    if nn <= 2:
        return 0.0
    nbr_sets = _clean_simple_nbr_sets(n=nn, adj=adj)
    wedges = 0
    closed_wedges = 0
    for i in range(nn):
        nbrs = nbr_sets[i]
        k = len(nbrs)
        if k < 2:
            continue
        wedges += (k * (k - 1)) // 2
        doubled_edges = 0
        for u in nbrs:
            doubled_edges += len(nbrs & nbr_sets[u])
        closed_wedges += doubled_edges // 2
    if wedges <= 0:
        return 0.0
    return float(closed_wedges) / float(wedges)


def harmonic_centrality_unweighted(*, n: int, adj: List[List[int]]) -> List[float]:
    """Boldi & Vigna (2014) normalized harmonic centrality: (1/(n-1)) * sum_{j != i} 1/d(i, j)."""
    nn = int(n)
    if nn <= 0:
        return []
    if nn == 1:
        return [0.0]
    clean = _dedupe_unweighted_adj(adj)
    out = [0.0] * nn
    denom = float(nn - 1)
    for s in range(nn):
        dist = [-1] * nn
        dist[s] = 0
        q = deque([s])
        while q:
            v = q.popleft()
            dv = dist[v] + 1
            for w in clean[v]:
                if dist[w] < 0:
                    dist[w] = dv
                    q.append(w)
        inv_sum = 0.0
        for t in range(nn):
            if t != s and dist[t] > 0:
                inv_sum += 1.0 / float(dist[t])
        out[s] = inv_sum / denom
    return out


def harmonic_centrality_weighted(*, n: int, adj: List[List[tuple]]) -> List[float]:
    """Weighted normalized harmonic centrality (Boldi & Vigna 2014) via Dijkstra distances."""
    import heapq
    import math

    nn = int(n)
    if nn <= 0:
        return []
    if len(adj) != nn:
        raise ValueError(f"Adjacency length {len(adj)} does not match n={nn}")

    dedup = []
    for u in range(nn):
        best_map = {}
        for item in adj[u]:
            v, raw_w = int(item[0]), float(item[1])
            if (not math.isfinite(raw_w)) or raw_w <= 0.0:
                raise ValueError(f"Weighted harmonic centrality requires positive finite weights (edge {u}->{v}: {raw_w})")
            if v == u:
                continue
            prev = best_map.get(v)
            if prev is None or raw_w < prev:
                best_map[v] = raw_w
        dedup.append(best_map)

    for u in range(nn):
        for v, w in dedup[u].items():
            rev = dedup[v].get(u)
            if rev is None or not math.isclose(w, rev, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError(f"Asymmetric weighted adjacency for edge ({u}, {v})")

    if nn == 1:
        return [0.0]

    out = [0.0] * nn
    denom = float(nn - 1)
    for s in range(nn):
        dist = [math.inf] * nn
        dist[s] = 0.0
        pq = [(0.0, s)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for v, w in dedup[u].items():
                nd = d + w
                if nd < dist[v]:
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
        inv_sum = 0.0
        for t in range(nn):
            if t != s and math.isfinite(dist[t]) and dist[t] > 0.0:
                inv_sum += 1.0 / float(dist[t])
        out[s] = inv_sum / denom
    return out


def graph_summary(*, n: int, adj: List[List[int]]) -> dict:
    """Summarize undirected graph topology (components, density, Watts-Strogatz clustering)."""
    nn = int(n)
    if nn <= 0:
        return {
            "n_nodes": 0,
            "n_edges": 0,
            "density": 0.0,
            "n_components": 0,
            "largest_component_size": 0,
            "avg_clustering": 0.0,
            "transitivity": 0.0,
        }
    nbr_sets = _clean_simple_nbr_sets(n=nn, adj=adj)
    n_edges = sum(len(s) for s in nbr_sets) // 2
    density = (2.0 * float(n_edges)) / float(nn * (nn - 1)) if nn > 1 else 0.0

    visited = [False] * nn
    comp_sizes = []
    for s in range(nn):
        if visited[s]:
            continue
        visited[s] = True
        q = deque([s])
        sz = 0
        while q:
            u = q.popleft()
            sz += 1
            for v in nbr_sets[u]:
                if not visited[v]:
                    visited[v] = True
                    q.append(v)
        comp_sizes.append(sz)

    clean = [sorted(s) for s in nbr_sets]
    cc = local_clustering_coefficients(n=nn, adj=clean)
    trans = global_transitivity(n=nn, adj=clean)
    return {
        "n_nodes": nn,
        "n_edges": int(n_edges),
        "density": float(density),
        "n_components": int(len(comp_sizes)),
        "largest_component_size": int(max(comp_sizes) if comp_sizes else 0),
        "avg_clustering": float(sum(cc) / float(nn)),
        "transitivity": float(trans),
    }
