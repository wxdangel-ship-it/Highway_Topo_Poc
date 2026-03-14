from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point

from .io import write_json, write_lines_geojson
from .models import CorridorIdentity, CorridorWitness, Segment, line_to_coords


def _pipeline():
    from . import pipeline as pipeline_module

    return pipeline_module


def _reverse_line(line: LineString) -> LineString:
    return LineString(list(reversed(list(line.coords))))


def find_prior_reference_line(segment: Segment, prior_roads: list[Any]) -> LineString | None:
    best_line: LineString | None = None
    best_cost = float("inf")
    segment_line = segment.geometry_metric()
    seg_start = Point(float(segment_line.coords[0][0]), float(segment_line.coords[0][1]))
    seg_end = Point(float(segment_line.coords[-1][0]), float(segment_line.coords[-1][1]))
    for road in prior_roads:
        line = getattr(road, "line", None)
        if not isinstance(line, LineString) or line.is_empty or line.length <= 1e-6:
            continue
        snodeid = int(getattr(road, "snodeid", 0))
        enodeid = int(getattr(road, "enodeid", 0))
        candidate_line: LineString | None = None
        if snodeid == int(segment.src_nodeid) and enodeid == int(segment.dst_nodeid):
            candidate_line = line
        elif snodeid == int(segment.dst_nodeid) and enodeid == int(segment.src_nodeid):
            candidate_line = _reverse_line(line)
        if candidate_line is None:
            continue
        road_start = Point(float(candidate_line.coords[0][0]), float(candidate_line.coords[0][1]))
        road_end = Point(float(candidate_line.coords[-1][0]), float(candidate_line.coords[-1][1]))
        cost = float(seg_start.distance(road_start) + seg_end.distance(road_end))
        if cost < best_cost:
            best_cost = cost
            best_line = candidate_line
    return best_line


def make_missing_witness(segment: Segment) -> CorridorWitness:
    return CorridorWitness(
        segment_id=str(segment.segment_id),
        status="insufficient",
        reason="witness_missing",
        line_coords=segment.geometry_coords,
        sample_s_norm=0.5,
        intervals=tuple(),
        selected_interval_rank=None,
        selected_interval_start_s=None,
        selected_interval_end_s=None,
        exclusive_interval=False,
        stability_score=0.0,
        neighbor_match_count=0,
        axis_vector=(0.0, 1.0),
    )


