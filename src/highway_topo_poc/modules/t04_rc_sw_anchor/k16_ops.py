from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from .io_geojson import RoadRecord
from .local_frame import normalize_vec


@dataclass(frozen=True)
class K16RoadSelection:
    road_index: int
    road: RoadRecord
    road_dir: int
    endpoint_role: str  # "start" | "end" in effective direction
    search_dir: str  # "forward" | "reverse"
    dir_sign: float  # +1.0 | -1.0
    tangent_endpoint_role: str  # snode_start|snode_end|enode_start|enode_end


def find_unique_k16_road(
    nodeid: int,
    roads: list[RoadRecord],
    direction_rules: dict[int, tuple[str, str]] | None = None,
) -> tuple[K16RoadSelection | None, dict[str, Any]]:
    rules = direction_rules or {2: ("snodeid", "enodeid"), 3: ("enodeid", "snodeid")}
    connected: list[tuple[int, RoadRecord]] = []
    for idx, road in enumerate(roads):
        if int(road.snodeid) == int(nodeid) or int(road.enodeid) == int(nodeid):
            connected.append((int(idx), road))

    if len(connected) != 1:
        return None, {
            "ok": False,
            "code": "K16_ROAD_NOT_UNIQUE",
            "reason": "k16_road_not_unique",
            "connected_count": int(len(connected)),
        }

    road_idx, road = connected[0]
    road_dir = int(road.direction) if road.direction is not None else None
    if road_dir not in rules:
        return None, {
            "ok": False,
            "code": "K16_ROAD_DIR_UNSUPPORTED",
            "reason": "k16_road_direction_unsupported",
            "road_direction": road.direction,
            "road_index": int(road_idx),
        }

    start_attr, end_attr = rules[int(road_dir)]
    start_id = int(getattr(road, start_attr))
    end_id = int(getattr(road, end_attr))

    if int(nodeid) == int(start_id):
        endpoint_role = "start"
        search_dir = "forward"
        dir_sign = 1.0
    elif int(nodeid) == int(end_id):
        endpoint_role = "end"
        search_dir = "reverse"
        dir_sign = -1.0
    else:
        return None, {
            "ok": False,
            "code": "K16_ROAD_NOT_UNIQUE",
            "reason": "k16_node_not_on_effective_road_endpoint",
            "road_index": int(road_idx),
            "start_id": int(start_id),
            "end_id": int(end_id),
        }

    if int(nodeid) == int(road.snodeid):
        tangent_endpoint_role = "snode_start" if endpoint_role == "start" else "snode_end"
    elif int(nodeid) == int(road.enodeid):
        tangent_endpoint_role = "enode_start" if endpoint_role == "start" else "enode_end"
    else:
        return None, {
            "ok": False,
            "code": "K16_ROAD_NOT_UNIQUE",
            "reason": "k16_node_not_matched_to_road_snode_or_enode",
            "road_index": int(road_idx),
        }

    return (
        K16RoadSelection(
            road_index=int(road_idx),
            road=road,
            road_dir=int(road_dir),
            endpoint_role=str(endpoint_role),
            search_dir=str(search_dir),
            dir_sign=float(dir_sign),
            tangent_endpoint_role=str(tangent_endpoint_role),
        ),
        {
            "ok": True,
            "road_index": int(road_idx),
            "road_direction": int(road_dir),
            "endpoint_role": str(endpoint_role),
            "search_dir": str(search_dir),
        },
    )


def compute_tangent_at_node(
    road_geom: LineString,
    node_pt: Point,
    endpoint_role: str,
) -> tuple[float, float]:
    _ = node_pt
    coords = list(road_geom.coords)
    if len(coords) < 2:
        raise ValueError("k16_road_geometry_too_short")

    s0 = (float(coords[0][0]), float(coords[0][1]))
    s1 = (float(coords[1][0]), float(coords[1][1]))
    e0 = (float(coords[-2][0]), float(coords[-2][1]))
    e1 = (float(coords[-1][0]), float(coords[-1][1]))
    v_s = (float(s1[0] - s0[0]), float(s1[1] - s0[1]))  # local direction near snode in s->e orientation
    v_e = (float(e1[0] - e0[0]), float(e1[1] - e0[1]))  # local direction near enode in s->e orientation

    role = str(endpoint_role).strip().lower()
    if role == "snode_start":
        vx, vy = v_s
    elif role == "snode_end":
        vx, vy = (-float(v_s[0]), -float(v_s[1]))
    elif role == "enode_start":
        vx, vy = (-float(v_e[0]), -float(v_e[1]))
    elif role == "enode_end":
        vx, vy = v_e
    else:
        raise ValueError(f"k16_invalid_tangent_endpoint_role:{endpoint_role}")
    return normalize_vec(float(vx), float(vy))


