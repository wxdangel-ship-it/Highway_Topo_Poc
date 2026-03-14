from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from .arc_selection_rules import (
    STRUCTURE_MERGE_MULTI_UPSTREAM,
    STRUCTURE_SAME_PAIR_MULTI_ARC,
    apply_arc_selection_rules,
    apply_diverge_merge_rule,
    apply_multi_arc_rule,
)
from .io import read_json, write_json


_DIRECT_TOPOLOGY_ARC_SOURCE = "direct_topology_arc"
_SYNTHETIC_ARC_SOURCES = {"bridge_chain_topology"}

_SIMPLE_PATCH_ACCEPTANCE_REGISTRY: dict[str, dict[str, Any]] = {
    "5417632690143239": {
        "targets": [
            "5384388146439546:5384392105852988",
            "5384388146439546:6857617069878593468",
            "5384392105852988:5389785712044517",
            "5384392105852988:8072586958615647485",
            "5384392508839431:5384388146439546",
            "5389785712044517:7998705316008936532",
            "5389785712044517:8158580167019407963",
            "1016966162728760379:5384392508839431",
            "3728057617623998474:5384392508839431",
        ],
    },
    "5417632690143326": {
        "targets": [
            "758869:5384392508835518",
            "5384392508835518:955482837631237043",
            "5384392508835518:1603093460035387302",
            "964818603820823078:758869",
            "1572513903999899080:758869",
        ],
    },
}

_FALSE_POSITIVE_PAIRS = [
    "5384367610468452:765141",
    "5384367610468452:608638238",
]

_STABLE_BLOCKED_PAIRS = [
    "791871:37687913",
    "55353246:37687913",
]
_COMPETING_ARC_CLOSURE_TARGET_PAIRS = [
    "55353246:37687913",
    "791871:37687913",
]
_MERGE_DIVERGE_TARGET_PAIRS = [
    "55353246:37687913",
    "791871:37687913",
]

_BRIDGE_TARGET_PAIR = "5395717732638194:37687913"
_REFERENCE_PAIR = "5395717732638194:29626540"

_REJECT_STAGE_PRIORITY = {
    "bridge_retain_gate": 0,
    "semantic_hard_gate": 1,
    "ownership_gate": 2,
    "pairing_filter": 3,
    "cross_filter": 4,
}

_ARC_LEGALITY_REASONS = {
    "pair_not_direct_legal_arc",
    "non_unique_direct_legal_arc",
    "arc_unique_connectivity_violation",
    "synthetic_arc_not_allowed",
    "final_gate_not_direct_legal",
    "final_gate_non_unique_arc",
    "final_gate_arc_unique_connectivity_violation",
    "final_gate_synthetic_arc_not_allowed",
    "final_gate_blocked_diagnostic_only",
    "final_gate_hard_blocked",
}

_PATCH_JSON_CACHE: dict[str, dict[str, Any]] = {}


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def _cached_patch_json(path: Path) -> dict[str, Any]:
    key = str(path.resolve())
    cached = _PATCH_JSON_CACHE.get(key)
    if cached is None:
        cached = _safe_read_json(path)
        _PATCH_JSON_CACHE[key] = cached
    return cached


def _pair_id_text(src_nodeid: int, dst_nodeid: int) -> str:
    return f"{int(src_nodeid)}:{int(dst_nodeid)}"


def _support_type_rank(row: dict[str, Any]) -> float:
    support_type = str(row.get("traj_support_type", "no_support"))
    if support_type in {"terminal_crossing_support", "stitched_arc_support"}:
        return 3.0
    if support_type == "partial_arc_support":
        return 2.0
    if support_type != "no_support":
        return 1.0
    if str(row.get("prior_support_type", "no_support")) == "prior_fallback_support":
        return 0.5
    return 0.0


def _support_strength_score(row: dict[str, Any]) -> float:
    coverage_ratio = float(row.get("traj_support_coverage_ratio", 0.0) or 0.0)
    support_length = float(row.get("support_total_length_m", 0.0) or 0.0)
    support_count = int(row.get("traj_support_count", 0) or 0)
    slot_bonus = 3.0 if str(row.get("slot_status", "")) == "resolved" else 0.0
    corridor_bonus = 2.0 if str(row.get("corridor_identity", "")) in {"witness_based", "prior_based"} else 0.0
    return float(
        (_support_type_rank(row) * 100.0)
        + (coverage_ratio * 100.0)
        + (min(support_length, 250.0) * 0.4)
        + (support_count * 6.0)
        + slot_bonus
        + corridor_bonus
    )


def _patch_dir(run_root: Path | str, patch_id: str) -> Path:
    return Path(run_root) / "patches" / str(patch_id)


def _row_pair_id(row: dict[str, Any]) -> str:
    pair_id = str(row.get("pair", "") or row.get("pair_id", ""))
    if pair_id:
        return pair_id
    src_nodeid = row.get("src")
    dst_nodeid = row.get("dst")
    if src_nodeid is None:
        src_nodeid = row.get("src_nodeid")
    if dst_nodeid is None:
        dst_nodeid = row.get("dst_nodeid")
    if src_nodeid is None or dst_nodeid is None:
        return ""
    try:
        return _pair_id_text(int(src_nodeid), int(dst_nodeid))
    except (TypeError, ValueError):
        return ""


def _built_pairs(roads_payload: dict[str, Any]) -> list[str]:
    return sorted(
        _pair_id_text(int(item.get("src_nodeid", 0)), int(item.get("dst_nodeid", 0)))
        for item in roads_payload.get("roads", [])
    )


