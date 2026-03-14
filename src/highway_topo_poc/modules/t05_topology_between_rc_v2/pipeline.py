from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from .io import (
    InputFrame,
    PatchInputs,
    load_divstrip_buffer,
    load_inputs_and_frame,
    read_json,
    write_json,
    write_lines_geojson,
    write_step_state,
)
from .models import (
    BaseCrossSection,
    CorridorIdentity,
    CorridorInterval,
    CorridorWitness,
    FinalRoad,
    Segment,
    SlotInterval,
    coords_to_line,
    line_to_coords,
)
from .step2_arc_registry import build_full_legal_arc_registry
from .step3_arc_evidence import run_witness_stage as _step3_run_arc_evidence_stage
from .step3_corridor_identity import (
    run_corridor_identity_stage as _step3_run_corridor_identity_stage,
)
from .step5_conservative_road import (
    build_final_road as _step5_build_final_road,
    classify_segment_outcome as _step5_classify_segment_outcome,
    run_build_road_stage as _step5_run_build_road_stage,
    run_slot_mapping_stage as _step5_run_slot_mapping_stage,
)


STAGES = (
    "step1_input_frame",
    "step2_segment",
    "step3_witness",
    "step4_corridor_identity",
    "step5_slot_mapping",
    "step6_build_road",
)

STAGE_DIR_NAMES = {
    "step1_input_frame": "step1",
    "step2_segment": "step2",
    "step3_witness": "step3",
    "step4_corridor_identity": "step4",
    "step5_slot_mapping": "step5",
    "step6_build_road": "step6",
}

DEFAULT_PARAMS: dict[str, Any] = {
    "TRAJ_SPLIT_MAX_GAP_M": 10.0,
    "TRAJ_SPLIT_MAX_TIME_GAP_S": 1.0,
    "TRAJ_SPLIT_MAX_SEQ_GAP": 20000000,
    "TRAJ_XSEC_HIT_BUFFER_M": 2.0,
    "SEGMENT_MIN_LENGTH_M": 5.0,
    "SEGMENT_MIN_DRIVEZONE_RATIO": 0.85,
    "SEGMENT_MAX_OTHER_XSEC_CROSSINGS": 1,
    "SEGMENT_CLUSTER_OFFSET_M": 6.0,
    "SEGMENT_CLUSTER_LINE_DIST_M": 5.0,
    "STEP2_STRICT_ADJACENT_PAIRING": 1,
    "STEP2_ALLOW_ONE_INTERMEDIATE_XSEC": 0,
    "STEP2_SAME_PAIR_TOPK": 1,
    "STEP2_CROSS1_MIN_SUPPORT": 2,
    "STEP2_CROSS1_MIN_DRIVEZONE_RATIO": 0.98,
    "STEP2_CROSS1_MAX_LENGTH_RATIO": 1.35,
    "STEP2_CROSS1_REQUIRE_NO_CROSS0_BETTER": 1,
    "STEP2_PAIR_SCOPED_CROSS1_EXCEPTION_ENABLE": 0,
    "STEP2_PAIR_SCOPED_CROSS1_ALLOWLIST": "",
    "STEP2_PAIR_SCOPED_BRIDGE_RETAIN_ENABLE": 1,
    "STEP2_PAIR_SCOPED_BRIDGE_RETAIN_PAIR_IDS": "5395717732638194:37687913",
    "STEP2_ENABLE_PSEUDO_RCS_NODE_XSECS": 1,
    "STEP2_PSEUDO_XSEC_HALF_LENGTH_M": 6.0,
    "STEP2_XSEC_ALIAS_NORMALIZATION_ENABLE": 1,
    "STEP2_XSEC_ALIAS_ALLOWLIST": "23287538:55353307",
    "STEP2_XSEC_ALIAS_MAX_NODE_TO_XSEC_DIST_M": 1.5,
    "STEP2_ENABLE_TERMINAL_TRACE_TOPOLOGY": 0,
    "PRIOR_ENDPOINT_ANCHOR_M": 20.0,
    "DIVSTRIP_BUFFER_M": 0.5,
    "WITNESS_HALF_LENGTH_M": 30.0,
    "WITNESS_MIN_SEGMENT_LENGTH_M": 12.0,
    "WITNESS_SAMPLE_POSITIONS": (0.35, 0.5, 0.65),
    "WITNESS_CENTER_TOL_M": 3.0,
    "WITNESS_GAP_MIN_M": 1.0,
    "WITNESS_MIN_STABILITY_SCORE": 0.55,
    "INTERVAL_MIN_LEN_M": 1.0,
    "ROAD_MIN_DRIVEZONE_RATIO": 0.85,
    "ARC_EVIDENCE_BUFFER_M": 8.0,
    "ARC_PARTIAL_MIN_COVERAGE_RATIO": 0.18,
    "ARC_PARTIAL_MIN_LENGTH_M": 12.0,
    "ARC_STITCH_MAX_SEQ_GAP": 12,
    "ARC_STITCH_MAX_PROJ_GAP_M": 25.0,
    "ARC_STITCH_MIN_COVERAGE_RATIO": 0.72,
    "ARC_STITCH_ENDPOINT_MARGIN_RATIO": 0.18,
    "STEP3_TOPOLOGY_GAP_CONTROL_ENABLE": 1,
    "STEP3_TOPOLOGY_GAP_CONTROL_PAIR_IDS": "55353246:37687913,760239:6963539359479390368,791871:37687913",
    "STEP3_TOPOLOGY_GAP_MIN_SUPPORT_COVERAGE_RATIO": 0.35,
}


def patch_root(out_root: Path | str, run_id: str, patch_id: str) -> Path:
    return Path(out_root) / str(run_id) / "patches" / str(patch_id)


def debug_dir(out_root: Path | str, run_id: str, patch_id: str) -> Path:
    return patch_root(out_root, run_id, patch_id) / "debug"


def stage_dir(out_root: Path | str, run_id: str, patch_id: str, stage: str) -> Path:
    stage_name = str(stage)
    dir_name = STAGE_DIR_NAMES.get(stage_name, stage_name)
    return patch_root(out_root, run_id, patch_id) / str(dir_name)


def _state_path(out_root: Path | str, run_id: str, patch_id: str, stage: str) -> Path:
    return stage_dir(out_root, run_id, patch_id, stage) / "step_state.json"


def _artifact_path(out_root: Path | str, run_id: str, patch_id: str, stage: str) -> Path:
    names = {
        "step1_input_frame": "input_frame.json",
        "step2_segment": "segments.json",
        "step3_witness": "witnesses.json",
        "step4_corridor_identity": "corridor_identity.json",
        "step5_slot_mapping": "slot_mapping.json",
        "step6_build_road": "final_roads.json",
    }
    return stage_dir(out_root, run_id, patch_id, stage) / names[stage]


def _trim_reason(reason: str, *, limit: int = 240) -> str:
    text = " ".join(str(reason or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _merge_params(overrides: dict[str, Any] | None) -> dict[str, Any]:
    params = dict(DEFAULT_PARAMS)
    if isinstance(overrides, dict):
        params.update(overrides)
    return params


def _xsec_map(frame: InputFrame) -> dict[int, BaseCrossSection]:
    return {int(x.nodeid): x for x in frame.base_cross_sections}


def _line_midpoint(line: LineString) -> Point:
    return line.interpolate(0.5, normalized=True)


def _unit_vector(dx: float, dy: float) -> tuple[float, float]:
    norm = math.hypot(dx, dy)
    if norm <= 1e-9:
        return (1.0, 0.0)
    return (float(dx / norm), float(dy / norm))


def _line_direction(line: LineString) -> tuple[float, float]:
    coords = list(line.coords)
    if len(coords) < 2:
        return (1.0, 0.0)
    x0, y0 = coords[0][:2]
    x1, y1 = coords[-1][:2]
    return _unit_vector(float(x1 - x0), float(y1 - y0))


def _line_tangent(line: LineString, distance_m: float) -> tuple[float, float]:
    if line.length <= 1e-6:
        return _line_direction(line)
    d0 = max(0.0, float(distance_m) - 1.0)
    d1 = min(float(line.length), float(distance_m) + 1.0)
    if d1 - d0 <= 1e-6:
        return _line_direction(line)
    p0 = line.interpolate(d0)
    p1 = line.interpolate(d1)
    return _unit_vector(float(p1.x - p0.x), float(p1.y - p0.y))


def _unique_line(points_xy: list[tuple[float, float]]) -> LineString | None:
    coords: list[tuple[float, float]] = []
    for x, y in points_xy:
        pt = (float(x), float(y))
        if not coords or pt != coords[-1]:
            coords.append(pt)
    if len(coords) < 2:
        return None
    line = LineString(coords)
    if line.is_empty or line.length <= 1e-6:
        return None
    return line


def _merge_line_coords(*coord_groups: Any) -> tuple[tuple[float, float], ...]:
    merged: list[tuple[float, float]] = []
    for group in coord_groups:
        if group is None:
            continue
        for coord in group:
            xy = (float(coord[0]), float(coord[1]))
            if not merged or xy != merged[-1]:
                merged.append(xy)
    return tuple(merged)


def _trajectory_line(traj: Any) -> LineString | None:
    xyz = getattr(traj, "xyz_metric", None)
    if xyz is None or len(xyz) < 2:
        return None
    pts = [(float(row[0]), float(row[1])) for row in xyz]
    return _unique_line(pts)


def _xsec_hit_index(points_xy: list[tuple[float, float]], line: LineString, xsec: LineString, buffer_m: float) -> int | None:
    hits: list[int] = []
    for idx, (x, y) in enumerate(points_xy):
        if float(xsec.distance(Point(float(x), float(y)))) <= float(buffer_m):
            hits.append(int(idx))
    if hits:
        return int(round(sum(hits) / max(1, len(hits))))
    probe = line.intersection(xsec.buffer(float(buffer_m)))
    if probe.is_empty:
        return None
    ref = probe.representative_point()
    best_idx = None
    best_d2 = float("inf")
    for idx, (x, y) in enumerate(points_xy):
        d2 = (float(x) - float(ref.x)) ** 2 + (float(y) - float(ref.y)) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_idx = idx
    return best_idx


def _local_traj_window_line(pts: list[tuple[float, float]], center_idx: int, *, half_window: int = 2) -> LineString | None:
    lo = max(0, int(center_idx) - int(half_window))
    hi = min(len(pts) - 1, int(center_idx) + int(half_window))
    if hi - lo < 1:
        return None
    return _unique_line(pts[lo : hi + 1])


def _local_heading_deg(line: LineString | None) -> float | None:
    if not isinstance(line, LineString) or line.is_empty or len(line.coords) < 2:
        return None
    x0, y0 = line.coords[0][:2]
    x1, y1 = line.coords[-1][:2]
    if math.hypot(float(x1 - x0), float(y1 - y0)) <= 1e-6:
        return None
    return float(math.degrees(math.atan2(float(y1 - y0), float(x1 - x0))))


def _trajectory_events(
    traj: Any,
    frame: InputFrame,
    hit_buffer_m: float,
    *,
    drivezone: BaseGeometry | None = None,
    divstrip_buffer: BaseGeometry | None = None,
) -> list[dict[str, Any]]:
    xyz = getattr(traj, "xyz_metric", None)
    line = _trajectory_line(traj)
    if xyz is None or line is None:
        return []
    pts = [(float(row[0]), float(row[1])) for row in xyz]
    events: list[dict[str, Any]] = []
    for xsec in frame.base_cross_sections:
        idx = _xsec_hit_index(pts, line, xsec.geometry_metric(), hit_buffer_m)
        if idx is None:
            continue
        px, py = pts[int(idx)]
        local_line = _local_traj_window_line(pts, int(idx))
        events.append(
            {
                "event_id": f"{traj.traj_id}:{int(xsec.nodeid)}:{int(idx)}",
                "traj_id": str(traj.traj_id),
                "nodeid": int(xsec.nodeid),
                "index": int(idx),
                "point": Point(float(px), float(py)),
                "local_heading": _local_heading_deg(local_line),
                "in_drivezone_ratio_local": _drivezone_ratio(local_line, drivezone) if local_line is not None else 0.0,
                "crosses_divstrip_local": bool(
                    local_line is not None
                    and divstrip_buffer is not None
                    and not divstrip_buffer.is_empty
                    and local_line.intersects(divstrip_buffer)
                ),
            }
        )
    events.sort(key=lambda item: (int(item["index"]), int(item["nodeid"])))
    deduped: list[dict[str, Any]] = []
    for event in events:
        if deduped and int(deduped[-1]["nodeid"]) == int(event["nodeid"]) and abs(int(deduped[-1]["index"]) - int(event["index"])) <= 2:
            continue
        deduped.append(event)
    for order, event in enumerate(deduped):
        event["crossing_order_on_traj"] = int(order)
        event["from_nodeid"] = None if order == 0 else int(deduped[order - 1]["nodeid"])
        event["to_nodeid"] = None if order >= len(deduped) - 1 else int(deduped[order + 1]["nodeid"])
    return deduped


def _candidate_subline_from_traj(traj: Any, start_idx: int, end_idx: int) -> LineString | None:
    xyz = getattr(traj, "xyz_metric", None)
    if xyz is None:
        return None
    lo = max(0, min(int(start_idx), int(end_idx)))
    hi = min(len(xyz) - 1, max(int(start_idx), int(end_idx)))
    pts = [(float(row[0]), float(row[1])) for row in xyz[lo : hi + 1]]
    return _unique_line(pts)


def _drivezone_ratio(line: LineString, drivezone: BaseGeometry | None) -> float:
    if drivezone is None or drivezone.is_empty or line.is_empty or line.length <= 1e-6:
        return 0.0
    inter = line.intersection(drivezone)
    length = float(getattr(inter, "length", 0.0))
    return float(max(0.0, min(1.0, length / max(line.length, 1e-6))))


def _count_other_xsecs(line: LineString, src_nodeid: int, dst_nodeid: int, frame: InputFrame, hit_buffer_m: float) -> list[int]:
    others: list[int] = []
    for xsec in frame.base_cross_sections:
        nodeid = int(xsec.nodeid)
        if nodeid in {int(src_nodeid), int(dst_nodeid)}:
            continue
        if line.intersects(xsec.geometry_metric().buffer(float(hit_buffer_m))):
            others.append(nodeid)
    return sorted(set(others))


def _axis_line_for_pair(segment_line: LineString, src_xsec: BaseCrossSection, dst_xsec: BaseCrossSection) -> LineString:
    src_mid = _line_midpoint(src_xsec.geometry_metric())
    dst_mid = _line_midpoint(dst_xsec.geometry_metric())
    axis = LineString([(float(src_mid.x), float(src_mid.y)), (float(dst_mid.x), float(dst_mid.y))])
    if axis.length <= 1e-6:
        coords = list(segment_line.coords)
        if len(coords) >= 2:
            return LineString([(float(coords[0][0]), float(coords[0][1])), (float(coords[-1][0]), float(coords[-1][1]))])
    return axis


def _signed_offset(line: LineString, axis: LineString) -> float:
    mid = _line_midpoint(line)
    ax0, ay0 = axis.coords[0][:2]
    ax1, ay1 = axis.coords[-1][:2]
    ux, uy = _unit_vector(float(ax1 - ax0), float(ay1 - ay0))
    vx = float(mid.x - ax0)
    vy = float(mid.y - ay0)
    return float(ux * vy - uy * vx)


def _line_parts(geom: BaseGeometry) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return [ls for ls in geom.geoms if isinstance(ls, LineString) and ls.length > 0]
    if isinstance(geom, GeometryCollection):
        out: list[LineString] = []
        for sub in geom.geoms:
            out.extend(_line_parts(sub))
        return out
    return []


def _intervals_on_xsec(
    xsec_line: LineString,
    drivable_surface: BaseGeometry | None,
    *,
    align_vector: tuple[float, float] | None,
    min_len_m: float,
) -> list[CorridorInterval]:
    if drivable_surface is None or drivable_surface.is_empty:
        return []
    inter = xsec_line.intersection(drivable_surface)
    parts = [part for part in _line_parts(inter) if float(part.length) >= float(min_len_m)]
    if not parts:
        return []
    reverse = False
    if align_vector is not None:
        x0, y0 = xsec_line.coords[0][:2]
        x1, y1 = xsec_line.coords[-1][:2]
        vx, vy = _unit_vector(float(x1 - x0), float(y1 - y0))
        reverse = (vx * float(align_vector[0]) + vy * float(align_vector[1])) < 0.0
    entries: list[CorridorInterval] = []
    for part in parts:
        coords = list(part.coords)
        p0 = Point(float(coords[0][0]), float(coords[0][1]))
        p1 = Point(float(coords[-1][0]), float(coords[-1][1]))
        s0 = float(xsec_line.project(p0))
        s1 = float(xsec_line.project(p1))
        start_s = min(s0, s1)
        end_s = max(s0, s1)
        entries.append(
            CorridorInterval(
                start_s=float(start_s),
                end_s=float(end_s),
                center_s=float((start_s + end_s) / 2.0),
                length_m=float(end_s - start_s),
                rank=0,
                geometry_coords=line_to_coords(part),
            )
        )
    entries.sort(key=lambda item: float(item.center_s), reverse=reverse)
    out: list[CorridorInterval] = []
    for rank, item in enumerate(entries):
        out.append(
            CorridorInterval(
                start_s=float(item.start_s),
                end_s=float(item.end_s),
                center_s=float(item.center_s),
                length_m=float(item.length_m),
                rank=int(rank),
                geometry_coords=item.geometry_coords,
            )
        )
    return out


def _choose_interval(intervals: list[CorridorInterval], *, reference_s: float, desired_rank: int | None) -> tuple[CorridorInterval | None, str, str]:
    if not intervals:
        return None, "unresolved", "no_legal_interval"
    if desired_rank is not None and 0 <= int(desired_rank) < len(intervals):
        return intervals[int(desired_rank)], "rank", "rank_match"
    for interval in intervals:
        if float(interval.start_s) - 1e-6 <= float(reference_s) <= float(interval.end_s) + 1e-6:
            return interval, "reference_contains", "reference_on_interval"
    best = min(intervals, key=lambda item: abs(float(item.center_s) - float(reference_s)))
    if desired_rank is not None:
        return best, "rank_fallback", "rank_missing_fallback_to_reference"
    return best, "reference_nearest", "reference_nearest_interval"


def _midpoint_of_interval(interval: CorridorInterval) -> Point:
    return interval.geometry_metric().interpolate(0.5, normalized=True)


def _reverse_line(line: LineString) -> LineString:
    return LineString(list(reversed(list(line.coords))))


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


def _load_previous_state(out_root: Path | str, run_id: str, patch_id: str, stage: str) -> dict[str, Any] | None:
    path = _state_path(out_root, run_id, patch_id, stage)
    if not path.is_file():
        return None
    return read_json(path)


def _require_previous_stage(out_root: Path | str, run_id: str, patch_id: str, stage: str) -> None:
    idx = STAGES.index(stage)
    if idx == 0:
        return
    prev_stage = STAGES[idx - 1]
    state_path = _state_path(out_root, run_id, patch_id, prev_stage)
    artifact_path = _artifact_path(out_root, run_id, patch_id, prev_stage)
    state = _load_previous_state(out_root, run_id, patch_id, prev_stage)
    if state is None:
        raise ValueError(
            f"previous_stage_missing:{prev_stage}:expected_state={state_path}:expected_artifact={artifact_path}"
        )
    if not bool(state.get("ok")):
        raise ValueError(
            f"previous_stage_failed:{prev_stage}:expected_state={state_path}:expected_artifact={artifact_path}"
        )
    if not artifact_path.is_file():
        raise ValueError(
            f"previous_stage_artifact_missing:{prev_stage}:expected_artifact={artifact_path}:state={state_path}"
        )


def _load_stage_payload(out_root: Path | str, run_id: str, patch_id: str, stage: str) -> dict[str, Any]:
    path = _artifact_path(out_root, run_id, patch_id, stage)
    if not path.is_file():
        raise ValueError(f"stage_artifact_missing:{stage}:expected_artifact={path}")
    return read_json(path)


def _pair_midpoint_distance_for_nodes(
    xsec_map: dict[int, BaseCrossSection],
    src_nodeid: int,
    dst_nodeid: int,
) -> float:
    src = xsec_map.get(int(src_nodeid))
    dst = xsec_map.get(int(dst_nodeid))
    if src is None or dst is None:
        return 0.0
    return float(_line_midpoint(src.geometry_metric()).distance(_line_midpoint(dst.geometry_metric())))


def _histogram(values: list[int]) -> dict[str, int]:
    counts = Counter(int(v) for v in values)
    return {str(int(key)): int(value) for key, value in sorted(counts.items(), key=lambda item: int(item[0]))}


def _parse_pair_scoped_allowlist(value: Any) -> set[tuple[int, int]]:
    if value is None:
        return set()
    if isinstance(value, str):
        tokens = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple, set)):
        tokens = [str(part).strip() for part in value if str(part).strip()]
    else:
        tokens = [str(value).strip()]
    out: set[tuple[int, int]] = set()
    for token in tokens:
        text = str(token).strip()
        if ":" not in text:
            continue
        src_text, dst_text = text.split(":", 1)
        try:
            out.add((int(src_text), int(dst_text)))
        except Exception:
            continue
    return out


def _parse_xsec_alias_allowlist(value: Any) -> dict[int, int]:
    if value is None:
        return {}
    if isinstance(value, str):
        tokens = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple, set)):
        tokens = [str(part).strip() for part in value if str(part).strip()]
    else:
        tokens = [str(value).strip()]
    out: dict[int, int] = {}
    for token in tokens:
        text = str(token).strip()
        if ":" not in text:
            continue
        raw_text, canonical_text = text.split(":", 1)
        try:
            raw_nodeid = int(raw_text)
            canonical_nodeid = int(canonical_text)
        except Exception:
            continue
        if raw_nodeid > 0 and canonical_nodeid > 0 and raw_nodeid != canonical_nodeid:
            out[int(raw_nodeid)] = int(canonical_nodeid)
    return out


