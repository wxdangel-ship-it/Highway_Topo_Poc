from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from .io_geojson import RoadRecord


def _safe_int(raw: Any) -> int | None:
    try:
        if raw is None:
            return None
        return int(raw)
    except Exception:
        return None


def _is_merge_or_diverge(kind: int | None) -> bool:
    if kind is None:
        return False
    return bool((int(kind) & (1 << 3)) != 0 or (int(kind) & (1 << 4)) != 0)


def _is_merge_kind(kind: int | None) -> bool:
    if kind is None:
        return False
    return bool((int(kind) & (1 << 3)) != 0)


def _is_diverge_kind(kind: int | None) -> bool:
    if kind is None:
        return False
    return bool((int(kind) & (1 << 4)) != 0)


def _edge_dist_limit_m(
    *,
    src_kind: int | None,
    dst_kind: int | None,
    continuous_dist_max_m: float,
    continuous_diverge_then_merge_dist_max_m: float,
) -> float:
    if _is_diverge_kind(src_kind) and _is_merge_kind(dst_kind):
        return float(continuous_diverge_then_merge_dist_max_m)
    return float(continuous_dist_max_m)


@dataclass(frozen=True)
class DirectedEdge:
    src: int
    dst: int
    road_idx: int
    direction: int
    length_m: float


@dataclass(frozen=True)
class ChainEdge:
    src: int
    dst: int
    dist_m: float
    path_road_indices: tuple[int, ...]
    start_road_idx: int


@dataclass(frozen=True)
class ChainComponent:
    component_id: str
    node_ids: tuple[int, ...]
    edges: tuple[ChainEdge, ...]
    offsets_m: dict[int, float]
    predecessors: dict[int, tuple[int, ...]]
    diag: dict[str, Any]


def build_effective_directed_edges(
    roads: list[RoadRecord],
) -> tuple[dict[int, list[DirectedEdge]], dict[int, set[int]], list[str]]:
    adjacency_out: dict[int, list[DirectedEdge]] = defaultdict(list)
    incident: dict[int, set[int]] = defaultdict(set)
    errors: list[str] = []

    for idx, road in enumerate(roads):
        direction = _safe_int(road.direction)
        if direction not in {2, 3}:
            if direction not in {0, 1}:
                errors.append(f"direction_invalid:road_idx={idx}:value={road.direction}")
            continue

        sn = int(road.snodeid)
        en = int(road.enodeid)
        length_m = float(max(0.0, road.length_m))
        incident[sn].add(int(idx))
        incident[en].add(int(idx))

        if direction == 2:
            edge = DirectedEdge(src=sn, dst=en, road_idx=int(idx), direction=int(direction), length_m=length_m)
        else:
            edge = DirectedEdge(src=en, dst=sn, road_idx=int(idx), direction=int(direction), length_m=length_m)
        adjacency_out[int(edge.src)].append(edge)

    return dict(adjacency_out), dict(incident), errors


def compute_degree(*, nodeid: int, incident_map: dict[int, set[int]]) -> int:
    return int(len(incident_map.get(int(nodeid), set())))


def follow_to_next_deg3(
    *,
    start_nodeid: int,
    first_edge: DirectedEdge,
    adjacency_out: dict[int, list[DirectedEdge]],
    incident_map: dict[int, set[int]],
    max_dist_m: float = 50.0,
    skip_deg2: bool = True,
) -> tuple[int, float, list[int], dict[str, Any]] | None:
    total = float(max(0.0, first_edge.length_m))
    if total > float(max_dist_m) + 1e-9:
        return None

    prev_node = int(start_nodeid)
    curr_node = int(first_edge.dst)
    path_edges = [int(first_edge.road_idx)]
    diag: dict[str, Any] = {
        "stopped_reason": "none",
        "deg2_steps": 0,
        "branch_stop": False,
    }

    hops = 0
    while hops < 256:
        hops += 1
        deg = compute_degree(nodeid=int(curr_node), incident_map=incident_map)
        if deg >= 3:
            return int(curr_node), float(total), path_edges, diag

        if not skip_deg2:
            diag["stopped_reason"] = "non_deg3_node"
            return None
        if deg != 2:
            diag["stopped_reason"] = "dead_end_or_isolated"
            return None

        out_edges = adjacency_out.get(int(curr_node), [])
        candidates = [e for e in out_edges if int(e.dst) != int(prev_node)]
        if len(candidates) != 1:
            diag["stopped_reason"] = "deg2_out_not_unique"
            diag["branch_stop"] = True
            return None

        nxt = candidates[0]
        total += float(max(0.0, nxt.length_m))
        if total > float(max_dist_m) + 1e-9:
            diag["stopped_reason"] = "distance_exceed"
            return None
        path_edges.append(int(nxt.road_idx))
        prev_node = int(curr_node)
        curr_node = int(nxt.dst)
        diag["deg2_steps"] = int(diag.get("deg2_steps", 0)) + 1

    diag["stopped_reason"] = "max_hops_reached"
    return None


