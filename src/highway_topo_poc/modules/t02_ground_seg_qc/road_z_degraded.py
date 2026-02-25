from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .corridor import pack_cells
from .crs_mercator import lonlat_array_to_3857


def _lookup_match_positions(query_keys: np.ndarray, sorted_keys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n_table = int(sorted_keys.size)
    n_query = int(query_keys.size)
    if n_table <= 0 or n_query <= 0:
        return np.zeros((n_query,), dtype=bool), np.zeros((n_query,), dtype=np.int64)
    pos = np.searchsorted(sorted_keys, query_keys)
    matched = pos < n_table
    if np.any(matched):
        idx = np.flatnonzero(matched)
        ok = sorted_keys[pos[idx]] == query_keys[idx]
        matched[idx] = ok
    return matched, pos.astype(np.int64)


def _append_with_cap(bucket: list[float], vals: np.ndarray, max_samples: int) -> None:
    if vals.size <= 0:
        return
    bucket.extend(np.asarray(vals, dtype=np.float64).tolist())
    if len(bucket) > max_samples:
        stride = int(math.ceil(len(bucket) / max_samples))
        bucket[:] = bucket[:: max(1, stride)][:max_samples]


def build_cell_z_peaks_from_pointcloud(
    points_path: str | Path,
    corridor_ids: np.ndarray,
    ref_grid_m: float,
    *,
    z_bin_m: float = 0.2,
    max_samples_per_cell: int = 512,
    chunk_points: int = 2_000_000,
    x0: float = 0.0,
    y0: float = 0.0,
    input_lonlat: bool = False,
) -> dict[int, dict[str, float | int]]:
    if ref_grid_m <= 0:
        raise ValueError("ref_grid_m must be > 0")
    if z_bin_m <= 0:
        raise ValueError("z_bin_m must be > 0")
    if max_samples_per_cell < 1:
        raise ValueError("max_samples_per_cell must be >= 1")

    corridor_sorted = np.asarray(np.unique(np.asarray(corridor_ids, dtype=np.int64)), dtype=np.int64)
    if corridor_sorted.size <= 0:
        return {}

    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - env-dependent
        raise ValueError(f"laspy_required:{type(exc).__name__}:{exc}") from exc

    cell_samples: dict[int, list[float]] = {}
    cell_total: dict[int, int] = {}

    with laspy.open(str(points_path)) as reader:
        for chunk in reader.chunk_iterator(int(chunk_points)):
            x = np.asarray(chunk.x, dtype=np.float64)
            y = np.asarray(chunk.y, dtype=np.float64)
            z = np.asarray(chunk.z, dtype=np.float64)
            valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
            if not np.any(valid):
                continue
            x = x[valid]
            y = y[valid]
            z = z[valid]
            if input_lonlat:
                x, y = lonlat_array_to_3857(x, y)

            ix = np.floor((x - float(x0)) / float(ref_grid_m)).astype(np.int64)
            iy = np.floor((y - float(y0)) / float(ref_grid_m)).astype(np.int64)
            keys = pack_cells(ix, iy)
            matched, _ = _lookup_match_positions(keys, corridor_sorted)
            if not np.any(matched):
                continue
            keys_hit = keys[matched]
            z_hit = z[matched]

            uniq, cnt = np.unique(keys_hit, return_counts=True)
            for k, c in zip(uniq.tolist(), cnt.tolist()):
                key = int(k)
                cell_total[key] = int(cell_total.get(key, 0) + int(c))

            order = np.argsort(keys_hit, kind="mergesort")
            k_sorted = keys_hit[order]
            z_sorted = z_hit[order]
            change = np.empty(k_sorted.size, dtype=bool)
            change[0] = True
            change[1:] = k_sorted[1:] != k_sorted[:-1]
            starts = np.flatnonzero(change)
            ends = np.concatenate([starts[1:], np.array([k_sorted.size], dtype=np.int64)])
            for s, e in zip(starts.tolist(), ends.tolist()):
                key = int(k_sorted[s])
                bucket = cell_samples.get(key)
                if bucket is None:
                    bucket = []
                    cell_samples[key] = bucket
                _append_with_cap(bucket, np.asarray(z_sorted[s:e], dtype=np.float64), int(max_samples_per_cell))

    out: dict[int, dict[str, float | int]] = {}
    for key, vals in cell_samples.items():
        zvals = np.asarray(vals, dtype=np.float64)
        zvals = zvals[np.isfinite(zvals)]
        if zvals.size <= 0:
            continue
        zmin = float(np.min(zvals))
        bins = np.floor((zvals - zmin) / float(z_bin_m)).astype(np.int64)
        if bins.size <= 0:
            continue
        counts = np.bincount(bins)
        if counts.size <= 0:
            continue

        top = np.argsort(counts)[::-1]
        top = [int(i) for i in top.tolist() if int(counts[int(i)]) > 0]
        if not top:
            continue
        i0 = int(top[0])
        i1 = int(top[1]) if len(top) > 1 else -1

        peak0 = float(zmin + (i0 + 0.5) * float(z_bin_m))
        support0 = int(counts[i0])
        peak1 = float(zmin + (i1 + 0.5) * float(z_bin_m)) if i1 >= 0 else math.nan
        support1 = int(counts[i1]) if i1 >= 0 else 0
        peak_sep = float(abs(peak1 - peak0)) if support1 > 0 and math.isfinite(peak1) else 0.0
        out[int(key)] = {
            "peak0": float(peak0),
            "peak1": float(peak1) if support1 > 0 else math.nan,
            "support0": int(support0),
            "support1": int(support1),
            "peak_sep": float(peak_sep),
            "total_points": int(cell_total.get(int(key), int(support0 + support1))),
            "sample_points": int(zvals.size),
        }
    return out


def choose_road_z_by_traj_direction(
    trajs_xy: list[np.ndarray],
    cell_peaks: dict[int, dict[str, float | int]],
    *,
    ref_grid_m: float,
    x0: float = 0.0,
    y0: float = 0.0,
    smooth_lambda: float = 0.5,
) -> tuple[dict[int, float], dict[str, object]]:
    if ref_grid_m <= 0:
        raise ValueError("ref_grid_m must be > 0")
    if smooth_lambda < 0:
        raise ValueError("smooth_lambda must be >= 0")

    votes: dict[int, list[float]] = {}
    per_traj: list[dict[str, object]] = []
    all_dz: list[float] = []

    peak_keys = set(int(k) for k in cell_peaks.keys())
    for ti, traj in enumerate(trajs_xy):
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
        keys = pack_cells(ix, iy)
        if keys.size <= 0:
            continue
        seq: list[int] = []
        last = None
        for k in keys.tolist():
            key = int(k)
            if last is None or key != last:
                last = key
                if key in peak_keys:
                    seq.append(key)
        if len(seq) <= 0:
            continue

        candidates: list[list[float]] = []
        for key in seq:
            info = cell_peaks.get(int(key), {})
            cands = [float(info.get("peak0", math.nan))]
            peak1 = float(info.get("peak1", math.nan))
            support1 = int(info.get("support1", 0))
            if support1 > 0 and math.isfinite(peak1) and abs(peak1 - cands[0]) > 1e-6:
                cands.append(peak1)
            candidates.append(cands)

        if len(candidates) <= 0:
            continue

        costs: list[list[float]] = [[0.0 for _ in candidates[0]]]
        backs: list[list[int]] = [[-1 for _ in candidates[0]]]
        for i in range(1, len(candidates)):
            prev = costs[i - 1]
            cur_cands = candidates[i]
            prev_cands = candidates[i - 1]
            cur_cost = [math.inf for _ in cur_cands]
            cur_back = [-1 for _ in cur_cands]
            for j, zj in enumerate(cur_cands):
                best_cost = math.inf
                best_k = -1
                for k, zk in enumerate(prev_cands):
                    c = float(prev[k]) + abs(float(zj) - float(zk)) + float(smooth_lambda) * (1.0 if j != k else 0.0)
                    if c < best_cost:
                        best_cost = c
                        best_k = k
                cur_cost[j] = float(best_cost)
                cur_back[j] = int(best_k)
            costs.append(cur_cost)
            backs.append(cur_back)

        last_cost = costs[-1]
        state = int(np.argmin(np.asarray(last_cost, dtype=np.float64))) if len(last_cost) > 0 else 0
        chosen_states = [state]
        for i in range(len(candidates) - 1, 0, -1):
            state = int(backs[i][state])
            state = max(0, state)
            chosen_states.append(state)
        chosen_states.reverse()

        chosen_z: list[float] = []
        peak1_choose = 0
        for i, key in enumerate(seq):
            st = int(chosen_states[i]) if i < len(chosen_states) else 0
            z_sel = float(candidates[i][st])
            chosen_z.append(z_sel)
            if st == 1:
                peak1_choose += 1
            votes.setdefault(int(key), []).append(float(z_sel))

        if len(chosen_z) >= 2:
            dz = np.abs(np.diff(np.asarray(chosen_z, dtype=np.float64)))
            all_dz.extend(np.asarray(dz, dtype=np.float64).tolist())
            dz_p50 = float(np.quantile(dz, 0.50))
            dz_p90 = float(np.quantile(dz, 0.90))
        else:
            dz_p50 = 0.0
            dz_p90 = 0.0
        per_traj.append(
            {
                "traj_index": int(ti),
                "n_cells": int(len(seq)),
                "dz_abs_p50": float(dz_p50),
                "dz_abs_p90": float(dz_p90),
                "peak1_selected_ratio": float(peak1_choose / len(seq)) if len(seq) > 0 else 0.0,
            }
        )

    road_z: dict[int, float] = {}
    for key, info in cell_peaks.items():
        k = int(key)
        cell_votes = votes.get(k)
        if cell_votes:
            road_z[k] = float(np.median(np.asarray(cell_votes, dtype=np.float64)))
        else:
            road_z[k] = float(info.get("peak0", 0.0))

    dz_arr = np.asarray(all_dz, dtype=np.float64)
    global_report = {
        "samples": int(dz_arr.size),
        "dz_abs_p50": float(np.quantile(dz_arr, 0.50)) if dz_arr.size > 0 else 0.0,
        "dz_abs_p90": float(np.quantile(dz_arr, 0.90)) if dz_arr.size > 0 else 0.0,
        "dz_abs_max": float(np.max(dz_arr)) if dz_arr.size > 0 else 0.0,
    }

    report: dict[str, object] = {
        "traj_count": int(len(trajs_xy)),
        "used_traj_count": int(len(per_traj)),
        "cells_with_votes": int(len(votes)),
        "per_traj": per_traj,
        "global": global_report,
    }
    return road_z, report
