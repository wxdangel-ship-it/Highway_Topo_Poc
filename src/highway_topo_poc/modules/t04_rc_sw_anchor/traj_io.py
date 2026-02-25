from __future__ import annotations

import glob
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .crs_norm import load_geojson_and_reproject


@dataclass(frozen=True)
class TrajLoadResult:
    points_xy: np.ndarray
    paths: list[str]
    total_points: int
    src_crs_list: list[str]
    per_file_meta: list[dict[str, Any]]


@dataclass
class TrajGridIndex:
    radius_m: float
    cell_size_m: float
    cells: dict[tuple[int, int], np.ndarray]


_TRAJ_DEFAULT_GLOB = "Traj/*/raw_dat_pose.geojson"


def discover_traj_paths(*, patch_dir: Path, traj_glob: str | None = None) -> list[Path]:
    if traj_glob and str(traj_glob).strip():
        matches = sorted(glob.glob(str(traj_glob), recursive=True))
        return [Path(p) for p in matches if Path(p).is_file()]
    return sorted([p for p in patch_dir.glob(_TRAJ_DEFAULT_GLOB) if p.is_file()])


def _iter_traj_xy(payload: dict[str, Any]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    feats = payload.get("features", [])
    if not isinstance(feats, list):
        return out

    for feat in feats:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry")
        if not isinstance(geom, dict):
            continue
        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            continue
        try:
            x = float(coords[0])
            y = float(coords[1])
        except Exception:
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        out.append((x, y))
    return out


def load_traj_points(
    *,
    paths: list[Path],
    src_crs_override: str,
    dst_crs: str,
) -> TrajLoadResult:
    arrays: list[np.ndarray] = []
    src_list: list[str] = []
    used_paths: list[str] = []
    per_file_meta: list[dict[str, Any]] = []

    for path in paths:
        payload, meta = load_geojson_and_reproject(path=path, src_crs_hint=src_crs_override, dst_crs=dst_crs)
        used_paths.append(str(path))
        src_list.append(str(meta.get("src_crs_used")))
        per_file_meta.append(meta)

        xy = _iter_traj_xy(payload)
        if not xy:
            continue

        arr = np.asarray(xy, dtype=np.float64)
        arrays.append(arr)

    if not arrays:
        out = np.zeros((0, 2), dtype=np.float64)
    else:
        out = np.concatenate(arrays, axis=0)

    return TrajLoadResult(
        points_xy=out,
        paths=used_paths,
        total_points=int(out.shape[0]),
        src_crs_list=src_list,
        per_file_meta=per_file_meta,
    )


def build_traj_grid_index(*, traj_points_xy: np.ndarray, radius_m: float) -> TrajGridIndex:
    radius = max(0.01, float(radius_m))
    cell_size = radius
    cells: dict[tuple[int, int], list[list[float]]] = {}

    if traj_points_xy.size > 0:
        for x, y in traj_points_xy:
            ix = int(math.floor(float(x) / cell_size))
            iy = int(math.floor(float(y) / cell_size))
            cells.setdefault((ix, iy), []).append([float(x), float(y)])

    dense: dict[tuple[int, int], np.ndarray] = {}
    for key, vals in cells.items():
        dense[key] = np.asarray(vals, dtype=np.float64)

    return TrajGridIndex(radius_m=radius, cell_size_m=cell_size, cells=dense)


def mark_points_near_traj(*, points_xy: np.ndarray, traj_index: TrajGridIndex) -> np.ndarray:
    if points_xy.size == 0:
        return np.zeros((0,), dtype=bool)
    if not traj_index.cells:
        return np.zeros((points_xy.shape[0],), dtype=bool)

    radius2 = float(traj_index.radius_m) * float(traj_index.radius_m)
    cell_size = float(traj_index.cell_size_m)
    out = np.zeros((points_xy.shape[0],), dtype=bool)

    for i, (x, y) in enumerate(points_xy):
        ix = int(math.floor(float(x) / cell_size))
        iy = int(math.floor(float(y) / cell_size))
        hit = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                arr = traj_index.cells.get((ix + dx, iy + dy))
                if arr is None or arr.size == 0:
                    continue
                diff_x = arr[:, 0] - float(x)
                diff_y = arr[:, 1] - float(y)
                d2 = diff_x * diff_x + diff_y * diff_y
                if np.any(d2 <= radius2):
                    hit = True
                    break
            if hit:
                break
        out[i] = hit

    return out


__all__ = [
    "TrajGridIndex",
    "TrajLoadResult",
    "build_traj_grid_index",
    "discover_traj_paths",
    "load_traj_points",
    "mark_points_near_traj",
]