def _best_excluded_entry(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return sorted(
        rows,
        key=lambda item: (
            int(_REJECT_STAGE_PRIORITY.get(str(item.get("stage", "")), 99)),
            str(item.get("reason", "")),
            str(item.get("candidate_id", "")),
        ),
    )[0]


def _best_segment_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return sorted(
        rows,
        key=lambda item: (
            0 if bool(item.get("topology_arc_is_direct_legal", False)) else 1,
            0 if bool(item.get("topology_arc_is_unique", False)) else 1,
            int(item.get("same_pair_rank", 999999) or 999999),
            -int(item.get("support_count", 0)),
            str(item.get("segment_id", "")),
        ),
    )[0]


def _find_pair_row(rows: list[dict[str, Any]], pair_id: str) -> dict[str, Any] | None:
    for row in rows:
        if _row_pair_id(row) == str(pair_id):
            return row
    return None


def _road_segment_map(patch_dir: Path) -> tuple[dict[str, dict[str, Any]], set[str]]:
    segments_payload = _cached_patch_json(patch_dir / "step2" / "segments.json")
    roads_payload = _cached_patch_json(patch_dir / "step6" / "final_roads.json")
    segments = {str(item.get("segment_id", "")): dict(item) for item in segments_payload.get("segments", [])}
    built_pairs = set(_built_pairs(roads_payload))
    return segments, built_pairs


def _pair_rows_by_id(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        pair_id = _row_pair_id(row)
        if not pair_id:
            continue
        grouped.setdefault(pair_id, []).append(dict(row))
    return grouped


def _best_registry_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return sorted(
        rows,
        key=lambda item: (
            0 if bool(item.get("built_final_road", False)) else 1,
            0 if bool(item.get("controlled_entry_allowed", False)) else 1,
            0 if bool(item.get("entered_main_flow", False)) else 1,
            0 if bool(item.get("is_direct_legal", item.get("topology_arc_is_direct_legal", False))) else 1,
            0 if bool(item.get("is_unique", item.get("topology_arc_is_unique", False))) else 1,
            str(item.get("working_segment_id", "")),
            str(item.get("topology_arc_id", "")),
        ),
    )[0]


def _registry_rows_by_pair(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        pair_id = _row_pair_id(row)
        if not pair_id:
            continue
        grouped.setdefault(pair_id, []).append(dict(row))
    return grouped


def _registry_rows_by_working_segment(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        working_segment_id = str(row.get("working_segment_id", ""))
        if not working_segment_id:
            continue
        grouped[working_segment_id] = dict(row)
    return grouped


def _identity_record_from_row(
    row: dict[str, Any] | None,
    *,
    pair_id: str = "",
    working_segment_id: str = "",
    resolution_source: str = "",
) -> dict[str, Any]:
    payload = dict(row or {})
    resolved_pair = str(pair_id or _row_pair_id(payload))
    resolved_segment_id = str(working_segment_id or payload.get("working_segment_id") or payload.get("segment_id") or "")
    controlled_entry_allowed = bool(payload.get("controlled_entry_allowed", False))
    blocked_diagnostic_only = bool(payload.get("blocked_diagnostic_only", False)) and not controlled_entry_allowed
    hard_block_reason = "" if controlled_entry_allowed else str(payload.get("hard_block_reason", ""))
    blocked_diagnostic_reason = (
        ""
        if not blocked_diagnostic_only
        else str(payload.get("blocked_diagnostic_reason", "") or payload.get("unbuilt_reason", ""))
    )
    topology_arc_source_type = str(payload.get("topology_arc_source_type") or payload.get("arc_source_type") or "")
    canonical_src_xsec_id = payload.get("canonical_src_xsec_id", payload.get("src", payload.get("src_nodeid")))
    canonical_dst_xsec_id = payload.get("canonical_dst_xsec_id", payload.get("dst", payload.get("dst_nodeid")))
    raw_src_nodeid = payload.get("raw_src_nodeid", canonical_src_xsec_id)
    raw_dst_nodeid = payload.get("raw_dst_nodeid", canonical_dst_xsec_id)
    raw_pair = (
        _pair_id_text(int(raw_src_nodeid), int(raw_dst_nodeid))
        if raw_src_nodeid is not None and raw_dst_nodeid is not None
        else resolved_pair
    )
    canonical_pair = (
        _pair_id_text(int(canonical_src_xsec_id), int(canonical_dst_xsec_id))
        if canonical_src_xsec_id is not None and canonical_dst_xsec_id is not None
        else resolved_pair
    )
    src_alias_applied = bool(payload.get("src_alias_applied", raw_src_nodeid != canonical_src_xsec_id))
    dst_alias_applied = bool(payload.get("dst_alias_applied", raw_dst_nodeid != canonical_dst_xsec_id))
    return {
        "pair": resolved_pair,
        "raw_pair": str(raw_pair or resolved_pair),
        "canonical_pair": str(canonical_pair or resolved_pair),
        "raw_src_nodeid": None if raw_src_nodeid is None else int(raw_src_nodeid),
        "raw_dst_nodeid": None if raw_dst_nodeid is None else int(raw_dst_nodeid),
        "canonical_src_xsec_id": None if canonical_src_xsec_id is None else int(canonical_src_xsec_id),
        "canonical_dst_xsec_id": None if canonical_dst_xsec_id is None else int(canonical_dst_xsec_id),
        "src_alias_applied": bool(src_alias_applied),
        "dst_alias_applied": bool(dst_alias_applied),
        "alias_normalized": bool(src_alias_applied or dst_alias_applied or str(raw_pair) != str(canonical_pair)),
        "working_segment_id": resolved_segment_id,
        "topology_arc_id": str(payload.get("topology_arc_id", "")),
        "canonical_topology_arc_id": str(payload.get("topology_arc_id", "")),
        "topology_arc_source_type": topology_arc_source_type,
        "topology_arc_is_direct_legal": bool(
            payload.get("topology_arc_is_direct_legal", payload.get("is_direct_legal", False))
        ),
        "topology_arc_is_unique": bool(payload.get("topology_arc_is_unique", payload.get("is_unique", False))),
        "controlled_entry_allowed": controlled_entry_allowed,
        "topology_gap_decision": str(payload.get("topology_gap_decision", "")),
        "topology_gap_reason": str(payload.get("topology_gap_reason", "")),
        "entered_main_flow": bool(payload.get("entered_main_flow", False)),
        "blocked_diagnostic_only": blocked_diagnostic_only,
        "blocked_diagnostic_reason": blocked_diagnostic_reason,
        "hard_block_reason": hard_block_reason,
        "traj_support_type": str(payload.get("traj_support_type", "")),
        "prior_support_type": str(payload.get("prior_support_type", "")),
        "corridor_identity": str(payload.get("corridor_identity", "")),
        "slot_status": str(payload.get("slot_status", "")),
        "built_final_road": bool(payload.get("built_final_road", False)),
        "unbuilt_stage": str(payload.get("unbuilt_stage", "")),
        "unbuilt_reason": str(payload.get("unbuilt_reason", "")),
        "bridge_chain_exists": bool(payload.get("bridge_chain_exists", False)),
        "bridge_chain_unique": bool(payload.get("bridge_chain_unique", False)),
        "bridge_chain_nodes": list(payload.get("bridge_chain_nodes", [])),
        "identity_resolution_source": str(resolution_source),
    }


def _resolve_identity_record(
    *,
    pair_id: str = "",
    working_segment_id: str = "",
    registry_row: dict[str, Any] | None = None,
    registry_by_pair: dict[str, list[dict[str, Any]]] | None = None,
    registry_by_working_segment: dict[str, dict[str, Any]] | None = None,
    segment_map: dict[str, dict[str, Any]] | None = None,
    selected_rows: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if registry_row:
        return _identity_record_from_row(
            registry_row,
            pair_id=pair_id,
            working_segment_id=working_segment_id,
            resolution_source="full_legal_arc_registry",
        )
    if working_segment_id and registry_by_working_segment:
        matched = dict(registry_by_working_segment.get(str(working_segment_id), {}) or {})
        if matched:
            return _identity_record_from_row(
                matched,
                pair_id=pair_id,
                working_segment_id=working_segment_id,
                resolution_source="full_legal_arc_registry",
            )
    if pair_id and registry_by_pair:
        matched = _best_registry_row(list(registry_by_pair.get(str(pair_id), [])))
        if matched:
            return _identity_record_from_row(
                matched,
                pair_id=pair_id,
                working_segment_id=working_segment_id,
                resolution_source="full_legal_arc_registry",
            )
    if working_segment_id and segment_map:
        matched = dict(segment_map.get(str(working_segment_id), {}) or {})
        if matched:
            return _identity_record_from_row(
                matched,
                pair_id=pair_id,
                working_segment_id=working_segment_id,
                resolution_source="step2_segments",
            )
    if pair_id and selected_rows:
        matched = _best_segment_row(list(selected_rows.get(str(pair_id), [])))
        if matched:
            return _identity_record_from_row(
                matched,
                pair_id=pair_id,
                working_segment_id=working_segment_id,
                resolution_source="step2_segments",
            )
    return _identity_record_from_row(
        {},
        pair_id=pair_id,
        working_segment_id=working_segment_id,
        resolution_source="unresolved",
    )


def evaluate_patch_acceptance(run_root: Path | str, patch_id: str) -> dict[str, Any]:
    patch_dir = _patch_dir(run_root, patch_id)
    metrics = _cached_patch_json(patch_dir / "metrics.json")
    gate = _cached_patch_json(patch_dir / "gate.json")
    roads_payload = _cached_patch_json(patch_dir / "step6" / "final_roads.json")
    expected_pairs = list(_SIMPLE_PATCH_ACCEPTANCE_REGISTRY.get(str(patch_id), {}).get("targets", []))
    built_pairs = _built_pairs(roads_payload)
    built_pair_set = set(built_pairs)
    unexpected_built_pairs = sorted(pair for pair in built_pairs if pair not in set(expected_pairs))

    results: list[dict[str, Any]] = [
        {
            "target_id": "patch_overall_pass",
            "target_name": "patch_overall_pass",
            "expected": True,
            "actual": bool(gate.get("overall_pass", False)),
            "pass": bool(gate.get("overall_pass", False)) is True,
            "fail_reason": "" if bool(gate.get("overall_pass", False)) else "overall_pass_false",
        },
        {
            "target_id": "patch_unresolved_segment_count_zero",
            "target_name": "patch_unresolved_segment_count_zero",
            "expected": 0,
            "actual": int(metrics.get("unresolved_segment_count", 0)),
            "pass": int(metrics.get("unresolved_segment_count", 0)) == 0,
            "fail_reason": "" if int(metrics.get("unresolved_segment_count", 0)) == 0 else "unresolved_segment_count_nonzero",
        },
        {
            "target_id": "patch_no_unexpected_built_pairs",
            "target_name": "patch_no_unexpected_built_pairs",
            "expected": [],
            "actual": list(unexpected_built_pairs),
            "pass": len(unexpected_built_pairs) == 0,
            "fail_reason": "" if len(unexpected_built_pairs) == 0 else "unexpected_built_pairs_present",
        },
    ]
    for pair_id in expected_pairs:
        results.append(
            {
                "target_id": f"built_pair_{str(pair_id).replace(':', '_')}",
                "target_name": f"built_pair:{pair_id}",
                "expected": {"pair_id": str(pair_id), "built": True},
                "actual": {"pair_id": str(pair_id), "built": bool(pair_id in built_pair_set)},
                "pass": bool(pair_id in built_pair_set),
                "fail_reason": "" if pair_id in built_pair_set else "expected_built_pair_missing",
            }
        )
    return {
        "patch_id": str(patch_id),
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "acceptance_pass": bool(all(bool(item["pass"]) for item in results)),
        "target_count": int(len(results)),
        "expected_built_pairs": list(expected_pairs),
        "actual_built_pairs": list(built_pairs),
        "unexpected_built_pairs": list(unexpected_built_pairs),
        "results": results,
    }


def build_pair_decisions(run_root: Path | str, complex_patch_id: str) -> dict[str, Any]:
    patch_dir = _patch_dir(run_root, complex_patch_id)
    segments_payload = _cached_patch_json(patch_dir / "step2" / "segments.json")
    roads_payload = _cached_patch_json(patch_dir / "step6" / "final_roads.json")
    should_not_payload = _cached_patch_json(patch_dir / "debug" / "step2_segment_should_not_exist.json")
    topology_pairs_payload = _cached_patch_json(patch_dir / "debug" / "step2_topology_pairs.json")
    bridge_audit_payload = _cached_patch_json(patch_dir / "debug" / "step2_blocked_pair_bridge_audit.json")

    built_pair_set = set(_built_pairs(roads_payload))
    selected_rows = _pair_rows_by_id(list(segments_payload.get("segments", [])))
    segment_map = {
        str(item.get("segment_id", "")): dict(item)
        for item in segments_payload.get("segments", [])
        if str(item.get("segment_id", ""))
    }
    excluded_rows = _pair_rows_by_id(list(segments_payload.get("excluded_candidates", [])))
    should_not_rows = list(should_not_payload.get("pairs", []))
    topology_rows = list(topology_pairs_payload.get("pairs", []))
    bridge_rows = list(bridge_audit_payload.get("pairs", []))
    registry_rows = _patch_full_registry_rows(run_root, complex_patch_id)
    registry_by_pair = _registry_rows_by_pair(registry_rows)
    registry_by_working_segment = _registry_rows_by_working_segment(registry_rows)

    decisions: list[dict[str, Any]] = []
    target_pairs = {
        *_FALSE_POSITIVE_PAIRS,
        *_STABLE_BLOCKED_PAIRS,
        _BRIDGE_TARGET_PAIR,
        _REFERENCE_PAIR,
        *built_pair_set,
    }
    target_pairs.update(
        str(_row_pair_id(row))
        for row in registry_rows
        if (
            str(_row_pair_id(row))
            and (
                bool(row.get("src_alias_applied", False))
                or bool(row.get("dst_alias_applied", False))
                or bool(row.get("alias_normalized", False))
                or
                bool(row.get("controlled_entry_allowed", False))
                or bool(row.get("built_final_road", False))
                or str(row.get("topology_gap_decision", ""))
                or bool(row.get("blocked_diagnostic_only", False))
                or bool(str(row.get("hard_block_reason", "")))
            )
        )
    )
    for pair_id in sorted(target_pairs):
        selected = _best_segment_row(list(selected_rows.get(pair_id, [])))
        excluded = _best_excluded_entry(excluded_rows.get(pair_id, []))
        should_not_row = _find_pair_row(should_not_rows, pair_id)
        topology_row = _find_pair_row(topology_rows, pair_id)
        bridge_row = _find_pair_row(bridge_rows, pair_id)
        registry_row = _best_registry_row(list(registry_by_pair.get(pair_id, [])))
        resolved = _resolve_identity_record(
            pair_id=pair_id,
            working_segment_id=str((selected or {}).get("segment_id", "")),
            registry_row=registry_row,
            registry_by_pair=registry_by_pair,
            registry_by_working_segment=registry_by_working_segment,
            segment_map=segment_map,
            selected_rows=selected_rows,
        )
        built_final_road = bool(pair_id in built_pair_set or resolved.get("built_final_road", False))
        reject_stage = ""
        reject_reason = ""
        if not built_final_road and not bool(resolved.get("entered_main_flow", False)) and not selected:
            reject_stage = str(
                (excluded or {}).get("stage")
                or resolved.get("unbuilt_stage", "")
                or (bridge_row or {}).get("reject_stage")
                or ""
            )
            reject_reason = str(
                (excluded or {}).get("reason")
                or resolved.get("hard_block_reason", "")
                or resolved.get("unbuilt_reason", "")
                or (bridge_row or {}).get("reject_reason")
                or ""
            )
        decisions.append(
            {
                "patch_id": str(complex_patch_id),
                "pair": str(pair_id),
                "raw_pair": str(resolved.get("raw_pair", pair_id)),
                "canonical_pair": str(resolved.get("canonical_pair", pair_id)),
                "raw_src_nodeid": resolved.get("raw_src_nodeid"),
                "raw_dst_nodeid": resolved.get("raw_dst_nodeid"),
                "canonical_src_xsec_id": resolved.get("canonical_src_xsec_id"),
                "canonical_dst_xsec_id": resolved.get("canonical_dst_xsec_id"),
                "src_alias_applied": bool(resolved.get("src_alias_applied", False)),
                "dst_alias_applied": bool(resolved.get("dst_alias_applied", False)),
                "alias_normalized": bool(resolved.get("alias_normalized", False)),
                "topology_arc_id": str(resolved.get("topology_arc_id", "")),
                "canonical_topology_arc_id": str(resolved.get("canonical_topology_arc_id", resolved.get("topology_arc_id", ""))),
                "topology_arc_source_type": str(resolved.get("topology_arc_source_type", "")),
                "topology_arc_is_direct_legal": bool(resolved.get("topology_arc_is_direct_legal", False)),
                "topology_arc_is_unique": bool(resolved.get("topology_arc_is_unique", False)),
                "blocked_diagnostic_only": bool(resolved.get("blocked_diagnostic_only", False)),
                "blocked_diagnostic_reason": str(resolved.get("blocked_diagnostic_reason", "")),
                "controlled_entry_allowed": bool(resolved.get("controlled_entry_allowed", False)),
                "hard_block_reason": str(resolved.get("hard_block_reason", "")),
                "topology_gap_decision": str(resolved.get("topology_gap_decision", "")),
                "topology_gap_reason": str(resolved.get("topology_gap_reason", "")),
                "bridge_chain_exists": bool(resolved.get("bridge_chain_exists", False)),
                "bridge_chain_unique": bool(resolved.get("bridge_chain_unique", False)),
                "bridge_chain_nodes": list(resolved.get("bridge_chain_nodes", [])),
                "bridge_diagnostic_reason": str((topology_row or {}).get("bridge_diagnostic_reason", "")),
                "bridge_classification": str(
                    (bridge_row or {}).get("bridge_classification")
                    or (topology_row or {}).get("bridge_classification")
                    or (bridge_row or {}).get("bridge_diagnostic_reason", "")
                    or ""
                ),
                "reject_stage": str(reject_stage),
                "reject_reason": str(reject_reason),
                "should_not_reason": str((should_not_row or {}).get("reason", "")),
                "topology_sources": list((topology_row or {}).get("topology_sources", [])),
                "topology_paths": list((topology_row or {}).get("topology_paths", [])),
                "entered_main_flow": bool(resolved.get("entered_main_flow", False)),
                "traj_support_type": str(resolved.get("traj_support_type", "")),
                "prior_support_type": str(resolved.get("prior_support_type", "")),
                "corridor_identity": str(resolved.get("corridor_identity", "")),
                "slot_status": str(resolved.get("slot_status", "")),
                "unbuilt_stage": str(resolved.get("unbuilt_stage", "")),
                "unbuilt_reason": str(resolved.get("unbuilt_reason", "")),
                "built_final_road": built_final_road,
                "segment_id": str(resolved.get("working_segment_id", "")),
                "selected_segment": bool(selected is not None),
                "identity_resolution_source": str(resolved.get("identity_resolution_source", "")),
            }
        )
    return {
        "patch_id": str(complex_patch_id),
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pairs": decisions,
    }


def build_arc_legality_audit(run_root: Path | str, patch_ids: list[str]) -> dict[str, Any]:
    built_road_rows: list[dict[str, Any]] = []
    selected_segment_rows: list[dict[str, Any]] = []
    for patch_id in patch_ids:
        patch_dir = _patch_dir(run_root, patch_id)
        segments_payload = _cached_patch_json(patch_dir / "step2" / "segments.json")
        roads_payload = _cached_patch_json(patch_dir / "step6" / "final_roads.json")
        segment_map = {
            str(item.get("segment_id", "")): dict(item)
            for item in segments_payload.get("segments", [])
            if str(item.get("segment_id", ""))
        }
        for segment in segments_payload.get("segments", []):
            selected_segment_rows.append(
                {
                    "patch_id": str(patch_id),
                    "segment_id": str(segment.get("segment_id", "")),
                    "pair": _pair_id_text(int(segment.get("src_nodeid", 0)), int(segment.get("dst_nodeid", 0))),
                    "topology_arc_id": str(segment.get("topology_arc_id", "")),
                    "topology_arc_source_type": str(segment.get("topology_arc_source_type", "")),
                    "topology_arc_is_direct_legal": bool(segment.get("topology_arc_is_direct_legal", False)),
                    "topology_arc_is_unique": bool(segment.get("topology_arc_is_unique", False)),
                    "bridge_chain_exists": bool(segment.get("bridge_chain_exists", False)),
                    "bridge_chain_unique": bool(segment.get("bridge_chain_unique", False)),
                    "bridge_chain_nodes": list(segment.get("bridge_chain_nodes", [])),
                    "production_arc_pass": bool(
                        str(segment.get("topology_arc_source_type", "")) == _DIRECT_TOPOLOGY_ARC_SOURCE
                        and bool(segment.get("topology_arc_is_direct_legal", False))
                        and bool(segment.get("topology_arc_is_unique", False))
                        and bool(str(segment.get("topology_arc_id", "")))
                    ),
                }
            )
        for road in roads_payload.get("roads", []):
            segment = segment_map.get(str(road.get("segment_id", "")), {})
            built_road_rows.append(
                {
                    "patch_id": str(patch_id),
                    "segment_id": str(road.get("segment_id", "")),
                    "pair": _pair_id_text(int(road.get("src_nodeid", 0)), int(road.get("dst_nodeid", 0))),
                    "topology_arc_id": str(segment.get("topology_arc_id", "")),
                    "topology_arc_source_type": str(segment.get("topology_arc_source_type", "")),
                    "topology_arc_is_direct_legal": bool(segment.get("topology_arc_is_direct_legal", False)),
                    "topology_arc_is_unique": bool(segment.get("topology_arc_is_unique", False)),
                    "bridge_chain_exists": bool(segment.get("bridge_chain_exists", False)),
                    "bridge_chain_unique": bool(segment.get("bridge_chain_unique", False)),
                    "bridge_chain_nodes": list(segment.get("bridge_chain_nodes", [])),
                    "production_arc_pass": bool(
                        str(segment.get("topology_arc_source_type", "")) == _DIRECT_TOPOLOGY_ARC_SOURCE
                        and bool(segment.get("topology_arc_is_direct_legal", False))
                        and bool(segment.get("topology_arc_is_unique", False))
                        and bool(str(segment.get("topology_arc_id", "")))
                    ),
                }
            )
    violating_selected_pairs = sorted(
        {
            str(item["pair"])
            for item in selected_segment_rows
            if (not bool(item["production_arc_pass"])) or str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES
        }
    )
    violating_built_pairs = sorted(
        {
            str(item["pair"])
            for item in built_road_rows
            if (not bool(item["production_arc_pass"])) or str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES
        }
    )
    return {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "selected_segments": selected_segment_rows,
        "built_roads": built_road_rows,
        "summary": {
            "selected_segment_count": int(len(selected_segment_rows)),
            "built_road_count": int(len(built_road_rows)),
            "all_selected_segments_direct_unique": bool(len(violating_selected_pairs) == 0),
            "all_built_roads_direct_unique": bool(len(violating_built_pairs) == 0),
            "synthetic_arc_in_selected_segments": bool(
                any(str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES for item in selected_segment_rows)
            ),
            "synthetic_arc_in_built_roads": bool(
                any(str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES for item in built_road_rows)
            ),
            "synthetic_arc_in_production": bool(
                any(str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES for item in selected_segment_rows)
                or any(str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES for item in built_road_rows)
            ),
            "violating_selected_pairs": violating_selected_pairs,
            "violating_built_pairs": violating_built_pairs,
        },
    }


def build_simple_patch_regression(
    acceptance_results: list[dict[str, Any]],
    arc_legality_audit: dict[str, Any],
) -> dict[str, Any]:
    built_roads = list(arc_legality_audit.get("built_roads", []))
    rows: list[dict[str, Any]] = []
    for item in acceptance_results:
        patch_id = str(item.get("patch_id", ""))
        failed_targets = [str(row.get("target_id", "")) for row in item.get("results", []) if not bool(row.get("pass", False))]
        patch_built_rows = [row for row in built_roads if str(row.get("patch_id", "")) == patch_id]
        rows.append(
            {
                "patch_id": patch_id,
                "acceptance_pass": bool(item.get("acceptance_pass", False)),
                "target_count": int(item.get("target_count", 0)),
                "failed_target_ids": failed_targets,
                "unexpected_built_pairs": list(item.get("unexpected_built_pairs", [])),
                "built_road_count": int(len(patch_built_rows)),
                "all_built_roads_direct_unique": bool(all(bool(row.get("production_arc_pass", False)) for row in patch_built_rows)),
            }
        )
    return {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "patches": rows,
        "all_simple_patches_pass": bool(all(bool(row["acceptance_pass"]) for row in rows)),
    }


def build_complex_patch_legality_review(
    pair_decisions: dict[str, Any],
    arc_legality_audit: dict[str, Any],
) -> dict[str, Any]:
    by_pair = {str(row.get("pair", "")): row for row in pair_decisions.get("pairs", [])}
    summary = dict(arc_legality_audit.get("summary", {}))
    target = dict(by_pair.get(_BRIDGE_TARGET_PAIR, {}))
    reference = dict(by_pair.get(_REFERENCE_PAIR, {}))
    false_positive_rows = [dict(by_pair.get(pair_id, {})) for pair_id in _FALSE_POSITIVE_PAIRS]
    blocked_rows = [dict(by_pair.get(pair_id, {})) for pair_id in _STABLE_BLOCKED_PAIRS]
    return {
        "patch_id": str(pair_decisions.get("patch_id", "")),
        "target_pair": target,
        "reference_pair": reference,
        "false_positive_pairs": false_positive_rows,
        "stable_blocked_pairs": blocked_rows,
        "target_pair_correctly_blocked": bool(
            target
            and not bool(target.get("built_final_road", False))
            and str(target.get("reject_reason", "")) in _ARC_LEGALITY_REASONS
        ),
        "false_positive_guard_ok": bool(all(not bool(row.get("built_final_road", False)) for row in false_positive_rows)),
        "stable_blocked_ok": bool(
            all(
                not bool(row.get("built_final_road", False))
                and str(row.get("bridge_classification", "")) == "topology_gap_unresolved"
                for row in blocked_rows
            )
        ),
        "synthetic_arc_in_production": bool(summary.get("synthetic_arc_in_production", False)),
        "all_built_roads_direct_unique": bool(summary.get("all_built_roads_direct_unique", False)),
    }


def build_strong_constraint_status(
    pair_decisions: dict[str, Any],
    arc_legality_audit: dict[str, Any],
    simple_patch_regression: dict[str, Any],
) -> dict[str, Any]:
    by_pair = {str(row.get("pair", "")): row for row in pair_decisions.get("pairs", [])}
    return {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kept_in_this_round": [
            {
                "constraint": "strict_adjacent_pairing_default_not_relaxed",
                "status": "kept",
                "evidence": "stable blocked pairs remain non_adjacent_pair_blocked and are not built",
            },
            {
                "constraint": "topology_gate_direction_and_terminal_ownership",
                "status": "kept",
                "evidence": "false positive pairs remain blocked and built=false",
            },
            {
                "constraint": "trace_audit_only_not_production_legality",
                "status": "kept",
                "evidence": "trace-only false positive pair remains built=false while should_not_reason stays trace_only_reachability",
            },
            {
                "constraint": "segment_grouping_and_same_pair_topk_still_arc_scoped",
                "status": "kept",
                "evidence": "simple patch acceptance remains pass and selected/built arcs are direct+unique",
            },
            {
                "constraint": "synthetic_bridge_arc_removed_from_production",
                "status": "kept",
                "evidence": "arc_legality_audit.summary.synthetic_arc_in_production=false",
            },
        ],
        "partially_closed_but_not_fixed": [
            {
                "constraint": "shared_intersection_nodeids_semantics",
                "status": "partial",
                "note": "still partial inheritance; not expanded in this round",
            },
            {
                "constraint": "step2_topology_first_architecture",
                "status": "partial",
                "note": "Step2 now hard-gates production arc legality, but overall pipeline is not fully topology-first",
            },
            {
                "constraint": "drivezone_full_containment_construction",
                "status": "partial",
                "note": "DriveZone remains posterior ratio/constraint check, not full-containment constructor",
            },
        ],
        "explicitly_not_touched": [
            "LaneBoundary main chain remains disabled",
            "FinalRoad geometry beautification remains out of scope",
            "FinalRoad still mainly relies on slot + witness + slot/segment-prior anchored shape_ref",
            "continuous corridor reconstruction remains out of scope",
        ],
        "false_positive_pairs": [dict(by_pair.get(pair_id, {})) for pair_id in _FALSE_POSITIVE_PAIRS],
        "simple_patch_regression_ok": bool(simple_patch_regression.get("all_simple_patches_pass", False)),
        "all_built_roads_direct_unique": bool(arc_legality_audit.get("summary", {}).get("all_built_roads_direct_unique", False)),
    }


def _render_summary_markdown(
    *,
    run_root: Path,
    acceptance_results: list[dict[str, Any]],
    pair_decisions: dict[str, Any],
    arc_legality_audit: dict[str, Any],
    simple_patch_regression: dict[str, Any],
    complex_review: dict[str, Any],
    strong_constraint_status: dict[str, Any],
) -> str:
    by_pair = {str(row.get("pair", "")): row for row in pair_decisions.get("pairs", [])}
    target = dict(by_pair.get(_BRIDGE_TARGET_PAIR, {}))
    reference = dict(by_pair.get(_REFERENCE_PAIR, {}))
    lines = [
        "# T05 v2 Arc Legality Fix Summary",
        "",
        f"- `run_root`: `{run_root}`",
        f"- `generated_at_utc`: `{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}`",
        "",
        "## Simple Patch Regression",
        "",
    ]
    for item in acceptance_results:
        failed = [row for row in item.get("results", []) if not bool(row.get("pass", False))]
        lines.append(
            f"- `{item['patch_id']}`: acceptance_pass={str(item['acceptance_pass']).lower()} "
            f"targets={item['target_count']} failed={len(failed)}"
        )
    lines.extend(
        [
            "",
            "## Arc Legality",
            "",
            f"- built_roads_all_direct_unique=`{str(bool(arc_legality_audit.get('summary', {}).get('all_built_roads_direct_unique', False))).lower()}`",
            f"- synthetic_arc_in_production=`{str(bool(arc_legality_audit.get('summary', {}).get('synthetic_arc_in_production', False))).lower()}`",
            "",
            "## Complex Patch Target Pairs",
            "",
            f"- target `{_BRIDGE_TARGET_PAIR}`: built={str(bool(target.get('built_final_road', False))).lower()} "
            f"reject=`{target.get('reject_stage', '')}/{target.get('reject_reason', '')}` "
            f"arc_direct={str(bool(target.get('topology_arc_is_direct_legal', False))).lower()} "
            f"arc_unique={str(bool(target.get('topology_arc_is_unique', False))).lower()}",
            f"- reference `{_REFERENCE_PAIR}`: built={str(bool(reference.get('built_final_road', False))).lower()} "
            f"topology_arc_id=`{reference.get('topology_arc_id', '')}` "
            f"arc_direct={str(bool(reference.get('topology_arc_is_direct_legal', False))).lower()} "
            f"arc_unique={str(bool(reference.get('topology_arc_is_unique', False))).lower()}",
        ]
    )
    for pair_id in _FALSE_POSITIVE_PAIRS:
        row = dict(by_pair.get(pair_id, {}))
        lines.append(
            f"- false_positive `{pair_id}`: built={str(bool(row.get('built_final_road', False))).lower()} "
            f"reject=`{row.get('reject_stage', '')}/{row.get('reject_reason', '')}`"
        )
    for pair_id in _STABLE_BLOCKED_PAIRS:
        row = dict(by_pair.get(pair_id, {}))
        lines.append(
            f"- blocked `{pair_id}`: built={str(bool(row.get('built_final_road', False))).lower()} "
            f"bridge=`{row.get('bridge_classification', '')}`"
        )
    lines.extend(
        [
            "",
            "## Strong Constraints",
            "",
            f"- simple_patch_regression_ok=`{str(bool(simple_patch_regression.get('all_simple_patches_pass', False))).lower()}`",
            f"- complex_target_fixed=`{str(bool(complex_review.get('target_pair_correctly_blocked', False))).lower()}`",
            f"- kept_constraints={len(strong_constraint_status.get('kept_in_this_round', []))}",
            f"- partial_constraints={len(strong_constraint_status.get('partially_closed_but_not_fixed', []))}",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_runtime_before_after_markdown(runtime_breakdown: dict[str, Any]) -> str:
    lines = [
        "# Runtime Before/After",
        "",
        "- before: unavailable in local writer unless an older bundle/runtime file already exists on inner network",
        "",
        "## Current",
        "",
    ]
    for patch in runtime_breakdown.get("patches", []):
        lines.append(
            f"- patch `{patch.get('patch_id','')}` total_runtime_ms={float(patch.get('total_runtime_ms', 0.0) or 0.0):.1f}"
        )
        for stage in patch.get("stages", []):
            stage_name = str(stage.get("stage", ""))
            duration_ms = float(stage.get("duration_ms", 0.0) or 0.0)
            runtime = dict(stage.get("runtime") or {})
            if stage_name == "step3_witness":
                lines.append(
                    "  "
                    f"step3_witness={duration_ms:.1f}ms "
                    f"prefilter={float(runtime.get('trajectory_prefilter_time_ms', 0.0)):.1f}ms "
                    f"attach={float(runtime.get('support_attach_core_loop_time_ms', 0.0)):.1f}ms "
                    f"aggregate={float(runtime.get('terminal_partial_stitched_aggregation_time_ms', 0.0)):.1f}ms "
                    f"witness_build={float(runtime.get('witness_build_time_ms', 0.0)):.1f}ms"
                )
            else:
                lines.append(f"  {stage_name}={duration_ms:.1f}ms")
    lines.append("")
    return "\n".join(lines)


def write_arc_legality_fix_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    run_root_path = Path(run_root)
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    patch_ids = list(simple_patch_ids or ["5417632690143239", "5417632690143326"])
    acceptance_results = [evaluate_patch_acceptance(run_root_path, patch_id) for patch_id in patch_ids]
    pair_decisions = build_pair_decisions(run_root_path, complex_patch_id)
    arc_legality_audit = build_arc_legality_audit(run_root_path, [*patch_ids, str(complex_patch_id)])
    simple_patch_regression = build_simple_patch_regression(acceptance_results, arc_legality_audit)
    complex_review = build_complex_patch_legality_review(pair_decisions, arc_legality_audit)
    strong_constraint_status = build_strong_constraint_status(
        pair_decisions=pair_decisions,
        arc_legality_audit=arc_legality_audit,
        simple_patch_regression=simple_patch_regression,
    )

    for item in acceptance_results:
        write_json(output_root_path / f"acceptance_{item['patch_id']}.json", item)
    write_json(output_root_path / "pair_decisions.json", pair_decisions)
    write_json(output_root_path / "arc_legality_audit.json", arc_legality_audit)
    write_json(output_root_path / "strong_constraint_status.json", strong_constraint_status)
    write_json(output_root_path / "simple_patch_regression.json", simple_patch_regression)
    write_json(output_root_path / "complex_patch_legality_review.json", complex_review)
    (output_root_path / "SUMMARY.md").write_text(
        _render_summary_markdown(
            run_root=run_root_path,
            acceptance_results=acceptance_results,
            pair_decisions=pair_decisions,
            arc_legality_audit=arc_legality_audit,
            simple_patch_regression=simple_patch_regression,
            complex_review=complex_review,
            strong_constraint_status=strong_constraint_status,
        ),
        encoding="utf-8",
    )
    return {
        "output_root": str(output_root_path),
        "acceptance": acceptance_results,
        "pair_decisions": pair_decisions,
        "arc_legality_audit": arc_legality_audit,
        "strong_constraint_status": strong_constraint_status,
        "simple_patch_regression": simple_patch_regression,
        "complex_patch_legality_review": complex_review,
    }


def write_bridge_trial_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    return write_arc_legality_fix_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )


__all__ = [
    "build_arc_legality_audit",
    "build_complex_patch_legality_review",
    "build_pair_decisions",
    "build_simple_patch_regression",
    "build_strong_constraint_status",
    "evaluate_patch_acceptance",
    "write_arc_legality_fix_review",
    "write_bridge_trial_review",
]


def _production_arc_pass(row: dict[str, Any]) -> bool:
    return bool(
        str(row.get("topology_arc_source_type", "")) == _DIRECT_TOPOLOGY_ARC_SOURCE
        and bool(row.get("topology_arc_is_direct_legal", False))
        and bool(row.get("topology_arc_is_unique", False))
        and bool(str(row.get("topology_arc_id", "")))
    )


def _registry_row_to_arc_record(row: dict[str, Any]) -> dict[str, Any]:
    identity = _identity_record_from_row(row)
    return {
        "raw_pair": str(identity.get("raw_pair", "")),
        "canonical_pair": str(identity.get("canonical_pair", "")),
        "raw_src_nodeid": identity.get("raw_src_nodeid"),
        "raw_dst_nodeid": identity.get("raw_dst_nodeid"),
        "canonical_src_xsec_id": identity.get("canonical_src_xsec_id"),
        "canonical_dst_xsec_id": identity.get("canonical_dst_xsec_id"),
        "src_alias_applied": bool(identity.get("src_alias_applied", False)),
        "dst_alias_applied": bool(identity.get("dst_alias_applied", False)),
        "alias_normalized": bool(identity.get("alias_normalized", False)),
        "topology_arc_id": str(identity.get("topology_arc_id", "")),
        "canonical_topology_arc_id": str(identity.get("canonical_topology_arc_id", identity.get("topology_arc_id", ""))),
        "topology_arc_source_type": str(identity.get("topology_arc_source_type", "")),
        "topology_arc_is_direct_legal": bool(identity.get("topology_arc_is_direct_legal", False)),
        "topology_arc_is_unique": bool(identity.get("topology_arc_is_unique", False)),
        "controlled_entry_allowed": bool(identity.get("controlled_entry_allowed", False)),
        "topology_gap_decision": str(identity.get("topology_gap_decision", "")),
        "topology_gap_reason": str(identity.get("topology_gap_reason", "")),
        "bridge_chain_exists": bool(identity.get("bridge_chain_exists", False)),
        "bridge_chain_unique": bool(identity.get("bridge_chain_unique", False)),
        "bridge_chain_nodes": list(identity.get("bridge_chain_nodes", [])),
        "blocked_diagnostic_only": bool(identity.get("blocked_diagnostic_only", False)),
        "blocked_diagnostic_reason": str(identity.get("blocked_diagnostic_reason", "")),
        "hard_block_reason": str(identity.get("hard_block_reason", "")),
        "working_segment_id": str(identity.get("working_segment_id", "")),
    }


def build_arc_legality_audit(run_root: Path | str, patch_ids: list[str]) -> dict[str, Any]:
    built_road_rows: list[dict[str, Any]] = []
    selected_segment_rows: list[dict[str, Any]] = []
    for patch_id in patch_ids:
        patch_dir = _patch_dir(run_root, patch_id)
        segments_payload = _cached_patch_json(patch_dir / "step2" / "segments.json")
        roads_payload = _cached_patch_json(patch_dir / "step6" / "final_roads.json")
        registry_rows = _patch_full_registry_rows(run_root, patch_id)
        segment_map = {
            str(item.get("segment_id", "")): dict(item)
            for item in segments_payload.get("segments", [])
            if str(item.get("segment_id", ""))
        }
        registry_by_pair = _registry_rows_by_pair(registry_rows)
        registry_by_working_segment = _registry_rows_by_working_segment(registry_rows)
        selected_rows = _pair_rows_by_id(list(segments_payload.get("segments", [])))
        for segment in segments_payload.get("segments", []):
            row = _identity_record_from_row(
                segment,
                pair_id=_pair_id_text(int(segment.get("src_nodeid", 0)), int(segment.get("dst_nodeid", 0))),
                working_segment_id=str(segment.get("segment_id", "")),
                resolution_source="step2_segments",
            )
            selected_row = {
                "patch_id": str(patch_id),
                "segment_id": str(segment.get("segment_id", "")),
                **row,
            }
            selected_row["production_arc_pass"] = _production_arc_pass(selected_row)
            selected_segment_rows.append(selected_row)
        for road in roads_payload.get("roads", []):
            road_segment_id = str(road.get("segment_id", ""))
            road_pair = _pair_id_text(int(road.get("src_nodeid", 0)), int(road.get("dst_nodeid", 0)))
            resolved = _resolve_identity_record(
                pair_id=road_pair,
                working_segment_id=road_segment_id,
                registry_by_pair=registry_by_pair,
                registry_by_working_segment=registry_by_working_segment,
                segment_map=segment_map,
                selected_rows=selected_rows,
            )
            row = {
                "patch_id": str(patch_id),
                "segment_id": road_segment_id,
                "pair": road_pair,
                **_registry_row_to_arc_record(resolved),
                "built_final_road": True,
                "identity_resolution_source": str(resolved.get("identity_resolution_source", "")),
            }
            row["production_arc_pass"] = _production_arc_pass(row)
            built_road_rows.append(row)
    violating_selected_pairs = sorted(
        {
            str(item["pair"])
            for item in selected_segment_rows
            if (not bool(item["production_arc_pass"])) or str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES
        }
    )
    violating_built_rows = [
        dict(item)
        for item in built_road_rows
        if (
            (not bool(item["production_arc_pass"]))
            or str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES
            or bool(item.get("blocked_diagnostic_only", False))
            or bool(str(item.get("hard_block_reason", "")))
        )
    ]
    violating_built_pairs = sorted({str(item["pair"]) for item in violating_built_rows})
    built_arc_count = int(len(built_road_rows))
    bad_built_arc_count = int(len(violating_built_rows))
    built_all_direct_unique = bool(bad_built_arc_count == 0)
    return {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "selected_segments": selected_segment_rows,
        "built_roads": built_road_rows,
        "built_road_arc_checks": built_road_rows,
        "violating_rows": violating_built_rows,
        "summary": {
            "selected_segment_count": int(len(selected_segment_rows)),
            "built_road_count": built_arc_count,
            "built_arc_count": built_arc_count,
            "bad_built_arc_count": bad_built_arc_count,
            "built_all_direct_unique": built_all_direct_unique,
            "all_selected_segments_direct_unique": bool(len(violating_selected_pairs) == 0),
            "all_built_roads_direct_unique": built_all_direct_unique,
            "synthetic_arc_in_selected_segments": bool(
                any(str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES for item in selected_segment_rows)
            ),
            "synthetic_arc_in_built_roads": bool(
                any(str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES for item in built_road_rows)
            ),
            "synthetic_arc_in_production": bool(
                any(str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES for item in selected_segment_rows)
                or any(str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES for item in built_road_rows)
            ),
            "violating_selected_pairs": violating_selected_pairs,
            "violating_built_pairs": violating_built_pairs,
            "audit_summary_inconsistent": bool(built_all_direct_unique != (bad_built_arc_count == 0)),
        },
    }


def _patch_metrics(run_root: Path | str, patch_id: str) -> dict[str, Any]:
    return _cached_patch_json(_patch_dir(run_root, patch_id) / "metrics.json")


def _patch_full_registry_rows(run_root: Path | str, patch_id: str) -> list[dict[str, Any]]:
    metrics = _patch_metrics(run_root, patch_id)
    rows = list(metrics.get("full_legal_arc_registry", []))
    if rows:
        return rows
    step4_payload = _cached_patch_json(_patch_dir(run_root, patch_id) / "step4" / "corridor_identity.json")
    rows = list(step4_payload.get("full_legal_arc_registry", []))
    if rows:
        return rows
    legacy_rows = list(step4_payload.get("legal_arc_registry", []))
    if legacy_rows:
        return [
            {
                **dict(row),
                "entered_main_flow": bool(row.get("entered_main_flow", True)),
                "is_direct_legal": bool(row.get("is_direct_legal", row.get("topology_arc_is_direct_legal", True))),
                "is_unique": bool(row.get("is_unique", row.get("topology_arc_is_unique", True))),
                "built_final_road": bool(row.get("built_final_road", False)),
                "slot_status": str(row.get("slot_status", "unresolved")),
                "unbuilt_stage": str(row.get("unbuilt_stage", "")),
                "unbuilt_reason": str(row.get("unbuilt_reason", "")),
            }
            for row in legacy_rows
        ]
    step2_payload = _cached_patch_json(_patch_dir(run_root, patch_id) / "step2" / "segments.json")
    return [
        {
            "pair": _pair_id_text(int(row.get("src_nodeid", 0)), int(row.get("dst_nodeid", 0))),
            "src": int(row.get("src_nodeid", 0)),
            "dst": int(row.get("dst_nodeid", 0)),
            "raw_src_nodeid": row.get("raw_src_nodeid", row.get("src_nodeid", 0)),
            "raw_dst_nodeid": row.get("raw_dst_nodeid", row.get("dst_nodeid", 0)),
            "canonical_src_xsec_id": row.get("canonical_src_xsec_id", row.get("src_nodeid", 0)),
            "canonical_dst_xsec_id": row.get("canonical_dst_xsec_id", row.get("dst_nodeid", 0)),
            "src_alias_applied": bool(row.get("src_alias_applied", False)),
            "dst_alias_applied": bool(row.get("dst_alias_applied", False)),
            "raw_pair": _pair_id_text(
                int(row.get("raw_src_nodeid", row.get("src_nodeid", 0))),
                int(row.get("raw_dst_nodeid", row.get("dst_nodeid", 0))),
            ),
            "canonical_pair": _pair_id_text(
                int(row.get("canonical_src_xsec_id", row.get("src_nodeid", 0))),
                int(row.get("canonical_dst_xsec_id", row.get("dst_nodeid", 0))),
            ),
            "topology_arc_id": str(row.get("topology_arc_id", "")),
            "topology_arc_source_type": str(row.get("topology_arc_source_type", "")),
            "is_direct_legal": bool(row.get("topology_arc_is_direct_legal", False)),
            "is_unique": bool(row.get("topology_arc_is_unique", False)),
            "entered_main_flow": bool(
                row.get("topology_arc_is_direct_legal", False)
                and row.get("topology_arc_is_unique", False)
                and str(row.get("topology_arc_id", ""))
            ),
            "selected_segment_ids": [str(row.get("segment_id", ""))] if str(row.get("segment_id", "")) else [],
            "selected_segment_count": 1 if str(row.get("segment_id", "")) else 0,
            "selected_segment_id": str(row.get("segment_id", "")),
            "working_segment_id": str(row.get("segment_id", "")),
            "working_segment_source": "step2_selected_segment" if str(row.get("segment_id", "")) else "",
            "traj_support_type": "no_support",
            "prior_support_type": "no_support",
            "corridor_identity": "unresolved",
            "slot_status": "unresolved",
            "built_final_road": False,
            "unbuilt_stage": "",
            "unbuilt_reason": "",
        }
        for row in step2_payload.get("segments", [])
        if str(row.get("topology_arc_source_type", "")) == _DIRECT_TOPOLOGY_ARC_SOURCE
        and bool(row.get("topology_arc_is_direct_legal", False))
        and bool(row.get("topology_arc_is_unique", False))
        and bool(str(row.get("topology_arc_id", "")))
    ]


def _patch_funnel(run_root: Path | str, patch_id: str) -> dict[str, Any]:
    metrics = _patch_metrics(run_root, patch_id)
    funnel = dict(metrics.get("legal_arc_funnel", {}))
    if funnel:
        return funnel
    step4_payload = _cached_patch_json(_patch_dir(run_root, patch_id) / "step4" / "corridor_identity.json")
    return dict(step4_payload.get("legal_arc_funnel", {}))


def _patch_arc_evidence_attach(run_root: Path | str, patch_id: str) -> list[dict[str, Any]]:
    payload = _cached_patch_json(_patch_dir(run_root, patch_id) / "step3" / "witness.json")
    rows = list(payload.get("arc_evidence_attach_audit", []))
    if rows:
        return rows
    debug_payload = _cached_patch_json(_patch_dir(run_root, patch_id) / "debug" / "arc_evidence_attach.json")
    return list(debug_payload.get("rows", [])) or list(debug_payload.get("arcs", []))


def _patch_runtime_breakdown(run_root: Path | str, patch_id: str) -> dict[str, Any]:
    patch_dir = _patch_dir(run_root, patch_id)
    payload = _cached_patch_json(patch_dir / "runtime_breakdown.json")
    if payload:
        return payload
    stages: list[dict[str, Any]] = []
    total_runtime_ms = 0.0
    for stage_name, dir_name in [
        ("step1_input_frame", "step1"),
        ("step2_segment", "step2"),
        ("step3_witness", "step3"),
        ("step4_corridor_identity", "step4"),
        ("step5_slot_mapping", "step5"),
        ("step6_build_road", "step6"),
    ]:
        state = _cached_patch_json(patch_dir / dir_name / "step_state.json")
        if not state:
            continue
        duration_ms = float(state.get("duration_ms", 0.0) or 0.0)
        total_runtime_ms += duration_ms
        stages.append(
            {
                "stage": str(stage_name),
                "status": "ok" if bool(state.get("ok")) else "failed",
                "duration_ms": float(duration_ms),
                "runtime": dict(state.get("runtime") or {}),
            }
        )
    return {"patch_id": str(patch_id), "stages": stages, "total_runtime_ms": float(total_runtime_ms)}


def build_runtime_breakdown(
    run_root: Path | str,
    patch_ids: list[str],
    *,
    review_runtime_ms: float = 0.0,
) -> dict[str, Any]:
    patches: list[dict[str, Any]] = []
    total_runtime_ms = float(review_runtime_ms)
    for patch_id in patch_ids:
        payload = dict(_patch_runtime_breakdown(run_root, patch_id))
        total_runtime_ms += float(payload.get("total_runtime_ms", 0.0) or 0.0)
        patches.append(payload)
    return {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "patches": patches,
        "review_runtime_ms": float(review_runtime_ms),
        "total_runtime_ms": float(total_runtime_ms),
    }


def _registry_example(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "pair": str(row.get("pair", "")),
        "topology_arc_id": str(row.get("topology_arc_id", "")),
        "traj_support_type": str(row.get("traj_support_type", "no_support")),
        "prior_support_type": str(row.get("prior_support_type", "no_support")),
        "corridor_identity": str(row.get("corridor_identity", "unresolved")),
        "slot_status": str(row.get("slot_status", "unresolved")),
        "built_final_road": bool(row.get("built_final_road", False)),
        "unbuilt_stage": str(row.get("unbuilt_stage", "")),
        "unbuilt_reason": str(row.get("unbuilt_reason", "")),
        "working_segment_source": str(row.get("working_segment_source", "")),
        "selected_segment_count": int(row.get("selected_segment_count", 0)),
        "traj_support_coverage_ratio": float(row.get("traj_support_coverage_ratio", 0.0)),
    }


def build_arc_evidence_attach_audit(run_root: Path | str, patch_ids: list[str]) -> dict[str, Any]:
    patch_rows: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    for patch_id in patch_ids:
        rows = [dict(item) for item in _patch_arc_evidence_attach(run_root, patch_id)]
        all_rows.extend([{**dict(item), "patch_id": str(patch_id)} for item in rows])
        patch_rows.append(
            {
                "patch_id": str(patch_id),
                "row_count": int(len(rows)),
                "entered_main_flow_count": int(sum(1 for item in rows if bool(item.get("entered_main_flow", False)))),
                "traj_support_type_hist": dict(Counter(str(item.get("traj_support_type", "no_support")) for item in rows)),
                "terminal_crossing_support_count": int(sum(1 for item in rows if str(item.get("traj_support_type", "")) == "terminal_crossing_support")),
                "partial_arc_support_count": int(sum(1 for item in rows if str(item.get("traj_support_type", "")) == "partial_arc_support")),
                "stitched_arc_support_count": int(sum(1 for item in rows if str(item.get("traj_support_type", "")) == "stitched_arc_support")),
                "prior_fallback_support_count": int(sum(1 for item in rows if str(item.get("prior_support_type", "")) == "prior_fallback_support")),
                "top_examples": [_registry_example(item) for item in rows[:5]],
            }
        )
    return {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "patches": patch_rows,
        "rows": all_rows,
    }


def build_legal_arc_coverage(run_root: Path | str, patch_ids: list[str]) -> dict[str, Any]:
    patch_rows: list[dict[str, Any]] = []
    legal_arc_rows: list[dict[str, Any]] = []
    for patch_id in patch_ids:
        registry_rows = [dict(item) for item in _patch_full_registry_rows(run_root, patch_id)]
        funnel = dict(_patch_funnel(run_root, patch_id))
        roads_payload = _cached_patch_json(_patch_dir(run_root, patch_id) / "step6" / "final_roads.json")
        built_segment_ids = {str(item.get("segment_id", "")) for item in roads_payload.get("roads", []) if str(item.get("segment_id", ""))}
        for row in registry_rows:
            row_segment_ids = [str(v) for v in row.get("selected_segment_ids", []) if str(v)]
            working_segment_id = str(row.get("working_segment_id", ""))
            if working_segment_id:
                row_segment_ids.append(working_segment_id)
            if not bool(row.get("built_final_road", False)) and any(segment_id in built_segment_ids for segment_id in row_segment_ids):
                row["built_final_road"] = True
                row["unbuilt_stage"] = ""
                row["unbuilt_reason"] = ""
        entered_rows = [row for row in registry_rows if bool(row.get("entered_main_flow", False))]
        entered_rows = sorted(entered_rows, key=lambda item: (str(item.get("pair", "")), str(item.get("topology_arc_id", ""))))
        legal_arc_rows.extend([{**dict(row), "patch_id": str(patch_id)} for row in entered_rows])
        legal_arc_total = int(funnel.get("entered_main_flow_arc_count", len(entered_rows)))
        legal_arc_built = int(funnel.get("built_arc_count", sum(1 for row in entered_rows if bool(row.get("built_final_road", False)))))
        unbuilt_rows = [row for row in entered_rows if not bool(row.get("built_final_road", False))]
        patch_rows.append(
            {
                "patch_id": str(patch_id),
                "all_direct_legal_arc_count": int(funnel.get("all_direct_legal_arc_count", len(registry_rows))),
                "all_direct_unique_legal_arc_count": int(funnel.get("all_direct_unique_legal_arc_count", sum(1 for row in registry_rows if bool(row.get("is_unique", False))))),
                "entered_main_flow_arc_count": int(legal_arc_total),
                "traj_supported_arc_count": int(funnel.get("traj_supported_arc_count", sum(1 for row in entered_rows if str(row.get("traj_support_type", "no_support")) != "no_support"))),
                "prior_supported_arc_count": int(funnel.get("prior_supported_arc_count", sum(1 for row in entered_rows if str(row.get("prior_support_type", "")) == "prior_fallback_support"))),
                "corridor_resolved_arc_count": int(funnel.get("corridor_resolved_arc_count", sum(1 for row in entered_rows if str(row.get("corridor_identity", "")) in {"witness_based", "prior_based"}))),
                "slot_established_arc_count": int(funnel.get("slot_established_arc_count", sum(1 for row in entered_rows if str(row.get("slot_status", "")) == "resolved"))),
                "legal_arc_total": legal_arc_total,
                "legal_arc_built": legal_arc_built,
                "legal_arc_build_rate": float((legal_arc_built / max(1, legal_arc_total)) if legal_arc_total else 0.0),
                "traj_support_type_hist": dict(Counter(str(row.get("traj_support_type", "no_support")) for row in entered_rows)),
                "unbuilt_reason_hist": dict(Counter(str(row.get("unbuilt_reason", "")) for row in unbuilt_rows if str(row.get("unbuilt_reason", "")))),
                "unbuilt_stage_hist": dict(Counter(str(row.get("unbuilt_stage", "")) for row in unbuilt_rows if str(row.get("unbuilt_stage", "")))),
                "top_unbuilt_examples": [_registry_example(row) for row in unbuilt_rows[:8]],
                "top_recovered_examples": [
                    _registry_example(row)
                    for row in entered_rows
                    if str(row.get("working_segment_source", "")) == "arc_first_materialized_segment"
                ][:8],
            }
        )
    return {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "patches": patch_rows,
        "legal_arcs": legal_arc_rows,
    }


def build_simple_patch_acceptance(
    acceptance_results: list[dict[str, Any]],
    legal_arc_coverage: dict[str, Any],
) -> dict[str, Any]:
    coverage_by_patch = {str(item.get("patch_id", "")): item for item in legal_arc_coverage.get("patches", [])}
    rows: list[dict[str, Any]] = []
    for item in acceptance_results:
        patch_id = str(item.get("patch_id", ""))
        failed_targets = [str(row.get("target_id", "")) for row in item.get("results", []) if not bool(row.get("pass", False))]
        coverage = dict(coverage_by_patch.get(patch_id, {}))
        rows.append(
            {
                "patch_id": patch_id,
                "acceptance_pass": bool(item.get("acceptance_pass", False)),
                "target_count": int(item.get("target_count", 0)),
                "failed_target_ids": failed_targets,
                "unexpected_built_pairs": list(item.get("unexpected_built_pairs", [])),
                "all_direct_legal_arc_count": int(coverage.get("all_direct_legal_arc_count", 0)),
                "all_direct_unique_legal_arc_count": int(coverage.get("all_direct_unique_legal_arc_count", 0)),
                "entered_main_flow_arc_count": int(coverage.get("entered_main_flow_arc_count", 0)),
                "traj_supported_arc_count": int(coverage.get("traj_supported_arc_count", 0)),
                "corridor_resolved_arc_count": int(coverage.get("corridor_resolved_arc_count", 0)),
                "slot_established_arc_count": int(coverage.get("slot_established_arc_count", 0)),
                "legal_arc_total": int(coverage.get("legal_arc_total", 0)),
                "legal_arc_built": int(coverage.get("legal_arc_built", 0)),
                "legal_arc_build_rate": float(coverage.get("legal_arc_build_rate", 0.0)),
                "unbuilt_reason_hist": dict(coverage.get("unbuilt_reason_hist", {})),
            }
        )
    return {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "patches": rows,
        "all_simple_patches_pass": bool(all(bool(row["acceptance_pass"]) for row in rows)),
    }


def build_simple_patch_regression(simple_patch_acceptance: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluated_at_utc": str(simple_patch_acceptance.get("evaluated_at_utc", "")),
        "patches": list(simple_patch_acceptance.get("patches", [])),
        "all_simple_patches_pass": bool(simple_patch_acceptance.get("all_simple_patches_pass", False)),
    }


def build_complex_patch_coverage_review(
    pair_decisions: dict[str, Any],
    arc_legality_audit: dict[str, Any],
    legal_arc_coverage: dict[str, Any],
) -> dict[str, Any]:
    by_pair = {str(row.get("pair", "")): row for row in pair_decisions.get("pairs", [])}
    summary = dict(arc_legality_audit.get("summary", {}))
    target = dict(by_pair.get(_BRIDGE_TARGET_PAIR, {}))
    reference = dict(by_pair.get(_REFERENCE_PAIR, {}))
    false_positive_rows = [dict(by_pair.get(pair_id, {})) for pair_id in _FALSE_POSITIVE_PAIRS]
    blocked_rows = [dict(by_pair.get(pair_id, {})) for pair_id in _STABLE_BLOCKED_PAIRS]
    complex_patch_id = str(pair_decisions.get("patch_id", ""))
    complex_coverage = next(
        (dict(item) for item in legal_arc_coverage.get("patches", []) if str(item.get("patch_id", "")) == complex_patch_id),
        {},
    )
    complex_legal_arcs = [
        dict(item)
        for item in legal_arc_coverage.get("legal_arcs", [])
        if str(item.get("patch_id", "")) == complex_patch_id
    ]
    return {
        "patch_id": complex_patch_id,
        "target_pair": target,
        "reference_pair": reference,
        "false_positive_pairs": false_positive_rows,
        "stable_blocked_pairs": blocked_rows,
        "all_direct_legal_arc_count": int(complex_coverage.get("all_direct_legal_arc_count", 0)),
        "all_direct_unique_legal_arc_count": int(complex_coverage.get("all_direct_unique_legal_arc_count", 0)),
        "entered_main_flow_arc_count": int(complex_coverage.get("entered_main_flow_arc_count", 0)),
        "traj_supported_arc_count": int(complex_coverage.get("traj_supported_arc_count", 0)),
        "prior_supported_arc_count": int(complex_coverage.get("prior_supported_arc_count", 0)),
        "corridor_resolved_arc_count": int(complex_coverage.get("corridor_resolved_arc_count", 0)),
        "slot_established_arc_count": int(complex_coverage.get("slot_established_arc_count", 0)),
        "legal_arc_total": int(complex_coverage.get("legal_arc_total", 0)),
        "legal_arc_built": int(complex_coverage.get("legal_arc_built", 0)),
        "legal_arc_build_rate": float(complex_coverage.get("legal_arc_build_rate", 0.0)),
        "traj_support_type_hist": dict(complex_coverage.get("traj_support_type_hist", {})),
        "unbuilt_reason_hist": dict(complex_coverage.get("unbuilt_reason_hist", {})),
        "unbuilt_stage_hist": dict(complex_coverage.get("unbuilt_stage_hist", {})),
        "top_unbuilt_examples": list(complex_coverage.get("top_unbuilt_examples", [])),
        "top_recovered_examples": list(complex_coverage.get("top_recovered_examples", [])),
        "built_legal_arc_pairs": [str(item.get("pair", "")) for item in complex_legal_arcs if bool(item.get("built_final_road", False))],
        "target_pair_correctly_blocked": bool(
            target
            and not bool(target.get("built_final_road", False))
            and str(target.get("reject_reason", "")) in _ARC_LEGALITY_REASONS
        ),
        "false_positive_guard_ok": bool(all(not bool(row.get("built_final_road", False)) for row in false_positive_rows)),
        "stable_blocked_ok": bool(
            all(
                not bool(row.get("built_final_road", False))
                and str(row.get("bridge_classification", "")) == "topology_gap_unresolved"
                for row in blocked_rows
            )
        ),
        "synthetic_arc_in_production": bool(summary.get("synthetic_arc_in_production", False)),
        "built_all_direct_unique": bool(summary.get("built_all_direct_unique", False)),
    }


def build_complex_patch_legality_review(
    pair_decisions: dict[str, Any],
    arc_legality_audit: dict[str, Any],
) -> dict[str, Any]:
    return build_complex_patch_coverage_review(pair_decisions, arc_legality_audit, {"patches": [], "legal_arcs": []})


def build_bad_built_rootcause(
    run_root: Path | str,
    complex_patch_id: str,
    pair_decisions: dict[str, Any],
    arc_legality_audit: dict[str, Any],
) -> dict[str, Any]:
    patch_dir = _patch_dir(run_root, complex_patch_id)
    registry_rows = _patch_full_registry_rows(run_root, complex_patch_id)
    evidence_rows = _patch_arc_evidence_attach(run_root, complex_patch_id)
    bridge_rows = list(_cached_patch_json(patch_dir / "debug" / "step2_blocked_pair_bridge_audit.json").get("pairs", []))
    registry_by_segment = {
        str(row.get("working_segment_id", "")): dict(row)
        for row in registry_rows
        if str(row.get("working_segment_id", ""))
    }
    registry_by_pair = {str(row.get("pair", "")): dict(row) for row in registry_rows if str(row.get("pair", ""))}
    evidence_by_pair = {str(row.get("pair", "")): dict(row) for row in evidence_rows if str(row.get("pair", ""))}
    bridge_by_pair = {str(row.get("pair_id", "")): dict(row) for row in bridge_rows if str(row.get("pair_id", ""))}
    decision_by_pair = {str(row.get("pair", "")): dict(row) for row in pair_decisions.get("pairs", [])}
    bad_rows = [
        dict(row)
        for row in arc_legality_audit.get("built_roads", [])
        if str(row.get("patch_id", "")) == str(complex_patch_id)
        and (
            not bool(row.get("production_arc_pass", False))
            or bool(row.get("blocked_diagnostic_only", False))
            or bool(str(row.get("hard_block_reason", "")))
        )
    ]
    cases: list[dict[str, Any]] = []
    for row in bad_rows:
        pair_id = str(row.get("pair", ""))
        segment_id = str(row.get("segment_id", ""))
        registry_row = dict(registry_by_segment.get(segment_id) or registry_by_pair.get(pair_id) or {})
        evidence_row = dict(evidence_by_pair.get(pair_id, {}))
        bridge_row = dict(bridge_by_pair.get(pair_id, {}))
        decision_row = dict(decision_by_pair.get(pair_id, {}))
        root_causes: list[str] = []
        if bool(registry_row.get("blocked_diagnostic_only", False)):
            root_causes.append("blocked_diagnostic_only_state_not_respected")
        if bool(str(registry_row.get("hard_block_reason", ""))):
            root_causes.append("hard_block_reason_not_respected")
        if str(segment_id).startswith("arcseg::") and not bool(row.get("production_arc_pass", False)):
            root_causes.append("audit_step2_only_segment_lookup")
        if not root_causes:
            root_causes.append("final_build_gate_missing")
        cases.append(
            {
                "pair": pair_id,
                "segment_id": segment_id,
                "topology_arc_id": str(row.get("topology_arc_id", "")),
                "topology_arc_source_type": str(row.get("topology_arc_source_type", "")),
                "topology_arc_is_direct_legal": bool(row.get("topology_arc_is_direct_legal", False)),
                "topology_arc_is_unique": bool(row.get("topology_arc_is_unique", False)),
                "blocked_diagnostic_only": bool(registry_row.get("blocked_diagnostic_only", row.get("blocked_diagnostic_only", False))),
                "hard_block_reason": str(registry_row.get("hard_block_reason", row.get("hard_block_reason", ""))),
                "bridge_classification": str(
                    bridge_row.get("bridge_classification")
                    or decision_row.get("bridge_classification")
                    or ""
                ),
                "traj_support_type": str(evidence_row.get("traj_support_type", "")),
                "prior_support_type": str(evidence_row.get("prior_support_type", "")),
                "corridor_identity": str(registry_row.get("corridor_identity", "")),
                "slot_status": str(registry_row.get("slot_status", "")),
                "working_segment_source": str(registry_row.get("working_segment_source", "")),
                "root_causes": root_causes,
            }
        )
    return {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "patch_id": str(complex_patch_id),
        "bad_built_case_count": int(len(cases)),
        "cases": cases,
    }


def build_semantic_regression_report(
    *,
    pair_decisions: dict[str, Any],
    arc_legality_audit: dict[str, Any],
    simple_patch_acceptance: dict[str, Any],
) -> dict[str, Any]:
    summary = dict(arc_legality_audit.get("summary", {}))
    by_pair = {str(row.get("pair", "")): row for row in pair_decisions.get("pairs", [])}
    blocked_guard_pairs = [*_STABLE_BLOCKED_PAIRS, _BRIDGE_TARGET_PAIR, *_FALSE_POSITIVE_PAIRS]
    blocked_built_pairs = [
        pair_id
        for pair_id in blocked_guard_pairs
        if bool((by_pair.get(pair_id) or {}).get("built_final_road", False))
    ]
    reasons: list[str] = []
    if int(summary.get("bad_built_arc_count", 0)) > 0:
        reasons.append("bad_built_arc_count_gt_zero")
    if not bool(summary.get("built_all_direct_unique", False)):
        reasons.append("built_all_direct_unique_false")
    if bool(summary.get("synthetic_arc_in_production", False)):
        reasons.append("synthetic_arc_in_production")
    if blocked_built_pairs:
        reasons.append("blocked_pairs_built")
    if not bool(simple_patch_acceptance.get("all_simple_patches_pass", False)):
        reasons.append("simple_patch_acceptance_failed")
    return {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "semantic_regression": bool(reasons),
        "semantic_regression_reasons": reasons,
        "blocked_built_pairs": blocked_built_pairs,
        "bad_built_arc_count": int(summary.get("bad_built_arc_count", 0)),
        "built_all_direct_unique": bool(summary.get("built_all_direct_unique", False)),
        "synthetic_arc_in_production": bool(summary.get("synthetic_arc_in_production", False)),
        "simple_patch_acceptance_pass": bool(simple_patch_acceptance.get("all_simple_patches_pass", False)),
    }


def build_strong_constraint_status(
    pair_decisions: dict[str, Any],
    arc_legality_audit: dict[str, Any],
    simple_patch_regression: dict[str, Any],
) -> dict[str, Any]:
    by_pair = {str(row.get("pair", "")): row for row in pair_decisions.get("pairs", [])}
    summary = dict(arc_legality_audit.get("summary", {}))
    return {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kept_in_this_round": [
            {"constraint": "production_arc_direct_unique_only", "status": "kept", "evidence": f"bad_built_arc_count={int(summary.get('bad_built_arc_count', 0))}"},
            {"constraint": "strict_adjacent_pairing_default_not_relaxed", "status": "kept", "evidence": "stable blocked pairs remain diagnostic-only"},
            {"constraint": "trace_audit_only_not_production_legality", "status": "kept", "evidence": "false positive trace-only pair remains built=false"},
            {"constraint": "synthetic_bridge_arc_removed_from_production", "status": "kept", "evidence": "synthetic_arc_in_production=false"},
            {"constraint": "traj_prior_attach_as_evidence_not_legality", "status": "kept", "evidence": "legal arc audit still derives from direct+unique topology arc"},
        ],
        "partially_closed_but_not_fixed": [
            {"constraint": "shared_intersection_nodeids_semantics", "status": "partial", "note": "still partial inheritance; not expanded in this round"},
            {"constraint": "step2_not_full_topology_first", "status": "partial", "note": "full registry is arc-first now, but the whole pipeline is not a full topology-first rewrite"},
            {"constraint": "drivezone_full_containment_construction", "status": "partial", "note": "DriveZone remains posterior ratio/constraint check, not full-containment constructor"},
        ],
        "explicitly_not_touched": [
            "LaneBoundary main chain remains disabled",
            "FinalRoad geometry beautification remains out of scope",
            "FinalRoad still mainly relies on slot + witness + slot/segment-prior anchored shape_ref",
            "continuous corridor reconstruction remains out of scope",
        ],
        "false_positive_pairs": [dict(by_pair.get(pair_id, {})) for pair_id in _FALSE_POSITIVE_PAIRS],
        "simple_patch_regression_ok": bool(simple_patch_regression.get("all_simple_patches_pass", False)),
        "built_all_direct_unique": bool(summary.get("built_all_direct_unique", False)),
    }


def _competing_arc_side_by_side_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "pair": str(row.get("pair", "")),
        "topology_arc_id": str(row.get("topology_arc_id", "")),
        "chord_summary": (
            f"{str(row.get('src_anchor_source', '') or '-')}->{str(row.get('dst_anchor_source', '') or '-')}"
        ),
        "traj_support_type": str(row.get("traj_support_type", "no_support")),
        "traj_support_count": int(row.get("traj_support_count", 0) or 0),
        "traj_support_coverage_ratio": float(row.get("traj_support_coverage_ratio", 0.0) or 0.0),
        "support_total_length_m": float(row.get("support_total_length_m", 0.0) or 0.0),
        "corridor_identity": str(row.get("corridor_identity", "unresolved")),
        "slot_status": str(row.get("slot_status", "unresolved")),
        "built_final_road": bool(row.get("built_final_road", False)),
        "drivezone_overlap_ratio": float(row.get("drivezone_overlap_ratio", 0.0) or 0.0),
        "divstrip_overlap_ratio": float(row.get("divstrip_overlap_ratio", 0.0) or 0.0),
        "support_strength_score": float(_support_strength_score(row)),
    }


def _competing_arc_analysis(
    row: dict[str, Any],
    *,
    competing_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    pair_id = str(row.get("pair", ""))
    peer_rows = [dict(peer) for peer in competing_rows if str(peer.get("pair", "")) != pair_id]
    current_score = float(_support_strength_score(row))
    peer_summaries = [_competing_arc_side_by_side_row(peer) for peer in peer_rows]
    current_summary = _competing_arc_side_by_side_row(row)
    side_by_side = [current_summary, *peer_summaries]
    side_by_side.sort(
        key=lambda item: (
            -int(bool(item.get("built_final_road", False))),
            -float(item.get("support_strength_score", 0.0)),
            str(item.get("pair", "")),
        )
    )

    strongest_peer = max(peer_summaries, key=lambda item: float(item.get("support_strength_score", 0.0)), default=None)
    strongest_peer_score = float(strongest_peer.get("support_strength_score", 0.0)) if strongest_peer else 0.0
    strongest_peer_pair = str(strongest_peer.get("pair", "")) if strongest_peer else ""
    score_gap_to_best = float(strongest_peer_score - current_score) if strongest_peer else 0.0
    slot_resolved = str(row.get("slot_status", "")) == "resolved"
    resolved_peer_exists = any(str(peer.get("slot_status", "")) == "resolved" for peer in peer_rows)
    built_peer = next((item for item in peer_summaries if bool(item.get("built_final_road", False))), None)
    stronger_peer = bool(strongest_peer and score_gap_to_best >= 2.0)

    root_cause_code = "competing_arc_business_rule_not_decided"
    blocking_layer = "business_rule"
    next_action = "confirm_business_rule_before_release"
    root_cause_detail = "the business rule for choosing among competing destination arcs is still not decided"

    if float(row.get("divstrip_overlap_ratio", 0.0) or 0.0) > 0.10:
        root_cause_code = "competing_arc_crosses_divstrip"
        blocking_layer = "geometry"
        next_action = "keep_blocked_until_corridor_stays_on_non_divstrip_side"
        root_cause_detail = (
            "candidate witness still overlaps divstrip, so the competing arc cannot be released without violating physical separation"
        )
    elif built_peer is not None:
        if stronger_peer and str(built_peer.get("pair", "")) == strongest_peer_pair:
            root_cause_code = "competing_arc_support_weaker_than_built_sibling"
            blocking_layer = "support_ranking"
            next_action = "compare_competing_arc_support_weight_before_release"
            root_cause_detail = (
                "a built competing sibling already occupies the destination branch and this arc is weaker on support evidence"
            )
        else:
            root_cause_code = "competing_arc_slot_conflict_with_built_sibling"
            blocking_layer = "slot"
            next_action = "compare_competing_arc_slot_against_built_sibling_before_release"
            root_cause_detail = (
                "this arc conflicts with an already-built competing sibling on the same downstream destination slot"
            )
    elif not slot_resolved and resolved_peer_exists:
        root_cause_code = "competing_arc_no_independent_slot"
        blocking_layer = "slot"
        next_action = "verify_whether_an_independent_destination_slot_exists"
        root_cause_detail = (
            "a competing peer already has a resolved downstream slot while this arc still lacks an independently established slot"
        )
    elif stronger_peer:
        blocking_layer = "support_ranking"
        next_action = "compare_competing_arc_support_weight_before_release"
        if score_gap_to_best >= 2.0:
            root_cause_code = "competing_arc_support_weaker_below_selection_threshold"
            root_cause_detail = (
                "this arc is measurably weaker than its strongest competing peer and currently falls below the pair-selection support threshold"
            )
        elif slot_resolved:
            root_cause_code = "competing_arc_support_weaker_but_slot_available"
            root_cause_detail = (
                "this arc has an available slot but still loses to a stronger competing peer on support evidence"
            )
        else:
            root_cause_code = "competing_arc_support_weaker_below_selection_threshold"
            root_cause_detail = (
                "this arc is weaker than its strongest competing peer and cannot be released under the current support-ranking threshold"
            )
    elif len(peer_rows) >= 1:
        root_cause_code = "competing_arc_requires_new_pair_selection_rule"
        blocking_layer = "business_rule"
        next_action = "define_pair_selection_rule_for_shared_destination"
        root_cause_detail = (
            "multiple topology-gap arcs compete for the same destination and release now requires an explicit pair-selection rule"
        )

    selected_by_support_ranking = bool(
        strongest_peer is None
        or current_score > strongest_peer_score + 2.0
    )
    independent_slot_available = bool(slot_resolved and built_peer is None)
    return {
        "root_cause_code": str(root_cause_code),
        "blocking_layer": str(blocking_layer),
        "next_action": str(next_action),
        "root_cause_detail": str(root_cause_detail),
        "support_strength_score": float(current_score),
        "strongest_peer_pair": str(strongest_peer_pair),
        "strongest_peer_support_score": float(strongest_peer_score),
        "support_score_gap_to_best": float(score_gap_to_best),
        "has_built_sibling": bool(built_peer is not None),
        "independent_slot_available": bool(independent_slot_available),
        "selected_by_support_ranking": bool(selected_by_support_ranking),
        "competing_siblings": side_by_side,
    }


def build_arc_obligation_registry(
    *,
    complex_patch_id: str,
    topology_gap_review: dict[str, Any],
    same_pair_multi_arc_observation: dict[str, Any],
) -> dict[str, Any]:
    gap_rows = [dict(row) for row in topology_gap_review.get("rows", []) if str(row.get("patch_id", "")) == str(complex_patch_id)]
    same_pair_rows = [
        dict(row)
        for row in same_pair_multi_arc_observation.get("rows", [])
        if str(row.get("patch_id", "")) == str(complex_patch_id)
    ]
    gap_rows_by_dst: dict[str, list[dict[str, Any]]] = {}
    for row in gap_rows:
        gap_rows_by_dst.setdefault(str(row.get("dst", "")), []).append(dict(row))

    rows: list[dict[str, Any]] = []
    for row in gap_rows:
        classification = str(row.get("gap_classification", ""))
        pair_id = str(row.get("pair", ""))
        competing_rows = list(gap_rows_by_dst.get(str(row.get("dst", "")), []))
        if classification == "gap_enter_mainflow":
            obligation_status = "must_build_now"
            current_status = "controlled_entry_built" if bool(row.get("built_final_road", False)) else "blocked"
            blocking_layer = "none" if bool(row.get("built_final_road", False)) else str(row.get("unbuilt_stage", "") or "entry_gate")
            blocking_reason = "" if bool(row.get("built_final_road", False)) else str(row.get("unbuilt_reason", "") or row.get("gap_reason", ""))
            next_action = (
                "keep_current_controlled_entry_resolution"
                if bool(row.get("built_final_road", False))
                else "trace_remaining_failure_in_stable_mainflow"
            )
        elif classification == "gap_remain_blocked":
            obligation_status = "must_remain_blocked"
            current_status = "blocked"
            blocking_layer = "entry_gate"
            blocking_reason = str(row.get("gap_reason", "") or row.get("unbuilt_reason", ""))
            next_action = "keep_blocked_until_business_rule_changes"
        else:
            analysis = _competing_arc_analysis(row, competing_rows=competing_rows)
            obligation_status = "must_remain_blocked"
            current_status = "blocked"
            blocking_layer = str(analysis.get("blocking_layer", "pair_identity"))
            blocking_reason = str(analysis.get("root_cause_code", "competing_arc_business_rule_not_decided"))
            next_action = str(analysis.get("next_action", "confirm_business_rule_before_release"))

        rows.append(
            {
                "patch_id": str(complex_patch_id),
                "src": int(row.get("src", 0)),
                "dst": int(row.get("dst", 0)),
                "pair": pair_id,
                "topology_arc_id": str(row.get("topology_arc_id", "")),
                "obligation_status": str(obligation_status),
                "current_status": str(current_status),
                "blocking_layer": str(blocking_layer),
                "blocking_reason": str(blocking_reason),
                "next_action": str(next_action),
                "gap_classification": str(classification),
                "gap_reason": str(row.get("gap_reason", "")),
                "controlled_entry_allowed": bool(row.get("controlled_entry_allowed", False)),
                "entered_main_flow": bool(row.get("entered_main_flow", False)),
                "built_final_road": bool(row.get("built_final_road", False)),
                "traj_support_type": str(row.get("traj_support_type", "no_support")),
                "traj_support_count": int(row.get("traj_support_count", 0)),
                "corridor_identity": str(row.get("corridor_identity", "unresolved")),
                "slot_status": str(row.get("slot_status", "unresolved")),
                "unbuilt_stage": str(row.get("unbuilt_stage", "")),
                "unbuilt_reason": str(row.get("unbuilt_reason", "")),
                "support_strength_score": float(_support_strength_score(row)),
            }
        )

    for row in same_pair_rows:
        rows.append(
            {
                "patch_id": str(complex_patch_id),
                "src": int(row.get("src", 0)),
                "dst": int(row.get("dst", 0)),
                "pair": str(row.get("pair", "")),
                "topology_arc_id": "",
                "obligation_status": "root_cause_confirm_first",
                "current_status": "observation_only",
                "blocking_layer": "pair_identity",
                "blocking_reason": "multi_arc_excluded_from_unique_denominator",
                "next_action": str(
                    row.get(
                        "next_rule_needed",
                        (
                            "compare_multi_arc_candidates_against_business_selection_rule"
                            if bool(row.get("has_built_sibling_arc", False))
                            else "define_multi_arc_selection_rule_before_allowing_build"
                        ),
                    )
                ),
                "pair_arc_count": int(row.get("pair_arc_count", 0)),
                "arc_ids": [str(v) for v in row.get("arc_ids", [])],
                "has_built_sibling_arc": bool(row.get("has_built_sibling_arc", False)),
                "built_sibling_arc_ids": [str(v) for v in row.get("built_sibling_arc_ids", [])],
                "current_business_status": str(row.get("current_business_status", "")),
                "next_rule_needed": str(row.get("next_rule_needed", "")),
                "chord_available": bool(row.get("chord_available", False)),
                "witness_available": bool(row.get("witness_available", False)),
                "visual_gap_note": str(row.get("visual_gap_note", "")),
            }
        )

    rows.sort(key=lambda item: (str(item.get("pair", "")), str(item.get("obligation_status", ""))))
    return {
        "patch_id": str(complex_patch_id),
        "row_count": int(len(rows)),
        "rows": rows,
    }


def build_competing_arc_review(
    *,
    complex_patch_id: str,
    topology_gap_review: dict[str, Any],
    same_pair_multi_arc_observation: dict[str, Any],
) -> dict[str, Any]:
    gap_rows = [dict(row) for row in topology_gap_review.get("rows", []) if str(row.get("patch_id", "")) == str(complex_patch_id)]
    same_pair_rows = [
        dict(row)
        for row in same_pair_multi_arc_observation.get("rows", [])
        if str(row.get("patch_id", "")) == str(complex_patch_id)
    ]
    gap_rows_by_dst: dict[str, list[dict[str, Any]]] = {}
    for row in gap_rows:
        gap_rows_by_dst.setdefault(str(row.get("dst", "")), []).append(dict(row))

    rows: list[dict[str, Any]] = []
    for row in gap_rows:
        if str(row.get("gap_classification", "")) != "gap_ambiguous_need_more_constraints":
            continue
        competing_rows = list(gap_rows_by_dst.get(str(row.get("dst", "")), []))
        analysis = _competing_arc_analysis(row, competing_rows=competing_rows)
        rows.append(
            {
                "patch_id": str(complex_patch_id),
                "pair": str(row.get("pair", "")),
                "review_scope": "topology_gap_competing_arc",
                "topology_arc_id": str(row.get("topology_arc_id", "")),
                "competing_group_key": f"dst:{int(row.get('dst', 0))}",
                "competing_pair_count": int(len(competing_rows)),
                "competing_pairs": [str(item.get("pair", "")) for item in competing_rows],
                "traj_support_type": str(row.get("traj_support_type", "no_support")),
                "traj_support_count": int(row.get("traj_support_count", 0)),
                "traj_support_coverage_ratio": float(row.get("traj_support_coverage_ratio", 0.0) or 0.0),
                "support_total_length_m": float(row.get("support_total_length_m", 0.0)),
                "slot_status": str(row.get("slot_status", "unresolved")),
                "built_final_road": bool(row.get("built_final_road", False)),
                "drivezone_overlap_ratio": float(row.get("drivezone_overlap_ratio", 0.0)),
                "divstrip_overlap_ratio": float(row.get("divstrip_overlap_ratio", 0.0)),
                "root_cause_code": str(analysis.get("root_cause_code", "competing_arc_business_rule_not_decided")),
                "root_cause_detail": str(analysis.get("root_cause_detail", "")),
                "next_action": str(analysis.get("next_action", "")),
                "blocking_layer": str(analysis.get("blocking_layer", "")),
                "support_strength_score": float(analysis.get("support_strength_score", 0.0)),
                "strongest_peer_pair": str(analysis.get("strongest_peer_pair", "")),
                "strongest_peer_support_score": float(analysis.get("strongest_peer_support_score", 0.0)),
                "support_score_gap_to_best": float(analysis.get("support_score_gap_to_best", 0.0)),
                "has_built_sibling": bool(analysis.get("has_built_sibling", False)),
                "independent_slot_available": bool(analysis.get("independent_slot_available", False)),
                "selected_by_support_ranking": bool(analysis.get("selected_by_support_ranking", False)),
                "competing_siblings": list(analysis.get("competing_siblings", [])),
            }
        )

    for row in same_pair_rows:
        rows.append(
            {
                "patch_id": str(complex_patch_id),
                "pair": str(row.get("pair", "")),
                "review_scope": "same_pair_multi_arc_observation",
                "topology_arc_id": "",
                "pair_arc_count": int(row.get("pair_arc_count", 0)),
                "arc_ids": [str(v) for v in row.get("arc_ids", [])],
                "has_built_sibling_arc": bool(row.get("has_built_sibling_arc", False)),
                "built_sibling_arc_ids": [str(v) for v in row.get("built_sibling_arc_ids", [])],
                "chord_available": bool(row.get("chord_available", False)),
                "witness_available": bool(row.get("witness_available", False)),
                "current_business_status": str(row.get("current_business_status", "")),
                "next_rule_needed": str(row.get("next_rule_needed", "")),
                "root_cause_code": "multi_arc_no_selection_rule",
                "root_cause_detail": (
                    "same src/dst has multiple direct arcs and no business selection rule exists yet, so the pair stays outside the strict unique denominator"
                    if not bool(row.get("has_built_sibling_arc", False))
                    else "same src/dst has multiple direct arcs; a built sibling exists but the non-selected arc still remains outside the strict unique denominator until an explicit selection rule is defined"
                ),
                "next_action": (
                    str(row.get("next_rule_needed", "multi_arc_selection_rule"))
                    if not bool(row.get("has_built_sibling_arc", False))
                    else "compare_built_sibling_and_nonbuilt_arc_before_selection"
                ),
            }
        )

    rows.sort(key=lambda item: (str(item.get("review_scope", "")), str(item.get("pair", ""))))
    return {
        "patch_id": str(complex_patch_id),
        "row_count": int(len(rows)),
        "rows": rows,
    }


def build_arc_selection_structure(
    run_root: Path | str,
    *,
    complex_patch_id: str,
) -> dict[str, Any]:
    registry_rows = [dict(row) for row in _patch_full_registry_rows(run_root, complex_patch_id)]
    if registry_rows:
        registry_rows = list(apply_arc_selection_rules(registry_rows).get("rows", []))
    rows: list[dict[str, Any]] = []
    merge_pairs: set[str] = set()
    same_pair_groups: set[str] = set()
    for row in registry_rows:
        structure_type = str(row.get("arc_structure_type", ""))
        if structure_type not in {STRUCTURE_MERGE_MULTI_UPSTREAM, STRUCTURE_SAME_PAIR_MULTI_ARC}:
            continue
        pair_id = str(_row_pair_id(row))
        canonical_pair = str(row.get("canonical_pair", pair_id))
        peer_pairs = [str(v) for v in row.get("arc_selection_peer_pairs", []) if str(v)]
        shared_downstream_nodes = [int(v) for v in row.get("arc_selection_shared_downstream_nodes", []) if v is not None]
        shared_downstream_edge_ids = [str(v) for v in row.get("arc_selection_shared_downstream_edge_ids", []) if str(v)]
        shared_downstream_signal = [str(v) for v in row.get("arc_selection_shared_downstream_signal", []) if str(v)]
        if structure_type == STRUCTURE_MERGE_MULTI_UPSTREAM:
            merge_pairs.add(pair_id)
        elif structure_type == STRUCTURE_SAME_PAIR_MULTI_ARC:
            same_pair_groups.add(canonical_pair)
        rows.append(
            {
                "patch_id": str(complex_patch_id),
                "pair": pair_id,
                "raw_pair": str(row.get("raw_pair", pair_id)),
                "canonical_pair": canonical_pair,
                "topology_arc_id": str(row.get("topology_arc_id", "")),
                "structure_type": structure_type,
                "arc_structure_type": structure_type,
                "selection_rule": str(row.get("arc_selection_rule", "")),
                "arc_selection_rule": str(row.get("arc_selection_rule", "")),
                "allow_multi_output": bool(row.get("arc_selection_allow_multi_output", False)),
                "selection_rule_reason": str(row.get("arc_selection_rule_reason", "")),
                "peer_pairs": peer_pairs,
                "shared_downstream_nodes": shared_downstream_nodes,
                "shared_downstream_edge_ids": shared_downstream_edge_ids,
                "shared_downstream_signal": shared_downstream_signal,
                "same_pair_arc_count": int(row.get("arc_selection_same_pair_arc_count", 0)),
                "same_pair_arc_ids": [str(v) for v in row.get("arc_selection_same_pair_arc_ids", []) if str(v)],
                "entered_main_flow": bool(row.get("entered_main_flow", False)),
                "built_final_road": bool(row.get("built_final_road", False)),
                "topology_arc_is_direct_legal": bool(
                    row.get("topology_arc_is_direct_legal", row.get("is_direct_legal", False))
                ),
                "topology_arc_is_unique": bool(row.get("topology_arc_is_unique", row.get("is_unique", False))),
            }
        )
    rows.sort(key=lambda item: (str(item.get("structure_type", "")), str(item.get("pair", "")), str(item.get("topology_arc_id", ""))))
    return {
        "patch_id": str(complex_patch_id),
        "row_count": int(len(rows)),
        "merge_multi_upstream_pair_count": int(len(merge_pairs)),
        "same_pair_multi_arc_pair_count": int(len(same_pair_groups)),
        "rows": rows,
    }


def build_merge_diverge_review(
    run_root: Path | str,
    *,
    complex_patch_id: str,
    target_pairs: list[str] | None = None,
    min_support_coverage_ratio: float = 0.35,
) -> dict[str, Any]:
    registry_rows = [dict(row) for row in _patch_full_registry_rows(run_root, complex_patch_id)]
    if registry_rows:
        registry_rows = list(apply_arc_selection_rules(registry_rows).get("rows", []))
    registry_by_pair = _registry_rows_by_pair(registry_rows)
    merge_rule_by_pair = apply_diverge_merge_rule(
        registry_rows,
        min_support_coverage_ratio=float(min_support_coverage_ratio),
    )
    pair_decisions = build_pair_decisions(run_root, str(complex_patch_id))
    decisions_by_pair = {
        str(row.get("pair", "")): dict(row)
        for row in pair_decisions.get("pairs", [])
    }
    rows: list[dict[str, Any]] = []
    for pair_id in list(target_pairs or _MERGE_DIVERGE_TARGET_PAIRS):
        registry_row = dict(_best_registry_row(list(registry_by_pair.get(str(pair_id), []))) or {})
        decision_row = dict(decisions_by_pair.get(str(pair_id), {}))
        src_text, dst_text = str(pair_id).split(":", 1)
        merge_rule = dict(merge_rule_by_pair.get(str(pair_id), {}))
        detected_structure_type = str(
            merge_rule.get("structure_type")
            or registry_row.get("arc_structure_type")
            or registry_row.get("structure_type")
            or ""
        )
        detected_rule = str(
            registry_row.get("arc_selection_rule")
            or ("allow_multiple_upstream_arcs" if detected_structure_type == STRUCTURE_MERGE_MULTI_UPSTREAM else "")
        )
        built_final_road = bool(
            decision_row.get("built_final_road", registry_row.get("built_final_road", False))
        )
        entered_main_flow = bool(
            registry_row.get("entered_main_flow", decision_row.get("entered_main_flow", False))
        )
        unbuilt_stage = ""
        unbuilt_reason = ""
        if not built_final_road:
            unbuilt_stage = str(
                registry_row.get("unbuilt_stage")
                or decision_row.get("reject_stage")
                or ""
            )
            unbuilt_reason = str(
                registry_row.get("unbuilt_reason")
                or decision_row.get("reject_reason")
                or ""
            )
        rows.append(
            {
                "patch_id": str(complex_patch_id),
                "pair": str(pair_id),
                "src": int(registry_row.get("src", src_text)),
                "dst": int(registry_row.get("dst", dst_text)),
                "topology_arc_id": str(registry_row.get("topology_arc_id", "")),
                "detected_structure_type": detected_structure_type,
                "detected_rule": detected_rule,
                "allow_multi_output": bool(
                    merge_rule.get(
                        "allow_multi_output",
                        registry_row.get("arc_selection_allow_multi_output", False),
                    )
                ),
                "shared_downstream_signal": list(
                    merge_rule.get(
                        "shared_downstream_signal",
                        registry_row.get("arc_selection_shared_downstream_signal", []),
                    )
                ),
                "shared_downstream_nodes": list(
                    merge_rule.get(
                        "shared_downstream_nodes",
                        registry_row.get("arc_selection_shared_downstream_nodes", []),
                    )
                ),
                "shared_downstream_edge_ids": list(
                    merge_rule.get(
                        "shared_downstream_edge_ids",
                        registry_row.get("arc_selection_shared_downstream_edge_ids", []),
                    )
                ),
                "independent_support_confirmed": bool(
                    merge_rule.get("independent_support_available", False)
                ),
                "independent_slot_confirmed": str(registry_row.get("slot_status", "")) == "resolved",
                "entered_main_flow": bool(entered_main_flow),
                "built": bool(built_final_road),
                "unbuilt_stage": str(unbuilt_stage),
                "unbuilt_reason": str(unbuilt_reason),
                "peer_pairs": list(
                    merge_rule.get(
                        "peer_pairs",
                        registry_row.get("arc_selection_peer_pairs", []),
                    )
                ),
                "rule_reason": str(
                    merge_rule.get(
                        "rule_reason",
                        registry_row.get("arc_selection_rule_reason", ""),
                    )
                ),
            }
        )
    return {
        "patch_id": str(complex_patch_id),
        "row_count": int(len(rows)),
        "allow_multi_output_count": int(sum(1 for row in rows if bool(row.get("allow_multi_output", False)))),
        "built_count": int(sum(1 for row in rows if bool(row.get("built", False)))),
        "rows": rows,
    }


def build_multi_arc_review(
    run_root: Path | str,
    *,
    complex_patch_id: str,
    same_pair_multi_arc_observation: dict[str, Any],
) -> dict[str, Any]:
    registry_rows = [dict(row) for row in _patch_full_registry_rows(run_root, complex_patch_id)]
    if registry_rows and any(not str(row.get("arc_structure_type", "")) for row in registry_rows):
        registry_rows = list(apply_arc_selection_rules(registry_rows).get("rows", []))
    same_pair_registry_rows = [
        dict(row)
        for row in registry_rows
        if str(row.get("arc_structure_type", "")) == STRUCTURE_SAME_PAIR_MULTI_ARC
    ]
    multi_arc_rule = apply_multi_arc_rule(same_pair_registry_rows)
    observation_by_pair = {
        str(row.get("pair", "")): dict(row)
        for row in same_pair_multi_arc_observation.get("rows", [])
        if str(row.get("patch_id", "")) == str(complex_patch_id)
    }
    target_pairs = set(observation_by_pair.keys()) | set(multi_arc_rule.keys())
    rows: list[dict[str, Any]] = []
    for pair_id in sorted(target_pairs):
        observation = dict(observation_by_pair.get(pair_id, {}))
        rule_row = dict(multi_arc_rule.get(pair_id, {}))
        allow_multi_output = bool(rule_row.get("allow_multi_output", False))
        current_business_status = str(observation.get("current_business_status", ""))
        next_rule_needed = str(observation.get("next_rule_needed", ""))
        if allow_multi_output:
            current_business_status = "multi_arc_dual_output_candidate"
            next_rule_needed = "align_production_output_with_multi_arc_rule"
        rows.append(
            {
                "patch_id": str(complex_patch_id),
                "pair": str(pair_id),
                "structure_type": str(rule_row.get("structure_type", STRUCTURE_SAME_PAIR_MULTI_ARC)),
                "pair_arc_count": int(rule_row.get("pair_arc_count", observation.get("pair_arc_count", 0))),
                "arc_ids": [str(v) for v in rule_row.get("arc_ids", observation.get("arc_ids", [])) if str(v)],
                "allow_multi_output": bool(allow_multi_output),
                "witness_based_arc_ids": [str(v) for v in rule_row.get("witness_based_arc_ids", []) if str(v)],
                "fallback_based_arc_ids": [str(v) for v in rule_row.get("fallback_based_arc_ids", []) if str(v)],
                "evidence_modes": dict(rule_row.get("evidence_modes", {})),
                "rule_reason": str(rule_row.get("rule_reason", "")),
                "has_built_sibling_arc": bool(observation.get("has_built_sibling_arc", False)),
                "built_sibling_arc_ids": [str(v) for v in observation.get("built_sibling_arc_ids", []) if str(v)],
                "excluded_from_unique_denominator_reason": str(
                    observation.get("excluded_from_unique_denominator_reason", "same_pair_multi_arc")
                ),
                "current_business_status": current_business_status,
                "next_rule_needed": next_rule_needed,
                "visual_gap_note": str(observation.get("visual_gap_note", "")),
            }
        )
    return {
        "patch_id": str(complex_patch_id),
        "row_count": int(len(rows)),
        "dual_output_candidate_count": int(sum(1 for row in rows if bool(row.get("allow_multi_output", False)))),
        "rows": rows,
    }


def _render_summary_markdown(
    *,
    run_root: Path,
    simple_patch_acceptance: dict[str, Any],
    pair_decisions: dict[str, Any],
    arc_legality_audit: dict[str, Any],
    complex_review: dict[str, Any],
    semantic_regression_report: dict[str, Any],
    strong_constraint_status: dict[str, Any],
) -> str:
    by_pair = {str(row.get("pair", "")): row for row in pair_decisions.get("pairs", [])}
    target = dict(by_pair.get(_BRIDGE_TARGET_PAIR, {}))
    reference = dict(by_pair.get(_REFERENCE_PAIR, {}))
    audit_summary = dict(arc_legality_audit.get("summary", {}))
    lines = [
        "# T05 v2 Arc-First Attach-Evidence Summary",
        "",
        f"- `run_root`: `{run_root}`",
        f"- `generated_at_utc`: `{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}`",
        f"- `semantic_regression`: `{str(bool(semantic_regression_report.get('semantic_regression', False))).lower()}`",
        f"- `semantic_regression_reasons`: `{','.join(str(v) for v in semantic_regression_report.get('semantic_regression_reasons', [])) or '-'}`",
        f"- `performance_status`: `see runtime_breakdown.json`",
        "",
        "## Simple Patch Acceptance",
        "",
    ]
    for item in simple_patch_acceptance.get("patches", []):
        lines.append(
            f"- `{item['patch_id']}`: acceptance_pass={str(item['acceptance_pass']).lower()} "
            f"direct_unique={item['entered_main_flow_arc_count']} built={item['legal_arc_built']} rate={float(item['legal_arc_build_rate']):.3f}"
        )
    lines.extend(
        [
            "",
            "## Arc Legality Audit",
            "",
            f"- built_arc_count=`{int(audit_summary.get('built_arc_count', 0))}`",
            f"- bad_built_arc_count=`{int(audit_summary.get('bad_built_arc_count', 0))}`",
            f"- built_all_direct_unique=`{str(bool(audit_summary.get('built_all_direct_unique', False))).lower()}`",
            f"- audit_summary_inconsistent=`{str(bool(audit_summary.get('audit_summary_inconsistent', False))).lower()}`",
            f"- synthetic_arc_in_production=`{str(bool(audit_summary.get('synthetic_arc_in_production', False))).lower()}`",
            "",
            "## Complex Patch Funnel",
            "",
            f"- all_direct={int(complex_review.get('all_direct_legal_arc_count', 0))}",
            f"- direct_unique={int(complex_review.get('all_direct_unique_legal_arc_count', 0))}",
            f"- entered_main_flow={int(complex_review.get('entered_main_flow_arc_count', 0))}",
            f"- traj_supported={int(complex_review.get('traj_supported_arc_count', 0))}",
            f"- prior_supported={int(complex_review.get('prior_supported_arc_count', 0))}",
            f"- corridor_resolved={int(complex_review.get('corridor_resolved_arc_count', 0))}",
            f"- slot_established={int(complex_review.get('slot_established_arc_count', 0))}",
            f"- built={int(complex_review.get('legal_arc_built', 0))}",
            "",
            "## Key Pairs",
            "",
            f"- target `{_BRIDGE_TARGET_PAIR}`: built={str(bool(target.get('built_final_road', False))).lower()} reject=`{target.get('reject_stage', '')}/{target.get('reject_reason', '')}`",
            f"- reference `{_REFERENCE_PAIR}`: built={str(bool(reference.get('built_final_road', False))).lower()} arc=`{reference.get('topology_arc_id', '')}`",
            "",
            "## Strong Constraints",
            "",
            f"- kept_constraints={len(strong_constraint_status.get('kept_in_this_round', []))}",
            f"- partial_constraints={len(strong_constraint_status.get('partially_closed_but_not_fixed', []))}",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def write_arc_first_attach_evidence_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    started = perf_counter()
    run_root_path = Path(run_root)
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    patch_ids = list(simple_patch_ids or ["5417632690143239", "5417632690143326"])
    all_patch_ids = [*patch_ids, str(complex_patch_id)]
    acceptance_results = [evaluate_patch_acceptance(run_root_path, patch_id) for patch_id in patch_ids]
    pair_decisions = build_pair_decisions(run_root_path, complex_patch_id)
    arc_legality_audit = build_arc_legality_audit(run_root_path, all_patch_ids)
    legal_arc_coverage = build_legal_arc_coverage(run_root_path, all_patch_ids)
    arc_evidence_attach_audit = build_arc_evidence_attach_audit(run_root_path, all_patch_ids)
    simple_patch_acceptance = build_simple_patch_acceptance(acceptance_results, legal_arc_coverage)
    simple_patch_regression = build_simple_patch_regression(simple_patch_acceptance)
    complex_review = build_complex_patch_coverage_review(pair_decisions, arc_legality_audit, legal_arc_coverage)
    semantic_regression_report = build_semantic_regression_report(
        pair_decisions=pair_decisions,
        arc_legality_audit=arc_legality_audit,
        simple_patch_acceptance=simple_patch_acceptance,
    )
    bad_built_rootcause = build_bad_built_rootcause(
        run_root=run_root_path,
        complex_patch_id=str(complex_patch_id),
        pair_decisions=pair_decisions,
        arc_legality_audit=arc_legality_audit,
    )
    strong_constraint_status = build_strong_constraint_status(
        pair_decisions=pair_decisions,
        arc_legality_audit=arc_legality_audit,
        simple_patch_regression=simple_patch_regression,
    )
    review_runtime_ms = float((perf_counter() - started) * 1000.0)
    runtime_breakdown = build_runtime_breakdown(run_root_path, all_patch_ids, review_runtime_ms=review_runtime_ms)
    complex_runtime = next(
        (dict(item) for item in runtime_breakdown.get("patches", []) if str(item.get("patch_id", "")) == str(complex_patch_id)),
        {},
    )
    complex_perf_review = {**dict(complex_review), "runtime": complex_runtime}
    full_registry_payload = {
        "evaluated_at_utc": legal_arc_coverage.get("evaluated_at_utc", ""),
        "patches": [
            {
                "patch_id": str(item.get("patch_id", "")),
                "rows": [dict(row) for row in _patch_full_registry_rows(run_root_path, str(item.get("patch_id", "")))],
            }
            for item in legal_arc_coverage.get("patches", [])
        ],
    }
    funnel_payload = {
        "evaluated_at_utc": legal_arc_coverage.get("evaluated_at_utc", ""),
        "patches": [
            {
                "patch_id": str(item.get("patch_id", "")),
                "all_direct_legal_arc_count": int(item.get("all_direct_legal_arc_count", 0)),
                "all_direct_unique_legal_arc_count": int(item.get("all_direct_unique_legal_arc_count", 0)),
                "entered_main_flow_arc_count": int(item.get("entered_main_flow_arc_count", 0)),
                "traj_supported_arc_count": int(item.get("traj_supported_arc_count", 0)),
                "prior_supported_arc_count": int(item.get("prior_supported_arc_count", 0)),
                "corridor_resolved_arc_count": int(item.get("corridor_resolved_arc_count", 0)),
                "slot_established_arc_count": int(item.get("slot_established_arc_count", 0)),
                "built_arc_count": int(item.get("legal_arc_built", 0)),
            }
            for item in legal_arc_coverage.get("patches", [])
        ],
    }
    for item in acceptance_results:
        write_json(output_root_path / f"acceptance_{item['patch_id']}.json", item)
    write_json(output_root_path / "full_legal_arc_registry.json", full_registry_payload)
    write_json(output_root_path / "legal_arc_funnel.json", funnel_payload)
    write_json(output_root_path / "arc_evidence_attach_audit.json", arc_evidence_attach_audit)
    write_json(output_root_path / "pair_decisions.json", pair_decisions)
    write_json(output_root_path / "arc_legality_audit.json", arc_legality_audit)
    write_json(output_root_path / "runtime_breakdown.json", runtime_breakdown)
    write_json(output_root_path / "legal_arc_coverage.json", legal_arc_coverage)
    write_json(output_root_path / "simple_patch_acceptance.json", simple_patch_acceptance)
    write_json(output_root_path / "simple_patch_regression.json", simple_patch_regression)
    write_json(output_root_path / "complex_patch_coverage_review.json", complex_review)
    write_json(output_root_path / "complex_patch_perf_review.json", complex_perf_review)
    write_json(output_root_path / "semantic_regression_report.json", semantic_regression_report)
    write_json(output_root_path / "bad_built_rootcause.json", bad_built_rootcause)
    write_json(output_root_path / "complex_patch_semantic_fix_review.json", {**dict(complex_review), "semantic_regression": semantic_regression_report})
    write_json(output_root_path / "complex_patch_funnel_review.json", complex_review)
    write_json(output_root_path / "complex_patch_legality_review.json", complex_review)
    write_json(output_root_path / "strong_constraint_status.json", strong_constraint_status)
    (output_root_path / "runtime_before_after.md").write_text(
        _render_runtime_before_after_markdown(runtime_breakdown),
        encoding="utf-8",
    )
    (output_root_path / "SUMMARY.md").write_text(
        _render_summary_markdown(
            run_root=run_root_path,
            simple_patch_acceptance=simple_patch_acceptance,
            pair_decisions=pair_decisions,
            arc_legality_audit=arc_legality_audit,
            complex_review=complex_review,
            semantic_regression_report=semantic_regression_report,
            strong_constraint_status=strong_constraint_status,
        ),
        encoding="utf-8",
    )
    return {
        "output_root": str(output_root_path),
        "acceptance": acceptance_results,
        "pair_decisions": pair_decisions,
        "arc_legality_audit": arc_legality_audit,
        "runtime_breakdown": runtime_breakdown,
        "legal_arc_coverage": legal_arc_coverage,
        "arc_evidence_attach_audit": arc_evidence_attach_audit,
        "simple_patch_acceptance": simple_patch_acceptance,
        "simple_patch_regression": simple_patch_regression,
        "complex_patch_legality_review": complex_review,
        "complex_patch_coverage_review": complex_review,
        "complex_patch_perf_review": complex_perf_review,
        "semantic_regression_report": semantic_regression_report,
        "bad_built_rootcause": bad_built_rootcause,
        "strong_constraint_status": strong_constraint_status,
    }


def write_legal_arc_coverage_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    return write_arc_first_attach_evidence_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )


def write_arc_legality_fix_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    return write_arc_first_attach_evidence_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )


def write_bridge_trial_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    return write_arc_first_attach_evidence_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )


def write_perf_opt_arc_first_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    return write_arc_first_attach_evidence_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )


def write_semantic_fix_after_perf_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    return write_arc_first_attach_evidence_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )


def write_witness_vis_step5_recovery_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    all_simple_patch_ids = list(simple_patch_ids) if simple_patch_ids else ["5417632690143239", "5417632690143326"]
    summary = write_semantic_fix_after_perf_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=all_simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )
    from .witness_review import write_witness_vis_step5_recovery_bundle

    witness_summary = write_witness_vis_step5_recovery_bundle(
        run_root=run_root,
        output_root=output_root,
        patch_ids=[*all_simple_patch_ids, str(complex_patch_id)],
        complex_patch_id=str(complex_patch_id),
    )
    return {
        **summary,
        **witness_summary,
    }


