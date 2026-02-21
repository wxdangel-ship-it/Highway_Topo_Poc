from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .config import Config


@dataclass(frozen=True)
class XSecQCResult:
    metrics: dict[str, object]
    intervals: dict[str, object]
    coverage: np.ndarray
    line_a: np.ndarray
    line_b: np.ndarray
    abs_res_p90: np.ndarray
    support_count: np.ndarray
    is_anomaly: np.ndarray


def compute_xsec_qc(traj_xyz: np.ndarray, ground_xyz: np.ndarray, cfg: Config) -> XSecQCResult:
    traj = np.asarray(traj_xyz, dtype=np.float64)
    ground = np.asarray(ground_xyz, dtype=np.float64)

    n = int(traj.shape[0])
    coverage = np.zeros(n, dtype=np.float64)
    line_a = np.full(n, np.nan, dtype=np.float64)
    line_b = np.full(n, np.nan, dtype=np.float64)
    abs_res_p90 = np.full(n, np.nan, dtype=np.float64)
    support_count = np.zeros(n, dtype=np.int64)
    is_anomaly = np.zeros(n, dtype=bool)

    if n == 0:
        intervals = _build_xsec_intervals(
            abs_res_p90=abs_res_p90,
            is_anomaly=is_anomaly,
            support_count=support_count,
            cfg=cfg,
        )
        metrics = _aggregate_metrics(
            abs_res_p90=abs_res_p90,
            coverage=coverage,
            is_anomaly=is_anomaly,
            support_count=support_count,
            cfg=cfg,
        )
        return XSecQCResult(
            metrics=metrics,
            intervals=intervals,
            coverage=coverage,
            line_a=line_a,
            line_b=line_b,
            abs_res_p90=abs_res_p90,
            support_count=support_count,
            is_anomaly=is_anomaly,
        )

    if ground.size == 0:
        is_anomaly[:] = True
        intervals = _build_xsec_intervals(
            abs_res_p90=abs_res_p90,
            is_anomaly=is_anomaly,
            support_count=support_count,
            cfg=cfg,
        )
        metrics = _aggregate_metrics(
            abs_res_p90=abs_res_p90,
            coverage=coverage,
            is_anomaly=is_anomaly,
            support_count=support_count,
            cfg=cfg,
        )
        return XSecQCResult(
            metrics=metrics,
            intervals=intervals,
            coverage=coverage,
            line_a=line_a,
            line_b=line_b,
            abs_res_p90=abs_res_p90,
            support_count=support_count,
            is_anomaly=is_anomaly,
        )

    headings = _compute_headings(traj[:, :2])

    cell_size = max(cfg.grid_size_m, 0.5)
    gx = ground[:, 0]
    gy = ground[:, 1]
    gz = ground[:, 2]

    grid_x0 = float(np.min(gx))
    grid_y0 = float(np.min(gy))
    cell_ix = np.floor((gx - grid_x0) / cell_size).astype(np.int64)
    cell_iy = np.floor((gy - grid_y0) / cell_size).astype(np.int64)

    cell_map_raw: dict[tuple[int, int], list[int]] = {}
    for idx, key in enumerate(zip(cell_ix, cell_iy)):
        k = (int(key[0]), int(key[1]))
        cell_map_raw.setdefault(k, []).append(idx)
    cell_map: dict[tuple[int, int], np.ndarray] = {
        k: np.asarray(v, dtype=np.int64) for k, v in cell_map_raw.items()
    }

    search_cell_radius = max(1, int(math.ceil(cfg.xsec_radius_m / cell_size)))

    bin_edges = np.linspace(-cfg.cross_half_width_m, cfg.cross_half_width_m, num=cfg.xsec_bin_count + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) * 0.5

    for i in range(n):
        heading = headings[i]
        if not np.all(np.isfinite(heading)):
            is_anomaly[i] = True
            continue

        t_hat = heading
        c_hat = np.asarray([-t_hat[1], t_hat[0]], dtype=np.float64)
        pxy = traj[i, :2]

        cix = int(math.floor((pxy[0] - grid_x0) / cell_size))
        ciy = int(math.floor((pxy[1] - grid_y0) / cell_size))

        chunks: list[np.ndarray] = []
        for dx in range(-search_cell_radius, search_cell_radius + 1):
            for dy in range(-search_cell_radius, search_cell_radius + 1):
                key = (cix + dx, ciy + dy)
                pts_idx = cell_map.get(key)
                if pts_idx is not None and pts_idx.size > 0:
                    chunks.append(pts_idx)

        if not chunks:
            is_anomaly[i] = True
            continue

        cand_idx = np.unique(np.concatenate(chunks))
        dx = gx[cand_idx] - pxy[0]
        dy = gy[cand_idx] - pxy[1]

        dist2 = dx * dx + dy * dy
        within_radius = dist2 <= (cfg.xsec_radius_m * cfg.xsec_radius_m)
        if not np.any(within_radius):
            is_anomaly[i] = True
            continue

        cand_idx = cand_idx[within_radius]
        dx = gx[cand_idx] - pxy[0]
        dy = gy[cand_idx] - pxy[1]

        forward = dx * t_hat[0] + dy * t_hat[1]
        cross = dx * c_hat[0] + dy * c_hat[1]

        mask_window = (np.abs(forward) <= cfg.along_window_m) & (np.abs(cross) <= cfg.cross_half_width_m)
        if not np.any(mask_window):
            is_anomaly[i] = True
            continue

        cand_idx = cand_idx[mask_window]
        cross = cross[mask_window]
        z = gz[cand_idx]

        support = int(cand_idx.size)
        support_count[i] = support

        bin_id = np.searchsorted(bin_edges, cross, side="right") - 1
        valid_bid = (bin_id >= 0) & (bin_id < cfg.xsec_bin_count)
        bin_id = bin_id[valid_bid]
        z = z[valid_bid]

        z_median = np.full(cfg.xsec_bin_count, np.nan, dtype=np.float64)
        for b in range(cfg.xsec_bin_count):
            m = bin_id == b
            if np.any(m):
                z_median[b] = float(np.median(z[m]))

        valid_bins = np.isfinite(z_median)
        n_valid_bins = int(np.count_nonzero(valid_bins))
        cov = float(n_valid_bins / cfg.xsec_bin_count)
        coverage[i] = cov

        if n_valid_bins >= 2:
            x_fit = bin_centers[valid_bins]
            y_fit = z_median[valid_bins]
            a, b = np.polyfit(x_fit, y_fit, deg=1)
            a_val = float(a)
            b_val = float(b)
            pred = a_val * x_fit + b_val
            residual = y_fit - pred
            abs_p90 = float(np.quantile(np.abs(residual), 0.90))
            line_a[i] = a_val
            line_b[i] = b_val
            abs_res_p90[i] = abs_p90
        elif n_valid_bins == 1:
            x_fit = bin_centers[valid_bins]
            y_fit = z_median[valid_bins]
            line_a[i] = 0.0
            line_b[i] = float(y_fit[0])
            abs_res_p90[i] = 0.0
        else:
            line_a[i] = np.nan
            line_b[i] = np.nan
            abs_res_p90[i] = np.nan

        bad_cov = cov < cfg.xsec_coverage_gate_per_sample
        bad_res = (np.isfinite(abs_res_p90[i]) and abs_res_p90[i] > cfg.xsec_residual_gate_per_sample) or (not np.isfinite(abs_res_p90[i]))
        is_anomaly[i] = bool(bad_cov or bad_res)

    metrics = _aggregate_metrics(
        abs_res_p90=abs_res_p90,
        coverage=coverage,
        is_anomaly=is_anomaly,
        support_count=support_count,
        cfg=cfg,
    )
    intervals = _build_xsec_intervals(
        abs_res_p90=abs_res_p90,
        is_anomaly=is_anomaly,
        support_count=support_count,
        cfg=cfg,
    )

    return XSecQCResult(
        metrics=metrics,
        intervals=intervals,
        coverage=coverage,
        line_a=line_a,
        line_b=line_b,
        abs_res_p90=abs_res_p90,
        support_count=support_count,
        is_anomaly=is_anomaly,
    )


