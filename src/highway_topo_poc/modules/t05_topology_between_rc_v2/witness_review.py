from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point

from .io import read_json, write_features_geojson, write_json
from .models import CorridorIdentity, CorridorWitness, Segment, SlotInterval
from .step3_arc_evidence import classify_topology_gap_rows
from .step3_corridor_identity import build_patch_geometry_cache, build_prior_reference_index
from .step5_conservative_road import shape_ref_line


_STEP5_TARGET_PAIRS = {
    "4625048846882874781:5384392508835506",
    "5384372208085190:5261514061535579261",
    "5389884430552920:2703260460721685999",
    "6460260817894928273:29626540",
}

_TOPOLOGY_GAP_TARGET_PAIRS = {
    "55353246:37687913",
    "760239:6963539359479390368",
    "791871:37687913",
}

_SAME_PAIR_MULTI_ARC_FOCUS_PAIRS = {
    "21779764:785642",
    "791873:791871",
}

_PATCH_CONTEXT_CACHE: dict[str, dict[str, Any]] = {}


def _pipeline():
    from . import pipeline as pipeline_module

    return pipeline_module


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def _patch_dir(run_root: Path | str, patch_id: str) -> Path:
    return Path(run_root) / "patches" / str(patch_id)


def _line_from_coords(coords: Any) -> LineString | None:
    pts = tuple(
        (float(item[0]), float(item[1]))
        for item in list(coords or [])
        if isinstance(item, (list, tuple)) and len(item) >= 2
    )
    if len(pts) < 2:
        return None
    line = LineString(list(pts))
    if line.is_empty or line.length <= 1e-6:
        return None
    return line


def _point_from_coords(coords: Any) -> Point | None:
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    return Point(float(coords[0]), float(coords[1]))


def _slot_payload_map(payload: dict[str, Any]) -> dict[str, dict[str, SlotInterval]]:
    out: dict[str, dict[str, SlotInterval]] = {}
    for segment_id, value in dict(payload.get("slot_mapping") or {}).items():
        out[str(segment_id)] = {
            "src": SlotInterval.from_dict(value["src"]),
            "dst": SlotInterval.from_dict(value["dst"]),
        }
    return out


def _patch_context(run_root: Path | str, patch_id: str) -> dict[str, Any]:
    patch_dir = _patch_dir(run_root, patch_id)
    key = str(patch_dir.resolve())
    cached = _PATCH_CONTEXT_CACHE.get(key)
    if cached is not None:
        return cached
    pipeline = _pipeline()
    step_state = {}
    for step_dir in ("step1", "step2", "step3", "step4", "step5", "step6"):
        state = _safe_read_json(patch_dir / step_dir / "step_state.json")
        if state:
            step_state = state
            break
    data_root = step_state.get("data_root")
    if not data_root:
        cached = {}
        _PATCH_CONTEXT_CACHE[key] = cached
        return cached
    try:
        params = dict(pipeline.DEFAULT_PARAMS)
        inputs, frame, prior_roads = pipeline.load_inputs_and_frame(data_root, patch_id, params=params)
        cached = {
            "inputs": inputs,
            "frame": frame,
            "prior_roads": prior_roads,
            "prior_index": build_prior_reference_index(prior_roads),
            "patch_geometry_cache": build_patch_geometry_cache(inputs, params),
            "xsec_map": pipeline._xsec_map(frame),
            "params": params,
            "metric_crs": str(frame.metric_crs),
        }
    except Exception:
        cached = {}
    _PATCH_CONTEXT_CACHE[key] = cached
    return cached


def _xsec_midpoint(xsec_map: dict[int, Any], nodeid: int) -> Point | None:
    pipeline = _pipeline()
    xsec = xsec_map.get(int(nodeid))
    if xsec is None:
        return None
    try:
        return pipeline._line_midpoint(xsec.geometry_metric())
    except Exception:
        return None


def _slot_midpoint(slot: SlotInterval | None) -> Point | None:
    if slot is None or slot.interval is None:
        return None
    pipeline = _pipeline()
    return pipeline._midpoint_of_interval(slot.interval)


