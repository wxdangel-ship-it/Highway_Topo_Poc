from __future__ import annotations

from pathlib import Path

from .config import Config


def build_summary(
    *,
    run_id: str,
    patch_id: str,
    patch_dir: Path,
    traj_path: Path,
    points_path: Path,
    output_dir: Path,
    metrics: dict[str, object],
    intervals_payload: dict[str, object],
    cfg: Config,
) -> str:
    lines: list[str] = []

    lines.append("=== t02_ground_seg_qc summary ===")
    lines.append(f"run_id: {run_id}")
    lines.append(f"patch_id: {patch_id}")
    lines.append(f"patch_dir: {patch_dir}")
    lines.append(f"traj_path: {traj_path}")
    lines.append(f"points_path: {points_path}")
    lines.append(f"output_dir: {output_dir}")
    lines.append("")

    lines.append("[metrics]")
    for key in ["p50", "p90", "p99", "coverage", "outlier_ratio", "bias", "baseline", "threshold", "n_total", "n_valid"]:
        if key in metrics:
            lines.append(f"{key}: {_fmt(metrics.get(key))}")

    gates = metrics.get("gates") if isinstance(metrics.get("gates"), dict) else {}
    lines.append("")
    lines.append("[gates]")
    for key in ["coverage_gate", "outlier_gate", "p99_gate_m", "overall_pass"]:
        lines.append(f"{key}: {gates.get(key)}")

    lines.append("")
    lines.append("[top_intervals]")
    intervals = intervals_payload.get("intervals", []) if isinstance(intervals_payload, dict) else []
    if not intervals:
        lines.append("(none)")
    else:
        for i, item in enumerate(intervals, start=1):
            if not isinstance(item, dict):
                continue
            start_bin = item.get("start_bin")
            end_bin = item.get("end_bin")
            start_idx = item.get("start_idx")
            end_idx = item.get("end_idx")
            n_bins = item.get("n_bins")
            score = item.get("score")
            max_mean_abs_res_m = item.get("max_mean_abs_res_m")
            max_outlier_ratio_bin = item.get("max_outlier_ratio_bin")
            lines.append(
                (
                    f"#{i}: bins={start_bin}-{end_bin} "
                    f"idx={start_idx}-{end_idx} "
                    f"n_bins={n_bins} score={_fmt(score)} "
                    f"max_mean_abs_res_m={_fmt(max_mean_abs_res_m)} "
                    f"max_outlier_ratio_bin={_fmt(max_outlier_ratio_bin)}"
                )
            )

    lines.append("")
    lines.append("[config]")
    lines.append(
        " ".join(
            [
                f"grid_size_m={cfg.grid_size_m}",
                f"dem_quantile_q={cfg.dem_quantile_q}",
                f"threshold_m={cfg.threshold_m}",
                f"bin_count={cfg.bin_count}",
                f"top_k={cfg.top_k}",
            ]
        )
    )

    text = "\n".join(lines) + "\n"
    return _apply_size_limit(text, max_lines=cfg.summary_max_lines, max_bytes=cfg.summary_max_bytes)


def _fmt(v: object) -> str:
    if isinstance(v, float):
        if v != v:
            return "nan"
        return f"{v:.6f}"
    return str(v)


def _apply_size_limit(text: str, *, max_lines: int, max_bytes: int) -> str:
    lines = text.splitlines()
    truncated = False
    reason = "na"

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
        reason = "line_limit"

    out = "\n".join(lines).rstrip("\n") + "\n"

    while len(out.encode("utf-8")) > max_bytes and lines:
        lines = lines[:-1]
        out = "\n".join(lines).rstrip("\n") + "\n"
        truncated = True
        reason = "byte_limit"

    out = out.rstrip("\n") + "\n"
    flag = "true" if truncated else "false"
    out += f"Truncated: {flag} (reason={reason})\n"
    return out
