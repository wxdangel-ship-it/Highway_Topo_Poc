from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
from typing import Any

from shapely.geometry import LineString, Point

from .arc_selection_rules import (
    STRUCTURE_MERGE_MULTI_UPSTREAM,
    STRUCTURE_SAME_PAIR_MULTI_ARC,
    apply_arc_selection_rules,
    apply_diverge_merge_rule,
    apply_multi_arc_rule,
)
from .io import write_features_geojson, write_json, write_lines_geojson
from .models import Segment, coords_to_line, line_to_coords
from .step3_corridor_identity import build_patch_geometry_cache, build_prior_reference_index

_DEFAULT_TOPOLOGY_GAP_PAIR_IDS = (
    "55353246:37687913",
    "760239:6963539359479390368",
    "791871:37687913",
)

_TOPOLOGY_GAP_DECISIONS = {
    "gap_enter_mainflow",
    "gap_remain_blocked",
    "gap_ambiguous_need_more_constraints",
}


def _pipeline():
    from . import pipeline as pipeline_module

    return pipeline_module


def _parse_pair_ids(value: Any) -> set[str]:
    pipeline = _pipeline()
    return {
        pipeline._pair_id_text(int(src_nodeid), int(dst_nodeid))
        for src_nodeid, dst_nodeid in pipeline._parse_pair_scoped_allowlist(value)
    }


def _topology_gap_pair_ids(params: dict[str, Any]) -> set[str]:
    pair_ids = _parse_pair_ids(params.get("STEP3_TOPOLOGY_GAP_CONTROL_PAIR_IDS", ""))
    return pair_ids or set(_DEFAULT_TOPOLOGY_GAP_PAIR_IDS)


