from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

from shapely.geometry import LineString, Point, shape

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

_NODE_ID_KEYS = ["id", "nodeid", "mainid", "mainnodeid"]
_MAINID_KEYS = ["mainid", "mainnodeid"]
_KIND_KEYS = ["kind"]
_ROAD_ID_KEYS = ["roadid", "id", "mainid"]
_DIRECTION_KEYS = ["direction"]
_SNODE_KEYS = ["snodeid", "src", "from", "startid"]
_ENODE_KEYS = ["enodeid", "dst", "to", "endid"]


@dataclass(frozen=True)
class NormalizedNode:
    node_id: Any
    mainid: Any
    kind: int | None
    point: Point
    raw_properties: dict[str, Any]


@dataclass(frozen=True)
class NormalizedRoad:
    road_id: str
    direction: int | None
    snodeid: Any
    enodeid: Any
    line: LineString
    raw_properties: dict[str, Any]


def normalize_key(key: str) -> str:
    return _NON_ALNUM.sub("", str(key).strip().lower())


def normalize_props(props: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw_key, value in props.items():
        nk = normalize_key(str(raw_key))
        if nk and nk not in out:
            out[nk] = value
    return out


def get_first_raw(props_norm: dict[str, Any], keys: Iterable[str]) -> Any | None:
    for key in keys:
        nk = normalize_key(key)
        if nk in props_norm and props_norm[nk] is not None:
            return props_norm[nk]
    return None


def get_first_int(props_norm: dict[str, Any], keys: Iterable[str]) -> int | None:
    raw = get_first_raw(props_norm, keys)
    if raw is None:
        return None
    try:
        if isinstance(raw, bool):
            return int(raw)
        if isinstance(raw, int):
            return raw
        if isinstance(raw, float):
            return int(raw)
        return int(str(raw).strip())
    except Exception:
        return None


def _as_linestring(geometry: Any) -> LineString:
    geom = shape(geometry)
    if isinstance(geom, LineString):
        return geom
    if geom.geom_type == "MultiLineString":
        parts = list(geom.geoms)
        if not parts:
            raise ValueError("road_geometry_empty")
        return max(parts, key=lambda item: float(item.length))
    raise ValueError(f"unsupported_road_geometry:{geom.geom_type}")


def normalize_node_features(features: Iterable[dict[str, Any]]) -> list[NormalizedNode]:
    nodes: list[NormalizedNode] = []
    for idx, feature in enumerate(features):
        props = dict(feature.get("properties") or {})
        props_norm = normalize_props(props)
        node_id = get_first_raw(props_norm, _NODE_ID_KEYS)
        if node_id is None:
            raise ValueError(f"node_id_missing[{idx}]")
        mainid = get_first_raw(props_norm, _MAINID_KEYS)
        if mainid is None:
            mainid = node_id
        kind = get_first_int(props_norm, _KIND_KEYS)
        geom = shape(feature.get("geometry"))
        if not isinstance(geom, Point):
            raise ValueError(f"node_geometry_not_point[{idx}]")
        nodes.append(
            NormalizedNode(
                node_id=node_id,
                mainid=mainid,
                kind=kind,
                point=geom,
                raw_properties=props,
            )
        )
    return nodes


def normalize_road_features(features: Iterable[dict[str, Any]]) -> list[NormalizedRoad]:
    roads: list[NormalizedRoad] = []
    for idx, feature in enumerate(features):
        props = dict(feature.get("properties") or {})
        props_norm = normalize_props(props)
        road_id_raw = get_first_raw(props_norm, _ROAD_ID_KEYS)
        road_id = str(road_id_raw) if road_id_raw is not None else f"road_{idx}"
        direction = get_first_int(props_norm, _DIRECTION_KEYS)
        snodeid = get_first_raw(props_norm, _SNODE_KEYS)
        enodeid = get_first_raw(props_norm, _ENODE_KEYS)
        if snodeid is None or enodeid is None:
            raise ValueError(f"road_endpoint_missing[{road_id}]")
        roads.append(
            NormalizedRoad(
                road_id=road_id,
                direction=direction,
                snodeid=snodeid,
                enodeid=enodeid,
                line=_as_linestring(feature.get("geometry")),
                raw_properties=props,
            )
        )
    return roads


def vector_angle_deg(dx: float, dy: float) -> float:
    ang = math.degrees(math.atan2(dy, dx))
    if ang < 0:
        ang += 360.0
    return float(ang)


def circular_diff_deg(a: float, b: float) -> float:
    diff = abs(float(a) - float(b)) % 360.0
    return min(diff, 360.0 - diff)


def normalize_vec(dx: float, dy: float) -> tuple[float, float]:
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return (1.0, 0.0)
    return (float(dx / length), float(dy / length))


def coord_xy(coord: Any) -> tuple[float, float]:
    if not isinstance(coord, (list, tuple)) or len(coord) < 2:
        raise ValueError("invalid_coordinate_tuple")
    return (float(coord[0]), float(coord[1]))


def road_away_vector(road: NormalizedRoad, *, node_id: Any) -> tuple[float, float]:
    coords = list(road.line.coords)
    if len(coords) < 2:
        return (1.0, 0.0)
    if road.snodeid == node_id:
        x0, y0 = coord_xy(coords[0])
        x1, y1 = coord_xy(coords[1])
        return normalize_vec(x1 - x0, y1 - y0)
    if road.enodeid == node_id:
        x0, y0 = coord_xy(coords[-1])
        x1, y1 = coord_xy(coords[-2])
        return normalize_vec(x1 - x0, y1 - y0)
    x0, y0 = coord_xy(coords[0])
    x1, y1 = coord_xy(coords[1])
    return normalize_vec(x1 - x0, y1 - y0)


def road_trend_vector(road: NormalizedRoad, *, node_id: Any) -> tuple[float, float]:
    coords = list(road.line.coords)
    if len(coords) < 2:
        return (1.0, 0.0)
    if road.snodeid == node_id:
        ref_idx = min(len(coords) - 1, max(1, len(coords) // 2))
        x0, y0 = coord_xy(coords[0])
        x1, y1 = coord_xy(coords[ref_idx])
        return normalize_vec(x1 - x0, y1 - y0)
    if road.enodeid == node_id:
        ref_idx = max(0, min(len(coords) - 2, len(coords) // 2 - 1))
        x0, y0 = coord_xy(coords[-1])
        x1, y1 = coord_xy(coords[ref_idx])
        return normalize_vec(x1 - x0, y1 - y0)
    return road_away_vector(road, node_id=node_id)
