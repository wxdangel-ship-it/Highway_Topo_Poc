from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


_RADIUS_M = 6378137.0
_MAX_WEBM_Y = 20037508.342789244
_MAX_WEBM_X = 20037508.342789244
_MAX_WGS84_LAT = 85.0511287798066


def normalize_epsg_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    m = re.search(r"(\d{4,5})", s)
    if m:
        return f"EPSG:{m.group(1)}"
    return s.upper()


def parse_geojson_crs(obj: dict[str, Any]) -> str | None:
    crs = obj.get("crs")
    if not isinstance(crs, dict):
        return None
    props = crs.get("properties")
    if not isinstance(props, dict):
        return None
    return normalize_epsg_name(props.get("name"))


def guess_crs_from_bbox(bbox: tuple[float, float, float, float] | None) -> str | None:
    if bbox is None:
        return None
    min_x, min_y, max_x, max_y = bbox
    vals = [min_x, min_y, max_x, max_y]
    if any((not isinstance(v, (int, float)) or not math.isfinite(float(v))) for v in vals):
        return None

    lonlat_like = abs(min_x) <= 180.0 and abs(max_x) <= 180.0 and abs(min_y) <= 90.0 and abs(max_y) <= 90.0
    if lonlat_like:
        return "EPSG:4326"

    max_abs = max(abs(float(v)) for v in vals)
    if 1.0e6 <= max_abs <= 2.1e7:
        return "EPSG:3857"
    return None


def wgs84_to_webmercator(x: float, y: float) -> tuple[float, float]:
    lon = float(x)
    lat = float(y)
    lat = min(_MAX_WGS84_LAT, max(-_MAX_WGS84_LAT, lat))
    lon_rad = math.radians(lon)
    lat_rad = math.radians(lat)
    out_x = _RADIUS_M * lon_rad
    out_y = _RADIUS_M * math.log(math.tan((math.pi / 4.0) + (lat_rad / 2.0)))
    out_y = min(_MAX_WEBM_Y, max(-_MAX_WEBM_Y, out_y))
    return float(out_x), float(out_y)


def webmercator_to_wgs84(x: float, y: float) -> tuple[float, float]:
    mx = min(_MAX_WEBM_X, max(-_MAX_WEBM_X, float(x)))
    my = min(_MAX_WEBM_Y, max(-_MAX_WEBM_Y, float(y)))
    lon = math.degrees(mx / _RADIUS_M)
    lat = math.degrees(2.0 * math.atan(math.exp(my / _RADIUS_M)) - (math.pi / 2.0))
    lat = min(_MAX_WGS84_LAT, max(-_MAX_WGS84_LAT, lat))
    return float(lon), float(lat)


def _transform_xy(x: float, y: float, *, src_epsg: str, dst_epsg: str) -> tuple[float, float]:
    if src_epsg == dst_epsg:
        return float(x), float(y)
    if src_epsg == "EPSG:4326" and dst_epsg == "EPSG:3857":
        return wgs84_to_webmercator(float(x), float(y))
    if src_epsg == "EPSG:3857" and dst_epsg == "EPSG:4326":
        return webmercator_to_wgs84(float(x), float(y))

    try:
        from pyproj import Transformer  # type: ignore

        tf = Transformer.from_crs(src_epsg, dst_epsg, always_xy=True)
        tx, ty = tf.transform(float(x), float(y))
        return float(tx), float(ty)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"unsupported_crs_transform:{src_epsg}->{dst_epsg}; install pyproj for this transform"
        ) from exc


def transform_coords_recursive(coords: Any, src_epsg: str, dst_epsg: str) -> Any:
    src = normalize_epsg_name(src_epsg)
    dst = normalize_epsg_name(dst_epsg)
    if src is None or dst is None:
        raise ValueError(f"invalid_crs_name: src={src_epsg}, dst={dst_epsg}")
    if src == dst:
        return coords

    if isinstance(coords, (tuple, list)):
        if len(coords) >= 2 and isinstance(coords[0], (int, float)) and isinstance(coords[1], (int, float)):
            tx, ty = _transform_xy(float(coords[0]), float(coords[1]), src_epsg=src, dst_epsg=dst)
            tail = list(coords[2:]) if len(coords) > 2 else []
            return [tx, ty, *tail]
        return [transform_coords_recursive(c, src, dst) for c in coords]
    return coords


def _iter_coord_pairs(coords: Any) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, (tuple, list)):
            if len(obj) >= 2 and isinstance(obj[0], (int, float)) and isinstance(obj[1], (int, float)):
                x = float(obj[0])
                y = float(obj[1])
                if math.isfinite(x) and math.isfinite(y):
                    out.append((x, y))
                return
            for item in obj:
                walk(item)

    walk(coords)
    return out


def compute_geojson_bbox(payload: dict[str, Any]) -> tuple[float, float, float, float] | None:
    feats = payload.get("features")
    if not isinstance(feats, list):
        return None
    xs: list[float] = []
    ys: list[float] = []
    for feat in feats:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry")
        if not isinstance(geom, dict):
            continue
        for x, y in _iter_coord_pairs(geom.get("coordinates")):
            xs.append(float(x))
            ys.append(float(y))
    if not xs:
        return None
    return (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))