def _shape_ref_line_for_row(
    *,
    row: dict[str, Any],
    segment: Segment | None,
    identity: CorridorIdentity | None,
    witness: CorridorWitness | None,
    slots: dict[str, SlotInterval] | None,
    prior_roads: list[Any],
    prior_index: dict[tuple[int, int], list[Any]] | None,
) -> tuple[LineString | None, str]:
    if segment is None:
        support_line = _line_from_coords(row.get("support_reference_coords", []))
        if support_line is not None:
            return support_line, "support_reference"
        return _line_from_coords(row.get("line_coords", [])), "topology_arc"
    if identity is None or slots is None or "src" not in slots or "dst" not in slots:
        return segment.geometry_metric(), "segment_support"
    try:
        line, mode = shape_ref_line(
            segment=segment,
            identity=identity,
            witness=witness,
            src_slot=slots["src"],
            dst_slot=slots["dst"],
            prior_roads=prior_roads,
            prior_index=prior_index,
        )
        return line, str(mode)
    except Exception:
        return segment.geometry_metric(), "segment_support"


def _corridor_width_m(
    *,
    witness: CorridorWitness | None,
    slots: dict[str, SlotInterval] | None,
) -> float:
    widths: list[float] = []
    if witness is not None and witness.selected_interval_rank is not None:
        for interval in witness.intervals:
            if int(interval.rank) == int(witness.selected_interval_rank):
                widths.append(float(interval.length_m))
                break
    if slots is not None:
        for tag in ("src", "dst"):
            slot = slots.get(tag)
            if slot is not None and slot.interval is not None:
                widths.append(float(slot.interval.length_m))
    if not widths:
        return 4.0
    width = float(sum(widths) / max(1, len(widths)))
    return max(3.0, min(8.0, width))


def _area_overlap_ratio(geom: Any, zone: Any) -> float:
    if geom is None or getattr(geom, "is_empty", True):
        return 0.0
    if zone is None or getattr(zone, "is_empty", True):
        return 0.0
    area = float(getattr(geom, "area", 0.0))
    if area <= 1e-6:
        return 0.0
    try:
        inter = geom.intersection(zone)
    except Exception:
        return 0.0
    return float(max(0.0, min(1.0, float(getattr(inter, "area", 0.0)) / max(area, 1e-6))))


def _witness_source(row: dict[str, Any]) -> str:
    traj_support_type = str(row.get("traj_support_type", "no_support"))
    prior_support_type = str(row.get("prior_support_type", "no_support"))
    if traj_support_type == "terminal_crossing_support":
        return "terminal_only"
    if traj_support_type == "partial_arc_support":
        return "partial_aggregate"
    if traj_support_type == "stitched_arc_support":
        return "stitched_aggregate"
    if prior_support_type == "prior_fallback_support":
        return "prior_fallback"
    return "unresolved"


def _support_type_major(row: dict[str, Any]) -> str:
    traj_support_type = str(row.get("traj_support_type", "no_support"))
    if traj_support_type != "no_support":
        return traj_support_type
    prior_support_type = str(row.get("prior_support_type", "no_support"))
    if prior_support_type == "prior_fallback_support":
        return "prior_fallback_support"
    return "no_support"


def _resolve_anchor_points(
    *,
    row: dict[str, Any],
    slots: dict[str, SlotInterval] | None,
    xsec_map: dict[int, Any],
) -> tuple[Point | None, str, Point | None, str]:
    src_slot_pt = _slot_midpoint((slots or {}).get("src"))
    if src_slot_pt is not None:
        src_pt = src_slot_pt
        src_source = "slot_midpoint"
    else:
        src_support_pt = _point_from_coords(row.get("support_anchor_src_coords"))
        if src_support_pt is not None:
            src_pt = src_support_pt
            src_source = "support_anchor"
        else:
            src_pt = _xsec_midpoint(xsec_map, int(row.get("src", 0)))
            src_source = "xsec_midpoint_fallback"

    dst_slot_pt = _slot_midpoint((slots or {}).get("dst"))
    if dst_slot_pt is not None:
        dst_pt = dst_slot_pt
        dst_source = "slot_midpoint"
    else:
        dst_support_pt = _point_from_coords(row.get("support_anchor_dst_coords"))
        if dst_support_pt is not None:
            dst_pt = dst_support_pt
            dst_source = "support_anchor"
        else:
            dst_pt = _xsec_midpoint(xsec_map, int(row.get("dst", 0)))
            dst_source = "xsec_midpoint_fallback"

    if src_pt is None:
        arc_line = _line_from_coords(row.get("line_coords", []))
        if arc_line is not None:
            src_pt = Point(float(arc_line.coords[0][0]), float(arc_line.coords[0][1]))
            src_source = "xsec_midpoint_fallback"
    if dst_pt is None:
        arc_line = _line_from_coords(row.get("line_coords", []))
        if arc_line is not None:
            dst_pt = Point(float(arc_line.coords[-1][0]), float(arc_line.coords[-1][1]))
            dst_source = "xsec_midpoint_fallback"
    return src_pt, str(src_source), dst_pt, str(dst_source)


