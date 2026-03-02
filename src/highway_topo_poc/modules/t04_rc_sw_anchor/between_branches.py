from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from .io_geojson import RoadRecord
from .local_frame import normalize_vec


def _dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(a[0] * b[0] + a[1] * b[1])


def _road_vec_away_from_node(road: RoadRecord, *, nodeid: int) -> tuple[float, float]:
    coords = list(road.line.coords)
    if len(coords) < 2:
        return (1.0, 0.0)
    if int(road.snodeid) == int(nodeid):
        x0, y0 = float(coords[0][0]), float(coords[0][1])
        x1, y1 = float(coords[1][0]), float(coords[1][1])
        return normalize_vec(x1 - x0, y1 - y0)
    if int(road.enodeid) == int(nodeid):
        x0, y0 = float(coords[-1][0]), float(coords[-1][1])
        x1, y1 = float(coords[-2][0]), float(coords[-2][1])
        return normalize_vec(x1 - x0, y1 - y0)
    x0, y0 = float(coords[0][0]), float(coords[0][1])
    x1, y1 = float(coords[1][0]), float(coords[1][1])
    return normalize_vec(x1 - x0, y1 - y0)


def _pick_max_angle_pair(
    *,
    nodeid: int,
    road_indices: list[int],
    roads: list[RoadRecord],
) -> tuple[int, int]:
    if len(road_indices) < 2:
        raise ValueError("branch_count_lt_2")
    best_pair = (road_indices[0], road_indices[1])
    best_angle = -1.0
    best_len = -1.0
    for i in range(len(road_indices)):
        for j in range(i + 1, len(road_indices)):
            ia = int(road_indices[i])
            ib = int(road_indices[j])
            va = _road_vec_away_from_node(roads[ia], nodeid=nodeid)
            vb = _road_vec_away_from_node(roads[ib], nodeid=nodeid)
            dp = max(-1.0, min(1.0, _dot(va, vb)))
            ang = float(math.acos(dp))
            pair_len = float(roads[ia].length_m + roads[ib].length_m)
            if ang > best_angle + 1e-9 or (abs(ang - best_angle) <= 1e-9 and pair_len > best_len):
                best_angle = ang
                best_len = pair_len
                best_pair = (ia, ib)
    return best_pair


def _pick_scan_axis_for_diverge(
    *,
    nodeid: int,
    outgoing_indices: list[int],
    incoming_indices: list[int],
    roads: list[RoadRecord],
) -> int:
    if not outgoing_indices:
        raise ValueError("diverge_outgoing_missing")

    if incoming_indices:
        incoming_main = sorted(incoming_indices, key=lambda idx: float(roads[idx].length_m), reverse=True)[0]
        incoming_away = _road_vec_away_from_node(roads[incoming_main], nodeid=nodeid)
        incoming_into = (-float(incoming_away[0]), -float(incoming_away[1]))
        ranked = []
        for ridx in outgoing_indices:
            away = _road_vec_away_from_node(roads[ridx], nodeid=nodeid)
            ranked.append((_dot(away, incoming_into), float(roads[ridx].length_m), int(ridx)))
        ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return int(ranked[0][2])

    return int(sorted(outgoing_indices, key=lambda idx: float(roads[idx].length_m), reverse=True)[0])


def _pick_scan_axis_for_merge(
    *,
    nodeid: int,
    outgoing_indices: list[int],
    incoming_indices: list[int],
    roads: list[RoadRecord],
) -> int:
    if outgoing_indices:
        return int(sorted(outgoing_indices, key=lambda idx: float(roads[idx].length_m), reverse=True)[0])
    if incoming_indices:
        return int(sorted(incoming_indices, key=lambda idx: float(roads[idx].length_m), reverse=True)[0])
    raise ValueError("merge_axis_missing")


@dataclass(frozen=True)
class BranchSelection:
    anchor_type: str
    scan_dir_label: str
    scan_dir: tuple[float, float]
    scan_axis_idx: int
    branch_a_idx: int
    branch_b_idx: int
    multi_branch_todo: bool


