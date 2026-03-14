from __future__ import annotations

from collections import Counter
from math import hypot
from pathlib import Path
from time import perf_counter
from typing import Any

from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, substring

from .io import write_json, write_lines_geojson
from .models import BaseCrossSection, CorridorIdentity, CorridorWitness, FinalRoad, Segment, SlotInterval, line_to_coords
from .step3_corridor_identity import (
    build_patch_geometry_cache,
    build_prior_reference_index,
    find_prior_reference_line,
    make_missing_witness,
)


def _pipeline():
    from . import pipeline as pipeline_module

    return pipeline_module


def _replace_endpoints(line: LineString, start_pt: Point, end_pt: Point) -> LineString:
    coords = list(line.coords)
    mid: list[tuple[float, float]] = []
    for coord in coords[1:-1]:
        xy = (float(coord[0]), float(coord[1]))
        if not mid or xy != mid[-1]:
            mid.append(xy)
    new_coords = [(float(start_pt.x), float(start_pt.y)), *mid, (float(end_pt.x), float(end_pt.y))]
    deduped: list[tuple[float, float]] = []
    for xy in new_coords:
        if not deduped or xy != deduped[-1]:
            deduped.append(xy)
    if len(deduped) < 2:
        deduped = [(float(start_pt.x), float(start_pt.y)), (float(end_pt.x), float(end_pt.y))]
    return LineString(deduped)


def _line_from_coords(coords: list[list[float]] | tuple[tuple[float, float], ...] | tuple[Any, ...]) -> LineString | None:
    pts = tuple(
        (float(item[0]), float(item[1]))
        for item in coords
        if isinstance(item, (list, tuple)) and len(item) >= 2
    )
    if len(pts) < 2:
        return None
    line = LineString(list(pts))
    if line.is_empty or line.length <= 1e-6:
        return None
    return line


def _anchor_along_base_line(base_line: LineString, start_pt: Point, end_pt: Point) -> LineString:
    if base_line.is_empty or base_line.length <= 1e-6:
        return _replace_endpoints(base_line, start_pt, end_pt)
    start_s = float(base_line.project(start_pt))
    end_s = float(base_line.project(end_pt))
    middle = substring(base_line, start_s, end_s)
    coords: list[tuple[float, float]] = [(float(start_pt.x), float(start_pt.y))]
    if isinstance(middle, Point):
        coords.append((float(middle.x), float(middle.y)))
    elif isinstance(middle, LineString) and not middle.is_empty:
        coords.extend((float(x), float(y)) for x, y, *_ in middle.coords)
    coords.append((float(end_pt.x), float(end_pt.y)))
    deduped: list[tuple[float, float]] = []
    for xy in coords:
        if not deduped or xy != deduped[-1]:
            deduped.append(xy)
    if len(deduped) < 2:
        deduped = [(float(start_pt.x), float(start_pt.y)), (float(end_pt.x), float(end_pt.y))]
    return LineString(deduped)


def _translate_line(line: LineString, dx: float, dy: float) -> LineString | None:
    coords = [(float(x) + float(dx), float(y) + float(dy)) for x, y, *_ in line.coords]
    if len(coords) < 2:
        return None
    translated = LineString(coords)
    if translated.is_empty or translated.length <= 1e-6:
        return None
    return translated


def _slot_side_shift_vector(
    base_line: LineString,
    start_pt: Point,
    end_pt: Point,
) -> tuple[float, float] | None:
    if base_line.is_empty or base_line.length <= 1e-6:
        return None
    try:
        start_proj = base_line.interpolate(float(base_line.project(start_pt)))
        end_proj = base_line.interpolate(float(base_line.project(end_pt)))
    except Exception:
        return None
    shift_dx = ((float(start_pt.x) - float(start_proj.x)) + (float(end_pt.x) - float(end_proj.x))) / 2.0
    shift_dy = ((float(start_pt.y) - float(start_proj.y)) + (float(end_pt.y) - float(end_proj.y))) / 2.0
    if hypot(float(shift_dx), float(shift_dy)) > 0.25:
        return float(shift_dx), float(shift_dy)
    coords = list(base_line.coords)
    if len(coords) < 3:
        return None
    start_inner = coords[1]
    end_inner = coords[-2]
    shift_dx = ((float(start_pt.x) - float(start_inner[0])) + (float(end_pt.x) - float(end_inner[0]))) / 2.0
    shift_dy = ((float(start_pt.y) - float(start_inner[1])) + (float(end_pt.y) - float(end_inner[1]))) / 2.0
    if hypot(float(shift_dx), float(shift_dy)) <= 0.25:
        return None
    return float(shift_dx), float(shift_dy)


def _slot_side_translated_line(
    base_line: LineString,
    start_pt: Point,
    end_pt: Point,
) -> LineString | None:
    if base_line.is_empty or base_line.length <= 1e-6:
        return None
    shift = _slot_side_shift_vector(base_line, start_pt, end_pt)
    if shift is None:
        return None
    shift_dx, shift_dy = shift
    translated = _translate_line(base_line, shift_dx, shift_dy)
    if translated is None:
        return None
    return _anchor_along_base_line(translated, start_pt, end_pt)


def _scaled_slot_side_translated_line(
    base_line: LineString,
    start_pt: Point,
    end_pt: Point,
    *,
    scale: float,
) -> LineString | None:
    if base_line.is_empty or base_line.length <= 1e-6:
        return None
    shift = _slot_side_shift_vector(base_line, start_pt, end_pt)
    if shift is None:
        return None
    base_shift_dx, base_shift_dy = shift
    shift_dx = float(base_shift_dx) * float(scale)
    shift_dy = float(base_shift_dy) * float(scale)
    if hypot(float(shift_dx), float(shift_dy)) <= 0.25:
        return None
    translated = _translate_line(base_line, shift_dx, shift_dy)
    if translated is None:
        return None
    return _anchor_along_base_line(translated, start_pt, end_pt)


def _append_candidate_line(
    candidate_lines: list[tuple[LineString, str]],
    line: LineString | None,
    mode: str,
    *,
    priority: bool = False,
) -> None:
    if line is None:
        return
    if any(line.equals(existing_line) for existing_line, _ in candidate_lines):
        return
    item = (line, str(mode))
    if priority:
        candidate_lines.insert(1 if candidate_lines else 0, item)
    else:
        candidate_lines.append(item)


def _append_side_constrained_candidates(
    candidate_lines: list[tuple[LineString, str]],
    base_line: LineString | None,
    base_mode: str,
    *,
    start_pt: Point,
    end_pt: Point,
    prefer_early: bool = False,
) -> None:
    if base_line is None:
        return
    inserted = False
    for scale in (1.0, 0.75, 1.25, 1.5):
        translated = _scaled_slot_side_translated_line(
            base_line,
            start_pt,
            end_pt,
            scale=float(scale),
        )
        if translated is None:
            continue
        _append_candidate_line(
            candidate_lines,
            translated,
            f"{base_mode}_side_constrained_{str(scale).rstrip('0').rstrip('.')}",
            priority=bool(prefer_early and not inserted),
        )
        inserted = True


def _selected_witness_interval(witness: CorridorWitness | None):
    if witness is None or witness.selected_interval_rank is None:
        return None
    for interval in witness.intervals:
        if int(interval.rank) == int(witness.selected_interval_rank):
            return interval
    return None


def _legacy_witness_centerline(
    *,
    witness: CorridorWitness | None,
    start_pt: Point,
    end_pt: Point,
) -> LineString | None:
    pipeline = _pipeline()
    selected = _selected_witness_interval(witness)
    if selected is None:
        return None
    mid_pt = pipeline._midpoint_of_interval(selected)
    return LineString(
        [
            (float(start_pt.x), float(start_pt.y)),
            (float(mid_pt.x), float(mid_pt.y)),
            (float(end_pt.x), float(end_pt.y)),
        ]
    )


def _witness_reference_projected_line(
    *,
    witness: CorridorWitness | None,
    start_pt: Point,
    end_pt: Point,
) -> LineString | None:
    if witness is None:
        return None
    witness_line = witness.geometry_metric()
    if witness_line.is_empty or float(witness_line.length) <= 1e-6:
        return None
    return _anchor_along_base_line(witness_line, start_pt, end_pt)


def _line_overlap_ratio(line: LineString, zone: Any | None) -> float:
    if zone is None or getattr(zone, "is_empty", True):
        return 0.0
    length = float(getattr(line, "length", 0.0))
    if length <= 1e-6:
        return 0.0
    try:
        overlap = line.intersection(zone)
    except Exception:
        return 0.0
    return float(max(0.0, min(1.0, float(getattr(overlap, "length", 0.0)) / max(length, 1e-6))))


