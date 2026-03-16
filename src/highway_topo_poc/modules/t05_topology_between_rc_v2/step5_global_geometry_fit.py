from __future__ import annotations

from math import atan2, hypot, isfinite, pi
from statistics import median
from typing import Any

from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, substring

from .models import Segment, line_to_coords


def _line_from_coords(
    coords: list[list[float]] | tuple[tuple[float, float], ...] | list[tuple[float, float]] | tuple[Any, ...],
) -> LineString | None:
    pts: list[tuple[float, float]] = []
    for item in coords or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        x = float(item[0])
        y = float(item[1])
        if not (isfinite(x) and isfinite(y)):
            continue
        xy = (x, y)
        if not pts or xy != pts[-1]:
            pts.append(xy)
    if len(pts) < 2:
        return None
    line = LineString(pts)
    if line.is_empty or float(line.length) <= 1e-6:
        return None
    return line


def _line_is_usable(line: Any) -> bool:
    return isinstance(line, LineString) and (not line.is_empty) and isfinite(float(line.length)) and float(line.length) > 1e-6


def _safe_line_interpolate(line: LineString, distance: float, *, normalized: bool = False) -> Point | None:
    try:
        point = line.interpolate(float(distance), normalized=bool(normalized))
    except Exception:
        return None
    return point if isinstance(point, Point) and not point.is_empty else None


def _safe_nearest_points(geometry_a: Any, geometry_b: Any) -> tuple[Point, Point] | None:
    try:
        point_a, point_b = nearest_points(geometry_a, geometry_b)
    except Exception:
        return None
    if not isinstance(point_a, Point) or not isinstance(point_b, Point):
        return None
    if point_a.is_empty or point_b.is_empty:
        return None
    return point_a, point_b


def _point_to_coords(point: Point | None) -> list[float] | None:
    if not isinstance(point, Point) or point.is_empty:
        return None
    return [float(point.x), float(point.y)]


def _replace_endpoints(line: LineString | None, start_pt: Point, end_pt: Point) -> LineString | None:
    if not _line_is_usable(line):
        return None
    coords = list(line.coords)
    middle: list[tuple[float, float]] = []
    for coord in coords[1:-1]:
        xy = (float(coord[0]), float(coord[1]))
        if not middle or xy != middle[-1]:
            middle.append(xy)
    return _line_from_coords([(float(start_pt.x), float(start_pt.y)), *middle, (float(end_pt.x), float(end_pt.y))])


def _direction_unit(line: LineString, *, at_start: bool) -> tuple[float, float] | None:
    if not _line_is_usable(line):
        return None
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    if at_start:
        origin = coords[0]
        neighbor = next(
            (
                coord
                for coord in coords[1:]
                if (float(coord[0]), float(coord[1])) != (float(origin[0]), float(origin[1]))
            ),
            None,
        )
        if neighbor is None:
            return None
        dx = float(neighbor[0]) - float(origin[0])
        dy = float(neighbor[1]) - float(origin[1])
    else:
        origin = coords[-1]
        neighbor = next(
            (
                coord
                for coord in reversed(coords[:-1])
                if (float(coord[0]), float(coord[1])) != (float(origin[0]), float(origin[1]))
            ),
            None,
        )
        if neighbor is None:
            return None
        dx = float(origin[0]) - float(neighbor[0])
        dy = float(origin[1]) - float(neighbor[1])
    norm = hypot(float(dx), float(dy))
    if norm <= 1e-6:
        return None
    return float(dx / norm), float(dy / norm)


def _sample_direction(line: LineString, station_norm: float) -> tuple[float, float] | None:
    if not _line_is_usable(line):
        return None
    t = max(0.0, min(1.0, float(station_norm)))
    delta = 0.02 if float(line.length) > 5.0 else 0.08
    p0 = _safe_line_interpolate(line, max(0.0, t - delta), normalized=True)
    p1 = _safe_line_interpolate(line, min(1.0, t + delta), normalized=True)
    if p0 is None or p1 is None:
        return _direction_unit(line, at_start=(t <= 0.5))
    dx = float(p1.x) - float(p0.x)
    dy = float(p1.y) - float(p0.y)
    norm = hypot(float(dx), float(dy))
    if norm <= 1e-6:
        return None
    return float(dx / norm), float(dy / norm)


def _orient_line_between_points(line: LineString, start_pt: Point, end_pt: Point) -> LineString:
    coords = list(line.coords)
    if len(coords) < 2:
        return line
    head = Point(coords[0][:2])
    tail = Point(coords[-1][:2])
    forward = float(head.distance(start_pt) + tail.distance(end_pt))
    reverse = float(head.distance(end_pt) + tail.distance(start_pt))
    if reverse + 1e-6 < forward:
        return LineString(list(reversed(coords)))
    return line


def _anchor_along_guide_line(line: LineString, start_pt: Point, end_pt: Point) -> LineString:
    oriented = _orient_line_between_points(line, start_pt, end_pt)
    if not _line_is_usable(oriented):
        return LineString([(float(start_pt.x), float(start_pt.y)), (float(end_pt.x), float(end_pt.y))])
    try:
        start_s = float(oriented.project(start_pt))
        end_s = float(oriented.project(end_pt))
    except Exception:
        return _replace_endpoints(oriented, start_pt, end_pt) or oriented
    if end_s > start_s + 1e-6:
        try:
            middle = substring(oriented, start_s, end_s)
        except Exception:
            middle = oriented
        if isinstance(middle, LineString) and not middle.is_empty and float(middle.length) > 1e-6:
            anchored = _replace_endpoints(middle, start_pt, end_pt)
            if anchored is not None:
                return anchored
    anchored = _replace_endpoints(oriented, start_pt, end_pt)
    return anchored if anchored is not None else oriented


def _line_overlap_ratio(line: LineString, zone: Any | None) -> float:
    if not _line_is_usable(line) or zone is None or getattr(zone, "is_empty", True):
        return 0.0
    try:
        overlap = line.intersection(zone)
    except Exception:
        return 0.0
    overlap_length = 0.0
    if isinstance(overlap, LineString):
        overlap_length = float(overlap.length)
    elif hasattr(overlap, "geoms"):
        overlap_length = float(
            sum(float(geom.length) for geom in overlap.geoms if isinstance(geom, LineString) and not geom.is_empty)
        )
    if float(line.length) <= 1e-6:
        return 0.0
    return max(0.0, min(1.0, float(overlap_length) / float(line.length)))


def _mean_turn_angle_deg(line: LineString) -> float:
    if not _line_is_usable(line):
        return 180.0
    coords = list(line.coords)
    if len(coords) < 3:
        return 0.0
    angles: list[float] = []
    for idx in range(1, len(coords) - 1):
        ax = float(coords[idx][0]) - float(coords[idx - 1][0])
        ay = float(coords[idx][1]) - float(coords[idx - 1][1])
        bx = float(coords[idx + 1][0]) - float(coords[idx][0])
        by = float(coords[idx + 1][1]) - float(coords[idx][1])
        norm_a = hypot(float(ax), float(ay))
        norm_b = hypot(float(bx), float(by))
        if norm_a <= 1e-6 or norm_b <= 1e-6:
            continue
        cross = float(ax) * float(by) - float(ay) * float(bx)
        dot = float(ax) * float(bx) + float(ay) * float(by)
        angles.append(abs(float(atan2(cross, dot))) * 180.0 / pi)
    return float(sum(angles) / max(len(angles), 1)) if angles else 0.0


def _choose_guide_line(
    *,
    segment: Segment,
    arc_row: dict[str, Any] | None,
    witness_line: LineString | None,
    fallback_line: LineString | None,
    start_anchor: Point,
    end_anchor: Point,
) -> tuple[LineString, str]:
    candidates: list[tuple[LineString | None, str]] = [
        (_line_from_coords(list((arc_row or {}).get("support_reference_coords", []))), "selected_support_reference"),
        (_line_from_coords(list((arc_row or {}).get("stitched_support_reference_coords", []))), "stitched_support_reference"),
        (_line_from_coords(list((arc_row or {}).get("line_coords", []))), "topology_arc_line"),
        (fallback_line, "shape_ref_fallback"),
        (witness_line, "corridor_witness_line"),
        (segment.geometry_metric(), "production_working_segment"),
    ]
    for line, label in candidates:
        if _line_is_usable(line):
            return _anchor_along_guide_line(line, start_anchor, end_anchor), str(label)
    return (
        LineString([(float(start_anchor.x), float(start_anchor.y)), (float(end_anchor.x), float(end_anchor.y))]),
        "anchor_chord",
    )


