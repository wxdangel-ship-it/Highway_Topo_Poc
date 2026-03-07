from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


_BUNDLE_MAX_LINES = 120
_BUNDLE_MAX_BYTES = 8 * 1024
_DEBUG_DIR_NAMES = ("debug", "step1", "step2", "step3", "step4")
_SUMMARY_KEY_PREFIXES = (
    "run_id:",
    "git_sha:",
    "patch_id:",
    "overall_pass:",
    "lane_boundary:",
    "Step0:",
    "road_count:",
    "road_features_count:",
    "road_candidate_count:",
    "pair_count:",
    "same_pair_multi_road_pair_count:",
    "same_pair_multi_road_output_count:",
    "no_geometry_candidate:",
    "no_geometry_candidate_count:",
    "hard_anomaly_count:",
    "soft_issue_count:",
)
_STEP1_REASON_KEYS = (
    "CROSS_DISTANCE_GATE_REJECT",
    "UNRESOLVED_NEIGHBOR",
    "NO_ADJACENT_PAIR_AFTER_PASS2",
    "MULTI_CHAIN_SAME_DST",
    "NO_STRATEGY_MERGE_TO_DIVERGE",
    "MULTI_NEIGHBOR_FOR_NODE",
    "MULTI_CORRIDOR",
)
_STEP23_REASON_KEYS = (
    "ROAD_OUTSIDE_TRAJ_SURFACE",
    "ROAD_OUTSIDE_DRIVEZONE",
    "ROAD_OUTSIDE_SEGMENT_CORRIDOR",
    "ROAD_INTERSECTS_DIVSTRIP",
    "BRIDGE_SEGMENT_TOO_LONG",
    "ENDPOINT_OFF_XSEC_ROAD",
    "ENDPOINT_NOT_ON_XSEC",
    "CENTER_ESTIMATE_EMPTY",
    "TRAJ_SURFACE_INSUFFICIENT",
    "TRAJ_SURFACE_GAP",
    "SPARSE_SURFACE_POINTS",
    "NO_LB_CONTINUOUS",
)
_EVIDENCE_MODE_VALUES = ("code_only", "code_plus_paste", "code_plus_run", "mixed")
_AUDIT_TRIGGER_VALUES = ("code_change", "regression_report", "business_rule_check", "run_bundle_followup")
_EVIDENCE_TYPE_ORDER = {
    "code_ref": 0,
    "diff_ref": 1,
    "rule_ref": 2,
    "pasted_text": 3,
    "inner_bundle": 4,
    "prior_report": 5,
}


@dataclass(frozen=True)
class QAArtifactResult:
    bundle_path: Path | None
    external_dir: Path | None


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _clean_line(value: Any, *, default: str = "NA") -> str:
    text = str(value or "").strip()
    if not text:
        return default
    return " ".join(text.split())


def _sanitize_topic(topic: str | None) -> str:
    text = _clean_line(topic, default="")
    if not text:
        return ""
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^A-Za-z0-9._-]", "_", text)
    return text.strip("._-")


def _truncate_lines(lines: list[str]) -> tuple[list[str], bool, str]:
    truncated = False
    reason = "na"
    reserve = 2
    content = list(lines)
    if len(content) > (_BUNDLE_MAX_LINES - reserve):
        content = content[: _BUNDLE_MAX_LINES - reserve]
        truncated = True
        reason = "line_limit"

    footer = [
        f"truncated: {'true' if truncated else 'false'}",
        f"truncate_reason: {reason}",
    ]
    while content:
        candidate = "\n".join([*content, *footer]).rstrip("\n") + "\n"
        if len(candidate.encode("utf-8")) <= _BUNDLE_MAX_BYTES:
            return [*content, *footer], truncated, reason
        content = content[:-1]
        truncated = True
        reason = "byte_limit"
        footer = [
            f"truncated: {'true' if truncated else 'false'}",
            f"truncate_reason: {reason}",
        ]
    return footer, True, "byte_limit"