def select_branch_pair_and_axis(
    *,
    nodeid: int,
    is_diverge: bool,
    roads: Iterable[RoadRecord],
) -> BranchSelection:
    road_list = list(roads)
    outgoing_indices = [idx for idx, road in enumerate(road_list) if int(road.snodeid) == int(nodeid)]
    incoming_indices = [idx for idx, road in enumerate(road_list) if int(road.enodeid) == int(nodeid)]

    if is_diverge:
        if len(outgoing_indices) < 2:
            raise ValueError("diverge_branch_count_lt_2")
        branch_a_idx, branch_b_idx = _pick_max_angle_pair(nodeid=nodeid, road_indices=outgoing_indices, roads=road_list)
        axis_idx = _pick_scan_axis_for_diverge(
            nodeid=nodeid,
            outgoing_indices=outgoing_indices,
            incoming_indices=incoming_indices,
            roads=road_list,
        )
        axis_away = _road_vec_away_from_node(road_list[axis_idx], nodeid=nodeid)
        scan_dir = normalize_vec(axis_away[0], axis_away[1])
        return BranchSelection(
            anchor_type="diverge",
            scan_dir_label="forward",
            scan_dir=scan_dir,
            scan_axis_idx=int(axis_idx),
            branch_a_idx=int(branch_a_idx),
            branch_b_idx=int(branch_b_idx),
            multi_branch_todo=bool(len(outgoing_indices) > 2),
        )

    if len(incoming_indices) < 2:
        raise ValueError("merge_branch_count_lt_2")
    branch_a_idx, branch_b_idx = _pick_max_angle_pair(nodeid=nodeid, road_indices=incoming_indices, roads=road_list)
    axis_idx = _pick_scan_axis_for_merge(
        nodeid=nodeid,
        outgoing_indices=outgoing_indices,
        incoming_indices=incoming_indices,
        roads=road_list,
    )
    axis_away = _road_vec_away_from_node(road_list[axis_idx], nodeid=nodeid)
    scan_dir = normalize_vec(-float(axis_away[0]), -float(axis_away[1]))
    return BranchSelection(
        anchor_type="merge",
        scan_dir_label="backward",
        scan_dir=scan_dir,
        scan_axis_idx=int(axis_idx),
        branch_a_idx=int(branch_a_idx),
        branch_b_idx=int(branch_b_idx),
        multi_branch_todo=bool(len(incoming_indices) > 2),
    )


def _crossline_segment(
    *,
    center_xy: tuple[float, float],
    scan_dir: tuple[float, float],
    half_len_m: float,
) -> LineString:
    sx, sy = normalize_vec(scan_dir[0], scan_dir[1])
    px, py = (-sy, sx)
    half = max(float(half_len_m), 0.1)
    cx, cy = float(center_xy[0]), float(center_xy[1])
    return LineString([(cx - px * half, cy - py * half), (cx + px * half, cy + py * half)])


def _collect_points_from_intersection(geom: BaseGeometry, *, center: Point) -> list[Point]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Point):
        return [geom]
    if isinstance(geom, MultiPoint):
        return [p for p in geom.geoms if p is not None and (not p.is_empty)]
    if isinstance(geom, LineString):
        proj = float(geom.project(center))
        return [geom.interpolate(proj)]
    if isinstance(geom, MultiLineString):
        pts: list[Point] = []
        for line in geom.geoms:
            if line is None or line.is_empty:
                continue
            proj = float(line.project(center))
            pts.append(line.interpolate(proj))
        return pts
    if isinstance(geom, GeometryCollection):
        pts: list[Point] = []
        for g in geom.geoms:
            pts.extend(_collect_points_from_intersection(g, center=center))
        return pts
    return []


def _pick_point_on_branch(
    *,
    branch_line: LineString,
    crossline: LineString,
    center: Point,
) -> tuple[Point, bool]:
    inter = branch_line.intersection(crossline)
    candidates = _collect_points_from_intersection(inter, center=center)
    if candidates:
        pt = sorted(candidates, key=lambda p: float(p.distance(center)))[0]
        return Point(float(pt.x), float(pt.y)), True
    p_branch, _p_cross = nearest_points(branch_line, crossline)
    return Point(float(p_branch.x), float(p_branch.y)), False


def build_between_branches_segment(
    *,
    center_xy: tuple[float, float],
    scan_dir: tuple[float, float],
    branch_a: RoadRecord,
    branch_b: RoadRecord,
    crossline_half_len_m: float,
) -> tuple[LineString, dict[str, float | bool]]:
    center = Point(float(center_xy[0]), float(center_xy[1]))
    crossline = _crossline_segment(
        center_xy=(float(center.x), float(center.y)),
        scan_dir=scan_dir,
        half_len_m=max(float(crossline_half_len_m), 120.0),
    )
    pa, a_hit = _pick_point_on_branch(branch_line=branch_a.line, crossline=crossline, center=center)
    pb, b_hit = _pick_point_on_branch(branch_line=branch_b.line, crossline=crossline, center=center)
    seg = LineString([(float(pa.x), float(pa.y)), (float(pb.x), float(pb.y))])
    diag: dict[str, float | bool] = {
        "seg_len_m": float(seg.length),
        "pa_center_dist_m": float(pa.distance(center)),
        "pb_center_dist_m": float(pb.distance(center)),
        "branch_a_crossline_hit": bool(a_hit),
        "branch_b_crossline_hit": bool(b_hit),
    }
    return seg, diag


__all__ = [
    "BranchSelection",
    "build_between_branches_segment",
    "select_branch_pair_and_axis",
]