def classify_topology_gap_rows(
    rows: list[dict[str, Any]],
    *,
    params: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if not bool(int(params.get("STEP3_TOPOLOGY_GAP_CONTROL_ENABLE", 1))):
        return {}
    target_pair_ids = _topology_gap_pair_ids(params)
    coverage_threshold = float(params.get("STEP3_TOPOLOGY_GAP_MIN_SUPPORT_COVERAGE_RATIO", 0.35))
    strong_types = {"terminal_crossing_support", "stitched_arc_support"}
    target_rows = [
        dict(row)
        for row in rows
        if str(row.get("pair", "")) in target_pair_ids
        and str(row.get("blocked_diagnostic_reason", row.get("unbuilt_reason", ""))) == "topology_gap_unresolved"
        and bool(row.get("is_direct_legal", False))
        and bool(row.get("is_unique", False))
    ]
    if target_rows:
        target_rows = list(apply_arc_selection_rules(target_rows).get("rows", []))
    target_count_by_dst = Counter(int(row.get("dst", 0)) for row in target_rows)
    merge_rule_by_pair = apply_diverge_merge_rule(
        target_rows,
        min_support_coverage_ratio=float(coverage_threshold),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in target_rows:
        pair_id = str(row.get("pair", ""))
        traj_support_type = str(row.get("traj_support_type", "no_support"))
        prior_support_type = str(row.get("prior_support_type", "no_support"))
        coverage_ratio = float(row.get("traj_support_coverage_ratio", 0.0) or 0.0)
        support_count = int(len(row.get("traj_support_ids", [])))
        has_src_anchor = row.get("support_anchor_src_coords") is not None
        has_dst_anchor = row.get("support_anchor_dst_coords") is not None
        dst_nodeid = int(row.get("dst", 0))
        merge_rule = dict(merge_rule_by_pair.get(pair_id) or {})

        decision = "gap_remain_blocked"
        reason = "gap_support_insufficient"
        if traj_support_type == "no_support" and prior_support_type == "no_support":
            decision = "gap_remain_blocked"
            reason = "gap_support_insufficient"
        elif not has_src_anchor or not has_dst_anchor:
            decision = "gap_ambiguous_need_more_constraints"
            reason = "gap_anchor_unreliable"
        elif bool(merge_rule.get("allow_multi_output", False)):
            decision = "gap_enter_mainflow"
            reason = "gap_should_enter_mainflow"
        elif str(row.get("arc_structure_type", "")) == STRUCTURE_MERGE_MULTI_UPSTREAM:
            decision = "gap_ambiguous_need_more_constraints"
            reason = (
                "gap_merge_support_not_independent"
                if str(merge_rule.get("rule_reason", "")) == "merge_multi_upstream_support_not_independent"
                else "gap_merge_rule_not_satisfied"
            )
        elif int(target_count_by_dst.get(dst_nodeid, 0)) >= 2:
            decision = "gap_ambiguous_need_more_constraints"
            reason = "gap_competing_arc_conflict"
        elif traj_support_type in strong_types and support_count >= 1 and coverage_ratio >= coverage_threshold:
            decision = "gap_enter_mainflow"
            reason = "gap_should_enter_mainflow"
        elif traj_support_type == "partial_arc_support" and coverage_ratio >= max(coverage_threshold, 0.5):
            decision = "gap_enter_mainflow"
            reason = "gap_should_enter_mainflow"
        elif coverage_ratio > 0.0:
            decision = "gap_ambiguous_need_more_constraints"
            reason = "gap_support_insufficient"
        elif prior_support_type == "prior_fallback_support":
            decision = "gap_ambiguous_need_more_constraints"
            reason = "gap_slot_ambiguous"

        out[pair_id] = {
            "pair": str(pair_id),
            "decision": str(decision),
            "reason": str(reason),
            "controlled_entry_allowed": bool(decision == "gap_enter_mainflow"),
            "target_count_same_dst": int(target_count_by_dst.get(dst_nodeid, 0)),
            "traj_support_type": str(traj_support_type),
            "prior_support_type": str(prior_support_type),
            "traj_support_coverage_ratio": float(coverage_ratio),
            "arc_structure_type": str(row.get("arc_structure_type", "")),
            "arc_selection_rule": str(row.get("arc_selection_rule", "")),
            "arc_selection_allow_multi_output": bool(
                merge_rule.get("allow_multi_output", row.get("arc_selection_allow_multi_output", False))
            ),
            "arc_selection_shared_downstream_nodes": list(
                merge_rule.get(
                    "shared_downstream_nodes",
                    row.get("arc_selection_shared_downstream_nodes", []),
                )
            ),
            "arc_selection_shared_downstream_edge_ids": list(
                merge_rule.get(
                    "shared_downstream_edge_ids",
                    row.get("arc_selection_shared_downstream_edge_ids", []),
                )
            ),
            "arc_selection_shared_downstream_signal": list(
                merge_rule.get(
                    "shared_downstream_signal",
                    row.get("arc_selection_shared_downstream_signal", []),
                )
            ),
            "arc_selection_peer_pairs": list(
                merge_rule.get("peer_pairs", row.get("arc_selection_peer_pairs", []))
            ),
            "arc_selection_rule_reason": str(
                merge_rule.get("rule_reason", row.get("arc_selection_rule_reason", ""))
            ),
        }
    return out


def _arc_line(row: dict[str, Any]) -> LineString | None:
    coords = tuple(
        (float(item[0]), float(item[1]))
        for item in row.get("line_coords", [])
        if isinstance(item, (list, tuple)) and len(item) >= 2
    )
    if len(coords) < 2:
        return None
    line = coords_to_line(coords)
    if line.is_empty or line.length <= 1e-6:
        return None
    return line


def _line_overlap_ratio(line: LineString | None, zone: Any | None) -> float:
    if line is None or zone is None or getattr(zone, "is_empty", True):
        return 0.0
    length = float(getattr(line, "length", 0.0))
    if length <= 1e-6:
        return 0.0
    try:
        overlap = line.intersection(zone)
    except Exception:
        return 0.0
    return float(max(0.0, min(1.0, float(getattr(overlap, "length", 0.0)) / max(length, 1e-6))))


def _trajectory_points(traj: Any) -> list[tuple[float, float]]:
    xyz = getattr(traj, "xyz_metric", None)
    if xyz is None:
        return []
    return [(float(row[0]), float(row[1])) for row in xyz if row is not None and len(row) >= 2]


def _bbox_intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (
        float(a[2]) < float(b[0])
        or float(b[2]) < float(a[0])
        or float(a[3]) < float(b[1])
        or float(b[3]) < float(a[1])
    )


def _expand_bounds(bounds: tuple[float, float, float, float], buffer_m: float) -> tuple[float, float, float, float]:
    return (
        float(bounds[0]) - float(buffer_m),
        float(bounds[1]) - float(buffer_m),
        float(bounds[2]) + float(buffer_m),
        float(bounds[3]) + float(buffer_m),
    )


def _group_projected_spans(
    *,
    projected_rows: list[tuple[int, float]],
    max_seq_gap: int,
    max_proj_gap_m: float,
    arc_length_m: float,
    min_span_ratio: float,
    min_span_length_m: float,
) -> list[dict[str, Any]]:
    if len(projected_rows) < 2 or arc_length_m <= 1e-6:
        return []
    spans: list[list[tuple[int, float]]] = [[projected_rows[0]]]
    for idx, proj_s in projected_rows[1:]:
        prev_idx, prev_proj = spans[-1][-1]
        if (int(idx) - int(prev_idx)) <= int(max_seq_gap) and abs(float(proj_s) - float(prev_proj)) <= float(max_proj_gap_m):
            spans[-1].append((int(idx), float(proj_s)))
            continue
        spans.append([(int(idx), float(proj_s))])
    out: list[dict[str, Any]] = []
    for rows in spans:
        if len(rows) < 2:
            continue
        start_s = float(min(item[1] for item in rows))
        end_s = float(max(item[1] for item in rows))
        span_len = max(0.0, float(end_s - start_s))
        span_ratio = float(span_len / max(arc_length_m, 1e-6))
        if span_len < float(min_span_length_m) and span_ratio < float(min_span_ratio):
            continue
        out.append(
            {
                "start_s": float(start_s),
                "end_s": float(end_s),
                "span_length_m": float(span_len),
                "coverage_ratio": float(span_ratio),
                "source_span_start_idx": int(min(item[0] for item in rows)),
                "source_span_end_idx": int(max(item[0] for item in rows)),
            }
        )
    return out


def _ordered_terminal_hit(hit_positions_by_node: dict[int, tuple[int, ...]], src_nodeid: int, dst_nodeid: int) -> bool:
    src_positions = hit_positions_by_node.get(int(src_nodeid), tuple())
    dst_positions = hit_positions_by_node.get(int(dst_nodeid), tuple())
    if not src_positions or not dst_positions:
        return False
    dst_idx = 0
    for src_pos in src_positions:
        while dst_idx < len(dst_positions) and int(dst_positions[dst_idx]) <= int(src_pos):
            dst_idx += 1
        if dst_idx < len(dst_positions):
            return True
    return False


def _ordered_terminal_event_pair(events: tuple[dict[str, Any], ...], src_nodeid: int, dst_nodeid: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
    src_events = [dict(item) for item in events if int(item.get("nodeid", 0)) == int(src_nodeid)]
    dst_events = [dict(item) for item in events if int(item.get("nodeid", 0)) == int(dst_nodeid)]
    if not src_events or not dst_events:
        return None
    dst_idx = 0
    for src_event in src_events:
        src_pos = int(src_event.get("index", -1))
        while dst_idx < len(dst_events) and int(dst_events[dst_idx].get("index", -1)) <= int(src_pos):
            dst_idx += 1
        if dst_idx < len(dst_events):
            return dict(src_event), dict(dst_events[dst_idx])
    return None


def _subline_from_coords(coords: tuple[tuple[float, float], ...], start_idx: int, end_idx: int) -> LineString | None:
    if not coords:
        return None
    lo = max(0, min(int(start_idx), int(end_idx)))
    hi = min(len(coords) - 1, max(int(start_idx), int(end_idx)))
    if hi - lo < 1:
        return None
    line = LineString(list(coords[lo : hi + 1]))
    if line.is_empty or line.length <= 1e-6:
        return None
    return line


def _coords_list(line: LineString | None) -> list[list[float]]:
    if line is None or line.is_empty:
        return []
    return [[float(x), float(y)] for x, y, *_ in line.coords]


def _line_surface_metrics(
    line: LineString | None,
    *,
    drivezone: Any | None,
    drivable_surface: Any | None,
    divstrip_buffer: Any | None,
) -> dict[str, Any]:
    if line is None or line.is_empty or line.length <= 1e-6:
        return {
            "on_drivable_surface_ratio": 0.0,
            "drivezone_overlap_ratio": 0.0,
            "divstrip_overlap_ratio": 0.0,
        }
    return {
        "on_drivable_surface_ratio": float(_line_overlap_ratio(line, drivable_surface)),
        "drivezone_overlap_ratio": float(_line_overlap_ratio(line, drivezone)),
        "divstrip_overlap_ratio": float(_line_overlap_ratio(line, divstrip_buffer)),
    }


def _support_surface_consistency(
    metrics: dict[str, Any],
    *,
    params: dict[str, Any],
) -> tuple[bool, str]:
    on_drivable_surface_ratio = float(metrics.get("on_drivable_surface_ratio", 0.0) or 0.0)
    drivezone_overlap_ratio = float(metrics.get("drivezone_overlap_ratio", 0.0) or 0.0)
    divstrip_overlap_ratio = float(metrics.get("divstrip_overlap_ratio", 0.0) or 0.0)
    if on_drivable_surface_ratio < float(params.get("ARC_SUPPORT_MIN_DRIVABLE_RATIO", 0.70)):
        return False, "low_on_drivable_surface_ratio"
    if drivezone_overlap_ratio < float(params.get("ARC_SUPPORT_MIN_DRIVEZONE_RATIO", 0.85)):
        return False, "low_drivezone_overlap_ratio"
    if divstrip_overlap_ratio > float(params.get("ARC_SUPPORT_MAX_DIVSTRIP_RATIO", 0.05)):
        return False, "high_divstrip_overlap_ratio"
    return True, ""


def _support_segment_payload(
    *,
    traj_id: str,
    topology_arc_id: str,
    support_type: str,
    support_mode: str,
    line: LineString | None,
    segment_order: int,
    is_stitched: bool,
    support_score: float,
    source_span_start_idx: int,
    source_span_end_idx: int,
    drivezone: Any | None,
    drivable_surface: Any | None,
    divstrip_buffer: Any | None,
    params: dict[str, Any],
) -> dict[str, Any] | None:
    if line is None or line.is_empty or line.length <= 1e-6:
        return None
    surface_metrics = _line_surface_metrics(
        line,
        drivezone=drivezone,
        drivable_surface=drivable_surface,
        divstrip_buffer=divstrip_buffer,
    )
    surface_consistent, surface_reject_reason = _support_surface_consistency(surface_metrics, params=params)
    return {
        "traj_id": str(traj_id),
        "topology_arc_id": str(topology_arc_id),
        "support_type": str(support_type),
        "support_mode": str(support_mode),
        "segment_order": int(segment_order),
        "is_stitched": bool(is_stitched),
        "support_score": float(support_score),
        "support_length_m": float(line.length),
        "source_span_start_idx": int(source_span_start_idx),
        "source_span_end_idx": int(source_span_end_idx),
        "line_coords": _coords_list(line),
        "start_anchor_coords": [float(line.coords[0][0]), float(line.coords[0][1])],
        "end_anchor_coords": [float(line.coords[-1][0]), float(line.coords[-1][1])],
        "on_drivable_surface_ratio": float(surface_metrics["on_drivable_surface_ratio"]),
        "drivezone_overlap_ratio": float(surface_metrics["drivezone_overlap_ratio"]),
        "divstrip_overlap_ratio": float(surface_metrics["divstrip_overlap_ratio"]),
        "surface_consistent": bool(surface_consistent),
        "surface_reject_reason": str(surface_reject_reason),
        "accepted_for_production": False,
    }


def _support_anchors_from_segments(segments: list[dict[str, Any]]) -> tuple[list[float] | None, list[float] | None]:
    if not segments:
        return None, None
    ordered = sorted(
        [dict(item) for item in segments if list(item.get("line_coords", []))],
        key=lambda item: (
            int(item.get("segment_order", 0)),
            int(item.get("source_span_start_idx", 0)),
            int(item.get("source_span_end_idx", 0)),
        ),
    )
    if not ordered:
        return None, None
    start_coords = list(ordered[0].get("start_anchor_coords", [])) or list((ordered[0].get("line_coords") or [[]])[0])
    end_coords = list(ordered[-1].get("end_anchor_coords", [])) or list((ordered[-1].get("line_coords") or [[]])[-1])
    if len(start_coords) < 2 or len(end_coords) < 2:
        return None, None
    return [float(start_coords[0]), float(start_coords[1])], [float(end_coords[0]), float(end_coords[1])]


def _best_support_reference_coords(segments: list[dict[str, Any]]) -> list[list[float]]:
    if not segments:
        return []
    best = sorted(
        [dict(item) for item in segments if list(item.get("line_coords", []))],
        key=lambda item: (
            -float(item.get("support_score", 0.0)),
            -float(item.get("support_length_m", 0.0)),
            str(item.get("traj_id", "")),
            int(item.get("segment_order", 0)),
        ),
    )
    return list(best[0].get("line_coords", [])) if best else []


def _merge_support_spans(
    span_rows: list[dict[str, Any]],
    *,
    max_proj_gap_m: float,
) -> list[list[float]]:
    ordered = sorted(
        [dict(item) for item in span_rows],
        key=lambda item: (float(item.get("start_s", 0.0)), float(item.get("end_s", 0.0))),
    )
    merged: list[list[float]] = []
    for span in ordered:
        start_s = float(span.get("start_s", 0.0))
        end_s = float(span.get("end_s", 0.0))
        if not merged or start_s > float(merged[-1][1]) + float(max_proj_gap_m):
            merged.append([start_s, end_s])
            continue
        merged[-1][1] = max(float(merged[-1][1]), end_s)
    return merged


def _coverage_ratio_from_spans(
    span_rows: list[dict[str, Any]],
    *,
    arc_length_m: float,
    max_proj_gap_m: float,
) -> float:
    if not span_rows or arc_length_m <= 1e-6:
        return 0.0
    merged = _merge_support_spans(span_rows, max_proj_gap_m=max_proj_gap_m)
    covered_length = float(sum(max(0.0, item[1] - item[0]) for item in merged))
    return float(covered_length / max(float(arc_length_m), 1e-6))


def _mark_support_segments_selected(segments: list[dict[str, Any]]) -> None:
    for item in segments:
        item["accepted_for_production"] = True


def _build_trajectory_attach_cache(
    *,
    inputs: Any,
    frame: Any,
    params: dict[str, Any],
    divstrip_buffer: Any | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pipeline = _pipeline()
    hit_buffer = float(params["TRAJ_XSEC_HIT_BUFFER_M"])
    started = perf_counter()
    rows: list[dict[str, Any]] = []
    total_points = 0
    for traj in getattr(inputs, "trajectories", []) or []:
        coords = _trajectory_points(traj)
        points = tuple(Point(float(x), float(y)) for x, y in coords)
        line = LineString(coords) if len(coords) >= 2 else None
        bbox = tuple(line.bounds) if line is not None and not line.is_empty else (0.0, 0.0, 0.0, 0.0)
        events = pipeline._trajectory_events(
            traj,
            frame,
            hit_buffer,
            drivezone=inputs.drivezone_zone_metric,
            divstrip_buffer=divstrip_buffer,
        )
        hit_positions_by_node: dict[int, list[int]] = defaultdict(list)
        for idx, event in enumerate(events):
            hit_positions_by_node[int(event.get("nodeid", 0))].append(int(idx))
        rows.append(
            {
                "traj_id": str(getattr(traj, "traj_id", "")),
                "coords": tuple((float(x), float(y)) for x, y in coords),
                "points": points,
                "line": line,
                "bbox": bbox,
                "events": tuple(dict(item) for item in events),
                "hit_positions_by_node": {int(nodeid): tuple(vals) for nodeid, vals in hit_positions_by_node.items()},
            }
        )
        total_points += int(len(points))
    return rows, {
        "trajectory_cache_time_ms": float((perf_counter() - started) * 1000.0),
        "trajectory_cache_traj_count": int(len(rows)),
        "trajectory_cache_point_count": int(total_points),
    }


def _prior_support_type(
    *,
    src_nodeid: int,
    dst_nodeid: int,
    prior_roads: list[Any],
    prior_index: dict[tuple[int, int], list[Any]] | None = None,
) -> tuple[str, bool]:
    if prior_index is not None:
        if prior_index.get((int(src_nodeid), int(dst_nodeid))) or prior_index.get((int(dst_nodeid), int(src_nodeid))):
            return "prior_fallback_support", True
        return "no_support", False
    for road in prior_roads:
        snodeid = int(getattr(road, "snodeid", 0))
        enodeid = int(getattr(road, "enodeid", 0))
        if (int(snodeid), int(enodeid)) == (int(src_nodeid), int(dst_nodeid)):
            return "prior_fallback_support", True
        if (int(snodeid), int(enodeid)) == (int(dst_nodeid), int(src_nodeid)):
            return "prior_fallback_support", True
    return "no_support", False


def _prefilter_traj_rows(
    *,
    arc_line: LineString,
    traj_rows: list[dict[str, Any]],
    buffer_m: float,
) -> list[dict[str, Any]]:
    if arc_line.is_empty or arc_line.length <= 1e-6:
        return []
    expanded_bounds = _expand_bounds(tuple(arc_line.bounds), float(buffer_m))
    candidate_rows: list[dict[str, Any]] = []
    for traj_row in traj_rows:
        traj_line = traj_row.get("line")
        if traj_line is None or traj_line.is_empty:
            continue
        if not _bbox_intersects(expanded_bounds, tuple(traj_row.get("bbox", (0.0, 0.0, 0.0, 0.0)))):
            continue
        if float(traj_line.distance(arc_line)) > float(buffer_m):
            continue
        candidate_rows.append(traj_row)
    return candidate_rows


def _scan_arc_traj_support(
    *,
    arc_line: LineString,
    arc_length_m: float,
    traj_row: dict[str, Any],
    src_nodeid: int,
    dst_nodeid: int,
    buffer_m: float,
    min_span_ratio: float,
    min_span_length_m: float,
    max_seq_gap: int,
    max_proj_gap_m: float,
) -> dict[str, Any]:
    projected_rows: list[tuple[int, float]] = []
    for idx, point in enumerate(traj_row.get("points", tuple())):
        if float(arc_line.distance(point)) > float(buffer_m):
            continue
        projected_rows.append((int(idx), float(arc_line.project(point))))
    return {
        "traj_id": str(traj_row.get("traj_id", "")),
        "terminal_supported": bool(_ordered_terminal_hit(traj_row.get("hit_positions_by_node", {}), int(src_nodeid), int(dst_nodeid))),
        "spans": _group_projected_spans(
            projected_rows=projected_rows,
            max_seq_gap=max_seq_gap,
            max_proj_gap_m=max_proj_gap_m,
            arc_length_m=float(arc_length_m),
            min_span_ratio=min_span_ratio,
            min_span_length_m=min_span_length_m,
        ),
    }


def _support_type_for_arc(
    *,
    row: dict[str, Any],
    arc_line: LineString | None,
    prior_roads: list[Any],
    prior_index: dict[tuple[int, int], list[Any]] | None,
    candidate_traj_rows: list[dict[str, Any]],
    drivezone: Any | None,
    drivable_surface: Any | None,
    divstrip_buffer: Any | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    buffer_m = float(params.get("ARC_EVIDENCE_BUFFER_M", 8.0))
    min_span_ratio = float(params.get("ARC_PARTIAL_MIN_COVERAGE_RATIO", 0.18))
    min_span_length_m = float(params.get("ARC_PARTIAL_MIN_LENGTH_M", 12.0))
    max_seq_gap = int(params.get("ARC_STITCH_MAX_SEQ_GAP", 12))
    max_proj_gap_m = float(params.get("ARC_STITCH_MAX_PROJ_GAP_M", 25.0))
    stitched_min_ratio = float(params.get("ARC_STITCH_MIN_COVERAGE_RATIO", 0.72))
    endpoint_margin_ratio = float(params.get("ARC_STITCH_ENDPOINT_MARGIN_RATIO", 0.18))

    prior_support_type, prior_available = _prior_support_type(
        src_nodeid=int(row["src"]),
        dst_nodeid=int(row["dst"]),
        prior_roads=prior_roads,
        prior_index=prior_index,
    )
    if arc_line is None:
        return {
            "traj_support_type": "no_support",
            "traj_support_ids": [],
            "traj_support_span_count": 0,
            "traj_support_coverage_ratio": 0.0,
            "traj_support_spans": [],
            "traj_support_segments": [],
            "support_reference_coords": [],
            "support_anchor_src_coords": None,
            "support_anchor_dst_coords": None,
            "support_generation_mode": "none",
            "support_generation_reason": "arc_line_missing",
            "selected_support_traj_id": "",
            "single_traj_support_segments": [],
            "stitched_traj_support_segments": [],
            "single_traj_candidate_count": int(len(candidate_traj_rows)),
            "single_traj_surface_consistent_count": 0,
            "prior_support_type": prior_support_type,
            "prior_support_available": bool(prior_available),
        }

    single_traj_support_segments: list[dict[str, Any]] = []
    single_traj_evals: list[dict[str, Any]] = []
    all_partial_span_rows: list[dict[str, Any]] = []
    for traj_row in candidate_traj_rows:
        support = _scan_arc_traj_support(
            arc_line=arc_line,
            arc_length_m=float(arc_line.length),
            traj_row=traj_row,
            src_nodeid=int(row["src"]),
            dst_nodeid=int(row["dst"]),
            buffer_m=buffer_m,
            min_span_ratio=min_span_ratio,
            min_span_length_m=min_span_length_m,
            max_seq_gap=max_seq_gap,
            max_proj_gap_m=max_proj_gap_m,
        )
        traj_id = str(support["traj_id"])
        traj_all_segments: list[dict[str, Any]] = []
        traj_accepted_span_rows: list[dict[str, Any]] = []
        traj_production_segments: list[dict[str, Any]] = []
        terminal_payload: dict[str, Any] | None = None
        if bool(support["terminal_supported"]):
            terminal_event_pair = _ordered_terminal_event_pair(tuple(traj_row.get("events", tuple())), int(row["src"]), int(row["dst"]))
            if terminal_event_pair is not None:
                start_event, end_event = terminal_event_pair
                terminal_line = _subline_from_coords(
                    tuple(traj_row.get("coords", tuple())),
                    int(start_event.get("index", 0)),
                    int(end_event.get("index", 0)),
                )
                terminal_payload = _support_segment_payload(
                    traj_id=traj_id,
                    topology_arc_id=str(row.get("topology_arc_id", "")),
                    support_type="terminal_crossing_support",
                    support_mode="single",
                    line=terminal_line,
                    segment_order=int(len(traj_all_segments)),
                    is_stitched=False,
                    support_score=1.0,
                    source_span_start_idx=int(start_event.get("index", 0)),
                    source_span_end_idx=int(end_event.get("index", 0)),
                    drivezone=drivezone,
                    drivable_surface=drivable_surface,
                    divstrip_buffer=divstrip_buffer,
                    params=params,
                )
                if terminal_payload is not None:
                    traj_all_segments.append(terminal_payload)
        spans = list(support["spans"])
        for span_order, span in enumerate(spans):
            span_row = {**dict(span), "traj_id": traj_id}
            all_partial_span_rows.append(span_row)
            span_line = _subline_from_coords(
                tuple(traj_row.get("coords", tuple())),
                int(span.get("source_span_start_idx", 0)),
                int(span.get("source_span_end_idx", 0)),
            )
            span_payload = _support_segment_payload(
                traj_id=traj_id,
                topology_arc_id=str(row.get("topology_arc_id", "")),
                support_type="partial_arc_support",
                support_mode="single",
                line=span_line,
                segment_order=int(span_order),
                is_stitched=False,
                support_score=float(span.get("coverage_ratio", 0.0)),
                source_span_start_idx=int(span.get("source_span_start_idx", 0)),
                source_span_end_idx=int(span.get("source_span_end_idx", 0)),
                drivezone=drivezone,
                drivable_surface=drivable_surface,
                divstrip_buffer=divstrip_buffer,
                params=params,
            )
            if span_payload is not None:
                traj_all_segments.append(span_payload)
                if bool(span_payload.get("surface_consistent", False)):
                    traj_accepted_span_rows.append(span_row)
        single_traj_support_segments.extend(traj_all_segments)
        surface_consistent_segments = [
            item for item in traj_all_segments if bool(item.get("surface_consistent", False))
        ]
        if terminal_payload is not None and bool(terminal_payload.get("surface_consistent", False)):
            traj_production_type = "terminal_crossing_support"
            traj_production_segments = [terminal_payload]
            coverage_ratio = 1.0 if arc_line.length > 1e-6 else 0.0
            traj_support_spans = [dict(item) for item in traj_accepted_span_rows]
        elif traj_accepted_span_rows:
            traj_production_type = "partial_arc_support"
            traj_production_segments = [
                item
                for item in traj_all_segments
                if str(item.get("support_type", "")) == "partial_arc_support"
                and bool(item.get("surface_consistent", False))
            ]
            coverage_ratio = _coverage_ratio_from_spans(
                traj_accepted_span_rows,
                arc_length_m=float(arc_line.length),
                max_proj_gap_m=float(max_proj_gap_m),
            )
            traj_support_spans = [dict(item) for item in traj_accepted_span_rows]
        else:
            traj_production_type = "no_support"
            coverage_ratio = 0.0
            traj_support_spans = []
        support_anchor_src_coords, support_anchor_dst_coords = _support_anchors_from_segments(traj_production_segments)
        support_reference_coords = _best_support_reference_coords(traj_production_segments)
        best_line_distance_m = min(
            (
                float(
                    coords_to_line(
                        tuple(
                            (float(coord[0]), float(coord[1]))
                            for coord in item.get("line_coords", [])
                            if isinstance(coord, (list, tuple)) and len(coord) >= 2
                        )
                    ).hausdorff_distance(arc_line)
                )
                for item in traj_production_segments
                if len(item.get("line_coords", [])) >= 2
            ),
            default=float("inf"),
        )
        single_traj_evals.append(
            {
                "traj_id": str(traj_id),
                "traj_support_type": str(traj_production_type),
                "traj_support_ids": [] if str(traj_production_type) == "no_support" else [str(traj_id)],
                "traj_support_span_count": int(
                    0
                    if str(traj_production_type) == "no_support"
                    else max(1, len(traj_production_segments))
                ),
                "traj_support_coverage_ratio": float(coverage_ratio),
                "traj_support_spans": traj_support_spans,
                "traj_support_segments": traj_production_segments,
                "support_reference_coords": support_reference_coords,
                "support_anchor_src_coords": support_anchor_src_coords,
                "support_anchor_dst_coords": support_anchor_dst_coords,
                "all_segments": traj_all_segments,
                "surface_consistent_segment_count": int(len(surface_consistent_segments)),
                "best_line_distance_m": float(best_line_distance_m),
            }
        )

    stitched_traj_support_segments = [
        {
            **dict(item),
            "support_type": "stitched_arc_support",
            "support_mode": "stitched",
            "is_stitched": True,
            "accepted_for_production": False,
        }
        for item in single_traj_support_segments
        if str(item.get("support_type", "")) == "partial_arc_support"
    ]
    qualified_single_evals = [
        dict(item)
        for item in single_traj_evals
        if str(item.get("traj_support_type", "")) != "no_support"
        and int(item.get("surface_consistent_segment_count", 0)) >= 1
    ]
    if qualified_single_evals:
        best_single = sorted(
            qualified_single_evals,
            key=lambda item: (
                0 if str(item.get("traj_support_type", "")) == "terminal_crossing_support" else 1,
                float(item.get("best_line_distance_m", float("inf"))),
                -float(item.get("traj_support_coverage_ratio", 0.0) or 0.0),
                -int(item.get("surface_consistent_segment_count", 0)),
                str(item.get("traj_id", "")),
            ),
        )[0]
        _mark_support_segments_selected(list(best_single.get("traj_support_segments", [])))
        return {
            "traj_support_type": str(best_single.get("traj_support_type", "no_support")),
            "traj_support_ids": [str(v) for v in best_single.get("traj_support_ids", [])],
            "traj_support_span_count": int(best_single.get("traj_support_span_count", 0)),
            "traj_support_coverage_ratio": float(best_single.get("traj_support_coverage_ratio", 0.0) or 0.0),
            "traj_support_spans": list(best_single.get("traj_support_spans", [])),
            "traj_support_segments": list(best_single.get("traj_support_segments", [])),
            "support_reference_coords": list(best_single.get("support_reference_coords", [])),
            "support_anchor_src_coords": best_single.get("support_anchor_src_coords"),
            "support_anchor_dst_coords": best_single.get("support_anchor_dst_coords"),
            "support_generation_mode": "single",
            "support_generation_reason": "single_traj_surface_consistent_preferred",
            "selected_support_traj_id": str(best_single.get("traj_id", "")),
            "single_traj_support_segments": single_traj_support_segments,
            "stitched_traj_support_segments": stitched_traj_support_segments,
            "single_traj_candidate_count": int(len(candidate_traj_rows)),
            "single_traj_surface_consistent_count": int(len(qualified_single_evals)),
            "prior_support_type": prior_support_type,
            "prior_support_available": bool(prior_available),
        }

    stitched_coverage_ratio = _coverage_ratio_from_spans(
        all_partial_span_rows,
        arc_length_m=float(arc_line.length),
        max_proj_gap_m=float(max_proj_gap_m),
    )
    merged = _merge_support_spans(all_partial_span_rows, max_proj_gap_m=float(max_proj_gap_m))
    endpoint_margin = float(arc_line.length) * float(endpoint_margin_ratio)
    covers_start = bool(merged and float(merged[0][0]) <= endpoint_margin)
    covers_end = bool(merged and float(merged[-1][1]) >= float(arc_line.length) - endpoint_margin)
    stitched_ready = bool(
        len(stitched_traj_support_segments) >= 2
        and covers_start
        and covers_end
        and stitched_coverage_ratio >= stitched_min_ratio
    )
    stitched_surface_consistent = bool(
        stitched_ready
        and stitched_traj_support_segments
        and all(bool(item.get("surface_consistent", False)) for item in stitched_traj_support_segments)
    )
    if stitched_surface_consistent:
        _mark_support_segments_selected(stitched_traj_support_segments)
        support_anchor_src_coords, support_anchor_dst_coords = _support_anchors_from_segments(stitched_traj_support_segments)
        support_reference_coords = _best_support_reference_coords(stitched_traj_support_segments)
        return {
            "traj_support_type": "stitched_arc_support",
            "traj_support_ids": sorted({str(item.get("traj_id", "")) for item in stitched_traj_support_segments if str(item.get("traj_id", ""))}),
            "traj_support_span_count": int(len(stitched_traj_support_segments)),
            "traj_support_coverage_ratio": float(stitched_coverage_ratio),
            "traj_support_spans": [dict(item) for item in all_partial_span_rows],
            "traj_support_segments": stitched_traj_support_segments,
            "support_reference_coords": support_reference_coords,
            "support_anchor_src_coords": support_anchor_src_coords,
            "support_anchor_dst_coords": support_anchor_dst_coords,
            "support_generation_mode": "stitched",
            "support_generation_reason": "zero_surface_consistent_single_traj_support",
            "selected_support_traj_id": "",
            "single_traj_support_segments": single_traj_support_segments,
            "stitched_traj_support_segments": stitched_traj_support_segments,
            "single_traj_candidate_count": int(len(candidate_traj_rows)),
            "single_traj_surface_consistent_count": 0,
            "prior_support_type": prior_support_type,
            "prior_support_available": bool(prior_available),
        }

    return {
        "traj_support_type": "no_support",
        "traj_support_ids": [],
        "traj_support_span_count": 0,
        "traj_support_coverage_ratio": 0.0,
        "traj_support_spans": [],
        "traj_support_segments": [],
        "support_reference_coords": [],
        "support_anchor_src_coords": None,
        "support_anchor_dst_coords": None,
        "support_generation_mode": "none",
        "support_generation_reason": (
            "stitched_support_surface_inconsistent"
            if stitched_ready and stitched_traj_support_segments
            else "no_surface_consistent_single_or_stitched_support"
        ),
        "selected_support_traj_id": "",
        "single_traj_support_segments": single_traj_support_segments,
        "stitched_traj_support_segments": stitched_traj_support_segments,
        "single_traj_candidate_count": int(len(candidate_traj_rows)),
        "single_traj_surface_consistent_count": 0,
        "prior_support_type": prior_support_type,
        "prior_support_available": bool(prior_available),
    }


def _support_source_modes(traj_support_type: str, prior_support_type: str) -> tuple[str, ...]:
    if str(traj_support_type) != "no_support" and str(prior_support_type) == "prior_fallback_support":
        return ("prior", "traj")
    if str(traj_support_type) != "no_support":
        return ("traj",)
    if str(prior_support_type) == "prior_fallback_support":
        return ("prior",)
    return ("arc",)


def _support_formation_reason(traj_support_type: str, prior_support_type: str, selected_segment_id: str) -> str:
    if str(selected_segment_id):
        return "arc_first_selected_segment"
    if str(traj_support_type) == "terminal_crossing_support":
        return "arc_first_terminal_support"
    if str(traj_support_type) == "partial_arc_support":
        return "arc_first_partial_support"
    if str(traj_support_type) == "stitched_arc_support":
        return "arc_first_stitched_support"
    if str(prior_support_type) == "prior_fallback_support":
        return "arc_first_prior_fallback"
    return "arc_first_no_support"


def _materialize_working_segment(
    *,
    row: dict[str, Any],
    selected_segment: Segment | None,
    inputs: Any,
    params: dict[str, Any],
    divstrip_buffer: Any | None,
) -> Segment:
    pipeline = _pipeline()
    if selected_segment is not None:
        support_ids = tuple(sorted(set([*selected_segment.support_traj_ids, *[str(v) for v in row.get("traj_support_ids", [])]])))
        return Segment(
            segment_id=str(selected_segment.segment_id),
            src_nodeid=int(selected_segment.src_nodeid),
            dst_nodeid=int(selected_segment.dst_nodeid),
            direction=str(selected_segment.direction),
            geometry_coords=tuple(selected_segment.geometry_coords),
            candidate_ids=tuple(selected_segment.candidate_ids),
            source_modes=_support_source_modes(str(row.get("traj_support_type", "")), str(row.get("prior_support_type", ""))),
            support_traj_ids=support_ids,
            support_count=max(int(selected_segment.support_count), int(len(support_ids))),
            dedup_count=int(selected_segment.dedup_count),
            representative_offset_m=float(selected_segment.representative_offset_m),
            other_xsec_crossing_count=int(selected_segment.other_xsec_crossing_count),
            tolerated_other_xsec_crossings=int(selected_segment.tolerated_other_xsec_crossings),
            prior_supported=bool(row.get("prior_support_available", False) or selected_segment.prior_supported),
            formation_reason=str(_support_formation_reason(str(row.get("traj_support_type", "")), str(row.get("prior_support_type", "")), str(selected_segment.segment_id))),
            length_m=float(selected_segment.length_m),
            drivezone_ratio=float(selected_segment.drivezone_ratio),
            crosses_divstrip=bool(selected_segment.crosses_divstrip),
            topology_arc_id=str(selected_segment.topology_arc_id),
            topology_arc_source_type=str(selected_segment.topology_arc_source_type),
            topology_arc_edge_ids=tuple(selected_segment.topology_arc_edge_ids),
            topology_arc_node_path=tuple(selected_segment.topology_arc_node_path),
            topology_arc_is_direct_legal=bool(selected_segment.topology_arc_is_direct_legal),
            topology_arc_is_unique=bool(selected_segment.topology_arc_is_unique),
            blocked_diagnostic_only=bool(getattr(selected_segment, "blocked_diagnostic_only", False)),
            controlled_entry_allowed=bool(row.get("controlled_entry_allowed", getattr(selected_segment, "controlled_entry_allowed", False))),
            hard_block_reason=str(getattr(selected_segment, "hard_block_reason", "")),
            topology_gap_decision=str(row.get("topology_gap_decision", getattr(selected_segment, "topology_gap_decision", ""))),
            topology_gap_reason=str(row.get("topology_gap_reason", getattr(selected_segment, "topology_gap_reason", ""))),
            bridge_candidate_retained=False,
            bridge_chain_exists=bool(selected_segment.bridge_chain_exists),
            bridge_chain_unique=bool(selected_segment.bridge_chain_unique),
            bridge_chain_nodes=tuple(selected_segment.bridge_chain_nodes),
            bridge_chain_source=str(selected_segment.bridge_chain_source),
            bridge_diagnostic_reason=str(selected_segment.bridge_diagnostic_reason),
            bridge_decision_stage=str(selected_segment.bridge_decision_stage),
            bridge_decision_reason=str(selected_segment.bridge_decision_reason),
            raw_src_nodeid=getattr(selected_segment, "raw_src_nodeid", selected_segment.src_nodeid),
            raw_dst_nodeid=getattr(selected_segment, "raw_dst_nodeid", selected_segment.dst_nodeid),
            canonical_src_xsec_id=getattr(selected_segment, "canonical_src_xsec_id", selected_segment.src_nodeid),
            canonical_dst_xsec_id=getattr(selected_segment, "canonical_dst_xsec_id", selected_segment.dst_nodeid),
            src_alias_applied=bool(getattr(selected_segment, "src_alias_applied", False)),
            dst_alias_applied=bool(getattr(selected_segment, "dst_alias_applied", False)),
            same_pair_multi_arc_candidate=bool(getattr(selected_segment, "same_pair_multi_arc_candidate", False)),
            same_pair_provisional_allowed=bool(getattr(selected_segment, "same_pair_provisional_allowed", False)),
            same_pair_distinct_path_signal=tuple(getattr(selected_segment, "same_pair_distinct_path_signal", ())),
            topology_arc_assignment_mode=str(getattr(selected_segment, "topology_arc_assignment_mode", "")),
            topology_arc_assignment_line_distance_m=getattr(selected_segment, "topology_arc_assignment_line_distance_m", None),
            topology_arc_assignment_anchor_fit_m=getattr(selected_segment, "topology_arc_assignment_anchor_fit_m", None),
            topology_arc_assignment_geometry_fit_m=getattr(selected_segment, "topology_arc_assignment_geometry_fit_m", None),
            topology_arc_assignment_score_gap_m=getattr(selected_segment, "topology_arc_assignment_score_gap_m", None),
            production_multi_arc_allowed=bool(
                row.get(
                    "production_multi_arc_allowed",
                    getattr(selected_segment, "production_multi_arc_allowed", False),
                )
            ),
            multi_arc_evidence_mode=str(
                row.get(
                    "multi_arc_evidence_mode",
                    getattr(selected_segment, "multi_arc_evidence_mode", ""),
                )
            ),
            multi_arc_structure_type=str(
                row.get(
                    "multi_arc_structure_type",
                    getattr(selected_segment, "multi_arc_structure_type", ""),
                )
            ),
            multi_arc_rule_reason=str(
                row.get(
                    "multi_arc_rule_reason",
                    getattr(selected_segment, "multi_arc_rule_reason", ""),
                )
            ),
            same_pair_rank=int(
                row.get(
                    "same_pair_rank",
                    getattr(selected_segment, "same_pair_rank", 1) or 1,
                )
            ),
            kept_reason=str(
                row.get("kept_reason", getattr(selected_segment, "kept_reason", "arc_first_main_flow"))
                or "arc_first_main_flow"
            ),
        )

    arc_line = _arc_line(row)
    if arc_line is None:
        raise ValueError(f"arc_line_missing:{row.get('topology_arc_id', '')}")
    drivezone_ratio = float(pipeline._drivezone_ratio(arc_line, inputs.drivezone_zone_metric))
    crosses_divstrip = bool(divstrip_buffer is not None and (not divstrip_buffer.is_empty) and arc_line.intersects(divstrip_buffer))
    support_ids = tuple(sorted(str(v) for v in row.get("traj_support_ids", [])))
    return Segment(
        segment_id=f"arcseg::{row['topology_arc_id']}",
        src_nodeid=int(row["src"]),
        dst_nodeid=int(row["dst"]),
        direction="src->dst",
        geometry_coords=line_to_coords(arc_line),
        candidate_ids=(f"arc::{row['topology_arc_id']}",),
        source_modes=_support_source_modes(str(row.get("traj_support_type", "")), str(row.get("prior_support_type", ""))),
        support_traj_ids=support_ids,
        support_count=int(len(support_ids)),
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=1,
        prior_supported=bool(row.get("prior_support_available", False)),
        formation_reason=str(_support_formation_reason(str(row.get("traj_support_type", "")), str(row.get("prior_support_type", "")), "")),
        length_m=float(arc_line.length),
        drivezone_ratio=drivezone_ratio,
        crosses_divstrip=crosses_divstrip,
        topology_arc_id=str(row["topology_arc_id"]),
        topology_arc_source_type=str(row["topology_arc_source_type"]),
        topology_arc_edge_ids=tuple(str(v) for v in row.get("edge_ids", [])),
        topology_arc_node_path=tuple(int(v) for v in row.get("node_path", [])),
        topology_arc_is_direct_legal=bool(row.get("is_direct_legal", False)),
        topology_arc_is_unique=bool(row.get("is_unique", False)),
        blocked_diagnostic_only=bool(row.get("blocked_diagnostic_only", False)),
        controlled_entry_allowed=bool(row.get("controlled_entry_allowed", False)),
        hard_block_reason=str(row.get("hard_block_reason", "")),
        topology_gap_decision=str(row.get("topology_gap_decision", "")),
        topology_gap_reason=str(row.get("topology_gap_reason", "")),
        bridge_candidate_retained=False,
        bridge_chain_exists=False,
        bridge_chain_unique=False,
        bridge_chain_nodes=tuple(),
        bridge_chain_source="",
        bridge_diagnostic_reason="",
        bridge_decision_stage="",
        bridge_decision_reason="",
        raw_src_nodeid=row.get("raw_src_nodeid", row["src"]),
        raw_dst_nodeid=row.get("raw_dst_nodeid", row["dst"]),
        canonical_src_xsec_id=row.get("canonical_src_xsec_id", row["src"]),
        canonical_dst_xsec_id=row.get("canonical_dst_xsec_id", row["dst"]),
        src_alias_applied=bool(row.get("src_alias_applied", False)),
        dst_alias_applied=bool(row.get("dst_alias_applied", False)),
        same_pair_multi_arc_candidate=bool(row.get("same_pair_multi_arc_candidate", False)),
        same_pair_provisional_allowed=bool(row.get("same_pair_provisional_allowed", False)),
        same_pair_distinct_path_signal=tuple(str(v) for v in row.get("same_pair_distinct_path_signal", [])),
        topology_arc_assignment_mode=str(row.get("topology_arc_assignment_mode", "")),
        topology_arc_assignment_line_distance_m=row.get("topology_arc_assignment_line_distance_m"),
        topology_arc_assignment_anchor_fit_m=row.get("topology_arc_assignment_anchor_fit_m"),
        topology_arc_assignment_geometry_fit_m=row.get("topology_arc_assignment_geometry_fit_m"),
        topology_arc_assignment_score_gap_m=row.get("topology_arc_assignment_score_gap_m"),
        production_multi_arc_allowed=bool(row.get("production_multi_arc_allowed", False)),
        multi_arc_evidence_mode=str(row.get("multi_arc_evidence_mode", "")),
        multi_arc_structure_type=str(row.get("multi_arc_structure_type", "")),
        multi_arc_rule_reason=str(row.get("multi_arc_rule_reason", "")),
        same_pair_rank=int(row.get("same_pair_rank", 1) or 1),
        kept_reason=str(row.get("kept_reason", "arc_first_main_flow") or "arc_first_main_flow"),
    )


def build_arc_evidence_attach(
    *,
    full_registry_rows: list[dict[str, Any]],
    selected_segments: list[Segment],
    inputs: Any,
    frame: Any,
    prior_roads: list[Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    pipeline = _pipeline()
    selected_by_arc = {str(segment.topology_arc_id): segment for segment in selected_segments if str(segment.topology_arc_id)}
    patch_geometry_cache = build_patch_geometry_cache(inputs, params)
    divstrip_buffer = patch_geometry_cache.get("divstrip_buffer")
    prior_index = build_prior_reference_index(prior_roads)
    traj_rows, traj_runtime = _build_trajectory_attach_cache(
        inputs=inputs,
        frame=frame,
        params=params,
        divstrip_buffer=divstrip_buffer,
    )
    preprocessed_traj_rows: list[dict[str, Any]] = []
    for traj_row in traj_rows:
        traj_line = traj_row.get("line")
        surface_metrics = _line_surface_metrics(
            traj_line,
            drivezone=inputs.drivezone_zone_metric,
            drivable_surface=patch_geometry_cache.get("drivable_surface"),
            divstrip_buffer=divstrip_buffer,
        )
        surface_consistent, surface_reject_reason = _support_surface_consistency(surface_metrics, params=params)
        preprocessed_traj_rows.append(
            {
                "traj_id": str(traj_row.get("traj_id", "")),
                "line_coords": _coords_list(traj_line),
                "support_mode": "preprocessed",
                "topology_arc_id": "",
                "on_drivable_surface_ratio": float(surface_metrics["on_drivable_surface_ratio"]),
                "drivezone_overlap_ratio": float(surface_metrics["drivezone_overlap_ratio"]),
                "divstrip_overlap_ratio": float(surface_metrics["divstrip_overlap_ratio"]),
                "surface_consistent": bool(surface_consistent),
                "surface_reject_reason": str(surface_reject_reason),
                "accepted_for_production": bool(surface_consistent),
            }
        )
    runtime_totals = {
        **dict(traj_runtime),
        "trajectory_prefilter_time_ms": 0.0,
        "support_attach_core_loop_time_ms": 0.0,
        "terminal_partial_stitched_aggregation_time_ms": 0.0,
        "working_segment_materialize_time_ms": 0.0,
    }
    prefilter_stats = {"arc_count": 0, "candidate_traj_total": 0, "candidate_traj_max": 0, "candidate_traj_hist": Counter()}
    rows: list[dict[str, Any]] = []
    working_segments: list[Segment] = []
    support_debug_rows: list[dict[str, Any]] = []
    for row in full_registry_rows:
        current = dict(row)
        selected_segment = selected_by_arc.get(str(current.get("topology_arc_id", "")))
        arc_line = _arc_line(current)
        prefilter_started = perf_counter()
        candidate_traj_rows = (
            _prefilter_traj_rows(
                arc_line=arc_line,
                traj_rows=traj_rows,
                buffer_m=float(params.get("ARC_EVIDENCE_BUFFER_M", 8.0)),
            )
            if arc_line is not None
            else []
        )
        runtime_totals["trajectory_prefilter_time_ms"] += float((perf_counter() - prefilter_started) * 1000.0)
        prefilter_stats["arc_count"] += 1
        prefilter_stats["candidate_traj_total"] += int(len(candidate_traj_rows))
        prefilter_stats["candidate_traj_max"] = max(int(prefilter_stats["candidate_traj_max"]), int(len(candidate_traj_rows)))
        prefilter_stats["candidate_traj_hist"][int(len(candidate_traj_rows))] += 1
        current["_prefilter_candidate_traj_count"] = int(len(candidate_traj_rows))

        core_started = perf_counter()
        support = _support_type_for_arc(
            row=current,
            arc_line=arc_line,
            prior_roads=prior_roads,
            prior_index=prior_index,
            candidate_traj_rows=candidate_traj_rows,
            drivezone=inputs.drivezone_zone_metric,
            drivable_surface=patch_geometry_cache.get("drivable_surface"),
            divstrip_buffer=divstrip_buffer,
            params=params,
        )
        runtime_totals["support_attach_core_loop_time_ms"] += float((perf_counter() - core_started) * 1000.0)

        aggregation_started = perf_counter()
        current.update(
            {
                "traj_support_type": str(support["traj_support_type"]),
                "traj_support_ids": [str(v) for v in support["traj_support_ids"]],
                "traj_support_span_count": int(support["traj_support_span_count"]),
                "traj_support_coverage_ratio": float(support["traj_support_coverage_ratio"]),
                "traj_support_spans": list(support["traj_support_spans"]),
                "traj_support_segments": list(support.get("traj_support_segments", [])),
                "single_traj_support_segments": list(support.get("single_traj_support_segments", [])),
                "stitched_traj_support_segments": list(support.get("stitched_traj_support_segments", [])),
                "support_reference_coords": list(support.get("support_reference_coords", [])),
                "support_anchor_src_coords": support.get("support_anchor_src_coords"),
                "support_anchor_dst_coords": support.get("support_anchor_dst_coords"),
                "support_generation_mode": str(support.get("support_generation_mode", "")),
                "support_generation_reason": str(support.get("support_generation_reason", "")),
                "selected_support_traj_id": str(support.get("selected_support_traj_id", "")),
                "single_traj_candidate_count": int(support.get("single_traj_candidate_count", 0)),
                "single_traj_surface_consistent_count": int(support.get("single_traj_surface_consistent_count", 0)),
                "prior_support_type": str(support["prior_support_type"]),
                "prior_support_available": bool(support["prior_support_available"]),
                "arc_path_drivezone_ratio": float(
                    pipeline._drivezone_ratio(arc_line, inputs.drivezone_zone_metric)
                    if arc_line is not None
                    else 0.0
                ),
                "arc_path_divstrip_overlap_ratio": float(_line_overlap_ratio(arc_line, divstrip_buffer)),
                "arc_path_crosses_divstrip": bool(
                    arc_line is not None
                    and divstrip_buffer is not None
                    and (not divstrip_buffer.is_empty)
                    and arc_line.intersects(divstrip_buffer)
                ),
            }
        )
        runtime_totals["terminal_partial_stitched_aggregation_time_ms"] += float((perf_counter() - aggregation_started) * 1000.0)
        rows.append(current)

    rows = list(apply_arc_selection_rules(rows).get("rows", []))
    topology_gap_decisions = classify_topology_gap_rows(rows, params=params)
    for current in rows:
        pair_id = str(current.get("pair", ""))
        gap_decision = dict(topology_gap_decisions.get(pair_id) or {})
        if gap_decision:
            current["topology_gap_decision"] = str(gap_decision.get("decision", ""))
            current["topology_gap_reason"] = str(gap_decision.get("reason", ""))
            current["controlled_entry_allowed"] = bool(gap_decision.get("controlled_entry_allowed", False))
            current["arc_structure_type"] = str(
                gap_decision.get("arc_structure_type", current.get("arc_structure_type", ""))
            )
            current["arc_selection_rule"] = str(
                gap_decision.get("arc_selection_rule", current.get("arc_selection_rule", ""))
            )
            current["arc_selection_allow_multi_output"] = bool(
                gap_decision.get(
                    "arc_selection_allow_multi_output",
                    current.get("arc_selection_allow_multi_output", False),
                )
            )
            current["arc_selection_shared_downstream_nodes"] = list(
                gap_decision.get(
                    "arc_selection_shared_downstream_nodes",
                    current.get("arc_selection_shared_downstream_nodes", []),
                )
            )
            current["arc_selection_peer_pairs"] = list(
                gap_decision.get(
                    "arc_selection_peer_pairs",
                    current.get("arc_selection_peer_pairs", []),
                )
            )
            current["arc_selection_rule_reason"] = str(
                gap_decision.get(
                    "arc_selection_rule_reason",
                    current.get("arc_selection_rule_reason", ""),
                )
            )
            if bool(current.get("controlled_entry_allowed", False)):
                current["entered_main_flow"] = True
                current["unbuilt_stage"] = ""
                current["unbuilt_reason"] = ""
            else:
                current["entered_main_flow"] = False
                current["unbuilt_stage"] = (
                    "hard_blocked"
                    if str(current.get("topology_gap_decision", "")) == "gap_remain_blocked"
                    else "gap_needs_more_constraints"
                )
                current["unbuilt_reason"] = str(current.get("topology_gap_reason", ""))
                current["blocked_diagnostic_reason"] = str(current.get("topology_gap_reason", ""))

    same_pair_rule = apply_multi_arc_rule(rows)
    same_pair_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for current in rows:
        canonical_pair = str(current.get("canonical_pair", current.get("pair", "")))
        rule_row = dict(same_pair_rule.get(canonical_pair, {}))
        if str(current.get("arc_structure_type", "")) != STRUCTURE_SAME_PAIR_MULTI_ARC:
            continue
        topology_arc_id = str(current.get("topology_arc_id", ""))
        evidence_modes = dict(rule_row.get("evidence_modes", {}))
        current["multi_arc_structure_type"] = str(rule_row.get("structure_type", STRUCTURE_SAME_PAIR_MULTI_ARC))
        current["multi_arc_rule_reason"] = str(rule_row.get("rule_reason", ""))
        current["multi_arc_evidence_mode"] = str(evidence_modes.get(topology_arc_id, "insufficient"))
        current["multi_arc_allow_multi_output"] = bool(rule_row.get("allow_multi_output", False))
        current["production_multi_arc_allowed"] = bool(
            current.get("multi_arc_allow_multi_output", False)
            and str(current.get("multi_arc_evidence_mode", "")) in {"witness_based", "fallback_based"}
        )
        if bool(current.get("production_multi_arc_allowed", False)):
            current["entered_main_flow"] = True
            current["blocked_diagnostic_only"] = False
            current["blocked_diagnostic_reason"] = ""
            current["hard_block_reason"] = ""
            current["unbuilt_stage"] = ""
            current["unbuilt_reason"] = ""
            current["working_segment_source"] = "arc_first_multi_arc_segment"
            same_pair_groups[canonical_pair].append(current)
        elif not bool(current.get("entered_main_flow", False)):
            current["unbuilt_stage"] = str(current.get("unbuilt_stage", "") or "step3_multi_arc_rule_blocked")
            current["unbuilt_reason"] = str(
                current.get("unbuilt_reason", "")
                or current.get("multi_arc_rule_reason", "")
                or "same_pair_multi_arc_evidence_not_sufficient"
            )

    for _canonical_pair, group_rows in same_pair_groups.items():
        ranked_rows = sorted(
            group_rows,
            key=lambda item: (
                0 if str(item.get("multi_arc_evidence_mode", "")) == "witness_based" else 1,
                -float(item.get("traj_support_coverage_ratio", 0.0) or 0.0),
                str(item.get("topology_arc_id", "")),
            ),
        )
        for rank, current in enumerate(ranked_rows, start=1):
            current["same_pair_rank"] = int(rank)
            current["kept_reason"] = "same_pair_multi_arc_allowed"

    for current in rows:
        selected_segment = selected_by_arc.get(str(current.get("topology_arc_id", "")))
        if bool(current.get("entered_main_flow", False)):
            materialize_started = perf_counter()
            working_segment = _materialize_working_segment(
                row=current,
                selected_segment=selected_segment,
                inputs=inputs,
                params=params,
                divstrip_buffer=divstrip_buffer,
            )
            current["working_segment_id"] = str(working_segment.segment_id)
            current["working_segment_source"] = "step2_selected_segment" if selected_segment is not None else "arc_first_materialized_segment"
            current["entered_main_flow"] = True
            if (
                str(current.get("unbuilt_stage", "")) == ""
                and str(current["traj_support_type"]) == "no_support"
                and str(current["prior_support_type"]) != "prior_fallback_support"
            ):
                current["unbuilt_stage"] = "step3_no_support"
                current["unbuilt_reason"] = "no_traj_support"
            working_segments.append(working_segment)
            runtime_totals["working_segment_materialize_time_ms"] += float((perf_counter() - materialize_started) * 1000.0)

        support_debug_rows.append(
            {
                "pair": str(current["pair"]),
                "topology_arc_id": str(current["topology_arc_id"]),
                "entered_main_flow": bool(current.get("entered_main_flow", False)),
                "prefilter_candidate_traj_count": int(current.get("_prefilter_candidate_traj_count", 0)),
                "selected_segment_count": int(current.get("selected_segment_count", 0)),
                "traj_support_type": str(current["traj_support_type"]),
                "traj_support_ids": [str(v) for v in current["traj_support_ids"]],
                "traj_support_span_count": int(current["traj_support_span_count"]),
                "traj_support_coverage_ratio": float(current["traj_support_coverage_ratio"]),
                "traj_support_segment_count": int(len(current.get("traj_support_segments", []))),
                "support_generation_mode": str(current.get("support_generation_mode", "")),
                "support_generation_reason": str(current.get("support_generation_reason", "")),
                "selected_support_traj_id": str(current.get("selected_support_traj_id", "")),
                "single_traj_candidate_count": int(current.get("single_traj_candidate_count", 0)),
                "single_traj_surface_consistent_count": int(current.get("single_traj_surface_consistent_count", 0)),
                "prior_support_type": str(current["prior_support_type"]),
                "topology_gap_decision": str(current.get("topology_gap_decision", "")),
                "topology_gap_reason": str(current.get("topology_gap_reason", "")),
                "controlled_entry_allowed": bool(current.get("controlled_entry_allowed", False)),
                "multi_arc_evidence_mode": str(current.get("multi_arc_evidence_mode", "")),
                "production_multi_arc_allowed": bool(current.get("production_multi_arc_allowed", False)),
                "working_segment_id": str(current.get("working_segment_id", "")),
                "working_segment_source": str(current.get("working_segment_source", "")),
            }
        )
        current.pop("_prefilter_candidate_traj_count", None)

    entered_main_flow_rows = [row for row in rows if bool(row.get("entered_main_flow", False))]
    traj_supported_rows = [row for row in entered_main_flow_rows if str(row.get("traj_support_type", "")) != "no_support"]
    prior_supported_rows = [row for row in entered_main_flow_rows if str(row.get("prior_support_type", "")) == "prior_fallback_support"]
    return {
        "rows": rows,
        "working_segments": working_segments,
        "summary": {
            "all_direct_legal_arc_count": int(len(rows)),
            "all_direct_unique_legal_arc_count": int(sum(1 for row in rows if bool(row.get("is_unique", False)))),
            "entered_main_flow_arc_count": int(len(entered_main_flow_rows)),
            "traj_supported_arc_count": int(len(traj_supported_rows)),
            "prior_supported_arc_count": int(len(prior_supported_rows)),
            "traj_support_type_hist": dict(Counter(str(row.get("traj_support_type", "")) for row in entered_main_flow_rows)),
            "topology_gap_decision_hist": dict(
                Counter(str(row.get("topology_gap_decision", "")) for row in rows if str(row.get("topology_gap_decision", "")))
            ),
            "working_segment_count": int(len(working_segments)),
        },
        "audit_rows": support_debug_rows,
        "preprocessed_traj_rows": preprocessed_traj_rows,
        "runtime": {
            **runtime_totals,
            "prefilter_avg_candidate_traj_count": float(float(prefilter_stats["candidate_traj_total"]) / max(1, int(prefilter_stats["arc_count"]))),
            "prefilter_candidate_traj_max": int(prefilter_stats["candidate_traj_max"]),
            "prefilter_candidate_traj_hist": {str(key): int(value) for key, value in sorted(prefilter_stats["candidate_traj_hist"].items())},
        },
    }


def _segment_feature(segment: Segment, row: dict[str, Any]) -> tuple[LineString, dict[str, Any]]:
    return (
        segment.geometry_metric(),
        {
            "segment_id": str(segment.segment_id),
            "src_nodeid": int(segment.src_nodeid),
            "dst_nodeid": int(segment.dst_nodeid),
            "topology_arc_id": str(segment.topology_arc_id),
            "traj_support_type": str(row.get("traj_support_type", "")),
            "prior_support_type": str(row.get("prior_support_type", "")),
            "traj_support_coverage_ratio": float(row.get("traj_support_coverage_ratio", 0.0)),
            "working_segment_source": str(row.get("working_segment_source", "")),
        },
    )


def _support_segment_feature(
    *,
    patch_id: str,
    row: dict[str, Any],
    item: dict[str, Any],
) -> tuple[LineString, dict[str, Any]] | None:
    coords = tuple(
        (float(coord[0]), float(coord[1]))
        for coord in item.get("line_coords", [])
        if isinstance(coord, (list, tuple)) and len(coord) >= 2
    )
    if len(coords) < 2:
        return None
    line = coords_to_line(coords)
    if line.is_empty or line.length <= 1e-6:
        return None
    return (
        line,
        {
            "patch_id": str(patch_id),
            "pair": str(row.get("pair", "")),
            "src": int(row.get("src", 0)),
            "dst": int(row.get("dst", 0)),
            "topology_arc_id": str(row.get("topology_arc_id", item.get("topology_arc_id", ""))),
            "traj_id": str(item.get("traj_id", "")),
            "support_type": str(item.get("support_type", "")),
            "support_mode": str(item.get("support_mode", "")),
            "segment_order": int(item.get("segment_order", 0)),
            "is_stitched": bool(item.get("is_stitched", False)),
            "support_score": float(item.get("support_score", 0.0)),
            "support_length_m": float(item.get("support_length_m", 0.0)),
            "source_span_start_idx": int(item.get("source_span_start_idx", 0)),
            "source_span_end_idx": int(item.get("source_span_end_idx", 0)),
            "on_drivable_surface_ratio": float(item.get("on_drivable_surface_ratio", 0.0) or 0.0),
            "drivezone_overlap_ratio": float(item.get("drivezone_overlap_ratio", 0.0) or 0.0),
            "divstrip_overlap_ratio": float(item.get("divstrip_overlap_ratio", 0.0) or 0.0),
            "surface_consistent": bool(item.get("surface_consistent", False)),
            "surface_reject_reason": str(item.get("surface_reject_reason", "")),
            "accepted_for_production": bool(item.get("accepted_for_production", False)),
        },
    )


def run_witness_stage(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    from .step3_corridor_identity import build_witness_for_segment

    pipeline = _pipeline()
    stage_started = perf_counter()
    inputs, frame, prior_roads = pipeline.load_inputs_and_frame(data_root, patch_id, params=params)
    patch_geometry_cache = build_patch_geometry_cache(inputs, params)
    segments_payload = pipeline._load_stage_payload(out_root, run_id, patch_id, "step2_segment")
    selected_segments = [Segment.from_dict(item) for item in segments_payload.get("segments", [])]
    full_registry_rows = list(segments_payload.get("full_legal_arc_registry", []))
    evidence = build_arc_evidence_attach(
        full_registry_rows=full_registry_rows,
        selected_segments=selected_segments,
        inputs=inputs,
        frame=frame,
        prior_roads=prior_roads,
        params=params,
    )
    row_by_segment_id = {str(row.get("working_segment_id", "")): row for row in evidence["rows"] if str(row.get("working_segment_id", ""))}
    witness_started = perf_counter()
    witnesses = [
        build_witness_for_segment(
            segment,
            inputs,
            params,
            drivable_surface=patch_geometry_cache.get("drivable_surface"),
        )
        for segment in evidence["working_segments"]
    ]
    runtime = {
        **dict(evidence.get("runtime", {})),
        "witness_build_time_ms": float((perf_counter() - witness_started) * 1000.0),
        "stage_runtime_ms": float((perf_counter() - stage_started) * 1000.0),
    }
    artifact = {
        "witnesses": [witness.to_dict() for witness in witnesses],
        "working_segments": [segment.to_dict() for segment in evidence["working_segments"]],
        "full_legal_arc_registry": list(evidence["rows"]),
        "legal_arc_funnel": dict(evidence["summary"]),
        "arc_evidence_attach_audit": list(evidence["audit_rows"]),
        "runtime": runtime,
    }
    dbg_dir = pipeline.debug_dir(out_root, run_id, patch_id)
    step_dir = pipeline.stage_dir(out_root, run_id, patch_id, "step3_witness")
    write_json(pipeline._artifact_path(out_root, run_id, patch_id, "step3_witness"), artifact)
    write_json(dbg_dir / "arc_evidence_attach.json", {"arcs": evidence["audit_rows"], "summary": evidence["summary"], "runtime": runtime})
    write_json(
        dbg_dir / "prefilter_stats.json",
        {
            "summary": {
                "trajectory_prefilter_time_ms": float(runtime.get("trajectory_prefilter_time_ms", 0.0)),
                "support_attach_core_loop_time_ms": float(runtime.get("support_attach_core_loop_time_ms", 0.0)),
                "terminal_partial_stitched_aggregation_time_ms": float(runtime.get("terminal_partial_stitched_aggregation_time_ms", 0.0)),
                "prefilter_avg_candidate_traj_count": float(runtime.get("prefilter_avg_candidate_traj_count", 0.0)),
                "prefilter_candidate_traj_max": int(runtime.get("prefilter_candidate_traj_max", 0)),
            },
            "hist": dict(runtime.get("prefilter_candidate_traj_hist", {})),
        },
    )
    write_json(
        dbg_dir / "step3_attach_hotspots.json",
        {
            "runtime": runtime,
            "top_arcs": sorted(
                [
                    {
                        "pair": str(item.get("pair", "")),
                        "topology_arc_id": str(item.get("topology_arc_id", "")),
                        "prefilter_candidate_traj_count": int(item.get("prefilter_candidate_traj_count", 0)),
                        "traj_support_type": str(item.get("traj_support_type", "")),
                        "traj_support_coverage_ratio": float(item.get("traj_support_coverage_ratio", 0.0)),
                    }
                    for item in evidence["audit_rows"]
                ],
                key=lambda item: (-int(item["prefilter_candidate_traj_count"]), -float(item["traj_support_coverage_ratio"]), str(item["topology_arc_id"])),
            )[:20],
        },
    )
    write_lines_geojson(
        dbg_dir / "arc_first_working_segments.geojson",
        [_segment_feature(segment, row_by_segment_id.get(str(segment.segment_id), {})) for segment in evidence["working_segments"]],
    )
    write_features_geojson(
        step_dir / "preprocessed_traj_lines.geojson",
        [
            (
                coords_to_line(
                    tuple(
                        (float(coord[0]), float(coord[1]))
                        for coord in item.get("line_coords", [])
                        if isinstance(coord, (list, tuple)) and len(coord) >= 2
                    )
                ),
                {
                    "patch_id": str(patch_id),
                    "traj_id": str(item.get("traj_id", "")),
                    "topology_arc_id": str(item.get("topology_arc_id", "")),
                    "support_mode": str(item.get("support_mode", "preprocessed")),
                    "on_drivable_surface_ratio": float(item.get("on_drivable_surface_ratio", 0.0) or 0.0),
                    "drivezone_overlap_ratio": float(item.get("drivezone_overlap_ratio", 0.0) or 0.0),
                    "divstrip_overlap_ratio": float(item.get("divstrip_overlap_ratio", 0.0) or 0.0),
                    "surface_consistent": bool(item.get("surface_consistent", False)),
                    "surface_reject_reason": str(item.get("surface_reject_reason", "")),
                    "accepted_for_production": bool(item.get("accepted_for_production", False)),
                },
            )
            for item in evidence.get("preprocessed_traj_rows", [])
            if len(item.get("line_coords", [])) >= 2
        ],
    )
    single_support_features = [
        feature
        for feature in (
            _support_segment_feature(patch_id=str(patch_id), row=row, item=item)
            for row in evidence["rows"]
            for item in row.get("single_traj_support_segments", [])
        )
        if feature is not None
    ]
    stitched_support_features = [
        feature
        for feature in (
            _support_segment_feature(patch_id=str(patch_id), row=row, item=item)
            for row in evidence["rows"]
            for item in row.get("stitched_traj_support_segments", [])
        )
        if feature is not None
    ]
    production_support_features = [
        feature
        for feature in (
            _support_segment_feature(patch_id=str(patch_id), row=row, item=item)
            for row in evidence["rows"]
            for item in row.get("traj_support_segments", [])
        )
        if feature is not None
    ]
    write_features_geojson(step_dir / "arc_single_traj_support_segments.geojson", single_support_features)
    write_features_geojson(step_dir / "arc_stitched_support_segments.geojson", stitched_support_features)
    write_features_geojson(
        dbg_dir / "arc_traj_support_segments.geojson",
        production_support_features,
    )
    target_support_review = next(
        (dict(row) for row in evidence["rows"] if str(row.get("pair", "")) == "55353246:37687913"),
        None,
    )
    if target_support_review is not None:
        write_json(
            step_dir / "support_generation_review_55353246_37687913.json",
            {
                "pair": "55353246:37687913",
                "topology_arc_id": str(target_support_review.get("topology_arc_id", "")),
                "entered_main_flow": bool(target_support_review.get("entered_main_flow", False)),
                "support_generation_mode": str(target_support_review.get("support_generation_mode", "")),
                "support_generation_reason": str(target_support_review.get("support_generation_reason", "")),
                "traj_support_type": str(target_support_review.get("traj_support_type", "")),
                "traj_support_ids": [str(v) for v in target_support_review.get("traj_support_ids", [])],
                "selected_support_traj_id": str(target_support_review.get("selected_support_traj_id", "")),
                "traj_support_coverage_ratio": float(target_support_review.get("traj_support_coverage_ratio", 0.0) or 0.0),
                "single_traj_candidate_count": int(target_support_review.get("single_traj_candidate_count", 0)),
                "single_traj_surface_consistent_count": int(
                    target_support_review.get("single_traj_surface_consistent_count", 0)
                ),
                "single_traj_support_segment_count": int(len(target_support_review.get("single_traj_support_segments", []))),
                "stitched_traj_support_segment_count": int(len(target_support_review.get("stitched_traj_support_segments", []))),
                "arc_path_drivezone_ratio": float(target_support_review.get("arc_path_drivezone_ratio", 0.0) or 0.0),
                "arc_path_divstrip_overlap_ratio": float(
                    target_support_review.get("arc_path_divstrip_overlap_ratio", 0.0) or 0.0
                ),
                "unbuilt_stage": str(target_support_review.get("unbuilt_stage", "")),
                "unbuilt_reason": str(target_support_review.get("unbuilt_reason", "")),
                "production_support_segments": list(target_support_review.get("traj_support_segments", [])),
            },
        )
    return {
        "artifact": artifact,
        "inputs": inputs,
        "frame": frame,
        "segments": evidence["working_segments"],
        "witnesses": witnesses,
        "runtime": runtime,
        "reason": "witness_ready",
    }


__all__ = ["build_arc_evidence_attach", "classify_topology_gap_rows", "run_witness_stage"]
