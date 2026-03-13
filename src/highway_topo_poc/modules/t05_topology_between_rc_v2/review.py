from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .io import read_json, write_json


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

_REJECT_STAGE_PRIORITY = {
    "bridge_retain_gate": 0,
    "semantic_hard_gate": 1,
    "ownership_gate": 2,
    "pairing_filter": 3,
    "cross_filter": 4,
}


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


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


def _find_pair_row(rows: list[dict[str, Any]], pair_id: str) -> dict[str, Any] | None:
    for row in rows:
        if str(row.get("pair_id", "")) == str(pair_id):
            return row
        src_nodeid = row.get("src_nodeid")
        dst_nodeid = row.get("dst_nodeid")
        if src_nodeid is not None and dst_nodeid is not None and _pair_id_text(int(src_nodeid), int(dst_nodeid)) == str(pair_id):
            return row
    return None


def evaluate_patch_acceptance(run_root: Path | str, patch_id: str) -> dict[str, Any]:
    patch_dir = _patch_dir(run_root, patch_id)
    metrics = _safe_read_json(patch_dir / "metrics.json")
    gate = _safe_read_json(patch_dir / "gate.json")
    roads_payload = _safe_read_json(patch_dir / "step6" / "final_roads.json")
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
        pair_target = {
            "target_id": f"built_pair_{str(pair_id).replace(':', '_')}",
            "target_name": f"built_pair:{pair_id}",
            "expected": {"pair_id": str(pair_id), "built": True},
            "actual": {"pair_id": str(pair_id), "built": bool(pair_id in built_pair_set)},
            "pass": bool(pair_id in built_pair_set),
            "fail_reason": "" if pair_id in built_pair_set else "expected_built_pair_missing",
        }
        results.append(pair_target)
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
    segments_payload = _safe_read_json(patch_dir / "step2" / "segments.json")
    roads_payload = _safe_read_json(patch_dir / "step6" / "final_roads.json")
    should_not_payload = _safe_read_json(patch_dir / "debug" / "step2_segment_should_not_exist.json")
    topology_pairs_payload = _safe_read_json(patch_dir / "debug" / "step2_topology_pairs.json")
    bridge_audit_payload = _safe_read_json(patch_dir / "debug" / "step2_blocked_pair_bridge_audit.json")
    bridge_trial_payload = _safe_read_json(patch_dir / "debug" / "step6_bridge_trial_decisions.json")

    built_pair_set = set(_built_pairs(roads_payload))
    excluded_candidates = list(segments_payload.get("excluded_candidates", []))
    should_not_rows = list(should_not_payload.get("pairs", []))
    topology_rows = list(topology_pairs_payload.get("pairs", []))
    bridge_rows = list(bridge_audit_payload.get("pairs", []))
    bridge_trial_rows = list(bridge_trial_payload.get("pairs", []))

    decisions: list[dict[str, Any]] = []
    target_pairs = [*_FALSE_POSITIVE_PAIRS, *_STABLE_BLOCKED_PAIRS, _BRIDGE_TARGET_PAIR]
    for pair_id in target_pairs:
        excluded_rows = [
            item
            for item in excluded_candidates
            if _pair_id_text(int(item.get("src_nodeid", 0)), int(item.get("dst_nodeid", 0))) == str(pair_id)
        ]
        excluded = _best_excluded_entry(excluded_rows)
        should_not_row = _find_pair_row(should_not_rows, pair_id)
        topology_row = _find_pair_row(topology_rows, pair_id)
        bridge_row = _find_pair_row(bridge_rows, pair_id)
        bridge_trial_row = _find_pair_row(bridge_trial_rows, pair_id)
        decisions.append(
            {
                "patch_id": str(complex_patch_id),
                "pair": str(pair_id),
                "topology_arc_id": str(
                    (bridge_trial_row or {}).get("topology_arc_id")
                    or (excluded or {}).get("topology_arc_id")
                    or (topology_row or {}).get("topology_arc_id", "")
                ),
                "arc_source_type": str(
                    (topology_row or {}).get("arc_source_type")
                    or (excluded or {}).get("arc_source_type")
                    or ""
                ),
                "reject_stage": str(
                    (bridge_trial_row or {}).get("reject_stage")
                    or (bridge_row or {}).get("reject_stage")
                    or (excluded or {}).get("stage", "")
                ),
                "reject_reason": str(
                    (bridge_trial_row or {}).get("reject_reason")
                    or (bridge_row or {}).get("reject_reason")
                    or (excluded or {}).get("reason", "")
                ),
                "bridge_classification": str(
                    (bridge_trial_row or {}).get("bridge_classification")
                    or (bridge_row or {}).get("bridge_classification")
                    or ""
                ),
                "bridge_candidate_retained": bool((bridge_trial_row or {}).get("bridge_candidate_retained", False)),
                "bridge_chain_nodes": list((bridge_trial_row or {}).get("bridge_chain_nodes", [])),
                "bridge_chain_source": str((bridge_trial_row or {}).get("bridge_chain_source", "")),
                "bridge_decision_stage": str((bridge_trial_row or {}).get("bridge_decision_stage", "")),
                "bridge_decision_reason": str((bridge_trial_row or {}).get("bridge_decision_reason", "")),
                "should_not_reason": str((should_not_row or {}).get("reason", "")),
                "topology_sources": list((topology_row or {}).get("topology_sources", [])),
                "topology_paths": list((topology_row or {}).get("topology_paths", [])),
                "built_final_road": bool(pair_id in built_pair_set or bool((bridge_trial_row or {}).get("built_final_road", False))),
            }
        )
    return {
        "patch_id": str(complex_patch_id),
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pairs": decisions,
    }