def _patch_visual_rows(run_root: Path | str, patch_id: str) -> tuple[list[dict[str, Any]], list[tuple[Any, dict[str, Any]]], list[tuple[Any, dict[str, Any]]], list[tuple[Any, dict[str, Any]]], list[tuple[Any, dict[str, Any]]]]:
    patch_dir = _patch_dir(run_root, patch_id)
    metrics = _safe_read_json(patch_dir / "metrics.json")
    step3_payload = _safe_read_json(patch_dir / "step3" / "witness.json")
    step4_payload = _safe_read_json(patch_dir / "step4" / "corridor_identity.json")
    step5_payload = _safe_read_json(patch_dir / "step5" / "slot_mapping.json")
    step6_payload = _safe_read_json(patch_dir / "step6" / "final_roads.json")
    context = _patch_context(run_root, patch_id)

    witnesses = {str(item.segment_id): item for item in (CorridorWitness.from_dict(v) for v in step3_payload.get("witnesses", []))}
    identities = {str(item.segment_id): item for item in (CorridorIdentity.from_dict(v) for v in step4_payload.get("corridor_identities", []))}
    segments = {str(item.segment_id): item for item in (Segment.from_dict(v) for v in step4_payload.get("working_segments", []))}
    slots = _slot_payload_map(step5_payload)
    road_results = {str(item.get("segment_id", "")): dict(item) for item in step6_payload.get("road_results", [])}
    built_segments = {str(item.get("segment_id", "")) for item in step6_payload.get("roads", []) if str(item.get("segment_id", ""))}
    rows = list(metrics.get("full_legal_arc_registry", [])) or list(step4_payload.get("full_legal_arc_registry", []))
    xsec_map = dict(context.get("xsec_map") or {})
    prior_roads = list(context.get("prior_roads") or [])
    prior_index = context.get("prior_index")
    drivezone = getattr(context.get("inputs"), "drivezone_zone_metric", None)
    divstrip = (context.get("patch_geometry_cache") or {}).get("divstrip_buffer")

    review_rows: list[dict[str, Any]] = []
    chord_features: list[tuple[Any, dict[str, Any]]] = []
    support_features: list[tuple[Any, dict[str, Any]]] = []
    witness_line_features: list[tuple[Any, dict[str, Any]]] = []
    witness_polygon_features: list[tuple[Any, dict[str, Any]]] = []

    for row in rows:
        current = dict(row)
        working_segment_id = str(current.get("working_segment_id", ""))
        segment = segments.get(working_segment_id)
        identity = identities.get(working_segment_id)
        witness = witnesses.get(working_segment_id)
        slot_map = slots.get(working_segment_id)
        built_final_road = bool(current.get("built_final_road", False) or working_segment_id in built_segments)
        if built_final_road:
            current["unbuilt_stage"] = ""
            current["unbuilt_reason"] = ""
        build_result = dict(road_results.get(working_segment_id, {}))
        slot_status = str(current.get("slot_status", ""))
        if not slot_status:
            slot_status = "resolved" if slot_map and slot_map["src"].resolved and slot_map["dst"].resolved else "unresolved"

        src_anchor, src_anchor_source, dst_anchor, dst_anchor_source = _resolve_anchor_points(
            row=current,
            slots=slot_map,
            xsec_map=xsec_map,
        )
        chord = None
        if src_anchor is not None and dst_anchor is not None:
            chord = LineString([(float(src_anchor.x), float(src_anchor.y)), (float(dst_anchor.x), float(dst_anchor.y))])
        chord_features.append(
            (
                chord,
                {
                    "patch_id": str(patch_id),
                    "src": int(current.get("src", 0)),
                    "dst": int(current.get("dst", 0)),
                    "topology_arc_id": str(current.get("topology_arc_id", "")),
                    "src_anchor_source": str(src_anchor_source),
                    "dst_anchor_source": str(dst_anchor_source),
                },
            )
        )

        for item in list(current.get("traj_support_segments", [])):
            line = _line_from_coords(item.get("line_coords", []))
            support_features.append(
                (
                    line,
                    {
                        "patch_id": str(patch_id),
                        "src": int(current.get("src", 0)),
                        "dst": int(current.get("dst", 0)),
                        "topology_arc_id": str(current.get("topology_arc_id", "")),
                        "traj_id": str(item.get("traj_id", "")),
                        "support_type": str(item.get("support_type", "")),
                        "segment_order": int(item.get("segment_order", 0)),
                        "is_stitched": bool(item.get("is_stitched", False)),
                        "support_score": float(item.get("support_score", 0.0)),
                        "support_length_m": float(item.get("support_length_m", 0.0)),
                        "source_span_start_idx": int(item.get("source_span_start_idx", 0)),
                        "source_span_end_idx": int(item.get("source_span_end_idx", 0)),
                    },
                )
            )

        witness_line, witness_line_mode = _shape_ref_line_for_row(
            row=current,
            segment=segment,
            identity=identity,
            witness=witness,
            slots=slot_map,
            prior_roads=prior_roads,
            prior_index=prior_index,
        )
        support_count = int(len(set(str(v) for v in current.get("traj_support_ids", []))))
        support_total_length_m = float(sum(float(item.get("support_length_m", 0.0)) for item in current.get("traj_support_segments", [])))
        final_stage = "built" if built_final_road else str(current.get("unbuilt_stage") or build_result.get("reject_stage") or "")
        final_reason = "built" if built_final_road else str(current.get("unbuilt_reason") or build_result.get("reason") or "")
        witness_line_features.append(
            (
                witness_line,
                {
                    "patch_id": str(patch_id),
                    "src": int(current.get("src", 0)),
                    "dst": int(current.get("dst", 0)),
                    "topology_arc_id": str(current.get("topology_arc_id", "")),
                    "corridor_identity": str(current.get("corridor_identity", "unresolved")),
                    "witness_source": str(_witness_source(current)),
                    "support_count": int(support_count),
                    "support_total_length_m": float(support_total_length_m),
                    "slot_status": str(slot_status),
                    "final_stage": str(final_stage),
                    "final_reason": str(final_reason),
                    "witness_line_mode": str(witness_line_mode),
                },
            )
        )

        corridor_width_m = _corridor_width_m(witness=witness, slots=slot_map)
        witness_polygon = witness_line.buffer(float(corridor_width_m) / 2.0, cap_style=2, join_style=2) if witness_line is not None else None
        drivezone_overlap_ratio = _area_overlap_ratio(witness_polygon, drivezone)
        divstrip_overlap_ratio = _area_overlap_ratio(witness_polygon, divstrip)
        witness_polygon_features.append(
            (
                witness_polygon,
                {
                    "patch_id": str(patch_id),
                    "src": int(current.get("src", 0)),
                    "dst": int(current.get("dst", 0)),
                    "topology_arc_id": str(current.get("topology_arc_id", "")),
                    "corridor_identity": str(current.get("corridor_identity", "unresolved")),
                    "support_type_major": str(_support_type_major(current)),
                    "drivezone_overlap_ratio": float(drivezone_overlap_ratio),
                    "divstrip_overlap_ratio": float(divstrip_overlap_ratio),
                    "corridor_width_m": float(corridor_width_m),
                    "slot_status": str(slot_status),
                    "built_final_road": bool(built_final_road),
                },
            )
        )

        review_rows.append(
            {
                "patch_id": str(patch_id),
                "src": int(current.get("src", 0)),
                "dst": int(current.get("dst", 0)),
                "pair": str(current.get("pair", "")),
                "raw_pair": str(current.get("raw_pair", current.get("pair", ""))),
                "canonical_pair": str(current.get("canonical_pair", current.get("pair", ""))),
                "topology_arc_id": str(current.get("topology_arc_id", "")),
                "is_direct_legal": bool(current.get("is_direct_legal", current.get("topology_arc_is_direct_legal", False))),
                "is_unique": bool(current.get("is_unique", current.get("topology_arc_is_unique", False))),
                "entered_main_flow": bool(current.get("entered_main_flow", False)),
                "direct_arc_count_for_pair": int(current.get("direct_arc_count_for_pair", 0)),
                "blocked_diagnostic_only": bool(current.get("blocked_diagnostic_only", False)),
                "blocked_diagnostic_reason": str(current.get("blocked_diagnostic_reason", "")),
                "controlled_entry_allowed": bool(current.get("controlled_entry_allowed", False)),
                "topology_gap_decision": str(current.get("topology_gap_decision", "")),
                "topology_gap_reason": str(current.get("topology_gap_reason", "")),
                "arc_structure_type": str(current.get("arc_structure_type", "")),
                "arc_selection_rule": str(current.get("arc_selection_rule", "")),
                "arc_selection_allow_multi_output": bool(current.get("arc_selection_allow_multi_output", False)),
                "arc_selection_rule_reason": str(current.get("arc_selection_rule_reason", "")),
                "arc_selection_peer_pairs": list(current.get("arc_selection_peer_pairs", [])),
                "arc_selection_shared_downstream_nodes": list(current.get("arc_selection_shared_downstream_nodes", [])),
                "node_path": [int(v) for v in current.get("node_path", []) if v is not None],
                "traj_support_type": str(current.get("traj_support_type", "no_support")),
                "traj_support_ids": [str(v) for v in current.get("traj_support_ids", [])],
                "traj_support_count": int(support_count),
                "traj_support_coverage_ratio": float(current.get("traj_support_coverage_ratio", 0.0)),
                "prior_support_type": str(current.get("prior_support_type", "no_support")),
                "support_anchor_src_coords": current.get("support_anchor_src_coords"),
                "support_anchor_dst_coords": current.get("support_anchor_dst_coords"),
                "stitched_used": bool(
                    str(current.get("traj_support_type", "")) == "stitched_arc_support"
                    or any(bool(item.get("is_stitched", False)) for item in current.get("traj_support_segments", []))
                ),
                "corridor_identity": str(current.get("corridor_identity", "unresolved")),
                "slot_status": str(slot_status),
                "built_final_road": bool(built_final_road),
                "unbuilt_stage": str(final_stage if not built_final_road else ""),
                "unbuilt_reason": str(final_reason if not built_final_road else ""),
                "drivezone_overlap_ratio": float(drivezone_overlap_ratio),
                "divstrip_overlap_ratio": float(divstrip_overlap_ratio),
                "support_total_length_m": float(support_total_length_m),
                "support_type_major": str(_support_type_major(current)),
                "src_anchor_source": str(src_anchor_source),
                "dst_anchor_source": str(dst_anchor_source),
            }
        )

    return review_rows, chord_features, support_features, witness_line_features, witness_polygon_features