def _compute_headings(traj_xy: np.ndarray) -> np.ndarray:
    xy = np.asarray(traj_xy, dtype=np.float64)
    n = int(xy.shape[0])
    out = np.full((n, 2), np.nan, dtype=np.float64)

    if n == 0:
        return out

    for i in range(n):
        if n == 1:
            break
        if i == 0:
            v = xy[1] - xy[0]
        elif i == n - 1:
            v = xy[n - 1] - xy[n - 2]
        else:
            v = xy[i + 1] - xy[i - 1]

        norm = float(np.linalg.norm(v))
        if norm > 1e-9:
            out[i] = v / norm

    return out


def _aggregate_metrics(
    *,
    abs_res_p90: np.ndarray,
    coverage: np.ndarray,
    is_anomaly: np.ndarray,
    support_count: np.ndarray,
    cfg: Config,
) -> dict[str, object]:
    n = int(abs_res_p90.size)

    valid_samples = coverage > 0
    valid_ratio = float(np.mean(valid_samples)) if n > 0 else 0.0

    finite_res = abs_res_p90[np.isfinite(abs_res_p90)]
    if finite_res.size > 0:
        p50 = float(np.quantile(finite_res, 0.50))
        p90 = float(np.quantile(finite_res, 0.90))
        p99 = float(np.quantile(finite_res, 0.99))
    else:
        p50 = float("nan")
        p90 = float("nan")
        p99 = float("nan")

    anomaly_ratio = float(np.mean(is_anomaly)) if n > 0 else 0.0
    support_median = float(np.median(support_count)) if n > 0 else 0.0

    support_gate = bool(valid_ratio >= cfg.xsec_valid_ratio_gate)
    residual_gate = bool(np.isfinite(p99) and p99 <= cfg.xsec_p99_abs_res_gate_m)
    anomaly_gate = bool(anomaly_ratio <= cfg.xsec_anomaly_ratio_gate)
    overall_pass = bool(support_gate and residual_gate and anomaly_gate)

    return {
        "n_traj": n,
        "xsec_valid_ratio": valid_ratio,
        "xsec_p50_abs_res_m": p50,
        "xsec_p90_abs_res_m": p90,
        "xsec_p99_abs_res_m": p99,
        "xsec_anomaly_ratio": anomaly_ratio,
        "xsec_support_median": support_median,
        "gate_thresholds": {
            "xsec_valid_ratio_gate": cfg.xsec_valid_ratio_gate,
            "xsec_p99_abs_res_gate_m": cfg.xsec_p99_abs_res_gate_m,
            "xsec_anomaly_ratio_gate": cfg.xsec_anomaly_ratio_gate,
        },
        "gates": {
            "support_gate": support_gate,
            "residual_gate": residual_gate,
            "anomaly_gate": anomaly_gate,
            "overall_pass": overall_pass,
        },
    }


