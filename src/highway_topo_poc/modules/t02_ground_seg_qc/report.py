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
    traj_intervals_payload: dict[str, object],
    xsec_intervals_payload: dict[str, object],
    ground_stats: dict[str, object],
    chosen_config: Config,
    tune_log: list[dict[str, object]],
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

    lines.append("[ground]")
    for key in ["ground_source", "ground_count", "ground_ratio", "ground_coverage", "export_count", "sampled"]:
        if key in metrics:
            lines.append(f"{key}: {_fmt(metrics.get(key))}")
        elif key in ground_stats:
            lines.append(f"{key}: {_fmt(ground_stats.get(key))}")

    lines.append("")
    lines.append("[traj_clearance_metrics]")
    for key in ["coverage", "outlier_ratio", "p50", "p90", "p99", "baseline", "threshold"]:
        if key in metrics:
            lines.append(f"{key}: {_fmt(metrics.get(key))}")

    lines.append("")
    lines.append("[xsec_metrics]")
    for key in ["xsec_valid_ratio", "xsec_p50_abs_res_m", "xsec_p90_abs_res_m", "xsec_p99_abs_res_m", "xsec_anomaly_ratio"]:
        if key in metrics:
            lines.append(f"{key}: {_fmt(metrics.get(key))}")

    lines.append("")
    lines.append("[gates]")
    gates = metrics.get("gates") if isinstance(metrics.get("gates"), dict) else {}
    for key in ["traj_gates", "ground_gates", "xsec_gates", "overall_pass"]:
        lines.append(f"{key}: {gates.get(key)}")

    lines.append("")
    lines.append("[top_traj_intervals]")
    lines.extend(_format_intervals(traj_intervals_payload, kind="traj"))

    lines.append("")
    lines.append("[top_xsec_intervals]")
    lines.extend(_format_intervals(xsec_intervals_payload, kind="xsec"))

    lines.append("")
    lines.append("[auto_tune]")
    lines.append(f"trials: {len(tune_log)}")
    if tune_log:
        last = tune_log[-1]
        lines.append(f"final_trial_pass: {last.get('overall_pass')}")
        lines.append(f"final_penalty: {_fmt(last.get('penalty'))}")

    lines.append("")
    lines.append("[chosen_config]")
    lines.append(
        " ".join(
            [
                f"grid_size_m={chosen_config.grid_size_m}",
                f"dem_quantile_q={chosen_config.dem_quantile_q}",
                f"above_margin_m={chosen_config.above_margin_m}",
                f"below_margin_m={chosen_config.below_margin_m}",
                f"xsec_bin_count={chosen_config.xsec_bin_count}",
                f"along_window_m={chosen_config.along_window_m}",
                f"cross_half_width_m={chosen_config.cross_half_width_m}",
            ]
        )
    )

    text = "\n".join(lines) + "\n"
    return _apply_size_limit(text, max_lines=chosen_config.summary_max_lines, max_bytes=chosen_config.summary_max_bytes)


def _format_intervals(payload: dict[str, object], *, kind: str) -> list[str]:
    intervals = payload.get("intervals", []) if isinstance(payload, dict) else []
    if not intervals:
        return ["(none)"]

    out: list[str] = []
    for i, item in enumerate(intervals[:5], start=1):
        if not isinstance(item, dict):
            continue
        if kind == "xsec":
            out.append(
                (
                    f"#{i}: bins={item.get('start_bin')}-{item.get('end_bin')} "
                    f"idx={item.get('start_idx')}-{item.get('end_idx')} "
                    f"score={_fmt(item.get('score'))} "
                    f"max_abs_res_p90_m={_fmt(item.get('max_abs_res_p90_m'))} "
                    f"max_anomaly_ratio_bin={_fmt(item.get('max_anomaly_ratio_bin'))}"
                )
            )
        else:
            out.append(
                (
                    f"#{i}: bins={item.get('start_bin')}-{item.get('end_bin')} "
                    f"idx={item.get('start_idx')}-{item.get('end_idx')} "
                    f"score={_fmt(item.get('score'))}"
                )
            )
    return out or ["(none)"]


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
