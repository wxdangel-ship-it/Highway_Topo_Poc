from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

import numpy as np


BP_FOCUS_NODE_NOT_FOUND = "FOCUS_NODE_NOT_FOUND"
BP_UNSUPPORTED_KIND = "UNSUPPORTED_KIND"
BP_AMBIGUOUS_KIND = "AMBIGUOUS_KIND"
BP_ROAD_LINK_NOT_FOUND = "ROAD_LINK_NOT_FOUND"
BP_ROAD_GRAPH_WEAK_STOP = "ROAD_GRAPH_WEAK_STOP"
BP_DIVSTRIPZONE_MISSING = "DIVSTRIPZONE_MISSING"
BP_POINTCLOUD_MISSING_OR_UNUSABLE = "POINTCLOUD_MISSING_OR_UNUSABLE"
BP_TRAJ_MISSING = "TRAJ_MISSING"
BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION = "NO_TRIGGER_BEFORE_NEXT_INTERSECTION"
BP_SCAN_EXCEED_200M = "SCAN_EXCEED_200M"
BP_DIVSTRIP_TOLERANCE_VIOLATION = "DIVSTRIP_TOLERANCE_VIOLATION"


def make_breakpoint(
    *,
    code: str,
    severity: str,
    nodeid: int | None,
    message: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "code": str(code),
        "severity": str(severity),
        "nodeid": None if nodeid is None else int(nodeid),
        "message": str(message),
    }
    if extra:
        item["extra"] = dict(extra)
    return item


