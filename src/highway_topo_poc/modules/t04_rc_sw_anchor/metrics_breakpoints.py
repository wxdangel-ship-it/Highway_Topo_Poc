from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

import numpy as np


BP_FOCUS_NODE_NOT_FOUND = "FOCUS_NODE_NOT_FOUND"
BP_CRS_UNKNOWN = "CRS_UNKNOWN"
BP_MISSING_KIND_FIELD = "MISSING_KIND_FIELD"
BP_UNSUPPORTED_KIND = "UNSUPPORTED_KIND"
BP_AMBIGUOUS_KIND = "AMBIGUOUS_KIND"
BP_ROAD_LINK_NOT_FOUND = "ROAD_LINK_NOT_FOUND"
BP_ROAD_GRAPH_WEAK_STOP = "ROAD_GRAPH_WEAK_STOP"
BP_ROAD_FIELD_MISSING = "ROAD_FIELD_MISSING"
BP_DIVSTRIPZONE_MISSING = "DIVSTRIPZONE_MISSING"
BP_POINTCLOUD_MISSING_OR_UNUSABLE = "POINTCLOUD_MISSING_OR_UNUSABLE"
BP_TRAJ_MISSING = "TRAJ_MISSING"
BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION = "NO_TRIGGER_BEFORE_NEXT_INTERSECTION"
BP_SCAN_EXCEED_200M = "SCAN_EXCEED_200M"
BP_DIVSTRIP_TOLERANCE_VIOLATION = "DIVSTRIP_TOLERANCE_VIOLATION"
BP_DIVSTRIP_NEVER_HIT = "DIVSTRIP_NEVER_HIT"
BP_DIVSTRIP_NON_INTERSECT_NOT_FOUND = "DIVSTRIP_NON_INTERSECT_NOT_FOUND"
BP_DRIVEZONE_MISSING = "DRIVEZONE_MISSING"
BP_DRIVEZONE_UNION_EMPTY = "DRIVEZONE_UNION_EMPTY"
BP_DRIVEZONE_CRS_UNKNOWN = "DRIVEZONE_CRS_UNKNOWN"
BP_DRIVEZONE_CLIP_EMPTY = "DRIVEZONE_CLIP_EMPTY"
BP_DRIVEZONE_CLIP_MULTIPIECE = "DRIVEZONE_CLIP_MULTIPIECE"
BP_DRIVEZONE_SPLIT_NOT_FOUND = "DRIVEZONE_SPLIT_NOT_FOUND"
BP_SEQUENTIAL_ORDER_VIOLATION = "SEQUENTIAL_ORDER_VIOLATION"
BP_NEXT_INTERSECTION_NOT_FOUND_CONNECTED = "NEXT_INTERSECTION_NOT_FOUND_CONNECTED"
BP_NEXT_INTERSECTION_NOT_FOUND_DEG3 = "NEXT_INTERSECTION_NOT_FOUND_DEG3"
BP_NEXT_INTERSECTION_DISABLED = "NEXT_INTERSECTION_DISABLED"
BP_NEXT_INTERSECTION_DEG_TOO_LOW_SKIPPED = "NEXT_INTERSECTION_DEG_TOO_LOW_SKIPPED"
BP_ROAD_GRAPH_DISCONNECTED_STOP = "ROAD_GRAPH_DISCONNECTED_STOP"
BP_POINTCLOUD_CRS_UNKNOWN_UNUSABLE = "POINTCLOUD_CRS_UNKNOWN_UNUSABLE"
BP_MULTI_BRANCH_TODO = "MULTI_BRANCH_TODO"
BP_ANCHOR_GAP_UNSTABLE = "ANCHOR_GAP_UNSTABLE"
BP_REVERSE_TIP_ATTEMPTED = "REVERSE_TIP_ATTEMPTED"
BP_REVERSE_TIP_USED = "REVERSE_TIP_USED"
BP_REVERSE_TIP_NOT_FOUND = "REVERSE_TIP_NOT_FOUND"
BP_UNTRUSTED_DIVSTRIP_AT_NODE = "UNTRUSTED_DIVSTRIP_AT_NODE"


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
    if trigger == "drivezone_split":
        val += 0.45

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
    hard_breakpoint_count = int(sum(1 for bp in breakpoints if str(bp.get("severity", "")).lower() == "hard"))
    degraded_trigger_count = int(sum(1 for x in seed_results if str(x.get("trigger", "")) not in {"drivezone_split", "none"}))
    stop_reason_counts = dict(Counter(str(x.get("stop_reason", "none")) for x in seed_results))
    evidence_source_counts = dict(Counter(str(x.get("evidence_source", "unknown")) for x in seed_results))

    min_ratio = float(params["min_anchor_found_ratio_focus"] if mode == "global_focus" else params["min_anchor_found_ratio_patch"])
    if mode == "global_focus":
        no_trigger_max = int(params.get("no_trigger_count_max_focus", 0))
        scan_exceed_max = int(params.get("scan_exceed_200m_count_max_focus", 0))
    else:
        no_trigger_max = int(params.get("no_trigger_count_max_patch", seed_total))
        scan_exceed_max = int(params.get("scan_exceed_200m_count_max_patch", seed_total))

    hard_checks = {
        "required_outputs_present": bool(required_outputs_ok),
        "seed_total_gt_0": bool(seed_total > 0),
        "hard_breakpoint_count_eq_0": bool(hard_breakpoint_count == 0),
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
        "hard_breakpoint_count": int(hard_breakpoint_count),
        "degraded_trigger_count": int(degraded_trigger_count),
        "stop_reason_counts": stop_reason_counts,
        "evidence_source_counts": evidence_source_counts,
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
    crs_diag: dict[str, Any] | None = None,
) -> str:
    lines: list[str] = []
    lines.append("=== t04_rc_sw_anchor summary ===")
    lines.append(f"run_id: {run_id}")
    lines.append(f"patch_id: {patch_id}")
    lines.append(f"mode: {mode}")
    lines.append(f"overall_pass: {str(bool(metrics.get('overall_pass', False))).lower()}")

    if isinstance(crs_diag, dict):
        lines.append(f"dst_crs: {crs_diag.get('dst_crs')}")
        layer_crs = crs_diag.get("layer_crs")
        if isinstance(layer_crs, dict):
            lines.append("layer_crs:")
            for key in ["node", "road", "divstrip", "drivezone", "traj", "pointcloud"]:
                row = layer_crs.get(key)
                if not isinstance(row, dict):
                    continue
                lines.append(
                    "- {name}: src_detected={src_detected} src_used={src_used} dst={dst} bbox_src={bbox_src} bbox_dst={bbox_dst}".format(
                        name=key,
                        src_detected=row.get("src_crs_detected"),
                        src_used=row.get("src_crs_used"),
                        dst=row.get("dst_crs"),
                        bbox_src=row.get("bbox_src"),
                        bbox_dst=row.get("bbox_dst"),
                    )
                )

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
        focus_resolve = item.get("resolved_from")
        if isinstance(focus_resolve, dict):
            focus_text = "{focus}->{canon}({field})".format(
                focus=focus_resolve.get("focus_id"),
                canon=focus_resolve.get("canonical_id"),
                field=focus_resolve.get("matched_field"),
            )
        else:
            focus_text = "na"
        lines.append(
            "- nodeid={nodeid} kind={kind} kind_bits(merge={is_merge},diverge={is_diverge}) anchor_type={anchor_type} status={status} found_split={found_split} scan_dist_m={scan_dist} trigger={trigger} evidence_source={evidence_source} stop_dist_m={stop} stop_reason={stop_reason} pieces_count={pieces_count} piece_lens_m={piece_lens} gap_len_m={gap_len} seg_len_m={seg_len} s_divstrip_m={s_divstrip} s_drivezone_split_m={s_dz} s_chosen_m={s_chosen} split_pick_source={pick_src} dist_line_to_divstrip_m={dist_line_to_divstrip} dist_line_to_drivezone_edge_m={dist_line_to_drivezone_edge} branchA={branch_a} branchB={branch_b} focus_resolve={focus_resolve}".format(
                nodeid=item.get("nodeid"),
                kind=item.get("kind"),
                is_merge=item.get("is_merge_kind"),
                is_diverge=item.get("is_diverge_kind"),
                anchor_type=item.get("anchor_type"),
                status=item.get("status"),
                found_split=item.get("found_split"),
                scan_dist=item.get("scan_dist_m"),
                trigger=item.get("trigger"),
                evidence_source=item.get("evidence_source"),
                stop=item.get("stop_dist_m"),
                stop_reason=item.get("stop_reason"),
                pieces_count=item.get("pieces_count"),
                piece_lens=item.get("piece_lens_m"),
                gap_len=item.get("gap_len_m"),
                seg_len=item.get("seg_len_m"),
                s_divstrip=item.get("s_divstrip_m"),
                s_dz=item.get("s_drivezone_split_m"),
                s_chosen=item.get("s_chosen_m"),
                pick_src=item.get("split_pick_source"),
                dist_line_to_divstrip=item.get("dist_line_to_divstrip_m"),
                dist_line_to_drivezone_edge=item.get("dist_line_to_drivezone_edge_m"),
                branch_a=item.get("branch_a_id"),
                branch_b=item.get("branch_b_id"),
                focus_resolve=focus_text,
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
    "BP_CRS_UNKNOWN",
    "BP_DIVSTRIP_NEVER_HIT",
    "BP_DIVSTRIP_NON_INTERSECT_NOT_FOUND",
    "BP_DRIVEZONE_CLIP_EMPTY",
    "BP_DRIVEZONE_CLIP_MULTIPIECE",
    "BP_DRIVEZONE_CRS_UNKNOWN",
    "BP_DRIVEZONE_MISSING",
    "BP_DRIVEZONE_SPLIT_NOT_FOUND",
    "BP_SEQUENTIAL_ORDER_VIOLATION",
    "BP_DRIVEZONE_UNION_EMPTY",
    "BP_DIVSTRIPZONE_MISSING",
    "BP_DIVSTRIP_TOLERANCE_VIOLATION",
    "BP_ANCHOR_GAP_UNSTABLE",
    "BP_FOCUS_NODE_NOT_FOUND",
    "BP_MISSING_KIND_FIELD",
    "BP_MULTI_BRANCH_TODO",
    "BP_REVERSE_TIP_ATTEMPTED",
    "BP_REVERSE_TIP_USED",
    "BP_REVERSE_TIP_NOT_FOUND",
    "BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION",
    "BP_NEXT_INTERSECTION_DEG_TOO_LOW_SKIPPED",
    "BP_NEXT_INTERSECTION_DISABLED",
    "BP_NEXT_INTERSECTION_NOT_FOUND_DEG3",
    "BP_NEXT_INTERSECTION_NOT_FOUND_CONNECTED",
    "BP_POINTCLOUD_CRS_UNKNOWN_UNUSABLE",
    "BP_POINTCLOUD_MISSING_OR_UNUSABLE",
    "BP_ROAD_GRAPH_DISCONNECTED_STOP",
    "BP_ROAD_FIELD_MISSING",
    "BP_ROAD_GRAPH_WEAK_STOP",
    "BP_ROAD_LINK_NOT_FOUND",
    "BP_SCAN_EXCEED_200M",
    "BP_TRAJ_MISSING",
    "BP_UNSUPPORTED_KIND",
    "BP_UNTRUSTED_DIVSTRIP_AT_NODE",
    "build_metrics",
    "build_summary_text",
    "compute_confidence",
    "make_breakpoint",
    "summarize_breakpoints",
]
