from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, MultiLineString, Point, mapping

from .crs_norm import transform_coords_recursive
from .io_geojson import make_feature_collection, write_geojson


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _props_min(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodeid": item.get("nodeid"),
        "id": item.get("id"),
        "mainid": item.get("mainid"),
        "mainnodeid": item.get("mainnodeid"),
        "kind": item.get("kind"),
        "is_merge_kind": item.get("is_merge_kind"),
        "is_diverge_kind": item.get("is_diverge_kind"),
        "kind_bits": {
            "merge": bool(item.get("is_merge_kind", False)),
            "diverge": bool(item.get("is_diverge_kind", False)),
            "k16": bool(item.get("k16_enabled", False)),
        },
        "anchor_type": item.get("anchor_type"),
        "status": item.get("status"),
        "found_split": item.get("found_split"),
        "scan_dir": item.get("scan_dir"),
        "scan_dist_m": item.get("scan_dist_m"),
        "stop_dist_node_raw_m": item.get("stop_dist_node_raw_m"),
        "stop_dist_chain_override_m": item.get("stop_dist_chain_override_m"),
        "stop_dist_chain_override_applied": item.get("stop_dist_chain_override_applied"),
        "trigger": item.get("trigger"),
        "dist_to_divstrip_m": item.get("dist_to_divstrip_m"),
        "dist_line_to_divstrip_m": item.get("dist_line_to_divstrip_m"),
        "dist_line_to_drivezone_edge_m": item.get("dist_line_to_drivezone_edge_m"),
        "confidence": item.get("confidence"),
        "flags": item.get("flags", []),
        "evidence_source": item.get("evidence_source"),
        "resolved_from": item.get("resolved_from"),
        "tip_s_m": item.get("tip_s_m"),
        "first_divstrip_hit_dist_m": item.get("first_divstrip_hit_dist_m"),
        "best_divstrip_dz_dist_m": item.get("best_divstrip_dz_dist_m"),
        "best_divstrip_pc_dist_m": item.get("best_divstrip_pc_dist_m"),
        "first_pc_only_dist_m": item.get("first_pc_only_dist_m"),
        "fan_area_m2": item.get("fan_area_m2"),
        "non_drivezone_area_m2": item.get("non_drivezone_area_m2"),
        "non_drivezone_frac": item.get("non_drivezone_frac"),
        "clipped_len_m": item.get("clipped_len_m"),
        "clip_empty": item.get("clip_empty"),
        "clip_piece_type": item.get("clip_piece_type"),
        "pieces_count": item.get("pieces_count"),
        "piece_lens_m": item.get("piece_lens_m"),
        "gap_len_m": item.get("gap_len_m"),
        "seg_len_m": item.get("seg_len_m"),
        "s_divstrip_m": item.get("s_divstrip_m"),
        "s_drivezone_split_m": item.get("s_drivezone_split_m"),
        "s_chosen_m": item.get("s_chosen_m"),
        "split_pick_source": item.get("split_pick_source"),
        "divstrip_ref_source": item.get("divstrip_ref_source"),
        "divstrip_ref_offset_m": item.get("divstrip_ref_offset_m"),
        "output_cross_half_len_m": item.get("output_cross_half_len_m"),
        "branch_a_id": item.get("branch_a_id"),
        "branch_b_id": item.get("branch_b_id"),
        "branch_axis_id": item.get("branch_axis_id"),
        "branch_a_crossline_hit": item.get("branch_a_crossline_hit"),
        "branch_b_crossline_hit": item.get("branch_b_crossline_hit"),
        "pa_center_dist_m": item.get("pa_center_dist_m"),
        "pb_center_dist_m": item.get("pb_center_dist_m"),
        "has_divstrip_nearby": item.get("has_divstrip_nearby"),
        "reverse_tip_attempted": item.get("reverse_tip_attempted"),
        "reverse_tip_used": item.get("reverse_tip_used"),
        "reverse_tip_not_improved": item.get("reverse_tip_not_improved"),
        "reverse_search_max_m": item.get("reverse_search_max_m"),
        "reverse_trigger": item.get("reverse_trigger"),
        "ref_s_forward_m": item.get("ref_s_forward_m"),
        "position_source_forward": item.get("position_source_forward"),
        "ref_s_reverse_m": item.get("ref_s_reverse_m"),
        "position_source_reverse": item.get("position_source_reverse"),
        "ref_s_final_m": item.get("ref_s_final_m"),
        "position_source_final": item.get("position_source_final"),
        "untrusted_divstrip_at_node": item.get("untrusted_divstrip_at_node"),
        "node_to_divstrip_m_at_s0": item.get("node_to_divstrip_m_at_s0"),
        "seg0_intersects_divstrip": item.get("seg0_intersects_divstrip"),
        "stop_reason": item.get("stop_reason"),
        "is_in_continuous_chain": item.get("is_in_continuous_chain"),
        "chain_component_id": item.get("chain_component_id"),
        "chain_node_offset_m": item.get("chain_node_offset_m"),
        "abs_s_chosen_m": item.get("abs_s_chosen_m"),
        "abs_s_prev_required_m": item.get("abs_s_prev_required_m"),
        "sequential_ok": item.get("sequential_ok"),
        "sequential_violation_reason": item.get("sequential_violation_reason"),
        "merged": item.get("merged"),
        "merged_group_id": item.get("merged_group_id"),
        "merged_with_nodeids": item.get("merged_with_nodeids"),
        "abs_s_merged_m": item.get("abs_s_merged_m"),
        "merged_crossline_id": item.get("merged_crossline_id"),
        "merge_reason": item.get("merge_reason"),
        "merge_geom_dist_m": item.get("merge_geom_dist_m"),
        "merge_abs_diff_m": item.get("merge_abs_diff_m"),
        "merge_abs_gap_cfg_m": item.get("merge_abs_gap_cfg_m"),
        "merge_abs_gate_skipped": item.get("merge_abs_gate_skipped"),
        "multibranch_enabled": item.get("multibranch_enabled"),
        "multibranch_N": item.get("multibranch_N"),
        "multibranch_expected_events": item.get("multibranch_expected_events"),
        "split_events_forward": item.get("split_events_forward"),
        "split_events_reverse": item.get("split_events_reverse"),
        "s_main_m": item.get("s_main_m"),
        "main_pick_source": item.get("main_pick_source"),
        "abnormal_two_sided": item.get("abnormal_two_sided"),
        "span_extra_m": item.get("span_extra_m"),
        "direction_filter_applied": item.get("direction_filter_applied"),
        "branches_used_count": item.get("branches_used_count"),
        "branches_ignored_due_to_direction": item.get("branches_ignored_due_to_direction"),
        "s_drivezone_split_first_m": item.get("s_drivezone_split_first_m"),
        "k16_enabled": item.get("k16_enabled"),
        "k16_road_id": item.get("k16_road_id"),
        "k16_road_dir": item.get("k16_road_dir"),
        "k16_endpoint_role": item.get("k16_endpoint_role"),
        "k16_search_dir": item.get("k16_search_dir"),
        "k16_search_max_m": item.get("k16_search_max_m"),
        "k16_step_m": item.get("k16_step_m"),
        "k16_cross_half_len_m": item.get("k16_cross_half_len_m"),
        "k16_output_cross_half_len_m": item.get("k16_output_cross_half_len_m"),
        "k16_s_found_m": item.get("k16_s_found_m"),
        "k16_s_best_m": item.get("k16_s_best_m"),
        "k16_found": item.get("k16_found"),
        "k16_min_dist_cross_to_drivezone_m": item.get("k16_min_dist_cross_to_drivezone_m"),
        "k16_break_reason": item.get("k16_break_reason"),
        "k16_refine_enable": item.get("k16_refine_enable"),
        "k16_refine_ahead_m": item.get("k16_refine_ahead_m"),
        "k16_refine_step_m": item.get("k16_refine_step_m"),
        "k16_first_hit_s_m": item.get("k16_first_hit_s_m"),
        "k16_refined_used": item.get("k16_refined_used"),
        "k16_s_refined_m": item.get("k16_s_refined_m"),
        "k16_first_hit_len_m": item.get("k16_first_hit_len_m"),
        "k16_refined_len_m": item.get("k16_refined_len_m"),
        "k16_refine_candidate_count": item.get("k16_refine_candidate_count"),
    }


