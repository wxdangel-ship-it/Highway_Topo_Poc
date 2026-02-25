from __future__ import annotations

from collections import deque

import numpy as np

from .corridor import pack_cell_scalar, unpack_cell


def _clamp(v: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, v)))


def detect_overlap_cells(
    cell_peaks: dict[int, dict[str, float | int]],
    road_z: dict[int, float],
    *,
    sep_gate_m: float = 3.0,
    min_support_points: int = 60,
    min_support_ratio: float = 0.10,
    min_total_points_per_cell: int = 200,
    density_reference: float = 500.0,
) -> tuple[set[int], set[int], dict[str, object]]:
    if sep_gate_m < 0:
        raise ValueError("sep_gate_m must be >= 0")
    if min_support_points < 1:
        raise ValueError("min_support_points must be >= 1")
    if min_support_ratio < 0 or min_support_ratio > 1:
        raise ValueError("min_support_ratio must be in [0,1]")
    if min_total_points_per_cell < 1:
        raise ValueError("min_total_points_per_cell must be >= 1")

    totals: list[int] = []
    for info in cell_peaks.values():
        total = int(info.get("total_points", 0))
        if total > 0:
            totals.append(total)
    mean_density = float(np.median(np.asarray(totals, dtype=np.float64))) if totals else 0.0
    density_scale = _clamp(mean_density / float(max(1.0, density_reference)), 0.2, 3.0)
    min_total_adapt = max(10, int(round(float(min_total_points_per_cell) * density_scale)))
    min_support_adapt = max(5, int(round(float(min_support_points) * density_scale)))

    high: set[int] = set()
    low: set[int] = set()
    considered = 0
    for key, info in cell_peaks.items():
        k = int(key)
        if k not in road_z:
            continue
        considered += 1
        total = int(info.get("total_points", 0))
        if total < min_total_adapt:
            continue
        peak0 = float(info.get("peak0", 0.0))
        peak1 = float(info.get("peak1", np.nan))
        support0 = int(info.get("support0", 0))
        support1 = int(info.get("support1", 0))
        if support1 <= 0 or not np.isfinite(peak1):
            continue

        rz = float(road_z[k])
        d0 = abs(peak0 - rz)
        d1 = abs(peak1 - rz)
        if d0 <= d1:
            inter_peak = float(peak1)
            inter_support = int(support1)
        else:
            inter_peak = float(peak0)
            inter_support = int(support0)
        sep = abs(inter_peak - rz)
        ratio = float(inter_support / max(1, total))
        if sep < float(sep_gate_m):
            continue
        if inter_support < min_support_adapt:
            continue
        if ratio < float(min_support_ratio):
            continue
        if inter_peak > rz:
            high.add(k)
        elif inter_peak < rz:
            low.add(k)

    report: dict[str, object] = {
        "considered_cells": int(considered),
        "candidate_high_count": int(len(high)),
        "candidate_low_count": int(len(low)),
        "mean_cell_density": float(mean_density),
        "density_scale": float(density_scale),
        "adaptive_thresholds": {
            "min_total_points_per_cell": int(min_total_adapt),
            "min_support_points": int(min_support_adapt),
        },
        "base_thresholds": {
            "min_total_points_per_cell": int(min_total_points_per_cell),
            "min_support_points": int(min_support_points),
            "min_support_ratio": float(min_support_ratio),
            "sep_gate_m": float(sep_gate_m),
        },
    }
    return high, low, report


def cluster_cells_8n(cell_ids: set[int]) -> list[set[int]]:
    clusters: list[set[int]] = []
    if not cell_ids:
        return clusters
    visited: set[int] = set()
    for start in sorted(cell_ids):
        if start in visited:
            continue
        q: deque[int] = deque([int(start)])
        visited.add(int(start))
        cluster: set[int] = set()
        while q:
            cur = q.popleft()
            cluster.add(cur)
            cx, cy = unpack_cell(cur)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nb = pack_cell_scalar(cx + dx, cy + dy)
                    if nb in cell_ids and nb not in visited:
                        visited.add(nb)
                        q.append(nb)
        clusters.append(cluster)
    return clusters


def keep_clusters_by_size(
    clusters: list[set[int]],
    *,
    min_cluster_cells: int,
) -> tuple[set[int], list[int]]:
    if min_cluster_cells < 1:
        raise ValueError("min_cluster_cells must be >= 1")
    kept: set[int] = set()
    sizes: list[int] = []
    for cluster in clusters:
        csz = int(len(cluster))
        sizes.append(csz)
        if csz >= int(min_cluster_cells):
            kept.update(cluster)
    return kept, sizes