def _connected_components(nodes: set[int], edges: list[ChainEdge]) -> list[set[int]]:
    if not nodes:
        return []
    undirected: dict[int, set[int]] = {int(n): set() for n in nodes}
    for e in edges:
        undirected.setdefault(int(e.src), set()).add(int(e.dst))
        undirected.setdefault(int(e.dst), set()).add(int(e.src))
    comps: list[set[int]] = []
    seen: set[int] = set()
    for n in sorted(nodes):
        if n in seen:
            continue
        q: deque[int] = deque([int(n)])
        seen.add(int(n))
        comp: set[int] = set()
        while q:
            cur = int(q.popleft())
            comp.add(cur)
            for nb in undirected.get(cur, set()):
                if nb in seen:
                    continue
                seen.add(nb)
                q.append(int(nb))
        comps.append(comp)
    return comps


def _topo_offsets(
    *,
    comp_nodes: set[int],
    comp_edges: list[ChainEdge],
) -> tuple[dict[int, float], dict[int, tuple[int, ...]], dict[str, Any]]:
    preds: dict[int, list[tuple[int, float]]] = {int(n): [] for n in comp_nodes}
    succs: dict[int, list[tuple[int, float]]] = {int(n): [] for n in comp_nodes}
    indeg: dict[int, int] = {int(n): 0 for n in comp_nodes}

    for e in comp_edges:
        src = int(e.src)
        dst = int(e.dst)
        if src not in comp_nodes or dst not in comp_nodes:
            continue
        preds[dst].append((src, float(e.dist_m)))
        succs[src].append((dst, float(e.dist_m)))
        indeg[dst] += 1

    sources = [n for n, d in indeg.items() if d == 0]
    offsets: dict[int, float] = {}
    q: deque[int] = deque(sorted(sources))
    for s in sources:
        offsets[int(s)] = 0.0

    processed = 0
    while q:
        cur = int(q.popleft())
        processed += 1
        cur_off = float(offsets.get(cur, 0.0))
        for nxt, dist in succs.get(cur, []):
            cand = cur_off + float(dist)
            if int(nxt) not in offsets or cand < float(offsets[int(nxt)]):
                offsets[int(nxt)] = float(cand)
            indeg[int(nxt)] = int(indeg[int(nxt)] - 1)
            if indeg[int(nxt)] == 0:
                q.append(int(nxt))

    is_dag = bool(processed == len(comp_nodes))
    cycle_nodes: list[int] = []
    if not is_dag:
        cycle_nodes = sorted([n for n, d in indeg.items() if d > 0])
        for n in cycle_nodes:
            offsets.setdefault(int(n), 0.0)
        changed = True
        guard = 0
        # Best-effort shortest-like relaxation for cyclic residual nodes.
        while changed and guard < 512:
            guard += 1
            changed = False
            for e in comp_edges:
                src = int(e.src)
                dst = int(e.dst)
                if src not in comp_nodes or dst not in comp_nodes:
                    continue
                cand = float(offsets.get(src, 0.0)) + float(e.dist_m)
                if dst not in offsets or cand < float(offsets[dst]):
                    offsets[dst] = float(cand)
                    changed = True

    pred_ids: dict[int, tuple[int, ...]] = {}
    for n, pred_list in preds.items():
        pred_ids[int(n)] = tuple(sorted([int(p) for p, _d in pred_list]))

    return offsets, pred_ids, {
        "is_dag": bool(is_dag),
        "sources": sorted([int(x) for x in sources]),
        "cycle_nodes": [int(x) for x in cycle_nodes],
    }


