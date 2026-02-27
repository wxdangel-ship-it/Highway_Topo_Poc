from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Iterable, Sequence

import numpy as np
from shapely import contains_xy
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, nearest_points, substring

from .io import CrossSection, TrajectoryData


HARD_MULTI_ROAD = "MULTI_ROAD_SAME_PAIR"
HARD_NON_RC = "NON_RC_IN_BETWEEN"
HARD_CENTER_EMPTY = "CENTER_ESTIMATE_EMPTY"
HARD_ENDPOINT = "ENDPOINT_NOT_ON_XSEC"
HARD_BRIDGE_SEGMENT = "BRIDGE_SEGMENT_TOO_LONG"
HARD_DIVSTRIP_INTERSECT = "ROAD_INTERSECTS_DIVSTRIP"

SOFT_LOW_SUPPORT = "LOW_SUPPORT"
SOFT_SPARSE_POINTS = "SPARSE_SURFACE_POINTS"
SOFT_NO_LB = "NO_LB_CONTINUOUS"
SOFT_NO_LB_PATH = "NO_LB_CONTINUOUS_PATH"
SOFT_WIGGLY = "WIGGLY_CENTERLINE"
SOFT_OPEN_END = "OPEN_END"
SOFT_UNRESOLVED_NEIGHBOR = "UNRESOLVED_NEIGHBOR"
SOFT_NO_STABLE_SECTION = "NO_STABLE_SECTION"
SOFT_DIVSTRIP_MISSING = "DIVSTRIP_MISSING"
SOFT_ROAD_OUTSIDE_TRAJ_SURFACE = "ROAD_OUTSIDE_TRAJ_SURFACE"
SOFT_TRAJ_SURFACE_INSUFFICIENT = "TRAJ_SURFACE_INSUFFICIENT"
SOFT_TRAJ_SURFACE_GAP = "TRAJ_SURFACE_GAP"


@dataclass(frozen=True)
class CrossingEvent:
    traj_id: str
    nodeid: int
    seq: int
    seg_idx: int
    seq_idx: int
    station_m: float
    cross_point: Point
    heading_xy: tuple[float, float]
    cross_dist_m: float


@dataclass(frozen=True)
class CrossingExtractResult:
    events_by_traj: dict[str, list[CrossingEvent]]
    raw_hit_count: int
    dedup_drop_count: int
    n_cross_empty_skipped: int
    n_cross_geom_unexpected: int
    n_cross_distance_gate_reject: int


@dataclass
class PairSupport:
    src_nodeid: int
    dst_nodeid: int
    support_traj_ids: set[str] = field(default_factory=set)
    support_event_count: int = 0
    traj_segments: list[LineString] = field(default_factory=list)
    src_cross_points: list[Point] = field(default_factory=list)
    dst_cross_points: list[Point] = field(default_factory=list)
    repr_traj_ids: list[str] = field(default_factory=list)
    open_end: bool = False
    hard_anomalies: set[str] = field(default_factory=set)
    hints: list[str] = field(default_factory=list)
    stitch_hops: list[int] = field(default_factory=list)
    evidence_traj_ids: list[str] = field(default_factory=list)
    evidence_cluster_ids: list[int] = field(default_factory=list)
    evidence_lengths_m: list[float] = field(default_factory=list)
    open_end_flags: list[bool] = field(default_factory=list)
    unresolved_neighbor_count: int = 0
    cluster_count: int = 1
    main_cluster_id: int = 0
    main_cluster_ratio: float = 1.0
    cluster_sep_m_est: float | None = None
    cluster_sizes: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class PairSupportBuildResult:
    supports: dict[tuple[int, int], PairSupport]
    unresolved_events: list[dict[str, Any]]
    graph_node_count: int
    graph_edge_count: int
    stitch_candidate_count: int
    stitch_edge_count: int
    stitch_query_count: int
    stitch_candidates_total: int
    stitch_reject_dist_count: int
    stitch_reject_angle_count: int
    stitch_reject_forward_count: int
    stitch_accept_count: int
    stitch_levels_used_hist: dict[str, int]


@dataclass
class CenterEstimate:
    centerline_metric: LineString | None
    shape_ref_metric: LineString | None
    lb_path_found: bool
    lb_path_edge_count: int
    lb_path_length_m: float | None
    stable_offset_m_src: float | None
    stable_offset_m_dst: float | None
    center_sample_coverage: float
    width_med_m: float | None
    width_p90_m: float | None
    max_turn_deg_per_10m: float | None
    used_lane_boundary: bool
    src_is_gore_tip: bool
    dst_is_gore_tip: bool
    src_is_expanded: bool
    dst_is_expanded: bool
    src_width_near_m: float | None
    dst_width_near_m: float | None
    src_width_base_m: float | None
    dst_width_base_m: float | None
    src_gore_overlap_near: float | None
    dst_gore_overlap_near: float | None
    src_stable_s_m: float | None
    dst_stable_s_m: float | None
    src_cut_mode: str
    dst_cut_mode: str
    endpoint_tangent_deviation_deg_src: float | None
    endpoint_tangent_deviation_deg_dst: float | None
    endpoint_center_offset_m_src: float | None
    endpoint_center_offset_m_dst: float | None
    endpoint_proj_dist_to_core_m_src: float | None
    endpoint_proj_dist_to_core_m_dst: float | None
    soft_flags: set[str]
    hard_flags: set[str]
    diagnostics: dict[str, Any]


def extract_crossing_events(
    trajectories: Sequence[TrajectoryData],
    cross_sections: Sequence[CrossSection],
    *,
    hit_buffer_m: float,
    dedup_gap_m: float,
) -> CrossingExtractResult:
    out: dict[str, list[CrossingEvent]] = {}
    raw_hit_count = 0
    dedup_drop_count = 0
    n_cross_empty_skipped = 0
    n_cross_geom_unexpected = 0
    n_cross_distance_gate_reject = 0

    if not cross_sections:
        return CrossingExtractResult(
            events_by_traj=out,
            raw_hit_count=0,
            dedup_drop_count=0,
            n_cross_empty_skipped=0,
            n_cross_geom_unexpected=0,
            n_cross_distance_gate_reject=0,
        )

    xsecs: list[tuple[int, LineString, Point]] = []
    for x in cross_sections:
        geom = x.geometry_metric
        if geom.is_empty or geom.length <= 0:
            continue
        center = geom.interpolate(0.5, normalized=True)
        center_xy = point_xy_safe(center, context="xsec_center")
        if center_xy is None:
            n_cross_empty_skipped += 1
            continue
        xsecs.append((x.nodeid, geom, Point(center_xy[0], center_xy[1])))

    for traj in trajectories:
        coords = np.asarray(traj.xyz_metric[:, :2], dtype=np.float64)
        seq = np.asarray(traj.seq, dtype=np.int64)
        if coords.shape[0] < 2:
            continue

        station = _traj_station(coords)
        events: list[CrossingEvent] = []
        for i in range(coords.shape[0] - 1):
            p0 = coords[i]
            p1 = coords[i + 1]
            if not (_finite_xy(p0) and _finite_xy(p1)):
                continue
            if float(np.linalg.norm(p1 - p0)) <= 1e-6:
                continue

            seg = LineString([tuple(p0), tuple(p1)])
            if seg.is_empty or seg.length <= 1e-9:
                n_cross_geom_unexpected += 1
                continue
            seg_heading = _unit_vec(p1 - p0)
            seg_len = float(np.linalg.norm(p1 - p0))
            for nodeid, xline, xcenter in xsecs:
                if xline.is_empty or xline.length <= 0:
                    n_cross_geom_unexpected += 1
                    continue
                try:
                    dist_seg_xsec = float(seg.distance(xline))
                except Exception:
                    n_cross_geom_unexpected += 1
                    continue
                if not math.isfinite(dist_seg_xsec):
                    n_cross_geom_unexpected += 1
                    continue
                if dist_seg_xsec > float(hit_buffer_m):
                    n_cross_distance_gate_reject += 1
                    continue

                cp = _segment_cross_point(seg, xline)
                cp_xy = point_xy_safe(cp, context="cross_event")
                if cp_xy is None:
                    n_cross_empty_skipped += 1
                    continue

                frac = _segment_fraction_xy(cp_xy, p0, p1)
                seq_val = int(round(float(seq[i] + frac * (seq[i + 1] - seq[i]))))
                station_m = float(station[i] + frac * seg_len)
                cp_point = Point(cp_xy[0], cp_xy[1])
                events.append(
                    CrossingEvent(
                        traj_id=traj.traj_id,
                        nodeid=int(nodeid),
                        seq=seq_val,
                        seg_idx=int(i),
                        seq_idx=int(i),
                        station_m=station_m,
                        cross_point=cp_point,
                        heading_xy=seg_heading,
                        cross_dist_m=float(cp_point.distance(xcenter)),
                    )
                )
                raw_hit_count += 1

        deduped, dropped = _dedup_events_by_node(events, dedup_gap_m=dedup_gap_m)
        dedup_drop_count += int(dropped)
        if deduped:
            out[traj.traj_id] = deduped

    return CrossingExtractResult(
        events_by_traj=out,
        raw_hit_count=int(raw_hit_count),
        dedup_drop_count=int(dedup_drop_count),
        n_cross_empty_skipped=int(n_cross_empty_skipped),
        n_cross_geom_unexpected=int(n_cross_geom_unexpected),
        n_cross_distance_gate_reject=int(n_cross_distance_gate_reject),
    )


def build_pair_supports(
    trajectories: Sequence[TrajectoryData],
    events_by_traj: dict[str, list[CrossingEvent]],
    *,
    node_type_map: dict[int, str],
    trj_sample_step_m: float = 2.0,
    stitch_tail_m: float = 30.0,
    stitch_max_dist_levels_m: Sequence[float] | None = None,
    stitch_max_dist_m: float = 12.0,
    stitch_max_angle_deg: float = 35.0,
    stitch_forward_dot_min: float = 0.0,
    stitch_min_advance_m: float = 5.0,
    stitch_penalty: float = 2.0,
    stitch_topk: int = 3,
    neighbor_max_dist_m: float = 2000.0,
    multi_road_sep_m: float = 8.0,
    multi_road_topn: int = 10,
) -> PairSupportBuildResult:
    levels = _normalize_stitch_levels(
        stitch_max_dist_levels_m=stitch_max_dist_levels_m,
        stitch_max_dist_m=stitch_max_dist_m,
    )
    graph = _build_forward_graph(
        trajectories=trajectories,
        events_by_traj=events_by_traj,
        trj_sample_step_m=float(trj_sample_step_m),
        stitch_tail_m=float(stitch_tail_m),
        stitch_max_dist_levels_m=levels,
        stitch_max_angle_deg=float(stitch_max_angle_deg),
        stitch_forward_dot_min=float(stitch_forward_dot_min),
        stitch_min_advance_m=float(stitch_min_advance_m),
        stitch_penalty=float(stitch_penalty),
        stitch_topk=max(1, int(stitch_topk)),
    )

    supports: dict[tuple[int, int], PairSupport] = {}
    unresolved_events: list[dict[str, Any]] = []

    for traj_id, items in graph.event_keys_by_traj.items():
        for ev, source_key in items:
            search = _search_next_crossing(
                source_key=source_key,
                source_nodeid=int(ev.nodeid),
                nodes=graph.nodes,
                edges=graph.edges,
                max_dist_m=float(neighbor_max_dist_m),
            )

            target_key = search.target_key
            if target_key is None:
                last_stitch_candidates = _count_outgoing_stitch_edges(graph.edges.get(search.last_key, []))
                unresolved_events.append(
                    {
                        "road_id": f"na_{ev.nodeid}_{traj_id}_{ev.seq_idx}",
                        "src_nodeid": int(ev.nodeid),
                        "dst_nodeid": None,
                        "traj_id": str(traj_id),
                        "seq_range": [int(ev.seq_idx), int(ev.seq_idx)],
                        "station_range_m": [float(ev.station_m), float(ev.station_m)],
                        "reason": SOFT_UNRESOLVED_NEIGHBOR,
                        "severity": "soft",
                        "hint": (
                            f"max_dist_m={search.max_explored_dist_m:.1f};"
                            f"last_node={search.last_key};"
                            f"stitch_candidates={last_stitch_candidates}"
                        ),
                        "max_explored_dist_m": float(search.max_explored_dist_m),
                        "last_node_ref": str(search.last_key),
                        "stitch_candidate_count": int(last_stitch_candidates),
                    }
                )
                continue

            target_node = graph.nodes.get(target_key)
            if target_node is None or target_node.cross_nodeid is None:
                continue

            dst_nodeid = int(target_node.cross_nodeid)
            if dst_nodeid == int(ev.nodeid):
                continue

            pair = (int(ev.nodeid), int(dst_nodeid))
            support = supports.get(pair)
            if support is None:
                support = PairSupport(src_nodeid=pair[0], dst_nodeid=pair[1])
                supports[pair] = support

            path_keys = _reconstruct_path(source_key=source_key, target_key=target_key, prev=search.prev)
            path_line = _build_path_linestring(
                path_keys=path_keys,
                nodes=graph.nodes,
                prev_edge=search.prev_edge,
                traj_line_map=graph.traj_line_map,
            )
            edge_kinds = _path_edge_kinds(path_keys=path_keys, prev_edge=search.prev_edge)
            if (path_line is None or path_line.length <= 0) and ("stitch" not in edge_kinds):
                src_xy = point_xy_safe(ev.cross_point, context="pair_path_fallback_src")
                dst_xy = point_xy_safe(target_node.point, context="pair_path_fallback_dst")
                if src_xy is None or dst_xy is None:
                    continue
                path_line = LineString(
                    [
                        (float(src_xy[0]), float(src_xy[1])),
                        (float(dst_xy[0]), float(dst_xy[1])),
                    ]
                )
            if path_line is None or path_line.length <= 0:
                # 不允许把 stitch 直连段带入几何证据，拓扑支持仍可保留。
                continue

            path_traj_ids = _extract_path_traj_ids(path_keys=path_keys, nodes=graph.nodes)
            if not path_traj_ids:
                path_traj_ids = {traj_id}

            support.support_traj_ids.update(path_traj_ids)
            support.support_event_count += 1
            support.src_cross_points.append(ev.cross_point)
            support.dst_cross_points.append(target_node.point)
            support.traj_segments.append(path_line)
            support.stitch_hops.append(int(search.stitch_hops))
            support.evidence_traj_ids.append(str(traj_id))
            support.evidence_cluster_ids.append(0)
            support.evidence_lengths_m.append(float(search.distance_m))

            is_open_end = ("start" in edge_kinds) or ("end" in edge_kinds)
            support.open_end_flags.append(bool(is_open_end))
            support.open_end = support.open_end or is_open_end

            if traj_id not in support.repr_traj_ids and len(support.repr_traj_ids) < 16:
                support.repr_traj_ids.append(str(traj_id))

            non_rc_hit = _first_non_rc_in_path(
                path_keys=path_keys,
                nodes=graph.nodes,
                node_type_map=node_type_map,
                src_nodeid=int(ev.nodeid),
            )
            dst_type = node_type_map.get(dst_nodeid, "unknown")
            if non_rc_hit is not None or dst_type == "non_rc":
                support.hard_anomalies.add(HARD_NON_RC)

    for pair, support in list(supports.items()):
        multi = _detect_multi_road_channels(
            support,
            sep_m=float(multi_road_sep_m),
            topn=max(3, int(multi_road_topn)),
        )
        support.cluster_count = int(multi.cluster_count)
        support.main_cluster_id = int(multi.main_cluster_id)
        support.main_cluster_ratio = float(multi.main_cluster_ratio)
        support.cluster_sep_m_est = multi.cluster_sep_m_est
        support.cluster_sizes = [int(v) for v in multi.cluster_sizes]
        if multi.labels_all:
            labels_norm = [int(v) for v in multi.labels_all]
            if len(labels_norm) == support.support_event_count:
                support.evidence_cluster_ids = labels_norm
            else:
                support.evidence_cluster_ids = labels_norm[: support.support_event_count]
                if len(support.evidence_cluster_ids) < support.support_event_count:
                    support.evidence_cluster_ids.extend(
                        [int(multi.main_cluster_id)] * (support.support_event_count - len(support.evidence_cluster_ids))
                    )
        elif support.support_event_count > 0:
            support.evidence_cluster_ids = [int(multi.main_cluster_id)] * support.support_event_count

        if multi.has_multi:
            support.hard_anomalies.add(HARD_MULTI_ROAD)

        if support.support_event_count <= 0:
            supports.pop(pair, None)
            continue

        support.open_end = bool(any(support.open_end_flags))

    return PairSupportBuildResult(
        supports=supports,
        unresolved_events=unresolved_events,
        graph_node_count=int(len(graph.nodes)),
        graph_edge_count=int(sum(len(v) for v in graph.edges.values())),
        stitch_candidate_count=int(graph.stitch_candidate_count),
        stitch_edge_count=int(graph.stitch_edge_count),
        stitch_query_count=int(graph.stitch_query_count),
        stitch_candidates_total=int(graph.stitch_candidates_total),
        stitch_reject_dist_count=int(graph.stitch_reject_dist_count),
        stitch_reject_angle_count=int(graph.stitch_reject_angle_count),
        stitch_reject_forward_count=int(graph.stitch_reject_forward_count),
        stitch_accept_count=int(graph.stitch_accept_count),
        stitch_levels_used_hist=dict(graph.stitch_levels_used_hist),
    )


def infer_node_types(
    *,
    node_ids: Iterable[int],
    pair_supports: dict[tuple[int, int], PairSupport],
    node_kind_map: dict[int, int],
) -> tuple[dict[int, str], dict[int, int], dict[int, int]]:
    in_degree: dict[int, int] = {int(n): 0 for n in node_ids}
    out_degree: dict[int, int] = {int(n): 0 for n in node_ids}

    for (src, dst), support in pair_supports.items():
        w = max(1, len(support.support_traj_ids))
        out_degree[src] = out_degree.get(src, 0) + w
        in_degree[dst] = in_degree.get(dst, 0) + w

    out: dict[int, str] = {}
    for n in set([*in_degree.keys(), *out_degree.keys(), *node_kind_map.keys()]):
        kind = node_kind_map.get(int(n))
        if kind is not None:
            out[int(n)] = _kind_to_node_type(kind)
            continue

        indeg = in_degree.get(int(n), 0)
        outdeg = out_degree.get(int(n), 0)
        if outdeg > 1 and indeg <= 1:
            out[int(n)] = "diverge"
        elif indeg > 1 and outdeg <= 1:
            out[int(n)] = "merge"
        elif indeg > 0 or outdeg > 0:
            out[int(n)] = "unknown"
        else:
            out[int(n)] = "unknown"

    return out, in_degree, out_degree


