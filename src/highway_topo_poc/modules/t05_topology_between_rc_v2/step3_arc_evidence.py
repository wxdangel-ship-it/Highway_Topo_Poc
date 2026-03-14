from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point

from .io import write_json, write_lines_geojson
from .models import CorridorWitness, Segment, coords_to_line, line_to_coords


def _pipeline():
    from . import pipeline as pipeline_module

    return pipeline_module


def _arc_line(row: dict[str, Any]) -> LineString | None:
    coords = tuple(
        (float(item[0]), float(item[1]))
        for item in row.get("line_coords", [])
        if isinstance(item, (list, tuple)) and len(item) >= 2
    )
    if len(coords) < 2:
        return None
    line = coords_to_line(coords)
    if line.is_empty or line.length <= 1e-6:
        return None
    return line


def _trajectory_points(traj: Any) -> list[tuple[float, float]]:
    xyz = getattr(traj, "xyz_metric", None)
    if xyz is None:
        return []
    return [(float(row[0]), float(row[1])) for row in xyz if row is not None and len(row) >= 2]


def _group_projected_spans(
    *,
    projected_rows: list[tuple[int, float]],
    max_seq_gap: int,
    max_proj_gap_m: float,
    arc_length_m: float,
    min_span_ratio: float,
    min_span_length_m: float,
) -> list[dict[str, Any]]:
    if len(projected_rows) < 2 or arc_length_m <= 1e-6:
        return []
    spans: list[list[tuple[int, float]]] = [[projected_rows[0]]]
    for idx, proj_s in projected_rows[1:]:
        prev_idx, prev_proj = spans[-1][-1]
        if (int(idx) - int(prev_idx)) <= int(max_seq_gap) and abs(float(proj_s) - float(prev_proj)) <= float(max_proj_gap_m):
            spans[-1].append((int(idx), float(proj_s)))
            continue
        spans.append([(int(idx), float(proj_s))])
    out: list[dict[str, Any]] = []
    for rows in spans:
        if len(rows) < 2:
            continue
        start_s = float(min(item[1] for item in rows))
        end_s = float(max(item[1] for item in rows))
        span_len = max(0.0, float(end_s - start_s))
        span_ratio = float(span_len / max(arc_length_m, 1e-6))
        if span_len < float(min_span_length_m) and span_ratio < float(min_span_ratio):
            continue
        out.append(
            {
                "start_s": float(start_s),
                "end_s": float(end_s),
                "span_length_m": float(span_len),
                "coverage_ratio": float(span_ratio),
            }
        )
    return out


def _trajectory_support_spans(
    *,
    arc_line: LineString,
    traj: Any,
    buffer_m: float,
    min_span_ratio: float,
    min_span_length_m: float,
    max_seq_gap: int,
    max_proj_gap_m: float,
) -> list[dict[str, Any]]:
    points_xy = _trajectory_points(traj)
    if len(points_xy) < 2 or arc_line.is_empty or arc_line.length <= 1e-6:
        return []
    projected_rows: list[tuple[int, float]] = []
    for idx, (x, y) in enumerate(points_xy):
        if float(arc_line.distance(Point(float(x), float(y)))) > float(buffer_m):
            continue
        projected_rows.append((int(idx), float(arc_line.project(Point(float(x), float(y))))))
    return _group_projected_spans(
        projected_rows=projected_rows,
        max_seq_gap=max_seq_gap,
        max_proj_gap_m=max_proj_gap_m,
        arc_length_m=float(arc_line.length),
        min_span_ratio=min_span_ratio,
        min_span_length_m=min_span_length_m,
    )