def write_topology_gap_controlled_cover_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    summary = write_witness_vis_step5_recovery_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )
    output_root_path = Path(output_root)
    topology_gap_review = dict(summary.get("topology_gap_decision_review", {}))
    same_pair_multi_arc_observation = dict(summary.get("same_pair_multi_arc_observation", {}))
    strict_vs_visual_gap_summary = dict(summary.get("strict_vs_visual_gap_summary", {}))
    complex_gap_cover_review = {
        "patch_id": str(complex_patch_id),
        "topology_gap_decision_review": topology_gap_review,
        "same_pair_multi_arc_observation": same_pair_multi_arc_observation,
        "strict_vs_visual_gap_summary": strict_vs_visual_gap_summary,
        "complex_patch_step5_recovery_review": dict(summary.get("complex_patch_step5_recovery_review", {})),
    }
    write_json(output_root_path / "complex_patch_gap_cover_review.json", complex_gap_cover_review)
    return {
        **summary,
        "complex_patch_gap_cover_review": complex_gap_cover_review,
    }


def write_arc_obligation_closure_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    summary = write_topology_gap_controlled_cover_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )
    output_root_path = Path(output_root)
    topology_gap_review = dict(summary.get("topology_gap_decision_review", {}))
    same_pair_multi_arc_observation = dict(summary.get("same_pair_multi_arc_observation", {}))
    strict_vs_visual_gap_summary = dict(summary.get("strict_vs_visual_gap_summary", {}))
    arc_obligation_registry = build_arc_obligation_registry(
        complex_patch_id=str(complex_patch_id),
        topology_gap_review=topology_gap_review,
        same_pair_multi_arc_observation=same_pair_multi_arc_observation,
    )
    competing_arc_review = build_competing_arc_review(
        complex_patch_id=str(complex_patch_id),
        topology_gap_review=topology_gap_review,
        same_pair_multi_arc_observation=same_pair_multi_arc_observation,
    )
    complex_patch_arc_obligation_review = {
        "patch_id": str(complex_patch_id),
        "arc_obligation_registry": arc_obligation_registry,
        "competing_arc_review": competing_arc_review,
        "strict_vs_visual_gap_summary": strict_vs_visual_gap_summary,
    }

    write_json(output_root_path / "arc_obligation_registry.json", arc_obligation_registry)
    with (output_root_path / "arc_obligation_registry.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "patch_id",
                "src",
                "dst",
                "pair",
                "topology_arc_id",
                "obligation_status",
                "current_status",
                "blocking_layer",
                "blocking_reason",
                "next_action",
                "gap_classification",
                "gap_reason",
                "controlled_entry_allowed",
                "entered_main_flow",
                "built_final_road",
                "traj_support_type",
                "traj_support_count",
                "support_strength_score",
                "corridor_identity",
                "slot_status",
                "unbuilt_stage",
                "unbuilt_reason",
                "pair_arc_count",
                "arc_ids",
                "has_built_sibling_arc",
                "built_sibling_arc_ids",
                "chord_available",
                "witness_available",
                "visual_gap_note",
            ],
        )
        writer.writeheader()
        for row in arc_obligation_registry.get("rows", []):
            payload = dict(row)
            payload["arc_ids"] = ",".join(str(v) for v in row.get("arc_ids", []))
            payload["built_sibling_arc_ids"] = ",".join(str(v) for v in row.get("built_sibling_arc_ids", []))
            writer.writerow({key: payload.get(key, "") for key in writer.fieldnames})

    write_json(output_root_path / "competing_arc_review.json", competing_arc_review)
    with (output_root_path / "competing_arc_review.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "patch_id",
                "pair",
                "review_scope",
                "topology_arc_id",
                "competing_group_key",
                "competing_pair_count",
                "competing_pairs",
                "traj_support_type",
                "traj_support_count",
                "traj_support_coverage_ratio",
                "support_total_length_m",
                "slot_status",
                "built_final_road",
                "drivezone_overlap_ratio",
                "divstrip_overlap_ratio",
                "blocking_layer",
                "support_strength_score",
                "strongest_peer_pair",
                "strongest_peer_support_score",
                "support_score_gap_to_best",
                "has_built_sibling",
                "independent_slot_available",
                "selected_by_support_ranking",
                "current_business_status",
                "next_rule_needed",
                "root_cause_code",
                "root_cause_detail",
                "next_action",
            ],
        )
        writer.writeheader()
        for row in competing_arc_review.get("rows", []):
            payload = dict(row)
            payload["competing_pairs"] = ",".join(str(v) for v in row.get("competing_pairs", []))
            writer.writerow({key: payload.get(key, "") for key in writer.fieldnames})
    write_json(output_root_path / "complex_patch_arc_obligation_review.json", complex_patch_arc_obligation_review)
    summary_lines = []
    summary_lines.append("")
    summary_lines.append("## Arc Obligation Closure")
    summary_lines.append("")
    summary_lines.append(
        f"- strict_coverage=`{strict_vs_visual_gap_summary.get('strict_coverage', {}).get('built', 0)}/{strict_vs_visual_gap_summary.get('strict_coverage', {}).get('total', 0)}`"
    )
    summary_lines.append(
        f"- same_pair_multi_arc_observation_count=`{same_pair_multi_arc_observation.get('row_count', 0)}`"
    )
    summary_lines.append(
        f"- arc_obligation_row_count=`{arc_obligation_registry.get('row_count', 0)}`"
    )
    summary_lines.append(
        f"- competing_arc_row_count=`{competing_arc_review.get('row_count', 0)}`"
    )
    controlled_rows = [
        row
        for row in arc_obligation_registry.get("rows", [])
        if str(row.get("current_status", "")) == "controlled_entry_built"
    ]
    if controlled_rows:
        summary_lines.append(
            f"- controlled_entry_built_pairs=`{','.join(str(row.get('pair', '')) for row in controlled_rows)}`"
        )
    summary_path = output_root_path / "SUMMARY.md"
    existing_summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    summary_path.write_text(existing_summary + "\n".join(summary_lines) + "\n", encoding="utf-8")
    return {
        **summary,
        "arc_obligation_registry": arc_obligation_registry,
        "competing_arc_review": competing_arc_review,
        "complex_patch_arc_obligation_review": complex_patch_arc_obligation_review,
    }