def _canonical_xsec_id(nodeid: int, alias_map: dict[int, int]) -> int:
    current = int(nodeid)
    seen: set[int] = set()
    while current in alias_map and current not in seen:
        seen.add(current)
        nxt = int(alias_map.get(current, current))
        if nxt == current:
            break
        current = nxt
    return int(current)


def _pair_id_text(src_nodeid: int, dst_nodeid: int) -> str:
    return f"{int(src_nodeid)}:{int(dst_nodeid)}"


_SEGMENT_TOPOLOGY_INVALID_REASONS = {
    "directed_path_not_supported",
    "trace_only_reachability",
    "terminal_owner_mismatch",
    "ambiguous_terminal_owner",
    "src_conflicts_with_unique_unanchored_prior_endpoint",
    "pair_not_direct_legal_arc",
    "non_unique_direct_legal_arc",
    "arc_unique_connectivity_violation",
    "synthetic_arc_not_allowed",
}


_DIRECT_TOPOLOGY_ARC_SOURCE = "direct_topology_arc"
_TRACE_ONLY_TOPOLOGY_SOURCE = "rcsdroad_trace"
_TERMINAL_TRACE_TOPOLOGY_SOURCE = "rcsdroad_terminal_trace"
_BRIDGE_CHAIN_TOPOLOGY_SOURCE = "bridge_chain_topology"


def _bridge_retain_pair_ids(params: dict[str, Any]) -> set[tuple[int, int]]:
    return _parse_pair_scoped_allowlist(params.get("STEP2_PAIR_SCOPED_BRIDGE_RETAIN_PAIR_IDS", ""))


def _bridge_chain_arc_id(node_path: list[int] | tuple[int, ...]) -> str:
    nodes = [str(int(v)) for v in node_path if v is not None]
    return f"bridge_chain:{'->'.join(nodes)}"


def _direct_arc_rows(
    *,
    src_nodeid: int,
    dst_nodeid: int,
    topology: dict[str, Any],
) -> list[dict[str, Any]]:
    pair = (int(src_nodeid), int(dst_nodeid))
    return [
        dict(item)
        for item in list(topology.get("pair_arcs", {}).get(pair, []))
        if str(item.get("source", "")) == _DIRECT_TOPOLOGY_ARC_SOURCE
    ]


def _arc_legality_diagnostics(
    *,
    src_nodeid: int,
    dst_nodeid: int,
    topology: dict[str, Any],
) -> dict[str, Any]:
    direct_arcs = _direct_arc_rows(src_nodeid=int(src_nodeid), dst_nodeid=int(dst_nodeid), topology=topology)
    bridge_reason = ""
    bridge_nodes: list[int] = []
    bridge_chain_exists = False
    if not direct_arcs:
        bridge_classification = _classify_blocked_pair_bridge(
            src_nodeid=int(src_nodeid),
            dst_nodeid=int(dst_nodeid),
            topology=topology,
        )
        bridge_reason = str(bridge_classification.get("bridge_classification", ""))
        bridge_nodes = [int(v) for v in bridge_classification.get("direct_bridge_nodeids", []) if v is not None]
        bridge_chain_exists = bool(
            bridge_reason in {"unique_directed_bridge_candidate", "multi_bridge_ambiguous", "topology_gap_unresolved"}
        )
    return {
        "topology_arc_is_direct_legal": bool(len(direct_arcs) > 0),
        "topology_arc_is_unique": bool(len(direct_arcs) == 1),
        "topology_arc_candidate_count": int(len(direct_arcs)),
        "direct_arcs": direct_arcs,
        "bridge_chain_exists": bool(bridge_chain_exists),
        "bridge_chain_unique": bool(bridge_reason == "unique_directed_bridge_candidate"),
        "bridge_chain_nodes": bridge_nodes,
        "bridge_diagnostic_reason": bridge_reason if bridge_chain_exists else "",
    }


def _production_arc_gate_reason(
    *,
    candidate: dict[str, Any],
    topology: dict[str, Any],
) -> str | None:
    if not bool(topology.get("enabled")):
        candidate["topology_arc_is_direct_legal"] = False
        candidate["topology_arc_is_unique"] = False
        candidate["topology_arc_candidate_count"] = 0
        candidate["bridge_chain_exists"] = False
        candidate["bridge_chain_unique"] = False
        candidate["bridge_chain_nodes"] = []
        candidate["bridge_diagnostic_reason"] = ""
        return None
    src_nodeid = int(candidate.get("src_nodeid", 0))
    dst_nodeid = int(candidate.get("dst_nodeid", 0))
    topology_reason = _topology_gate_reason(
        src_nodeid=int(src_nodeid),
        dst_nodeid=int(dst_nodeid),
        topology=topology,
    )
    diagnostics = _arc_legality_diagnostics(
        src_nodeid=int(src_nodeid),
        dst_nodeid=int(dst_nodeid),
        topology=topology,
    )
    candidate["topology_arc_is_direct_legal"] = bool(diagnostics["topology_arc_is_direct_legal"])
    candidate["topology_arc_is_unique"] = bool(diagnostics["topology_arc_is_unique"])
    candidate["topology_arc_candidate_count"] = int(diagnostics["topology_arc_candidate_count"])
    candidate["bridge_chain_exists"] = bool(diagnostics["bridge_chain_exists"])
    candidate["bridge_chain_unique"] = bool(diagnostics["bridge_chain_unique"])
    candidate["bridge_chain_nodes"] = [int(v) for v in diagnostics["bridge_chain_nodes"]]
    candidate["bridge_diagnostic_reason"] = str(diagnostics["bridge_diagnostic_reason"])
    if str(topology_reason) == "trace_only_reachability":
        return "trace_only_reachability"
    if not bool(diagnostics["topology_arc_is_direct_legal"]):
        if bool(diagnostics["bridge_chain_exists"]):
            return "synthetic_arc_not_allowed"
        if str(topology_reason) in {"terminal_owner_mismatch", "ambiguous_terminal_owner"}:
            return str(topology_reason)
        return "pair_not_direct_legal_arc"
    if not bool(diagnostics["topology_arc_is_unique"]):
        if str(topology_reason) in {"terminal_owner_mismatch", "ambiguous_terminal_owner"}:
            return str(topology_reason)
        return "non_unique_direct_legal_arc"
    return topology_reason


def _is_bridge_retain_candidate_enabled(
    *,
    src_nodeid: int,
    dst_nodeid: int,
    params: dict[str, Any],
) -> bool:
    if not bool(int(params.get("STEP2_PAIR_SCOPED_BRIDGE_RETAIN_ENABLE", 0))):
        return False
    return (int(src_nodeid), int(dst_nodeid)) in _bridge_retain_pair_ids(params)


def _build_direct_terminal_ownership(
    *,
    incoming: dict[int, set[int]],
    outgoing: dict[int, set[int]],
    pair_paths: dict[tuple[int, int], list[dict[str, Any]]],
) -> dict[int, dict[str, Any]]:
    ownership: dict[int, dict[str, Any]] = {}
    terminal_nodes = {
        int(nodeid)
        for nodeid, srcs in incoming.items()
        if srcs and not outgoing.get(int(nodeid))
    }
    for nodeid in sorted(terminal_nodes):
        src_nodeids = sorted(int(v) for v in incoming.get(int(nodeid), set()))
        status = "no_owner"
        owner_src_nodeid: int | None = None
        if len(src_nodeids) == 1:
            status = "unique_owner"
            owner_src_nodeid = int(src_nodeids[0])
        elif len(src_nodeids) >= 2:
            status = "ambiguous_owner"
        ownership[int(nodeid)] = {
            "nodeid": int(nodeid),
            "status": str(status),
            "src_nodeid": int(owner_src_nodeid) if owner_src_nodeid is not None else None,
            "src_nodeids": [int(v) for v in src_nodeids],
            "anchor_count": int(len(src_nodeids)),
            "paths": [
                {
                    "src_nodeid": int(src_nodeid),
                    "node_path": [int(v) for v in rec.get("node_path", [])],
                    "edge_ids": [str(v) for v in rec.get("edge_ids", [])],
                    "chain_len": int(rec.get("chain_len", 0)),
                }
                for src_nodeid in src_nodeids
                for rec in list(pair_paths.get((int(src_nodeid), int(nodeid)), []))[:3]
            ],
            "anchors": [
                {
                    "anchor_id": f"{int(nodeid)}::DIR::{idx}",
                    "owner_src_nodeid": int(src_nodeid),
                    "owner_src_nodeids": [int(src_nodeid)],
                    "status": "accepted" if len(src_nodeids) == 1 else "ambiguous_owner",
                    "chain_count": int(len(pair_paths.get((int(src_nodeid), int(nodeid)), []))),
                    "paths": [
                        {
                            "node_path": [int(v) for v in rec.get("node_path", [])],
                            "edge_ids": [str(v) for v in rec.get("edge_ids", [])],
                            "chain_len": int(rec.get("chain_len", 0)),
                        }
                        for rec in list(pair_paths.get((int(src_nodeid), int(nodeid)), []))[:3]
                    ],
                }
                for idx, src_nodeid in enumerate(src_nodeids)
            ],
        }
    return ownership


def _directed_road_pair(road: Any) -> tuple[int, int] | None:
    try:
        snodeid = int(getattr(road, "snodeid", 0))
        enodeid = int(getattr(road, "enodeid", 0))
    except Exception:
        return None
    if snodeid <= 0 or enodeid <= 0 or snodeid == enodeid:
        return None
    try:
        direction = int(getattr(road, "direction", 2))
    except Exception:
        direction = 2
    if int(direction) == 3:
        return int(enodeid), int(snodeid)
    return int(snodeid), int(enodeid)


def _build_xsec_alias_map(
    *,
    frame: InputFrame,
    inputs: PatchInputs,
    prior_roads: list[Any],
    params: dict[str, Any],
) -> tuple[dict[int, int], list[dict[str, Any]]]:
    if not bool(int(params.get("STEP2_XSEC_ALIAS_NORMALIZATION_ENABLE", 1))):
        return {}, []
    xsec_map = _xsec_map(frame)
    alias_map: dict[int, int] = {}
    alias_rows: list[dict[str, Any]] = []
    allowlist = _parse_xsec_alias_allowlist(params.get("STEP2_XSEC_ALIAS_ALLOWLIST", ""))
    for raw_nodeid, canonical_xsec_id in sorted(allowlist.items()):
        if int(raw_nodeid) in xsec_map or int(canonical_xsec_id) not in xsec_map:
            continue
        alias_map[int(raw_nodeid)] = int(canonical_xsec_id)
        alias_rows.append(
            {
                "raw_nodeid": int(raw_nodeid),
                "canonical_xsec_id": int(canonical_xsec_id),
                "method": "allowlist",
            }
        )

    threshold_m = float(params.get("STEP2_XSEC_ALIAS_MAX_NODE_TO_XSEC_DIST_M", 1.5))
    node_points = {
        int(getattr(node, "nodeid", 0)): getattr(node, "point")
        for node in getattr(inputs, "node_records", ()) or ()
        if getattr(node, "point", None) is not None
    }
    detected: dict[int, set[int]] = defaultdict(set)
    for road in prior_roads:
        pair = _directed_road_pair(road)
        if pair is None:
            continue
        src_nodeid, dst_nodeid = pair
        for raw_nodeid, canonical_xsec_id in (
            (int(src_nodeid), int(dst_nodeid)),
            (int(dst_nodeid), int(src_nodeid)),
        ):
            if raw_nodeid in xsec_map or canonical_xsec_id not in xsec_map:
                continue
            point = node_points.get(int(raw_nodeid))
            if point is None:
                continue
            try:
                distance_m = float(point.distance(xsec_map[int(canonical_xsec_id)].geometry_metric()))
            except Exception:
                continue
            if distance_m <= threshold_m:
                detected[int(raw_nodeid)].add(int(canonical_xsec_id))
    for raw_nodeid, candidates in sorted(detected.items()):
        if int(raw_nodeid) in alias_map or len(candidates) != 1:
            continue
        canonical_xsec_id = next(iter(candidates))
        alias_map[int(raw_nodeid)] = int(canonical_xsec_id)
        alias_rows.append(
            {
                "raw_nodeid": int(raw_nodeid),
                "canonical_xsec_id": int(canonical_xsec_id),
                "method": "incident_xsec_distance",
            }
        )
    alias_rows.sort(key=lambda item: (int(item["raw_nodeid"]), int(item["canonical_xsec_id"]), str(item["method"])))
    return alias_map, alias_rows


def _build_topology_adjacency_edges(
    prior_roads: list[Any],
    *,
    alias_map: dict[int, int] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    resolved_alias_map = {int(key): int(value) for key, value in dict(alias_map or {}).items()}
    adjacency_edges: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for idx, road in enumerate(prior_roads):
        pair = _directed_road_pair(road)
        if pair is None:
            continue
        line = getattr(road, "line", None)
        if not isinstance(line, LineString) or line.is_empty or len(line.coords) < 2:
            continue
        try:
            direction = int(getattr(road, "direction", 2))
        except Exception:
            direction = 2
        if int(direction) == 3:
            line = _reverse_line(line)
        raw_src_nodeid, raw_dst_nodeid = int(pair[0]), int(pair[1])
        src_nodeid = _canonical_xsec_id(int(raw_src_nodeid), resolved_alias_map)
        dst_nodeid = _canonical_xsec_id(int(raw_dst_nodeid), resolved_alias_map)
        if int(src_nodeid) == int(dst_nodeid):
            continue
        adjacency_edges[int(src_nodeid)].append(
            {
                "to": int(dst_nodeid),
                "edge_id": f"prior_{idx}",
                "path_nodes": [int(src_nodeid), int(dst_nodeid)],
                "raw_path_nodes": [int(raw_src_nodeid), int(raw_dst_nodeid)],
                "raw_src_nodeid": int(raw_src_nodeid),
                "raw_dst_nodeid": int(raw_dst_nodeid),
                "canonical_src_xsec_id": int(src_nodeid),
                "canonical_dst_xsec_id": int(dst_nodeid),
                "src_alias_applied": bool(int(raw_src_nodeid) != int(src_nodeid)),
                "dst_alias_applied": bool(int(raw_dst_nodeid) != int(dst_nodeid)),
                "line_coords": [list(coord) for coord in line_to_coords(line)],
            }
        )
    for src, vals in adjacency_edges.items():
        vals.sort(
            key=lambda item: (
                int(item.get("to", -1)),
                str(item.get("edge_id", "")),
            )
        )
        adjacency_edges[int(src)] = vals
    return dict(adjacency_edges)


def _compress_topology_graph(
    adjacency_edges: dict[int, list[dict[str, Any]]],
    *,
    cross_nodes: set[int],
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, Any]]:
    all_nodes: set[int] = set(int(v) for v in cross_nodes)
    out_neighbors: dict[int, set[int]] = {}
    in_neighbors: dict[int, set[int]] = {}
    for src, edges in adjacency_edges.items():
        src_i = int(src)
        all_nodes.add(src_i)
        out_neighbors.setdefault(src_i, set())
        for edge in edges:
            dst_i = int(edge.get("to"))
            all_nodes.add(dst_i)
            out_neighbors.setdefault(src_i, set()).add(dst_i)
            in_neighbors.setdefault(dst_i, set()).add(src_i)
    for node in all_nodes:
        out_neighbors.setdefault(int(node), set())
        in_neighbors.setdefault(int(node), set())

    removable_nodes = {
        int(node)
        for node in all_nodes
        if int(node) not in cross_nodes
        and int(len(in_neighbors.get(int(node), set()))) == 1
        and int(len(out_neighbors.get(int(node), set()))) == 1
    }
    keep_nodes = {int(node) for node in all_nodes if int(node) not in removable_nodes}
    compressed: dict[int, list[dict[str, Any]]] = {}
    seen: set[tuple[int, int, tuple[str, ...]]] = set()
    cycle_truncate_count = 0

    for src in sorted(keep_nodes):
        src_edges = list(adjacency_edges.get(int(src), []))
        for first_edge in src_edges:
            chain_edge_ids: list[str] = []
            path_nodes: list[int] = [int(src)]
            raw_path_nodes: list[int] = [int(first_edge.get("raw_src_nodeid", src))]
            line_coords: tuple[tuple[float, float], ...] = tuple()
            src_alias_applied = bool(first_edge.get("src_alias_applied", False))
            dst_alias_applied = bool(first_edge.get("dst_alias_applied", False))
            visited: set[int] = set()
            edge_cur = dict(first_edge)
            for _ in range(100000):
                dst = int(edge_cur.get("to"))
                edge_id = str(edge_cur.get("edge_id") or "")
                chain_edge_ids.append(edge_id)
                path_nodes.append(int(dst))
                raw_dst_nodeid = int(edge_cur.get("raw_dst_nodeid", dst))
                if not raw_path_nodes or int(raw_path_nodes[-1]) != int(raw_dst_nodeid):
                    raw_path_nodes.append(int(raw_dst_nodeid))
                src_alias_applied = bool(src_alias_applied or edge_cur.get("src_alias_applied", False))
                dst_alias_applied = bool(dst_alias_applied or edge_cur.get("dst_alias_applied", False))
                line_coords = _merge_line_coords(line_coords, edge_cur.get("line_coords", []))
                if int(dst) in keep_nodes:
                    break
                if int(dst) in visited:
                    cycle_truncate_count += 1
                    break
                visited.add(int(dst))
                next_edges = list(adjacency_edges.get(int(dst), []))
                if len(next_edges) != 1:
                    break
                edge_cur = dict(next_edges[0])
            if len(path_nodes) < 2:
                continue
            dst_keep = int(path_nodes[-1])
            sig = (int(src), int(dst_keep), tuple(chain_edge_ids))
            if sig in seen:
                continue
            seen.add(sig)
            compressed.setdefault(int(src), []).append(
                {
                    "to": int(dst_keep),
                    "edge_ids": [str(v) for v in chain_edge_ids],
                    "path_nodes": [int(v) for v in path_nodes],
                    "raw_path_nodes": [int(v) for v in raw_path_nodes],
                    "raw_src_nodeid": int(raw_path_nodes[0]) if raw_path_nodes else int(src),
                    "raw_dst_nodeid": int(raw_path_nodes[-1]) if raw_path_nodes else int(dst_keep),
                    "canonical_src_xsec_id": int(src),
                    "canonical_dst_xsec_id": int(dst_keep),
                    "src_alias_applied": bool(
                        src_alias_applied or (raw_path_nodes and int(raw_path_nodes[0]) != int(src))
                    ),
                    "dst_alias_applied": bool(
                        dst_alias_applied or (raw_path_nodes and int(raw_path_nodes[-1]) != int(dst_keep))
                    ),
                    "line_coords": [[float(x), float(y)] for x, y in line_coords],
                }
            )

    for src, vals in compressed.items():
        vals.sort(
            key=lambda it: (
                int(it.get("to", -1)),
                int(len(it.get("edge_ids", []))),
                ",".join(str(v) for v in it.get("edge_ids", [])),
            )
        )
        compressed[int(src)] = vals

    stats = {
        "raw_node_count": int(len(all_nodes)),
        "raw_edge_count": int(sum(len(v) for v in adjacency_edges.values())),
        "compressible_node_count": int(len(removable_nodes)),
        "keep_node_count": int(len(keep_nodes)),
        "compressed_edge_count": int(sum(len(v) for v in compressed.values())),
        "cycle_truncate_count": int(cycle_truncate_count),
    }
    return compressed, stats


def _reverse_compressed_graph(
    compressed_adj: dict[int, list[dict[str, Any]]],
) -> dict[int, list[dict[str, Any]]]:
    reversed_graph: dict[int, list[dict[str, Any]]] = {}
    for src, edges in compressed_adj.items():
        src_i = int(src)
        for idx, edge in enumerate(edges):
            to_raw = edge.get("to")
            if to_raw is None:
                continue
            dst_i = int(to_raw)
            edge_ids = [str(v) for v in edge.get("edge_ids", [])]
            path_nodes = [int(v) for v in edge.get("path_nodes", []) if v is not None]
            line_coords = [tuple((float(x), float(y))) for x, y, *_ in edge.get("line_coords", [])]
            if not path_nodes:
                path_nodes = [int(src_i), int(dst_i)]
            if int(path_nodes[0]) != int(src_i):
                path_nodes = [int(src_i)] + path_nodes
            if int(path_nodes[-1]) != int(dst_i):
                path_nodes.append(int(dst_i))
            if not line_coords:
                line_coords = [(float(path_nodes[0]), 0.0), (float(path_nodes[-1]), 0.0)]
            rev_edge_ids = [f"rev:{str(v)}" for v in reversed(edge_ids)] if edge_ids else [f"rev_edge_{src_i}_{dst_i}_{idx}"]
            rev_path_nodes = [int(v) for v in reversed(path_nodes)]
            rev_line_coords = [list(coord) for coord in reversed(line_coords)]
            reversed_graph.setdefault(int(dst_i), []).append(
                {
                    "to": int(src_i),
                    "edge_ids": [str(v) for v in rev_edge_ids],
                    "path_nodes": [int(v) for v in rev_path_nodes],
                    "line_coords": rev_line_coords,
                }
            )
    for src, vals in reversed_graph.items():
        vals.sort(
            key=lambda it: (
                int(it.get("to", -1)),
                int(len(it.get("edge_ids", []))),
                ",".join(str(v) for v in it.get("edge_ids", [])),
            )
        )
        reversed_graph[int(src)] = vals
    return reversed_graph


