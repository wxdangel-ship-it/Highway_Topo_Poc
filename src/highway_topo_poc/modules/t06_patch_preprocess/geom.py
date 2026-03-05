from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

BIT16_VALUE = 1 << 16
SNAP_TOL_M = 0.05
ENDPOINT_CHANGE_TOL_M = 0.05
HASH_ROUND_M = 0.001
MAX_HASH_TRIES = 64
WEBMERCATOR_LAT_MAX = 85.05112878


@dataclass(frozen=True)
class SideAssignment:
    src_point: Point
    dst_point: Point
    src_distance_m: float
    dst_distance_m: float


@dataclass(frozen=True)
class SegmentChoice:
    segment: LineString | None
    reason: str | None
    connect_src: bool
    connect_dst: bool


@dataclass(frozen=True)
class DrivezoneUnionResult:
    raw_geom: BaseGeometry
    clip_geom: BaseGeometry


def _stable_hash64(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def is_finite_geometry(geom: BaseGeometry | None) -> bool:
    if geom is None or geom.is_empty:
        return False
    b = geom.bounds
    return bool(np.isfinite(np.asarray(b, dtype=float)).all())


def build_transformer(src_crs_name: str, dst_epsg: int) -> tuple[Transformer, bool]:
    src = CRS.from_user_input(src_crs_name)
    dst = CRS.from_epsg(dst_epsg)
    clamp_geographic = bool(src.is_geographic and dst.to_epsg() == 3857)
    return Transformer.from_crs(src, dst, always_xy=True), clamp_geographic


def project_geometry(geom: BaseGeometry, *, transformer: Transformer, clamp_geographic: bool) -> BaseGeometry:
    if not clamp_geographic:
        out = transform(transformer.transform, geom)
        if not is_finite_geometry(out):
            raise ValueError("non_finite_geometry_after_projection")
        return out

    def _clamp_then_project(x, y, z=None):
        y = np.clip(y, -WEBMERCATOR_LAT_MAX, WEBMERCATOR_LAT_MAX)
        if z is None:
            xx, yy = transformer.transform(x, y)
            return xx, yy
        xx, yy, zz = transformer.transform(x, y, z)
        return xx, yy, zz

    out = transform(_clamp_then_project, geom)
    if not is_finite_geometry(out):
        raise ValueError("non_finite_geometry_after_projection")
    return out


def extract_linear_segments(geom: BaseGeometry | None) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        if geom.length > 0 and len(geom.coords) >= 2:
            return [geom]
        return []
    if isinstance(geom, MultiLineString):
        out: list[LineString] = []
        for g in geom.geoms:
            out.extend(extract_linear_segments(g))
        return out
    if isinstance(geom, GeometryCollection):
        out: list[LineString] = []
        for g in geom.geoms:
            out.extend(extract_linear_segments(g))
        return out
    return []


def choose_reference_line(geom: BaseGeometry) -> LineString | None:
    segments = extract_linear_segments(geom)
    if not segments:
        return None
    segments.sort(key=lambda g: (-float(g.length), g.wkt))
    return segments[0]


def line_endpoints(line: LineString) -> tuple[Point, Point]:
    c0 = line.coords[0]
    c1 = line.coords[-1]
    return Point(float(c0[0]), float(c0[1])), Point(float(c1[0]), float(c1[1]))


def assign_by_references(
    p0: Point,
    p1: Point,
    *,
    src_ref: Point,
    dst_ref: Point,
) -> SideAssignment:
    d00 = src_ref.distance(p0)
    d11 = dst_ref.distance(p1)
    d01 = src_ref.distance(p1)
    d10 = dst_ref.distance(p0)

    if d00 + d11 <= d01 + d10:
        return SideAssignment(src_point=p0, dst_point=p1, src_distance_m=float(d00), dst_distance_m=float(d11))
    return SideAssignment(src_point=p1, dst_point=p0, src_distance_m=float(d01), dst_distance_m=float(d10))


def assign_original_sides(
    p0: Point,
    p1: Point,
    *,
    src_node: Point | None,
    dst_node: Point | None,
) -> SideAssignment:
    if src_node is not None and dst_node is not None:
        return assign_by_references(p0, p1, src_ref=src_node, dst_ref=dst_node)
    if src_node is not None:
        if src_node.distance(p0) <= src_node.distance(p1):
            return SideAssignment(
                src_point=p0,
                dst_point=p1,
                src_distance_m=float(src_node.distance(p0)),
                dst_distance_m=float(src_node.distance(p1)),
            )
        return SideAssignment(
            src_point=p1,
            dst_point=p0,
            src_distance_m=float(src_node.distance(p1)),
            dst_distance_m=float(src_node.distance(p0)),
        )
    if dst_node is not None:
        if dst_node.distance(p1) <= dst_node.distance(p0):
            return SideAssignment(
                src_point=p0,
                dst_point=p1,
                src_distance_m=float(dst_node.distance(p0)),
                dst_distance_m=float(dst_node.distance(p1)),
            )
        return SideAssignment(
            src_point=p1,
            dst_point=p0,
            src_distance_m=float(dst_node.distance(p1)),
            dst_distance_m=float(dst_node.distance(p0)),
        )
    return SideAssignment(src_point=p0, dst_point=p1, src_distance_m=0.0, dst_distance_m=0.0)


def segment_connects_node(segment: LineString, node: Point | None, *, tol_m: float) -> bool:
    if node is None:
        return False
    q0, q1 = line_endpoints(segment)
    return bool(min(node.distance(q0), node.distance(q1)) <= tol_m)


def choose_segment(
    *,
    segments: list[LineString],
    src_exists: bool,
    dst_exists: bool,
    src_node: Point | None,
    dst_node: Point | None,
    tol_m: float,
) -> SegmentChoice:
    if not segments:
        return SegmentChoice(segment=None, reason="clipped_empty", connect_src=False, connect_dst=False)

    ranked: list[tuple[int, float, float, str, int, LineString, bool, bool, int]] = []
    for idx, seg in enumerate(segments):
        connect_src = src_exists and segment_connects_node(seg, src_node, tol_m=tol_m)
        connect_dst = dst_exists and segment_connects_node(seg, dst_node, tol_m=tol_m)
        connected_count = int(bool(connect_src)) + int(bool(connect_dst))

        q0, q1 = line_endpoints(seg)
        if src_node is not None and dst_node is not None:
            assigned = assign_by_references(q0, q1, src_ref=src_node, dst_ref=dst_node)
            dist_score = float(assigned.src_distance_m + assigned.dst_distance_m)
        elif src_node is not None:
            dist_score = float(min(src_node.distance(q0), src_node.distance(q1)))
        elif dst_node is not None:
            dist_score = float(min(dst_node.distance(q0), dst_node.distance(q1)))
        else:
            dist_score = 0.0

        ranked.append(
            (
                -connected_count,
                -float(seg.length),
                dist_score,
                seg.wkt,
                idx,
                seg,
                connect_src,
                connect_dst,
                connected_count,
            )
        )

    if not ranked:
        return SegmentChoice(segment=None, reason="segment_select_failed", connect_src=False, connect_dst=False)

    ranked.sort(key=lambda t: (t[0], t[1], t[2], t[3], t[4]))
    _, _, _, _, _, chosen, cs, cd, best_connected_count = ranked[0]

    if src_exists or dst_exists:
        if best_connected_count == 0:
            reason = "fallback_longest_no_endpoint_match"
        else:
            reason = None
    else:
        reason = "fallback_longest_no_existing_endpoint"

    return SegmentChoice(segment=chosen, reason=reason, connect_src=bool(cs), connect_dst=bool(cd))


def endpoint_changed(original_side: Point, new_side: Point, *, tol_m: float) -> bool:
    return bool(original_side.distance(new_side) > tol_m)


def build_drivezone_union(polygons: list[BaseGeometry], *, clip_buffer_m: float) -> DrivezoneUnionResult:
    cleaned: list[BaseGeometry] = []
    for idx, geom in enumerate(polygons):
        if geom.is_empty:
            continue
        g = geom
        if not g.is_valid:
            raise ValueError(f"drivezone_invalid_geometry:index={idx}")
        cleaned.append(g)
    if not cleaned:
        return DrivezoneUnionResult(raw_geom=GeometryCollection(), clip_geom=GeometryCollection())
    raw = unary_union(cleaned)
    clip = raw.buffer(float(clip_buffer_m))
    return DrivezoneUnionResult(raw_geom=raw, clip_geom=clip)


def relation_to_zone(line_geom: BaseGeometry, zone_union: BaseGeometry) -> str:
    if line_geom.is_empty:
        return "empty"
    if zone_union.is_empty:
        return "zone_empty"
    if line_geom.within(zone_union):
        return "inside"
    if line_geom.disjoint(zone_union):
        return "outside"
    return "boundary_intersection"


def coerce_id_type(value: Any, *, id_is_int: bool) -> Any:
    if id_is_int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, np.integer)):
            return int(value)
        if isinstance(value, float) and math.isfinite(value) and value.is_integer():
            return int(value)
        raise ValueError(f"cannot_coerce_to_int_id: {value!r}")
    return str(value)


def generate_stable_node_id(
    *,
    road_primary_id: Any,
    side: str,
    x_m: float,
    y_m: float,
    id_is_int: bool,
    existing_ids: set[Any],
    max_tries: int = MAX_HASH_TRIES,
) -> Any:
    x_round = round(float(x_m), 3)
    y_round = round(float(y_m), 3)
    for salt in range(max_tries):
        key = f"{road_primary_id}|{side}|{x_round:.3f}|{y_round:.3f}|{salt}"
        h = _stable_hash64(key)
        if id_is_int:
            candidate = int(h & 0x7FFFFFFFFFFFFFFF)
            if candidate == 0:
                candidate = 1
        else:
            candidate = f"{h:016x}"
        if candidate not in existing_ids:
            return candidate
    raise RuntimeError("virtual_node_id_collision_exhausted")
