from __future__ import annotations

import math

import numpy as np

from .config import Config


def compute_intervals(abs_res: np.ndarray, valid_mask: np.ndarray, cfg: Config) -> dict[str, object]:
    a = np.asarray(abs_res, dtype=np.float64)
    v = np.asarray(valid_mask, dtype=bool)

    if a.shape != v.shape:
        raise ValueError("abs_res_and_valid_mask_shape_mismatch")

    n_total = int(a.size)
    if n_total == 0:
        return {
            "bin_count": 0,
            "threshold_m": float(cfg.threshold_m),
            "bin_outlier_gate": float(cfg.bin_outlier_gate),
            "intervals": [],
            "bins": [],
            "n_total": 0,
        }

    bin_count = int(min(cfg.bin_count, n_total))
    edges = np.linspace(0, n_total, num=bin_count + 1, dtype=np.int64)

    bins: list[dict[str, object]] = []
    for b in range(bin_count):
        s = int(edges[b])
        e_excl = int(edges[b + 1])
        if e_excl <= s:
            continue

        vv = v[s:e_excl]
        if np.any(vv):
            av = a[s:e_excl][vv]
            mean_abs = float(np.mean(av))
            out_ratio = float(np.mean(av > cfg.threshold_m))
        else:
            mean_abs = float("nan")
            out_ratio = 0.0

        is_anomaly = bool(
            (math.isfinite(mean_abs) and mean_abs > cfg.threshold_m)
            or (out_ratio > cfg.bin_outlier_gate)
        )

        bins.append(
            {
                "bin": b,
                "start_idx": s,
                "end_idx": e_excl - 1,
                "n_idx": e_excl - s,
                "mean_abs_res_m": mean_abs,
                "outlier_ratio_bin": out_ratio,
                "is_anomaly": is_anomaly,
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
        if n_bins >= cfg.min_interval_bins:
            chunk = bins[i : j + 1]
            means = np.asarray([x["mean_abs_res_m"] for x in chunk], dtype=np.float64)
            ratios = np.asarray([x["outlier_ratio_bin"] for x in chunk], dtype=np.float64)

            max_mean = float(np.nanmax(means)) if np.any(np.isfinite(means)) else float("nan")
            max_ratio = float(np.max(ratios)) if ratios.size else 0.0
            score = float(max_mean * (1.0 + max_ratio)) if math.isfinite(max_mean) else float(max_ratio)

            merged.append(
                {
                    "start_bin": int(chunk[0]["bin"]),
                    "end_bin": int(chunk[-1]["bin"]),
                    "n_bins": n_bins,
                    "start_idx": int(chunk[0]["start_idx"]),
                    "end_idx": int(chunk[-1]["end_idx"]),
                    "max_mean_abs_res_m": max_mean,
                    "max_outlier_ratio_bin": max_ratio,
                    "score": score,
                }
            )

        i = j + 1

    merged = sorted(merged, key=lambda x: (-float(x["score"]), int(x["start_bin"])))
    top_intervals = merged[: cfg.top_k]

    return {
        "bin_count": len(bins),
        "threshold_m": float(cfg.threshold_m),
        "bin_outlier_gate": float(cfg.bin_outlier_gate),
        "intervals": top_intervals,
        "bins": bins,
        "n_total": n_total,
    }
