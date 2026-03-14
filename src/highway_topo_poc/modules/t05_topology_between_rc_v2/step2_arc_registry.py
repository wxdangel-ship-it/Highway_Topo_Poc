from __future__ import annotations

from collections import defaultdict
from typing import Any


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
) -> dict[str, Any]:
    selected_by_arc: dict[str, list[Any]] = defaultdict(list)
    for segment in selected_segments:
        arc_id = str(getattr(segment, "topology_arc_id", ""))
        if arc_id:
            selected_by_arc[arc_id].append(segment)

    rows: list[dict[str, Any]] = []
    for row in _direct_topology_arc_rows(topology):
        arc_id = str(row["topology_arc_id"])
        attached_segments = list(selected_by_arc.get(arc_id, []))
        rows.append(
            {
                **dict(row),
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
                "unbuilt_stage": "hard_blocked" if str(row["hard_block_reason"]) else "",
                "unbuilt_reason": str(row["hard_block_reason"]),
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
