from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
from typing import Any

from shapely.geometry import LineString, Point
from shapely.ops import substring

from .models import BaseCrossSection, EndpointInterval, Segment, coords_to_line, line_to_coords


def _pipeline():
    from . import pipeline as pipeline_module

    return pipeline_module


def _line_from_coords(coords: Any) -> LineString | None:
    pts = []
    for item in coords or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        x = float(item[0])
        y = float(item[1])
        if not (isfinite(x) and isfinite(y)):
            continue
        pts.append((x, y))
    if len(pts) < 2:
        return None
    line = LineString(pts)
    if line.is_empty or float(line.length) <= 1e-6:
        return None
    return line


def _line_is_usable(line: LineString | None) -> bool:
    return bool(line is not None and not line.is_empty and float(line.length) > 1e-6)


def _safe_line_project(line: LineString | None, point: Point | None) -> float | None:
    if not _line_is_usable(line) or point is None or point.is_empty:
        return None
    try:
        value = float(line.project(point))
    except Exception:
        return None
    return value if isfinite(value) else None


def _safe_point(x: float, y: float) -> Point | None:
    if not (isfinite(float(x)) and isfinite(float(y))):
        return None
    point = Point(float(x), float(y))
    return point if not point.is_empty else None


def _segment_line(selected_segment: Segment | None) -> LineString | None:
    if selected_segment is None:
        return None
    try:
        line = selected_segment.geometry_metric()
    except Exception:
        return None
    return line if _line_is_usable(line) else None


def _arc_line(row: dict[str, Any]) -> LineString | None:
    return _line_from_coords(row.get("line_coords", []))


def _support_corridor_line(row: dict[str, Any]) -> LineString | None:
    line = _line_from_coords(row.get("support_reference_coords", []))
    if _line_is_usable(line):
        return line
    line = _line_from_coords(row.get("stitched_support_reference_coords", []))
    if _line_is_usable(line):
        return line
    merged_coords: list[tuple[float, float]] = []
    for item in list(row.get("traj_support_segments", []) or []):
        for coord in item.get("line_coords", []) or []:
            if not isinstance(coord, (list, tuple)) or len(coord) < 2:
                continue
            xy = (float(coord[0]), float(coord[1]))
            if not merged_coords or xy != merged_coords[-1]:
                merged_coords.append(xy)
    return _line_from_coords(merged_coords)


def _production_line(row: dict[str, Any], production_segments_by_arc: dict[str, Segment]) -> LineString | None:
    production = production_segments_by_arc.get(str(row.get("topology_arc_id", "")))
    return _segment_line(production)


def _point_from_event(event: dict[str, Any]) -> Point | None:
    point = event.get("point")
    if isinstance(point, Point) and not point.is_empty:
        return point
    return None


def _surface_intervals(
    *,
    xsec_line: LineString,
    drivable_surface: Any | None,
    params: dict[str, Any],
) -> list[Any]:
    pipeline = _pipeline()
    if drivable_surface is None or getattr(drivable_surface, "is_empty", True):
        return []
    return pipeline._intervals_on_xsec(
        xsec_line,
        drivable_surface,
        align_vector=None,
        min_len_m=float(params.get("INTERVAL_MIN_LEN_M", 1.0)),
    )


def _surface_clip_interval(
    *,
    raw_start_s: float,
    raw_end_s: float,
    raw_center_s: float,
    surface_intervals: list[Any],
    xsec_line: LineString,
) -> tuple[float, float, float, LineString, str]:
    start_s = float(max(0.0, min(raw_start_s, raw_end_s)))
    end_s = float(max(start_s, max(raw_start_s, raw_end_s)))
    if not surface_intervals:
        clipped = substring(xsec_line, start_s, end_s)
        clipped_line = clipped if isinstance(clipped, LineString) and not clipped.is_empty else _line_from_coords(
            [
                [float(xsec_line.interpolate(start_s).x), float(xsec_line.interpolate(start_s).y)],
                [float(xsec_line.interpolate(end_s).x), float(xsec_line.interpolate(end_s).y)],
            ]
        )
        return start_s, end_s, float((start_s + end_s) / 2.0), clipped_line, "no_surface_clip"
    best = None
    best_overlap = -1.0
    for interval in surface_intervals:
        overlap_start = max(float(interval.start_s), float(start_s))
        overlap_end = min(float(interval.end_s), float(end_s))
        overlap = max(0.0, float(overlap_end - overlap_start))
        contains_center = float(interval.start_s) - 1e-6 <= float(raw_center_s) <= float(interval.end_s) + 1e-6
        score = (1.0 if contains_center else 0.0, float(overlap), -abs(float(interval.center_s) - float(raw_center_s)))
        if best is None or score > best[0]:
            best = (score, interval, overlap_start, overlap_end)
            best_overlap = float(overlap)
    if best is None:
        start_s = float(surface_intervals[0].start_s)
        end_s = float(surface_intervals[0].end_s)
        reason = "surface_nearest_interval"
    else:
        _, interval, overlap_start, overlap_end = best
        if best_overlap > 1e-6:
            start_s = float(overlap_start)
            end_s = float(overlap_end)
            reason = "surface_overlap_clip"
        else:
            start_s = float(interval.start_s)
            end_s = float(interval.end_s)
            reason = "surface_nearest_interval"
    if end_s <= start_s + 1e-6:
        center = min(max(float(raw_center_s), float(start_s)), float(end_s))
        half = min(0.5, float(xsec_line.length) / 2.0)
        start_s = max(0.0, float(center - half))
        end_s = min(float(xsec_line.length), float(center + half))
    clipped = substring(xsec_line, start_s, end_s)
    clipped_line = clipped if isinstance(clipped, LineString) and not clipped.is_empty else _line_from_coords(
        [
            [float(xsec_line.interpolate(start_s).x), float(xsec_line.interpolate(start_s).y)],
            [float(xsec_line.interpolate(end_s).x), float(xsec_line.interpolate(end_s).y)],
        ]
    )
    center_s = float((start_s + end_s) / 2.0)
    return start_s, end_s, center_s, clipped_line, reason


