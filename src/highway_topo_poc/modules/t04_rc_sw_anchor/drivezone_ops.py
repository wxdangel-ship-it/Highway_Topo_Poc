from __future__ import annotations

import math
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry

from .local_frame import normalize_vec


def _rotate(vec: tuple[float, float], theta_rad: float) -> tuple[float, float]:
    vx, vy = vec
    ct = math.cos(theta_rad)
    st = math.sin(theta_rad)
    return (vx * ct - vy * st, vx * st + vy * ct)


def _collect_lines(geom: BaseGeometry | None) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom] if geom.length > 1e-9 else []
    if isinstance(geom, MultiLineString):
        return [ln for ln in geom.geoms if ln.length > 1e-9]
    if isinstance(geom, GeometryCollection):
        out: list[LineString] = []
        for g in geom.geoms:
            out.extend(_collect_lines(g))
        return out
    return []


def _piece_interval_on_segment(*, segment: LineString, piece: LineString) -> tuple[float, float]:
    coords = list(piece.coords)
    if not coords:
        return (0.0, 0.0)
    vals = [float(segment.project(Point(float(x), float(y)))) for x, y in coords]
    return (float(min(vals)), float(max(vals)))


def _collect_polygons(geom: BaseGeometry | None) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom] if float(geom.area) > 1e-9 else []
    if isinstance(geom, MultiPolygon):
        return [pg for pg in geom.geoms if float(pg.area) > 1e-9]
    if isinstance(geom, GeometryCollection):
        out: list[Polygon] = []
        for g in geom.geoms:
            out.extend(_collect_polygons(g))
        return out
    return []


def build_fan_band(
    *,
    origin_xy: tuple[float, float],
    scan_unit_vec: tuple[float, float],
    radius_m: float,
    half_angle_deg: float,
    band_width_m: float,
    arc_segments: int = 24,
) -> Polygon:
    ox, oy = float(origin_xy[0]), float(origin_xy[1])
    ux, uy = normalize_vec(float(scan_unit_vec[0]), float(scan_unit_vec[1]))
    radius = max(0.01, float(radius_m))
    half_angle = max(0.5, float(half_angle_deg))
    half_w = max(0.1, float(band_width_m) * 0.5)
    segs = max(8, int(arc_segments))

    arc: list[tuple[float, float]] = []
    for i in range(segs + 1):
        t = -half_angle + (2.0 * half_angle) * (float(i) / float(segs))
        vec = _rotate((ux, uy), math.radians(t))
        arc.append((ox + radius * vec[0], oy + radius * vec[1]))

    sector = Polygon([(ox, oy), *arc, (ox, oy)])
    px, py = (-uy, ux)
    ex, ey = (ox + ux * radius, oy + uy * radius)
    corridor = Polygon(
        [
            (ox + px * half_w, oy + py * half_w),
            (ex + px * half_w, ey + py * half_w),
            (ex - px * half_w, ey - py * half_w),
            (ox - px * half_w, oy - py * half_w),
            (ox + px * half_w, oy + py * half_w),
        ]
    )
    band = sector.intersection(corridor)
    if band.is_empty:
        return sector
    if isinstance(band, Polygon):
        return band
    hull = band.convex_hull
    if isinstance(hull, Polygon):
        return hull
    return sector


def detect_non_drivezone_in_fan(
    *,
    drivezone_union: BaseGeometry | None,
    fan_band: BaseGeometry,
    area_min_m2: float,
    frac_min: float,
) -> tuple[bool, dict[str, Any]]:
    fan_area = float(fan_band.area) if fan_band is not None and (not fan_band.is_empty) else 0.0
    diag: dict[str, Any] = {
        "fan_area_m2": fan_area,
        "non_drivezone_area_m2": 0.0,
        "non_drivezone_frac": 0.0,
        "reason": "ok",
    }
    if fan_area <= 1e-9:
        diag["reason"] = "fan_empty"
        return False, diag
    if drivezone_union is None or drivezone_union.is_empty:
        diag["reason"] = "drivezone_missing"
        return False, diag

    non_geom = fan_band.difference(drivezone_union)
    non_area = 0.0 if non_geom is None or non_geom.is_empty else float(non_geom.area)
    frac = 0.0 if fan_area <= 1e-9 else float(non_area / fan_area)
    diag["non_drivezone_area_m2"] = float(non_area)
    diag["non_drivezone_frac"] = float(frac)

    hit = bool(non_area >= float(area_min_m2) or frac >= float(frac_min))
    return hit, diag


def segment_drivezone_pieces(
    *,
    segment: LineString,
    drivezone_union: BaseGeometry | None,
    min_piece_len_m: float,
) -> list[LineString]:
    if drivezone_union is None or drivezone_union.is_empty:
        return []
    inter = segment.intersection(drivezone_union)
    pieces = [ln for ln in _collect_lines(inter) if float(ln.length) >= max(0.01, float(min_piece_len_m))]
    if not pieces:
        return []
    return sorted(pieces, key=lambda ln: _piece_interval_on_segment(segment=segment, piece=ln)[0])