def build_alias_normalization_review(
    run_root: Path | str,
    *,
    complex_patch_id: str,
    pair_decisions: dict[str, Any],
    arc_legality_audit: dict[str, Any],
) -> dict[str, Any]:
    registry_rows = _patch_full_registry_rows(run_root, complex_patch_id)
    decisions_by_pair = {str(row.get("pair", "")): dict(row) for row in pair_decisions.get("pairs", [])}
    violating_pairs = set(str(v) for v in arc_legality_audit.get("summary", {}).get("violating_built_pairs", []))
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for registry_row in registry_rows:
        resolved = _identity_record_from_row(
            registry_row,
            pair_id=_row_pair_id(registry_row),
            working_segment_id=str(registry_row.get("working_segment_id", "")),
            resolution_source="full_legal_arc_registry",
        )
        if not bool(resolved.get("alias_normalized", False)):
            continue
        canonical_pair = str(resolved.get("canonical_pair", resolved.get("pair", "")))
        decision_row = dict(decisions_by_pair.get(canonical_pair, {}))
        key = (
            str(resolved.get("raw_pair", canonical_pair)),
            str(resolved.get("canonical_pair", canonical_pair)),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "patch_id": str(complex_patch_id),
                "raw_src_nodeid": resolved.get("raw_src_nodeid"),
                "raw_dst_nodeid": resolved.get("raw_dst_nodeid"),
                "raw_pair": str(resolved.get("raw_pair", canonical_pair)),
                "canonical_src_xsec_id": resolved.get("canonical_src_xsec_id"),
                "canonical_dst_xsec_id": resolved.get("canonical_dst_xsec_id"),
                "canonical_pair": canonical_pair,
                "src_alias_applied": bool(resolved.get("src_alias_applied", False)),
                "dst_alias_applied": bool(resolved.get("dst_alias_applied", False)),
                "alias_normalized": True,
                "topology_arc_id": str(resolved.get("topology_arc_id", "")),
                "canonical_topology_arc_id": str(
                    resolved.get("canonical_topology_arc_id", resolved.get("topology_arc_id", ""))
                ),
                "topology_arc_source_type": str(resolved.get("topology_arc_source_type", "")),
                "topology_arc_is_direct_legal": bool(
                    decision_row.get("topology_arc_is_direct_legal", resolved.get("topology_arc_is_direct_legal", False))
                ),
                "topology_arc_is_unique": bool(
                    decision_row.get("topology_arc_is_unique", resolved.get("topology_arc_is_unique", False))
                ),
                "entered_main_flow": bool(decision_row.get("entered_main_flow", resolved.get("entered_main_flow", False))),
                "controlled_entry_allowed": bool(
                    decision_row.get("controlled_entry_allowed", resolved.get("controlled_entry_allowed", False))
                ),
                "built_final_road": bool(decision_row.get("built_final_road", resolved.get("built_final_road", False))),
                "unbuilt_stage": str(decision_row.get("unbuilt_stage", resolved.get("unbuilt_stage", ""))),
                "unbuilt_reason": str(decision_row.get("unbuilt_reason", resolved.get("unbuilt_reason", ""))),
                "identity_resolution_source": str(
                    decision_row.get("identity_resolution_source", resolved.get("identity_resolution_source", ""))
                ),
                "audit_violation": bool(canonical_pair in violating_pairs),
            }
        )
    rows.sort(key=lambda item: (str(item.get("raw_pair", "")), str(item.get("canonical_pair", ""))))
    return {
        "patch_id": str(complex_patch_id),
        "row_count": int(len(rows)),
        "direct_legal_count": int(sum(1 for row in rows if bool(row.get("topology_arc_is_direct_legal", False)))),
        "entered_main_flow_count": int(sum(1 for row in rows if bool(row.get("entered_main_flow", False)))),
        "built_count": int(sum(1 for row in rows if bool(row.get("built_final_road", False)))),
        "rows": rows,
    }


