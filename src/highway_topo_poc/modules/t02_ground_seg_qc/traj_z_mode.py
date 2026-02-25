from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .traj_io import iter_traj_points_geojson


def check_traj_z(
    paths: list[Path],
    *,
    nonzero_ratio_gate: float = 0.01,
    z_std_gate: float = 0.05,
    sample_max_points_per_file: int = 1000,
) -> dict[str, object]:
    if nonzero_ratio_gate < 0 or nonzero_ratio_gate > 1:
        raise ValueError("nonzero_ratio_gate must be in [0,1]")
    if z_std_gate < 0:
        raise ValueError("z_std_gate must be >= 0")

    z_vals: list[float] = []
    sampled_points = 0
    for p in sorted(paths, key=lambda x: x.as_posix()):
        for _, _, z in iter_traj_points_geojson(p, sample_max_points=sample_max_points_per_file):
            sampled_points += 1
            zv = float(z) if z is not None else 0.0
            if not math.isfinite(zv):
                zv = 0.0
            z_vals.append(zv)

    if len(z_vals) <= 0:
        return {
            "traj_file_count": int(len(paths)),
            "sampled_points": 0,
            "nonzero_ratio": 0.0,
            "z_std": 0.0,
            "is_degraded": True,
            "nonzero_ratio_gate": float(nonzero_ratio_gate),
            "z_std_gate": float(z_std_gate),
        }

    z_arr = np.asarray(z_vals, dtype=np.float64)
    nonzero_ratio = float(np.count_nonzero(np.abs(z_arr) > 1e-9) / z_arr.size)
    z_std = float(np.std(z_arr)) if z_arr.size > 1 else 0.0
    is_degraded = bool(nonzero_ratio < float(nonzero_ratio_gate) and z_std < float(z_std_gate))

    return {
        "traj_file_count": int(len(paths)),
        "sampled_points": int(sampled_points),
        "nonzero_ratio": float(nonzero_ratio),
        "z_std": float(z_std),
        "is_degraded": bool(is_degraded),
        "nonzero_ratio_gate": float(nonzero_ratio_gate),
        "z_std_gate": float(z_std_gate),
    }
