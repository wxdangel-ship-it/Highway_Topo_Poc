from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point
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
    line_to_coords,
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


def _trajectory_events(traj: Any, frame: InputFrame, hit_buffer_m: float) -> list[dict[str, Any]]:
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
        events.append({"nodeid": int(xsec.nodeid), "index": int(idx), "point": Point(float(px), float(py))})
    events.sort(key=lambda item: (int(item["index"]), int(item["nodeid"])))
    deduped: list[dict[str, Any]] = []
    for event in events:
        if deduped and int(deduped[-1]["nodeid"]) == int(event["nodeid"]) and abs(int(deduped[-1]["index"]) - int(event["index"])) <= 2:
            continue
        deduped.append(event)
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


def _segment_candidates(
    inputs: PatchInputs,
    frame: InputFrame,
    prior_roads: list[Any],
    params: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    xsec_map = _xsec_map(frame)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    hit_buffer = float(params["TRAJ_XSEC_HIT_BUFFER_M"])
    max_other = int(params["SEGMENT_MAX_OTHER_XSEC_CROSSINGS"])
    min_len = float(params["SEGMENT_MIN_LENGTH_M"])
    min_drivezone = float(params["SEGMENT_MIN_DRIVEZONE_RATIO"])
    divstrip_buffer = load_divstrip_buffer(inputs.divstrip_zone_metric, float(params["DIVSTRIP_BUFFER_M"]))

    def evaluate_candidate(candidate: dict[str, Any]) -> None:
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
            candidate["reason"] = "segment_too_short"
            rejected.append(candidate)
            return
        if inside_ratio < min_drivezone:
            candidate["reason"] = "segment_outside_drivezone"
            rejected.append(candidate)
            return
        if divstrip_cross:
            candidate["reason"] = "segment_crosses_divstrip"
            rejected.append(candidate)
            return
        if len(other_nodes) > max_other:
            candidate["reason"] = "segment_crosses_too_many_other_xsecs"
            rejected.append(candidate)
            return
        candidate["reason"] = "accepted"
        accepted.append(candidate)

    for traj in inputs.trajectories:
        traj_line = _trajectory_line(traj)
        if traj_line is None:
            continue
        events = _trajectory_events(traj, frame, hit_buffer)
        if len(events) < 2:
            continue
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
                evaluate_candidate(
                    {
                        "candidate_id": f"traj_{traj.traj_id}_{i}_{j}",
                        "source": "traj",
                        "src_nodeid": int(src_nodeid),
                        "dst_nodeid": int(dst_nodeid),
                        "line": subline,
                        "support_traj_ids": {str(traj.traj_id)},
                        "intermediate_nodeids": [int(v) for v in intermediate],
                        "prior_supported": False,
                    }
                )
    for idx, road in enumerate(prior_roads):
        line = getattr(road, "line", None)
        if not isinstance(line, LineString) or line.is_empty or line.length <= 1e-6:
            continue
        src_nodeid = int(getattr(road, "snodeid", 0))
        dst_nodeid = int(getattr(road, "enodeid", 0))
        if src_nodeid not in xsec_map or dst_nodeid not in xsec_map:
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
                rejected.append(
                    {
                        "candidate_id": f"prior_{idx}",
                        "source": "prior",
                        "src_nodeid": int(src_nodeid),
                        "dst_nodeid": int(dst_nodeid),
                        "line": line,
                        "support_traj_ids": set(),
                        "intermediate_nodeids": [],
                        "prior_supported": True,
                        "reason": "prior_endpoints_not_anchored",
                    }
                )
                continue
            src_nodeid, dst_nodeid = best_pair
        evaluate_candidate(
            {
                "candidate_id": f"prior_{idx}",
                "source": "prior",
                "src_nodeid": int(src_nodeid),
                "dst_nodeid": int(dst_nodeid),
                "line": line,
                "support_traj_ids": set(),
                "intermediate_nodeids": [],
                "prior_supported": True,
            }
        )
    return accepted, rejected


def _cluster_segments(candidates: list[dict[str, Any]], frame: InputFrame, params: dict[str, Any]) -> list[Segment]:
    xsec_map = _xsec_map(frame)
    by_pair: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for candidate in candidates:
        key = (int(candidate["src_nodeid"]), int(candidate["dst_nodeid"]))
        by_pair.setdefault(key, []).append(candidate)
    out: list[Segment] = []
    cluster_offset = float(params["SEGMENT_CLUSTER_OFFSET_M"])
    cluster_line_dist = float(params["SEGMENT_CLUSTER_LINE_DIST_M"])
    for (src_nodeid, dst_nodeid), pair_candidates in sorted(by_pair.items()):
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
            out.append(
                Segment(
                    segment_id=f"seg_{src_nodeid}_{dst_nodeid}_{rank}",
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
                    other_xsec_crossing_count=int(representative["other_xsec_crossing_count"]),
                    tolerated_other_xsec_crossings=int(params["SEGMENT_MAX_OTHER_XSEC_CROSSINGS"]),
                    prior_supported=bool(any(bool(item["prior_supported"]) for item in cluster)),
                    formation_reason=str(formation_reason),
                )
            )
    return out


def _segment_debug_features(candidates: list[dict[str, Any]], *, status: str) -> list[tuple[LineString, dict[str, Any]]]:
    out: list[tuple[LineString, dict[str, Any]]] = []
    for candidate in candidates:
        out.append(
            (
                candidate["line"],
                {
                    "candidate_id": str(candidate["candidate_id"]),
                    "source": str(candidate["source"]),
                    "src_nodeid": int(candidate["src_nodeid"]),
                    "dst_nodeid": int(candidate["dst_nodeid"]),
                    "status": str(status),
                    "reason": str(candidate.get("reason", "")),
                    "drivezone_ratio": float(candidate.get("drivezone_ratio", 0.0)),
                    "other_xsec_crossing_count": int(candidate.get("other_xsec_crossing_count", 0)),
                    "crosses_divstrip": bool(candidate.get("crosses_divstrip", False)),
                },
            )
        )
    return out


def _segment_features(segments: list[Segment]) -> list[tuple[LineString, dict[str, Any]]]:
    out: list[tuple[LineString, dict[str, Any]]] = []
    for segment in segments:
        out.append(
            (
                segment.geometry_metric(),
                {
                    "segment_id": str(segment.segment_id),
                    "src_nodeid": int(segment.src_nodeid),
                    "dst_nodeid": int(segment.dst_nodeid),
                    "support_count": int(segment.support_count),
                    "dedup_count": int(segment.dedup_count),
                    "source_modes": list(segment.source_modes),
                    "prior_supported": bool(segment.prior_supported),
                    "other_xsec_crossing_count": int(segment.other_xsec_crossing_count),
                    "formation_reason": str(segment.formation_reason),
                },
            )
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


def _build_witness_for_segment(segment: Segment, inputs: PatchInputs, params: dict[str, Any]) -> CorridorWitness:
    line = segment.geometry_metric()
    if float(line.length) < float(params["WITNESS_MIN_SEGMENT_LENGTH_M"]):
        return CorridorWitness(
            segment_id=str(segment.segment_id),
            status="insufficient",
            reason="segment_too_short_for_witness",
            line_coords=line_to_coords(line),
            sample_s_norm=0.5,
            intervals=tuple(),
            selected_interval_rank=None,
            selected_interval_start_s=None,
            selected_interval_end_s=None,
            exclusive_interval=False,
            stability_score=0.0,
            neighbor_match_count=0,
            axis_vector=(0.0, 1.0),
        )
    surface = _drivable_surface(inputs, params)
    if surface is None or surface.is_empty:
        return CorridorWitness(
            segment_id=str(segment.segment_id),
            status="insufficient",
            reason="drivable_surface_empty",
            line_coords=line_to_coords(line),
            sample_s_norm=0.5,
            intervals=tuple(),
            selected_interval_rank=None,
            selected_interval_start_s=None,
            selected_interval_end_s=None,
            exclusive_interval=False,
            stability_score=0.0,
            neighbor_match_count=0,
            axis_vector=(0.0, 1.0),
        )
    candidates: list[dict[str, Any]] = []
    for s_norm in tuple(params["WITNESS_SAMPLE_POSITIONS"]):
        dist = float(line.length) * float(s_norm)
        if dist <= 1.0 or dist >= float(line.length) - 1.0:
            continue
        center_pt = line.interpolate(dist)
        tx, ty = _line_tangent(line, dist)
        nx, ny = (-float(ty), float(tx))
        half_len = float(params["WITNESS_HALF_LENGTH_M"])
        witness_line = LineString(
            [
                (float(center_pt.x) - nx * half_len, float(center_pt.y) - ny * half_len),
                (float(center_pt.x) + nx * half_len, float(center_pt.y) + ny * half_len),
            ]
        )
        intervals = _intervals_on_xsec(
            witness_line,
            surface,
            align_vector=(nx, ny),
            min_len_m=float(params["INTERVAL_MIN_LEN_M"]),
        )
        if not intervals:
            candidates.append({"s_norm": float(s_norm), "line": witness_line, "intervals": [], "selected": None, "axis_vector": (nx, ny)})
            continue
        ref_s = float(witness_line.project(center_pt))
        selected, _method, _reason = _choose_interval(intervals, reference_s=ref_s, desired_rank=None)
        if selected is None:
            candidates.append({"s_norm": float(s_norm), "line": witness_line, "intervals": intervals, "selected": None, "axis_vector": (nx, ny)})
            continue
        nearest_gap = float("inf")
        if len(intervals) > 1:
            for other in intervals:
                if int(other.rank) == int(selected.rank):
                    continue
                gap = max(0.0, min(abs(float(selected.start_s) - float(other.end_s)), abs(float(other.start_s) - float(selected.end_s))))
                nearest_gap = min(nearest_gap, gap)
        candidates.append(
            {
                "s_norm": float(s_norm),
                "line": witness_line,
                "intervals": intervals,
                "selected": selected,
                "nearest_gap": float(nearest_gap),
                "axis_vector": (nx, ny),
            }
        )
    if not candidates:
        return CorridorWitness(
            segment_id=str(segment.segment_id),
            status="insufficient",
            reason="no_witness_candidates",
            line_coords=line_to_coords(line),
            sample_s_norm=0.5,
            intervals=tuple(),
            selected_interval_rank=None,
            selected_interval_start_s=None,
            selected_interval_end_s=None,
            exclusive_interval=False,
            stability_score=0.0,
            neighbor_match_count=0,
            axis_vector=(0.0, 1.0),
        )
    best: dict[str, Any] | None = None
    tol = float(params["WITNESS_CENTER_TOL_M"])
    for candidate in candidates:
        selected = candidate.get("selected")
        if selected is None:
            candidate["score"] = 0.0
            candidate["match_count"] = 0
            continue
        match_count = 0
        for other in candidates:
            other_selected = other.get("selected")
            if other is candidate or other_selected is None:
                continue
            if int(other_selected.rank) != int(selected.rank):
                continue
            if abs(float(other_selected.center_s) - float(selected.center_s)) <= tol:
                match_count += 1
        exclusive = len(candidate["intervals"]) == 1 or float(candidate.get("nearest_gap", 0.0)) >= float(params["WITNESS_GAP_MIN_M"])
        score = 0.7 * (float(match_count) / max(1.0, float(max(1, len(candidates) - 1)))) + 0.3 * (1.0 if exclusive else 0.0)
        candidate["score"] = float(score)
        candidate["match_count"] = int(match_count)
        candidate["exclusive"] = bool(exclusive)
        if best is None or float(score) > float(best.get("score", -1.0)):
            best = candidate
    if best is None or best.get("selected") is None:
        chosen = candidates[min(range(len(candidates)), key=lambda idx: abs(float(candidates[idx]["s_norm"]) - 0.5))]
        return CorridorWitness(
            segment_id=str(segment.segment_id),
            status="insufficient",
            reason="witness_no_legal_interval",
            line_coords=line_to_coords(chosen["line"]),
            sample_s_norm=float(chosen["s_norm"]),
            intervals=tuple(),
            selected_interval_rank=None,
            selected_interval_start_s=None,
            selected_interval_end_s=None,
            exclusive_interval=False,
            stability_score=0.0,
            neighbor_match_count=0,
            axis_vector=(float(chosen["axis_vector"][0]), float(chosen["axis_vector"][1])),
        )
    selected = best["selected"]
    status = "selected"
    reason = "stable_exclusive_interval"
    if float(best.get("score", 0.0)) < float(params["WITNESS_MIN_STABILITY_SCORE"]):
        status = "insufficient"
        reason = "witness_not_stable_enough"
    return CorridorWitness(
        segment_id=str(segment.segment_id),
        status=str(status),
        reason=str(reason),
        line_coords=line_to_coords(best["line"]),
        sample_s_norm=float(best["s_norm"]),
        intervals=tuple(best["intervals"]),
        selected_interval_rank=int(selected.rank),
        selected_interval_start_s=float(selected.start_s),
        selected_interval_end_s=float(selected.end_s),
        exclusive_interval=bool(best.get("exclusive", False)),
        stability_score=float(best.get("score", 0.0)),
        neighbor_match_count=int(best.get("match_count", 0)),
        axis_vector=(float(best["axis_vector"][0]), float(best["axis_vector"][1])),
    )


def _build_identity(segment: Segment, witness: CorridorWitness) -> CorridorIdentity:
    if str(witness.status) == "selected" and bool(witness.exclusive_interval):
        return CorridorIdentity(
            segment_id=str(segment.segment_id),
            state="witness_based",
            reason="stable_witness_interval",
            risk_flags=tuple(),
            witness_interval_rank=witness.selected_interval_rank,
            prior_supported=bool(segment.prior_supported),
        )
    if bool(segment.prior_supported):
        return CorridorIdentity(
            segment_id=str(segment.segment_id),
            state="prior_based",
            reason="fallback_to_prior_reference",
            risk_flags=("prior_fallback",),
            witness_interval_rank=witness.selected_interval_rank,
            prior_supported=True,
        )
    return CorridorIdentity(
        segment_id=str(segment.segment_id),
        state="unresolved",
        reason=str(witness.reason or "no_stable_corridor_identity"),
        risk_flags=tuple(),
        witness_interval_rank=witness.selected_interval_rank,
        prior_supported=bool(segment.prior_supported),
    )


def _build_slot(
    *,
    segment: Segment,
    witness: CorridorWitness | None,
    identity: CorridorIdentity,
    xsec: BaseCrossSection,
    line: LineString,
    inputs: PatchInputs,
    params: dict[str, Any],
    endpoint_tag: str,
) -> SlotInterval:
    surface = _drivable_surface(inputs, params)
    xsec_line = xsec.geometry_metric()
    align_vector = witness.axis_vector if witness is not None else _line_direction(xsec_line)
    intervals = _intervals_on_xsec(
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
        interval, method, reason = _choose_interval(intervals, reference_s=ref_s, desired_rank=desired_rank)
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


def _build_final_road(
    *,
    patch_id: str,
    segment: Segment,
    identity: CorridorIdentity,
    witness: CorridorWitness | None,
    src_slot: SlotInterval,
    dst_slot: SlotInterval,
    inputs: PatchInputs,
    params: dict[str, Any],
) -> tuple[FinalRoad | None, dict[str, Any]]:
    result = {"segment_id": str(segment.segment_id), "corridor_state": str(identity.state), "reason": ""}
    if str(identity.state) == "unresolved":
        result["reason"] = str(identity.reason)
        return None, result
    if src_slot.interval is None or dst_slot.interval is None:
        result["reason"] = "slot_unresolved"
        return None, result
    start_pt = _midpoint_of_interval(src_slot.interval)
    end_pt = _midpoint_of_interval(dst_slot.interval)
    support_line = segment.geometry_metric()
    road_line = _replace_endpoints(support_line, start_pt, end_pt)
    if str(identity.state) == "witness_based" and witness is not None and witness.selected_interval_rank is not None:
        selected = None
        for interval in witness.intervals:
            if int(interval.rank) == int(witness.selected_interval_rank):
                selected = interval
                break
        if selected is not None:
            mid_pt = _midpoint_of_interval(selected)
            road_line = LineString(
                [
                    (float(start_pt.x), float(start_pt.y)),
                    (float(mid_pt.x), float(mid_pt.y)),
                    (float(end_pt.x), float(end_pt.y)),
                ]
            )
    drivezone_ratio = _drivezone_ratio(road_line, inputs.drivezone_zone_metric)
    divstrip_buffer = load_divstrip_buffer(inputs.divstrip_zone_metric, float(params["DIVSTRIP_BUFFER_M"]))
    if drivezone_ratio < float(params["ROAD_MIN_DRIVEZONE_RATIO"]):
        result["reason"] = "road_outside_drivezone"
        return None, result
    if divstrip_buffer is not None and (not divstrip_buffer.is_empty) and road_line.intersects(divstrip_buffer):
        result["reason"] = "road_crosses_divstrip"
        return None, result
    road = FinalRoad(
        road_id=f"{patch_id}_{segment.segment_id}",
        segment_id=str(segment.segment_id),
        src_nodeid=int(segment.src_nodeid),
        dst_nodeid=int(segment.dst_nodeid),
        corridor_state=str(identity.state),
        line_coords=line_to_coords(road_line),
        length_m=float(road_line.length),
        support_traj_count=int(len(segment.support_traj_ids)),
        dedup_count=int(segment.dedup_count),
        risk_flags=tuple(str(v) for v in identity.risk_flags),
    )
    result["reason"] = "built"
    result["drivezone_ratio"] = float(drivezone_ratio)
    return road, result


def _write_road_outputs(
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
    inputs: PatchInputs,
) -> None:
    patch_dir = patch_root(out_root, run_id, patch_id)
    dbg_dir = debug_dir(out_root, run_id, patch_id)
    road_features: list[tuple[LineString, dict[str, Any]]] = []
    shape_ref_features: list[tuple[LineString, dict[str, Any]]] = []
    metrics_segments: list[dict[str, Any]] = []
    hard_breakpoints: list[dict[str, Any]] = []
    soft_breakpoints: list[dict[str, Any]] = []
    road_map = {str(road.segment_id): road for road in roads}
    result_map = {str(item["segment_id"]): item for item in road_results}
    for segment in segments:
        identity = identities[str(segment.segment_id)]
        witness = witnesses.get(str(segment.segment_id))
        src_slot = slots[str(segment.segment_id)]["src"]
        dst_slot = slots[str(segment.segment_id)]["dst"]
        shape_ref_features.append(
            (
                segment.geometry_metric(),
                {
                    "segment_id": str(segment.segment_id),
                    "src_nodeid": int(segment.src_nodeid),
                    "dst_nodeid": int(segment.dst_nodeid),
                    "corridor_state": str(identity.state),
                },
            )
        )
        road = road_map.get(str(segment.segment_id))
        build_result = result_map.get(str(segment.segment_id), {})
        endpoint_dist_to_slot = {"src": None, "dst": None}
        endpoint_dist_to_xsec = {"src": None, "dst": None}
        road_in_drivezone = False
        road_crosses_divstrip = False
        if road is not None:
            road_line = road.geometry_metric()
            road_in_drivezone = _drivezone_ratio(road_line, inputs.drivezone_zone_metric) >= 0.999
            divstrip_buffer = load_divstrip_buffer(inputs.divstrip_zone_metric, float(DEFAULT_PARAMS["DIVSTRIP_BUFFER_M"]))
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
                    },
                )
            )
        unresolved_reason = ""
        if road is None:
            unresolved_reason = str(build_result.get("reason") or identity.reason)
        metrics_entry = {
            "segment_id": str(segment.segment_id),
            "segment_established": True,
            "src_nodeid": int(segment.src_nodeid),
            "dst_nodeid": int(segment.dst_nodeid),
            "corridor_identity": str(identity.state),
            "corridor_reason": str(identity.reason),
            "has_exclusive_interval": bool(witness.exclusive_interval) if witness is not None else False,
            "witness_stability_score": 0.0 if witness is None else float(witness.stability_score),
            "src_slot_resolved": bool(src_slot.resolved),
            "dst_slot_resolved": bool(dst_slot.resolved),
            "endpoint_dist_to_slot": endpoint_dist_to_slot,
            "endpoint_dist_to_xsec": endpoint_dist_to_xsec,
            "road_in_drivezone": bool(road_in_drivezone),
            "road_crosses_divstrip": bool(road_crosses_divstrip),
            "unresolved_reason": str(unresolved_reason),
        }
        metrics_segments.append(metrics_entry)
        if road is None:
            hard_breakpoints.append({"segment_id": str(segment.segment_id), "reason": str(unresolved_reason or "no_geometry_candidate"), "severity": "hard"})
        elif identity.state == "prior_based":
            soft_breakpoints.append({"segment_id": str(segment.segment_id), "reason": "prior_based_fallback", "severity": "soft"})
    metrics = {
        "patch_id": str(patch_id),
        "segment_count": int(len(segments)),
        "road_count": int(len(roads)),
        "unresolved_segment_count": int(sum(1 for entry in metrics_segments if entry["unresolved_reason"])),
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
    ]
    for entry in metrics_segments:
        summary_lines.append(
            " ".join(
                [
                    f"segment_id={entry['segment_id']}",
                    f"corridor={entry['corridor_identity']}",
                    f"src_slot={str(entry['src_slot_resolved']).lower()}",
                    f"dst_slot={str(entry['dst_slot_resolved']).lower()}",
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
            "road_build": road_results,
        },
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
    accepted, rejected = _segment_candidates(inputs, frame, prior_roads, params)
    segments = _cluster_segments(accepted, frame, params)
    artifact = {
        "segments": [segment.to_dict() for segment in segments],
        "accepted_candidate_count": int(len(accepted)),
        "rejected_candidate_count": int(len(rejected)),
        "excluded_candidates": [
            {
                "candidate_id": str(item["candidate_id"]),
                "source": str(item["source"]),
                "src_nodeid": int(item["src_nodeid"]),
                "dst_nodeid": int(item["dst_nodeid"]),
                "reason": str(item.get("reason", "")),
                "other_xsec_nodes": [int(v) for v in item.get("other_xsec_nodes", [])],
            }
            for item in rejected
        ],
    }
    dbg_dir = debug_dir(out_root, run_id, patch_id)
    write_json(_artifact_path(out_root, run_id, patch_id, "step2_segment"), artifact)
    write_lines_geojson(dbg_dir / "segment_candidates.geojson", [*_segment_debug_features(accepted, status="accepted"), *_segment_debug_features(rejected, status="rejected")])
    write_lines_geojson(dbg_dir / "segment_selected.geojson", _segment_features(segments))
    return {
        "artifact": artifact,
        "inputs": inputs,
        "frame": frame,
        "segments": segments,
        "reason": "segments_ready" if segments else "no_segment_candidates",
    }


def _stage3_witness(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    inputs, frame, _prior_roads = load_inputs_and_frame(data_root, patch_id, params=params)
    segments_payload = _load_stage_payload(out_root, run_id, patch_id, "step2_segment")
    segments = [Segment.from_dict(item) for item in segments_payload.get("segments", [])]
    witnesses = [_build_witness_for_segment(segment, inputs, params) for segment in segments]
    artifact = {"witnesses": [witness.to_dict() for witness in witnesses]}
    dbg_dir = debug_dir(out_root, run_id, patch_id)
    write_json(_artifact_path(out_root, run_id, patch_id, "step3_witness"), artifact)
    write_lines_geojson(
        dbg_dir / "corridor_witness_candidates.geojson",
        [
            (
                witness.geometry_metric(),
                {
                    "segment_id": str(witness.segment_id),
                    "status": str(witness.status),
                    "reason": str(witness.reason),
                    "stability_score": float(witness.stability_score),
                    "selected_interval_rank": witness.selected_interval_rank,
                },
            )
            for witness in witnesses
        ],
    )
    write_lines_geojson(
        dbg_dir / "corridor_witness_selected.geojson",
        [
            (
                witness.geometry_metric(),
                {
                    "segment_id": str(witness.segment_id),
                    "status": str(witness.status),
                    "stability_score": float(witness.stability_score),
                    "exclusive_interval": bool(witness.exclusive_interval),
                },
            )
            for witness in witnesses
            if str(witness.status) == "selected"
        ],
    )
    return {"artifact": artifact, "inputs": inputs, "frame": frame, "segments": segments, "witnesses": witnesses, "reason": "witness_ready"}


def _stage4_corridor_identity(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    segments_payload = _load_stage_payload(out_root, run_id, patch_id, "step2_segment")
    witnesses_payload = _load_stage_payload(out_root, run_id, patch_id, "step3_witness")
    segments = [Segment.from_dict(item) for item in segments_payload.get("segments", [])]
    witnesses = [CorridorWitness.from_dict(item) for item in witnesses_payload.get("witnesses", [])]
    witness_map = {str(witness.segment_id): witness for witness in witnesses}
    fallback_witness = lambda segment: CorridorWitness(
        segment_id=str(segment.segment_id),
        status="insufficient",
        reason="witness_missing",
        line_coords=segment.geometry_coords,
        sample_s_norm=0.5,
        intervals=tuple(),
        selected_interval_rank=None,
        selected_interval_start_s=None,
        selected_interval_end_s=None,
        exclusive_interval=False,
        stability_score=0.0,
        neighbor_match_count=0,
        axis_vector=(0.0, 1.0),
    )
    identities = [_build_identity(segment, witness_map.get(str(segment.segment_id), fallback_witness(segment))) for segment in segments]
    artifact = {"corridor_identities": [identity.to_dict() for identity in identities]}
    dbg_dir = debug_dir(out_root, run_id, patch_id)
    write_json(_artifact_path(out_root, run_id, patch_id, "step4_corridor_identity"), artifact)
    write_json(dbg_dir / "corridor_identity.json", artifact)
    return {"artifact": artifact, "segments": segments, "identities": identities, "reason": "corridor_identity_ready"}


def _stage5_slot_mapping(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    inputs, frame, _prior_roads = load_inputs_and_frame(data_root, patch_id, params=params)
    xsec_map = _xsec_map(frame)
    segments_payload = _load_stage_payload(out_root, run_id, patch_id, "step2_segment")
    witnesses_payload = _load_stage_payload(out_root, run_id, patch_id, "step3_witness")
    identities_payload = _load_stage_payload(out_root, run_id, patch_id, "step4_corridor_identity")
    segments = [Segment.from_dict(item) for item in segments_payload.get("segments", [])]
    witnesses = {str(item.segment_id): item for item in (CorridorWitness.from_dict(v) for v in witnesses_payload.get("witnesses", []))}
    identities = {str(item.segment_id): item for item in (CorridorIdentity.from_dict(v) for v in identities_payload.get("corridor_identities", []))}
    slot_map: dict[str, dict[str, SlotInterval]] = {}
    debug_features: list[tuple[LineString, dict[str, Any]]] = []
    for segment in segments:
        witness = witnesses.get(str(segment.segment_id))
        identity = identities[str(segment.segment_id)]
        line = segment.geometry_metric()
        src_slot = _build_slot(
            segment=segment,
            witness=witness,
            identity=identity,
            xsec=xsec_map[int(segment.src_nodeid)],
            line=line,
            inputs=inputs,
            params=params,
            endpoint_tag="src",
        )
        dst_slot = _build_slot(
            segment=segment,
            witness=witness,
            identity=identity,
            xsec=xsec_map[int(segment.dst_nodeid)],
            line=line,
            inputs=inputs,
            params=params,
            endpoint_tag="dst",
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
                    },
                )
            )
    artifact = {
        "slot_mapping": {
            segment_id: {"src": values["src"].to_dict(), "dst": values["dst"].to_dict()}
            for segment_id, values in slot_map.items()
        }
    }
    dbg_dir = debug_dir(out_root, run_id, patch_id)
    write_json(_artifact_path(out_root, run_id, patch_id, "step5_slot_mapping"), artifact)
    write_lines_geojson(dbg_dir / "slot_src_dst.geojson", debug_features)
    return {
        "artifact": artifact,
        "inputs": inputs,
        "frame": frame,
        "segments": segments,
        "witnesses": witnesses,
        "identities": identities,
        "slots": slot_map,
        "reason": "slot_mapping_ready",
    }


def _stage6_build_road(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    inputs, frame, _prior_roads = load_inputs_and_frame(data_root, patch_id, params=params)
    segments_payload = _load_stage_payload(out_root, run_id, patch_id, "step2_segment")
    witnesses_payload = _load_stage_payload(out_root, run_id, patch_id, "step3_witness")
    identities_payload = _load_stage_payload(out_root, run_id, patch_id, "step4_corridor_identity")
    slots_payload = _load_stage_payload(out_root, run_id, patch_id, "step5_slot_mapping")
    segments = [Segment.from_dict(item) for item in segments_payload.get("segments", [])]
    witnesses = {str(item.segment_id): item for item in (CorridorWitness.from_dict(v) for v in witnesses_payload.get("witnesses", []))}
    identities = {str(item.segment_id): item for item in (CorridorIdentity.from_dict(v) for v in identities_payload.get("corridor_identities", []))}
    slot_map: dict[str, dict[str, SlotInterval]] = {}
    for segment_id, value in (slots_payload.get("slot_mapping") or {}).items():
        slot_map[str(segment_id)] = {"src": SlotInterval.from_dict(value["src"]), "dst": SlotInterval.from_dict(value["dst"])}
    roads: list[FinalRoad] = []
    road_results: list[dict[str, Any]] = []
    for segment in segments:
        road, build_meta = _build_final_road(
            patch_id=str(patch_id),
            segment=segment,
            identity=identities[str(segment.segment_id)],
            witness=witnesses.get(str(segment.segment_id)),
            src_slot=slot_map[str(segment.segment_id)]["src"],
            dst_slot=slot_map[str(segment.segment_id)]["dst"],
            inputs=inputs,
            params=params,
        )
        road_results.append(dict(build_meta))
        if road is not None:
            roads.append(road)
    artifact = {"roads": [road.to_dict() for road in roads], "road_results": road_results}
    write_json(_artifact_path(out_root, run_id, patch_id, "step6_build_road"), artifact)
    _write_road_outputs(
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
    )
    return {"artifact": artifact, "roads": roads, "reason": "road_ready" if roads else "no_geometry_candidate"}


def run_stage(
    *,
    stage: str,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    force: bool = False,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stage_name = str(stage)
    if stage_name not in STAGES:
        raise ValueError(f"unknown_stage:{stage_name}")
    merged_params = _merge_params(params)
    patch_dir = patch_root(out_root, run_id, patch_id)
    patch_dir.mkdir(parents=True, exist_ok=True)
    dbg_dir = debug_dir(out_root, run_id, patch_id)
    dbg_dir.mkdir(parents=True, exist_ok=True)
    existing_state = _load_previous_state(out_root, run_id, patch_id, stage_name)
    if existing_state is not None and bool(existing_state.get("ok")) and not bool(force):
        return {"stage": stage_name, "status": "skipped", "reason": "already_completed"}
    _require_previous_stage(out_root, run_id, patch_id, stage_name)
    runner = {
        "step1_input_frame": _stage1_input_frame,
        "step2_segment": _stage2_segment,
        "step3_witness": _stage3_witness,
        "step4_corridor_identity": _stage4_corridor_identity,
        "step5_slot_mapping": _stage5_slot_mapping,
        "step6_build_road": _stage6_build_road,
    }[stage_name]
    try:
        result = runner(data_root=data_root, patch_id=patch_id, run_id=run_id, out_root=out_root, params=merged_params)
    except Exception as exc:
        reason = _trim_reason(str(exc) or type(exc).__name__)
        write_step_state(
            step_dir=stage_dir(out_root, run_id, patch_id, stage_name),
            step=stage_name,
            ok=False,
            reason=reason,
            run_id=run_id,
            patch_id=patch_id,
            data_root=data_root,
            out_root=out_root,
        )
        raise
    write_step_state(
        step_dir=stage_dir(out_root, run_id, patch_id, stage_name),
        step=stage_name,
        ok=True,
        reason=str(result.get("reason", "ok")),
        run_id=run_id,
        patch_id=patch_id,
        data_root=data_root,
        out_root=out_root,
    )
    return {"stage": stage_name, "status": "ok", "reason": str(result.get("reason", "ok"))}


def run_full_pipeline(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    force: bool = False,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    merged_params = _merge_params(params)
    out: list[dict[str, Any]] = []
    for stage in STAGES:
        out.append(
            run_stage(
                stage=stage,
                data_root=data_root,
                patch_id=patch_id,
                run_id=run_id,
                out_root=out_root,
                force=force,
                params=merged_params,
            )
        )
    return out


__all__ = ["DEFAULT_PARAMS", "STAGES", "run_full_pipeline", "run_stage"]
