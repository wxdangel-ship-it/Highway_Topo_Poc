from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import PatchAnalysis


def _f(v: float | None) -> float | None:
    if v is None:
        return None
    return float(v)


def _metrics_item(result: PatchAnalysis) -> dict[str, Any]:
    m = result.metrics
    return {
        "patch_key": result.patch_key,
        "cloud_path": result.cloud_path,
        "traj_path": result.traj_path,
        "n_traj": int(m.n_traj),
        "n_valid": int(m.n_valid),
        "coverage": _f(m.coverage),
        "p50": _f(m.p50),
        "p90": _f(m.p90),
        "p99": _f(m.p99),
        "threshold_A": _f(m.threshold_A),
        "status": m.status,
        "backend": m.backend,
        "warnings": list(m.warnings),
    }


def _interval_item(result: PatchAnalysis) -> dict[str, Any]:
    return {
        "patch_key": result.patch_key,
        "intervals": [
            {
                "start_bin": int(iv.start_bin),
                "end_bin": int(iv.end_bin),
                "len_bins": int(iv.len_bins),
                "interval_score": _f(iv.interval_score),
                "start_idx": int(iv.start_idx),
                "end_idx": int(iv.end_idx),
            }
            for iv in result.intervals
        ],
        "bins": [
            {
                "bin_index": int(b.bin_index),
                "start_idx": int(b.start_idx),
                "end_idx": int(b.end_idx),
                "valid_fraction": _f(b.valid_fraction),
                "valid_count": int(b.valid_count),
                "bin_score": _f(b.bin_score),
                "insufficient_coverage": bool(b.insufficient_coverage),
                "abnormal": bool(b.abnormal),
            }
            for b in result.bins
        ],
    }


def write_run_reports(results: list[PatchAnalysis], out_dir: Path, params: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics_payload = {
        "module": "t01_fusion_qc",
        "params": params,
        "results": [_metrics_item(r) for r in results],
    }
    intervals_payload = {
        "module": "t01_fusion_qc",
        "params": params,
        "results": [_interval_item(r) for r in results],
    }

    (out_dir / "metrics.json").write_text(
        json.dumps(metrics_payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "intervals.json").write_text(
        json.dumps(intervals_payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    lines: list[str] = []
    lines.append("t01_fusion_qc summary")
    lines.append(f"patch_count: {len(results)}")

    for idx, r in enumerate(results, start=1):
        m = r.metrics
        lines.append("")
        lines.append(f"[{idx}] patch_key: {r.patch_key}")
        lines.append(f"cloud_path: {r.cloud_path}")
        lines.append(f"traj_path: {r.traj_path}")
        lines.append(f"coverage: {m.coverage:.6f} ({m.n_valid}/{m.n_traj})")
        lines.append(f"p50/p90/p99: {_fmt(m.p50)} / {_fmt(m.p90)} / {_fmt(m.p99)}")
        lines.append(f"threshold_A: {_fmt(m.threshold_A)}")
        lines.append(f"status: {m.status}")
        lines.append(f"backend: {m.backend}")
        lines.append("TopK intervals:")

        if not r.intervals:
            lines.append("- (none)")
        else:
            for j, iv in enumerate(r.intervals, start=1):
                lines.append(
                    "- #{j} bins=[{sb},{eb}) score={score} idx=[{si},{ei}) len_bins={lb}".format(
                        j=j,
                        sb=iv.start_bin,
                        eb=iv.end_bin,
                        score=_fmt(iv.interval_score),
                        si=iv.start_idx,
                        ei=iv.end_idx,
                        lb=iv.len_bins,
                    )
                )

        if m.warnings:
            lines.append("warnings: " + "; ".join(m.warnings))

    (out_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(v: float | None) -> str:
    if v is None:
        return "na"
    return f"{float(v):.6f}"
