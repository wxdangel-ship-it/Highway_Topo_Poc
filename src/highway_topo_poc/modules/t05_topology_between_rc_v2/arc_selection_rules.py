from __future__ import annotations

from collections import defaultdict
from typing import Any


STRUCTURE_SINGLE = "SINGLE"
STRUCTURE_MERGE_MULTI_UPSTREAM = "MERGE_MULTI_UPSTREAM"
STRUCTURE_SAME_PAIR_MULTI_ARC = "SAME_PAIR_MULTI_ARC"


def _pair_id(src_nodeid: int, dst_nodeid: int) -> str:
    return f"{int(src_nodeid)}:{int(dst_nodeid)}"


def _canonical_pair(row: dict[str, Any]) -> str:
    canonical_pair = str(row.get("canonical_pair", ""))
    if canonical_pair:
        return canonical_pair
    return str(row.get("pair", ""))


def _pair(row: dict[str, Any]) -> str:
    pair_id = str(row.get("pair", ""))
    if pair_id:
        return pair_id
    src = row.get("src", row.get("src_nodeid", 0))
    dst = row.get("dst", row.get("dst_nodeid", 0))
    return _pair_id(int(src), int(dst))


def _node_path(row: dict[str, Any]) -> list[int]:
    return [int(v) for v in row.get("node_path", []) if v is not None]


def _internal_nodes(row: dict[str, Any]) -> list[int]:
    path = _node_path(row)
    if len(path) <= 2:
        return []
    return [int(v) for v in path[1:-1]]


def _direct_legal_row(row: dict[str, Any]) -> bool:
    return bool(
        row.get("is_direct_legal", row.get("topology_arc_is_direct_legal", False))
    )


def _unique_row(row: dict[str, Any]) -> bool:
    return bool(row.get("is_unique", row.get("topology_arc_is_unique", False)))


def _support_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    src_anchor = tuple(row.get("support_anchor_src_coords") or [])
    dst_anchor = tuple(row.get("support_anchor_dst_coords") or [])
    return (
        str(row.get("traj_support_type", "no_support")),
        tuple(sorted(str(v) for v in row.get("traj_support_ids", []))),
        src_anchor,
        dst_anchor,
    )


def _has_independent_traj_support(row: dict[str, Any], *, min_coverage_ratio: float) -> bool:
    traj_support_type = str(row.get("traj_support_type", "no_support"))
    if traj_support_type == "no_support":
        return False
    support_ids = [str(v) for v in row.get("traj_support_ids", []) if str(v)]
    if not support_ids:
        return False
    coverage_ratio = float(row.get("traj_support_coverage_ratio", 0.0) or 0.0)
    if coverage_ratio < float(min_coverage_ratio):
        return False
    return row.get("support_anchor_src_coords") is not None and row.get("support_anchor_dst_coords") is not None


