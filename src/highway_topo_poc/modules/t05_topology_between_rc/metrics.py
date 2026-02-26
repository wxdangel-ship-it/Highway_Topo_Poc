from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Sequence

import numpy as np


def clamp01(v: float) -> float:
    return min(1.0, max(0.0, float(v)))


def compute_confidence(
    *,
    support_traj_count: int,
    center_sample_coverage: float,
    max_turn_deg_per_10m: float | None,
    turn_limit_deg_per_10m: float,
    w1: float,
    w2: float,
    w3: float,
) -> float:
    f_support = 1.0 - math.exp(-float(support_traj_count) / 2.0)
    f_coverage = clamp01(center_sample_coverage)

    if max_turn_deg_per_10m is None:
        f_smooth = 0.0
    else:
        f_smooth = clamp01(1.0 - float(max_turn_deg_per_10m) / max(turn_limit_deg_per_10m, 1e-6))

    conf = w1 * f_support + w2 * f_coverage + w3 * f_smooth
    return clamp01(conf)


def params_digest(params: dict[str, Any]) -> str:
    payload = json.dumps(_jsonable(params), ensure_ascii=True, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def build_metrics_payload(
    *,
    patch_id: str,
    roads: Sequence[dict[str, Any]],
    hard_breakpoints: Sequence[dict[str, Any]],
    soft_breakpoints: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    confs = np.asarray([_to_float(r.get("conf")) for r in roads], dtype=np.float64)
    confs = confs[np.isfinite(confs)]

    coverage = np.asarray([_to_float(r.get("center_sample_coverage")) for r in roads], dtype=np.float64)
    coverage = coverage[np.isfinite(coverage)]
    endpoint_offsets = np.asarray(
        [
            _to_float(v)
            for r in roads
            for v in (r.get("endpoint_center_offset_m_src"), r.get("endpoint_center_offset_m_dst"))
        ],
        dtype=np.float64,
    )
    endpoint_offsets = endpoint_offsets[np.isfinite(endpoint_offsets)]

    hard_count = sum(1 for r in roads if bool(r.get("hard_anomaly", False)))
    soft_count = sum(len(list(r.get("soft_issue_flags", []))) for r in roads)
    low_support_count = sum(1 for r in roads if "LOW_SUPPORT" in set(r.get("soft_issue_flags", [])))

    pair_set = {(int(r.get("src_nodeid", -1)), int(r.get("dst_nodeid", -1))) for r in roads}

    return {
        "patch_id": patch_id,
        "road_count": int(len(roads)),
        "unique_pair_count": int(len(pair_set)),
        "hard_anomaly_count": int(hard_count),
        "soft_issue_count": int(soft_count),
        "low_support_road_count": int(low_support_count),
        "avg_conf": _safe_stat(confs, np.mean),
        "p10_conf": _safe_percentile(confs, 10.0),
        "p50_conf": _safe_percentile(confs, 50.0),
        "center_coverage_avg": _safe_stat(coverage, np.mean),
        "endpoint_center_offset_p50": _safe_percentile(endpoint_offsets, 50.0),
        "endpoint_center_offset_p90": _safe_percentile(endpoint_offsets, 90.0),
        "endpoint_center_offset_max": _safe_stat(endpoint_offsets, np.max),
        "hard_breakpoint_count": int(len(hard_breakpoints)),
        "soft_breakpoint_count": int(len(soft_breakpoints)),
    }


def build_intervals_payload(
    *,
    breakpoints: Sequence[dict[str, Any]],
    topk: int,
) -> dict[str, Any]:
    ranked = sorted(breakpoints, key=_breakpoint_sort_key)
    top = ranked[: max(1, int(topk))]

    intervals: list[dict[str, Any]] = []
    for bp in top:
        item = {
            "road_id": bp.get("road_id"),
            "traj_id": bp.get("traj_id"),
            "seq_range": bp.get("seq_range"),
            "station_range_m": bp.get("station_range_m"),
            "reason": bp.get("reason"),
            "severity": bp.get("severity"),
            "hint": bp.get("hint"),
        }
        if "max_explored_dist_m" in bp:
            item["max_explored_dist_m"] = bp.get("max_explored_dist_m")
        if "last_node_ref" in bp:
            item["last_node_ref"] = bp.get("last_node_ref")
        if "stitch_candidate_count" in bp:
            item["stitch_candidate_count"] = bp.get("stitch_candidate_count")
        if "seg_index" in bp:
            item["seg_index"] = bp.get("seg_index")
        if "seg_length_m" in bp:
            item["seg_length_m"] = bp.get("seg_length_m")
        if "max_segment_m" in bp:
            item["max_segment_m"] = bp.get("max_segment_m")
        if "traj_surface_enforced" in bp:
            item["traj_surface_enforced"] = bp.get("traj_surface_enforced")
        if "traj_in_ratio" in bp:
            item["traj_in_ratio"] = bp.get("traj_in_ratio")
        if "slice_valid_ratio" in bp:
            item["slice_valid_ratio"] = bp.get("slice_valid_ratio")
        if "covered_length_ratio" in bp:
            item["covered_length_ratio"] = bp.get("covered_length_ratio")
        if "unique_traj_count" in bp:
            item["unique_traj_count"] = bp.get("unique_traj_count")
        intervals.append(item)

    return {"topk": intervals}


def build_gate_payload(
    *,
    overall_pass: bool,
    hard_breakpoints: Sequence[dict[str, Any]],
    soft_breakpoints: Sequence[dict[str, Any]],
    params_digest_value: str,
    version: str = "t05_gate_v1",
) -> dict[str, Any]:
    return {
        "overall_pass": bool(overall_pass),
        "hard_breakpoints": list(hard_breakpoints),
        "soft_breakpoints": list(soft_breakpoints),
        "params_digest": str(params_digest_value),
        "version": version,
    }


def build_summary_text(
    *,
    run_id: str,
    git_sha: str,
    patch_id: str,
    overall_pass: bool,
    roads: Sequence[dict[str, Any]],
    hard_breakpoints: Sequence[dict[str, Any]],
    soft_breakpoints: Sequence[dict[str, Any]],
    params: dict[str, Any],
    max_lines: int = 120,
    max_bytes: int = 8 * 1024,
) -> str:
    lines: list[str] = []
    lines.append("=== t05_topology_between_rc summary ===")
    lines.append(f"run_id: {run_id}")
    lines.append(f"git_sha: {git_sha}")
    lines.append(f"patch_id: {patch_id}")
    lines.append(f"overall_pass: {str(bool(overall_pass)).lower()}")
    lines.append("")

    road_count = len(roads)
    hard_count = sum(1 for r in roads if bool(r.get("hard_anomaly", False)))
    soft_count = sum(len(list(r.get("soft_issue_flags", []))) for r in roads)
    lines.append(f"road_count: {road_count}")
    lines.append(f"hard_anomaly_count: {hard_count}")
    lines.append(f"soft_issue_count: {soft_count}")
    stitch_vals: list[float] = []
    for road in roads:
        v = _to_float(road.get("stitch_hops_p50"))
        if math.isfinite(v):
            stitch_vals.append(float(v))
    if stitch_vals:
        arr = np.asarray(stitch_vals, dtype=np.float64)
        lines.append(f"stitch_hops_p50: {int(round(float(np.percentile(arr, 50.0))))}")
        lines.append(f"stitch_hops_p90: {int(round(float(np.percentile(arr, 90.0))))}")
        lines.append(f"stitch_hops_max: {int(round(float(np.max(arr))))}")

    lines.append("")
    lines.append("hard_breakpoints_topk:")
    if not hard_breakpoints:
        lines.append("- (none)")
    else:
        for bp in hard_breakpoints[:20]:
            lines.append(
                "- road_id={road} src={src} dst={dst} reason={reason} hint={hint}".format(
                    road=bp.get("road_id", "na"),
                    src=bp.get("src_nodeid", "na"),
                    dst=bp.get("dst_nodeid", "na"),
                    reason=bp.get("reason", "na"),
                    hint=bp.get("hint", ""),
                )
            )

    lines.append("")
    lines.append("soft_breakpoints_topk:")
    if not soft_breakpoints:
        lines.append("- (none)")
    else:
        for bp in soft_breakpoints[:20]:
            lines.append(
                "- road_id={road} src={src} dst={dst} reason={reason} hint={hint}".format(
                    road=bp.get("road_id", "na"),
                    src=bp.get("src_nodeid", "na"),
                    dst=bp.get("dst_nodeid", "na"),
                    reason=bp.get("reason", "na"),
                    hint=bp.get("hint", ""),
                )
            )

    lines.append("")
    lines.append("params:")
    for k in sorted(params.keys()):
        lines.append(f"- {k}={params[k]}")

    out = "\n".join(lines) + "\n"
    return apply_size_guard(out, max_lines=max_lines, max_bytes=max_bytes)


def build_breakpoint(
    *,
    road: dict[str, Any],
    reason: str,
    severity: str,
    hint: str,
    traj_id: str | None = None,
    seq_range: list[int] | None = None,
    station_range_m: list[float] | None = None,
) -> dict[str, Any]:
    return {
        "road_id": road.get("road_id"),
        "src_nodeid": road.get("src_nodeid"),
        "dst_nodeid": road.get("dst_nodeid"),
        "traj_id": traj_id,
        "seq_range": seq_range,
        "station_range_m": station_range_m,
        "reason": reason,
        "severity": severity,
        "hint": hint,
    }


def apply_size_guard(text: str, *, max_lines: int, max_bytes: int) -> str:
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

    out += f"Truncated: {'true' if truncated else 'false'} (reason={reason})\n"
    return out


def _safe_stat(x: np.ndarray, fn: Any) -> float | None:
    if x.size == 0:
        return None
    v = float(fn(x))
    if math.isfinite(v):
        return v
    return None


def _safe_percentile(x: np.ndarray, q: float) -> float | None:
    if x.size == 0:
        return None
    v = float(np.percentile(x, q))
    if math.isfinite(v):
        return v
    return None


def _breakpoint_sort_key(bp: dict[str, Any]) -> tuple[int, int, float]:
    sev = str(bp.get("severity", "soft"))
    if sev == "hard":
        s = 0
    elif sev == "soft":
        s = 1
    else:
        s = 2

    reason = str(bp.get("reason", ""))
    order = {
        "MULTI_ROAD_SAME_PAIR": 0,
        "NON_RC_IN_BETWEEN": 1,
        "CENTER_ESTIMATE_EMPTY": 2,
        "ENDPOINT_NOT_ON_XSEC": 3,
        "BRIDGE_SEGMENT_TOO_LONG": 4,
        "NO_ADJACENT_PAIR_AFTER_PASS2": 5,
        "LOW_SUPPORT": 10,
        "SPARSE_SURFACE_POINTS": 11,
        "NO_LB_CONTINUOUS": 12,
        "NO_LB_CONTINUOUS_PATH": 13,
        "WIGGLY_CENTERLINE": 13,
        "OPEN_END": 14,
        "UNRESOLVED_NEIGHBOR": 15,
        "NO_STABLE_SECTION": 16,
        "DIVSTRIP_MISSING": 17,
        "CROSS_EMPTY_SKIPPED": 18,
        "CROSS_GEOM_UNEXPECTED": 19,
        "CROSS_DISTANCE_GATE_REJECT": 20,
        "ROAD_OUTSIDE_TRAJ_SURFACE": 21,
        "TRAJ_SURFACE_INSUFFICIENT": 22,
        "TRAJ_SURFACE_GAP": 23,
    }
    r = order.get(reason, 99)

    src = _to_float(bp.get("src_nodeid"))
    return (s, r, src)


def _to_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return float("nan")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if math.isfinite(float(value)):
            return float(value)
        return None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


__all__ = [
    "apply_size_guard",
    "build_breakpoint",
    "build_gate_payload",
    "build_intervals_payload",
    "build_metrics_payload",
    "build_summary_text",
    "clamp01",
    "compute_confidence",
    "params_digest",
]