def build_witness_for_segment(segment: Segment, inputs: Any, params: dict[str, Any]) -> CorridorWitness:
    pipeline = _pipeline()
    line = segment.geometry_metric()
    if float(line.length) < float(params["WITNESS_MIN_SEGMENT_LENGTH_M"]):
        return CorridorWitness(
            segment_id=str(segment.segment_id),
            status="insufficient",
            reason="segment_too_short_for_witness",
            line_coords=line_to_coords(line),
            sample_s_norm=0.5,
            intervals=tuple(),
            selected_interval_rank=None,
            selected_interval_start_s=None,
            selected_interval_end_s=None,
            exclusive_interval=False,
            stability_score=0.0,
            neighbor_match_count=0,
            axis_vector=(0.0, 1.0),
        )
    surface = pipeline._drivable_surface(inputs, params)
    if surface is None or surface.is_empty:
        return CorridorWitness(
            segment_id=str(segment.segment_id),
            status="insufficient",
            reason="drivable_surface_empty",
            line_coords=line_to_coords(line),
            sample_s_norm=0.5,
            intervals=tuple(),
            selected_interval_rank=None,
            selected_interval_start_s=None,
            selected_interval_end_s=None,
            exclusive_interval=False,
            stability_score=0.0,
            neighbor_match_count=0,
            axis_vector=(0.0, 1.0),
        )
    candidates: list[dict[str, Any]] = []
    for s_norm in tuple(params["WITNESS_SAMPLE_POSITIONS"]):
        dist = float(line.length) * float(s_norm)
        if dist <= 1.0 or dist >= float(line.length) - 1.0:
            continue
        center_pt = line.interpolate(dist)
        tx, ty = pipeline._line_tangent(line, dist)
        nx, ny = (-float(ty), float(tx))
        half_len = float(params["WITNESS_HALF_LENGTH_M"])
        witness_line = LineString(
            [
                (float(center_pt.x) - nx * half_len, float(center_pt.y) - ny * half_len),
                (float(center_pt.x) + nx * half_len, float(center_pt.y) + ny * half_len),
            ]
        )
        intervals = pipeline._intervals_on_xsec(
            witness_line,
            surface,
            align_vector=(nx, ny),
            min_len_m=float(params["INTERVAL_MIN_LEN_M"]),
        )
        if not intervals:
            candidates.append({"s_norm": float(s_norm), "line": witness_line, "intervals": [], "selected": None, "axis_vector": (nx, ny)})
            continue
        ref_s = float(witness_line.project(center_pt))
        selected, _method, _reason = pipeline._choose_interval(intervals, reference_s=ref_s, desired_rank=None)
        if selected is None:
            candidates.append({"s_norm": float(s_norm), "line": witness_line, "intervals": intervals, "selected": None, "axis_vector": (nx, ny)})
            continue
        nearest_gap = float("inf")
        if len(intervals) > 1:
            for other in intervals:
                if int(other.rank) == int(selected.rank):
                    continue
                gap = max(0.0, min(abs(float(selected.start_s) - float(other.end_s)), abs(float(other.start_s) - float(selected.end_s))))
                nearest_gap = min(nearest_gap, gap)
        candidates.append(
            {
                "s_norm": float(s_norm),
                "line": witness_line,
                "intervals": intervals,
                "selected": selected,
                "nearest_gap": float(nearest_gap),
                "axis_vector": (nx, ny),
            }
        )
    if not candidates:
        return CorridorWitness(
            segment_id=str(segment.segment_id),
            status="insufficient",
            reason="no_witness_candidates",
            line_coords=line_to_coords(line),
            sample_s_norm=0.5,
            intervals=tuple(),
            selected_interval_rank=None,
            selected_interval_start_s=None,
            selected_interval_end_s=None,
            exclusive_interval=False,
            stability_score=0.0,
            neighbor_match_count=0,
            axis_vector=(0.0, 1.0),
        )
    best: dict[str, Any] | None = None
    tol = float(params["WITNESS_CENTER_TOL_M"])
    for candidate in candidates:
        selected = candidate.get("selected")
        if selected is None:
            candidate["score"] = 0.0
            candidate["match_count"] = 0
            continue
        match_count = 0
        for other in candidates:
            other_selected = other.get("selected")
            if other is candidate or other_selected is None:
                continue
            if int(other_selected.rank) != int(selected.rank):
                continue
            if abs(float(other_selected.center_s) - float(selected.center_s)) <= tol:
                match_count += 1
        exclusive = len(candidate["intervals"]) == 1 or float(candidate.get("nearest_gap", 0.0)) >= float(params["WITNESS_GAP_MIN_M"])
        score = 0.7 * (float(match_count) / max(1.0, float(max(1, len(candidates) - 1)))) + 0.3 * (1.0 if exclusive else 0.0)
        candidate["score"] = float(score)
        candidate["match_count"] = int(match_count)
        candidate["exclusive"] = bool(exclusive)
        if best is None or float(score) > float(best.get("score", -1.0)):
            best = candidate
    if best is None or best.get("selected") is None:
        chosen = candidates[min(range(len(candidates)), key=lambda idx: abs(float(candidates[idx]["s_norm"]) - 0.5))]
        return CorridorWitness(
            segment_id=str(segment.segment_id),
            status="insufficient",
            reason="witness_no_legal_interval",
            line_coords=line_to_coords(chosen["line"]),
            sample_s_norm=float(chosen["s_norm"]),
            intervals=tuple(),
            selected_interval_rank=None,
            selected_interval_start_s=None,
            selected_interval_end_s=None,
            exclusive_interval=False,
            stability_score=0.0,
            neighbor_match_count=0,
            axis_vector=(float(chosen["axis_vector"][0]), float(chosen["axis_vector"][1])),
        )
    selected = best["selected"]
    status = "selected"
    reason = "stable_exclusive_interval"
    if float(best.get("score", 0.0)) < float(params["WITNESS_MIN_STABILITY_SCORE"]):
        status = "insufficient"
        reason = "witness_not_stable_enough"
    return CorridorWitness(
        segment_id=str(segment.segment_id),
        status=str(status),
        reason=str(reason),
        line_coords=line_to_coords(best["line"]),
        sample_s_norm=float(best["s_norm"]),
        intervals=tuple(best["intervals"]),
        selected_interval_rank=int(selected.rank),
        selected_interval_start_s=float(selected.start_s),
        selected_interval_end_s=float(selected.end_s),
        exclusive_interval=bool(best.get("exclusive", False)),
        stability_score=float(best.get("score", 0.0)),
        neighbor_match_count=int(best.get("match_count", 0)),
        axis_vector=(float(best["axis_vector"][0]), float(best["axis_vector"][1])),
    )


