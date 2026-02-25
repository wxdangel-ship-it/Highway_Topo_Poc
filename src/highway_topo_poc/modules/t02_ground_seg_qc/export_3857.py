from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .crs_mercator import lonlat_array_to_3857, lonlat_like_bbox


def transform_xy_to_3857_if_needed(
    x: np.ndarray,
    y: np.ndarray,
    *,
    input_lonlat: bool,
) -> tuple[np.ndarray, np.ndarray]:
    x_arr = np.asarray(x, dtype=np.float64)
    y_arr = np.asarray(y, dtype=np.float64)
    if not input_lonlat:
        return x_arr, y_arr
    return lonlat_array_to_3857(x_arr, y_arr)


def transformed_xy_bounds_from_header(
    header: object,
    *,
    input_lonlat: bool,
) -> tuple[float, float, float, float]:
    mins = np.asarray(getattr(header, "mins"), dtype=np.float64)
    maxs = np.asarray(getattr(header, "maxs"), dtype=np.float64)
    min_x = float(mins[0]) if mins.size >= 1 else 0.0
    min_y = float(mins[1]) if mins.size >= 2 else 0.0
    max_x = float(maxs[0]) if maxs.size >= 1 else min_x
    max_y = float(maxs[1]) if maxs.size >= 2 else min_y

    if not input_lonlat:
        return min_x, max_x, min_y, max_y

    lon = np.asarray([min_x, min_x, max_x, max_x], dtype=np.float64)
    lat = np.asarray([min_y, max_y, min_y, max_y], dtype=np.float64)
    xx, yy = lonlat_array_to_3857(lon, lat)
    return float(np.min(xx)), float(np.max(xx)), float(np.min(yy)), float(np.max(yy))


def prepare_output_header_3857(reader_header: object, *, input_lonlat: bool):
    header = reader_header.copy()
    if input_lonlat:
        min_x, max_x, min_y, max_y = transformed_xy_bounds_from_header(header, input_lonlat=True)
        z_scale = float(header.scales[2]) if len(header.scales) >= 3 else 0.001
        z_offset = float(header.offsets[2]) if len(header.offsets) >= 3 else 0.0
        header.scales = np.array([0.001, 0.001, max(0.0001, z_scale)], dtype=np.float64)
        header.offsets = np.array([math.floor(min_x), math.floor(min_y), z_offset], dtype=np.float64)
        _ = max_x
        _ = max_y
    return header


def read_point_count(path: str | Path) -> int:
    import laspy  # type: ignore

    with laspy.open(str(path)) as reader:
        return int(reader.header.point_count)


def read_bbox(path: str | Path) -> dict[str, float]:
    import laspy  # type: ignore

    with laspy.open(str(path)) as reader:
        mins = np.asarray(reader.header.mins, dtype=np.float64)
        maxs = np.asarray(reader.header.maxs, dtype=np.float64)
    return {
        "min_x": float(mins[0]) if mins.size >= 1 else 0.0,
        "min_y": float(mins[1]) if mins.size >= 2 else 0.0,
        "max_x": float(maxs[0]) if maxs.size >= 1 else 0.0,
        "max_y": float(maxs[1]) if maxs.size >= 2 else 0.0,
    }


def verify_output_bbox_is_3857(path: str | Path) -> None:
    bbox = read_bbox(path)
    if lonlat_like_bbox(
        min_x=float(bbox["min_x"]),
        max_x=float(bbox["max_x"]),
        min_y=float(bbox["min_y"]),
        max_y=float(bbox["max_y"]),
    ):
        raise ValueError(
            f"verify_bbox_lonlat_like:{path}:{bbox['min_x']},{bbox['max_x']},{bbox['min_y']},{bbox['max_y']}"
        )