def _support_segment_candidates(
    *,
    segment: Segment,
    arc_row: dict[str, Any] | None,
    guide_line: LineString,
    start_anchor: Point,
    end_anchor: Point,
    safe_surface: Any | None,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    guide_buffer_m = float(params.get("GLOBAL_FIT_GUIDE_BUFFER_M", 18.0))
    min_overlap_ratio = float(params.get("GLOBAL_FIT_MIN_TRAJ_OVERLAP_RATIO", 0.28))
    guide_zone = guide_line.buffer(max(guide_buffer_m, 1.0), cap_style=2, join_style=2) if _line_is_usable(guide_line) else None
    raw_rows: list[dict[str, Any]] = []
    for source_key, support_family in (
        ("single_traj_support_segments", "single"),
        ("stitched_traj_support_segments", "stitched"),
        ("traj_support_segments", "aggregate"),
    ):
        for raw in list((arc_row or {}).get(source_key, []) or []):
            current = dict(raw)
            current["_support_family"] = str(support_family)
            raw_rows.append(current)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_rows:
        source_id = str(raw.get("source_traj_id") or raw.get("traj_id") or "")
        if not source_id:
            continue
        grouped.setdefault(source_id, []).append(raw)

    selected_support_id = str((arc_row or {}).get("selected_support_segment_traj_id") or (arc_row or {}).get("selected_support_traj_id") or "")
    support_ids = {str(v) for v in getattr(segment, "support_traj_ids", ()) if str(v)}
    if selected_support_id:
        support_ids.add(str(selected_support_id))

    rows: list[dict[str, Any]] = []
    for source_id, items in grouped.items():
        best: dict[str, Any] | None = None
        best_rank: tuple[Any, ...] | None = None
        for raw in items:
            line = _line_from_coords(list(raw.get("line_coords", [])))
            if not _line_is_usable(line):
                continue
            line = _orient_line_between_points(line, start_anchor, end_anchor)
            overlap_ratio = _line_overlap_ratio(line, guide_zone) if guide_zone is not None else 1.0
            anchor_count = int(bool(raw.get("supports_src_xsec_anchor", False))) + int(bool(raw.get("supports_dst_xsec_anchor", False)))
            surface_consistent = bool(raw.get("surface_consistent", False))
            is_terminal = str(raw.get("support_type", "")) == "terminal_crossing_support"
            is_stitched = bool(raw.get("is_stitched", False)) or str(raw.get("_support_family")) == "stitched"
            rank = (
                -int(surface_consistent),
                -anchor_count,
                -int(is_terminal),
                int(is_stitched),
                -float(raw.get("support_score", 0.0) or 0.0),
                -float(line.length),
                -float(overlap_ratio),
            )
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best = {
                    "source_traj_id": str(source_id),
                    "traj_id": str(raw.get("traj_id") or source_id),
                    "support_type": str(raw.get("support_type", "")),
                    "support_mode": str(raw.get("support_mode", "")),
                    "support_family": str(raw.get("_support_family", "")),
                    "support_score": float(raw.get("support_score", 0.0) or 0.0),
                    "support_length_m": float(line.length),
                    "surface_consistent": bool(surface_consistent),
                    "surface_reject_reason": str(raw.get("surface_reject_reason", "")),
                    "supports_src_xsec_anchor": bool(raw.get("supports_src_xsec_anchor", False)),
                    "supports_dst_xsec_anchor": bool(raw.get("supports_dst_xsec_anchor", False)),
                    "endpoint_anchor_count": int(anchor_count),
                    "is_stitched": bool(is_stitched),
                    "is_selected_support": bool(str(raw.get("traj_id") or "") == selected_support_id or source_id == selected_support_id),
                    "is_support_family": bool(source_id in support_ids or str(raw.get("traj_id") or "") in support_ids),
                    "guide_overlap_ratio": float(overlap_ratio),
                    "line": line,
                    "start_anchor_coords": raw.get("start_anchor_coords"),
                    "end_anchor_coords": raw.get("end_anchor_coords"),
                }
        if best is None:
            continue
        include = False
        reason = ""
        score = float(best["guide_overlap_ratio"])
        if not bool(best["surface_consistent"]):
            reason = str(best["surface_reject_reason"] or "surface_inconsistent")
        elif int(best["endpoint_anchor_count"]) >= 2 and str(best["support_type"]) == "terminal_crossing_support":
            include = True
            reason = "clean_endpoint_identity"
            score += 4.0
        elif int(best["endpoint_anchor_count"]) >= 2 and not bool(best["is_stitched"]):
            include = True
            reason = "clean_support_full_crossing"
            score += 3.0
        elif bool(best["is_support_family"]) and not bool(best["is_stitched"]) and float(best["guide_overlap_ratio"]) >= min_overlap_ratio:
            include = True
            reason = "clean_support_family"
            score += 2.0
        elif bool(best["is_selected_support"]) and float(best["guide_overlap_ratio"]) >= min_overlap_ratio * 0.8:
            include = True
            reason = "selected_support_family"
            score += 1.5
        elif bool(best["is_stitched"]) and float(best["guide_overlap_ratio"]) >= min_overlap_ratio:
            include = True
            reason = "stitched_partial_support"
            score += 0.9
        elif float(best["guide_overlap_ratio"]) < min_overlap_ratio:
            reason = "guide_overlap_low"
        else:
            reason = "weak_partial_support"
        if include and safe_surface is not None and not getattr(safe_surface, "is_empty", True):
            if _line_overlap_ratio(best["line"], safe_surface) < 0.60:
                include = False
                reason = "outside_safe_surface"
        best["included_bool"] = bool(include)
        best["selection_reason"] = str(reason)
        best["selection_weight"] = max(0.15, float(score))
        rows.append(best)
    seen_sources = {str(row["source_traj_id"]) for row in rows}
    for missing_id in sorted(support_ids - seen_sources):
        rows.append(
            {
                "source_traj_id": str(missing_id),
                "traj_id": str(missing_id),
                "support_type": "",
                "support_mode": "",
                "support_family": "missing",
                "support_score": 0.0,
                "support_length_m": 0.0,
                "surface_consistent": False,
                "surface_reject_reason": "support_id_missing_support_segment",
                "supports_src_xsec_anchor": False,
                "supports_dst_xsec_anchor": False,
                "endpoint_anchor_count": 0,
                "is_stitched": False,
                "is_selected_support": bool(str(missing_id) == selected_support_id),
                "is_support_family": True,
                "guide_overlap_ratio": 0.0,
                "line": None,
                "included_bool": False,
                "selection_reason": "support_id_missing_support_segment",
                "selection_weight": 0.0,
                "start_anchor_coords": None,
                "end_anchor_coords": None,
            }
        )
    rows.sort(
        key=lambda item: (
            -int(item.get("included_bool", False)),
            -float(item.get("selection_weight", 0.0)),
            str(item.get("source_traj_id", "")),
        )
    )
    return rows


def select_trajectory_evidence(
    *,
    segment: Segment,
    arc_row: dict[str, Any] | None,
    witness_line: LineString | None,
    fallback_line: LineString | None,
    start_anchor: Point,
    end_anchor: Point,
    safe_surface: Any | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    guide_line, guide_source = _choose_guide_line(
        segment=segment,
        arc_row=arc_row,
        witness_line=witness_line,
        fallback_line=fallback_line,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
    )
    selection_rows = _support_segment_candidates(
        segment=segment,
        arc_row=arc_row,
        guide_line=guide_line,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        safe_surface=safe_surface,
        params=params,
    )
    selected_rows = [row for row in selection_rows if bool(row.get("included_bool", False)) and _line_is_usable(row.get("line"))]
    selected_rows.sort(
        key=lambda item: (
            -float(item.get("selection_weight", 0.0)),
            -int(item.get("endpoint_anchor_count", 0)),
            -float(item.get("support_length_m", 0.0)),
            str(item.get("source_traj_id", "")),
        )
    )
    return {
        "guide_line": guide_line,
        "guide_source": str(guide_source),
        "selection_rows": selection_rows,
        "selected_rows": selected_rows,
    }


def _robust_center_from_samples(samples: list[dict[str, Any]]) -> tuple[Point | None, float, float]:
    if not samples:
        return None, 0.0, 0.0
    total_weight = sum(max(float(item.get("weight", 0.0)), 1e-6) for item in samples)
    if total_weight <= 1e-6:
        return None, 0.0, 0.0
    x = sum(float(item["point"].x) * max(float(item.get("weight", 0.0)), 1e-6) for item in samples) / total_weight
    y = sum(float(item["point"].y) * max(float(item.get("weight", 0.0)), 1e-6) for item in samples) / total_weight
    for _ in range(2):
        center = Point(float(x), float(y))
        distances = [float(item["point"].distance(center)) for item in samples]
        scale = median(distances) if distances else 0.0
        scale = max(float(scale), 1.0)
        adjusted_weights: list[float] = []
        for item, distance in zip(samples, distances):
            base_weight = max(float(item.get("weight", 0.0)), 1e-6)
            adjusted_weights.append(float(base_weight) / max(1.0, float(distance) / float(scale)))
        total = sum(adjusted_weights)
        if total <= 1e-6:
            break
        x = sum(float(item["point"].x) * weight for item, weight in zip(samples, adjusted_weights)) / total
        y = sum(float(item["point"].y) * weight for item, weight in zip(samples, adjusted_weights)) / total
    center = Point(float(x), float(y))
    distances = [float(item["point"].distance(center)) for item in samples]
    dispersion = float(median(distances)) if distances else 0.0
    confidence = max(
        0.0,
        min(
            1.0,
            min(1.0, float(len(samples)) / 3.0) * max(0.05, 1.0 - float(dispersion) / 10.0),
        ),
    )
    return center, float(dispersion), float(confidence)


def aggregate_trajectory_stations(
    *,
    guide_line: LineString,
    selected_rows: list[dict[str, Any]],
    start_anchor: Point,
    end_anchor: Point,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    if not _line_is_usable(guide_line):
        return []
    step_m = max(4.0, float(params.get("GLOBAL_FIT_STATION_STEP_M", 6.0)))
    min_count = max(5, int(params.get("GLOBAL_FIT_MIN_STATION_COUNT", 9)))
    max_count = max(min_count, int(params.get("GLOBAL_FIT_MAX_STATION_COUNT", 55)))
    station_count = max(min_count, min(max_count, int(float(guide_line.length) / step_m) + 1))
    if station_count < 2:
        station_count = 2
    sample_search_m = max(step_m * 1.75, float(params.get("GLOBAL_FIT_TRAJ_SAMPLE_SEARCH_M", 14.0)))
    rows: list[dict[str, Any]] = []
    for idx in range(station_count):
        station_norm = 0.0 if station_count == 1 else float(idx) / float(station_count - 1)
        guide_point = _safe_line_interpolate(guide_line, station_norm, normalized=True)
        if guide_point is None:
            continue
        tangent = _sample_direction(guide_line, station_norm)
        samples: list[dict[str, Any]] = []
        for selected in selected_rows:
            line = selected.get("line")
            if not _line_is_usable(line):
                continue
            nearest = _safe_nearest_points(line, guide_point)
            if nearest is None:
                continue
            evidence_point = nearest[0]
            guide_distance = float(evidence_point.distance(guide_point))
            if guide_distance > sample_search_m:
                continue
            samples.append(
                {
                    "source_traj_id": str(selected.get("source_traj_id", "")),
                    "point": evidence_point,
                    "distance_to_guide_m": float(guide_distance),
                    "weight": max(
                        0.15,
                        float(selected.get("selection_weight", 0.0))
                        * max(0.2, 1.0 - float(guide_distance) / float(sample_search_m)),
                    ),
                }
            )
        robust_center, dispersion_m, confidence = _robust_center_from_samples(samples)
        rows.append(
            {
                "station_index": int(idx),
                "station_norm": float(station_norm),
                "station_distance_m": float(station_norm * float(guide_line.length)),
                "guide_coords": _point_to_coords(guide_point),
                "tangent": None if tangent is None else [float(tangent[0]), float(tangent[1])],
                "sample_count": int(len(samples)),
                "sample_source_ids": [str(item["source_traj_id"]) for item in samples],
                "trajectory_robust_center_coords": _point_to_coords(robust_center),
                "trajectory_dispersion_m": float(dispersion_m),
                "trajectory_confidence": float(confidence),
                "trajectory_samples": [
                    {
                        "source_traj_id": str(item["source_traj_id"]),
                        "coords": _point_to_coords(item["point"]),
                        "distance_to_guide_m": float(item["distance_to_guide_m"]),
                        "weight": float(item["weight"]),
                    }
                    for item in samples
                ],
                "lane_boundary_center_hint_coords": None,
                "lane_boundary_center_tangent": None,
                "lane_boundary_quality_score": 0.0,
                "lane_boundary_weight": 0.0,
                "lane_boundary_usage_band": "skipped",
                "center_corrected_spine_coords": None,
                "center_correction_m": 0.0,
                "center_correction_source": "",
                "center_correction_applied_bool": False,
                "fitted_coords": None,
            }
        )
    if rows:
        rows[0]["trajectory_robust_center_coords"] = _point_to_coords(start_anchor)
        rows[0]["trajectory_confidence"] = 1.0
        rows[0]["center_corrected_spine_coords"] = _point_to_coords(start_anchor)
        rows[-1]["trajectory_robust_center_coords"] = _point_to_coords(end_anchor)
        rows[-1]["trajectory_confidence"] = 1.0
        rows[-1]["center_corrected_spine_coords"] = _point_to_coords(end_anchor)
    return rows


def _coords_to_point(coords: Any) -> Point | None:
    if not isinstance(coords, list) or len(coords) < 2:
        return None
    return Point(float(coords[0]), float(coords[1]))


def _normalize_vector(dx: float, dy: float) -> tuple[float, float] | None:
    norm = hypot(float(dx), float(dy))
    if norm <= 1e-6:
        return None
    return float(dx / norm), float(dy / norm)


def _align_vector(
    vector: tuple[float, float] | None,
    reference: tuple[float, float] | None,
) -> tuple[float, float] | None:
    if vector is None:
        return None
    if reference is None:
        return vector
    dot = float(vector[0]) * float(reference[0]) + float(vector[1]) * float(reference[1])
    if dot < 0.0:
        return (-float(vector[0]), -float(vector[1]))
    return vector


def _blend_unit_vectors(
    vectors: list[tuple[tuple[float, float], float]],
    *,
    fallback: tuple[float, float] | None = None,
) -> tuple[tuple[float, float] | None, float]:
    sx = 0.0
    sy = 0.0
    sw = 0.0
    for vector, weight in vectors:
        if vector is None or float(weight) <= 0.0:
            continue
        sx += float(vector[0]) * float(weight)
        sy += float(vector[1]) * float(weight)
        sw += float(weight)
    blended = _normalize_vector(sx, sy)
    if blended is None:
        return fallback, 0.0 if fallback is None else min(1.0, float(sw))
    return blended, min(1.0, float(sw) / max(1.0, float(sw)))


def _vector_angle_deg(
    vector_a: tuple[float, float] | None,
    vector_b: tuple[float, float] | None,
) -> float:
    if vector_a is None or vector_b is None:
        return 180.0
    cross = float(vector_a[0]) * float(vector_b[1]) - float(vector_a[1]) * float(vector_b[0])
    dot = float(vector_a[0]) * float(vector_b[0]) + float(vector_a[1]) * float(vector_b[1])
    return abs(float(atan2(cross, dot))) * 180.0 / pi


def _point_along_vector(
    origin: Point,
    tangent: tuple[float, float] | None,
    distance_m: float,
    *,
    reverse: bool = False,
) -> Point:
    if tangent is None:
        return Point(float(origin.x), float(origin.y))
    sign = -1.0 if bool(reverse) else 1.0
    return Point(
        float(origin.x) + float(tangent[0]) * float(distance_m) * sign,
        float(origin.y) + float(tangent[1]) * float(distance_m) * sign,
    )


def _station_reference_length(
    station_rows: list[dict[str, Any]],
    start_anchor: Point,
    end_anchor: Point,
) -> float:
    guide_line = _line_from_coords([row.get("guide_coords") for row in station_rows if isinstance(row.get("guide_coords"), list)])
    if _line_is_usable(guide_line):
        return float(guide_line.length)
    return max(1.0, float(start_anchor.distance(end_anchor)))


def _copy_station_rows(station_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in station_rows:
        current = dict(row)
        if isinstance(current.get("trajectory_samples"), list):
            current["trajectory_samples"] = [dict(item) for item in current["trajectory_samples"]]
        out.append(current)
    return out


def _iter_station_points(
    rows: list[dict[str, Any]],
    *,
    coords_key: str = "trajectory_robust_center_coords",
) -> list[tuple[int, float, Point, tuple[float, float] | None]]:
    out: list[tuple[int, float, Point, tuple[float, float] | None]] = []
    for row in rows:
        coords = row.get(coords_key) or row.get("trajectory_robust_center_coords") or row.get("guide_coords")
        point = _coords_to_point(coords)
        if point is None:
            continue
        tangent_raw = row.get("tangent")
        tangent = None
        if isinstance(tangent_raw, list) and len(tangent_raw) >= 2:
            tangent = _normalize_vector(float(tangent_raw[0]), float(tangent_raw[1]))
        out.append((int(row.get("station_index", len(out))), float(row.get("station_norm", 0.0)), point, tangent))
    return out


def extract_lane_boundary_center_hints(
    *,
    station_rows: list[dict[str, Any]],
    lane_boundaries: tuple[LineString, ...],
    safe_surface: Any | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    search_m = float(params.get("GLOBAL_FIT_LANE_BOUNDARY_SEARCH_M", params.get("GEOMETRY_REFINE_LANE_BOUNDARY_SEARCH_M", 12.0)))
    min_sep_m = float(params.get("GLOBAL_FIT_LANE_BOUNDARY_PAIR_MIN_SEP_M", params.get("GEOMETRY_REFINE_LANE_BOUNDARY_PAIR_MIN_SEP_M", 1.5)))
    max_sep_m = float(params.get("GLOBAL_FIT_LANE_BOUNDARY_PAIR_MAX_SEP_M", params.get("GEOMETRY_REFINE_LANE_BOUNDARY_PAIR_MAX_SEP_M", 18.0)))
    target_width_m = float(params.get("GLOBAL_FIT_LANE_BOUNDARY_TARGET_WIDTH_M", params.get("GEOMETRY_REFINE_LANE_BOUNDARY_TARGET_WIDTH_M", 6.0)))
    max_weight = float(params.get("GLOBAL_FIT_LANE_HINT_MAX_WEIGHT", 0.35))
    min_quality = float(params.get("GLOBAL_FIT_LANE_HINT_MIN_QUALITY", 0.45))
    high_quality = float(params.get("GLOBAL_FIT_LANE_HINT_HIGH_QUALITY", 0.70))
    rows: list[dict[str, Any]] = []
    high_quality_count = 0
    weak_quality_count = 0
    total_station_count = 0
    for station_index, station_norm, point, tangent in _iter_station_points(station_rows):
        total_station_count += 1
        if tangent is None or len(lane_boundaries) < 2:
            continue
        normal = (-float(tangent[1]), float(tangent[0]))
        left_candidates: list[dict[str, Any]] = []
        right_candidates: list[dict[str, Any]] = []
        for boundary_index, boundary in enumerate(lane_boundaries):
            if not _line_is_usable(boundary):
                continue
            nearest = _safe_nearest_points(boundary, point)
            if nearest is None:
                continue
            boundary_point = nearest[0]
            distance = float(boundary_point.distance(point))
            if distance > search_m:
                continue
            signed_offset = (
                (float(boundary_point.x) - float(point.x)) * float(normal[0])
                + (float(boundary_point.y) - float(point.y)) * float(normal[1])
            )
            boundary_norm = float(boundary.project(boundary_point) / max(boundary.length, 1e-6))
            boundary_tangent = _align_vector(_sample_direction(boundary, boundary_norm), tangent)
            tangent_align = 0.0
            if boundary_tangent is not None:
                tangent_align = abs(
                    float(boundary_tangent[0]) * float(tangent[0]) + float(boundary_tangent[1]) * float(tangent[1])
                )
            candidate = {
                "boundary_index": int(boundary_index),
                "point": boundary_point,
                "distance": float(distance),
                "signed_offset": float(signed_offset),
                "tangent_align": float(tangent_align),
                "boundary_tangent": boundary_tangent,
                "rank_score": float(tangent_align) - float(distance) / max(search_m, 1.0),
            }
            if signed_offset >= 0.0:
                right_candidates.append(candidate)
            else:
                left_candidates.append(candidate)
        if not left_candidates or not right_candidates:
            continue
        left = max(left_candidates, key=lambda item: float(item["rank_score"]))
        right = max(right_candidates, key=lambda item: float(item["rank_score"]))
        separation = float(left["point"].distance(right["point"]))
        if separation < min_sep_m or separation > max_sep_m:
            continue
        center_point = Point(
            (float(left["point"].x) + float(right["point"].x)) / 2.0,
            (float(left["point"].y) + float(right["point"].y)) / 2.0,
        )
        surface_penalty = 0.0
        if safe_surface is not None and not getattr(safe_surface, "is_empty", True):
            try:
                if not safe_surface.buffer(1.0).contains(center_point):
                    surface_penalty = 0.20
            except Exception:
                surface_penalty = 0.0
        offset_m = float(center_point.distance(point))
        quality = max(
            0.0,
            min(
                1.0,
                1.0
                - float(offset_m) / max(search_m, 1.0)
                - min(0.35, abs(float(separation) - target_width_m) / max(max_sep_m, 1.0))
                - min(0.2, abs(float(left["tangent_align"]) - 1.0))
                - min(0.2, abs(float(right["tangent_align"]) - 1.0))
                - float(surface_penalty),
            ),
        )
        if quality < min_quality:
            continue
        usage_band = "high_quality" if float(quality) >= high_quality else "weak_constraint"
        if usage_band == "high_quality":
            high_quality_count += 1
        else:
            weak_quality_count += 1
        weight_scale = 1.25 if usage_band == "high_quality" else 0.80
        weight = max(0.0, min(max_weight, float(quality) * max_weight * weight_scale))
        center_tangent, _ = _blend_unit_vectors(
            [
                (left["boundary_tangent"], max(0.1, float(left["tangent_align"]))),
                (right["boundary_tangent"], max(0.1, float(right["tangent_align"]))),
            ],
            fallback=tangent,
        )
        rows.append(
            {
                "station_index": int(station_index),
                "station_norm": float(station_norm),
                "coords": _point_to_coords(center_point),
                "quality_score": float(quality),
                "weight": float(weight),
                "width_m": float(separation),
                "offset_from_spine_m": float(offset_m),
                "tangent": [float(tangent[0]), float(tangent[1])],
                "center_tangent": None if center_tangent is None else [float(center_tangent[0]), float(center_tangent[1])],
                "usage_band": str(usage_band),
                "source_lane_boundary_ids": [
                    f"lane_boundary_{int(left['boundary_index'])}",
                    f"lane_boundary_{int(right['boundary_index'])}",
                ],
            }
        )
    quality_values = [float(item["quality_score"]) for item in rows]
    return {
        "hint_rows": rows,
        "hint_count": int(len(rows)),
        "quality_mean": float(sum(quality_values) / max(len(quality_values), 1)) if quality_values else 0.0,
        "quality_max": max(quality_values, default=0.0),
        "high_quality_count": int(high_quality_count),
        "weak_quality_count": int(weak_quality_count),
        "skipped_station_count": max(0, int(total_station_count) - int(len(rows))),
        "total_station_count": int(total_station_count),
        "usage_ratio": float(len(rows) / max(total_station_count, 1)) if total_station_count else 0.0,
        "used_bool": bool(rows),
    }


def build_center_corrected_spine(
    *,
    station_rows: list[dict[str, Any]],
    start_anchor: Point,
    end_anchor: Point,
    params: dict[str, Any],
) -> dict[str, Any]:
    corrected_rows = _copy_station_rows(station_rows)
    min_quality = float(params.get("GLOBAL_FIT_LANE_HINT_MIN_QUALITY", 0.45))
    high_quality = float(params.get("GLOBAL_FIT_LANE_HINT_HIGH_QUALITY", 0.70))
    base_blend = float(params.get("GLOBAL_FIT_CENTER_CORRECTION_BASE_BLEND", 0.48))
    max_blend = float(params.get("GLOBAL_FIT_CENTER_CORRECTION_MAX_BLEND", 0.68))
    weak_scale = float(params.get("GLOBAL_FIT_CENTER_CORRECTION_WEAK_SCALE", 0.55))
    max_shift_m = float(params.get("GLOBAL_FIT_CENTER_CORRECTION_MAX_SHIFT_M", 2.6))
    high_quality_count = 0
    weak_quality_count = 0
    skipped_count = 0
    raw_correction_values: list[float] = []
    for index, row in enumerate(corrected_rows):
        base_point = _coords_to_point(row.get("trajectory_robust_center_coords") or row.get("guide_coords"))
        if base_point is None:
            row["center_corrected_spine_coords"] = row.get("trajectory_robust_center_coords") or row.get("guide_coords")
            row["center_correction_m"] = 0.0
            row["center_correction_source"] = ""
            row["center_correction_applied_bool"] = False
            row["lane_boundary_usage_band"] = "skipped"
            skipped_count += 1
            continue
        if index == 0:
            row["center_corrected_spine_coords"] = _point_to_coords(start_anchor)
            row["center_correction_m"] = 0.0
            row["center_correction_source"] = "authoritative_anchor"
            row["center_correction_applied_bool"] = False
            row["lane_boundary_usage_band"] = "skipped"
            continue
        if index == len(corrected_rows) - 1:
            row["center_corrected_spine_coords"] = _point_to_coords(end_anchor)
            row["center_correction_m"] = 0.0
            row["center_correction_source"] = "authoritative_anchor"
            row["center_correction_applied_bool"] = False
            row["lane_boundary_usage_band"] = "skipped"
            continue
        hint_point = _coords_to_point(row.get("lane_boundary_center_hint_coords"))
        hint_quality = float(row.get("lane_boundary_quality_score", 0.0) or 0.0)
        if hint_point is None or hint_quality < min_quality:
            row["center_corrected_spine_coords"] = _point_to_coords(base_point)
            row["center_correction_m"] = 0.0
            row["center_correction_source"] = ""
            row["center_correction_applied_bool"] = False
            row["lane_boundary_usage_band"] = "skipped"
            skipped_count += 1
            continue
        usage_band = "high_quality" if hint_quality >= high_quality else "weak_constraint"
        traj_confidence = max(0.15, float(row.get("trajectory_confidence", 0.0) or 0.0))
        lane_weight = max(0.0, float(row.get("lane_boundary_weight", 0.0) or 0.0))
        dx = float(hint_point.x) - float(base_point.x)
        dy = float(hint_point.y) - float(base_point.y)
        offset_norm = hypot(float(dx), float(dy))
        if offset_norm <= 1e-6:
            row["center_corrected_spine_coords"] = _point_to_coords(base_point)
            row["center_correction_m"] = 0.0
            row["center_correction_source"] = ""
            row["center_correction_applied_bool"] = False
            row["lane_boundary_usage_band"] = str(usage_band)
            if usage_band == "high_quality":
                high_quality_count += 1
            else:
                weak_quality_count += 1
            continue
        band_scale = 1.0 if usage_band == "high_quality" else weak_scale
        blend = min(
            max_blend,
            max(
                0.10,
                float(base_blend) * float(band_scale) * max(0.75, 1.15 - 0.35 * float(traj_confidence)) * max(0.55, 0.8 + 1.2 * float(lane_weight)),
            ),
        )
        correction_m = min(float(max_shift_m), float(offset_norm) * float(blend))
        corrected_point = Point(
            float(base_point.x) + float(dx) / float(offset_norm) * float(correction_m),
            float(base_point.y) + float(dy) / float(offset_norm) * float(correction_m),
        )
        row["center_corrected_spine_coords"] = _point_to_coords(corrected_point)
        row["center_correction_m"] = float(correction_m)
        row["center_correction_source"] = f"lane_boundary_center_hint_{usage_band}"
        row["center_correction_applied_bool"] = bool(correction_m > 1e-6)
        row["lane_boundary_usage_band"] = str(usage_band)
        raw_correction_values.append(float(correction_m))
        if usage_band == "high_quality":
            high_quality_count += 1
        else:
            weak_quality_count += 1
    corrected_line, corrected_metrics = fit_global_centerline(
        station_rows=corrected_rows,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        params=params,
        use_lane_hints=False,
        target_key="center_corrected_spine_coords",
        objective_name="center_corrected_spine",
    )
    if corrected_line is None:
        corrected_line = _line_from_coords([row.get("center_corrected_spine_coords") for row in corrected_rows])
    actual_correction_values: list[float] = []
    if corrected_line is not None:
        for row in corrected_rows:
            corrected_point = _safe_line_interpolate(corrected_line, float(row.get("station_norm", 0.0)), normalized=True)
            if corrected_point is None:
                continue
            row["center_corrected_spine_coords"] = _point_to_coords(corrected_point)
            base_point = _coords_to_point(row.get("trajectory_robust_center_coords") or row.get("guide_coords"))
            if base_point is not None:
                actual_correction = float(corrected_point.distance(base_point))
                row["center_correction_m"] = float(actual_correction)
                if float(actual_correction) > 1e-6 and not str(row.get("center_correction_source", "")):
                    row["center_correction_source"] = "smoothed_center_correction"
                row["center_correction_applied_bool"] = bool(actual_correction > 1e-6)
                actual_correction_values.append(float(actual_correction))
    correction_values = actual_correction_values or raw_correction_values
    return {
        "station_rows": corrected_rows,
        "corrected_line": corrected_line,
        "corrected_spine_quality": float(corrected_metrics.get("fit_quality", 0.0) or 0.0),
        "correction_enabled_bool": bool(correction_values),
        "high_quality_count": int(high_quality_count),
        "weak_quality_count": int(weak_quality_count),
        "skipped_count": int(skipped_count),
        "correction_mean_m": float(sum(correction_values) / max(len(correction_values), 1)) if correction_values else 0.0,
        "correction_max_m": max(correction_values, default=0.0),
        "correction_source": "lane_boundary_center_hint_centerline_correction" if correction_values else "",
    }


def estimate_endpoint_local_tangents(
    *,
    selected_rows: list[dict[str, Any]],
    station_rows: list[dict[str, Any]],
    corrected_spine_line: LineString | None,
    start_anchor: Point,
    end_anchor: Point,
    params: dict[str, Any],
) -> dict[str, Any]:
    enabled = bool(params.get("GLOBAL_FIT_ENDPOINT_TANGENT_ENABLE", 1))
    window_m = float(params.get("GLOBAL_FIT_ENDPOINT_TANGENT_WINDOW_M", 18.0))
    sample_m = float(params.get("GLOBAL_FIT_ENDPOINT_TANGENT_SAMPLE_M", max(6.0, min(12.0, window_m * 0.75))))
    reference_length = _station_reference_length(station_rows, start_anchor, end_anchor)
    fallback_start = _direction_unit(corrected_spine_line, at_start=True) if _line_is_usable(corrected_spine_line) else _normalize_vector(float(end_anchor.x) - float(start_anchor.x), float(end_anchor.y) - float(start_anchor.y))
    fallback_end = _direction_unit(corrected_spine_line, at_start=False) if _line_is_usable(corrected_spine_line) else fallback_start

    def _build_endpoint_payload(*, at_start: bool) -> dict[str, Any]:
        anchor = start_anchor if at_start else end_anchor
        fallback = fallback_start if at_start else fallback_end
        trajectory_vectors: list[tuple[tuple[float, float], float]] = []
        for row in selected_rows:
            line = row.get("line")
            if not _line_is_usable(line):
                continue
            nearest = _safe_nearest_points(line, anchor)
            if nearest is None:
                continue
            line_anchor = nearest[0]
            anchor_distance = float(line_anchor.distance(anchor))
            if anchor_distance > float(window_m) * 1.5:
                continue
            projected = float(line.project(line_anchor))
            if at_start:
                point_a = _safe_line_interpolate(line, projected)
                point_b = _safe_line_interpolate(line, min(float(line.length), projected + float(sample_m)))
            else:
                point_a = _safe_line_interpolate(line, max(0.0, projected - float(sample_m)))
                point_b = _safe_line_interpolate(line, projected)
            if point_a is None or point_b is None:
                continue
            vector = _align_vector(
                _normalize_vector(float(point_b.x) - float(point_a.x), float(point_b.y) - float(point_a.y)),
                fallback,
            )
            if vector is None:
                continue
            weight = max(0.10, float(row.get("selection_weight", 0.0) or 0.0)) * max(0.10, 1.0 - anchor_distance / max(window_m * 1.5, 1.0))
            trajectory_vectors.append((vector, float(weight)))
        trajectory_vector, trajectory_confidence = _blend_unit_vectors(trajectory_vectors, fallback=None)

        lane_vectors: list[tuple[tuple[float, float], float]] = []
        for row in station_rows:
            station_norm = float(row.get("station_norm", 0.0) or 0.0)
            station_distance = float(row.get("station_distance_m", station_norm * reference_length) or 0.0)
            endpoint_distance = station_distance if at_start else max(0.0, reference_length - station_distance)
            if endpoint_distance > window_m:
                continue
            tangent_raw = row.get("lane_boundary_center_tangent") or row.get("tangent")
            if not isinstance(tangent_raw, list) or len(tangent_raw) < 2:
                continue
            vector = _align_vector(_normalize_vector(float(tangent_raw[0]), float(tangent_raw[1])), fallback)
            if vector is None:
                continue
            quality = max(0.0, float(row.get("lane_boundary_quality_score", 0.0) or 0.0))
            weight = float(quality) * max(0.10, 1.0 - endpoint_distance / max(window_m, 1.0))
            if weight <= 0.0:
                continue
            lane_vectors.append((vector, float(weight)))
        lane_vector, lane_confidence = _blend_unit_vectors(lane_vectors, fallback=None)

        blend_inputs: list[tuple[tuple[float, float], float]] = []
        if trajectory_vector is not None:
            blend_inputs.append((trajectory_vector, max(0.35, 1.35 * float(trajectory_confidence))))
        if lane_vector is not None:
            blend_inputs.append((lane_vector, max(0.15, 0.65 * float(lane_confidence))))
        if fallback is not None:
            blend_inputs.append((fallback, 0.25))
        tangent, _ = _blend_unit_vectors(blend_inputs, fallback=fallback)
        if tangent is None:
            tangent = fallback
        source_type = "corrected_spine_fallback"
        if trajectory_vector is not None and lane_vector is not None and lane_confidence >= 0.35:
            source_type = "trajectory_local_trend_blended_lane_hint"
        elif trajectory_vector is not None:
            source_type = "trajectory_local_trend"
        elif lane_vector is not None:
            source_type = "lane_boundary_local_tangent"
        confidence = min(1.0, max(float(trajectory_confidence), 0.0) * 0.70 + max(float(lane_confidence), 0.0) * 0.20 + (0.10 if fallback is not None else 0.0))
        return {
            "tangent": None if tangent is None else [float(tangent[0]), float(tangent[1])],
            "source_type": str(source_type),
            "confidence": float(confidence),
            "trajectory_candidate_count": int(len(trajectory_vectors)),
            "lane_hint_count": int(len(lane_vectors)),
            "window_m": float(window_m),
        }

    return {
        "enabled_bool": bool(enabled),
        "src": _build_endpoint_payload(at_start=True) if enabled else {"tangent": None, "source_type": "", "confidence": 0.0},
        "dst": _build_endpoint_payload(at_start=False) if enabled else {"tangent": None, "source_type": "", "confidence": 0.0},
    }


def fit_global_centerline(
    *,
    station_rows: list[dict[str, Any]],
    start_anchor: Point,
    end_anchor: Point,
    params: dict[str, Any],
    use_lane_hints: bool,
    target_key: str = "trajectory_robust_center_coords",
    endpoint_tangents: dict[str, Any] | None = None,
    objective_name: str = "global_fitted_line",
) -> tuple[LineString | None, dict[str, Any]]:
    if len(station_rows) < 2:
        return None, {"fit_quality": 0.0, "mean_traj_offset_m": float("inf"), "mean_lane_offset_m": float("inf")}
    smooth_weight = float(params.get("GLOBAL_FIT_SMOOTHNESS_WEIGHT", 1.8))
    guide_weight = float(params.get("GLOBAL_FIT_GUIDE_WEIGHT", 0.32))
    traj_base_weight = float(params.get("GLOBAL_FIT_TRAJECTORY_WEIGHT", 2.6))
    corrected_spine_weight = float(params.get("GLOBAL_FIT_CORRECTED_SPINE_WEIGHT", max(3.1, traj_base_weight)))
    lane_max_weight = float(params.get("GLOBAL_FIT_LANE_HINT_MAX_WEIGHT", 0.35))
    centerline_penalty_weight = float(params.get("GLOBAL_FIT_CENTERLINE_PENALTY_WEIGHT", 2.0))
    endpoint_tangent_weight = float(params.get("GLOBAL_FIT_ENDPOINT_TANGENT_WEIGHT", 2.8))
    endpoint_neighborhood_weight = float(params.get("GLOBAL_FIT_ENDPOINT_NEIGHBORHOOD_WEIGHT", 2.1))
    endpoint_window_m = float(params.get("GLOBAL_FIT_ENDPOINT_TANGENT_WINDOW_M", 18.0))
    iterations = max(8, int(params.get("GLOBAL_FIT_SMOOTHING_ITERATIONS", 18)))
    reference_length = _station_reference_length(station_rows, start_anchor, end_anchor)
    src_tangent_raw = None if not isinstance(endpoint_tangents, dict) else (endpoint_tangents.get("src") or {}).get("tangent")
    dst_tangent_raw = None if not isinstance(endpoint_tangents, dict) else (endpoint_tangents.get("dst") or {}).get("tangent")
    src_tangent = None
    dst_tangent = None
    if isinstance(src_tangent_raw, list) and len(src_tangent_raw) >= 2:
        src_tangent = _normalize_vector(float(src_tangent_raw[0]), float(src_tangent_raw[1]))
    if isinstance(dst_tangent_raw, list) and len(dst_tangent_raw) >= 2:
        dst_tangent = _normalize_vector(float(dst_tangent_raw[0]), float(dst_tangent_raw[1]))
    coords: list[tuple[float, float]] = []
    for row in station_rows:
        target = row.get(target_key) or row.get("trajectory_robust_center_coords") or row.get("guide_coords")
        if not isinstance(target, list) or len(target) < 2:
            return None, {"fit_quality": 0.0, "mean_traj_offset_m": float("inf"), "mean_lane_offset_m": float("inf")}
        coords.append((float(target[0]), float(target[1])))
    coords[0] = (float(start_anchor.x), float(start_anchor.y))
    coords[-1] = (float(end_anchor.x), float(end_anchor.y))
    target_base_weight = float(corrected_spine_weight if target_key == "center_corrected_spine_coords" else traj_base_weight)
    for _ in range(iterations):
        next_coords = list(coords)
        for idx in range(1, len(coords) - 1):
            row = station_rows[idx]
            sx = 0.0
            sy = 0.0
            sw = 0.0
            target_coords = row.get(target_key) or row.get("trajectory_robust_center_coords") or row.get("guide_coords")
            if isinstance(target_coords, list) and len(target_coords) >= 2:
                target_weight = max(0.25, float(target_base_weight) * max(float(row.get("trajectory_confidence", 0.0) or 0.0), 0.15))
                sx += float(target_coords[0]) * float(target_weight)
                sy += float(target_coords[1]) * float(target_weight)
                sw += float(target_weight)
            guide_coords = row.get("guide_coords")
            if isinstance(guide_coords, list) and len(guide_coords) >= 2:
                sx += float(guide_coords[0]) * float(guide_weight)
                sy += float(guide_coords[1]) * float(guide_weight)
                sw += float(guide_weight)
            if use_lane_hints:
                hint_coords = row.get("lane_boundary_center_hint_coords")
                hint_weight = min(
                    float(lane_max_weight) * 2.25,
                    max(0.0, float(row.get("lane_boundary_weight", 0.0) or 0.0))
                    * float(centerline_penalty_weight)
                    * (1.30 if str(row.get("lane_boundary_usage_band", "")) == "high_quality" else 0.80),
                )
                if isinstance(hint_coords, list) and len(hint_coords) >= 2 and hint_weight > 0.0:
                    sx += float(hint_coords[0]) * float(hint_weight)
                    sy += float(hint_coords[1]) * float(hint_weight)
                    sw += float(hint_weight)
            smooth_x = (float(coords[idx - 1][0]) + float(coords[idx + 1][0])) / 2.0
            smooth_y = (float(coords[idx - 1][1]) + float(coords[idx + 1][1])) / 2.0
            sx += float(smooth_x) * float(smooth_weight)
            sy += float(smooth_y) * float(smooth_weight)
            sw += float(smooth_weight)
            station_norm = float(row.get("station_norm", 0.0) or 0.0)
            station_distance = float(row.get("station_distance_m", station_norm * reference_length) or 0.0)
            dist_from_start = float(station_distance)
            dist_from_end = max(0.0, float(reference_length) - float(station_distance))
            if src_tangent is not None and dist_from_start < endpoint_window_m:
                ramp = max(0.0, 1.0 - float(dist_from_start) / max(endpoint_window_m, 1.0))
                tangent_target = _point_along_vector(start_anchor, src_tangent, dist_from_start, reverse=False)
                tangent_weight = float(endpoint_tangent_weight) * float(ramp)
                sx += float(tangent_target.x) * float(tangent_weight)
                sy += float(tangent_target.y) * float(tangent_weight)
                sw += float(tangent_weight)
                if isinstance(target_coords, list) and len(target_coords) >= 2:
                    neighborhood_weight = float(endpoint_neighborhood_weight) * float(ramp)
                    sx += float(target_coords[0]) * float(neighborhood_weight)
                    sy += float(target_coords[1]) * float(neighborhood_weight)
                    sw += float(neighborhood_weight)
            if dst_tangent is not None and dist_from_end < endpoint_window_m:
                ramp = max(0.0, 1.0 - float(dist_from_end) / max(endpoint_window_m, 1.0))
                tangent_target = _point_along_vector(end_anchor, dst_tangent, dist_from_end, reverse=True)
                tangent_weight = float(endpoint_tangent_weight) * float(ramp)
                sx += float(tangent_target.x) * float(tangent_weight)
                sy += float(tangent_target.y) * float(tangent_weight)
                sw += float(tangent_weight)
                if isinstance(target_coords, list) and len(target_coords) >= 2:
                    neighborhood_weight = float(endpoint_neighborhood_weight) * float(ramp)
                    sx += float(target_coords[0]) * float(neighborhood_weight)
                    sy += float(target_coords[1]) * float(neighborhood_weight)
                    sw += float(neighborhood_weight)
            if sw > 1e-6:
                next_coords[idx] = (float(sx / sw), float(sy / sw))
        next_coords[0] = (float(start_anchor.x), float(start_anchor.y))
        next_coords[-1] = (float(end_anchor.x), float(end_anchor.y))
        coords = next_coords
    fitted_line = _line_from_coords(coords)
    if fitted_line is None:
        return None, {"fit_quality": 0.0, "mean_traj_offset_m": float("inf"), "mean_lane_offset_m": float("inf")}
    fitted_line = _replace_endpoints(fitted_line, start_anchor, end_anchor) or fitted_line
    mean_target_offset = 0.0
    target_count = 0
    mean_lane_offset = 0.0
    lane_count = 0
    endpoint_neighborhood_offset = 0.0
    endpoint_neighborhood_count = 0
    for row in station_rows:
        station_norm = float(row.get("station_norm", 0.0))
        fit_point = _safe_line_interpolate(fitted_line, station_norm, normalized=True)
        if fit_point is None:
            continue
        row["fitted_coords"] = _point_to_coords(fit_point)
        target_coords = row.get(target_key) or row.get("trajectory_robust_center_coords")
        if isinstance(target_coords, list) and len(target_coords) >= 2:
            distance_to_target = float(fit_point.distance(Point(float(target_coords[0]), float(target_coords[1]))))
            mean_target_offset += float(distance_to_target)
            target_count += 1
            station_distance = float(row.get("station_distance_m", station_norm * reference_length) or 0.0)
            dist_from_start = float(station_distance)
            dist_from_end = max(0.0, float(reference_length) - float(station_distance))
            if dist_from_start < endpoint_window_m or dist_from_end < endpoint_window_m:
                endpoint_neighborhood_offset += float(distance_to_target)
                endpoint_neighborhood_count += 1
        hint_coords = row.get("lane_boundary_center_hint_coords")
        if isinstance(hint_coords, list) and len(hint_coords) >= 2 and float(row.get("lane_boundary_weight", 0.0)) > 0.0:
            mean_lane_offset += float(fit_point.distance(Point(float(hint_coords[0]), float(hint_coords[1]))))
            lane_count += 1
    mean_target_offset /= max(target_count, 1)
    mean_lane_offset = (mean_lane_offset / max(lane_count, 1)) if lane_count else 0.0
    endpoint_neighborhood_offset = (endpoint_neighborhood_offset / max(endpoint_neighborhood_count, 1)) if endpoint_neighborhood_count else 0.0
    smoothness_deg = _mean_turn_angle_deg(fitted_line)
    fitted_src_tangent = _direction_unit(fitted_line, at_start=True)
    fitted_dst_tangent = _direction_unit(fitted_line, at_start=False)
    src_tangent_error = _vector_angle_deg(fitted_src_tangent, src_tangent) if src_tangent is not None else 0.0
    dst_tangent_error = _vector_angle_deg(fitted_dst_tangent, dst_tangent) if dst_tangent is not None else 0.0
    fit_quality = max(
        0.0,
        min(
            1.0,
            1.0
            - float(mean_target_offset) / 8.0
            - min(0.25, float(mean_lane_offset) / 8.0)
            - min(0.18, float(endpoint_neighborhood_offset) / 8.0)
            - min(0.18, (float(src_tangent_error) + float(dst_tangent_error)) / 180.0)
            - min(0.28, float(smoothness_deg) / 90.0),
        ),
    )
    return fitted_line, {
        "fit_quality": float(fit_quality),
        "objective_name": str(objective_name),
        "target_key": str(target_key),
        "mean_traj_offset_m": float(mean_target_offset),
        "mean_target_offset_m": float(mean_target_offset),
        "mean_lane_offset_m": float(mean_lane_offset),
        "endpoint_neighborhood_offset_m": float(endpoint_neighborhood_offset),
        "smoothness_angle_deg": float(smoothness_deg),
        "src_tangent_error_deg": float(src_tangent_error),
        "dst_tangent_error_deg": float(dst_tangent_error),
    }


def _fallback_spine(
    *,
    guide_line: LineString,
    start_anchor: Point,
    end_anchor: Point,
    reason: str,
) -> dict[str, Any]:
    spine = _anchor_along_guide_line(guide_line, start_anchor, end_anchor)
    return {
        "trajectory_spine_line": spine,
        "trajectory_spine_quality": 0.0,
        "trajectory_spine_support_count": 0,
        "trajectory_spine_weak_bool": True,
        "trajectory_spine_fallback_bool": True,
        "fallback_reason": str(reason),
    }


def build_global_geometry_fit(
    *,
    segment: Segment,
    arc_row: dict[str, Any] | None,
    witness_line: LineString | None,
    lane_boundaries: tuple[LineString, ...],
    safe_surface: Any | None,
    start_anchor: Point,
    end_anchor: Point,
    params: dict[str, Any],
    fallback_line: LineString | None = None,
) -> dict[str, Any]:
    selection = select_trajectory_evidence(
        segment=segment,
        arc_row=arc_row,
        witness_line=witness_line,
        fallback_line=fallback_line,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        safe_surface=safe_surface,
        params=params,
    )
    guide_line = selection["guide_line"]
    selected_rows = list(selection["selected_rows"])
    trace: dict[str, Any] = {
        "guide_source": str(selection["guide_source"]),
        "guide_coords": [] if not _line_is_usable(guide_line) else [[float(x), float(y)] for x, y in line_to_coords(guide_line)],
        "trajectory_selection_rows": [],
        "trajectory_spine_coords": [],
        "original_spine_coords": [],
        "trajectory_spine_source": "",
        "trajectory_spine_quality": 0.0,
        "trajectory_spine_support_count": int(len(selected_rows)),
        "trajectory_spine_weak_bool": False,
        "trajectory_spine_fallback_bool": False,
        "center_corrected_spine_coords": [],
        "center_corrected_spine_quality": 0.0,
        "centerline_correction_enabled_bool": False,
        "centerline_correction_summary": {
            "high_quality_count": 0,
            "weak_quality_count": 0,
            "skipped_count": 0,
            "correction_mean_m": 0.0,
            "correction_max_m": 0.0,
            "correction_source": "",
        },
        "lane_boundary_hint_rows": [],
        "lane_boundary_hint_usage": {
            "hint_count": 0,
            "quality_mean": 0.0,
            "quality_max": 0.0,
            "high_quality_count": 0,
            "weak_quality_count": 0,
            "skipped_station_count": 0,
            "total_station_count": 0,
            "usage_ratio": 0.0,
            "used_bool": False,
        },
        "endpoint_tangent_trace": {
            "enabled_bool": False,
            "src": {"tangent": None, "source_type": "", "confidence": 0.0},
            "dst": {"tangent": None, "source_type": "", "confidence": 0.0},
        },
        "endpoint_tangent_continuity_enabled_bool": False,
        "station_rows": [],
        "fitted_line_coords": [],
        "fitting_mode": "trajectory_centered_global_fit_v2",
        "fitted_line_source": "center_corrected_spine_with_endpoint_tangent_continuity",
        "fitting_success_bool": False,
        "fallback_reason": "",
        "quality_gate_passed": False,
        "quality_gate_reason": "",
    }
    for row in list(selection["selection_rows"]):
        current = dict(row)
        current.pop("line", None)
        trace["trajectory_selection_rows"].append(current)
    if not _line_is_usable(guide_line):
        trace["fallback_reason"] = "guide_line_missing"
        return trace
    station_rows = aggregate_trajectory_stations(
        guide_line=guide_line,
        selected_rows=selected_rows,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        params=params,
    )
    if not station_rows:
        trace["fallback_reason"] = "station_rows_missing"
        return trace
    spine_line, spine_metrics = fit_global_centerline(
        station_rows=station_rows,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        params=params,
        use_lane_hints=False,
    )
    if spine_line is None:
        fallback = _fallback_spine(
            guide_line=guide_line,
            start_anchor=start_anchor,
            end_anchor=end_anchor,
            reason="trajectory_spine_fit_failed",
        )
        trace["trajectory_spine_coords"] = [[float(x), float(y)] for x, y in line_to_coords(fallback["trajectory_spine_line"])]
        trace["trajectory_spine_quality"] = float(fallback["trajectory_spine_quality"])
        trace["trajectory_spine_support_count"] = int(fallback["trajectory_spine_support_count"])
        trace["trajectory_spine_weak_bool"] = bool(fallback["trajectory_spine_weak_bool"])
        trace["trajectory_spine_fallback_bool"] = bool(fallback["trajectory_spine_fallback_bool"])
        trace["station_rows"] = station_rows
        trace["fallback_reason"] = str(fallback["fallback_reason"])
        return trace
    spine_quality = float(spine_metrics["fit_quality"])
    weak_spine = bool(len(selected_rows) < 2 or spine_quality < float(params.get("GLOBAL_FIT_MIN_SPINE_QUALITY", 0.35)))
    trace["trajectory_spine_source"] = "trajectory_station_robust_center"
    trace["trajectory_spine_coords"] = [[float(x), float(y)] for x, y in line_to_coords(spine_line)]
    trace["original_spine_coords"] = list(trace["trajectory_spine_coords"])
    trace["trajectory_spine_quality"] = float(spine_quality)
    trace["trajectory_spine_support_count"] = int(len(selected_rows))
    trace["trajectory_spine_weak_bool"] = bool(weak_spine)
    trace["trajectory_spine_fallback_bool"] = False

    spine_station_rows = aggregate_trajectory_stations(
        guide_line=spine_line,
        selected_rows=selected_rows,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        params=params,
    )
    hint_usage = extract_lane_boundary_center_hints(
        station_rows=spine_station_rows,
        lane_boundaries=lane_boundaries,
        safe_surface=safe_surface,
        params=params,
    )
    hint_rows = list(hint_usage["hint_rows"])
    hint_by_station = {int(item["station_index"]): dict(item) for item in hint_rows}
    for row in spine_station_rows:
        hint = hint_by_station.get(int(row.get("station_index", -1)))
        if hint is None:
            continue
        row["lane_boundary_center_hint_coords"] = list(hint.get("coords") or [])
        row["lane_boundary_center_tangent"] = list(hint.get("center_tangent") or []) if isinstance(hint.get("center_tangent"), list) else None
        row["lane_boundary_quality_score"] = float(hint.get("quality_score", 0.0))
        row["lane_boundary_weight"] = float(hint.get("weight", 0.0))
        row["lane_boundary_usage_band"] = str(hint.get("usage_band", "weak_constraint"))

    correction = build_center_corrected_spine(
        station_rows=spine_station_rows,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        params=params,
    )
    corrected_station_rows = list(correction["station_rows"])
    corrected_spine_line = correction["corrected_line"]
    trace["center_corrected_spine_coords"] = (
        []
        if corrected_spine_line is None
        else [[float(x), float(y)] for x, y in line_to_coords(corrected_spine_line)]
    )
    trace["center_corrected_spine_quality"] = float(correction.get("corrected_spine_quality", 0.0) or 0.0)
    trace["centerline_correction_enabled_bool"] = bool(correction.get("correction_enabled_bool", False))
    trace["centerline_correction_summary"] = {
        "high_quality_count": int(correction.get("high_quality_count", 0) or 0),
        "weak_quality_count": int(correction.get("weak_quality_count", 0) or 0),
        "skipped_count": int(correction.get("skipped_count", 0) or 0),
        "correction_mean_m": float(correction.get("correction_mean_m", 0.0) or 0.0),
        "correction_max_m": float(correction.get("correction_max_m", 0.0) or 0.0),
        "correction_source": str(correction.get("correction_source", "")),
    }

    endpoint_tangent_trace = estimate_endpoint_local_tangents(
        selected_rows=selected_rows,
        station_rows=corrected_station_rows,
        corrected_spine_line=corrected_spine_line,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        params=params,
    )
    trace["endpoint_tangent_trace"] = dict(endpoint_tangent_trace)
    trace["endpoint_tangent_continuity_enabled_bool"] = bool(endpoint_tangent_trace.get("enabled_bool", False))

    fitted_line, fit_metrics = fit_global_centerline(
        station_rows=corrected_station_rows,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        params=params,
        use_lane_hints=True,
        target_key="center_corrected_spine_coords",
        endpoint_tangents=endpoint_tangent_trace,
        objective_name="trajectory_centered_global_fit_v2",
    )
    trace["lane_boundary_hint_rows"] = hint_rows
    trace["lane_boundary_hint_usage"] = {
        "hint_count": int(hint_usage["hint_count"]),
        "quality_mean": float(hint_usage["quality_mean"]),
        "quality_max": float(hint_usage["quality_max"]),
        "high_quality_count": int(hint_usage.get("high_quality_count", 0) or 0),
        "weak_quality_count": int(hint_usage.get("weak_quality_count", 0) or 0),
        "skipped_station_count": int(hint_usage.get("skipped_station_count", 0) or 0),
        "total_station_count": int(hint_usage.get("total_station_count", 0) or 0),
        "usage_ratio": float(hint_usage.get("usage_ratio", 0.0) or 0.0),
        "used_bool": bool(hint_usage["used_bool"]),
    }
    trace["station_rows"] = corrected_station_rows
    if fitted_line is None:
        trace["fallback_reason"] = "global_fit_failed"
        return trace
    lane_gate_min_quality = float(params.get("GLOBAL_FIT_LANE_GATE_MIN_QUALITY", 0.52))
    gate_candidates = [
        item
        for item in hint_rows
        if float(item.get("quality_score", 0.0)) >= lane_gate_min_quality
    ]
    lane_gate_mean_offset = 0.0
    lane_gate_count = 0
    for hint in gate_candidates:
        fit_point = _safe_line_interpolate(fitted_line, float(hint.get("station_norm", 0.0)), normalized=True)
        hint_coords = hint.get("coords")
        if fit_point is None or not isinstance(hint_coords, list) or len(hint_coords) < 2:
            continue
        lane_gate_mean_offset += float(fit_point.distance(Point(float(hint_coords[0]), float(hint_coords[1]))))
        lane_gate_count += 1
    lane_gate_mean_offset = (lane_gate_mean_offset / max(lane_gate_count, 1)) if lane_gate_count else 0.0
    lane_gate_threshold_m = float(params.get("GLOBAL_FIT_LANE_GATE_MAX_OFFSET_M", 3.5))
    quality_gate_passed = True
    quality_gate_reason = "lane_hint_sparse"
    if lane_gate_count >= 3:
        quality_gate_passed = float(lane_gate_mean_offset) <= float(lane_gate_threshold_m)
        quality_gate_reason = "ok" if quality_gate_passed else "lane_boundary_center_deviation"
    if weak_spine and not gate_candidates:
        quality_gate_passed = False
        quality_gate_reason = "weak_spine_without_lane_hints"
    trace["fitted_line_coords"] = [[float(x), float(y)] for x, y in line_to_coords(fitted_line)]
    trace["fitting_success_bool"] = bool(quality_gate_passed)
    trace["quality_gate_passed"] = bool(quality_gate_passed)
    trace["quality_gate_reason"] = str(quality_gate_reason)
    trace["fallback_reason"] = "" if quality_gate_passed else str(quality_gate_reason)
    trace["fit_metrics"] = {
        "fit_quality": float(fit_metrics["fit_quality"]),
        "objective_name": str(fit_metrics.get("objective_name", "")),
        "mean_traj_offset_m": float(fit_metrics["mean_traj_offset_m"]),
        "mean_target_offset_m": float(fit_metrics.get("mean_target_offset_m", fit_metrics["mean_traj_offset_m"])),
        "mean_lane_offset_m": float(fit_metrics["mean_lane_offset_m"]),
        "endpoint_neighborhood_offset_m": float(fit_metrics.get("endpoint_neighborhood_offset_m", 0.0)),
        "smoothness_angle_deg": float(fit_metrics["smoothness_angle_deg"]),
        "src_tangent_error_deg": float(fit_metrics.get("src_tangent_error_deg", 0.0)),
        "dst_tangent_error_deg": float(fit_metrics.get("dst_tangent_error_deg", 0.0)),
        "lane_gate_mean_offset_m": float(lane_gate_mean_offset),
    }
    return trace


__all__ = [
    "aggregate_trajectory_stations",
    "build_center_corrected_spine",
    "build_global_geometry_fit",
    "estimate_endpoint_local_tangents",
    "extract_lane_boundary_center_hints",
    "fit_global_centerline",
    "select_trajectory_evidence",
]
