from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

import numpy as np

from .types import BinRecord, IntervalRecord, MetricsRecord, PatchAnalysis, PatchCandidate, TrajectoryData


_UINT32_MASK = np.int64(0xFFFFFFFF)


def _as_float(v: float | np.floating | None) -> float | None:
    if v is None:
        return None
    vv = float(v)
    if math.isnan(vv):
        return None
    return vv


def _pack_cell(cx: int, cy: int) -> int:
    return int(((np.int64(cx) & _UINT32_MASK) << np.int64(32)) | (np.int64(cy) & _UINT32_MASK))


def _pack_cells_np(cx: np.ndarray, cy: np.ndarray) -> np.ndarray:
    return ((cx.astype(np.int64) & _UINT32_MASK) << np.int64(32)) | (cy.astype(np.int64) & _UINT32_MASK)


def _ensure_knn(min_neighbors: int, knn: int) -> int:
    return max(min_neighbors, knn)


def estimate_cloud_z_from_arrays(
    traj_x: np.ndarray,
    traj_y: np.ndarray,
    cloud_x: np.ndarray,
    cloud_y: np.ndarray,
    cloud_z: np.ndarray,
    *,
    radius_m: float,
    min_neighbors: int,
    knn: int,
) -> tuple[np.ndarray, str, list[str]]:
    n_traj = int(traj_x.size)
    z_est = np.full(n_traj, np.nan, dtype=np.float64)
    warnings: list[str] = []

    if cloud_x.size == 0:
        warnings.append("empty_cloud")
        return z_est, "empty", warnings

    knn = _ensure_knn(min_neighbors=min_neighbors, knn=knn)
    traj_xy = np.column_stack((traj_x, traj_y))
    cloud_xy = np.column_stack((cloud_x, cloud_y))

    try:  # pragma: no cover - optional dependency
        from scipy.spatial import cKDTree

        tree = cKDTree(cloud_xy)
        nbr_ids = tree.query_ball_point(traj_xy, r=radius_m)

        for i, idxs in enumerate(nbr_ids):
            if len(idxs) >= min_neighbors:
                z_est[i] = float(np.median(cloud_z[np.asarray(idxs, dtype=np.int64)]))
                continue

            k = min(knn, cloud_xy.shape[0])
            _dist, idx = tree.query(traj_xy[i], k=k)
            idx = np.atleast_1d(np.asarray(idx, dtype=np.int64))
            if idx.size >= min_neighbors:
                z_est[i] = float(np.median(cloud_z[idx]))

        return z_est, "scipy.cKDTree", warnings
    except Exception:
        pass

    try:  # pragma: no cover - optional dependency
        from sklearn.neighbors import NearestNeighbors

        tree = NearestNeighbors(n_neighbors=min(knn, cloud_xy.shape[0]), algorithm="kd_tree")
        tree.fit(cloud_xy)

        radius_nbr_ids = tree.radius_neighbors(traj_xy, radius=radius_m, return_distance=False)
        for i, idxs in enumerate(radius_nbr_ids):
            idxs = np.asarray(idxs, dtype=np.int64)
            if idxs.size >= min_neighbors:
                z_est[i] = float(np.median(cloud_z[idxs]))
                continue

            dist, idx = tree.kneighbors(traj_xy[i : i + 1], n_neighbors=min(knn, cloud_xy.shape[0]), return_distance=True)
            idx = np.asarray(idx[0], dtype=np.int64)
            if idx.size >= min_neighbors:
                z_est[i] = float(np.median(cloud_z[idx]))

        return z_est, "sklearn.KDTree", warnings
    except Exception:
        pass

    warnings.append("kdtree_missing_use_bruteforce")
    r2 = float(radius_m) * float(radius_m)

    for i in range(n_traj):
        dx = cloud_x - traj_x[i]
        dy = cloud_y - traj_y[i]
        d2 = dx * dx + dy * dy

        radius_mask = d2 <= r2
        radius_idx = np.flatnonzero(radius_mask)
        if radius_idx.size >= min_neighbors:
            z_est[i] = float(np.median(cloud_z[radius_idx]))
            continue

        k = min(knn, cloud_x.size)
        if k < min_neighbors:
            continue
        idx = np.argpartition(d2, kth=k - 1)[:k]
        z_est[i] = float(np.median(cloud_z[idx]))

    return z_est, "bruteforce", warnings