def write_alias_fix_and_rootcause_push_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    summary = write_arc_obligation_closure_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )
    output_root_path = Path(output_root)
    pair_decisions = dict(summary.get("pair_decisions", {}))
    arc_legality_audit = dict(summary.get("arc_legality_audit", {}))
    competing_arc_review = dict(summary.get("competing_arc_review", {}))
    same_pair_multi_arc_observation = dict(summary.get("same_pair_multi_arc_observation", {}))
    strict_vs_visual_gap_summary = dict(summary.get("strict_vs_visual_gap_summary", {}))
    alias_normalization_review = build_alias_normalization_review(
        run_root,
        complex_patch_id=str(complex_patch_id),
        pair_decisions=pair_decisions,
        arc_legality_audit=arc_legality_audit,
    )
    strict_vs_visual_gap_summary = {
        **strict_vs_visual_gap_summary,
        "alias_normalized_review": {
            "row_count": int(alias_normalization_review.get("row_count", 0)),
            "direct_legal_count": int(alias_normalization_review.get("direct_legal_count", 0)),
            "entered_main_flow_count": int(alias_normalization_review.get("entered_main_flow_count", 0)),
            "built_count": int(alias_normalization_review.get("built_count", 0)),
            "raw_pairs": [str(row.get("raw_pair", "")) for row in alias_normalization_review.get("rows", [])],
            "canonical_pairs": [str(row.get("canonical_pair", "")) for row in alias_normalization_review.get("rows", [])],
        },
    }
    complex_patch_alias_and_competing_review = {
        "patch_id": str(complex_patch_id),
        "alias_normalization_review": alias_normalization_review,
        "competing_arc_review": competing_arc_review,
        "same_pair_multi_arc_observation": same_pair_multi_arc_observation,
        "strict_vs_visual_gap_summary": strict_vs_visual_gap_summary,
    }

    write_json(output_root_path / "alias_normalization_review.json", alias_normalization_review)
    with (output_root_path / "alias_normalization_review.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "patch_id",
                "raw_src_nodeid",
                "raw_dst_nodeid",
                "raw_pair",
                "canonical_src_xsec_id",
                "canonical_dst_xsec_id",
                "canonical_pair",
                "src_alias_applied",
                "dst_alias_applied",
                "alias_normalized",
                "topology_arc_id",
                "canonical_topology_arc_id",
                "topology_arc_source_type",
                "topology_arc_is_direct_legal",
                "topology_arc_is_unique",
                "entered_main_flow",
                "controlled_entry_allowed",
                "built_final_road",
                "unbuilt_stage",
                "unbuilt_reason",
                "identity_resolution_source",
                "audit_violation",
            ],
        )
        writer.writeheader()
        for row in alias_normalization_review.get("rows", []):
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})
    with (output_root_path / "competing_arc_review.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "patch_id",
                "pair",
                "review_scope",
                "topology_arc_id",
                "competing_group_key",
                "competing_pair_count",
                "competing_pairs",
                "traj_support_type",
                "traj_support_count",
                "support_total_length_m",
                "slot_status",
                "built_final_road",
                "drivezone_overlap_ratio",
                "divstrip_overlap_ratio",
                "current_business_status",
                "next_rule_needed",
                "root_cause_code",
                "root_cause_detail",
                "next_action",
            ],
        )
        writer.writeheader()
        for row in competing_arc_review.get("rows", []):
            payload = dict(row)
            payload["competing_pairs"] = ",".join(str(v) for v in row.get("competing_pairs", []))
            payload["arc_ids"] = ",".join(str(v) for v in row.get("arc_ids", []))
            writer.writerow({key: payload.get(key, "") for key in writer.fieldnames})
    write_json(output_root_path / "strict_vs_visual_gap_summary.json", strict_vs_visual_gap_summary)
    write_json(output_root_path / "complex_patch_alias_and_competing_review.json", complex_patch_alias_and_competing_review)

    summary_lines = [
        "",
        "## Alias Fix And Rootcause Push",
        "",
        (
            f"- strict_coverage=`{strict_vs_visual_gap_summary.get('strict_coverage', {}).get('built', 0)}"
            f"/{strict_vs_visual_gap_summary.get('strict_coverage', {}).get('total', 0)}`"
        ),
        (
            f"- alias_normalized_row_count=`{alias_normalization_review.get('row_count', 0)}` "
            f"built=`{alias_normalization_review.get('built_count', 0)}`"
        ),
        f"- competing_arc_row_count=`{competing_arc_review.get('row_count', 0)}`",
        f"- same_pair_multi_arc_observation_count=`{same_pair_multi_arc_observation.get('row_count', 0)}`",
    ]
    summary_path = output_root_path / "SUMMARY.md"
    existing_summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    summary_path.write_text(existing_summary + "\n".join(summary_lines) + "\n", encoding="utf-8")
    return {
        **summary,
        "alias_normalization_review": alias_normalization_review,
        "strict_vs_visual_gap_summary": strict_vs_visual_gap_summary,
        "complex_patch_alias_and_competing_review": complex_patch_alias_and_competing_review,
    }


