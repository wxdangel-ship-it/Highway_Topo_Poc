from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from .config import Config


@dataclass(frozen=True)
class GroundGrid:
    x0: float
    y0: float
    cell_quantile: dict[tuple[int, int], float]
    cell_points_z: dict[tuple[int, int], np.ndarray]


def build_ground_grid(points_xyz: np.ndarray, cfg: Config) -> GroundGrid:
    if points_xyz.size == 0:
        return GroundGrid(0.0, 0.0, {}, {})

    pts = np.asarray(points_xyz, dtype=np.float64)
    finite = np.isfinite(pts).all(axis=1)
    pts = pts[finite]
    if pts.size == 0:
        return GroundGrid(0.0, 0.0, {}, {})

    x0 = float(np.min(pts[:, 0]))
    y0 = float(np.min(pts[:, 1]))

    ix = np.floor((pts[:, 0] - x0) / cfg.grid_size_m).astype(np.int64)
    iy = np.floor((pts[:, 1] - y0) / cfg.grid_size_m).astype(np.int64)

    cell_lists: dict[tuple[int, int], list[float]] = defaultdict(list)
    for cx, cy, z in zip(ix, iy, pts[:, 2]):
        cell_lists[(int(cx), int(cy))].append(float(z))

    cell_points_z: dict[tuple[int, int], np.ndarray] = {}
    cell_quantile: dict[tuple[int, int], float] = {}

    for cell, z_list in cell_lists.items():
        z = np.asarray(z_list, dtype=np.float64)
        cell_points_z[cell] = z
        if z.size >= cfg.min_points_per_cell:
            cell_quantile[cell] = float(np.quantile(z, cfg.dem_quantile_q))

    return GroundGrid(x0=x0, y0=y0, cell_quantile=cell_quantile, cell_points_z=cell_points_z)


def estimate_ground_z_for_traj(traj_xyz: np.ndarray, grid: GroundGrid, cfg: Config) -> np.ndarray:
    n = int(traj_xyz.shape[0])
    out = np.full(n, np.nan, dtype=np.float64)

    if n == 0:
        return out

    if not grid.cell_points_z:
        return out

    traj = np.asarray(traj_xyz, dtype=np.float64)
    ix = np.floor((traj[:, 0] - grid.x0) / cfg.grid_size_m).astype(np.int64)
    iy = np.floor((traj[:, 1] - grid.y0) / cfg.grid_size_m).astype(np.int64)

    fallback_cache: dict[tuple[int, int], float] = {}
    radius = int(cfg.neighbor_cell_radius)

    for idx, (cx, cy) in enumerate(zip(ix, iy)):
        key = (int(cx), int(cy))

        if key in grid.cell_quantile:
            out[idx] = grid.cell_quantile[key]
            continue

        if key in fallback_cache:
            out[idx] = fallback_cache[key]
            continue

        pooled: list[np.ndarray] = []
        total = 0

        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                nkey = (key[0] + dx, key[1] + dy)
                z = grid.cell_points_z.get(nkey)
                if z is None:
                    continue
                pooled.append(z)
                total += int(z.size)

        if total >= cfg.neighbor_min_points and pooled:
            merged = np.concatenate(pooled)
            val = float(np.quantile(merged, cfg.dem_quantile_q))
        else:
            val = float("nan")

        fallback_cache[key] = val
        out[idx] = val

    return out


def compute_ground_z(traj_xyz: np.ndarray, points_xyz: np.ndarray, cfg: Config) -> np.ndarray:
    grid = build_ground_grid(points_xyz, cfg)
    return estimate_ground_z_for_traj(traj_xyz, grid, cfg)