def build_complex_bridge_trial_review(pair_decisions: dict[str, Any]) -> dict[str, Any]:
    rows = list(pair_decisions.get("pairs", []))
    by_pair = {str(row.get("pair", "")): row for row in rows}
    bridge_target = dict(by_pair.get(_BRIDGE_TARGET_PAIR, {}))
    false_positive_rows = [dict(by_pair.get(pair_id, {})) for pair_id in _FALSE_POSITIVE_PAIRS]
    blocked_rows = [dict(by_pair.get(pair_id, {})) for pair_id in _STABLE_BLOCKED_PAIRS]
    bridge_closed = bool(
        bridge_target
        and (
            bool(bridge_target.get("built_final_road", False))
            or str(bridge_target.get("bridge_decision_reason", "")).startswith("bridge_")
        )
    )
    return {
        "patch_id": str(pair_decisions.get("patch_id", "")),
        "bridge_target_pair": bridge_target,
        "false_positive_pairs": false_positive_rows,
        "stable_blocked_pairs": blocked_rows,
        "bridge_closure_status": "closed" if bridge_closed else "not_closed",
        "false_positive_guard_ok": bool(all(not bool(row.get("built_final_road", False)) for row in false_positive_rows)),
        "stable_blocked_ok": bool(
            all(
                not bool(row.get("built_final_road", False))
                and str(row.get("bridge_classification", "")) == "topology_gap_unresolved"
                for row in blocked_rows
            )
        ),
    }


def _render_summary_markdown(
    *,
    run_root: Path,
    acceptance_results: list[dict[str, Any]],
    pair_decisions: dict[str, Any],
    complex_review: dict[str, Any],
) -> str:
    lines = [
        "# T05 v2 Bridge Trial Summary",
        "",
        f"- `run_root`: `{run_root}`",
        f"- `generated_at_utc`: `{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}`",
        "",
        "## Simple Patch Acceptance",
        "",
    ]
    for item in acceptance_results:
        failed = [row for row in item.get("results", []) if not bool(row.get("pass", False))]
        lines.append(
            f"- `{item['patch_id']}`: acceptance_pass={str(item['acceptance_pass']).lower()} "
            f"targets={item['target_count']} failed={len(failed)}"
        )
    lines.extend(["", "## Complex Bridge Trial", ""])
    bridge_target = dict(complex_review.get("bridge_target_pair", {}))
    lines.append(
        f"- target `{_BRIDGE_TARGET_PAIR}`: built={str(bool(bridge_target.get('built_final_road', False))).lower()} "
        f"bridge_reason=`{bridge_target.get('bridge_decision_reason', '')}` "
        f"bridge_stage=`{bridge_target.get('bridge_decision_stage', '')}`"
    )
    for pair_id in _FALSE_POSITIVE_PAIRS:
        row = next((item for item in pair_decisions.get("pairs", []) if str(item.get("pair")) == pair_id), {})
        lines.append(
            f"- false_positive `{pair_id}`: built={str(bool(row.get('built_final_road', False))).lower()} "
            f"reject=`{row.get('reject_stage', '')}/{row.get('reject_reason', '')}`"
        )
    for pair_id in _STABLE_BLOCKED_PAIRS:
        row = next((item for item in pair_decisions.get("pairs", []) if str(item.get("pair")) == pair_id), {})
        lines.append(
            f"- blocked `{pair_id}`: built={str(bool(row.get('built_final_road', False))).lower()} "
            f"bridge=`{row.get('bridge_classification', '')}`"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_bridge_trial_review(
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
    complex_review = build_complex_bridge_trial_review(pair_decisions)

    for item in acceptance_results:
        write_json(output_root_path / f"acceptance_{item['patch_id']}.json", item)
    write_json(output_root_path / "pair_decisions.json", pair_decisions)
    write_json(output_root_path / "complex_bridge_trial_review.json", complex_review)
    (output_root_path / "SUMMARY.md").write_text(
        _render_summary_markdown(
            run_root=run_root_path,
            acceptance_results=acceptance_results,
            pair_decisions=pair_decisions,
            complex_review=complex_review,
        ),
        encoding="utf-8",
    )
    return {
        "output_root": str(output_root_path),
        "acceptance": acceptance_results,
        "pair_decisions": pair_decisions,
        "complex_bridge_trial_review": complex_review,
    }


__all__ = [
    "build_complex_bridge_trial_review",
    "build_pair_decisions",
    "evaluate_patch_acceptance",
    "write_bridge_trial_review",
]