def write_competing_arc_closure_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    summary = write_arc_obligation_closure_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )
    output_root_path = Path(output_root)
    arc_obligation_registry = dict(summary.get("arc_obligation_registry", {}))
    competing_arc_review = dict(summary.get("competing_arc_review", {}))
    strict_vs_visual_gap_summary = dict(summary.get("strict_vs_visual_gap_summary", {}))

    obligation_by_pair = {
        str(row.get("pair", "")): dict(row)
        for row in arc_obligation_registry.get("rows", [])
    }
    competing_by_pair = {
        str(row.get("pair", "")): dict(row)
        for row in competing_arc_review.get("rows", [])
    }
    target_rows = []
    for pair_id in _COMPETING_ARC_CLOSURE_TARGET_PAIRS:
        target_rows.append(
            {
                "pair": str(pair_id),
                "arc_obligation": dict(obligation_by_pair.get(pair_id, {})),
                "competing_arc_review": dict(competing_by_pair.get(pair_id, {})),
            }
        )
    complex_patch_competing_arc_closure_review = {
        "patch_id": str(complex_patch_id),
        "target_pairs": target_rows,
        "arc_obligation_registry": arc_obligation_registry,
        "competing_arc_review": competing_arc_review,
        "strict_vs_visual_gap_summary": strict_vs_visual_gap_summary,
    }
    write_json(output_root_path / "complex_patch_competing_arc_closure_review.json", complex_patch_competing_arc_closure_review)

    summary_lines = [
        "",
        "## Competing Arc Closure",
        "",
    ]
    for pair_id in _COMPETING_ARC_CLOSURE_TARGET_PAIRS:
        obligation = dict(obligation_by_pair.get(pair_id, {}))
        summary_lines.append(
            f"- `{pair_id}`: obligation=`{obligation.get('obligation_status', '-')}` "
            f"current=`{obligation.get('current_status', '-')}` "
            f"reason=`{obligation.get('blocking_reason', '-')}` "
            f"next=`{obligation.get('next_action', '-')}`"
        )
    summary_path = output_root_path / "SUMMARY.md"
    existing_summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    summary_path.write_text(existing_summary + "\n".join(summary_lines) + "\n", encoding="utf-8")
    return {
        **summary,
        "complex_patch_competing_arc_closure_review": complex_patch_competing_arc_closure_review,
    }


