from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

import numpy as np

from .crs_mercator import (
    build_xy_transform,
    is_lonlat_bbox,
    lonlat_like_bbox,
)


def _header_xy_bbox(header: object) -> tuple[float, float, float, float]:
    mins = np.asarray(getattr(header, "mins"), dtype=np.float64)
    maxs = np.asarray(getattr(header, "maxs"), dtype=np.float64)
    min_x = float(mins[0]) if mins.size >= 1 else 0.0
    min_y = float(mins[1]) if mins.size >= 2 else 0.0
    max_x = float(maxs[0]) if maxs.size >= 1 else min_x
    max_y = float(maxs[1]) if maxs.size >= 2 else min_y
    return min_x, max_x, min_y, max_y


def _header_parsed_crs(header: object):
    parse_crs = getattr(header, "parse_crs", None)
    if not callable(parse_crs):
        return None
    try:
        return parse_crs()
    except Exception:
        return None


def detect_las_input_crs(
    header: object,
    *,
    target_epsg: int = 3857,
) -> dict[str, object]:
    min_x, max_x, min_y, max_y = _header_xy_bbox(header)
    bbox_lonlat = bool(
        is_lonlat_bbox(
            min_x=float(min_x),
            max_x=float(max_x),
            min_y=float(min_y),
            max_y=float(max_y),
        )
    )
    parsed = _header_parsed_crs(header)
    declared_name: str | None = None
    declared_epsg: int | None = None
    if parsed is not None:
        to_string = getattr(parsed, "to_string", None)
        if callable(to_string):
            try:
                s = str(to_string()).strip()
                declared_name = s if s else None
            except Exception:
                declared_name = None
        to_epsg = getattr(parsed, "to_epsg", None)
        if callable(to_epsg):
            try:
                e = to_epsg()
                declared_epsg = int(e) if e is not None else None
            except Exception:
                declared_epsg = None

    source_for_transform: object | None = parsed if parsed is not None else ("EPSG:4326" if bbox_lonlat else None)
    xy_transform, plan = build_xy_transform(
        source_crs=source_for_transform,
        target_epsg=int(target_epsg),
        lonlat_hint=bool(bbox_lonlat),
    )
    return {
        "bbox_lonlat_like": bool(bbox_lonlat),
        "declared_crs_name": declared_name,
        "declared_epsg": declared_epsg,
        "transform_plan": {
            "source_crs_name": plan.source_crs_name,
            "source_epsg": plan.source_epsg,
            "target_epsg": plan.target_epsg,
            "method": plan.method,
            "transformed": plan.transformed,
            "reason": plan.reason,
        },
        "xy_transform": xy_transform,
    }


def transform_xy_to_3857_if_needed(
    x: np.ndarray,
    y: np.ndarray,
    *,
    xy_transform: Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    x_arr = np.asarray(x, dtype=np.float64)
    y_arr = np.asarray(y, dtype=np.float64)
    return xy_transform(x_arr, y_arr)


def transformed_xy_bounds_from_header(
    header: object,
    *,
    xy_transform: Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]],
) -> tuple[float, float, float, float]:
    min_x, max_x, min_y, max_y = _header_xy_bbox(header)
    xs = np.asarray([min_x, min_x, max_x, max_x], dtype=np.float64)
    ys = np.asarray([min_y, max_y, min_y, max_y], dtype=np.float64)
    xx, yy = xy_transform(xs, ys)
    return float(np.min(xx)), float(np.max(xx)), float(np.min(yy)), float(np.max(yy))


def _set_header_crs_3857(header: object) -> None:
    add_crs = getattr(header, "add_crs", None)
    if not callable(add_crs):
        return
    try:
        import pyproj  # type: ignore

        add_crs(pyproj.CRS.from_epsg(3857))
    except Exception:
        return


def _set_header_crs(header: object, *, out_epsg: int) -> None:
    add_crs = getattr(header, "add_crs", None)
    if not callable(add_crs):
        return
    try:
        import pyproj  # type: ignore

        add_crs(pyproj.CRS.from_epsg(int(out_epsg)))
    except Exception:
        return


def _guess_xy_scale_for_epsg(out_epsg: int) -> float:
    try:
        import pyproj  # type: ignore

        crs = pyproj.CRS.from_epsg(int(out_epsg))
        if getattr(crs, "is_geographic", False):
            return 1e-7
    except Exception:
        pass
    return 0.001


def prepare_output_header_3857(
    reader_header: object,
    *,
    xy_transform: Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]],
    out_epsg: int = 3857,
):
    header = reader_header.copy()
    min_x, max_x, min_y, max_y = transformed_xy_bounds_from_header(header, xy_transform=xy_transform)
    _ = max_x
    _ = max_y
    xy_scale = _guess_xy_scale_for_epsg(int(out_epsg))
    z_scale = float(header.scales[2]) if len(header.scales) >= 3 else 0.001
    z_offset = float(header.offsets[2]) if len(header.offsets) >= 3 else 0.0
    header.scales = np.array([xy_scale, xy_scale, max(0.0001, z_scale)], dtype=np.float64)
    header.offsets = np.array([math.floor(min_x), math.floor(min_y), z_offset], dtype=np.float64)
    _set_header_crs(header, out_epsg=int(out_epsg))
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


def verify_output_bbox_is_3857(path: str | Path, *, out_epsg: int = 3857) -> None:
    import laspy  # type: ignore

    bbox = read_bbox(path)
    if int(out_epsg) == 3857:
        if lonlat_like_bbox(
            min_x=float(bbox["min_x"]),
            max_x=float(bbox["max_x"]),
            min_y=float(bbox["min_y"]),
            max_y=float(bbox["max_y"]),
        ):
            raise ValueError(
                f"verify_bbox_lonlat_like:{path}:{bbox['min_x']},{bbox['max_x']},{bbox['min_y']},{bbox['max_y']}"
            )

    with laspy.open(str(path)) as reader:
        parsed = None
        try:
            parsed = reader.header.parse_crs()
        except Exception:
            parsed = None
        if parsed is None:
            raise ValueError(f"verify_crs_missing:{path}")
        epsg = None
        to_epsg = getattr(parsed, "to_epsg", None)
        if callable(to_epsg):
            try:
                epsg = to_epsg()
            except Exception:
                epsg = None
        if epsg is None:
            raise ValueError(f"verify_crs_unresolved:{path}:{parsed}")
        if int(epsg) != int(out_epsg):
            raise ValueError(f"verify_crs_not_target:{path}:epsg={int(epsg)}:target={int(out_epsg)}")
