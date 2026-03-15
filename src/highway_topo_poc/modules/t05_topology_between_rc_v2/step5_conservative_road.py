from __future__ import annotations

from collections import Counter
from dataclasses import replace
from math import atan2, hypot, isfinite
from pathlib import Path
from time import perf_counter
from typing import Any
import warnings

from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, substring, unary_union

from .io import write_features_geojson, write_json, write_lines_geojson
from .models import BaseCrossSection, CorridorIdentity, CorridorInterval, CorridorWitness, FinalRoad, Segment, SlotInterval, line_to_coords
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
        if isinstance(item, (list, tuple))
        and len(item) >= 2
        and isfinite(float(item[0]))
        and isfinite(float(item[1]))
    )
    if len(pts) < 2:
        return None
    line = LineString(list(pts))
    if line.is_empty or line.length <= 1e-6:
        return None
    return line


def _point_is_finite(point: Any) -> bool:
    return (
        isinstance(point, Point)
        and not point.is_empty
        and isfinite(float(point.x))
        and isfinite(float(point.y))
    )


def _line_is_usable(line: Any) -> bool:
    return isinstance(line, LineString) and not line.is_empty and isfinite(float(line.length)) and float(line.length) > 1e-6


def _safe_line_project(line: LineString, point: Point) -> float | None:
    if not _line_is_usable(line) or not _point_is_finite(point):
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            value = float(line.project(point))
        except Exception:
            return None
    return value if isfinite(value) else None


def _safe_line_interpolate(line: LineString, distance: float, *, normalized: bool = False) -> Point | None:
    if not _line_is_usable(line) or not isfinite(float(distance)):
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            point = line.interpolate(float(distance), normalized=bool(normalized))
        except Exception:
            return None
    return point if _point_is_finite(point) else None


def _safe_nearest_points(geometry_a: Any, geometry_b: Any) -> tuple[Point, Point] | None:
    if geometry_a is None or geometry_b is None:
        return None
    if getattr(geometry_a, "is_empty", True) or getattr(geometry_b, "is_empty", True):
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            point_a, point_b = nearest_points(geometry_a, geometry_b)
        except Exception:
            return None
    if not _point_is_finite(point_a) or not _point_is_finite(point_b):
        return None
    return point_a, point_b


def _safe_point_from_coords(anchor_coords: list[float] | tuple[float, float] | None) -> Point | None:
    if anchor_coords is None or len(anchor_coords) < 2:
        return None
    try:
        point = Point(float(anchor_coords[0]), float(anchor_coords[1]))
    except Exception:
        return None
    return point if _point_is_finite(point) else None


def _mean_endpoint_distance(line: LineString, start_pt: Point, end_pt: Point) -> float:
    if not _line_is_usable(line) or not _point_is_finite(start_pt) or not _point_is_finite(end_pt):
        return 999.0
    coords = list(line.coords)
    if len(coords) < 2:
        return 999.0
    line_start = Point(float(coords[0][0]), float(coords[0][1]))
    line_end = Point(float(coords[-1][0]), float(coords[-1][1]))
    return float(line_start.distance(start_pt) + line_end.distance(end_pt)) / 2.0


def _mean_line_offset(line: LineString, reference_line: LineString | None, *, step_m: float) -> float:
    if not _line_is_usable(line) or reference_line is None or not _line_is_usable(reference_line):
        return 999.0
    points = _sample_line_points(line, step_m=step_m)
    if not points:
        return 999.0
    distances: list[float] = []
    for point in points:
        nearest = _safe_nearest_points(reference_line, point)
        if nearest is None:
            continue
        distances.append(float(nearest[0].distance(point)))
    if not distances:
        return 999.0
    return float(sum(distances) / max(len(distances), 1))


def _mean_turn_angle_deg(line: LineString, *, step_m: float) -> float:
    points = _sample_line_points(line, step_m=step_m)
    if len(points) < 3:
        return 0.0
    angles: list[float] = []
    coords = [(float(point.x), float(point.y)) for point in points]
    for idx in range(1, len(coords) - 1):
        px, py = coords[idx - 1]
        cx, cy = coords[idx]
        nx, ny = coords[idx + 1]
        heading_in = atan2(float(cy - py), float(cx - px))
        heading_out = atan2(float(ny - cy), float(nx - cx))
        delta = abs(float(heading_out - heading_in))
        while delta > 3.141592653589793:
            delta -= 2.0 * 3.141592653589793
        angles.append(abs(delta) * 180.0 / 3.141592653589793)
    if not angles:
        return 0.0
    return float(sum(angles) / max(len(angles), 1))


def _distance_to_score(distance_m: float, *, scale_m: float) -> float:
    if not isfinite(float(distance_m)):
        return 0.0
    scale = max(float(scale_m), 0.5)
    return float(1.0 / (1.0 + max(0.0, float(distance_m)) / scale))


def _slot_surface_geometry(slot: SlotInterval, safe_surface: Any | None) -> Any | None:
    slot_line = _slot_interval_line(slot)
    if slot_line is None:
        return None
    slot_geom: Any = slot_line
    if safe_surface is not None and not getattr(safe_surface, "is_empty", True):
        try:
            clipped = slot_line.intersection(safe_surface)
        except Exception:
            clipped = slot_line
        line_components = _iter_line_components(clipped)
        if line_components:
            slot_geom = max(line_components, key=lambda item: float(item.length))
        elif isinstance(clipped, Point) and _point_is_finite(clipped):
            return clipped
    return slot_geom


def _anchor_along_base_line(base_line: LineString, start_pt: Point, end_pt: Point) -> LineString:
    if base_line.is_empty or base_line.length <= 1e-6:
        return _replace_endpoints(base_line, start_pt, end_pt)
    start_s = _safe_line_project(base_line, start_pt)
    end_s = _safe_line_project(base_line, end_pt)
    if start_s is None or end_s is None:
        return _replace_endpoints(base_line, start_pt, end_pt)
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
    start_s = _safe_line_project(base_line, start_pt)
    end_s = _safe_line_project(base_line, end_pt)
    if start_s is None or end_s is None:
        return None
    start_proj = _safe_line_interpolate(base_line, start_s)
    end_proj = _safe_line_interpolate(base_line, end_s)
    if start_proj is None or end_proj is None:
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


def _safe_surface(inputs: Any, divstrip_buffer: Any | None) -> Any | None:
    drivezone = getattr(inputs, "drivezone_zone_metric", None)
    if drivezone is None or getattr(drivezone, "is_empty", True):
        return None
    if divstrip_buffer is None or getattr(divstrip_buffer, "is_empty", True):
        return drivezone
    try:
        safe = drivezone.difference(divstrip_buffer)
    except Exception:
        return drivezone
    if safe is None or getattr(safe, "is_empty", True):
        return drivezone
    return safe


def _iter_line_components(geometry: Any) -> list[LineString]:
    if geometry is None or getattr(geometry, "is_empty", True):
        return []
    if isinstance(geometry, LineString):
        return [geometry] if float(geometry.length) > 1e-6 else []
    components: list[LineString] = []
    for geom in getattr(geometry, "geoms", []) or []:
        components.extend(_iter_line_components(geom))
    return components


def _slot_interval_line(slot: SlotInterval) -> LineString | None:
    interval = slot.interval
    if interval is None:
        return None
    coords = list(getattr(interval, "geometry_coords", ()) or ())
    return _line_from_coords(coords)


def _surface_envelope_core_line(
    base_line: LineString,
    safe_surface: Any | None,
) -> LineString | None:
    if safe_surface is None or getattr(safe_surface, "is_empty", True):
        return None
    try:
        clipped = base_line.intersection(safe_surface)
    except Exception:
        return None
    components = _iter_line_components(clipped)
    if not components:
        return None
    return max(components, key=lambda item: float(item.length))


def _slot_surface_anchor_point(
    slot: SlotInterval,
    reference_line: LineString,
    safe_surface: Any | None,
) -> Point:
    slot_geom = _slot_surface_geometry(slot, safe_surface)
    if slot_geom is None:
        pipeline = _pipeline()
        return pipeline._midpoint_of_interval(slot.interval)
    if isinstance(slot_geom, Point):
        return slot_geom
    if str(getattr(slot, "method", "")) == "fraction_match":
        midpoint = _safe_line_interpolate(slot_geom, 0.5, normalized=True) if isinstance(slot_geom, LineString) else None
        if midpoint is not None:
            return midpoint
    nearest = _safe_nearest_points(slot_geom, reference_line)
    if nearest is not None:
        return nearest[0]
    pipeline = _pipeline()
    return pipeline._midpoint_of_interval(slot.interval)


def _slot_surface_mid_anchor_point(
    slot: SlotInterval,
    safe_surface: Any | None,
) -> Point:
    pipeline = _pipeline()
    slot_geom = _slot_surface_geometry(slot, safe_surface)
    if slot_geom is None:
        return pipeline._midpoint_of_interval(slot.interval)
    if isinstance(slot_geom, Point):
        return slot_geom
    midpoint = _safe_line_interpolate(slot_geom, 0.5, normalized=True) if isinstance(slot_geom, LineString) else None
    if midpoint is not None:
        return midpoint
    return pipeline._midpoint_of_interval(slot.interval)


def _anchor_line_to_slot_intervals(
    base_line: LineString,
    src_slot: SlotInterval,
    dst_slot: SlotInterval,
    *,
    safe_surface: Any | None = None,
    prefer_trend: bool = False,
    anchor_reference_line: LineString | None = None,
) -> LineString:
    anchor_line = anchor_reference_line if anchor_reference_line is not None else base_line
    if prefer_trend:
        start_anchor = _slot_trend_anchor_point(src_slot, anchor_line, safe_surface, at_start=True)
        end_anchor = _slot_trend_anchor_point(dst_slot, anchor_line, safe_surface, at_start=False)
    else:
        start_anchor = _slot_surface_anchor_point(src_slot, anchor_line, safe_surface)
        end_anchor = _slot_surface_anchor_point(dst_slot, anchor_line, safe_surface)
    return _anchor_along_base_line(base_line, start_anchor, end_anchor)


def _surface_envelope_candidate_line(
    base_line: LineString,
    src_slot: SlotInterval,
    dst_slot: SlotInterval,
    safe_surface: Any | None,
) -> LineString | None:
    core_line = _surface_envelope_core_line(base_line, safe_surface)
    if core_line is None:
        return None
    start_anchor = _slot_surface_anchor_point(src_slot, core_line, safe_surface)
    end_anchor = _slot_surface_anchor_point(dst_slot, core_line, safe_surface)
    candidate = _anchor_along_base_line(core_line, start_anchor, end_anchor)
    if candidate.is_empty or float(candidate.length) <= 1e-6:
        return None
    return candidate


def _endpoint_trend_ray(
    base_line: LineString,
    *,
    at_start: bool,
) -> tuple[LineString, Point] | None:
    if base_line.is_empty or float(base_line.length) <= 1e-6:
        return None
    coords = list(base_line.coords)
    if len(coords) < 2:
        return None
    if at_start:
        endpoint = coords[0]
        neighbor = next(
            (coord for coord in coords[1:] if (float(coord[0]), float(coord[1])) != (float(endpoint[0]), float(endpoint[1]))),
            None,
        )
    else:
        endpoint = coords[-1]
        neighbor = next(
            (coord for coord in reversed(coords[:-1]) if (float(coord[0]), float(coord[1])) != (float(endpoint[0]), float(endpoint[1]))),
            None,
        )
    if neighbor is None:
        return None
    endpoint_pt = Point(float(endpoint[0]), float(endpoint[1]))
    dx = float(endpoint[0]) - float(neighbor[0])
    dy = float(endpoint[1]) - float(neighbor[1])
    norm = hypot(float(dx), float(dy))
    if norm <= 1e-6:
        return None
    ray_len = max(float(base_line.length), 50.0)
    far_pt = Point(
        float(endpoint_pt.x) + float(dx / norm) * float(ray_len),
        float(endpoint_pt.y) + float(dy / norm) * float(ray_len),
    )
    return LineString(
        [
            (float(endpoint_pt.x), float(endpoint_pt.y)),
            (float(far_pt.x), float(far_pt.y)),
        ]
    ), endpoint_pt


def _closest_point_on_geometry(geometry: Any, reference_point: Point) -> Point | None:
    if geometry is None or getattr(geometry, "is_empty", True):
        return None
    if isinstance(geometry, Point):
        return geometry if _point_is_finite(geometry) else None
    if isinstance(geometry, LineString):
        nearest = _safe_nearest_points(geometry, reference_point)
        return nearest[0] if nearest is not None else None
    candidates: list[Point] = []
    for geom in getattr(geometry, "geoms", []) or []:
        point = _closest_point_on_geometry(geom, reference_point)
        if point is not None:
            candidates.append(point)
    if not candidates:
        return None
    return min(candidates, key=lambda item: float(item.distance(reference_point)))


def _slot_trend_anchor_point(
    slot: SlotInterval,
    reference_line: LineString,
    safe_surface: Any | None,
    *,
    at_start: bool,
) -> Point:
    slot_geom = _slot_surface_geometry(slot, safe_surface)
    if slot_geom is None:
        pipeline = _pipeline()
        return pipeline._midpoint_of_interval(slot.interval)
    if isinstance(slot_geom, Point):
        return slot_geom
    trend_ray = _endpoint_trend_ray(reference_line, at_start=bool(at_start))
    if trend_ray is None:
        return _slot_surface_anchor_point(slot, reference_line, safe_surface)
    ray_line, endpoint_pt = trend_ray
    try:
        intersection = slot_geom.intersection(ray_line)
    except Exception:
        intersection = None
    trend_point = _closest_point_on_geometry(intersection, endpoint_pt)
    if trend_point is not None:
        return trend_point
    nearest = _safe_nearest_points(slot_geom, ray_line)
    return nearest[0] if nearest is not None else _slot_surface_anchor_point(slot, reference_line, safe_surface)


def _rcsdroad_trend_extended_candidate_line(
    base_line: LineString,
    src_slot: SlotInterval,
    dst_slot: SlotInterval,
    *,
    safe_surface: Any | None = None,
    use_safe_core: bool = False,
) -> LineString | None:
    if base_line.is_empty or float(base_line.length) <= 1e-6:
        return None
    core_line = _surface_envelope_core_line(base_line, safe_surface) if use_safe_core else base_line
    if core_line is None or core_line.is_empty or float(core_line.length) <= 1e-6:
        return None
    start_anchor = _slot_trend_anchor_point(src_slot, core_line, safe_surface, at_start=True)
    end_anchor = _slot_trend_anchor_point(dst_slot, core_line, safe_surface, at_start=False)
    candidate = _anchor_along_base_line(core_line, start_anchor, end_anchor)
    if candidate.is_empty or float(candidate.length) <= 1e-6:
        return None
    return candidate


