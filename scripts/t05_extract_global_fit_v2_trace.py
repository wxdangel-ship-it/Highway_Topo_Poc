from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median
from typing import Any


SIMPLE_PATCH_IDS = {"5417632690143239", "5417632690143326"}
EMPTY_LABEL = "__empty__"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_pairs(text: str) -> list[str]:
    return [item.strip() for item in str(text or "").split(",") if item.strip()]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _nonempty_str(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else EMPTY_LABEL


def _metric_stats(values: list[float]) -> dict[str, Any]:
    clean = [float(item) for item in values]
    if not clean:
        return {"count": 0, "mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
    clean.sort()
    return {
        "count": int(len(clean)),
        "mean": float(sum(clean) / len(clean)),
        "median": float(median(clean)),
        "min": float(clean[0]),
        "max": float(clean[-1]),
    }


def _histogram(values: list[Any]) -> dict[str, int]:
    counter = Counter(_nonempty_str(item) for item in values)
    return {key: int(count) for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))}


def _lane_hint_usage_ratio(row: dict[str, Any]) -> float:
    return _safe_float(dict(row.get("lane_boundary_hint_usage") or {}).get("usage_ratio"), 0.0)


def _correction_mean_m(row: dict[str, Any]) -> float:
    return _safe_float(dict(row.get("centerline_correction_summary") or {}).get("correction_mean_m"), 0.0)


def _correction_max_m(row: dict[str, Any]) -> float:
    return _safe_float(dict(row.get("centerline_correction_summary") or {}).get("correction_max_m"), 0.0)


def _tangent_confidence(row: dict[str, Any], endpoint_key: str) -> float:
    return _safe_float(dict(row.get(endpoint_key) or {}).get("confidence"), 0.0)


def _tangent_source(row: dict[str, Any], endpoint_key: str) -> str:
    return str(dict(row.get(endpoint_key) or {}).get("source_type", "") or "")


def _fit_metric(row: dict[str, Any], key: str) -> float:
    return _safe_float(dict(row.get("fit_metrics") or {}).get(key), 0.0)


