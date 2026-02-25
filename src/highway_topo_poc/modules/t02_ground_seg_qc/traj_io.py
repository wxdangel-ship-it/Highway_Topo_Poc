from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable

import numpy as np

from .crs_mercator import is_lonlat_bbox, lonlat_array_to_3857


def _iter_geometry_coords(geom: object):
    if not isinstance(geom, dict):
        return
    gtype = str(geom.get("type", "")).lower()
    coords = geom.get("coordinates")

    if gtype == "point":
        if isinstance(coords, list):
            yield coords
        return
    if gtype in {"linestring", "multipoint"}:
        if isinstance(coords, list):
            for pt in coords:
                if isinstance(pt, list):
                    yield pt
        return
    if gtype == "multilinestring":
        if isinstance(coords, list):
            for line in coords:
                if isinstance(line, list):
                    for pt in line:
                        if isinstance(pt, list):
                            yield pt
        return
    if gtype == "geometrycollection":
        geoms = geom.get("geometries")
        if isinstance(geoms, list):
            for sub in geoms:
                yield from _iter_geometry_coords(sub)
        return


def iter_traj_points_geojson(path: str | Path, sample_max_points: int | None = None):
    p = Path(path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return

    features: list[dict[str, object]] = []
    ptype = str(payload.get("type", "")).lower()
    if ptype == "featurecollection":
        feats = payload.get("features")
        if isinstance(feats, list):
            features = [x for x in feats if isinstance(x, dict)]
    elif ptype == "feature":
        features = [payload]
    else:
        features = [{"type": "Feature", "geometry": payload, "properties": {}}]

    limit = None if sample_max_points is None else max(1, int(sample_max_points))
    emitted = 0
    for feat in features:
        geom = feat.get("geometry")
        for coord in _iter_geometry_coords(geom):
            if not isinstance(coord, list) or len(coord) < 2:
                continue
            try:
                x = float(coord[0])
                y = float(coord[1])
            except Exception:
                continue
            if not math.isfinite(x) or not math.isfinite(y):
                continue
            z_val: float | None = None
            if len(coord) >= 3:
                try:
                    z_tmp = float(coord[2])
                    if math.isfinite(z_tmp):
                        z_val = z_tmp
                except Exception:
                    z_val = None
            yield x, y, z_val
            emitted += 1
            if limit is not None and emitted >= limit:
                return


def read_geojson_crs_name(path: str | Path) -> str | None:
    p = Path(path)
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
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


def collect_traj_crs(paths: list[Path]) -> dict[str, object]:
    names: list[str] = []
    for p in sorted(paths, key=lambda x: x.as_posix()):
        n = read_geojson_crs_name(p)
        if n:
            names.append(n)
    uniq = sorted(set(names))
    return {
        "declared_count": int(len(names)),
        "declared_crs_names": uniq,
        "declared_crs": uniq[0] if len(uniq) == 1 else None,
        "crs_conflict": bool(len(uniq) > 1),
    }


def _downsample_by_distance(
    *,
    xy: np.ndarray,
    z: np.ndarray,
    step_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    if xy.shape[0] <= 2 or step_m <= 0:
        return xy, z

    keep_idx = [0]
    last = xy[0]
    step = float(step_m)

    for i in range(1, int(xy.shape[0]) - 1):
        cur = xy[i]
        dist = float(np.linalg.norm(cur - last))
        if dist >= step:
            keep_idx.append(i)
            last = cur
    keep_idx.append(int(xy.shape[0]) - 1)
    idx = np.asarray(sorted(set(keep_idx)), dtype=np.int64)
    return xy[idx], z[idx]


def collect_traj_bbox(
    paths: list[Path],
    *,
    sample_max_points: int = 2000,
) -> dict[str, float | int | bool]:
    min_x = math.inf
    min_y = math.inf
    max_x = -math.inf
    max_y = -math.inf
    n = 0
    for p in paths:
        for x, y, _ in iter_traj_points_geojson(p, sample_max_points=sample_max_points):
            min_x = min(min_x, float(x))
            min_y = min(min_y, float(y))
            max_x = max(max_x, float(x))
            max_y = max(max_y, float(y))
            n += 1

    if n <= 0:
        return {
            "point_count": 0,
            "min_x": 0.0,
            "max_x": 0.0,
            "min_y": 0.0,
            "max_y": 0.0,
            "lonlat_like": False,
        }
    return {
        "point_count": int(n),
        "min_x": float(min_x),
        "max_x": float(max_x),
        "min_y": float(min_y),
        "max_y": float(max_y),
        "lonlat_like": bool(is_lonlat_bbox(min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y)),
    }


def load_traj_xyz_3857(
    paths: list[Path],
    *,
    step_m: float = 2.0,
    assume_lonlat: bool | None = None,
    xy_transform: Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]] | None = None,
) -> list[np.ndarray]:
    out: list[np.ndarray] = []
    for p in sorted(paths, key=lambda x: x.as_posix()):
        xs: list[float] = []
        ys: list[float] = []
        zs: list[float] = []
        for x, y, z in iter_traj_points_geojson(p):
            xs.append(float(x))
            ys.append(float(y))
            zs.append(float(z) if z is not None and math.isfinite(float(z)) else np.nan)

        if len(xs) <= 0:
            continue
        x_arr = np.asarray(xs, dtype=np.float64)
        y_arr = np.asarray(ys, dtype=np.float64)
        z_arr = np.asarray(zs, dtype=np.float64)
        valid_xy = np.isfinite(x_arr) & np.isfinite(y_arr)
        if not np.any(valid_xy):
            continue
        x_arr = x_arr[valid_xy]
        y_arr = y_arr[valid_xy]
        z_arr = z_arr[valid_xy]
        if x_arr.size <= 0:
            continue

        if xy_transform is not None:
            x_arr, y_arr = xy_transform(x_arr, y_arr)
        else:
            lonlat_mode = bool(assume_lonlat)
            if assume_lonlat is None:
                lonlat_mode = bool(
                    is_lonlat_bbox(
                        min_x=float(np.min(x_arr)),
                        max_x=float(np.max(x_arr)),
                        min_y=float(np.min(y_arr)),
                        max_y=float(np.max(y_arr)),
                    )
                )
            if lonlat_mode:
                x_arr, y_arr = lonlat_array_to_3857(x_arr, y_arr)

        xy = np.column_stack([x_arr, y_arr]).astype(np.float64)
        xy, z_arr = _downsample_by_distance(xy=xy, z=z_arr, step_m=float(step_m))
        if xy.shape[0] <= 0:
            continue
        out.append(np.column_stack([xy[:, 0], xy[:, 1], z_arr]).astype(np.float64))
    return out


def load_traj_xy_3857(
    paths: list[Path],
    *,
    step_m: float = 2.0,
    sample_for_zcheck: int = 1000,
    assume_lonlat: bool | None = None,
    xy_transform: Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]] | None = None,
) -> list[np.ndarray]:
    del sample_for_zcheck  # kept for CLI/contract compatibility
    xyz_list = load_traj_xyz_3857(paths, step_m=step_m, assume_lonlat=assume_lonlat, xy_transform=xy_transform)
    out: list[np.ndarray] = []
    for xyz in xyz_list:
        if xyz.shape[0] <= 0:
            continue
        out.append(np.asarray(xyz[:, :2], dtype=np.float64))
    return out