def _fallback_segment_identity(segment: Segment, witness: CorridorWitness, prior_available: bool) -> CorridorIdentity:
    if str(witness.status) == "selected" and bool(witness.exclusive_interval):
        return CorridorIdentity(
            segment_id=str(segment.segment_id),
            state="witness_based",
            reason="stable_witness_interval",
            risk_flags=tuple(),
            witness_interval_rank=witness.selected_interval_rank,
            prior_supported=bool(segment.prior_supported or prior_available),
        )
    if bool(segment.prior_supported or prior_available):
        return CorridorIdentity(
            segment_id=str(segment.segment_id),
            state="prior_based",
            reason="fallback_to_prior_reference",
            risk_flags=("prior_fallback",),
            witness_interval_rank=witness.selected_interval_rank,
            prior_supported=True,
        )
    return CorridorIdentity(
        segment_id=str(segment.segment_id),
        state="unresolved",
        reason=str(witness.reason or "corridor_identity_unresolved"),
        risk_flags=tuple(),
        witness_interval_rank=witness.selected_interval_rank,
        prior_supported=False,
    )


def _pick_best_arc_witness(rows: list[tuple[Segment, CorridorWitness]]) -> tuple[Segment, CorridorWitness] | None:
    if not rows:
        return None
    return sorted(
        rows,
        key=lambda item: (
            0 if str(item[1].status) == "selected" and bool(item[1].exclusive_interval) else 1,
            -float(item[1].stability_score),
            -int(item[0].support_count),
            int(item[0].same_pair_rank or 999999),
            str(item[0].segment_id),
        ),
    )[0]


def _arc_unresolved_reason(witnesses: list[CorridorWitness], prior_available: bool) -> str:
    reasons = Counter(str(item.reason or "unknown") for item in witnesses)
    if reasons.get("drivable_surface_empty", 0) > 0:
        return "drivezone_support_insufficient"
    if sum(reasons.get(key, 0) for key in ("witness_not_stable_enough", "witness_no_legal_interval", "segment_too_short_for_witness")) > 0:
        return "weak_or_unstable_witness"
    if sum(reasons.get(key, 0) for key in ("no_witness_candidates", "witness_missing")) > 0:
        return "no_same_arc_witness" if prior_available else "no_same_arc_prior"
    return "corridor_identity_unresolved" if prior_available else "no_same_arc_prior"


