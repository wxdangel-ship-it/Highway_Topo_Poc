from __future__ import annotations

import math

import numpy as np

from .corridor import pack_cells


def _append_with_cap(bucket: list[float], vals: np.ndarray, max_samples: int) -> None:
    if vals.size <= 0:
        return
    bucket.extend(np.asarray(vals, dtype=np.float64).tolist())
    if len(bucket) > max_samples:
        stride = int(math.ceil(len(bucket) / max_samples))
        bucket[:] = bucket[:: max(1, stride)][:max_samples]


def _robust_spread(zvals: np.ndarray) -> float:
    z = np.asarray(zvals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if z.size <= 1:
        return 0.0
    med = float(np.median(z))
    mad = float(np.median(np.abs(z - med)))
    sig = 1.4826 * mad
    if math.isfinite(sig) and sig > 0:
        return float(sig)
    q10 = float(np.quantile(z, 0.10))
    q90 = float(np.quantile(z, 0.90))
    sig = 0.5 * (q90 - q10)
    if math.isfinite(sig) and sig > 0:
        return float(sig)
    sig = float(np.std(z))
    if math.isfinite(sig) and sig > 0:
        return float(sig)
    return 0.0


def build_road_z_from_trajz(
    trajs_xyz: list[np.ndarray],
    ref_grid_m: float,
    *,
    x0: float = 0.0,
    y0: float = 0.0,
    max_samples_per_cell: int = 2048,
) -> tuple[dict[int, float], dict[int, float]]:
    if ref_grid_m <= 0:
        raise ValueError("ref_grid_m must be > 0")
    if max_samples_per_cell < 1:
        raise ValueError("max_samples_per_cell must be >= 1")

    cell_z: dict[int, list[float]] = {}
    for traj in trajs_xyz:
        arr = np.asarray(traj, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] < 3 or arr.shape[0] <= 0:
            continue
        x = np.asarray(arr[:, 0], dtype=np.float64)
        y = np.asarray(arr[:, 1], dtype=np.float64)
        z = np.asarray(arr[:, 2], dtype=np.float64)
        valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
        if not np.any(valid):
            continue
        x = x[valid]
        y = y[valid]
        z = z[valid]
        ix = np.floor((x - float(x0)) / float(ref_grid_m)).astype(np.int64)
        iy = np.floor((y - float(y0)) / float(ref_grid_m)).astype(np.int64)
        keys = pack_cells(ix, iy)
        order = np.argsort(keys, kind="mergesort")
        keys_s = keys[order]
        z_s = z[order]
        if keys_s.size <= 0:
            continue
        change = np.empty(keys_s.size, dtype=bool)
        change[0] = True
        change[1:] = keys_s[1:] != keys_s[:-1]
        starts = np.flatnonzero(change)
        ends = np.concatenate([starts[1:], np.array([keys_s.size], dtype=np.int64)])
        for s, e in zip(starts.tolist(), ends.tolist()):
            key = int(keys_s[s])
            bucket = cell_z.get(key)
            if bucket is None:
                bucket = []
                cell_z[key] = bucket
            _append_with_cap(bucket, np.asarray(z_s[s:e], dtype=np.float64), int(max_samples_per_cell))

    road_z: dict[int, float] = {}
    spread: dict[int, float] = {}
    for key, values in cell_z.items():
        zvals = np.asarray(values, dtype=np.float64)
        zvals = zvals[np.isfinite(zvals)]
        if zvals.size <= 0:
            continue
        road_z[int(key)] = float(np.median(zvals))
        spread[int(key)] = float(_robust_spread(zvals))

    return road_z, spread