def _rcsdroad_fallback_base_line(
    *,
    segment: Segment,
    arc_row: dict[str, Any] | None = None,
    prior_roads: list[Any],
    prior_index: dict[tuple[int, int], list[Any]] | None = None,
) -> LineString:
    arc_line = _line_from_coords(list((arc_row or {}).get("line_coords", [])))
    if arc_line is not None:
        return arc_line
    prior_line = find_prior_reference_line(segment, prior_roads, prior_index=prior_index)
    return prior_line if prior_line is not None else segment.geometry_metric()


def slot_reference_line(
    *,
    segment: Segment,
    identity: CorridorIdentity,
    prior_roads: list[Any],
    prior_index: dict[tuple[int, int], list[Any]] | None = None,
) -> tuple[LineString, str]:
    if bool(getattr(segment, "production_consumable_default", False)) and str(
        getattr(segment, "geometry_role", "")
    ) == "step3_production_working_segment":
        return segment.geometry_metric(), "production_working_segment"
    if str(identity.state) == "prior_based":
        prior_line = find_prior_reference_line(segment, prior_roads, prior_index=prior_index)
        if prior_line is not None:
            return prior_line, "prior_reference"
    return segment.geometry_metric(), "production_working_segment"


def _shape_ref_source_family(mode: str) -> str:
    text = str(mode or "")
    if text.startswith(("selected_support_", "stitched_support_", "traj_support_")):
        return "support_reference_family"
    if text.startswith("witness"):
        return "witness_family"
    if text.startswith("prior"):
        return "prior_family"
    if text.startswith("topology_arc"):
        return "topology_arc_family"
    if text.startswith(("production_working_segment", "segment_support")):
        return "production_working_segment_family"
    if text.startswith("rcsdroad"):
        return "rcsdroad_family"
    return "other_family"


def _segment_prefers_production_shape_ref(segment: Segment) -> bool:
    return bool(getattr(segment, "production_consumable_default", False)) and str(
        getattr(segment, "geometry_role", "")
    ) == "step3_production_working_segment"


def _support_candidate_policy(segment: Segment) -> str:
    if not _segment_prefers_production_shape_ref(segment):
        return "allowed"
    fallback_reason = str(getattr(segment, "geometry_fallback_reason", "") or "")
    if not fallback_reason:
        return "allowed"
    if (
        str(getattr(segment, "geometry_source_type", "")) != "support_arc_fused"
        and (
            "arc_fallback" in fallback_reason
            or "support_" in fallback_reason
            or "shared_xsec" in fallback_reason
            or "weak_partial_support" in fallback_reason
        )
    ):
        return "suppressed_after_step3_arc_fallback"
    return "allowed"


def _allow_support_reference_candidates(segment: Segment) -> bool:
    return str(_support_candidate_policy(segment)) == "allowed"


def _project_anchor_s_on_xsec(xsec_line: LineString, anchor_coords: list[float] | tuple[float, float] | None) -> float | None:
    if anchor_coords is None or len(anchor_coords) < 2 or xsec_line.is_empty or float(xsec_line.length) <= 1e-6:
        return None
    anchor = _safe_point_from_coords(anchor_coords)
    if anchor is None:
        return None
    return _safe_line_project(xsec_line, anchor)


def _resolve_interval_from_anchor(
    *,
    intervals: list[CorridorInterval],
    xsec_line: LineString,
    anchor_coords: list[float] | tuple[float, float] | None,
    tolerance_m: float,
    label: str,
) -> tuple[CorridorInterval | None, str, str]:
    anchor_s = _project_anchor_s_on_xsec(xsec_line, anchor_coords)
    if anchor_s is None or not intervals:
        return None, "unresolved", "anchor_missing"
    for interval in intervals:
        if float(interval.start_s) - float(tolerance_m) <= float(anchor_s) <= float(interval.end_s) + float(tolerance_m):
            return interval, f"{label}_contains", f"{label}_anchor_on_interval"
    nearest = min(intervals, key=lambda item: abs(float(item.center_s) - float(anchor_s)))
    if abs(float(nearest.center_s) - float(anchor_s)) <= float(tolerance_m):
        return nearest, f"{label}_nearest", f"{label}_anchor_nearest_interval"
    return None, "unresolved", "anchor_outside_legal_interval"


def _slot_anchor_candidates(
    *,
    arc_row: dict[str, Any] | None,
    endpoint_tag: str,
    trusted_only: bool = False,
) -> list[tuple[list[float] | tuple[float, float], str]]:
    if not isinstance(arc_row, dict) or not arc_row:
        return []
    endpoint_key = "src" if str(endpoint_tag) == "src" else "dst"
    stitched_anchor = arc_row.get(f"stitched_support_anchor_{endpoint_key}_coords")
    support_anchor = arc_row.get(f"support_anchor_{endpoint_key}_coords")
    support_trusted = bool(arc_row.get("selected_support_interval_reference_trusted", False))
    stitched_trusted = bool(arc_row.get("stitched_support_interval_reference_trusted", False))
    preferred_source = str(arc_row.get("support_interval_reference_source", "") or "")
    ordered: list[tuple[Any, str]] = []
    if trusted_only:
        if preferred_source == "selected_support" and support_trusted:
            ordered.append((support_anchor, "selected_support"))
            if stitched_trusted:
                ordered.append((stitched_anchor, "stitched_support"))
        elif preferred_source == "stitched_support" and stitched_trusted:
            ordered.append((stitched_anchor, "stitched_support"))
            if support_trusted:
                ordered.append((support_anchor, "selected_support"))
        else:
            if support_trusted:
                ordered.append((support_anchor, "selected_support"))
            if stitched_trusted:
                ordered.append((stitched_anchor, "stitched_support"))
    else:
        prefer_stitched = bool(arc_row.get("stitched_support_available", False)) and (
            not bool(arc_row.get("support_full_xsec_crossing", False))
            or not bool(arc_row.get("support_cluster_is_dominant", False))
            or not bool(arc_row.get("selected_support_interval_reference_trusted", False))
        )
        ordered = [
            (stitched_anchor, "stitched_support"),
            (support_anchor, "selected_support"),
        ] if prefer_stitched else [
            (support_anchor, "selected_support"),
            (stitched_anchor, "stitched_support"),
        ]
    out: list[tuple[list[float] | tuple[float, float], str]] = []
    for coords, label in ordered:
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            out.append((coords, label))
    return out


def _trusted_support_shape_ref_line(
    *,
    arc_row: dict[str, Any] | None,
    start_pt: Point,
    end_pt: Point,
) -> tuple[LineString, str] | None:
    if not isinstance(arc_row, dict) or not arc_row:
        return None
    support_trusted = bool(arc_row.get("selected_support_interval_reference_trusted", False))
    stitched_trusted = bool(arc_row.get("stitched_support_interval_reference_trusted", False))
    preferred_source = str(arc_row.get("support_interval_reference_source", "") or "")
    ordered: list[tuple[str, Any]] = []
    if preferred_source == "selected_support" and support_trusted:
        ordered.append(("selected_support", arc_row.get("support_reference_coords", [])))
        if stitched_trusted:
            ordered.append(("stitched_support", arc_row.get("stitched_support_reference_coords", [])))
    elif preferred_source == "stitched_support" and stitched_trusted:
        ordered.append(("stitched_support", arc_row.get("stitched_support_reference_coords", [])))
        if support_trusted:
            ordered.append(("selected_support", arc_row.get("support_reference_coords", [])))
    else:
        if support_trusted:
            ordered.append(("selected_support", arc_row.get("support_reference_coords", [])))
        if stitched_trusted:
            ordered.append(("stitched_support", arc_row.get("stitched_support_reference_coords", [])))
    for label, coords in ordered:
        reference_line = _line_from_coords(list(coords or []))
        if reference_line is None:
            continue
        return _anchor_along_base_line(reference_line, start_pt, end_pt), f"{label}_reference_projected_anchored"
    return None


def _trusted_support_reference_line(
    *,
    arc_row: dict[str, Any] | None,
) -> tuple[LineString, str] | None:
    if not isinstance(arc_row, dict) or not arc_row:
        return None
    support_trusted = bool(arc_row.get("selected_support_interval_reference_trusted", False))
    stitched_trusted = bool(arc_row.get("stitched_support_interval_reference_trusted", False))
    preferred_source = str(arc_row.get("support_interval_reference_source", "") or "")
    ordered: list[tuple[str, Any]] = []
    if preferred_source == "selected_support" and support_trusted:
        ordered.append(("selected_support", arc_row.get("support_reference_coords", [])))
        if stitched_trusted:
            ordered.append(("stitched_support", arc_row.get("stitched_support_reference_coords", [])))
    elif preferred_source == "stitched_support" and stitched_trusted:
        ordered.append(("stitched_support", arc_row.get("stitched_support_reference_coords", [])))
        if support_trusted:
            ordered.append(("selected_support", arc_row.get("support_reference_coords", [])))
    else:
        if support_trusted:
            ordered.append(("selected_support", arc_row.get("support_reference_coords", [])))
        if stitched_trusted:
            ordered.append(("stitched_support", arc_row.get("stitched_support_reference_coords", [])))
    for label, coords in ordered:
        reference_line = _line_from_coords(list(coords or []))
        if reference_line is not None:
            return reference_line, str(label)
    return None


def shape_ref_line(
    *,
    segment: Segment,
    identity: CorridorIdentity,
    witness: CorridorWitness | None,
    src_slot: SlotInterval,
    dst_slot: SlotInterval,
    prior_roads: list[Any],
    arc_row: dict[str, Any] | None = None,
    prior_index: dict[tuple[int, int], list[Any]] | None = None,
) -> tuple[LineString, str]:
    base_line, mode = slot_reference_line(segment=segment, identity=identity, prior_roads=prior_roads, prior_index=prior_index)
    if src_slot.interval is None or dst_slot.interval is None:
        return base_line, str(mode)
    if _segment_prefers_production_shape_ref(segment):
        return _anchor_line_to_slot_intervals(base_line, src_slot, dst_slot), f"{mode}_slot_anchored"
    trusted_support_ref = _trusted_support_reference_line(arc_row=arc_row)
    if trusted_support_ref is not None:
        trusted_line, trusted_label = trusted_support_ref
        return _anchor_line_to_slot_intervals(trusted_line, src_slot, dst_slot), f"{trusted_label}_reference_projected_anchored"
    if str(identity.state) == "witness_based":
        witness_reference = None if witness is None else witness.geometry_metric()
        if witness_reference is not None and not witness_reference.is_empty and float(witness_reference.length) > 1e-6:
            return _anchor_line_to_slot_intervals(
                witness_reference,
                src_slot,
                dst_slot,
                anchor_reference_line=base_line,
            ), "witness_reference_projected_anchored"
        start_pt = _slot_surface_anchor_point(src_slot, base_line, None)
        end_pt = _slot_surface_anchor_point(dst_slot, base_line, None)
        legacy_centerline = _legacy_witness_centerline(witness=witness, start_pt=start_pt, end_pt=end_pt)
        if legacy_centerline is not None:
            return legacy_centerline, "witness_centerline"
    return _anchor_line_to_slot_intervals(base_line, src_slot, dst_slot), f"{mode}_slot_anchored"


def _midpoint_between_points(point_a: Point, point_b: Point) -> Point:
    return Point(
        (float(point_a.x) + float(point_b.x)) / 2.0,
        (float(point_a.y) + float(point_b.y)) / 2.0,
    )


def _direction_unit(line: LineString, *, at_start: bool) -> tuple[float, float] | None:
    if line.is_empty or float(line.length) <= 1e-6:
        return None
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    if at_start:
        endpoint = coords[0]
        neighbor = next(
            (coord for coord in coords[1:] if (float(coord[0]), float(coord[1])) != (float(endpoint[0]), float(endpoint[1]))),
            None,
        )
        if neighbor is None:
            return None
        dx = float(neighbor[0]) - float(endpoint[0])
        dy = float(neighbor[1]) - float(endpoint[1])
    else:
        endpoint = coords[-1]
        neighbor = next(
            (coord for coord in reversed(coords[:-1]) if (float(coord[0]), float(coord[1])) != (float(endpoint[0]), float(endpoint[1]))),
            None,
        )
        if neighbor is None:
            return None
        dx = float(endpoint[0]) - float(neighbor[0])
        dy = float(endpoint[1]) - float(neighbor[1])
    norm = hypot(float(dx), float(dy))
    if norm <= 1e-6:
        return None
    return float(dx / norm), float(dy / norm)


def _curve_connector_line(
    start_pt: Point,
    end_pt: Point,
    *,
    start_dir: tuple[float, float] | None,
    end_dir: tuple[float, float] | None,
    ctrl_frac: float,
    ctrl_min_m: float,
    ctrl_max_m: float,
    samples: int = 12,
) -> LineString | None:
    span = float(start_pt.distance(end_pt))
    if span <= 1e-6:
        return None
    if span <= 2.0:
        return _line_from_coords(
            [
                (float(start_pt.x), float(start_pt.y)),
                (float(end_pt.x), float(end_pt.y)),
            ]
        )
    ctrl_len = max(float(ctrl_min_m), min(float(ctrl_max_m), float(span) * float(ctrl_frac)))
    if start_dir is None:
        start_dir = (
            float(end_pt.x) - float(start_pt.x),
            float(end_pt.y) - float(start_pt.y),
        )
        start_norm = hypot(float(start_dir[0]), float(start_dir[1]))
        start_dir = None if start_norm <= 1e-6 else (float(start_dir[0] / start_norm), float(start_dir[1] / start_norm))
    if end_dir is None:
        end_dir = (
            float(end_pt.x) - float(start_pt.x),
            float(end_pt.y) - float(start_pt.y),
        )
        end_norm = hypot(float(end_dir[0]), float(end_dir[1]))
        end_dir = None if end_norm <= 1e-6 else (float(end_dir[0] / end_norm), float(end_dir[1] / end_norm))
    if start_dir is None or end_dir is None:
        return _line_from_coords(
            [
                (float(start_pt.x), float(start_pt.y)),
                (float(end_pt.x), float(end_pt.y)),
            ]
        )
    ctrl_1 = (
        float(start_pt.x) + float(start_dir[0]) * float(ctrl_len),
        float(start_pt.y) + float(start_dir[1]) * float(ctrl_len),
    )
    ctrl_2 = (
        float(end_pt.x) - float(end_dir[0]) * float(ctrl_len),
        float(end_pt.y) - float(end_dir[1]) * float(ctrl_len),
    )
    sample_count = max(6, int(samples))
    coords: list[tuple[float, float]] = []
    for idx in range(sample_count):
        t = float(idx) / float(sample_count - 1)
        mt = 1.0 - t
        x = (
            float(mt**3) * float(start_pt.x)
            + 3.0 * float(mt**2) * float(t) * float(ctrl_1[0])
            + 3.0 * float(mt) * float(t**2) * float(ctrl_2[0])
            + float(t**3) * float(end_pt.x)
        )
        y = (
            float(mt**3) * float(start_pt.y)
            + 3.0 * float(mt**2) * float(t) * float(ctrl_1[1])
            + 3.0 * float(mt) * float(t**2) * float(ctrl_2[1])
            + float(t**3) * float(end_pt.y)
        )
        coords.append((float(x), float(y)))
    return _line_from_coords(coords)