def summarize_breakpoints(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    cnt = Counter(str(x.get("code", "")) for x in items)
    by_code = [{"code": code, "count": int(c)} for code, c in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {
        "count": int(len(items)),
        "by_code": by_code,
        "items": list(items),
    }


def _distance_stats(vals: list[float]) -> dict[str, float | None]:
    if not vals:
        return {"min": None, "mean": None, "p50": None, "p95": None, "max": None}
    arr = np.asarray(vals, dtype=np.float64)
    return {
        "min": float(np.min(arr)),
        "mean": float(np.mean(arr)),
        "p50": float(np.percentile(arr, 50.0)),
        "p95": float(np.percentile(arr, 95.0)),
        "max": float(np.max(arr)),
    }


def clamp01(v: float) -> float:
    return min(1.0, max(0.0, float(v)))


def compute_confidence(*, trigger: str, scan_dist_m: float | None) -> float:
    val = 0.35
    if trigger == "divstrip+pc":
        val += 0.45
    elif trigger == "pc_only":
        val += 0.30
    elif trigger == "divstrip_only_degraded":
        val += 0.15

    d = float(scan_dist_m) if scan_dist_m is not None else 0.0
    if d > 20.0:
        val -= 0.20
    if d > 200.0:
        val -= 0.30
    return clamp01(val)


def _count_code(items: Sequence[dict[str, Any]], code: str) -> int:
    return int(sum(1 for x in items if str(x.get("code")) == code))


def build_metrics(
    *,
    patch_id: str,
    mode: str,
    seed_results: Sequence[dict[str, Any]],
    breakpoints: Sequence[dict[str, Any]],
    params: dict[str, Any],
    required_outputs_ok: bool,
) -> dict[str, Any]:
    seed_total = int(len(seed_results))
    found_count = int(sum(1 for x in seed_results if bool(x.get("anchor_found", False))))
    missing_count = int(seed_total - found_count)

    ratio = float(found_count / seed_total) if seed_total > 0 else 0.0

    scan_dists = [float(x.get("scan_dist_m")) for x in seed_results if x.get("scan_dist_m") is not None]

    no_trigger_count = _count_code(breakpoints, BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION)
    scan_exceed_count = _count_code(breakpoints, BP_SCAN_EXCEED_200M)

    min_ratio = float(params["min_anchor_found_ratio_focus"] if mode == "global_focus" else params["min_anchor_found_ratio_patch"])
    no_trigger_max = int(params.get("no_trigger_count_max_focus", 0 if mode == "global_focus" else seed_total))
    scan_exceed_max = int(params.get("scan_exceed_200m_count_max_focus", 0 if mode == "global_focus" else seed_total))

    hard_checks = {
        "required_outputs_present": bool(required_outputs_ok),
        "seed_total_gt_0": bool(seed_total > 0),
    }

    soft_checks = {
        "anchor_found_ratio": {
            "value": ratio,
            "threshold": min_ratio,
            "pass": ratio >= min_ratio,
        },
        "no_trigger_count": {
            "value": int(no_trigger_count),
            "threshold": int(no_trigger_max),
            "pass": int(no_trigger_count) <= int(no_trigger_max),
        },
        "scan_exceed_200m_count": {
            "value": int(scan_exceed_count),
            "threshold": int(scan_exceed_max),
            "pass": int(scan_exceed_count) <= int(scan_exceed_max),
        },
    }

    hard_pass = all(bool(v) for v in hard_checks.values())
    soft_pass = all(bool(v.get("pass", False)) for v in soft_checks.values())

    bp_summary = summarize_breakpoints(breakpoints)

    return {
        "patch_id": str(patch_id),
        "mode": str(mode),
        "seed_total": int(seed_total),
        "anchors_found_count": int(found_count),
        "anchors_missing_count": int(missing_count),
        "anchor_found_ratio": float(ratio),
        "scan_dist_m_stats": _distance_stats(scan_dists),
        "breakpoints_by_code": bp_summary.get("by_code", []),
        "gate_eval": {
            "hard": hard_checks,
            "soft": soft_checks,
            "hard_pass": bool(hard_pass),
            "soft_pass": bool(soft_pass),
        },
        "overall_pass": bool(hard_pass and soft_pass),
    }


def build_summary_text(
    *,
    run_id: str,
    patch_id: str,
    mode: str,
    metrics: dict[str, Any],
    breakpoints_summary: dict[str, Any],
    seed_results: Sequence[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append("=== t04_rc_sw_anchor summary ===")
    lines.append(f"run_id: {run_id}")
    lines.append(f"patch_id: {patch_id}")
    lines.append(f"mode: {mode}")
    lines.append(f"overall_pass: {str(bool(metrics.get('overall_pass', False))).lower()}")
    lines.append("")
    lines.append(
        "seed_total={seed_total} found={found} missing={missing} ratio={ratio:.3f}".format(
            seed_total=int(metrics.get("seed_total", 0)),
            found=int(metrics.get("anchors_found_count", 0)),
            missing=int(metrics.get("anchors_missing_count", 0)),
            ratio=float(metrics.get("anchor_found_ratio", 0.0)),
        )
    )

    lines.append("")
    lines.append("per_node:")
    for item in seed_results:
        lines.append(
            "- nodeid={nodeid} anchor_type={anchor_type} status={status} scan_dist_m={scan_dist} trigger={trigger} stop_dist_m={stop}".format(
                nodeid=item.get("nodeid"),
                anchor_type=item.get("anchor_type"),
                status=item.get("status"),
                scan_dist=item.get("scan_dist_m"),
                trigger=item.get("trigger"),
                stop=item.get("stop_dist_m"),
            )
        )

    lines.append("")
    lines.append("top_breakpoints:")
    by_code = breakpoints_summary.get("by_code", [])
    if isinstance(by_code, list) and by_code:
        for row in by_code[:8]:
            lines.append(f"- {row.get('code')}: {row.get('count')}")
    else:
        lines.append("- (none)")

    soft = metrics.get("gate_eval", {}).get("soft", {})
    lines.append("")
    lines.append("gates:")
    lines.append(f"- anchor_found_ratio >= {soft.get('anchor_found_ratio', {}).get('threshold')}")
    lines.append(f"- no_trigger_count <= {soft.get('no_trigger_count', {}).get('threshold')}")
    lines.append(f"- scan_exceed_200m_count <= {soft.get('scan_exceed_200m_count', {}).get('threshold')}")
    lines.append("=== END ===")
    return "\n".join(lines) + "\n"


__all__ = [
    "BP_AMBIGUOUS_KIND",
    "BP_DIVSTRIPZONE_MISSING",
    "BP_DIVSTRIP_TOLERANCE_VIOLATION",
    "BP_FOCUS_NODE_NOT_FOUND",
    "BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION",
    "BP_POINTCLOUD_MISSING_OR_UNUSABLE",
    "BP_ROAD_GRAPH_WEAK_STOP",
    "BP_ROAD_LINK_NOT_FOUND",
    "BP_SCAN_EXCEED_200M",
    "BP_TRAJ_MISSING",
    "BP_UNSUPPORTED_KIND",
    "build_metrics",
    "build_summary_text",
    "compute_confidence",
    "make_breakpoint",
    "summarize_breakpoints",
]