def pick_top_two_segment_pieces(
    *,
    segment: LineString,
    pieces: list[LineString],
) -> tuple[list[LineString], bool]:
    if len(pieces) <= 2:
        return list(pieces), False
    top = sorted(pieces, key=lambda ln: float(ln.length), reverse=True)[:2]
    top = sorted(top, key=lambda ln: _piece_interval_on_segment(segment=segment, piece=ln)[0])
    return top, True


def gap_midpoint_between_pieces(
    *,
    segment: LineString,
    pieces: list[LineString],
) -> tuple[Point | None, float | None]:
    if len(pieces) < 2:
        return None, None
    p0, p1 = pieces[0], pieces[1]
    i0 = _piece_interval_on_segment(segment=segment, piece=p0)
    i1 = _piece_interval_on_segment(segment=segment, piece=p1)
    left = i0 if i0[0] <= i1[0] else i1
    right = i1 if i0[0] <= i1[0] else i0
    gap = float(right[0] - left[1])
    if not math.isfinite(gap) or gap < -1e-6:
        return None, None
    start = max(0.0, float(left[1]))
    end = max(start, float(right[0]))
    mid = 0.5 * (start + end)
    try:
        return segment.interpolate(mid), float(max(0.0, gap))
    except Exception:
        return None, None


def clip_crossline_to_drivezone(
    *,
    crossline: LineString,
    drivezone_union: BaseGeometry | None,
    anchor_pt: Point | None,
) -> tuple[BaseGeometry, dict[str, Any]]:
    diag: dict[str, Any] = {
        "clipped_len_m": float(crossline.length),
        "clip_empty": False,
        "chosen_piece_type": "original",
        "piece_count": 0,
        "piece_count_before_select": 0,
        "selected_by": "none",
        "selected_component_dist_m": None,
    }
    if drivezone_union is None or drivezone_union.is_empty:
        diag["chosen_piece_type"] = "drivezone_missing"
        return crossline, diag

    all_pieces = _collect_lines(crossline.intersection(drivezone_union))
    total_piece_count = int(len(all_pieces))
    diag["piece_count_before_select"] = total_piece_count

    chosen_drivezone: BaseGeometry = drivezone_union
    polygons = _collect_polygons(drivezone_union)
    if polygons and anchor_pt is not None and (not anchor_pt.is_empty):
        best_comp = min(
            polygons,
            key=lambda pg: (float(pg.distance(anchor_pt)), float(-pg.area)),
        )
        chosen_drivezone = best_comp
        diag["selected_by"] = "component_nearest_anchor"
        diag["selected_component_dist_m"] = float(best_comp.distance(anchor_pt))

    inter = crossline.intersection(chosen_drivezone)
    pieces = _collect_lines(inter)
    if not pieces and chosen_drivezone is not drivezone_union:
        inter = crossline.intersection(drivezone_union)
        pieces = _collect_lines(inter)
        diag["selected_by"] = "component_fallback_union"

    diag["piece_count"] = int(len(pieces))
    if not pieces:
        diag["clip_empty"] = True
        diag["chosen_piece_type"] = "clip_empty"
        return crossline, diag

    if len(pieces) > 1:
        center = crossline.interpolate(0.5, normalized=True)
        ranked = sorted(
            pieces,
            key=lambda ln: (
                float(ln.distance(anchor_pt)) if anchor_pt is not None and (not anchor_pt.is_empty) else 1.0e9,
                float(ln.distance(center)),
                abs(
                    float(crossline.project(ln.interpolate(0.5, normalized=True)))
                    - float(crossline.project(center))
                ),
            ),
        )
        chosen = ranked[0]
        diag["clipped_len_m"] = float(chosen.length)
        if anchor_pt is not None and not anchor_pt.is_empty:
            diag["chosen_piece_type"] = "multi_piece_selected_by_anchor"
            diag["selected_by"] = "piece_nearest_anchor"
        else:
            diag["chosen_piece_type"] = "multi_piece_selected_by_midpoint"
            diag["selected_by"] = "piece_nearest_midpoint"
        return chosen, diag

    chosen = pieces[0]
    chosen_type = "single_piece"
    if anchor_pt is not None and not anchor_pt.is_empty and chosen.distance(anchor_pt) <= 1e-6:
        chosen_type = "single_piece_contains_anchor"
    if total_piece_count > 1:
        chosen_type = "multi_piece_component_selected_single"
    diag["clipped_len_m"] = float(chosen.length)
    diag["chosen_piece_type"] = chosen_type
    return chosen, diag


def extend_line_to_half_len(*, line: LineString, half_len_m: float) -> LineString:
    coords = list(line.coords)
    if len(coords) < 2:
        return line
    x0, y0 = float(coords[0][0]), float(coords[0][1])
    x1, y1 = float(coords[-1][0]), float(coords[-1][1])
    cx = 0.5 * (x0 + x1)
    cy = 0.5 * (y0 + y1)
    ux, uy = normalize_vec(x1 - x0, y1 - y0)
    half = max(float(half_len_m), 0.1)
    return LineString([(cx - ux * half, cy - uy * half), (cx + ux * half, cy + uy * half)])


__all__ = [
    "build_fan_band",
    "clip_crossline_to_drivezone",
    "detect_non_drivezone_in_fan",
    "extend_line_to_half_len",
    "gap_midpoint_between_pieces",
    "pick_top_two_segment_pieces",
    "segment_drivezone_pieces",
]