def detect_diverge_merge_structure(
    row: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    dst_nodeid = int(row.get("dst", row.get("dst_nodeid", 0)))
    src_nodeid = int(row.get("src", row.get("src_nodeid", 0)))
    row_pair = _pair(row)
    row_internal_nodes = set(_internal_nodes(row))
    peer_pairs: set[str] = set()
    shared_downstream_nodes: set[int] = set()
    for peer in rows:
        if _pair(peer) == row_pair:
            continue
        if not _direct_legal_row(peer) or not _unique_row(peer):
            continue
        if int(peer.get("dst", peer.get("dst_nodeid", 0))) != dst_nodeid:
            continue
        if int(peer.get("src", peer.get("src_nodeid", 0))) == src_nodeid:
            continue
        peer_internal_nodes = set(_internal_nodes(peer))
        shared_nodes = row_internal_nodes & peer_internal_nodes
        if not shared_nodes:
            continue
        peer_pairs.add(_pair(peer))
        shared_downstream_nodes.update(int(v) for v in shared_nodes)
    return {
        "structure_type": (
            STRUCTURE_MERGE_MULTI_UPSTREAM if peer_pairs else STRUCTURE_SINGLE
        ),
        "peer_pairs": sorted(peer_pairs),
        "shared_downstream_nodes": sorted(shared_downstream_nodes),
    }


def allow_multiple_upstream_arcs(
    row: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    min_support_coverage_ratio: float,
) -> dict[str, Any]:
    structure = detect_diverge_merge_structure(row, rows)
    peer_pairs = list(structure.get("peer_pairs", []))
    if str(structure.get("structure_type", STRUCTURE_SINGLE)) != STRUCTURE_MERGE_MULTI_UPSTREAM:
        return {
            **structure,
            "allow_multi_output": False,
            "rule_reason": "not_merge_multi_upstream",
            "competing_group_key": "",
            "independent_support_available": False,
        }
    group_pairs = {_pair(row), *peer_pairs}
    group_rows = [
        dict(item)
        for item in rows
        if _pair(item) in group_pairs
    ]
    direct_unique_group = [
        dict(item)
        for item in group_rows
        if _direct_legal_row(item) and _unique_row(item)
    ]
    support_ready = all(
        _has_independent_traj_support(item, min_coverage_ratio=float(min_support_coverage_ratio))
        for item in direct_unique_group
    )
    support_signatures = {_support_signature(item) for item in direct_unique_group}
    independent_support_available = support_ready and len(support_signatures) == len(direct_unique_group)
    return {
        **structure,
        "allow_multi_output": bool(independent_support_available and len(direct_unique_group) >= 2),
        "rule_reason": (
            "merge_multi_upstream_independent_support"
            if independent_support_available and len(direct_unique_group) >= 2
            else "merge_multi_upstream_support_not_independent"
        ),
        "competing_group_key": f"merge_dst:{int(row.get('dst', row.get('dst_nodeid', 0)))}",
        "independent_support_available": bool(independent_support_available),
    }


def classify_arc_structure(
    row: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    canonical_pair = _canonical_pair(row)
    same_pair_rows = [
        dict(item)
        for item in rows
        if _canonical_pair(item) == canonical_pair and _direct_legal_row(item)
    ]
    if len(same_pair_rows) > 1:
        return {
            "structure_type": STRUCTURE_SAME_PAIR_MULTI_ARC,
            "peer_pairs": sorted({_pair(item) for item in same_pair_rows}),
            "shared_downstream_nodes": [],
            "same_pair_arc_count": int(len(same_pair_rows)),
            "same_pair_arc_ids": sorted(str(item.get("topology_arc_id", "")) for item in same_pair_rows if str(item.get("topology_arc_id", ""))),
            "rule_name": "apply_multi_arc_rule",
            "allow_multi_output": True,
        }
    merge_structure = detect_diverge_merge_structure(row, rows)
    if str(merge_structure.get("structure_type", STRUCTURE_SINGLE)) == STRUCTURE_MERGE_MULTI_UPSTREAM:
        return {
            **merge_structure,
            "same_pair_arc_count": int(len(same_pair_rows)),
            "same_pair_arc_ids": sorted(str(item.get("topology_arc_id", "")) for item in same_pair_rows if str(item.get("topology_arc_id", ""))),
            "rule_name": "allow_multiple_upstream_arcs",
            "allow_multi_output": True,
        }
    return {
        "structure_type": STRUCTURE_SINGLE,
        "peer_pairs": [],
        "shared_downstream_nodes": [],
        "same_pair_arc_count": int(len(same_pair_rows)),
        "same_pair_arc_ids": sorted(str(item.get("topology_arc_id", "")) for item in same_pair_rows if str(item.get("topology_arc_id", ""))),
        "rule_name": "single_arc_default",
        "allow_multi_output": False,
    }


def apply_arc_selection_rules(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    annotated_rows: list[dict[str, Any]] = []
    merge_pairs: set[str] = set()
    same_pair_groups: set[str] = set()
    for row in rows:
        current = dict(row)
        structure = classify_arc_structure(current, rows)
        structure_type = str(structure.get("structure_type", STRUCTURE_SINGLE))
        current["arc_structure_type"] = structure_type
        current["arc_selection_rule"] = str(structure.get("rule_name", "single_arc_default"))
        current["arc_selection_allow_multi_output"] = bool(structure.get("allow_multi_output", False))
        current["arc_selection_peer_pairs"] = list(structure.get("peer_pairs", []))
        current["arc_selection_shared_downstream_nodes"] = list(structure.get("shared_downstream_nodes", []))
        current["arc_selection_same_pair_arc_count"] = int(structure.get("same_pair_arc_count", 0))
        current["arc_selection_same_pair_arc_ids"] = list(structure.get("same_pair_arc_ids", []))
        current["arc_selection_group_key"] = (
            f"same_pair:{_canonical_pair(current)}"
            if structure_type == STRUCTURE_SAME_PAIR_MULTI_ARC
            else f"merge_dst:{int(current.get('dst', current.get('dst_nodeid', 0)))}"
            if structure_type == STRUCTURE_MERGE_MULTI_UPSTREAM
            else f"single:{_pair(current)}"
        )
        if structure_type == STRUCTURE_MERGE_MULTI_UPSTREAM:
            merge_pairs.add(_pair(current))
        elif structure_type == STRUCTURE_SAME_PAIR_MULTI_ARC:
            same_pair_groups.add(_canonical_pair(current))
        annotated_rows.append(current)
    return {
        "rows": annotated_rows,
        "summary": {
            "row_count": int(len(annotated_rows)),
            "merge_multi_upstream_pair_count": int(len(merge_pairs)),
            "same_pair_multi_arc_pair_count": int(len(same_pair_groups)),
        },
    }


def apply_diverge_merge_rule(
    rows: list[dict[str, Any]],
    *,
    min_support_coverage_ratio: float,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("arc_structure_type", "")) != STRUCTURE_MERGE_MULTI_UPSTREAM:
            continue
        pair_id = _pair(row)
        out[pair_id] = allow_multiple_upstream_arcs(
            row,
            rows,
            min_support_coverage_ratio=float(min_support_coverage_ratio),
        )
    return out


def _multi_arc_evidence_mode(row: dict[str, Any]) -> str:
    if str(row.get("corridor_identity", "")) == "witness_based" and str(row.get("traj_support_type", "no_support")) != "no_support":
        return "witness_based"
    if (
        _direct_legal_row(row)
        and (row.get("support_anchor_src_coords") is not None)
        and (row.get("support_anchor_dst_coords") is not None)
        and str(row.get("prior_support_type", "no_support")) == "prior_fallback_support"
        and float(row.get("divstrip_overlap_ratio", 0.0) or 0.0) <= 0.12
        and float(row.get("drivezone_overlap_ratio", 0.0) or 0.0) >= 0.5
    ):
        return "fallback_based"
    return "insufficient"


def apply_multi_arc_rule(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row.get("arc_structure_type", "")) == STRUCTURE_SAME_PAIR_MULTI_ARC:
            groups[_canonical_pair(row)].append(dict(row))
    out: dict[str, dict[str, Any]] = {}
    for canonical_pair, group_rows in groups.items():
        evidence_modes = {
            str(row.get("topology_arc_id", "")): _multi_arc_evidence_mode(row)
            for row in group_rows
            if str(row.get("topology_arc_id", ""))
        }
        witness_based_arc_ids = sorted(arc_id for arc_id, mode in evidence_modes.items() if mode == "witness_based")
        fallback_based_arc_ids = sorted(arc_id for arc_id, mode in evidence_modes.items() if mode == "fallback_based")
        allow_multi_output = bool(witness_based_arc_ids) and (
            len(witness_based_arc_ids) + len(fallback_based_arc_ids) == len(evidence_modes)
        )
        out[str(canonical_pair)] = {
            "pair": str(canonical_pair),
            "structure_type": STRUCTURE_SAME_PAIR_MULTI_ARC,
            "pair_arc_count": int(len(group_rows)),
            "arc_ids": sorted(str(row.get("topology_arc_id", "")) for row in group_rows if str(row.get("topology_arc_id", ""))),
            "allow_multi_output": bool(allow_multi_output),
            "witness_based_arc_ids": witness_based_arc_ids,
            "fallback_based_arc_ids": fallback_based_arc_ids,
            "evidence_modes": dict(evidence_modes),
            "rule_reason": (
                "same_pair_multi_arc_dual_output_ready"
                if allow_multi_output
                else "same_pair_multi_arc_evidence_not_sufficient"
            ),
        }
    return out


__all__ = [
    "STRUCTURE_SINGLE",
    "STRUCTURE_MERGE_MULTI_UPSTREAM",
    "STRUCTURE_SAME_PAIR_MULTI_ARC",
    "allow_multiple_upstream_arcs",
    "apply_arc_selection_rules",
    "apply_diverge_merge_rule",
    "apply_multi_arc_rule",
    "classify_arc_structure",
    "detect_diverge_merge_structure",
]
