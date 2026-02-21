from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Config
from .ground_ref import build_ground_grid, estimate_ground_z_for_traj
from .io import PointCloudData


@dataclass(frozen=True)
class GroundClassifyResult:
    source: str
    ground_local_idx_all: np.ndarray
    ground_xyz_all: np.ndarray
    ground_local_idx_export: np.ndarray
    ground_idx_export: np.ndarray
    ground_points_export: np.ndarray
    ground_mask_export: np.ndarray
    ground_ref_z_points: np.ndarray
    dz_points: np.ndarray
    ground_stats: dict[str, object]


def classify_ground_points(point_data: PointCloudData, cfg: Config) -> GroundClassifyResult:
    xyz = np.asarray(point_data.xyz, dtype=np.float64)
    n = int(xyz.shape[0])

    if n == 0:
        empty_i64 = np.empty((0,), dtype=np.int64)
        empty_xyz = np.empty((0, 3), dtype=np.float64)
        empty_f64 = np.full((0,), np.nan, dtype=np.float64)
        return GroundClassifyResult(
            source="empty",
            ground_local_idx_all=empty_i64,
            ground_xyz_all=empty_xyz,
            ground_local_idx_export=empty_i64,
            ground_idx_export=empty_i64,
            ground_points_export=empty_xyz,
            ground_mask_export=np.zeros((0,), dtype=bool),
            ground_ref_z_points=empty_f64,
            dz_points=empty_f64,
            ground_stats={
                "ground_source": "empty",
                "n_points_total_loaded": 0,
                "n_points_total_input": int(point_data.total_points),
                "ground_count": 0,
                "ground_ratio": 0.0,
                "export_count": 0,
                "sampled": bool(point_data.sampled),
            },
        )

    cls = point_data.classification
    use_las_cls = False
    if cls is not None:
        cls_arr = np.asarray(cls)
        if cls_arr.shape[0] == n:
            las_ground_count = int(np.count_nonzero(cls_arr == 2))
            use_las_cls = las_ground_count >= cfg.min_las_ground_points
        else:
            cls_arr = None
    else:
        cls_arr = None

    if use_las_cls and cls_arr is not None:
        source = "las_classification"
        ground_mask_all = np.asarray(cls_arr == 2, dtype=bool)
        ground_ref_z_points = np.full(n, np.nan, dtype=np.float64)
        dz_points = np.full(n, np.nan, dtype=np.float64)
        score = np.zeros(n, dtype=np.float64)
    else:
        source = "dem_band"
        grid = build_ground_grid(xyz, cfg)
        ground_ref_z_points = estimate_ground_z_for_traj(xyz, grid, cfg)
        dz_points = xyz[:, 2] - ground_ref_z_points
        valid = np.isfinite(dz_points)
        ground_mask_all = valid & (dz_points >= -cfg.below_margin_m) & (dz_points <= cfg.above_margin_m)
        score = np.abs(np.where(np.isfinite(dz_points), dz_points, np.inf))

    ground_local_idx_all = np.flatnonzero(ground_mask_all).astype(np.int64)
    ground_xyz_all = xyz[ground_local_idx_all] if ground_local_idx_all.size else np.empty((0, 3), dtype=np.float64)

    ground_local_idx_export = _select_export_indices(
        xyz=xyz,
        selected_idx=ground_local_idx_all,
        score=score,
        cfg=cfg,
    )

    ground_points_export = xyz[ground_local_idx_export] if ground_local_idx_export.size else np.empty((0, 3), dtype=np.float64)
    ground_idx_export = (
        point_data.original_indices[ground_local_idx_export]
        if ground_local_idx_export.size
        else np.empty((0,), dtype=np.int64)
    )

    ground_mask_export = np.zeros(n, dtype=bool)
    if ground_local_idx_export.size:
        ground_mask_export[ground_local_idx_export] = True

    ground_count = int(ground_local_idx_all.size)
    ground_ratio = float(ground_count / n) if n > 0 else 0.0

    finite_dz = dz_points[np.isfinite(dz_points)]
    if finite_dz.size > 0:
        dz_p50 = float(np.quantile(np.abs(finite_dz), 0.50))
        dz_p90 = float(np.quantile(np.abs(finite_dz), 0.90))
        dz_p99 = float(np.quantile(np.abs(finite_dz), 0.99))
    else:
        dz_p50 = float("nan")
        dz_p90 = float("nan")
        dz_p99 = float("nan")

    ground_stats: dict[str, object] = {
        "ground_source": source,
        "n_points_total_loaded": n,
        "n_points_total_input": int(point_data.total_points),
        "ground_count": ground_count,
        "ground_ratio": ground_ratio,
        "export_count": int(ground_local_idx_export.size),
        "dz_abs_p50": dz_p50,
        "dz_abs_p90": dz_p90,
        "dz_abs_p99": dz_p99,
        "thresholds": {
            "above_margin_m": float(cfg.above_margin_m),
            "below_margin_m": float(cfg.below_margin_m),
            "min_las_ground_points": int(cfg.min_las_ground_points),
            "max_points_per_cell_export": int(cfg.max_points_per_cell_export),
            "max_export_points": int(cfg.max_export_points),
        },
        "sampled": bool(point_data.sampled),
    }

    return GroundClassifyResult(
        source=source,
        ground_local_idx_all=ground_local_idx_all,
        ground_xyz_all=ground_xyz_all,
        ground_local_idx_export=ground_local_idx_export,
        ground_idx_export=ground_idx_export,
        ground_points_export=ground_points_export,
        ground_mask_export=ground_mask_export,
        ground_ref_z_points=ground_ref_z_points,
        dz_points=dz_points,
        ground_stats=ground_stats,
    )


def _select_export_indices(xyz: np.ndarray, selected_idx: np.ndarray, score: np.ndarray, cfg: Config) -> np.ndarray:
    if selected_idx.size == 0:
        return np.empty((0,), dtype=np.int64)

    pts = xyz[selected_idx]
    x0 = float(np.min(pts[:, 0]))
    y0 = float(np.min(pts[:, 1]))

    ix = np.floor((pts[:, 0] - x0) / cfg.grid_size_m).astype(np.int64)
    iy = np.floor((pts[:, 1] - y0) / cfg.grid_size_m).astype(np.int64)

    keep_local: list[int] = []

    cell_map: dict[tuple[int, int], list[int]] = {}
    for pos, (cx, cy) in enumerate(zip(ix, iy)):
        key = (int(cx), int(cy))
        cell_map.setdefault(key, []).append(pos)

    for key in sorted(cell_map.keys()):
        positions = cell_map[key]
        positions_sorted = sorted(
            positions,
            key=lambda p: (
                float(score[int(selected_idx[p])]),
                int(selected_idx[p]),
            ),
        )
        keep_local.extend(positions_sorted[: cfg.max_points_per_cell_export])

    if not keep_local:
        return np.empty((0,), dtype=np.int64)

    keep_positions = np.asarray(sorted(set(keep_local)), dtype=np.int64)
    out = selected_idx[keep_positions]

    out = np.asarray(sorted(out.tolist()), dtype=np.int64)
    if out.size > cfg.max_export_points:
        out = out[: cfg.max_export_points]

    return out
