from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Callable

from .config import Config


@dataclass(frozen=True)
class TuneOutcome:
    chosen_config: Config
    chosen_result: dict[str, object]
    tune_log: list[dict[str, object]]
    overall_pass: bool


def tune_until_pass(
    *,
    base_cfg: Config,
    base_result: dict[str, object],
    evaluate_once: Callable[[Config], dict[str, object]],
    enabled: bool,
) -> TuneOutcome:
    base_metrics = _as_dict(base_result.get("metrics"))
    base_pass = bool(_as_dict(base_metrics.get("gates")).get("overall_pass", False))
    base_penalty = _compute_penalty(base_metrics, base_cfg)

    tune_log: list[dict[str, object]] = [
        _make_log_record(
            trial_id=0,
            cfg=base_cfg,
            metrics=base_metrics,
            passed=base_pass,
            penalty=base_penalty,
            note="default",
        )
    ]

    best_cfg = base_cfg
    best_result = base_result
    best_penalty = base_penalty

    if base_pass or not enabled:
        return TuneOutcome(
            chosen_config=best_cfg,
            chosen_result=best_result,
            tune_log=tune_log,
            overall_pass=base_pass,
        )

    candidates = _candidate_configs(base_cfg, limit=base_cfg.auto_tune_max_trials)

    trial_id = 0
    for cfg in candidates:
        trial_id += 1
        try:
            result = evaluate_once(cfg)
            metrics = _as_dict(result.get("metrics"))
            passed = bool(_as_dict(metrics.get("gates")).get("overall_pass", False))
            penalty = _compute_penalty(metrics, cfg)
            rec = _make_log_record(
                trial_id=trial_id,
                cfg=cfg,
                metrics=metrics,
                passed=passed,
                penalty=penalty,
                note="trial",
            )
            tune_log.append(rec)

            if penalty < best_penalty:
                best_penalty = penalty
                best_cfg = cfg
                best_result = result

            if passed:
                return TuneOutcome(
                    chosen_config=cfg,
                    chosen_result=result,
                    tune_log=tune_log,
                    overall_pass=True,
                )

        except Exception as exc:
            tune_log.append(
                {
                    "trial_id": trial_id,
                    "params": cfg.to_dict(),
                    "overall_pass": False,
                    "penalty": 1e9,
                    "error": f"{type(exc).__name__}: {exc}",
                    "note": "trial_error",
                }
            )

    final_pass = bool(_as_dict(_as_dict(best_result.get("metrics")).get("gates")).get("overall_pass", False))
    return TuneOutcome(
        chosen_config=best_cfg,
        chosen_result=best_result,
        tune_log=tune_log,
        overall_pass=final_pass,
    )


