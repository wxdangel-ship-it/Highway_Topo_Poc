from __future__ import annotations

import math

import numpy as np


def pack_cells(ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
    ix64 = np.asarray(ix, dtype=np.int64)
    iy64 = np.asarray(iy, dtype=np.int64)
    return ((ix64 & np.int64(0xFFFFFFFF)) << np.int64(32)) | (iy64 & np.int64(0xFFFFFFFF))


def pack_cell_scalar(ix: int, iy: int) -> int:
    ix_u = int(ix) & 0xFFFFFFFF
    iy_u = int(iy) & 0xFFFFFFFF
    key = (ix_u << 32) | iy_u
    if key >= (1 << 63):
        key -= (1 << 64)
    return int(key)


def unpack_cell(key: int) -> tuple[int, int]:
    hi = (int(key) >> 32) & 0xFFFFFFFF
    lo = int(key) & 0xFFFFFFFF
    if hi >= 0x80000000:
        hi -= 0x100000000
    if lo >= 0x80000000:
        lo -= 0x100000000
    return int(hi), int(lo)


def _build_radius_offsets(*, grid_m: float, radius_m: float) -> list[tuple[int, int]]:
    if radius_m <= 0:
        return [(0, 0)]
    max_k = int(math.ceil(float(radius_m) / float(grid_m)))
    out: list[tuple[int, int]] = []
    for dx in range(-max_k, max_k + 1):
        for dy in range(-max_k, max_k + 1):
            dist = math.hypot(dx * grid_m, dy * grid_m)
            if dist <= radius_m + 1e-9:
                out.append((dx, dy))
    return sorted(out)


def build_corridor_cell_ids(
    trajs_xy: list[np.ndarray],
    ref_grid_m: float,
    corridor_radius_m: float,
    *,
    x0: float = 0.0,
    y0: float = 0.0,
) -> np.ndarray:
    if ref_grid_m <= 0:
        raise ValueError("ref_grid_m must be > 0")
    if corridor_radius_m < 0:
        raise ValueError("corridor_radius_m must be >= 0")

    offsets = _build_radius_offsets(grid_m=float(ref_grid_m), radius_m=float(corridor_radius_m))
    out: set[int] = set()

    for traj in trajs_xy:
        arr = np.asarray(traj, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] < 2 or arr.shape[0] <= 0:
            continue
        x = np.asarray(arr[:, 0], dtype=np.float64)
        y = np.asarray(arr[:, 1], dtype=np.float64)
        valid = np.isfinite(x) & np.isfinite(y)
        if not np.any(valid):
            continue
        x = x[valid]
        y = y[valid]
        ix = np.floor((x - float(x0)) / float(ref_grid_m)).astype(np.int64)
        iy = np.floor((y - float(y0)) / float(ref_grid_m)).astype(np.int64)
        base = np.unique(pack_cells(ix, iy))
        for key in base.tolist():
            cx, cy = unpack_cell(int(key))
            for dx, dy in offsets:
                out.add(pack_cell_scalar(cx + int(dx), cy + int(dy)))

    if not out:
        return np.empty((0,), dtype=np.int64)
    return np.asarray(sorted(out), dtype=np.int64)
