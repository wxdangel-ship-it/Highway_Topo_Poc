from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Sequence

import numpy as np


BP_MISSING_INTERSECTION_L = "MISSING_INTERSECTION_L"
BP_MULTIPLE_INTERSECTION_L = "MULTIPLE_INTERSECTION_L"
BP_ROAD_LINK_NOT_FOUND = "ROAD_LINK_NOT_FOUND"
BP_UNSUPPORTED_KIND = "UNSUPPORTED_KIND"
BP_AMBIGUOUS_KIND = "AMBIGUOUS_KIND"
BP_POINTCLOUD_MISSING_OR_UNUSABLE = "POINTCLOUD_MISSING_OR_UNUSABLE"
BP_DIVSTRIPZONE_MISSING = "DIVSTRIPZONE_MISSING"
BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION = "NO_TRIGGER_BEFORE_NEXT_INTERSECTION"
BP_SCAN_EXCEED_200M = "SCAN_EXCEED_200M"
BP_DIVSTRIP_TOLERANCE_VIOLATION = "DIVSTRIP_TOLERANCE_VIOLATION"


def clamp01(v: float) -> float:
    return min(1.0, max(0.0, float(v)))


def compute_confidence(trigger: str, scan_dist_m: float | None) -> float:
    v = 0.4
    if trigger == "divstrip+pc":
        v += 0.4
    elif trigger == "pc_only":
        v += 0.25
    elif trigger == "divstrip_only_degraded":
        v += 0.15

    d = float(scan_dist_m) if scan_dist_m is not None else 0.0
    if d > 20.0:
        v -= 0.2
    if d > 200.0:
        v -= 0.3
    return clamp01(v)


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
    nodes_by_code: dict[str, list[int]] = defaultdict(list)
    for x in items:
        code = str(x.get("code", ""))
        nodeid = x.get("nodeid")
        if isinstance(nodeid, int):
            nodes_by_code[code].append(int(nodeid))

    by_code = []
    for code, c in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0])):
        by_code.append(
            {
                "code": code,
                "count": int(c),
                "nodeids_topk": sorted(set(nodes_by_code.get(code, [])))[:10],
            }
        )

    return {
        "count": int(len(items)),
        "by_code": by_code,
        "items": list(items),
    }