def _selected_metrics(metrics_payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "patch_id",
        "road_count",
        "road_features_count",
        "road_candidate_count",
        "pair_count",
        "no_geometry_candidate",
        "no_geometry_candidate_count",
        "unique_pair_count",
        "same_pair_multi_road_pair_count",
        "same_pair_multi_road_output_count",
        "hard_anomaly_count",
        "soft_issue_count",
        "avg_conf",
        "p10_conf",
        "p50_conf",
        "center_coverage_avg",
        "endpoint_center_offset_p50",
        "endpoint_center_offset_p90",
        "endpoint_center_offset_max",
        "params_digest",
        "runtime_exception",
        "error_type",
        "error_message",
    )
    return {key: metrics_payload.get(key) for key in keys if key in metrics_payload}


def _selected_gate(gate_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "overall_pass": bool(gate_payload.get("overall_pass", False)),
        "hard_breakpoint_count": int(len(list(gate_payload.get("hard_breakpoints", [])))),
        "soft_breakpoint_count": int(len(list(gate_payload.get("soft_breakpoints", [])))),
        "params_digest": gate_payload.get("params_digest"),
        "version": gate_payload.get("version"),
        "error_type": gate_payload.get("error_type"),
        "error_message": gate_payload.get("error_message"),
    }


