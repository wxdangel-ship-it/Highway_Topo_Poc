from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_pair(text: str) -> tuple[int, int]:
    raw = str(text).strip().replace("->", ":")
    if ":" not in raw:
        raise ValueError(f"invalid_pair:{text}")
    src_text, dst_text = raw.split(":", 1)
    return int(src_text), int(dst_text)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t05_pair_check")
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--patch-id", required=True)
    parser.add_argument("--pair", required=True, help="src:dst or src->dst")
    parser.add_argument("--support-limit", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    src_nodeid, dst_nodeid = _parse_pair(args.pair)
    root = Path(args.out_root) / str(args.run_id) / "patches" / str(args.patch_id)

    segments_payload = _read_json(root / "step2" / "segments.json")
    metrics_payload = _read_json(root / "metrics.json")
    terminal_audit = _read_json(root / "debug" / "step2_terminal_node_audit.json")
    support_trajs = _read_json(root / "debug" / "step2_segment_support_trajs.geojson")
    should_not_exist = _read_json(root / "debug" / "step2_segment_should_not_exist.json")
    raw_crossings = _read_json(root / "debug" / "step2_traj_crossings_raw.geojson")
    filtered_crossings = _read_json(root / "debug" / "step2_traj_crossings_filtered.geojson")

    selected_segments = [
        item
        for item in segments_payload.get("segments", [])
        if int(item.get("src_nodeid", -1)) == int(src_nodeid) and int(item.get("dst_nodeid", -1)) == int(dst_nodeid)
    ]
    excluded_candidates = [
        item
        for item in segments_payload.get("excluded_candidates", [])
        if int(item.get("src_nodeid", -1)) == int(src_nodeid) and int(item.get("dst_nodeid", -1)) == int(dst_nodeid)
    ]
    metrics_entry = next(
        (
            item
            for item in metrics_payload.get("segments", [])
            if int(item.get("src_nodeid", -1)) == int(src_nodeid) and int(item.get("dst_nodeid", -1)) == int(dst_nodeid)
        ),
        None,
    )
    terminal_node = next(
        (item for item in terminal_audit.get("nodes", []) if int(item.get("nodeid", -1)) == int(dst_nodeid)),
        None,
    )
    terminal_pair = None
    if isinstance(terminal_node, dict):
        terminal_pair = next(
            (
                item
                for item in terminal_node.get("pairs", [])
                if int(item.get("src_nodeid", -1)) == int(src_nodeid) and int(item.get("dst_nodeid", -1)) == int(dst_nodeid)
            ),
            None,
        )
    should_not_exist_entry = next(
        (
            item
            for item in should_not_exist.get("pairs", [])
            if int(item.get("src_nodeid", -1)) == int(src_nodeid) and int(item.get("dst_nodeid", -1)) == int(dst_nodeid)
        ),
        None,
    )
    support_entries = [
        feat.get("properties", {})
        for feat in support_trajs.get("features", [])
        if int(feat.get("properties", {}).get("src_nodeid", -1)) == int(src_nodeid)
        and int(feat.get("properties", {}).get("dst_nodeid", -1)) == int(dst_nodeid)
    ]
    raw_crossing_entries = [
        feat.get("properties", {})
        for feat in raw_crossings.get("features", [])
        if f"{src_nodeid}:{dst_nodeid}" in set(feat.get("properties", {}).get("pair_ids", []))
    ]
    filtered_crossing_entries = [
        feat.get("properties", {})
        for feat in filtered_crossings.get("features", [])
        if f"{src_nodeid}:{dst_nodeid}" in set(feat.get("properties", {}).get("pair_ids", []))
    ]

    payload = {
        "pair": {
            "src_nodeid": int(src_nodeid),
            "dst_nodeid": int(dst_nodeid),
            "pair_id": f"{src_nodeid}:{dst_nodeid}",
        },
        "selected_segment_count": int(len(selected_segments)),
        "selected_segments": [
            {
                "segment_id": str(item.get("segment_id", "")),
                "support_count": int(item.get("support_count", 0)),
                "formation_reason": str(item.get("formation_reason", "")),
                "kept_reason": str(item.get("kept_reason", "")),
                "other_xsec_crossing_count": int(item.get("other_xsec_crossing_count", 0)),
            }
            for item in selected_segments
        ],
        "excluded_candidates": [
            {
                "candidate_id": str(item.get("candidate_id", "")),
                "stage": str(item.get("stage", "")),
                "reason": str(item.get("reason", "")),
                "support_count": int(item.get("support_count", 0)),
                "pairing_mode": str(item.get("pairing_mode", "")),
                "topology_reason": str(item.get("topology_reason", "")),
                "topology_reverse_owner_status": str(item.get("topology_reverse_owner_status", "")),
                "topology_reverse_owner_src_nodeid": item.get("topology_reverse_owner_src_nodeid"),
                "prior_anchor_cost_m": item.get("prior_anchor_cost_m"),
                "prior_anchor_best_pair": item.get("prior_anchor_best_pair"),
                "competing_prior_pair_ids": list(item.get("competing_prior_pair_ids", [])),
                "competing_prior_candidate_ids": list(item.get("competing_prior_candidate_ids", [])),
                "competing_prior_trace_paths": list(item.get("competing_prior_trace_paths", [])),
                "support_traj_ids": list(item.get("support_traj_ids", [])),
            }
            for item in excluded_candidates
        ],
        "metric": None
        if metrics_entry is None
        else {
            "segment_id": str(metrics_entry.get("segment_id", "")),
            "support_count": int(metrics_entry.get("support_count", 0)),
            "corridor_state": str(metrics_entry.get("corridor_identity_state", metrics_entry.get("corridor_identity", ""))),
            "road_failure_class": str(metrics_entry.get("failure_classification", "")),
            "shape_ref_mode": str(metrics_entry.get("shape_ref_mode", "")),
            "road_ratio": metrics_entry.get("road_in_drivezone_ratio"),
            "road_cross_divstrip": metrics_entry.get("road_crosses_divstrip"),
            "no_geometry_reason": str(metrics_entry.get("no_geometry_candidate_reason", "")),
        },
        "terminal_node_audit": None
        if terminal_node is None
        else {
            "nodeid": int(terminal_node.get("nodeid", -1)),
            "reverse_owner_status": str(terminal_node.get("reverse_owner_status", "")),
            "reverse_owner_src_nodeid": terminal_node.get("reverse_owner_src_nodeid"),
            "allowed_incoming_src_nodeids": list(terminal_node.get("allowed_incoming_src_nodeids", [])),
            "pair_row": terminal_pair,
        },
        "segment_should_not_exist": should_not_exist_entry,
        "support_trajs": support_entries[: max(0, int(args.support_limit))],
        "support_traj_count": int(len(support_entries)),
        "raw_crossings": raw_crossing_entries[: max(0, int(args.support_limit))],
        "filtered_crossings": filtered_crossing_entries[: max(0, int(args.support_limit))],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