def _normalize_src_hint(src_crs_hint: str | None) -> str:
    if src_crs_hint is None:
        return "auto"
    s = str(src_crs_hint).strip()
    if not s:
        return "auto"
    if s.lower() == "auto":
        return "auto"
    out = normalize_epsg_name(s)
    if out is None:
        raise ValueError(f"invalid_src_crs_hint:{src_crs_hint}")
    return out


def load_geojson_and_reproject(
    path: Path,
    src_crs_hint: str | None,
    dst_crs: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"geojson_not_found:{path}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"geojson_parse_failed:{path}:{type(exc).__name__}") from exc

    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError(f"geojson_not_feature_collection:{path}")
    if not isinstance(payload.get("features"), list):
        raise ValueError(f"geojson_features_not_list:{path}")

    dst = normalize_epsg_name(dst_crs)
    if dst is None:
        raise ValueError(f"invalid_dst_crs:{dst_crs}")

    bbox_src = compute_geojson_bbox(payload)

    explicit = _normalize_src_hint(src_crs_hint)
    src_detected = parse_geojson_crs(payload)
    guess_source = "none"

    if explicit != "auto":
        src_used = explicit
        guess_source = "cli_hint"
    else:
        if src_detected is not None:
            src_used = src_detected
            guess_source = "geojson_crs"
        else:
            guessed = guess_crs_from_bbox(bbox_src)
            if guessed is not None:
                src_used = guessed
                guess_source = "bbox_guess"
            else:
                src_used = None
                guess_source = "unknown"

    if src_used is None:
        meta = {
            "path": str(path),
            "src_crs_detected": src_detected,
            "src_crs_used": None,
            "dst_crs": dst,
            "bbox_src": bbox_src,
            "bbox_dst": None,
            "guess_source": guess_source,
        }
        raise ValueError(f"crs_unknown:{path}:{meta}")

    src_used = normalize_epsg_name(src_used)
    if src_used is None:
        raise ValueError(f"invalid_src_crs_used:{path}:{src_used}")

    feats_out: list[dict[str, Any]] = []
    for feat in payload.get("features", []):
        if not isinstance(feat, dict):
            feats_out.append(feat)
            continue
        geom = feat.get("geometry")
        if isinstance(geom, dict) and "coordinates" in geom:
            geom2 = dict(geom)
            geom2["coordinates"] = transform_coords_recursive(geom.get("coordinates"), src_used, dst)
            feat2 = dict(feat)
            feat2["geometry"] = geom2
            feats_out.append(feat2)
            continue
        feats_out.append(dict(feat))

    out = {"type": "FeatureCollection", "features": feats_out}
    out["crs"] = {"type": "name", "properties": {"name": dst}}
    bbox_dst = compute_geojson_bbox(out)
    meta = {
        "path": str(path),
        "src_crs_detected": src_detected,
        "src_crs_used": src_used,
        "dst_crs": dst,
        "bbox_src": bbox_src,
        "bbox_dst": bbox_dst,
        "guess_source": guess_source,
    }
    return out, meta


def transform_xy_arrays(x: Any, y: Any, *, src_epsg: str, dst_epsg: str) -> tuple[Any, Any]:
    src = normalize_epsg_name(src_epsg)
    dst = normalize_epsg_name(dst_epsg)
    if src is None or dst is None:
        raise ValueError(f"invalid_crs_name: src={src_epsg}, dst={dst_epsg}")
    if src == dst:
        return x, y

    if src == "EPSG:4326" and dst == "EPSG:3857":
        import numpy as np

        lon = np.asarray(x, dtype=np.float64)
        lat = np.asarray(y, dtype=np.float64)
        lat = np.clip(lat, -_MAX_WGS84_LAT, _MAX_WGS84_LAT)
        out_x = _RADIUS_M * np.deg2rad(lon)
        out_y = _RADIUS_M * np.log(np.tan((math.pi / 4.0) + (np.deg2rad(lat) / 2.0)))
        out_y = np.clip(out_y, -_MAX_WEBM_Y, _MAX_WEBM_Y)
        return out_x, out_y

    if src == "EPSG:3857" and dst == "EPSG:4326":
        import numpy as np

        mx = np.asarray(x, dtype=np.float64)
        my = np.asarray(y, dtype=np.float64)
        mx = np.clip(mx, -_MAX_WEBM_X, _MAX_WEBM_X)
        my = np.clip(my, -_MAX_WEBM_Y, _MAX_WEBM_Y)
        out_lon = np.rad2deg(mx / _RADIUS_M)
        out_lat = np.rad2deg(2.0 * np.arctan(np.exp(my / _RADIUS_M)) - (math.pi / 2.0))
        out_lat = np.clip(out_lat, -_MAX_WGS84_LAT, _MAX_WGS84_LAT)
        return out_lon, out_lat

    try:
        from pyproj import Transformer  # type: ignore

        tf = Transformer.from_crs(src, dst, always_xy=True)
        return tf.transform(x, y)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"unsupported_crs_transform:{src}->{dst}") from exc


__all__ = [
    "compute_geojson_bbox",
    "guess_crs_from_bbox",
    "load_geojson_and_reproject",
    "normalize_epsg_name",
    "parse_geojson_crs",
    "transform_coords_recursive",
    "transform_xy_arrays",
    "webmercator_to_wgs84",
    "wgs84_to_webmercator",
]