def _neighbor_point_for_role(
    traj_row: dict[str, Any],
    *,
    event_index: int,
    endpoint_role: str,
) -> Point | None:
    points = list(traj_row.get("points", tuple()) or ())
    if not points:
        return None
    direction = 1 if str(endpoint_role) == "src" else -1
    start = int(event_index) + int(direction)
    limit = len(points) if direction > 0 else -1
    idx = start
    while idx != limit:
        point = points[idx]
        if isinstance(point, Point) and not point.is_empty:
            return point
        idx += int(direction)
    return None


def _is_clean_crossing(
    *,
    traj_row: dict[str, Any],
    event: dict[str, Any],
    current_xsec_id: int,
    endpoint_xsec_map: dict[int, BaseCrossSection],
    params: dict[str, Any],
) -> bool:
    event_index = int(event.get("index", -1))
    if event_index < 0:
        return False
    coords = list(traj_row.get("coords", tuple()) or ())
    if len(coords) < 2:
        return False
    lo = max(0, event_index - int(params.get("XSEC_ENDPOINT_CLEAN_NEIGHBOR_POINTS", 2)))
    hi = min(len(coords) - 1, event_index + int(params.get("XSEC_ENDPOINT_CLEAN_NEIGHBOR_POINTS", 2)))
    if hi - lo < 1:
        return True
    local_line = _line_from_coords(coords[lo : hi + 1])
    if not _line_is_usable(local_line):
        return True
    hit_buffer = float(params.get("TRAJ_XSEC_HIT_BUFFER_M", 4.0))
    for nodeid, xsec in endpoint_xsec_map.items():
        if int(nodeid) == int(current_xsec_id):
            continue
        try:
            if local_line.intersects(xsec.geometry_metric().buffer(hit_buffer)):
                return False
        except Exception:
            continue
    return True


def _distance_to_corridor(point: Point | None, line: LineString | None) -> float:
    if point is None or point.is_empty or not _line_is_usable(line):
        return 999.0
    try:
        return float(point.distance(line))
    except Exception:
        return 999.0


def _row_candidate_order(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        0 if bool(row.get("production_multi_arc_allowed", False)) else 1,
        int(row.get("same_pair_rank", 9999) or 9999),
        str(row.get("canonical_pair", row.get("pair", ""))),
        str(row.get("topology_arc_id", "")),
    )


def _ownership_for_crossing(
    *,
    group_rows: list[dict[str, Any]],
    traj_row: dict[str, Any],
    event: dict[str, Any],
    endpoint_role: str,
    selected_segments_by_arc: dict[str, Segment],
    production_segments_by_arc: dict[str, Segment],
    params: dict[str, Any],
) -> tuple[dict[str, Any] | None, str, float]:
    del selected_segments_by_arc
    event_index = int(event.get("index", -1))
    if event_index < 0:
        return None, "event_index_missing", 999.0
    event_point = _point_from_event(event)
    if event_point is None:
        return None, "event_point_missing", 999.0
    neighbor_point = _neighbor_point_for_role(
        traj_row,
        event_index=event_index,
        endpoint_role=endpoint_role,
    ) or event_point
    corridor_buffer_m = float(params.get("XSEC_ENDPOINT_CORRIDOR_BUFFER_M", 4.0))

    support_hits: list[tuple[float, dict[str, Any]]] = []
    for row in group_rows:
        line = _support_corridor_line(row)
        distance = _distance_to_corridor(neighbor_point, line)
        if distance <= corridor_buffer_m:
            support_hits.append((distance, row))
    if support_hits:
        distance, row = min(support_hits, key=lambda item: (float(item[0]), _row_candidate_order(item[1])))
        return row, "support_corridor", float(distance)

    production_hits: list[tuple[float, dict[str, Any]]] = []
    for row in group_rows:
        line = _production_line(row, production_segments_by_arc)
        distance = _distance_to_corridor(neighbor_point, line)
        if distance <= corridor_buffer_m:
            production_hits.append((distance, row))
    if production_hits:
        distance, row = min(production_hits, key=lambda item: (float(item[0]), _row_candidate_order(item[1])))
        return row, "production_working_segment", float(distance)

    nearest: tuple[float, dict[str, Any]] | None = None
    for row in group_rows:
        candidate = (_distance_to_corridor(neighbor_point, _arc_line(row)), row)
        if nearest is None or candidate < nearest:
            nearest = candidate
    if nearest is None:
        return None, "arc_geometry_missing", 999.0
    return nearest[1], "arc_geometry_nearest", float(nearest[0])