def _summary_examples(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for row in rows[:limit]:
        examples.append(
            {
                "patch_id": str(row.get("patch_id", "")),
                "pair": str(row.get("pair", "")),
                "arc_id": str(row.get("arc_id", "")),
                "final_export_source": str(row.get("final_export_source", "")),
                "fallback_reason": str(row.get("fallback_reason", "")),
                "quality_gate_reason": str(row.get("quality_gate_reason", "")),
            }
        )
    return examples


def _bucket(rows: list[dict[str, Any]], *, limit: int) -> dict[str, Any]:
    return {
        "count": int(len(rows)),
        "examples": _summary_examples(rows, limit=limit),
    }


def _row_issue_flags(
    row: dict[str, Any],
    *,
    low_spine_quality: float,
    low_lane_hint_usage: float,
    high_tangent_error_deg: float,
    high_target_offset_m: float,
    high_endpoint_offset_m: float,
) -> list[str]:
    issues: list[str] = []
    if not bool(row.get("built_final_road", False)):
        issues.append("built_false")
    if not bool(row.get("global_fit_used_bool", False)):
        issues.append("global_fit_not_used")
    fallback_reason = str(row.get("fallback_reason", "") or "")
    if fallback_reason:
        issues.append(f"fallback:{fallback_reason}")
    quality_gate_reason = str(row.get("quality_gate_reason", "") or "")
    if quality_gate_reason:
        issues.append(f"quality_gate:{quality_gate_reason}")
    if _safe_float(row.get("center_corrected_spine_quality"), 0.0) < low_spine_quality:
        issues.append("low_corrected_spine_quality")
    if _lane_hint_usage_ratio(row) < low_lane_hint_usage:
        issues.append("low_lane_hint_usage")
    if _fit_metric(row, "src_tangent_error_deg") > high_tangent_error_deg:
        issues.append("high_src_tangent_error")
    if _fit_metric(row, "dst_tangent_error_deg") > high_tangent_error_deg:
        issues.append("high_dst_tangent_error")
    if _fit_metric(row, "mean_target_offset_m") > high_target_offset_m:
        issues.append("high_target_offset")
    if _fit_metric(row, "endpoint_neighborhood_offset_m") > high_endpoint_offset_m:
        issues.append("high_endpoint_offset")
    return issues


def _row_suspicion_score(
    row: dict[str, Any],
    *,
    low_spine_quality: float,
    low_lane_hint_usage: float,
    high_tangent_error_deg: float,
    high_target_offset_m: float,
    high_endpoint_offset_m: float,
) -> float:
    score = 0.0
    if not bool(row.get("built_final_road", False)):
        score += 6.0
    if not bool(row.get("global_fit_used_bool", False)):
        score += 4.0
    if str(row.get("fallback_reason", "") or ""):
        score += 3.0
    if str(row.get("quality_gate_reason", "") or ""):
        score += 2.0
    corrected_quality = _safe_float(row.get("center_corrected_spine_quality"), 0.0)
    if corrected_quality < low_spine_quality:
        score += 1.0 + (low_spine_quality - corrected_quality) * 4.0
    lane_hint_usage = _lane_hint_usage_ratio(row)
    if lane_hint_usage < low_lane_hint_usage:
        score += 1.0 + max(0.0, low_lane_hint_usage - lane_hint_usage) * 2.0
    score += max(0.0, _fit_metric(row, "src_tangent_error_deg") - high_tangent_error_deg) / 10.0
    score += max(0.0, _fit_metric(row, "dst_tangent_error_deg") - high_tangent_error_deg) / 10.0
    score += max(0.0, _fit_metric(row, "mean_target_offset_m") - high_target_offset_m)
    score += max(0.0, _fit_metric(row, "endpoint_neighborhood_offset_m") - high_endpoint_offset_m)
    return float(score)


def _build_abstract_findings(
    *,
    row_count: int,
    overview: dict[str, Any],
    quality_summary: dict[str, Any],
) -> list[str]:
    if row_count <= 0:
        return ["No rows matched the requested patch/pair filter."]
    findings: list[str] = []
    final_export_ratio = _safe_float(overview.get("global_fit_final_export_ratio"), 0.0)
    fallback_count = _safe_int(overview.get("fallback_count"), 0)
    built_false_count = _safe_int(overview.get("built_false_count"), 0)
    correction_ratio = _safe_float(overview.get("centerline_correction_enabled_ratio"), 0.0)
    tangent_ratio = _safe_float(overview.get("endpoint_tangent_enabled_ratio"), 0.0)
    lane_usage_mean = _safe_float(dict(quality_summary.get("lane_hint_usage_ratio") or {}).get("mean"), 0.0)
    src_tangent_error_mean = _safe_float(dict(quality_summary.get("src_tangent_error_deg") or {}).get("mean"), 0.0)
    dst_tangent_error_mean = _safe_float(dict(quality_summary.get("dst_tangent_error_deg") or {}).get("mean"), 0.0)
    corrected_quality_mean = _safe_float(dict(quality_summary.get("center_corrected_spine_quality") or {}).get("mean"), 0.0)
    trajectory_quality_mean = _safe_float(dict(quality_summary.get("trajectory_spine_quality") or {}).get("mean"), 0.0)

    if final_export_ratio >= 0.9:
        findings.append("Global fitted line has become the dominant final export path; the remaining issue is quality refinement rather than apply-chain leakage.")
    elif final_export_ratio >= 0.6:
        findings.append("Global fitted line is the main final export source, but fallback is still non-trivial on a noticeable subset.")
    else:
        findings.append("Global fitted line is not yet dominant in final export for this scope; fallback pressure is still high.")

    if correction_ratio >= 0.7 and lane_usage_mean < 0.25:
        findings.append("Centerline correction is enabled on many rows, but high-quality lane-boundary coverage remains sparse, so mid-section centering is still constrained.")
    elif correction_ratio < 0.5:
        findings.append("Centerline correction coverage is limited; a large share of rows still follow trajectory trend with weak center compensation.")
    else:
        findings.append("Centerline correction coverage looks broadly active, and the remaining centering gap is more about hint quality/strength than feature enablement.")

    if tangent_ratio < 0.5:
        findings.append("Endpoint tangent continuity is not widely active in this scope, so endpoint naturalness likely still depends on the raw fitted spine.")
    elif max(src_tangent_error_mean, dst_tangent_error_mean) > 20.0:
        dominant_side = "src" if src_tangent_error_mean >= dst_tangent_error_mean else "dst"
        findings.append(f"Endpoint tangent continuity is enabled, but {dominant_side}-side tangent mismatch is still the dominant residual issue.")
    else:
        findings.append("Endpoint tangent continuity looks broadly active, and only low-grade endpoint residuals should remain.")

    if corrected_quality_mean + 0.05 < trajectory_quality_mean:
        findings.append("The corrected spine quality is noticeably below the original trajectory spine quality, which suggests center correction is still over-constraining some rows.")
    elif corrected_quality_mean > trajectory_quality_mean + 0.05:
        findings.append("The corrected spine quality is measurably stronger than the original trajectory spine quality, so centerline-aware correction is adding useful structure.")

    if fallback_count > 0:
        findings.append("Fallback still appears in this scope; inspect the top suspicious rows first instead of reading all rows.")
    if built_false_count > 0:
        findings.append("There are rows with built_final_road=false; these should be isolated before judging geometry quality.")
    return findings


def _build_summary(
    rows: list[dict[str, Any]],
    *,
    requested_patch_id: str,
    requested_pairs: list[str],
    bucket_limit: int,
    top_k: int,
    low_spine_quality: float,
    low_lane_hint_usage: float,
    high_tangent_error_deg: float,
    high_target_offset_m: float,
    high_endpoint_offset_m: float,
) -> dict[str, Any]:
    row_count = int(len(rows))
    built_false_rows = [row for row in rows if not bool(row.get("built_final_road", False))]
    global_fit_not_used_rows = [row for row in rows if not bool(row.get("global_fit_used_bool", False))]
    fallback_rows = [row for row in rows if str(row.get("fallback_reason", "") or "")]
    quality_gate_rows = [row for row in rows if str(row.get("quality_gate_reason", "") or "")]
    low_corrected_spine_rows = [
        row for row in rows if _safe_float(row.get("center_corrected_spine_quality"), 0.0) < low_spine_quality
    ]
    low_lane_hint_rows = [row for row in rows if _lane_hint_usage_ratio(row) < low_lane_hint_usage]
    high_tangent_error_rows = [
        row
        for row in rows
        if (
            _fit_metric(row, "src_tangent_error_deg") > high_tangent_error_deg
            or _fit_metric(row, "dst_tangent_error_deg") > high_tangent_error_deg
        )
    ]
    high_target_offset_rows = [row for row in rows if _fit_metric(row, "mean_target_offset_m") > high_target_offset_m]
    high_endpoint_offset_rows = [
        row for row in rows if _fit_metric(row, "endpoint_neighborhood_offset_m") > high_endpoint_offset_m
    ]

    overview = {
        "row_count": row_count,
        "built_count": int(sum(1 for row in rows if bool(row.get("built_final_road", False)))),
        "built_false_count": int(len(built_false_rows)),
        "global_fit_used_count": int(sum(1 for row in rows if bool(row.get("global_fit_used_bool", False)))),
        "global_fit_not_used_count": int(len(global_fit_not_used_rows)),
        "global_fit_success_count": int(sum(1 for row in rows if bool(row.get("global_fitting_success_bool", False)))),
        "global_fit_failed_count": int(sum(1 for row in rows if not bool(row.get("global_fitting_success_bool", False)))),
        "final_export_is_fitted_count": int(sum(1 for row in rows if bool(row.get("fitted_line_is_final_export", False)))),
        "fallback_count": int(len(fallback_rows)),
        "quality_gate_count": int(len(quality_gate_rows)),
        "centerline_correction_enabled_count": int(
            sum(1 for row in rows if bool(row.get("centerline_correction_enabled_bool", False)))
        ),
        "endpoint_tangent_enabled_count": int(
            sum(1 for row in rows if bool(row.get("endpoint_tangent_continuity_enabled_bool", False)))
        ),
    }
    overview["built_ratio"] = float(overview["built_count"] / row_count) if row_count else 0.0
    overview["global_fit_final_export_ratio"] = (
        float(overview["final_export_is_fitted_count"] / row_count) if row_count else 0.0
    )
    overview["centerline_correction_enabled_ratio"] = (
        float(overview["centerline_correction_enabled_count"] / row_count) if row_count else 0.0
    )
    overview["endpoint_tangent_enabled_ratio"] = (
        float(overview["endpoint_tangent_enabled_count"] / row_count) if row_count else 0.0
    )

    quality_summary = {
        "trajectory_spine_quality": _metric_stats([_safe_float(row.get("trajectory_spine_quality"), 0.0) for row in rows]),
        "center_corrected_spine_quality": _metric_stats(
            [_safe_float(row.get("center_corrected_spine_quality"), 0.0) for row in rows]
        ),
        "lane_hint_usage_ratio": _metric_stats([_lane_hint_usage_ratio(row) for row in rows]),
        "center_correction_mean_m": _metric_stats([_correction_mean_m(row) for row in rows]),
        "center_correction_max_m": _metric_stats([_correction_max_m(row) for row in rows]),
        "src_tangent_confidence": _metric_stats([_tangent_confidence(row, "src_local_tangent") for row in rows]),
        "dst_tangent_confidence": _metric_stats([_tangent_confidence(row, "dst_local_tangent") for row in rows]),
        "src_tangent_error_deg": _metric_stats([_fit_metric(row, "src_tangent_error_deg") for row in rows]),
        "dst_tangent_error_deg": _metric_stats([_fit_metric(row, "dst_tangent_error_deg") for row in rows]),
        "mean_target_offset_m": _metric_stats([_fit_metric(row, "mean_target_offset_m") for row in rows]),
        "endpoint_neighborhood_offset_m": _metric_stats(
            [_fit_metric(row, "endpoint_neighborhood_offset_m") for row in rows]
        ),
    }

    histograms = {
        "final_export_source": _histogram([row.get("final_export_source", "") for row in rows]),
        "fallback_reason": _histogram([row.get("fallback_reason", "") for row in rows]),
        "quality_gate_reason": _histogram([row.get("quality_gate_reason", "") for row in rows]),
        "global_fitting_mode": _histogram([row.get("global_fitting_mode", "") for row in rows]),
        "trajectory_spine_source": _histogram([row.get("trajectory_spine_source", "") for row in rows]),
        "src_tangent_source": _histogram([_tangent_source(row, "src_local_tangent") for row in rows]),
        "dst_tangent_source": _histogram([_tangent_source(row, "dst_local_tangent") for row in rows]),
    }

    ranked_rows = []
    for row in rows:
        issues = _row_issue_flags(
            row,
            low_spine_quality=low_spine_quality,
            low_lane_hint_usage=low_lane_hint_usage,
            high_tangent_error_deg=high_tangent_error_deg,
            high_target_offset_m=high_target_offset_m,
            high_endpoint_offset_m=high_endpoint_offset_m,
        )
        score = _row_suspicion_score(
            row,
            low_spine_quality=low_spine_quality,
            low_lane_hint_usage=low_lane_hint_usage,
            high_tangent_error_deg=high_tangent_error_deg,
            high_target_offset_m=high_target_offset_m,
            high_endpoint_offset_m=high_endpoint_offset_m,
        )
        ranked_rows.append(
            {
                "patch_id": str(row.get("patch_id", "")),
                "pair": str(row.get("pair", "")),
                "arc_id": str(row.get("arc_id", "")),
                "suspicion_score": float(score),
                "issues": issues,
                "final_export_source": str(row.get("final_export_source", "")),
                "fallback_reason": str(row.get("fallback_reason", "")),
                "quality_gate_reason": str(row.get("quality_gate_reason", "")),
                "center_corrected_spine_quality": _safe_float(row.get("center_corrected_spine_quality"), 0.0),
                "lane_hint_usage_ratio": _lane_hint_usage_ratio(row),
                "src_tangent_error_deg": _fit_metric(row, "src_tangent_error_deg"),
                "dst_tangent_error_deg": _fit_metric(row, "dst_tangent_error_deg"),
                "mean_target_offset_m": _fit_metric(row, "mean_target_offset_m"),
                "endpoint_neighborhood_offset_m": _fit_metric(row, "endpoint_neighborhood_offset_m"),
            }
        )
    ranked_rows.sort(key=lambda item: (-float(item["suspicion_score"]), str(item["pair"]), str(item["arc_id"])))

    abstract_findings = _build_abstract_findings(
        row_count=row_count,
        overview=overview,
        quality_summary=quality_summary,
    )

    return {
        "scope": {
            "requested_patch_id": str(requested_patch_id),
            "requested_pairs": list(requested_pairs),
            "row_count": row_count,
        },
        "overview": overview,
        "abstract_findings": abstract_findings,
        "quality_summary": quality_summary,
        "histograms": histograms,
        "issue_buckets": {
            "built_false": _bucket(built_false_rows, limit=bucket_limit),
            "global_fit_not_used": _bucket(global_fit_not_used_rows, limit=bucket_limit),
            "fallback": _bucket(fallback_rows, limit=bucket_limit),
            "quality_gate": _bucket(quality_gate_rows, limit=bucket_limit),
            "low_corrected_spine_quality": _bucket(low_corrected_spine_rows, limit=bucket_limit),
            "low_lane_hint_usage": _bucket(low_lane_hint_rows, limit=bucket_limit),
            "high_tangent_error": _bucket(high_tangent_error_rows, limit=bucket_limit),
            "high_target_offset": _bucket(high_target_offset_rows, limit=bucket_limit),
            "high_endpoint_offset": _bucket(high_endpoint_offset_rows, limit=bucket_limit),
        },
        "top_suspicious_rows": ranked_rows[:top_k],
        "thresholds": {
            "low_spine_quality": float(low_spine_quality),
            "low_lane_hint_usage": float(low_lane_hint_usage),
            "high_tangent_error_deg": float(high_tangent_error_deg),
            "high_target_offset_m": float(high_target_offset_m),
            "high_endpoint_offset_m": float(high_endpoint_offset_m),
        },
    }


def _render_summary_text(payload: dict[str, Any]) -> str:
    summary = dict(payload.get("summary") or {})
    scope = dict(summary.get("scope") or {})
    overview = dict(summary.get("overview") or {})
    quality = dict(summary.get("quality_summary") or {})
    histograms = dict(summary.get("histograms") or {})
    buckets = dict(summary.get("issue_buckets") or {})
    lines = [
        f"Run: {payload.get('run_dir', '')}",
        f"Patch: {scope.get('requested_patch_id', '') or '<all>'}",
        f"Pairs: {', '.join(scope.get('requested_pairs', []) or []) or '<all>'}",
        f"Rows: {scope.get('row_count', 0)}",
        "",
        "Overview:",
        (
            "  built={built_count}/{row_count}, final_export_fitted={final_export_is_fitted_count}/{row_count}, "
            "global_fit_used={global_fit_used_count}/{row_count}, fallback={fallback_count}, quality_gate={quality_gate_count}"
        ).format(
            built_count=overview.get("built_count", 0),
            row_count=overview.get("row_count", 0),
            final_export_is_fitted_count=overview.get("final_export_is_fitted_count", 0),
            global_fit_used_count=overview.get("global_fit_used_count", 0),
            fallback_count=overview.get("fallback_count", 0),
            quality_gate_count=overview.get("quality_gate_count", 0),
        ),
        (
            "  centerline_correction={centerline_count}/{row_count}, endpoint_tangent={endpoint_count}/{row_count}"
        ).format(
            centerline_count=overview.get("centerline_correction_enabled_count", 0),
            row_count=overview.get("row_count", 0),
            endpoint_count=overview.get("endpoint_tangent_enabled_count", 0),
        ),
        "",
        "Abstract findings:",
    ]
    for item in list(summary.get("abstract_findings") or []):
        lines.append(f"  - {item}")
    lines.extend(
        [
            "",
            "Quality summary:",
            "  trajectory_spine_quality mean={:.3f} min={:.3f} max={:.3f}".format(
                _safe_float(dict(quality.get("trajectory_spine_quality") or {}).get("mean"), 0.0),
                _safe_float(dict(quality.get("trajectory_spine_quality") or {}).get("min"), 0.0),
                _safe_float(dict(quality.get("trajectory_spine_quality") or {}).get("max"), 0.0),
            ),
            "  corrected_spine_quality  mean={:.3f} min={:.3f} max={:.3f}".format(
                _safe_float(dict(quality.get("center_corrected_spine_quality") or {}).get("mean"), 0.0),
                _safe_float(dict(quality.get("center_corrected_spine_quality") or {}).get("min"), 0.0),
                _safe_float(dict(quality.get("center_corrected_spine_quality") or {}).get("max"), 0.0),
            ),
            "  lane_hint_usage_ratio    mean={:.3f}".format(
                _safe_float(dict(quality.get("lane_hint_usage_ratio") or {}).get("mean"), 0.0)
            ),
            "  correction_mean_m        mean={:.3f}".format(
                _safe_float(dict(quality.get("center_correction_mean_m") or {}).get("mean"), 0.0)
            ),
            "  src_tangent_error_deg    mean={:.3f}".format(
                _safe_float(dict(quality.get("src_tangent_error_deg") or {}).get("mean"), 0.0)
            ),
            "  dst_tangent_error_deg    mean={:.3f}".format(
                _safe_float(dict(quality.get("dst_tangent_error_deg") or {}).get("mean"), 0.0)
            ),
            "",
            "Histograms:",
            f"  final_export_source={json.dumps(histograms.get('final_export_source', {}), ensure_ascii=True)}",
            f"  fallback_reason={json.dumps(histograms.get('fallback_reason', {}), ensure_ascii=True)}",
            f"  quality_gate_reason={json.dumps(histograms.get('quality_gate_reason', {}), ensure_ascii=True)}",
            "",
            "Issue buckets:",
        ]
    )
    for key in [
        "built_false",
        "global_fit_not_used",
        "fallback",
        "quality_gate",
        "low_corrected_spine_quality",
        "low_lane_hint_usage",
        "high_tangent_error",
        "high_target_offset",
        "high_endpoint_offset",
    ]:
        bucket = dict(buckets.get(key) or {})
        example_pairs = [str(item.get("pair", "")) for item in list(bucket.get("examples") or []) if str(item.get("pair", ""))]
        lines.append(f"  {key}: count={bucket.get('count', 0)} examples={example_pairs}")
    lines.extend(["", "Top suspicious rows:"])
    for index, item in enumerate(list(summary.get("top_suspicious_rows") or []), start=1):
        lines.append(
            (
                "  {index}. pair={pair} score={score:.2f} issues={issues} "
                "source={source} corrected_q={corrected_q:.3f} lane_usage={lane_usage:.3f} "
                "src_err={src_err:.2f} dst_err={dst_err:.2f}"
            ).format(
                index=index,
                pair=item.get("pair", ""),
                score=_safe_float(item.get("suspicion_score"), 0.0),
                issues=",".join(item.get("issues", []) or []) or "<none>",
                source=item.get("final_export_source", ""),
                corrected_q=_safe_float(item.get("center_corrected_spine_quality"), 0.0),
                lane_usage=_safe_float(item.get("lane_hint_usage_ratio"), 0.0),
                src_err=_safe_float(item.get("src_tangent_error_deg"), 0.0),
                dst_err=_safe_float(item.get("dst_tangent_error_deg"), 0.0),
            )
        )
    simple_patch_summary = dict(payload.get("simple_patch_summary") or {})
    if simple_patch_summary:
        lines.extend(["", "Simple patch summary:"])
        for patch_id in sorted(simple_patch_summary):
            lines.append(f"  {patch_id}: {json.dumps(simple_patch_summary[patch_id], ensure_ascii=True)}")
    return "\n".join(lines) + "\n"


def _global_fit_payload(patch_dir: Path) -> dict[str, Any]:
    payload = _read_json(patch_dir / "step5_global_fit_v2_trace.json")
    if payload:
        return payload
    return _read_json(patch_dir / "step5_global_fit_trace.json")


def _merge_patch_rows(patch_dir: Path) -> list[dict[str, Any]]:
    global_fit_payload = _global_fit_payload(patch_dir)
    final_trace_payload = _read_json(patch_dir / "step5_final_geometry_trace.json")
    final_by_pair = {
        str(item.get("pair", "")): dict(item)
        for item in final_trace_payload.get("rows", [])
        if str(item.get("pair", ""))
    }
    rows: list[dict[str, Any]] = []
    for item in global_fit_payload.get("rows", []):
        pair = str(item.get("pair", ""))
        final_row = dict(final_by_pair.get(pair, {}))
        endpoint_tangent_trace = dict(item.get("endpoint_tangent_trace") or {})
        rows.append(
            {
                "patch_id": str(patch_dir.name),
                "segment_id": str(item.get("segment_id", "")),
                "pair": pair,
                "arc_id": str(item.get("arc_id", "")),
                "trajectory_spine_source": str(item.get("trajectory_spine_source", "")),
                "trajectory_spine_quality": float(item.get("trajectory_spine_quality", 0.0) or 0.0),
                "trajectory_spine_support_count": int(item.get("trajectory_spine_support_count", 0) or 0),
                "original_spine_coords": list(item.get("original_spine_coords") or []),
                "corrected_spine_coords": list(item.get("corrected_spine_coords") or []),
                "center_corrected_spine_quality": float(item.get("center_corrected_spine_quality", 0.0) or 0.0),
                "centerline_correction_enabled_bool": bool(item.get("centerline_correction_enabled_bool", False)),
                "centerline_correction_summary": dict(item.get("centerline_correction_summary") or {}),
                "lane_boundary_hint_usage": dict(item.get("lane_boundary_hint_usage") or {}),
                "src_local_tangent": dict(endpoint_tangent_trace.get("src") or {}),
                "dst_local_tangent": dict(endpoint_tangent_trace.get("dst") or {}),
                "endpoint_tangent_continuity_enabled_bool": bool(item.get("endpoint_tangent_continuity_enabled_bool", False)),
                "global_fitting_mode": str(item.get("fitting_mode", "")),
                "global_fitting_success_bool": bool(item.get("fitting_success_bool", False)),
                "global_fit_used_bool": bool(item.get("global_fit_used_bool", False)),
                "fitted_line_is_final_export": bool(final_row.get("global_fit_used_bool", False)),
                "final_export_source": str(final_row.get("final_export_source", item.get("final_export_source", ""))),
                "fit_metrics": dict(item.get("fit_metrics") or {}),
                "fallback_reason": str(item.get("fallback_reason", "") or final_row.get("global_fit_fallback_reason", "")),
                "quality_gate_reason": str(item.get("quality_gate_reason", "") or final_row.get("global_fit_quality_gate_reason", "")),
                "built_state": bool(item.get("built_final_road", final_row.get("built_final_road", False))),
                "built_final_road": bool(item.get("built_final_road", final_row.get("built_final_road", False))),
            }
        )
    return rows


def _simple_patch_summary(run_dir: Path) -> dict[str, Any]:
    per_patch: dict[str, dict[str, Any]] = {}
    for patch_id in sorted(SIMPLE_PATCH_IDS):
        patch_dir = run_dir / "patches" / patch_id
        trace_payload = _read_json(patch_dir / "step5_final_geometry_trace.json")
        global_fit_payload = _global_fit_payload(patch_dir)
        rows = list(trace_payload.get("rows", []))
        global_rows = list(global_fit_payload.get("rows", []))
        per_patch[patch_id] = {
            "row_count": int(len(rows)),
            "built_count": int(sum(1 for item in rows if bool(item.get("built_final_road", False)))),
            "global_fit_used_count": int(sum(1 for item in rows if bool(item.get("global_fit_used_bool", False)))),
            "global_fit_success_count": int(sum(1 for item in global_rows if bool(item.get("fitting_success_bool", False)))),
            "centerline_correction_enabled_count": int(
                sum(1 for item in global_rows if bool(item.get("centerline_correction_enabled_bool", False)))
            ),
            "endpoint_tangent_enabled_count": int(
                sum(1 for item in global_rows if bool(item.get("endpoint_tangent_continuity_enabled_bool", False)))
            ),
            "refine_applied_count": int(sum(1 for item in rows if bool(item.get("refine_applied_bool", False)))),
        }
    return per_patch


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t05_extract_global_fit_v2_trace")
    parser.add_argument("--run_dir", required=True, help="Run directory like outputs/_work/<RUN_ID>")
    parser.add_argument("--patch_id", default="", help="Optional patch id filter")
    parser.add_argument("--pairs", default="", help="Optional comma-separated pair ids: src:dst,src:dst")
    parser.add_argument("--summary_only", action="store_true", help="Emit only summary/abstract analysis without raw rows")
    parser.add_argument("--format", choices=("json", "text"), default="json", help="Output format")
    parser.add_argument("--top_k", type=int, default=8, help="Top suspicious rows to keep in summary")
    parser.add_argument("--bucket_limit", type=int, default=6, help="Example rows kept for each issue bucket")
    parser.add_argument("--low_spine_quality", type=float, default=0.65, help="Threshold for low corrected spine quality")
    parser.add_argument("--low_lane_hint_usage", type=float, default=0.25, help="Threshold for weak lane hint usage ratio")
    parser.add_argument("--high_tangent_error_deg", type=float, default=20.0, help="Threshold for high tangent error")
    parser.add_argument("--high_target_offset_m", type=float, default=2.0, help="Threshold for high target offset")
    parser.add_argument(
        "--high_endpoint_offset_m",
        type=float,
        default=1.5,
        help="Threshold for high endpoint neighborhood offset",
    )
    parser.add_argument("--output", default="", help="Optional JSON output path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_dir = Path(args.run_dir)
    target_pairs = set(_parse_pairs(args.pairs))
    target_patch_id = str(args.patch_id or "").strip()
    if not target_patch_id and not target_pairs:
        raise SystemExit("ERROR: at least one of --patch_id or --pairs is required")
    rows: list[dict[str, Any]] = []
    patch_dirs: list[Path]
    if target_patch_id:
        patch_dirs = [run_dir / "patches" / target_patch_id]
    else:
        patch_dirs = sorted((run_dir / "patches").glob("*"))
    for patch_dir in patch_dirs:
        if not patch_dir.is_dir():
            continue
        rows.extend(_merge_patch_rows(patch_dir))
    filtered = rows
    if target_pairs:
        filtered = [row for row in filtered if str(row.get("pair", "")) in target_pairs]
    requested_pairs = sorted(target_pairs)
    summary = _build_summary(
        filtered,
        requested_patch_id=target_patch_id,
        requested_pairs=requested_pairs,
        bucket_limit=max(1, int(args.bucket_limit)),
        top_k=max(1, int(args.top_k)),
        low_spine_quality=float(args.low_spine_quality),
        low_lane_hint_usage=float(args.low_lane_hint_usage),
        high_tangent_error_deg=float(args.high_tangent_error_deg),
        high_target_offset_m=float(args.high_target_offset_m),
        high_endpoint_offset_m=float(args.high_endpoint_offset_m),
    )
    payload = {
        "run_dir": str(run_dir),
        "requested_patch_id": str(target_patch_id),
        "requested_pairs": requested_pairs,
        "row_count": int(len(filtered)),
        "summary": summary,
        "simple_patch_summary": _simple_patch_summary(run_dir),
    }
    if not bool(args.summary_only):
        payload["rows"] = filtered
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if args.format == "text":
            output_path.write_text(_render_summary_text(payload), encoding="utf-8")
        else:
            output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    if args.format == "text":
        print(_render_summary_text(payload), end="")
    else:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
