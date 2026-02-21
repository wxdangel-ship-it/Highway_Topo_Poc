from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Config


@dataclass(frozen=True)
class QCResult:
    metrics: dict[str, object]
    z_diff: np.ndarray
    residual: np.ndarray
    abs_res: np.ndarray
    valid_mask: np.ndarray


def compute_qc(traj_z: np.ndarray, ground_z: np.ndarray, cfg: Config) -> QCResult:
    t = np.asarray(traj_z, dtype=np.float64)
    g = np.asarray(ground_z, dtype=np.float64)

    if t.shape != g.shape:
        raise ValueError("traj_z_and_ground_z_shape_mismatch")

    z_diff = t - g
    valid_mask = np.isfinite(z_diff)

    n_total = int(z_diff.size)
    n_valid = int(np.count_nonzero(valid_mask))

    if n_valid > 0:
        z_valid = z_diff[valid_mask]
        if cfg.baseline_mode == "mean":
            baseline = float(np.mean(z_valid))
        else:
            baseline = float(np.median(z_valid))
        residual = z_diff - baseline
        abs_res = np.abs(residual)
        abs_res_valid = abs_res[valid_mask]
        p50 = float(np.quantile(abs_res_valid, 0.50))
        p90 = float(np.quantile(abs_res_valid, 0.90))
        p99 = float(np.quantile(abs_res_valid, 0.99))
        outlier_ratio = float(np.mean(abs_res_valid > cfg.threshold_m))
        bias = float(np.mean(residual[valid_mask]))
    else:
        baseline = float("nan")
        residual = np.full_like(z_diff, np.nan)
        abs_res = np.full_like(z_diff, np.nan)
        p50 = float("nan")
        p90 = float("nan")
        p99 = float("nan")
        outlier_ratio = 0.0
        bias = float("nan")

    coverage = float(n_valid / n_total) if n_total > 0 else 0.0

    coverage_gate = bool(coverage >= cfg.coverage_gate)
    outlier_gate = bool(outlier_ratio <= cfg.outlier_gate)
    p99_gate_m = bool(np.isfinite(p99) and p99 <= cfg.p99_gate_m)
    overall_pass = bool(coverage_gate and outlier_gate and p99_gate_m)

    gates = {
        "coverage_gate": coverage_gate,
        "outlier_gate": outlier_gate,
        "p99_gate_m": p99_gate_m,
        "overall_pass": overall_pass,
    }

    metrics: dict[str, object] = {
        "p50": p50,
        "p90": p90,
        "p99": p99,
        "coverage": coverage,
        "outlier_ratio": outlier_ratio,
        "bias": bias,
        "baseline": baseline,
        "threshold": float(cfg.threshold_m),
        # aliases for readability in downstream reports
        "bias_m": bias,
        "baseline_m": baseline,
        "threshold_m": float(cfg.threshold_m),
        "n_total": n_total,
        "n_valid": n_valid,
        "gates": gates,
        "gate_thresholds": {
            "coverage_gate": cfg.coverage_gate,
            "outlier_gate": cfg.outlier_gate,
            "p99_gate_m": cfg.p99_gate_m,
        },
    }

    return QCResult(
        metrics=metrics,
        z_diff=z_diff,
        residual=residual,
        abs_res=abs_res,
        valid_mask=valid_mask,
    )
