from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable

import numpy as np

WEB_MERCATOR_R = 6378137.0
WEB_MERCATOR_MAX_LAT = 85.05112878


def is_lonlat_xy(x: float, y: float) -> bool:
    if not math.isfinite(x) or not math.isfinite(y):
        return False
    return abs(float(x)) <= 180.0 and abs(float(y)) <= 90.0


def is_lonlat_bbox(*, min_x: float, max_x: float, min_y: float, max_y: float) -> bool:
    vals = [min_x, max_x, min_y, max_y]
    if not all(math.isfinite(v) for v in vals):
        return False
    return (
        min_x >= -180.0
        and max_x <= 180.0
        and min_y >= -90.0
        and max_y <= 90.0
    )


def lonlat_to_3857(lon: float, lat: float) -> tuple[float, float]:
    lon_rad = math.radians(float(lon))
    lat_clamped = max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, float(lat)))
    lat_rad = math.radians(lat_clamped)
    x = WEB_MERCATOR_R * lon_rad
    y = WEB_MERCATOR_R * math.log(math.tan((math.pi / 4.0) + (lat_rad / 2.0)))
    return float(x), float(y)


def lonlat_array_to_3857(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lon_arr = np.asarray(lon, dtype=np.float64)
    lat_arr = np.asarray(lat, dtype=np.float64)
    lat_clamped = np.clip(lat_arr, -WEB_MERCATOR_MAX_LAT, WEB_MERCATOR_MAX_LAT)
    x = WEB_MERCATOR_R * np.deg2rad(lon_arr)
    y = WEB_MERCATOR_R * np.log(np.tan((np.pi / 4.0) + (np.deg2rad(lat_clamped) / 2.0)))
    return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)


def lonlat_like_bbox(
    *,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
) -> bool:
    return is_lonlat_bbox(min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y)


@dataclass(frozen=True)
class TransformPlan:
    source_crs_name: str | None
    source_epsg: int | None
    target_epsg: int
    method: str
    transformed: bool
    reason: str


def _identity_xy(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)


def _parse_epsg_text(name: str | None) -> int | None:
    if not isinstance(name, str):
        return None
    m = re.search(r"epsg[:\s/]*([0-9]{3,7})", name, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _safe_to_epsg(crs_obj: object | None) -> int | None:
    if crs_obj is None:
        return None
    to_epsg = getattr(crs_obj, "to_epsg", None)
    if callable(to_epsg):
        try:
            v = to_epsg()
            if v is not None:
                return int(v)
        except Exception:
            pass
    to_string = getattr(crs_obj, "to_string", None)
    if callable(to_string):
        try:
            return _parse_epsg_text(str(to_string()))
        except Exception:
            return None
    return _parse_epsg_text(str(crs_obj))


def _safe_crs_name(crs_obj: object | None) -> str | None:
    if crs_obj is None:
        return None
    to_string = getattr(crs_obj, "to_string", None)
    if callable(to_string):
        try:
            s = str(to_string()).strip()
            if s:
                return s
        except Exception:
            pass
    s = str(crs_obj).strip()
    return s if s else None


def _load_pyproj():
    try:
        import pyproj  # type: ignore
    except Exception:
        return None
    return pyproj


def _to_pyproj_crs(crs_like: object | None):
    if crs_like is None:
        return None
    pyproj = _load_pyproj()
    if pyproj is None:
        return None
    try:
        return pyproj.CRS.from_user_input(crs_like)
    except Exception:
        return None


def build_xy_transform(
    *,
    source_crs: object | None,
    target_epsg: int,
    lonlat_hint: bool = False,
) -> tuple[Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]], TransformPlan]:
    if int(target_epsg) <= 0:
        raise ValueError(f"invalid_target_epsg:{target_epsg}")
    pyproj_crs = _to_pyproj_crs(source_crs)
    source_name = _safe_crs_name(pyproj_crs if pyproj_crs is not None else source_crs)
    source_epsg = _safe_to_epsg(pyproj_crs if pyproj_crs is not None else source_crs)

    if source_epsg == int(target_epsg):
        return _identity_xy, TransformPlan(
            source_crs_name=source_name or f"EPSG:{int(target_epsg)}",
            source_epsg=int(target_epsg),
            target_epsg=int(target_epsg),
            method="identity",
            transformed=False,
            reason="already_target_epsg",
        )

    if source_epsg == 4326 and int(target_epsg) == 3857:
        return (
            lambda x, y: lonlat_array_to_3857(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)),
            TransformPlan(
                source_crs_name=source_name or "EPSG:4326",
                source_epsg=4326,
                target_epsg=int(target_epsg),
                method="webmercator_formula",
                transformed=True,
                reason="source_epsg_4326_to_3857",
            ),
        )

    if pyproj_crs is not None:
        pyproj = _load_pyproj()
        assert pyproj is not None  # for typing
        target = pyproj.CRS.from_epsg(int(target_epsg))
        if pyproj_crs == target:
            return _identity_xy, TransformPlan(
                source_crs_name=source_name or f"EPSG:{int(target_epsg)}",
                source_epsg=int(target_epsg),
                target_epsg=int(target_epsg),
                method="identity",
                transformed=False,
                reason="already_target_epsg",
            )
        transformer = pyproj.Transformer.from_crs(pyproj_crs, target, always_xy=True)

        def _transform(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            xx, yy = transformer.transform(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))
            return np.asarray(xx, dtype=np.float64), np.asarray(yy, dtype=np.float64)

        return _transform, TransformPlan(
            source_crs_name=source_name,
            source_epsg=source_epsg,
            target_epsg=int(target_epsg),
            method="pyproj",
            transformed=True,
            reason="source_crs_declared",
        )

    if bool(lonlat_hint):
        if int(target_epsg) == 3857:
            return (
                lambda x, y: lonlat_array_to_3857(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)),
                TransformPlan(
                    source_crs_name=source_name,
                    source_epsg=source_epsg,
                    target_epsg=int(target_epsg),
                    method="webmercator_formula",
                    transformed=True,
                    reason="lonlat_hint_to_3857",
                ),
            )
        pyproj = _load_pyproj()
        if pyproj is not None:
            transformer = pyproj.Transformer.from_crs(pyproj.CRS.from_epsg(4326), pyproj.CRS.from_epsg(int(target_epsg)), always_xy=True)

            def _transform_from_4326(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
                xx, yy = transformer.transform(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))
                return np.asarray(xx, dtype=np.float64), np.asarray(yy, dtype=np.float64)

            return _transform_from_4326, TransformPlan(
                source_crs_name=source_name or "EPSG:4326",
                source_epsg=4326,
                target_epsg=int(target_epsg),
                method="pyproj",
                transformed=True,
                reason="lonlat_hint_assume_4326",
            )

    return _identity_xy, TransformPlan(
        source_crs_name=source_name,
        source_epsg=source_epsg,
        target_epsg=int(target_epsg),
        method="identity",
        transformed=False,
        reason="unknown_metric_assumed_target_epsg",
    )


def build_xy_transform_to_3857(
    *,
    source_crs: object | None,
    lonlat_hint: bool = False,
) -> tuple[Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]], TransformPlan]:
    return build_xy_transform(source_crs=source_crs, target_epsg=3857, lonlat_hint=lonlat_hint)
