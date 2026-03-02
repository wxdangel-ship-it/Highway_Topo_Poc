from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from shapely.geometry import Point

from .io_geojson import RoadRecord
from .local_frame import normalize_vec


def dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(a[0] * b[0] + a[1] * b[1])


def _coords_vec(coords: list[tuple[float, float]], i0: int, i1: int) -> tuple[float, float]:
    x0, y0 = float(coords[i0][0]), float(coords[i0][1])
    x1, y1 = float(coords[i1][0]), float(coords[i1][1])
    return normalize_vec(x1 - x0, y1 - y0)


@dataclass(frozen=True)
class RoadPick:
    road: RoadRecord
    tangent_at_node: tuple[float, float]


class RoadGraph:
    def __init__(
        self,
        *,
        roads: Iterable[RoadRecord],
        node_points: dict[int, Point],
        node_kinds: dict[int, int],
    ) -> None:
        self.roads: list[RoadRecord] = list(roads)
        self.node_points = dict(node_points)
        self.node_kinds = dict(node_kinds)
        self.incident: dict[int, list[int]] = {}
        for idx, road in enumerate(self.roads):
            self.incident.setdefault(int(road.snodeid), []).append(idx)
            self.incident.setdefault(int(road.enodeid), []).append(idx)

    def node_degree(self, nodeid: int) -> int:
        edges = self.incident.get(int(nodeid), [])
        if not edges:
            return 0
        return int(len(set(int(x) for x in edges)))

    def pick_incoming_road(self, nodeid: int) -> RoadPick | None:
        cands = [r for r in self.roads if int(r.enodeid) == int(nodeid)]
        if not cands:
            return None
        chosen = sorted(cands, key=lambda r: float(r.length_m), reverse=True)[0]
        tangent = self.compute_tangent_at_node(chosen, nodeid=int(nodeid))
        return RoadPick(road=chosen, tangent_at_node=tangent)

    def pick_outgoing_road(self, nodeid: int) -> RoadPick | None:
        cands = [r for r in self.roads if int(r.snodeid) == int(nodeid)]
        if not cands:
            return None
        chosen = sorted(cands, key=lambda r: float(r.length_m), reverse=True)[0]
        tangent = self.compute_tangent_at_node(chosen, nodeid=int(nodeid))
        return RoadPick(road=chosen, tangent_at_node=tangent)

    def compute_tangent_at_node(self, road: RoadRecord, *, nodeid: int) -> tuple[float, float]:
        coords = list(road.line.coords)
        if len(coords) < 2:
            return (1.0, 0.0)

        if int(nodeid) == int(road.snodeid):
            return _coords_vec(coords, 0, 1)
        if int(nodeid) == int(road.enodeid):
            return _coords_vec(coords, len(coords) - 2, len(coords) - 1)

        p = self.node_points.get(int(nodeid))
        if p is None:
            return _coords_vec(coords, 0, 1)

        sx, sy = float(coords[0][0]), float(coords[0][1])
        ex, ey = float(coords[-1][0]), float(coords[-1][1])
        ds = math.hypot(sx - p.x, sy - p.y)
        de = math.hypot(ex - p.x, ey - p.y)
        if ds <= de:
            return _coords_vec(coords, 0, 1)
        return _coords_vec(coords, len(coords) - 2, len(coords) - 1)

    def _other_node(self, road_idx: int, nodeid: int) -> int | None:
        road = self.roads[road_idx]
        if int(road.snodeid) == int(nodeid):
            return int(road.enodeid)
        if int(road.enodeid) == int(nodeid):
            return int(road.snodeid)
        return None

    def _edge_direction_away(self, road_idx: int, nodeid: int) -> tuple[float, float]:
        road = self.roads[road_idx]
        coords = list(road.line.coords)
        if len(coords) < 2:
            return (1.0, 0.0)
        if int(nodeid) == int(road.snodeid):
            return _coords_vec(coords, 0, 1)
        if int(nodeid) == int(road.enodeid):
            return _coords_vec(coords, len(coords) - 1, len(coords) - 2)
        return (1.0, 0.0)

    def _is_intersection_kind(self, nodeid: int, mask: int | None) -> bool:
        if mask is None:
            return True
        kind = int(self.node_kinds.get(int(nodeid), 0))
        return (kind & int(mask)) != 0

    def _walk_candidate_connected(
        self,
        *,
        start_nodeid: int,
        start_edge_idx: int,
        initial_dir: tuple[float, float],
        degree_min: int,
        intersection_kind_mask: int | None,
        max_hops: int,
    ) -> tuple[float | None, dict[str, int]]:
        road = self.roads[start_edge_idx]
        other = self._other_node(start_edge_idx, start_nodeid)
        if other is None:
            return None, {"deg_too_low_skipped": 0}

        total = float(road.length_m)
        prev_node = int(start_nodeid)
        curr_node = int(other)
        curr_edge_idx = int(start_edge_idx)
        direction = normalize_vec(initial_dir[0], initial_dir[1])

        diag = {"deg_too_low_skipped": 0}
        for _ in range(max_hops):
            if curr_node != int(start_nodeid):
                deg = self.node_degree(curr_node)
                if deg >= int(degree_min) and self._is_intersection_kind(curr_node, intersection_kind_mask):
                    return total, diag
                if deg < int(degree_min):
                    diag["deg_too_low_skipped"] += 1

            edge_candidates = self.incident.get(curr_node, [])
            best_edge_idx: int | None = None
            best_align = -999.0
            best_len = -1.0
            best_dir = (1.0, 0.0)
            best_next_node: int | None = None

            for eidx in edge_candidates:
                if int(eidx) == int(curr_edge_idx):
                    continue
                next_node = self._other_node(eidx, curr_node)
                if next_node is None:
                    continue
                if int(next_node) == int(prev_node):
                    continue

                cand_dir = self._edge_direction_away(eidx, curr_node)
                align = dot(cand_dir, direction)
                road_len = float(self.roads[eidx].length_m)

                if align > best_align + 1e-9 or (abs(align - best_align) <= 1e-9 and road_len > best_len):
                    best_align = align
                    best_len = road_len
                    best_edge_idx = int(eidx)
                    best_dir = cand_dir
                    best_next_node = int(next_node)

            if best_edge_idx is None:
                return None, diag
            if best_align < -0.25:
                return None, diag

            total += float(self.roads[best_edge_idx].length_m)
            prev_node = curr_node
            curr_node = int(best_next_node)
            curr_edge_idx = int(best_edge_idx)
            direction = normalize_vec(best_dir[0], best_dir[1])

        return None, diag

    def _walk_candidate_connected_with_node(
        self,
        *,
        start_nodeid: int,
        start_edge_idx: int,
        initial_dir: tuple[float, float],
        degree_min: int,
        intersection_kind_mask: int | None,
        max_hops: int,
    ) -> tuple[float | None, int | None, dict[str, int]]:
        road = self.roads[start_edge_idx]
        other = self._other_node(start_edge_idx, start_nodeid)
        if other is None:
            return None, None, {"deg_too_low_skipped": 0}

        total = float(road.length_m)
        prev_node = int(start_nodeid)
        curr_node = int(other)
        curr_edge_idx = int(start_edge_idx)
        direction = normalize_vec(initial_dir[0], initial_dir[1])

        diag = {"deg_too_low_skipped": 0}
        for _ in range(max_hops):
            if curr_node != int(start_nodeid):
                deg = self.node_degree(curr_node)
                if deg >= int(degree_min) and self._is_intersection_kind(curr_node, intersection_kind_mask):
                    return total, int(curr_node), diag
                if deg < int(degree_min):
                    diag["deg_too_low_skipped"] += 1

            edge_candidates = self.incident.get(curr_node, [])
            best_edge_idx: int | None = None
            best_align = -999.0
            best_len = -1.0
            best_dir = (1.0, 0.0)
            best_next_node: int | None = None

            for eidx in edge_candidates:
                if int(eidx) == int(curr_edge_idx):
                    continue
                next_node = self._other_node(eidx, curr_node)
                if next_node is None:
                    continue
                if int(next_node) == int(prev_node):
                    continue

                cand_dir = self._edge_direction_away(eidx, curr_node)
                align = dot(cand_dir, direction)
                road_len = float(self.roads[eidx].length_m)

                if align > best_align + 1e-9 or (abs(align - best_align) <= 1e-9 and road_len > best_len):
                    best_align = align
                    best_len = road_len
                    best_edge_idx = int(eidx)
                    best_dir = cand_dir
                    best_next_node = int(next_node)

            if best_edge_idx is None:
                return None, None, diag
            if best_align < -0.25:
                return None, None, diag

            total += float(self.roads[best_edge_idx].length_m)
            prev_node = curr_node
            curr_node = int(best_next_node)
            curr_edge_idx = int(best_edge_idx)
            direction = normalize_vec(best_dir[0], best_dir[1])

        return None, None, diag

    def _fallback_projection_distance(self, *, start_nodeid: int, scan_dir: tuple[float, float], mask: int) -> float | None:
        start_pt = self.node_points.get(int(start_nodeid))
        if start_pt is None:
            return None

        sx, sy = float(start_pt.x), float(start_pt.y)
        dir_u = normalize_vec(scan_dir[0], scan_dir[1])

        best: float | None = None
        for nid, kind in self.node_kinds.items():
            if int(nid) == int(start_nodeid):
                continue
            if (int(kind) & int(mask)) == 0:
                continue
            pt = self.node_points.get(int(nid))
            if pt is None:
                continue

            dx = float(pt.x) - sx
            dy = float(pt.y) - sy
            proj = dx * dir_u[0] + dy * dir_u[1]
            if proj <= 1e-6:
                continue

            px = dx - proj * dir_u[0]
            py = dy - proj * dir_u[1]
            perp = math.hypot(px, py)
            if perp > 40.0:
                continue

            if best is None or proj < best:
                best = float(proj)

        return best

    def find_next_intersection_distance_connected(
        self,
        *,
        nodeid: int,
        scan_dir: tuple[float, float],
        degree_min: int = 3,
        intersection_kind_mask: int | None = 0b11100,
        max_hops: int = 64,
        disable_geometric_fallback: bool = True,
    ) -> tuple[float | None, dict[str, object]]:
        dir_u = normalize_vec(scan_dir[0], scan_dir[1])
        start_edges = []
        for eidx in self.incident.get(int(nodeid), []):
            away = self._edge_direction_away(eidx, int(nodeid))
            align = dot(away, dir_u)
            if align > 0.0:
                start_edges.append((align, float(self.roads[eidx].length_m), int(eidx), away))

        start_edges.sort(key=lambda x: (x[0], x[1]), reverse=True)

        distances: list[float] = []
        deg_too_low_skipped = 0
        for _align, _length, edge_idx, away in start_edges:
            d, path_diag = self._walk_candidate_connected(
                start_nodeid=int(nodeid),
                start_edge_idx=int(edge_idx),
                initial_dir=away,
                degree_min=int(degree_min),
                intersection_kind_mask=None if intersection_kind_mask is None else int(intersection_kind_mask),
                max_hops=int(max_hops),
            )
            deg_too_low_skipped += int(path_diag.get("deg_too_low_skipped", 0))
            if d is not None and d > 0:
                distances.append(float(d))

        if distances:
            return float(min(distances)), {
                "start_edges_count": int(len(start_edges)),
                "degree_min": int(degree_min),
                "deg_too_low_skipped": int(deg_too_low_skipped),
                "used_fallback": False,
                "low_confidence_fallback": False,
            }

        if not bool(disable_geometric_fallback):
            fb = self._fallback_projection_distance(
                start_nodeid=int(nodeid),
                scan_dir=dir_u,
                mask=int(intersection_kind_mask) if intersection_kind_mask is not None else 0,
            )
            if fb is not None and fb > 0:
                return float(fb), {
                    "start_edges_count": int(len(start_edges)),
                    "degree_min": int(degree_min),
                    "deg_too_low_skipped": int(deg_too_low_skipped),
                    "used_fallback": True,
                    "low_confidence_fallback": True,
                }

        return None, {
            "start_edges_count": int(len(start_edges)),
            "degree_min": int(degree_min),
            "deg_too_low_skipped": int(deg_too_low_skipped),
            "used_fallback": False,
            "low_confidence_fallback": False,
        }

    def find_next_intersection_distance(
        self,
        *,
        nodeid: int,
        scan_dir: tuple[float, float],
        intersection_kind_mask: int = 0b11100,
        max_hops: int = 64,
    ) -> float | None:
        dist, _diag = self.find_next_intersection_distance_connected(
            nodeid=nodeid,
            scan_dir=scan_dir,
            degree_min=3,
            intersection_kind_mask=int(intersection_kind_mask),
            max_hops=int(max_hops),
            disable_geometric_fallback=True,
        )
        return dist

    def find_next_intersection_connected_deg3(
        self,
        *,
        nodeid: int,
        scan_dir: tuple[float, float],
        degree_min: int = 3,
        max_hops: int = 64,
    ) -> tuple[float | None, dict[str, object]]:
        dir_u = normalize_vec(scan_dir[0], scan_dir[1])
        start_edges = []
        for eidx in self.incident.get(int(nodeid), []):
            away = self._edge_direction_away(eidx, int(nodeid))
            align = dot(away, dir_u)
            if align > 0.0:
                start_edges.append((align, float(self.roads[eidx].length_m), int(eidx), away))

        start_edges.sort(key=lambda x: (x[0], x[1]), reverse=True)

        best_dist: float | None = None
        best_nodeid: int | None = None
        deg_too_low_skipped = 0
        for _align, _length, edge_idx, away in start_edges:
            d, hit_nodeid, path_diag = self._walk_candidate_connected_with_node(
                start_nodeid=int(nodeid),
                start_edge_idx=int(edge_idx),
                initial_dir=away,
                degree_min=int(degree_min),
                intersection_kind_mask=None,
                max_hops=int(max_hops),
            )
            deg_too_low_skipped += int(path_diag.get("deg_too_low_skipped", 0))
            if d is None or d <= 0 or hit_nodeid is None:
                continue
            if best_dist is None or float(d) < float(best_dist):
                best_dist = float(d)
                best_nodeid = int(hit_nodeid)

        return best_dist, {
            "start_edges_count": int(len(start_edges)),
            "degree_min": int(degree_min),
            "deg_too_low_skipped": int(deg_too_low_skipped),
            "next_intersection_nodeid": best_nodeid,
            "used_fallback": False,
        }


__all__ = ["RoadGraph", "RoadPick", "dot"]