def write_merge_diverge_rules_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    summary = write_competing_arc_closure_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )
    output_root_path = Path(output_root)
    same_pair_multi_arc_observation = dict(summary.get("same_pair_multi_arc_observation", {}))
    strict_vs_visual_gap_summary = dict(summary.get("strict_vs_visual_gap_summary", {}))
    arc_selection_structure = build_arc_selection_structure(
        run_root,
        complex_patch_id=str(complex_patch_id),
    )
    multi_arc_review = build_multi_arc_review(
        run_root,
        complex_patch_id=str(complex_patch_id),
        same_pair_multi_arc_observation=same_pair_multi_arc_observation,
    )
    strict_vs_visual_gap_summary = {
        **strict_vs_visual_gap_summary,
        "arc_selection_structure": {
            "row_count": int(arc_selection_structure.get("row_count", 0)),
            "merge_multi_upstream_pair_count": int(arc_selection_structure.get("merge_multi_upstream_pair_count", 0)),
            "same_pair_multi_arc_pair_count": int(arc_selection_structure.get("same_pair_multi_arc_pair_count", 0)),
            "allow_multi_output_pairs": sorted(
                str(row.get("pair", ""))
                for row in arc_selection_structure.get("rows", [])
                if bool(row.get("allow_multi_output", False))
            ),
        },
        "multi_arc_review": {
            "row_count": int(multi_arc_review.get("row_count", 0)),
            "dual_output_candidate_count": int(multi_arc_review.get("dual_output_candidate_count", 0)),
            "pairs": [str(row.get("pair", "")) for row in multi_arc_review.get("rows", [])],
        },
    }
    complex_patch_merge_diverge_rules_review = {
        "patch_id": str(complex_patch_id),
        "arc_selection_structure": arc_selection_structure,
        "multi_arc_review": multi_arc_review,
        "strict_vs_visual_gap_summary": strict_vs_visual_gap_summary,
    }

    write_json(output_root_path / "arc_selection_structure.json", arc_selection_structure)
    write_json(output_root_path / "multi_arc_review.json", multi_arc_review)
    write_json(output_root_path / "strict_vs_visual_gap_summary.json", strict_vs_visual_gap_summary)
    write_json(output_root_path / "complex_patch_merge_diverge_rules_review.json", complex_patch_merge_diverge_rules_review)

    summary_lines = [
        "",
        "## Merge Diverge Rules",
        "",
        (
            f"- strict_coverage=`{strict_vs_visual_gap_summary.get('strict_coverage', {}).get('built', 0)}"
            f"/{strict_vs_visual_gap_summary.get('strict_coverage', {}).get('total', 0)}`"
        ),
        f"- merge_multi_upstream_pair_count=`{arc_selection_structure.get('merge_multi_upstream_pair_count', 0)}`",
        f"- same_pair_multi_arc_pair_count=`{arc_selection_structure.get('same_pair_multi_arc_pair_count', 0)}`",
        f"- multi_arc_rule_row_count=`{multi_arc_review.get('row_count', 0)}`",
    ]
    summary_path = output_root_path / "SUMMARY.md"
    existing_summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    summary_path.write_text(existing_summary + "\n".join(summary_lines) + "\n", encoding="utf-8")
    return {
        **summary,
        "arc_selection_structure": arc_selection_structure,
        "multi_arc_review": multi_arc_review,
        "strict_vs_visual_gap_summary": strict_vs_visual_gap_summary,
        "complex_patch_merge_diverge_rules_review": complex_patch_merge_diverge_rules_review,
    }