@dataclass(frozen=True)
class _GraphNode:
    key: str
    traj_id: str
    kind: str
    station_m: float
    point: Point
    heading_xy: tuple[float, float]
    cross_nodeid: int | None
    seq_idx: int | None


@dataclass(frozen=True)
class _GraphEdge:
    to_key: str
    weight: float
    kind: str
    traj_id: str | None
    station_from: float | None
    station_to: float | None


@dataclass(frozen=True)
class _GraphBuildResult:
    nodes: dict[str, _GraphNode]
    edges: dict[str, list[_GraphEdge]]
    event_keys_by_traj: dict[str, list[tuple[CrossingEvent, str]]]
    traj_line_map: dict[str, LineString]
    stitch_candidate_count: int
    stitch_edge_count: int
    stitch_query_count: int
    stitch_candidates_total: int
    stitch_reject_dist_count: int
    stitch_reject_angle_count: int
    stitch_reject_forward_count: int
    stitch_accept_count: int
    stitch_levels_used_hist: dict[str, int]


@dataclass(frozen=True)
class _SearchResult:
    target_key: str | None
    distance_m: float
    stitch_hops: int
    prev: dict[str, str]
    prev_edge: dict[str, _GraphEdge]
    max_explored_dist_m: float
    last_key: str


@dataclass(frozen=True)
class _MultiRoadDetectResult:
    has_multi: bool
    keep_idx: list[int] | None
    labels_all: list[int]
    cluster_count: int
    cluster_sizes: list[int]
    main_cluster_id: int
    main_cluster_ratio: float
    cluster_sep_m_est: float | None


@dataclass(frozen=True)
class _EndStableDecision:
    is_gore_tip: bool
    is_expanded: bool
    width_near_m: float | None
    width_base_m: float | None
    gore_overlap_near: float | None
    stable_s_m: float | None
    anchor_station_m: float | None
    anchor_offset_m: float | None
    cut_mode: str
    used_fallback: bool
    short_base_proxy: bool


@dataclass(frozen=True)
class _ShapeRefChoice:
    line: LineString | None
    used_lane_boundary: bool
    lb_path_found: bool
    lb_path_edge_count: int
    lb_path_length_m: float | None
    lb_graph_build_ms: float | None = None
    lb_shortest_path_ms: float | None = None
    lb_graph_edge_total: int = 0
    lb_graph_edge_filtered: int = 0


@dataclass(frozen=True)
class _LbGraphEdge:
    u: int
    v: int
    length: float
    cost: float
    outside_len: float
    coords: tuple[tuple[float, float], tuple[float, float]]


def _build_forward_graph(
    *,
    trajectories: Sequence[TrajectoryData],
    events_by_traj: dict[str, list[CrossingEvent]],
    trj_sample_step_m: float,
    stitch_tail_m: float,
    stitch_max_dist_levels_m: Sequence[float],
    stitch_max_angle_deg: float,
    stitch_forward_dot_min: float,
    stitch_min_advance_m: float,
    stitch_penalty: float,
    stitch_topk: int,
) -> _GraphBuildResult:
    nodes: dict[str, _GraphNode] = {}
    edges: dict[str, list[_GraphEdge]] = {}
    event_keys_by_traj: dict[str, list[tuple[CrossingEvent, str]]] = {}
    traj_line_map: dict[str, LineString] = {}
    traj_sample_keys: dict[str, list[str]] = {}
    traj_length_by_id: dict[str, float] = {}

    for traj in trajectories:
        coords = np.asarray(traj.xyz_metric[:, :2], dtype=np.float64)
        if coords.shape[0] < 2:
            continue

        line = LineString([(float(p[0]), float(p[1])) for p in coords])
        if line.is_empty or line.length <= 0:
            continue

        traj_line_map[traj.traj_id] = line
        traj_len = float(line.length)
        traj_length_by_id[traj.traj_id] = traj_len

        sample_step = max(0.5, float(trj_sample_step_m))
        sample_ss = np.arange(0.0, traj_len + sample_step, sample_step, dtype=np.float64)
        if sample_ss.size == 0 or abs(float(sample_ss[-1]) - traj_len) > 1e-6:
            sample_ss = np.concatenate((sample_ss, np.asarray([traj_len], dtype=np.float64)))
        sample_ss = np.clip(sample_ss, 0.0, traj_len)
        sample_ss = np.unique(sample_ss)
        if sample_ss.size < 2:
            sample_ss = np.asarray([0.0, traj_len], dtype=np.float64)

        sample_pts = np.zeros((sample_ss.size, 2), dtype=np.float64)
        for i, s in enumerate(sample_ss):
            p = line.interpolate(float(s))
            p_xy = point_xy_safe(p, context="traj_sample_point")
            if p_xy is None:
                if i > 0:
                    sample_pts[i, :] = sample_pts[i - 1, :]
                else:
                    sample_pts[i, :] = coords[0, :]
            else:
                sample_pts[i, :] = [float(p_xy[0]), float(p_xy[1])]
        sample_heading = _sample_heading_by_points(sample_pts)

        node_entries: list[tuple[float, int, str]] = []
        sample_keys: list[str] = []
        n_samples = int(sample_ss.size)
        for i in range(n_samples):
            if i == 0:
                kind = "start"
                key = f"{traj.traj_id}:start"
            elif i == n_samples - 1:
                kind = "end"
                key = f"{traj.traj_id}:end"
            else:
                kind = "sample"
                key = f"{traj.traj_id}:sample:{i}"
            node = _GraphNode(
                key=key,
                traj_id=traj.traj_id,
                kind=kind,
                station_m=float(sample_ss[i]),
                point=Point(float(sample_pts[i, 0]), float(sample_pts[i, 1])),
                heading_xy=(float(sample_heading[i, 0]), float(sample_heading[i, 1])),
                cross_nodeid=None,
                seq_idx=None,
            )
            nodes[key] = node
            sample_keys.append(key)
            node_entries.append((float(sample_ss[i]), 10, key))
        traj_sample_keys[traj.traj_id] = sample_keys

        sorted_events = sorted(events_by_traj.get(traj.traj_id, []), key=lambda e: (e.station_m, e.nodeid, e.seq_idx))
        event_items: list[tuple[CrossingEvent, str]] = []
        for idx, ev in enumerate(sorted_events):
            key = f"{traj.traj_id}:cross:{idx}:{ev.nodeid}"
            node = _GraphNode(
                key=key,
                traj_id=traj.traj_id,
                kind="cross",
                station_m=float(ev.station_m),
                point=ev.cross_point,
                heading_xy=ev.heading_xy,
                cross_nodeid=int(ev.nodeid),
                seq_idx=int(ev.seq_idx),
            )
            nodes[key] = node
            event_items.append((ev, key))
            node_entries.append((float(ev.station_m), 20, key))

        event_keys_by_traj[traj.traj_id] = event_items
        node_entries.sort(key=lambda it: (it[0], it[1], it[2]))
        ordered = [k for _, _, k in node_entries]
        for a, b in zip(ordered[:-1], ordered[1:]):
            na = nodes[a]
            nb = nodes[b]
            w = float(nb.station_m - na.station_m)
            if w < -1e-6:
                continue
            if w <= 1e-6:
                w = 0.05
            edges.setdefault(a, []).append(
                _GraphEdge(
                    to_key=b,
                    weight=w,
                    kind="traj",
                    traj_id=traj.traj_id,
                    station_from=float(na.station_m),
                    station_to=float(nb.station_m),
                )
            )

    levels = [float(v) for v in stitch_max_dist_levels_m if float(v) > 0.0]
    levels = sorted(set(levels))
    stitch_candidate_count = 0
    stitch_edge_count = 0
    stitch_query_count = 0
    stitch_candidates_total = 0
    stitch_reject_dist_count = 0
    stitch_reject_angle_count = 0
    stitch_reject_forward_count = 0
    stitch_accept_count = 0
    stitch_levels_used_hist: dict[str, int] = {}
    if levels:
        cell = 10.0 if levels[-1] <= 60.0 else 20.0
        sample_grid: dict[tuple[int, int], list[str]] = {}
        for key, node in nodes.items():
            if node.kind not in {"start", "end", "sample"}:
                continue
            n_xy = point_xy_safe(node.point, context="stitch_sample_grid")
            if n_xy is None:
                continue
            gk = _grid_key(float(n_xy[0]), float(n_xy[1]), cell)
            sample_grid.setdefault(gk, []).append(key)

        topk_val = max(1, int(stitch_topk))
        for traj_id, sample_keys in traj_sample_keys.items():
            traj_len = float(traj_length_by_id.get(traj_id, 0.0))
            if traj_len <= 0:
                continue
            tail_keys = [
                k
                for k in sample_keys
                if (traj_len - float(nodes[k].station_m)) <= max(0.0, float(stitch_tail_m)) + 1e-6
            ]
            for tail_key in tail_keys:
                tail_node = nodes.get(tail_key)
                if tail_node is None:
                    continue
                tail_xy = point_xy_safe(tail_node.point, context="stitch_tail")
                if tail_xy is None:
                    continue
                stitch_query_count += 1
                used_level: float | None = None
                accepted_cands: list[tuple[float, float, str, str]] = []
                for level in levels:
                    radius = float(level)
                    raw_keys = _query_stitch_grid_keys(
                        sample_grid,
                        center_xy=np.asarray([float(tail_xy[0]), float(tail_xy[1])], dtype=np.float64),
                        radius_m=radius,
                        cell_size=cell,
                    )
                    if not raw_keys:
                        continue
                    cands: list[tuple[float, float, str, str]] = []
                    for cand_key in raw_keys:
                        cand_node = nodes.get(cand_key)
                        if cand_node is None:
                            continue
                        if cand_node.traj_id == tail_node.traj_id:
                            continue
                        cand_xy = point_xy_safe(cand_node.point, context="stitch_cand")
                        if cand_xy is None:
                            continue
                        dx = float(cand_xy[0] - tail_xy[0])
                        dy = float(cand_xy[1] - tail_xy[1])
                        dist = float(math.hypot(dx, dy))
                        if dist > radius + 1e-6:
                            stitch_reject_dist_count += 1
                            continue
                        cand_len = float(traj_length_by_id.get(cand_node.traj_id, cand_node.station_m))
                        if cand_len - float(cand_node.station_m) < float(stitch_min_advance_m):
                            stitch_reject_forward_count += 1
                            continue
                        dot = float(dx * tail_node.heading_xy[0] + dy * tail_node.heading_xy[1])
                        if dot <= float(stitch_forward_dot_min):
                            stitch_reject_forward_count += 1
                            continue
                        ang = _angle_deg(tail_node.heading_xy, cand_node.heading_xy)
                        if ang > float(stitch_max_angle_deg):
                            stitch_reject_angle_count += 1
                            continue
                        cands.append((dist, float(ang), str(cand_node.traj_id), cand_key))
                    if cands:
                        cands.sort(key=lambda it: (it[0], it[1], it[2], it[3]))
                        used_level = radius
                        accepted_cands = cands
                        break
                if not accepted_cands:
                    continue
                stitch_candidates_total += int(len(accepted_cands))
                stitch_candidate_count += int(len(accepted_cands))
                if used_level is not None:
                    lk = _format_level_key(used_level)
                    stitch_levels_used_hist[lk] = int(stitch_levels_used_hist.get(lk, 0) + 1)
                for dist, _ang, _tid, cand_key in accepted_cands[:topk_val]:
                    w = max(0.05, float(dist) * max(0.1, float(stitch_penalty)))
                    edges.setdefault(tail_key, []).append(
                        _GraphEdge(
                            to_key=cand_key,
                            weight=w,
                            kind="stitch",
                            traj_id=None,
                            station_from=None,
                            station_to=None,
                        )
                    )
                    stitch_edge_count += 1
                    stitch_accept_count += 1

    for key, vals in edges.items():
        vals.sort(key=lambda e: (e.weight, e.kind, e.to_key))
        edges[key] = vals

    return _GraphBuildResult(
        nodes=nodes,
        edges=edges,
        event_keys_by_traj=event_keys_by_traj,
        traj_line_map=traj_line_map,
        stitch_candidate_count=int(stitch_candidate_count),
        stitch_edge_count=int(stitch_edge_count),
        stitch_query_count=int(stitch_query_count),
        stitch_candidates_total=int(stitch_candidates_total),
        stitch_reject_dist_count=int(stitch_reject_dist_count),
        stitch_reject_angle_count=int(stitch_reject_angle_count),
        stitch_reject_forward_count=int(stitch_reject_forward_count),
        stitch_accept_count=int(stitch_accept_count),
        stitch_levels_used_hist=dict(stitch_levels_used_hist),
    )


def _search_next_crossing(
    *,
    source_key: str,
    source_nodeid: int,
    nodes: dict[str, _GraphNode],
    edges: dict[str, list[_GraphEdge]],
    max_dist_m: float,
) -> _SearchResult:
    best: dict[str, tuple[float, int]] = {source_key: (0.0, 0)}
    prev: dict[str, str] = {}
    prev_edge: dict[str, _GraphEdge] = {}
    heap: list[tuple[float, int, str]] = [(0.0, 0, source_key)]

    max_explored = 0.0
    last_key = source_key

    while heap:
        dist, hops, key = heapq.heappop(heap)
        rec = best.get(key)
        if rec is None:
            continue
        if dist > rec[0] + 1e-9:
            continue
        if abs(dist - rec[0]) <= 1e-9 and hops > rec[1]:
            continue
        if dist > max_dist_m + 1e-6:
            continue

        if dist >= max_explored:
            max_explored = float(dist)
            last_key = key

        node = nodes.get(key)
        if node is None:
            continue
        if node.kind == "cross" and node.cross_nodeid is not None and int(node.cross_nodeid) != int(source_nodeid):
            return _SearchResult(
                target_key=key,
                distance_m=float(dist),
                stitch_hops=int(hops),
                prev=prev,
                prev_edge=prev_edge,
                max_explored_dist_m=float(max_explored),
                last_key=str(last_key),
            )

        for edge in edges.get(key, []):
            nd = float(dist + edge.weight)
            if nd > max_dist_m + 1e-6:
                continue
            nh = int(hops + (1 if edge.kind == "stitch" else 0))
            old = best.get(edge.to_key)
            if old is not None:
                if nd > old[0] + 1e-9:
                    continue
                if abs(nd - old[0]) <= 1e-9 and nh >= old[1]:
                    continue
            best[edge.to_key] = (nd, nh)
            prev[edge.to_key] = key
            prev_edge[edge.to_key] = edge
            heapq.heappush(heap, (nd, nh, edge.to_key))

    return _SearchResult(
        target_key=None,
        distance_m=float(max_explored),
        stitch_hops=0,
        prev=prev,
        prev_edge=prev_edge,
        max_explored_dist_m=float(max_explored),
        last_key=str(last_key),
    )


def _reconstruct_path(*, source_key: str, target_key: str, prev: dict[str, str]) -> list[str]:
    out: list[str] = [target_key]
    cur = target_key
    while cur != source_key:
        p = prev.get(cur)
        if p is None:
            break
        out.append(p)
        cur = p
    out.reverse()
    if not out or out[0] != source_key:
        return [source_key, target_key]
    return out


def _build_path_linestring(
    *,
    path_keys: list[str],
    nodes: dict[str, _GraphNode],
    prev_edge: dict[str, _GraphEdge],
    traj_line_map: dict[str, LineString],
) -> LineString | None:
    if len(path_keys) < 2:
        return None

    traj_parts: list[LineString] = []
    for idx in range(1, len(path_keys)):
        to_key = path_keys[idx]
        edge = prev_edge.get(to_key)
        if edge is None:
            continue

        if edge.kind == "traj" and edge.traj_id is not None:
            line = traj_line_map.get(edge.traj_id)
            s0 = 0.0 if edge.station_from is None else float(edge.station_from)
            s1 = 0.0 if edge.station_to is None else float(edge.station_to)
            if line is not None and s1 > s0 + 1e-6:
                try:
                    part = substring(line, s0, s1)
                except Exception:
                    part = None
                if isinstance(part, LineString) and not part.is_empty and len(part.coords) >= 2:
                    traj_parts.append(part)

    if not traj_parts:
        return None

    merged: BaseGeometry
    if len(traj_parts) == 1:
        merged = traj_parts[0]
    else:
        try:
            merged = linemerge(MultiLineString(traj_parts))
        except Exception:
            merged = MultiLineString(traj_parts)

    if isinstance(merged, LineString):
        if merged.is_empty or merged.length <= 0 or len(merged.coords) < 2:
            return None
        return merged

    if isinstance(merged, MultiLineString):
        valid = [ls for ls in merged.geoms if isinstance(ls, LineString) and not ls.is_empty and len(ls.coords) >= 2]
        if not valid:
            return None
        best = max(valid, key=lambda g: float(g.length))
        if best.length <= 0:
            return None
        return best

    # stitch 只用于拓扑，不可进入几何；这里仅保留真实轨迹片段。
    if isinstance(merged, BaseGeometry) and not merged.is_empty:
        if getattr(merged, "geom_type", "") == "GeometryCollection":
            lines = [
                g
                for g in getattr(merged, "geoms", [])
                if isinstance(g, LineString) and not g.is_empty and len(g.coords) >= 2
            ]
            if lines:
                return max(lines, key=lambda g: float(g.length))

    # nodes 参数保留用于兼容调用签名。
    del nodes
    if traj_parts:
        best = max(traj_parts, key=lambda g: float(g.length))
        if best.length > 0:
            return best
    return None


def _extract_path_traj_ids(*, path_keys: list[str], nodes: dict[str, _GraphNode]) -> set[str]:
    out: set[str] = set()
    for key in path_keys:
        node = nodes.get(key)
        if node is not None and node.traj_id:
            out.add(str(node.traj_id))
    return out


def _path_edge_kinds(*, path_keys: list[str], prev_edge: dict[str, _GraphEdge]) -> set[str]:
    kinds: set[str] = set()
    for idx in range(1, len(path_keys)):
        to_key = path_keys[idx]
        edge = prev_edge.get(to_key)
        if edge is not None:
            kinds.add(edge.kind)
        for k in [path_keys[idx - 1], path_keys[idx]]:
            if ":start" in k:
                kinds.add("start")
            elif ":end" in k:
                kinds.add("end")
    return kinds


