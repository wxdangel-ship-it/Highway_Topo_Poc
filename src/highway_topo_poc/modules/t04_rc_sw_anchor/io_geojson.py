from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union


@dataclass(frozen=True)
class NodeRecord:
    nodeid: int
    kind: int
    point: Point


@dataclass(frozen=True)
class IntersectionLineRecord:
    nodeid: int
    line: LineString


@dataclass(frozen=True)
class RoadRecord:
    snodeid: int
    enodeid: int
    line: LineString
    length_m: float


def _to_int(value: Any, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value).strip())
    except Exception:
        return default


def read_geojson(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"geojson_not_found: {path}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"geojson_parse_failed: {path}: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError(f"geojson_not_feature_collection: {path}")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError(f"geojson_features_not_list: {path}")
    return payload


def write_geojson(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_crs_name(payload: dict[str, Any]) -> str | None:
    crs = payload.get("crs")
    if not isinstance(crs, dict):
        return None
    props = crs.get("properties")
    if not isinstance(props, dict):
        return None
    name = props.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def make_feature_collection(features: list[dict[str, Any]], *, crs_name: str | None) -> dict[str, Any]:
    obj: dict[str, Any] = {"type": "FeatureCollection", "features": features}
    if crs_name:
        obj["crs"] = {"type": "name", "properties": {"name": crs_name}}
    return obj


def load_nodes(payload: dict[str, Any]) -> tuple[list[NodeRecord], list[str]]:
    errors: list[str] = []
    out: list[NodeRecord] = []

    for idx, feat in enumerate(payload.get("features", [])):
        if not isinstance(feat, dict):
            errors.append(f"node_feature_not_object:{idx}")
            continue

        geom = feat.get("geometry")
        if not isinstance(geom, dict):
            errors.append(f"node_geometry_missing:{idx}")
            continue

        try:
            g = shape(geom)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"node_geometry_invalid:{idx}:{type(exc).__name__}")
            continue

        if not isinstance(g, Point):
            errors.append(f"node_geometry_not_point:{idx}")
            continue

        props = feat.get("properties")
        props = props if isinstance(props, dict) else {}

        nodeid = _to_int(props.get("mainid"), default=None)
        if nodeid is None:
            nodeid = _to_int(props.get("id"), default=None)
        if nodeid is None:
            errors.append(f"nodeid_missing:{idx}")
            continue

        kind = _to_int(props.get("Kind"), default=0)
        out.append(NodeRecord(nodeid=int(nodeid), kind=int(kind or 0), point=g))

    return out, errors


def load_intersection_lines(payload: dict[str, Any]) -> tuple[list[IntersectionLineRecord], list[str]]:
    errors: list[str] = []
    out: list[IntersectionLineRecord] = []

    for idx, feat in enumerate(payload.get("features", [])):
        if not isinstance(feat, dict):
            errors.append(f"intersection_feature_not_object:{idx}")
            continue

        geom = feat.get("geometry")
        if not isinstance(geom, dict):
            errors.append(f"intersection_geometry_missing:{idx}")
            continue

        try:
            g = shape(geom)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"intersection_geometry_invalid:{idx}:{type(exc).__name__}")
            continue

        if not isinstance(g, LineString):
            errors.append(f"intersection_geometry_not_linestring:{idx}")
            continue

        props = feat.get("properties")
        props = props if isinstance(props, dict) else {}

        nodeid = _to_int(props.get("nodeid"), default=None)
        if nodeid is None:
            nodeid = _to_int(props.get("mainid"), default=None)
        if nodeid is None:
            nodeid = _to_int(props.get("id"), default=None)
        if nodeid is None:
            errors.append(f"intersection_nodeid_missing:{idx}")
            continue

        out.append(IntersectionLineRecord(nodeid=int(nodeid), line=g))

    return out, errors


def load_roads(payload: dict[str, Any]) -> tuple[list[RoadRecord], list[str]]:
    errors: list[str] = []
    out: list[RoadRecord] = []

    for idx, feat in enumerate(payload.get("features", [])):
        if not isinstance(feat, dict):
            errors.append(f"road_feature_not_object:{idx}")
            continue

        geom = feat.get("geometry")
        if not isinstance(geom, dict):
            errors.append(f"road_geometry_missing:{idx}")
            continue

        try:
            g = shape(geom)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"road_geometry_invalid:{idx}:{type(exc).__name__}")
            continue

        if not isinstance(g, LineString):
            errors.append(f"road_geometry_not_linestring:{idx}")
            continue

        props = feat.get("properties")
        props = props if isinstance(props, dict) else {}

        snodeid = _to_int(props.get("snodeid"), default=None)
        enodeid = _to_int(props.get("enodeid"), default=None)
        if snodeid is None or enodeid is None:
            errors.append(f"road_nodeid_missing:{idx}")
            continue

        out.append(
            RoadRecord(
                snodeid=int(snodeid),
                enodeid=int(enodeid),
                line=g,
                length_m=float(g.length),
            )
        )

    return out, errors


def load_divstrip_union(payload: dict[str, Any]) -> tuple[Any | None, list[str]]:
    errors: list[str] = []
    geoms: list[Any] = []

    for idx, feat in enumerate(payload.get("features", [])):
        if not isinstance(feat, dict):
            errors.append(f"divstrip_feature_not_object:{idx}")
            continue
        geom = feat.get("geometry")
        if not isinstance(geom, dict):
            continue

        try:
            g = shape(geom)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"divstrip_geometry_invalid:{idx}:{type(exc).__name__}")
            continue

        if g.is_empty:
            continue

        gt = g.geom_type
        if gt in {"Polygon", "MultiPolygon"}:
            geoms.append(g)

    if not geoms:
        return None, errors

    try:
        return unary_union(geoms), errors
    except Exception as exc:  # noqa: BLE001
        errors.append(f"divstrip_union_failed:{type(exc).__name__}")
        return None, errors


__all__ = [
    "NodeRecord",
    "IntersectionLineRecord",
    "RoadRecord",
    "extract_crs_name",
    "load_divstrip_union",
    "load_intersection_lines",
    "load_nodes",
    "load_roads",
    "make_feature_collection",
    "read_geojson",
    "write_geojson",
]