def slot_reference_line(
    *,
    segment: Segment,
    identity: CorridorIdentity,
    prior_roads: list[Any],
    prior_index: dict[tuple[int, int], list[Any]] | None = None,
) -> tuple[LineString, str]:
    if str(identity.state) == "prior_based":
        prior_line = find_prior_reference_line(segment, prior_roads, prior_index=prior_index)
        if prior_line is not None:
            return prior_line, "prior_reference"
    return segment.geometry_metric(), "segment_support"


def shape_ref_line(
    *,
    segment: Segment,
    identity: CorridorIdentity,
    witness: CorridorWitness | None,
    src_slot: SlotInterval,
    dst_slot: SlotInterval,
    prior_roads: list[Any],
    prior_index: dict[tuple[int, int], list[Any]] | None = None,
) -> tuple[LineString, str]:
    pipeline = _pipeline()
    base_line, mode = slot_reference_line(segment=segment, identity=identity, prior_roads=prior_roads, prior_index=prior_index)
    if src_slot.interval is None or dst_slot.interval is None:
        return base_line, str(mode)
    start_pt = pipeline._midpoint_of_interval(src_slot.interval)
    end_pt = pipeline._midpoint_of_interval(dst_slot.interval)
    if str(identity.state) == "witness_based":
        witness_reference = _witness_reference_projected_line(witness=witness, start_pt=start_pt, end_pt=end_pt)
        if witness_reference is not None:
            return witness_reference, "witness_reference_projected_anchored"
        legacy_centerline = _legacy_witness_centerline(witness=witness, start_pt=start_pt, end_pt=end_pt)
        if legacy_centerline is not None:
            return legacy_centerline, "witness_centerline"
    return _replace_endpoints(base_line, start_pt, end_pt), f"{mode}_slot_anchored"


def build_slot(
    *,
    segment: Segment,
    witness: CorridorWitness | None,
    identity: CorridorIdentity,
    xsec: BaseCrossSection,
    line: LineString,
    inputs: Any,
    params: dict[str, Any],
    endpoint_tag: str,
    drivable_surface: Any | None = None,
) -> SlotInterval:
    pipeline = _pipeline()
    surface = drivable_surface if drivable_surface is not None else pipeline._drivable_surface(inputs, params)
    xsec_line = xsec.geometry_metric()
    align_vector = witness.axis_vector if witness is not None else pipeline._line_direction(xsec_line)
    intervals = pipeline._intervals_on_xsec(
        xsec_line,
        surface,
        align_vector=align_vector,
        min_len_m=float(params["INTERVAL_MIN_LEN_M"]),
    )
    if str(identity.state) == "unresolved":
        return SlotInterval(
            segment_id=str(segment.segment_id),
            endpoint_tag=str(endpoint_tag),
            xsec_nodeid=int(xsec.nodeid),
            xsec_coords=xsec.geometry_coords,
            interval=None,
            resolved=False,
            method="unresolved",
            reason="corridor_identity_unresolved",
            interval_count=int(len(intervals)),
        )
    ref_point = nearest_points(xsec_line, line)[0]
    ref_s = float(xsec_line.project(ref_point))
    desired_rank = identity.witness_interval_rank if str(identity.state) == "witness_based" else None
    interval = None
    method = "unresolved"
    reason = "no_legal_interval"
    if (
        str(identity.state) == "witness_based"
        and witness is not None
        and witness.selected_interval_start_s is not None
        and witness.selected_interval_end_s is not None
        and intervals
        and float(xsec_line.length) > 1e-6
        and float(witness.geometry_metric().length) > 1e-6
    ):
        witness_center = (float(witness.selected_interval_start_s) + float(witness.selected_interval_end_s)) / 2.0
        witness_fraction = witness_center / max(float(witness.geometry_metric().length), 1e-6)
        if len(intervals) == len(witness.intervals) and desired_rank is not None and 0 <= int(desired_rank) < len(intervals):
            interval = intervals[int(desired_rank)]
            method = "rank"
            reason = "witness_rank_match"
        elif len(intervals) > 1:
            interval = min(intervals, key=lambda item: abs((float(item.center_s) / max(float(xsec_line.length), 1e-6)) - float(witness_fraction)))
            method = "fraction_match"
            reason = "witness_fraction_match"
    if interval is None:
        interval, method, reason = pipeline._choose_interval(intervals, reference_s=ref_s, desired_rank=desired_rank)
    return SlotInterval(
        segment_id=str(segment.segment_id),
        endpoint_tag=str(endpoint_tag),
        xsec_nodeid=int(xsec.nodeid),
        xsec_coords=xsec.geometry_coords,
        interval=interval,
        resolved=interval is not None,
        method=str(method),
        reason=str(reason),
        interval_count=int(len(intervals)),
    )