def _append_with_cap(
    store: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]],
    *,
    key: int,
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    cap: int,
    rng: np.random.Generator,
) -> None:
    if x.size == 0:
        return

    cur = store.get(key)
    if cur is None:
        if x.size <= cap:
            store[key] = (x.copy(), y.copy(), z.copy())
        else:
            idx = rng.choice(x.size, size=cap, replace=False)
            store[key] = (x[idx], y[idx], z[idx])
        return

    ox, oy, oz = cur
    nx = np.concatenate((ox, x), axis=0)
    ny = np.concatenate((oy, y), axis=0)
    nz = np.concatenate((oz, z), axis=0)

    if nx.size > cap:
        idx = rng.choice(nx.size, size=cap, replace=False)
        nx = nx[idx]
        ny = ny[idx]
        nz = nz[idx]

    store[key] = (nx, ny, nz)


def _neighbor_keys(cx: int, cy: int, expand: int) -> list[int]:
    out: list[int] = []
    for dx in range(-expand, expand + 1):
        for dy in range(-expand, expand + 1):
            out.append(_pack_cell(cx + dx, cy + dy))
    return out


def _gather_points(
    cell_points: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]],
    keys: list[int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    zs: list[np.ndarray] = []

    for key in keys:
        arr = cell_points.get(key)
        if arr is None:
            continue
        xs.append(arr[0])
        ys.append(arr[1])
        zs.append(arr[2])

    if not xs:
        empty = np.asarray([], dtype=np.float64)
        return empty, empty, empty

    return (
        np.concatenate(xs, axis=0),
        np.concatenate(ys, axis=0),
        np.concatenate(zs, axis=0),
    )


def estimate_cloud_z_streaming(
    traj_x: np.ndarray,
    traj_y: np.ndarray,
    cloud_chunks: Iterable[tuple[np.ndarray, np.ndarray, np.ndarray]],
    *,
    radius_m: float,
    min_neighbors: int,
    knn: int,
    knn_search_radius_m: float,
    max_points_per_cell: int,
    seed: int,
) -> tuple[np.ndarray, str, list[str]]:
    n_traj = int(traj_x.size)
    z_est = np.full(n_traj, np.nan, dtype=np.float64)

    if n_traj == 0:
        return z_est, "streaming.grid", ["empty_traj"]

    knn = _ensure_knn(min_neighbors=min_neighbors, knn=knn)
    cell_size = max(float(radius_m), 1.0)
    r_expand = max(1, int(math.ceil(float(radius_m) / cell_size)))
    k_expand = max(r_expand, int(math.ceil(float(knn_search_radius_m) / cell_size)))

    traj_cx = np.floor(traj_x / cell_size).astype(np.int64)
    traj_cy = np.floor(traj_y / cell_size).astype(np.int64)
    unique_centers = {(int(cx), int(cy)) for cx, cy in zip(traj_cx.tolist(), traj_cy.tolist())}

    active_keys_set: set[int] = set()
    min_cx = 10**18
    min_cy = 10**18
    max_cx = -(10**18)
    max_cy = -(10**18)
    for cx, cy in unique_centers:
        min_cx = min(min_cx, cx - k_expand)
        min_cy = min(min_cy, cy - k_expand)
        max_cx = max(max_cx, cx + k_expand)
        max_cy = max(max_cy, cy + k_expand)
        for dx in range(-k_expand, k_expand + 1):
            for dy in range(-k_expand, k_expand + 1):
                active_keys_set.add(_pack_cell(cx + dx, cy + dy))

    if not active_keys_set:
        return z_est, "streaming.grid", ["no_active_cells"]

    active_keys = np.fromiter(active_keys_set, dtype=np.int64)
    cell_points: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    rng = np.random.default_rng(seed)

    for x, y, z in cloud_chunks:
        if x.size == 0:
            continue

        cx = np.floor(x / cell_size).astype(np.int64)
        cy = np.floor(y / cell_size).astype(np.int64)

        in_bbox = (cx >= min_cx) & (cx <= max_cx) & (cy >= min_cy) & (cy <= max_cy)
        if not np.any(in_bbox):
            continue

        x2 = x[in_bbox]
        y2 = y[in_bbox]
        z2 = z[in_bbox]
        cx2 = cx[in_bbox]
        cy2 = cy[in_bbox]

        keys = _pack_cells_np(cx2, cy2)
        in_active = np.isin(keys, active_keys)
        if not np.any(in_active):
            continue

        keys = keys[in_active]
        x_keep = x2[in_active]
        y_keep = y2[in_active]
        z_keep = z2[in_active]

        uniq, inv = np.unique(keys, return_inverse=True)
        for i, key in enumerate(uniq.tolist()):
            mask = inv == i
            _append_with_cap(
                cell_points,
                key=int(key),
                x=x_keep[mask],
                y=y_keep[mask],
                z=z_keep[mask],
                cap=max_points_per_cell,
                rng=rng,
            )

    warnings = [
        "kdtree_missing_use_streaming_grid",
        f"max_points_per_cell={max_points_per_cell}",
    ]

    r2 = float(radius_m) * float(radius_m)
    for i in range(n_traj):
        center = (int(traj_cx[i]), int(traj_cy[i]))
        radius_keys = _neighbor_keys(center[0], center[1], r_expand)
        knn_keys = _neighbor_keys(center[0], center[1], k_expand)

        rx, ry, rz = _gather_points(cell_points, radius_keys)
        if rz.size >= min_neighbors:
            d2 = (rx - traj_x[i]) ** 2 + (ry - traj_y[i]) ** 2
            rad_idx = np.flatnonzero(d2 <= r2)
            if rad_idx.size >= min_neighbors:
                z_est[i] = float(np.median(rz[rad_idx]))
                continue

        kx, ky, kz = _gather_points(cell_points, knn_keys)
        if kz.size < min_neighbors:
            continue

        d2 = (kx - traj_x[i]) ** 2 + (ky - traj_y[i]) ** 2
        k = min(knn, kz.size)
        if k < min_neighbors:
            continue
        idx = np.argpartition(d2, kth=k - 1)[:k]
        z_est[i] = float(np.median(kz[idx]))

    return z_est, "streaming.grid", warnings


def compute_metrics_and_intervals(
    traj_z: np.ndarray,
    z_cloud_est: np.ndarray,
    *,
    th_abs_min: float,
    th_quantile: float,
    binN: int,
    stride: int,
    coverage_gate: float,
    status_coverage_gate: float,
    min_interval_len: int,
    top_k: int,
    backend: str,
    warnings: list[str],
) -> tuple[MetricsRecord, list[BinRecord], list[IntervalRecord]]:
    if traj_z.shape != z_cloud_est.shape:
        raise ValueError("traj_z_and_z_cloud_est_shape_mismatch")

    n_traj = int(traj_z.size)
    if n_traj == 0:
        metrics = MetricsRecord(
            n_traj=0,
            n_valid=0,
            coverage=0.0,
            p50=None,
            p90=None,
            p99=None,
            threshold_A=_as_float(th_abs_min),
            status="NO_VALID",
            backend=backend,
            warnings=warnings,
        )
        return metrics, [], []

    residual = traj_z - z_cloud_est
    valid_mask = np.isfinite(traj_z) & np.isfinite(z_cloud_est)
    abs_all = np.abs(residual)
    abs_valid = abs_all[valid_mask]

    n_valid = int(abs_valid.size)
    coverage = float(n_valid / n_traj)

    p50 = _as_float(np.quantile(abs_valid, 0.50)) if n_valid else None
    p90 = _as_float(np.quantile(abs_valid, 0.90)) if n_valid else None
    p99 = _as_float(np.quantile(abs_valid, 0.99)) if n_valid else None

    if n_valid > 0:
        qv = float(np.quantile(abs_valid, float(th_quantile)))
        threshold_A = float(max(float(th_abs_min), qv))
    else:
        threshold_A = float(th_abs_min)

    if n_valid == 0:
        status = "NO_VALID"
    elif coverage < float(status_coverage_gate):
        status = "LOW_COVERAGE"
    else:
        status = "OK"

    bins: list[BinRecord] = []
    for j, start_idx in enumerate(range(0, n_traj, stride)):
        end_idx = min(start_idx + binN, n_traj)
        span = end_idx - start_idx

        local = abs_all[start_idx:end_idx]
        local_valid = np.isfinite(local)
        local_vals = local[local_valid]

        valid_count = int(local_vals.size)
        valid_fraction = float(valid_count / span) if span > 0 else 0.0

        score = float(np.median(local_vals)) if valid_count > 0 else None
        insufficient = valid_fraction < float(coverage_gate)
        abnormal = (not insufficient) and (score is not None) and (score > threshold_A)

        bins.append(
            BinRecord(
                bin_index=j,
                start_idx=start_idx,
                end_idx=end_idx,
                valid_fraction=valid_fraction,
                valid_count=valid_count,
                bin_score=score,
                insufficient_coverage=insufficient,
                abnormal=abnormal,
            )
        )

    merged: list[IntervalRecord] = []
    run_start: int | None = None
    run_scores: list[float] = []

    def _flush(run_end_exclusive: int) -> None:
        nonlocal run_start, run_scores
        if run_start is None:
            return

        len_bins = run_end_exclusive - run_start
        if len_bins >= min_interval_len:
            interval_score = float(max(run_scores))
            merged.append(
                IntervalRecord(
                    start_bin=run_start,
                    end_bin=run_end_exclusive,
                    len_bins=len_bins,
                    interval_score=interval_score,
                    start_idx=run_start * stride,
                    end_idx=(run_end_exclusive - 1) * stride + binN,
                )
            )

        run_start = None
        run_scores = []

    for b in bins:
        if b.abnormal:
            if run_start is None:
                run_start = b.bin_index
                run_scores = [float(b.bin_score or 0.0)]
            else:
                run_scores.append(float(b.bin_score or 0.0))
        elif run_start is not None:
            _flush(b.bin_index)

    if run_start is not None:
        _flush(len(bins))

    merged = sorted(merged, key=lambda x: (-x.interval_score, x.start_bin, x.end_bin))
    intervals = merged[: max(0, int(top_k))]

    metrics = MetricsRecord(
        n_traj=n_traj,
        n_valid=n_valid,
        coverage=coverage,
        p50=p50,
        p90=p90,
        p99=p99,
        threshold_A=threshold_A,
        status=status,
        backend=backend,
        warnings=warnings,
    )

    return metrics, bins, intervals


def analyze_patch_candidate(
    candidate: PatchCandidate,
    traj: TrajectoryData,
    z_cloud_est: np.ndarray,
    *,
    th_abs_min: float,
    th_quantile: float,
    binN: int,
    stride: int,
    coverage_gate: float,
    status_coverage_gate: float,
    min_interval_len: int,
    top_k: int,
    backend: str,
    warnings: list[str],
    repo_root: Path,
) -> PatchAnalysis:
    metrics, bins, intervals = compute_metrics_and_intervals(
        traj.z,
        z_cloud_est,
        th_abs_min=th_abs_min,
        th_quantile=th_quantile,
        binN=binN,
        stride=stride,
        coverage_gate=coverage_gate,
        status_coverage_gate=status_coverage_gate,
        min_interval_len=min_interval_len,
        top_k=top_k,
        backend=backend,
        warnings=warnings,
    )

    def _display_path(p: Path) -> str:
        try:
            return p.relative_to(repo_root).as_posix()
        except ValueError:
            return p.as_posix()

    return PatchAnalysis(
        patch_key=candidate.patch_key,
        cloud_path=_display_path(candidate.cloud_path),
        traj_path=_display_path(candidate.traj_path),
        metrics=metrics,
        bins=bins,
        intervals=intervals,
    )