def build_legal_arc_registry(
    *,
    segments: list[Segment],
    witnesses: dict[str, CorridorWitness],
    prior_roads: list[Any],
) -> list[dict[str, Any]]:
    by_arc: dict[str, dict[str, Any]] = {}
    for segment in segments:
        if not (
            str(segment.topology_arc_id)
            and str(segment.topology_arc_source_type) == "direct_topology_arc"
            and bool(segment.topology_arc_is_direct_legal)
            and bool(segment.topology_arc_is_unique)
        ):
            continue
        row = by_arc.setdefault(
            str(segment.topology_arc_id),
            {
                "src": int(segment.src_nodeid),
                "dst": int(segment.dst_nodeid),
                "pair": f"{int(segment.src_nodeid)}:{int(segment.dst_nodeid)}",
                "topology_arc_id": str(segment.topology_arc_id),
                "topology_arc_is_direct_legal": True,
                "topology_arc_is_unique": True,
                "segment_ids": [],
                "segment_count": 0,
                "prior_available": False,
                "corridor_identity": "unresolved",
                "corridor_reason": "",
                "witness_interval_rank": None,
                "risk_flags": [],
            },
        )
        row["segment_ids"].append(str(segment.segment_id))
        row["segment_count"] = int(row["segment_count"]) + 1
        if find_prior_reference_line(segment, prior_roads) is not None:
            row["prior_available"] = True
    for arc_id, row in by_arc.items():
        arc_segments = [segment for segment in segments if str(segment.topology_arc_id) == str(arc_id)]
        arc_witnesses = [witnesses.get(str(segment.segment_id), make_missing_witness(segment)) for segment in arc_segments]
        selected_rows = [
            (segment, witnesses.get(str(segment.segment_id), make_missing_witness(segment)))
            for segment in arc_segments
            if str(witnesses.get(str(segment.segment_id), make_missing_witness(segment)).status) == "selected"
            and bool(witnesses.get(str(segment.segment_id), make_missing_witness(segment)).exclusive_interval)
        ]
        chosen = _pick_best_arc_witness(selected_rows)
        if chosen is not None:
            _segment, witness = chosen
            row["corridor_identity"] = "witness_based"
            row["corridor_reason"] = "stable_same_arc_witness"
            row["witness_interval_rank"] = witness.selected_interval_rank
            row["risk_flags"] = []
            continue
        if bool(row["prior_available"]):
            row["corridor_identity"] = "prior_based"
            row["corridor_reason"] = "same_arc_prior_fallback"
            row["witness_interval_rank"] = None
            row["risk_flags"] = ["prior_fallback"]
            continue
        row["corridor_identity"] = "unresolved"
        row["corridor_reason"] = _arc_unresolved_reason(arc_witnesses, bool(row["prior_available"]))
        row["witness_interval_rank"] = None
        row["risk_flags"] = []
    return [dict(row) for _arc_id, row in sorted(by_arc.items(), key=lambda item: item[0])]