def _sample_line_points(line: LineString, *, step_m: float) -> list[Point]:
    if line.is_empty or float(line.length) <= 1e-6:
        return []
    sample_step = max(float(step_m), 2.0)
    sample_count = max(5, int(float(line.length) / sample_step) + 1)
    if sample_count <= 2:
        sample_count = 3
    points: list[Point] = []
    for idx in range(sample_count):
        point = _safe_line_interpolate(line, float(idx) / float(sample_count - 1), normalized=True)
        if point is not None:
            points.append(point)
    return points


def _combine_line_parts(*parts: LineString | None) -> LineString | None:
    coords: list[tuple[float, float]] = []
    for line in parts:
        if line is None or line.is_empty:
            continue
        for x, y, *_ in line.coords:
            xy = (float(x), float(y))
            if not coords or xy != coords[-1]:
                coords.append(xy)
    if len(coords) < 2:
        return None
    combined = LineString(coords)
    if combined.is_empty or float(combined.length) <= 1e-6:
        return None
    return combined


def _trim_line_middle(line: LineString, *, trim_frac: float) -> LineString | None:
    if line.is_empty or float(line.length) <= 1e-6:
        return None
    frac = max(0.0, min(0.35, float(trim_frac)))
    start_s = float(line.length) * frac
    end_s = float(line.length) * (1.0 - frac)
    if end_s - start_s <= 1e-6:
        return line
    middle = substring(line, start_s, end_s)
    if isinstance(middle, Point):
        return None
    if not isinstance(middle, LineString) or middle.is_empty or float(middle.length) <= 1e-6:
        return None
    return middle


def _smoothed_line(line: LineString, *, step_m: float) -> LineString | None:
    points = _sample_line_points(line, step_m=step_m)
    if len(points) < 5:
        return None
    coords = [(float(point.x), float(point.y)) for point in points]
    smoothed: list[tuple[float, float]] = [coords[0]]
    for idx in range(1, len(coords) - 1):
        prev_x, prev_y = coords[idx - 1]
        cur_x, cur_y = coords[idx]
        next_x, next_y = coords[idx + 1]
        smoothed.append(
            (
                float(prev_x * 0.25 + cur_x * 0.5 + next_x * 0.25),
                float(prev_y * 0.25 + cur_y * 0.5 + next_y * 0.25),
            )
        )
    smoothed.append(coords[-1])
    line_smoothed = _line_from_coords(smoothed)
    if line_smoothed is None:
        return None
    return line_smoothed


def _lane_boundary_centerline_for_road(
    *,
    road_line: LineString,
    lane_boundaries: tuple[LineString, ...],
    safe_surface: Any | None,
    params: dict[str, Any],
) -> tuple[LineString | None, dict[str, Any]]:
    info = {
        "quality_score": 0.0,
        "center_offset": None,
        "use_reason": "lane_boundary_missing_or_low_quality",
    }
    if road_line.is_empty or float(road_line.length) <= 1e-6 or len(lane_boundaries) < 2:
        return None, info
    midpoint = _safe_line_interpolate(road_line, 0.5, normalized=True)
    if midpoint is None:
        return None, info
    search_m = float(params.get("GEOMETRY_REFINE_LANE_BOUNDARY_SEARCH_M", 12.0))
    min_sep_m = float(params.get("GEOMETRY_REFINE_LANE_BOUNDARY_PAIR_MIN_SEP_M", 1.5))
    max_sep_m = float(params.get("GEOMETRY_REFINE_LANE_BOUNDARY_PAIR_MAX_SEP_M", 18.0))
    candidates: list[tuple[float, LineString]] = []
    for boundary in lane_boundaries:
        if boundary.is_empty or float(boundary.length) <= 1e-6:
            continue
        nearest = _safe_nearest_points(boundary, midpoint)
        if nearest is None:
            continue
        boundary_point = nearest[0]
        distance = float(boundary_point.distance(midpoint))
        if distance <= search_m:
            candidates.append((distance, boundary))
    if len(candidates) < 2:
        return None, info
    candidates.sort(key=lambda item: float(item[0]))
    sample_points = _sample_line_points(road_line, step_m=float(params.get("GEOMETRY_REFINE_SMOOTH_SAMPLE_STEP_M", 8.0)))
    best_line: LineString | None = None
    best_rank: tuple[float, float, float] | None = None
    best_meta: dict[str, Any] = {}
    for idx in range(len(candidates)):
        for jdx in range(idx + 1, len(candidates)):
            boundary_a = candidates[idx][1]
            boundary_b = candidates[jdx][1]
            center_points: list[tuple[float, float]] = []
            center_offsets: list[float] = []
            separations: list[float] = []
            valid_pair = True
            for sample_point in sample_points:
                nearest_a = _safe_nearest_points(boundary_a, sample_point)
                nearest_b = _safe_nearest_points(boundary_b, sample_point)
                if nearest_a is None or nearest_b is None:
                    valid_pair = False
                    break
                point_a = nearest_a[0]
                point_b = nearest_b[0]
                separation = float(point_a.distance(point_b))
                if separation < min_sep_m or separation > max_sep_m:
                    valid_pair = False
                    break
                center_point = _midpoint_between_points(point_a, point_b)
                center_points.append((float(center_point.x), float(center_point.y)))
                center_offsets.append(float(center_point.distance(sample_point)))
                separations.append(separation)
            if not valid_pair or len(center_points) < 3:
                continue
            center_line = _line_from_coords(center_points)
            if center_line is None:
                continue
            if safe_surface is not None and not getattr(safe_surface, "is_empty", True):
                if _line_overlap_ratio(center_line, safe_surface) < 0.75:
                    continue
            avg_offset = float(sum(center_offsets) / max(len(center_offsets), 1))
            avg_sep = float(sum(separations) / max(len(separations), 1))
            sep_spread = float(max(separations) - min(separations)) if separations else 0.0
            quality = max(
                0.0,
                min(
                    1.0,
                    1.0
                    - (avg_offset / max(search_m, 1.0))
                    - min(0.45, sep_spread / max(max_sep_m, 1.0))
                    - min(0.25, abs(avg_sep - float(params.get("GEOMETRY_REFINE_LANE_BOUNDARY_TARGET_WIDTH_M", 6.0))) / max(max_sep_m, 1.0)),
                ),
            )
            rank = (
                -float(quality),
                float(avg_offset),
                float(-center_line.length),
            )
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_line = center_line
                best_meta = {
                    "quality_score": float(quality),
                    "center_offset": float(avg_offset),
                    "use_reason": "paired_lane_boundary_centerline",
                }
    if best_line is None:
        return None, info
    return best_line, best_meta


def _geometry_refine_source_family(source_label: str) -> str:
    label = str(source_label or "")
    if label.startswith(("selected_support_", "stitched_support_")):
        return "traj_guided"
    if label.startswith("production_working_segment"):
        return "traj_guided"
    if label.startswith("lane_boundary"):
        return "lane_boundary_guided"
    if label.startswith("witness"):
        return "witness_guided"
    if label.startswith("prior"):
        return "prior_guided"
    return "reference_guided"


def _blend_centerlines(
    primary_line: LineString,
    center_hint_line: LineString | None,
    *,
    primary_weight: float,
    step_m: float,
) -> LineString | None:
    if center_hint_line is None or center_hint_line.is_empty or float(center_hint_line.length) <= 1e-6:
        return None
    if primary_line.is_empty or float(primary_line.length) <= 1e-6:
        return None
    weight = max(0.5, min(0.92, float(primary_weight)))
    sample_step = max(float(step_m), 4.0)
    sample_count = max(7, int(max(float(primary_line.length), float(center_hint_line.length)) / sample_step) + 1)
    coords: list[tuple[float, float]] = []
    for idx in range(sample_count):
        t = float(idx) / float(sample_count - 1)
        primary_pt = _safe_line_interpolate(primary_line, t, normalized=True)
        center_pt = _safe_line_interpolate(center_hint_line, t, normalized=True)
        if primary_pt is None or center_pt is None:
            continue
        coords.append(
            (
                float(primary_pt.x) * weight + float(center_pt.x) * (1.0 - weight),
                float(primary_pt.y) * weight + float(center_pt.y) * (1.0 - weight),
            )
        )
    return _line_from_coords(coords)


def _local_safe_envelope(
    *,
    safe_surface: Any | None,
    source_line: LineString | None,
    source_family: str,
    lane_boundary_line: LineString | None,
    original_line: LineString,
    params: dict[str, Any],
) -> tuple[Any | None, str, bool]:
    if safe_surface is None or getattr(safe_surface, "is_empty", True):
        return None, "", False
    corridor_buffer_m = float(params.get("GEOMETRY_REFINE_LOCAL_CORRIDOR_BUFFER_M", 12.0))
    lane_buffer_m = float(params.get("GEOMETRY_REFINE_LANE_BOUNDARY_BUFFER_M", max(4.0, corridor_buffer_m * 0.8)))
    weak_buffer_m = float(params.get("GEOMETRY_REFINE_ORIGINAL_WEAK_BUFFER_M", max(3.0, corridor_buffer_m * 0.45)))
    corridor_parts = []
    if source_line is not None and _line_is_usable(source_line):
        try:
            corridor_parts.append(source_line.buffer(corridor_buffer_m, cap_style=2, join_style=2))
        except Exception:
            pass
    lane_boundary_used = bool(lane_boundary_line is not None and _line_is_usable(lane_boundary_line))
    if lane_boundary_used:
        try:
            corridor_parts.append(lane_boundary_line.buffer(lane_buffer_m, cap_style=2, join_style=2))
        except Exception:
            lane_boundary_used = False
    original_used_as_weak_ref = False
    if _line_is_usable(original_line) and source_family != "traj_guided":
        try:
            corridor_parts.append(original_line.buffer(weak_buffer_m, cap_style=2, join_style=2))
            original_used_as_weak_ref = True
        except Exception:
            original_used_as_weak_ref = False
    if not corridor_parts:
        return safe_surface, "mixed", bool(original_used_as_weak_ref)
    try:
        corridor = unary_union(corridor_parts)
        envelope = safe_surface.intersection(corridor)
    except Exception:
        return safe_surface, "mixed", bool(original_used_as_weak_ref)
    if envelope is None or getattr(envelope, "is_empty", True):
        return safe_surface, "mixed", bool(original_used_as_weak_ref)
    if source_family == "lane_boundary_guided" and lane_boundary_used:
        envelope_source = "lane_boundary"
    elif source_family == "traj_guided" and lane_boundary_used:
        envelope_source = "mixed"
    elif source_family == "traj_guided":
        envelope_source = "traj_guided"
    elif lane_boundary_used:
        envelope_source = "mixed"
    else:
        envelope_source = "mixed"
    return envelope, envelope_source, bool(original_used_as_weak_ref)


def _slot_anchor_point_from_coords(
    slot: SlotInterval,
    anchor_coords: list[float] | tuple[float, float],
    safe_surface: Any | None,
) -> Point | None:
    point = _safe_point_from_coords(anchor_coords)
    if point is None:
        return None
    slot_geom = _slot_surface_geometry(slot, safe_surface)
    if slot_geom is None:
        pipeline = _pipeline()
        return pipeline._midpoint_of_interval(slot.interval)
    if isinstance(slot_geom, Point):
        return slot_geom
    nearest = _safe_nearest_points(slot_geom, point)
    return nearest[0] if nearest is not None else None


def _stabilize_slot_anchor_point(
    *,
    slot: SlotInterval,
    point: Point,
    safe_surface: Any | None,
    params: dict[str, Any],
) -> tuple[Point, bool]:
    midpoint = _slot_surface_mid_anchor_point(slot, safe_surface)
    slot_geom = _slot_surface_geometry(slot, safe_surface)
    if slot_geom is None:
        return midpoint, True
    if isinstance(slot_geom, Point):
        return slot_geom, False
    if not _point_is_finite(point):
        return midpoint, True
    nearest = _safe_nearest_points(slot_geom, point)
    if nearest is None:
        return midpoint, True
    snapped = nearest[0]
    max_snap_dist_m = float(params.get("GEOMETRY_REFINE_ANCHOR_MAX_SNAP_DIST_M", 3.0))
    if float(point.distance(snapped)) > max_snap_dist_m:
        return midpoint, True
    return snapped, False