def _candidate_configs(base_cfg: Config, *, limit: int) -> list[Config]:
    # Hand-crafted mixed presets (ground + xsec) prioritized for real-patch recovery.
    presets = [
        base_cfg.with_updates(
            grid_size_m=0.5,
            dem_quantile_q=0.05,
            above_margin_m=0.08,
            below_margin_m=0.20,
            xsec_bin_count=15,
            along_window_m=0.5,
            cross_half_width_m=2.5,
            xsec_residual_gate_per_sample=0.18,
            xsec_coverage_gate_per_sample=0.25,
        ),
        base_cfg.with_updates(
            grid_size_m=0.5,
            dem_quantile_q=0.05,
            above_margin_m=0.08,
            below_margin_m=0.20,
            xsec_bin_count=11,
            along_window_m=0.5,
            cross_half_width_m=2.5,
            xsec_residual_gate_per_sample=0.18,
            xsec_coverage_gate_per_sample=0.25,
        ),
        base_cfg.with_updates(
            grid_size_m=0.5,
            dem_quantile_q=0.05,
            above_margin_m=0.05,
            below_margin_m=0.15,
            xsec_bin_count=15,
            along_window_m=0.5,
            cross_half_width_m=3.0,
            xsec_residual_gate_per_sample=0.15,
            xsec_coverage_gate_per_sample=0.25,
        ),
    ]

    # Stage-1: ground-focused search.
    stage1 = []
    for grid_size_m, dem_quantile_q, above_margin_m, below_margin_m in product(
        [0.5, 1.0, 1.5],
        [0.03, 0.05, 0.10],
        [0.05, 0.08, 0.12],
        [0.15, 0.20, 0.30],
    ):
        stage1.append(
            base_cfg.with_updates(
                grid_size_m=grid_size_m,
                dem_quantile_q=dem_quantile_q,
                above_margin_m=above_margin_m,
                below_margin_m=below_margin_m,
            )
        )

    # Stage-2: cross-section-focused search around current best defaults.
    stage2 = []
    for xsec_bin_count, along_window_m, cross_half_width_m, xsec_residual_gate_per_sample, xsec_coverage_gate_per_sample in product(
        [11, 15, 21],
        [0.5, 1.0],
        [2.5, 3.0, 4.0, 6.0, 10.0],
        [0.18, 0.15, 0.12, 0.10],
        [0.25, 0.35],
    ):
        stage2.append(
            base_cfg.with_updates(
                xsec_bin_count=xsec_bin_count,
                along_window_m=along_window_m,
                cross_half_width_m=cross_half_width_m,
                xsec_residual_gate_per_sample=xsec_residual_gate_per_sample,
                xsec_coverage_gate_per_sample=xsec_coverage_gate_per_sample,
            )
        )

    # Prioritize mixed presets and cross-section search first; real patches often fail on xsec gates.
    merged = presets + stage2 + stage1

    out: list[Config] = []
    seen: set[tuple[tuple[str, object], ...]] = set()
    base_key = tuple(sorted(base_cfg.to_dict().items()))
    seen.add(base_key)

    for cfg in merged:
        key = tuple(sorted(cfg.to_dict().items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(cfg)
        if len(out) >= limit:
            break

    return out


def _compute_penalty(metrics: dict[str, object], cfg: Config) -> float:
    def f(name: str, default: float = 0.0) -> float:
        val = metrics.get(name, default)
        try:
            return float(val)
        except Exception:
            return default

    penalty = 0.0

    coverage = f("coverage", 0.0)
    outlier_ratio = f("outlier_ratio", 1.0)
    p99 = f("p99", 1.0)

    penalty += max(0.0, cfg.coverage_gate - coverage)
    penalty += max(0.0, outlier_ratio - cfg.outlier_gate)
    penalty += max(0.0, p99 - cfg.p99_gate_m)

    ground_ratio = f("ground_ratio", 0.0)
    ground_count = f("ground_count", 0.0)
    penalty += max(0.0, cfg.ground_ratio_min - ground_ratio)
    penalty += max(0.0, ground_ratio - cfg.ground_ratio_max)
    penalty += max(0.0, cfg.ground_count_gate_min - ground_count) / max(float(cfg.ground_count_gate_min), 1.0)

    xsec_valid_ratio = f("xsec_valid_ratio", 0.0)
    xsec_p99 = f("xsec_p99_abs_res_m", 1.0)
    xsec_anomaly_ratio = f("xsec_anomaly_ratio", 1.0)

    penalty += max(0.0, cfg.xsec_valid_ratio_gate - xsec_valid_ratio)
    penalty += max(0.0, xsec_p99 - cfg.xsec_p99_abs_res_gate_m)
    penalty += max(0.0, xsec_anomaly_ratio - cfg.xsec_anomaly_ratio_gate)

    gates = _as_dict(metrics.get("gates"))
    if not bool(gates.get("overall_pass", False)):
        penalty += 0.1

    return float(penalty)


def _make_log_record(
    *,
    trial_id: int,
    cfg: Config,
    metrics: dict[str, object],
    passed: bool,
    penalty: float,
    note: str,
) -> dict[str, object]:
    return {
        "trial_id": int(trial_id),
        "params": cfg.to_dict(),
        "overall_pass": bool(passed),
        "penalty": float(penalty),
        "core_metrics": {
            "coverage": metrics.get("coverage"),
            "outlier_ratio": metrics.get("outlier_ratio"),
            "p99": metrics.get("p99"),
            "ground_ratio": metrics.get("ground_ratio"),
            "ground_count": metrics.get("ground_count"),
            "xsec_valid_ratio": metrics.get("xsec_valid_ratio"),
            "xsec_p99_abs_res_m": metrics.get("xsec_p99_abs_res_m"),
            "xsec_anomaly_ratio": metrics.get("xsec_anomaly_ratio"),
        },
        "note": note,
    }


def _as_dict(v: object) -> dict[str, object]:
    return v if isinstance(v, dict) else {}
