from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

_MAX_SAFE_FLOAT_INT = 9007199254740991  # 2^53 - 1


def normalize_fields(
    props: dict[str, Any] | None,
    *,
    int64_fields: Iterable[str] = ("nodeid", "mainid", "id"),
    int32_fields: Iterable[str] = ("kind",),
) -> dict[str, Any]:
    src = dict(props or {})
    lower_to_key = {str(k).strip().lower(): k for k in src.keys()}
    out: dict[str, Any] = dict(src)

    for f in int64_fields:
        key = lower_to_key.get(str(f).lower())
        if key is None:
            continue
        val = _to_int(src.get(key))
        if val is not None:
            out[str(f)] = int(np.int64(val))

    for f in int32_fields:
        key = lower_to_key.get(str(f).lower())
        if key is None:
            continue
        val = _to_int(src.get(key))
        if val is not None:
            out[str(f)] = int(np.int32(val))

    return out


def load_divstrip_buffer(divstrip_zone_metric: BaseGeometry | None, gore_buffer_m: float) -> BaseGeometry | None:
    if divstrip_zone_metric is None or divstrip_zone_metric.is_empty:
        return None
    buf = float(max(0.0, gore_buffer_m))
    if buf <= 0.0:
        return divstrip_zone_metric
    try:
        return divstrip_zone_metric.buffer(buf)
    except Exception:
        return divstrip_zone_metric


@dataclass(frozen=True)
class PointCloudRadiusIndex:
    points_by_class: dict[int, np.ndarray]
    cell_size_m: float
    grid_by_class: dict[int, dict[tuple[int, int], np.ndarray]]


def build_pointcloud_radius_index(
    points_by_class: dict[int, np.ndarray],
    *,
    cell_size_m: float = 1.0,
) -> PointCloudRadiusIndex:
    cell = float(max(0.5, cell_size_m))
    norm_points: dict[int, np.ndarray] = {}
    norm_grid: dict[int, dict[tuple[int, int], np.ndarray]] = {}
    for cid, arr in points_by_class.items():
        pts = np.asarray(arr, dtype=np.float64)
        if pts.ndim != 2 or pts.shape[0] == 0:
            norm_points[int(cid)] = np.empty((0, 2), dtype=np.float64)
            norm_grid[int(cid)] = {}
            continue
        if pts.shape[1] >= 2:
            xy = pts[:, :2]
        else:
            norm_points[int(cid)] = np.empty((0, 2), dtype=np.float64)
            norm_grid[int(cid)] = {}
            continue
        finite = np.isfinite(xy[:, 0]) & np.isfinite(xy[:, 1])
        xy = xy[finite, :]
        norm_points[int(cid)] = xy
        grid: dict[tuple[int, int], list[int]] = {}
        for i in range(xy.shape[0]):
            key = _grid_key(float(xy[i, 0]), float(xy[i, 1]), cell)
            grid.setdefault(key, []).append(i)
        norm_grid[int(cid)] = {
            k: np.asarray(v, dtype=np.int64)
            for k, v in grid.items()
        }
    return PointCloudRadiusIndex(points_by_class=norm_points, cell_size_m=cell, grid_by_class=norm_grid)


def pointcloud_query_radius(
    radius_index: PointCloudRadiusIndex,
    class_id: int,
    center_xy: tuple[float, float],
    r_m: float,
) -> int:
    pts = radius_index.points_by_class.get(int(class_id))
    grid = radius_index.grid_by_class.get(int(class_id))
    if pts is None or grid is None or pts.size == 0:
        return 0
    return _query_grid_radius_count(
        pts_xy=pts,
        grid=grid,
        center_xy=(float(center_xy[0]), float(center_xy[1])),
        radius_m=float(max(0.0, r_m)),
        cell_size=radius_index.cell_size_m,
    )


@dataclass(frozen=True)
class TrajRadiusIndex:
    all_xy: np.ndarray
    all_grid: dict[tuple[int, int], np.ndarray]
    by_traj_xy: dict[str, np.ndarray]
    by_traj_grid: dict[str, dict[tuple[int, int], np.ndarray]]
    cell_size_m: float


def build_traj_radius_index(
    traj_xy_by_id: dict[str, np.ndarray],
    *,
    cell_size_m: float = 2.0,
) -> TrajRadiusIndex:
    cell = float(max(0.5, cell_size_m))
    by_xy: dict[str, np.ndarray] = {}
    by_grid: dict[str, dict[tuple[int, int], np.ndarray]] = {}
    all_parts: list[np.ndarray] = []
    all_grid_raw: dict[tuple[int, int], list[int]] = {}
    offset = 0
    for tid, arr in traj_xy_by_id.items():
        pts = np.asarray(arr, dtype=np.float64)
        if pts.ndim != 2 or pts.shape[0] == 0:
            by_xy[str(tid)] = np.empty((0, 2), dtype=np.float64)
            by_grid[str(tid)] = {}
            continue
        xy = pts[:, :2]
        finite = np.isfinite(xy[:, 0]) & np.isfinite(xy[:, 1])
        xy = xy[finite, :]
        by_xy[str(tid)] = xy
        raw: dict[tuple[int, int], list[int]] = {}
        for i in range(xy.shape[0]):
            key = _grid_key(float(xy[i, 0]), float(xy[i, 1]), cell)
            raw.setdefault(key, []).append(i)
            all_grid_raw.setdefault(key, []).append(offset + i)
        by_grid[str(tid)] = {
            k: np.asarray(v, dtype=np.int64)
            for k, v in raw.items()
        }
        all_parts.append(xy)
        offset += int(xy.shape[0])
    all_xy = np.vstack(all_parts) if all_parts else np.empty((0, 2), dtype=np.float64)
    all_grid = {
        k: np.asarray(v, dtype=np.int64)
        for k, v in all_grid_raw.items()
    }
    return TrajRadiusIndex(
        all_xy=all_xy,
        all_grid=all_grid,
        by_traj_xy=by_xy,
        by_traj_grid=by_grid,
        cell_size_m=cell,
    )