def _select_refine_anchor_point(
    *,
    slot: SlotInterval,
    safe_surface: Any | None,
    arc_row: dict[str, Any] | None,
    source_line: LineString | None,
    source_family: str,
    endpoint_tag: str,
    witness: CorridorWitness | None,
    params: dict[str, Any],
) -> tuple[Point, dict[str, Any]]:
    def _anchor_result(point: Point, *, source: str, confidence: float, midpoint_fallback_used: bool) -> tuple[Point, dict[str, Any]]:
        return point, {
            "anchor_source": str(source),
            "anchor_confidence": float(max(0.0, min(1.0, confidence))),
            "anchor_midpoint_fallback_used": bool(midpoint_fallback_used),
        }

    if source_family == "traj_guided" and source_line is not None:
        point = _slot_surface_anchor_point(slot, source_line, safe_surface)
        point, midpoint_used = _stabilize_slot_anchor_point(slot=slot, point=point, safe_surface=safe_surface, params=params)
        return _anchor_result(
            point,
            source="midpoint_fallback" if midpoint_used else "traj_crossing",
            confidence=0.35 if midpoint_used else 0.98,
            midpoint_fallback_used=midpoint_used,
        )
    for coords, label in _slot_anchor_candidates(arc_row=arc_row, endpoint_tag=endpoint_tag, trusted_only=False):
        point = _slot_anchor_point_from_coords(slot, coords, safe_surface)
        if point is not None:
            point, midpoint_used = _stabilize_slot_anchor_point(slot=slot, point=point, safe_surface=safe_surface, params=params)
            return _anchor_result(
                point,
                source="midpoint_fallback" if midpoint_used else "support_crossing",
                confidence=0.32 if midpoint_used else (0.9 if label == "selected_support" else 0.84),
                midpoint_fallback_used=midpoint_used,
            )
    if witness is not None:
        witness_line = witness.geometry_metric()
        if not witness_line.is_empty and float(witness_line.length) > 1e-6:
            point = _slot_surface_anchor_point(slot, witness_line, safe_surface)
            point, midpoint_used = _stabilize_slot_anchor_point(slot=slot, point=point, safe_surface=safe_surface, params=params)
            return _anchor_result(
                point,
                source="midpoint_fallback" if midpoint_used else "witness",
                confidence=0.3 if midpoint_used else 0.72,
                midpoint_fallback_used=midpoint_used,
            )
    return _anchor_result(
        _slot_surface_mid_anchor_point(slot, safe_surface),
        source="midpoint_fallback",
        confidence=0.25,
        midpoint_fallback_used=True,
    )