def build_continuous_graph(
    *,
    starts_set: set[int],
    nodes_kind: dict[int, int],
    roads: list[RoadRecord],
    continuous_dist_max_m: float = 50.0,
    continuous_diverge_then_merge_dist_max_m: float = 75.0,
) -> tuple[list[ChainEdge], list[ChainComponent], dict[str, Any]]:
    starts = {int(x) for x in starts_set}
    adjacency_out, incident_map, dir_errors = build_effective_directed_edges(roads)

    base_limit_m = float(continuous_dist_max_m)
    diverge_merge_limit_m = float(continuous_diverge_then_merge_dist_max_m)
    search_limit_m = float(max(base_limit_m, diverge_merge_limit_m))

    edges_map: dict[tuple[int, int], ChainEdge] = {}
    visit_queue: deque[int] = deque(sorted(starts))
    seen_expand: set[int] = set()
    trace_diag: dict[int, list[dict[str, Any]]] = defaultdict(list)

    while visit_queue:
        src = int(visit_queue.popleft())
        if src in seen_expand:
            continue
        seen_expand.add(src)
        src_kind = _safe_int(nodes_kind.get(int(src)))
        out_edges = adjacency_out.get(src, [])
        for first_edge in out_edges:
            out = follow_to_next_deg3(
                start_nodeid=int(src),
                first_edge=first_edge,
                adjacency_out=adjacency_out,
                incident_map=incident_map,
                max_dist_m=float(search_limit_m),
                skip_deg2=True,
            )
            if out is None:
                continue
            dst, dist_m, path_road_indices, diag = out
            dst_kind = _safe_int(nodes_kind.get(int(dst)))
            edge_limit_m = _edge_dist_limit_m(
                src_kind=src_kind,
                dst_kind=dst_kind,
                continuous_dist_max_m=base_limit_m,
                continuous_diverge_then_merge_dist_max_m=diverge_merge_limit_m,
            )
            trace_diag[src].append(
                {
                    "dst": int(dst),
                    "dist_m": float(dist_m),
                    "dist_limit_m": float(edge_limit_m),
                    "path_road_indices": [int(x) for x in path_road_indices],
                    "diag": dict(diag),
                }
            )
            if int(dst) not in starts:
                continue
            if not _is_merge_or_diverge(dst_kind):
                continue
            if float(dist_m) >= float(edge_limit_m):
                continue
            key = (int(src), int(dst))
            prev = edges_map.get(key)
            cur = ChainEdge(
                src=int(src),
                dst=int(dst),
                dist_m=float(dist_m),
                path_road_indices=tuple(int(x) for x in path_road_indices),
                start_road_idx=int(first_edge.road_idx),
            )
            if prev is None or float(cur.dist_m) < float(prev.dist_m):
                edges_map[key] = cur
            if int(dst) not in seen_expand:
                visit_queue.append(int(dst))

    chain_edges = sorted(list(edges_map.values()), key=lambda e: (int(e.src), int(e.dst), float(e.dist_m)))
    comp_nodes_all: set[int] = set()
    for e in chain_edges:
        comp_nodes_all.add(int(e.src))
        comp_nodes_all.add(int(e.dst))
    components_nodes = _connected_components(comp_nodes_all, chain_edges)

    components: list[ChainComponent] = []
    for idx, comp_nodes in enumerate(components_nodes):
        comp_edges = [e for e in chain_edges if int(e.src) in comp_nodes and int(e.dst) in comp_nodes]
        offsets, predecessors, topo_diag = _topo_offsets(comp_nodes=comp_nodes, comp_edges=comp_edges)
        component_id = f"chain_{idx:03d}"
        components.append(
            ChainComponent(
                component_id=component_id,
                node_ids=tuple(sorted([int(x) for x in comp_nodes])),
                edges=tuple(sorted(comp_edges, key=lambda e: (int(e.src), int(e.dst), float(e.dist_m)))),
                offsets_m={int(k): float(v) for k, v in offsets.items()},
                predecessors=predecessors,
                diag={"topology": topo_diag},
            )
        )

    graph_diag = {
        "starts_count": int(len(starts)),
        "dir_errors": list(dir_errors),
        "edge_count": int(len(chain_edges)),
        "component_count": int(len(components)),
        "trace": {str(k): v for k, v in trace_diag.items()},
    }
    return chain_edges, components, graph_diag


__all__ = [
    "DirectedEdge",
    "ChainEdge",
    "ChainComponent",
    "build_effective_directed_edges",
    "compute_degree",
    "follow_to_next_deg3",
    "build_continuous_graph",
]
