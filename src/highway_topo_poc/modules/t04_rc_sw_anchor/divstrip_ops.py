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
    target_geom: BaseGeometry = divstrip_union
    comps = _collect_polygon_components(divstrip_union)
    if comps and origin_xy is not None:
        ox, oy = float(origin_xy[0]), float(origin_xy[1])
        ahead: list[tuple[float, BaseGeometry]] = []
        for g in comps:
            rp = g.representative_point()
            proj = float((float(rp.x) - ox) * ux + (float(rp.y) - oy) * uy)
            if proj >= -1e-6:
                ahead.append((proj, g))
        if ahead:
            target_geom = min(ahead, key=lambda x: x[0])[1]
        else:
            target_geom = max(
                ((float((float(g.representative_point().x) - ox) * ux + (float(g.representative_point().y) - oy) * uy), g) for g in comps),
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

    scores = [float(x * ux + y * uy) for x, y in vertices]
    best_score = max(scores)
    tol = 1e-6
    front_pts = [vertices[i] for i, s in enumerate(scores) if s >= best_score - tol]
    if not front_pts:
        best_xy = vertices[int(max(range(len(scores)), key=lambda i: scores[i]))]
        return Point(float(best_xy[0]), float(best_xy[1]))
    mx = float(sum(p[0] for p in front_pts) / float(len(front_pts)))
    my = float(sum(p[1] for p in front_pts) / float(len(front_pts)))
    return Point(mx, my)


__all__ = ["anchor_point_from_crossline", "is_divstrip_hit", "tip_point_from_divstrip"]