def _build_xsec_intervals(
    *,
    abs_res_p90: np.ndarray,
    is_anomaly: np.ndarray,
    support_count: np.ndarray,
    cfg: Config,
) -> dict[str, object]:
    n = int(is_anomaly.size)
    if n == 0:
        return {
            "bin_count": 0,
            "xsec_bin_anomaly_gate": float(cfg.xsec_bin_anomaly_gate),
            "intervals": [],
            "bins": [],
            "n_total": 0,
        }

    bin_count = int(min(cfg.xsec_interval_bin_count, n))
    edges = np.linspace(0, n, num=bin_count + 1, dtype=np.int64)

    bins: list[dict[str, object]] = []
    for b in range(bin_count):
        s = int(edges[b])
        e = int(edges[b + 1])
        if e <= s:
            continue

        sub_anom = is_anomaly[s:e]
        sub_res = abs_res_p90[s:e]
        sub_support = support_count[s:e]

        ratio = float(np.mean(sub_anom))
        finite = sub_res[np.isfinite(sub_res)]
        max_res = float(np.max(finite)) if finite.size else float("nan")
        min_support = int(np.min(sub_support)) if sub_support.size else 0

        is_bin_anomaly = bool(ratio > cfg.xsec_bin_anomaly_gate)
        bins.append(
            {
                "bin": b,
                "start_idx": s,
                "end_idx": e - 1,
                "anomaly_ratio_bin": ratio,
                "max_abs_res_p90_m": max_res,
                "min_support_count": min_support,
                "is_anomaly": is_bin_anomaly,
            }
        )

    merged: list[dict[str, object]] = []
    i = 0
    while i < len(bins):
        if not bool(bins[i]["is_anomaly"]):
            i += 1
            continue

        j = i
        while j + 1 < len(bins) and bool(bins[j + 1]["is_anomaly"]):
            j += 1

        n_bins = j - i + 1
        if n_bins >= cfg.xsec_min_interval_bins:
            chunk = bins[i : j + 1]
            max_ratio = float(np.max([float(x["anomaly_ratio_bin"]) for x in chunk]))
            res_vals = np.asarray([float(x["max_abs_res_p90_m"]) for x in chunk], dtype=np.float64)
            max_res = float(np.nanmax(res_vals)) if np.any(np.isfinite(res_vals)) else 0.0
            min_support = int(np.min([int(x["min_support_count"]) for x in chunk]))
            score = float(max_res * (1.0 + max_ratio))

            merged.append(
                {
                    "start_bin": int(chunk[0]["bin"]),
                    "end_bin": int(chunk[-1]["bin"]),
                    "n_bins": n_bins,
                    "start_idx": int(chunk[0]["start_idx"]),
                    "end_idx": int(chunk[-1]["end_idx"]),
                    "max_abs_res_p90_m": max_res,
                    "max_anomaly_ratio_bin": max_ratio,
                    "min_support_count": min_support,
                    "score": score,
                }
            )

        i = j + 1

    merged = sorted(merged, key=lambda x: (-float(x["score"]), int(x["start_bin"])))

    return {
        "bin_count": len(bins),
        "xsec_bin_anomaly_gate": float(cfg.xsec_bin_anomaly_gate),
        "intervals": merged[: cfg.xsec_top_k],
        "bins": bins,
        "n_total": n,
    }
