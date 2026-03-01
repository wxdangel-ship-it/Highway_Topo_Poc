from __future__ import annotations

import math
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, Polygon
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


def clip_crossline_to_drivezone(
    *,
    crossline: LineString,
    drivezone_union: BaseGeometry | None,
    anchor_pt: Point | None,
) -> tuple[LineString, dict[str, Any]]:
    diag: dict[str, Any] = {
        "clipped_len_m": float(crossline.length),
        "clip_empty": False,
        "chosen_piece_type": "original",
    }
    if drivezone_union is None or drivezone_union.is_empty:
        diag["chosen_piece_type"] = "drivezone_missing"
        return crossline, diag

    inter = crossline.intersection(drivezone_union)
    pieces = _collect_lines(inter)
    if not pieces:
        diag["clip_empty"] = True
        diag["chosen_piece_type"] = "clip_empty"
        return crossline, diag

    chosen = pieces[0]
    chosen_type = "nearest_piece"
    if anchor_pt is not None and not anchor_pt.is_empty:
        containing = [ln for ln in pieces if ln.distance(anchor_pt) <= 1e-6]
        if containing:
            chosen = max(containing, key=lambda ln: float(ln.length))
            chosen_type = "contains_anchor"
        else:
            chosen = min(pieces, key=lambda ln: float(ln.distance(anchor_pt)))
            chosen_type = "nearest_anchor"
    else:
        chosen = max(pieces, key=lambda ln: float(ln.length))
        chosen_type = "longest_piece"

    diag["clipped_len_m"] = float(chosen.length)
    diag["chosen_piece_type"] = chosen_type
    return chosen, diag


__all__ = [
    "build_fan_band",
    "clip_crossline_to_drivezone",
    "detect_non_drivezone_in_fan",
]