def _first_non_rc_in_path(
    *,
    path_keys: list[str],
    nodes: dict[str, _GraphNode],
    node_type_map: dict[int, str],
    src_nodeid: int,
) -> int | None:
    for key in path_keys:
        node = nodes.get(key)
        if node is None or node.cross_nodeid is None:
            continue
        nid = int(node.cross_nodeid)
        if nid == int(src_nodeid):
            continue
        if node_type_map.get(nid, "unknown") == "non_rc":
            return nid
    return None


def _count_outgoing_stitch_edges(edges: Sequence[_GraphEdge]) -> int:
    return int(sum(1 for e in edges if e.kind == "stitch"))


def _apply_support_subset(support: PairSupport, keep_idx: list[int]) -> None:
    if not keep_idx:
        support.support_event_count = 0
        support.traj_segments = []
        support.src_cross_points = []
        support.dst_cross_points = []
        support.stitch_hops = []
        support.evidence_traj_ids = []
        support.evidence_cluster_ids = []
        support.evidence_lengths_m = []
        support.open_end_flags = []
        support.support_traj_ids = set()
        support.repr_traj_ids = []
        support.open_end = False
        return

    idx = sorted(set(int(i) for i in keep_idx if 0 <= int(i) < support.support_event_count))
    if not idx:
        _apply_support_subset(support, [])
        return

    support.traj_segments = [support.traj_segments[i] for i in idx]
    support.src_cross_points = [support.src_cross_points[i] for i in idx]
    support.dst_cross_points = [support.dst_cross_points[i] for i in idx]
    support.stitch_hops = [support.stitch_hops[i] for i in idx]
    support.evidence_traj_ids = [support.evidence_traj_ids[i] for i in idx]
    if support.evidence_cluster_ids:
        support.evidence_cluster_ids = [support.evidence_cluster_ids[i] for i in idx]
    else:
        support.evidence_cluster_ids = [0 for _ in idx]
    support.evidence_lengths_m = [support.evidence_lengths_m[i] for i in idx]
    support.open_end_flags = [support.open_end_flags[i] for i in idx]
    support.support_event_count = int(len(idx))
    support.support_traj_ids = set(support.evidence_traj_ids)
    support.repr_traj_ids = []
    for tid in support.evidence_traj_ids:
        if tid not in support.repr_traj_ids:
            support.repr_traj_ids.append(tid)
            if len(support.repr_traj_ids) >= 16:
                break
    support.open_end = bool(any(support.open_end_flags))