def build_crossline(
    center: tuple[float, float],
    perp: tuple[float, float],
    half_len: float = 10.0,
) -> LineString:
    px, py = normalize_vec(float(perp[0]), float(perp[1]))
    cx, cy = (float(center[0]), float(center[1]))
    h = max(0.01, float(half_len))
    return LineString(
        [
            (float(cx - px * h), float(cy - py * h)),
            (float(cx + px * h), float(cy + py * h)),
        ]
    )


def _sample_distances(max_m: float, step_m: float) -> list[float]:
    max_v = max(0.0, float(max_m))
    step = max(0.05, float(step_m))
    out: list[float] = []
    cur = 0.0
    while cur <= max_v + 1e-9:
        out.append(float(cur))
        cur += step
    if not out:
        out = [0.0]
    elif abs(float(out[-1]) - max_v) > 1e-9:
        out.append(float(max_v))
    return out


def search_crossline_hit_drivezone(
    node_pt: Point,
    t: tuple[float, float],
    perp: tuple[float, float],
    drivezone_union: BaseGeometry | None,
    dir_sign: float,
    max_m: float = 10.0,
    step: float = 0.5,
    cross_half_len_m: float = 10.0,
) -> dict[str, Any]:
    tx, ty = normalize_vec(float(t[0]), float(t[1]))
    sign = 1.0 if float(dir_sign) >= 0.0 else -1.0
    samples = _sample_distances(max_m=float(max_m), step_m=float(step))

    hit = False
    s_found_abs: float | None = None
    s_found_signed: float | None = None
    inter_found: BaseGeometry | None = None
    crossline_found: LineString | None = None
    center_found: tuple[float, float] | None = None

    min_dist: float | None = None
    s_best_signed: float | None = None
    crossline_best: LineString | None = None
    center_best: tuple[float, float] | None = None

    for s_abs in samples:
        s_signed = float(sign * float(s_abs))
        cx = float(node_pt.x + tx * s_signed)
        cy = float(node_pt.y + ty * s_signed)
        center_xy = (float(cx), float(cy))
        crossline = build_crossline(center=center_xy, perp=perp, half_len=float(cross_half_len_m))

        if drivezone_union is None or drivezone_union.is_empty:
            continue

        dist = float(crossline.distance(drivezone_union))
        if min_dist is None or dist < float(min_dist):
            min_dist = float(dist)
            s_best_signed = float(s_signed)
            crossline_best = crossline
            center_best = center_xy

        inter = crossline.intersection(drivezone_union)
        if not inter.is_empty:
            hit = True
            s_found_abs = float(s_abs)
            s_found_signed = float(s_signed)
            inter_found = inter
            crossline_found = crossline
            center_found = center_xy
            break

    return {
        "hit": bool(hit),
        "s_found_abs_m": None if s_found_abs is None else float(s_found_abs),
        "s_found_m": None if s_found_signed is None else float(s_found_signed),
        "intersection": inter_found,
        "crossline_found": crossline_found,
        "center_found_xy": center_found,
        "min_dist_cross_to_drivezone_m": None if min_dist is None else float(min_dist),
        "s_best_m": None if s_best_signed is None else float(s_best_signed),
        "crossline_best": crossline_best,
        "center_best_xy": center_best,
        "samples_count": int(len(samples)),
        "max_m": float(max(0.0, float(max_m))),
        "step_m": float(max(0.05, float(step))),
        "dir_sign": float(sign),
    }


__all__ = [
    "K16RoadSelection",
    "build_crossline",
    "compute_tangent_at_node",
    "find_unique_k16_road",
    "search_crossline_hit_drivezone",
]