def _step5_issue_classification(row: dict[str, Any]) -> str:
    if bool(row.get("built_final_road", False)):
        return "step5_issue_confirmed"
    if str(row.get("unbuilt_stage", "")) != "step5_geometry_rejected":
        return "witness_layer_issue"
    if float(row.get("divstrip_overlap_ratio", 0.0)) > 0.12:
        return "witness_layer_issue"
    if float(row.get("drivezone_overlap_ratio", 0.0)) < 0.80:
        return "witness_layer_issue"
    if str(row.get("corridor_identity", "")) not in {"witness_based", "prior_based"}:
        return "witness_layer_issue"
    if str(row.get("slot_status", "")) != "resolved":
        return "witness_layer_issue"
    return "step5_issue_confirmed"


def _topology_gap_decision_rows(
    *,
    patch_id: str,
    review_rows: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    by_pair = {
        str(row.get("pair", "")): dict(row)
        for row in review_rows
        if str(row.get("patch_id", "")) == str(patch_id)
    }
    decisions = classify_topology_gap_rows(list(by_pair.values()), params=dict(params or {}))
    rows: list[dict[str, Any]] = []
    for pair_id in sorted(_TOPOLOGY_GAP_TARGET_PAIRS):
        row = dict(by_pair.get(pair_id) or {})
        if not row:
            src_text, dst_text = str(pair_id).split(":", 1)
            row = {
                "patch_id": str(patch_id),
                "src": int(src_text),
                "dst": int(dst_text),
                "pair": str(pair_id),
            }
        decision = dict(decisions.get(pair_id) or {})
        classification = str(
            row.get("topology_gap_decision")
            or decision.get("decision")
            or ("gap_remain_blocked" if str(row.get("blocked_diagnostic_reason", "")) == "topology_gap_unresolved" else "")
        )
        reason = str(
            row.get("topology_gap_reason")
            or decision.get("reason")
            or row.get("blocked_diagnostic_reason", "")
            or row.get("unbuilt_reason", "")
        )
        rows.append(
            {
                "patch_id": str(patch_id),
                "src": int(row.get("src", 0)),
                "dst": int(row.get("dst", 0)),
                "pair": str(pair_id),
                "topology_arc_id": str(row.get("topology_arc_id", "")),
                "gap_classification": str(classification),
                "gap_reason": str(reason),
                "controlled_entry_allowed": bool(
                    row.get("controlled_entry_allowed", decision.get("controlled_entry_allowed", False))
                ),
                "entered_main_flow": bool(row.get("entered_main_flow", False)),
                "built_final_road": bool(row.get("built_final_road", False)),
                "traj_support_type": str(row.get("traj_support_type", "no_support")),
                "traj_support_count": int(row.get("traj_support_count", 0)),
                "traj_support_coverage_ratio": float(row.get("traj_support_coverage_ratio", 0.0)),
                "corridor_identity": str(row.get("corridor_identity", "unresolved")),
                "slot_status": str(row.get("slot_status", "unresolved")),
                "unbuilt_stage": str(row.get("unbuilt_stage", "")),
                "unbuilt_reason": str(row.get("unbuilt_reason", "")),
                "src_anchor_source": str(row.get("src_anchor_source", "")),
                "dst_anchor_source": str(row.get("dst_anchor_source", "")),
                "drivezone_overlap_ratio": float(row.get("drivezone_overlap_ratio", 0.0)),
                "divstrip_overlap_ratio": float(row.get("divstrip_overlap_ratio", 0.0)),
                "support_total_length_m": float(row.get("support_total_length_m", 0.0)),
            }
        )
    return rows


def _same_pair_multi_arc_rows(
    *,
    patch_id: str,
    review_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    patch_rows = [dict(row) for row in review_rows if str(row.get("patch_id", "")) == str(patch_id)]
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for row in patch_rows:
        by_pair.setdefault(str(row.get("pair", "")), []).append(dict(row))
    rows: list[dict[str, Any]] = []
    for pair_id, pair_rows in sorted(by_pair.items()):
        pair_arc_count = max(int(max((int(item.get("direct_arc_count_for_pair", 0)) for item in pair_rows), default=0)), int(len(pair_rows)))
        if pair_arc_count <= 1 and pair_id not in _SAME_PAIR_MULTI_ARC_FOCUS_PAIRS:
            continue
        built_rows = [item for item in pair_rows if bool(item.get("built_final_road", False))]
        rows.append(
            {
                "patch_id": str(patch_id),
                "src": int(pair_rows[0].get("src", 0)),
                "dst": int(pair_rows[0].get("dst", 0)),
                "pair": str(pair_id),
                "pair_arc_count": int(pair_arc_count),
                "arc_ids": [str(item.get("topology_arc_id", "")) for item in pair_rows if str(item.get("topology_arc_id", ""))],
                "excluded_from_unique_denominator_reason": "same_pair_multi_arc",
                "current_business_status": (
                    "multi_arc_with_built_sibling_under_observation"
                    if built_rows
                    else "multi_arc_no_built_sibling_visual_gap_candidate"
                ),
                "next_rule_needed": "multi_arc_selection_rule",
                "has_built_sibling_arc": bool(built_rows),
                "built_sibling_arc_ids": [str(item.get("topology_arc_id", "")) for item in built_rows if str(item.get("topology_arc_id", ""))],
                "chord_available": bool(any(str(item.get("src_anchor_source", "")) and str(item.get("dst_anchor_source", "")) for item in pair_rows)),
                "witness_available": bool(any(str(item.get("traj_support_type", "no_support")) != "no_support" for item in pair_rows)),
                "visual_gap_note": (
                    "built_sibling_present_visual_gap_possible"
                    if built_rows
                    else "no_built_sibling_visual_gap_candidate"
                ),
            }
        )
    present_pairs = {str(row.get("pair", "")) for row in rows}
    for pair_id in sorted(_SAME_PAIR_MULTI_ARC_FOCUS_PAIRS - present_pairs):
        src_text, dst_text = str(pair_id).split(":", 1)
        rows.append(
            {
                "patch_id": str(patch_id),
                "src": int(src_text),
                "dst": int(dst_text),
                "pair": str(pair_id),
                "pair_arc_count": 0,
                "arc_ids": [],
                "excluded_from_unique_denominator_reason": "same_pair_multi_arc",
                "current_business_status": "multi_arc_missing_from_review_rows",
                "next_rule_needed": "multi_arc_selection_rule",
                "has_built_sibling_arc": False,
                "built_sibling_arc_ids": [],
                "chord_available": False,
                "witness_available": False,
                "visual_gap_note": "focus_pair_missing_from_review_rows",
            }
        )
    rows.sort(key=lambda item: (str(item.get("pair", "")), str(item.get("patch_id", ""))))
    return rows


def write_witness_vis_step5_recovery_bundle(
    *,
    run_root: Path | str,
    output_root: Path | str,
    patch_ids: list[str],
    complex_patch_id: str,
) -> dict[str, Any]:
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)

    review_rows: list[dict[str, Any]] = []
    chord_features: list[tuple[Any, dict[str, Any]]] = []
    support_features: list[tuple[Any, dict[str, Any]]] = []
    witness_line_features: list[tuple[Any, dict[str, Any]]] = []
    witness_polygon_features: list[tuple[Any, dict[str, Any]]] = []

    for patch_id in patch_ids:
        rows, chords, supports, witness_lines, witness_polygons = _patch_visual_rows(run_root, patch_id)
        review_rows.extend(rows)
        chord_features.extend(chords)
        support_features.extend(supports)
        witness_line_features.extend(witness_lines)
        witness_polygon_features.extend(witness_polygons)

    corridor_review = {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": review_rows,
    }

    step5_target_rows = []
    for row in review_rows:
        if str(row.get("patch_id", "")) != str(complex_patch_id):
            continue
        if str(row.get("pair", "")) not in _STEP5_TARGET_PAIRS:
            continue
        current = dict(row)
        current["issue_classification"] = _step5_issue_classification(current)
        current["final_result"] = "built" if bool(current.get("built_final_road", False)) else "unbuilt"
        step5_target_rows.append(current)

    step5_review = {
        "patch_id": str(complex_patch_id),
        "target_arc_count": int(len(step5_target_rows)),
        "built_count": int(sum(1 for item in step5_target_rows if bool(item.get("built_final_road", False)))),
        "witness_layer_issue_count": int(sum(1 for item in step5_target_rows if str(item.get("issue_classification", "")) == "witness_layer_issue")),
        "step5_issue_confirmed_count": int(sum(1 for item in step5_target_rows if str(item.get("issue_classification", "")) == "step5_issue_confirmed")),
        "rows": step5_target_rows,
    }

    complex_context = _patch_context(run_root, complex_patch_id)
    topology_gap_rows = _topology_gap_decision_rows(
        patch_id=str(complex_patch_id),
        review_rows=review_rows,
        params=dict(complex_context.get("params") or {}),
    )
    same_pair_rows = _same_pair_multi_arc_rows(
        patch_id=str(complex_patch_id),
        review_rows=review_rows,
    )
    strict_total = int(
        sum(
            1
            for row in review_rows
            if str(row.get("patch_id", "")) == str(complex_patch_id)
            and bool(row.get("is_direct_legal", False))
            and bool(row.get("is_unique", False))
        )
    )
    strict_built = int(
        sum(
            1
            for row in review_rows
            if str(row.get("patch_id", "")) == str(complex_patch_id)
            and bool(row.get("is_direct_legal", False))
            and bool(row.get("is_unique", False))
            and bool(row.get("built_final_road", False))
        )
    )
    strict_vs_visual_summary = {
        "patch_id": str(complex_patch_id),
        "strict_coverage": {
            "built": int(strict_built),
            "total": int(strict_total),
            "rate": float((strict_built / max(1, strict_total)) if strict_total else 0.0),
        },
        "visual_observation": {
            "same_pair_multi_arc_observation_count": int(len(same_pair_rows)),
            "same_pair_multi_arc_focus_pair_count": int(sum(1 for row in same_pair_rows if str(row.get("pair", "")) in _SAME_PAIR_MULTI_ARC_FOCUS_PAIRS)),
            "built_sibling_present_count": int(sum(1 for row in same_pair_rows if bool(row.get("has_built_sibling_arc", False)))),
            "observation_pairs": [str(row.get("pair", "")) for row in same_pair_rows],
        },
    }

    write_features_geojson(output_root_path / "arc_crosssection_chords.geojson", chord_features)
    write_features_geojson(output_root_path / "arc_traj_support_segments.geojson", support_features)
    write_features_geojson(output_root_path / "arc_corridor_witness_lines.geojson", witness_line_features)
    write_features_geojson(output_root_path / "arc_corridor_witness_polygons.geojson", witness_polygon_features)
    write_json(output_root_path / "corridor_witness_review.json", corridor_review)
    with (output_root_path / "corridor_witness_review.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "patch_id",
                "src",
                "dst",
                "pair",
                "topology_arc_id",
                "is_direct_legal",
                "is_unique",
                "entered_main_flow",
                "direct_arc_count_for_pair",
                "blocked_diagnostic_only",
                "blocked_diagnostic_reason",
                "controlled_entry_allowed",
                "topology_gap_decision",
                "topology_gap_reason",
                "traj_support_type",
                "traj_support_count",
                "stitched_used",
                "corridor_identity",
                "slot_status",
                "built_final_road",
                "unbuilt_stage",
                "unbuilt_reason",
                "drivezone_overlap_ratio",
                "divstrip_overlap_ratio",
                "support_total_length_m",
                "support_type_major",
                "src_anchor_source",
                "dst_anchor_source",
            ],
        )
        writer.writeheader()
        for row in review_rows:
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})
    topology_gap_review = {
        "patch_id": str(complex_patch_id),
        "row_count": int(len(topology_gap_rows)),
        "rows": topology_gap_rows,
    }
    write_json(output_root_path / "topology_gap_decision_review.json", topology_gap_review)
    with (output_root_path / "topology_gap_decision_review.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "patch_id",
                "src",
                "dst",
                "pair",
                "topology_arc_id",
                "gap_classification",
                "gap_reason",
                "controlled_entry_allowed",
                "entered_main_flow",
                "built_final_road",
                "traj_support_type",
                "traj_support_count",
                "traj_support_coverage_ratio",
                "corridor_identity",
                "slot_status",
                "unbuilt_stage",
                "unbuilt_reason",
                "src_anchor_source",
                "dst_anchor_source",
                "drivezone_overlap_ratio",
                "divstrip_overlap_ratio",
                "support_total_length_m",
            ],
        )
        writer.writeheader()
        for row in topology_gap_rows:
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})
    same_pair_multi_arc_observation = {
        "patch_id": str(complex_patch_id),
        "row_count": int(len(same_pair_rows)),
        "rows": same_pair_rows,
    }
    write_json(output_root_path / "same_pair_multi_arc_observation.json", same_pair_multi_arc_observation)
    with (output_root_path / "same_pair_multi_arc_observation.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "patch_id",
                "src",
                "dst",
                "pair",
                "pair_arc_count",
                "arc_ids",
                "excluded_from_unique_denominator_reason",
                "current_business_status",
                "next_rule_needed",
                "has_built_sibling_arc",
                "built_sibling_arc_ids",
                "chord_available",
                "witness_available",
                "visual_gap_note",
            ],
        )
        writer.writeheader()
        for row in same_pair_rows:
            payload = dict(row)
            payload["arc_ids"] = ",".join(str(v) for v in row.get("arc_ids", []))
            payload["built_sibling_arc_ids"] = ",".join(str(v) for v in row.get("built_sibling_arc_ids", []))
            writer.writerow({key: payload.get(key, "") for key in writer.fieldnames})
    write_json(output_root_path / "strict_vs_visual_gap_summary.json", strict_vs_visual_summary)
    write_json(output_root_path / "complex_patch_step5_recovery_review.json", step5_review)
    write_json(
        output_root_path / "debug" / "step5_target_arc_examples.json",
        {"rows": step5_target_rows},
    )
    write_json(
        output_root_path / "debug" / "witness_layer_issue_examples.json",
        {"rows": [dict(item) for item in step5_target_rows if str(item.get("issue_classification", "")) == "witness_layer_issue"]},
    )
    write_features_geojson(
        output_root_path / "debug" / "topology_gap_arc_examples.geojson",
        [
            (geom, dict(props))
            for geom, props in chord_features
            if f"{int(props.get('src', 0))}:{int(props.get('dst', 0))}" in _TOPOLOGY_GAP_TARGET_PAIRS
        ],
    )
    write_features_geojson(
        output_root_path / "debug" / "same_pair_multi_arc_chords.geojson",
        [
            (geom, dict(props))
            for geom, props in chord_features
            if f"{int(props.get('src', 0))}:{int(props.get('dst', 0))}" in {str(row.get("pair", "")) for row in same_pair_rows}
        ],
    )
    return {
        "corridor_witness_review": corridor_review,
        "complex_patch_step5_recovery_review": step5_review,
        "topology_gap_decision_review": topology_gap_review,
        "same_pair_multi_arc_observation": same_pair_multi_arc_observation,
        "strict_vs_visual_gap_summary": strict_vs_visual_summary,
    }


__all__ = ["write_witness_vis_step5_recovery_bundle"]