def _transform_geometry_dict(geom: dict[str, Any], *, src_crs: str, dst_crs: str) -> dict[str, Any]:
    if src_crs == dst_crs:
        return geom
    out = dict(geom)
    if "coordinates" in out:
        out["coordinates"] = transform_coords_recursive(out["coordinates"], src_crs, dst_crs)
    return out


def write_anchor_geojson(
    *,
    path: Path,
    seed_results: list[dict[str, Any]],
    src_crs_name: str,
    dst_crs_name: str,
) -> None:
    features: list[dict[str, Any]] = []
    for item in seed_results:
        props = _props_min(item)

        pt = item.get("anchor_point")
        if isinstance(pt, Point):
            geom = mapping(pt)
            geom = _transform_geometry_dict(geom, src_crs=src_crs_name, dst_crs=dst_crs_name)
            features.append(
                {
                    "type": "Feature",
                    "properties": {**props, "feature_role": "anchor_point"},
                    "geometry": geom,
                }
            )

        line = item.get("crossline_opt")
        if isinstance(line, (LineString, MultiLineString)):
            geom = mapping(line)
            geom = _transform_geometry_dict(geom, src_crs=src_crs_name, dst_crs=dst_crs_name)
            features.append(
                {
                    "type": "Feature",
                    "properties": {**props, "feature_role": "crossline_opt"},
                    "geometry": geom,
                }
            )

    write_geojson(path, make_feature_collection(features, crs_name=dst_crs_name))


