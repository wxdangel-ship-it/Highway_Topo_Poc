from __future__ import annotations

import math

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