def _reason_count(breakpoints: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for bp in breakpoints:
        reason = _clean_line(bp.get("reason"), default="NA")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _format_signal_line(keys: tuple[str, ...], counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={int(counts.get(key, 0))}" for key in keys)


def _topk_breakpoint_lines(label: str, breakpoints: list[dict[str, Any]], *, topk: int = 8) -> list[str]:
    lines = [f"{label}:"]
    if not breakpoints:
        lines.append("- (none)")
        return lines
    for bp in breakpoints[: max(1, int(topk))]:
        lines.append(
            "- reason={reason} road_id={road} src={src} dst={dst} hint={hint}".format(
                reason=_clean_line(bp.get("reason")),
                road=_clean_line(bp.get("road_id"), default="na"),
                src=_clean_line(bp.get("src_nodeid"), default="na"),
                dst=_clean_line(bp.get("dst_nodeid"), default="na"),
                hint=_clean_line(bp.get("hint"), default="NA"),
            )
        )
    return lines


def _summary_key_lines(summary_text: str) -> list[str]:
    lines = summary_text.splitlines()
    out: list[str] = []
    mode: str | None = None
    hard_count = 0
    soft_count = 0
    for line in lines:
        if line.startswith("params:"):
            break
        if mode is None and any(line.startswith(prefix) for prefix in _SUMMARY_KEY_PREFIXES):
            out.append(line)
            continue
        if line == "hard_breakpoints_topk:":
            mode = "hard"
            out.append(line)
            continue
        if line == "soft_breakpoints_topk:":
            mode = "soft"
            out.append(line)
            continue
        if mode == "hard":
            if not line.startswith("- "):
                mode = None
                continue
            if hard_count < 3:
                out.append(line)
            hard_count += 1
            continue
        if mode == "soft":
            if not line.startswith("- "):
                mode = None
                continue
            if soft_count < 3:
                out.append(line)
            soft_count += 1
            continue
    return out[:20]


def _find_first(patterns: tuple[str, ...], *, base_dir: Path) -> bool:
    for pattern in patterns:
        if any(base_dir.glob(pattern)):
            return True
    return False


def _infer_input_snapshot(*, data_patch_dir: Path, metrics_payload: dict[str, Any]) -> dict[str, str]:
    vector_dir = data_patch_dir / "Vector"
    traj_dir = data_patch_dir / "Traj"
    pointcloud_dir = data_patch_dir / "PointCloud"
    lane_method = _clean_line(metrics_payload.get("lane_boundary_crs_method"), default="unknown")
    lane_inferred = bool(metrics_payload.get("lane_boundary_crs_inferred", False))
    lane_used = bool(metrics_payload.get("lane_boundary_used", False))
    pointcloud_enabled = bool(metrics_payload.get("pointcloud_enabled", False))

    lane_status = "missing"
    if (vector_dir / "LaneBoundary.geojson").is_file():
        if lane_method == "skipped":
            lane_status = "skipped"
        elif lane_inferred or lane_method not in {"ok", "unknown"}:
            lane_status = "crs_missing_fixed"
        elif lane_used:
            lane_status = "ok"
        else:
            lane_status = "ok"

    pointcloud_file_present = _find_first(("*.las", "*.laz", "*.pcd", "*.ply"), base_dir=pointcloud_dir)
    if pointcloud_enabled and pointcloud_file_present:
        pointcloud_status = "ok"
    elif pointcloud_enabled:
        pointcloud_status = "missing"
    elif pointcloud_file_present:
        pointcloud_status = "skipped"
    else:
        pointcloud_status = "skipped"

    actual_crs = _clean_line(
        metrics_payload.get("lane_boundary_crs_name_final")
        or metrics_payload.get("drivezone_src_crs")
        or metrics_payload.get("intersection_src_crs"),
        default="unknown",
    )
    return {
        "required_DriveZone": "ok" if (vector_dir / "DriveZone.geojson").is_file() else "missing",
        "required_intersection_l": "ok" if (vector_dir / "intersection_l.geojson").is_file() else "missing",
        "required_Traj": "ok" if _find_first(("**/raw_dat_pose.geojson",), base_dir=traj_dir) else "missing",
        "optional_LaneBoundary": lane_status,
        "optional_DivStripZone": "ok" if (vector_dir / "DivStripZone.geojson").is_file() else "missing",
        "optional_Node_or_RCSDNode": (
            "ok"
            if (vector_dir / "RCSDNode.geojson").is_file() or (vector_dir / "Node.geojson").is_file()
            else "missing"
        ),
        "optional_PointCloud": pointcloud_status,
        "crs_expected": "EPSG:3857",
        "crs_actual": actual_crs,
    }


def _collect_debug_files(patch_out_dir: Path, *, max_items: int = 20) -> list[str]:
    files: list[str] = []
    for dirname in _DEBUG_DIR_NAMES:
        root = patch_out_dir / dirname
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            files.append(path.relative_to(patch_out_dir).as_posix())
            if len(files) >= max_items:
                return files
    return files


def _infer_runtime_result(
    *,
    metrics_payload: dict[str, Any],
    gate_payload: dict[str, Any],
    runtime_exception_type: str | None,
) -> str:
    if runtime_exception_type:
        return "fail"
    if bool(gate_payload.get("overall_pass", False)):
        return "pass"
    road_count = int(metrics_payload.get("road_count") or 0)
    road_features_count = int(metrics_payload.get("road_features_count") or road_count)
    if road_count > 0 or road_features_count > 0:
        return "partial"
    return "fail"


def _build_execution_conclusion(
    *,
    metrics_payload: dict[str, Any],
    gate_payload: dict[str, Any],
    runtime_exception_type: str | None,
) -> str:
    if runtime_exception_type:
        return (
            f"Execution failed with {runtime_exception_type}; minimal summary/metrics/gate were emitted for QA follow-up."
        )
    road_count = int(metrics_payload.get("road_count") or 0)
    road_features_count = int(metrics_payload.get("road_features_count") or road_count)
    no_geometry = bool(metrics_payload.get("no_geometry_candidate", False))
    hard_breakpoints = list(gate_payload.get("hard_breakpoints", []))
    if bool(gate_payload.get("overall_pass", False)):
        return "Execution passed; primary outputs and gate are consistent and ready for QA review."
    if road_count != road_features_count:
        return (
            "Execution has an output consistency risk: road_count={road_count} but road_features_count={road_features_count}."
        ).format(road_count=road_count, road_features_count=road_features_count)
    if no_geometry:
        return "Execution produced no_geometry_candidate; QA should inspect hard reasons and debug layers together."
    if hard_breakpoints:
        return "Execution failed; primary hard breakpoint is {reason}.".format(
            reason=_clean_line(hard_breakpoints[0].get("reason"), default="UNKNOWN_HARD")
        )
    return "Execution failed, but gate lacks an explanatory hard breakpoint and should be completed first."


def _parse_scalar_field(text: str, key: str) -> str | None:
    prefix = f"{key}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            value = line[len(prefix) :].strip()
            return value or None
    return None


def _parse_list_block(text: str, key: str) -> list[str]:
    lines = text.splitlines()
    header = f"{key}:"
    items: list[str] = []
    collecting = False
    for line in lines:
        if line.strip() == header:
            collecting = True
            continue
        if not collecting:
            continue
        if line.startswith("- "):
            value = line[2:].strip()
            if value:
                items.append(value)
            continue
        if line.strip():
            break
    return items


def _parse_name_block(text: str, key: str) -> list[str]:
    scalar = _clean_line(_parse_scalar_field(text, key), default="NA")
    if scalar not in {"", "NA"}:
        return [scalar]
    return [item for item in _parse_list_block(text, key) if item not in {"", "NA"}]


def _normalize_name_list(values: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        item = _clean_line(value, default="")
        if not item or item == "NA" or item in seen:
            continue
        cleaned.append(item)
        seen.add(item)
    return cleaned


def _normalize_evidence_item(item: dict[str, Any], *, git_sha: str) -> dict[str, str]:
    evidence_type = _clean_line(item.get("evidence_type"), default="code_ref")
    source = _clean_line(item.get("source"), default="NA")
    return {
        "evidence_type": evidence_type,
        "source": source,
        "related_git_sha": _clean_line(item.get("related_git_sha"), default=git_sha),
        "related_run_id": _clean_line(item.get("related_run_id")),
        "related_patch_id": _clean_line(item.get("related_patch_id")),
        "note": _clean_line(item.get("note")),
    }


def _parse_evidence_index(text: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    meta: dict[str, str] = {}
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("evidence_mode:"):
            meta["evidence_mode"] = _clean_line(line.split(":", 1)[1])
            continue
        if line.startswith("latest_inner_run_id:"):
            meta["latest_inner_run_id"] = _clean_line(line.split(":", 1)[1])
            continue
        if line.startswith("latest_inner_patch_id:"):
            meta["latest_inner_patch_id"] = _clean_line(line.split(":", 1)[1])
            continue
        if line.startswith("## evidence_"):
            if current:
                items.append(current)
            current = {}
            continue
        if current is None or not line.startswith("- "):
            continue
        key, _, value = line[2:].partition(":")
        key_text = _clean_line(key, default="")
        if not key_text:
            continue
        current[key_text] = _clean_line(value)
    if current:
        items.append(current)
    return meta, items


def _merge_evidence_items(existing: list[dict[str, str]], new_items: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    for item in [*existing, *new_items]:
        normalized = {
            "evidence_type": _clean_line(item.get("evidence_type"), default="code_ref"),
            "source": _clean_line(item.get("source")),
            "related_git_sha": _clean_line(item.get("related_git_sha")),
            "related_run_id": _clean_line(item.get("related_run_id")),
            "related_patch_id": _clean_line(item.get("related_patch_id")),
            "note": _clean_line(item.get("note")),
        }
        key = (
            normalized["evidence_type"],
            normalized["source"],
            normalized["related_git_sha"],
            normalized["related_run_id"],
            normalized["related_patch_id"],
        )
        if key not in merged:
            merged[key] = normalized
            continue
        if normalized["note"] != "NA":
            merged[key]["note"] = normalized["note"]
    return sorted(
        merged.values(),
        key=lambda item: (
            _EVIDENCE_TYPE_ORDER.get(item.get("evidence_type", "code_ref"), 99),
            item.get("source", ""),
            item.get("related_run_id", ""),
            item.get("related_patch_id", ""),
        ),
    )


def _infer_evidence_mode(items: list[dict[str, str]], explicit_mode: str | None, existing_mode: str | None = None) -> str:
    candidate = _clean_line(explicit_mode, default="")
    if candidate in _EVIDENCE_MODE_VALUES:
        return candidate
    existing = _clean_line(existing_mode, default="")
    if existing in _EVIDENCE_MODE_VALUES and not items:
        return existing
    evidence_types = {str(item.get("evidence_type", "")) for item in items}
    has_pasted = "pasted_text" in evidence_types
    has_run = "inner_bundle" in evidence_types
    if has_run and has_pasted:
        return "mixed"
    if has_run:
        return "code_plus_run"
    if has_pasted:
        return "code_plus_paste"
    return "code_only"


def _blocked_reason(scope_reason: str, question_to_qa: str, items: list[dict[str, str]]) -> str:
    if _clean_line(scope_reason) == "NA":
        return "missing_scope"
    if _clean_line(question_to_qa) == "NA":
        return "missing_question"
    if not items:
        return "missing_code_reference"
    return "none"


def _default_external_evidence(*, repo_root: Path, git_sha: str) -> list[dict[str, str]]:
    qa_audit_path = (
        repo_root / "src" / "highway_topo_poc" / "modules" / "t05_topology_between_rc" / "qa_audit.py"
    ).resolve()
    run_path = (repo_root / "src" / "highway_topo_poc" / "modules" / "t05_topology_between_rc" / "run.py").resolve()
    protocol_path = (repo_root / "modules" / "t05_topology_between_rc" / "audits" / "T05_DEV_QA_PROTOCOL.md").resolve()
    return [
        {
            "evidence_type": "code_ref",
            "source": qa_audit_path.as_posix(),
            "related_git_sha": git_sha,
            "related_run_id": "NA",
            "related_patch_id": "NA",
            "note": "external audit upsert entrypoint and status semantics",
        },
        {
            "evidence_type": "diff_ref",
            "source": run_path.as_posix(),
            "related_git_sha": git_sha,
            "related_run_id": "NA",
            "related_patch_id": "NA",
            "note": "run result to QA artifact bridge and failure fallback outputs",
        },
        {
            "evidence_type": "rule_ref",
            "source": protocol_path.as_posix(),
            "related_git_sha": git_sha,
            "related_run_id": "NA",
            "related_patch_id": "NA",
            "note": "T05 DEV-QA protocol and external-audit semantics",
        },
    ]


def _write_exec_bundle(
    *,
    data_patch_dir: Path,
    patch_out_dir: Path,
    run_id: str,
    patch_id: str,
    git_sha: str,
    visual_verdict: str,
    execution_goal: str,
    focus_question: str,
    previous_git_sha: str | None,
    previous_audit_topic: str | None,
    previous_priority: str | None,
    action_taken: str | None,
    runtime_exception_type: str | None,
    runtime_exception_summary: str | None,
) -> Path:
    summary_path = patch_out_dir / "summary.txt"
    metrics_path = patch_out_dir / "metrics.json"
    gate_path = patch_out_dir / "gate.json"
    summary_text = _safe_read_text(summary_path)
    metrics_payload = _safe_read_json(metrics_path)
    gate_payload = _safe_read_json(gate_path)
    hard_breakpoints = list(gate_payload.get("hard_breakpoints", []))
    soft_breakpoints = list(gate_payload.get("soft_breakpoints", []))
    reason_counts = _reason_count([*hard_breakpoints, *soft_breakpoints])
    input_snapshot = _infer_input_snapshot(data_patch_dir=data_patch_dir, metrics_payload=metrics_payload)
    debug_files = _collect_debug_files(patch_out_dir)
    runtime_result = _infer_runtime_result(
        metrics_payload=metrics_payload,
        gate_payload=gate_payload,
        runtime_exception_type=runtime_exception_type,
    )
    lines = [
        "# T05_EXEC_AUDIT_BUNDLE",
        f"run_id: {run_id}",
        f"patch_id: {patch_id}",
        f"git_sha: {git_sha}",
        f"bundle_time: {_now_iso()}",
        f"visual_verdict: {_clean_line(visual_verdict)}",
        f"execution_goal: {_clean_line(execution_goal, default='formal_diagnostic_run')}",
        f"runtime_result: {runtime_result}",
        f"focus_question: {_clean_line(focus_question)}",
        f"previous_git_sha: {_clean_line(previous_git_sha)}",
        f"previous_audit_topic: {_clean_line(previous_audit_topic)}",
        f"previous_priority: {_clean_line(previous_priority)}",
        f"action_taken: {_clean_line(action_taken)}",
        "",
        "input_status_snapshot:",
        f"- required_inputs: DriveZone={input_snapshot['required_DriveZone']}, intersection_l={input_snapshot['required_intersection_l']}, Traj={input_snapshot['required_Traj']}",
        f"- optional_inputs: LaneBoundary={input_snapshot['optional_LaneBoundary']}, DivStripZone={input_snapshot['optional_DivStripZone']}, Node_or_RCSDNode={input_snapshot['optional_Node_or_RCSDNode']}, PointCloud={input_snapshot['optional_PointCloud']}",
        f"- crs_status: expected={input_snapshot['crs_expected']}, actual={input_snapshot['crs_actual']}",
        "- runtime_exception: has_exception={has_exc}, exception_type={exc_type}, exception_summary={exc_summary}".format(
            has_exc=str(bool(runtime_exception_type)).lower(),
            exc_type=_clean_line(runtime_exception_type),
            exc_summary=_clean_line(runtime_exception_summary),
        ),
        "",
        "summary_key_excerpt:",
        *[f"- {line}" for line in _summary_key_lines(summary_text)],
        "",
        f"metrics_key_fields: {json.dumps(_selected_metrics(metrics_payload), ensure_ascii=True, sort_keys=True)}",
        f"gate_key_fields: {json.dumps(_selected_gate(gate_payload), ensure_ascii=True, sort_keys=True)}",
        f"step1_signals: {_format_signal_line(_STEP1_REASON_KEYS, reason_counts)}",
        f"step2_3_signals: {_format_signal_line(_STEP23_REASON_KEYS, reason_counts)}",
        "",
        *_topk_breakpoint_lines("hard_breakpoints_topk", hard_breakpoints),
        "",
        *_topk_breakpoint_lines("soft_breakpoints_topk", soft_breakpoints),
        "",
        "key_debug_files:",
    ]
    if debug_files:
        lines.extend(f"- {item}" for item in debug_files)
    else:
        lines.append("- (none)")
    lines.extend(
        [
            "",
            "execution_conclusion:",
            _build_execution_conclusion(
                metrics_payload=metrics_payload,
                gate_payload=gate_payload,
                runtime_exception_type=runtime_exception_type,
            ),
        ]
    )
    final_lines, _, _ = _truncate_lines(lines)
    qa_inner_dir = patch_out_dir / "qa_inner"
    qa_inner_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = qa_inner_dir / f"T05_EXEC_AUDIT_BUNDLE__{run_id}__{patch_id}.md"
    bundle_path.write_text("\n".join(final_lines).rstrip("\n") + "\n", encoding="utf-8")
    return bundle_path


def upsert_external_audit_topic(
    *,
    repo_root: Path,
    git_sha: str,
    audit_topic: str,
    scope_reason: str,
    question_to_qa: str,
    audit_trigger: str = "code_change",
    static_audit_allowed: bool = True,
    target_runs: list[str] | None = None,
    target_patches: list[str] | None = None,
    evidence_items: list[dict[str, Any]] | None = None,
    evidence_mode: str | None = None,
    latest_inner_run_id: str | None = None,
    latest_inner_patch_id: str | None = None,
    qa_blocked_reason: str | None = None,
) -> Path:
    topic = _sanitize_topic(audit_topic)
    external_dir = (
        repo_root
        / "outputs"
        / "_qa_external"
        / "t05_topology_between_rc"
        / "by_version"
        / git_sha
        / topic
    )
    external_dir.mkdir(parents=True, exist_ok=True)

    scope_path = external_dir / "AUDIT_SCOPE.md"
    scope_text = _safe_read_text(scope_path)
    existing_target_runs = _parse_name_block(scope_text, "target_runs")
    existing_target_patches = _parse_name_block(scope_text, "target_patches")
    scope_reason_value = _clean_line(scope_reason)
    if scope_reason_value == "NA":
        scope_reason_value = _clean_line(_parse_scalar_field(scope_text, "scope_reason"))
    question_to_qa_value = _clean_line(question_to_qa)
    if question_to_qa_value == "NA":
        question_to_qa_value = _clean_line(_parse_scalar_field(scope_text, "question_to_qa"))
    audit_trigger_value = _clean_line(audit_trigger, default="code_change")
    if audit_trigger_value not in _AUDIT_TRIGGER_VALUES:
        audit_trigger_value = _clean_line(_parse_scalar_field(scope_text, "audit_trigger"), default="code_change")
    static_allowed_text = _clean_line(
        _parse_scalar_field(scope_text, "static_audit_allowed"),
        default="true" if bool(static_audit_allowed) else "false",
    ).lower()
    static_allowed_value = static_allowed_text in {"1", "true", "yes"}
    merged_target_runs = _normalize_name_list([*existing_target_runs, *list(target_runs or [])])
    merged_target_patches = _normalize_name_list([*existing_target_patches, *list(target_patches or [])])
    scope_lines = [
        "# T05 Version Audit Scope",
        f"git_sha: {git_sha}",
        f"audit_topic: {topic}",
        f"scope_reason: {scope_reason_value}",
        f"audit_trigger: {audit_trigger_value}",
        f"question_to_qa: {question_to_qa_value}",
        f"static_audit_allowed: {'true' if static_allowed_value else 'false'}",
    ]
    if merged_target_runs:
        scope_lines.extend(["target_runs:", *[f"- {item}" for item in merged_target_runs]])
    else:
        scope_lines.append("target_runs: NA")
    if merged_target_patches:
        scope_lines.extend(["target_patches:", *[f"- {item}" for item in merged_target_patches]])
    else:
        scope_lines.append("target_patches: NA")
    scope_path.write_text("\n".join(scope_lines).rstrip("\n") + "\n", encoding="utf-8")

    evidence_path = external_dir / "EVIDENCE_INDEX.md"
    evidence_text = _safe_read_text(evidence_path)
    evidence_meta, existing_items = _parse_evidence_index(evidence_text)
    normalized_items = [
        _normalize_evidence_item(item, git_sha=git_sha)
        for item in list(evidence_items or [])
        if _clean_line(item.get("source"), default="") not in {"", "NA"}
    ]
    merged_items = _merge_evidence_items(existing_items, normalized_items)
    evidence_mode_value = _infer_evidence_mode(merged_items, evidence_mode, evidence_meta.get("evidence_mode"))
    latest_run_value = _clean_line(latest_inner_run_id)
    latest_patch_value = _clean_line(latest_inner_patch_id)
    if latest_run_value == "NA":
        latest_run_value = _clean_line(evidence_meta.get("latest_inner_run_id"))
    if latest_patch_value == "NA":
        latest_patch_value = _clean_line(evidence_meta.get("latest_inner_patch_id"))
    evidence_lines = [
        "# T05 Evidence Index",
        f"evidence_mode: {evidence_mode_value}",
        f"latest_inner_run_id: {latest_run_value}",
        f"latest_inner_patch_id: {latest_patch_value}",
    ]
    for idx, item in enumerate(merged_items, start=1):
        evidence_lines.extend(
            [
                "",
                f"## evidence_{idx:03d}",
                f"- evidence_type: {item['evidence_type']}",
                f"- source: {item['source']}",
                f"- related_git_sha: {item['related_git_sha']}",
                f"- related_run_id: {item['related_run_id']}",
                f"- related_patch_id: {item['related_patch_id']}",
                f"- note: {item['note']}",
            ]
        )
    evidence_path.write_text("\n".join(evidence_lines).rstrip("\n") + "\n", encoding="utf-8")

    status_path = external_dir / "audit_status.json"
    existing_status = _safe_read_json(status_path)
    now_iso = _now_iso()
    blocked_reason = _clean_line(qa_blocked_reason, default="")
    if blocked_reason in {"", "NA"}:
        blocked_reason = _blocked_reason(scope_reason_value, question_to_qa_value, merged_items)
    qa_report_ready = bool(existing_status.get("qa_report_ready", False)) or (external_dir / "T05_VERSION_QA_REPORT.md").is_file()
    status_payload = {
        "git_sha": git_sha,
        "audit_topic": topic,
        "scope_ready": _clean_line(scope_reason_value) != "NA",
        "evidence_ready": blocked_reason == "none",
        "evidence_mode": evidence_mode_value,
        "qa_report_ready": qa_report_ready,
        "dev_acknowledged": bool(existing_status.get("dev_acknowledged", False)),
        "created_at": existing_status.get("created_at") or now_iso,
        "updated_at": now_iso,
        "latest_inner_run_id": latest_run_value,
        "latest_inner_patch_id": latest_patch_value,
        "qa_blocked_reason": blocked_reason,
    }
    status_path.write_text(json.dumps(status_payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return external_dir


def _acknowledge_previous_report(*, repo_root: Path, previous_git_sha: str | None, previous_audit_topic: str | None) -> None:
    prev_sha = _clean_line(previous_git_sha, default="")
    prev_topic = _sanitize_topic(previous_audit_topic)
    if not prev_sha or not prev_topic:
        return
    status_path = (
        repo_root
        / "outputs"
        / "_qa_external"
        / "t05_topology_between_rc"
        / "by_version"
        / prev_sha
        / prev_topic
        / "audit_status.json"
    )
    existing_status = _safe_read_json(status_path)
    if not existing_status:
        return
    existing_status["dev_acknowledged"] = True
    existing_status["updated_at"] = _now_iso()
    status_path.write_text(json.dumps(existing_status, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def emit_qa_artifacts(
    *,
    repo_root: Path,
    data_patch_dir: Path,
    patch_out_dir: Path,
    run_id: str,
    patch_id: str,
    git_sha: str,
    visual_verdict: str = "NA",
    execution_goal: str = "formal_diagnostic_run",
    focus_question: str = "NA",
    audit_topic: str | None = None,
    scope_reason: str = "NA",
    question_to_qa: str = "NA",
    previous_git_sha: str | None = None,
    previous_audit_topic: str | None = None,
    previous_priority: str | None = None,
    action_taken: str | None = None,
    runtime_exception_type: str | None = None,
    runtime_exception_summary: str | None = None,
) -> QAArtifactResult:
    summary_path = patch_out_dir / "summary.txt"
    metrics_path = patch_out_dir / "metrics.json"
    gate_path = patch_out_dir / "gate.json"
    if not summary_path.is_file() or not metrics_path.is_file() or not gate_path.is_file():
        return QAArtifactResult(bundle_path=None, external_dir=None)

    bundle_path = _write_exec_bundle(
        data_patch_dir=data_patch_dir,
        patch_out_dir=patch_out_dir,
        run_id=run_id,
        patch_id=patch_id,
        git_sha=git_sha,
        visual_verdict=visual_verdict,
        execution_goal=execution_goal,
        focus_question=focus_question,
        previous_git_sha=previous_git_sha,
        previous_audit_topic=previous_audit_topic,
        previous_priority=previous_priority,
        action_taken=action_taken,
        runtime_exception_type=runtime_exception_type,
        runtime_exception_summary=runtime_exception_summary,
    )

    _acknowledge_previous_report(
        repo_root=repo_root,
        previous_git_sha=previous_git_sha,
        previous_audit_topic=previous_audit_topic,
    )

    topic = _sanitize_topic(audit_topic)
    external_dir: Path | None = None
    if topic:
        evidence_items = [
            *_default_external_evidence(repo_root=repo_root, git_sha=git_sha),
            {
                "evidence_type": "inner_bundle",
                "source": bundle_path.as_posix(),
                "related_git_sha": git_sha,
                "related_run_id": run_id,
                "related_patch_id": patch_id,
                "note": f"visual_verdict={_clean_line(visual_verdict)}; debug_files={','.join(_collect_debug_files(patch_out_dir)) or '(none)'}",
            },
        ]
        external_dir = upsert_external_audit_topic(
            repo_root=repo_root,
            git_sha=git_sha,
            audit_topic=topic,
            scope_reason=scope_reason,
            question_to_qa=question_to_qa,
            audit_trigger="run_bundle_followup",
            static_audit_allowed=True,
            target_runs=[run_id],
            target_patches=[patch_id],
            evidence_items=evidence_items,
            evidence_mode=None,
            latest_inner_run_id=run_id,
            latest_inner_patch_id=patch_id,
            qa_blocked_reason="none",
        )
    return QAArtifactResult(bundle_path=bundle_path, external_dir=external_dir)


__all__ = ["QAArtifactResult", "emit_qa_artifacts", "upsert_external_audit_topic"]