def collect_xsec_crossings(
    *,
    rows: list[dict[str, Any]],
    traj_rows: list[dict[str, Any]],
    xsec_map: dict[int, BaseCrossSection],
    selected_segments_by_arc: dict[str, Segment],
    production_segments_by_arc: dict[str, Segment] | None,
    params: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    production_segments_by_arc = dict(production_segments_by_arc or {})
    endpoint_xsec_ids = {
        int(nodeid)
        for row in rows
        for nodeid in (row.get("src"), row.get("dst"))
        if nodeid is not None and int(nodeid) in xsec_map
    }
    endpoint_xsec_map = {int(nodeid): xsec_map[int(nodeid)] for nodeid in endpoint_xsec_ids}
    crossings_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for endpoint_role in ("src", "dst"):
        group_rows_by_xsec: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            xsec_id = int(row.get("src" if endpoint_role == "src" else "dst", 0) or 0)
            if xsec_id in xsec_map:
                group_rows_by_xsec[xsec_id].append(row)
        for xsec_id, group_rows in group_rows_by_xsec.items():
            xsec_line = xsec_map[int(xsec_id)].geometry_metric()
            for traj_row in traj_rows:
                for event in traj_row.get("events", tuple()) or ():
                    if int(event.get("nodeid", -1)) != int(xsec_id):
                        continue
                    owner_row, ownership_reason, owner_distance = _ownership_for_crossing(
                        group_rows=group_rows,
                        traj_row=traj_row,
                        event=event,
                        endpoint_role=endpoint_role,
                        selected_segments_by_arc=selected_segments_by_arc,
                        production_segments_by_arc=production_segments_by_arc,
                        params=params,
                    )
                    if owner_row is None:
                        continue
                    point = _point_from_event(event)
                    crossing_s = _safe_line_project(xsec_line, point)
                    if crossing_s is None:
                        continue
                    clean = _is_clean_crossing(
                        traj_row=traj_row,
                        event=event,
                        current_xsec_id=int(xsec_id),
                        endpoint_xsec_map=endpoint_xsec_map,
                        params=params,
                    )
                    crossings_by_key[f"{owner_row.get('topology_arc_id', '')}:{endpoint_role}"].append(
                        {
                            "xsec_id": int(xsec_id),
                            "arc_id": str(owner_row.get("topology_arc_id", "")),
                            "endpoint_role": str(endpoint_role),
                            "traj_id": str(traj_row.get("traj_id", "")),
                            "source_traj_id": str(traj_row.get("source_traj_id", traj_row.get("traj_id", ""))),
                            "crossing_s": float(crossing_s),
                            "ownership_reason": str(ownership_reason),
                            "ownership_distance_m": float(owner_distance),
                            "clean": bool(clean),
                            "point": point,
                            "raw_event_index": int(event.get("index", -1)),
                            "raw_crossing_order": int(event.get("crossing_order_on_traj", -1)),
                        }
                    )
    return crossings_by_key


def _projection_fallback_s(
    *,
    row: dict[str, Any],
    endpoint_role: str,
    xsec_line: LineString,
    selected_segments_by_arc: dict[str, Segment],
    production_segments_by_arc: dict[str, Segment],
) -> tuple[float | None, str]:
    del selected_segments_by_arc
    support_line = _support_corridor_line(row)
    if _line_is_usable(support_line):
        point = support_line.interpolate(0.0 if str(endpoint_role) == "src" else 1.0, normalized=True)
        value = _safe_line_project(xsec_line, point)
        if value is not None:
            return value, "support_projection_fallback"
    production_line = _production_line(row, production_segments_by_arc)
    if _line_is_usable(production_line):
        point = production_line.interpolate(0.0 if str(endpoint_role) == "src" else 1.0, normalized=True)
        value = _safe_line_project(xsec_line, point)
        if value is not None:
            return value, "production_projection_fallback"
    return None, "projection_missing"


def _raw_interval_from_crossings(
    *,
    row: dict[str, Any],
    endpoint_role: str,
    xsec_id: int,
    xsec_line: LineString,
    surface_intervals: list[Any],
    crossings: list[dict[str, Any]],
    group_rows: list[dict[str, Any]],
    selected_segments_by_arc: dict[str, Segment],
    production_segments_by_arc: dict[str, Segment],
    params: dict[str, Any],
) -> tuple[EndpointInterval, dict[str, Any]]:
    clean_crossings = [item for item in crossings if bool(item.get("clean", False))]
    used_crossings = clean_crossings or crossings
    if used_crossings:
        crossing_s_values = sorted(float(item.get("crossing_s", 0.0)) for item in used_crossings)
        traj_ids = tuple(sorted({str(item.get("traj_id", "")) for item in used_crossings if str(item.get("traj_id", ""))}))
        if len(traj_ids) <= 1:
            center_s = float(crossing_s_values[len(crossing_s_values) // 2])
            width_m = float(params.get("XSEC_ENDPOINT_SINGLE_TRAJ_WIDTH_M", 1.0))
            raw_start_s = float(center_s - width_m / 2.0)
            raw_end_s = float(center_s + width_m / 2.0)
        else:
            raw_start_s = float(min(crossing_s_values))
            raw_end_s = float(max(crossing_s_values))
            width_m = max(float(raw_end_s - raw_start_s), float(params.get("XSEC_ENDPOINT_SINGLE_TRAJ_WIDTH_M", 1.0)))
            center_s = float((raw_start_s + raw_end_s) / 2.0)
            if float(raw_end_s - raw_start_s) < 1e-6:
                raw_start_s = float(center_s - width_m / 2.0)
                raw_end_s = float(center_s + width_m / 2.0)
        clipped_start, clipped_end, clipped_center, clipped_line, clip_reason = _surface_clip_interval(
            raw_start_s=raw_start_s,
            raw_end_s=raw_end_s,
            raw_center_s=center_s,
            surface_intervals=surface_intervals,
            xsec_line=xsec_line,
        )
        interval = EndpointInterval(
            xsec_id=int(xsec_id),
            arc_id=str(row.get("topology_arc_id", "")),
            endpoint_role=str(endpoint_role),
            interval_start_s=float(clipped_start),
            interval_end_s=float(clipped_end),
            interval_center_s=float(clipped_center),
            width_m=float(max(width_m, clipped_end - clipped_start)),
            geometry_coords=line_to_coords(clipped_line),
            evidence_mode="clean_traj_crossing" if clean_crossings else "ambiguous_traj_crossing",
            traj_cross_count=int(len(used_crossings)),
            traj_ids=traj_ids,
            ownership_reason=str(Counter(str(item.get("ownership_reason", "")) for item in used_crossings).most_common(1)[0][0]),
            deconflict_reason="",
            fallback_reason="" if clean_crossings else "ambiguous_crossing_used",
            relative_order_satisfied=True,
        )
        return interval, {
            "surface_clip_reason": str(clip_reason),
            "used_clean_crossing": bool(clean_crossings),
            "used_crossing_count": int(len(used_crossings)),
        }

    projection_s, fallback_reason = _projection_fallback_s(
        row=row,
        endpoint_role=endpoint_role,
        xsec_line=xsec_line,
        selected_segments_by_arc=selected_segments_by_arc,
        production_segments_by_arc=production_segments_by_arc,
    )
    if projection_s is None and surface_intervals and len(group_rows) > 1:
        ordered = sorted(group_rows, key=_row_candidate_order)
        rank = int(ordered.index(row))
        carrier = max(surface_intervals, key=lambda item: float(item.length_m))
        fraction = float(rank + 1) / float(len(ordered) + 1)
        projection_s = float(carrier.start_s + fraction * max(0.0, float(carrier.end_s - carrier.start_s)))
        fallback_reason = "group_relative_order_fallback"
    if projection_s is not None:
        width_m = float(params.get("XSEC_ENDPOINT_SINGLE_TRAJ_WIDTH_M", 1.0))
        clipped_start, clipped_end, clipped_center, clipped_line, clip_reason = _surface_clip_interval(
            raw_start_s=float(projection_s - width_m / 2.0),
            raw_end_s=float(projection_s + width_m / 2.0),
            raw_center_s=float(projection_s),
            surface_intervals=surface_intervals,
            xsec_line=xsec_line,
        )
        interval = EndpointInterval(
            xsec_id=int(xsec_id),
            arc_id=str(row.get("topology_arc_id", "")),
            endpoint_role=str(endpoint_role),
            interval_start_s=float(clipped_start),
            interval_end_s=float(clipped_end),
            interval_center_s=float(clipped_center),
            width_m=float(max(width_m, clipped_end - clipped_start)),
            geometry_coords=line_to_coords(clipped_line),
            evidence_mode="fallback_projection",
            traj_cross_count=0,
            traj_ids=(),
            ownership_reason="fallback_projection",
            deconflict_reason="",
            fallback_reason=str(fallback_reason),
            relative_order_satisfied=True,
        )
        return interval, {
            "surface_clip_reason": str(clip_reason),
            "used_clean_crossing": False,
            "used_crossing_count": 0,
        }

    if surface_intervals:
        carrier = max(surface_intervals, key=lambda item: float(item.length_m))
        interval = EndpointInterval(
            xsec_id=int(xsec_id),
            arc_id=str(row.get("topology_arc_id", "")),
            endpoint_role=str(endpoint_role),
            interval_start_s=float(carrier.start_s),
            interval_end_s=float(carrier.end_s),
            interval_center_s=float(carrier.center_s),
            width_m=float(carrier.length_m),
            geometry_coords=carrier.geometry_coords,
            evidence_mode="surface_legal_interval",
            traj_cross_count=0,
            traj_ids=(),
            ownership_reason="surface_legal_interval",
            deconflict_reason="",
            fallback_reason="surface_legal_interval_fallback",
            relative_order_satisfied=True,
        )
        return interval, {
            "surface_clip_reason": "surface_interval_direct",
            "used_clean_crossing": False,
            "used_crossing_count": 0,
        }

    point0 = xsec_line.interpolate(0.0)
    point1 = xsec_line.interpolate(min(float(xsec_line.length), 1.0))
    interval = EndpointInterval(
        xsec_id=int(xsec_id),
        arc_id=str(row.get("topology_arc_id", "")),
        endpoint_role=str(endpoint_role),
        interval_start_s=0.0,
        interval_end_s=min(float(xsec_line.length), 1.0),
        interval_center_s=min(float(xsec_line.length), 0.5),
        width_m=min(float(xsec_line.length), 1.0),
        geometry_coords=((float(point0.x), float(point0.y)), (float(point1.x), float(point1.y))),
        evidence_mode="xsec_fallback_interval",
        traj_cross_count=0,
        traj_ids=(),
        ownership_reason="xsec_fallback_interval",
        deconflict_reason="",
        fallback_reason="xsec_fallback_interval",
        relative_order_satisfied=True,
    )
    return interval, {
        "surface_clip_reason": "xsec_fallback_interval",
        "used_clean_crossing": False,
        "used_crossing_count": 0,
    }


def _build_role_intervals(
    *,
    rows: list[dict[str, Any]],
    xsec_map: dict[int, BaseCrossSection],
    selected_segments_by_arc: dict[str, Segment],
    production_segments_by_arc: dict[str, Segment] | None,
    drivable_surface: Any | None,
    params: dict[str, Any],
    endpoint_role: str,
    crossings_by_key: dict[str, list[dict[str, Any]]],
) -> dict[int, list[dict[str, Any]]]:
    production_segments_by_arc = dict(production_segments_by_arc or {})
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        xsec_id = int(row.get("src" if endpoint_role == "src" else "dst", 0) or 0)
        if xsec_id in xsec_map:
            groups[xsec_id].append(row)
    out: dict[int, list[dict[str, Any]]] = {}
    for xsec_id, group_rows in groups.items():
        xsec_line = xsec_map[int(xsec_id)].geometry_metric()
        surface_intervals = _surface_intervals(
            xsec_line=xsec_line,
            drivable_surface=drivable_surface,
            params=params,
        )
        raw_rows: list[dict[str, Any]] = []
        for row in group_rows:
            raw_interval, meta = _raw_interval_from_crossings(
                row=row,
                endpoint_role=endpoint_role,
                xsec_id=int(xsec_id),
                xsec_line=xsec_line,
                surface_intervals=surface_intervals,
                crossings=list(crossings_by_key.get(f"{row.get('topology_arc_id', '')}:{endpoint_role}", [])),
                group_rows=group_rows,
                selected_segments_by_arc=selected_segments_by_arc,
                production_segments_by_arc=production_segments_by_arc,
                params=params,
            )
            raw_rows.append(
                {
                    "row": row,
                    "raw_interval": raw_interval,
                    "surface_intervals": surface_intervals,
                    "meta": meta,
                }
            )
        out[int(xsec_id)] = raw_rows
    return out


def build_src_intervals(
    *,
    rows: list[dict[str, Any]],
    traj_rows: list[dict[str, Any]],
    xsec_map: dict[int, BaseCrossSection],
    selected_segments_by_arc: dict[str, Segment],
    drivable_surface: Any | None,
    params: dict[str, Any],
    production_segments_by_arc: dict[str, Segment] | None = None,
    crossings_by_key: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    del traj_rows
    return _build_role_intervals(
        rows=rows,
        xsec_map=xsec_map,
        selected_segments_by_arc=selected_segments_by_arc,
        production_segments_by_arc=production_segments_by_arc,
        drivable_surface=drivable_surface,
        params=params,
        endpoint_role="src",
        crossings_by_key=crossings_by_key or {},
    )


def build_dst_intervals(
    *,
    rows: list[dict[str, Any]],
    traj_rows: list[dict[str, Any]],
    xsec_map: dict[int, BaseCrossSection],
    selected_segments_by_arc: dict[str, Segment],
    drivable_surface: Any | None,
    params: dict[str, Any],
    production_segments_by_arc: dict[str, Segment] | None = None,
    crossings_by_key: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    del traj_rows
    return _build_role_intervals(
        rows=rows,
        xsec_map=xsec_map,
        selected_segments_by_arc=selected_segments_by_arc,
        production_segments_by_arc=production_segments_by_arc,
        drivable_surface=drivable_surface,
        params=params,
        endpoint_role="dst",
        crossings_by_key=crossings_by_key or {},
    )


def _allocate_group_intervals(
    *,
    raw_intervals: list[EndpointInterval],
    xsec_line: LineString,
    endpoint_role: str,
    params: dict[str, Any],
) -> tuple[list[EndpointInterval], list[tuple[LineString, dict[str, Any]]]]:
    if not raw_intervals:
        return [], []
    allocator_gap_m = float(params.get("XSEC_ENDPOINT_ALLOCATOR_GAP_M", 0.1))
    ordered = sorted(raw_intervals, key=lambda item: (float(item.interval_center_s), str(item.arc_id)))
    centers = [float(item.interval_center_s) for item in ordered]
    for idx in range(1, len(centers)):
        centers[idx] = max(float(centers[idx]), float(centers[idx - 1] + allocator_gap_m))
    if centers and centers[-1] > float(xsec_line.length):
        overflow = float(centers[-1] - xsec_line.length)
        centers = [max(0.0, float(value - overflow)) for value in centers]
    assigned: list[EndpointInterval] = []
    features: list[tuple[LineString, dict[str, Any]]] = []
    for idx, raw in enumerate(ordered):
        center = float(min(max(centers[idx], raw.interval_start_s), raw.interval_end_s))
        left_boundary = float(raw.interval_start_s)
        right_boundary = float(raw.interval_end_s)
        if idx > 0:
            left_boundary = max(left_boundary, float((centers[idx - 1] + center) / 2.0 + allocator_gap_m / 2.0))
        if idx < len(ordered) - 1:
            right_boundary = min(right_boundary, float((center + centers[idx + 1]) / 2.0 - allocator_gap_m / 2.0))
        if right_boundary < left_boundary:
            left_boundary = center
            right_boundary = center
        start_s = float(max(raw.interval_start_s, min(left_boundary, right_boundary)))
        end_s = float(min(raw.interval_end_s, max(left_boundary, right_boundary)))
        if end_s <= start_s + 1e-6:
            half = min(0.25, max(0.01, float(raw.width_m) / 4.0))
            start_s = max(float(raw.interval_start_s), float(center - half))
            end_s = min(float(raw.interval_end_s), float(center + half))
        clipped = substring(xsec_line, start_s, end_s)
        clipped_line = clipped if isinstance(clipped, LineString) and not clipped.is_empty else _line_from_coords(
            [
                [float(xsec_line.interpolate(start_s).x), float(xsec_line.interpolate(start_s).y)],
                [float(xsec_line.interpolate(end_s).x), float(xsec_line.interpolate(end_s).y)],
            ]
        )
        relative_ok = not (idx > 0 and float(start_s) < float(assigned[-1].interval_end_s) - 1e-6)
        assigned_interval = EndpointInterval(
            xsec_id=int(raw.xsec_id),
            arc_id=str(raw.arc_id),
            endpoint_role=str(endpoint_role),
            interval_start_s=float(start_s),
            interval_end_s=float(end_s),
            interval_center_s=float((start_s + end_s) / 2.0),
            width_m=float(max(0.0, end_s - start_s)),
            geometry_coords=line_to_coords(clipped_line),
            evidence_mode=str(raw.evidence_mode),
            traj_cross_count=int(raw.traj_cross_count),
            traj_ids=tuple(str(v) for v in raw.traj_ids),
            ownership_reason=str(raw.ownership_reason),
            deconflict_reason="allocator_preserved_order" if relative_ok else "allocator_overlap_shrunk",
            fallback_reason=str(raw.fallback_reason),
            relative_order_satisfied=bool(relative_ok),
        )
        assigned.append(assigned_interval)
        features.append(
            (
                assigned_interval.geometry_metric(),
                {
                    "xsec_id": int(assigned_interval.xsec_id),
                    "arc_id": str(assigned_interval.arc_id),
                    "endpoint_role": str(endpoint_role),
                    "evidence_mode": str(assigned_interval.evidence_mode),
                    "deconflict_reason": str(assigned_interval.deconflict_reason),
                    "relative_order_satisfied": bool(assigned_interval.relative_order_satisfied),
                },
            )
        )
    return assigned, features


def _allocate_role_intervals(
    *,
    raw_intervals_by_xsec: dict[int, list[dict[str, Any]]],
    xsec_map: dict[int, BaseCrossSection],
    endpoint_role: str,
    params: dict[str, Any],
) -> tuple[dict[int, list[EndpointInterval]], list[tuple[LineString, dict[str, Any]]]]:
    out: dict[int, list[EndpointInterval]] = {}
    features: list[tuple[LineString, dict[str, Any]]] = []
    for xsec_id, raw_rows in raw_intervals_by_xsec.items():
        xsec = xsec_map.get(int(xsec_id))
        if xsec is None:
            continue
        assigned, allocator_features = _allocate_group_intervals(
            raw_intervals=[item["raw_interval"] for item in raw_rows],
            xsec_line=xsec.geometry_metric(),
            endpoint_role=endpoint_role,
            params=params,
        )
        out[int(xsec_id)] = assigned
        features.extend(allocator_features)
    return out, features


def allocate_start_intervals(
    *,
    raw_intervals_by_xsec: dict[int, list[dict[str, Any]]],
    xsec_map: dict[int, BaseCrossSection],
    params: dict[str, Any],
) -> tuple[dict[int, list[EndpointInterval]], list[tuple[LineString, dict[str, Any]]]]:
    return _allocate_role_intervals(
        raw_intervals_by_xsec=raw_intervals_by_xsec,
        xsec_map=xsec_map,
        endpoint_role="src",
        params=params,
    )


def allocate_end_intervals(
    *,
    raw_intervals_by_xsec: dict[int, list[dict[str, Any]]],
    xsec_map: dict[int, BaseCrossSection],
    params: dict[str, Any],
) -> tuple[dict[int, list[EndpointInterval]], list[tuple[LineString, dict[str, Any]]]]:
    return _allocate_role_intervals(
        raw_intervals_by_xsec=raw_intervals_by_xsec,
        xsec_map=xsec_map,
        endpoint_role="dst",
        params=params,
    )


def build_endpoint_intervals(
    *,
    rows: list[dict[str, Any]],
    traj_rows: list[dict[str, Any]],
    xsec_map: dict[int, BaseCrossSection],
    selected_segments_by_arc: dict[str, Segment],
    drivable_surface: Any | None,
    params: dict[str, Any],
    production_segments_by_arc: dict[str, Segment] | None = None,
) -> dict[str, Any]:
    crossings_by_key = collect_xsec_crossings(
        rows=rows,
        traj_rows=traj_rows,
        xsec_map=xsec_map,
        selected_segments_by_arc=selected_segments_by_arc,
        production_segments_by_arc=production_segments_by_arc,
        params=params,
    )
    src_raw = build_src_intervals(
        rows=rows,
        traj_rows=traj_rows,
        xsec_map=xsec_map,
        selected_segments_by_arc=selected_segments_by_arc,
        production_segments_by_arc=production_segments_by_arc,
        drivable_surface=drivable_surface,
        params=params,
        crossings_by_key=crossings_by_key,
    )
    dst_raw = build_dst_intervals(
        rows=rows,
        traj_rows=traj_rows,
        xsec_map=xsec_map,
        selected_segments_by_arc=selected_segments_by_arc,
        production_segments_by_arc=production_segments_by_arc,
        drivable_surface=drivable_surface,
        params=params,
        crossings_by_key=crossings_by_key,
    )
    src_assigned, allocator_start_features = allocate_start_intervals(
        raw_intervals_by_xsec=src_raw,
        xsec_map=xsec_map,
        params=params,
    )
    dst_assigned, allocator_end_features = allocate_end_intervals(
        raw_intervals_by_xsec=dst_raw,
        xsec_map=xsec_map,
        params=params,
    )

    surface_features: list[tuple[LineString, dict[str, Any]]] = []
    raw_features: list[tuple[LineString, dict[str, Any]]] = []
    assigned_features: list[tuple[LineString, dict[str, Any]]] = []
    crossing_features: list[tuple[Point, dict[str, Any]]] = []
    review_rows: list[dict[str, Any]] = []

    for endpoint_role, raw_map, assigned_map in (
        ("src", src_raw, src_assigned),
        ("dst", dst_raw, dst_assigned),
    ):
        for xsec_id, raw_rows in raw_map.items():
            for item in raw_rows:
                for surface_interval in item["surface_intervals"]:
                    surface_features.append(
                        (
                            surface_interval.geometry_metric(),
                            {
                                "xsec_id": int(xsec_id),
                                "endpoint_role": str(endpoint_role),
                                "role": "surface_legal_interval",
                                "interval_rank": int(surface_interval.rank),
                            },
                        )
                    )
                raw_interval: EndpointInterval = item["raw_interval"]
                raw_features.append(
                    (
                        raw_interval.geometry_metric(),
                        {
                            "xsec_id": int(raw_interval.xsec_id),
                            "arc_id": str(raw_interval.arc_id),
                            "endpoint_role": str(raw_interval.endpoint_role),
                            "evidence_mode": str(raw_interval.evidence_mode),
                            "traj_cross_count": int(raw_interval.traj_cross_count),
                            "ownership_reason": str(raw_interval.ownership_reason),
                            "fallback_reason": str(raw_interval.fallback_reason),
                        },
                    )
                )
            assigned_by_arc = {str(item.arc_id): item for item in assigned_map.get(int(xsec_id), [])}
            for item in raw_rows:
                row = item["row"]
                raw_interval = item["raw_interval"]
                assigned_interval = assigned_by_arc.get(str(raw_interval.arc_id), raw_interval)
                assigned_features.append(
                    (
                        assigned_interval.geometry_metric(),
                        {
                            "xsec_id": int(assigned_interval.xsec_id),
                            "arc_id": str(assigned_interval.arc_id),
                            "endpoint_role": str(assigned_interval.endpoint_role),
                            "evidence_mode": str(assigned_interval.evidence_mode),
                            "traj_cross_count": int(assigned_interval.traj_cross_count),
                            "ownership_reason": str(assigned_interval.ownership_reason),
                            "deconflict_reason": str(assigned_interval.deconflict_reason),
                            "fallback_reason": str(assigned_interval.fallback_reason),
                            "relative_order_satisfied": bool(assigned_interval.relative_order_satisfied),
                        },
                    )
                )
                key = f"{row.get('topology_arc_id', '')}:{endpoint_role}"
                for crossing in list(crossings_by_key.get(key, [])):
                    crossing_point = crossing.get("point")
                    if isinstance(crossing_point, Point) and not crossing_point.is_empty:
                        crossing_features.append(
                            (
                                crossing_point,
                                {
                                    "xsec_id": int(xsec_id),
                                    "arc_id": str(row.get("topology_arc_id", "")),
                                    "endpoint_role": str(endpoint_role),
                                    "traj_id": str(crossing.get("traj_id", "")),
                                    "crossing_s": float(crossing.get("crossing_s", 0.0)),
                                    "clean": bool(crossing.get("clean", False)),
                                    "ownership_reason": str(crossing.get("ownership_reason", "")),
                                },
                            )
                        )
                review_rows.append(
                    {
                        "pair": str(row.get("pair", "")),
                        "topology_arc_id": str(row.get("topology_arc_id", "")),
                        "xsec_id": int(xsec_id),
                        "endpoint_role": str(endpoint_role),
                        "assigned_interval": assigned_interval.to_dict(),
                        "raw_interval": raw_interval.to_dict(),
                        "traj_cross_count": int(assigned_interval.traj_cross_count),
                        "traj_ids": [str(v) for v in assigned_interval.traj_ids],
                        "ownership_reason": str(assigned_interval.ownership_reason),
                        "deconflict_reason": str(assigned_interval.deconflict_reason),
                        "fallback_reason": str(assigned_interval.fallback_reason),
                        "relative_order_satisfied": bool(assigned_interval.relative_order_satisfied),
                        "used_clean_crossing": bool(item["meta"].get("used_clean_crossing", False)),
                        "surface_clip_reason": str(item["meta"].get("surface_clip_reason", "")),
                    }
                )

    assigned_by_arc_role: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for intervals in list(src_assigned.values()) + list(dst_assigned.values()):
        for interval in intervals:
            assigned_by_arc_role[str(interval.arc_id)][str(interval.endpoint_role)] = interval.to_dict()

    return {
        "assigned_intervals_by_arc": {str(key): dict(value) for key, value in assigned_by_arc_role.items()},
        "review_rows": review_rows,
        "surface_features": surface_features,
        "crossing_features": crossing_features,
        "raw_interval_features": raw_features,
        "assigned_interval_features": assigned_features,
        "allocator_features": [*allocator_start_features, *allocator_end_features],
    }


__all__ = [
    "collect_xsec_crossings",
    "build_src_intervals",
    "build_dst_intervals",
    "allocate_start_intervals",
    "allocate_end_intervals",
    "build_endpoint_intervals",
]