def _geometry_refine_candidate_metrics(
    *,
    line: LineString,
    start_anchor: Point,
    end_anchor: Point,
    entry_anchor_confidence: float,
    exit_anchor_confidence: float,
    source_line: LineString | None,
    lane_boundary_line: LineString | None,
    inputs: Any,
    divstrip_buffer: Any | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    pipeline = _pipeline()
    drivezone_ratio = float(pipeline._drivezone_ratio(line, inputs.drivezone_zone_metric))
    divstrip_overlap_ratio = float(_line_overlap_ratio(line, divstrip_buffer))
    road_intersects_divstrip = bool(
        divstrip_buffer is not None and (not divstrip_buffer.is_empty) and line.intersects(divstrip_buffer)
    )
    hard_min_drivezone_ratio = max(
        float(params.get("ROAD_MIN_DRIVEZONE_RATIO", 0.85)),
        float(params.get("GEOMETRY_REFINE_HARD_MIN_DRIVEZONE_RATIO", 0.93)),
    )
    endpoint_fit_distance = _mean_endpoint_distance(line, start_anchor, end_anchor)
    geometry_offset = _mean_line_offset(
        line,
        source_line,
        step_m=float(params.get("GEOMETRY_REFINE_SMOOTH_SAMPLE_STEP_M", 8.0)),
    )
    center_offset = _mean_line_offset(
        line,
        lane_boundary_line,
        step_m=float(params.get("GEOMETRY_REFINE_SMOOTH_SAMPLE_STEP_M", 8.0)),
    )
    smoothness_angle_deg = _mean_turn_angle_deg(
        line,
        step_m=float(params.get("GEOMETRY_REFINE_SMOOTH_SAMPLE_STEP_M", 8.0)),
    )
    endpoint_fit_score = _distance_to_score(
        endpoint_fit_distance,
        scale_m=float(params.get("GEOMETRY_REFINE_ENDPOINT_FIT_SCORE_SCALE_M", 3.0)),
    )
    geometry_score = _distance_to_score(
        geometry_offset,
        scale_m=float(params.get("GEOMETRY_REFINE_GEOMETRY_SCORE_SCALE_M", 6.0)),
    )
    centering_score = (
        _distance_to_score(
            center_offset,
            scale_m=float(params.get("GEOMETRY_REFINE_CENTERING_SCORE_SCALE_M", 4.0)),
        )
        if lane_boundary_line is not None
        else geometry_score
    )
    smoothness_score = max(
        0.0,
        min(
            1.0,
            1.0 - float(smoothness_angle_deg) / max(float(params.get("GEOMETRY_REFINE_SMOOTHNESS_CAP_DEG", 55.0)), 1.0),
        ),
    )
    drivezone_score = max(
        0.0,
        min(
            1.0,
            (float(drivezone_ratio) - float(hard_min_drivezone_ratio)) / max(1e-6, 1.0 - float(hard_min_drivezone_ratio)),
        ),
    )
    anchor_score = max(
        0.0,
        min(1.0, 0.55 * endpoint_fit_score + 0.45 * ((float(entry_anchor_confidence) + float(exit_anchor_confidence)) / 2.0)),
    )
    geometry_quality_score = max(
        0.0,
        min(1.0, 0.6 * geometry_score + 0.4 * centering_score),
    )
    total_score = (
        0.30 * geometry_quality_score
        + 0.22 * anchor_score
        + 0.18 * centering_score
        + 0.16 * smoothness_score
        + 0.14 * drivezone_score
    )
    return {
        "ok": (not road_intersects_divstrip) and drivezone_ratio >= hard_min_drivezone_ratio,
        "drivezone_ratio": float(drivezone_ratio),
        "divstrip_overlap_ratio": float(divstrip_overlap_ratio),
        "road_intersects_divstrip": bool(road_intersects_divstrip),
        "hard_min_drivezone_ratio": float(hard_min_drivezone_ratio),
        "candidate_total_score": float(total_score),
        "candidate_geometry_score": float(geometry_quality_score),
        "candidate_anchor_score": float(anchor_score),
        "candidate_centering_score": float(centering_score),
        "candidate_smoothness_score": float(smoothness_score),
        "candidate_drivezone_score": float(drivezone_score),
        "center_offset_score": float(centering_score),
        "endpoint_fit_score": float(endpoint_fit_score),
        "smoothness_score": float(smoothness_score),
        "center_offset_m": float(center_offset),
        "geometry_offset_m": float(geometry_offset),
        "endpoint_fit_distance_m": float(endpoint_fit_distance),
        "smoothness_angle_deg": float(smoothness_angle_deg),
    }


def _refine_built_road_geometry(
    *,
    road: FinalRoad,
    segment: Segment,
    identity: CorridorIdentity,
    witness: CorridorWitness | None,
    src_slot: SlotInterval,
    dst_slot: SlotInterval,
    build_result: dict[str, Any],
    inputs: Any,
    prior_roads: list[Any],
    params: dict[str, Any],
    arc_row: dict[str, Any] | None = None,
    prior_index: dict[tuple[int, int], list[Any]] | None = None,
    divstrip_buffer: Any | None = None,
) -> tuple[FinalRoad, dict[str, Any], dict[str, list[tuple[Any, dict[str, Any]]]]]:
    pipeline = _pipeline()
    pair = pipeline._pair_id_text(int(segment.src_nodeid), int(segment.dst_nodeid))
    original_line = road.geometry_metric()
    original_drivezone_ratio = float(pipeline._drivezone_ratio(original_line, inputs.drivezone_zone_metric))
    original_divstrip_overlap_ratio = float(_line_overlap_ratio(original_line, divstrip_buffer))
    safe_surface = _safe_surface(inputs, divstrip_buffer)
    empty_artifacts: dict[str, list[tuple[Any, dict[str, Any]]]] = {
        "traj_guided_core_line": [],
        "trusted_core_skeleton": [],
        "xsec_anchor_points": [],
        "entry_exit_segments": [],
        "safe_envelope_polygon": [],
        "refined_final_road": [],
    }
    review = {
        "pair": str(pair),
        "segment_id": str(segment.segment_id),
        "built_source_road_id": str(road.road_id),
        "built_final_road": True,
        "eligible": False,
        "applied": False,
        "skip_reason": "",
        "core_skeleton_source": "",
        "core_skeleton_source_detail": "",
        "entry_anchor_source": "",
        "exit_anchor_source": "",
        "entry_anchor_confidence": 0.0,
        "exit_anchor_confidence": 0.0,
        "anchor_confidence": 0.0,
        "entry_midpoint_fallback_used": False,
        "exit_midpoint_fallback_used": False,
        "smoothed": False,
        "lane_boundary_used": False,
        "lane_boundary_quality_score": 0.0,
        "lane_boundary_center_offset": None,
        "lane_boundary_use_reason": "",
        "traj_guided_used": False,
        "support_trend_used": False,
        "safe_envelope_applied": False,
        "safe_envelope_source": "",
        "original_road_used_as_weak_ref": False,
        "shape_ref_mode_before": str(build_result.get("shape_ref_mode", "")),
        "before_length": float(original_line.length),
        "after_length": float(original_line.length),
        "road_drivezone_overlap_ratio_before": float(original_drivezone_ratio),
        "before_drivezone_overlap_ratio": float(original_drivezone_ratio),
        "before_divstrip_overlap_ratio": float(original_divstrip_overlap_ratio),
        "road_drivezone_overlap_ratio_after": float(original_drivezone_ratio),
        "after_drivezone_overlap_ratio": float(original_drivezone_ratio),
        "road_divstrip_overlap_ratio_after": float(original_divstrip_overlap_ratio),
        "after_divstrip_overlap_ratio": float(original_divstrip_overlap_ratio),
        "before_center_offset_score": 0.0,
        "after_center_offset_score": 0.0,
        "before_endpoint_fit_score": 0.0,
        "after_endpoint_fit_score": 0.0,
        "before_smoothness_score": 0.0,
        "after_smoothness_score": 0.0,
        "candidate_total_score": 0.0,
        "candidate_geometry_score": 0.0,
        "candidate_anchor_score": 0.0,
        "candidate_centering_score": 0.0,
        "candidate_smoothness_score": 0.0,
        "candidate_drivezone_score": 0.0,
        "selected_candidate_mode": "original",
    }
    if src_slot.interval is None or dst_slot.interval is None:
        review["skip_reason"] = "slot_unresolved"
        empty_artifacts["refined_final_road"].append(
            (
                original_line,
                {
                    "pair": str(pair),
                    "segment_id": str(segment.segment_id),
                    "built_source_road_id": str(road.road_id),
                    "applied": False,
                    "smoothed": False,
                },
            )
        )
        return road, review, empty_artifacts
    slot_start_pt = _slot_surface_anchor_point(src_slot, original_line, safe_surface)
    slot_end_pt = _slot_surface_anchor_point(dst_slot, original_line, safe_surface)
    lane_boundary_line, lane_boundary_meta = _lane_boundary_centerline_for_road(
        road_line=original_line,
        lane_boundaries=tuple(inputs.lane_boundaries_metric),
        safe_surface=safe_surface,
        params=params,
    )
    lane_boundary_quality_score = float(lane_boundary_meta.get("quality_score", 0.0) or 0.0)
    review["lane_boundary_quality_score"] = lane_boundary_quality_score
    review["lane_boundary_center_offset"] = lane_boundary_meta.get("center_offset")
    review["lane_boundary_use_reason"] = str(lane_boundary_meta.get("use_reason", "") or "")
    build_shape_ref_mode = str(build_result.get("shape_ref_mode", ""))
    build_shape_ref_family = _shape_ref_source_family(build_shape_ref_mode)
    build_shape_ref_line = _line_from_coords(list(build_result.get("shape_ref_coords", [])))
    trusted_support_ref = _trusted_support_shape_ref_line(
        arc_row=arc_row,
        start_pt=slot_start_pt,
        end_pt=slot_end_pt,
    )
    traj_guided_line: LineString | None = None
    source_line: LineString | None = None
    source_label = ""
    if _segment_prefers_production_shape_ref(segment):
        if build_shape_ref_line is not None and str(build_shape_ref_family) == "production_working_segment_family":
            source_line = _anchor_along_base_line(build_shape_ref_line, slot_start_pt, slot_end_pt)
            source_label = build_shape_ref_mode or "production_working_segment_slot_anchored"
        else:
            source_line = _anchor_along_base_line(segment.geometry_metric(), slot_start_pt, slot_end_pt)
            source_label = "production_working_segment_slot_anchored"
        traj_guided_line = source_line
        review["traj_guided_used"] = True
    elif trusted_support_ref is not None:
        traj_guided_line, source_label = trusted_support_ref
        source_line = traj_guided_line
        review["support_trend_used"] = True
        review["traj_guided_used"] = True
    elif lane_boundary_line is not None and lane_boundary_quality_score >= float(params.get("GEOMETRY_REFINE_LANE_BOUNDARY_MIN_QUALITY_SCORE", 0.45)):
        source_line = _anchor_along_base_line(lane_boundary_line, slot_start_pt, slot_end_pt)
        source_label = "lane_boundary_centerline"
        review["lane_boundary_used"] = True
    elif str(identity.state) == "witness_based":
        source_line = _witness_reference_projected_line(witness=witness, start_pt=slot_start_pt, end_pt=slot_end_pt)
        source_label = "witness_reference_projected_anchored"
        if source_line is None:
            source_line = _legacy_witness_centerline(witness=witness, start_pt=slot_start_pt, end_pt=slot_end_pt)
            source_label = "witness_centerline" if source_line is not None else ""
    elif str(identity.state) == "prior_based":
        prior_line = find_prior_reference_line(segment, prior_roads, prior_index=prior_index)
        if prior_line is not None:
            source_line = _anchor_along_base_line(prior_line, slot_start_pt, slot_end_pt)
            source_label = "prior_reference_projected_anchored"
    if source_line is None:
        if build_shape_ref_line is not None and not str(build_shape_ref_mode).startswith("traj_support"):
            source_line = _anchor_along_base_line(build_shape_ref_line, slot_start_pt, slot_end_pt)
            source_label = "selected_shape_ref"
    if source_line is None or source_line.is_empty or float(source_line.length) <= 1e-6:
        review["skip_reason"] = "no_trusted_ref_source"
        empty_artifacts["refined_final_road"].append(
            (
                original_line,
                {
                    "pair": str(pair),
                    "segment_id": str(segment.segment_id),
                    "built_source_road_id": str(road.road_id),
                    "applied": False,
                    "smoothed": False,
                },
            )
        )
        return road, review, empty_artifacts
    support_dirty = str(build_result.get("shape_ref_mode", "")).startswith("traj_support") and not (
        bool((arc_row or {}).get("selected_support_interval_reference_trusted", False))
        or bool((arc_row or {}).get("stitched_support_interval_reference_trusted", False))
    )
    if support_dirty and not review["lane_boundary_used"]:
        review["skip_reason"] = "support_reference_untrusted"
        empty_artifacts["refined_final_road"].append(
            (
                original_line,
                {
                    "pair": str(pair),
                    "segment_id": str(segment.segment_id),
                    "built_source_road_id": str(road.road_id),
                    "applied": False,
                    "smoothed": False,
                },
            )
        )
        return road, review, empty_artifacts
    source_family = _geometry_refine_source_family(source_label)
    start_pt, start_anchor_info = _select_refine_anchor_point(
        slot=src_slot,
        safe_surface=safe_surface,
        arc_row=arc_row,
        source_line=source_line,
        source_family=source_family,
        endpoint_tag="src",
        witness=witness,
        params=params,
    )
    end_pt, end_anchor_info = _select_refine_anchor_point(
        slot=dst_slot,
        safe_surface=safe_surface,
        arc_row=arc_row,
        source_line=source_line,
        source_family=source_family,
        endpoint_tag="dst",
        witness=witness,
        params=params,
    )
    review["eligible"] = True
    review["core_skeleton_source"] = str(source_family)
    review["core_skeleton_source_detail"] = str(source_label)
    review["entry_anchor_source"] = str(start_anchor_info["anchor_source"])
    review["exit_anchor_source"] = str(end_anchor_info["anchor_source"])
    review["entry_anchor_confidence"] = float(start_anchor_info["anchor_confidence"])
    review["exit_anchor_confidence"] = float(end_anchor_info["anchor_confidence"])
    review["anchor_confidence"] = float(
        (float(start_anchor_info["anchor_confidence"]) + float(end_anchor_info["anchor_confidence"])) / 2.0
    )
    review["entry_midpoint_fallback_used"] = bool(start_anchor_info["anchor_midpoint_fallback_used"])
    review["exit_midpoint_fallback_used"] = bool(end_anchor_info["anchor_midpoint_fallback_used"])
    if traj_guided_line is not None:
        traj_guided_line = _anchor_along_base_line(traj_guided_line, start_pt, end_pt)
    if lane_boundary_line is not None:
        lane_boundary_line = _anchor_along_base_line(lane_boundary_line, start_pt, end_pt)
    source_line = _anchor_along_base_line(source_line, start_pt, end_pt)
    local_safe_envelope, safe_envelope_source, original_used_as_weak_ref = _local_safe_envelope(
        safe_surface=safe_surface,
        source_line=source_line,
        source_family=source_family,
        lane_boundary_line=lane_boundary_line,
        original_line=original_line,
        params=params,
    )
    review["safe_envelope_applied"] = bool(local_safe_envelope is not None and not getattr(local_safe_envelope, "is_empty", True))
    review["safe_envelope_source"] = str(safe_envelope_source)
    review["original_road_used_as_weak_ref"] = bool(original_used_as_weak_ref)
    core_input_line = source_line
    if (
        review["traj_guided_used"]
        and lane_boundary_line is not None
        and lane_boundary_quality_score >= float(params.get("GEOMETRY_REFINE_LANE_BOUNDARY_MIN_QUALITY_SCORE", 0.45))
    ):
        lane_weight = max(
            0.08,
            min(0.34, float(lane_boundary_quality_score) * float(params.get("GEOMETRY_REFINE_LANE_BOUNDARY_BLEND_MAX_WEIGHT", 0.32))),
        )
        blended_core = _blend_centerlines(
            source_line,
            lane_boundary_line,
            primary_weight=float(1.0 - lane_weight),
            step_m=float(params.get("GEOMETRY_REFINE_SMOOTH_SAMPLE_STEP_M", 8.0)),
        )
        if blended_core is not None:
            core_input_line = _anchor_along_base_line(blended_core, start_pt, end_pt)
            review["lane_boundary_used"] = True
    core_line = _surface_envelope_core_line(core_input_line, local_safe_envelope) or core_input_line
    trimmed_core = _trim_line_middle(core_line, trim_frac=float(params.get("GEOMETRY_REFINE_CORE_TRIM_FRAC", 0.15)))
    if trimmed_core is not None:
        core_line = trimmed_core
    entry_line = _curve_connector_line(
        start_pt,
        Point(core_line.coords[0][:2]),
        start_dir=_direction_unit(source_line, at_start=True),
        end_dir=_direction_unit(core_line, at_start=True),
        ctrl_frac=float(params.get("GEOMETRY_REFINE_ENTRY_EXIT_CTRL_FRAC", 0.35)),
        ctrl_min_m=float(params.get("GEOMETRY_REFINE_ENTRY_EXIT_CTRL_MIN_M", 2.5)),
        ctrl_max_m=float(params.get("GEOMETRY_REFINE_ENTRY_EXIT_CTRL_MAX_M", 14.0)),
    )
    exit_line = _curve_connector_line(
        Point(core_line.coords[-1][:2]),
        end_pt,
        start_dir=_direction_unit(core_line, at_start=False),
        end_dir=_direction_unit(source_line, at_start=False),
        ctrl_frac=float(params.get("GEOMETRY_REFINE_ENTRY_EXIT_CTRL_FRAC", 0.35)),
        ctrl_min_m=float(params.get("GEOMETRY_REFINE_ENTRY_EXIT_CTRL_MIN_M", 2.5)),
        ctrl_max_m=float(params.get("GEOMETRY_REFINE_ENTRY_EXIT_CTRL_MAX_M", 14.0)),
    )
    entry_line = entry_line if isinstance(entry_line, LineString) and not entry_line.is_empty else _line_from_coords([(start_pt.x, start_pt.y), core_line.coords[0][:2]])
    exit_line = exit_line if isinstance(exit_line, LineString) and not exit_line.is_empty else _line_from_coords([core_line.coords[-1][:2], (end_pt.x, end_pt.y)])
    refined_candidate = _combine_line_parts(entry_line, core_line, exit_line)
    if refined_candidate is None:
        review["skip_reason"] = "refine_candidate_missing"
        empty_artifacts["safe_envelope_polygon"] = (
            []
            if local_safe_envelope is None or getattr(local_safe_envelope, "is_empty", True)
            else [
                (
                    local_safe_envelope,
                    {
                        "pair": str(pair),
                        "segment_id": str(segment.segment_id),
                        "built_source_road_id": str(road.road_id),
                        "safe_envelope_applied": bool(review["safe_envelope_applied"]),
                    },
                )
            ]
        )
        empty_artifacts["trusted_core_skeleton"] = [
            (
                core_line,
                {
                    "pair": str(pair),
                    "segment_id": str(segment.segment_id),
                    "built_source_road_id": str(road.road_id),
                    "core_skeleton_source": str(review["core_skeleton_source"]),
                    "core_skeleton_source_detail": str(source_label),
                    "lane_boundary_used": bool(review["lane_boundary_used"]),
                    "traj_guided_used": bool(review["traj_guided_used"]),
                    "support_trend_used": bool(review["support_trend_used"]),
                    "applied": False,
                },
            )
        ]
        empty_artifacts["refined_final_road"] = [
            (
                original_line,
                {
                    "pair": str(pair),
                    "segment_id": str(segment.segment_id),
                    "built_source_road_id": str(road.road_id),
                    "applied": False,
                    "smoothed": False,
                },
            )
        ]
        return road, review, empty_artifacts
    smoothed_candidate = _smoothed_line(
        refined_candidate,
        step_m=float(params.get("GEOMETRY_REFINE_SMOOTH_SAMPLE_STEP_M", 8.0)),
    )
    smoothed_candidate = _replace_endpoints(smoothed_candidate, start_pt, end_pt) if smoothed_candidate is not None else None
    baseline_metrics = _geometry_refine_candidate_metrics(
        line=original_line,
        start_anchor=start_pt,
        end_anchor=end_pt,
        entry_anchor_confidence=float(review["entry_anchor_confidence"]),
        exit_anchor_confidence=float(review["exit_anchor_confidence"]),
        source_line=source_line,
        lane_boundary_line=lane_boundary_line,
        inputs=inputs,
        divstrip_buffer=divstrip_buffer,
        params=params,
    )
    review["before_center_offset_score"] = float(baseline_metrics["center_offset_score"])
    review["before_endpoint_fit_score"] = float(baseline_metrics["endpoint_fit_score"])
    review["before_smoothness_score"] = float(baseline_metrics["smoothness_score"])
    review["candidate_total_score"] = float(baseline_metrics["candidate_total_score"])
    review["candidate_geometry_score"] = float(baseline_metrics["candidate_geometry_score"])
    review["candidate_anchor_score"] = float(baseline_metrics["candidate_anchor_score"])
    review["candidate_centering_score"] = float(baseline_metrics["candidate_centering_score"])
    review["candidate_smoothness_score"] = float(baseline_metrics["candidate_smoothness_score"])
    review["candidate_drivezone_score"] = float(baseline_metrics["candidate_drivezone_score"])
    candidates: list[tuple[LineString, bool, str]] = []
    if smoothed_candidate is not None:
        candidates.append((smoothed_candidate, True, "smoothed_candidate"))
    candidates.append((refined_candidate, False, "refined_candidate"))
    selected_line = original_line
    selected_metrics = dict(baseline_metrics)
    selected_mode = "original"
    min_score_gain = float(params.get("GEOMETRY_REFINE_MIN_SCORE_GAIN", 0.03))
    for candidate_line, smoothed, candidate_mode in candidates:
        metrics = _geometry_refine_candidate_metrics(
            line=candidate_line,
            start_anchor=start_pt,
            end_anchor=end_pt,
            entry_anchor_confidence=float(review["entry_anchor_confidence"]),
            exit_anchor_confidence=float(review["exit_anchor_confidence"]),
            source_line=source_line,
            lane_boundary_line=lane_boundary_line,
            inputs=inputs,
            divstrip_buffer=divstrip_buffer,
            params=params,
        )
        if not bool(metrics["ok"]):
            continue
        if float(metrics["candidate_total_score"]) <= float(selected_metrics["candidate_total_score"]) + float(min_score_gain):
            continue
        selected_line = candidate_line
        selected_metrics = dict(metrics)
        selected_mode = str(candidate_mode)
        review["applied"] = not candidate_line.equals(original_line)
        review["smoothed"] = bool(smoothed and review["applied"])
    review["selected_candidate_mode"] = str(selected_mode)
    review["after_length"] = float(selected_line.length)
    review["road_drivezone_overlap_ratio_after"] = float(selected_metrics["drivezone_ratio"])
    review["after_drivezone_overlap_ratio"] = float(selected_metrics["drivezone_ratio"])
    review["road_divstrip_overlap_ratio_after"] = float(selected_metrics["divstrip_overlap_ratio"])
    review["after_divstrip_overlap_ratio"] = float(selected_metrics["divstrip_overlap_ratio"])
    review["road_intersects_divstrip_after"] = bool(selected_metrics["road_intersects_divstrip"])
    review["after_center_offset_score"] = float(selected_metrics["center_offset_score"])
    review["after_endpoint_fit_score"] = float(selected_metrics["endpoint_fit_score"])
    review["after_smoothness_score"] = float(selected_metrics["smoothness_score"])
    review["candidate_total_score"] = float(selected_metrics["candidate_total_score"])
    review["candidate_geometry_score"] = float(selected_metrics["candidate_geometry_score"])
    review["candidate_anchor_score"] = float(selected_metrics["candidate_anchor_score"])
    review["candidate_centering_score"] = float(selected_metrics["candidate_centering_score"])
    review["candidate_smoothness_score"] = float(selected_metrics["candidate_smoothness_score"])
    review["candidate_drivezone_score"] = float(selected_metrics["candidate_drivezone_score"])
    artifacts: dict[str, list[tuple[Any, dict[str, Any]]]] = {
        "traj_guided_core_line": [],
        "trusted_core_skeleton": [],
        "xsec_anchor_points": [
            (
                start_pt,
                {
                    "pair": str(pair),
                    "segment_id": str(segment.segment_id),
                    "built_source_road_id": str(road.road_id),
                    "endpoint_tag": "src",
                    "anchor_source": str(review["entry_anchor_source"]),
                    "anchor_confidence": float(review["entry_anchor_confidence"]),
                    "anchor_midpoint_fallback_used": bool(review["entry_midpoint_fallback_used"]),
                    "applied": bool(review["applied"]),
                },
            ),
            (
                end_pt,
                {
                    "pair": str(pair),
                    "segment_id": str(segment.segment_id),
                    "built_source_road_id": str(road.road_id),
                    "endpoint_tag": "dst",
                    "anchor_source": str(review["exit_anchor_source"]),
                    "anchor_confidence": float(review["exit_anchor_confidence"]),
                    "anchor_midpoint_fallback_used": bool(review["exit_midpoint_fallback_used"]),
                    "applied": bool(review["applied"]),
                },
            ),
        ],
        "entry_exit_segments": [],
        "safe_envelope_polygon": [],
        "refined_final_road": [],
    }
    if traj_guided_line is not None:
        artifacts["traj_guided_core_line"].append(
            (
                traj_guided_line,
                {
                    "pair": str(pair),
                    "segment_id": str(segment.segment_id),
                    "built_source_road_id": str(road.road_id),
                    "core_skeleton_source": "traj_guided",
                    "source_detail": str(source_label),
                    "lane_boundary_quality_score": float(review["lane_boundary_quality_score"]),
                    "applied": bool(review["applied"]),
                },
            )
        )
    artifacts["trusted_core_skeleton"].append(
        (
            core_line,
            {
                "pair": str(pair),
                "segment_id": str(segment.segment_id),
                "built_source_road_id": str(road.road_id),
                "core_skeleton_source": str(review["core_skeleton_source"]),
                "core_skeleton_source_detail": str(source_label),
                "lane_boundary_used": bool(review["lane_boundary_used"]),
                "traj_guided_used": bool(review["traj_guided_used"]),
                "support_trend_used": bool(review["support_trend_used"]),
                "lane_boundary_quality_score": float(review["lane_boundary_quality_score"]),
                "applied": bool(review["applied"]),
            },
        )
    )
    artifacts["entry_exit_segments"].extend(
        [
            (
                entry_line,
                {
                    "pair": str(pair),
                    "segment_id": str(segment.segment_id),
                    "built_source_road_id": str(road.road_id),
                    "role": "entry",
                    "anchor_source": str(review["entry_anchor_source"]),
                    "anchor_confidence": float(review["entry_anchor_confidence"]),
                    "anchor_midpoint_fallback_used": bool(review["entry_midpoint_fallback_used"]),
                    "applied": bool(review["applied"]),
                },
            ),
            (
                exit_line,
                {
                    "pair": str(pair),
                    "segment_id": str(segment.segment_id),
                    "built_source_road_id": str(road.road_id),
                    "role": "exit",
                    "anchor_source": str(review["exit_anchor_source"]),
                    "anchor_confidence": float(review["exit_anchor_confidence"]),
                    "anchor_midpoint_fallback_used": bool(review["exit_midpoint_fallback_used"]),
                    "applied": bool(review["applied"]),
                },
            ),
        ]
    )
    if local_safe_envelope is not None and not getattr(local_safe_envelope, "is_empty", True):
        artifacts["safe_envelope_polygon"].append(
            (
                local_safe_envelope,
                {
                    "pair": str(pair),
                    "segment_id": str(segment.segment_id),
                    "built_source_road_id": str(road.road_id),
                    "safe_envelope_applied": bool(review["safe_envelope_applied"]),
                    "safe_envelope_source": str(review["safe_envelope_source"]),
                    "original_road_used_as_weak_ref": bool(review["original_road_used_as_weak_ref"]),
                    "lane_boundary_used": bool(review["lane_boundary_used"]),
                    "traj_guided_used": bool(review["traj_guided_used"]),
                },
            )
        )
    if not review["applied"]:
        review["skip_reason"] = review["skip_reason"] or "kept_original_geometry"
        review["after_length"] = float(original_line.length)
        review["road_drivezone_overlap_ratio_after"] = float(original_drivezone_ratio)
        review["after_drivezone_overlap_ratio"] = float(original_drivezone_ratio)
        review["road_divstrip_overlap_ratio_after"] = float(original_divstrip_overlap_ratio)
        review["after_divstrip_overlap_ratio"] = float(original_divstrip_overlap_ratio)
        artifacts["refined_final_road"].append(
            (
                original_line,
                {
                    "pair": str(pair),
                    "segment_id": str(segment.segment_id),
                    "built_source_road_id": str(road.road_id),
                    "applied": False,
                    "smoothed": False,
                },
            )
        )
        return road, review, artifacts
    refined_road = replace(
        road,
        line_coords=line_to_coords(selected_line),
        length_m=float(selected_line.length),
    )
    artifacts["refined_final_road"].append(
        (
            selected_line,
            {
                "pair": str(pair),
                "segment_id": str(segment.segment_id),
                "built_source_road_id": str(road.road_id),
                    "applied": True,
                    "smoothed": bool(review["smoothed"]),
                    "selected_candidate_mode": str(review["selected_candidate_mode"]),
                    "before_length": float(review["before_length"]),
                    "after_length": float(review["after_length"]),
                    "before_drivezone_overlap_ratio": float(review["before_drivezone_overlap_ratio"]),
                    "after_drivezone_overlap_ratio": float(review["after_drivezone_overlap_ratio"]),
                    "before_endpoint_fit_score": float(review["before_endpoint_fit_score"]),
                    "after_endpoint_fit_score": float(review["after_endpoint_fit_score"]),
                    "before_center_offset_score": float(review["before_center_offset_score"]),
                    "after_center_offset_score": float(review["after_center_offset_score"]),
                    "before_smoothness_score": float(review["before_smoothness_score"]),
                    "after_smoothness_score": float(review["after_smoothness_score"]),
                },
            )
        )
    return refined_road, review, artifacts


def _apply_geometry_refine(
    *,
    segments: list[Segment],
    identities: dict[str, CorridorIdentity],
    witnesses: dict[str, CorridorWitness],
    slots: dict[str, dict[str, SlotInterval]],
    roads: list[FinalRoad],
    road_results: list[dict[str, Any]],
    inputs: Any,
    prior_roads: list[Any],
    params: dict[str, Any],
    full_registry_rows: list[dict[str, Any]] | None = None,
    prior_index: dict[tuple[int, int], list[Any]] | None = None,
    divstrip_buffer: Any | None = None,
) -> tuple[list[FinalRoad], list[dict[str, Any]], dict[str, list[tuple[Any, dict[str, Any]]]], dict[str, Any]]:
    if not bool(params.get("GEOMETRY_REFINE_ENABLE", 1)):
        return roads, road_results, {}, {"rows": [], "summary": {"enable": False, "road_count": int(len(roads))}}
    road_map = {str(road.segment_id): road for road in roads}
    result_map = {str(item.get("segment_id", "")): dict(item) for item in road_results if str(item.get("segment_id", ""))}
    registry_by_working_segment = {
        str(item.get("working_segment_id", "")): dict(item)
        for item in list(full_registry_rows or [])
        if str(item.get("working_segment_id", ""))
    }
    registry_by_arc_id = {
        str(item.get("topology_arc_id", "")): dict(item)
        for item in list(full_registry_rows or [])
        if str(item.get("topology_arc_id", ""))
    }
    refined_roads: list[FinalRoad] = []
    artifact_features: dict[str, list[tuple[Any, dict[str, Any]]]] = {
        "traj_guided_core_line": [],
        "trusted_core_skeleton": [],
        "xsec_anchor_points": [],
        "entry_exit_segments": [],
        "safe_envelope_polygon": [],
        "refined_final_road": [],
    }
    review_rows: list[dict[str, Any]] = []
    for segment in segments:
        road = road_map.get(str(segment.segment_id))
        if road is None:
            continue
        refined_road, review, local_artifacts = _refine_built_road_geometry(
            road=road,
            segment=segment,
            identity=identities[str(segment.segment_id)],
            witness=witnesses.get(str(segment.segment_id)),
            src_slot=slots[str(segment.segment_id)]["src"],
            dst_slot=slots[str(segment.segment_id)]["dst"],
            build_result=result_map.get(str(segment.segment_id), {}),
            inputs=inputs,
            prior_roads=prior_roads,
            params=params,
            arc_row=registry_by_working_segment.get(str(segment.segment_id))
            or registry_by_arc_id.get(str(segment.topology_arc_id))
            or {},
            prior_index=prior_index,
            divstrip_buffer=divstrip_buffer,
        )
        result_map.setdefault(str(segment.segment_id), {})
        result_map[str(segment.segment_id)].update(
            {
                "geometry_refine_eligible": bool(review["eligible"]),
                "geometry_refine_applied": bool(review["applied"]),
                "geometry_refine_skip_reason": str(review["skip_reason"]),
                "geometry_refine_core_skeleton_source": str(review["core_skeleton_source"]),
                "geometry_refine_core_skeleton_source_detail": str(review["core_skeleton_source_detail"]),
                "geometry_refine_entry_anchor_source": str(review["entry_anchor_source"]),
                "geometry_refine_exit_anchor_source": str(review["exit_anchor_source"]),
                "geometry_refine_entry_anchor_confidence": float(review["entry_anchor_confidence"]),
                "geometry_refine_exit_anchor_confidence": float(review["exit_anchor_confidence"]),
                "geometry_refine_entry_midpoint_fallback_used": bool(review["entry_midpoint_fallback_used"]),
                "geometry_refine_exit_midpoint_fallback_used": bool(review["exit_midpoint_fallback_used"]),
                "geometry_refine_smoothed": bool(review["smoothed"]),
                "geometry_refine_lane_boundary_used": bool(review["lane_boundary_used"]),
                "geometry_refine_lane_boundary_quality_score": float(review["lane_boundary_quality_score"]),
                "geometry_refine_lane_boundary_use_reason": str(review["lane_boundary_use_reason"]),
                "geometry_refine_traj_guided_used": bool(review["traj_guided_used"]),
                "geometry_refine_support_trend_used": bool(review["support_trend_used"]),
                "geometry_refine_safe_envelope_applied": bool(review["safe_envelope_applied"]),
                "geometry_refine_safe_envelope_source": str(review["safe_envelope_source"]),
                "geometry_refine_original_road_used_as_weak_ref": bool(review["original_road_used_as_weak_ref"]),
                "geometry_refine_before_length": float(review["before_length"]),
                "geometry_refine_after_length": float(review["after_length"]),
                "geometry_refine_drivezone_ratio_before": float(review["before_drivezone_overlap_ratio"]),
                "geometry_refine_drivezone_ratio_after": float(review["road_drivezone_overlap_ratio_after"]),
                "geometry_refine_divstrip_overlap_ratio_before": float(review["before_divstrip_overlap_ratio"]),
                "geometry_refine_divstrip_overlap_ratio_after": float(review["road_divstrip_overlap_ratio_after"]),
                "geometry_refine_before_center_offset_score": float(review["before_center_offset_score"]),
                "geometry_refine_after_center_offset_score": float(review["after_center_offset_score"]),
                "geometry_refine_before_endpoint_fit_score": float(review["before_endpoint_fit_score"]),
                "geometry_refine_after_endpoint_fit_score": float(review["after_endpoint_fit_score"]),
                "geometry_refine_before_smoothness_score": float(review["before_smoothness_score"]),
                "geometry_refine_after_smoothness_score": float(review["after_smoothness_score"]),
                "geometry_refine_candidate_total_score": float(review["candidate_total_score"]),
                "geometry_refine_selected_candidate_mode": str(review["selected_candidate_mode"]),
            }
        )
        refined_roads.append(refined_road)
        review_rows.append(review)
        for key, rows in local_artifacts.items():
            artifact_features.setdefault(str(key), []).extend(list(rows or []))
    summary = {
        "enable": True,
        "road_count": int(len(roads)),
        "reviewed_count": int(len(review_rows)),
        "eligible_count": int(sum(1 for row in review_rows if bool(row.get("eligible", False)))),
        "applied_count": int(sum(1 for row in review_rows if bool(row.get("applied", False)))),
        "smoothed_count": int(sum(1 for row in review_rows if bool(row.get("smoothed", False)))),
        "lane_boundary_used_count": int(sum(1 for row in review_rows if bool(row.get("lane_boundary_used", False)))),
        "traj_guided_used_count": int(sum(1 for row in review_rows if bool(row.get("traj_guided_used", False)))),
        "support_trend_used_count": int(sum(1 for row in review_rows if bool(row.get("support_trend_used", False)))),
        "safe_envelope_applied_count": int(sum(1 for row in review_rows if bool(row.get("safe_envelope_applied", False)))),
        "entry_midpoint_fallback_count": int(sum(1 for row in review_rows if bool(row.get("entry_midpoint_fallback_used", False)))),
        "exit_midpoint_fallback_count": int(sum(1 for row in review_rows if bool(row.get("exit_midpoint_fallback_used", False)))),
        "skip_reason_hist": dict(Counter(str(row.get("skip_reason", "") or "-") for row in review_rows if str(row.get("skip_reason", "") or "-") != "-")),
    }
    ordered_results = [result_map[str(item.get("segment_id", ""))] for item in road_results if str(item.get("segment_id", "")) in result_map]
    return refined_roads, ordered_results, artifact_features, {"rows": review_rows, "summary": summary}


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
    arc_row: dict[str, Any] | None = None,
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
    nearest = _safe_nearest_points(xsec_line, line)
    ref_point = nearest[0] if nearest is not None else pipeline._midpoint_of_interval(intervals[0]) if intervals else Point()
    ref_s = _safe_line_project(xsec_line, ref_point)
    if ref_s is None:
        ref_s = float(intervals[0].center_s) if intervals else 0.0
    desired_rank = identity.witness_interval_rank if str(identity.state) == "witness_based" else None
    interval = None
    method = "unresolved"
    reason = "no_legal_interval"
    anchor_tolerance_m = float(params.get("STEP5_SLOT_ANCHOR_TOL_M", 0.75))
    if len(intervals) > 1:
        for anchor_coords, label in _slot_anchor_candidates(
            arc_row=arc_row,
            endpoint_tag=endpoint_tag,
            trusted_only=True,
        ):
            interval, method, reason = _resolve_interval_from_anchor(
                intervals=intervals,
                xsec_line=xsec_line,
                anchor_coords=anchor_coords,
                tolerance_m=anchor_tolerance_m,
                label=label,
            )
            if interval is not None:
                break
    if (
        interval is None
        and
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
    if interval is None and len(intervals) > 1:
        for anchor_coords, label in _slot_anchor_candidates(
            arc_row=arc_row,
            endpoint_tag=endpoint_tag,
            trusted_only=False,
        ):
            interval, method, reason = _resolve_interval_from_anchor(
                intervals=intervals,
                xsec_line=xsec_line,
                anchor_coords=anchor_coords,
                tolerance_m=anchor_tolerance_m,
                label=label,
            )
            if interval is not None:
                break
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
        "shape_ref_source_family": "",
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
        "same_pair_arc_finalize_allowed": bool(getattr(segment, "same_pair_arc_finalize_allowed", False)),
        "multi_arc_evidence_mode": str(segment.multi_arc_evidence_mode),
        "multi_arc_structure_type": str(segment.multi_arc_structure_type),
        "multi_arc_rule_reason": str(segment.multi_arc_rule_reason),
        "blocked_diagnostic_only": bool(segment.blocked_diagnostic_only),
        "controlled_entry_allowed": bool(segment.controlled_entry_allowed),
        "hard_block_reason": str(segment.hard_block_reason),
        "topology_gap_decision": str(segment.topology_gap_decision),
        "topology_gap_reason": str(segment.topology_gap_reason),
        "reject_stage": "",
        "endpoint_anchor_policy": "slot_interval_surface",
        "support_candidate_policy": str(_support_candidate_policy(segment)),
        "rcsdroad_fallback_applied": False,
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
    elif (
        has_topology_assignment
        and not bool(segment.topology_arc_is_unique)
        and not bool(segment.production_multi_arc_allowed)
        and not bool(getattr(segment, "same_pair_arc_finalize_allowed", False))
    ):
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
            arc_row=arc_row,
            prior_index=prior_index,
        )
        result["shape_ref_mode"] = str(fallback_mode)
        result["shape_ref_source_family"] = str(_shape_ref_source_family(fallback_mode))
        result["shape_ref_coords"] = [[float(x), float(y)] for x, y in line_to_coords(fallback_shape_ref)]
        result["bridge_decision_stage"] = "bridge_final_decision" if bridge_retained else str(result["bridge_decision_stage"])
        result["bridge_decision_reason"] = "bridge_slot_not_established" if bridge_retained else str(result["bridge_decision_reason"])
        result["reason"] = "bridge_slot_not_established" if bridge_retained else "slot_unresolved"
        return None, result
    safe_surface = _safe_surface(inputs, divstrip_buffer)
    preferred_line, preferred_mode = shape_ref_line(
        segment=segment,
        identity=identity,
        witness=witness,
        src_slot=src_slot,
        dst_slot=dst_slot,
        prior_roads=prior_roads,
        arc_row=arc_row,
        prior_index=prior_index,
    )
    start_pt = _slot_surface_anchor_point(src_slot, preferred_line, safe_surface)
    end_pt = _slot_surface_anchor_point(dst_slot, preferred_line, safe_surface)
    candidate_lines: list[tuple[LineString, str]] = [(preferred_line, str(preferred_mode))]
    preferred_envelope = _surface_envelope_candidate_line(preferred_line, src_slot, dst_slot, safe_surface)
    _append_candidate_line(candidate_lines, preferred_envelope, f"{preferred_mode}_safe_envelope", priority=True)
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
        legacy_envelope = _surface_envelope_candidate_line(legacy_centerline, src_slot, dst_slot, safe_surface)
        _append_candidate_line(candidate_lines, legacy_envelope, "witness_centerline_safe_envelope")
        _append_side_constrained_candidates(
            candidate_lines,
            legacy_centerline,
            "witness_centerline",
            start_pt=start_pt,
            end_pt=end_pt,
        )
    support_reference_line = _line_from_coords(list((arc_row or {}).get("support_reference_coords", [])))
    if support_reference_line is not None and bool(_allow_support_reference_candidates(segment)):
        prefer_support_trend_extension = (
            str(getattr(segment, "topology_gap_decision", "")) == "gap_enter_mainflow"
            and str((arc_row or {}).get("traj_support_type", "")) == "partial_arc_support"
            and not bool((arc_row or {}).get("support_full_xsec_crossing", False))
        )
        support_trend_safe = _rcsdroad_trend_extended_candidate_line(
            support_reference_line,
            src_slot,
            dst_slot,
            safe_surface=safe_surface,
            use_safe_core=True,
        )
        _append_candidate_line(
            candidate_lines,
            support_trend_safe,
            "traj_support_trend_extended_safe_envelope",
            priority=bool(prefer_support_trend_extension),
        )
        support_trend = _rcsdroad_trend_extended_candidate_line(
            support_reference_line,
            src_slot,
            dst_slot,
            safe_surface=safe_surface,
            use_safe_core=False,
        )
        _append_candidate_line(
            candidate_lines,
            support_trend,
            "traj_support_trend_extended",
            priority=bool(prefer_support_trend_extension),
        )
        support_anchor = _anchor_line_to_slot_intervals(
            support_reference_line,
            src_slot,
            dst_slot,
            safe_surface=safe_surface,
        )
        _append_candidate_line(
            candidate_lines,
            support_anchor,
            "traj_support_slot_anchored",
        )
        support_envelope = _surface_envelope_candidate_line(support_anchor, src_slot, dst_slot, safe_surface)
        _append_candidate_line(
            candidate_lines,
            support_envelope,
            "traj_support_slot_anchored_safe_envelope",
        )
        _append_side_constrained_candidates(
            candidate_lines,
            support_anchor,
            "traj_support_slot_anchored",
            start_pt=start_pt,
            end_pt=end_pt,
        )
    segment_projected = _anchor_line_to_slot_intervals(
        segment.geometry_metric(),
        src_slot,
        dst_slot,
        safe_surface=None,
    )
    _append_candidate_line(candidate_lines, segment_projected, "production_working_segment_projected_anchored")
    segment_envelope = _surface_envelope_candidate_line(segment_projected, src_slot, dst_slot, safe_surface)
    _append_candidate_line(candidate_lines, segment_envelope, "production_working_segment_projected_anchored_safe_envelope")
    _append_side_constrained_candidates(
        candidate_lines,
        segment_projected,
        "production_working_segment_projected_anchored",
        start_pt=start_pt,
        end_pt=end_pt,
    )
    segment_anchor = _anchor_line_to_slot_intervals(
        segment.geometry_metric(),
        src_slot,
        dst_slot,
        safe_surface=safe_surface,
    )
    if not segment_anchor.equals(preferred_line):
        _append_candidate_line(candidate_lines, segment_anchor, "production_working_segment_slot_anchored")
        segment_anchor_envelope = _surface_envelope_candidate_line(segment_anchor, src_slot, dst_slot, safe_surface)
        _append_candidate_line(candidate_lines, segment_anchor_envelope, "production_working_segment_slot_anchored_safe_envelope")
    prior_line = find_prior_reference_line(segment, prior_roads, prior_index=prior_index)
    if prior_line is not None:
        prior_projected = _anchor_line_to_slot_intervals(
            prior_line,
            src_slot,
            dst_slot,
            safe_surface=None,
        )
        _append_candidate_line(
            candidate_lines,
            prior_projected,
            "prior_reference_projected_anchored",
            priority=str(identity.state) == "prior_based",
        )
        prior_envelope = _surface_envelope_candidate_line(prior_projected, src_slot, dst_slot, safe_surface)
        _append_candidate_line(
            candidate_lines,
            prior_envelope,
            "prior_reference_projected_anchored_safe_envelope",
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
        prior_anchor = _anchor_line_to_slot_intervals(
            prior_line,
            src_slot,
            dst_slot,
            safe_surface=safe_surface,
        )
        _append_candidate_line(
            candidate_lines,
            prior_anchor,
            "prior_reference_slot_anchored",
            priority=str(identity.state) == "prior_based",
        )
        prior_anchor_envelope = _surface_envelope_candidate_line(prior_anchor, src_slot, dst_slot, safe_surface)
        _append_candidate_line(
            candidate_lines,
            prior_anchor_envelope,
            "prior_reference_slot_anchored_safe_envelope",
            priority=str(identity.state) == "prior_based",
        )
    topology_arc_line = _line_from_coords(list((arc_row or {}).get("line_coords", [])))
    if topology_arc_line is not None:
        prefer_topology_arc_trend = (
            str(getattr(segment, "topology_gap_decision", "")) == "gap_enter_mainflow"
            and str((arc_row or {}).get("traj_support_type", "")) == "partial_arc_support"
            and not bool((arc_row or {}).get("support_full_xsec_crossing", False))
        )
        topology_arc_trend_safe = _rcsdroad_trend_extended_candidate_line(
            topology_arc_line,
            src_slot,
            dst_slot,
            safe_surface=safe_surface,
            use_safe_core=True,
        )
        _append_candidate_line(
            candidate_lines,
            topology_arc_trend_safe,
            "topology_arc_trend_extended_safe_envelope",
            priority=bool(prefer_topology_arc_trend),
        )
        topology_arc_trend = _rcsdroad_trend_extended_candidate_line(
            topology_arc_line,
            src_slot,
            dst_slot,
            safe_surface=safe_surface,
            use_safe_core=False,
        )
        _append_candidate_line(
            candidate_lines,
            topology_arc_trend,
            "topology_arc_trend_extended",
            priority=bool(prefer_topology_arc_trend),
        )
        topology_arc_projected = _anchor_line_to_slot_intervals(
            topology_arc_line,
            src_slot,
            dst_slot,
            safe_surface=None,
        )
        _append_candidate_line(
            candidate_lines,
            topology_arc_projected,
            "topology_arc_projected_anchored",
            priority=bool(prefer_topology_arc_trend),
        )
        topology_arc_envelope = _surface_envelope_candidate_line(topology_arc_projected, src_slot, dst_slot, safe_surface)
        _append_candidate_line(
            candidate_lines,
            topology_arc_envelope,
            "topology_arc_projected_anchored_safe_envelope",
            priority=bool(prefer_topology_arc_trend),
        )
    rcsdroad_priority = str(segment.topology_gap_reason) == "gap_small_terminal_gap_candidate"
    rcsdroad_base_line = _rcsdroad_fallback_base_line(
        segment=segment,
        arc_row=arc_row,
        prior_roads=prior_roads,
        prior_index=prior_index,
    )
    if rcsdroad_priority:
        rcsdroad_trend = _rcsdroad_trend_extended_candidate_line(
            rcsdroad_base_line,
            src_slot,
            dst_slot,
            safe_surface=safe_surface,
            use_safe_core=False,
        )
        _append_candidate_line(candidate_lines, rcsdroad_trend, "rcsdroad_trend_extended", priority=True)
        rcsdroad_trend_safe = _rcsdroad_trend_extended_candidate_line(
            rcsdroad_base_line,
            src_slot,
            dst_slot,
            safe_surface=safe_surface,
            use_safe_core=True,
        )
        _append_candidate_line(
            candidate_lines,
            rcsdroad_trend_safe,
            "rcsdroad_trend_extended_safe_envelope",
            priority=True,
        )
    else:
        rcsdroad_trend_safe = _rcsdroad_trend_extended_candidate_line(
            rcsdroad_base_line,
            src_slot,
            dst_slot,
            safe_surface=safe_surface,
            use_safe_core=True,
        )
        _append_candidate_line(candidate_lines, rcsdroad_trend_safe, "rcsdroad_trend_extended_safe_envelope")
        rcsdroad_trend = _rcsdroad_trend_extended_candidate_line(
            rcsdroad_base_line,
            src_slot,
            dst_slot,
            safe_surface=safe_surface,
            use_safe_core=False,
        )
        _append_candidate_line(candidate_lines, rcsdroad_trend, "rcsdroad_trend_extended")
    attempts: list[dict[str, Any]] = []
    selected_candidate: tuple[LineString, str, float, float, bool] | None = None
    best_candidate: tuple[LineString, str, float, float, bool] | None = None
    rcsdroad_fallback_candidate: tuple[LineString, str, float, float, bool] | None = None
    attempted_side_constrained = False
    relaxed_small_gap_modes = {
        "traj_support_trend_extended_safe_envelope",
        "traj_support_trend_extended",
        "traj_support_slot_anchored",
        "traj_support_slot_anchored_safe_envelope",
        "topology_arc_trend_extended_safe_envelope",
        "topology_arc_trend_extended",
        "topology_arc_projected_anchored",
        "topology_arc_projected_anchored_safe_envelope",
        "rcsdroad_trend_extended_safe_envelope",
        "rcsdroad_trend_extended",
    }
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
        if (
            str(mode).startswith("rcsdroad_trend_extended")
            and not road_intersects_divstrip
            and float(drivezone_ratio) >= float(
                params.get(
                    "ROAD_RCSDROAD_FALLBACK_MIN_DRIVEZONE_RATIO",
                    params.get("ROAD_SMALL_GAP_RELAXED_DRIVEZONE_RATIO", 0.65),
                )
            )
        ):
            if rcsdroad_fallback_candidate is None or (
                float(drivezone_ratio),
                float(-divstrip_overlap_ratio),
            ) > (
                float(rcsdroad_fallback_candidate[2]),
                float(-rcsdroad_fallback_candidate[3]),
            ):
                rcsdroad_fallback_candidate = candidate
        min_drivezone_ratio = float(params["ROAD_MIN_DRIVEZONE_RATIO"])
        if (
            str(getattr(segment, "topology_gap_reason", "")) == "gap_small_terminal_gap_candidate"
            and str(getattr(segment, "topology_gap_decision", "")) == "gap_enter_mainflow"
            and str(mode) in relaxed_small_gap_modes
        ):
            min_drivezone_ratio = min(
                float(min_drivezone_ratio),
                float(params.get("ROAD_SMALL_GAP_RELAXED_DRIVEZONE_RATIO", 0.65)),
            )
        if drivezone_ratio >= float(min_drivezone_ratio) and not road_intersects_divstrip:
            selected_candidate = candidate
            break
    if selected_candidate is None and rcsdroad_fallback_candidate is not None:
        selected_candidate = rcsdroad_fallback_candidate
        result["rcsdroad_fallback_applied"] = True
    chosen_line, chosen_mode, drivezone_ratio, divstrip_overlap_ratio, road_intersects_divstrip = selected_candidate or best_candidate or (
        preferred_line,
        str(preferred_mode),
        0.0,
        0.0,
        False,
    )
    result["candidate_attempts"] = attempts
    result["shape_ref_mode"] = str(chosen_mode)
    result["shape_ref_source_family"] = str(_shape_ref_source_family(chosen_mode))
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
    geometry_refine_review: dict[str, Any] | None = None,
    geometry_refine_artifacts: dict[str, list[tuple[Any, dict[str, Any]]]] | None = None,
) -> None:
    pipeline = _pipeline()
    patch_geometry_cache = build_patch_geometry_cache(inputs, params or pipeline.DEFAULT_PARAMS)
    divstrip_buffer = patch_geometry_cache.get("divstrip_buffer")
    patch_dir = pipeline.patch_root(out_root, run_id, patch_id)
    dbg_dir = pipeline.debug_dir(out_root, run_id, patch_id)
    geometry_refine_review = dict(geometry_refine_review or {"rows": [], "summary": {}})
    geometry_refine_artifacts = dict(geometry_refine_artifacts or {})
    geometry_refine_traj_guided_features = list(geometry_refine_artifacts.get("traj_guided_core_line") or [])
    geometry_refine_core_features = list(geometry_refine_artifacts.get("trusted_core_skeleton") or [])
    geometry_refine_anchor_features = list(geometry_refine_artifacts.get("xsec_anchor_points") or [])
    geometry_refine_entry_exit_features = list(geometry_refine_artifacts.get("entry_exit_segments") or [])
    geometry_refine_safe_envelope_features = list(geometry_refine_artifacts.get("safe_envelope_polygon") or [])
    geometry_refine_refined_road_features = list(geometry_refine_artifacts.get("refined_final_road") or [])
    road_features: list[tuple[LineString, dict[str, Any]]] = []
    shape_ref_features: list[tuple[LineString, dict[str, Any]]] = []
    metrics_segments: list[dict[str, Any]] = []
    hard_breakpoints: list[dict[str, Any]] = []
    soft_breakpoints: list[dict[str, Any]] = []
    road_trace_entries: list[dict[str, Any]] = []
    bridge_trial_entries: list[dict[str, Any]] = []
    road_map = {str(road.segment_id): road for road in roads}
    result_map = {str(item["segment_id"]): item for item in road_results}
    registry_by_working_segment = {
        str(item.get("working_segment_id", "")): dict(item)
        for item in list(full_registry_rows or [])
        if str(item.get("working_segment_id", ""))
    }
    registry_by_arc_id = {
        str(item.get("topology_arc_id", "")): dict(item)
        for item in list(full_registry_rows or [])
        if str(item.get("topology_arc_id", ""))
    }
    geometry_input_source_rows: list[dict[str, Any]] = []
    for segment in segments:
        identity = identities[str(segment.segment_id)]
        witness = witnesses.get(str(segment.segment_id))
        src_slot = slots[str(segment.segment_id)]["src"]
        dst_slot = slots[str(segment.segment_id)]["dst"]
        build_result = result_map.get(str(segment.segment_id), {})
        registry_row = (
            registry_by_working_segment.get(str(segment.segment_id))
            or registry_by_arc_id.get(str(segment.topology_arc_id))
            or {}
        )
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
                    "shape_ref_mode": str(build_result.get("shape_ref_mode", "production_working_segment")),
                    "shape_ref_source_family": str(
                        build_result.get(
                            "shape_ref_source_family",
                            _shape_ref_source_family(build_result.get("shape_ref_mode", "")),
                        )
                    ),
                    "no_geometry_candidate": bool(str(build_result.get("reason", "")) != "built"),
                    "no_geometry_reason": str(build_result.get("reason", "")),
                    "geometry_role": str(segment.geometry_role),
                    "geometry_source_type": str(segment.geometry_source_type),
                    "topology_arc_id": str(segment.topology_arc_id),
                    "topology_arc_source_type": str(segment.topology_arc_source_type),
                    "topology_arc_is_direct_legal": bool(segment.topology_arc_is_direct_legal),
                    "topology_arc_is_unique": bool(segment.topology_arc_is_unique),
                    "production_multi_arc_allowed": bool(segment.production_multi_arc_allowed),
                    "same_pair_arc_finalize_allowed": bool(getattr(segment, "same_pair_arc_finalize_allowed", False)),
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
                        "same_pair_arc_finalize_allowed": bool(getattr(segment, "same_pair_arc_finalize_allowed", False)),
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
                        "geometry_refine_applied": bool(build_result.get("geometry_refine_applied", False)),
                        "geometry_refine_smoothed": bool(build_result.get("geometry_refine_smoothed", False)),
                        "geometry_refine_core_skeleton_source": str(build_result.get("geometry_refine_core_skeleton_source", "")),
                        "geometry_refine_core_skeleton_source_detail": str(build_result.get("geometry_refine_core_skeleton_source_detail", "")),
                        "geometry_refine_entry_anchor_source": str(build_result.get("geometry_refine_entry_anchor_source", "")),
                        "geometry_refine_exit_anchor_source": str(build_result.get("geometry_refine_exit_anchor_source", "")),
                        "geometry_refine_entry_midpoint_fallback_used": bool(build_result.get("geometry_refine_entry_midpoint_fallback_used", False)),
                        "geometry_refine_exit_midpoint_fallback_used": bool(build_result.get("geometry_refine_exit_midpoint_fallback_used", False)),
                        "geometry_refine_entry_anchor_confidence": float(build_result.get("geometry_refine_entry_anchor_confidence", 0.0)),
                        "geometry_refine_exit_anchor_confidence": float(build_result.get("geometry_refine_exit_anchor_confidence", 0.0)),
                        "geometry_refine_lane_boundary_used": bool(build_result.get("geometry_refine_lane_boundary_used", False)),
                        "geometry_refine_lane_boundary_quality_score": float(build_result.get("geometry_refine_lane_boundary_quality_score", 0.0)),
                        "geometry_refine_traj_guided_used": bool(build_result.get("geometry_refine_traj_guided_used", False)),
                        "geometry_refine_support_trend_used": bool(build_result.get("geometry_refine_support_trend_used", False)),
                        "geometry_refine_safe_envelope_applied": bool(build_result.get("geometry_refine_safe_envelope_applied", False)),
                        "geometry_refine_safe_envelope_source": str(build_result.get("geometry_refine_safe_envelope_source", "")),
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
                "chosen_shape_ref_source_family": str(
                    build_result.get(
                        "shape_ref_source_family",
                        _shape_ref_source_family(build_result.get("shape_ref_mode", "")),
                    )
                ),
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
                "same_pair_arc_finalize_allowed": bool(getattr(segment, "same_pair_arc_finalize_allowed", False)),
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
                "geometry_refine_applied": bool(build_result.get("geometry_refine_applied", False)),
                "geometry_refine_smoothed": bool(build_result.get("geometry_refine_smoothed", False)),
                "geometry_refine_core_skeleton_source": str(build_result.get("geometry_refine_core_skeleton_source", "")),
                "geometry_refine_core_skeleton_source_detail": str(build_result.get("geometry_refine_core_skeleton_source_detail", "")),
                "geometry_refine_entry_anchor_source": str(build_result.get("geometry_refine_entry_anchor_source", "")),
                "geometry_refine_exit_anchor_source": str(build_result.get("geometry_refine_exit_anchor_source", "")),
                "geometry_refine_entry_midpoint_fallback_used": bool(build_result.get("geometry_refine_entry_midpoint_fallback_used", False)),
                "geometry_refine_exit_midpoint_fallback_used": bool(build_result.get("geometry_refine_exit_midpoint_fallback_used", False)),
                "geometry_refine_safe_envelope_source": str(build_result.get("geometry_refine_safe_envelope_source", "")),
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
            "shape_ref_source_family": str(
                build_result.get(
                    "shape_ref_source_family",
                    _shape_ref_source_family(build_result.get("shape_ref_mode", "")),
                )
            ),
            "no_geometry_candidate": bool(road is None),
            "no_geometry_candidate_reason": str(unresolved_reason),
            "unresolved_reason": str(unresolved_reason),
            "topology_arc_id": str(segment.topology_arc_id),
            "topology_arc_source_type": str(segment.topology_arc_source_type),
            "topology_arc_is_direct_legal": bool(segment.topology_arc_is_direct_legal),
            "topology_arc_is_unique": bool(segment.topology_arc_is_unique),
            "production_multi_arc_allowed": bool(segment.production_multi_arc_allowed),
            "same_pair_arc_finalize_allowed": bool(getattr(segment, "same_pair_arc_finalize_allowed", False)),
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
            "geometry_refine_applied": bool(build_result.get("geometry_refine_applied", False)),
            "geometry_refine_smoothed": bool(build_result.get("geometry_refine_smoothed", False)),
            "geometry_refine_core_skeleton_source": str(build_result.get("geometry_refine_core_skeleton_source", "")),
            "geometry_refine_core_skeleton_source_detail": str(build_result.get("geometry_refine_core_skeleton_source_detail", "")),
            "geometry_refine_entry_anchor_source": str(build_result.get("geometry_refine_entry_anchor_source", "")),
            "geometry_refine_exit_anchor_source": str(build_result.get("geometry_refine_exit_anchor_source", "")),
            "geometry_refine_entry_midpoint_fallback_used": bool(build_result.get("geometry_refine_entry_midpoint_fallback_used", False)),
            "geometry_refine_exit_midpoint_fallback_used": bool(build_result.get("geometry_refine_exit_midpoint_fallback_used", False)),
            "geometry_refine_lane_boundary_used": bool(build_result.get("geometry_refine_lane_boundary_used", False)),
            "geometry_refine_lane_boundary_quality_score": float(build_result.get("geometry_refine_lane_boundary_quality_score", 0.0)),
            "geometry_refine_traj_guided_used": bool(build_result.get("geometry_refine_traj_guided_used", False)),
            "geometry_refine_support_trend_used": bool(build_result.get("geometry_refine_support_trend_used", False)),
            "geometry_refine_safe_envelope_applied": bool(build_result.get("geometry_refine_safe_envelope_applied", False)),
            "geometry_refine_safe_envelope_source": str(build_result.get("geometry_refine_safe_envelope_source", "")),
            "failure_classification": str(failure_classification),
        }
        metrics_segments.append(metrics_entry)
        geometry_input_source_rows.append(
            {
                "segment_id": str(segment.segment_id),
                "pair": pipeline._pair_id_text(int(segment.src_nodeid), int(segment.dst_nodeid)),
                "topology_arc_id": str(segment.topology_arc_id),
                "geometry_role": str(segment.geometry_role),
                "production_geometry_source_type": str(segment.geometry_source_type),
                "production_support_provenance": str(segment.support_provenance),
                "production_anchor_provenance": str(segment.anchor_provenance),
                "production_geometry_fallback_reason": str(segment.geometry_fallback_reason),
                "preliminary_hint_used": bool(segment.preliminary_hint_used),
                "step3_working_segment_source": str(registry_row.get("working_segment_source", "")),
                "step3_support_source_type": str(registry_row.get("production_support_source_type", "")),
                "step3_support_driven": bool(registry_row.get("production_support_driven", False)),
                "step3_preliminary_segment_id": str(registry_row.get("preliminary_segment_id", "")),
                "step3_preliminary_geometry_source": str(registry_row.get("preliminary_geometry_source", "")),
                "corridor_identity_state": str(identity.state),
                "shape_ref_mode": str(build_result.get("shape_ref_mode", "")),
                "shape_ref_source_family": str(
                    build_result.get(
                        "shape_ref_source_family",
                        _shape_ref_source_family(build_result.get("shape_ref_mode", "")),
                    )
                ),
                "step5_endpoint_anchor_policy": str(build_result.get("endpoint_anchor_policy", "")),
                "step5_support_candidate_policy": str(build_result.get("support_candidate_policy", "")),
                "step5_rcsdroad_fallback_applied": bool(build_result.get("rcsdroad_fallback_applied", False)),
                "built_final_road": bool(road is not None),
                "final_reason": str(build_result.get("reason", "")),
                "same_pair_arc_finalize_allowed": bool(
                    getattr(segment, "same_pair_arc_finalize_allowed", False)
                ),
                "production_multi_arc_allowed": bool(segment.production_multi_arc_allowed),
            }
        )
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
                    and not bool(entry.get("same_pair_arc_finalize_allowed", False))
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
    write_features_geojson(patch_dir / "traj_guided_core_line.geojson", geometry_refine_traj_guided_features)
    write_lines_geojson(patch_dir / "trusted_core_skeleton.geojson", geometry_refine_core_features)
    write_features_geojson(patch_dir / "xsec_anchor_points.geojson", geometry_refine_anchor_features)
    write_lines_geojson(patch_dir / "entry_exit_segments.geojson", geometry_refine_entry_exit_features)
    write_features_geojson(patch_dir / "safe_envelope_polygon.geojson", geometry_refine_safe_envelope_features)
    write_features_geojson(patch_dir / "refined_final_road.geojson", geometry_refine_refined_road_features)
    write_lines_geojson(patch_dir / "geometry_refine_core_skeleton.geojson", geometry_refine_core_features)
    write_lines_geojson(patch_dir / "geometry_refine_entry_exit.geojson", geometry_refine_entry_exit_features)
    write_json(patch_dir / "metrics.json", metrics)
    write_json(patch_dir / "gate.json", gate)
    write_json(patch_dir / "geometry_refine_review.json", geometry_refine_review)
    write_json(
        pipeline.stage_dir(out_root, run_id, patch_id, "step5_slot_mapping") / "step5_geometry_input_sources.json",
        {
            "rows": geometry_input_source_rows,
            "summary": {
                "row_count": int(len(geometry_input_source_rows)),
                "built_count": int(sum(1 for item in geometry_input_source_rows if bool(item["built_final_road"]))),
                "production_working_segment_family_count": int(
                    sum(
                        1
                        for item in geometry_input_source_rows
                        if str(item["shape_ref_source_family"]) == "production_working_segment_family"
                    )
                ),
                "support_reference_family_count": int(
                    sum(
                        1
                        for item in geometry_input_source_rows
                        if str(item["shape_ref_source_family"]) == "support_reference_family"
                    )
                ),
            },
        },
    )
    (patch_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    write_lines_geojson(dbg_dir / "shape_ref_line.geojson", shape_ref_features)
    write_lines_geojson(dbg_dir / "road_final.geojson", road_features)
    write_features_geojson(dbg_dir / "traj_guided_core_line.geojson", geometry_refine_traj_guided_features)
    write_lines_geojson(dbg_dir / "trusted_core_skeleton.geojson", geometry_refine_core_features)
    write_features_geojson(dbg_dir / "xsec_anchor_points.geojson", geometry_refine_anchor_features)
    write_lines_geojson(dbg_dir / "entry_exit_segments.geojson", geometry_refine_entry_exit_features)
    write_features_geojson(dbg_dir / "safe_envelope_polygon.geojson", geometry_refine_safe_envelope_features)
    write_features_geojson(dbg_dir / "refined_final_road.geojson", geometry_refine_refined_road_features)
    write_lines_geojson(dbg_dir / "geometry_refine_core_skeleton.geojson", geometry_refine_core_features)
    write_lines_geojson(dbg_dir / "geometry_refine_entry_exit.geojson", geometry_refine_entry_exit_features)
    write_json(dbg_dir / "geometry_refine_review.json", geometry_refine_review)
    write_json(dbg_dir / "step5_geometry_input_sources.json", {"rows": geometry_input_source_rows})
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
    legal_arc_funnel = dict(identities_payload.get("legal_arc_funnel", {}))
    slot_map: dict[str, dict[str, SlotInterval]] = {}
    debug_features: list[tuple[LineString, dict[str, Any]]] = []
    for segment in segments:
        witness = witnesses.get(str(segment.segment_id))
        identity = identities[str(segment.segment_id)]
        arc_row = (
            registry_by_working_segment.get(str(segment.segment_id))
            or registry_by_arc_id.get(str(segment.topology_arc_id))
            or {}
        )
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
            arc_row=arc_row,
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
            arc_row=arc_row,
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
    roads, road_results, geometry_refine_artifacts, geometry_refine_review = _apply_geometry_refine(
        segments=segments,
        identities=identities,
        witnesses=witnesses,
        slots=slot_map,
        roads=roads,
        road_results=road_results,
        inputs=inputs,
        prior_roads=prior_roads,
        params=params,
        full_registry_rows=full_registry_rows,
        prior_index=prior_index,
        divstrip_buffer=patch_geometry_cache.get("divstrip_buffer"),
    )
    artifact = {
        "roads": [road.to_dict() for road in roads],
        "road_results": road_results,
        "geometry_refine_review": geometry_refine_review,
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
        geometry_refine_review=geometry_refine_review,
        geometry_refine_artifacts=geometry_refine_artifacts,
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