def _search_topology_next_nodes_from_anchor(
    compressed_adj: dict[int, list[dict[str, Any]]],
    *,
    src_nodeid: int,
    start_to: int | None,
    start_edge_ids: list[str],
    start_path_nodes: list[int],
    cross_nodes: set[int],
    max_expansions: int,
) -> dict[str, Any]:
    src = int(src_nodeid)
    if start_to is None:
        return {
            "src_nodeid": int(src),
            "dst_paths": {},
            "dst_nodeids": [],
            "expansions": 0,
            "overflow": False,
        }

    init_node_path = [int(v) for v in start_path_nodes if v is not None]
    if not init_node_path:
        init_node_path = [int(src), int(start_to)]
    if int(init_node_path[0]) != int(src):
        init_node_path = [int(src)] + [int(v) for v in init_node_path]
    if int(init_node_path[-1]) != int(start_to):
        init_node_path.append(int(start_to))
    init_edge_path = [str(v) for v in start_edge_ids]

    init_line_coords = _merge_line_coords(next((edge.get("line_coords", []) for edge in compressed_adj.get(int(src), []) if int(edge.get("to", -1)) == int(start_to) and [str(v) for v in edge.get("edge_ids", [])] == init_edge_path), []))
    stack: list[tuple[int, list[int], list[str], tuple[tuple[float, float], ...]]] = [
        (int(start_to), [int(v) for v in init_node_path], [str(v) for v in init_edge_path], init_line_coords)
    ]
    expansions = 1
    overflow = False
    dst_paths_raw: dict[int, list[dict[str, Any]]] = {}

    while stack:
        node, node_path, edge_path, line_coords = stack.pop()
        if int(node) != int(src) and int(node) in cross_nodes:
            dst_paths_raw.setdefault(int(node), []).append(
                {
                    "node_path": [int(v) for v in node_path],
                    "edge_ids": [str(v) for v in edge_path],
                    "line_coords": [[float(x), float(y)] for x, y in line_coords],
                }
            )
            continue
        for edge in compressed_adj.get(int(node), []):
            if expansions >= int(max_expansions):
                overflow = True
                stack = []
                break
            nxt = int(edge.get("to"))
            if int(nxt) in node_path:
                continue
            edge_ids = [str(v) for v in edge.get("edge_ids", [])]
            stack.append(
                (
                    int(nxt),
                    [int(v) for v in node_path] + [int(nxt)],
                    [str(v) for v in edge_path] + edge_ids,
                    _merge_line_coords(line_coords, edge.get("line_coords", [])),
                )
            )
            expansions += 1

    dst_paths: dict[int, list[dict[str, Any]]] = {}
    for dst, records in dst_paths_raw.items():
        uniq: dict[tuple[str, ...], dict[str, Any]] = {}
        for rec in records:
            edge_ids = [str(v) for v in rec.get("edge_ids", [])]
            node_path = [int(v) for v in rec.get("node_path", [])]
            sig = tuple(edge_ids) if edge_ids else tuple(str(v) for v in node_path)
            if sig in uniq:
                continue
            uniq[sig] = {
                "node_path": node_path,
                "edge_ids": edge_ids,
                "signature": [str(v) for v in sig],
                "chain_len": int(len(edge_ids)),
                "line_coords": list(rec.get("line_coords", [])),
            }
        dst_paths[int(dst)] = list(uniq.values())

    return {
        "src_nodeid": int(src),
        "dst_paths": dst_paths,
        "dst_nodeids": sorted(int(k) for k in dst_paths.keys()),
        "expansions": int(expansions),
        "overflow": bool(overflow),
    }


def _search_topology_terminal_nodes_from_anchor(
    compressed_adj: dict[int, list[dict[str, Any]]],
    *,
    src_nodeid: int,
    start_to: int | None,
    start_edge_ids: list[str],
    start_path_nodes: list[int],
    terminal_nodes: set[int],
    max_expansions: int,
) -> dict[str, Any]:
    src = int(src_nodeid)
    if start_to is None:
        return {
            "src_nodeid": int(src),
            "dst_paths": {},
            "dst_nodeids": [],
            "expansions": 0,
            "overflow": False,
        }

    init_node_path = [int(v) for v in start_path_nodes if v is not None]
    if not init_node_path:
        init_node_path = [int(src), int(start_to)]
    if int(init_node_path[0]) != int(src):
        init_node_path = [int(src)] + [int(v) for v in init_node_path]
    if int(init_node_path[-1]) != int(start_to):
        init_node_path.append(int(start_to))
    init_edge_path = [str(v) for v in start_edge_ids]

    init_line_coords = _merge_line_coords(next((edge.get("line_coords", []) for edge in compressed_adj.get(int(src), []) if int(edge.get("to", -1)) == int(start_to) and [str(v) for v in edge.get("edge_ids", [])] == init_edge_path), []))
    stack: list[tuple[int, list[int], list[str], tuple[tuple[float, float], ...]]] = [
        (int(start_to), [int(v) for v in init_node_path], [str(v) for v in init_edge_path], init_line_coords)
    ]
    expansions = 1
    overflow = False
    dst_paths_raw: dict[int, list[dict[str, Any]]] = {}

    while stack:
        node, node_path, edge_path, line_coords = stack.pop()
        if int(node) != int(src) and int(node) in terminal_nodes:
            dst_paths_raw.setdefault(int(node), []).append(
                {
                    "node_path": [int(v) for v in node_path],
                    "edge_ids": [str(v) for v in edge_path],
                    "line_coords": [[float(x), float(y)] for x, y in line_coords],
                }
            )
            continue
        for edge in compressed_adj.get(int(node), []):
            if expansions >= int(max_expansions):
                overflow = True
                stack = []
                break
            nxt = int(edge.get("to"))
            if int(nxt) in node_path:
                continue
            edge_ids = [str(v) for v in edge.get("edge_ids", [])]
            stack.append(
                (
                    int(nxt),
                    [int(v) for v in node_path] + [int(nxt)],
                    [str(v) for v in edge_path] + edge_ids,
                    _merge_line_coords(line_coords, edge.get("line_coords", [])),
                )
            )
            expansions += 1

    dst_paths: dict[int, list[dict[str, Any]]] = {}
    for dst, records in dst_paths_raw.items():
        uniq: dict[tuple[str, ...], dict[str, Any]] = {}
        for rec in records:
            edge_ids = [str(v) for v in rec.get("edge_ids", [])]
            node_path = [int(v) for v in rec.get("node_path", [])]
            sig = tuple(edge_ids) if edge_ids else tuple(str(v) for v in node_path)
            if sig in uniq:
                continue
            uniq[sig] = {
                "node_path": node_path,
                "edge_ids": edge_ids,
                "signature": [str(v) for v in sig],
                "chain_len": int(len(edge_ids)),
                "line_coords": list(rec.get("line_coords", [])),
            }
        dst_paths[int(dst)] = list(uniq.values())

    return {
        "src_nodeid": int(src),
        "dst_paths": dst_paths,
        "dst_nodeids": sorted(int(k) for k in dst_paths.keys()),
        "expansions": int(expansions),
        "overflow": bool(overflow),
    }