def build_corridor_identities(
    *,
    segments: list[Segment],
    witnesses: list[CorridorWitness],
    prior_roads: list[Any],
    full_registry_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[CorridorIdentity], list[dict[str, Any]]]:
    witness_map = {str(item.segment_id): item for item in witnesses}
    if full_registry_rows:
        registry_rows = [dict(item) for item in full_registry_rows]
    else:
        registry_rows = build_legal_arc_registry(segments=segments, witnesses=witness_map, prior_roads=prior_roads)
    registry_by_arc = {str(item["topology_arc_id"]): item for item in registry_rows}
    identities: list[CorridorIdentity] = []
    for segment in segments:
        witness = witness_map.get(str(segment.segment_id), make_missing_witness(segment))
        registry = registry_by_arc.get(str(segment.topology_arc_id))
        if registry is None:
            identities.append(
                _fallback_segment_identity(
                    segment=segment,
                    witness=witness,
                    prior_available=find_prior_reference_line(segment, prior_roads) is not None,
                )
            )
            continue
        arc_segments = [item for item in segments if str(item.topology_arc_id) == str(segment.topology_arc_id)]
        arc_witnesses = [witness_map.get(str(item.segment_id), make_missing_witness(item)) for item in arc_segments]
        legacy_selected_rows = [
            (arc_segment, witness_map.get(str(arc_segment.segment_id), make_missing_witness(arc_segment)))
            for arc_segment in arc_segments
            if str(witness_map.get(str(arc_segment.segment_id), make_missing_witness(arc_segment)).status) == "selected"
            and bool(witness_map.get(str(arc_segment.segment_id), make_missing_witness(arc_segment)).exclusive_interval)
        ]
        traj_support_type = str(registry.get("traj_support_type", "no_support"))
        prior_support_type = str(registry.get("prior_support_type", "no_support"))
        coverage_ratio = float(registry.get("traj_support_coverage_ratio", 0.0))
        if str(registry.get("hard_block_reason", "")):
            state = "unresolved"
            reason = str(registry.get("hard_block_reason", "corridor_identity_unresolved"))
            risk_flags: tuple[str, ...] = tuple()
            witness_rank = None
        elif "traj_support_type" not in registry and "prior_support_type" not in registry:
            chosen = _pick_best_arc_witness(legacy_selected_rows)
            if chosen is not None:
                _segment, selected_witness = chosen
                state = "witness_based"
                reason = "stable_same_arc_witness"
                risk_flags = tuple()
                witness_rank = selected_witness.selected_interval_rank
            elif bool(registry.get("prior_available", False)):
                state = "prior_based"
                reason = "same_arc_prior_fallback"
                risk_flags = ("prior_fallback",)
                witness_rank = None
            else:
                state = "unresolved"
                reason = _arc_unresolved_reason(arc_witnesses, bool(registry.get("prior_available", False)))
                risk_flags = tuple()
                witness_rank = None
        elif traj_support_type == "terminal_crossing_support":
            state = "witness_based"
            reason = "terminal_crossing_support"
            risk_flags = tuple()
            witness_rank = witness.selected_interval_rank
        elif traj_support_type == "partial_arc_support":
            if str(witness.status) == "selected" or coverage_ratio >= 0.45:
                state = "witness_based"
                reason = "partial_arc_support"
                risk_flags = tuple()
                witness_rank = witness.selected_interval_rank
            else:
                state = "unresolved"
                reason = "insufficient_partial_support"
                risk_flags = tuple()
                witness_rank = witness.selected_interval_rank
        elif traj_support_type == "stitched_arc_support":
            if str(witness.status) == "selected" or coverage_ratio >= 0.72:
                state = "witness_based"
                reason = "stitched_arc_support"
                risk_flags = ("stitched_support",)
                witness_rank = witness.selected_interval_rank
            else:
                state = "unresolved"
                reason = "stitch_failed"
                risk_flags = ("stitched_support",)
                witness_rank = witness.selected_interval_rank
        elif prior_support_type == "prior_fallback_support":
            state = "prior_based"
            reason = "same_arc_prior_fallback"
            risk_flags = ("prior_fallback",)
            witness_rank = witness.selected_interval_rank
        else:
            state = "unresolved"
            if str(witness.reason) == "drivable_surface_empty":
                reason = "drivezone_support_insufficient"
            else:
                reason = "no_traj_support"
            risk_flags = tuple()
            witness_rank = witness.selected_interval_rank
        registry["corridor_identity"] = str(state)
        registry["corridor_reason"] = str(reason)
        registry["witness_interval_rank"] = witness_rank
        registry["risk_flags"] = list(risk_flags)
        identities.append(
            CorridorIdentity(
                segment_id=str(segment.segment_id),
                state=str(state),
                reason=str(reason),
                risk_flags=tuple(str(v) for v in risk_flags),
                witness_interval_rank=witness_rank,
                prior_supported=bool(segment.prior_supported or registry.get("prior_support_available", False)),
            )
        )
    return identities, registry_rows


