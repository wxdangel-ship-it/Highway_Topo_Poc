from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

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


def _iter_coords_any(geom: Any) -> Iterable[tuple[float, float]]:
    if not isinstance(geom, dict):
        return []
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if gtype == "Point" and isinstance(coords, list) and len(coords) >= 2:
        return [(float(coords[0]), float(coords[1]))]

    out: list[tuple[float, float]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, list):
            if len(obj) >= 2 and all(isinstance(x, (int, float)) for x in obj[:2]):
                out.append((float(obj[0]), float(obj[1])))
                return
            for it in obj:
                walk(it)

    walk(coords)
    return out


def _guess_src_crs_from_payload(payload: dict[str, Any]) -> str:
    feats = payload.get("features")
    if not isinstance(feats, list):
        return "EPSG:3857"

    sample: list[tuple[float, float]] = []
    for feat in feats[:200]:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry")
        for xy in _iter_coords_any(geom):
            sample.append(xy)
            if len(sample) >= 1000:
                break
        if len(sample) >= 1000:
            break

    if not sample:
        return "EPSG:3857"

    lonlat_like = sum(1 for x, y in sample if abs(x) <= 180.0 and abs(y) <= 90.0)
    if lonlat_like >= int(0.95 * len(sample)):
        return "EPSG:4326"
    return "EPSG:3857"


def resolve_source_crs(payload: dict[str, Any], *, src_crs_override: str) -> str:
    explicit = str(src_crs_override).strip()
    if explicit and explicit.lower() != "auto":
        return explicit

    from_payload = extract_crs_name(payload)
    if from_payload:
        return from_payload

    return _guess_src_crs_from_payload(payload)


def _build_transformer(src_crs: str, dst_crs: str) -> Transformer:
    return Transformer.from_crs(src_crs, dst_crs, always_xy=True)


def _project_geom(geom: BaseGeometry, transformer: Transformer | None) -> BaseGeometry:
    if transformer is None:
        return geom
    return transform(transformer.transform, geom)


def _int_field(props_norm: dict[str, Any], keys: list[str]) -> int | None:
    return get_first_int(props_norm, keys)


def load_nodes(
    *,
    path: Path,
    src_crs_override: str,
    dst_crs: str,
    aoi: BaseGeometry | None = None,
) -> tuple[list[NodeRecord], GeoLoadMeta, list[str]]:
    payload = read_geojson(path)
    src_crs = resolve_source_crs(payload, src_crs_override=src_crs_override)
    transformer = None if src_crs == dst_crs else _build_transformer(src_crs, dst_crs)

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

        g2 = _project_geom(g, transformer)
        if aoi is not None and not g2.intersects(aoi):
            continue

        # Keep all id aliases for later canonical alignment in runner.
        raw_id_pairs: list[tuple[str, int]] = []
        for key in ["mainid", "mainnodeid", "id", "nodeid"]:
            val = _int_field(props_norm, [key])
            if val is not None:
                raw_id_pairs.append((key, int(val)))

        if not raw_id_pairs:
            errors.append(f"nodeid_missing:{idx}")
            continue

        # Dedup while preserving first-seen field order.
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
                point=Point(float(g2.x), float(g2.y)),
                id_fields=tuple(id_pairs),
                kind_raw=kind_raw,
            )
        )

    meta = GeoLoadMeta(
        path=str(path),
        src_crs=str(src_crs),
        dst_crs=str(dst_crs),
        total_features=int(total),
        kept_features=int(len(out)),
    )
    return out, meta, errors


def load_roads(
    *,
    path: Path,
    src_crs_override: str,
    dst_crs: str,
    aoi: BaseGeometry | None = None,
) -> tuple[list[RoadRecord], GeoLoadMeta, list[str]]:
    payload = read_geojson(path)
    src_crs = resolve_source_crs(payload, src_crs_override=src_crs_override)
    transformer = None if src_crs == dst_crs else _build_transformer(src_crs, dst_crs)

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

        g2 = _project_geom(g, transformer)
        if aoi is not None and not g2.intersects(aoi):
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
                line=g2,
                length_m=float(g2.length),
            )
        )

    meta = GeoLoadMeta(
        path=str(path),
        src_crs=str(src_crs),
        dst_crs=str(dst_crs),
        total_features=int(total),
        kept_features=int(len(out)),
    )
    return out, meta, errors


def load_intersection_lines(
    *,
    path: Path,
    src_crs_override: str,
    dst_crs: str,
    aoi: BaseGeometry | None = None,
) -> tuple[list[IntersectionLineRecord], GeoLoadMeta, list[str]]:
    payload = read_geojson(path)
    src_crs = resolve_source_crs(payload, src_crs_override=src_crs_override)
    transformer = None if src_crs == dst_crs else _build_transformer(src_crs, dst_crs)

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

        g2 = _project_geom(g, transformer)
        if aoi is not None and not g2.intersects(aoi):
            continue

        nodeid = _int_field(props_norm, ["nodeid", "mainid", "mainnodeid", "id"])
        if nodeid is None:
            errors.append(f"intersection_nodeid_missing:{idx}")
            continue

        out.append(IntersectionLineRecord(nodeid=int(nodeid), line=g2))

    meta = GeoLoadMeta(
        path=str(path),
        src_crs=str(src_crs),
        dst_crs=str(dst_crs),
        total_features=int(total),
        kept_features=int(len(out)),
    )
    return out, meta, errors


def load_divstrip_union(
    *,
    path: Path,
    src_crs_override: str,
    dst_crs: str,
    aoi: BaseGeometry | None = None,
) -> tuple[BaseGeometry | None, GeoLoadMeta, list[str]]:
    payload = read_geojson(path)
    src_crs = resolve_source_crs(payload, src_crs_override=src_crs_override)
    transformer = None if src_crs == dst_crs else _build_transformer(src_crs, dst_crs)

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

        g2 = _project_geom(g, transformer)
        if aoi is not None and not g2.intersects(aoi):
            continue
        geoms.append(g2)

    union = None
    if geoms:
        try:
            union = unary_union(geoms)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"divstrip_union_failed:{type(exc).__name__}")

    meta = GeoLoadMeta(
        path=str(path),
        src_crs=str(src_crs),
        dst_crs=str(dst_crs),
        total_features=int(total),
        kept_features=int(len(geoms)),
    )
    return union, meta, errors


def infer_lonlat_like_bbox(min_x: float, min_y: float, max_x: float, max_y: float) -> bool:
    vals = [min_x, min_y, max_x, max_y]
    if any((not isinstance(v, (int, float)) or not math.isfinite(float(v))) for v in vals):
        return False
    return abs(min_x) <= 180.0 and abs(max_x) <= 180.0 and abs(min_y) <= 90.0 and abs(max_y) <= 90.0


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