def estimate_centerline(
    *,
    support: PairSupport,
    src_xsec: LineString,
    dst_xsec: LineString,
    src_type: str,
    dst_type: str,
    src_out_degree: int,
    dst_in_degree: int,
    lane_boundaries_metric: Sequence[LineString],
    surface_points_xyz: np.ndarray,
    center_sample_step_m: float,
    xsec_along_half_window_m: float,
    xsec_across_half_window_m: float,
    xsec_min_points: int,
    width_pct_low: float,
    width_pct_high: float,
    min_center_coverage: float,
    smooth_window_m: float,
    corridor_half_width_m: float,
    offset_smooth_win_m_1: float,
    offset_smooth_win_m_2: float,
    max_offset_delta_per_step_m: float,
    simplify_tol_m: float,
    stable_offset_m: float,
    stable_margin_m: float,
    endpoint_tol_m: float,
    road_max_vertices: int,
    lb_snap_m: float,
    lb_start_end_topk: int,
    lb_outside_lambda: float,
    lb_outside_edge_ratio_max: float,
    lb_surface_node_buffer_m: float,
    trend_fit_win_m: float,
    traj_surface_metric: BaseGeometry | None,
    traj_surface_enforced: bool,
    divstrip_zone_metric: BaseGeometry | None,
    xsec_anchor_window_m: float,
    xsec_endpoint_max_dist_m: float,
    d_min: float,
    d_max: float,
    near_len: float,
    base_from: float,
    base_to: float,
    l_stable: float,
    ratio_tol: float,
    w_tol: float,
    r_gore: float,
    transition_m: float,
    stable_fallback_m: float,
) -> CenterEstimate:
    del stable_offset_m
    del stable_margin_m
    soft_flags: set[str] = set()
    hard_flags: set[str] = set(support.hard_anomalies)
    diagnostics: dict[str, Any] = {}

    shape_choice = _choose_shape_ref_with_graph(
        support=support,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        lane_boundaries_metric=lane_boundaries_metric,
        lb_snap_m=float(lb_snap_m),
        lb_start_end_topk=int(lb_start_end_topk),
        traj_surface_metric=traj_surface_metric,
        lb_outside_lambda=float(lb_outside_lambda),
        traj_surface_enforced=bool(traj_surface_enforced),
        outside_edge_ratio_max=float(lb_outside_edge_ratio_max),
        surface_node_buffer_m=float(lb_surface_node_buffer_m),
        divstrip_barrier_metric=divstrip_zone_metric,
    )
    shape_ref = shape_choice.line
    used_lb = bool(shape_choice.used_lane_boundary)
    if shape_ref is None:
        soft_flags.add(SOFT_NO_LB_PATH)
        fallback_shape = _build_shape_ref_from_surface_points(
            src_xsec=src_xsec,
            dst_xsec=dst_xsec,
            points_xyz=surface_points_xyz,
            gore_zone_metric=divstrip_zone_metric,
            corridor_half_width_m=float(corridor_half_width_m),
            sample_step_m=max(2.0, float(center_sample_step_m)),
        )
        if fallback_shape is None:
            hard_flags.add(HARD_CENTER_EMPTY)
            return CenterEstimate(
                centerline_metric=None,
                shape_ref_metric=None,
                lb_path_found=False,
                lb_path_edge_count=0,
                lb_path_length_m=None,
                stable_offset_m_src=None,
                stable_offset_m_dst=None,
                center_sample_coverage=0.0,
                width_med_m=None,
                width_p90_m=None,
                max_turn_deg_per_10m=None,
                used_lane_boundary=False,
                src_is_gore_tip=False,
                dst_is_gore_tip=False,
                src_is_expanded=False,
                dst_is_expanded=False,
                src_width_near_m=None,
                dst_width_near_m=None,
                src_width_base_m=None,
                dst_width_base_m=None,
                src_gore_overlap_near=None,
                dst_gore_overlap_near=None,
                src_stable_s_m=None,
                dst_stable_s_m=None,
                src_cut_mode="fallback_50m",
                dst_cut_mode="fallback_50m",
                endpoint_tangent_deviation_deg_src=None,
                endpoint_tangent_deviation_deg_dst=None,
                endpoint_center_offset_m_src=None,
                endpoint_center_offset_m_dst=None,
                endpoint_proj_dist_to_core_m_src=None,
                endpoint_proj_dist_to_core_m_dst=None,
                soft_flags=soft_flags,
                hard_flags=hard_flags,
                diagnostics={"reason": "shape_ref_unavailable"},
            )
        shape_ref = fallback_shape
        used_lb = False
        diagnostics["shape_ref_fallback"] = "surface_skeleton"

    if shape_ref is not None and (not shape_ref.is_empty) and shape_ref.length > 1.0:
        clipped_shape_ref = _shape_ref_substring_by_xsecs(shape_ref, src_xsec=src_xsec, dst_xsec=dst_xsec)
        if clipped_shape_ref is not None and clipped_shape_ref.length > 1.0:
            shape_ref = clipped_shape_ref
            diagnostics["shape_ref_substring_applied"] = True

    diagnostics["lb_graph_build_ms"] = shape_choice.lb_graph_build_ms
    diagnostics["lb_shortest_path_ms"] = shape_choice.lb_shortest_path_ms
    diagnostics["lb_graph_edge_total"] = int(shape_choice.lb_graph_edge_total)
    diagnostics["lb_graph_edge_filtered"] = int(shape_choice.lb_graph_edge_filtered)

    if not used_lb:
        soft_flags.add(SOFT_NO_LB)
        soft_flags.add(SOFT_NO_LB_PATH)

    ss, sp, tv, nv = _sample_line(shape_ref, step_m=center_sample_step_m)
    if sp.shape[0] < 2:
        hard_flags.add(HARD_CENTER_EMPTY)
        return CenterEstimate(
            centerline_metric=None,
            shape_ref_metric=shape_ref,
            lb_path_found=bool(shape_choice.lb_path_found),
            lb_path_edge_count=int(shape_choice.lb_path_edge_count),
            lb_path_length_m=shape_choice.lb_path_length_m,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=0.0,
            width_med_m=None,
            width_p90_m=None,
            max_turn_deg_per_10m=None,
            used_lane_boundary=used_lb,
            src_is_gore_tip=False,
            dst_is_gore_tip=False,
            src_is_expanded=False,
            dst_is_expanded=False,
            src_width_near_m=None,
            dst_width_near_m=None,
            src_width_base_m=None,
            dst_width_base_m=None,
            src_gore_overlap_near=None,
            dst_gore_overlap_near=None,
            src_stable_s_m=None,
            dst_stable_s_m=None,
            src_cut_mode="fallback_50m",
            dst_cut_mode="fallback_50m",
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=soft_flags,
            hard_flags=hard_flags,
            diagnostics={"reason": "shape_ref_sampling_failed"},
        )

    offsets, widths, gore_overlap, coverage = _estimate_offsets_from_surface(
        sample_points=sp,
        tangents=tv,
        normals=nv,
        points_xyz=surface_points_xyz,
        gore_zone_metric=divstrip_zone_metric,
        along_half_window_m=xsec_along_half_window_m,
        across_half_window_m=xsec_across_half_window_m,
        corridor_half_width_m=corridor_half_width_m,
        min_points=xsec_min_points,
        width_pct_low=width_pct_low,
        width_pct_high=width_pct_high,
    )

    diagnostics["surface_points_in_window"] = int(surface_points_xyz.shape[0])
    diagnostics["raw_coverage"] = float(coverage)
    diagnostics["divstrip_enabled"] = bool(divstrip_zone_metric is not None)

    if coverage < float(min_center_coverage):
        soft_flags.add(SOFT_SPARSE_POINTS)

    smoothed = _smooth_offsets_two_stage(
        offsets,
        step_m=center_sample_step_m,
        window_m_1=offset_smooth_win_m_1 if offset_smooth_win_m_1 > 0 else smooth_window_m,
        window_m_2=offset_smooth_win_m_2 if offset_smooth_win_m_2 > 0 else max(smooth_window_m, offset_smooth_win_m_1),
        max_delta_per_step_m=max_offset_delta_per_step_m,
    )
    if np.count_nonzero(np.isfinite(smoothed)) < 2:
        hard_flags.add(HARD_CENTER_EMPTY)
        return CenterEstimate(
            centerline_metric=None,
            shape_ref_metric=shape_ref,
            lb_path_found=bool(shape_choice.lb_path_found),
            lb_path_edge_count=int(shape_choice.lb_path_edge_count),
            lb_path_length_m=shape_choice.lb_path_length_m,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=float(coverage),
            width_med_m=_nanmedian(widths),
            width_p90_m=_nanpercentile(widths, 90.0),
            max_turn_deg_per_10m=None,
            used_lane_boundary=used_lb,
            src_is_gore_tip=False,
            dst_is_gore_tip=False,
            src_is_expanded=False,
            dst_is_expanded=False,
            src_width_near_m=None,
            dst_width_near_m=None,
            src_width_base_m=None,
            dst_width_base_m=None,
            src_gore_overlap_near=None,
            dst_gore_overlap_near=None,
            src_stable_s_m=None,
            dst_stable_s_m=None,
            src_cut_mode="fallback_50m",
            dst_cut_mode="fallback_50m",
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=soft_flags,
            hard_flags=hard_flags,
            diagnostics=diagnostics,
        )

    length_m = float(shape_ref.length)
    src_decision = _select_stable_section_for_end(
        stations=ss,
        widths=widths,
        gore_overlap=gore_overlap,
        offsets=smoothed,
        length_m=length_m,
        from_src=True,
        d_min=float(d_min),
        d_max=float(d_max),
        near_len=float(near_len),
        base_from=float(base_from),
        base_to=float(base_to),
        l_stable=float(l_stable),
        ratio_tol=float(ratio_tol),
        w_tol=float(w_tol),
        r_gore=float(r_gore),
        stable_fallback_m=float(stable_fallback_m),
    )
    dst_decision = _select_stable_section_for_end(
        stations=ss,
        widths=widths,
        gore_overlap=gore_overlap,
        offsets=smoothed,
        length_m=length_m,
        from_src=False,
        d_min=float(d_min),
        d_max=float(d_max),
        near_len=float(near_len),
        base_from=float(base_from),
        base_to=float(base_to),
        l_stable=float(l_stable),
        ratio_tol=float(ratio_tol),
        w_tol=float(w_tol),
        r_gore=float(r_gore),
        stable_fallback_m=float(stable_fallback_m),
    )
    smoothed_clamped = _apply_endpoint_stable_clamp(
        offsets=smoothed,
        stations=ss,
        src_decision=src_decision,
        dst_decision=dst_decision,
        transition_m=float(transition_m),
        length_m=float(shape_ref.length),
    )
    stable_src = src_decision.anchor_offset_m
    stable_dst = dst_decision.anchor_offset_m
    if src_decision.used_fallback or dst_decision.used_fallback:
        soft_flags.add(SOFT_NO_STABLE_SECTION)
    if src_decision.short_base_proxy or dst_decision.short_base_proxy:
        diagnostics["short_road_base_proxy"] = True

    center_samples = sp + nv * smoothed_clamped[:, None]
    centerline = _offset_line(sample_points=sp, normals=nv, offsets=smoothed_clamped)
    if centerline is None or centerline.length <= 0:
        hard_flags.add(HARD_CENTER_EMPTY)
        return CenterEstimate(
            centerline_metric=None,
            shape_ref_metric=shape_ref,
            lb_path_found=bool(shape_choice.lb_path_found),
            lb_path_edge_count=int(shape_choice.lb_path_edge_count),
            lb_path_length_m=shape_choice.lb_path_length_m,
            stable_offset_m_src=stable_src,
            stable_offset_m_dst=stable_dst,
            center_sample_coverage=float(coverage),
            width_med_m=_nanmedian(widths),
            width_p90_m=_nanpercentile(widths, 90.0),
            max_turn_deg_per_10m=None,
            used_lane_boundary=used_lb,
            src_is_gore_tip=bool(src_decision.is_gore_tip),
            dst_is_gore_tip=bool(dst_decision.is_gore_tip),
            src_is_expanded=bool(src_decision.is_expanded),
            dst_is_expanded=bool(dst_decision.is_expanded),
            src_width_near_m=src_decision.width_near_m,
            dst_width_near_m=dst_decision.width_near_m,
            src_width_base_m=src_decision.width_base_m,
            dst_width_base_m=dst_decision.width_base_m,
            src_gore_overlap_near=src_decision.gore_overlap_near,
            dst_gore_overlap_near=dst_decision.gore_overlap_near,
            src_stable_s_m=src_decision.stable_s_m,
            dst_stable_s_m=dst_decision.stable_s_m,
            src_cut_mode=src_decision.cut_mode,
            dst_cut_mode=dst_decision.cut_mode,
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=soft_flags,
            hard_flags=hard_flags,
            diagnostics=diagnostics,
        )

    if simplify_tol_m > 0.0:
        try:
            simp = centerline.simplify(float(simplify_tol_m), preserve_topology=False)
        except Exception:
            simp = centerline
        if isinstance(simp, LineString) and not simp.is_empty and len(simp.coords) >= 2:
            centerline = simp

    (
        trend_line,
        trend_dev_src,
        trend_dev_dst,
        trend_reason,
        proj_dist_src,
        proj_dist_dst,
        trend_meta,
    ) = _apply_endpoint_trend_projection(
        base_line=centerline,
        shape_ref_line=shape_ref,
        sample_stations=ss,
        sample_center_points=center_samples,
        src_decision=src_decision,
        dst_decision=dst_decision,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        src_channel_points=support.src_cross_points,
        dst_channel_points=support.dst_cross_points,
        trend_fit_win_m=float(trend_fit_win_m),
        traj_surface_metric=traj_surface_metric,
        traj_surface_enforced=bool(traj_surface_enforced),
        gore_zone_metric=divstrip_zone_metric,
        endpoint_tol_m=float(endpoint_tol_m),
        anchor_window_m=float(xsec_anchor_window_m),
        endpoint_local_max_dist_m=float(xsec_endpoint_max_dist_m),
        road_max_vertices=int(road_max_vertices),
    )
    if trend_line is None:
        clipped, clip_reason = clip_line_to_cross_sections(
            centerline,
            src_xsec,
            dst_xsec,
            endpoint_tol_m=endpoint_tol_m,
        )
        trend_dev_src = None
        trend_dev_dst = None
        proj_dist_src = None
        proj_dist_dst = None
        trend_meta = {}
    else:
        clipped = trend_line
        clip_reason = trend_reason

    if clipped is None:
        hard_flags.add(clip_reason or HARD_CENTER_EMPTY)
        return CenterEstimate(
            centerline_metric=None,
            shape_ref_metric=shape_ref,
            lb_path_found=bool(shape_choice.lb_path_found),
            lb_path_edge_count=int(shape_choice.lb_path_edge_count),
            lb_path_length_m=shape_choice.lb_path_length_m,
            stable_offset_m_src=stable_src,
            stable_offset_m_dst=stable_dst,
            center_sample_coverage=float(coverage),
            width_med_m=_nanmedian(widths),
            width_p90_m=_nanpercentile(widths, 90.0),
            max_turn_deg_per_10m=None,
            used_lane_boundary=used_lb,
            src_is_gore_tip=bool(src_decision.is_gore_tip),
            dst_is_gore_tip=bool(dst_decision.is_gore_tip),
            src_is_expanded=bool(src_decision.is_expanded),
            dst_is_expanded=bool(dst_decision.is_expanded),
            src_width_near_m=src_decision.width_near_m,
            dst_width_near_m=dst_decision.width_near_m,
            src_width_base_m=src_decision.width_base_m,
            dst_width_base_m=dst_decision.width_base_m,
            src_gore_overlap_near=src_decision.gore_overlap_near,
            dst_gore_overlap_near=dst_decision.gore_overlap_near,
            src_stable_s_m=src_decision.stable_s_m,
            dst_stable_s_m=dst_decision.stable_s_m,
            src_cut_mode=src_decision.cut_mode,
            dst_cut_mode=dst_decision.cut_mode,
            endpoint_tangent_deviation_deg_src=trend_dev_src,
            endpoint_tangent_deviation_deg_dst=trend_dev_dst,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=proj_dist_src,
            endpoint_proj_dist_to_core_m_dst=proj_dist_dst,
            soft_flags=soft_flags,
            hard_flags=hard_flags,
            diagnostics=diagnostics,
        )

    clipped = _limit_vertices(clipped, road_max_vertices)

    turn = compute_max_turn_deg_per_10m(clipped)
    if turn is not None:
        diagnostics["max_turn_deg_per_10m"] = float(turn)
    endpoint_src = _estimate_endpoint_center_offset(
        line=clipped,
        at_start=True,
        points_xyz=surface_points_xyz,
        gore_zone_metric=divstrip_zone_metric,
        along_half_window_m=xsec_along_half_window_m,
        across_half_window_m=xsec_across_half_window_m,
        corridor_half_width_m=corridor_half_width_m,
        min_points=max(20, int(xsec_min_points // 4)),
        width_pct_low=width_pct_low,
        width_pct_high=width_pct_high,
    )
    endpoint_dst = _estimate_endpoint_center_offset(
        line=clipped,
        at_start=False,
        points_xyz=surface_points_xyz,
        gore_zone_metric=divstrip_zone_metric,
        along_half_window_m=xsec_along_half_window_m,
        across_half_window_m=xsec_across_half_window_m,
        corridor_half_width_m=corridor_half_width_m,
        min_points=max(20, int(xsec_min_points // 4)),
        width_pct_low=width_pct_low,
        width_pct_high=width_pct_high,
    )
    diagnostics["endpoint_center_offset_m_src"] = endpoint_src
    diagnostics["endpoint_center_offset_m_dst"] = endpoint_dst
    diagnostics["endpoint_tangent_deviation_deg_src"] = trend_dev_src
    diagnostics["endpoint_tangent_deviation_deg_dst"] = trend_dev_dst
    diagnostics["endpoint_proj_dist_to_core_m_src"] = proj_dist_src
    diagnostics["endpoint_proj_dist_to_core_m_dst"] = proj_dist_dst
    diagnostics["src_cut_mode"] = src_decision.cut_mode
    diagnostics["dst_cut_mode"] = dst_decision.cut_mode
    if isinstance(trend_meta, dict) and trend_meta:
        diagnostics.update(trend_meta)

    return CenterEstimate(
        centerline_metric=clipped,
        shape_ref_metric=shape_ref,
        lb_path_found=bool(shape_choice.lb_path_found),
        lb_path_edge_count=int(shape_choice.lb_path_edge_count),
        lb_path_length_m=shape_choice.lb_path_length_m,
        stable_offset_m_src=stable_src,
        stable_offset_m_dst=stable_dst,
        center_sample_coverage=float(coverage),
        width_med_m=_nanmedian(widths),
        width_p90_m=_nanpercentile(widths, 90.0),
        max_turn_deg_per_10m=turn,
        used_lane_boundary=used_lb,
        src_is_gore_tip=bool(src_decision.is_gore_tip),
        dst_is_gore_tip=bool(dst_decision.is_gore_tip),
        src_is_expanded=bool(src_decision.is_expanded),
        dst_is_expanded=bool(dst_decision.is_expanded),
        src_width_near_m=src_decision.width_near_m,
        dst_width_near_m=dst_decision.width_near_m,
        src_width_base_m=src_decision.width_base_m,
        dst_width_base_m=dst_decision.width_base_m,
        src_gore_overlap_near=src_decision.gore_overlap_near,
        dst_gore_overlap_near=dst_decision.gore_overlap_near,
        src_stable_s_m=src_decision.stable_s_m,
        dst_stable_s_m=dst_decision.stable_s_m,
        src_cut_mode=src_decision.cut_mode,
        dst_cut_mode=dst_decision.cut_mode,
        endpoint_tangent_deviation_deg_src=trend_dev_src,
        endpoint_tangent_deviation_deg_dst=trend_dev_dst,
        endpoint_center_offset_m_src=endpoint_src,
        endpoint_center_offset_m_dst=endpoint_dst,
        endpoint_proj_dist_to_core_m_src=proj_dist_src,
        endpoint_proj_dist_to_core_m_dst=proj_dist_dst,
        soft_flags=soft_flags,
        hard_flags=hard_flags,
        diagnostics=diagnostics,
    )


def clip_line_to_cross_sections(
    line: LineString,
    src_xsec: LineString,
    dst_xsec: LineString,
    *,
    endpoint_tol_m: float,
) -> tuple[LineString | None, str | None]:
    s0 = _locate_on_line(line, src_xsec, tol=endpoint_tol_m)
    s1 = _locate_on_line(line, dst_xsec, tol=endpoint_tol_m)

    if s0 is None or s1 is None:
        return None, HARD_CENTER_EMPTY

    if abs(s1 - s0) < 1e-3:
        return None, HARD_CENTER_EMPTY

    start = min(s0, s1)
    end = max(s0, s1)
    try:
        seg = substring(line, start, end)
    except Exception:
        seg = line

    if seg is None or seg.is_empty or not isinstance(seg, LineString) or len(seg.coords) < 2:
        return None, HARD_CENTER_EMPTY

    p_start = Point(seg.coords[0])
    p_end = Point(seg.coords[-1])
    if p_start.distance(src_xsec) > endpoint_tol_m or p_end.distance(dst_xsec) > endpoint_tol_m:
        # 尝试反向检查（可能方向相反）
        if p_start.distance(dst_xsec) <= endpoint_tol_m and p_end.distance(src_xsec) <= endpoint_tol_m:
            rev = LineString(list(seg.coords)[::-1])
            return rev, None
        return None, HARD_ENDPOINT

    return seg, None


def _apply_endpoint_trend_projection(
    *,
    base_line: LineString,
    shape_ref_line: LineString,
    sample_stations: np.ndarray,
    sample_center_points: np.ndarray,
    src_decision: _EndStableDecision,
    dst_decision: _EndStableDecision,
    src_xsec: LineString,
    dst_xsec: LineString,
    src_channel_points: Sequence[Point],
    dst_channel_points: Sequence[Point],
    trend_fit_win_m: float,
    traj_surface_metric: BaseGeometry | None,
    traj_surface_enforced: bool,
    gore_zone_metric: BaseGeometry | None,
    endpoint_tol_m: float,
    anchor_window_m: float,
    endpoint_local_max_dist_m: float,
    road_max_vertices: int,
) -> tuple[LineString | None, float | None, float | None, str | None, float | None, float | None, dict[str, Any]]:
    trend_meta: dict[str, Any] = {
        "anchor_window_m": float(max(0.0, anchor_window_m)),
        "xsec_support_len_src": 0.0,
        "xsec_support_len_dst": 0.0,
        "xsec_support_disabled_due_to_insufficient_src": not bool(traj_surface_enforced),
        "xsec_support_disabled_due_to_insufficient_dst": not bool(traj_surface_enforced),
        "endpoint_fallback_mode_src": None,
        "endpoint_fallback_mode_dst": None,
        "s_anchor_src_m": None,
        "s_anchor_dst_m": None,
        "s_end_src_m": None,
        "s_end_dst_m": None,
    }
    if base_line.is_empty or base_line.length <= 0:
        return None, None, None, HARD_CENTER_EMPTY, None, None, trend_meta
    if sample_center_points.shape[0] < 2 or sample_stations.size != sample_center_points.shape[0]:
        return None, None, None, HARD_CENTER_EMPTY, None, None, trend_meta

    n = int(sample_center_points.shape[0])
    if src_decision.anchor_station_m is None or dst_decision.anchor_station_m is None:
        return None, None, None, HARD_CENTER_EMPTY, None, None, trend_meta
    i_src = int(np.argmin(np.abs(sample_stations - float(src_decision.anchor_station_m))))
    i_dst = int(np.argmin(np.abs(sample_stations - float(dst_decision.anchor_station_m))))
    i_src = max(0, min(n - 1, i_src))
    i_dst = max(0, min(n - 1, i_dst))
    if i_dst <= i_src:
        return None, None, None, HARD_CENTER_EMPTY, None, None, trend_meta

    src_anchor = sample_center_points[i_src, :]
    dst_anchor = sample_center_points[i_dst, :]

    t_src = _shape_ref_tangent(shape_ref_line, station_m=float(src_decision.anchor_station_m))
    if t_src is None:
        t_src = _fit_endpoint_trend(
            stations=sample_stations,
            points=sample_center_points,
            anchor_idx=i_src,
            from_src=True,
            fit_win_m=max(5.0, float(trend_fit_win_m)),
        )
    t_dst = _shape_ref_tangent(shape_ref_line, station_m=float(dst_decision.anchor_station_m))
    if t_dst is None:
        t_dst = _fit_endpoint_trend(
            stations=sample_stations,
            points=sample_center_points,
            anchor_idx=i_dst,
            from_src=False,
            fit_win_m=max(5.0, float(trend_fit_win_m)),
        )
    if t_src is None or t_dst is None:
        return None, None, None, HARD_CENTER_EMPTY, None, None, trend_meta

    p_src0 = _project_trend_to_xsec(
        anchor_xy=(float(src_anchor[0]), float(src_anchor[1])),
        trend_xy=t_src,
        xsec=src_xsec,
    )
    p_dst0 = _project_trend_to_xsec(
        anchor_xy=(float(dst_anchor[0]), float(dst_anchor[1])),
        trend_xy=t_dst,
        xsec=dst_xsec,
    )
    if p_src0 is None or p_dst0 is None:
        return None, None, None, HARD_CENTER_EMPTY, None, None, trend_meta

    src_ref = _channel_ref_on_xsec(src_xsec=src_xsec, cross_points=src_channel_points)
    dst_ref = _channel_ref_on_xsec(src_xsec=dst_xsec, cross_points=dst_channel_points)
    src_support_raw = _xsec_surface_support(
        xsec=src_xsec,
        gore_zone_metric=gore_zone_metric,
        traj_surface_metric=traj_surface_metric,
        enforced=bool(traj_surface_enforced),
    )
    dst_support_raw = _xsec_surface_support(
        xsec=dst_xsec,
        gore_zone_metric=gore_zone_metric,
        traj_surface_metric=traj_surface_metric,
        enforced=bool(traj_surface_enforced),
    )
    src_support_parts = _iter_linestring_parts(src_support_raw)
    dst_support_parts = _iter_linestring_parts(dst_support_raw)
    src_support_enabled = bool(traj_surface_enforced) and bool(src_support_parts)
    dst_support_enabled = bool(traj_surface_enforced) and bool(dst_support_parts)
    if bool(traj_surface_enforced) and not src_support_enabled:
        trend_meta["xsec_support_disabled_due_to_insufficient_src"] = True
    if bool(traj_surface_enforced) and not dst_support_enabled:
        trend_meta["xsec_support_disabled_due_to_insufficient_dst"] = True

    p_src, mode_src, support_len_src = _project_endpoint_to_valid_xsec(
        endpoint_xy=p_src0,
        xsec=src_xsec,
        gore_zone_metric=gore_zone_metric,
        channel_ref_xy=src_ref,
        xsec_support_geom=(src_support_raw if src_support_enabled else None),
        lb_ref_line=shape_ref_line,
        prefer_lb_guard=not bool(src_support_enabled),
        local_max_dist_m=float(endpoint_local_max_dist_m),
    )
    p_dst, mode_dst, support_len_dst = _project_endpoint_to_valid_xsec(
        endpoint_xy=p_dst0,
        xsec=dst_xsec,
        gore_zone_metric=gore_zone_metric,
        channel_ref_xy=dst_ref,
        xsec_support_geom=(dst_support_raw if dst_support_enabled else None),
        lb_ref_line=shape_ref_line,
        prefer_lb_guard=not bool(dst_support_enabled),
        local_max_dist_m=float(endpoint_local_max_dist_m),
    )
    trend_meta["endpoint_fallback_mode_src"] = str(mode_src)
    trend_meta["endpoint_fallback_mode_dst"] = str(mode_dst)
    trend_meta["xsec_support_len_src"] = float(max(0.0, support_len_src))
    trend_meta["xsec_support_len_dst"] = float(max(0.0, support_len_dst))

    q_src = _nearest_point_on_line_xy(base_line, p_src)
    q_dst = _nearest_point_on_line_xy(base_line, p_dst)
    if q_src is None or q_dst is None:
        return None, None, None, HARD_CENTER_EMPTY, None, None, trend_meta
    proj_dist_src = float(math.hypot(float(p_src[0]) - float(q_src[0]), float(p_src[1]) - float(q_src[1])))
    proj_dist_dst = float(math.hypot(float(p_dst[0]) - float(q_dst[0]), float(p_dst[1]) - float(q_dst[1])))

    s_anchor_src = _xsec_anchor_station(base_line, src_xsec)
    s_anchor_dst = _xsec_anchor_station(base_line, dst_xsec)
    trend_meta["s_anchor_src_m"] = float(s_anchor_src) if s_anchor_src is not None else None
    trend_meta["s_anchor_dst_m"] = float(s_anchor_dst) if s_anchor_dst is not None else None
    try:
        s_src = float(base_line.project(Point(float(q_src[0]), float(q_src[1]))))
        s_dst = float(base_line.project(Point(float(q_dst[0]), float(q_dst[1]))))
    except Exception:
        return None, None, None, HARD_CENTER_EMPTY, None, None, trend_meta
    L = float(base_line.length)
    aw = float(max(0.0, anchor_window_m))
    if s_anchor_src is not None and aw > 0.0:
        lo = max(0.0, float(s_anchor_src) - aw)
        hi = min(L, float(s_anchor_src) + aw)
        s_src = min(max(float(s_src), lo), hi)
        p = base_line.interpolate(s_src)
        pxy = point_xy_safe(p, context="src_anchor_window_snap")
        if pxy is not None:
            q_src = (float(pxy[0]), float(pxy[1]))
    if s_anchor_dst is not None and aw > 0.0:
        lo = max(0.0, float(s_anchor_dst) - aw)
        hi = min(L, float(s_anchor_dst) + aw)
        s_dst = min(max(float(s_dst), lo), hi)
        p = base_line.interpolate(s_dst)
        pxy = point_xy_safe(p, context="dst_anchor_window_snap")
        if pxy is not None:
            q_dst = (float(pxy[0]), float(pxy[1]))
    trend_meta["s_end_src_m"] = float(s_src)
    trend_meta["s_end_dst_m"] = float(s_dst)
    if abs(s_dst - s_src) < 1e-3:
        return None, None, None, HARD_CENTER_EMPTY, proj_dist_src, proj_dist_dst, trend_meta
    s0 = min(s_src, s_dst)
    s1 = max(s_src, s_dst)
    try:
        core = substring(base_line, s0, s1)
    except Exception:
        return None, None, None, HARD_CENTER_EMPTY, proj_dist_src, proj_dist_dst, trend_meta
    if core is None or core.is_empty or (not isinstance(core, LineString)) or len(core.coords) < 2:
        return None, None, None, HARD_CENTER_EMPTY, proj_dist_src, proj_dist_dst, trend_meta
    core = _orient_line(core, src_xsec, dst_xsec)
    core_coords = list(core.coords)
    if len(core_coords) < 2:
        return None, None, None, HARD_CENTER_EMPTY, proj_dist_src, proj_dist_dst, trend_meta

    src_mid = _build_trend_midpoint(
        endpoint_xy=p_src,
        anchor_xy=(float(q_src[0]), float(q_src[1])),
        trend_xy=t_src,
        toward_start=True,
    )
    dst_mid = _build_trend_midpoint(
        endpoint_xy=p_dst,
        anchor_xy=(float(q_dst[0]), float(q_dst[1])),
        trend_xy=t_dst,
        toward_start=False,
    )
    coords: list[tuple[float, float]] = []
    coords.append((float(p_src[0]), float(p_src[1])))
    coords.append((float(src_mid[0]), float(src_mid[1])))
    coords.append((float(q_src[0]), float(q_src[1])))
    for c in core_coords[1:-1]:
        coords.append((float(c[0]), float(c[1])))
    coords.append((float(q_dst[0]), float(q_dst[1])))
    coords.append((float(dst_mid[0]), float(dst_mid[1])))
    coords.append((float(p_dst[0]), float(p_dst[1])))
    coords = _dedup_coords(coords, eps=1e-4)
    if len(coords) < 2:
        return None, None, None, HARD_CENTER_EMPTY, proj_dist_src, proj_dist_dst, trend_meta
    line = LineString(coords)
    if line.is_empty or line.length <= 0:
        return None, None, None, HARD_CENTER_EMPTY, proj_dist_src, proj_dist_dst, trend_meta
    line = _limit_vertices(line, road_max_vertices)

    p0 = Point(line.coords[0])
    p1 = Point(line.coords[-1])
    d0 = float(p0.distance(src_xsec))
    d1 = float(p1.distance(dst_xsec))
    max_local = max(5.0, float(endpoint_local_max_dist_m))
    if d0 > max_local * 1.5 or d1 > max_local * 1.5:
        return None, None, None, HARD_ENDPOINT, proj_dist_src, proj_dist_dst, trend_meta

    dev_src = _endpoint_tangent_deviation(line, trend_xy=t_src, at_start=True)
    dev_dst = _endpoint_tangent_deviation(line, trend_xy=t_dst, at_start=False)

    return line, dev_src, dev_dst, None, proj_dist_src, proj_dist_dst, trend_meta


def _fit_endpoint_trend(
    *,
    stations: np.ndarray,
    points: np.ndarray,
    anchor_idx: int,
    from_src: bool,
    fit_win_m: float,
) -> tuple[float, float] | None:
    n = int(points.shape[0])
    if n < 2:
        return None
    anchor_idx = max(0, min(n - 1, int(anchor_idx)))
    anchor_s = float(stations[anchor_idx])

    if from_src:
        mask = (stations >= max(0.0, anchor_s - float(fit_win_m)) - 1e-9) & (stations <= anchor_s + 1e-9)
    else:
        mask = (stations >= anchor_s - 1e-9) & (stations <= min(float(stations[-1]), anchor_s + float(fit_win_m)) + 1e-9)
    idx = np.flatnonzero(mask)
    if idx.size < 3:
        lo = max(0, anchor_idx - 2)
        hi = min(n, anchor_idx + 3)
        idx = np.arange(lo, hi, dtype=np.int64)
    if idx.size < 2:
        return None

    pts = points[idx, :]
    ctr = np.mean(pts, axis=0)
    rel = pts - ctr[None, :]
    try:
        cov = np.cov(rel.T)
        eig_vals, eig_vecs = np.linalg.eigh(cov)
        vec = eig_vecs[:, int(np.argmax(eig_vals))]
    except Exception:
        vec = rel[-1, :] - rel[0, :]
    if not np.isfinite(vec).all():
        return None
    if np.linalg.norm(vec) <= 1e-9:
        return None
    vec_u = np.asarray(_unit_vec(vec), dtype=np.float64)

    if from_src:
        side_idx = max(0, anchor_idx - min(2, anchor_idx))
    else:
        side_idx = min(n - 1, anchor_idx + min(2, n - 1 - anchor_idx))
    side_vec = points[side_idx, :] - points[anchor_idx, :]
    if np.linalg.norm(side_vec) > 1e-9 and float(np.dot(vec_u, side_vec)) < 0.0:
        vec_u = -vec_u

    return (float(vec_u[0]), float(vec_u[1]))


def _shape_ref_tangent(shape_ref_line: LineString, *, station_m: float) -> tuple[float, float] | None:
    if shape_ref_line is None or shape_ref_line.is_empty or shape_ref_line.length <= 0:
        return None
    L = float(shape_ref_line.length)
    s = min(max(0.0, float(station_m)), L)
    ds = min(2.0, max(0.5, 0.05 * L))
    p0 = shape_ref_line.interpolate(max(0.0, s - ds))
    p1 = shape_ref_line.interpolate(min(L, s + ds))
    p0_xy = point_xy_safe(p0, context="shape_ref_tangent_p0")
    p1_xy = point_xy_safe(p1, context="shape_ref_tangent_p1")
    if p0_xy is None or p1_xy is None:
        return None
    v = np.asarray([float(p1_xy[0]) - float(p0_xy[0]), float(p1_xy[1]) - float(p0_xy[1])], dtype=np.float64)
    if np.linalg.norm(v) <= 1e-9:
        return None
    u = _unit_vec(v)
    return (float(u[0]), float(u[1]))


def _channel_ref_on_xsec(*, src_xsec: LineString, cross_points: Sequence[Point]) -> tuple[float, float] | None:
    if src_xsec.is_empty or src_xsec.length <= 0:
        return None
    refs: list[tuple[float, float]] = []
    for pt in cross_points:
        xy = point_xy_safe(pt, context="channel_ref_pt")
        if xy is None:
            continue
        s = float(src_xsec.project(Point(float(xy[0]), float(xy[1]))))
        p = src_xsec.interpolate(s)
        p_xy = point_xy_safe(p, context="channel_ref_proj")
        if p_xy is not None:
            refs.append((float(p_xy[0]), float(p_xy[1])))
    if not refs:
        return None
    arr = np.asarray(refs, dtype=np.float64)
    return (float(np.median(arr[:, 0])), float(np.median(arr[:, 1])))


def _iter_linestring_parts(geom: BaseGeometry | None) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    gtype = getattr(geom, "geom_type", "")
    if gtype == "LineString":
        ls = geom if isinstance(geom, LineString) else None
        return [ls] if (ls is not None and not ls.is_empty and len(ls.coords) >= 2) else []
    if gtype == "MultiLineString":
        out = []
        for g in getattr(geom, "geoms", []):
            if isinstance(g, LineString) and not g.is_empty and len(g.coords) >= 2:
                out.append(g)
        return out
    if gtype == "GeometryCollection":
        out: list[LineString] = []
        for g in getattr(geom, "geoms", []):
            out.extend(_iter_linestring_parts(g))
        return out
    return []


def _project_endpoint_to_valid_xsec(
    *,
    endpoint_xy: tuple[float, float],
    xsec: LineString,
    gore_zone_metric: BaseGeometry | None,
    channel_ref_xy: tuple[float, float] | None,
    xsec_support_geom: BaseGeometry | None = None,
    lb_ref_line: LineString | None = None,
    prefer_lb_guard: bool = False,
    local_max_dist_m: float = 20.0,
) -> tuple[tuple[float, float], str, float]:
    if xsec.is_empty or xsec.length <= 0:
        return (float(endpoint_xy[0]), float(endpoint_xy[1])), "xsec_empty", 0.0
    valid_geom: BaseGeometry = xsec
    if gore_zone_metric is not None:
        try:
            diff = xsec.difference(gore_zone_metric)
            if diff is not None and not diff.is_empty:
                valid_geom = diff
        except Exception:
            pass
    support_parts = _iter_linestring_parts(xsec_support_geom)
    support_len = float(sum(float(p.length) for p in support_parts))
    parts = support_parts if support_parts else _iter_linestring_parts(valid_geom)
    if not parts:
        out = _adjust_endpoint_on_xsec_gore(endpoint_xy=endpoint_xy, xsec=xsec, gore_zone_metric=gore_zone_metric)
        return out, "fallback_no_parts", support_len

    ref_pt = Point(float(endpoint_xy[0]), float(endpoint_xy[1]))
    ch_pt = (
        Point(float(channel_ref_xy[0]), float(channel_ref_xy[1]))
        if channel_ref_xy is not None
        else None
    )
    lb_line = lb_ref_line if isinstance(lb_ref_line, LineString) and (not lb_ref_line.is_empty) and lb_ref_line.length > 0 else None
    best_xy: tuple[float, float] | None = None
    best_score = float("inf")
    best_d0 = float("inf")
    mode = "enforced_support" if support_parts else ("lb_path_guarded_fallback" if prefer_lb_guard else "channel_fallback")
    for part in parts:
        try:
            s = float(part.project(ref_pt))
            p = part.interpolate(s)
        except Exception:
            continue
        p_xy = point_xy_safe(p, context="project_valid_xsec_part")
        if p_xy is None:
            continue
        d0 = float(math.hypot(float(p_xy[0]) - float(endpoint_xy[0]), float(p_xy[1]) - float(endpoint_xy[1])))
        d1 = 0.0
        if ch_pt is not None:
            d1 = float(ch_pt.distance(Point(float(p_xy[0]), float(p_xy[1]))))
        d_lb = 0.0
        if lb_line is not None:
            try:
                d_lb = float(lb_line.distance(Point(float(p_xy[0]), float(p_xy[1]))))
            except Exception:
                d_lb = 0.0
        if support_parts:
            score = d0 + 0.7 * d1
        elif prefer_lb_guard:
            score = 2.0 * d_lb + 0.6 * d1 + 0.3 * d0
        else:
            score = d0 + 0.7 * d1
        if score < best_score:
            best_score = score
            best_d0 = d0
            best_xy = (float(p_xy[0]), float(p_xy[1]))
    if best_xy is not None:
        if float(local_max_dist_m) > 0.0 and best_d0 > float(local_max_dist_m):
            mode = f"{mode}_out_local"
        return best_xy, mode, support_len
    out = _adjust_endpoint_on_xsec_gore(endpoint_xy=endpoint_xy, xsec=xsec, gore_zone_metric=gore_zone_metric)
    return out, f"{mode}_adjust_gore", support_len


def _xsec_surface_support(
    *,
    xsec: LineString,
    gore_zone_metric: BaseGeometry | None,
    traj_surface_metric: BaseGeometry | None,
    enforced: bool,
) -> BaseGeometry | None:
    if xsec.is_empty or xsec.length <= 0:
        return None
    valid_geom: BaseGeometry = xsec
    if gore_zone_metric is not None:
        try:
            diff = xsec.difference(gore_zone_metric)
            if diff is not None and not diff.is_empty:
                valid_geom = diff
        except Exception:
            pass
    if not enforced or traj_surface_metric is None or traj_surface_metric.is_empty:
        return None
    try:
        inter = valid_geom.intersection(traj_surface_metric)
    except Exception:
        return None
    if inter is None or inter.is_empty:
        return None
    return inter


def _build_trend_midpoint(
    *,
    endpoint_xy: tuple[float, float],
    anchor_xy: tuple[float, float],
    trend_xy: tuple[float, float],
    toward_start: bool,
) -> tuple[float, float]:
    t = np.asarray(_unit_vec(np.asarray([float(trend_xy[0]), float(trend_xy[1])], dtype=np.float64)), dtype=np.float64)
    a = np.asarray([float(anchor_xy[0]), float(anchor_xy[1])], dtype=np.float64)
    e = np.asarray([float(endpoint_xy[0]), float(endpoint_xy[1])], dtype=np.float64)
    d = float(np.linalg.norm(a - e))
    step = min(10.0, max(3.0, 0.6 * d))
    sign = -1.0 if bool(toward_start) else 1.0
    m = a + sign * t * step
    if float(np.linalg.norm(m - a)) > d:
        m = 0.5 * (a + e)
    return (float(m[0]), float(m[1]))


def _endpoint_tangent_deviation(
    line: LineString,
    *,
    trend_xy: tuple[float, float],
    at_start: bool,
) -> float | None:
    if line.is_empty or line.length <= 0 or len(line.coords) < 2:
        return None
    L = float(line.length)
    d = min(10.0, max(1.0, 0.2 * L))
    if at_start:
        p0 = line.interpolate(0.0)
        p1 = line.interpolate(d)
    else:
        p0 = line.interpolate(max(0.0, L - d))
        p1 = line.interpolate(L)
    p0_xy = point_xy_safe(p0, context="endpoint_dev_p0")
    p1_xy = point_xy_safe(p1, context="endpoint_dev_p1")
    if p0_xy is None or p1_xy is None:
        return None
    lv = np.asarray([float(p1_xy[0]) - float(p0_xy[0]), float(p1_xy[1]) - float(p0_xy[1])], dtype=np.float64)
    if np.linalg.norm(lv) <= 1e-9:
        return None
    return _angle_deg(_unit_vec(lv), _unit_vec(np.asarray([float(trend_xy[0]), float(trend_xy[1])], dtype=np.float64)))


def _project_trend_to_xsec(
    *,
    anchor_xy: tuple[float, float],
    trend_xy: tuple[float, float],
    xsec: LineString,
) -> tuple[float, float] | None:
    t = np.asarray([float(trend_xy[0]), float(trend_xy[1])], dtype=np.float64)
    if np.linalg.norm(t) <= 1e-9:
        return None
    t = np.asarray(_unit_vec(t), dtype=np.float64)
    a = np.asarray([float(anchor_xy[0]), float(anchor_xy[1])], dtype=np.float64)
    seg = LineString(
        [
            (float(a[0] - 5000.0 * t[0]), float(a[1] - 5000.0 * t[1])),
            (float(a[0] + 5000.0 * t[0]), float(a[1] + 5000.0 * t[1])),
        ]
    )
    try:
        inter = seg.intersection(xsec)
    except Exception:
        inter = None
    p_xy = _pick_nearest_point_xy(inter, ref_xy=anchor_xy)
    if p_xy is not None:
        return p_xy
    try:
        _lp, xp = nearest_points(seg, xsec)
    except Exception:
        return None
    xp_xy = point_xy_safe(xp, context="trend_project_nearest")
    if xp_xy is None:
        return None
    return (float(xp_xy[0]), float(xp_xy[1]))


def _xsec_anchor_station(line: LineString, xsec: LineString) -> float | None:
    if line.is_empty or line.length <= 0 or xsec.is_empty or xsec.length <= 0:
        return None
    try:
        lp, _xp = nearest_points(line, xsec)
    except Exception:
        return None
    lp_xy = point_xy_safe(lp, context="xsec_anchor_station_line")
    if lp_xy is None:
        return None
    try:
        return float(line.project(Point(float(lp_xy[0]), float(lp_xy[1]))))
    except Exception:
        return None


def _nearest_point_on_line_xy(
    line: LineString,
    xy: tuple[float, float],
) -> tuple[float, float] | None:
    if line.is_empty or line.length <= 0:
        return None
    try:
        s = float(line.project(Point(float(xy[0]), float(xy[1]))))
    except Exception:
        return None
    try:
        p = line.interpolate(s)
    except Exception:
        return None
    p_xy = point_xy_safe(p, context="nearest_point_on_core")
    if p_xy is None:
        return None
    return (float(p_xy[0]), float(p_xy[1]))


def _pick_nearest_point_xy(geom: Any, *, ref_xy: tuple[float, float]) -> tuple[float, float] | None:
    if geom is None:
        return None
    gtype = getattr(geom, "geom_type", "")
    if gtype == "Point":
        return point_xy_safe(geom, context="pick_nearest_point")
    if gtype == "MultiPoint":
        best = None
        best_d = float("inf")
        for g in getattr(geom, "geoms", []):
            xy = point_xy_safe(g, context="pick_nearest_multipoint")
            if xy is None:
                continue
            d = math.hypot(float(xy[0]) - float(ref_xy[0]), float(xy[1]) - float(ref_xy[1]))
            if d < best_d:
                best_d = d
                best = xy
        return best
    if gtype in {"LineString", "LinearRing", "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection"}:
        rp = point_xy_safe(geom, context="pick_nearest_fallback")
        if rp is not None:
            return (float(rp[0]), float(rp[1]))
    return None


def _adjust_endpoint_on_xsec_gore(
    *,
    endpoint_xy: tuple[float, float],
    xsec: LineString,
    gore_zone_metric: BaseGeometry | None,
) -> tuple[float, float]:
    out = (float(endpoint_xy[0]), float(endpoint_xy[1]))
    if gore_zone_metric is None:
        return out
    try:
        if not bool(contains_xy(gore_zone_metric, np.asarray([out[0]]), np.asarray([out[1]])).item()):
            return out
    except Exception:
        return out
    if xsec.is_empty or xsec.length <= 0:
        return out
    ref_pt = Point(out[0], out[1])
    try:
        s0 = float(xsec.project(ref_pt))
    except Exception:
        s0 = 0.0
    L = float(xsec.length)
    offsets = np.linspace(-20.0, 20.0, 81, dtype=np.float64)
    for off in offsets[np.argsort(np.abs(offsets))]:
        s = min(L, max(0.0, s0 + float(off)))
        p = xsec.interpolate(s)
        p_xy = point_xy_safe(p, context="adjust_gore_candidate")
        if p_xy is None:
            continue
        try:
            in_gore = bool(
                contains_xy(
                    gore_zone_metric,
                    np.asarray([float(p_xy[0])], dtype=np.float64),
                    np.asarray([float(p_xy[1])], dtype=np.float64),
                ).item()
            )
        except Exception:
            in_gore = False
        if not in_gore:
            return (float(p_xy[0]), float(p_xy[1]))
    return out


def compute_max_turn_deg_per_10m(line: LineString) -> float | None:
    coords = np.asarray(line.coords, dtype=np.float64)
    if coords.shape[0] < 3:
        return 0.0

    max_val = 0.0
    for i in range(1, coords.shape[0] - 1):
        a = coords[i] - coords[i - 1]
        b = coords[i + 1] - coords[i]
        la = float(np.linalg.norm(a))
        lb = float(np.linalg.norm(b))
        if la <= 1e-6 or lb <= 1e-6:
            continue
        cosv = float(np.dot(a, b) / (la * lb))
        cosv = min(1.0, max(-1.0, cosv))
        angle = math.degrees(math.acos(cosv))
        span = 0.5 * (la + lb)
        scaled = angle * (10.0 / max(span, 1e-3))
        if scaled > max_val:
            max_val = scaled

    return float(max_val)


def compute_max_segment_m(line: LineString) -> float | None:
    if line.is_empty:
        return None
    coords = np.asarray(line.coords, dtype=np.float64)
    if coords.shape[0] < 2:
        return None
    seg = coords[1:, :] - coords[:-1, :]
    d = np.linalg.norm(seg, axis=1)
    if d.size == 0:
        return None
    return float(np.max(d))


def _kind_to_node_type(kind: int) -> str:
    k = int(kind)
    if k & (1 << 4):
        return "diverge"
    if k & (1 << 3):
        return "merge"
    if k & (1 << 2):
        return "non_rc"
    if k == 0:
        return "unknown"
    return "non_rc"


def _detect_multi_road_channels(
    support: PairSupport,
    *,
    sep_m: float,
    topn: int,
) -> _MultiRoadDetectResult:
    n = min(
        len(support.traj_segments),
        len(support.src_cross_points),
        len(support.dst_cross_points),
    )
    if n < 4:
        return _MultiRoadDetectResult(
            has_multi=False,
            keep_idx=None,
            labels_all=[0 for _ in range(int(n))],
            cluster_count=1,
            cluster_sizes=[int(n)] if n > 0 else [],
            main_cluster_id=0,
            main_cluster_ratio=1.0 if n > 0 else 0.0,
            cluster_sep_m_est=None,
        )

    use_n = min(n, max(3, int(topn)))
    mids = np.zeros((use_n, 2), dtype=np.float64)
    for i in range(use_n):
        mid_xy = _safe_midpoint_xy(
            support.traj_segments[i],
            support.src_cross_points[i],
            support.dst_cross_points[i],
        )
        if mid_xy is None:
            return _MultiRoadDetectResult(
                has_multi=False,
                keep_idx=None,
                labels_all=[0 for _ in range(int(n))],
                cluster_count=1,
                cluster_sizes=[int(n)] if n > 0 else [],
                main_cluster_id=0,
                main_cluster_ratio=1.0 if n > 0 else 0.0,
                cluster_sep_m_est=None,
            )
        mids[i, :] = [float(mid_xy[0]), float(mid_xy[1])]

    if mids.shape[0] < 4:
        return _MultiRoadDetectResult(
            has_multi=False,
            keep_idx=None,
            labels_all=[0 for _ in range(int(n))],
            cluster_count=1,
            cluster_sizes=[int(n)] if n > 0 else [],
            main_cluster_id=0,
            main_cluster_ratio=1.0 if n > 0 else 0.0,
            cluster_sep_m_est=None,
        )

    dm = np.linalg.norm(mids[:, None, :] - mids[None, :, :], axis=2)
    medoid_idx = int(np.argmin(np.sum(dm, axis=1)))
    ref = mids[medoid_idx]
    radial = np.linalg.norm(mids - ref[None, :], axis=1)

    labels, centers = _cluster_1d(radial, tol=max(1.0, float(sep_m) * 0.45))
    if len(centers) < 2:
        return _MultiRoadDetectResult(
            has_multi=False,
            keep_idx=None,
            labels_all=[0 for _ in range(int(n))],
            cluster_count=1,
            cluster_sizes=[int(n)] if n > 0 else [],
            main_cluster_id=0,
            main_cluster_ratio=1.0 if n > 0 else 0.0,
            cluster_sep_m_est=None,
        )

    max_sep = float(max(centers) - min(centers))

    radial_all = np.zeros((n,), dtype=np.float64)
    for i in range(n):
        mid_xy = _safe_midpoint_xy(
            support.traj_segments[i],
            support.src_cross_points[i],
            support.dst_cross_points[i],
        )
        if mid_xy is None:
            return _MultiRoadDetectResult(
                has_multi=False,
                keep_idx=None,
                labels_all=[0 for _ in range(int(n))],
                cluster_count=1,
                cluster_sizes=[int(n)] if n > 0 else [],
                main_cluster_id=0,
                main_cluster_ratio=1.0 if n > 0 else 0.0,
                cluster_sep_m_est=None,
            )
        mid = np.asarray([float(mid_xy[0]), float(mid_xy[1])], dtype=np.float64)
        radial_all[i] = float(np.linalg.norm(mid - ref))

    cluster_counts = [0 for _ in centers]
    labels_all = [-1 for _ in range(n)]
    for i, v in enumerate(radial_all):
        dif = [abs(float(v) - float(c)) for c in centers]
        cidx = int(np.argmin(np.asarray(dif, dtype=np.float64)))
        labels_all[i] = cidx
        cluster_counts[cidx] += 1

    major = int(np.argmax(np.asarray(cluster_counts, dtype=np.int64)))
    keep_idx = [i for i, lab in enumerate(labels_all) if int(lab) == major]
    if not keep_idx:
        return _MultiRoadDetectResult(
            has_multi=False,
            keep_idx=None,
            labels_all=[int(v) for v in labels_all],
            cluster_count=max(1, int(len(centers))),
            cluster_sizes=[int(v) for v in cluster_counts],
            main_cluster_id=major,
            main_cluster_ratio=0.0,
            cluster_sep_m_est=max_sep,
        )
    multi = bool(max_sep > float(sep_m))
    return _MultiRoadDetectResult(
        has_multi=multi,
        keep_idx=keep_idx if multi else None,
        labels_all=[int(v) for v in labels_all],
        cluster_count=max(1, int(len(centers))),
        cluster_sizes=[int(v) for v in cluster_counts],
        main_cluster_id=int(major),
        main_cluster_ratio=float(len(keep_idx) / max(1, n)),
        cluster_sep_m_est=max_sep,
    )


def _safe_midpoint_xy(
    line: LineString | None,
    src_pt: Point,
    dst_pt: Point,
) -> tuple[float, float] | None:
    if line is not None and not line.is_empty and line.length > 0:
        p = line.interpolate(0.5, normalized=True)
        p_xy = point_xy_safe(p, context="multi_road_line_mid")
        if p_xy is not None:
            return p_xy
    src_xy = point_xy_safe(src_pt, context="multi_road_src")
    dst_xy = point_xy_safe(dst_pt, context="multi_road_dst")
    if src_xy is None or dst_xy is None:
        return None
    return (
        0.5 * (float(src_xy[0]) + float(dst_xy[0])),
        0.5 * (float(src_xy[1]) + float(dst_xy[1])),
    )


def _cluster_1d(values: np.ndarray, *, tol: float) -> tuple[list[int], list[float]]:
    if values.size == 0:
        return [], []
    order = np.argsort(values)
    labels = [-1 for _ in range(values.size)]
    centers: list[float] = []
    counts: list[int] = []
    for idx in order:
        v = float(values[int(idx)])
        assigned = False
        for cid, c in enumerate(centers):
            if abs(v - c) <= float(tol):
                labels[int(idx)] = cid
                counts[cid] += 1
                centers[cid] = centers[cid] + (v - centers[cid]) / float(counts[cid])
                assigned = True
                break
        if not assigned:
            labels[int(idx)] = len(centers)
            centers.append(v)
            counts.append(1)
    return labels, centers


def _normalize_stitch_levels(
    *,
    stitch_max_dist_levels_m: Sequence[float] | None,
    stitch_max_dist_m: float,
) -> list[float]:
    if stitch_max_dist_levels_m:
        vals = [float(v) for v in stitch_max_dist_levels_m if float(v) > 0.0]
        if vals:
            return sorted(set(vals))
    if float(stitch_max_dist_m) > 0:
        return [float(stitch_max_dist_m)]
    return []


def _sample_heading_by_points(pts: np.ndarray) -> np.ndarray:
    n = int(pts.shape[0])
    out = np.zeros((n, 2), dtype=np.float64)
    if n <= 1:
        out[:, 0] = 1.0
        return out
    for i in range(n):
        if i == 0:
            v = pts[1, :] - pts[0, :]
        elif i == n - 1:
            v = pts[-1, :] - pts[-2, :]
        else:
            v = pts[i + 1, :] - pts[i - 1, :]
        out[i, :] = np.asarray(_unit_vec(v), dtype=np.float64)
    return out


def _query_stitch_grid_keys(
    grid: dict[tuple[int, int], list[str]],
    *,
    center_xy: np.ndarray,
    radius_m: float,
    cell_size: float,
) -> list[str]:
    if radius_m <= 0.0:
        return []
    gx, gy = _grid_key(float(center_xy[0]), float(center_xy[1]), float(cell_size))
    dr = int(math.ceil(float(radius_m) / max(1e-6, float(cell_size))))
    out: list[str] = []
    for ix in range(gx - dr, gx + dr + 1):
        for iy in range(gy - dr, gy + dr + 1):
            out.extend(grid.get((ix, iy), []))
    return out


def _format_level_key(v: float) -> str:
    f = float(v)
    if abs(f - round(f)) <= 1e-6:
        return str(int(round(f)))
    return f"{f:.3f}"


def _traj_station(coords: np.ndarray) -> np.ndarray:
    if coords.shape[0] <= 1:
        return np.zeros((coords.shape[0],), dtype=np.float64)
    d = np.linalg.norm(coords[1:, :] - coords[:-1, :], axis=1)
    return np.concatenate((np.asarray([0.0], dtype=np.float64), np.cumsum(np.asarray(d, dtype=np.float64))))


def _unit_vec(v: np.ndarray) -> tuple[float, float]:
    x = float(v[0])
    y = float(v[1])
    n = math.hypot(x, y)
    if n <= 1e-12:
        return (1.0, 0.0)
    return (x / n, y / n)


def _as_float_or_none(v: Any) -> float | None:
    try:
        f = float(v)
    except Exception:
        return None
    if not np.isfinite(f):
        return None
    return float(f)


def _angle_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    an = math.hypot(ax, ay)
    bn = math.hypot(bx, by)
    if an <= 1e-12 or bn <= 1e-12:
        return 180.0
    cosv = (ax * bx + ay * by) / max(1e-12, an * bn)
    cosv = min(1.0, max(-1.0, float(cosv)))
    return float(math.degrees(math.acos(cosv)))


def _grid_key(x: float, y: float, cell: float) -> tuple[int, int]:
    return (int(math.floor(float(x) / float(cell))), int(math.floor(float(y) / float(cell))))


def _append_coords(dst: list[tuple[float, float]], src: list[tuple[float, float]]) -> None:
    if not src:
        return
    if not dst:
        dst.extend([(float(x), float(y)) for x, y in src])
        return
    first = (float(src[0][0]), float(src[0][1]))
    if math.hypot(first[0] - dst[-1][0], first[1] - dst[-1][1]) <= 1e-6:
        src = src[1:]
    dst.extend([(float(x), float(y)) for x, y in src])


def point_xy_safe(pt: Any, *, context: str) -> tuple[float, float] | None:
    del context
    if pt is None:
        return None
    try:
        if isinstance(pt, Point):
            if pt.is_empty:
                return None
            return (float(pt.x), float(pt.y))

        gtype = getattr(pt, "geom_type", "")
        if gtype == "MultiPoint":
            for sub in getattr(pt, "geoms", []):
                xy = point_xy_safe(sub, context="multipoint")
                if xy is not None:
                    return xy
            return None

        if gtype in {
            "LineString",
            "LinearRing",
            "MultiLineString",
            "Polygon",
            "MultiPolygon",
            "GeometryCollection",
        }:
            rp = pt.representative_point()
            if rp is None or rp.is_empty:
                return None
            return (float(rp.x), float(rp.y))
    except Exception:
        return None
    return None


def _segment_cross_point(seg: LineString, xline: LineString) -> Point | None:
    if seg.is_empty or xline.is_empty:
        return None
    try:
        p_seg, p_xsec = nearest_points(seg, xline)
    except Exception:
        return None

    xy_seg = point_xy_safe(p_seg, context="nearest_seg")
    xy_xsec = point_xy_safe(p_xsec, context="nearest_xsec")
    if xy_seg is None or xy_xsec is None:
        return None
    return Point(
        0.5 * (float(xy_seg[0]) + float(xy_xsec[0])),
        0.5 * (float(xy_seg[1]) + float(xy_xsec[1])),
    )


def _segment_fraction_xy(cp_xy: tuple[float, float], p0: np.ndarray, p1: np.ndarray) -> float:
    d = p1 - p0
    l2 = float(np.dot(d, d))
    if l2 <= 1e-12:
        return 0.5
    t = float(((float(cp_xy[0]) - p0[0]) * d[0] + (float(cp_xy[1]) - p0[1]) * d[1]) / l2)
    return min(1.0, max(0.0, t))


def _dedup_events_by_node(events: list[CrossingEvent], *, dedup_gap_m: float) -> tuple[list[CrossingEvent], int]:
    del dedup_gap_m
    if not events:
        return [], 0

    best_by_node: dict[int, CrossingEvent] = {}
    for ev in events:
        prev = best_by_node.get(int(ev.nodeid))
        if prev is None:
            best_by_node[int(ev.nodeid)] = ev
            continue
        key_prev = (float(prev.cross_dist_m), float(prev.station_m), int(prev.seq_idx))
        key_curr = (float(ev.cross_dist_m), float(ev.station_m), int(ev.seq_idx))
        if key_curr < key_prev:
            best_by_node[int(ev.nodeid)] = ev

    out = sorted(best_by_node.values(), key=lambda e: (float(e.station_m), int(e.nodeid), int(e.seq_idx)))
    dropped = int(len(events) - len(out))
    return out, dropped


def _extract_traj_segment(traj: TrajectoryData, a: CrossingEvent, b: CrossingEvent) -> LineString | None:
    xy = np.asarray(traj.xyz_metric[:, :2], dtype=np.float64)
    n = xy.shape[0]
    if n < 2:
        return None

    i0 = max(0, min(n - 2, int(a.seg_idx)))
    i1 = max(0, min(n - 2, int(b.seg_idx)))
    if i1 < i0:
        i0, i1 = i1, i0

    a_xy = point_xy_safe(a.cross_point, context="extract_traj_segment_a")
    b_xy = point_xy_safe(b.cross_point, context="extract_traj_segment_b")
    if a_xy is None or b_xy is None:
        return None

    coords: list[tuple[float, float]] = [(float(a_xy[0]), float(a_xy[1]))]
    for i in range(i0 + 1, i1 + 1):
        coords.append((float(xy[i, 0]), float(xy[i, 1])))
    coords.append((float(b_xy[0]), float(b_xy[1])))

    coords = _dedup_coords(coords)
    if len(coords) < 2:
        return None

    seg = LineString(coords)
    if seg.is_empty or seg.length <= 0:
        return None
    return seg


def _dedup_coords(coords: list[tuple[float, float]], eps: float = 1e-6) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for c in coords:
        if not out:
            out.append(c)
            continue
        if math.hypot(c[0] - out[-1][0], c[1] - out[-1][1]) > eps:
            out.append(c)
    return out


def _choose_shape_ref(
    support: PairSupport,
    src_xsec: LineString,
    dst_xsec: LineString,
    lane_boundaries_metric: Sequence[LineString],
) -> _ShapeRefChoice:
    return _choose_shape_ref_with_graph(
        support=support,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        lane_boundaries_metric=lane_boundaries_metric,
        lb_snap_m=1.0,
        lb_start_end_topk=5,
    )


def _choose_shape_ref_with_graph(
    *,
    support: PairSupport,
    src_xsec: LineString,
    dst_xsec: LineString,
    lane_boundaries_metric: Sequence[LineString],
    lb_snap_m: float,
    lb_start_end_topk: int,
    traj_surface_metric: BaseGeometry | None = None,
    lb_outside_lambda: float = 0.0,
    traj_surface_enforced: bool = False,
    outside_edge_ratio_max: float = 1.0,
    surface_node_buffer_m: float = 2.0,
    divstrip_barrier_metric: BaseGeometry | None = None,
) -> _ShapeRefChoice:
    lb_diag: dict[str, Any] = {}
    lb_path = _build_lb_graph_path(
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        lane_boundaries_metric=lane_boundaries_metric,
        snap_m=max(0.1, float(lb_snap_m)),
        topk=max(1, int(lb_start_end_topk)),
        traj_surface_metric=traj_surface_metric,
        outside_lambda=max(0.0, float(lb_outside_lambda)),
        enforce_surface=bool(traj_surface_enforced),
        outside_edge_ratio_max=float(outside_edge_ratio_max),
        surface_node_buffer_m=float(surface_node_buffer_m),
        divstrip_barrier_metric=divstrip_barrier_metric,
        diag_out=lb_diag,
    )
    if lb_path is not None and lb_path[0] is not None:
        lb_line = _orient_line(lb_path[0], src_xsec, dst_xsec)
        return _ShapeRefChoice(
            line=lb_line,
            used_lane_boundary=True,
            lb_path_found=True,
            lb_path_edge_count=int(lb_path[1]),
            lb_path_length_m=float(lb_line.length),
            lb_graph_build_ms=_as_float_or_none(lb_diag.get("t_build_lane_graph_ms")),
            lb_shortest_path_ms=_as_float_or_none(lb_diag.get("t_shortest_path_ms")),
            lb_graph_edge_total=int(lb_diag.get("edge_total", 0)),
            lb_graph_edge_filtered=int(lb_diag.get("edge_filtered", 0)),
        )

    return _ShapeRefChoice(
        line=None,
        used_lane_boundary=False,
        lb_path_found=False,
        lb_path_edge_count=0,
        lb_path_length_m=None,
        lb_graph_build_ms=_as_float_or_none(lb_diag.get("t_build_lane_graph_ms")),
        lb_shortest_path_ms=_as_float_or_none(lb_diag.get("t_shortest_path_ms")),
        lb_graph_edge_total=int(lb_diag.get("edge_total", 0)),
        lb_graph_edge_filtered=int(lb_diag.get("edge_filtered", 0)),
    )


def _build_shape_ref_from_surface_points(
    *,
    src_xsec: LineString,
    dst_xsec: LineString,
    points_xyz: np.ndarray,
    gore_zone_metric: BaseGeometry | None,
    corridor_half_width_m: float,
    sample_step_m: float,
) -> LineString | None:
    if points_xyz.size == 0 or points_xyz.shape[0] < 32:
        return None
    src_c = src_xsec.interpolate(0.5, normalized=True) if src_xsec.length > 0 else None
    dst_c = dst_xsec.interpolate(0.5, normalized=True) if dst_xsec.length > 0 else None
    src_xy = point_xy_safe(src_c, context="shape_ref_surface_src")
    dst_xy = point_xy_safe(dst_c, context="shape_ref_surface_dst")
    if src_xy is None or dst_xy is None:
        return None
    dx = float(dst_xy[0] - src_xy[0])
    dy = float(dst_xy[1] - src_xy[1])
    axis = np.asarray(_unit_vec(np.asarray([dx, dy], dtype=np.float64)), dtype=np.float64)
    axis_len = float(math.hypot(dx, dy))
    if axis_len <= 1.0:
        return None
    normal = np.asarray([-axis[1], axis[0]], dtype=np.float64)

    xy = np.asarray(points_xyz[:, :2], dtype=np.float64)
    finite = np.isfinite(xy[:, 0]) & np.isfinite(xy[:, 1])
    if np.count_nonzero(finite) < 32:
        return None
    xy = xy[finite, :]
    if gore_zone_metric is not None and xy.shape[0] > 0:
        try:
            gore_mask = np.asarray(contains_xy(gore_zone_metric, xy[:, 0], xy[:, 1]), dtype=bool)
            xy = xy[~gore_mask, :]
        except Exception:
            pass
    if xy.shape[0] < 24:
        return None

    rel = xy - np.asarray([float(src_xy[0]), float(src_xy[1])], dtype=np.float64)[None, :]
    along = rel @ axis
    across = rel @ normal
    keep = (
        (along >= -10.0)
        & (along <= axis_len + 10.0)
        & (np.abs(across) <= max(10.0, float(corridor_half_width_m) * 1.5))
    )
    if np.count_nonzero(keep) < 24:
        return None
    along = along[keep]
    across = across[keep]

    step = max(3.0, float(sample_step_m))
    stations = np.arange(0.0, axis_len + step * 0.5, step, dtype=np.float64)
    if stations.size == 0 or abs(float(stations[-1]) - axis_len) > 1e-6:
        stations = np.concatenate((stations, np.asarray([axis_len], dtype=np.float64)))
    stations = np.unique(np.clip(stations, 0.0, axis_len))

    centers: list[tuple[float, float]] = []
    win = max(2.0, step * 0.75)
    for s in stations:
        mask = np.abs(along - float(s)) <= win
        if np.count_nonzero(mask) < 8:
            continue
        ac = float(np.median(across[mask]))
        px = float(src_xy[0] + axis[0] * float(s) + normal[0] * ac)
        py = float(src_xy[1] + axis[1] * float(s) + normal[1] * ac)
        centers.append((px, py))
    if len(centers) < 3:
        return None
    line = LineString(_dedup_coords(centers, eps=1e-3))
    if line.is_empty or line.length <= 1.0:
        return None
    line = _orient_line(line, src_xsec, dst_xsec)
    line = _densify_line(line, step_m=5.0)
    if line.length <= 1.0 or len(line.coords) < 2:
        return None
    return line


def _build_lb_graph_path(
    *,
    src_xsec: LineString,
    dst_xsec: LineString,
    lane_boundaries_metric: Sequence[LineString],
    snap_m: float,
    topk: int,
    traj_surface_metric: BaseGeometry | None = None,
    outside_lambda: float = 0.0,
    enforce_surface: bool = False,
    outside_edge_ratio_max: float = 1.0,
    surface_node_buffer_m: float = 2.0,
    divstrip_barrier_metric: BaseGeometry | None = None,
    diag_out: dict[str, Any] | None = None,
) -> tuple[LineString, int] | None:
    if not lane_boundaries_metric:
        return None

    t0_build = perf_counter()
    nodes_xy: list[tuple[float, float]] = []
    edges: list[_LbGraphEdge] = []
    adj: dict[int, list[tuple[int, int, bool]]] = {}
    edge_total = 0
    edge_filtered = 0

    surface_metric = traj_surface_metric
    if (
        bool(enforce_surface)
        and traj_surface_metric is not None
        and (not traj_surface_metric.is_empty)
        and float(surface_node_buffer_m) > 0.0
    ):
        try:
            surface_metric = traj_surface_metric.buffer(float(surface_node_buffer_m))
        except Exception:
            surface_metric = traj_surface_metric

    barrier_metric = divstrip_barrier_metric

    def _snap_node(xy: tuple[float, float]) -> int:
        if not nodes_xy:
            nodes_xy.append((float(xy[0]), float(xy[1])))
            return 0
        best_idx = -1
        best_dist = float("inf")
        for i, p in enumerate(nodes_xy):
            d = math.hypot(float(xy[0]) - p[0], float(xy[1]) - p[1])
            if d <= snap_m + 1e-9 and d < best_dist:
                best_idx = int(i)
                best_dist = float(d)
        if best_idx >= 0:
            return best_idx
        nodes_xy.append((float(xy[0]), float(xy[1])))
        return int(len(nodes_xy) - 1)

    for lb in lane_boundaries_metric:
        if lb is None or lb.is_empty or lb.length <= 0:
            continue
        coords = list(lb.coords)
        if len(coords) < 2:
            continue
        for i in range(len(coords) - 1):
            p0 = (float(coords[i][0]), float(coords[i][1]))
            p1 = (float(coords[i + 1][0]), float(coords[i + 1][1]))
            seg_len = float(math.hypot(p1[0] - p0[0], p1[1] - p0[1]))
            if seg_len <= 1e-6:
                continue
            edge_total += 1
            seg_geom = LineString([p0, p1])
            if barrier_metric is not None and (not barrier_metric.is_empty):
                try:
                    if bool(seg_geom.intersects(barrier_metric)):
                        edge_filtered += 1
                        continue
                except Exception:
                    pass
            outside_len = 0.0
            if (
                surface_metric is not None
                and (not surface_metric.is_empty)
                and (float(outside_lambda) > 0.0 or bool(enforce_surface))
            ):
                try:
                    outside_len = float(seg_geom.difference(surface_metric).length)
                except Exception:
                    outside_len = 0.0
            if bool(enforce_surface):
                ratio = float(outside_len / max(seg_len, 1e-6))
                if ratio > float(max(0.0, outside_edge_ratio_max)):
                    edge_filtered += 1
                    continue
            seg_cost = float(seg_len + max(0.0, float(outside_lambda)) * max(0.0, outside_len))
            u = _snap_node(p0)
            v = _snap_node(p1)
            if u == v:
                continue
            eidx = len(edges)
            edges.append(
                _LbGraphEdge(
                    u=u,
                    v=v,
                    length=seg_len,
                    cost=seg_cost,
                    outside_len=float(outside_len),
                    coords=(p0, p1),
                )
            )
            adj.setdefault(u, []).append((v, eidx, True))
            adj.setdefault(v, []).append((u, eidx, False))

    if not nodes_xy or not edges:
        if diag_out is not None:
            diag_out["t_build_lane_graph_ms"] = float((perf_counter() - t0_build) * 1000.0)
            diag_out["t_shortest_path_ms"] = 0.0
            diag_out["edge_total"] = int(edge_total)
            diag_out["edge_filtered"] = int(edge_filtered)
        return None

    start_nodes = _rank_lb_nodes_for_xsec(
        nodes_xy=nodes_xy,
        xsec=src_xsec,
        topk=topk,
        surface_filter_geom=(surface_metric if bool(enforce_surface) else None),
    )
    end_nodes = _rank_lb_nodes_for_xsec(
        nodes_xy=nodes_xy,
        xsec=dst_xsec,
        topk=topk,
        surface_filter_geom=(surface_metric if bool(enforce_surface) else None),
    )
    if start_nodes and end_nodes:
        start_set = {int(v) for v in start_nodes}
        end_filtered = [int(v) for v in end_nodes if int(v) not in start_set]
        if end_filtered:
            end_nodes = end_filtered
        elif start_set == {int(v) for v in end_nodes}:
            start_nodes = [int(start_nodes[0])]
            end_pick = int(end_nodes[0])
            if end_pick == int(start_nodes[0]) and len(end_nodes) > 1:
                end_pick = int(end_nodes[1])
            end_nodes = [end_pick]
    if not start_nodes or not end_nodes:
        if diag_out is not None:
            diag_out["t_build_lane_graph_ms"] = float((perf_counter() - t0_build) * 1000.0)
            diag_out["t_shortest_path_ms"] = 0.0
            diag_out["edge_total"] = int(edge_total)
            diag_out["edge_filtered"] = int(edge_filtered)
        return None

    t1_build = perf_counter()
    t0_sp = perf_counter()
    best = _dijkstra_lb_path(
        start_nodes=start_nodes,
        end_nodes=end_nodes,
        adj=adj,
        edges=edges,
    )
    t_sp_ms = float((perf_counter() - t0_sp) * 1000.0)
    if best is None:
        if diag_out is not None:
            diag_out["t_build_lane_graph_ms"] = float((t1_build - t0_build) * 1000.0)
            diag_out["t_shortest_path_ms"] = float(t_sp_ms)
            diag_out["edge_total"] = int(edge_total)
            diag_out["edge_filtered"] = int(edge_filtered)
        return None
    path_nodes, path_edge_refs = best
    if len(path_nodes) < 2 or len(path_edge_refs) < 1:
        return None

    coords: list[tuple[float, float]] = []
    for edge_idx, forward in path_edge_refs:
        e = edges[edge_idx]
        seg = [e.coords[0], e.coords[1]] if forward else [e.coords[1], e.coords[0]]
        _append_coords(coords, seg)
    coords = _dedup_coords(coords, eps=1e-3)
    if len(coords) < 2:
        return None
    line = LineString(coords)
    if line.is_empty or line.length <= 0:
        return None
    line = _densify_line(line, step_m=5.0)
    try:
        simp = line.simplify(0.8, preserve_topology=False)
    except Exception:
        simp = line
    if isinstance(simp, LineString) and not simp.is_empty and len(simp.coords) >= 2:
        line = _densify_line(simp, step_m=5.0)
    if diag_out is not None:
        diag_out["t_build_lane_graph_ms"] = float((t1_build - t0_build) * 1000.0)
        diag_out["t_shortest_path_ms"] = float(t_sp_ms)
        diag_out["edge_total"] = int(edge_total)
        diag_out["edge_filtered"] = int(edge_filtered)
    return line, int(len(path_edge_refs))


def _rank_lb_nodes_for_xsec(
    *,
    nodes_xy: Sequence[tuple[float, float]],
    xsec: LineString,
    topk: int,
    surface_filter_geom: BaseGeometry | None = None,
) -> list[int]:
    if not nodes_xy:
        return []
    surface_check_geom = None
    if surface_filter_geom is not None and (not surface_filter_geom.is_empty):
        try:
            surface_check_geom = surface_filter_geom.buffer(1e-6)
        except Exception:
            surface_check_geom = surface_filter_geom
    scores: list[tuple[float, int]] = []
    for i, xy in enumerate(nodes_xy):
        if surface_check_geom is not None:
            try:
                if not bool(surface_check_geom.covers(Point(float(xy[0]), float(xy[1])))):
                    continue
            except Exception:
                continue
        try:
            d = float(Point(float(xy[0]), float(xy[1])).distance(xsec))
        except Exception:
            d = float("inf")
        scores.append((d, int(i)))
    scores.sort(key=lambda it: (it[0], it[1]))
    out = [idx for _, idx in scores[: max(1, int(topk))]]
    return out


def _dijkstra_lb_path(
    *,
    start_nodes: Sequence[int],
    end_nodes: Sequence[int],
    adj: dict[int, list[tuple[int, int, bool]]],
    edges: Sequence[_LbGraphEdge],
) -> tuple[list[int], list[tuple[int, bool]]] | None:
    target_set = {int(v) for v in end_nodes}
    start_set = {int(v) for v in start_nodes}
    if not target_set:
        return None

    best: dict[int, float] = {}
    prev: dict[int, tuple[int, int, bool]] = {}
    heap: list[tuple[float, int]] = []
    for s in start_nodes:
        s_int = int(s)
        best[s_int] = 0.0
        heapq.heappush(heap, (0.0, s_int))

    end_hit: int | None = None
    while heap:
        dist, node = heapq.heappop(heap)
        cur_best = best.get(node)
        if cur_best is None or dist > cur_best + 1e-9:
            continue
        if node in target_set and not (node in start_set and dist <= 1e-9):
            end_hit = int(node)
            break
        for nei, eidx, forward in adj.get(node, []):
            w = float(edges[eidx].cost)
            nd = float(dist + w)
            old = best.get(int(nei))
            if old is not None and nd >= old - 1e-9:
                continue
            best[int(nei)] = nd
            prev[int(nei)] = (int(node), int(eidx), bool(forward))
            heapq.heappush(heap, (nd, int(nei)))

    if end_hit is None:
        return None

    nodes_out: list[int] = [int(end_hit)]
    edge_out: list[tuple[int, bool]] = []
    cur = int(end_hit)
    while cur not in start_set:
        p = prev.get(cur)
        if p is None:
            return None
        prev_node, edge_idx, forward = p
        edge_out.append((int(edge_idx), bool(forward)))
        nodes_out.append(int(prev_node))
        cur = int(prev_node)
    nodes_out.reverse()
    edge_out.reverse()
    return nodes_out, edge_out


def _orient_line(line: LineString, src_xsec: LineString, dst_xsec: LineString) -> LineString:
    if line.is_empty or len(line.coords) < 2:
        return line
    p0 = Point(line.coords[0])
    p1 = Point(line.coords[-1])

    forward = p0.distance(src_xsec) + p1.distance(dst_xsec)
    backward = p1.distance(src_xsec) + p0.distance(dst_xsec)
    if backward < forward:
        return LineString(list(line.coords)[::-1])
    return line


def _shape_ref_substring_by_xsecs(
    line: LineString,
    *,
    src_xsec: LineString,
    dst_xsec: LineString,
) -> LineString | None:
    if line.is_empty or line.length <= 0:
        return None
    try:
        p_src_line, _ = nearest_points(line, src_xsec)
        p_dst_line, _ = nearest_points(line, dst_xsec)
    except Exception:
        return None
    p_src_xy = point_xy_safe(p_src_line, context="shape_ref_sub_src")
    p_dst_xy = point_xy_safe(p_dst_line, context="shape_ref_sub_dst")
    if p_src_xy is None or p_dst_xy is None:
        return None
    try:
        s_src = float(line.project(Point(float(p_src_xy[0]), float(p_src_xy[1]))))
        s_dst = float(line.project(Point(float(p_dst_xy[0]), float(p_dst_xy[1]))))
    except Exception:
        return None
    if abs(s_dst - s_src) < 1e-3:
        return None
    s0 = min(s_src, s_dst)
    s1 = max(s_src, s_dst)
    try:
        seg = substring(line, s0, s1)
    except Exception:
        return None
    if seg is None or seg.is_empty or (not isinstance(seg, LineString)) or len(seg.coords) < 2:
        return None
    seg = _orient_line(seg, src_xsec, dst_xsec)
    return seg


def _densify_line(line: LineString, *, step_m: float) -> LineString:
    if line.is_empty or line.length <= 0:
        return line
    step = max(0.5, float(step_m))
    L = float(line.length)
    ss = np.arange(0.0, L + step * 0.5, step, dtype=np.float64)
    if ss.size == 0 or abs(float(ss[-1]) - L) > 1e-6:
        ss = np.concatenate((ss, np.asarray([L], dtype=np.float64)))
    ss = np.unique(np.clip(ss, 0.0, L))
    coords: list[tuple[float, float]] = []
    for s in ss:
        p = line.interpolate(float(s))
        p_xy = point_xy_safe(p, context="densify_line")
        if p_xy is None:
            continue
        coords.append((float(p_xy[0]), float(p_xy[1])))
    coords = _dedup_coords(coords, eps=1e-5)
    if len(coords) < 2:
        return line
    return LineString(coords)


def _sample_line(line: LineString, *, step_m: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    length = float(line.length)
    if length <= 0:
        return (
            np.empty((0,), dtype=np.float64),
            np.empty((0, 2), dtype=np.float64),
            np.empty((0, 2), dtype=np.float64),
            np.empty((0, 2), dtype=np.float64),
        )

    n = max(2, int(math.ceil(length / max(step_m, 0.5))) + 1)
    ss = np.linspace(0.0, length, n)
    pts = np.zeros((n, 2), dtype=np.float64)
    tangents = np.zeros((n, 2), dtype=np.float64)
    normals = np.zeros((n, 2), dtype=np.float64)

    delta = min(2.0, max(0.5, step_m * 0.5))

    for i, s in enumerate(ss):
        p = line.interpolate(float(s))
        p_xy = point_xy_safe(p, context="sample_line_point")
        if p_xy is None:
            if i > 0:
                pts[i, :] = pts[i - 1, :]
            else:
                p0 = line.coords[0]
                pts[i, :] = [float(p0[0]), float(p0[1])]
        else:
            pts[i, :] = [float(p_xy[0]), float(p_xy[1])]

        s0 = max(0.0, float(s - delta))
        s1 = min(length, float(s + delta))
        p0 = line.interpolate(s0)
        p1 = line.interpolate(s1)
        p0_xy = point_xy_safe(p0, context="sample_line_tangent_p0")
        p1_xy = point_xy_safe(p1, context="sample_line_tangent_p1")
        if p0_xy is None or p1_xy is None:
            v = np.asarray([0.0, 0.0], dtype=np.float64)
        else:
            v = np.asarray([float(p1_xy[0]) - float(p0_xy[0]), float(p1_xy[1]) - float(p0_xy[1])], dtype=np.float64)
        nv = np.linalg.norm(v)
        if nv <= 1e-9:
            if i > 0:
                tangents[i, :] = tangents[i - 1, :]
                normals[i, :] = normals[i - 1, :]
            else:
                tangents[i, :] = [1.0, 0.0]
                normals[i, :] = [0.0, 1.0]
            continue

        t = v / nv
        tangents[i, :] = t
        normals[i, :] = np.asarray([-t[1], t[0]], dtype=np.float64)

    return ss, pts, tangents, normals


def _estimate_offsets_from_surface(
    *,
    sample_points: np.ndarray,
    tangents: np.ndarray,
    normals: np.ndarray,
    points_xyz: np.ndarray,
    gore_zone_metric: BaseGeometry | None,
    along_half_window_m: float,
    across_half_window_m: float,
    corridor_half_width_m: float,
    min_points: int,
    width_pct_low: float,
    width_pct_high: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    n = sample_points.shape[0]
    offsets = np.full((n,), np.nan, dtype=np.float64)
    widths = np.full((n,), np.nan, dtype=np.float64)
    gore_overlap = np.full((n,), np.nan, dtype=np.float64)

    if points_xyz.size == 0 or points_xyz.shape[0] < 8:
        return offsets, widths, gore_overlap, 0.0

    xy = np.asarray(points_xyz[:, :2], dtype=np.float64)
    grid = _build_grid_index(xy, cell_size=max(2.0, across_half_window_m / 3.0))

    for i in range(n):
        c = sample_points[i]
        t = tangents[i]
        no = normals[i]

        idx = _query_grid_indices(
            grid,
            center_xy=c,
            half_dx=along_half_window_m + across_half_window_m,
            half_dy=along_half_window_m + across_half_window_m,
        )
        if idx.size == 0:
            continue

        rel = xy[idx, :] - c[None, :]
        along = rel @ t
        across = rel @ no
        keep_window = (np.abs(along) <= along_half_window_m) & (np.abs(across) <= across_half_window_m)
        if np.count_nonzero(keep_window) < 1:
            continue
        gore_mask_local = np.zeros((idx.size,), dtype=bool)
        if gore_zone_metric is not None:
            try:
                gore_mask_local = np.asarray(
                    contains_xy(gore_zone_metric, xy[idx, 0], xy[idx, 1]),
                    dtype=bool,
                )
            except Exception:
                gore_mask_local = np.zeros((idx.size,), dtype=bool)
        total_ground = int(np.count_nonzero(keep_window))
        gore_cut = int(np.count_nonzero(keep_window & gore_mask_local))
        if total_ground > 0:
            gore_overlap[i] = float(gore_cut / float(total_ground))
        keep = (
            keep_window
            & (~gore_mask_local)
            & (np.abs(across) <= max(0.1, float(corridor_half_width_m)))
        )
        if np.count_nonzero(keep) < int(min_points):
            continue

        vals = across[keep]
        lo = float(np.percentile(vals, width_pct_low))
        hi = float(np.percentile(vals, width_pct_high))
        center = 0.5 * (lo + hi)

        offsets[i] = center
        widths[i] = max(0.0, hi - lo)

    coverage = float(np.count_nonzero(np.isfinite(offsets)) / max(1, n))
    return offsets, widths, gore_overlap, coverage


def _build_grid_index(xy: np.ndarray, *, cell_size: float) -> dict[str, Any]:
    x = xy[:, 0]
    y = xy[:, 1]
    ix = np.floor(x / cell_size).astype(np.int64)
    iy = np.floor(y / cell_size).astype(np.int64)

    cells: dict[tuple[int, int], list[int]] = {}
    for i in range(xy.shape[0]):
        key = (int(ix[i]), int(iy[i]))
        cells.setdefault(key, []).append(i)

    compact = {k: np.asarray(v, dtype=np.int64) for k, v in cells.items()}
    return {"cell_size": float(cell_size), "cells": compact}


def _query_grid_indices(
    grid: dict[str, Any],
    *,
    center_xy: np.ndarray,
    half_dx: float,
    half_dy: float,
) -> np.ndarray:
    cell_size = float(grid["cell_size"])
    cells: dict[tuple[int, int], np.ndarray] = grid["cells"]

    minx = center_xy[0] - half_dx
    maxx = center_xy[0] + half_dx
    miny = center_xy[1] - half_dy
    maxy = center_xy[1] + half_dy

    ix0 = int(math.floor(minx / cell_size))
    ix1 = int(math.floor(maxx / cell_size))
    iy0 = int(math.floor(miny / cell_size))
    iy1 = int(math.floor(maxy / cell_size))

    out: list[np.ndarray] = []
    for ix in range(ix0, ix1 + 1):
        for iy in range(iy0, iy1 + 1):
            arr = cells.get((ix, iy))
            if arr is not None and arr.size > 0:
                out.append(arr)

    if not out:
        return np.empty((0,), dtype=np.int64)
    return np.concatenate(out)


def _smooth_offsets(offsets: np.ndarray, *, step_m: float, window_m: float) -> np.ndarray:
    x = np.asarray(offsets, dtype=np.float64).copy()
    if np.count_nonzero(np.isfinite(x)) == 0:
        return x

    x = _fill_nan_linear(x)

    win = max(1, int(round(window_m / max(step_m, 0.5))))
    if win <= 1:
        return x
    if win % 2 == 0:
        win += 1

    pad = win // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    kernel = np.ones((win,), dtype=np.float64) / float(win)
    smoothed = np.convolve(xp, kernel, mode="valid")
    return smoothed.astype(np.float64)


def _smooth_offsets_two_stage(
    offsets: np.ndarray,
    *,
    step_m: float,
    window_m_1: float,
    window_m_2: float,
    max_delta_per_step_m: float,
) -> np.ndarray:
    x = np.asarray(offsets, dtype=np.float64).copy()
    if np.count_nonzero(np.isfinite(x)) == 0:
        return x
    x = _fill_nan_linear(x)
    x = _smooth_offsets(x, step_m=step_m, window_m=max(0.0, float(window_m_1)))
    x = _smooth_offsets(x, step_m=step_m, window_m=max(0.0, float(window_m_2)))
    lim = max(0.0, float(max_delta_per_step_m))
    if lim <= 0.0 or x.size <= 1:
        return x
    out = x.copy()
    for i in range(1, out.size):
        d = float(out[i] - out[i - 1])
        if d > lim:
            out[i] = out[i - 1] + lim
        elif d < -lim:
            out[i] = out[i - 1] - lim
    return out


def _select_stable_section_for_end(
    *,
    stations: np.ndarray,
    widths: np.ndarray,
    gore_overlap: np.ndarray,
    offsets: np.ndarray,
    length_m: float,
    from_src: bool,
    d_min: float,
    d_max: float,
    near_len: float,
    base_from: float,
    base_to: float,
    l_stable: float,
    ratio_tol: float,
    w_tol: float,
    r_gore: float,
    stable_fallback_m: float,
) -> _EndStableDecision:
    if stations.size == 0:
        return _EndStableDecision(
            is_gore_tip=False,
            is_expanded=False,
            width_near_m=None,
            width_base_m=None,
            gore_overlap_near=None,
            stable_s_m=None,
            anchor_station_m=None,
            anchor_offset_m=None,
            cut_mode="fallback_50m",
            used_fallback=True,
            short_base_proxy=False,
        )
    dist = np.asarray(stations, dtype=np.float64) if from_src else (float(length_m) - np.asarray(stations, dtype=np.float64))
    width_arr = np.asarray(widths, dtype=np.float64)
    gore_arr = np.asarray(gore_overlap, dtype=np.float64)
    offset_arr = np.asarray(offsets, dtype=np.float64)
    finite_mask = np.isfinite(width_arr) & np.isfinite(offset_arr) & np.isfinite(dist)
    if np.count_nonzero(finite_mask) == 0:
        return _EndStableDecision(
            is_gore_tip=False,
            is_expanded=False,
            width_near_m=None,
            width_base_m=None,
            gore_overlap_near=None,
            stable_s_m=None,
            anchor_station_m=None,
            anchor_offset_m=None,
            cut_mode="fallback_50m",
            used_fallback=True,
            short_base_proxy=False,
        )

    d_min_v = max(0.0, float(d_min))
    d_max_v = min(float(d_max), max(0.0, float(length_m) - 1e-3))
    if d_max_v < d_min_v:
        d_min_v = max(0.0, min(d_min_v, d_max_v))
    near_to = min(d_max_v, d_min_v + max(0.0, float(near_len)))

    near_mask = finite_mask & (dist >= d_min_v - 1e-9) & (dist <= near_to + 1e-9)
    width_near = _nanmedian(width_arr[near_mask]) if np.any(near_mask) else None
    gore_near = _nanmedian(gore_arr[near_mask]) if np.any(np.isfinite(gore_arr[near_mask])) else 0.0
    if gore_near is None:
        gore_near = 0.0

    base_from_v, base_to_v, short_proxy = _choose_base_window(
        length_m=float(length_m),
        d_min=float(d_min_v),
        near_len=float(near_len),
        base_from=float(base_from),
        base_to=float(base_to),
        d_max=float(d_max_v),
    )
    base_mask = finite_mask & (dist >= base_from_v - 1e-9) & (dist <= base_to_v + 1e-9)
    width_base = _nanmedian(width_arr[base_mask]) if np.any(base_mask) else None
    if width_base is None:
        width_base = _nanmedian(width_arr[finite_mask])

    is_gore_tip = float(gore_near) > float(r_gore)
    is_expanded = False
    if width_near is not None and width_base is not None:
        is_expanded = float(width_near) > float(width_base) * (1.0 + float(ratio_tol))

    cands = np.flatnonzero(finite_mask & (dist >= d_min_v - 1e-9) & (dist <= d_max_v + 1e-9))
    cands = cands[np.argsort(dist[cands])]
    chosen_idx: int | None = None
    stable_win = max(float(l_stable), 5.0)
    for idx in cands:
        g = gore_arr[idx]
        if np.isfinite(g) and float(g) > float(r_gore):
            continue
        d = float(dist[idx])
        seg_mask = finite_mask & (dist >= d - 1e-9) & (dist <= min(d_max_v, d + stable_win) + 1e-9)
        if np.count_nonzero(seg_mask) < 3:
            continue
        wv = width_arr[seg_mask]
        if wv.size < 3:
            continue
        span = float(np.max(wv) - np.min(wv))
        if width_base is not None and np.isfinite(width_base):
            span_lim = max(float(w_tol), float(width_base) * float(ratio_tol))
        else:
            span_lim = float(w_tol)
        if span > span_lim + 1e-9:
            continue
        if is_expanded and width_base is not None and np.isfinite(width_base):
            if float(width_arr[idx]) > float(width_base) * (1.0 + float(ratio_tol)):
                continue
        chosen_idx = int(idx)
        break

    used_fallback = False
    cut_mode = "stable_section" if (is_expanded or is_gore_tip) else "simple_near"
    if chosen_idx is None:
        used_fallback = True
        cut_mode = "fallback_50m"
        d_fb = min(max(0.0, float(stable_fallback_m)), d_max_v if d_max_v > 0 else float(length_m))
        if cands.size > 0:
            chosen_idx = int(cands[int(np.argmin(np.abs(dist[cands] - d_fb)))])
        else:
            any_idx = np.flatnonzero(np.isfinite(offset_arr) & np.isfinite(dist))
            if any_idx.size > 0:
                chosen_idx = int(any_idx[int(np.argmin(np.abs(dist[any_idx] - d_fb)))])
    if chosen_idx is None:
        return _EndStableDecision(
            is_gore_tip=bool(is_gore_tip),
            is_expanded=bool(is_expanded),
            width_near_m=width_near,
            width_base_m=width_base,
            gore_overlap_near=float(gore_near),
            stable_s_m=None,
            anchor_station_m=None,
            anchor_offset_m=None,
            cut_mode=cut_mode,
            used_fallback=used_fallback,
            short_base_proxy=short_proxy,
        )

    return _EndStableDecision(
        is_gore_tip=bool(is_gore_tip),
        is_expanded=bool(is_expanded),
        width_near_m=width_near,
        width_base_m=width_base,
        gore_overlap_near=float(gore_near),
        stable_s_m=float(dist[chosen_idx]),
        anchor_station_m=float(stations[chosen_idx]),
        anchor_offset_m=float(offset_arr[chosen_idx]),
        cut_mode=cut_mode,
        used_fallback=used_fallback,
        short_base_proxy=bool(short_proxy),
    )


def _choose_base_window(
    *,
    length_m: float,
    d_min: float,
    near_len: float,
    base_from: float,
    base_to: float,
    d_max: float,
) -> tuple[float, float, bool]:
    short_proxy = False
    d_cap = max(0.0, float(d_max))
    b0 = max(0.0, float(base_from))
    b1 = max(b0 + 1e-3, float(base_to))
    if b1 <= d_cap + 1e-6:
        return b0, b1, short_proxy
    if float(length_m) >= float(d_min + near_len + 20.0):
        b0 = min(0.5 * float(length_m), max(0.0, float(length_m) - 40.0))
        b1 = min(0.8 * float(length_m), max(0.0, float(length_m) - 10.0))
        b1 = min(b1, d_cap)
        if b1 > b0 + 1e-3:
            return b0, b1, short_proxy
    short_proxy = float(length_m) < 60.0
    b0 = max(float(d_min), max(0.0, d_cap - max(20.0, 0.3 * float(length_m))))
    b1 = d_cap
    if b1 <= b0 + 1e-3:
        b0 = max(0.0, min(float(d_min), d_cap))
        b1 = d_cap
    return b0, max(b0 + 1e-3, b1), short_proxy


def _apply_endpoint_stable_clamp(
    *,
    offsets: np.ndarray,
    stations: np.ndarray,
    src_decision: _EndStableDecision,
    dst_decision: _EndStableDecision,
    transition_m: float,
    length_m: float,
) -> np.ndarray:
    out = np.asarray(offsets, dtype=np.float64).copy()
    raw = np.asarray(offsets, dtype=np.float64)
    tr = max(0.0, float(transition_m))

    if src_decision.anchor_station_m is not None and src_decision.anchor_offset_m is not None:
        anchor_s = float(src_decision.anchor_station_m)
        target = float(src_decision.anchor_offset_m)
        if tr <= 1e-6:
            out[stations <= anchor_s + 1e-9] = target
        else:
            hard_until = max(0.0, anchor_s - tr)
            mask_hard = stations <= hard_until + 1e-9
            out[mask_hard] = target
            mask_tr = (stations > hard_until + 1e-9) & (stations <= anchor_s + 1e-9)
            idxs = np.flatnonzero(mask_tr)
            span = max(1e-6, anchor_s - hard_until)
            for i in idxs:
                w = float((stations[i] - hard_until) / span)
                out[i] = (1.0 - w) * target + w * float(raw[i])

    if dst_decision.anchor_station_m is not None and dst_decision.anchor_offset_m is not None:
        anchor_s = float(dst_decision.anchor_station_m)
        target = float(dst_decision.anchor_offset_m)
        if tr <= 1e-6:
            out[stations >= anchor_s - 1e-9] = target
        else:
            hard_from = min(float(length_m), anchor_s + tr)
            mask_hard = stations >= hard_from - 1e-9
            out[mask_hard] = target
            mask_tr = (stations >= anchor_s - 1e-9) & (stations < hard_from - 1e-9)
            idxs = np.flatnonzero(mask_tr)
            span = max(1e-6, hard_from - anchor_s)
            for i in idxs:
                w = float((stations[i] - anchor_s) / span)
                out[i] = (1.0 - w) * float(raw[i]) + w * target
    return out


def _fill_nan_linear(x: np.ndarray) -> np.ndarray:
    idx = np.arange(x.size)
    mask = np.isfinite(x)
    if np.count_nonzero(mask) == 0:
        return x
    if np.count_nonzero(mask) == 1:
        x[~mask] = x[mask][0]
        return x
    x[~mask] = np.interp(idx[~mask], idx[mask], x[mask])
    return x


def _apply_stable_zone(
    *,
    offsets: np.ndarray,
    stations: np.ndarray,
    length_m: float,
    apply_head: bool,
    apply_tail: bool,
    stable_offset_m: float,
    margin_m: float,
) -> tuple[float | None, float | None]:
    stable_src: float | None = None
    stable_dst: float | None = None

    if offsets.size < 3 or length_m <= 1.0:
        return stable_src, stable_dst

    s_stable = min(float(stable_offset_m), max(0.0, length_m - float(margin_m)))
    if s_stable <= 0.0:
        return stable_src, stable_dst

    if apply_head:
        idx = int(np.argmin(np.abs(stations - s_stable)))
        stable_src = float(offsets[idx])
        mask = stations <= s_stable
        offsets[mask] = stable_src

    if apply_tail:
        target = max(0.0, length_m - s_stable)
        idx = int(np.argmin(np.abs(stations - target)))
        stable_dst = float(offsets[idx])
        mask = stations >= target
        offsets[mask] = stable_dst

    return stable_src, stable_dst


def _offset_line(*, sample_points: np.ndarray, normals: np.ndarray, offsets: np.ndarray) -> LineString | None:
    if sample_points.shape[0] < 2:
        return None

    pts = sample_points + normals * offsets[:, None]
    coords = [(float(p[0]), float(p[1])) for p in pts]
    coords = _dedup_coords(coords)
    if len(coords) < 2:
        return None

    line = LineString(coords)
    if line.is_empty or line.length <= 0:
        return None
    return line


def _estimate_endpoint_center_offset(
    *,
    line: LineString,
    at_start: bool,
    points_xyz: np.ndarray,
    gore_zone_metric: BaseGeometry | None,
    along_half_window_m: float,
    across_half_window_m: float,
    corridor_half_width_m: float,
    min_points: int,
    width_pct_low: float,
    width_pct_high: float,
) -> float | None:
    if line.is_empty or line.length <= 0:
        return None
    if points_xyz.size == 0 or points_xyz.shape[0] < max(8, int(min_points)):
        return None
    coords = np.asarray(line.coords, dtype=np.float64)
    if coords.shape[0] < 2:
        return None

    if bool(at_start):
        c = coords[0]
        v = coords[min(1, coords.shape[0] - 1)] - coords[0]
    else:
        c = coords[-1]
        v = coords[-1] - coords[max(0, coords.shape[0] - 2)]
    t = np.asarray(_unit_vec(v), dtype=np.float64)
    no = np.asarray([-t[1], t[0]], dtype=np.float64)

    xy = np.asarray(points_xyz[:, :2], dtype=np.float64)
    grid = _build_grid_index(xy, cell_size=max(2.0, float(across_half_window_m) / 3.0))
    idx = _query_grid_indices(
        grid,
        center_xy=np.asarray([float(c[0]), float(c[1])], dtype=np.float64),
        half_dx=float(along_half_window_m + across_half_window_m),
        half_dy=float(along_half_window_m + across_half_window_m),
    )
    if idx.size == 0:
        return None
    rel = xy[idx, :] - c[None, :]
    along = rel @ t
    across = rel @ no
    gore_mask_local = np.zeros((idx.size,), dtype=bool)
    if gore_zone_metric is not None:
        try:
            gore_mask_local = np.asarray(
                contains_xy(gore_zone_metric, xy[idx, 0], xy[idx, 1]),
                dtype=bool,
            )
        except Exception:
            gore_mask_local = np.zeros((idx.size,), dtype=bool)
    keep = (
        (np.abs(along) <= float(along_half_window_m))
        & (np.abs(across) <= float(across_half_window_m))
        & (np.abs(across) <= max(0.1, float(corridor_half_width_m)))
        & (~gore_mask_local)
    )
    if np.count_nonzero(keep) < int(min_points):
        return None
    vals = across[keep]
    lo = float(np.percentile(vals, width_pct_low))
    hi = float(np.percentile(vals, width_pct_high))
    center = 0.5 * (lo + hi)
    return float(abs(center))


def _locate_on_line(line: LineString, xsec: LineString, *, tol: float) -> float | None:
    try:
        inter = line.intersection(xsec)
    except Exception:
        inter = None

    p_xy = point_xy_safe(inter, context="locate_on_line_intersection")
    if p_xy is not None:
        p = Point(float(p_xy[0]), float(p_xy[1]))
        try:
            return float(line.project(p))
        except Exception:
            pass

    try:
        lp, xp = nearest_points(line, xsec)
        lp_xy = point_xy_safe(lp, context="locate_on_line_lp")
        xp_xy = point_xy_safe(xp, context="locate_on_line_xp")
        if lp_xy is not None and xp_xy is not None:
            lp_p = Point(float(lp_xy[0]), float(lp_xy[1]))
            xp_p = Point(float(xp_xy[0]), float(xp_xy[1]))
            if lp_p.distance(xp_p) <= max(0.5, tol * 2.0):
                return float(line.project(lp_p))
    except Exception:
        return None

    return None


def _limit_vertices(line: LineString, max_vertices: int) -> LineString:
    coords = list(line.coords)
    n = len(coords)
    if n <= max_vertices:
        return line

    idx = np.linspace(0, n - 1, max_vertices).astype(np.int64)
    new_coords = [coords[int(i)] for i in idx]
    new_coords = _dedup_coords([(float(x), float(y)) for x, y in new_coords])
    if len(new_coords) < 2:
        return line
    return LineString(new_coords)


def _finite_xy(xy: np.ndarray) -> bool:
    return bool(np.isfinite(xy[0]) and np.isfinite(xy[1]))


def _nanmedian(x: np.ndarray) -> float | None:
    vals = x[np.isfinite(x)]
    if vals.size == 0:
        return None
    return float(np.median(vals))


def _nanpercentile(x: np.ndarray, q: float) -> float | None:
    vals = x[np.isfinite(x)]
    if vals.size == 0:
        return None
    return float(np.percentile(vals, q))


__all__ = [
    "CenterEstimate",
    "CrossingEvent",
    "CrossingExtractResult",
    "HARD_CENTER_EMPTY",
    "HARD_ENDPOINT",
    "HARD_BRIDGE_SEGMENT",
    "HARD_DIVSTRIP_INTERSECT",
    "HARD_MULTI_ROAD",
    "HARD_NON_RC",
    "PairSupport",
    "PairSupportBuildResult",
    "SOFT_LOW_SUPPORT",
    "SOFT_DIVSTRIP_MISSING",
    "SOFT_NO_LB",
    "SOFT_NO_LB_PATH",
    "SOFT_NO_STABLE_SECTION",
    "SOFT_OPEN_END",
    "SOFT_ROAD_OUTSIDE_TRAJ_SURFACE",
    "SOFT_SPARSE_POINTS",
    "SOFT_TRAJ_SURFACE_GAP",
    "SOFT_TRAJ_SURFACE_INSUFFICIENT",
    "SOFT_UNRESOLVED_NEIGHBOR",
    "SOFT_WIGGLY",
    "build_pair_supports",
    "clip_line_to_cross_sections",
    "compute_max_segment_m",
    "compute_max_turn_deg_per_10m",
    "estimate_centerline",
    "extract_crossing_events",
    "infer_node_types",
    "point_xy_safe",
]