def run_witness_stage(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    pipeline = _pipeline()
    inputs, frame, _prior_roads = pipeline.load_inputs_and_frame(data_root, patch_id, params=params)
    segments_payload = pipeline._load_stage_payload(out_root, run_id, patch_id, "step2_segment")
    segments = [Segment.from_dict(item) for item in segments_payload.get("segments", [])]
    segment_map = {str(segment.segment_id): segment for segment in segments}
    witnesses = [build_witness_for_segment(segment, inputs, params) for segment in segments]
    artifact = {"witnesses": [witness.to_dict() for witness in witnesses]}
    dbg_dir = pipeline.debug_dir(out_root, run_id, patch_id)
    write_json(pipeline._artifact_path(out_root, run_id, patch_id, "step3_witness"), artifact)
    write_lines_geojson(dbg_dir / "step3_witness_input_segments.geojson", pipeline._segment_features(segments, status="witness_input"))
    write_lines_geojson(
        dbg_dir / "corridor_witness_candidates.geojson",
        [
            (
                witness.geometry_metric(),
                {
                    "segment_id": str(witness.segment_id),
                    "status": str(witness.status),
                    "reason": str(witness.reason),
                    "stability_score": float(witness.stability_score),
                    "selected_interval_rank": witness.selected_interval_rank,
                    "crossing_dist": int(segment_map[str(witness.segment_id)].other_xsec_crossing_count),
                    "support_count": int(segment_map[str(witness.segment_id)].support_count),
                    "same_pair_rank": segment_map[str(witness.segment_id)].same_pair_rank,
                    "kept_reason": str(segment_map[str(witness.segment_id)].kept_reason),
                },
            )
            for witness in witnesses
        ],
    )
    write_lines_geojson(
        dbg_dir / "corridor_witness_selected.geojson",
        [
            (
                witness.geometry_metric(),
                {
                    "segment_id": str(witness.segment_id),
                    "status": str(witness.status),
                    "stability_score": float(witness.stability_score),
                    "exclusive_interval": bool(witness.exclusive_interval),
                    "crossing_dist": int(segment_map[str(witness.segment_id)].other_xsec_crossing_count),
                    "support_count": int(segment_map[str(witness.segment_id)].support_count),
                    "same_pair_rank": segment_map[str(witness.segment_id)].same_pair_rank,
                    "kept_reason": str(segment_map[str(witness.segment_id)].kept_reason),
                },
            )
            for witness in witnesses
            if str(witness.status) == "selected"
        ],
    )
    return {
        "artifact": artifact,
        "inputs": inputs,
        "frame": frame,
        "segments": segments,
        "witnesses": witnesses,
        "reason": "witness_ready",
    }


def run_corridor_identity_stage(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    pipeline = _pipeline()
    _inputs, _frame, prior_roads = pipeline.load_inputs_and_frame(data_root, patch_id, params=params)
    witnesses_payload = pipeline._load_stage_payload(out_root, run_id, patch_id, "step3_witness")
    segments = [Segment.from_dict(item) for item in witnesses_payload.get("working_segments", [])]
    witnesses = [CorridorWitness.from_dict(item) for item in witnesses_payload.get("witnesses", [])]
    full_registry_rows = list(witnesses_payload.get("full_legal_arc_registry", []))
    identities, registry_rows = build_corridor_identities(
        segments=segments,
        witnesses=witnesses,
        prior_roads=prior_roads,
        full_registry_rows=full_registry_rows,
    )
    corridor_resolved_arc_count = int(sum(1 for item in registry_rows if str(item.get("corridor_identity", "")) in {"witness_based", "prior_based"}))
    legal_arc_funnel = dict(witnesses_payload.get("legal_arc_funnel", {}))
    legal_arc_funnel["corridor_resolved_arc_count"] = corridor_resolved_arc_count
    artifact = {
        "corridor_identities": [identity.to_dict() for identity in identities],
        "legal_arc_registry": [dict(item) for item in registry_rows if bool(item.get("entered_main_flow", False))],
        "full_legal_arc_registry": registry_rows,
        "working_segments": [segment.to_dict() for segment in segments],
        "legal_arc_funnel": legal_arc_funnel,
    }
    dbg_dir = pipeline.debug_dir(out_root, run_id, patch_id)
    write_json(pipeline._artifact_path(out_root, run_id, patch_id, "step4_corridor_identity"), artifact)
    write_json(dbg_dir / "corridor_identity.json", artifact)
    return {"artifact": artifact, "segments": segments, "identities": identities, "reason": "corridor_identity_ready"}


__all__ = [
    "build_corridor_identities",
    "build_legal_arc_registry",
    "build_witness_for_segment",
    "find_prior_reference_line",
    "make_missing_witness",
    "run_corridor_identity_stage",
    "run_witness_stage",
]
