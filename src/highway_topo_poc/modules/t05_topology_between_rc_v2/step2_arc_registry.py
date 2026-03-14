from __future__ import annotations

from collections import defaultdict
from typing import Any


def _pair_status_indexes(
    *,
    segment_should_not_exist: list[dict[str, Any]] | None,
    blocked_pair_bridge_audit: list[dict[str, Any]] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    hard_block_by_pair: dict[str, str] = {}
    for row in list(segment_should_not_exist or []):
        pair_id = str(row.get("pair_id") or row.get("pair") or "")
        reason = str(row.get("reason") or "")
        if pair_id and reason and pair_id not in hard_block_by_pair:
            hard_block_by_pair[pair_id] = reason

    blocked_diag_by_pair: dict[str, str] = {}
    for row in list(blocked_pair_bridge_audit or []):
        pair_id = str(row.get("pair_id") or row.get("pair") or "")
        if not pair_id:
            continue
        bridge_classification = str(row.get("bridge_classification") or "")
        reject_reason = str(row.get("reject_reason") or "")
        blocked_diag_by_pair[pair_id] = bridge_classification or reject_reason or "blocked_diagnostic_only"
    return hard_block_by_pair, blocked_diag_by_pair


def _direct_topology_arc_rows(topology: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pair_arcs = dict(topology.get("pair_arcs", {}))
    for pair in sorted(pair_arcs.keys()):
        src_nodeid, dst_nodeid = int(pair[0]), int(pair[1])
        direct_arcs = [
            dict(item)
            for item in list(pair_arcs.get(pair, []))
            if str(item.get("source", "")) == "direct_topology_arc"
        ]
        arc_count = int(len(direct_arcs))
        for arc in direct_arcs:
            rows.append(
                {
                    "pair": f"{src_nodeid}:{dst_nodeid}",
                    "src": src_nodeid,
                    "dst": dst_nodeid,
                    "raw_src_nodeid": int(arc.get("raw_src_nodeid", src_nodeid)),
                    "raw_dst_nodeid": int(arc.get("raw_dst_nodeid", dst_nodeid)),
                    "canonical_src_xsec_id": int(arc.get("canonical_src_xsec_id", src_nodeid)),
                    "canonical_dst_xsec_id": int(arc.get("canonical_dst_xsec_id", dst_nodeid)),
                    "src_alias_applied": bool(arc.get("src_alias_applied", False)),
                    "dst_alias_applied": bool(arc.get("dst_alias_applied", False)),
                    "raw_pair": str(arc.get("raw_pair", f"{src_nodeid}:{dst_nodeid}")),
                    "canonical_pair": str(arc.get("canonical_pair", f"{src_nodeid}:{dst_nodeid}")),
                    "topology_arc_id": str(arc.get("arc_id", "")),
                    "topology_arc_source_type": str(arc.get("source", "")),
                    "node_path": [int(v) for v in arc.get("node_path", []) if v is not None],
                    "edge_ids": [str(v) for v in arc.get("edge_ids", []) if str(v)],
                    "line_coords": list(arc.get("line_coords", [])),
                    "chain_len": int(arc.get("chain_len", 0)),
                    "is_direct_legal": True,
                    "is_unique": bool(arc_count == 1),
                    "direct_arc_count_for_pair": arc_count,
                    "entered_main_flow": bool(arc_count == 1),
                    "hard_block_reason": "" if arc_count == 1 else "non_unique_direct_legal_arc",
                }
            )
    return rows


def build_full_legal_arc_registry(
    *,
    topology: dict[str, Any],
    selected_segments: list[Any],
    segment_should_not_exist: list[dict[str, Any]] | None = None,
    blocked_pair_bridge_audit: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    hard_block_by_pair, blocked_diag_by_pair = _pair_status_indexes(
        segment_should_not_exist=segment_should_not_exist,
        blocked_pair_bridge_audit=blocked_pair_bridge_audit,
    )
    selected_by_arc: dict[str, list[Any]] = defaultdict(list)
    for segment in selected_segments:
        arc_id = str(getattr(segment, "topology_arc_id", ""))
        if arc_id:
            selected_by_arc[arc_id].append(segment)

    rows: list[dict[str, Any]] = []
    for row in _direct_topology_arc_rows(topology):
        arc_id = str(row["topology_arc_id"])
        attached_segments = list(selected_by_arc.get(arc_id, []))
        selected_segment = attached_segments[0] if attached_segments else None
        pair_id = str(row["pair"])
        pair_hard_block_reason = "" if attached_segments else str(hard_block_by_pair.get(pair_id, ""))
        blocked_diagnostic_only = bool((not attached_segments) and pair_id in blocked_diag_by_pair)
        blocked_diagnostic_reason = str(blocked_diag_by_pair.get(pair_id, ""))
        hard_block_reason = str(row["hard_block_reason"] or pair_hard_block_reason)
        entered_main_flow = bool(row["is_unique"]) and not hard_block_reason and not blocked_diagnostic_only
        rows.append(
            {
                **dict(row),
                "entered_main_flow": bool(entered_main_flow),
                "hard_block_reason": str(hard_block_reason),
                "blocked_diagnostic_only": bool(blocked_diagnostic_only),
                "blocked_diagnostic_reason": str(blocked_diagnostic_reason),
                "controlled_entry_allowed": False,
                "topology_gap_decision": "",
                "topology_gap_reason": "",
                "raw_src_nodeid": int(
                    (
                        getattr(selected_segment, "raw_src_nodeid", None)
                        if selected_segment is not None
                        else row.get("raw_src_nodeid", row["src"])
                    )
                    or row.get("raw_src_nodeid", row["src"])
                    if selected_segment is not None
                    else row.get("raw_src_nodeid", row["src"])
                ),
                "raw_dst_nodeid": int(
                    (
                        getattr(selected_segment, "raw_dst_nodeid", None)
                        if selected_segment is not None
                        else row.get("raw_dst_nodeid", row["dst"])
                    )
                    or row.get("raw_dst_nodeid", row["dst"])
                    if selected_segment is not None
                    else row.get("raw_dst_nodeid", row["dst"])
                ),
                "canonical_src_xsec_id": int(
                    (
                        getattr(selected_segment, "canonical_src_xsec_id", None)
                        if selected_segment is not None
                        else row.get("canonical_src_xsec_id", row["src"])
                    )
                    or row.get("canonical_src_xsec_id", row["src"])
                    if selected_segment is not None
                    else row.get("canonical_src_xsec_id", row["src"])
                ),
                "canonical_dst_xsec_id": int(
                    (
                        getattr(selected_segment, "canonical_dst_xsec_id", None)
                        if selected_segment is not None
                        else row.get("canonical_dst_xsec_id", row["dst"])
                    )
                    or row.get("canonical_dst_xsec_id", row["dst"])
                    if selected_segment is not None
                    else row.get("canonical_dst_xsec_id", row["dst"])
                ),
                "src_alias_applied": bool(
                    getattr(selected_segment, "src_alias_applied", row.get("src_alias_applied", False))
                    if selected_segment is not None
                    else row.get("src_alias_applied", False)
                ),
                "dst_alias_applied": bool(
                    getattr(selected_segment, "dst_alias_applied", row.get("dst_alias_applied", False))
                    if selected_segment is not None
                    else row.get("dst_alias_applied", False)
                ),
                "raw_pair": str(
                    (
                        f"{int((getattr(selected_segment, 'raw_src_nodeid', None) or row.get('raw_src_nodeid', row['src'])))}:"
                        f"{int((getattr(selected_segment, 'raw_dst_nodeid', None) or row.get('raw_dst_nodeid', row['dst'])))}"
                    )
                    if selected_segment is not None
                    else row.get("raw_pair", pair_id)
                ),
                "canonical_pair": str(row.get("canonical_pair", pair_id)),
                "selected_segment_ids": [str(getattr(segment, "segment_id", "")) for segment in attached_segments],
                "selected_segment_count": int(len(attached_segments)),
                "selected_segment_id": "" if not attached_segments else str(attached_segments[0].segment_id),
                "traj_support_type": "no_support",
                "traj_support_ids": [],
                "traj_support_span_count": 0,
                "traj_support_coverage_ratio": 0.0,
                "prior_support_type": "no_support",
                "prior_support_available": False,
                "corridor_identity": "unresolved",
                "corridor_reason": "",
                "slot_status": "unresolved",
                "slot_src_resolved": False,
                "slot_dst_resolved": False,
                "built_final_road": False,
                "unbuilt_stage": (
                    "hard_blocked"
                    if hard_block_reason or blocked_diagnostic_only
                    else ""
                ),
                "unbuilt_reason": str(hard_block_reason or blocked_diagnostic_reason),
                "working_segment_id": "" if not attached_segments else str(attached_segments[0].segment_id),
                "working_segment_source": "step2_selected_segment" if attached_segments else "",
            }
        )

    all_direct_legal_arc_count = int(len(rows))
    all_direct_unique_legal_arc_count = int(sum(1 for row in rows if bool(row["is_unique"])))
    entered_main_flow_arc_count = int(sum(1 for row in rows if bool(row["entered_main_flow"])))
    return {
        "rows": rows,
        "summary": {
            "all_direct_legal_arc_count": all_direct_legal_arc_count,
            "all_direct_unique_legal_arc_count": all_direct_unique_legal_arc_count,
            "entered_main_flow_arc_count": entered_main_flow_arc_count,
        },
    }


__all__ = ["build_full_legal_arc_registry"]
