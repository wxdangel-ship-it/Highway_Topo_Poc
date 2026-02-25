from __future__ import annotations

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry


def is_divstrip_hit(*, line: LineString, divstrip_union: BaseGeometry | None, tol_m: float) -> bool:
    if divstrip_union is None:
        return False
    return bool(line.distance(divstrip_union) <= float(tol_m))


def anchor_point_from_crossline(*, line: LineString, divstrip_union: BaseGeometry | None) -> tuple[Point, float | None]:
    if divstrip_union is None:
        pt = line.interpolate(0.5, normalized=True) if line.length > 1e-9 else Point(*line.coords[0])
        return pt, None

    inter = line.intersection(divstrip_union)
    if inter is not None and not inter.is_empty:
        pt = inter.centroid
    else:
        pt = line.interpolate(0.5, normalized=True) if line.length > 1e-9 else Point(*line.coords[0])

    return pt, float(pt.distance(divstrip_union))


__all__ = ["anchor_point_from_crossline", "is_divstrip_hit"]