def _build_terminal_reverse_ownership(
    *,
    compressed_adj: dict[int, list[dict[str, Any]]],
    terminal_nodes: set[int],
    cross_nodes: set[int],
    max_expansions: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    reverse_adj = _reverse_compressed_graph(compressed_adj)
    ownership: dict[int, dict[str, Any]] = {}
    unique_owner_count = 0
    multi_owner_count = 0
    ambiguous_owner_count = 0
    no_owner_count = 0
    overflow_count = 0
    for nodeid in sorted(int(v) for v in terminal_nodes):
        reverse_edges = list(reverse_adj.get(int(nodeid), []))
        anchor_rows: list[dict[str, Any]] = []
        accepted_src_nodeids: list[int] = []
        accepted_paths: list[dict[str, Any]] = []
        multi_src_anchor_count = 0
        multi_chain_anchor_count = 0
        no_owner_anchor_count = 0
        overflow_anchor_count = 0
        for idx, edge in enumerate(reverse_edges):
            start_to_raw = edge.get("to")
            start_to = int(start_to_raw) if start_to_raw is not None else None
            start_edge_ids = [str(v) for v in edge.get("edge_ids", [])]
            start_path_nodes = [int(v) for v in edge.get("path_nodes", []) if v is not None]
            search = _search_topology_next_nodes_from_anchor(
                reverse_adj,
                src_nodeid=int(nodeid),
                start_to=start_to,
                start_edge_ids=start_edge_ids,
                start_path_nodes=start_path_nodes,
                cross_nodes=cross_nodes,
                max_expansions=int(max_expansions),
            )
            candidate_src_nodeids = [int(v) for v in search.get("dst_nodeids", [])]
            overflow = bool(search.get("overflow", False))
            if overflow:
                overflow_anchor_count += 1
            owner_src_nodeid: int | None = None
            chain_count = 0
            status = "no_owner"
            if len(candidate_src_nodeids) >= 2:
                status = "multi_src"
                multi_src_anchor_count += 1
            elif len(candidate_src_nodeids) == 1:
                owner_src_nodeid = int(candidate_src_nodeids[0])
                chain_count = int(len(search.get("dst_paths", {}).get(int(owner_src_nodeid), [])))
                if chain_count >= 2:
                    status = "multi_chain"
                    multi_chain_anchor_count += 1
                else:
                    status = "accepted"
                    accepted_src_nodeids.append(int(owner_src_nodeid))
                    for rec in search.get("dst_paths", {}).get(int(owner_src_nodeid), [])[:3]:
                        accepted_paths.append(
                            {
                                "src_nodeid": int(owner_src_nodeid),
                                "node_path": [int(v) for v in rec.get("node_path", [])],
                                "edge_ids": [str(v) for v in rec.get("edge_ids", [])],
                                "chain_len": int(rec.get("chain_len", 0)),
                                "anchor_id": f"{int(nodeid)}::REV::{int(idx)}",
                            }
                        )
            else:
                no_owner_anchor_count += 1
            anchor_rows.append(
                {
                    "anchor_id": f"{int(nodeid)}::REV::{int(idx)}",
                    "start_to": int(start_to) if start_to is not None else None,
                    "status": str(status),
                    "owner_src_nodeid": int(owner_src_nodeid) if owner_src_nodeid is not None else None,
                    "owner_src_nodeids": [int(v) for v in candidate_src_nodeids],
                    "chain_count": int(chain_count),
                    "expansions": int(search.get("expansions", 0)),
                    "overflow": bool(overflow),
                    "paths": [
                        {
                            "node_path": [int(v) for v in rec.get("node_path", [])],
                            "edge_ids": [str(v) for v in rec.get("edge_ids", [])],
                            "chain_len": int(rec.get("chain_len", 0)),
                        }
                        for src in sorted(search.get("dst_paths", {}).keys())
                        for rec in list(search.get("dst_paths", {}).get(int(src), []))[:3]
                    ],
                }
            )
        unique_src_nodeids = sorted(set(int(v) for v in accepted_src_nodeids))
        ownership_status = "no_owner"
        unique_owner_src_nodeid: int | None = None
        if overflow_anchor_count > 0:
            overflow_count += 1
        if reverse_edges and unique_src_nodeids and len(unique_src_nodeids) == 1 and multi_src_anchor_count == 0 and multi_chain_anchor_count == 0 and no_owner_anchor_count == 0:
            ownership_status = "unique_owner"
            unique_owner_src_nodeid = int(unique_src_nodeids[0])
            unique_owner_count += 1
        elif multi_src_anchor_count > 0 or len(unique_src_nodeids) >= 2:
            ownership_status = "multi_owner"
            multi_owner_count += 1
        elif multi_chain_anchor_count > 0 or overflow_anchor_count > 0:
            ownership_status = "ambiguous_owner"
            ambiguous_owner_count += 1
        else:
            no_owner_count += 1
        ownership[int(nodeid)] = {
            "nodeid": int(nodeid),
            "status": str(ownership_status),
            "src_nodeid": int(unique_owner_src_nodeid) if unique_owner_src_nodeid is not None else None,
            "src_nodeids": [int(v) for v in unique_src_nodeids],
            "anchor_count": int(len(reverse_edges)),
            "accepted_anchor_count": int(sum(1 for row in anchor_rows if str(row.get("status")) == "accepted")),
            "multi_src_anchor_count": int(multi_src_anchor_count),
            "multi_chain_anchor_count": int(multi_chain_anchor_count),
            "no_owner_anchor_count": int(no_owner_anchor_count),
            "overflow_anchor_count": int(overflow_anchor_count),
            "paths": list(accepted_paths[:10]),
            "anchors": anchor_rows,
        }
    stats = {
        "reverse_terminal_owner_unique_count": int(unique_owner_count),
        "reverse_terminal_owner_multi_count": int(multi_owner_count),
        "reverse_terminal_owner_ambiguous_count": int(ambiguous_owner_count),
        "reverse_terminal_owner_none_count": int(no_owner_count),
        "reverse_terminal_owner_overflow_count": int(overflow_count),
    }
    return ownership, stats


def _build_directed_topology(
    *,
    frame: InputFrame,
    inputs: PatchInputs,
    prior_roads: list[Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    xsec_ids = {int(xsec.nodeid) for xsec in frame.base_cross_sections}
    xsec_alias_map, xsec_alias_rows = _build_xsec_alias_map(
        frame=frame,
        inputs=inputs,
        prior_roads=prior_roads,
        params=params,
    )
    allowed_pairs: set[tuple[int, int]] = set()
    incoming: dict[int, set[int]] = defaultdict(set)
    outgoing: dict[int, set[int]] = defaultdict(set)
    pair_prior_ids: dict[tuple[int, int], list[str]] = defaultdict(list)
    pair_sources: dict[tuple[int, int], set[str]] = defaultdict(set)
    pair_paths: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    pair_arcs: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    trace_only_pair_paths: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    terminal_trace_paths: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    adjacency_edges = _build_topology_adjacency_edges(prior_roads, alias_map=xsec_alias_map)
    compressed_adj, compress_stats = _compress_topology_graph(adjacency_edges, cross_nodes=xsec_ids)
    for src_nodeid in sorted(xsec_ids):
        for edge in compressed_adj.get(int(src_nodeid), []):
            start_to_raw = edge.get("to")
            if start_to_raw is None:
                continue
            start_to = int(start_to_raw)
            if int(start_to) not in xsec_ids or int(start_to) == int(src_nodeid):
                continue
            pair_key = (int(src_nodeid), int(start_to))
            edge_ids = [str(v) for v in edge.get("edge_ids", []) if str(v)]
            path_nodes = [int(v) for v in edge.get("path_nodes", []) if v is not None]
            if not path_nodes:
                path_nodes = [int(src_nodeid), int(start_to)]
            if int(path_nodes[0]) != int(src_nodeid):
                path_nodes = [int(src_nodeid), *path_nodes]
            if int(path_nodes[-1]) != int(start_to):
                path_nodes = [*path_nodes, int(start_to)]
            arc_rank = int(len(pair_arcs.get(pair_key, [])) + 1)
            arc_id = f"arc_{int(src_nodeid)}_{int(start_to)}_{int(arc_rank)}"
            arc_payload = {
                "arc_id": str(arc_id),
                "src_nodeid": int(src_nodeid),
                "dst_nodeid": int(start_to),
                "raw_src_nodeid": int(edge.get("raw_src_nodeid", src_nodeid)),
                "raw_dst_nodeid": int(edge.get("raw_dst_nodeid", start_to)),
                "canonical_src_xsec_id": int(src_nodeid),
                "canonical_dst_xsec_id": int(start_to),
                "src_alias_applied": bool(edge.get("src_alias_applied", False)),
                "dst_alias_applied": bool(edge.get("dst_alias_applied", False)),
                "raw_pair": _pair_id_text(
                    int(edge.get("raw_src_nodeid", src_nodeid)),
                    int(edge.get("raw_dst_nodeid", start_to)),
                ),
                "canonical_pair": _pair_id_text(int(src_nodeid), int(start_to)),
                "raw_node_path": [int(v) for v in edge.get("raw_path_nodes", []) if v is not None],
                "source": _DIRECT_TOPOLOGY_ARC_SOURCE,
                "node_path": [int(v) for v in path_nodes],
                "edge_ids": edge_ids,
                "chain_len": int(len(edge_ids)),
                "line_coords": list(edge.get("line_coords", [])),
            }
            allowed_pairs.add(pair_key)
            outgoing[int(src_nodeid)].add(int(start_to))
            incoming[int(start_to)].add(int(src_nodeid))
            pair_prior_ids[pair_key].extend(edge_ids)
            pair_sources[pair_key].add(_DIRECT_TOPOLOGY_ARC_SOURCE)
            pair_paths[pair_key].append(dict(arc_payload))
            pair_arcs[pair_key].append(dict(arc_payload))
    for src_nodeid in sorted(xsec_ids):
        for edge in compressed_adj.get(int(src_nodeid), []):
            start_to_raw = edge.get("to")
            start_to = int(start_to_raw) if start_to_raw is not None else None
            start_edge_ids = [str(v) for v in edge.get("edge_ids", [])]
            start_path_nodes = [int(v) for v in edge.get("path_nodes", []) if v is not None]
            if start_to is None or int(start_to) in xsec_ids:
                continue
            search = _search_topology_next_nodes_from_anchor(
                compressed_adj,
                src_nodeid=int(src_nodeid),
                start_to=start_to,
                start_edge_ids=start_edge_ids,
                start_path_nodes=start_path_nodes,
                cross_nodes=xsec_ids,
                max_expansions=2048,
            )
            for dst_nodeid, records in sorted(search.get("dst_paths", {}).items()):
                if int(dst_nodeid) == int(src_nodeid):
                    continue
                pair_key = (int(src_nodeid), int(dst_nodeid))
                for rec in sorted(
                    list(records),
                    key=lambda item: (
                        int(item.get("chain_len", 0)),
                        ",".join(str(v) for v in item.get("edge_ids", [])),
                    ),
                ):
                    trace_only_pair_paths[pair_key].append(
                        {
                            "source": _TRACE_ONLY_TOPOLOGY_SOURCE,
                            "node_path": [int(v) for v in rec.get("node_path", [])],
                            "edge_ids": [str(v) for v in rec.get("edge_ids", []) if str(v)],
                            "chain_len": int(rec.get("chain_len", 0)),
                            "line_coords": list(rec.get("line_coords", [])),
                        }
                    )
    node_kind_map: dict[int, int | None] = {}
    for node in getattr(inputs, "node_records", ()) or ():
        try:
            nodeid = int(getattr(node, "nodeid", 0))
        except Exception:
            continue
        if nodeid <= 0:
            continue
        node_kind_map[nodeid] = getattr(node, "kind", None)
    terminal_nodes = {
        int(nodeid)
        for nodeid, srcs in incoming.items()
        if srcs and not outgoing.get(int(nodeid))
    }
    for src_nodeid in sorted(xsec_ids):
        for edge in compressed_adj.get(int(src_nodeid), []):
            start_to_raw = edge.get("to")
            start_to = int(start_to_raw) if start_to_raw is not None else None
            start_edge_ids = [str(v) for v in edge.get("edge_ids", [])]
            start_path_nodes = [int(v) for v in edge.get("path_nodes", []) if v is not None]
            if start_to is None:
                continue
            search = _search_topology_terminal_nodes_from_anchor(
                compressed_adj,
                src_nodeid=int(src_nodeid),
                start_to=start_to,
                start_edge_ids=start_edge_ids,
                start_path_nodes=start_path_nodes,
                terminal_nodes=terminal_nodes,
                max_expansions=2048,
            )
            for dst_nodeid, records in sorted(search.get("dst_paths", {}).items()):
                pair = (int(src_nodeid), int(dst_nodeid))
                if pair in allowed_pairs or int(src_nodeid) == int(dst_nodeid):
                    continue
                terminal_records = [rec for rec in records if int(len(rec.get("node_path", []))) >= 3]
                if not terminal_records:
                    continue
                terminal_records.sort(
                    key=lambda rec: (
                        int(rec.get("chain_len", 0)),
                        ",".join(str(v) for v in rec.get("edge_ids", [])),
                    )
                )
                for rec in terminal_records:
                    terminal_trace_paths[pair].append(
                        {
                            "source": _TERMINAL_TRACE_TOPOLOGY_SOURCE,
                            "node_path": [int(v) for v in rec.get("node_path", [])],
                            "edge_ids": [str(v) for v in rec.get("edge_ids", []) if str(v)],
                            "chain_len": int(rec.get("chain_len", 0)),
                            "line_coords": list(rec.get("line_coords", [])),
                        }
                    )
    direct_terminal_ownership = _build_direct_terminal_ownership(
        incoming={int(k): {int(v) for v in vals} for k, vals in incoming.items()},
        outgoing={int(k): {int(v) for v in vals} for k, vals in outgoing.items()},
        pair_paths={pair: list(vals) for pair, vals in pair_paths.items()},
    )
    terminal_reverse_ownership, reverse_owner_stats = _build_terminal_reverse_ownership(
        compressed_adj=compressed_adj,
        terminal_nodes={int(v) for v in terminal_nodes},
        cross_nodes=xsec_ids,
        max_expansions=2048,
    )
    return {
        "enabled": bool(allowed_pairs),
        "allowed_pairs": allowed_pairs,
        "incoming": {int(k): {int(v) for v in vals} for k, vals in incoming.items()},
        "outgoing": {int(k): {int(v) for v in vals} for k, vals in outgoing.items()},
        "pair_prior_ids": {pair: sorted(set(vals)) for pair, vals in pair_prior_ids.items()},
        "pair_sources": {pair: sorted(str(v) for v in vals) for pair, vals in pair_sources.items()},
        "pair_paths": {pair: list(vals) for pair, vals in pair_paths.items()},
        "pair_arcs": {pair: list(vals) for pair, vals in pair_arcs.items()},
        "trace_only_pair_paths": {pair: list(vals) for pair, vals in trace_only_pair_paths.items()},
        "terminal_trace_paths": {pair: list(vals) for pair, vals in terminal_trace_paths.items()},
        "xsec_alias_map": {int(raw): int(canonical) for raw, canonical in xsec_alias_map.items()},
        "xsec_alias_rows": list(xsec_alias_rows),
        "terminal_nodes": {int(v) for v in terminal_nodes},
        "terminal_direct_ownership": {int(k): dict(v) for k, v in direct_terminal_ownership.items()},
        "terminal_reverse_ownership": {int(k): dict(v) for k, v in terminal_reverse_ownership.items()},
        "node_kind_map": dict(node_kind_map),
        "graph_stats": {**dict(compress_stats), **dict(reverse_owner_stats)},
    }


def _topology_pair_semantics(
    *,
    src_nodeid: int,
    dst_nodeid: int,
    topology: dict[str, Any],
) -> dict[str, Any]:
    pair = (int(src_nodeid), int(dst_nodeid))
    allowed_pairs: set[tuple[int, int]] = topology.get("allowed_pairs", set())
    pair_sources = list(topology.get("pair_sources", {}).get(pair, []))
    pair_paths = list(topology.get("pair_paths", {}).get(pair, []))
    trace_only_paths = list(topology.get("trace_only_pair_paths", {}).get(pair, []))
    terminal_trace_paths = list(topology.get("terminal_trace_paths", {}).get(pair, []))
    source_type = ""
    if pair_sources:
        unique_sources = sorted(set(str(v) for v in pair_sources))
        source_type = unique_sources[0] if len(unique_sources) == 1 else "mixed"
    elif trace_only_paths:
        source_type = _TRACE_ONLY_TOPOLOGY_SOURCE
    elif terminal_trace_paths:
        source_type = _TERMINAL_TRACE_TOPOLOGY_SOURCE
    return {
        "pair": pair,
        "direct_allowed": bool(pair in allowed_pairs),
        "reverse_direct_allowed": bool((int(dst_nodeid), int(src_nodeid)) in allowed_pairs),
        "pair_sources": pair_sources,
        "pair_paths": pair_paths,
        "trace_only_paths": trace_only_paths,
        "terminal_trace_paths": terminal_trace_paths,
        "trace_only_available": bool(trace_only_paths),
        "terminal_trace_available": bool(terminal_trace_paths),
        "arc_source_type": str(source_type),
    }


def _topology_gate_reason(
    *,
    src_nodeid: int,
    dst_nodeid: int,
    topology: dict[str, Any],
) -> str | None:
    if not bool(topology.get("enabled")):
        return None
    semantics = _topology_pair_semantics(
        src_nodeid=int(src_nodeid),
        dst_nodeid=int(dst_nodeid),
        topology=topology,
    )
    direct_owner = dict(topology.get("terminal_direct_ownership", {})).get(int(dst_nodeid), {})
    reverse_owner = dict(topology.get("terminal_reverse_ownership", {})).get(int(dst_nodeid), {})
    owner = dict(direct_owner) if direct_owner else dict(reverse_owner)
    owner_status = str(owner.get("status", ""))
    owner_src_nodeid = owner.get("src_nodeid")
    if bool(semantics["direct_allowed"]):
        direct_owner_status = str(direct_owner.get("status", ""))
        direct_owner_src_nodeid = direct_owner.get("src_nodeid")
        if direct_owner_status == "ambiguous_owner":
            return "ambiguous_terminal_owner"
        if (
            direct_owner_status == "unique_owner"
            and direct_owner_src_nodeid is not None
            and int(direct_owner_src_nodeid) != int(src_nodeid)
        ):
            return "terminal_owner_mismatch"
        return None
    if bool(semantics["trace_only_available"]) or bool(semantics["terminal_trace_available"]):
        return "trace_only_reachability"
    if bool(semantics["reverse_direct_allowed"]):
        return "directed_path_not_supported"
    if int(dst_nodeid) in topology.get("terminal_nodes", set()):
        if owner_status == "ambiguous_owner":
            return "ambiguous_terminal_owner"
        if owner_status == "unique_owner" and owner_src_nodeid is not None and int(owner_src_nodeid) != int(src_nodeid):
            return "terminal_owner_mismatch"
    return "directed_path_not_supported"


def _assign_topology_arc(
    candidate: dict[str, Any],
    *,
    topology: dict[str, Any],
) -> dict[str, Any] | None:
    arcs = _direct_arc_rows(
        src_nodeid=int(candidate.get("src_nodeid", 0)),
        dst_nodeid=int(candidate.get("dst_nodeid", 0)),
        topology=topology,
    )
    candidate["topology_arc_is_direct_legal"] = bool(len(arcs) > 0)
    candidate["topology_arc_is_unique"] = bool(len(arcs) == 1)
    candidate["topology_arc_candidate_count"] = int(len(arcs))
    if len(arcs) != 1:
        return None
    chosen = arcs[0]
    candidate["topology_arc_distance_m"] = 0.0
    candidate["topology_arc_id"] = str(chosen.get("arc_id", ""))
    candidate["topology_arc_source_type"] = str(chosen.get("source", ""))
    candidate["topology_arc_edge_ids"] = [str(v) for v in chosen.get("edge_ids", [])]
    candidate["topology_arc_node_path"] = [int(v) for v in chosen.get("node_path", [])]
    candidate["canonical_src_xsec_id"] = int(chosen.get("canonical_src_xsec_id", candidate.get("src_nodeid", 0)))
    candidate["canonical_dst_xsec_id"] = int(chosen.get("canonical_dst_xsec_id", candidate.get("dst_nodeid", 0)))
    candidate["raw_src_nodeid"] = int(chosen.get("raw_src_nodeid", candidate.get("raw_src_nodeid", candidate.get("src_nodeid", 0))))
    candidate["raw_dst_nodeid"] = int(chosen.get("raw_dst_nodeid", candidate.get("raw_dst_nodeid", candidate.get("dst_nodeid", 0))))
    candidate["src_alias_applied"] = bool(chosen.get("src_alias_applied", candidate.get("src_alias_applied", False)))
    candidate["dst_alias_applied"] = bool(chosen.get("dst_alias_applied", candidate.get("dst_alias_applied", False)))
    return chosen


def _bridge_retain_decision(
    *,
    candidate: dict[str, Any],
    topology: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any] | None:
    src_nodeid = int(candidate.get("src_nodeid", 0))
    dst_nodeid = int(candidate.get("dst_nodeid", 0))
    if not _is_bridge_retain_candidate_enabled(src_nodeid=src_nodeid, dst_nodeid=dst_nodeid, params=params):
        return None
    diagnostics = _arc_legality_diagnostics(
        src_nodeid=int(src_nodeid),
        dst_nodeid=int(dst_nodeid),
        topology=topology,
    )
    candidate["bridge_candidate_retained"] = False
    candidate["bridge_chain_exists"] = bool(diagnostics["bridge_chain_exists"])
    candidate["bridge_chain_unique"] = bool(diagnostics["bridge_chain_unique"])
    candidate["bridge_chain_nodes"] = [int(v) for v in diagnostics["bridge_chain_nodes"]]
    candidate["bridge_chain_source"] = "diagnostic_only"
    candidate["bridge_diagnostic_reason"] = str(diagnostics["bridge_diagnostic_reason"])
    candidate["bridge_decision_stage"] = "bridge_retain_gate"
    candidate["bridge_decision_reason"] = "synthetic_arc_not_allowed" if bool(diagnostics["bridge_chain_exists"]) else "pair_not_direct_legal_arc"
    candidate["bridge_classification"] = str(diagnostics["bridge_diagnostic_reason"])
    return {
        "handled": True,
        "retained": False,
        "stage": "bridge_retain_gate",
        "reason": str(candidate["bridge_decision_reason"]),
        "bridge_classification": str(candidate["bridge_classification"]),
        "bridge_nodes": [int(v) for v in candidate["bridge_chain_nodes"]],
    }


def _candidate_support_count(candidate: dict[str, Any]) -> int:
    return int(max(1, len({str(v) for v in candidate.get("support_traj_ids", set())})))


def _candidate_feature_properties(
    candidate: dict[str, Any],
    *,
    stage: str,
    status: str,
    reason: str,
) -> dict[str, Any]:
    pair_distance = float(candidate.get("pair_midpoint_distance_m", 0.0))
    line_length = float(candidate.get("line_length_m", getattr(candidate.get("line"), "length", 0.0)))
    length_ratio = float(line_length / max(pair_distance, 1e-6)) if pair_distance > 1e-6 else 1.0
    return {
        "candidate_id": str(candidate.get("candidate_id", "")),
        "source": str(candidate.get("source", "")),
        "src_nodeid": int(candidate.get("src_nodeid", 0)),
        "dst_nodeid": int(candidate.get("dst_nodeid", 0)),
        "raw_src_nodeid": int(candidate.get("raw_src_nodeid", candidate.get("src_nodeid", 0))),
        "raw_dst_nodeid": int(candidate.get("raw_dst_nodeid", candidate.get("dst_nodeid", 0))),
        "canonical_src_xsec_id": int(candidate.get("canonical_src_xsec_id", candidate.get("src_nodeid", 0))),
        "canonical_dst_xsec_id": int(candidate.get("canonical_dst_xsec_id", candidate.get("dst_nodeid", 0))),
        "src_alias_applied": bool(candidate.get("src_alias_applied", False)),
        "dst_alias_applied": bool(candidate.get("dst_alias_applied", False)),
        "stage": str(stage),
        "status": str(status),
        "reason": str(reason),
        "support_count": int(_candidate_support_count(candidate)),
        "crossing_dist": int(candidate.get("other_xsec_crossing_count", 0)),
        "other_xsec_crossing_count": int(candidate.get("other_xsec_crossing_count", 0)),
        "inside_ratio": float(candidate.get("drivezone_ratio", 0.0)),
        "drivezone_ratio": float(candidate.get("drivezone_ratio", 0.0)),
        "gore_conflict": bool(candidate.get("crosses_divstrip", False)),
        "crosses_divstrip": bool(candidate.get("crosses_divstrip", False)),
        "line_length_m": float(line_length),
        "length_ratio": float(length_ratio),
        "pair_index_gap": int(candidate.get("pair_index_gap", 0)),
        "pairing_mode": str(candidate.get("pairing_mode", "")),
        "prior_supported": bool(candidate.get("prior_supported", False)),
        "traj_id": str(candidate.get("traj_id", "")),
        "topology_allowed": bool(candidate.get("topology_allowed", False)),
        "topology_reason": str(candidate.get("topology_reason", "")),
        "topology_arc_id": str(candidate.get("topology_arc_id", "")),
        "topology_arc_source_type": str(candidate.get("topology_arc_source_type", candidate.get("arc_source_type", ""))),
        "topology_arc_distance_m": candidate.get("topology_arc_distance_m"),
        "topology_arc_is_direct_legal": bool(candidate.get("topology_arc_is_direct_legal", False)),
        "topology_arc_is_unique": bool(candidate.get("topology_arc_is_unique", False)),
        "topology_arc_candidate_count": int(candidate.get("topology_arc_candidate_count", 0)),
        "bridge_candidate_retained": bool(candidate.get("bridge_candidate_retained", False)),
        "bridge_chain_exists": bool(candidate.get("bridge_chain_exists", False)),
        "bridge_chain_unique": bool(candidate.get("bridge_chain_unique", False)),
        "bridge_chain_nodes": [int(v) for v in candidate.get("bridge_chain_nodes", []) if v is not None],
        "bridge_chain_source": str(candidate.get("bridge_chain_source", "")),
        "bridge_diagnostic_reason": str(candidate.get("bridge_diagnostic_reason", "")),
        "bridge_decision_stage": str(candidate.get("bridge_decision_stage", "")),
        "bridge_decision_reason": str(candidate.get("bridge_decision_reason", "")),
    }


def _segment_length_ratio(segment: Segment, xsec_map: dict[int, BaseCrossSection]) -> float:
    pair_distance = _pair_midpoint_distance_for_nodes(xsec_map, int(segment.src_nodeid), int(segment.dst_nodeid))
    if pair_distance <= 1e-6:
        return 1.0
    return float(segment.length_m / max(pair_distance, 1e-6))


def _segment_feature_properties(segment: Segment, *, status: str, reason: str = "", dropped_reason: str = "") -> dict[str, Any]:
    props = {
        "segment_id": str(segment.segment_id),
        "src_nodeid": int(segment.src_nodeid),
        "dst_nodeid": int(segment.dst_nodeid),
        "raw_src_nodeid": int(segment.raw_src_nodeid if segment.raw_src_nodeid is not None else segment.src_nodeid),
        "raw_dst_nodeid": int(segment.raw_dst_nodeid if segment.raw_dst_nodeid is not None else segment.dst_nodeid),
        "canonical_src_xsec_id": int(
            segment.canonical_src_xsec_id if segment.canonical_src_xsec_id is not None else segment.src_nodeid
        ),
        "canonical_dst_xsec_id": int(
            segment.canonical_dst_xsec_id if segment.canonical_dst_xsec_id is not None else segment.dst_nodeid
        ),
        "src_alias_applied": bool(segment.src_alias_applied),
        "dst_alias_applied": bool(segment.dst_alias_applied),
        "support_count": int(segment.support_count),
        "dedup_count": int(segment.dedup_count),
        "source_modes": list(segment.source_modes),
        "prior_supported": bool(segment.prior_supported),
        "crossing_dist": int(segment.other_xsec_crossing_count),
        "other_xsec_crossing_count": int(segment.other_xsec_crossing_count),
        "formation_reason": str(segment.formation_reason),
        "length_m": float(segment.length_m),
        "inside_ratio": float(segment.drivezone_ratio),
        "drivezone_ratio": float(segment.drivezone_ratio),
        "gore_conflict": bool(segment.crosses_divstrip),
        "crosses_divstrip": bool(segment.crosses_divstrip),
        "topology_arc_id": str(segment.topology_arc_id),
        "topology_arc_source_type": str(segment.topology_arc_source_type),
        "topology_arc_edge_ids": [str(v) for v in segment.topology_arc_edge_ids],
        "topology_arc_node_path": [int(v) for v in segment.topology_arc_node_path],
        "topology_arc_is_direct_legal": bool(segment.topology_arc_is_direct_legal),
        "topology_arc_is_unique": bool(segment.topology_arc_is_unique),
        "bridge_candidate_retained": bool(segment.bridge_candidate_retained),
        "bridge_chain_exists": bool(segment.bridge_chain_exists),
        "bridge_chain_unique": bool(segment.bridge_chain_unique),
        "bridge_chain_nodes": [int(v) for v in segment.bridge_chain_nodes],
        "bridge_chain_source": str(segment.bridge_chain_source),
        "bridge_diagnostic_reason": str(segment.bridge_diagnostic_reason),
        "bridge_decision_stage": str(segment.bridge_decision_stage),
        "bridge_decision_reason": str(segment.bridge_decision_reason),
        "same_pair_rank": None if segment.same_pair_rank is None else int(segment.same_pair_rank),
        "kept_reason": str(segment.kept_reason),
        "status": str(status),
    }
    if reason:
        props["reason"] = str(reason)
    if dropped_reason:
        props["dropped_reason"] = str(dropped_reason)
    return props


def _apply_candidate_alias_identity(
    candidate: dict[str, Any],
    *,
    xsec_map: dict[int, BaseCrossSection],
    alias_map: dict[int, int],
) -> dict[str, Any]:
    raw_src_nodeid = int(candidate.get("raw_src_nodeid", candidate.get("src_nodeid", 0)))
    raw_dst_nodeid = int(candidate.get("raw_dst_nodeid", candidate.get("dst_nodeid", 0)))
    canonical_src_xsec_id = _canonical_xsec_id(int(raw_src_nodeid), alias_map)
    canonical_dst_xsec_id = _canonical_xsec_id(int(raw_dst_nodeid), alias_map)
    candidate["raw_src_nodeid"] = int(raw_src_nodeid)
    candidate["raw_dst_nodeid"] = int(raw_dst_nodeid)
    candidate["canonical_src_xsec_id"] = int(canonical_src_xsec_id)
    candidate["canonical_dst_xsec_id"] = int(canonical_dst_xsec_id)
    candidate["src_alias_applied"] = bool(int(raw_src_nodeid) != int(canonical_src_xsec_id))
    candidate["dst_alias_applied"] = bool(int(raw_dst_nodeid) != int(canonical_dst_xsec_id))
    candidate["src_nodeid"] = int(canonical_src_xsec_id)
    candidate["dst_nodeid"] = int(canonical_dst_xsec_id)
    candidate["raw_pair"] = _pair_id_text(int(raw_src_nodeid), int(raw_dst_nodeid))
    candidate["canonical_pair"] = _pair_id_text(int(canonical_src_xsec_id), int(canonical_dst_xsec_id))
    candidate["pair_midpoint_distance_m"] = float(
        _pair_midpoint_distance_for_nodes(xsec_map, int(canonical_src_xsec_id), int(canonical_dst_xsec_id))
    )
    return candidate


def _segment_candidates(
    inputs: PatchInputs,
    frame: InputFrame,
    prior_roads: list[Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    xsec_map = _xsec_map(frame)
    topology = _build_directed_topology(frame=frame, inputs=inputs, prior_roads=prior_roads, params=params)
    alias_map = {int(key): int(value) for key, value in dict(topology.get("xsec_alias_map", {})).items()}
    raw_candidates: list[dict[str, Any]] = []
    pairing_candidates: list[dict[str, Any]] = []
    accepted_before_topology_gate: list[dict[str, Any]] = []
    topology_kept_candidates: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    debug_features: list[tuple[LineString, dict[str, Any]]] = []
    raw_crossing_features: list[dict[str, Any]] = []
    filtered_crossing_features: list[dict[str, Any]] = []
    crossing_audit: dict[str, dict[str, Any]] = {}
    unanchored_prior_candidates_by_src: dict[int, list[dict[str, Any]]] = defaultdict(list)
    hit_buffer = float(params["TRAJ_XSEC_HIT_BUFFER_M"])
    max_other = int(params["SEGMENT_MAX_OTHER_XSEC_CROSSINGS"])
    min_len = float(params["SEGMENT_MIN_LENGTH_M"])
    min_drivezone = float(params["SEGMENT_MIN_DRIVEZONE_RATIO"])
    strict_adjacent = bool(int(params["STEP2_STRICT_ADJACENT_PAIRING"]))
    allow_cross1 = bool(int(params["STEP2_ALLOW_ONE_INTERMEDIATE_XSEC"]))
    pair_scoped_cross1_enabled = bool(int(params.get("STEP2_PAIR_SCOPED_CROSS1_EXCEPTION_ENABLE", 0)))
    pair_scoped_cross1_allowlist = _parse_pair_scoped_allowlist(params.get("STEP2_PAIR_SCOPED_CROSS1_ALLOWLIST", ""))
    divstrip_buffer = load_divstrip_buffer(inputs.divstrip_zone_metric, float(params["DIVSTRIP_BUFFER_M"]))
    topology_invalid_counter: Counter[str] = Counter()
    bridge_retain_counter: Counter[str] = Counter()

    def crossing_props(event: dict[str, Any]) -> dict[str, Any]:
        nodeid = int(event.get("nodeid", event.get("crossing_nodeid", 0)))
        return {
            "event_id": str(event.get("event_id", "")),
            "traj_id": str(event.get("traj_id", "")),
            "nodeid": int(nodeid),
            "crossing_nodeid": int(nodeid),
            "from_nodeid": event.get("from_nodeid"),
            "to_nodeid": event.get("to_nodeid"),
            "crossing_order_on_traj": int(event.get("crossing_order_on_traj", 0)),
            "local_heading": event.get("local_heading"),
            "in_drivezone_ratio_local": float(event.get("in_drivezone_ratio_local", 0.0)),
            "crosses_divstrip_local": bool(event.get("crosses_divstrip_local", False)),
        }

    def ensure_crossing_audit(event: dict[str, Any]) -> None:
        event_id = str(event.get("event_id", ""))
        if not event_id or event_id in crossing_audit:
            return
        crossing_audit[event_id] = {
            **crossing_props(event),
            "point": event["point"],
            "candidate_ids": set(),
            "pair_ids": set(),
            "topology_kept_pair_ids": set(),
            "selected_pair_ids": set(),
            "topology_kept_candidate_ids": set(),
            "selected_candidate_ids": set(),
            "dropped_reasons": [],
            "kept_reasons": set(),
        }

    def note_candidate_events(candidate: dict[str, Any], *, phase: str, reason: str = "") -> None:
        pair_id = _pair_id_text(int(candidate.get("src_nodeid", 0)), int(candidate.get("dst_nodeid", 0)))
        for key in ("start_event_id", "end_event_id"):
            event_id = str(candidate.get(key, ""))
            if not event_id or event_id not in crossing_audit:
                continue
            entry = crossing_audit[event_id]
            entry["candidate_ids"].add(str(candidate.get("candidate_id", "")))
            entry["pair_ids"].add(str(pair_id))
            if phase == "topology_kept":
                entry["topology_kept_candidate_ids"].add(str(candidate.get("candidate_id", "")))
                entry["topology_kept_pair_ids"].add(str(pair_id))
                if reason:
                    entry["kept_reasons"].add(str(reason))
            elif phase == "selected":
                entry["selected_candidate_ids"].add(str(candidate.get("candidate_id", "")))
                entry["selected_pair_ids"].add(str(pair_id))
                if reason:
                    entry["kept_reasons"].add(str(reason))
            elif phase == "dropped" and reason:
                entry["dropped_reasons"].append(str(reason))

    def record(candidate: dict[str, Any], *, stage: str, status: str, reason: str) -> None:
        line = candidate.get("line")
        if isinstance(line, LineString) and (not line.is_empty) and line.length > 1e-6:
            debug_features.append((line, _candidate_feature_properties(candidate, stage=stage, status=status, reason=reason)))

    def make_candidate(
        *,
        candidate_id: str,
        source: str,
        src_nodeid: int,
        dst_nodeid: int,
        line: LineString,
        support_traj_ids: set[str],
        intermediate_nodeids: list[int],
        prior_supported: bool,
        pair_index_gap: int,
        pairing_mode: str,
    ) -> dict[str, Any]:
        return {
            "candidate_id": str(candidate_id),
            "source": str(source),
            "src_nodeid": int(src_nodeid),
            "dst_nodeid": int(dst_nodeid),
            "raw_src_nodeid": int(src_nodeid),
            "raw_dst_nodeid": int(dst_nodeid),
            "canonical_src_xsec_id": int(src_nodeid),
            "canonical_dst_xsec_id": int(dst_nodeid),
            "src_alias_applied": False,
            "dst_alias_applied": False,
            "raw_pair": _pair_id_text(int(src_nodeid), int(dst_nodeid)),
            "canonical_pair": _pair_id_text(int(src_nodeid), int(dst_nodeid)),
            "line": line,
            "support_traj_ids": {str(v) for v in support_traj_ids},
            "intermediate_nodeids": [int(v) for v in intermediate_nodeids],
            "prior_supported": bool(prior_supported),
            "pair_index_gap": int(pair_index_gap),
            "pairing_mode": str(pairing_mode),
            "line_length_m": float(line.length),
            "pair_midpoint_distance_m": float(_pair_midpoint_distance_for_nodes(xsec_map, int(src_nodeid), int(dst_nodeid))),
            "traj_id": "" if str(source) != "traj" else next(iter({str(v) for v in support_traj_ids}), ""),
            "topology_arc_id": "",
            "topology_arc_source_type": "",
            "topology_arc_edge_ids": [],
            "topology_arc_node_path": [],
            "topology_arc_is_direct_legal": False,
            "topology_arc_is_unique": False,
            "topology_arc_candidate_count": 0,
            "arc_source_type": "",
            "bridge_candidate_retained": False,
            "bridge_chain_exists": False,
            "bridge_chain_unique": False,
            "bridge_chain_nodes": [],
            "bridge_chain_source": "",
            "bridge_diagnostic_reason": "",
            "bridge_decision_stage": "",
            "bridge_decision_reason": "",
            "bridge_classification": "",
        }

    def reject(candidate: dict[str, Any], *, stage: str, reason: str) -> None:
        candidate["reason"] = str(reason)
        candidate["dropped_stage"] = str(stage)
        rejected.append(candidate)
        note_candidate_events(candidate, phase="dropped", reason=reason)
        if str(reason) in _SEGMENT_TOPOLOGY_INVALID_REASONS:
            topology_invalid_counter[str(reason)] += 1
        record(candidate, stage=stage, status="dropped", reason=reason)

    def cross_filter_reason(candidate: dict[str, Any]) -> str | None:
        line = candidate["line"]
        src_nodeid = int(candidate["src_nodeid"])
        dst_nodeid = int(candidate["dst_nodeid"])
        inside_ratio = _drivezone_ratio(line, inputs.drivezone_zone_metric)
        other_nodes = _count_other_xsecs(line, src_nodeid, dst_nodeid, frame, hit_buffer)
        divstrip_cross = bool(divstrip_buffer is not None and (not divstrip_buffer.is_empty) and line.intersects(divstrip_buffer))
        candidate["drivezone_ratio"] = float(inside_ratio)
        candidate["other_xsec_nodes"] = [int(v) for v in other_nodes]
        candidate["other_xsec_crossing_count"] = int(len(other_nodes))
        candidate["crosses_divstrip"] = bool(divstrip_cross)
        if float(line.length) < min_len:
            return "segment_too_short"
        if inside_ratio < min_drivezone:
            return "segment_outside_drivezone"
        if divstrip_cross:
            return "segment_crosses_divstrip"
        if len(other_nodes) > max_other:
            return "segment_crosses_too_many_other_xsecs"
        if (
            len(other_nodes) == 1
            and not allow_cross1
            and pair_scoped_cross1_enabled
            and (int(src_nodeid), int(dst_nodeid)) not in pair_scoped_cross1_allowlist
        ):
            return "cross1_pair_not_allowlisted"
        return None

    def accept_candidate(candidate: dict[str, Any]) -> None:
        candidate["reason"] = "candidate_survives_cross_filter"
        accepted.append(candidate)
        note_candidate_events(candidate, phase="selected", reason="candidate_survives_cross_filter")
        record(candidate, stage="cross_filter", status="selected", reason="candidate_survives_cross_filter")

    for traj in inputs.trajectories:
        traj_line = _trajectory_line(traj)
        if traj_line is None:
            continue
        events = _trajectory_events(
            traj,
            frame,
            hit_buffer,
            drivezone=inputs.drivezone_zone_metric,
            divstrip_buffer=divstrip_buffer,
        )
        if len(events) < 2:
            continue
        for event in events:
            ensure_crossing_audit(event)
        for i in range(len(events) - 1):
            for j in range(i + 1, len(events)):
                src_nodeid = int(events[i]["nodeid"])
                dst_nodeid = int(events[j]["nodeid"])
                if src_nodeid == dst_nodeid:
                    continue
                intermediate = sorted(
                    {
                        int(events[k]["nodeid"])
                        for k in range(i + 1, j)
                        if int(events[k]["nodeid"]) not in {src_nodeid, dst_nodeid}
                    }
                )
                subline = _candidate_subline_from_traj(traj, int(events[i]["index"]), int(events[j]["index"]))
                if subline is None:
                    continue
                candidate = make_candidate(
                    candidate_id=f"traj_{traj.traj_id}_{i}_{j}",
                    source="traj",
                    src_nodeid=int(src_nodeid),
                    dst_nodeid=int(dst_nodeid),
                    line=subline,
                    support_traj_ids={str(traj.traj_id)},
                    intermediate_nodeids=[int(v) for v in intermediate],
                    prior_supported=False,
                    pair_index_gap=int(j - i),
                    pairing_mode="adjacent" if int(j - i) == 1 else "skip_pair",
                )
                _apply_candidate_alias_identity(candidate, xsec_map=xsec_map, alias_map=alias_map)
                candidate["start_event_id"] = str(events[i]["event_id"])
                candidate["end_event_id"] = str(events[j]["event_id"])
                raw_candidates.append(candidate)
                record(candidate, stage="raw_generated", status="generated", reason="raw_candidate_generated")
    for idx, road in enumerate(prior_roads):
        line = getattr(road, "line", None)
        if not isinstance(line, LineString) or line.is_empty or line.length <= 1e-6:
            continue
        src_nodeid = int(getattr(road, "snodeid", 0))
        dst_nodeid = int(getattr(road, "enodeid", 0))
        candidate = make_candidate(
            candidate_id=f"prior_{idx}",
            source="prior",
            src_nodeid=int(src_nodeid),
            dst_nodeid=int(dst_nodeid),
            line=line,
            support_traj_ids=set(),
            intermediate_nodeids=[],
            prior_supported=True,
            pair_index_gap=0,
            pairing_mode="prior",
        )
        _apply_candidate_alias_identity(candidate, xsec_map=xsec_map, alias_map=alias_map)
        raw_candidates.append(candidate)
        record(candidate, stage="raw_generated", status="generated", reason="raw_candidate_generated")
        if int(candidate["src_nodeid"]) not in xsec_map or int(candidate["dst_nodeid"]) not in xsec_map:
            start_pt = Point(float(line.coords[0][0]), float(line.coords[0][1]))
            end_pt = Point(float(line.coords[-1][0]), float(line.coords[-1][1]))
            best_pair = None
            best_cost = float("inf")
            for xsec_a in frame.base_cross_sections:
                for xsec_b in frame.base_cross_sections:
                    if int(xsec_a.nodeid) == int(xsec_b.nodeid):
                        continue
                    cost_direct = float(start_pt.distance(xsec_a.geometry_metric())) + float(end_pt.distance(xsec_b.geometry_metric()))
                    cost_reverse = float(start_pt.distance(xsec_b.geometry_metric())) + float(end_pt.distance(xsec_a.geometry_metric()))
                    if cost_direct < best_cost:
                        best_cost = cost_direct
                        best_pair = (int(xsec_a.nodeid), int(xsec_b.nodeid))
                    if cost_reverse < best_cost:
                        best_cost = cost_reverse
                        best_pair = (int(xsec_b.nodeid), int(xsec_a.nodeid))
            if best_pair is None or best_cost > float(params["PRIOR_ENDPOINT_ANCHOR_M"]) * 2.0:
                candidate["prior_anchor_cost_m"] = None if not math.isfinite(best_cost) else float(best_cost)
                candidate["prior_anchor_best_pair"] = None if best_pair is None else [int(best_pair[0]), int(best_pair[1])]
                unanchored_prior_candidates_by_src[int(src_nodeid)].append(
                    {
                        "candidate_id": str(candidate["candidate_id"]),
                        "src_nodeid": int(src_nodeid),
                        "dst_nodeid": int(dst_nodeid),
                        "pair_id": _pair_id_text(int(src_nodeid), int(dst_nodeid)),
                        "prior_anchor_cost_m": None if not math.isfinite(best_cost) else float(best_cost),
                        "prior_anchor_best_pair": None if best_pair is None else [int(best_pair[0]), int(best_pair[1])],
                    }
                )
                reject(candidate, stage="pairing_filter", reason="prior_endpoints_not_anchored")
                continue
            candidate["src_nodeid"], candidate["dst_nodeid"] = (int(best_pair[0]), int(best_pair[1]))
            candidate["canonical_src_xsec_id"], candidate["canonical_dst_xsec_id"] = (int(best_pair[0]), int(best_pair[1]))
            candidate["pair_midpoint_distance_m"] = float(_pair_midpoint_distance_for_nodes(xsec_map, int(best_pair[0]), int(best_pair[1])))
            candidate["canonical_pair"] = _pair_id_text(int(best_pair[0]), int(best_pair[1]))
        pairing_candidates.append(candidate)
        record(candidate, stage="pairing_filter", status="selected", reason="prior_candidate_retained")
    for candidate in raw_candidates:
        if str(candidate["source"]) != "traj":
            continue
        if strict_adjacent and int(candidate.get("pair_index_gap", 0)) > 1:
            bridge_decision = _bridge_retain_decision(candidate=candidate, topology=topology, params=params)
            if bridge_decision is not None:
                bridge_retain_counter[f"{str(bridge_decision.get('stage', 'bridge_retain_gate'))}:{str(bridge_decision.get('reason', 'unknown'))}"] += 1
                reject(
                    candidate,
                    stage=str(bridge_decision.get("stage", "bridge_retain_gate")),
                    reason=str(bridge_decision.get("reason", "synthetic_arc_not_allowed")),
                )
                continue
            topology_semantics = _topology_pair_semantics(
                src_nodeid=int(candidate["src_nodeid"]),
                dst_nodeid=int(candidate["dst_nodeid"]),
                topology=topology,
            )
            if bool(topology_semantics.get("trace_only_available")) or bool(topology_semantics.get("terminal_trace_available")):
                candidate["topology_reason"] = "trace_only_reachability"
                reject(
                    candidate,
                    stage="semantic_hard_gate",
                    reason="trace_only_reachability",
                )
                continue
            if bool(topology_semantics.get("reverse_direct_allowed")):
                candidate["topology_reason"] = "directed_path_not_supported"
                reject(
                    candidate,
                    stage="semantic_hard_gate",
                    reason="directed_path_not_supported",
                )
                continue
            reject(candidate, stage="pairing_filter", reason="non_adjacent_pair_blocked")
            continue
        pairing_candidates.append(candidate)
        reason = "adjacent_pair_retained" if int(candidate.get("pair_index_gap", 0)) <= 1 else "non_adjacent_pair_retained"
        if bool(candidate.get("bridge_candidate_retained", False)):
            reason = str(candidate.get("bridge_decision_reason", "bridge_pair_scoped_retained"))
        record(candidate, stage="pairing_filter", status="selected", reason=reason)
    topology_ready_candidates: list[dict[str, Any]] = []
    for candidate in pairing_candidates:
        geometry_probe = dict(candidate)
        pre_reason = cross_filter_reason(geometry_probe)
        if pre_reason is None:
            accepted_before_topology_gate.append(geometry_probe)
        topology_semantics = _topology_pair_semantics(
            src_nodeid=int(candidate["src_nodeid"]),
            dst_nodeid=int(candidate["dst_nodeid"]),
            topology=topology,
        )
        reverse_owner = (
            topology.get("terminal_direct_ownership", {}).get(int(candidate["dst_nodeid"]))
            or topology.get("terminal_reverse_ownership", {}).get(int(candidate["dst_nodeid"]), {})
        )
        candidate["topology_reverse_owner_status"] = str(reverse_owner.get("status", ""))
        candidate["topology_reverse_owner_src_nodeid"] = reverse_owner.get("src_nodeid")
        candidate["topology_reverse_owner_src_nodeids"] = [
            int(v) for v in reverse_owner.get("src_nodeids", []) if v is not None
        ]
        candidate["topology_pair_paths"] = list(topology_semantics.get("pair_paths", []))
        candidate["topology_trace_only_paths"] = list(topology_semantics.get("trace_only_paths", []))
        candidate["topology_terminal_trace_paths"] = list(topology_semantics.get("terminal_trace_paths", []))
        candidate["arc_source_type"] = str(topology_semantics.get("arc_source_type", ""))
        topology_reason = _production_arc_gate_reason(candidate=candidate, topology=topology)
        candidate["topology_allowed"] = bool(topology_reason is None)
        candidate["topology_reason"] = "" if topology_reason is None else str(topology_reason)
        if topology_reason is not None:
            reject(candidate, stage="semantic_hard_gate", reason=str(topology_reason))
            continue
        if bool(topology.get("enabled")):
            assigned_arc = _assign_topology_arc(candidate, topology=topology)
            if assigned_arc is None:
                reject(candidate, stage="semantic_hard_gate", reason="arc_unique_connectivity_violation")
                continue
        topology_ready_candidates.append(candidate)

    arc_has_prior_candidate: set[tuple[int, int, str]] = set()
    arc_traj_support_ids: dict[tuple[int, int, str], set[str]] = defaultdict(set)
    for candidate in topology_ready_candidates:
        arc_key = (
            int(candidate["src_nodeid"]),
            int(candidate["dst_nodeid"]),
            str(candidate.get("topology_arc_id", "") or ""),
        )
        if str(candidate.get("source", "")) == "prior":
            arc_has_prior_candidate.add(arc_key)
            continue
        for traj_id in candidate.get("support_traj_ids", set()) or []:
            arc_traj_support_ids[arc_key].add(str(traj_id))

    def ownership_gate_reason(candidate: dict[str, Any]) -> str | None:
        if str(candidate.get("source", "")) != "traj":
            return None
        if str(candidate.get("pairing_mode", "")) != "adjacent":
            return None
        pair = (int(candidate["src_nodeid"]), int(candidate["dst_nodeid"]))
        arc_key = (
            int(candidate["src_nodeid"]),
            int(candidate["dst_nodeid"]),
            str(candidate.get("topology_arc_id", "") or ""),
        )
        if arc_key in arc_has_prior_candidate:
            return None
        if int(len(arc_traj_support_ids.get(arc_key, set()))) > 1:
            return None
        competing_priors = list(unanchored_prior_candidates_by_src.get(int(candidate["src_nodeid"]), []))
        competing_pairs = {
            (int(item.get("src_nodeid", 0)), int(item.get("dst_nodeid", 0)))
            for item in competing_priors
        }
        if len(competing_pairs) != 1:
            return None
        competing_pair = next(iter(competing_pairs))
        if competing_pair == pair:
            return None
        competing_dst_nodeids = {int(item.get("dst_nodeid", 0)) for item in competing_priors}
        if len(competing_dst_nodeids) != 1:
            return None
        competing_dst_nodeid = next(iter(competing_dst_nodeids))
        node_path = [int(v) for v in candidate.get("topology_arc_node_path", []) if v is not None]
        matching_paths: list[list[int]] = []
        if (
            len(node_path) == 3
            and int(node_path[0]) == int(candidate["src_nodeid"])
            and int(node_path[1]) == int(competing_dst_nodeid)
            and int(node_path[-1]) == int(candidate["dst_nodeid"])
        ):
            matching_paths.append(list(node_path))
        if not matching_paths:
            return None
        candidate["competing_prior_pair_ids"] = sorted(
            str(item.get("pair_id", "")) for item in competing_priors if str(item.get("pair_id", ""))
        )
        candidate["competing_prior_candidate_ids"] = sorted(
            str(item.get("candidate_id", "")) for item in competing_priors if str(item.get("candidate_id", ""))
        )
        candidate["competing_prior_anchor_cost_m"] = [item.get("prior_anchor_cost_m") for item in competing_priors]
        candidate["competing_prior_anchor_best_pairs"] = [item.get("prior_anchor_best_pair") for item in competing_priors]
        candidate["competing_prior_trace_paths"] = [list(path) for path in matching_paths]
        return "src_conflicts_with_unique_unanchored_prior_endpoint"

    for candidate in topology_ready_candidates:
        ownership_reason = ownership_gate_reason(candidate)
        if ownership_reason is not None:
            reject(candidate, stage="semantic_hard_gate", reason=str(ownership_reason))
            continue
        topology_kept_candidates.append(candidate)
        note_candidate_events(candidate, phase="topology_kept", reason="topology_legal_candidate")
        cross_reason = cross_filter_reason(candidate)
        if cross_reason is not None:
            reject(candidate, stage="cross_filter", reason=str(cross_reason))
            continue
        accept_candidate(candidate)
    for event_id in sorted(crossing_audit.keys()):
        entry = crossing_audit[event_id]
        dropped_reason = ""
        if entry["dropped_reasons"]:
            counts = Counter(str(v) for v in entry["dropped_reasons"])
            dropped_reason = str(sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))[0][0])
        kept_reason = ""
        if entry["kept_reasons"]:
            kept_reason = "|".join(sorted(str(v) for v in entry["kept_reasons"]))
        raw_crossing_features.append(
            {
                "type": "Feature",
                "geometry": mapping(entry["point"]),
                "properties": {
                    **crossing_props(entry),
                    "candidate_count": int(len(entry["candidate_ids"])),
                    "pair_count": int(len(entry["pair_ids"])),
                    "pair_ids": sorted(str(v) for v in entry["pair_ids"]),
                    "topology_kept_pair_ids": sorted(str(v) for v in entry["topology_kept_pair_ids"]),
                    "selected_pair_ids": sorted(str(v) for v in entry["selected_pair_ids"]),
                    "topology_kept_candidate_count": int(len(entry["topology_kept_candidate_ids"])),
                    "selected_candidate_count": int(len(entry["selected_candidate_ids"])),
                    "kept_reason": str(kept_reason),
                    "dropped_reason": str(dropped_reason),
                    "status": "raw",
                },
            }
        )
        filtered_crossing_features.append(
            {
                "type": "Feature",
                "geometry": mapping(entry["point"]),
                "properties": {
                    **crossing_props(entry),
                    "candidate_count": int(len(entry["candidate_ids"])),
                    "pair_count": int(len(entry["pair_ids"])),
                    "pair_ids": sorted(str(v) for v in entry["pair_ids"]),
                    "topology_kept_pair_ids": sorted(str(v) for v in entry["topology_kept_pair_ids"]),
                    "selected_pair_ids": sorted(str(v) for v in entry["selected_pair_ids"]),
                    "topology_kept_candidate_count": int(len(entry["topology_kept_candidate_ids"])),
                    "selected_candidate_count": int(len(entry["selected_candidate_ids"])),
                    "kept_reason": str(kept_reason),
                    "dropped_reason": str(dropped_reason),
                    "status": "kept" if entry["topology_kept_candidate_ids"] else "dropped",
                },
            }
        )
    return {
        "raw_candidates": raw_candidates,
        "paired_candidates": pairing_candidates,
        "accepted_candidates_before_topology_gate": accepted_before_topology_gate,
        "topology_kept_candidates": topology_kept_candidates,
        "accepted_candidates": accepted,
        "rejected_candidates": rejected,
        "candidate_debug_features": debug_features,
        "raw_crossing_features": raw_crossing_features,
        "filtered_crossing_features": filtered_crossing_features,
        "topology": topology,
        "stats": {
            "raw_candidate_count": int(len(raw_candidates)),
            "alias_normalized_candidate_count": int(
                sum(
                    1
                    for item in raw_candidates
                    if bool(item.get("src_alias_applied", False) or item.get("dst_alias_applied", False))
                )
            ),
            "xsec_alias_count": int(len(alias_map)),
            "xsec_alias_rows": list(topology.get("xsec_alias_rows", [])),
            "candidate_count_after_pairing": int(len(pairing_candidates)),
            "candidate_count_after_topology_gate": int(len(topology_kept_candidates)),
            "candidate_count_after_cross_filter": int(len(accepted)),
            "crossing_dist_hist_raw": _histogram([int(item.get("other_xsec_crossing_count", 0)) for item in pairing_candidates]),
            "traj_crossing_raw_count": int(len(raw_crossing_features)),
            "traj_crossing_filtered_count": int(
                sum(1 for feat in filtered_crossing_features if int(feat["properties"].get("topology_kept_candidate_count", 0)) > 0)
            ),
            "unanchored_prior_conflict_segment_count": int(
                topology_invalid_counter.get("src_conflicts_with_unique_unanchored_prior_endpoint", 0)
            ),
            "directed_path_not_supported_count": int(topology_invalid_counter.get("directed_path_not_supported", 0)),
            "trace_only_reachability_segment_count": int(topology_invalid_counter.get("trace_only_reachability", 0)),
            "terminal_owner_mismatch_segment_count": int(topology_invalid_counter.get("terminal_owner_mismatch", 0)),
            "ambiguous_terminal_owner_segment_count": int(topology_invalid_counter.get("ambiguous_terminal_owner", 0)),
            "pair_not_direct_legal_arc_count": int(topology_invalid_counter.get("pair_not_direct_legal_arc", 0)),
            "non_unique_direct_legal_arc_count": int(topology_invalid_counter.get("non_unique_direct_legal_arc", 0)),
            "arc_unique_connectivity_violation_count": int(
                topology_invalid_counter.get("arc_unique_connectivity_violation", 0)
            ),
            "synthetic_arc_not_allowed_count": int(topology_invalid_counter.get("synthetic_arc_not_allowed", 0)),
            "bridge_retain_attempt_count": int(sum(int(v) for v in bridge_retain_counter.values())),
            "bridge_retain_success_count": int(
                sum(int(v) for key, v in bridge_retain_counter.items() if str(key) == "bridge_retain:bridge_pair_scoped_retained")
            ),
            "bridge_retain_rejected_count": int(
                sum(int(v) for key, v in bridge_retain_counter.items() if str(key).startswith("bridge_retain_gate:"))
            ),
            "bridge_retain_reason_hist": {str(key): int(value) for key, value in sorted(bridge_retain_counter.items())},
            "directionally_invalid_segment_count": int(topology_invalid_counter.get("directed_path_not_supported", 0)),
            "topology_invalid_segment_count": int(
                topology_invalid_counter.get("directed_path_not_supported", 0)
                + topology_invalid_counter.get("trace_only_reachability", 0)
                + topology_invalid_counter.get("pair_not_direct_legal_arc", 0)
                + topology_invalid_counter.get("non_unique_direct_legal_arc", 0)
                + topology_invalid_counter.get("arc_unique_connectivity_violation", 0)
                + topology_invalid_counter.get("synthetic_arc_not_allowed", 0)
            ),
            "terminal_node_invalid_segment_count": int(
                topology_invalid_counter.get("terminal_owner_mismatch", 0)
                + topology_invalid_counter.get("ambiguous_terminal_owner", 0)
            ),
        },
    }


def _cluster_segments(candidates: list[dict[str, Any]], frame: InputFrame, params: dict[str, Any]) -> list[Segment]:
    xsec_map = _xsec_map(frame)
    by_pair: dict[tuple[int, int, str], list[dict[str, Any]]] = {}
    for candidate in candidates:
        key = (
            int(candidate["src_nodeid"]),
            int(candidate["dst_nodeid"]),
            str(candidate.get("topology_arc_id", "") or ""),
        )
        by_pair.setdefault(key, []).append(candidate)
    out: list[Segment] = []
    cluster_offset = float(params["SEGMENT_CLUSTER_OFFSET_M"])
    cluster_line_dist = float(params["SEGMENT_CLUSTER_LINE_DIST_M"])
    for (src_nodeid, dst_nodeid, topology_arc_id), pair_candidates in sorted(by_pair.items()):
        src_xsec = xsec_map[int(src_nodeid)]
        dst_xsec = xsec_map[int(dst_nodeid)]
        scored: list[dict[str, Any]] = []
        for candidate in pair_candidates:
            axis = _axis_line_for_pair(candidate["line"], src_xsec, dst_xsec)
            candidate["offset_m"] = _signed_offset(candidate["line"], axis)
            scored.append(candidate)
        scored.sort(key=lambda item: float(item["offset_m"]))
        clusters: list[list[dict[str, Any]]] = []
        for candidate in scored:
            placed = False
            for cluster in clusters:
                ref = cluster[0]
                if (
                    abs(float(candidate["offset_m"]) - float(ref["offset_m"])) <= cluster_offset
                    and float(candidate["line"].distance(ref["line"])) <= cluster_line_dist
                ):
                    cluster.append(candidate)
                    placed = True
                    break
            if not placed:
                clusters.append([candidate])
        ordered_clusters = sorted(
            clusters,
            key=lambda items: float(sum(float(item["offset_m"]) for item in items) / max(1, len(items))),
        )
        dedup_count = int(len(ordered_clusters))
        for rank, cluster in enumerate(ordered_clusters, start=1):
            representative = sorted(
                cluster,
                key=lambda item: (
                    0 if str(item["source"]) == "traj" else 1,
                    -len(item["support_traj_ids"]),
                    -float(item["line"].length),
                ),
            )[0]
            source_modes = tuple(sorted({str(item["source"]) for item in cluster}))
            support_traj_ids = tuple(sorted({str(tid) for item in cluster for tid in item["support_traj_ids"]}))
            formation_reason = "mixed_support"
            if source_modes == ("prior",):
                formation_reason = "prior_only_cluster"
            elif source_modes == ("traj",):
                formation_reason = "traj_supported_cluster"
            representative_offset = float(sum(float(item["offset_m"]) for item in cluster) / max(1, len(cluster)))
            arc_token = str(topology_arc_id or "pair")
            raw_src_nodeid = next(
                (
                    int(item.get("raw_src_nodeid", item["src_nodeid"]))
                    for item in cluster
                    if bool(item.get("src_alias_applied", False))
                ),
                int(representative.get("raw_src_nodeid", representative["src_nodeid"])),
            )
            raw_dst_nodeid = next(
                (
                    int(item.get("raw_dst_nodeid", item["dst_nodeid"]))
                    for item in cluster
                    if bool(item.get("dst_alias_applied", False))
                ),
                int(representative.get("raw_dst_nodeid", representative["dst_nodeid"])),
            )
            out.append(
                Segment(
                    segment_id=f"seg_{src_nodeid}_{dst_nodeid}_{arc_token}_{rank}",
                    src_nodeid=int(src_nodeid),
                    dst_nodeid=int(dst_nodeid),
                    direction="src->dst",
                    geometry_coords=line_to_coords(representative["line"]),
                    candidate_ids=tuple(str(item["candidate_id"]) for item in cluster),
                    source_modes=source_modes,
                    support_traj_ids=support_traj_ids,
                    support_count=int(len(cluster)),
                    dedup_count=int(dedup_count),
                    representative_offset_m=float(representative_offset),
                    other_xsec_crossing_count=int(min(int(item.get("other_xsec_crossing_count", 0)) for item in cluster)),
                    tolerated_other_xsec_crossings=int(params["SEGMENT_MAX_OTHER_XSEC_CROSSINGS"]),
                    prior_supported=bool(any(bool(item["prior_supported"]) for item in cluster)),
                    formation_reason=str(formation_reason),
                    length_m=float(representative["line"].length),
                    drivezone_ratio=float(sum(float(item.get("drivezone_ratio", 0.0)) for item in cluster) / max(1, len(cluster))),
                    crosses_divstrip=bool(any(bool(item.get("crosses_divstrip", False)) for item in cluster)),
                    topology_arc_id=str(topology_arc_id or ""),
                    topology_arc_source_type=str(representative.get("topology_arc_source_type", representative.get("arc_source_type", ""))),
                    topology_arc_edge_ids=tuple(str(v) for v in representative.get("topology_arc_edge_ids", [])),
                    topology_arc_node_path=tuple(int(v) for v in representative.get("topology_arc_node_path", [])),
                    topology_arc_is_direct_legal=bool(representative.get("topology_arc_is_direct_legal", False)),
                    topology_arc_is_unique=bool(representative.get("topology_arc_is_unique", False)),
                    bridge_candidate_retained=bool(any(bool(item.get("bridge_candidate_retained", False)) for item in cluster)),
                    bridge_chain_exists=bool(any(bool(item.get("bridge_chain_exists", False)) for item in cluster)),
                    bridge_chain_unique=bool(representative.get("bridge_chain_unique", False)),
                    bridge_chain_nodes=tuple(int(v) for v in representative.get("bridge_chain_nodes", [])),
                    bridge_chain_source=str(representative.get("bridge_chain_source", "")),
                    bridge_diagnostic_reason=str(representative.get("bridge_diagnostic_reason", "")),
                    bridge_decision_stage=str(representative.get("bridge_decision_stage", "")),
                    bridge_decision_reason=str(representative.get("bridge_decision_reason", "")),
                    raw_src_nodeid=int(raw_src_nodeid),
                    raw_dst_nodeid=int(raw_dst_nodeid),
                    canonical_src_xsec_id=int(representative.get("canonical_src_xsec_id", src_nodeid)),
                    canonical_dst_xsec_id=int(representative.get("canonical_dst_xsec_id", dst_nodeid)),
                    src_alias_applied=bool(any(bool(item.get("src_alias_applied", False)) for item in cluster)),
                    dst_alias_applied=bool(any(bool(item.get("dst_alias_applied", False)) for item in cluster)),
                )
            )
    return out


def _select_segments_same_pair(
    segments: list[Segment],
    frame: InputFrame,
    params: dict[str, Any],
) -> tuple[list[Segment], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    xsec_map = _xsec_map(frame)
    topk = max(1, int(params["STEP2_SAME_PAIR_TOPK"]))
    allow_cross1 = bool(int(params["STEP2_ALLOW_ONE_INTERMEDIATE_XSEC"]))
    cross1_min_support = max(1, int(params["STEP2_CROSS1_MIN_SUPPORT"]))
    cross1_min_drivezone = float(params["STEP2_CROSS1_MIN_DRIVEZONE_RATIO"])
    cross1_max_length_ratio = float(params["STEP2_CROSS1_MAX_LENGTH_RATIO"])
    cross1_require_no_cross0 = bool(int(params["STEP2_CROSS1_REQUIRE_NO_CROSS0_BETTER"]))
    pair_scoped_cross1_enabled = bool(int(params.get("STEP2_PAIR_SCOPED_CROSS1_EXCEPTION_ENABLE", 0)))
    pair_scoped_cross1_allowlist = _parse_pair_scoped_allowlist(params.get("STEP2_PAIR_SCOPED_CROSS1_ALLOWLIST", ""))
    by_pair: dict[tuple[int, int, str], list[Segment]] = {}
    for segment in segments:
        by_pair.setdefault(
            (
                int(segment.src_nodeid),
                int(segment.dst_nodeid),
                str(segment.topology_arc_id or ""),
            ),
            [],
        ).append(segment)

    def sort_key(segment: Segment) -> tuple[Any, ...]:
        return (
            int(segment.other_xsec_crossing_count),
            -int(segment.support_count),
            -float(segment.drivezone_ratio),
            1 if bool(segment.crosses_divstrip) else 0,
            float(_segment_length_ratio(segment, xsec_map)),
            float(segment.length_m),
            abs(float(segment.representative_offset_m)),
            str(segment.segment_id),
        )

    selected: list[Segment] = []
    dropped: list[dict[str, Any]] = []
    group_payloads: list[dict[str, Any]] = []
    zero_selected_pairs: list[dict[str, Any]] = []
    pair_scoped_exception_hits: set[tuple[int, int]] = set()
    selected_cross1_exception_count = 0
    bridge_retained_pair_ids: set[str] = set()
    bridge_retained_segment_count = 0
    for (src_nodeid, dst_nodeid, topology_arc_id), pair_segments in sorted(by_pair.items()):
        ordered = sorted(pair_segments, key=sort_key)
        has_cross0 = any(int(segment.other_xsec_crossing_count) == 0 for segment in ordered)
        pair_scoped_exception_applicable = bool(
            pair_scoped_cross1_enabled and (int(src_nodeid), int(dst_nodeid)) in pair_scoped_cross1_allowlist
        )
        kept_count = 0
        segment_payloads: list[dict[str, Any]] = []
        for rank, segment in enumerate(ordered, start=1):
            length_ratio = float(_segment_length_ratio(segment, xsec_map))
            dropped_reason = ""
            kept_reason = ""
            selected_via_pair_scoped_exception = False
            if int(segment.other_xsec_crossing_count) == 0:
                kept_reason = "cross0_primary"
            elif bool(segment.bridge_candidate_retained):
                dropped_reason = str(segment.bridge_decision_reason or "synthetic_arc_not_allowed")
            else:
                if allow_cross1:
                    if int(segment.support_count) < cross1_min_support:
                        dropped_reason = "cross1_support_too_low"
                    elif float(segment.drivezone_ratio) < cross1_min_drivezone:
                        dropped_reason = "cross1_drivezone_ratio_too_low"
                    elif bool(segment.crosses_divstrip):
                        dropped_reason = "cross1_gore_conflict"
                    elif float(length_ratio) > cross1_max_length_ratio:
                        dropped_reason = "cross1_length_ratio_too_high"
                    elif cross1_require_no_cross0 and has_cross0:
                        dropped_reason = "cross1_has_cross0_alternative"
                    else:
                        kept_reason = (
                            f"cross1_exception:support={int(segment.support_count)}:"
                            f"drivezone_ratio={float(segment.drivezone_ratio):.3f}:"
                            f"length_ratio={float(length_ratio):.3f}"
                        )
                elif pair_scoped_exception_applicable:
                    if int(rank) != 1:
                        dropped_reason = "cross1_pair_scoped_not_best_rank"
                    elif int(segment.support_count) <= 0:
                        dropped_reason = "cross1_support_zero"
                    elif float(segment.drivezone_ratio) < cross1_min_drivezone:
                        dropped_reason = "cross1_drivezone_ratio_too_low"
                    elif bool(segment.crosses_divstrip):
                        dropped_reason = "cross1_gore_conflict"
                    elif float(length_ratio) > cross1_max_length_ratio:
                        dropped_reason = "cross1_length_ratio_too_high"
                    elif has_cross0:
                        dropped_reason = "cross1_has_cross0_alternative"
                    else:
                        kept_reason = (
                            "pair_scoped_cross1_exception:"
                            "no_cross0_alternative:"
                            "business_prior_confirmed:"
                            f"support={int(segment.support_count)}:"
                            f"drivezone_ratio={float(segment.drivezone_ratio):.3f}:"
                            f"length_ratio={float(length_ratio):.3f}"
                        )
                        selected_via_pair_scoped_exception = True
                else:
                    dropped_reason = "cross1_disabled"
            if not dropped_reason and kept_count >= topk:
                dropped_reason = "same_pair_topk_exceeded"
            if dropped_reason:
                dropped.append(
                    {
                        "segment": replace(segment, same_pair_rank=int(rank), kept_reason=""),
                        "dropped_reason": str(dropped_reason),
                        "length_ratio": float(length_ratio),
                    }
                )
            else:
                kept_count += 1
                selected.append(replace(segment, same_pair_rank=int(rank), kept_reason=str(kept_reason)))
                if selected_via_pair_scoped_exception:
                    selected_cross1_exception_count += 1
                    pair_scoped_exception_hits.add((int(src_nodeid), int(dst_nodeid)))
                if bool(segment.bridge_candidate_retained):
                    bridge_retained_segment_count += 1
                    bridge_retained_pair_ids.add(_pair_id_text(int(src_nodeid), int(dst_nodeid)))
            segment_payloads.append(
                {
                    "segment_id": str(segment.segment_id),
                    "sort_rank": int(rank),
                    "same_pair_rank": int(rank),
                    "support_count": int(segment.support_count),
                    "crossing_dist": int(segment.other_xsec_crossing_count),
                    "other_xsec_crossing_count": int(segment.other_xsec_crossing_count),
                    "drivezone_ratio": float(segment.drivezone_ratio),
                    "inside_ratio": float(segment.drivezone_ratio),
                    "gore_conflict": bool(segment.crosses_divstrip),
                    "length_m": float(segment.length_m),
                    "length_ratio": float(length_ratio),
                    "selected": bool(not dropped_reason),
                    "kept_reason": str(kept_reason),
                    "dropped_reason": str(dropped_reason),
                    "whether_pair_scoped_exception_applicable": bool(pair_scoped_exception_applicable),
                }
            )
        selected_segment_count = int(sum(1 for item in segment_payloads if bool(item["selected"])))
        group_payloads.append(
            {
                "src_nodeid": int(src_nodeid),
                "dst_nodeid": int(dst_nodeid),
                "topology_arc_id": str(topology_arc_id),
                "candidate_segment_count": int(len(pair_segments)),
                "selected_segment_count": int(selected_segment_count),
                "same_pair_topk": int(topk),
                "has_cross0_candidate": bool(has_cross0),
                "whether_pair_scoped_exception_applicable": bool(pair_scoped_exception_applicable),
                "segments": segment_payloads,
            }
        )
        if selected_segment_count == 0 and segment_payloads:
            best = dict(segment_payloads[0])
            zero_selected_pairs.append(
                {
                    "src_nodeid": int(src_nodeid),
                    "dst_nodeid": int(dst_nodeid),
                    "topology_arc_id": str(topology_arc_id),
                    "pair_id": _pair_id_text(src_nodeid, dst_nodeid),
                    "candidate_count": int(len(pair_segments)),
                    "support_count": int(best.get("support_count", 0)),
                    "other_xsec_crossing_count": int(best.get("other_xsec_crossing_count", 0)),
                    "inside_ratio": float(best.get("inside_ratio", 0.0)),
                    "gore_conflict": bool(best.get("gore_conflict", False)),
                    "dropped_reason": str(best.get("dropped_reason", "")),
                    "whether_pair_scoped_exception_applicable": bool(pair_scoped_exception_applicable),
                    "kept_reason": str(best.get("kept_reason", "")),
                    "segments": segment_payloads,
                }
            )
    metrics = {
        "candidate_count_after_same_pair_topk": int(len(selected)),
        "crossing_dist_hist_selected": _histogram([int(item.other_xsec_crossing_count) for item in selected]),
        "pair_count": int(len(group_payloads)),
        "same_pair_hist": _histogram([int(item["selected_segment_count"]) for item in group_payloads]),
        "pairs_with_multi_segments": int(sum(1 for item in group_payloads if int(item["selected_segment_count"]) > 1)),
        "max_segments_per_pair": int(max((int(item["selected_segment_count"]) for item in group_payloads), default=0)),
        "pair_scoped_cross1_exception_enabled": bool(pair_scoped_cross1_enabled),
        "pair_scoped_cross1_exception_hit_count": int(len(pair_scoped_exception_hits)),
        "selected_cross1_exception_count": int(selected_cross1_exception_count),
        "bridge_retained_segment_count": int(bridge_retained_segment_count),
        "bridge_retained_pair_ids": sorted(str(v) for v in bridge_retained_pair_ids),
        "zero_selected_pair_count": int(len(zero_selected_pairs)),
        "zero_selected_pair_ids": [str(item["pair_id"]) for item in zero_selected_pairs],
    }
    return selected, dropped, group_payloads, zero_selected_pairs, metrics


def _segment_debug_features(candidates: list[dict[str, Any]], *, status: str, stage: str) -> list[tuple[LineString, dict[str, Any]]]:
    out: list[tuple[LineString, dict[str, Any]]] = []
    for candidate in candidates:
        out.append(
            (
                candidate["line"],
                _candidate_feature_properties(candidate, stage=stage, status=status, reason=str(candidate.get("reason", ""))),
            )
        )
    return out


def _segment_features(segments: list[Segment], *, status: str = "selected") -> list[tuple[LineString, dict[str, Any]]]:
    out: list[tuple[LineString, dict[str, Any]]] = []
    for segment in segments:
        out.append(
            (
                segment.geometry_metric(),
                _segment_feature_properties(segment, status=status, reason=segment.kept_reason),
            )
        )
    return out


def _best_audit_rejected_reason(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""
    preferred = (
        "src_conflicts_with_unique_unanchored_prior_endpoint",
        "terminal_owner_mismatch",
        "ambiguous_terminal_owner",
        "trace_only_reachability",
        "directed_path_not_supported",
        "cross1_pair_not_allowlisted",
        "cross1_has_cross0_alternative",
        "cross1_length_ratio_too_high",
        "cross1_gore_conflict",
        "cross1_drivezone_ratio_too_low",
        "cross1_support_too_low",
        "cross1_support_zero",
        "cross1_pair_scoped_not_best_rank",
        "cross1_disabled",
        "non_adjacent_pair_blocked",
    )
    by_reason = {str(item.get("reason", item.get("dropped_reason", ""))): item for item in entries}
    for reason in preferred:
        if reason in by_reason:
            return str(reason)
    first = entries[0]
    return str(first.get("reason", first.get("dropped_reason", "")))


def _build_pair_scoped_exception_audit(
    *,
    same_pair_groups: list[dict[str, Any]],
    zero_selected_pairs: list[dict[str, Any]],
    rejected_candidates: list[dict[str, Any]],
    params: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    allowlist = _parse_pair_scoped_allowlist(params.get("STEP2_PAIR_SCOPED_CROSS1_ALLOWLIST", ""))
    group_map: dict[tuple[int, int], dict[str, Any]] = {}
    for item in same_pair_groups:
        pair = (int(item["src_nodeid"]), int(item["dst_nodeid"]))
        row = group_map.setdefault(
            pair,
            {
                "src_nodeid": int(item["src_nodeid"]),
                "dst_nodeid": int(item["dst_nodeid"]),
                "has_cross0_candidate": False,
                "segments": [],
            },
        )
        row["has_cross0_candidate"] = bool(row["has_cross0_candidate"] or item.get("has_cross0_candidate"))
        row["segments"].extend(list(item.get("segments", [])))
    zero_map: dict[tuple[int, int], dict[str, Any]] = {}
    for item in zero_selected_pairs:
        pair = (int(item["src_nodeid"]), int(item["dst_nodeid"]))
        row = zero_map.setdefault(
            pair,
            {
                "src_nodeid": int(item["src_nodeid"]),
                "dst_nodeid": int(item["dst_nodeid"]),
                "pair_id": str(item.get("pair_id", _pair_id_text(int(item["src_nodeid"]), int(item["dst_nodeid"])))),
                "candidate_count": 0,
                "support_count": 0,
                "other_xsec_crossing_count": 0,
                "inside_ratio": 0.0,
                "gore_conflict": False,
                "dropped_reason": "",
                "whether_pair_scoped_exception_applicable": False,
                "kept_reason": "",
                "segments": [],
            },
        )
        row["candidate_count"] += int(item.get("candidate_count", 0))
        row["support_count"] = max(int(row["support_count"]), int(item.get("support_count", 0)))
        row["other_xsec_crossing_count"] = int(item.get("other_xsec_crossing_count", row["other_xsec_crossing_count"]))
        row["inside_ratio"] = max(float(row["inside_ratio"]), float(item.get("inside_ratio", 0.0)))
        row["gore_conflict"] = bool(row["gore_conflict"] or item.get("gore_conflict", False))
        if not row["dropped_reason"]:
            row["dropped_reason"] = str(item.get("dropped_reason", ""))
        row["whether_pair_scoped_exception_applicable"] = bool(
            row["whether_pair_scoped_exception_applicable"] or item.get("whether_pair_scoped_exception_applicable")
        )
        if not row["kept_reason"]:
            row["kept_reason"] = str(item.get("kept_reason", ""))
        row["segments"].extend(list(item.get("segments", [])))
    rejected_by_pair: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for item in rejected_candidates:
        pair = (int(item.get("src_nodeid", 0)), int(item.get("dst_nodeid", 0)))
        rejected_by_pair.setdefault(pair, []).append(item)

    pairs_to_audit: set[tuple[int, int]] = set(allowlist)
    for pair, group in group_map.items():
        if any(int(seg.get("other_xsec_crossing_count", seg.get("crossing_dist", 0))) == 1 for seg in group.get("segments", [])):
            pairs_to_audit.add(pair)
    for pair, entries in rejected_by_pair.items():
        if any(int(item.get("other_xsec_crossing_count", 0)) == 1 for item in entries):
            pairs_to_audit.add(pair)
    pairs_to_audit.update(zero_map.keys())

    audit_rows: list[dict[str, Any]] = []
    selected_pair_ids: list[str] = []
    rejected_pair_ids: list[str] = []
    non_allowlisted_cross1_pair_ids: list[str] = []
    for src_nodeid, dst_nodeid in sorted(pairs_to_audit):
        pair = (int(src_nodeid), int(dst_nodeid))
        pair_id = _pair_id_text(src_nodeid, dst_nodeid)
        pair_in_allowlist = bool(pair in allowlist)
        group = group_map.get(pair)
        zero_item = zero_map.get(pair)
        rejected_items = list(rejected_by_pair.get(pair, []))
        grouped_segments = list(group.get("segments", [])) if group is not None else []
        cross1_grouped = [
            item for item in grouped_segments if int(item.get("other_xsec_crossing_count", item.get("crossing_dist", 0))) == 1
        ]
        cross1_rejected = [item for item in rejected_items if int(item.get("other_xsec_crossing_count", 0)) == 1]
        has_cross0_alternative = bool(group is not None and bool(group.get("has_cross0_candidate")))
        best_grouped = cross1_grouped[0] if cross1_grouped else (grouped_segments[0] if grouped_segments else None)
        best_rejected = None
        if cross1_rejected:
            reason_priority = {
                "cross1_pair_not_allowlisted": 0,
                "cross1_has_cross0_alternative": 1,
                "cross1_length_ratio_too_high": 2,
                "cross1_gore_conflict": 3,
                "cross1_drivezone_ratio_too_low": 4,
                "cross1_support_too_low": 5,
                "cross1_disabled": 6,
                "non_adjacent_pair_blocked": 7,
            }
            best_rejected = sorted(
                cross1_rejected,
                key=lambda item: (
                    int(reason_priority.get(str(item.get("reason", "")), 99)),
                    -int(item.get("support_count", 0)),
                    -float(item.get("drivezone_ratio", 0.0)),
                ),
            )[0]

        selected_by_exception = False
        selected_segment_id = ""
        kept_reason = ""
        if best_grouped is not None and "pair_scoped_cross1_exception" in str(best_grouped.get("kept_reason", "")):
            selected_by_exception = True
            selected_segment_id = str(best_grouped.get("segment_id", ""))
            kept_reason = str(best_grouped.get("kept_reason", ""))

        if selected_by_exception:
            final_decision = "selected"
        elif best_grouped is not None or zero_item is not None:
            final_decision = "rejected"
        else:
            final_decision = "rejected_before_exception"

        if best_grouped is not None:
            support_count = int(best_grouped.get("support_count", 0))
            inside_ratio = float(best_grouped.get("inside_ratio", best_grouped.get("drivezone_ratio", 0.0)))
            gore_conflict = bool(best_grouped.get("gore_conflict", False))
            same_pair_rank = int(best_grouped.get("same_pair_rank", best_grouped.get("sort_rank", 0)))
        elif best_rejected is not None:
            support_count = int(best_rejected.get("support_count", 0))
            inside_ratio = float(best_rejected.get("drivezone_ratio", 0.0))
            gore_conflict = bool(best_rejected.get("crosses_divstrip", False))
            same_pair_rank = 0
        else:
            support_count = 0
            inside_ratio = 0.0
            gore_conflict = False
            same_pair_rank = 0

        crossing_values: list[int] = []
        for item in grouped_segments:
            crossing_values.append(int(item.get("other_xsec_crossing_count", item.get("crossing_dist", 0))))
        for item in rejected_items:
            crossing_values.append(int(item.get("other_xsec_crossing_count", 0)))
        best_candidate_crossing_dist = int(min(crossing_values)) if crossing_values else 0

        rejected_reason = ""
        if final_decision != "selected":
            if zero_item is not None and str(zero_item.get("dropped_reason", "")):
                rejected_reason = str(zero_item.get("dropped_reason", ""))
            elif best_grouped is not None and str(best_grouped.get("dropped_reason", "")):
                rejected_reason = str(best_grouped.get("dropped_reason", ""))
            else:
                rejected_reason = _best_audit_rejected_reason(rejected_items)

        if not pair_in_allowlist and any(value == 1 for value in crossing_values):
            non_allowlisted_cross1_pair_ids.append(pair_id)

        row = {
            "src_nodeid": int(src_nodeid),
            "dst_nodeid": int(dst_nodeid),
            "pair_id": str(pair_id),
            "pair_in_allowlist": bool(pair_in_allowlist),
            "has_cross0_alternative": bool(has_cross0_alternative),
            "best_candidate_crossing_dist": int(best_candidate_crossing_dist),
            "selected_by_exception": bool(selected_by_exception),
            "selected_segment_id": str(selected_segment_id),
            "kept_reason": str(kept_reason),
            "rejected_reason": str(rejected_reason),
            "support_count": int(support_count),
            "inside_ratio": float(inside_ratio),
            "gore_conflict": bool(gore_conflict),
            "same_pair_rank": int(same_pair_rank),
            "final_decision": str(final_decision),
        }
        audit_rows.append(row)
        if final_decision == "selected":
            selected_pair_ids.append(pair_id)
        else:
            rejected_pair_ids.append(pair_id)

    metrics = {
        "pair_scoped_exception_audit_count": int(len(audit_rows)),
        "pair_scoped_exception_selected_pair_ids": list(selected_pair_ids),
        "pair_scoped_exception_rejected_pair_ids": list(rejected_pair_ids),
        "pair_scoped_exception_non_allowlisted_cross1_pair_ids": list(non_allowlisted_cross1_pair_ids),
    }
    return audit_rows, metrics


def _make_feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": list(features),
        "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
    }


def _build_segment_support_traj_features(
    *,
    clustered_segments: list[Segment],
    selected_segments: list[Segment],
    accepted_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    accepted_by_id = {str(item.get("candidate_id", "")): item for item in accepted_candidates}
    selected_ids = {str(segment.segment_id) for segment in selected_segments}
    features: list[dict[str, Any]] = []
    for segment in clustered_segments:
        traj_candidates = [
            accepted_by_id[str(candidate_id)]
            for candidate_id in segment.candidate_ids
            if str(candidate_id) in accepted_by_id and str(accepted_by_id[str(candidate_id)].get("source", "")) == "traj"
        ]
        for support_rank, candidate in enumerate(
            sorted(
                traj_candidates,
                key=lambda item: (
                    -float(item.get("drivezone_ratio", 0.0)),
                    -float(item.get("line_length_m", getattr(item.get("line"), "length", 0.0))),
                    str(item.get("candidate_id", "")),
                ),
            ),
            start=1,
        ):
            line = candidate.get("line")
            if not isinstance(line, LineString) or line.is_empty:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(line),
                    "properties": {
                        "segment_id": str(segment.segment_id),
                        "src_nodeid": int(segment.src_nodeid),
                        "dst_nodeid": int(segment.dst_nodeid),
                        "traj_id": str(candidate.get("traj_id", "")),
                        "candidate_id": str(candidate.get("candidate_id", "")),
                        "pair_id": _pair_id_text(int(segment.src_nodeid), int(segment.dst_nodeid)),
                        "support_rank": int(support_rank),
                        "support_length": float(line.length),
                        "support_direction_ok": bool(candidate.get("topology_allowed", False)),
                        "support_topology_reason": str(candidate.get("topology_reason", "")),
                        "support_inside_ratio": float(candidate.get("drivezone_ratio", 0.0)),
                        "support_crossing_count": int(candidate.get("other_xsec_crossing_count", 0)),
                        "start_event_id": str(candidate.get("start_event_id", "")),
                        "end_event_id": str(candidate.get("end_event_id", "")),
                        "segment_support_count": int(segment.support_count),
                        "segment_formation_reason": str(segment.formation_reason),
                        "segment_single_traj_support": bool(int(segment.support_count) <= 1),
                        "segment_selected": bool(str(segment.segment_id) in selected_ids),
                    },
                }
            )
    return features


def _build_segment_should_not_exist(
    rejected_candidates: list[dict[str, Any]],
    *,
    topology: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    pair_sources = {} if topology is None else dict(topology.get("pair_sources", {}))
    pair_paths = {} if topology is None else dict(topology.get("pair_paths", {}))
    trace_only_pair_paths = {} if topology is None else dict(topology.get("trace_only_pair_paths", {}))
    terminal_trace_paths = {} if topology is None else dict(topology.get("terminal_trace_paths", {}))
    terminal_reverse_ownership = {} if topology is None else dict(topology.get("terminal_reverse_ownership", {}))
    by_pair: dict[tuple[int, int], dict[str, Any]] = {}
    for item in rejected_candidates:
        reason = str(item.get("reason", ""))
        if reason not in _SEGMENT_TOPOLOGY_INVALID_REASONS:
            continue
        pair = (int(item.get("src_nodeid", 0)), int(item.get("dst_nodeid", 0)))
        reverse_owner = terminal_reverse_ownership.get(int(pair[1]), {})
        row = by_pair.setdefault(
            pair,
            {
                "src_nodeid": int(pair[0]),
                "dst_nodeid": int(pair[1]),
                "reason": str(reason),
                "related_traj_ids": set(),
                "related_candidate_ids": set(),
                "topology_arc_is_direct_legal": bool(item.get("topology_arc_is_direct_legal", False)),
                "topology_arc_is_unique": bool(item.get("topology_arc_is_unique", False)),
                "bridge_chain_exists": bool(item.get("bridge_chain_exists", False)),
                "bridge_chain_unique": bool(item.get("bridge_chain_unique", False)),
                "bridge_chain_nodes": [int(v) for v in item.get("bridge_chain_nodes", []) if v is not None],
                "topology_sources": sorted(
                    {
                        *[str(v) for v in pair_sources.get(pair, [])],
                        *[
                            str(item.get("source", ""))
                            for item in [*trace_only_pair_paths.get(pair, []), *terminal_trace_paths.get(pair, [])]
                            if str(item.get("source", ""))
                        ],
                    }
                ),
                "topology_paths": list(pair_paths.get(pair, []))
                or list(trace_only_pair_paths.get(pair, []))
                or list(terminal_trace_paths.get(pair, [])),
                "topology_reverse_owner_status": str(reverse_owner.get("status", "")),
                "topology_reverse_owner_src_nodeid": reverse_owner.get("src_nodeid"),
                "topology_reverse_owner_src_nodeids": [int(v) for v in reverse_owner.get("src_nodeids", []) if v is not None],
                "competing_prior_pair_ids": set(),
                "competing_prior_candidate_ids": set(),
            },
        )
        if not row["reason"]:
            row["reason"] = str(reason)
        row["topology_arc_is_direct_legal"] = bool(
            row["topology_arc_is_direct_legal"] or bool(item.get("topology_arc_is_direct_legal", False))
        )
        row["topology_arc_is_unique"] = bool(
            row["topology_arc_is_unique"] or bool(item.get("topology_arc_is_unique", False))
        )
        row["bridge_chain_exists"] = bool(row["bridge_chain_exists"] or bool(item.get("bridge_chain_exists", False)))
        row["bridge_chain_unique"] = bool(row["bridge_chain_unique"] or bool(item.get("bridge_chain_unique", False)))
        if not row["bridge_chain_nodes"]:
            row["bridge_chain_nodes"] = [int(v) for v in item.get("bridge_chain_nodes", []) if v is not None]
        row["related_candidate_ids"].add(str(item.get("candidate_id", "")))
        for pair_id in item.get("competing_prior_pair_ids", []) or []:
            if str(pair_id):
                row["competing_prior_pair_ids"].add(str(pair_id))
        for candidate_id in item.get("competing_prior_candidate_ids", []) or []:
            if str(candidate_id):
                row["competing_prior_candidate_ids"].add(str(candidate_id))
        for traj_id in item.get("support_traj_ids", set()) or []:
            row["related_traj_ids"].add(str(traj_id))
    out: list[dict[str, Any]] = []
    for pair in sorted(by_pair.keys()):
        row = by_pair[pair]
        out.append(
            {
                "src_nodeid": int(row["src_nodeid"]),
                "dst_nodeid": int(row["dst_nodeid"]),
                "reason": str(row["reason"]),
                "related_traj_ids": sorted(str(v) for v in row["related_traj_ids"]),
                "related_traj_count": int(len(row["related_traj_ids"])),
                "related_candidate_ids": sorted(str(v) for v in row["related_candidate_ids"]),
                "topology_arc_is_direct_legal": bool(row["topology_arc_is_direct_legal"]),
                "topology_arc_is_unique": bool(row["topology_arc_is_unique"]),
                "bridge_chain_exists": bool(row["bridge_chain_exists"]),
                "bridge_chain_unique": bool(row["bridge_chain_unique"]),
                "bridge_chain_nodes": [int(v) for v in row["bridge_chain_nodes"]],
                "topology_sources": list(row["topology_sources"]),
                "topology_paths": list(row["topology_paths"]),
                "topology_reverse_owner_status": str(row["topology_reverse_owner_status"]),
                "topology_reverse_owner_src_nodeid": row["topology_reverse_owner_src_nodeid"],
                "topology_reverse_owner_src_nodeids": list(row["topology_reverse_owner_src_nodeids"]),
                "competing_prior_pair_ids": sorted(str(v) for v in row["competing_prior_pair_ids"]),
                "competing_prior_candidate_ids": sorted(str(v) for v in row["competing_prior_candidate_ids"]),
                "competing_prior_trace_paths": [
                    list(path)
                    for path in sorted(
                        {
                            tuple(int(v) for v in path)
                            for item in rejected_candidates
                            if int(item.get("src_nodeid", 0)) == int(row["src_nodeid"])
                            and int(item.get("dst_nodeid", 0)) == int(row["dst_nodeid"])
                            for path in item.get("competing_prior_trace_paths", []) or []
                        }
                    )
                ],
            }
        )
    return out


def _build_terminal_node_audit(
    *,
    topology: dict[str, Any],
    selected_segments: list[Segment],
    paired_candidates: list[dict[str, Any]],
    rejected_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not bool(topology.get("enabled")):
        return []
    selected_pairs = {
        (int(segment.src_nodeid), int(segment.dst_nodeid)): segment
        for segment in selected_segments
    }
    rejected_by_pair: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for item in rejected_candidates:
        rejected_by_pair[(int(item.get("src_nodeid", 0)), int(item.get("dst_nodeid", 0)))].append(item)
    candidate_by_pair: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for item in paired_candidates:
        pair = (int(item.get("src_nodeid", 0)), int(item.get("dst_nodeid", 0)))
        candidate_by_pair[pair].append(item)
    node_ids = set(int(v) for v in topology.get("terminal_nodes", set()))
    for pair in candidate_by_pair.keys():
        src_nodeid, dst_nodeid = pair
        if int(src_nodeid) in node_ids or int(dst_nodeid) in node_ids:
            continue
        if rejected_by_pair.get(pair):
            reasons = {str(item.get("reason", "")) for item in rejected_by_pair[pair]}
            if reasons & _SEGMENT_TOPOLOGY_INVALID_REASONS:
                if int(src_nodeid) in topology.get("incoming", {}) or int(dst_nodeid) in topology.get("incoming", {}):
                    node_ids.add(int(src_nodeid))
                    node_ids.add(int(dst_nodeid))
    audits: list[dict[str, Any]] = []
    allowed_pairs: set[tuple[int, int]] = topology["allowed_pairs"]
    incoming: dict[int, set[int]] = topology.get("incoming", {})
    outgoing: dict[int, set[int]] = topology.get("outgoing", {})
    node_kind_map: dict[int, Any] = topology.get("node_kind_map", {})
    pair_sources: dict[tuple[int, int], list[str]] = topology.get("pair_sources", {})
    pair_paths: dict[tuple[int, int], list[dict[str, Any]]] = topology.get("pair_paths", {})
    terminal_reverse_ownership: dict[int, dict[str, Any]] = topology.get("terminal_reverse_ownership", {})
    for nodeid in sorted(node_ids):
        reverse_owner = terminal_reverse_ownership.get(int(nodeid), {})
        pair_rows: list[dict[str, Any]] = []
        for pair, items in sorted(candidate_by_pair.items()):
            src_nodeid, dst_nodeid = pair
            if int(src_nodeid) != int(nodeid) and int(dst_nodeid) != int(nodeid):
                continue
            rejected_items = rejected_by_pair.get(pair, [])
            segment = selected_pairs.get(pair)
            reasons = [str(item.get("reason", "")) for item in rejected_items if str(item.get("reason", ""))]
            pair_rows.append(
                {
                    "src_nodeid": int(src_nodeid),
                    "dst_nodeid": int(dst_nodeid),
                    "pair_id": _pair_id_text(src_nodeid, dst_nodeid),
                    "traj_support_count": int(len({str(tid) for item in items for tid in item.get("support_traj_ids", set())})),
                    "candidate_ids": sorted(str(item.get("candidate_id", "")) for item in items),
                    "related_traj_ids": sorted({str(tid) for item in items for tid in item.get("support_traj_ids", set())}),
                    "topology_allowed": bool(pair in allowed_pairs),
                    "direction_allowed": bool(pair in allowed_pairs),
                    "topology_sources": list(pair_sources.get(pair, [])),
                    "topology_paths": list(pair_paths.get(pair, [])),
                    "topology_reverse_owner_status": str(reverse_owner.get("status", "")),
                    "topology_reverse_owner_src_nodeid": reverse_owner.get("src_nodeid"),
                    "topology_reverse_owner_src_nodeids": [int(v) for v in reverse_owner.get("src_nodeids", []) if v is not None],
                    "topology_reverse_owner_match": (
                        None
                        if str(reverse_owner.get("status", "")) != "unique_owner"
                        else bool(int(src_nodeid) == int(reverse_owner.get("src_nodeid")))
                    ),
                    "weak_single_traj_support": bool(int(len({str(tid) for item in items for tid in item.get("support_traj_ids", set())})) <= 1),
                    "selected": bool(segment is not None),
                    "selected_segment_id": "" if segment is None else str(segment.segment_id),
                    "selected_reason": "" if segment is None else str(segment.kept_reason),
                    "rejected_reason": "" if segment is not None else _best_audit_rejected_reason(rejected_items),
                    "rejected_reasons": sorted(set(reasons)),
                }
            )
        if not pair_rows:
            continue
        audits.append(
            {
                "nodeid": int(nodeid),
                "node_kind": node_kind_map.get(int(nodeid)),
                "terminal_by_topology": bool(int(nodeid) in topology.get("terminal_nodes", set())),
                "allowed_incoming_src_nodeids": sorted(int(v) for v in incoming.get(int(nodeid), set())),
                "allowed_outgoing_dst_nodeids": sorted(int(v) for v in outgoing.get(int(nodeid), set())),
                "reverse_owner_status": str(reverse_owner.get("status", "")),
                "reverse_owner_src_nodeid": reverse_owner.get("src_nodeid"),
                "reverse_owner_src_nodeids": [int(v) for v in reverse_owner.get("src_nodeids", []) if v is not None],
                "reverse_owner_anchor_count": int(reverse_owner.get("anchor_count", 0)),
                "reverse_owner_paths": list(reverse_owner.get("paths", [])),
                "reverse_owner_anchors": list(reverse_owner.get("anchors", [])),
                "pairs": pair_rows,
            }
        )
    return audits


def _enumerate_direct_bridge_paths(
    *,
    outgoing: dict[int, set[int]],
    src_nodeid: int,
    dst_nodeid: int,
    max_hops: int = 4,
    max_paths: int = 32,
) -> list[list[int]]:
    src = int(src_nodeid)
    dst = int(dst_nodeid)
    if int(src) == int(dst):
        return []
    paths: list[list[int]] = []

    def dfs(node: int, path: list[int]) -> None:
        if len(paths) >= int(max_paths):
            return
        hops = int(len(path) - 1)
        if hops > int(max_hops):
            return
        if int(node) == int(dst):
            paths.append([int(v) for v in path])
            return
        for nxt in sorted(int(v) for v in outgoing.get(int(node), set())):
            if int(nxt) in path:
                continue
            dfs(int(nxt), [*path, int(nxt)])

    dfs(int(src), [int(src)])
    return paths


def _classify_blocked_pair_bridge(
    *,
    src_nodeid: int,
    dst_nodeid: int,
    topology: dict[str, Any],
) -> dict[str, Any]:
    outgoing: dict[int, set[int]] = {
        int(k): {int(v) for v in vals}
        for k, vals in dict(topology.get("outgoing", {})).items()
    }
    direct_paths = _enumerate_direct_bridge_paths(
        outgoing=outgoing,
        src_nodeid=int(src_nodeid),
        dst_nodeid=int(dst_nodeid),
    )
    two_hop_paths = sorted({tuple(path) for path in direct_paths if len(path) == 3})
    direct_bridge_nodeids = sorted({int(path[1]) for path in two_hop_paths})
    trace_only_paths = list(dict(topology.get("trace_only_pair_paths", {})).get((int(src_nodeid), int(dst_nodeid)), []))
    terminal_trace_paths = list(dict(topology.get("terminal_trace_paths", {})).get((int(src_nodeid), int(dst_nodeid)), []))
    if len(direct_bridge_nodeids) == 1:
        classification = "unique_directed_bridge_candidate"
    elif len(direct_bridge_nodeids) >= 2:
        classification = "multi_bridge_ambiguous"
    elif any(len(path) == 2 for path in direct_paths) or direct_paths or trace_only_paths or terminal_trace_paths:
        classification = "topology_gap_unresolved"
    else:
        classification = "truly_non_adjacent_reject"
    return {
        "bridge_classification": str(classification),
        "direct_bridge_nodeids": [int(v) for v in direct_bridge_nodeids],
        "direct_bridge_paths": [[int(v) for v in path] for path in direct_paths],
        "trace_only_paths": list(trace_only_paths),
        "terminal_trace_paths": list(terminal_trace_paths),
    }


def _build_blocked_pair_bridge_audit(
    *,
    topology: dict[str, Any],
    rejected_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_pair: dict[tuple[int, int], dict[str, Any]] = {}
    for item in rejected_candidates:
        if str(item.get("reason", "")) != "non_adjacent_pair_blocked":
            continue
        pair = (int(item.get("src_nodeid", 0)), int(item.get("dst_nodeid", 0)))
        row = by_pair.setdefault(
            pair,
            {
                "src_nodeid": int(pair[0]),
                "dst_nodeid": int(pair[1]),
                "pair_id": _pair_id_text(int(pair[0]), int(pair[1])),
                "candidate_ids": set(),
                "traj_ids": set(),
                "reject_stage": str(item.get("dropped_stage", "")),
                "reject_reason": str(item.get("reason", "")),
            },
        )
        row["candidate_ids"].add(str(item.get("candidate_id", "")))
        for traj_id in item.get("support_traj_ids", set()) or []:
            row["traj_ids"].add(str(traj_id))
    out: list[dict[str, Any]] = []
    for pair in sorted(by_pair.keys()):
        row = by_pair[pair]
        classification = _classify_blocked_pair_bridge(
            src_nodeid=int(row["src_nodeid"]),
            dst_nodeid=int(row["dst_nodeid"]),
            topology=topology,
        )
        out.append(
            {
                "src_nodeid": int(row["src_nodeid"]),
                "dst_nodeid": int(row["dst_nodeid"]),
                "pair_id": str(row["pair_id"]),
                "reject_stage": str(row["reject_stage"]),
                "reject_reason": str(row["reject_reason"]),
                "candidate_ids": sorted(str(v) for v in row["candidate_ids"]),
                "traj_ids": sorted(str(v) for v in row["traj_ids"]),
                **classification,
            }
        )
    return out


def _build_topology_pairs_debug(
    topology: dict[str, Any],
) -> list[dict[str, Any]]:
    allowed_pairs: set[tuple[int, int]] = topology.get("allowed_pairs", set())
    pair_sources: dict[tuple[int, int], list[str]] = topology.get("pair_sources", {})
    pair_paths: dict[tuple[int, int], list[dict[str, Any]]] = topology.get("pair_paths", {})
    trace_only_pair_paths: dict[tuple[int, int], list[dict[str, Any]]] = topology.get("trace_only_pair_paths", {})
    terminal_trace_paths: dict[tuple[int, int], list[dict[str, Any]]] = topology.get("terminal_trace_paths", {})
    out: list[dict[str, Any]] = []
    all_pairs = set(allowed_pairs) | set(trace_only_pair_paths.keys()) | set(terminal_trace_paths.keys())
    for pair in sorted(all_pairs):
        is_allowed = pair in allowed_pairs
        sources = list(pair_sources.get(pair, []))
        paths = list(pair_paths.get(pair, []))
        diagnostics = _arc_legality_diagnostics(
            src_nodeid=int(pair[0]),
            dst_nodeid=int(pair[1]),
            topology=topology,
        )
        if not is_allowed:
            sources = sorted(
                {
                    *[str(v) for v in sources],
                    *[str(item.get("source", "")) for item in trace_only_pair_paths.get(pair, []) if str(item.get("source", ""))],
                    *[str(item.get("source", "")) for item in terminal_trace_paths.get(pair, []) if str(item.get("source", ""))],
                }
            )
            paths = [*list(trace_only_pair_paths.get(pair, [])), *list(terminal_trace_paths.get(pair, []))]
        arc_source_type = ""
        if sources:
            arc_source_type = str(sources[0]) if len(sources) == 1 else "mixed"
        out.append(
            {
                "src_nodeid": int(pair[0]),
                "dst_nodeid": int(pair[1]),
                "pair_id": _pair_id_text(int(pair[0]), int(pair[1])),
                "raw_pair_ids": sorted(
                    {
                        str(item.get("raw_pair", ""))
                        for item in paths
                        if str(item.get("raw_pair", ""))
                    }
                ),
                "canonical_pair_id": _pair_id_text(int(pair[0]), int(pair[1])),
                "alias_normalized": bool(
                    any(bool(item.get("src_alias_applied", False) or item.get("dst_alias_applied", False)) for item in paths)
                ),
                "topology_allowed": True if is_allowed else None,
                "direction_allowed": True if is_allowed else None,
                "selected": None,
                "rejected_reason": None,
                "arc_source_type": str(arc_source_type),
                "topology_arc_is_direct_legal": bool(diagnostics["topology_arc_is_direct_legal"]),
                "topology_arc_is_unique": bool(diagnostics["topology_arc_is_unique"]),
                "topology_arc_candidate_count": int(diagnostics["topology_arc_candidate_count"]),
                "bridge_chain_exists": bool(diagnostics["bridge_chain_exists"]),
                "bridge_chain_unique": bool(diagnostics["bridge_chain_unique"]),
                "bridge_chain_nodes": [int(v) for v in diagnostics["bridge_chain_nodes"]],
                "bridge_diagnostic_reason": str(diagnostics["bridge_diagnostic_reason"]),
                "topology_sources": list(sources),
                "topology_paths": list(paths),
            }
        )
    return out


def _build_topology_arcs_debug(
    topology: dict[str, Any],
) -> list[dict[str, Any]]:
    pair_arcs: dict[tuple[int, int], list[dict[str, Any]]] = topology.get("pair_arcs", {})
    out: list[dict[str, Any]] = []
    for pair in sorted(pair_arcs.keys()):
        for arc in pair_arcs.get(pair, []):
            out.append(
                {
                    "arc_id": str(arc.get("arc_id", "")),
                    "src_nodeid": int(arc.get("src_nodeid", pair[0])),
                    "dst_nodeid": int(arc.get("dst_nodeid", pair[1])),
                    "pair_id": _pair_id_text(int(pair[0]), int(pair[1])),
                    "raw_src_nodeid": int(arc.get("raw_src_nodeid", arc.get("src_nodeid", pair[0]))),
                    "raw_dst_nodeid": int(arc.get("raw_dst_nodeid", arc.get("dst_nodeid", pair[1]))),
                    "raw_pair": str(arc.get("raw_pair", _pair_id_text(int(pair[0]), int(pair[1])))),
                    "canonical_pair": str(arc.get("canonical_pair", _pair_id_text(int(pair[0]), int(pair[1])))),
                    "src_alias_applied": bool(arc.get("src_alias_applied", False)),
                    "dst_alias_applied": bool(arc.get("dst_alias_applied", False)),
                    "source": str(arc.get("source", "")),
                    "edge_ids": [str(v) for v in arc.get("edge_ids", [])],
                    "node_path": [int(v) for v in arc.get("node_path", []) if v is not None],
                    "chain_len": int(arc.get("chain_len", 0)),
                    "line_coords": list(arc.get("line_coords", [])),
                }
            )
    return out


def _drivable_surface(inputs: PatchInputs, params: dict[str, Any]) -> BaseGeometry | None:
    if inputs.drivezone_zone_metric is None or inputs.drivezone_zone_metric.is_empty:
        return None
    divstrip_buffer = load_divstrip_buffer(inputs.divstrip_zone_metric, float(params["DIVSTRIP_BUFFER_M"]))
    if divstrip_buffer is None or divstrip_buffer.is_empty:
        return inputs.drivezone_zone_metric
    try:
        surface = inputs.drivezone_zone_metric.difference(divstrip_buffer)
    except Exception:
        surface = inputs.drivezone_zone_metric
    if surface is None or surface.is_empty:
        return inputs.drivezone_zone_metric
    return surface



def _build_final_road(
    *,
    patch_id: str,
    segment: Segment,
    identity: CorridorIdentity,
    witness: CorridorWitness | None,
    src_slot: SlotInterval,
    dst_slot: SlotInterval,
    inputs: PatchInputs,
    prior_roads: list[Any],
    params: dict[str, Any],
    arc_row: dict[str, Any] | None = None,
    divstrip_buffer: Any | None = None,
) -> tuple[FinalRoad | None, dict[str, Any]]:
    return _step5_build_final_road(
        patch_id=patch_id,
        segment=segment,
        identity=identity,
        witness=witness,
        src_slot=src_slot,
        dst_slot=dst_slot,
        inputs=inputs,
        prior_roads=prior_roads,
        params=params,
        arc_row=arc_row,
        divstrip_buffer=divstrip_buffer,
    )


def _classify_segment_outcome(
    *,
    identity: CorridorIdentity,
    src_slot: SlotInterval,
    dst_slot: SlotInterval,
    build_result: dict[str, Any],
    road: FinalRoad | None,
) -> str:
    return _step5_classify_segment_outcome(
        identity=identity,
        src_slot=src_slot,
        dst_slot=dst_slot,
        build_result=build_result,
        road=road,
    )


def _stage1_input_frame(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    inputs, frame, prior_roads = load_inputs_and_frame(data_root, patch_id, params=params)
    dbg_dir = debug_dir(out_root, run_id, patch_id)
    artifact = {"input_frame": frame.to_dict(), "road_prior_count": int(len(prior_roads))}
    write_json(_artifact_path(out_root, run_id, patch_id, "step1_input_frame"), artifact)
    write_lines_geojson(
        dbg_dir / "base_xsec_all.geojson",
        [(xsec.geometry_metric(), {"nodeid": int(xsec.nodeid), "kind": str(xsec.properties.get("kind", ""))}) for xsec in frame.base_cross_sections],
    )
    write_json(
        dbg_dir / "probe_xsec_all.geojson",
        {"type": "FeatureCollection", "features": [], "crs": {"type": "name", "properties": {"name": "EPSG:3857"}}},
    )
    return {"artifact": artifact, "inputs": inputs, "frame": frame, "reason": "input_frame_ready"}


def _stage2_segment(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    inputs, frame, prior_roads = load_inputs_and_frame(data_root, patch_id, params=params)
    candidate_bundle = _segment_candidates(inputs, frame, prior_roads, params)
    pre_topology_segments = _cluster_segments(list(candidate_bundle.get("accepted_candidates_before_topology_gate", [])), frame, params)
    accepted = list(candidate_bundle["accepted_candidates"])
    rejected = list(candidate_bundle["rejected_candidates"])
    clustered_segments = _cluster_segments(accepted, frame, params)
    segments, dropped_segments, same_pair_groups, zero_selected_pairs, step2_metrics = _select_segments_same_pair(
        clustered_segments,
        frame,
        params,
    )
    pair_scoped_exception_audit, pair_scoped_exception_metrics = _build_pair_scoped_exception_audit(
        same_pair_groups=same_pair_groups,
        zero_selected_pairs=zero_selected_pairs,
        rejected_candidates=rejected,
        params=params,
    )
    terminal_node_audit = _build_terminal_node_audit(
        topology=dict(candidate_bundle.get("topology", {})),
        selected_segments=segments,
        paired_candidates=list(candidate_bundle.get("paired_candidates", [])),
        rejected_candidates=rejected,
    )
    blocked_pair_bridge_audit = _build_blocked_pair_bridge_audit(
        topology=dict(candidate_bundle.get("topology", {})),
        rejected_candidates=rejected,
    )
    segment_should_not_exist = _build_segment_should_not_exist(rejected, topology=dict(candidate_bundle.get("topology", {})))
    topology_pairs_debug = _build_topology_pairs_debug(dict(candidate_bundle.get("topology", {})))
    topology_arcs_debug = _build_topology_arcs_debug(dict(candidate_bundle.get("topology", {})))
    full_arc_registry = build_full_legal_arc_registry(
        topology=dict(candidate_bundle.get("topology", {})),
        selected_segments=segments,
        segment_should_not_exist=segment_should_not_exist,
        blocked_pair_bridge_audit=blocked_pair_bridge_audit,
    )
    step2_metrics = {
        **step2_metrics,
        "segment_selected_count_before_topology_gate": int(len(pre_topology_segments)),
        "segment_selected_count_after_topology_gate": int(len(clustered_segments)),
        "topology_arc_count": int(len(topology_arcs_debug)),
        "all_direct_legal_arc_count": int(full_arc_registry["summary"]["all_direct_legal_arc_count"]),
        "all_direct_unique_legal_arc_count": int(full_arc_registry["summary"]["all_direct_unique_legal_arc_count"]),
        "entered_main_flow_arc_count": int(full_arc_registry["summary"]["entered_main_flow_arc_count"]),
        "blocked_pair_bridge_audit_count": int(len(blocked_pair_bridge_audit)),
        "topology_multi_arc_pair_count": int(
            sum(
                1
                for pair in {
                    (int(item["src_nodeid"]), int(item["dst_nodeid"]))
                    for item in topology_arcs_debug
                }
                if sum(
                    1
                    for item in topology_arcs_debug
                    if int(item["src_nodeid"]) == int(pair[0]) and int(item["dst_nodeid"]) == int(pair[1])
                )
                > 1
            )
        ),
    }
    artifact = {
        "segments": [segment.to_dict() for segment in segments],
        "dropped_segments": [
            {
                "segment": item["segment"].to_dict(),
                "dropped_reason": str(item["dropped_reason"]),
                "length_ratio": float(item["length_ratio"]),
            }
            for item in dropped_segments
        ],
        "accepted_candidate_count": int(len(accepted)),
        "rejected_candidate_count": int(len(rejected)),
        "xsec_alias_rows": list(candidate_bundle.get("topology", {}).get("xsec_alias_rows", [])),
        "excluded_candidates": [
            {
                "candidate_id": str(item["candidate_id"]),
                "source": str(item["source"]),
                "src_nodeid": int(item["src_nodeid"]),
                "dst_nodeid": int(item["dst_nodeid"]),
                "raw_src_nodeid": int(item.get("raw_src_nodeid", item["src_nodeid"])),
                "raw_dst_nodeid": int(item.get("raw_dst_nodeid", item["dst_nodeid"])),
                "canonical_src_xsec_id": int(item.get("canonical_src_xsec_id", item["src_nodeid"])),
                "canonical_dst_xsec_id": int(item.get("canonical_dst_xsec_id", item["dst_nodeid"])),
                "src_alias_applied": bool(item.get("src_alias_applied", False)),
                "dst_alias_applied": bool(item.get("dst_alias_applied", False)),
                "raw_pair": str(item.get("raw_pair", _pair_id_text(int(item["src_nodeid"]), int(item["dst_nodeid"])))),
                "canonical_pair": str(
                    item.get("canonical_pair", _pair_id_text(int(item["src_nodeid"]), int(item["dst_nodeid"])))
                ),
                "traj_id": str(item.get("traj_id", "")),
                "support_traj_ids": sorted(str(v) for v in item.get("support_traj_ids", set())),
                "reason": str(item.get("reason", "")),
                "stage": str(item.get("dropped_stage", "")),
                "pairing_mode": str(item.get("pairing_mode", "")),
                "support_count": int(_candidate_support_count(item)),
                "prior_supported": bool(item.get("prior_supported", False)),
                "drivezone_ratio": float(item.get("drivezone_ratio", 0.0)),
                "other_xsec_crossing_count": int(item.get("other_xsec_crossing_count", 0)),
                "other_xsec_nodes": [int(v) for v in item.get("other_xsec_nodes", [])],
                "topology_reason": str(item.get("topology_reason", "")),
                "topology_reverse_owner_status": str(item.get("topology_reverse_owner_status", "")),
                "topology_reverse_owner_src_nodeid": item.get("topology_reverse_owner_src_nodeid"),
                "topology_reverse_owner_src_nodeids": [int(v) for v in item.get("topology_reverse_owner_src_nodeids", [])],
                "topology_arc_id": str(item.get("topology_arc_id", "")),
                "arc_source_type": str(item.get("topology_arc_source_type", item.get("arc_source_type", ""))),
                "topology_arc_node_path": [int(v) for v in item.get("topology_arc_node_path", [])],
                "topology_arc_is_direct_legal": bool(item.get("topology_arc_is_direct_legal", False)),
                "topology_arc_is_unique": bool(item.get("topology_arc_is_unique", False)),
                "topology_arc_candidate_count": int(item.get("topology_arc_candidate_count", 0)),
                "topology_pair_paths": list(item.get("topology_pair_paths", [])),
                "topology_trace_only_paths": list(item.get("topology_trace_only_paths", [])),
                "topology_terminal_trace_paths": list(item.get("topology_terminal_trace_paths", [])),
                "bridge_candidate_retained": bool(item.get("bridge_candidate_retained", False)),
                "bridge_chain_exists": bool(item.get("bridge_chain_exists", False)),
                "bridge_chain_unique": bool(item.get("bridge_chain_unique", False)),
                "bridge_chain_nodes": [int(v) for v in item.get("bridge_chain_nodes", []) if v is not None],
                "bridge_chain_source": str(item.get("bridge_chain_source", "")),
                "bridge_diagnostic_reason": str(item.get("bridge_diagnostic_reason", "")),
                "bridge_decision_stage": str(item.get("bridge_decision_stage", "")),
                "bridge_decision_reason": str(item.get("bridge_decision_reason", "")),
                "bridge_classification": str(item.get("bridge_classification", "")),
                "prior_anchor_cost_m": item.get("prior_anchor_cost_m"),
                "prior_anchor_best_pair": item.get("prior_anchor_best_pair"),
                "competing_prior_pair_ids": [str(v) for v in item.get("competing_prior_pair_ids", [])],
                "competing_prior_candidate_ids": [str(v) for v in item.get("competing_prior_candidate_ids", [])],
                "competing_prior_anchor_cost_m": list(item.get("competing_prior_anchor_cost_m", [])),
                "competing_prior_anchor_best_pairs": list(item.get("competing_prior_anchor_best_pairs", [])),
                "competing_prior_trace_paths": list(item.get("competing_prior_trace_paths", [])),
                "start_event_id": str(item.get("start_event_id", "")),
                "end_event_id": str(item.get("end_event_id", "")),
            }
            for item in rejected
        ],
        "same_pair_groups": same_pair_groups,
        "zero_selected_pairs": zero_selected_pairs,
        "pair_scoped_exception_audit": pair_scoped_exception_audit,
        "terminal_node_audit": terminal_node_audit,
        "blocked_pair_bridge_audit": blocked_pair_bridge_audit,
        "segment_should_not_exist": segment_should_not_exist,
        "topology_pairs": topology_pairs_debug,
        "topology_arcs": topology_arcs_debug,
        "full_legal_arc_registry": list(full_arc_registry["rows"]),
        "legal_arc_funnel": dict(full_arc_registry["summary"]),
        "step2_metrics": {**candidate_bundle["stats"], **step2_metrics, **pair_scoped_exception_metrics},
    }
    dbg_dir = debug_dir(out_root, run_id, patch_id)
    write_json(_artifact_path(out_root, run_id, patch_id, "step2_segment"), artifact)
    all_candidate_features = list(candidate_bundle["candidate_debug_features"])
    dropped_segment_features = [
        (
            item["segment"].geometry_metric(),
            _segment_feature_properties(item["segment"], status="dropped", dropped_reason=str(item["dropped_reason"])),
        )
        for item in dropped_segments
    ]
    selected_segment_features = _segment_features(segments, status="selected")
    support_traj_features = _build_segment_support_traj_features(
        clustered_segments=clustered_segments,
        selected_segments=segments,
        accepted_candidates=accepted,
    )
    write_lines_geojson(dbg_dir / "step2_segment_candidates_all.geojson", all_candidate_features)
    write_lines_geojson(dbg_dir / "segment_candidates.geojson", all_candidate_features)
    write_lines_geojson(dbg_dir / "step2_segment_selected.geojson", selected_segment_features)
    write_lines_geojson(dbg_dir / "segment_selected.geojson", selected_segment_features)
    write_lines_geojson(dbg_dir / "step2_segment_dropped.geojson", dropped_segment_features)
    write_json(dbg_dir / "step2_traj_crossings_raw.geojson", _make_feature_collection(list(candidate_bundle.get("raw_crossing_features", []))))
    write_json(
        dbg_dir / "step2_traj_crossings_filtered.geojson",
        _make_feature_collection(list(candidate_bundle.get("filtered_crossing_features", []))),
    )
    write_json(dbg_dir / "step2_segment_support_trajs.geojson", _make_feature_collection(support_traj_features))
    write_json(
        dbg_dir / "step2_same_pair_groups.json",
        {"pairs": same_pair_groups, "metrics": {**candidate_bundle["stats"], **step2_metrics, **pair_scoped_exception_metrics}},
    )
    write_json(
        dbg_dir / "step2_zero_selected_pairs.json",
        {"pairs": zero_selected_pairs, "metrics": {**candidate_bundle["stats"], **step2_metrics, **pair_scoped_exception_metrics}},
    )
    write_json(
        dbg_dir / "step2_pair_scoped_exception_audit.json",
        {"pairs": pair_scoped_exception_audit, "metrics": {**candidate_bundle["stats"], **step2_metrics, **pair_scoped_exception_metrics}},
    )
    write_json(
        dbg_dir / "step2_terminal_node_audit.json",
        {"nodes": terminal_node_audit, "metrics": {**candidate_bundle["stats"], **step2_metrics, **pair_scoped_exception_metrics}},
    )
    write_json(
        dbg_dir / "step2_blocked_pair_bridge_audit.json",
        {"pairs": blocked_pair_bridge_audit, "metrics": {**candidate_bundle["stats"], **step2_metrics, **pair_scoped_exception_metrics}},
    )
    write_json(
        dbg_dir / "step2_segment_should_not_exist.json",
        {"pairs": segment_should_not_exist, "metrics": {**candidate_bundle["stats"], **step2_metrics, **pair_scoped_exception_metrics}},
    )
    write_json(
        dbg_dir / "step2_topology_pairs.json",
        {"pairs": topology_pairs_debug, "metrics": {**candidate_bundle["stats"], **step2_metrics, **pair_scoped_exception_metrics}},
    )
    write_json(
        dbg_dir / "step2_topology_arcs.json",
        {"arcs": topology_arcs_debug, "metrics": {**candidate_bundle["stats"], **step2_metrics, **pair_scoped_exception_metrics}},
    )
    write_json(
        dbg_dir / "step2_full_legal_arc_registry.json",
        {"arcs": list(full_arc_registry["rows"]), "summary": dict(full_arc_registry["summary"])},
    )
    return {
        "artifact": artifact,
        "inputs": inputs,
        "frame": frame,
        "segments": segments,
        "reason": "segments_ready" if segments else "no_segment_candidates",
    }


from .runner import run_full_pipeline, run_stage


__all__ = ["DEFAULT_PARAMS", "STAGES", "run_full_pipeline", "run_stage"]