def _ratio(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return float(num) / float(den)


def _distance_stats(vals: list[float]) -> dict[str, float | None]:
    if not vals:
        return {"min": None, "p50": None, "p90": None, "max": None}
    arr = np.asarray(vals, dtype=np.float64)
    return {
        "min": float(np.min(arr)),
        "p50": float(np.percentile(arr, 50.0)),
        "p90": float(np.percentile(arr, 90.0)),
        "max": float(np.max(arr)),
    }


def build_metrics(
    *,
    seed_results: Sequence[dict[str, Any]],
    breakpoints: Sequence[dict[str, Any]],
    config: dict[str, Any],
    must_inputs_ok: bool,
    required_outputs_ok: bool,
) -> dict[str, Any]:
    seed_total = int(len(seed_results))
    found_count = int(sum(1 for x in seed_results if bool(x.get("anchor_found", False))))

    no_trigger_count = int(
        sum(1 for x in breakpoints if str(x.get("code")) == BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION)
    )
    scan_exceed_count = int(sum(1 for x in breakpoints if str(x.get("code")) == BP_SCAN_EXCEED_200M))
    multiple_intersection_count = int(
        sum(1 for x in breakpoints if str(x.get("code")) == BP_MULTIPLE_INTERSECTION_L)
    )
    divstrip_tol_violation_count = int(
        sum(1 for x in breakpoints if str(x.get("code")) == BP_DIVSTRIP_TOLERANCE_VIOLATION)
    )

    found_dists = [float(x["scan_dist_m"]) for x in seed_results if x.get("anchor_found") and x.get("scan_dist_m") is not None]

    anchor_found_ratio = _ratio(found_count, seed_total)
    no_trigger_ratio = _ratio(no_trigger_count, seed_total)
    scan_exceed_ratio = _ratio(scan_exceed_count, seed_total)

    hard_checks = {
        "must_inputs_parsed": bool(must_inputs_ok),
        "seed_total_gt_0": seed_total > 0,
        "multiple_intersection_l_zero": multiple_intersection_count == 0,
        "required_outputs_present": bool(required_outputs_ok),
    }
    if bool(config.get("divstrip_tolerance_violation_hard", True)):
        hard_checks["divstrip_tolerance_violation_zero"] = divstrip_tol_violation_count == 0

    soft_checks = {
        "anchor_found_ratio": {
            "value": float(anchor_found_ratio),
            "threshold": float(config["anchor_found_ratio_min"]),
            "pass": float(anchor_found_ratio) >= float(config["anchor_found_ratio_min"]),
        },
        "no_trigger_before_next_intersection_ratio": {
            "value": float(no_trigger_ratio),
            "threshold": float(config["no_trigger_before_next_intersection_ratio_max"]),
            "pass": float(no_trigger_ratio)
            <= float(config["no_trigger_before_next_intersection_ratio_max"]),
        },
        "scan_exceed_200m_ratio": {
            "value": float(scan_exceed_ratio),
            "threshold": float(config["scan_exceed_200m_ratio_max"]),
            "pass": float(scan_exceed_ratio) <= float(config["scan_exceed_200m_ratio_max"]),
        },
    }

    hard_pass = all(bool(v) for v in hard_checks.values())
    soft_pass = all(bool(v.get("pass", False)) for v in soft_checks.values())
    overall_pass = bool(hard_pass and soft_pass)

    return {
        "seed_total": int(seed_total),
        "anchor_found_count": int(found_count),
        "anchor_found_ratio": float(anchor_found_ratio),
        "anchors_found_ratio": float(anchor_found_ratio),
        "no_trigger_before_next_intersection_count": int(no_trigger_count),
        "no_trigger_before_next_intersection_ratio": float(no_trigger_ratio),
        "scan_exceed_200m_count": int(scan_exceed_count),
        "scan_exceed_200m_ratio": float(scan_exceed_ratio),
        "multiple_intersection_l_count": int(multiple_intersection_count),
        "divstrip_tolerance_violation_count": int(divstrip_tol_violation_count),
        "status_count": {
            "ok": int(sum(1 for x in seed_results if str(x.get("status")) == "ok")),
            "suspect": int(sum(1 for x in seed_results if str(x.get("status")) == "suspect")),
            "fail": int(sum(1 for x in seed_results if str(x.get("status")) == "fail")),
        },
        "scan_dist_m_stats": _distance_stats(found_dists),
        "gate_eval": {
            "hard": hard_checks,
            "soft": soft_checks,
            "hard_pass": bool(hard_pass),
            "soft_pass": bool(soft_pass),
        },
        "overall_pass": bool(overall_pass),
    }


def build_summary_text(
    *,
    run_id: str,
    patch_id: str,
    metrics: dict[str, Any],
    breakpoints_summary: dict[str, Any],
    seed_results: Sequence[dict[str, Any]],
    max_lines: int = 60,
) -> str:
    lines: list[str] = []
    lines.append("=== t04_rc_sw_anchor summary ===")
    lines.append(f"run_id: {run_id}")
    lines.append(f"patch_id: {patch_id}")
    lines.append(f"overall_pass: {str(bool(metrics.get('overall_pass', False))).lower()}")
    lines.append("")

    lines.append(f"seed_total: {metrics.get('seed_total', 0)}")
    lines.append(f"anchor_found_ratio: {metrics.get('anchor_found_ratio', 0.0):.3f}")
    lines.append(f"no_trigger_ratio: {metrics.get('no_trigger_before_next_intersection_ratio', 0.0):.3f}")
    lines.append(f"scan_exceed_200m_ratio: {metrics.get('scan_exceed_200m_ratio', 0.0):.3f}")

    lines.append("")
    lines.append("top_breakpoints:")
    by_code = breakpoints_summary.get("by_code", [])
    if isinstance(by_code, list) and by_code:
        for item in by_code[:5]:
            code = str(item.get("code", "na"))
            count = int(item.get("count", 0))
            nodes = item.get("nodeids_topk", [])
            lines.append(f"- {code}: count={count} nodes={nodes}")
    else:
        lines.append("- (none)")

    lines.append("")
    lines.append("scan_dist_topk:")
    ranked = [x for x in seed_results if x.get("scan_dist_m") is not None]
    ranked = sorted(ranked, key=lambda x: float(x.get("scan_dist_m", -1.0)), reverse=True)
    if ranked:
        for item in ranked[:5]:
            nodeid = item.get("nodeid")
            status = item.get("status")
            dist = float(item.get("scan_dist_m", 0.0))
            trigger = item.get("trigger")
            lines.append(f"- nodeid={nodeid} status={status} scan_dist_m={dist:.2f} trigger={trigger}")
    else:
        lines.append("- (none)")

    lines.append("=== END ===")

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append("Truncated: true (reason=line_limit)")
    else:
        lines.append("Truncated: false (reason=na)")

    return "\n".join(lines) + "\n"


__all__ = [
    "BP_AMBIGUOUS_KIND",
    "BP_DIVSTRIP_TOLERANCE_VIOLATION",
    "BP_DIVSTRIPZONE_MISSING",
    "BP_MISSING_INTERSECTION_L",
    "BP_MULTIPLE_INTERSECTION_L",
    "BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION",
    "BP_POINTCLOUD_MISSING_OR_UNUSABLE",
    "BP_ROAD_LINK_NOT_FOUND",
    "BP_SCAN_EXCEED_200M",
    "BP_UNSUPPORTED_KIND",
    "build_metrics",
    "build_summary_text",
    "compute_confidence",
    "make_breakpoint",
    "summarize_breakpoints",
]