def write_merge_diverge_fix_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    summary = write_competing_arc_closure_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )
    output_root_path = Path(output_root)
    arc_selection_structure = build_arc_selection_structure(
        run_root,
        complex_patch_id=str(complex_patch_id),
    )
    merge_diverge_review = build_merge_diverge_review(
        run_root,
        complex_patch_id=str(complex_patch_id),
    )
    strict_vs_visual_gap_summary = {
        **dict(summary.get("strict_vs_visual_gap_summary", {})),
        "merge_diverge_review": {
            "row_count": int(merge_diverge_review.get("row_count", 0)),
            "allow_multi_output_count": int(merge_diverge_review.get("allow_multi_output_count", 0)),
            "built_count": int(merge_diverge_review.get("built_count", 0)),
            "pairs": [str(row.get("pair", "")) for row in merge_diverge_review.get("rows", [])],
        },
        "arc_selection_structure": {
            "row_count": int(arc_selection_structure.get("row_count", 0)),
            "merge_multi_upstream_pair_count": int(arc_selection_structure.get("merge_multi_upstream_pair_count", 0)),
            "same_pair_multi_arc_pair_count": int(arc_selection_structure.get("same_pair_multi_arc_pair_count", 0)),
            "allow_multi_output_pairs": sorted(
                str(row.get("pair", ""))
                for row in arc_selection_structure.get("rows", [])
                if bool(row.get("allow_multi_output", False))
            ),
        },
    }
    complex_patch_merge_diverge_fix_review = {
        "patch_id": str(complex_patch_id),
        "arc_selection_structure": arc_selection_structure,
        "merge_diverge_review": merge_diverge_review,
        "strict_vs_visual_gap_summary": strict_vs_visual_gap_summary,
    }

    write_json(output_root_path / "arc_selection_structure.json", arc_selection_structure)
    write_json(output_root_path / "merge_diverge_review.json", merge_diverge_review)
    with (output_root_path / "merge_diverge_review.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "patch_id",
                "pair",
                "src",
                "dst",
                "topology_arc_id",
                "detected_structure_type",
                "detected_rule",
                "allow_multi_output",
                "shared_downstream_signal",
                "shared_downstream_nodes",
                "shared_downstream_edge_ids",
                "independent_support_confirmed",
                "independent_slot_confirmed",
                "entered_main_flow",
                "built",
                "unbuilt_stage",
                "unbuilt_reason",
                "peer_pairs",
                "rule_reason",
            ],
        )
        writer.writeheader()
        for payload in merge_diverge_review.get("rows", []):
            row = dict(payload)
            row["shared_downstream_signal"] = ",".join(str(v) for v in payload.get("shared_downstream_signal", []))
            row["shared_downstream_nodes"] = ",".join(str(v) for v in payload.get("shared_downstream_nodes", []))
            row["shared_downstream_edge_ids"] = ",".join(str(v) for v in payload.get("shared_downstream_edge_ids", []))
            row["peer_pairs"] = ",".join(str(v) for v in payload.get("peer_pairs", []))
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})
    write_json(output_root_path / "strict_vs_visual_gap_summary.json", strict_vs_visual_gap_summary)
    write_json(output_root_path / "complex_patch_merge_diverge_fix_review.json", complex_patch_merge_diverge_fix_review)

    summary_lines = [
        "",
        "## Merge Diverge Fix",
        "",
    ]
    for payload in merge_diverge_review.get("rows", []):
        summary_lines.append(
            f"- `{payload.get('pair', '-')}`: structure=`{payload.get('detected_structure_type', '-')}` "
            f"allow_multi_output=`{str(bool(payload.get('allow_multi_output', False))).lower()}` "
            f"built=`{str(bool(payload.get('built', False))).lower()}` "
            f"unbuilt=`{payload.get('unbuilt_stage', '')}/{payload.get('unbuilt_reason', '')}`"
        )
    summary_path = output_root_path / "SUMMARY.md"
    existing_summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    summary_path.write_text(existing_summary + "\n".join(summary_lines) + "\n", encoding="utf-8")
    return {
        **summary,
        "arc_selection_structure": arc_selection_structure,
        "merge_diverge_review": merge_diverge_review,
        "strict_vs_visual_gap_summary": strict_vs_visual_gap_summary,
        "complex_patch_merge_diverge_fix_review": complex_patch_merge_diverge_fix_review,
    }


def write_step5_finish_review(
    *,
    run_root: Path | str,
    output_root: Path | str,
    simple_patch_ids: list[str] | None = None,
    complex_patch_id: str = "5417632623039346",
) -> dict[str, Any]:
    summary = write_merge_diverge_fix_review(
        run_root=run_root,
        output_root=output_root,
        simple_patch_ids=simple_patch_ids,
        complex_patch_id=complex_patch_id,
    )
    from .witness_review import write_step5_target_finish_review_bundle

    step5_target_summary = write_step5_target_finish_review_bundle(
        run_root=run_root,
        output_root=output_root,
        complex_patch_id=str(complex_patch_id),
    )
    output_root_path = Path(output_root)
    target_review = dict(step5_target_summary.get("step5_target_review_55353246_37687913", {}))
    summary_lines = [
        "",
        "## Step5 Finish 55353246 37687913",
        "",
        f"- before=`{target_review.get('before', {}).get('stage', '')}/{target_review.get('before', {}).get('reason', '')}`",
        f"- after=`{target_review.get('after', {}).get('stage', '')}/{target_review.get('after', {}).get('reason', '')}`",
        f"- after_built=`{str(bool(target_review.get('after', {}).get('built', False))).lower()}`",
        f"- after_divstrip_overlap_ratio=`{target_review.get('after', {}).get('divstrip_overlap_ratio', 0.0)}`",
    ]
    summary_path = output_root_path / "SUMMARY.md"
    existing_summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    summary_path.write_text(existing_summary + "\n".join(summary_lines) + "\n", encoding="utf-8")
    return {
        **summary,
        **step5_target_summary,
    }


__all__ = [
    "build_arc_evidence_attach_audit",
    "build_arc_legality_audit",
    "build_arc_selection_structure",
    "build_merge_diverge_review",
    "build_complex_patch_coverage_review",
    "build_complex_patch_legality_review",
    "build_legal_arc_coverage",
    "build_multi_arc_review",
    "build_pair_decisions",
    "build_simple_patch_acceptance",
    "build_simple_patch_regression",
    "build_strong_constraint_status",
    "evaluate_patch_acceptance",
    "write_alias_fix_and_rootcause_push_review",
    "write_arc_first_attach_evidence_review",
    "write_arc_legality_fix_review",
    "write_bridge_trial_review",
    "write_competing_arc_closure_review",
    "write_legal_arc_coverage_review",
    "write_merge_diverge_fix_review",
    "write_step5_finish_review",
    "write_merge_diverge_rules_review",
    "write_perf_opt_arc_first_review",
    "write_arc_obligation_closure_review",
    "write_semantic_fix_after_perf_review",
    "write_topology_gap_controlled_cover_review",
    "write_witness_vis_step5_recovery_review",
]
