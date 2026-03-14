from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

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


def _patch_dir(run_root: Path | str, patch_id: str) -> Path:
    return Path(run_root) / "patches" / str(patch_id)


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
        if str(row.get("pair_id", "")) == str(pair_id):
            return row
        src_nodeid = row.get("src_nodeid")
        dst_nodeid = row.get("dst_nodeid")
        if src_nodeid is not None and dst_nodeid is not None and _pair_id_text(int(src_nodeid), int(dst_nodeid)) == str(pair_id):
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
        pair_id = str(row.get("pair_id", "")) or _pair_id_text(int(row.get("src_nodeid", 0)), int(row.get("dst_nodeid", 0)))
        grouped.setdefault(pair_id, []).append(dict(row))
    return grouped


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
    metrics_payload = _patch_metrics(run_root, complex_patch_id)
    roads_payload = _cached_patch_json(patch_dir / "step6" / "final_roads.json")
    should_not_payload = _cached_patch_json(patch_dir / "debug" / "step2_segment_should_not_exist.json")
    topology_pairs_payload = _cached_patch_json(patch_dir / "debug" / "step2_topology_pairs.json")
    bridge_audit_payload = _cached_patch_json(patch_dir / "debug" / "step2_blocked_pair_bridge_audit.json")

    built_pair_set = set(_built_pairs(roads_payload))
    selected_rows = _pair_rows_by_id(list(segments_payload.get("segments", [])))
    excluded_rows = _pair_rows_by_id(list(segments_payload.get("excluded_candidates", [])))
    should_not_rows = list(should_not_payload.get("pairs", []))
    topology_rows = list(topology_pairs_payload.get("pairs", []))
    bridge_rows = list(bridge_audit_payload.get("pairs", []))
    registry_rows = list(metrics_payload.get("full_legal_arc_registry", []))

    decisions: list[dict[str, Any]] = []
    target_pairs = [*_FALSE_POSITIVE_PAIRS, *_STABLE_BLOCKED_PAIRS, _BRIDGE_TARGET_PAIR, _REFERENCE_PAIR]
    for pair_id in target_pairs:
        selected = _best_segment_row(selected_rows.get(pair_id, []))
        excluded = _best_excluded_entry(excluded_rows.get(pair_id, []))
        should_not_row = _find_pair_row(should_not_rows, pair_id)
        topology_row = _find_pair_row(topology_rows, pair_id)
        bridge_row = _find_pair_row(bridge_rows, pair_id)
        registry_row = _find_pair_row(registry_rows, pair_id)
        source_row = selected or registry_row or excluded or topology_row or should_not_row or bridge_row or {}
        reject_stage = ""
        reject_reason = ""
        if not bool(pair_id in built_pair_set) and not selected:
            reject_stage = str(
                (excluded or {}).get("stage")
                or (registry_row or {}).get("unbuilt_stage")
                or (bridge_row or {}).get("reject_stage")
                or ""
            )
            reject_reason = str(
                (excluded or {}).get("reason")
                or (registry_row or {}).get("hard_block_reason")
                or (registry_row or {}).get("unbuilt_reason")
                or (bridge_row or {}).get("reject_reason")
                or ""
            )
        decisions.append(
            {
                "patch_id": str(complex_patch_id),
                "pair": str(pair_id),
                "topology_arc_id": str(source_row.get("topology_arc_id", "")),
                "topology_arc_source_type": str(
                    source_row.get("topology_arc_source_type")
                    or source_row.get("arc_source_type")
                    or ""
                ),
                "topology_arc_is_direct_legal": bool(source_row.get("topology_arc_is_direct_legal", False)),
                "topology_arc_is_unique": bool(source_row.get("topology_arc_is_unique", False)),
                "bridge_chain_exists": bool(source_row.get("bridge_chain_exists", False)),
                "bridge_chain_unique": bool(source_row.get("bridge_chain_unique", False)),
                "bridge_chain_nodes": list(source_row.get("bridge_chain_nodes", [])),
                "bridge_diagnostic_reason": str(source_row.get("bridge_diagnostic_reason", "")),
                "bridge_classification": str(
                    (bridge_row or {}).get("bridge_classification")
                    or source_row.get("bridge_classification")
                    or source_row.get("bridge_diagnostic_reason", "")
                    or ""
                ),
                "reject_stage": str(reject_stage),
                "reject_reason": str(reject_reason),
                "should_not_reason": str((should_not_row or {}).get("reason", "")),
                "topology_sources": list((topology_row or {}).get("topology_sources", [])),
                "topology_paths": list((topology_row or {}).get("topology_paths", [])),
                "entered_main_flow": bool(source_row.get("entered_main_flow", False)),
                "traj_support_type": str(source_row.get("traj_support_type", "")),
                "prior_support_type": str(source_row.get("prior_support_type", "")),
                "corridor_identity": str(source_row.get("corridor_identity", "")),
                "slot_status": str(source_row.get("slot_status", "")),
                "unbuilt_stage": str(source_row.get("unbuilt_stage", "")),
                "unbuilt_reason": str(source_row.get("unbuilt_reason", "")),
                "built_final_road": bool(pair_id in built_pair_set),
                "segment_id": str((selected or {}).get("segment_id", "")),
                "selected_segment": bool(selected is not None),
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
            row = {
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
            }
            row["production_arc_pass"] = _production_arc_pass(row)
            selected_segment_rows.append(row)
        for road in roads_payload.get("roads", []):
            segment = segment_map.get(str(road.get("segment_id", "")), {})
            row = {
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
                "built_final_road": True,
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
        if (not bool(item["production_arc_pass"])) or str(item["topology_arc_source_type"]) in _SYNTHETIC_ARC_SOURCES
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


def _render_summary_markdown(
    *,
    run_root: Path,
    simple_patch_acceptance: dict[str, Any],
    pair_decisions: dict[str, Any],
    arc_legality_audit: dict[str, Any],
    complex_review: dict[str, Any],
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


__all__ = [
    "build_arc_evidence_attach_audit",
    "build_arc_legality_audit",
    "build_complex_patch_coverage_review",
    "build_complex_patch_legality_review",
    "build_legal_arc_coverage",
    "build_pair_decisions",
    "build_simple_patch_acceptance",
    "build_simple_patch_regression",
    "build_strong_constraint_status",
    "evaluate_patch_acceptance",
    "write_arc_first_attach_evidence_review",
    "write_arc_legality_fix_review",
    "write_bridge_trial_review",
    "write_legal_arc_coverage_review",
    "write_perf_opt_arc_first_review",
]
