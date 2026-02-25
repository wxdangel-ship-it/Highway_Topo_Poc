from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .crs_norm import compute_geojson_bbox, load_geojson_and_reproject, normalize_epsg_name, parse_geojson_crs
from .field_norm import get_first_int, get_first_raw, normalize_props


@dataclass(frozen=True)
class NodeRecord:
    nodeid: int
    kind: int | None
    point: Point
    # (field_name, id_value), field_name in normalized namespace.
    id_fields: tuple[tuple[str, int], ...] = ()
    kind_raw: Any | None = None


@dataclass(frozen=True)
class RoadRecord:
    snodeid: int
    enodeid: int
    line: LineString
    length_m: float


@dataclass(frozen=True)
class IntersectionLineRecord:
    nodeid: int
    line: LineString


@dataclass(frozen=True)
class GeoLoadMeta:
    path: str
    src_crs: str
    dst_crs: str
    total_features: int
    kept_features: int
    src_crs_detected: str | None = None
    guess_source: str = "unknown"
    bbox_src: tuple[float, float, float, float] | None = None
    bbox_dst: tuple[float, float, float, float] | None = None


def read_geojson(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"geojson_not_found: {path}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"geojson_parse_failed: {path}: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError(f"geojson_not_feature_collection: {path}")
    if not isinstance(payload.get("features"), list):
        raise ValueError(f"geojson_features_not_list: {path}")
    return payload


def write_geojson(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_feature_collection(features: list[dict[str, Any]], *, crs_name: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "FeatureCollection", "features": features}
    if crs_name:
        payload["crs"] = {"type": "name", "properties": {"name": str(crs_name)}}
    return payload


def extract_crs_name(payload: dict[str, Any]) -> str | None:
    return parse_geojson_crs(payload)


def infer_lonlat_like_bbox(min_x: float, min_y: float, max_x: float, max_y: float) -> bool:
    vals = [min_x, min_y, max_x, max_y]
    if any((not isinstance(v, (int, float)) or not math.isfinite(float(v))) for v in vals):
        return False
    return abs(min_x) <= 180.0 and abs(max_x) <= 180.0 and abs(min_y) <= 90.0 and abs(max_y) <= 90.0


def resolve_source_crs(payload: dict[str, Any], *, src_crs_override: str) -> str:
    override = str(src_crs_override).strip() if src_crs_override is not None else ""
    if override and override.lower() != "auto":
        out = normalize_epsg_name(override)
        if out is None:
            raise ValueError(f"invalid_src_crs_override:{src_crs_override}")
        return out

    src = extract_crs_name(payload)
    if src:
        return src

    bbox = compute_geojson_bbox(payload)
    if bbox is not None and infer_lonlat_like_bbox(*bbox):
        return "EPSG:4326"
    return "EPSG:3857"


def _build_meta(path: Path, meta_dict: dict[str, Any], total: int, kept: int) -> GeoLoadMeta:
    src_used = meta_dict.get("src_crs_used")
    dst_used = meta_dict.get("dst_crs")
    return GeoLoadMeta(
        path=str(path),
        src_crs=str(src_used) if src_used else "UNKNOWN",
        dst_crs=str(dst_used) if dst_used else "UNKNOWN",
        total_features=int(total),
        kept_features=int(kept),
        src_crs_detected=None if meta_dict.get("src_crs_detected") is None else str(meta_dict.get("src_crs_detected")),
        guess_source=str(meta_dict.get("guess_source", "unknown")),
        bbox_src=meta_dict.get("bbox_src"),
        bbox_dst=meta_dict.get("bbox_dst"),
    )


def _load_reprojected(
    *,
    path: Path,
    src_crs_override: str,
    dst_crs: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, meta = load_geojson_and_reproject(path=path, src_crs_hint=src_crs_override, dst_crs=dst_crs)
    feats = payload.get("features", [])
    if not isinstance(feats, list):
        raise ValueError(f"geojson_features_not_list:{path}")
    return payload, meta


def _int_field(props_norm: dict[str, Any], keys: list[str]) -> int | None:
    return get_first_int(props_norm, keys)


def load_nodes(
    *,
    path: Path,
    src_crs_override: str,
    dst_crs: str,
    aoi: BaseGeometry | None = None,
) -> tuple[list[NodeRecord], GeoLoadMeta, list[str]]:
    payload, src_meta = _load_reprojected(path=path, src_crs_override=src_crs_override, dst_crs=dst_crs)
    errors: list[str] = []
    out: list[NodeRecord] = []
    total = 0

    for idx, feat in enumerate(payload.get("features", [])):
        total += 1
        if not isinstance(feat, dict):
            errors.append(f"node_feature_not_object:{idx}")
            continue

        props = feat.get("properties")
        props = props if isinstance(props, dict) else {}
        props_norm = normalize_props(props)

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

        if aoi is not None and not g.intersects(aoi):
            continue

        raw_id_pairs: list[tuple[str, int]] = []
        for key in ["mainid", "mainnodeid", "id", "nodeid"]:
            val = _int_field(props_norm, [key])
            if val is not None:
                raw_id_pairs.append((key, int(val)))

        if not raw_id_pairs:
            errors.append(f"nodeid_missing:{idx}")
            continue

        id_pairs: list[tuple[str, int]] = []
        seen_val: set[int] = set()
        for field, value in raw_id_pairs:
            if value in seen_val:
                continue
            seen_val.add(value)
            id_pairs.append((field, value))

        kind = _int_field(props_norm, ["kind"])
        kind_raw = get_first_raw(props_norm, ["kind"])
        if kind is None and kind_raw is not None:
            errors.append(f"kind_parse_error:{idx}:{kind_raw!r}")

        out.append(
            NodeRecord(
                nodeid=int(id_pairs[0][1]),
                kind=None if kind is None else int(kind),
                point=Point(float(g.x), float(g.y)),
                id_fields=tuple(id_pairs),
                kind_raw=kind_raw,
            )
        )

    meta = _build_meta(path, src_meta, total, len(out))
    return out, meta, errors


def load_roads(
    *,
    path: Path,
    src_crs_override: str,
    dst_crs: str,
    aoi: BaseGeometry | None = None,
) -> tuple[list[RoadRecord], GeoLoadMeta, list[str]]:
    payload, src_meta = _load_reprojected(path=path, src_crs_override=src_crs_override, dst_crs=dst_crs)
    errors: list[str] = []
    out: list[RoadRecord] = []
    total = 0

    for idx, feat in enumerate(payload.get("features", [])):
        total += 1
        if not isinstance(feat, dict):
            errors.append(f"road_feature_not_object:{idx}")
            continue

        props = feat.get("properties")
        props = props if isinstance(props, dict) else {}
        props_norm = normalize_props(props)

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

        if aoi is not None and not g.intersects(aoi):
            continue

        snodeid = _int_field(props_norm, ["snodeid", "startnodeid", "fromnodeid", "startid", "snode"])
        enodeid = _int_field(props_norm, ["enodeid", "endnodeid", "tonodeid", "endid", "enode"])
        if snodeid is None or enodeid is None:
            errors.append(f"road_field_missing:{idx}:snodeid_or_enodeid")
            continue

        out.append(
            RoadRecord(
                snodeid=int(snodeid),
                enodeid=int(enodeid),
                line=g,
                length_m=float(g.length),
            )
        )

    meta = _build_meta(path, src_meta, total, len(out))
    return out, meta, errors


def load_intersection_lines(
    *,
    path: Path,
    src_crs_override: str,
    dst_crs: str,
    aoi: BaseGeometry | None = None,
) -> tuple[list[IntersectionLineRecord], GeoLoadMeta, list[str]]:
    payload, src_meta = _load_reprojected(path=path, src_crs_override=src_crs_override, dst_crs=dst_crs)
    errors: list[str] = []
    out: list[IntersectionLineRecord] = []
    total = 0

    for idx, feat in enumerate(payload.get("features", [])):
        total += 1
        if not isinstance(feat, dict):
            errors.append(f"intersection_feature_not_object:{idx}")
            continue

        props = feat.get("properties")
        props = props if isinstance(props, dict) else {}
        props_norm = normalize_props(props)

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

        if aoi is not None and not g.intersects(aoi):
            continue

        nodeid = _int_field(props_norm, ["nodeid", "mainid", "mainnodeid", "id"])
        if nodeid is None:
            errors.append(f"intersection_nodeid_missing:{idx}")
            continue
        out.append(IntersectionLineRecord(nodeid=int(nodeid), line=g))

    meta = _build_meta(path, src_meta, total, len(out))
    return out, meta, errors


def load_divstrip_union(
    *,
    path: Path,
    src_crs_override: str,
    dst_crs: str,
    aoi: BaseGeometry | None = None,
) -> tuple[BaseGeometry | None, GeoLoadMeta, list[str]]:
    payload, src_meta = _load_reprojected(path=path, src_crs_override=src_crs_override, dst_crs=dst_crs)
    errors: list[str] = []
    geoms: list[BaseGeometry] = []
    total = 0

    for idx, feat in enumerate(payload.get("features", [])):
        total += 1
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
        if g.geom_type not in {"Polygon", "MultiPolygon"}:
            continue

        if aoi is not None and not g.intersects(aoi):
            continue
        geoms.append(g)

    union = None
    if geoms:
        try:
            union = unary_union(geoms)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"divstrip_union_failed:{type(exc).__name__}")

    meta = _build_meta(path, src_meta, total, len(geoms))
    return union, meta, errors


__all__ = [
    "GeoLoadMeta",
    "IntersectionLineRecord",
    "NodeRecord",
    "RoadRecord",
    "extract_crs_name",
    "infer_lonlat_like_bbox",
    "load_divstrip_union",
    "load_intersection_lines",
    "load_nodes",
    "load_roads",
    "make_feature_collection",
    "read_geojson",
    "resolve_source_crs",
    "write_geojson",
]