def build_final_road(
    *,
    patch_id: str,
    segment: Segment,
    identity: CorridorIdentity,
    witness: CorridorWitness | None,
    src_slot: SlotInterval,
    dst_slot: SlotInterval,
    inputs: Any,
    prior_roads: list[Any],
    params: dict[str, Any],
    arc_row: dict[str, Any] | None = None,
    prior_index: dict[tuple[int, int], list[Any]] | None = None,
    divstrip_buffer: Any | None = None,
) -> tuple[FinalRoad | None, dict[str, Any]]:
    pipeline = _pipeline()
    bridge_retained = bool(segment.bridge_candidate_retained)
    result = {
        "segment_id": str(segment.segment_id),
        "corridor_state": str(identity.state),
        "shape_ref_mode": "",
        "shape_ref_coords": [],
        "candidate_attempts": [],
        "drivezone_ratio": 0.0,
        "divstrip_overlap_ratio": 0.0,
        "road_intersects_divstrip": False,
        "reason": "",
        "bridge_candidate_retained": bool(bridge_retained),
        "bridge_chain_nodes": [int(v) for v in segment.bridge_chain_nodes],
        "bridge_chain_source": str(segment.bridge_chain_source),
        "bridge_decision_stage": str(segment.bridge_decision_stage),
        "bridge_decision_reason": str(segment.bridge_decision_reason),
        "topology_arc_id": str(segment.topology_arc_id),
        "topology_arc_source_type": str(segment.topology_arc_source_type),
        "topology_arc_is_direct_legal": bool(segment.topology_arc_is_direct_legal),
        "topology_arc_is_unique": bool(segment.topology_arc_is_unique),
        "production_multi_arc_allowed": bool(segment.production_multi_arc_allowed),
        "multi_arc_evidence_mode": str(segment.multi_arc_evidence_mode),
        "multi_arc_structure_type": str(segment.multi_arc_structure_type),
        "multi_arc_rule_reason": str(segment.multi_arc_rule_reason),
        "blocked_diagnostic_only": bool(segment.blocked_diagnostic_only),
        "controlled_entry_allowed": bool(segment.controlled_entry_allowed),
        "hard_block_reason": str(segment.hard_block_reason),
        "topology_gap_decision": str(segment.topology_gap_decision),
        "topology_gap_reason": str(segment.topology_gap_reason),
        "reject_stage": "",
    }
    final_gate_reason = ""
    has_topology_assignment = bool(
        str(segment.topology_arc_id)
        or str(segment.topology_arc_source_type)
        or len(segment.topology_arc_node_path) > 0
    )
    if str(segment.topology_arc_source_type) == pipeline._BRIDGE_CHAIN_TOPOLOGY_SOURCE:
        final_gate_reason = "final_gate_synthetic_arc_not_allowed"
    elif has_topology_assignment and not bool(segment.topology_arc_is_direct_legal):
        final_gate_reason = "final_gate_not_direct_legal"
    elif has_topology_assignment and not bool(segment.topology_arc_is_unique) and not bool(segment.production_multi_arc_allowed):
        final_gate_reason = "final_gate_non_unique_arc"
    elif has_topology_assignment and not str(segment.topology_arc_id):
        final_gate_reason = "final_gate_arc_unique_connectivity_violation"
    elif bool(segment.blocked_diagnostic_only) and not bool(segment.controlled_entry_allowed):
        final_gate_reason = "final_gate_blocked_diagnostic_only"
    elif str(segment.hard_block_reason):
        final_gate_reason = "final_gate_hard_blocked"
    if final_gate_reason:
        result["reason"] = str(final_gate_reason)
        result["reject_stage"] = "final_build_gate"
        return None, result
    if str(identity.state) == "unresolved":
        result["bridge_decision_stage"] = "bridge_final_decision" if bridge_retained else str(result["bridge_decision_stage"])
        result["bridge_decision_reason"] = "bridge_corridor_insufficient" if bridge_retained else str(result["bridge_decision_reason"])
        result["reason"] = "bridge_corridor_insufficient" if bridge_retained else str(identity.reason)
        return None, result
    if src_slot.interval is None or dst_slot.interval is None:
        fallback_shape_ref, fallback_mode = shape_ref_line(
            segment=segment,
            identity=identity,
            witness=witness,
            src_slot=src_slot,
            dst_slot=dst_slot,
            prior_roads=prior_roads,
            prior_index=prior_index,
        )
        result["shape_ref_mode"] = str(fallback_mode)
        result["shape_ref_coords"] = [[float(x), float(y)] for x, y in line_to_coords(fallback_shape_ref)]
        result["bridge_decision_stage"] = "bridge_final_decision" if bridge_retained else str(result["bridge_decision_stage"])
        result["bridge_decision_reason"] = "bridge_slot_not_established" if bridge_retained else str(result["bridge_decision_reason"])
        result["reason"] = "bridge_slot_not_established" if bridge_retained else "slot_unresolved"
        return None, result
    start_pt = pipeline._midpoint_of_interval(src_slot.interval)
    end_pt = pipeline._midpoint_of_interval(dst_slot.interval)
    preferred_line, preferred_mode = shape_ref_line(
        segment=segment,
        identity=identity,
        witness=witness,
        src_slot=src_slot,
        dst_slot=dst_slot,
        prior_roads=prior_roads,
        prior_index=prior_index,
    )
    candidate_lines: list[tuple[LineString, str]] = [(preferred_line, str(preferred_mode))]
    _append_side_constrained_candidates(
        candidate_lines,
        preferred_line,
        str(preferred_mode),
        start_pt=start_pt,
        end_pt=end_pt,
        prefer_early=True,
    )
    if str(identity.state) == "witness_based":
        legacy_centerline = _legacy_witness_centerline(witness=witness, start_pt=start_pt, end_pt=end_pt)
        _append_candidate_line(candidate_lines, legacy_centerline, "witness_centerline")
        _append_side_constrained_candidates(
            candidate_lines,
            legacy_centerline,
            "witness_centerline",
            start_pt=start_pt,
            end_pt=end_pt,
        )
    support_reference_line = _line_from_coords(list((arc_row or {}).get("support_reference_coords", [])))
    if support_reference_line is not None:
        support_anchor = _anchor_along_base_line(support_reference_line, start_pt, end_pt)
        _append_candidate_line(candidate_lines, support_anchor, "traj_support_slot_anchored")
        _append_side_constrained_candidates(
            candidate_lines,
            support_anchor,
            "traj_support_slot_anchored",
            start_pt=start_pt,
            end_pt=end_pt,
        )
    segment_projected = _anchor_along_base_line(segment.geometry_metric(), start_pt, end_pt)
    _append_candidate_line(candidate_lines, segment_projected, "segment_support_projected_anchored")
    _append_side_constrained_candidates(
        candidate_lines,
        segment_projected,
        "segment_support_projected_anchored",
        start_pt=start_pt,
        end_pt=end_pt,
    )
    segment_anchor = _replace_endpoints(segment.geometry_metric(), start_pt, end_pt)
    if not segment_anchor.equals(preferred_line):
        _append_candidate_line(candidate_lines, segment_anchor, "segment_support_slot_anchored")
    prior_line = find_prior_reference_line(segment, prior_roads, prior_index=prior_index)
    if prior_line is not None:
        prior_projected = _anchor_along_base_line(prior_line, start_pt, end_pt)
        _append_candidate_line(
            candidate_lines,
            prior_projected,
            "prior_reference_projected_anchored",
            priority=str(identity.state) == "prior_based",
        )
        _append_side_constrained_candidates(
            candidate_lines,
            prior_projected,
            "prior_reference_projected_anchored",
            start_pt=start_pt,
            end_pt=end_pt,
            prefer_early=str(identity.state) == "prior_based",
        )
        prior_anchor = _replace_endpoints(prior_line, start_pt, end_pt)
        _append_candidate_line(
            candidate_lines,
            prior_anchor,
            "prior_reference_slot_anchored",
            priority=str(identity.state) == "prior_based",
        )
    attempts: list[dict[str, Any]] = []
    selected_candidate: tuple[LineString, str, float, float, bool] | None = None
    best_candidate: tuple[LineString, str, float, float, bool] | None = None
    attempted_side_constrained = False
    for line, mode in candidate_lines:
        drivezone_ratio = pipeline._drivezone_ratio(line, inputs.drivezone_zone_metric)
        divstrip_overlap_ratio = _line_overlap_ratio(line, divstrip_buffer)
        road_intersects_divstrip = bool(
            divstrip_buffer is not None and (not divstrip_buffer.is_empty) and line.intersects(divstrip_buffer)
        )
        attempted_side_constrained = attempted_side_constrained or ("side_constrained" in str(mode))
        attempts.append(
            {
                "mode": str(mode),
                "drivezone_ratio": float(drivezone_ratio),
                "divstrip_overlap_ratio": float(divstrip_overlap_ratio),
                "road_intersects_divstrip": bool(road_intersects_divstrip),
            }
        )
        candidate = (line, str(mode), float(drivezone_ratio), float(divstrip_overlap_ratio), bool(road_intersects_divstrip))
        if best_candidate is None or (
            int(not road_intersects_divstrip),
            float(-divstrip_overlap_ratio),
            float(drivezone_ratio),
        ) > (
            int(not best_candidate[4]),
            float(-best_candidate[3]),
            float(best_candidate[2]),
        ):
            best_candidate = candidate
        if drivezone_ratio >= float(params["ROAD_MIN_DRIVEZONE_RATIO"]) and not road_intersects_divstrip:
            selected_candidate = candidate
            break
    chosen_line, chosen_mode, drivezone_ratio, divstrip_overlap_ratio, road_intersects_divstrip = selected_candidate or best_candidate or (
        preferred_line,
        str(preferred_mode),
        0.0,
        0.0,
        False,
    )
    result["candidate_attempts"] = attempts
    result["shape_ref_mode"] = str(chosen_mode)
    result["shape_ref_coords"] = [[float(x), float(y)] for x, y in line_to_coords(chosen_line)]
    result["drivezone_ratio"] = float(drivezone_ratio)
    result["divstrip_overlap_ratio"] = float(divstrip_overlap_ratio)
    result["road_intersects_divstrip"] = bool(road_intersects_divstrip)
    if selected_candidate is None:
        if road_intersects_divstrip:
            result["reason"] = (
                "bridge_divstrip_conflict_after_side_constrained_generation"
                if bridge_retained and attempted_side_constrained
                else "bridge_divstrip_conflict"
                if bridge_retained
                else "road_crosses_divstrip_after_side_constrained_generation"
                if attempted_side_constrained
                else "road_crosses_divstrip"
            )
            if bridge_retained:
                result["bridge_decision_stage"] = "bridge_final_decision"
                result["bridge_decision_reason"] = str(result["reason"])
        else:
            unresolved_reason = "bridge_prior_discontinuous" if bridge_retained and str(identity.state) == "prior_based" else (
                "bridge_corridor_insufficient" if bridge_retained else "road_outside_drivezone"
            )
            result["reason"] = str(unresolved_reason)
            if bridge_retained:
                result["bridge_decision_stage"] = "bridge_final_decision"
                result["bridge_decision_reason"] = str(unresolved_reason)
        return None, result
    road = FinalRoad(
        road_id=f"{patch_id}_{segment.segment_id}",
        segment_id=str(segment.segment_id),
        src_nodeid=int(segment.src_nodeid),
        dst_nodeid=int(segment.dst_nodeid),
        corridor_state=str(identity.state),
        line_coords=line_to_coords(chosen_line),
        length_m=float(chosen_line.length),
        support_traj_count=int(len(segment.support_traj_ids)),
        dedup_count=int(segment.dedup_count),
        risk_flags=tuple(str(v) for v in identity.risk_flags),
    )
    result["reason"] = "built"
    if bridge_retained:
        result["bridge_decision_stage"] = "bridge_final_decision"
        result["bridge_decision_reason"] = "built"
    return road, result


def classify_segment_outcome(
    *,
    identity: CorridorIdentity,
    src_slot: SlotInterval,
    dst_slot: SlotInterval,
    build_result: dict[str, Any],
    road: FinalRoad | None,
) -> str:
    pipeline = _pipeline()
    if road is not None or str(build_result.get("reason", "")) == "built":
        return "built"
    if (
        str(build_result.get("reason", "")) in (pipeline._SEGMENT_TOPOLOGY_INVALID_REASONS | {"arc_unique_connectivity_violation"})
        or str(build_result.get("reason", "")).startswith("final_gate_")
    ):
        return "arc_legality_rejected"
    if bool(build_result.get("bridge_candidate_retained", False)) and str(build_result.get("reason", "")).startswith("bridge_"):
        return "bridge_aware_unresolved"
    if str(identity.state) == "unresolved":
        return "unresolved_corridor"
    if (not bool(src_slot.resolved)) or (not bool(dst_slot.resolved)) or str(build_result.get("reason", "")) == "slot_unresolved":
        return "slot_mapping_failed"
    if str(build_result.get("reason", "")) in {"road_outside_drivezone", "road_crosses_divstrip"}:
        return "final_geometry_invalid"
    return "should_be_no_geometry_candidate"


