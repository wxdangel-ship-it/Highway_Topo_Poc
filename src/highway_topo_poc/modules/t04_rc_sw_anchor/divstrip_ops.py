from __future__ import annotations

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry

from .local_frame import normalize_vec


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


def _collect_divstrip_vertices(geom: BaseGeometry | None) -> list[tuple[float, float]]:
    def _xy(coord: object) -> tuple[float, float]:
        # Accept 2D/3D coordinates and keep XY for planar logic.
        seq = coord if isinstance(coord, (list, tuple)) else tuple(coord)  # type: ignore[arg-type]
        if len(seq) < 2:
            raise ValueError("coord_dim_lt_2")
        return (float(seq[0]), float(seq[1]))

    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Point):
        return [(float(geom.x), float(geom.y))]
    if isinstance(geom, LineString):
        return [_xy(c) for c in geom.coords]
    if isinstance(geom, Polygon):
        pts: list[tuple[float, float]] = [_xy(c) for c in geom.exterior.coords]
        for ring in geom.interiors:
            pts.extend(_xy(c) for c in ring.coords)
        return pts
    if isinstance(geom, MultiLineString):
        out: list[tuple[float, float]] = []
        for g in geom.geoms:
            out.extend(_collect_divstrip_vertices(g))
        return out
    if isinstance(geom, MultiPolygon):
        out: list[tuple[float, float]] = []
        for g in geom.geoms:
            out.extend(_collect_divstrip_vertices(g))
        return out
    if isinstance(geom, GeometryCollection):
        out: list[tuple[float, float]] = []
        for g in geom.geoms:
            out.extend(_collect_divstrip_vertices(g))
        return out
    return []


def _collect_polygon_components(geom: BaseGeometry | None) -> list[BaseGeometry]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms if g is not None and (not g.is_empty)]
    if isinstance(geom, GeometryCollection):
        out: list[BaseGeometry] = []
        for g in geom.geoms:
            out.extend(_collect_polygon_components(g))
        return out
    return [geom]


def tip_point_from_divstrip(
    *,
    divstrip_union: BaseGeometry | None,
    scan_vec: tuple[float, float],
    origin_xy: tuple[float, float] | None = None,
) -> Point | None:
    if divstrip_union is None or divstrip_union.is_empty:
        return None
    ux, uy = normalize_vec(float(scan_vec[0]), float(scan_vec[1]))
    base_ox: float | None = None
    base_oy: float | None = None
    if origin_xy is not None:
        base_ox = float(origin_xy[0])
        base_oy = float(origin_xy[1])

    def _proj_xy(x: float, y: float) -> float:
        if base_ox is not None and base_oy is not None:
            return float((x - base_ox) * ux + (y - base_oy) * uy)
        return float(x * ux + y * uy)

    target_geom: BaseGeometry = divstrip_union
    comps = _collect_polygon_components(divstrip_union)
    if comps and origin_xy is not None:
        ahead: list[tuple[float, BaseGeometry]] = []
        for g in comps:
            rp = g.representative_point()
            proj = _proj_xy(float(rp.x), float(rp.y))
            if proj >= -1e-6:
                ahead.append((proj, g))
        if ahead:
            target_geom = min(ahead, key=lambda x: x[0])[1]
        else:
            target_geom = max(
                ((_proj_xy(float(g.representative_point().x), float(g.representative_point().y)), g) for g in comps),
                key=lambda x: x[0],
            )[1]
    elif comps:
        target_geom = comps[0]

    vertices = _collect_divstrip_vertices(target_geom)
    if not vertices:
        rep = target_geom.representative_point()
        if rep is None or rep.is_empty:
            return None
        return Point(float(rep.x), float(rep.y))

    scores = [_proj_xy(x, y) for x, y in vertices]
    tol = 1e-6
    non_neg = [s for s in scores if s >= -tol]
    if non_neg:
        target_s = min(non_neg)
        tip_pts = [vertices[i] for i, s in enumerate(scores) if abs(s - target_s) <= tol]
    else:
        # Fallback: if every vertex is behind origin along scan direction,
        # use the least-behind side.
        target_s = max(scores)
        tip_pts = [vertices[i] for i, s in enumerate(scores) if abs(s - target_s) <= tol]
    if not tip_pts:
        best_xy = vertices[int(max(range(len(scores)), key=lambda i: scores[i]))]
        return Point(float(best_xy[0]), float(best_xy[1]))
    uniq_pts = list(dict.fromkeys((float(p[0]), float(p[1])) for p in tip_pts))
    mx = float(sum(p[0] for p in uniq_pts) / float(len(uniq_pts)))
    my = float(sum(p[1] for p in uniq_pts) / float(len(uniq_pts)))
    return Point(mx, my)


__all__ = ["anchor_point_from_crossline", "is_divstrip_hit", "tip_point_from_divstrip"]