def traj_query_radius(
    traj_points_index: TrajRadiusIndex,
    center_xy: tuple[float, float],
    r_m: float,
    *,
    support_traj_ids: set[str] | None = None,
) -> int:
    radius = float(max(0.0, r_m))
    center = (float(center_xy[0]), float(center_xy[1]))
    if support_traj_ids:
        total = 0
        for tid in support_traj_ids:
            pts = traj_points_index.by_traj_xy.get(str(tid))
            grid = traj_points_index.by_traj_grid.get(str(tid))
            if pts is None or grid is None or pts.size == 0:
                continue
            total += _query_grid_radius_count(
                pts_xy=pts,
                grid=grid,
                center_xy=center,
                radius_m=radius,
                cell_size=traj_points_index.cell_size_m,
            )
        return int(total)
    return _query_grid_radius_count(
        pts_xy=traj_points_index.all_xy,
        grid=traj_points_index.all_grid,
        center_xy=center,
        radius_m=radius,
        cell_size=traj_points_index.cell_size_m,
    )


def geom_union_fc(path: Path | str) -> BaseGeometry | None:
    fp = Path(path)
    if not fp.is_file():
        return None
    try:
        payload = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("type") != "FeatureCollection":
        return None
    geoms: list[BaseGeometry] = []
    for feat in payload.get("features", []):
        try:
            geom = shape(feat.get("geometry"))
        except Exception:
            continue
        if geom is None or geom.is_empty:
            continue
        geoms.append(geom)
    if not geoms:
        return None
    try:
        merged = unary_union(geoms)
    except Exception:
        merged = geoms[0]
    if merged is None or merged.is_empty:
        return None
    return merged


def debug_write_fc(path: Path | str, features: list[dict[str, Any]], crs: str = "EPSG:3857") -> None:
    out = Path(path)
    payload = {
        "type": "FeatureCollection",
        "features": list(features),
        "crs": {"type": "name", "properties": {"name": str(crs)}},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def metrics_write_json(path: Path | str, payload: dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _query_grid_radius_count(
    *,
    pts_xy: np.ndarray,
    grid: dict[tuple[int, int], np.ndarray],
    center_xy: tuple[float, float],
    radius_m: float,
    cell_size: float,
) -> int:
    if pts_xy.size == 0 or radius_m <= 0.0:
        return 0
    cx = float(center_xy[0])
    cy = float(center_xy[1])
    rr = float(radius_m * radius_m)
    reach = int(math.ceil(float(radius_m) / max(1e-6, float(cell_size))))
    gx, gy = _grid_key(cx, cy, float(cell_size))
    sel: list[np.ndarray] = []
    for ix in range(gx - reach, gx + reach + 1):
        for iy in range(gy - reach, gy + reach + 1):
            idx = grid.get((ix, iy))
            if idx is None or idx.size == 0:
                continue
            sel.append(idx)
    if not sel:
        return 0
    idx_all = np.unique(np.concatenate(sel, axis=0))
    if idx_all.size == 0:
        return 0
    sub = pts_xy[idx_all, :]
    d2 = (sub[:, 0] - cx) ** 2 + (sub[:, 1] - cy) ** 2
    return int(np.count_nonzero(d2 <= rr))


def _to_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        if abs(float(v)) > float(_MAX_SAFE_FLOAT_INT):
            return None
        if not float(v).is_integer():
            return None
        return int(v)
    if isinstance(v, str):
        text = str(v).strip()
        if not text:
            return None
        if re.fullmatch(r"[+-]?\d+", text):
            try:
                return int(text)
            except Exception:
                return None
        try:
            f = float(text)
        except Exception:
            return None
        if not math.isfinite(f):
            return None
        if abs(float(f)) > float(_MAX_SAFE_FLOAT_INT):
            return None
        if not float(f).is_integer():
            return None
        return int(f)
    try:
        f = float(v)
    except Exception:
        return None
    if not math.isfinite(f):
        return None
    if abs(float(f)) > float(_MAX_SAFE_FLOAT_INT):
        return None
    if not float(f).is_integer():
        return None
    return int(f)


def _grid_key(x: float, y: float, cell_size: float) -> tuple[int, int]:
    return (int(math.floor(float(x) / float(cell_size))), int(math.floor(float(y) / float(cell_size))))