def _terminal_crossing_support(
    *,
    src_nodeid: int,
    dst_nodeid: int,
    inputs: Any,
    frame: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    pipeline = _pipeline()
    divstrip_buffer = pipeline.load_divstrip_buffer(inputs.divstrip_zone_metric, float(params["DIVSTRIP_BUFFER_M"]))
    hit_buffer = float(params["TRAJ_XSEC_HIT_BUFFER_M"])
    traj_ids: list[str] = []
    for traj in getattr(inputs, "trajectories", []) or []:
        events = pipeline._trajectory_events(
            traj,
            frame,
            hit_buffer,
            drivezone=inputs.drivezone_zone_metric,
            divstrip_buffer=divstrip_buffer,
        )
        ordered_hits = [int(event.get("nodeid", 0)) for event in events]
        found = False
        for idx, nodeid in enumerate(ordered_hits):
            if int(nodeid) != int(src_nodeid):
                continue
            if any(int(next_nodeid) == int(dst_nodeid) for next_nodeid in ordered_hits[idx + 1 :]):
                found = True
                break
        if found:
            traj_ids.append(str(getattr(traj, "traj_id", "")))
    return {"traj_ids": sorted(set(traj_ids)), "count": int(len(set(traj_ids)))}


def _prior_support_type(*, src_nodeid: int, dst_nodeid: int, prior_roads: list[Any]) -> tuple[str, bool]:
    for road in prior_roads:
        snodeid = int(getattr(road, "snodeid", 0))
        enodeid = int(getattr(road, "enodeid", 0))
        if (int(snodeid), int(enodeid)) == (int(src_nodeid), int(dst_nodeid)):
            return "prior_fallback_support", True
        if (int(snodeid), int(enodeid)) == (int(dst_nodeid), int(src_nodeid)):
            return "prior_fallback_support", True
    return "no_support", False


def _support_type_for_arc(
    *,
    row: dict[str, Any],
    arc_line: LineString | None,
    inputs: Any,
    frame: Any,
    prior_roads: list[Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    buffer_m = float(params.get("ARC_EVIDENCE_BUFFER_M", 8.0))
    min_span_ratio = float(params.get("ARC_PARTIAL_MIN_COVERAGE_RATIO", 0.18))
    min_span_length_m = float(params.get("ARC_PARTIAL_MIN_LENGTH_M", 12.0))
    max_seq_gap = int(params.get("ARC_STITCH_MAX_SEQ_GAP", 12))
    max_proj_gap_m = float(params.get("ARC_STITCH_MAX_PROJ_GAP_M", 25.0))
    stitched_min_ratio = float(params.get("ARC_STITCH_MIN_COVERAGE_RATIO", 0.72))
    endpoint_margin_ratio = float(params.get("ARC_STITCH_ENDPOINT_MARGIN_RATIO", 0.18))

    prior_support_type, prior_available = _prior_support_type(
        src_nodeid=int(row["src"]),
        dst_nodeid=int(row["dst"]),
        prior_roads=prior_roads,
    )
    if arc_line is None:
        return {
            "traj_support_type": "no_support",
            "traj_support_ids": [],
            "traj_support_span_count": 0,
            "traj_support_coverage_ratio": 0.0,
            "traj_support_spans": [],
            "prior_support_type": prior_support_type,
            "prior_support_available": bool(prior_available),
        }

    terminal = _terminal_crossing_support(
        src_nodeid=int(row["src"]),
        dst_nodeid=int(row["dst"]),
        inputs=inputs,
        frame=frame,
        params=params,
    )
    span_rows: list[dict[str, Any]] = []
    span_traj_ids: list[str] = []
    for traj in getattr(inputs, "trajectories", []) or []:
        spans = _trajectory_support_spans(
            arc_line=arc_line,
            traj=traj,
            buffer_m=buffer_m,
            min_span_ratio=min_span_ratio,
            min_span_length_m=min_span_length_m,
            max_seq_gap=max_seq_gap,
            max_proj_gap_m=max_proj_gap_m,
        )
        if not spans:
            continue
        traj_id = str(getattr(traj, "traj_id", ""))
        span_traj_ids.append(traj_id)
        for span in spans:
            span_rows.append({**dict(span), "traj_id": traj_id})
    traj_ids = sorted(set(list(terminal["traj_ids"]) + span_traj_ids))
    if terminal["count"] > 0:
        coverage_ratio = 1.0 if arc_line.length > 1e-6 else 0.0
        return {
            "traj_support_type": "terminal_crossing_support",
            "traj_support_ids": traj_ids,
            "traj_support_span_count": int(max(1, len(span_rows))),
            "traj_support_coverage_ratio": float(coverage_ratio),
            "traj_support_spans": span_rows,
            "prior_support_type": prior_support_type,
            "prior_support_available": bool(prior_available),
        }
    if not span_rows:
        return {
            "traj_support_type": "no_support",
            "traj_support_ids": [],
            "traj_support_span_count": 0,
            "traj_support_coverage_ratio": 0.0,
            "traj_support_spans": [],
            "prior_support_type": prior_support_type,
            "prior_support_available": bool(prior_available),
        }

    span_rows = sorted(span_rows, key=lambda item: (float(item["start_s"]), float(item["end_s"])))
    merged: list[list[float]] = []
    for span in span_rows:
        start_s = float(span["start_s"])
        end_s = float(span["end_s"])
        if not merged or start_s > float(merged[-1][1]) + float(max_proj_gap_m):
            merged.append([start_s, end_s])
            continue
        merged[-1][1] = max(float(merged[-1][1]), end_s)
    covered_length = float(sum(max(0.0, row[1] - row[0]) for row in merged))
    coverage_ratio = float(covered_length / max(float(arc_line.length), 1e-6))
    endpoint_margin = float(arc_line.length) * float(endpoint_margin_ratio)
    covers_start = bool(merged and float(merged[0][0]) <= endpoint_margin)
    covers_end = bool(merged and float(merged[-1][1]) >= float(arc_line.length) - endpoint_margin)
    stitched = bool(len(span_rows) >= 2 and covers_start and covers_end and coverage_ratio >= stitched_min_ratio)
    return {
        "traj_support_type": "stitched_arc_support" if stitched else "partial_arc_support",
        "traj_support_ids": traj_ids,
        "traj_support_span_count": int(len(span_rows)),
        "traj_support_coverage_ratio": float(coverage_ratio),
        "traj_support_spans": span_rows,
        "prior_support_type": prior_support_type,
        "prior_support_available": bool(prior_available),
    }


def _support_source_modes(traj_support_type: str, prior_support_type: str) -> tuple[str, ...]:
    if str(traj_support_type) != "no_support" and str(prior_support_type) == "prior_fallback_support":
        return ("prior", "traj")
    if str(traj_support_type) != "no_support":
        return ("traj",)
    if str(prior_support_type) == "prior_fallback_support":
        return ("prior",)
    return ("arc",)


def _support_formation_reason(traj_support_type: str, prior_support_type: str, selected_segment_id: str) -> str:
    if str(selected_segment_id):
        return "arc_first_selected_segment"
    if str(traj_support_type):
        if str(traj_support_type) == "terminal_crossing_support":
            return "arc_first_terminal_support"
        if str(traj_support_type) == "partial_arc_support":
            return "arc_first_partial_support"
        if str(traj_support_type) == "stitched_arc_support":
            return "arc_first_stitched_support"
    if str(prior_support_type) == "prior_fallback_support":
        return "arc_first_prior_fallback"
    return "arc_first_no_support"


def _materialize_working_segment(
    *,
    row: dict[str, Any],
    selected_segment: Segment | None,
    inputs: Any,
    params: dict[str, Any],
) -> Segment:
    pipeline = _pipeline()
    if selected_segment is not None:
        support_ids = tuple(sorted(set([*selected_segment.support_traj_ids, *[str(v) for v in row.get("traj_support_ids", [])]])))
        return Segment(
            segment_id=str(selected_segment.segment_id),
            src_nodeid=int(selected_segment.src_nodeid),
            dst_nodeid=int(selected_segment.dst_nodeid),
            direction=str(selected_segment.direction),
            geometry_coords=tuple(selected_segment.geometry_coords),
            candidate_ids=tuple(selected_segment.candidate_ids),
            source_modes=_support_source_modes(str(row.get("traj_support_type", "")), str(row.get("prior_support_type", ""))),
            support_traj_ids=support_ids,
            support_count=max(int(selected_segment.support_count), int(len(support_ids))),
            dedup_count=int(selected_segment.dedup_count),
            representative_offset_m=float(selected_segment.representative_offset_m),
            other_xsec_crossing_count=int(selected_segment.other_xsec_crossing_count),
            tolerated_other_xsec_crossings=int(selected_segment.tolerated_other_xsec_crossings),
            prior_supported=bool(row.get("prior_support_available", False) or selected_segment.prior_supported),
            formation_reason=str(_support_formation_reason(str(row.get("traj_support_type", "")), str(row.get("prior_support_type", "")), str(selected_segment.segment_id))),
            length_m=float(selected_segment.length_m),
            drivezone_ratio=float(selected_segment.drivezone_ratio),
            crosses_divstrip=bool(selected_segment.crosses_divstrip),
            topology_arc_id=str(selected_segment.topology_arc_id),
            topology_arc_source_type=str(selected_segment.topology_arc_source_type),
            topology_arc_edge_ids=tuple(selected_segment.topology_arc_edge_ids),
            topology_arc_node_path=tuple(selected_segment.topology_arc_node_path),
            topology_arc_is_direct_legal=bool(selected_segment.topology_arc_is_direct_legal),
            topology_arc_is_unique=bool(selected_segment.topology_arc_is_unique),
            bridge_candidate_retained=False,
            bridge_chain_exists=bool(selected_segment.bridge_chain_exists),
            bridge_chain_unique=bool(selected_segment.bridge_chain_unique),
            bridge_chain_nodes=tuple(selected_segment.bridge_chain_nodes),
            bridge_chain_source=str(selected_segment.bridge_chain_source),
            bridge_diagnostic_reason=str(selected_segment.bridge_diagnostic_reason),
            bridge_decision_stage=str(selected_segment.bridge_decision_stage),
            bridge_decision_reason=str(selected_segment.bridge_decision_reason),
            same_pair_rank=1,
            kept_reason="arc_first_main_flow",
        )

    arc_line = _arc_line(row)
    if arc_line is None:
        raise ValueError(f"arc_line_missing:{row.get('topology_arc_id', '')}")
    divstrip_buffer = pipeline.load_divstrip_buffer(inputs.divstrip_zone_metric, float(params["DIVSTRIP_BUFFER_M"]))
    drivezone_ratio = float(pipeline._drivezone_ratio(arc_line, inputs.drivezone_zone_metric))
    crosses_divstrip = bool(divstrip_buffer is not None and (not divstrip_buffer.is_empty) and arc_line.intersects(divstrip_buffer))
    support_ids = tuple(sorted(str(v) for v in row.get("traj_support_ids", [])))
    return Segment(
        segment_id=f"arcseg::{row['topology_arc_id']}",
        src_nodeid=int(row["src"]),
        dst_nodeid=int(row["dst"]),
        direction="src->dst",
        geometry_coords=line_to_coords(arc_line),
        candidate_ids=(f"arc::{row['topology_arc_id']}",),
        source_modes=_support_source_modes(str(row.get("traj_support_type", "")), str(row.get("prior_support_type", ""))),
        support_traj_ids=support_ids,
        support_count=int(len(support_ids)),
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=1,
        prior_supported=bool(row.get("prior_support_available", False)),
        formation_reason=str(_support_formation_reason(str(row.get("traj_support_type", "")), str(row.get("prior_support_type", "")), "")),
        length_m=float(arc_line.length),
        drivezone_ratio=drivezone_ratio,
        crosses_divstrip=crosses_divstrip,
        topology_arc_id=str(row["topology_arc_id"]),
        topology_arc_source_type=str(row["topology_arc_source_type"]),
        topology_arc_edge_ids=tuple(str(v) for v in row.get("edge_ids", [])),
        topology_arc_node_path=tuple(int(v) for v in row.get("node_path", [])),
        topology_arc_is_direct_legal=bool(row.get("is_direct_legal", False)),
        topology_arc_is_unique=bool(row.get("is_unique", False)),
        bridge_candidate_retained=False,
        bridge_chain_exists=False,
        bridge_chain_unique=False,
        bridge_chain_nodes=tuple(),
        bridge_chain_source="",
        bridge_diagnostic_reason="",
        bridge_decision_stage="",
        bridge_decision_reason="",
        same_pair_rank=1,
        kept_reason="arc_first_main_flow",
    )


def build_arc_evidence_attach(
    *,
    full_registry_rows: list[dict[str, Any]],
    selected_segments: list[Segment],
    inputs: Any,
    frame: Any,
    prior_roads: list[Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    selected_by_arc = {str(segment.topology_arc_id): segment for segment in selected_segments if str(segment.topology_arc_id)}
    rows: list[dict[str, Any]] = []
    working_segments: list[Segment] = []
    support_debug_rows: list[dict[str, Any]] = []
    for row in full_registry_rows:
        current = dict(row)
        selected_segment = selected_by_arc.get(str(current.get("topology_arc_id", "")))
        arc_line = _arc_line(current)
        support = _support_type_for_arc(
            row=current,
            arc_line=arc_line,
            inputs=inputs,
            frame=frame,
            prior_roads=prior_roads,
            params=params,
        )
        current.update(
            {
                "traj_support_type": str(support["traj_support_type"]),
                "traj_support_ids": [str(v) for v in support["traj_support_ids"]],
                "traj_support_span_count": int(support["traj_support_span_count"]),
                "traj_support_coverage_ratio": float(support["traj_support_coverage_ratio"]),
                "traj_support_spans": list(support["traj_support_spans"]),
                "prior_support_type": str(support["prior_support_type"]),
                "prior_support_available": bool(support["prior_support_available"]),
            }
        )
        if bool(current.get("entered_main_flow", False)):
            working_segment = _materialize_working_segment(
                row=current,
                selected_segment=selected_segment,
                inputs=inputs,
                params=params,
            )
            current["working_segment_id"] = str(working_segment.segment_id)
            current["working_segment_source"] = "step2_selected_segment" if selected_segment is not None else "arc_first_support_attach"
            current["entered_main_flow"] = True
            current["unbuilt_stage"] = "step3_no_support" if str(current["traj_support_type"]) == "no_support" and str(current["prior_support_type"]) != "prior_fallback_support" else ""
            current["unbuilt_reason"] = "no_traj_support" if str(current["unbuilt_stage"]) == "step3_no_support" else ""
            working_segments.append(working_segment)
        support_debug_rows.append(
            {
                "pair": str(current["pair"]),
                "topology_arc_id": str(current["topology_arc_id"]),
                "entered_main_flow": bool(current.get("entered_main_flow", False)),
                "selected_segment_count": int(current.get("selected_segment_count", 0)),
                "traj_support_type": str(current["traj_support_type"]),
                "traj_support_ids": [str(v) for v in current["traj_support_ids"]],
                "traj_support_span_count": int(current["traj_support_span_count"]),
                "traj_support_coverage_ratio": float(current["traj_support_coverage_ratio"]),
                "prior_support_type": str(current["prior_support_type"]),
                "working_segment_id": str(current.get("working_segment_id", "")),
                "working_segment_source": str(current.get("working_segment_source", "")),
            }
        )
        rows.append(current)

    entered_main_flow_rows = [row for row in rows if bool(row.get("entered_main_flow", False))]
    traj_supported_rows = [row for row in entered_main_flow_rows if str(row.get("traj_support_type", "")) != "no_support"]
    prior_supported_rows = [row for row in entered_main_flow_rows if str(row.get("prior_support_type", "")) == "prior_fallback_support"]
    return {
        "rows": rows,
        "working_segments": working_segments,
        "summary": {
            "all_direct_legal_arc_count": int(len(rows)),
            "all_direct_unique_legal_arc_count": int(sum(1 for row in rows if bool(row.get("is_unique", False)))),
            "entered_main_flow_arc_count": int(len(entered_main_flow_rows)),
            "traj_supported_arc_count": int(len(traj_supported_rows)),
            "prior_supported_arc_count": int(len(prior_supported_rows)),
            "traj_support_type_hist": dict(Counter(str(row.get("traj_support_type", "")) for row in entered_main_flow_rows)),
            "working_segment_count": int(len(working_segments)),
        },
        "audit_rows": support_debug_rows,
    }


def _segment_feature(segment: Segment, row: dict[str, Any]) -> tuple[LineString, dict[str, Any]]:
    return (
        segment.geometry_metric(),
        {
            "segment_id": str(segment.segment_id),
            "src_nodeid": int(segment.src_nodeid),
            "dst_nodeid": int(segment.dst_nodeid),
            "topology_arc_id": str(segment.topology_arc_id),
            "traj_support_type": str(row.get("traj_support_type", "")),
            "prior_support_type": str(row.get("prior_support_type", "")),
            "traj_support_coverage_ratio": float(row.get("traj_support_coverage_ratio", 0.0)),
            "working_segment_source": str(row.get("working_segment_source", "")),
        },
    )


def run_witness_stage(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    from .step3_corridor_identity import build_witness_for_segment

    pipeline = _pipeline()
    inputs, frame, prior_roads = pipeline.load_inputs_and_frame(data_root, patch_id, params=params)
    segments_payload = pipeline._load_stage_payload(out_root, run_id, patch_id, "step2_segment")
    selected_segments = [Segment.from_dict(item) for item in segments_payload.get("segments", [])]
    full_registry_rows = list(segments_payload.get("full_legal_arc_registry", []))
    evidence = build_arc_evidence_attach(
        full_registry_rows=full_registry_rows,
        selected_segments=selected_segments,
        inputs=inputs,
        frame=frame,
        prior_roads=prior_roads,
        params=params,
    )
    row_by_segment_id = {
        str(row.get("working_segment_id", "")): row
        for row in evidence["rows"]
        if str(row.get("working_segment_id", ""))
    }
    witnesses = [build_witness_for_segment(segment, inputs, params) for segment in evidence["working_segments"]]
    artifact = {
        "witnesses": [witness.to_dict() for witness in witnesses],
        "working_segments": [segment.to_dict() for segment in evidence["working_segments"]],
        "full_legal_arc_registry": list(evidence["rows"]),
        "legal_arc_funnel": dict(evidence["summary"]),
        "arc_evidence_attach_audit": list(evidence["audit_rows"]),
    }
    dbg_dir = pipeline.debug_dir(out_root, run_id, patch_id)
    write_json(pipeline._artifact_path(out_root, run_id, patch_id, "step3_witness"), artifact)
    write_json(dbg_dir / "arc_evidence_attach.json", {"arcs": evidence["audit_rows"], "summary": evidence["summary"]})
    write_lines_geojson(
        dbg_dir / "arc_first_working_segments.geojson",
        [_segment_feature(segment, row_by_segment_id.get(str(segment.segment_id), {})) for segment in evidence["working_segments"]],
    )
    return {
        "artifact": artifact,
        "inputs": inputs,
        "frame": frame,
        "segments": evidence["working_segments"],
        "witnesses": witnesses,
        "reason": "witness_ready",
    }


__all__ = ["build_arc_evidence_attach", "run_witness_stage"]