def write_intersection_opt_geojson(
    *,
    path: Path,
    seed_results: list[dict[str, Any]],
    src_crs_name: str,
    dst_crs_name: str,
) -> None:
    features: list[dict[str, Any]] = []
    def _piece_role(idx: int, piece_count: int) -> str:
        if piece_count >= 2:
            if idx == 0:
                return "branch_a_side"
            if idx == 1:
                return "branch_b_side"
        if piece_count == 1:
            return "single_piece"
        return f"piece_{int(idx)}"

    for item in seed_results:
        if bool(item.get("suppress_intersection_feature", False)):
            continue
        props = _props_min(item)
        merged_nodeids = item.get("merged_output_nodeids")
        if isinstance(merged_nodeids, list) and merged_nodeids:
            props.update(
                {
                    "nodeids": [int(x) for x in merged_nodeids],
                    "kinds": list(item.get("merged_output_kinds") or []),
                    "roles": list(item.get("merged_output_roles") or []),
                    "anchor_types": list(item.get("merged_output_anchor_types") or []),
                }
            )
        pieces = item.get("crossline_opt_pieces")
        if isinstance(pieces, list) and pieces:
            for idx, piece in enumerate(pieces):
                if not isinstance(piece, LineString):
                    continue
                geom = mapping(piece)
                geom = _transform_geometry_dict(geom, src_crs=src_crs_name, dst_crs=dst_crs_name)
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            **props,
                            "piece_idx": int(idx),
                            "piece_role": _piece_role(int(idx), len(pieces)),
                        },
                        "geometry": geom,
                    }
                )
            continue

        line = item.get("crossline_opt")
        if isinstance(line, LineString):
            geom = mapping(line)
            geom = _transform_geometry_dict(geom, src_crs=src_crs_name, dst_crs=dst_crs_name)
            features.append(
                {
                    "type": "Feature",
                    "properties": {**props, "piece_idx": 0, "piece_role": "single_piece"},
                    "geometry": geom,
                }
            )
            continue
        if isinstance(line, MultiLineString):
            for idx, ln in enumerate(line.geoms):
                if not isinstance(ln, LineString):
                    continue
                geom = mapping(ln)
                geom = _transform_geometry_dict(geom, src_crs=src_crs_name, dst_crs=dst_crs_name)
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            **props,
                            "piece_idx": int(idx),
                            "piece_role": _piece_role(int(idx), len(line.geoms)),
                        },
                        "geometry": geom,
                    }
                )

    write_geojson(path, make_feature_collection(features, crs_name=dst_crs_name))


def write_intersection_multi_geojson(
    *,
    path: Path,
    seed_results: list[dict[str, Any]],
    src_crs_name: str,
    dst_crs_name: str,
) -> None:
    features: list[dict[str, Any]] = []
    for item in seed_results:
        events = item.get("multibranch_event_lines")
        if not isinstance(events, list) or not events:
            continue
        props = _props_min(item)
        for idx, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            line = event.get("line")
            if not isinstance(line, LineString):
                continue
            geom = mapping(line)
            geom = _transform_geometry_dict(geom, src_crs=src_crs_name, dst_crs=dst_crs_name)
            evt_idx = int(event.get("event_idx", idx))
            evt_s = event.get("event_s_m")
            evt_dir = str(event.get("event_dir", "unknown"))
            pieces_at_event = event.get("pieces_count_at_event")
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        **props,
                        "event_idx": int(evt_idx),
                        "event_s_m": None if evt_s is None else float(evt_s),
                        "event_dir": evt_dir,
                        "pieces_count_at_event": None if pieces_at_event is None else int(pieces_at_event),
                        "expected_events": item.get("multibranch_expected_events"),
                        "raw_event": False,
                    },
                    "geometry": geom,
                }
            )
    write_geojson(path, make_feature_collection(features, crs_name=dst_crs_name))


__all__ = [
    "write_anchor_geojson",
    "write_intersection_opt_geojson",
    "write_intersection_multi_geojson",
    "write_json",
    "write_text",
]
