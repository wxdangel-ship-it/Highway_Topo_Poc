from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from .drivezone_ops import segment_drivezone_pieces
from .io_geojson import RoadRecord
from .local_frame import normalize_vec


@dataclass(frozen=True)
class BranchPointSample:
    road_idx: int
    point: Point
    hit_crossline: bool
    v_proj_m: float


def _dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(a[0] * b[0] + a[1] * b[1])


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


def _pick_point_on_branch_crossline(
    *,
    branch_line: LineString,
    crossline: LineString,
    center: Point,
) -> tuple[Point, bool]:
    inter = branch_line.intersection(crossline)
    candidates = _collect_points_from_intersection(inter, center=center)
    if candidates:
        pt = min(candidates, key=lambda p: float(p.distance(center)))
        return Point(float(pt.x), float(pt.y)), True
    p_branch, _p_cross = nearest_points(branch_line, crossline)
    return Point(float(p_branch.x), float(p_branch.y)), False


def _is_direction_valid(direction: int | None) -> bool:
    return bool(direction is not None and int(direction) in {2, 3})


def collect_valid_branches_by_direction(
    *,
    nodeid: int,
    roads: list[RoadRecord],
    anchor_type: str,
) -> tuple[list[tuple[int, RoadRecord]], dict[str, int]]:
    atype = str(anchor_type).strip().lower()
    candidates: list[tuple[int, RoadRecord]] = []
    for idx, road in enumerate(roads):
        if atype == "diverge":
            if int(road.snodeid) != int(nodeid):
                continue
        elif atype == "merge":
            if int(road.enodeid) != int(nodeid):
                continue
        else:
            continue
        candidates.append((int(idx), road))

    valid = [(idx, road) for idx, road in candidates if _is_direction_valid(road.direction)]
    ignored = int(len(candidates) - len(valid))
    diag = {
        "candidates_total": int(len(candidates)),
        "valid_count": int(len(valid)),
        "ignored_due_to_direction": int(max(0, ignored)),
    }
    return valid, diag


def build_crossline_span(
    *,
    center_xy: tuple[float, float],
    perp_vec: tuple[float, float],
    v_min_m: float,
    v_max_m: float,
    extra_m: float = 10.0,
) -> LineString:
    ux, uy = normalize_vec(float(perp_vec[0]), float(perp_vec[1]))
    cx, cy = float(center_xy[0]), float(center_xy[1])
    lo = float(min(v_min_m, v_max_m) - max(0.0, float(extra_m)))
    hi = float(max(v_min_m, v_max_m) + max(0.0, float(extra_m)))
    return LineString(
        [
            (float(cx + ux * lo), float(cy + uy * lo)),
            (float(cx + ux * hi), float(cy + uy * hi)),
        ]
    )


def crossline_span_points_all_branches(
    *,
    branches: list[tuple[int, RoadRecord]],
    center_xy: tuple[float, float],
    perp_vec: tuple[float, float],
) -> tuple[float, float, list[BranchPointSample]]:
    if not branches:
        raise ValueError("branches_empty")
    ux, uy = normalize_vec(float(perp_vec[0]), float(perp_vec[1]))
    cx, cy = float(center_xy[0]), float(center_xy[1])
    center = Point(cx, cy)

    # Use a long probe line to emulate an infinite crossline for branch matching.
    probe_len = 5000.0
    probe = LineString(
        [
            (float(cx - ux * probe_len), float(cy - uy * probe_len)),
            (float(cx + ux * probe_len), float(cy + uy * probe_len)),
        ]
    )

    samples: list[BranchPointSample] = []
    for road_idx, road in branches:
        pt, hit = _pick_point_on_branch_crossline(
            branch_line=road.line,
            crossline=probe,
            center=center,
        )
        v = _dot((float(pt.x - cx), float(pt.y - cy)), (ux, uy))
        samples.append(
            BranchPointSample(
                road_idx=int(road_idx),
                point=Point(float(pt.x), float(pt.y)),
                hit_crossline=bool(hit),
                v_proj_m=float(v),
            )
        )

    v_vals = [float(s.v_proj_m) for s in samples]
    return float(min(v_vals)), float(max(v_vals)), samples


def compute_pieces_count(
    *,
    crossline: LineString,
    drivezone_union: BaseGeometry | None,
    min_piece_len_m: float,
) -> int:
    pieces = segment_drivezone_pieces(
        segment=crossline,
        drivezone_union=drivezone_union,
        min_piece_len_m=float(min_piece_len_m),
    )
    return int(len(pieces))


def extract_split_events(
    *,
    s_values: list[float],
    pieces_count_seq: list[int],
    expected_events: int,
) -> tuple[list[float], list[dict[str, Any]]]:
    max_events = max(0, int(expected_events))
    if max_events <= 0:
        return [], []
    if (not s_values) or (not pieces_count_seq):
        return [], []

    n = min(len(s_values), len(pieces_count_seq))
    events: list[float] = []
    diag: list[dict[str, Any]] = []

    prev = int(max(0, pieces_count_seq[0]))
    if prev >= 2:
        grow0 = int(prev - 1)
        take0 = min(grow0, max_events - len(events))
        for rep in range(take0):
            events.append(float(s_values[0]))
            diag.append(
                {
                    "scan_index": 0,
                    "s_m": float(s_values[0]),
                    "pieces_prev": 1,
                    "pieces_curr": int(prev),
                    "delta": int(grow0),
                    "replica_idx": int(rep),
                    "coincident_events_count": int(take0),
                    "event_ambiguous_jump": bool(grow0 > 1),
                }
            )

    for i in range(1, n):
        if len(events) >= max_events:
            break
        curr = int(max(0, pieces_count_seq[i]))
        if curr > prev:
            grow = int(curr - prev)
            take = min(grow, max_events - len(events))
            for rep in range(take):
                events.append(float(s_values[i]))
                diag.append(
                    {
                        "scan_index": int(i),
                        "s_m": float(s_values[i]),
                        "pieces_prev": int(prev),
                        "pieces_curr": int(curr),
                        "delta": int(grow),
                        "replica_idx": int(rep),
                        "coincident_events_count": int(take),
                        "event_ambiguous_jump": bool(grow > 1),
                    }
                )
        prev = int(curr)
    return events, diag


__all__ = [
    "BranchPointSample",
    "build_crossline_span",
    "collect_valid_branches_by_direction",
    "compute_pieces_count",
    "crossline_span_points_all_branches",
    "extract_split_events",
]