def _finalize_full_legal_arc_registry(
    *,
    patch_id: str,
    registry_rows: list[dict[str, Any]],
    metrics_segments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    metrics_by_segment = {str(item.get("segment_id", "")): dict(item) for item in metrics_segments if str(item.get("segment_id", ""))}
    finalized_rows: list[dict[str, Any]] = []
    for row in registry_rows:
        current = dict(row)
        current["patch_id"] = str(patch_id)
        segment_id = str(current.get("working_segment_id", "") or current.get("segment_id", ""))
        metric = metrics_by_segment.get(segment_id, {})
        if metric:
            built = str(metric.get("failure_classification", "")) == "built"
            current["corridor_identity"] = str(metric.get("corridor_identity", current.get("corridor_identity", "unresolved")))
            current["slot_src_resolved"] = bool(metric.get("src_slot_resolved", False))
            current["slot_dst_resolved"] = bool(metric.get("dst_slot_resolved", False))
            current["slot_status"] = "resolved" if bool(metric.get("src_slot_resolved", False) and metric.get("dst_slot_resolved", False)) else "unresolved"
            current["built_final_road"] = bool(built)
            if built:
                current["unbuilt_stage"] = ""
                current["unbuilt_reason"] = ""
            elif bool(current.get("blocked_diagnostic_only", False)) and not bool(current.get("controlled_entry_allowed", False)):
                current["unbuilt_stage"] = "hard_blocked"
                current["unbuilt_reason"] = str(current.get("blocked_diagnostic_reason", "") or "blocked_diagnostic_only")
            elif str(current.get("hard_block_reason", "")):
                current["unbuilt_stage"] = "hard_blocked"
                current["unbuilt_reason"] = str(current.get("hard_block_reason", ""))
            elif str(current.get("traj_support_type", "")) == "no_support" and str(current.get("prior_support_type", "")) == "no_support":
                current["unbuilt_stage"] = "step3_no_support"
                current["unbuilt_reason"] = "no_traj_support"
            elif str(current.get("corridor_identity", "")) == "unresolved":
                current["unbuilt_stage"] = "step3_corridor_unresolved"
                current["unbuilt_reason"] = str(metric.get("corridor_reason") or metric.get("unresolved_reason") or current.get("corridor_reason", "corridor_identity_unresolved"))
            elif not bool(metric.get("src_slot_resolved", False) and metric.get("dst_slot_resolved", False)):
                current["unbuilt_stage"] = "step4_slot_not_established"
                current["unbuilt_reason"] = "slot_not_established"
            else:
                current["unbuilt_stage"] = "step5_geometry_rejected"
                current["unbuilt_reason"] = str(metric.get("unresolved_reason") or metric.get("failure_classification") or "final_geometry_rejected")
        else:
            if bool(current.get("blocked_diagnostic_only", False)) and not bool(current.get("controlled_entry_allowed", False)):
                current["unbuilt_stage"] = "hard_blocked"
                current["unbuilt_reason"] = str(current.get("blocked_diagnostic_reason", "") or "blocked_diagnostic_only")
            elif str(current.get("hard_block_reason", "")):
                current["unbuilt_stage"] = "hard_blocked"
                current["unbuilt_reason"] = str(current.get("hard_block_reason", ""))
            elif bool(current.get("entered_main_flow", False)):
                current["unbuilt_stage"] = "step2_not_entered" if not str(current.get("working_segment_id", "")) else "step3_no_support"
                current["unbuilt_reason"] = str(current.get("unbuilt_reason", "") or "no_traj_support")
        finalized_rows.append(current)

    entered_rows = [row for row in finalized_rows if bool(row.get("entered_main_flow", False))]
    funnel = {
        "all_direct_legal_arc_count": int(len(finalized_rows)),
        "all_direct_unique_legal_arc_count": int(sum(1 for row in finalized_rows if bool(row.get("is_unique", False)))),
        "entered_main_flow_arc_count": int(len(entered_rows)),
        "traj_supported_arc_count": int(sum(1 for row in entered_rows if str(row.get("traj_support_type", "")) != "no_support")),
        "prior_supported_arc_count": int(sum(1 for row in entered_rows if str(row.get("prior_support_type", "")) == "prior_fallback_support")),
        "corridor_resolved_arc_count": int(sum(1 for row in entered_rows if str(row.get("corridor_identity", "")) in {"witness_based", "prior_based"})),
        "slot_established_arc_count": int(sum(1 for row in entered_rows if bool(row.get("slot_src_resolved", False) and row.get("slot_dst_resolved", False)))),
        "built_arc_count": int(sum(1 for row in entered_rows if bool(row.get("built_final_road", False)))),
    }
    return finalized_rows, funnel


def write_road_outputs(
    *,
    out_root: Path | str,
    run_id: str,
    patch_id: str,
    segments: list[Segment],
    identities: dict[str, CorridorIdentity],
    witnesses: dict[str, CorridorWitness],
    slots: dict[str, dict[str, SlotInterval]],
    roads: list[FinalRoad],
    road_results: list[dict[str, Any]],
    inputs: Any,
    step2_metrics: dict[str, Any] | None = None,
    full_registry_rows: list[dict[str, Any]] | None = None,
    legal_arc_funnel_seed: dict[str, Any] | None = None,
    arc_evidence_attach_audit: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
) -> None:
    pipeline = _pipeline()
    patch_geometry_cache = build_patch_geometry_cache(inputs, params or pipeline.DEFAULT_PARAMS)
    divstrip_buffer = patch_geometry_cache.get("divstrip_buffer")
    patch_dir = pipeline.patch_root(out_root, run_id, patch_id)
    dbg_dir = pipeline.debug_dir(out_root, run_id, patch_id)
    road_features: list[tuple[LineString, dict[str, Any]]] = []
    shape_ref_features: list[tuple[LineString, dict[str, Any]]] = []
    metrics_segments: list[dict[str, Any]] = []
    hard_breakpoints: list[dict[str, Any]] = []
    soft_breakpoints: list[dict[str, Any]] = []
    road_trace_entries: list[dict[str, Any]] = []
    bridge_trial_entries: list[dict[str, Any]] = []
    road_map = {str(road.segment_id): road for road in roads}
    result_map = {str(item["segment_id"]): item for item in road_results}
    for segment in segments:
        identity = identities[str(segment.segment_id)]
        witness = witnesses.get(str(segment.segment_id))
        src_slot = slots[str(segment.segment_id)]["src"]
        dst_slot = slots[str(segment.segment_id)]["dst"]
        build_result = result_map.get(str(segment.segment_id), {})
        shape_ref_coords = build_result.get("shape_ref_coords") or [[float(x), float(y)] for x, y in segment.geometry_coords]
        shape_ref_line = pipeline.coords_to_line(tuple((float(x), float(y)) for x, y in shape_ref_coords))
        failure_classification = classify_segment_outcome(
            identity=identity,
            src_slot=src_slot,
            dst_slot=dst_slot,
            build_result=build_result,
            road=road_map.get(str(segment.segment_id)),
        )
        shape_ref_features.append(
            (
                shape_ref_line,
                {
                    "segment_id": str(segment.segment_id),
                    "src_nodeid": int(segment.src_nodeid),
                    "dst_nodeid": int(segment.dst_nodeid),
                    "corridor_state": str(identity.state),
                    "shape_ref_mode": str(build_result.get("shape_ref_mode", "segment_support")),
                    "no_geometry_candidate": bool(str(build_result.get("reason", "")) != "built"),
                    "no_geometry_reason": str(build_result.get("reason", "")),
                    "topology_arc_id": str(segment.topology_arc_id),
                    "topology_arc_source_type": str(segment.topology_arc_source_type),
                    "topology_arc_is_direct_legal": bool(segment.topology_arc_is_direct_legal),
                    "topology_arc_is_unique": bool(segment.topology_arc_is_unique),
                    "production_multi_arc_allowed": bool(segment.production_multi_arc_allowed),
                    "multi_arc_evidence_mode": str(segment.multi_arc_evidence_mode),
                    "multi_arc_structure_type": str(segment.multi_arc_structure_type),
                    "multi_arc_rule_reason": str(segment.multi_arc_rule_reason),
                    "blocked_diagnostic_only": bool(segment.blocked_diagnostic_only),
                    "controlled_entry_allowed": bool(segment.controlled_entry_allowed),
                    "hard_block_reason": str(segment.hard_block_reason),
                    "topology_gap_decision": str(segment.topology_gap_decision),
                    "topology_gap_reason": str(segment.topology_gap_reason),
                    "bridge_candidate_retained": bool(segment.bridge_candidate_retained),
                    "bridge_chain_exists": bool(segment.bridge_chain_exists),
                    "bridge_chain_unique": bool(segment.bridge_chain_unique),
                    "bridge_chain_nodes": [int(v) for v in segment.bridge_chain_nodes],
                    "bridge_chain_source": str(segment.bridge_chain_source),
                    "bridge_diagnostic_reason": str(segment.bridge_diagnostic_reason),
                    "bridge_decision_stage": str(build_result.get("bridge_decision_stage", segment.bridge_decision_stage)),
                    "bridge_decision_reason": str(build_result.get("bridge_decision_reason", segment.bridge_decision_reason)),
                    "failure_classification": str(failure_classification),
                },
            )
        )
        road = road_map.get(str(segment.segment_id))
        endpoint_dist_to_slot = {"src": None, "dst": None}
        endpoint_dist_to_xsec = {"src": None, "dst": None}
        road_in_drivezone = False
        road_in_drivezone_ratio = float(build_result.get("drivezone_ratio", 0.0) or 0.0)
        road_crosses_divstrip = bool(build_result.get("road_intersects_divstrip", False))
        if road is not None:
            road_line = road.geometry_metric()
            road_in_drivezone_ratio = float(pipeline._drivezone_ratio(road_line, inputs.drivezone_zone_metric))
            road_in_drivezone = road_in_drivezone_ratio >= 0.999
            road_crosses_divstrip = bool(divstrip_buffer is not None and (not divstrip_buffer.is_empty) and road_line.intersects(divstrip_buffer))
            if src_slot.interval is not None:
                endpoint_dist_to_slot["src"] = float(Point(road_line.coords[0][:2]).distance(src_slot.interval.geometry_metric()))
                endpoint_dist_to_xsec["src"] = float(Point(road_line.coords[0][:2]).distance(src_slot.xsec_metric()))
            if dst_slot.interval is not None:
                endpoint_dist_to_slot["dst"] = float(Point(road_line.coords[-1][:2]).distance(dst_slot.interval.geometry_metric()))
                endpoint_dist_to_xsec["dst"] = float(Point(road_line.coords[-1][:2]).distance(dst_slot.xsec_metric()))
            road_features.append(
                (
                    road_line,
                    {
                        "road_id": str(road.road_id),
                        "segment_id": str(road.segment_id),
                        "src_nodeid": int(road.src_nodeid),
                        "dst_nodeid": int(road.dst_nodeid),
                        "corridor_state": str(road.corridor_state),
                        "length_m": float(road.length_m),
                        "support_traj_count": int(road.support_traj_count),
                        "dedup_count": int(road.dedup_count),
                        "risk_flags": list(road.risk_flags),
                        "road_in_drivezone_ratio": float(road_in_drivezone_ratio),
                        "road_intersects_divstrip": bool(road_crosses_divstrip),
                        "topology_arc_id": str(segment.topology_arc_id),
                        "topology_arc_source_type": str(segment.topology_arc_source_type),
                        "topology_arc_is_direct_legal": bool(segment.topology_arc_is_direct_legal),
                        "topology_arc_is_unique": bool(segment.topology_arc_is_unique),
                        "production_multi_arc_allowed": bool(segment.production_multi_arc_allowed),
                        "multi_arc_evidence_mode": str(segment.multi_arc_evidence_mode),
                        "multi_arc_structure_type": str(segment.multi_arc_structure_type),
                        "multi_arc_rule_reason": str(segment.multi_arc_rule_reason),
                        "blocked_diagnostic_only": bool(segment.blocked_diagnostic_only),
                        "controlled_entry_allowed": bool(segment.controlled_entry_allowed),
                        "hard_block_reason": str(segment.hard_block_reason),
                        "topology_gap_decision": str(segment.topology_gap_decision),
                        "topology_gap_reason": str(segment.topology_gap_reason),
                        "bridge_candidate_retained": bool(segment.bridge_candidate_retained),
                        "bridge_chain_exists": bool(segment.bridge_chain_exists),
                        "bridge_chain_unique": bool(segment.bridge_chain_unique),
                        "bridge_chain_nodes": [int(v) for v in segment.bridge_chain_nodes],
                        "bridge_chain_source": str(segment.bridge_chain_source),
                        "bridge_diagnostic_reason": str(segment.bridge_diagnostic_reason),
                        "bridge_decision_stage": str(build_result.get("bridge_decision_stage", segment.bridge_decision_stage)),
                        "bridge_decision_reason": str(build_result.get("bridge_decision_reason", segment.bridge_decision_reason)),
                        "failure_classification": "built",
                    },
                )
            )
        unresolved_reason = ""
        if road is None:
            unresolved_reason = str(build_result.get("reason") or identity.reason)
        road_trace_entries.append(
            {
                "segment_id": str(segment.segment_id),
                "corridor_identity_state": str(identity.state),
                "src_slot_status": "resolved" if bool(src_slot.resolved) else "unresolved",
                "dst_slot_status": "resolved" if bool(dst_slot.resolved) else "unresolved",
                "chosen_shape_ref_mode": str(build_result.get("shape_ref_mode", "")),
                "candidate_attempts": list(build_result.get("candidate_attempts") or []),
                "drivezone_ratio": float(build_result.get("drivezone_ratio", 0.0) or 0.0),
                "road_intersects_divstrip": bool(build_result.get("road_intersects_divstrip", False)),
                "final_reason": str(build_result.get("reason", "")),
                "final_decision": "selected" if road is not None else "rejected",
                "topology_arc_id": str(segment.topology_arc_id),
                "topology_arc_source_type": str(segment.topology_arc_source_type),
                "topology_arc_is_direct_legal": bool(segment.topology_arc_is_direct_legal),
                "topology_arc_is_unique": bool(segment.topology_arc_is_unique),
                "production_multi_arc_allowed": bool(segment.production_multi_arc_allowed),
                "multi_arc_evidence_mode": str(segment.multi_arc_evidence_mode),
                "multi_arc_structure_type": str(segment.multi_arc_structure_type),
                "multi_arc_rule_reason": str(segment.multi_arc_rule_reason),
                "blocked_diagnostic_only": bool(segment.blocked_diagnostic_only),
                "controlled_entry_allowed": bool(segment.controlled_entry_allowed),
                "hard_block_reason": str(segment.hard_block_reason),
                "topology_gap_decision": str(segment.topology_gap_decision),
                "topology_gap_reason": str(segment.topology_gap_reason),
                "bridge_candidate_retained": bool(segment.bridge_candidate_retained),
                "bridge_chain_exists": bool(segment.bridge_chain_exists),
                "bridge_chain_unique": bool(segment.bridge_chain_unique),
                "bridge_chain_nodes": [int(v) for v in segment.bridge_chain_nodes],
                "bridge_chain_source": str(segment.bridge_chain_source),
                "bridge_diagnostic_reason": str(segment.bridge_diagnostic_reason),
                "bridge_decision_stage": str(build_result.get("bridge_decision_stage", segment.bridge_decision_stage)),
                "bridge_decision_reason": str(build_result.get("bridge_decision_reason", segment.bridge_decision_reason)),
                "failure_classification": str(failure_classification),
            }
        )
        metrics_entry = {
            "segment_id": str(segment.segment_id),
            "segment_established": True,
            "src_nodeid": int(segment.src_nodeid),
            "dst_nodeid": int(segment.dst_nodeid),
            "support_count": int(segment.support_count),
            "same_pair_rank": None if segment.same_pair_rank is None else int(segment.same_pair_rank),
            "segment_kept_reason": str(segment.kept_reason),
            "other_xsec_crossing_count": int(segment.other_xsec_crossing_count),
            "corridor_identity": str(identity.state),
            "corridor_identity_state": str(identity.state),
            "corridor_reason": str(identity.reason),
            "has_exclusive_interval": bool(witness.exclusive_interval) if witness is not None else False,
            "witness_stability_score": 0.0 if witness is None else float(witness.stability_score),
            "src_slot_resolved": bool(src_slot.resolved),
            "dst_slot_resolved": bool(dst_slot.resolved),
            "slot_src_status": "resolved" if bool(src_slot.resolved) else "unresolved",
            "slot_dst_status": "resolved" if bool(dst_slot.resolved) else "unresolved",
            "slot_src_reason": str(src_slot.reason),
            "slot_dst_reason": str(dst_slot.reason),
            "endpoint_dist_to_slot": endpoint_dist_to_slot,
            "endpoint_dist_to_xsec": endpoint_dist_to_xsec,
            "endpoint_dist_to_slot_src": endpoint_dist_to_slot["src"],
            "endpoint_dist_to_slot_dst": endpoint_dist_to_slot["dst"],
            "road_in_drivezone": bool(road_in_drivezone),
            "road_in_drivezone_ratio": float(road_in_drivezone_ratio),
            "road_crosses_divstrip": bool(road_crosses_divstrip),
            "road_intersects_divstrip": bool(road_crosses_divstrip),
            "shape_ref_mode": str(build_result.get("shape_ref_mode", "")),
            "no_geometry_candidate": bool(road is None),
            "no_geometry_candidate_reason": str(unresolved_reason),
            "unresolved_reason": str(unresolved_reason),
            "topology_arc_id": str(segment.topology_arc_id),
            "topology_arc_source_type": str(segment.topology_arc_source_type),
            "topology_arc_is_direct_legal": bool(segment.topology_arc_is_direct_legal),
            "topology_arc_is_unique": bool(segment.topology_arc_is_unique),
            "production_multi_arc_allowed": bool(segment.production_multi_arc_allowed),
            "multi_arc_evidence_mode": str(segment.multi_arc_evidence_mode),
            "multi_arc_structure_type": str(segment.multi_arc_structure_type),
            "multi_arc_rule_reason": str(segment.multi_arc_rule_reason),
            "blocked_diagnostic_only": bool(segment.blocked_diagnostic_only),
            "controlled_entry_allowed": bool(segment.controlled_entry_allowed),
            "hard_block_reason": str(segment.hard_block_reason),
            "topology_gap_decision": str(segment.topology_gap_decision),
            "topology_gap_reason": str(segment.topology_gap_reason),
            "bridge_candidate_retained": bool(segment.bridge_candidate_retained),
            "bridge_chain_exists": bool(segment.bridge_chain_exists),
            "bridge_chain_unique": bool(segment.bridge_chain_unique),
            "bridge_chain_nodes": [int(v) for v in segment.bridge_chain_nodes],
            "bridge_chain_source": str(segment.bridge_chain_source),
            "bridge_diagnostic_reason": str(segment.bridge_diagnostic_reason),
            "bridge_decision_stage": str(build_result.get("bridge_decision_stage", segment.bridge_decision_stage)),
            "bridge_decision_reason": str(build_result.get("bridge_decision_reason", segment.bridge_decision_reason)),
            "reject_stage": str(build_result.get("reject_stage", "")),
            "failure_classification": str(failure_classification),
        }
        metrics_segments.append(metrics_entry)
        if bool(segment.bridge_candidate_retained):
            bridge_trial_entries.append(
                {
                    "segment_id": str(segment.segment_id),
                    "src_nodeid": int(segment.src_nodeid),
                    "dst_nodeid": int(segment.dst_nodeid),
                    "pair_id": pipeline._pair_id_text(int(segment.src_nodeid), int(segment.dst_nodeid)),
                    "bridge_candidate_retained": True,
                    "bridge_chain_nodes": [int(v) for v in segment.bridge_chain_nodes],
                    "bridge_chain_source": str(segment.bridge_chain_source),
                    "bridge_decision_stage": str(build_result.get("bridge_decision_stage", segment.bridge_decision_stage)),
                    "bridge_decision_reason": str(build_result.get("bridge_decision_reason", segment.bridge_decision_reason)),
                    "corridor_identity_state": str(identity.state),
                    "src_slot_resolved": bool(src_slot.resolved),
                    "dst_slot_resolved": bool(dst_slot.resolved),
                    "shape_ref_mode": str(build_result.get("shape_ref_mode", "")),
                    "built_final_road": bool(road is not None),
                    "failure_classification": str(failure_classification),
                    "final_reason": str(build_result.get("reason", "")),
                }
            )
        if road is None:
            hard_breakpoints.append({"segment_id": str(segment.segment_id), "reason": str(unresolved_reason or "no_geometry_candidate"), "severity": "hard"})
        elif identity.state == "prior_based":
            soft_breakpoints.append({"segment_id": str(segment.segment_id), "reason": "prior_based_fallback", "severity": "soft"})
    witness_selected_total = int(sum(1 for witness in witnesses.values() if str(witness.status) == "selected"))
    witness_selected_cross0 = int(
        sum(
            1
            for segment in segments
            if str(witnesses.get(str(segment.segment_id), make_missing_witness(segment)).status) == "selected"
            and int(segment.other_xsec_crossing_count) == 0
        )
    )
    witness_selected_cross1 = int(
        sum(
            1
            for segment in segments
            if str(witnesses.get(str(segment.segment_id), make_missing_witness(segment)).status) == "selected"
            and int(segment.other_xsec_crossing_count) == 1
        )
    )
    root_step2_metrics = dict(step2_metrics or {})
    no_geometry_entries = [entry for entry in metrics_segments if bool(entry["no_geometry_candidate"])]
    no_geometry_reason_hist = dict(Counter(str(entry["no_geometry_candidate_reason"] or "unknown") for entry in no_geometry_entries))
    failure_classification_hist = dict(
        Counter(
            str(entry["failure_classification"])
            for entry in metrics_segments
            if str(entry["failure_classification"]) != "built"
        )
    )
    no_geometry_reason = ""
    if no_geometry_reason_hist:
        no_geometry_reason = next(iter(no_geometry_reason_hist.keys())) if len(no_geometry_reason_hist) == 1 else "multiple"
    production_arc_violation_entries = [
        entry
        for entry in metrics_segments
        if (
            bool(entry["topology_arc_id"] or entry["topology_arc_source_type"])
            and (
                (not bool(entry["topology_arc_is_direct_legal"]))
                or (
                    (not bool(entry["topology_arc_is_unique"]))
                    and not bool(entry.get("production_multi_arc_allowed", False))
                )
            )
        )
    ]
    synthetic_production_arc_entries = [
        entry
        for entry in metrics_segments
        if str(entry["topology_arc_source_type"]) == pipeline._BRIDGE_CHAIN_TOPOLOGY_SOURCE
    ]
    legal_arc_registry, legal_arc_funnel = _finalize_full_legal_arc_registry(
        patch_id=str(patch_id),
        registry_rows=list(full_registry_rows or []),
        metrics_segments=metrics_segments,
    )
    if legal_arc_funnel_seed:
        legal_arc_funnel = {**dict(legal_arc_funnel_seed), **dict(legal_arc_funnel)}
    metrics = {
        "patch_id": str(patch_id),
        "segment_count": int(len(segments)),
        "road_count": int(len(roads)),
        "unresolved_segment_count": int(sum(1 for entry in metrics_segments if entry["unresolved_reason"])),
        "no_geometry_candidate_count": int(len(no_geometry_entries)),
        "no_geometry_candidate_reason": str(no_geometry_reason),
        "no_geometry_candidate_reasons": no_geometry_reason_hist,
        "failure_classification_hist": failure_classification_hist,
        "raw_candidate_count": int(root_step2_metrics.get("raw_candidate_count", 0)),
        "candidate_count_after_pairing": int(root_step2_metrics.get("candidate_count_after_pairing", 0)),
        "candidate_count_after_topology_gate": int(root_step2_metrics.get("candidate_count_after_topology_gate", 0)),
        "candidate_count_after_cross_filter": int(root_step2_metrics.get("candidate_count_after_cross_filter", 0)),
        "candidate_count_after_same_pair_topk": int(root_step2_metrics.get("candidate_count_after_same_pair_topk", len(segments))),
        "segment_selected_count_before_topology_gate": int(root_step2_metrics.get("segment_selected_count_before_topology_gate", 0)),
        "segment_selected_count_after_topology_gate": int(root_step2_metrics.get("segment_selected_count_after_topology_gate", 0)),
        "crossing_dist_hist_raw": dict(root_step2_metrics.get("crossing_dist_hist_raw", {})),
        "crossing_dist_hist_selected": dict(root_step2_metrics.get("crossing_dist_hist_selected", {})),
        "traj_crossing_raw_count": int(root_step2_metrics.get("traj_crossing_raw_count", 0)),
        "traj_crossing_filtered_count": int(root_step2_metrics.get("traj_crossing_filtered_count", 0)),
        "unanchored_prior_conflict_segment_count": int(root_step2_metrics.get("unanchored_prior_conflict_segment_count", 0)),
        "directed_path_not_supported_count": int(root_step2_metrics.get("directed_path_not_supported_count", 0)),
        "trace_only_reachability_segment_count": int(root_step2_metrics.get("trace_only_reachability_segment_count", 0)),
        "terminal_owner_mismatch_segment_count": int(root_step2_metrics.get("terminal_owner_mismatch_segment_count", 0)),
        "ambiguous_terminal_owner_segment_count": int(root_step2_metrics.get("ambiguous_terminal_owner_segment_count", 0)),
        "directionally_invalid_segment_count": int(root_step2_metrics.get("directionally_invalid_segment_count", 0)),
        "topology_invalid_segment_count": int(root_step2_metrics.get("topology_invalid_segment_count", 0)),
        "terminal_node_invalid_segment_count": int(root_step2_metrics.get("terminal_node_invalid_segment_count", 0)),
        "same_pair_hist": dict(root_step2_metrics.get("same_pair_hist", {})),
        "pair_count": int(root_step2_metrics.get("pair_count", 0)),
        "pairs_with_multi_segments": int(root_step2_metrics.get("pairs_with_multi_segments", 0)),
        "max_segments_per_pair": int(root_step2_metrics.get("max_segments_per_pair", 0)),
        "pair_scoped_cross1_exception_enabled": bool(root_step2_metrics.get("pair_scoped_cross1_exception_enabled", False)),
        "pair_scoped_cross1_exception_hit_count": int(root_step2_metrics.get("pair_scoped_cross1_exception_hit_count", 0)),
        "selected_cross1_exception_count": int(root_step2_metrics.get("selected_cross1_exception_count", 0)),
        "bridge_retained_segment_count": int(root_step2_metrics.get("bridge_retained_segment_count", 0)),
        "bridge_retained_pair_ids": [str(v) for v in root_step2_metrics.get("bridge_retained_pair_ids", [])],
        "zero_selected_pair_count": int(root_step2_metrics.get("zero_selected_pair_count", 0)),
        "zero_selected_pair_ids": [str(v) for v in root_step2_metrics.get("zero_selected_pair_ids", [])],
        "pair_scoped_exception_audit_count": int(root_step2_metrics.get("pair_scoped_exception_audit_count", 0)),
        "pair_scoped_exception_selected_pair_ids": [str(v) for v in root_step2_metrics.get("pair_scoped_exception_selected_pair_ids", [])],
        "pair_scoped_exception_rejected_pair_ids": [str(v) for v in root_step2_metrics.get("pair_scoped_exception_rejected_pair_ids", [])],
        "pair_scoped_exception_non_allowlisted_cross1_pair_ids": [str(v) for v in root_step2_metrics.get("pair_scoped_exception_non_allowlisted_cross1_pair_ids", [])],
        "blocked_pair_bridge_audit_count": int(root_step2_metrics.get("blocked_pair_bridge_audit_count", 0)),
        "production_arc_direct_unique_violation_count": int(len(production_arc_violation_entries)),
        "production_arc_direct_unique_violation_pair_ids": [
            pipeline._pair_id_text(int(entry["src_nodeid"]), int(entry["dst_nodeid"]))
            for entry in production_arc_violation_entries
        ],
        "production_synthetic_arc_count": int(len(synthetic_production_arc_entries)),
        "production_synthetic_arc_pair_ids": [
            pipeline._pair_id_text(int(entry["src_nodeid"]), int(entry["dst_nodeid"]))
            for entry in synthetic_production_arc_entries
        ],
        "witness_selected_count_total": int(witness_selected_total),
        "witness_selected_count_cross0": int(witness_selected_cross0),
        "witness_selected_count_cross1": int(witness_selected_cross1),
        "full_legal_arc_registry": legal_arc_registry,
        "legal_arc_registry": [dict(item) for item in legal_arc_registry if bool(item.get("entered_main_flow", False))],
        "legal_arc_funnel": legal_arc_funnel,
        "arc_evidence_attach_audit": list(arc_evidence_attach_audit or []),
        "legal_arc_total": int(legal_arc_funnel.get("entered_main_flow_arc_count", 0)),
        "legal_arc_built": int(legal_arc_funnel.get("built_arc_count", 0)),
        "legal_arc_build_rate": float(
            (int(legal_arc_funnel.get("built_arc_count", 0)) / max(1, int(legal_arc_funnel.get("entered_main_flow_arc_count", 0))))
            if int(legal_arc_funnel.get("entered_main_flow_arc_count", 0))
            else 0.0
        ),
        "legal_arc_unbuilt_reason_hist": dict(
            Counter(str(item["unbuilt_reason"]) for item in legal_arc_registry if not bool(item["built_final_road"]) and str(item["unbuilt_reason"]))
        ),
        "segments": metrics_segments,
    }
    if not hard_breakpoints and len(roads) == 0:
        hard_breakpoints.append(
            {
                "segment_id": None,
                "reason": "no_segment_candidates" if len(segments) == 0 else "no_geometry_candidate",
                "severity": "hard",
            }
        )
    gate = {
        "overall_pass": bool(len(roads) > 0 and not hard_breakpoints),
        "hard_breakpoints": hard_breakpoints,
        "soft_breakpoints": soft_breakpoints,
        "version": "t05v2_gate_v1",
    }
    summary_lines = [
        f"patch_id={patch_id}",
        f"segment_count={len(segments)}",
        f"road_count={len(roads)}",
        f"overall_pass={str(gate['overall_pass']).lower()}",
        (
            "pair_scoped_exception: "
            f"selected={len(metrics['pair_scoped_exception_selected_pair_ids'])} "
            f"rejected={len(metrics['pair_scoped_exception_rejected_pair_ids'])} "
            f"non_allowlisted_cross1={len(metrics['pair_scoped_exception_non_allowlisted_cross1_pair_ids'])}"
        ),
        (
            "segment_topology_gate: "
            f"before={int(metrics['segment_selected_count_before_topology_gate'])} "
            f"after={int(metrics['segment_selected_count_after_topology_gate'])}"
        ),
        (
            "traj_crossings: "
            f"raw={int(metrics['traj_crossing_raw_count'])} "
            f"filtered={int(metrics['traj_crossing_filtered_count'])}"
        ),
        (
            "invalid_segment: "
            f"prior_conflict={int(metrics.get('unanchored_prior_conflict_segment_count', 0))} "
            f"directed_path={int(metrics.get('directed_path_not_supported_count', 0))} "
            f"trace_only={int(metrics.get('trace_only_reachability_segment_count', 0))} "
            f"terminal_mismatch={int(metrics.get('terminal_owner_mismatch_segment_count', 0))} "
            f"terminal_ambiguous={int(metrics.get('ambiguous_terminal_owner_segment_count', 0))} "
            f"pair_not_direct={int(metrics.get('pair_not_direct_legal_arc_count', 0))} "
            f"non_unique_direct={int(metrics.get('non_unique_direct_legal_arc_count', 0))} "
            f"synthetic_not_allowed={int(metrics.get('synthetic_arc_not_allowed_count', 0))}"
        ),
        (
            "arc_legality: "
            f"direct_unique_violation={int(metrics.get('production_arc_direct_unique_violation_count', 0))} "
            f"synthetic_arc={int(metrics.get('production_synthetic_arc_count', 0))}"
        ),
        (
            "legal_arc_funnel: "
            f"all_direct={int(legal_arc_funnel.get('all_direct_legal_arc_count', 0))} "
            f"direct_unique={int(legal_arc_funnel.get('all_direct_unique_legal_arc_count', 0))} "
            f"entered={int(legal_arc_funnel.get('entered_main_flow_arc_count', 0))} "
            f"traj_supported={int(legal_arc_funnel.get('traj_supported_arc_count', 0))} "
            f"prior_supported={int(legal_arc_funnel.get('prior_supported_arc_count', 0))} "
            f"corridor_resolved={int(legal_arc_funnel.get('corridor_resolved_arc_count', 0))} "
            f"slot_established={int(legal_arc_funnel.get('slot_established_arc_count', 0))} "
            f"built={int(legal_arc_funnel.get('built_arc_count', 0))}"
        ),
        (
            "road_summary: "
            f"built={len(roads)} "
            f"failed={len(no_geometry_entries)} "
            f"final_geometry_invalid={int(failure_classification_hist.get('final_geometry_invalid', 0))} "
            f"slot_mapping_failed={int(failure_classification_hist.get('slot_mapping_failed', 0))} "
            f"unresolved_corridor={int(failure_classification_hist.get('unresolved_corridor', 0))} "
            f"should_be_no_geometry_candidate={int(failure_classification_hist.get('should_be_no_geometry_candidate', 0))}"
        ),
    ]
    for entry in metrics_segments:
        summary_lines.append(
            " ".join(
                [
                    f"segment_id={entry['segment_id']}",
                    f"corridor={entry['corridor_identity']}",
                    f"src_slot={str(entry['src_slot_resolved']).lower()}",
                    f"dst_slot={str(entry['dst_slot_resolved']).lower()}",
                    f"shape_ref={entry['shape_ref_mode']}",
                    f"failure_class={entry['failure_classification']}",
                    f"reason={entry['unresolved_reason'] or entry['corridor_reason']}",
                ]
            )
        )
    write_lines_geojson(patch_dir / "Road.geojson", road_features)
    write_json(patch_dir / "metrics.json", metrics)
    write_json(patch_dir / "gate.json", gate)
    (patch_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    write_lines_geojson(dbg_dir / "shape_ref_line.geojson", shape_ref_features)
    write_lines_geojson(dbg_dir / "road_final.geojson", road_features)
    write_json(
        dbg_dir / "reason_trace.json",
        {
            "corridor_identities": [identities[key].to_dict() for key in sorted(identities.keys())],
            "slot_mapping": {
                str(segment_id): {"src": slots[str(segment_id)]["src"].to_dict(), "dst": slots[str(segment_id)]["dst"].to_dict()}
                for segment_id in sorted(slots.keys())
            },
            "road_build": road_trace_entries,
            "road_results": road_trace_entries,
            "summary": {
                "road_count": int(len(roads)),
                "no_geometry_candidate_count": int(len(no_geometry_entries)),
                "failure_classification_hist": failure_classification_hist,
            },
        },
    )
    write_json(
        dbg_dir / "step6_bridge_trial_decisions.json",
        {
            "pairs": bridge_trial_entries,
            "summary": {
                "bridge_trial_count": int(len(bridge_trial_entries)),
                "built_count": int(sum(1 for item in bridge_trial_entries if bool(item["built_final_road"]))),
                "unresolved_count": int(sum(1 for item in bridge_trial_entries if not bool(item["built_final_road"]))),
            },
        },
    )


def run_slot_mapping_stage(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    pipeline = _pipeline()
    stage_started = perf_counter()
    inputs, frame, prior_roads = pipeline.load_inputs_and_frame(data_root, patch_id, params=params)
    patch_geometry_cache = build_patch_geometry_cache(inputs, params)
    prior_index = build_prior_reference_index(prior_roads)
    xsec_map = pipeline._xsec_map(frame)
    witnesses_payload = pipeline._load_stage_payload(out_root, run_id, patch_id, "step3_witness")
    identities_payload = pipeline._load_stage_payload(out_root, run_id, patch_id, "step4_corridor_identity")
    segments = [Segment.from_dict(item) for item in identities_payload.get("working_segments", [])]
    witnesses = {str(item.segment_id): item for item in (CorridorWitness.from_dict(v) for v in witnesses_payload.get("witnesses", []))}
    identities = {str(item.segment_id): item for item in (CorridorIdentity.from_dict(v) for v in identities_payload.get("corridor_identities", []))}
    full_registry_rows = list(identities_payload.get("full_legal_arc_registry", []))
    legal_arc_funnel = dict(identities_payload.get("legal_arc_funnel", {}))
    slot_map: dict[str, dict[str, SlotInterval]] = {}
    debug_features: list[tuple[LineString, dict[str, Any]]] = []
    for segment in segments:
        witness = witnesses.get(str(segment.segment_id))
        identity = identities[str(segment.segment_id)]
        line, line_mode = slot_reference_line(segment=segment, identity=identity, prior_roads=prior_roads, prior_index=prior_index)
        src_slot = build_slot(
            segment=segment,
            witness=witness,
            identity=identity,
            xsec=xsec_map[int(segment.src_nodeid)],
            line=line,
            inputs=inputs,
            params=params,
            endpoint_tag="src",
            drivable_surface=patch_geometry_cache.get("drivable_surface"),
        )
        dst_slot = build_slot(
            segment=segment,
            witness=witness,
            identity=identity,
            xsec=xsec_map[int(segment.dst_nodeid)],
            line=line,
            inputs=inputs,
            params=params,
            endpoint_tag="dst",
            drivable_surface=patch_geometry_cache.get("drivable_surface"),
        )
        slot_map[str(segment.segment_id)] = {"src": src_slot, "dst": dst_slot}
        for slot in (src_slot, dst_slot):
            if slot.interval is not None:
                debug_features.append(
                    (
                        slot.interval.geometry_metric(),
                        {
                            "segment_id": str(segment.segment_id),
                            "endpoint_tag": str(slot.endpoint_tag),
                            "xsec_nodeid": int(slot.xsec_nodeid),
                            "resolved": bool(slot.resolved),
                            "method": str(slot.method),
                            "reason": str(slot.reason),
                            "corridor_state": str(identity.state),
                            "line_mode": str(line_mode),
                        },
                    )
                )
            debug_features.append(
                (
                    slot.xsec_metric(),
                    {
                        "segment_id": str(segment.segment_id),
                        "endpoint_tag": str(slot.endpoint_tag),
                        "xsec_nodeid": int(slot.xsec_nodeid),
                        "resolved": bool(slot.resolved),
                        "role": "base_xsec",
                        "corridor_state": str(identity.state),
                        "line_mode": str(line_mode),
                    },
                )
            )
    artifact = {
        "slot_mapping": {
            segment_id: {"src": values["src"].to_dict(), "dst": values["dst"].to_dict()}
            for segment_id, values in slot_map.items()
        },
        "working_segments": [segment.to_dict() for segment in segments],
        "full_legal_arc_registry": full_registry_rows,
        "legal_arc_funnel": legal_arc_funnel,
        "runtime": {"stage_runtime_ms": float((perf_counter() - stage_started) * 1000.0)},
    }
    dbg_dir = pipeline.debug_dir(out_root, run_id, patch_id)
    write_json(pipeline._artifact_path(out_root, run_id, patch_id, "step5_slot_mapping"), artifact)
    write_lines_geojson(dbg_dir / "slot_src_dst.geojson", debug_features)
    return {
        "artifact": artifact,
        "inputs": inputs,
        "frame": frame,
        "segments": segments,
        "witnesses": witnesses,
        "identities": identities,
        "slots": slot_map,
        "full_legal_arc_registry": full_registry_rows,
        "legal_arc_funnel": legal_arc_funnel,
        "runtime": artifact["runtime"],
        "reason": "slot_mapping_ready",
    }


def run_build_road_stage(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    pipeline = _pipeline()
    stage_started = perf_counter()
    inputs, _frame, prior_roads = pipeline.load_inputs_and_frame(data_root, patch_id, params=params)
    patch_geometry_cache = build_patch_geometry_cache(inputs, params)
    prior_index = build_prior_reference_index(prior_roads)
    segments_payload = pipeline._load_stage_payload(out_root, run_id, patch_id, "step2_segment")
    step2_metrics = dict(segments_payload.get("step2_metrics") or {})
    witnesses_payload = pipeline._load_stage_payload(out_root, run_id, patch_id, "step3_witness")
    identities_payload = pipeline._load_stage_payload(out_root, run_id, patch_id, "step4_corridor_identity")
    slots_payload = pipeline._load_stage_payload(out_root, run_id, patch_id, "step5_slot_mapping")
    segments = [Segment.from_dict(item) for item in identities_payload.get("working_segments", [])]
    witnesses = {str(item.segment_id): item for item in (CorridorWitness.from_dict(v) for v in witnesses_payload.get("witnesses", []))}
    identities = {str(item.segment_id): item for item in (CorridorIdentity.from_dict(v) for v in identities_payload.get("corridor_identities", []))}
    slot_map: dict[str, dict[str, SlotInterval]] = {
        str(segment_id): {"src": SlotInterval.from_dict(value["src"]), "dst": SlotInterval.from_dict(value["dst"])}
        for segment_id, value in (slots_payload.get("slot_mapping") or {}).items()
    }
    full_registry_rows = list(identities_payload.get("full_legal_arc_registry", []))
    registry_by_working_segment = {
        str(item.get("working_segment_id", "")): dict(item)
        for item in full_registry_rows
        if str(item.get("working_segment_id", ""))
    }
    registry_by_arc_id = {
        str(item.get("topology_arc_id", "")): dict(item)
        for item in full_registry_rows
        if str(item.get("topology_arc_id", ""))
    }
    legal_arc_funnel_seed = dict(identities_payload.get("legal_arc_funnel", {}))
    arc_evidence_attach_audit = list(witnesses_payload.get("arc_evidence_attach_audit", []))
    roads: list[FinalRoad] = []
    road_results: list[dict[str, Any]] = []
    for segment in segments:
        road, build_meta = build_final_road(
            patch_id=str(patch_id),
            segment=segment,
            identity=identities[str(segment.segment_id)],
            witness=witnesses.get(str(segment.segment_id)),
            src_slot=slot_map[str(segment.segment_id)]["src"],
            dst_slot=slot_map[str(segment.segment_id)]["dst"],
            inputs=inputs,
            prior_roads=prior_roads,
            params=params,
            arc_row=registry_by_working_segment.get(str(segment.segment_id))
            or registry_by_arc_id.get(str(segment.topology_arc_id))
            or {},
            prior_index=prior_index,
            divstrip_buffer=patch_geometry_cache.get("divstrip_buffer"),
        )
        road_results.append(dict(build_meta))
        if road is not None:
            roads.append(road)
    artifact = {
        "roads": [road.to_dict() for road in roads],
        "road_results": road_results,
        "runtime": {"stage_runtime_ms": float((perf_counter() - stage_started) * 1000.0)},
    }
    write_json(pipeline._artifact_path(out_root, run_id, patch_id, "step6_build_road"), artifact)
    write_road_outputs(
        out_root=out_root,
        run_id=run_id,
        patch_id=patch_id,
        segments=segments,
        identities=identities,
        witnesses=witnesses,
        slots=slot_map,
        roads=roads,
        road_results=road_results,
        inputs=inputs,
        step2_metrics=step2_metrics,
        full_registry_rows=full_registry_rows,
        legal_arc_funnel_seed=legal_arc_funnel_seed,
        arc_evidence_attach_audit=arc_evidence_attach_audit,
        params=params,
    )
    return {
        "artifact": artifact,
        "roads": roads,
        "runtime": artifact["runtime"],
        "reason": "road_ready" if roads else "no_geometry_candidate",
    }


__all__ = [
    "build_final_road",
    "build_slot",
    "classify_segment_outcome",
    "run_build_road_stage",
    "run_slot_mapping_stage",
    "shape_ref_line",
    "slot_reference_line",
    "write_road_outputs",
]
