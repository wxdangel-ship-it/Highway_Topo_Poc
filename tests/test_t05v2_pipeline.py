from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import pytest
from shapely.geometry import LineString, Point, Polygon

from highway_topo_poc.modules.t05_topology_between_rc_v2 import step3_arc_evidence as _step3_evidence
from highway_topo_poc.modules.t05_topology_between_rc_v2 import step5_conservative_road as _step5_road
from highway_topo_poc.modules.t05_topology_between_rc_v2.io import InputFrame, PatchInputs
from highway_topo_poc.modules.t05_topology_between_rc_v2.audit_acceptance import (
    build_arc_selection_structure,
    build_arc_obligation_registry,
    build_arc_legality_audit,
    build_competing_arc_review,
    build_merge_diverge_review,
    build_multi_arc_review,
    build_pair_decisions,
    build_same_pair_provisional_allow_review,
)
from highway_topo_poc.modules.t05_topology_between_rc_v2.arc_selection_rules import (
    apply_arc_selection_rules,
)
from highway_topo_poc.modules.t05_topology_between_rc_v2.models import (
    BaseCrossSection,
    CorridorIdentity,
    CorridorInterval,
    CorridorWitness,
    Segment,
    SlotInterval,
)
from highway_topo_poc.modules.t05_topology_between_rc_v2.pipeline import (
    DEFAULT_PARAMS,
    _build_directed_topology,
    _build_final_road,
    _classify_blocked_pair_bridge,
    _classify_segment_outcome,
    _production_arc_gate_reason,
    _topology_gate_reason,
    run_full_pipeline,
    run_stage,
)
from highway_topo_poc.modules.t05_topology_between_rc_v2.review import (
    evaluate_patch_acceptance,
    write_alias_fix_and_rootcause_push_review,
    write_arc_first_attach_evidence_review,
    write_arc_legality_fix_review,
    write_arc_obligation_closure_review,
    write_competing_arc_closure_review,
    write_legal_arc_coverage_review,
    write_merge_diverge_fix_review,
    write_merge_diverge_rules_review,
    write_perf_opt_arc_first_review,
    write_semantic_fix_after_perf_review,
    write_step5_finish_review,
    write_step5_plus_multiarc_finish_review,
    write_topology_gap_controlled_cover_review,
    write_witness_vis_step5_recovery_review,
)
from highway_topo_poc.modules.t05_topology_between_rc_v2.step2_arc_registry import build_full_legal_arc_registry
from highway_topo_poc.modules.t05_topology_between_rc_v2.step3_arc_evidence import (
    build_arc_evidence_attach,
    classify_topology_gap_rows,
)
from highway_topo_poc.modules.t05_topology_between_rc_v2.step5_conservative_road import (
    _rcsdroad_fallback_base_line,
    _rcsdroad_trend_extended_candidate_line,
    build_slot,
)
from highway_topo_poc.modules.t05_topology_between_rc_v2.step3_corridor_identity import (
    build_corridor_identities,
    build_patch_geometry_cache,
    build_witness_for_segment,
)


def _fc(features: list[dict], crs_name: str | None = "EPSG:3857") -> dict:
    payload = {"type": "FeatureCollection", "features": features}
    if crs_name is not None:
        payload["crs"] = {"type": "name", "properties": {"name": crs_name}}
    return payload


def _line_feature(coords: list[tuple[float, float]], props: dict | None = None) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[float(x), float(y)] for x, y in coords]},
        "properties": dict(props or {}),
    }


def _poly_feature(coords: list[tuple[float, float]], props: dict | None = None) -> dict:
    ring = [[float(x), float(y)] for x, y in coords]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": dict(props or {}),
    }


def _point_feature(coord: tuple[float, float], props: dict | None = None) -> dict:
    x, y = coord
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float(x), float(y)]},
        "properties": dict(props or {}),
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_patch(
    root: Path,
    *,
    patch_id: str,
    intersection_fc: dict,
    drivezone_fc: dict | None,
    traj_tracks: list[list[tuple[float, float]]],
    lane_fc: dict | None = None,
    divstrip_fc: dict | None = None,
    road_fc: dict | None = None,
    node_fc: dict | None = None,
) -> Path:
    patch_dir = root / patch_id
    vector_dir = patch_dir / "Vector"
    traj_dir = patch_dir / "Traj"
    _write_json(vector_dir / "intersection_l.geojson", intersection_fc)
    if drivezone_fc is not None:
        _write_json(vector_dir / "DriveZone.geojson", drivezone_fc)
    if lane_fc is not None:
        _write_json(vector_dir / "LaneBoundary.geojson", lane_fc)
    if divstrip_fc is not None:
        _write_json(vector_dir / "DivStripZone.geojson", divstrip_fc)
    if road_fc is not None:
        _write_json(vector_dir / "RCSDRoad.geojson", road_fc)
    if node_fc is not None:
        _write_json(vector_dir / "RCSDNode.geojson", node_fc)
    for idx, track in enumerate(traj_tracks):
        features = []
        for seq, coord in enumerate(track):
            features.append(_point_feature(coord, {"seq": seq, "traj_id": f"traj_{idx:02d}"}))
        _write_json(traj_dir / f"traj_{idx:02d}" / "raw_dat_pose.geojson", _fc(features, "EPSG:3857"))
    return patch_dir


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _simple_intersections() -> dict:
    return _fc(
        [
            _line_feature([(0.0, -15.0), (0.0, 15.0)], {"nodeid": 1}),
            _line_feature([(100.0, -15.0), (100.0, 15.0)], {"nodeid": 2}),
        ],
        "EPSG:3857",
    )


def test_t05v2_step1_handles_optional_lane_missing_crs_and_crs84(tmp_path: Path) -> None:
    patch_id = "crs84_case"
    lon0 = 120.0
    lat0 = 30.0
    intersection_fc = _fc(
        [
            _line_feature([(lon0, lat0 - 0.00015), (lon0, lat0 + 0.00015)], {"nodeid": 1}),
            _line_feature([(lon0 + 0.001, lat0 - 0.00015), (lon0 + 0.001, lat0 + 0.00015)], {"nodeid": 2}),
        ],
        "EPSG:4326",
    )
    drivezone_fc = _fc(
        [_poly_feature([(lon0 - 0.0001, lat0 - 0.00004), (lon0 + 0.0011, lat0 - 0.00004), (lon0 + 0.0011, lat0 + 0.00004), (lon0 - 0.0001, lat0 + 0.00004)])],
        "EPSG:4326",
    )
    lane_fc = _fc(
        [_line_feature([(lon0 + 0.0002, lat0 - 0.00002), (lon0 + 0.0008, lat0 - 0.00002)], {"id": 1})],
        None,
    )
    traj_fc_tracks = [[(lon0, lat0), (lon0 + 0.0005, lat0), (lon0 + 0.001, lat0)]]
    patch_dir = tmp_path / "data"
    patch = _write_patch(
        patch_dir,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=traj_fc_tracks,
        lane_fc=lane_fc,
    )
    for path in patch.glob("Traj/*/raw_dat_pose.geojson"):
        payload = _read_json(path)
        payload["crs"] = {"type": "name", "properties": {"name": "EPSG:4326"}}
        _write_json(path, payload)
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=patch_dir, patch_id=patch_id, run_id="run1", out_root=out_root)
    artifact = _read_json(out_root / "run1" / "patches" / patch_id / "step1" / "input_frame.json")
    step_state = _read_json(out_root / "run1" / "patches" / patch_id / "step1" / "step_state.json")
    frame = artifact["input_frame"]
    assert frame["metric_crs"] == "EPSG:3857"
    assert int(frame["lane_boundary_count"]) == 1
    assert int(frame["trajectory_count"]) == 1
    assert bool(step_state["ok"]) is True


def test_t05v2_missing_drivezone_hard_fail(tmp_path: Path) -> None:
    patch_id = "missing_drivezone"
    data_root = tmp_path / "data"
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=None,
        traj_tracks=[[(0.0, 0.0), (100.0, 0.0)]],
    )
    with pytest.raises(Exception, match="drivezone_missing"):
        run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run1", out_root=tmp_path / "out")


def test_t05v2_segment_rejects_candidates_crossing_too_many_other_xsecs(tmp_path: Path) -> None:
    patch_id = "segment_fail"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -10.0), (0.0, 10.0)], {"nodeid": 1}),
            _line_feature([(30.0, -10.0), (30.0, 10.0)], {"nodeid": 2}),
            _line_feature([(60.0, -10.0), (60.0, 10.0)], {"nodeid": 3}),
            _line_feature([(90.0, -10.0), (90.0, 10.0)], {"nodeid": 4}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -4.0), (95.0, -4.0), (95.0, 4.0), (-5.0, 4.0)])], "EPSG:3857")
    _write_patch(data_root, patch_id=patch_id, intersection_fc=intersection_fc, drivezone_fc=drivezone_fc, traj_tracks=[[(0.0, 0.0), (30.0, 0.0), (60.0, 0.0), (90.0, 0.0)]])
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run2", out_root=out_root)
    run_stage(
        stage="step2_segment",
        data_root=data_root,
        patch_id=patch_id,
        run_id="run2",
        out_root=out_root,
        params={"STEP2_STRICT_ADJACENT_PAIRING": 0},
    )
    segments_payload = _read_json(out_root / "run2" / "patches" / patch_id / "step2" / "segments.json")
    reasons = {item["reason"] for item in segments_payload["excluded_candidates"]}
    assert "segment_crosses_too_many_other_xsecs" in reasons


def test_t05v2_step2_default_strict_adjacent_pairing_reduces_long_span_pairs(tmp_path: Path) -> None:
    patch_id = "strict_adjacent"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -10.0), (0.0, 10.0)], {"nodeid": 1}),
            _line_feature([(30.0, -10.0), (30.0, 10.0)], {"nodeid": 2}),
            _line_feature([(60.0, -10.0), (60.0, 10.0)], {"nodeid": 3}),
            _line_feature([(90.0, -10.0), (90.0, 10.0)], {"nodeid": 4}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -4.0), (95.0, -4.0), (95.0, 4.0), (-5.0, 4.0)])], "EPSG:3857")
    _write_patch(data_root, patch_id=patch_id, intersection_fc=intersection_fc, drivezone_fc=drivezone_fc, traj_tracks=[[(0.0, 0.0), (30.0, 0.0), (60.0, 0.0), (90.0, 0.0)]])
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_adj", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_adj", out_root=out_root)
    segments_payload = _read_json(out_root / "run_adj" / "patches" / patch_id / "step2" / "segments.json")
    step2_metrics = segments_payload["step2_metrics"]
    assert int(step2_metrics["raw_candidate_count"]) == 6
    assert int(step2_metrics["candidate_count_after_pairing"]) == 3
    assert int(step2_metrics["candidate_count_after_same_pair_topk"]) == 3
    assert step2_metrics["crossing_dist_hist_selected"] == {"0": 3}


def test_t05v2_step2_cross1_requires_explicit_exception_and_support(tmp_path: Path) -> None:
    patch_id = "cross1_exception"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -10.0), (0.0, 10.0)], {"nodeid": 1}),
            _line_feature([(30.0, -10.0), (30.0, 10.0)], {"nodeid": 2}),
            _line_feature([(60.0, -10.0), (60.0, 10.0)], {"nodeid": 3}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -4.0), (65.0, -4.0), (65.0, 4.0), (-5.0, 4.0)])], "EPSG:3857")
    tracks = [
        [(0.0, 0.0), (30.0, 0.0), (60.0, 0.0)],
        [(0.0, 0.0), (30.0, 0.0), (60.0, 0.0)],
    ]
    _write_patch(data_root, patch_id=patch_id, intersection_fc=intersection_fc, drivezone_fc=drivezone_fc, traj_tracks=tracks)
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_cross1", out_root=out_root)
    run_stage(
        stage="step2_segment",
        data_root=data_root,
        patch_id=patch_id,
        run_id="run_cross1",
        out_root=out_root,
        params={
            "STEP2_STRICT_ADJACENT_PAIRING": 0,
            "STEP2_ALLOW_ONE_INTERMEDIATE_XSEC": 1,
            "STEP2_CROSS1_MIN_SUPPORT": 2,
        },
    )
    segments_payload = _read_json(out_root / "run_cross1" / "patches" / patch_id / "step2" / "segments.json")
    kept = [item for item in segments_payload["segments"] if int(item["src_nodeid"]) == 1 and int(item["dst_nodeid"]) == 3]
    assert len(kept) == 1
    assert int(kept[0]["other_xsec_crossing_count"]) == 1
    assert str(kept[0]["kept_reason"]).startswith("cross1_exception:")


def test_t05v2_step2_pair_scoped_cross1_default_off_keeps_baseline_and_writes_zero_selected_pairs(tmp_path: Path) -> None:
    patch_id = "pair_scoped_default_off"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -10.0), (0.0, 10.0)], {"nodeid": 1}),
            _line_feature([(30.0, -10.0), (30.0, 10.0)], {"nodeid": 2}),
            _line_feature([(60.0, -10.0), (60.0, 10.0)], {"nodeid": 3}),
            _line_feature([(90.0, -10.0), (90.0, 10.0)], {"nodeid": 4}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -4.0), (95.0, -4.0), (95.0, 4.0), (-5.0, 4.0)])], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(0.0, 0.0), (30.0, 0.0), (60.0, 0.0), (90.0, 0.0)]],
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_pair_off", out_root=out_root)
    run_stage(
        stage="step2_segment",
        data_root=data_root,
        patch_id=patch_id,
        run_id="run_pair_off",
        out_root=out_root,
        params={
            "STEP2_STRICT_ADJACENT_PAIRING": 0,
            "STEP2_PAIR_SCOPED_CROSS1_EXCEPTION_ENABLE": 0,
            "STEP2_PAIR_SCOPED_CROSS1_ALLOWLIST": "1:3",
        },
    )
    patch_dir = out_root / "run_pair_off" / "patches" / patch_id
    segments_payload = _read_json(patch_dir / "step2" / "segments.json")
    metrics = segments_payload["step2_metrics"]
    kept_pairs = {(int(item["src_nodeid"]), int(item["dst_nodeid"])) for item in segments_payload["segments"]}
    assert (1, 3) not in kept_pairs
    assert metrics["crossing_dist_hist_selected"] == {"0": 3}
    assert bool(metrics["pair_scoped_cross1_exception_enabled"]) is False
    assert int(metrics["selected_cross1_exception_count"]) == 0
    assert "1:3" in set(metrics["zero_selected_pair_ids"])
    zero_debug = _read_json(patch_dir / "debug" / "step2_zero_selected_pairs.json")
    target = next(item for item in zero_debug["pairs"] if str(item["pair_id"]) == "1:3")
    assert bool(target["whether_pair_scoped_exception_applicable"]) is False
    assert str(target["dropped_reason"]) == "cross1_disabled"


def test_t05v2_step2_pair_scoped_cross1_exception_restores_only_allowlisted_pair(tmp_path: Path) -> None:
    patch_id = "pair_scoped_restore"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -10.0), (0.0, 10.0)], {"nodeid": 1}),
            _line_feature([(30.0, -10.0), (30.0, 10.0)], {"nodeid": 2}),
            _line_feature([(60.0, -10.0), (60.0, 10.0)], {"nodeid": 3}),
            _line_feature([(90.0, -10.0), (90.0, 10.0)], {"nodeid": 4}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -4.0), (95.0, -4.0), (95.0, 4.0), (-5.0, 4.0)])], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(0.0, 0.0), (30.0, 0.0), (60.0, 0.0), (90.0, 0.0)]],
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_pair_on", out_root=out_root)
    run_stage(
        stage="step2_segment",
        data_root=data_root,
        patch_id=patch_id,
        run_id="run_pair_on",
        out_root=out_root,
        params={
            "STEP2_STRICT_ADJACENT_PAIRING": 0,
            "STEP2_PAIR_SCOPED_CROSS1_EXCEPTION_ENABLE": 1,
            "STEP2_PAIR_SCOPED_CROSS1_ALLOWLIST": "1:3",
        },
    )
    patch_dir = out_root / "run_pair_on" / "patches" / patch_id
    segments_payload = _read_json(patch_dir / "step2" / "segments.json")
    kept = {(int(item["src_nodeid"]), int(item["dst_nodeid"])): item for item in segments_payload["segments"]}
    assert (1, 3) in kept
    assert (2, 4) not in kept
    assert "pair_scoped_cross1_exception" in str(kept[(1, 3)]["kept_reason"])
    assert "no_cross0_alternative" in str(kept[(1, 3)]["kept_reason"])
    assert "business_prior_confirmed" in str(kept[(1, 3)]["kept_reason"])
    metrics = segments_payload["step2_metrics"]
    assert bool(metrics["pair_scoped_cross1_exception_enabled"]) is True
    assert int(metrics["pair_scoped_cross1_exception_hit_count"]) == 1
    assert int(metrics["selected_cross1_exception_count"]) == 1
    assert metrics["crossing_dist_hist_selected"] == {"0": 3, "1": 1}
    assert int(metrics["pair_scoped_exception_audit_count"]) == 2
    assert metrics["pair_scoped_exception_selected_pair_ids"] == ["1:3"]
    assert metrics["pair_scoped_exception_rejected_pair_ids"] == ["2:4"]
    assert metrics["pair_scoped_exception_non_allowlisted_cross1_pair_ids"] == ["2:4"]
    excluded = segments_payload["excluded_candidates"]
    blocked_pairs = {
        (int(item["src_nodeid"]), int(item["dst_nodeid"])): str(item["reason"])
        for item in excluded
        if str(item.get("reason")) == "cross1_pair_not_allowlisted"
    }
    assert blocked_pairs[(2, 4)] == "cross1_pair_not_allowlisted"
    audit = _read_json(patch_dir / "debug" / "step2_pair_scoped_exception_audit.json")
    audit_rows = {str(item["pair_id"]): item for item in audit["pairs"]}
    assert audit_rows["1:3"]["final_decision"] == "selected"
    assert bool(audit_rows["1:3"]["selected_by_exception"]) is True
    assert audit_rows["2:4"]["final_decision"] == "rejected_before_exception"
    assert audit_rows["2:4"]["rejected_reason"] == "cross1_pair_not_allowlisted"


def test_t05v2_step2_same_pair_topk_prefers_stronger_cluster(tmp_path: Path) -> None:
    patch_id = "same_pair_topk"
    data_root = tmp_path / "data"
    drivezone_fc = _fc([_poly_feature([(-5.0, -12.0), (105.0, -12.0), (105.0, 12.0), (-5.0, 12.0)])], "EPSG:3857")
    tracks = [
        [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)],
        [(0.0, 0.2), (50.0, 0.2), (100.0, 0.2)],
        [(0.0, 8.0), (50.0, 8.0), (100.0, 8.0)],
    ]
    _write_patch(data_root, patch_id=patch_id, intersection_fc=_simple_intersections(), drivezone_fc=drivezone_fc, traj_tracks=tracks)
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_topk", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_topk", out_root=out_root)
    segments_payload = _read_json(out_root / "run_topk" / "patches" / patch_id / "step2" / "segments.json")
    assert len(segments_payload["segments"]) == 1
    assert int(segments_payload["segments"][0]["support_count"]) == 2
    assert any(item["dropped_reason"] == "same_pair_topk_exceeded" for item in segments_payload["dropped_segments"])


def test_t05v2_step2_topology_gate_rejects_wrong_terminal_pairs_and_reverse_direction(tmp_path: Path) -> None:
    patch_id = "topology_gate_terminal"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -5.0), (0.0, 5.0)], {"nodeid": 11}),
            _line_feature([(0.0, 15.0), (0.0, 25.0)], {"nodeid": 21}),
            _line_feature([(70.0, 5.0), (70.0, 15.0)], {"nodeid": 31}),
            _line_feature([(100.0, -5.0), (100.0, 25.0)], {"nodeid": 41}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -10.0), (105.0, -10.0), (105.0, 30.0), (-5.0, 30.0)])], "EPSG:3857")
    road_fc = _fc([_line_feature([(70.0, 10.0), (100.0, 10.0)], {"snodeid": 31, "enodeid": 41})], "EPSG:3857")
    tracks = [
        [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)],
        [(0.0, 20.0), (50.0, 20.0), (100.0, 20.0)],
        [(70.0, 10.0), (85.0, 10.0), (100.0, 10.0)],
        [(100.0, 10.0), (85.0, 10.0), (70.0, 10.0)],
    ]
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=tracks,
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_topology", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_topology", out_root=out_root)
    patch_dir = out_root / "run_topology" / "patches" / patch_id
    segments_payload = _read_json(patch_dir / "step2" / "segments.json")
    kept_pairs = {(int(item["src_nodeid"]), int(item["dst_nodeid"])) for item in segments_payload["segments"]}
    assert kept_pairs == {(31, 41)}
    excluded = segments_payload["excluded_candidates"]
    excluded_by_pair = {(int(item["src_nodeid"]), int(item["dst_nodeid"])): str(item["reason"]) for item in excluded}
    assert excluded_by_pair[(11, 41)] == "terminal_owner_mismatch"
    assert excluded_by_pair[(21, 41)] == "terminal_owner_mismatch"
    assert excluded_by_pair[(41, 31)] == "pair_not_direct_legal_arc"
    step2_metrics = segments_payload["step2_metrics"]
    assert int(step2_metrics["segment_selected_count_before_topology_gate"]) == 4
    assert int(step2_metrics["segment_selected_count_after_topology_gate"]) == 1
    assert int(step2_metrics["directed_path_not_supported_count"]) == 0
    assert int(step2_metrics["pair_not_direct_legal_arc_count"]) == 1
    assert int(step2_metrics["terminal_owner_mismatch_segment_count"]) == 2
    assert int(step2_metrics["directionally_invalid_segment_count"]) == 0
    assert int(step2_metrics["terminal_node_invalid_segment_count"]) == 2
    audit = _read_json(patch_dir / "debug" / "step2_terminal_node_audit.json")
    node_41 = next(item for item in audit["nodes"] if int(item["nodeid"]) == 41)
    assert node_41["reverse_owner_status"] == "unique_owner"
    assert int(node_41["reverse_owner_src_nodeid"]) == 31
    pair_map = {str(item["pair_id"]): item for item in node_41["pairs"]}
    assert bool(pair_map["31:41"]["selected"]) is True
    assert bool(pair_map["31:41"]["topology_reverse_owner_match"]) is True
    assert pair_map["11:41"]["rejected_reason"] == "terminal_owner_mismatch"
    assert pair_map["21:41"]["rejected_reason"] == "terminal_owner_mismatch"
    assert bool(pair_map["11:41"]["topology_reverse_owner_match"]) is False
    should_not_exist = _read_json(patch_dir / "debug" / "step2_segment_should_not_exist.json")
    reasons = { (int(item["src_nodeid"]), int(item["dst_nodeid"])): str(item["reason"]) for item in should_not_exist["pairs"] }
    assert reasons[(11, 41)] == "terminal_owner_mismatch"
    assert reasons[(21, 41)] == "terminal_owner_mismatch"
    assert reasons[(41, 31)] == "pair_not_direct_legal_arc"
    invalid_11_41 = next(item for item in should_not_exist["pairs"] if int(item["src_nodeid"]) == 11 and int(item["dst_nodeid"]) == 41)
    assert invalid_11_41["topology_reverse_owner_status"] == "unique_owner"
    assert int(invalid_11_41["topology_reverse_owner_src_nodeid"]) == 31


def test_t05v2_topology_gate_keeps_explicit_allowed_pair_even_when_reverse_owner_prefers_other_src() -> None:
    topology = {
        "enabled": True,
        "allowed_pairs": {(5384367610468452, 765141), (23287538, 765141)},
        "incoming": {765141: {5384367610468452, 23287538}},
        "terminal_nodes": {765141},
        "terminal_reverse_ownership": {
            765141: {
                "status": "unique_owner",
                "src_nodeid": 23287538,
                "src_nodeids": [23287538],
            }
        },
    }

    assert (
        _topology_gate_reason(
            src_nodeid=5384367610468452,
            dst_nodeid=765141,
            topology=topology,
        )
        is None
    )
    assert (
        _topology_gate_reason(
            src_nodeid=23287538,
            dst_nodeid=765141,
            topology=topology,
        )
        is None
    )
    assert (
        _topology_gate_reason(
            src_nodeid=999999,
            dst_nodeid=765141,
            topology=topology,
        )
        == "terminal_owner_mismatch"
    )


def test_t05v2_production_arc_gate_requires_direct_legal_arc() -> None:
    candidate = {
        "src_nodeid": 10,
        "dst_nodeid": 20,
    }
    topology = {
        "enabled": True,
        "allowed_pairs": set(),
        "pair_arcs": {},
        "trace_only_pair_paths": {},
        "terminal_trace_paths": {},
        "terminal_nodes": set(),
        "terminal_direct_ownership": {},
        "terminal_reverse_ownership": {},
        "pair_sources": {},
        "pair_paths": {},
        "outgoing": {},
    }

    reason = _production_arc_gate_reason(candidate=candidate, topology=topology)

    assert reason == "pair_not_direct_legal_arc"
    assert bool(candidate["topology_arc_is_direct_legal"]) is False
    assert bool(candidate["topology_arc_is_unique"]) is False


def test_t05v2_step2_rejects_single_traj_pair_when_src_has_unique_unanchored_prior_endpoint(tmp_path: Path) -> None:
    patch_id = "unanchored_prior_conflict"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -5.0), (0.0, 5.0)], {"nodeid": 10}),
            _line_feature([(100.0, -5.0), (100.0, 5.0)], {"nodeid": 40}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -6.0), (105.0, -6.0), (105.0, 6.0), (-5.0, 6.0)])], "EPSG:3857")
    road_fc = _fc(
        [
            _line_feature([(0.0, 0.0), (50.0, 0.0)], {"snodeid": 10, "enodeid": 30}),
            _line_feature([(50.0, 0.0), (100.0, 0.0)], {"snodeid": 30, "enodeid": 40}),
        ],
        "EPSG:3857",
    )
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_prior_conflict", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_prior_conflict", out_root=out_root)
    patch_dir = out_root / "run_prior_conflict" / "patches" / patch_id
    segments_payload = _read_json(patch_dir / "step2" / "segments.json")
    assert segments_payload["segments"] == []
    excluded_by_pair = [
        item
        for item in segments_payload["excluded_candidates"]
        if int(item["src_nodeid"]) == 10 and int(item["dst_nodeid"]) == 40
    ]
    assert excluded_by_pair
    assert excluded_by_pair[0]["reason"] == "src_conflicts_with_unique_unanchored_prior_endpoint"
    assert excluded_by_pair[0]["stage"] == "semantic_hard_gate"
    assert excluded_by_pair[0]["arc_source_type"] == "direct_topology_arc"
    assert excluded_by_pair[0]["topology_arc_node_path"] == [10, 30, 40]
    assert excluded_by_pair[0]["competing_prior_pair_ids"] == ["10:30"]
    assert excluded_by_pair[0]["competing_prior_candidate_ids"] == ["prior_0"]
    assert excluded_by_pair[0]["competing_prior_trace_paths"] == [[10, 30, 40]]
    assert int(segments_payload["step2_metrics"]["unanchored_prior_conflict_segment_count"]) == 1
    should_not_exist = _read_json(patch_dir / "debug" / "step2_segment_should_not_exist.json")
    row = next(item for item in should_not_exist["pairs"] if int(item["src_nodeid"]) == 10 and int(item["dst_nodeid"]) == 40)
    assert row["reason"] == "src_conflicts_with_unique_unanchored_prior_endpoint"
    assert row["topology_sources"] == ["direct_topology_arc"]
    assert row["topology_paths"][0]["node_path"] == [10, 30, 40]


def test_t05v2_step2_keeps_multi_traj_pair_despite_unanchored_prior_endpoint(tmp_path: Path) -> None:
    patch_id = "unanchored_prior_multi_support"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -5.0), (0.0, 5.0)], {"nodeid": 10}),
            _line_feature([(100.0, -5.0), (100.0, 5.0)], {"nodeid": 40}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -6.0), (105.0, -6.0), (105.0, 6.0), (-5.0, 6.0)])], "EPSG:3857")
    road_fc = _fc(
        [
            _line_feature([(0.0, 0.0), (50.0, 0.0)], {"snodeid": 10, "enodeid": 30}),
            _line_feature([(50.0, 0.0), (100.0, 0.0)], {"snodeid": 30, "enodeid": 40}),
        ],
        "EPSG:3857",
    )
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[
            [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)],
            [(0.0, 0.2), (50.0, 0.2), (100.0, 0.2)],
        ],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_prior_multi", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_prior_multi", out_root=out_root)
    patch_dir = out_root / "run_prior_multi" / "patches" / patch_id
    segments_payload = _read_json(patch_dir / "step2" / "segments.json")
    kept_pairs = {(int(item["src_nodeid"]), int(item["dst_nodeid"])) for item in segments_payload["segments"]}
    assert kept_pairs == {(10, 40)}
    assert int(segments_payload["segments"][0]["support_count"]) == 2
    assert int(segments_payload["step2_metrics"]["unanchored_prior_conflict_segment_count"]) == 0


def test_t05v2_step2_keeps_single_traj_pair_when_unanchored_prior_only_matches_deeper_terminal_trace(tmp_path: Path) -> None:
    patch_id = "unanchored_prior_deep_terminal_trace"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -5.0), (0.0, 5.0)], {"nodeid": 10}),
            _line_feature([(100.0, -5.0), (100.0, 5.0)], {"nodeid": 40}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -6.0), (105.0, -6.0), (105.0, 60.0), (-5.0, 60.0)])], "EPSG:3857")
    road_fc = _fc(
        [
            _line_feature([(0.0, 50.0), (30.0, 50.0)], {"snodeid": 10, "enodeid": 25}),
            _line_feature([(30.0, 50.0), (70.0, 50.0)], {"snodeid": 25, "enodeid": 26}),
            _line_feature([(70.0, 50.0), (100.0, 50.0)], {"snodeid": 26, "enodeid": 40}),
        ],
        "EPSG:3857",
    )
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_prior_deep", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_prior_deep", out_root=out_root)
    patch_dir = out_root / "run_prior_deep" / "patches" / patch_id
    segments_payload = _read_json(patch_dir / "step2" / "segments.json")
    kept_pairs = {(int(item["src_nodeid"]), int(item["dst_nodeid"])) for item in segments_payload["segments"]}
    assert kept_pairs == {(10, 40)}
    assert int(segments_payload["step2_metrics"]["unanchored_prior_conflict_segment_count"]) == 0
    topology_debug = _read_json(patch_dir / "debug" / "step2_topology_pairs.json")
    pair_map = {str(item["pair_id"]): item for item in topology_debug["pairs"]}
    assert pair_map["10:40"]["topology_sources"] == ["direct_topology_arc"]
    assert pair_map["10:40"]["topology_paths"][0]["node_path"] == [10, 25, 26, 40]


def test_t05v2_step2_accepts_compressed_direct_arcs_and_keeps_trace_only_in_audit(tmp_path: Path) -> None:
    patch_id = "topology_trace_chain"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -5.0), (0.0, 5.0)], {"nodeid": 10}),
            _line_feature([(25.0, -5.0), (25.0, 5.0)], {"nodeid": 20}),
            _line_feature([(50.0, -5.0), (50.0, 5.0)], {"nodeid": 30}),
            _line_feature([(75.0, -5.0), (75.0, 5.0)], {"nodeid": 40}),
            _line_feature([(100.0, -5.0), (100.0, 5.0)], {"nodeid": 50}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -6.0), (105.0, -6.0), (105.0, 6.0), (-5.0, 6.0)])], "EPSG:3857")
    road_fc = _fc(
        [
            _line_feature([(0.0, 0.0), (10.0, 0.0)], {"snodeid": 10, "enodeid": 101}),
            _line_feature([(10.0, 0.0), (25.0, 0.0)], {"snodeid": 101, "enodeid": 20}),
            _line_feature([(25.0, 0.0), (35.0, 0.0)], {"snodeid": 20, "enodeid": 102}),
            _line_feature([(35.0, 0.0), (50.0, 0.0)], {"snodeid": 102, "enodeid": 30}),
            _line_feature([(50.0, 0.0), (60.0, 0.0)], {"snodeid": 30, "enodeid": 103}),
            _line_feature([(60.0, 0.0), (75.0, 0.0)], {"snodeid": 103, "enodeid": 40}),
            _line_feature([(75.0, 0.0), (85.0, 0.0)], {"snodeid": 40, "enodeid": 104}),
            _line_feature([(85.0, 0.0), (100.0, 0.0)], {"snodeid": 104, "enodeid": 50}),
        ],
        "EPSG:3857",
    )
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(0.0, 0.0), (25.0, 0.0), (50.0, 0.0), (75.0, 0.0), (100.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_trace", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_trace", out_root=out_root)
    patch_dir = out_root / "run_trace" / "patches" / patch_id
    segments_payload = _read_json(patch_dir / "step2" / "segments.json")
    kept_pairs = {(int(item["src_nodeid"]), int(item["dst_nodeid"])) for item in segments_payload["segments"]}
    assert kept_pairs == {(10, 20), (20, 30), (30, 40), (40, 50)}
    topology_debug = _read_json(patch_dir / "debug" / "step2_topology_pairs.json")
    pair_map = {str(item["pair_id"]): item for item in topology_debug["pairs"]}
    assert "10:20" in pair_map
    assert pair_map["10:20"]["topology_sources"] == ["direct_topology_arc"]
    assert pair_map["10:20"]["arc_source_type"] == "direct_topology_arc"
    assert pair_map["10:20"]["topology_paths"][0]["node_path"] == [10, 101, 20]
    step2_metrics = segments_payload["step2_metrics"]
    assert int(step2_metrics["segment_selected_count_after_topology_gate"]) == 4
    assert int(step2_metrics["trace_only_reachability_segment_count"]) == 3
    assert int(step2_metrics["topology_invalid_segment_count"]) == 3


def test_t05v2_step2_terminal_trace_is_audit_only(tmp_path: Path) -> None:
    patch_id = "topology_terminal_trace_audit_only"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -5.0), (0.0, 5.0)], {"nodeid": 10}),
            _line_feature([(50.0, 15.0), (50.0, 25.0)], {"nodeid": 20}),
            _line_feature([(100.0, -5.0), (100.0, 5.0)], {"nodeid": 40}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -10.0), (105.0, -10.0), (105.0, 30.0), (-5.0, 30.0)])], "EPSG:3857")
    road_fc = _fc(
        [
            _line_feature([(0.0, 0.0), (50.0, 20.0)], {"snodeid": 10, "enodeid": 20}),
            _line_feature([(50.0, 20.0), (100.0, 0.0)], {"snodeid": 20, "enodeid": 40}),
        ],
        "EPSG:3857",
    )
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_terminal_trace", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_terminal_trace", out_root=out_root)
    patch_dir = out_root / "run_terminal_trace" / "patches" / patch_id
    segments_payload = _read_json(patch_dir / "step2" / "segments.json")
    kept_pairs = {(int(item["src_nodeid"]), int(item["dst_nodeid"])) for item in segments_payload["segments"]}
    assert (10, 40) not in kept_pairs
    topology_debug = _read_json(patch_dir / "debug" / "step2_topology_pairs.json")
    pair_map = {str(item["pair_id"]): item for item in topology_debug["pairs"]}
    assert pair_map["10:40"]["topology_allowed"] is None
    assert pair_map["10:40"]["topology_sources"] == ["rcsdroad_terminal_trace"]
    assert pair_map["10:40"]["topology_paths"][0]["node_path"] == [10, 20, 40]
    excluded = [
        item
        for item in segments_payload["excluded_candidates"]
        if int(item["src_nodeid"]) == 10 and int(item["dst_nodeid"]) == 40
    ]
    assert excluded
    assert {str(item["reason"]) for item in excluded} == {"trace_only_reachability"}
    assert {str(item["stage"]) for item in excluded} == {"semantic_hard_gate"}


def test_t05v2_blocked_pair_bridge_classification_categories() -> None:
    unique = _classify_blocked_pair_bridge(
        src_nodeid=10,
        dst_nodeid=30,
        topology={"outgoing": {10: {20}, 20: {30}}, "trace_only_pair_paths": {}, "terminal_trace_paths": {}},
    )
    assert unique["bridge_classification"] == "unique_directed_bridge_candidate"
    assert unique["direct_bridge_nodeids"] == [20]

    multi = _classify_blocked_pair_bridge(
        src_nodeid=10,
        dst_nodeid=40,
        topology={"outgoing": {10: {20, 30}, 20: {40}, 30: {40}}, "trace_only_pair_paths": {}, "terminal_trace_paths": {}},
    )
    assert multi["bridge_classification"] == "multi_bridge_ambiguous"
    assert multi["direct_bridge_nodeids"] == [20, 30]

    gap = _classify_blocked_pair_bridge(
        src_nodeid=10,
        dst_nodeid=40,
        topology={"outgoing": {10: {20}, 20: {30}, 30: {40}}, "trace_only_pair_paths": {}, "terminal_trace_paths": {}},
    )
    assert gap["bridge_classification"] == "topology_gap_unresolved"
    assert gap["direct_bridge_paths"] == [[10, 20, 30, 40]]

    reject = _classify_blocked_pair_bridge(
        src_nodeid=10,
        dst_nodeid=40,
        topology={"outgoing": {10: {20}, 50: {60}}, "trace_only_pair_paths": {}, "terminal_trace_paths": {}},
    )
    assert reject["bridge_classification"] == "truly_non_adjacent_reject"
    assert reject["direct_bridge_paths"] == []


def test_t05v2_step2_writes_blocked_pair_bridge_audit(tmp_path: Path) -> None:
    patch_id = "blocked_pair_bridge_audit"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -5.0), (0.0, 5.0)], {"nodeid": 10}),
            _line_feature([(50.0, -5.0), (50.0, 5.0)], {"nodeid": 20}),
            _line_feature([(100.0, -5.0), (100.0, 5.0)], {"nodeid": 30}),
            _line_feature([(150.0, -5.0), (150.0, 5.0)], {"nodeid": 40}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -6.0), (155.0, -6.0), (155.0, 6.0), (-5.0, 6.0)])], "EPSG:3857")
    road_fc = _fc(
        [
            _line_feature([(0.0, 0.0), (50.0, 0.0)], {"snodeid": 10, "enodeid": 20}),
            _line_feature([(50.0, 0.0), (100.0, 0.0)], {"snodeid": 20, "enodeid": 30}),
            _line_feature([(100.0, 0.0), (150.0, 0.0)], {"snodeid": 30, "enodeid": 40}),
        ],
        "EPSG:3857",
    )
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0), (150.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_bridge", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_bridge", out_root=out_root)
    patch_dir = out_root / "run_bridge" / "patches" / patch_id
    bridge_audit = _read_json(patch_dir / "debug" / "step2_blocked_pair_bridge_audit.json")
    row = next(item for item in bridge_audit["pairs"] if str(item["pair_id"]) == "10:30")
    assert row["reject_stage"] == "pairing_filter"
    assert row["reject_reason"] == "non_adjacent_pair_blocked"
    assert row["bridge_classification"] == "unique_directed_bridge_candidate"
    assert row["direct_bridge_nodeids"] == [20]
    assert row["direct_bridge_paths"] == [[10, 20, 30]]


def test_t05v2_step2_promotes_missing_rcsd_node_to_pseudo_xsec_and_builds_direct_arcs(tmp_path: Path) -> None:
    patch_id = "pseudo_xsec_direct_arcs"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -5.0), (0.0, 5.0)], {"nodeid": 10}),
            _line_feature([(100.0, -5.0), (100.0, 5.0)], {"nodeid": 40}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -6.0), (105.0, -6.0), (105.0, 6.0), (-5.0, 6.0)])], "EPSG:3857")
    road_fc = _fc(
        [
            _line_feature([(0.0, 0.0), (50.0, 0.0)], {"snodeid": 10, "enodeid": 30}),
            _line_feature([(50.0, 0.0), (100.0, 0.0)], {"snodeid": 30, "enodeid": 40}),
        ],
        "EPSG:3857",
    )
    node_fc = _fc(
        [
            _point_feature((50.0, 0.0), {"nodeid": 30, "kind": 2}),
        ],
        "EPSG:3857",
    )
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]],
        road_fc=road_fc,
        node_fc=node_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_pseudo_xsec", out_root=out_root)
    frame_payload = _read_json(out_root / "run_pseudo_xsec" / "patches" / patch_id / "step1" / "input_frame.json")
    base_xsecs = frame_payload["input_frame"]["base_cross_sections"]
    assert {int(item["nodeid"]) for item in base_xsecs} == {10, 30, 40}
    pseudo_rows = [item for item in base_xsecs if str(item.get("properties", {}).get("source", "")) == "pseudo_rcsd_node"]
    assert len(pseudo_rows) == 1
    assert int(frame_payload["input_frame"]["input_summary"]["pseudo_xsec_count"]) == 1

    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_pseudo_xsec", out_root=out_root)
    segments_payload = _read_json(out_root / "run_pseudo_xsec" / "patches" / patch_id / "step2" / "segments.json")
    kept_pairs = {(int(item["src_nodeid"]), int(item["dst_nodeid"])) for item in segments_payload["segments"]}
    assert kept_pairs == {(10, 30), (30, 40)}


def test_t05v2_step2_provisional_allows_same_pair_multi_arc_candidates(tmp_path: Path) -> None:
    patch_id = "same_pair_multi_arc"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -10.0), (0.0, 10.0)], {"nodeid": 1}),
            _line_feature([(100.0, -10.0), (100.0, 10.0)], {"nodeid": 2}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -2.0), (105.0, -2.0), (105.0, 6.0), (-5.0, 6.0)])], "EPSG:3857")
    road_fc = _fc(
        [
            _line_feature([(0.0, 0.0), (100.0, 0.0)], {"snodeid": 1, "enodeid": 2}),
            _line_feature([(0.0, 4.0), (100.0, 4.0)], {"snodeid": 1, "enodeid": 2}),
        ],
        "EPSG:3857",
    )
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(0.0, 0.0), (100.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_multi_arc", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_multi_arc", out_root=out_root)
    segments_payload = _read_json(out_root / "run_multi_arc" / "patches" / patch_id / "step2" / "segments.json")
    pair_segments = [item for item in segments_payload["segments"] if int(item["src_nodeid"]) == 1 and int(item["dst_nodeid"]) == 2]
    assert len(pair_segments) == 2
    assert {str(item["topology_arc_id"]) for item in pair_segments} == {"arc_1_2_1", "arc_1_2_2"}
    assert all(bool(item["same_pair_provisional_allowed"]) for item in pair_segments)
    assert all(str(item["topology_arc_assignment_mode"]) == "same_pair_line_anchor_geometry_fit" for item in pair_segments)
    excluded = [
        item
        for item in segments_payload["excluded_candidates"]
        if int(item["src_nodeid"]) == 1 and int(item["dst_nodeid"]) == 2
    ]
    assert excluded == []
    registry_rows = [
        item
        for item in segments_payload["full_legal_arc_registry"]
        if int(item["src"]) == 1 and int(item["dst"]) == 2
    ]
    assert len(registry_rows) == 2
    assert all(str(item["arc_structure_type"]) == "SAME_PAIR_MULTI_ARC" for item in registry_rows)
    assert all(bool(item["same_pair_provisional_allowed"]) for item in registry_rows)
    assert all(str(item["unbuilt_stage"]) == "step3_same_pair_evidence_pending" for item in registry_rows)
    assert all(str(item["hard_block_reason"]) == "" for item in registry_rows)


def test_t05v2_same_pair_multi_arc_finalizes_in_step3_and_writes_review(tmp_path: Path) -> None:
    patch_id = "same_pair_multi_arc_step3"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -10.0), (0.0, 10.0)], {"nodeid": 1}),
            _line_feature([(100.0, -10.0), (100.0, 10.0)], {"nodeid": 2}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -2.0), (105.0, -2.0), (105.0, 6.0), (-5.0, 6.0)])], "EPSG:3857")
    road_fc = _fc(
        [
            _line_feature([(0.0, 0.0), (100.0, 0.0)], {"snodeid": 1, "enodeid": 2}),
            _line_feature([(0.0, 4.0), (100.0, 4.0)], {"snodeid": 1, "enodeid": 2}),
        ],
        "EPSG:3857",
    )
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[
            [(0.0, 0.0), (100.0, 0.0)],
            [(0.0, 4.0), (100.0, 4.0)],
        ],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_multi_arc_step3", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_multi_arc_step3", out_root=out_root)
    run_stage(stage="step3_witness", data_root=data_root, patch_id=patch_id, run_id="run_multi_arc_step3", out_root=out_root)
    run_root = out_root / "run_multi_arc_step3"
    step3_payload = _read_json(run_root / "patches" / patch_id / "step3" / "witnesses.json")
    rows = {str(item["topology_arc_id"]): item for item in step3_payload["full_legal_arc_registry"]}
    assert rows["arc_1_2_1"]["selected_support_traj_id"] == "traj_00"
    assert rows["arc_1_2_2"]["selected_support_traj_id"] == "traj_01"
    assert rows["arc_1_2_1"]["production_multi_arc_allowed"] is True
    assert rows["arc_1_2_2"]["production_multi_arc_allowed"] is True
    assert rows["arc_1_2_1"]["multi_arc_evidence_mode"] == "fallback_based"
    assert rows["arc_1_2_2"]["multi_arc_evidence_mode"] == "fallback_based"
    assert rows["arc_1_2_1"]["entered_main_flow"] is True
    assert rows["arc_1_2_2"]["entered_main_flow"] is True

    review = build_same_pair_provisional_allow_review(run_root, complex_patch_id=patch_id)
    assert int(review["row_count"]) == 2
    assert int(review["provisional_allow_count"]) == 2
    assert int(review["finalized_allow_count"]) == 2
    review_by_arc = {str(item["topology_arc_id"]): item for item in review["rows"]}
    assert review_by_arc["arc_1_2_1"]["topology_arc_assignment_mode"] == "same_pair_line_anchor_geometry_fit"
    assert review_by_arc["arc_1_2_1"]["multi_arc_evidence_mode"] == "fallback_based"
    assert review_by_arc["arc_1_2_2"]["multi_arc_evidence_mode"] == "fallback_based"


def test_t05v2_step1_splits_large_gap_trajectory_and_step3_writes_split_preprocessed_lines(tmp_path: Path) -> None:
    patch_id = "traj_split_preprocessed"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -10.0), (0.0, 10.0)], {"nodeid": 1}),
            _line_feature([(45.0, -10.0), (45.0, 10.0)], {"nodeid": 2}),
        ],
        "EPSG:3857",
    )
    road_fc = _fc([_line_feature([(0.0, 0.0), (45.0, 0.0)], {"snodeid": 1, "enodeid": 2})], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=_fc([_poly_feature([(-5.0, -4.0), (50.0, -4.0), (50.0, 4.0), (-5.0, 4.0)])], "EPSG:3857"),
        traj_tracks=[[(0.0, 0.0), (5.0, 0.0), (40.0, 0.0), (45.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_split", out_root=out_root)
    frame_payload = _read_json(out_root / "run_split" / "patches" / patch_id / "step1" / "input_frame.json")
    assert int(frame_payload["input_frame"]["trajectory_count"]) == 2
    input_summary = frame_payload["input_frame"]["input_summary"]
    assert int(input_summary["traj_source_count"]) == 1
    assert int(input_summary["traj_segment_count"]) == 2
    assert int(input_summary["traj_split_source_count"]) == 1

    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_split", out_root=out_root)
    run_stage(stage="step3_witness", data_root=data_root, patch_id=patch_id, run_id="run_split", out_root=out_root)
    preprocessed = _read_json(out_root / "run_split" / "patches" / patch_id / "step3" / "preprocessed_traj_lines.geojson")
    assert len(preprocessed["features"]) == 2
    traj_ids = {str(item["properties"]["traj_id"]) for item in preprocessed["features"]}
    assert traj_ids == {"traj_00__seg0001", "traj_00__seg0002"}
    assert {int(item["properties"]["segment_index"]) for item in preprocessed["features"]} == {1, 2}
    assert all(str(item["properties"]["source_traj_id"]) == "traj_00" for item in preprocessed["features"])


def test_t05v2_arc_first_partial_support_uses_effective_points_without_internal_flyline(tmp_path: Path) -> None:
    patch_id = "arc_first_partial_clean_points"
    data_root = tmp_path / "data"
    road_fc = _fc([_line_feature([(0.0, 0.0), (100.0, 0.0)], {"snodeid": 1, "enodeid": 2})], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=_fc([_poly_feature([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)])], "EPSG:3857"),
        traj_tracks=[[(20.0, 0.0), (40.0, 0.0), (50.0, 20.0), (60.0, 0.0), (80.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_partial_clean", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_partial_clean", out_root=out_root)
    run_stage(stage="step3_witness", data_root=data_root, patch_id=patch_id, run_id="run_partial_clean", out_root=out_root)
    step3_payload = _read_json(out_root / "run_partial_clean" / "patches" / patch_id / "step3" / "witnesses.json")
    row = step3_payload["full_legal_arc_registry"][0]
    assert row["traj_support_type"] == "partial_arc_support"
    assert row["traj_support_segments"]
    line_coords = row["traj_support_segments"][0]["line_coords"]
    assert {round(float(coord[1]), 6) for coord in line_coords} == {0.0}


def test_t05v2_same_pair_support_deconflict_assigns_distinct_support_sides(tmp_path: Path) -> None:
    from highway_topo_poc.modules.t05_topology_between_rc_v2 import pipeline as pipeline_module

    patch_id = "same_pair_support_deconflict"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -10.0), (0.0, 10.0)], {"nodeid": 1}),
            _line_feature([(100.0, -10.0), (100.0, 10.0)], {"nodeid": 2}),
        ],
        "EPSG:3857",
    )
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=_fc([_poly_feature([(-5.0, -2.0), (105.0, -2.0), (105.0, 6.0), (-5.0, 6.0)])], "EPSG:3857"),
        traj_tracks=[
            [(0.0, 0.0), (100.0, 0.0)],
            [(0.0, 4.0), (100.0, 4.0)],
        ],
        road_fc=_fc(
            [
                _line_feature([(0.0, 2.0), (100.0, 2.0)], {"snodeid": 1, "enodeid": 2}),
            ],
            "EPSG:3857",
        ),
    )
    inputs, frame, prior_roads = pipeline_module.load_inputs_and_frame(data_root, patch_id, params=DEFAULT_PARAMS)
    full_registry_rows = [
        {
            "pair": "1:2",
            "canonical_pair": "1:2",
            "src": 1,
            "dst": 2,
            "topology_arc_id": "arc_1_2_1",
            "topology_arc_source_type": "direct_topology_arc",
            "edge_ids": ["edge_low"],
            "node_path": [1, 10, 2],
            "line_coords": [[0.0, 2.0], [100.0, 2.0]],
            "is_direct_legal": True,
            "is_unique": False,
            "entered_main_flow": False,
            "selected_segment_count": 0,
            "same_pair_multi_arc_candidate": True,
            "same_pair_provisional_allowed": True,
            "same_pair_distinct_path_signal": ["distinct_topology_edge_signal"],
            "topology_arc_assignment_mode": "same_pair_line_anchor_geometry_fit",
            "working_segment_source": "",
            "unbuilt_stage": "step3_same_pair_evidence_pending",
            "unbuilt_reason": "same_pair_multi_arc_candidate_pending_step3",
        },
        {
            "pair": "1:2",
            "canonical_pair": "1:2",
            "src": 1,
            "dst": 2,
            "topology_arc_id": "arc_1_2_2",
            "topology_arc_source_type": "direct_topology_arc",
            "edge_ids": ["edge_high"],
            "node_path": [1, 11, 2],
            "line_coords": [[0.0, 2.0], [100.0, 2.0]],
            "is_direct_legal": True,
            "is_unique": False,
            "entered_main_flow": False,
            "selected_segment_count": 0,
            "same_pair_multi_arc_candidate": True,
            "same_pair_provisional_allowed": True,
            "same_pair_distinct_path_signal": ["distinct_topology_edge_signal"],
            "topology_arc_assignment_mode": "same_pair_line_anchor_geometry_fit",
            "working_segment_source": "",
            "unbuilt_stage": "step3_same_pair_evidence_pending",
            "unbuilt_reason": "same_pair_multi_arc_candidate_pending_step3",
        },
    ]
    evidence = build_arc_evidence_attach(
        full_registry_rows=full_registry_rows,
        selected_segments=[],
        inputs=inputs,
        frame=frame,
        prior_roads=prior_roads,
        params=DEFAULT_PARAMS,
    )
    rows = {str(item["topology_arc_id"]): item for item in evidence["rows"]}
    assert rows["arc_1_2_1"]["selected_support_traj_id"] != rows["arc_1_2_2"]["selected_support_traj_id"]
    assert rows["arc_1_2_1"]["support_surface_side_signature"] != rows["arc_1_2_2"]["support_surface_side_signature"]
    assert rows["arc_1_2_1"]["production_multi_arc_allowed"] is True
    assert rows["arc_1_2_2"]["production_multi_arc_allowed"] is True


def test_t05v2_same_pair_conflict_key_coalesces_nearly_identical_surface_sides() -> None:
    from highway_topo_poc.modules.t05_topology_between_rc_v2 import step3_arc_evidence as evidence_module

    candidate_a = {
        "support_corridor_signature": [(10.0, 0.0), (0.0, 0.0), (100.0, 0.0)],
        "support_surface_side_signature": [0.97, 0.03],
        "support_anchor_src_coords": [0.0, 0.0],
        "support_anchor_dst_coords": [100.0, 0.0],
    }
    candidate_b = {
        "support_corridor_signature": [(10.0, 0.0), (0.0, 0.0), (100.0, 0.0)],
        "support_surface_side_signature": [0.96, 0.04],
        "support_anchor_src_coords": [0.0, 0.2],
        "support_anchor_dst_coords": [100.0, 0.2],
    }

    assert evidence_module._same_pair_support_conflict_key(candidate_a) == evidence_module._same_pair_support_conflict_key(candidate_b)


def test_t05v2_step2_writes_traj_crossing_and_support_audits(tmp_path: Path) -> None:
    patch_id = "traj_audit"
    data_root = tmp_path / "data"
    road_fc = _fc([_line_feature([(0.0, 0.0), (100.0, 0.0)], {"snodeid": 1, "enodeid": 2})], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=_fc([_poly_feature([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)])], "EPSG:3857"),
        traj_tracks=[[(0.0, 0.0), (30.0, 0.0), (70.0, 0.0), (100.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_audit", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_audit", out_root=out_root)
    patch_dir = out_root / "run_audit" / "patches" / patch_id
    raw_crossings = _read_json(patch_dir / "debug" / "step2_traj_crossings_raw.geojson")
    filtered_crossings = _read_json(patch_dir / "debug" / "step2_traj_crossings_filtered.geojson")
    support_trajs = _read_json(patch_dir / "debug" / "step2_segment_support_trajs.geojson")
    metrics = _read_json(patch_dir / "step2" / "segments.json")["step2_metrics"]
    assert raw_crossings["features"]
    assert filtered_crossings["features"]
    assert support_trajs["features"]
    raw_props = raw_crossings["features"][0]["properties"]
    filtered_props = filtered_crossings["features"][0]["properties"]
    support_props = support_trajs["features"][0]["properties"]
    assert "traj_id" in raw_props
    assert "crossing_order_on_traj" in raw_props
    assert "local_heading" in raw_props
    assert "dropped_reason" in filtered_props
    assert "kept_reason" in filtered_props
    assert "pair_ids" in raw_props
    assert "selected_pair_ids" in filtered_props
    assert "segment_id" in support_props
    assert "support_direction_ok" in support_props
    assert "pair_id" in support_props
    assert "segment_single_traj_support" in support_props
    assert int(metrics["traj_crossing_raw_count"]) >= 2
    assert int(metrics["traj_crossing_filtered_count"]) >= 2


def test_t05v2_missing_previous_stage_reports_expected_paths(tmp_path: Path) -> None:
    patch_id = "missing_prev"
    data_root = tmp_path / "data"
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=_fc([_poly_feature([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)])], "EPSG:3857"),
        traj_tracks=[[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]],
    )
    out_root = tmp_path / "out"
    with pytest.raises(Exception, match="previous_stage_missing:step1_input_frame:expected_state=.*step1.*step_state.json:expected_artifact=.*step1.*input_frame.json"):
        run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_missing", out_root=out_root)


def test_t05v2_unique_witness_based_full_pipeline(tmp_path: Path) -> None:
    patch_id = "unique_corridor"
    data_root = tmp_path / "data"
    road_fc = _fc([_line_feature([(0.0, 0.0), (100.0, 0.0)], {"snodeid": 1, "enodeid": 2})], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=_fc([_poly_feature([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)])], "EPSG:3857"),
        traj_tracks=[[(0.0, 0.0), (20.0, 0.0), (50.0, 0.0), (80.0, 0.0), (100.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_full_pipeline(data_root=data_root, patch_id=patch_id, run_id="run3", out_root=out_root)
    metrics = _read_json(out_root / "run3" / "patches" / patch_id / "metrics.json")
    gate = _read_json(out_root / "run3" / "patches" / patch_id / "gate.json")
    roads = _read_json(out_root / "run3" / "patches" / patch_id / "Road.geojson")
    shape_ref = _read_json(out_root / "run3" / "patches" / patch_id / "debug" / "shape_ref_line.geojson")
    summary = (out_root / "run3" / "patches" / patch_id / "summary.txt").read_text(encoding="utf-8")
    assert int(metrics["road_count"]) == 1
    assert int(metrics["raw_candidate_count"]) >= 1
    assert int(metrics["witness_selected_count_total"]) == 1
    assert int(metrics["witness_selected_count_cross0"]) == 1
    assert int(metrics["witness_selected_count_cross1"]) == 0
    assert int(metrics["no_geometry_candidate_count"]) == 0
    assert int(metrics["pair_scoped_exception_audit_count"]) == 0
    assert metrics["pair_scoped_exception_selected_pair_ids"] == []
    assert metrics["pair_scoped_exception_rejected_pair_ids"] == []
    assert metrics["pair_scoped_exception_non_allowlisted_cross1_pair_ids"] == []
    assert metrics["segments"][0]["corridor_identity"] == "witness_based"
    assert metrics["segments"][0]["corridor_identity_state"] == "witness_based"
    assert metrics["segments"][0]["slot_src_status"] == "resolved"
    assert metrics["segments"][0]["slot_dst_status"] == "resolved"
    assert metrics["segments"][0]["failure_classification"] == "built"
    assert float(metrics["segments"][0]["road_in_drivezone_ratio"]) >= 0.99
    assert metrics["segments"][0]["shape_ref_mode"] == "witness_reference_projected_anchored"
    assert bool(gate["overall_pass"]) is True
    assert len(roads["features"]) == 1
    assert len(shape_ref["features"]) == 1
    assert "pair_scoped_exception: selected=0 rejected=0 non_allowlisted_cross1=0" in summary
    assert "road_summary: built=1 failed=0" in summary


def test_t05v2_prior_based_for_short_prior_segment(tmp_path: Path) -> None:
    patch_id = "prior_short"
    data_root = tmp_path / "data"
    road_fc = _fc([_line_feature([(0.0, 0.0), (8.0, 0.0)], {"snodeid": 10, "enodeid": 20})], "EPSG:3857")
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -8.0), (0.0, 8.0)], {"nodeid": 10}),
            _line_feature([(8.0, -8.0), (8.0, 8.0)], {"nodeid": 20}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-2.0, -2.0), (10.0, -2.0), (10.0, 2.0), (-2.0, 2.0)])], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(-20.0, 20.0), (-10.0, 20.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_full_pipeline(data_root=data_root, patch_id=patch_id, run_id="run4", out_root=out_root)
    metrics = _read_json(out_root / "run4" / "patches" / patch_id / "metrics.json")
    gate = _read_json(out_root / "run4" / "patches" / patch_id / "gate.json")
    roads = _read_json(out_root / "run4" / "patches" / patch_id / "Road.geojson")
    assert metrics["segments"][0]["corridor_identity"] == "prior_based"
    assert metrics["segments"][0]["failure_classification"] == "built"
    assert metrics["segments"][0]["shape_ref_mode"] == "prior_reference_slot_anchored"
    assert roads["features"][0]["properties"]["corridor_state"] == "prior_based"
    assert bool(gate["overall_pass"]) is True
    assert any(bp["reason"] == "prior_based_fallback" for bp in gate["soft_breakpoints"])


def test_t05v2_short_direct_arc_with_terminal_support_can_build(tmp_path: Path) -> None:
    patch_id = "short_unresolved"
    data_root = tmp_path / "data"
    road_fc = _fc([_line_feature([(0.0, 0.0), (8.0, 0.0)], {"snodeid": 10, "enodeid": 20})], "EPSG:3857")
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -8.0), (0.0, 8.0)], {"nodeid": 10}),
            _line_feature([(8.0, -8.0), (8.0, 8.0)], {"nodeid": 20}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-2.0, -2.0), (10.0, -2.0), (10.0, 2.0), (-2.0, 2.0)])], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(0.0, 0.0), (4.0, 0.0), (8.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_full_pipeline(data_root=data_root, patch_id=patch_id, run_id="run5", out_root=out_root)
    metrics = _read_json(out_root / "run5" / "patches" / patch_id / "metrics.json")
    gate = _read_json(out_root / "run5" / "patches" / patch_id / "gate.json")
    roads = _read_json(out_root / "run5" / "patches" / patch_id / "Road.geojson")
    reason_trace = _read_json(out_root / "run5" / "patches" / patch_id / "debug" / "reason_trace.json")
    assert metrics["segments"][0]["corridor_identity"] == "witness_based"
    assert int(metrics["no_geometry_candidate_count"]) == 0
    assert metrics["segments"][0]["failure_classification"] == "built"
    assert reason_trace["road_results"][0]["failure_classification"] == "built"
    assert len(roads["features"]) == 1
    assert bool(gate["overall_pass"]) is True


def test_t05v2_slot_mapping_uses_witness_fraction_not_nearest_point(tmp_path: Path) -> None:
    patch_id = "slot_fraction"
    data_root = tmp_path / "data"
    road_fc = _fc([_line_feature([(0.0, -6.0), (100.0, 6.0)], {"snodeid": 1, "enodeid": 2})], "EPSG:3857")
    drivezone_fc = _fc(
        [
            _poly_feature([(-5.0, 4.0), (105.0, 4.0), (105.0, 8.0), (-5.0, 8.0)]),
            _poly_feature([(-5.0, -8.0), (20.0, -8.0), (20.0, -4.0), (-5.0, -4.0)]),
            _poly_feature([(20.0, -8.0), (35.0, -8.0), (35.0, 8.0), (20.0, 8.0)]),
        ],
        "EPSG:3857",
    )
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(0.0, -6.0), (20.0, -6.0), (30.0, 0.0), (40.0, 6.0), (70.0, 6.0), (100.0, 6.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_full_pipeline(data_root=data_root, patch_id=patch_id, run_id="run6", out_root=out_root)
    roads = _read_json(out_root / "run6" / "patches" / patch_id / "Road.geojson")
    metrics = _read_json(out_root / "run6" / "patches" / patch_id / "metrics.json")
    start_x, start_y = roads["features"][0]["geometry"]["coordinates"][0]
    assert metrics["segments"][0]["corridor_identity"] == "witness_based"
    assert start_y > 4.0
    assert abs(start_y - (-6.0)) > 5.0


def test_t05v2_arc_first_registry_enters_direct_unique_arc_without_selected_segment() -> None:
    topology = {
        "pair_arcs": {
            (1, 2): [
                {
                    "arc_id": "arc_1_2_1",
                    "source": "direct_topology_arc",
                    "node_path": [1, 2],
                    "edge_ids": ["edge_12"],
                    "line_coords": [(0.0, 0.0), (100.0, 0.0)],
                    "chain_len": 1,
                }
            ]
        }
    }
    registry = build_full_legal_arc_registry(topology=topology, selected_segments=[])
    assert int(registry["summary"]["all_direct_legal_arc_count"]) == 1
    assert int(registry["summary"]["all_direct_unique_legal_arc_count"]) == 1
    assert int(registry["summary"]["entered_main_flow_arc_count"]) == 1
    row = registry["rows"][0]
    assert bool(row["entered_main_flow"]) is True
    assert int(row["selected_segment_count"]) == 0
    assert row["working_segment_source"] == ""


def test_t05v2_arc_first_partial_support_recovers_same_arc_without_terminal_crossing(tmp_path: Path) -> None:
    patch_id = "arc_first_partial"
    data_root = tmp_path / "data"
    road_fc = _fc([_line_feature([(0.0, 0.0), (100.0, 0.0)], {"snodeid": 1, "enodeid": 2})], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=_fc([_poly_feature([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)])], "EPSG:3857"),
        traj_tracks=[[(20.0, 0.0), (40.0, 0.0), (60.0, 0.0), (80.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_arcfirst1", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_arcfirst1", out_root=out_root)
    run_stage(stage="step3_witness", data_root=data_root, patch_id=patch_id, run_id="run_arcfirst1", out_root=out_root)
    step3_payload = _read_json(out_root / "run_arcfirst1" / "patches" / patch_id / "step3" / "witnesses.json")
    row = step3_payload["full_legal_arc_registry"][0]
    assert bool(row["entered_main_flow"]) is True
    assert row["traj_support_type"] == "partial_arc_support"
    assert float(row["traj_support_coverage_ratio"]) > 0.18
    assert len(row["traj_support_segments"]) >= 1
    assert row["support_reference_coords"]
    assert row["support_anchor_src_coords"] is not None
    assert row["support_anchor_dst_coords"] is not None
    assert row["working_segment_source"] in {"arc_first_materialized_segment", "step2_selected_segment"}


def test_t05v2_arc_first_stitched_support_uses_same_arc_fragments(tmp_path: Path) -> None:
    patch_id = "arc_first_stitched"
    data_root = tmp_path / "data"
    road_fc = _fc([_line_feature([(0.0, 0.0), (100.0, 0.0)], {"snodeid": 1, "enodeid": 2})], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=_fc([_poly_feature([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)])], "EPSG:3857"),
        traj_tracks=[
            [(0.0, 0.0), (20.0, 0.0), (35.0, 0.0), (45.0, 0.0)],
            [(55.0, 0.0), (70.0, 0.0), (85.0, 0.0), (100.0, 0.0)],
        ],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_arcfirst2", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_arcfirst2", out_root=out_root)
    run_stage(stage="step3_witness", data_root=data_root, patch_id=patch_id, run_id="run_arcfirst2", out_root=out_root)
    patch_dir = out_root / "run_arcfirst2" / "patches" / patch_id
    step3_payload = _read_json(patch_dir / "step3" / "witnesses.json")
    row = step3_payload["full_legal_arc_registry"][0]
    assert row["traj_support_type"] == "stitched_arc_support"
    assert row["support_generation_mode"] == "stitched"
    assert row["support_generation_reason"] == "stitched_fallback_due_to_untrusted_or_missing_full_xsec_single_support"
    assert row["selected_support_traj_id"] == ""
    assert len(row["traj_support_segments"]) >= 2
    assert all(bool(item["is_stitched"]) for item in row["traj_support_segments"])
    assert bool(row["stitched_support_interval_reference_trusted"]) is True
    assert row["support_interval_reference_source"] == "stitched_support"
    assert (patch_dir / "step3" / "preprocessed_traj_lines.geojson").exists()
    assert (patch_dir / "step3" / "arc_single_traj_support_segments.geojson").exists()
    assert (patch_dir / "step3" / "arc_stitched_support_segments.geojson").exists()
    stitched_debug = _read_json(patch_dir / "step3" / "arc_stitched_support_segments.geojson")
    assert len(stitched_debug["features"]) >= 2
    assert all(bool(item["properties"]["is_stitched"]) for item in stitched_debug["features"])
    assert any(bool(item["properties"]["accepted_for_production"]) for item in stitched_debug["features"])


def test_t05v2_arc_first_prefers_dominant_terminal_crossing_cluster(tmp_path: Path) -> None:
    patch_id = "arc_first_terminal_cluster"
    data_root = tmp_path / "data"
    road_fc = _fc([_line_feature([(0.0, 2.0), (100.0, 2.0)], {"snodeid": 1, "enodeid": 2})], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=_fc([_poly_feature([(-5.0, -6.0), (105.0, -6.0), (105.0, 6.0), (-5.0, 6.0)])], "EPSG:3857"),
        traj_tracks=[
            [(0.0, 4.0), (50.0, 4.0), (100.0, 4.0)],
            [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)],
            [(0.0, 0.2), (50.0, 0.2), (100.0, 0.2)],
        ],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_terminal_cluster", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_terminal_cluster", out_root=out_root)
    run_stage(stage="step3_witness", data_root=data_root, patch_id=patch_id, run_id="run_terminal_cluster", out_root=out_root)
    step3_payload = _read_json(out_root / "run_terminal_cluster" / "patches" / patch_id / "step3" / "witnesses.json")
    row = step3_payload["full_legal_arc_registry"][0]
    assert row["traj_support_type"] == "terminal_crossing_support"
    assert row["selected_support_traj_id"] in {"traj_01", "traj_02"}
    assert bool(row["support_full_xsec_crossing"]) is True
    assert bool(row["support_cluster_is_dominant"]) is True
    assert int(row["support_cluster_support_count"]) == 2
    assert bool(row["selected_support_interval_reference_trusted"]) is True
    assert row["support_interval_reference_source"] == "selected_support"


def test_t05v2_support_full_xsec_status_promotes_dual_anchor_partial_support() -> None:
    promoted, mode, has_src_anchor, has_dst_anchor = _step3_evidence._support_full_xsec_status(
        traj_production_type="partial_arc_support",
        traj_production_segments=[
            {
                "supports_src_xsec_anchor": True,
                "supports_dst_xsec_anchor": True,
            }
        ],
        traj_support_span_count=1,
        coverage_ratio=0.88,
        support_anchor_src_coords=[0.0, 0.5],
        support_anchor_dst_coords=[100.0, 0.2],
        params=dict(DEFAULT_PARAMS),
    )

    assert bool(promoted) is True
    assert mode == "partial_dual_anchor"
    assert bool(has_src_anchor) is True
    assert bool(has_dst_anchor) is True


def test_t05v2_near_full_partial_support_cluster_beats_isolated_terminal_outlier() -> None:
    params = dict(DEFAULT_PARAMS)
    candidates = [
        {
            "traj_id": "wrong_terminal",
            "selected_support_traj_id": "wrong_terminal",
            "traj_support_type": "terminal_crossing_support",
            "traj_support_ids": ["wrong_terminal"],
            "traj_support_span_count": 1,
            "traj_support_coverage_ratio": 1.0,
            "traj_support_segments": [],
            "support_reference_coords": [[0.0, 4.0], [50.0, 4.0], [100.0, 4.0]],
            "support_anchor_src_coords": [0.0, 4.0],
            "support_anchor_dst_coords": [100.0, 4.0],
            "support_corridor_signature": [[0.0, 4.0], [50.0, 4.0], [100.0, 4.0]],
            "support_surface_side_signature": [0.9, 0.9],
            "support_full_xsec_crossing": True,
            "support_full_xsec_mode": "strict_terminal",
            "support_has_src_xsec_anchor": True,
            "support_has_dst_xsec_anchor": True,
            "surface_consistent_segment_count": 1,
            "best_line_distance_m": 12.0,
        },
        {
            "traj_id": "near_full_a",
            "selected_support_traj_id": "near_full_a",
            "traj_support_type": "partial_arc_support",
            "traj_support_ids": ["near_full_a"],
            "traj_support_span_count": 1,
            "traj_support_coverage_ratio": 0.93,
            "traj_support_segments": [],
            "support_reference_coords": [[0.0, 0.5], [50.0, 0.3], [100.0, 0.1]],
            "support_anchor_src_coords": [1.0, 0.6],
            "support_anchor_dst_coords": [101.0, 0.2],
            "support_corridor_signature": [[0.0, 0.5], [50.0, 0.3], [100.0, 0.1]],
            "support_surface_side_signature": [0.18, 0.22],
            "support_full_xsec_crossing": True,
            "support_full_xsec_mode": "partial_dual_anchor",
            "support_has_src_xsec_anchor": True,
            "support_has_dst_xsec_anchor": True,
            "surface_consistent_segment_count": 1,
            "best_line_distance_m": 1.2,
        },
        {
            "traj_id": "near_full_b",
            "selected_support_traj_id": "near_full_b",
            "traj_support_type": "partial_arc_support",
            "traj_support_ids": ["near_full_b"],
            "traj_support_span_count": 1,
            "traj_support_coverage_ratio": 0.91,
            "traj_support_segments": [],
            "support_reference_coords": [[0.0, 0.4], [50.0, 0.2], [100.0, 0.0]],
            "support_anchor_src_coords": [2.0, 0.5],
            "support_anchor_dst_coords": [102.0, 0.1],
            "support_corridor_signature": [[0.0, 0.4], [50.0, 0.2], [100.0, 0.0]],
            "support_surface_side_signature": [0.21, 0.19],
            "support_full_xsec_crossing": True,
            "support_full_xsec_mode": "partial_dual_anchor",
            "support_has_src_xsec_anchor": True,
            "support_has_dst_xsec_anchor": True,
            "surface_consistent_segment_count": 1,
            "best_line_distance_m": 1.1,
        },
    ]
    stitched_summary = {
        "stitched_support_available": False,
        "stitched_support_ready": False,
        "stitched_support_anchor_src_coords": None,
        "stitched_support_anchor_dst_coords": None,
        "stitched_support_surface_side_signature": [],
    }

    annotated = _step3_evidence._annotate_support_candidate_clusters(list(candidates), params=params)
    annotated = _step3_evidence._annotate_support_candidate_interval_reference_trust(
        annotated,
        stitched_summary=stitched_summary,
        params=params,
    )
    ranked = sorted(annotated, key=_step3_evidence._support_selection_key)

    assert ranked[0]["traj_id"] in {"near_full_a", "near_full_b"}
    assert bool(ranked[0]["support_cluster_is_dominant"]) is True
    assert int(ranked[0]["support_cluster_support_count"]) == 2
    assert bool(ranked[0]["support_interval_reference_trusted"]) is True
    outlier = next(item for item in annotated if item["traj_id"] == "wrong_terminal")
    assert int(outlier["support_cluster_support_count"]) == 1
    assert bool(outlier["support_interval_reference_trusted"]) is False


def test_t05v2_arc_first_prefilter_keeps_same_arc_support_and_skips_far_traj(tmp_path: Path) -> None:
    patch_id = "arc_first_prefilter"
    data_root = tmp_path / "data"
    road_fc = _fc([_line_feature([(0.0, 0.0), (100.0, 0.0)], {"snodeid": 1, "enodeid": 2})], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=_fc([_poly_feature([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)])], "EPSG:3857"),
        traj_tracks=[
            [(20.0, 0.0), (40.0, 0.0), (60.0, 0.0), (80.0, 0.0)],
            [(20.0, 40.0), (40.0, 40.0), (60.0, 40.0), (80.0, 40.0)],
        ],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_prefilter", out_root=out_root)
    run_stage(stage="step2_segment", data_root=data_root, patch_id=patch_id, run_id="run_prefilter", out_root=out_root)
    run_stage(stage="step3_witness", data_root=data_root, patch_id=patch_id, run_id="run_prefilter", out_root=out_root)
    step3_payload = _read_json(out_root / "run_prefilter" / "patches" / patch_id / "step3" / "witnesses.json")
    audit_row = step3_payload["arc_evidence_attach_audit"][0]
    assert audit_row["traj_support_type"] == "partial_arc_support"
    assert int(audit_row["prefilter_candidate_traj_count"]) == 1
    assert step3_payload["runtime"]["trajectory_prefilter_time_ms"] >= 0.0
    assert step3_payload["runtime"]["support_attach_core_loop_time_ms"] >= 0.0


def test_t05v2_build_witness_patch_surface_cache_keeps_same_result(tmp_path: Path) -> None:
    from highway_topo_poc.modules.t05_topology_between_rc_v2 import pipeline as pipeline_module

    patch_id = "surface_cache_same_result"
    data_root = tmp_path / "data"
    road_fc = _fc([_line_feature([(0.0, 0.0), (100.0, 0.0)], {"snodeid": 1, "enodeid": 2})], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=_fc([_poly_feature([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)])], "EPSG:3857"),
        traj_tracks=[[(0.0, 0.0), (30.0, 0.0), (60.0, 0.0), (100.0, 0.0)]],
        road_fc=road_fc,
    )
    inputs, _frame, _prior = pipeline_module.load_inputs_and_frame(data_root, patch_id, params=DEFAULT_PARAMS)
    cache = build_patch_geometry_cache(inputs, DEFAULT_PARAMS)
    segment = Segment(
        segment_id="seg-cache",
        src_nodeid=1,
        dst_nodeid=2,
        direction="src->dst",
        geometry_coords=((0.0, 0.0), (100.0, 0.0)),
        candidate_ids=("cand",),
        source_modes=("traj",),
        support_traj_ids=("traj_00",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=1,
        prior_supported=False,
        formation_reason="test",
        length_m=100.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_1_2_1",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_edge_ids=("edge_12",),
        topology_arc_node_path=(1, 2),
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
        bridge_candidate_retained=False,
        bridge_chain_exists=False,
        bridge_chain_unique=False,
        bridge_chain_nodes=tuple(),
        bridge_chain_source="",
        bridge_diagnostic_reason="",
        bridge_decision_stage="",
        bridge_decision_reason="",
        same_pair_rank=1,
        kept_reason="test",
    )
    uncached = build_witness_for_segment(segment, inputs, DEFAULT_PARAMS)
    cached = build_witness_for_segment(segment, inputs, DEFAULT_PARAMS, drivable_surface=cache["drivable_surface"])
    assert uncached.status == cached.status
    assert uncached.reason == cached.reason
    assert uncached.selected_interval_rank == cached.selected_interval_rank


def test_t05v2_divstrip_blocks_final_road(tmp_path: Path) -> None:
    patch_id = "divstrip_block"
    data_root = tmp_path / "data"
    drivezone_fc = _fc([_poly_feature([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)])], "EPSG:3857")
    divstrip_fc = _fc([_poly_feature([(45.0, -5.0), (55.0, -5.0), (55.0, 5.0), (45.0, 5.0)])], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=drivezone_fc,
        divstrip_fc=divstrip_fc,
        traj_tracks=[[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]],
    )
    out_root = tmp_path / "out"
    run_full_pipeline(data_root=data_root, patch_id=patch_id, run_id="run7", out_root=out_root)
    gate = _read_json(out_root / "run7" / "patches" / patch_id / "gate.json")
    metrics = _read_json(out_root / "run7" / "patches" / patch_id / "metrics.json")
    reason_trace = _read_json(out_root / "run7" / "patches" / patch_id / "debug" / "reason_trace.json")
    assert bool(gate["overall_pass"]) is False
    assert gate["hard_breakpoints"]
    assert int(metrics["road_count"]) == 0
    if metrics["segments"]:
        assert metrics["segments"][0]["failure_classification"] == "final_geometry_invalid"
        assert metrics["failure_classification_hist"] == {"final_geometry_invalid": 1}
        assert reason_trace["road_results"][0]["failure_classification"] == "final_geometry_invalid"
        assert reason_trace["road_results"][0]["candidate_attempts"]
    else:
        assert metrics["failure_classification_hist"] == {}
        assert reason_trace["road_results"] == []


def test_t05v2_build_final_road_prefers_projected_witness_reference_before_segment_support() -> None:
    segment = Segment(
        segment_id="seg_fallback",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((0.0, 1.0), (50.0, 1.0), (100.0, 1.0)),
        candidate_ids=("cand_1",),
        source_modes=("traj",),
        support_traj_ids=("traj_1",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=False,
        formation_reason="traj_supported_cluster",
        length_m=100.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        same_pair_rank=1,
        kept_reason="",
    )
    witness_interval = CorridorInterval(
        start_s=3.5,
        end_s=4.5,
        center_s=4.0,
        length_m=1.0,
        rank=0,
        geometry_coords=((50.0, -6.5), (50.0, -5.5)),
    )
    witness = CorridorWitness(
        segment_id="seg_fallback",
        status="selected",
        reason="witness_interval_selected",
        line_coords=((50.0, -10.0), (50.0, 10.0)),
        sample_s_norm=0.5,
        intervals=(witness_interval,),
        selected_interval_rank=0,
        selected_interval_start_s=3.5,
        selected_interval_end_s=4.5,
        exclusive_interval=True,
        stability_score=1.0,
        neighbor_match_count=2,
        axis_vector=(0.0, 1.0),
    )
    identity = CorridorIdentity(
        segment_id="seg_fallback",
        state="witness_based",
        reason="witness_selected",
        risk_flags=tuple(),
        witness_interval_rank=0,
        prior_supported=False,
    )
    src_slot = SlotInterval(
        segment_id="seg_fallback",
        endpoint_tag="src",
        xsec_nodeid=10,
        xsec_coords=((0.0, -10.0), (0.0, 10.0)),
        interval=CorridorInterval(
            start_s=10.8,
            end_s=11.2,
            center_s=11.0,
            length_m=0.4,
            rank=0,
            geometry_coords=((0.0, 0.8), (0.0, 1.2)),
        ),
        resolved=True,
        method="rank",
        reason="synthetic",
        interval_count=1,
    )
    dst_slot = SlotInterval(
        segment_id="seg_fallback",
        endpoint_tag="dst",
        xsec_nodeid=20,
        xsec_coords=((100.0, -10.0), (100.0, 10.0)),
        interval=CorridorInterval(
            start_s=10.8,
            end_s=11.2,
            center_s=11.0,
            length_m=0.4,
            rank=0,
            geometry_coords=((100.0, 0.8), (100.0, 1.2)),
        ),
        resolved=True,
        method="rank",
        reason="synthetic",
        interval_count=1,
    )
    inputs = PatchInputs(
        patch_id="synthetic_fallback",
        patch_dir=Path("synthetic_fallback"),
        metric_crs="EPSG:3857",
        intersection_lines=tuple(),
        lane_boundaries_metric=tuple(),
        trajectories=tuple(),
        drivezone_zone_metric=Polygon([(-5.0, 0.0), (105.0, 0.0), (105.0, 2.0), (-5.0, 2.0)]),
        divstrip_zone_metric=None,
        road_prior_path=None,
        input_summary={},
    )

    road, result = _build_final_road(
        patch_id="synthetic_fallback",
        segment=segment,
        identity=identity,
        witness=witness,
        src_slot=src_slot,
        dst_slot=dst_slot,
        inputs=inputs,
        prior_roads=[],
        params=dict(DEFAULT_PARAMS),
    )

    assert road is not None
    assert result["reason"] == "built"
    assert result["shape_ref_mode"] == "witness_reference_projected_anchored"
    assert len(result["candidate_attempts"]) == 1
    assert result["candidate_attempts"][0]["mode"] == "witness_reference_projected_anchored"
    assert float(result["candidate_attempts"][0]["drivezone_ratio"]) >= float(DEFAULT_PARAMS["ROAD_MIN_DRIVEZONE_RATIO"])
    assert road.line_coords == ((0.0, 1.0), (50.0, 1.0), (100.0, 1.0))


def test_t05v2_build_slot_prefers_support_anchor_interval_over_reference_interval() -> None:
    segment = Segment(
        segment_id="seg_slot_anchor",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((-10.0, -7.0), (10.0, -7.0)),
        candidate_ids=("cand_1",),
        source_modes=("traj",),
        support_traj_ids=("traj_1",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=True,
        formation_reason="traj_supported_cluster",
        length_m=20.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_slot_anchor",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
    )
    identity = CorridorIdentity(
        segment_id="seg_slot_anchor",
        state="prior_based",
        reason="prior_reference_available",
        risk_flags=tuple(),
        witness_interval_rank=None,
        prior_supported=True,
    )
    xsec = BaseCrossSection(
        nodeid=10,
        geometry_coords=((0.0, -10.0), (0.0, 10.0)),
        properties={},
    )
    surface = Polygon([(-1.0, -8.0), (1.0, -8.0), (1.0, -6.0), (-1.0, -6.0)]).union(
        Polygon([(-1.0, 2.0), (1.0, 2.0), (1.0, 4.0), (-1.0, 4.0)])
    )
    inputs = PatchInputs(
        patch_id="slot_anchor_patch",
        patch_dir=Path("."),
        metric_crs="EPSG:3857",
        intersection_lines=tuple(),
        lane_boundaries_metric=tuple(),
        trajectories=tuple(),
        drivezone_zone_metric=surface,
        divstrip_zone_metric=None,
        road_prior_path=None,
        input_summary={},
    )
    slot = build_slot(
        segment=segment,
        witness=None,
        identity=identity,
        xsec=xsec,
        line=LineString([(-10.0, -7.0), (10.0, -7.0)]),
        inputs=inputs,
        params=dict(DEFAULT_PARAMS),
        endpoint_tag="src",
        drivable_surface=surface,
        arc_row={
            "support_anchor_src_coords": [0.0, 3.0],
            "support_full_xsec_crossing": True,
            "support_cluster_is_dominant": True,
            "stitched_support_available": False,
        },
    )

    assert slot.resolved is True
    assert slot.interval is not None
    assert slot.method == "selected_support_contains"
    assert slot.reason == "selected_support_anchor_on_interval"
    assert float(slot.interval.center_s) > 0.0


def test_t05v2_build_slot_prefers_trusted_support_anchor_over_witness_interval() -> None:
    segment = Segment(
        segment_id="seg_slot_trusted",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((-10.0, -7.0), (10.0, -7.0)),
        candidate_ids=("cand_1",),
        source_modes=("traj",),
        support_traj_ids=("traj_1",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=False,
        formation_reason="traj_supported_cluster",
        length_m=20.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_slot_trusted",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
    )
    identity = CorridorIdentity(
        segment_id="seg_slot_trusted",
        state="witness_based",
        reason="witness_selected",
        risk_flags=tuple(),
        witness_interval_rank=0,
        prior_supported=False,
    )
    xsec = BaseCrossSection(
        nodeid=10,
        geometry_coords=((0.0, -10.0), (0.0, 10.0)),
        properties={},
    )
    witness = CorridorWitness(
        segment_id="seg_slot_trusted",
        status="resolved",
        reason="test_witness",
        line_coords=((-10.0, -7.0), (10.0, -7.0)),
        sample_s_norm=0.5,
        intervals=(
            CorridorInterval(
                start_s=1.0,
                end_s=3.0,
                center_s=2.0,
                length_m=2.0,
                rank=0,
                geometry_coords=((0.0, -9.0), (0.0, -7.0)),
            ),
            CorridorInterval(
                start_s=11.0,
                end_s=13.0,
                center_s=12.0,
                length_m=2.0,
                rank=1,
                geometry_coords=((0.0, 1.0), (0.0, 3.0)),
            ),
        ),
        selected_interval_rank=0,
        selected_interval_start_s=1.0,
        selected_interval_end_s=3.0,
        exclusive_interval=False,
        stability_score=1.0,
        neighbor_match_count=2,
        axis_vector=(1.0, 0.0),
    )
    surface = Polygon([(-1.0, -8.0), (1.0, -8.0), (1.0, -6.0), (-1.0, -6.0)]).union(
        Polygon([(-1.0, 2.0), (1.0, 2.0), (1.0, 4.0), (-1.0, 4.0)])
    )
    inputs = PatchInputs(
        patch_id="slot_trusted_patch",
        patch_dir=Path("."),
        metric_crs="EPSG:3857",
        intersection_lines=tuple(),
        lane_boundaries_metric=tuple(),
        trajectories=tuple(),
        drivezone_zone_metric=surface,
        divstrip_zone_metric=None,
        road_prior_path=None,
        input_summary={},
    )
    slot = build_slot(
        segment=segment,
        witness=witness,
        identity=identity,
        xsec=xsec,
        line=LineString([(-10.0, -7.0), (10.0, -7.0)]),
        inputs=inputs,
        params=dict(DEFAULT_PARAMS),
        endpoint_tag="src",
        drivable_surface=surface,
        arc_row={
            "support_anchor_src_coords": [0.0, 3.0],
            "support_full_xsec_crossing": True,
            "support_cluster_is_dominant": True,
            "selected_support_interval_reference_trusted": True,
            "support_interval_reference_source": "selected_support",
            "stitched_support_available": False,
        },
    )

    assert slot.resolved is True
    assert slot.interval is not None
    assert slot.method == "selected_support_contains"
    assert slot.reason == "selected_support_anchor_on_interval"
    assert float(slot.interval.center_s) > 0.0


def test_t05v2_build_final_road_uses_support_reference_candidate_to_avoid_divstrip() -> None:
    segment = Segment(
        segment_id="seg_support_ref",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((0.0, 0.0), (50.0, 0.0), (100.0, 0.0)),
        candidate_ids=("cand_1",),
        source_modes=("traj",),
        support_traj_ids=("traj_1",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=False,
        formation_reason="arc_first_terminal_support",
        length_m=100.0,
        drivezone_ratio=1.0,
        crosses_divstrip=True,
        topology_arc_id="arc_support_ref",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
        same_pair_rank=1,
        kept_reason="",
    )
    witness_interval = CorridorInterval(
        start_s=0.5,
        end_s=1.5,
        center_s=1.0,
        length_m=1.0,
        rank=0,
        geometry_coords=((50.0, -0.5), (50.0, 0.5)),
    )
    witness = CorridorWitness(
        segment_id="seg_support_ref",
        status="selected",
        reason="witness_interval_selected",
        line_coords=((40.0, 0.0), (60.0, 0.0)),
        sample_s_norm=0.5,
        intervals=(witness_interval,),
        selected_interval_rank=0,
        selected_interval_start_s=0.5,
        selected_interval_end_s=1.5,
        exclusive_interval=True,
        stability_score=1.0,
        neighbor_match_count=2,
        axis_vector=(0.0, 1.0),
    )
    identity = CorridorIdentity(
        segment_id="seg_support_ref",
        state="witness_based",
        reason="witness_selected",
        risk_flags=tuple(),
        witness_interval_rank=0,
        prior_supported=False,
    )
    src_slot = SlotInterval(
        segment_id="seg_support_ref",
        endpoint_tag="src",
        xsec_nodeid=10,
        xsec_coords=((0.0, -10.0), (0.0, 10.0)),
        interval=CorridorInterval(
            start_s=12.5,
            end_s=13.5,
            center_s=13.0,
            length_m=1.0,
            rank=0,
            geometry_coords=((0.0, 2.5), (0.0, 3.5)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    dst_slot = SlotInterval(
        segment_id="seg_support_ref",
        endpoint_tag="dst",
        xsec_nodeid=20,
        xsec_coords=((100.0, -10.0), (100.0, 10.0)),
        interval=CorridorInterval(
            start_s=12.5,
            end_s=13.5,
            center_s=13.0,
            length_m=1.0,
            rank=0,
            geometry_coords=((100.0, 2.5), (100.0, 3.5)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    inputs = PatchInputs(
        patch_id="support_reference_case",
        patch_dir=Path("support_reference_case"),
        metric_crs="EPSG:3857",
        intersection_lines=tuple(),
        lane_boundaries_metric=tuple(),
        trajectories=tuple(),
        drivezone_zone_metric=Polygon([(-5.0, 2.0), (105.0, 2.0), (105.0, 4.0), (-5.0, 4.0)]),
        divstrip_zone_metric=Polygon([(45.0, -1.0), (55.0, -1.0), (55.0, 1.0), (45.0, 1.0)]),
        road_prior_path=None,
        input_summary={},
    )

    road, result = _build_final_road(
        patch_id="support_reference_case",
        segment=segment,
        identity=identity,
        witness=witness,
        src_slot=src_slot,
        dst_slot=dst_slot,
        inputs=inputs,
        prior_roads=[],
        params=dict(DEFAULT_PARAMS),
        arc_row={"support_reference_coords": [[0.0, 3.0], [50.0, 3.0], [100.0, 3.0]]},
        divstrip_buffer=Polygon([(45.0, -1.5), (55.0, -1.5), (55.0, 1.5), (45.0, 1.5)]),
    )

    assert road is not None
    assert result["reason"] == "built"
    assert (
        result["shape_ref_mode"] == "traj_support_slot_anchored"
        or "safe_envelope" in str(result["shape_ref_mode"])
    )
    assert result["candidate_attempts"][0]["mode"] == "witness_reference_projected_anchored"
    assert float(result["candidate_attempts"][0]["divstrip_overlap_ratio"]) > 0.0
    assert all(attempt["mode"] != "traj_support_slot_anchored" or float(attempt["drivezone_ratio"]) >= float(DEFAULT_PARAMS["ROAD_MIN_DRIVEZONE_RATIO"]) for attempt in result["candidate_attempts"])


def test_t05v2_build_final_road_prefers_trusted_support_reference_before_witness_reference() -> None:
    segment = Segment(
        segment_id="seg_support_preferred",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((0.0, 1.0), (50.0, 1.0), (100.0, 1.0)),
        candidate_ids=("cand_1",),
        source_modes=("traj",),
        support_traj_ids=("traj_1",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=False,
        formation_reason="arc_first_terminal_support",
        length_m=100.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_support_preferred",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
        same_pair_rank=1,
        kept_reason="",
    )
    witness_interval = CorridorInterval(
        start_s=0.5,
        end_s=1.5,
        center_s=1.0,
        length_m=1.0,
        rank=0,
        geometry_coords=((50.0, -0.5), (50.0, 0.5)),
    )
    witness = CorridorWitness(
        segment_id="seg_support_preferred",
        status="selected",
        reason="witness_interval_selected",
        line_coords=((50.0, -10.0), (50.0, 10.0)),
        sample_s_norm=0.5,
        intervals=(witness_interval,),
        selected_interval_rank=0,
        selected_interval_start_s=0.5,
        selected_interval_end_s=1.5,
        exclusive_interval=True,
        stability_score=1.0,
        neighbor_match_count=2,
        axis_vector=(0.0, 1.0),
    )
    identity = CorridorIdentity(
        segment_id="seg_support_preferred",
        state="witness_based",
        reason="witness_selected",
        risk_flags=tuple(),
        witness_interval_rank=0,
        prior_supported=False,
    )
    src_slot = SlotInterval(
        segment_id="seg_support_preferred",
        endpoint_tag="src",
        xsec_nodeid=10,
        xsec_coords=((0.0, -10.0), (0.0, 10.0)),
        interval=CorridorInterval(
            start_s=12.5,
            end_s=13.5,
            center_s=13.0,
            length_m=1.0,
            rank=0,
            geometry_coords=((0.0, 2.5), (0.0, 3.5)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    dst_slot = SlotInterval(
        segment_id="seg_support_preferred",
        endpoint_tag="dst",
        xsec_nodeid=20,
        xsec_coords=((100.0, -10.0), (100.0, 10.0)),
        interval=CorridorInterval(
            start_s=12.5,
            end_s=13.5,
            center_s=13.0,
            length_m=1.0,
            rank=0,
            geometry_coords=((100.0, 2.5), (100.0, 3.5)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    inputs = PatchInputs(
        patch_id="support_preferred_case",
        patch_dir=Path("support_preferred_case"),
        metric_crs="EPSG:3857",
        intersection_lines=tuple(),
        lane_boundaries_metric=tuple(),
        trajectories=tuple(),
        drivezone_zone_metric=Polygon([(-5.0, 0.0), (105.0, 0.0), (105.0, 4.0), (-5.0, 4.0)]),
        divstrip_zone_metric=None,
        road_prior_path=None,
        input_summary={},
    )

    road, result = _build_final_road(
        patch_id="support_preferred_case",
        segment=segment,
        identity=identity,
        witness=witness,
        src_slot=src_slot,
        dst_slot=dst_slot,
        inputs=inputs,
        prior_roads=[],
        params=dict(DEFAULT_PARAMS),
        arc_row={
            "support_reference_coords": [[0.0, 3.0], [50.0, 3.0], [100.0, 3.0]],
            "selected_support_interval_reference_trusted": True,
            "support_interval_reference_source": "selected_support",
            "stitched_support_interval_reference_trusted": False,
        },
    )

    assert road is not None
    assert result["reason"] == "built"
    assert result["shape_ref_mode"] == "selected_support_reference_projected_anchored"
    assert result["candidate_attempts"][0]["mode"] == "selected_support_reference_projected_anchored"
    assert road.line_coords == ((0.0, 3.0), (50.0, 3.0), (100.0, 3.0))


def test_t05v2_rcsdroad_trend_extended_candidate_line_uses_endpoint_trend() -> None:
    src_slot = SlotInterval(
        segment_id="seg_trend",
        endpoint_tag="src",
        xsec_nodeid=10,
        xsec_coords=((0.0, -10.0), (0.0, 10.0)),
        interval=CorridorInterval(
            start_s=0.0,
            end_s=20.0,
            center_s=10.0,
            length_m=20.0,
            rank=0,
            geometry_coords=((0.0, -10.0), (0.0, 10.0)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    dst_slot = SlotInterval(
        segment_id="seg_trend",
        endpoint_tag="dst",
        xsec_nodeid=20,
        xsec_coords=((100.0, -10.0), (100.0, 10.0)),
        interval=CorridorInterval(
            start_s=0.0,
            end_s=20.0,
            center_s=10.0,
            length_m=20.0,
            rank=0,
            geometry_coords=((100.0, -10.0), (100.0, 10.0)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    candidate = _rcsdroad_trend_extended_candidate_line(
        LineString([(10.0, 0.0), (50.0, 2.0), (90.0, 4.0)]),
        src_slot,
        dst_slot,
    )

    assert candidate is not None
    coords = list(candidate.coords)
    assert float(coords[0][0]) == pytest.approx(0.0)
    assert float(coords[0][1]) == pytest.approx(-0.5, abs=1e-6)
    assert float(coords[-1][0]) == pytest.approx(100.0)
    assert float(coords[-1][1]) == pytest.approx(4.5, abs=1e-6)


def test_t05v2_rcsdroad_fallback_base_line_prefers_prior_reference() -> None:
    segment = Segment(
        segment_id="seg_rcsd_prior",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((10.0, 0.0), (50.0, 8.0), (90.0, 16.0)),
        candidate_ids=("cand_prior",),
        source_modes=("traj",),
        support_traj_ids=("traj_prior",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=True,
        formation_reason="traj_supported_cluster",
        length_m=82.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_rcsd_prior",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
        same_pair_rank=1,
        kept_reason="",
    )
    prior_line = LineString([(10.0, 5.0), (50.0, 5.0), (90.0, 5.0)])
    base_line = _rcsdroad_fallback_base_line(
        segment=segment,
        arc_row=None,
        prior_roads=[SimpleNamespace(line=prior_line, snodeid=10, enodeid=20)],
    )

    assert base_line.equals(prior_line)


def test_t05v2_rcsdroad_fallback_base_line_prefers_topology_arc_line() -> None:
    segment = Segment(
        segment_id="seg_rcsd_arc",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((10.0, 0.0), (50.0, 8.0), (90.0, 16.0)),
        candidate_ids=("cand_arc",),
        source_modes=("traj",),
        support_traj_ids=("traj_arc",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=False,
        formation_reason="traj_supported_cluster",
        length_m=82.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_rcsd_arc",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
        same_pair_rank=1,
        kept_reason="",
    )
    base_line = _rcsdroad_fallback_base_line(
        segment=segment,
        arc_row={"line_coords": [[0.0, 4.0], [50.0, 4.0], [100.0, 4.0]]},
        prior_roads=[],
    )

    assert list(base_line.coords) == [(0.0, 4.0), (50.0, 4.0), (100.0, 4.0)]


def test_t05v2_build_final_road_uses_rcsdroad_trend_extension_as_last_fallback() -> None:
    segment = Segment(
        segment_id="seg_rcsd_fallback",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((10.0, 0.0), (50.0, 2.0), (90.0, 4.0)),
        candidate_ids=("cand_rcsd",),
        source_modes=("traj",),
        support_traj_ids=("traj_rcsd",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=False,
        formation_reason="traj_supported_cluster",
        length_m=80.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_rcsd_fallback",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
        same_pair_rank=1,
        kept_reason="",
    )
    witness = CorridorWitness(
        segment_id="seg_rcsd_fallback",
        status="selected",
        reason="witness_interval_selected",
        line_coords=((0.0, 6.0), (100.0, 6.0)),
        sample_s_norm=0.5,
        intervals=tuple(),
        selected_interval_rank=None,
        selected_interval_start_s=None,
        selected_interval_end_s=None,
        exclusive_interval=True,
        stability_score=1.0,
        neighbor_match_count=1,
        axis_vector=(0.0, 1.0),
    )
    identity = CorridorIdentity(
        segment_id="seg_rcsd_fallback",
        state="witness_based",
        reason="witness_selected",
        risk_flags=tuple(),
        witness_interval_rank=None,
        prior_supported=False,
    )
    src_slot = SlotInterval(
        segment_id="seg_rcsd_fallback",
        endpoint_tag="src",
        xsec_nodeid=10,
        xsec_coords=((0.0, -2.0), (0.0, 14.0)),
        interval=CorridorInterval(
            start_s=0.0,
            end_s=16.0,
            center_s=8.0,
            length_m=16.0,
            rank=0,
            geometry_coords=((0.0, -2.0), (0.0, 14.0)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    dst_slot = SlotInterval(
        segment_id="seg_rcsd_fallback",
        endpoint_tag="dst",
        xsec_nodeid=20,
        xsec_coords=((100.0, -2.0), (100.0, 14.0)),
        interval=CorridorInterval(
            start_s=0.0,
            end_s=16.0,
            center_s=8.0,
            length_m=16.0,
            rank=0,
            geometry_coords=((100.0, -2.0), (100.0, 14.0)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    trend_line = _rcsdroad_trend_extended_candidate_line(segment.geometry_metric(), src_slot, dst_slot)
    assert trend_line is not None
    inputs = PatchInputs(
        patch_id="rcsdroad_trend_case",
        patch_dir=Path("rcsdroad_trend_case"),
        metric_crs="EPSG:3857",
        intersection_lines=tuple(),
        lane_boundaries_metric=tuple(),
        trajectories=tuple(),
        drivezone_zone_metric=trend_line.buffer(0.4, cap_style=2, join_style=2),
        divstrip_zone_metric=Polygon(),
        road_prior_path=None,
        input_summary={},
    )
    params = dict(DEFAULT_PARAMS)
    params["ROAD_MIN_DRIVEZONE_RATIO"] = 0.98

    with (
        patch.object(_step5_road, "_surface_envelope_candidate_line", return_value=None),
        patch.object(_step5_road, "_append_side_constrained_candidates", return_value=None),
    ):
        road, result = _build_final_road(
            patch_id="rcsdroad_trend_case",
            segment=segment,
            identity=identity,
            witness=witness,
            src_slot=src_slot,
            dst_slot=dst_slot,
            inputs=inputs,
            prior_roads=[],
            params=params,
        )

    assert road is not None
    assert result["reason"] == "built"
    assert str(result["shape_ref_mode"]).startswith("rcsdroad_trend_extended")
    assert any(str(item["mode"]).startswith("rcsdroad_trend_extended") for item in result["candidate_attempts"])
    assert float(result["drivezone_ratio"]) >= 0.98


def test_t05v2_build_final_road_prefers_partial_support_trend_extension_for_gap_case() -> None:
    segment = Segment(
        segment_id="seg_gap_support_trend",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((0.0, 6.0), (50.0, 6.0), (100.0, 6.0)),
        candidate_ids=("cand_gap",),
        source_modes=("traj",),
        support_traj_ids=("traj_gap",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=True,
        formation_reason="arc_first_partial_support",
        length_m=100.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_gap_support",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
        topology_gap_decision="gap_enter_mainflow",
        topology_gap_reason="gap_should_enter_mainflow",
        same_pair_rank=1,
        kept_reason="",
    )
    witness = CorridorWitness(
        segment_id="seg_gap_support_trend",
        status="selected",
        reason="witness_interval_selected",
        line_coords=((0.0, 10.0), (100.0, 10.0)),
        sample_s_norm=0.5,
        intervals=tuple(),
        selected_interval_rank=None,
        selected_interval_start_s=None,
        selected_interval_end_s=None,
        exclusive_interval=True,
        stability_score=1.0,
        neighbor_match_count=1,
        axis_vector=(0.0, 1.0),
    )
    identity = CorridorIdentity(
        segment_id="seg_gap_support_trend",
        state="witness_based",
        reason="witness_selected",
        risk_flags=tuple(),
        witness_interval_rank=None,
        prior_supported=False,
    )
    src_slot = SlotInterval(
        segment_id="seg_gap_support_trend",
        endpoint_tag="src",
        xsec_nodeid=10,
        xsec_coords=((0.0, 0.0), (0.0, 10.0)),
        interval=CorridorInterval(
            start_s=0.0,
            end_s=10.0,
            center_s=5.0,
            length_m=10.0,
            rank=0,
            geometry_coords=((0.0, 0.0), (0.0, 10.0)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    dst_slot = SlotInterval(
        segment_id="seg_gap_support_trend",
        endpoint_tag="dst",
        xsec_nodeid=20,
        xsec_coords=((100.0, 0.0), (100.0, 10.0)),
        interval=CorridorInterval(
            start_s=0.0,
            end_s=10.0,
            center_s=5.0,
            length_m=10.0,
            rank=0,
            geometry_coords=((100.0, 0.0), (100.0, 10.0)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    support_reference = [[10.0, 4.8], [50.0, 5.0], [90.0, 5.2]]
    safe_surface = Polygon([(-5.0, 4.4), (105.0, 4.4), (105.0, 5.6), (-5.0, 5.6)])
    inputs = PatchInputs(
        patch_id="gap_support_trend_case",
        patch_dir=Path("gap_support_trend_case"),
        metric_crs="EPSG:3857",
        intersection_lines=tuple(),
        lane_boundaries_metric=tuple(),
        trajectories=tuple(),
        drivezone_zone_metric=safe_surface,
        divstrip_zone_metric=Polygon(),
        road_prior_path=None,
        input_summary={},
    )
    road, result = _build_final_road(
        patch_id="gap_support_trend_case",
        segment=segment,
        identity=identity,
        witness=witness,
        src_slot=src_slot,
        dst_slot=dst_slot,
        inputs=inputs,
        prior_roads=[],
        params=dict(DEFAULT_PARAMS),
        arc_row={
            "traj_support_type": "partial_arc_support",
            "support_full_xsec_crossing": False,
            "support_reference_coords": support_reference,
        },
    )

    assert road is not None
    assert result["reason"] == "built"
    assert str(result["shape_ref_mode"]).startswith("traj_support_trend_extended")


def test_t05v2_build_final_road_prefers_topology_arc_trend_for_gap_case() -> None:
    segment = Segment(
        segment_id="seg_gap_topology_arc",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((0.0, 6.0), (50.0, 6.0), (100.0, 6.0)),
        candidate_ids=("cand_gap_arc",),
        source_modes=("traj",),
        support_traj_ids=("traj_gap_arc",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=False,
        formation_reason="arc_first_partial_support",
        length_m=100.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_gap_topology_arc",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
        topology_gap_decision="gap_enter_mainflow",
        topology_gap_reason="gap_should_enter_mainflow",
        same_pair_rank=1,
        kept_reason="",
    )
    witness = CorridorWitness(
        segment_id="seg_gap_topology_arc",
        status="selected",
        reason="witness_interval_selected",
        line_coords=((0.0, 10.0), (100.0, 10.0)),
        sample_s_norm=0.5,
        intervals=tuple(),
        selected_interval_rank=None,
        selected_interval_start_s=None,
        selected_interval_end_s=None,
        exclusive_interval=True,
        stability_score=1.0,
        neighbor_match_count=1,
        axis_vector=(0.0, 1.0),
    )
    identity = CorridorIdentity(
        segment_id="seg_gap_topology_arc",
        state="witness_based",
        reason="witness_selected",
        risk_flags=tuple(),
        witness_interval_rank=None,
        prior_supported=False,
    )
    src_slot = SlotInterval(
        segment_id="seg_gap_topology_arc",
        endpoint_tag="src",
        xsec_nodeid=10,
        xsec_coords=((0.0, 0.0), (0.0, 10.0)),
        interval=CorridorInterval(
            start_s=0.0,
            end_s=10.0,
            center_s=5.0,
            length_m=10.0,
            rank=0,
            geometry_coords=((0.0, 0.0), (0.0, 10.0)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    dst_slot = SlotInterval(
        segment_id="seg_gap_topology_arc",
        endpoint_tag="dst",
        xsec_nodeid=20,
        xsec_coords=((100.0, 0.0), (100.0, 10.0)),
        interval=CorridorInterval(
            start_s=0.0,
            end_s=10.0,
            center_s=5.0,
            length_m=10.0,
            rank=0,
            geometry_coords=((100.0, 0.0), (100.0, 10.0)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    topology_arc_line = LineString([(0.0, 5.0), (50.0, 5.0), (100.0, 5.0)])
    inputs = PatchInputs(
        patch_id="gap_topology_arc_case",
        patch_dir=Path("gap_topology_arc_case"),
        metric_crs="EPSG:3857",
        intersection_lines=tuple(),
        lane_boundaries_metric=tuple(),
        trajectories=tuple(),
        drivezone_zone_metric=topology_arc_line.buffer(0.4, cap_style=2, join_style=2),
        divstrip_zone_metric=Polygon(),
        road_prior_path=None,
        input_summary={},
    )
    params = dict(DEFAULT_PARAMS)
    params["ROAD_MIN_DRIVEZONE_RATIO"] = 0.98

    with (
        patch.object(_step5_road, "_surface_envelope_candidate_line", return_value=None),
        patch.object(_step5_road, "_append_side_constrained_candidates", return_value=None),
    ):
        road, result = _build_final_road(
            patch_id="gap_topology_arc_case",
            segment=segment,
            identity=identity,
            witness=witness,
            src_slot=src_slot,
            dst_slot=dst_slot,
            inputs=inputs,
            prior_roads=[],
            params=params,
            arc_row={
                "traj_support_type": "partial_arc_support",
                "support_full_xsec_crossing": False,
                "support_reference_coords": [[0.0, 6.0], [50.0, 6.0], [100.0, 6.0]],
                "line_coords": [[0.0, 5.0], [50.0, 5.0], [100.0, 5.0]],
            },
        )

    assert road is not None
    assert result["reason"] == "built"
    assert str(result["shape_ref_mode"]).startswith("topology_arc_")


def test_t05v2_build_final_road_allows_same_pair_multi_arc_with_side_constrained_candidate() -> None:
    segment = Segment(
        segment_id="seg_multi_arc",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((0.0, 0.0), (50.0, 0.0), (100.0, 0.0)),
        candidate_ids=("cand_multi",),
        source_modes=("traj",),
        support_traj_ids=("traj_multi",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=True,
        formation_reason="same_pair_multi_arc_allowed",
        length_m=100.0,
        drivezone_ratio=1.0,
        crosses_divstrip=True,
        topology_arc_id="arc_multi_fallback",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=False,
        production_multi_arc_allowed=True,
        multi_arc_evidence_mode="fallback_based",
        multi_arc_structure_type="SAME_PAIR_MULTI_ARC",
        multi_arc_rule_reason="same_pair_multi_arc_dual_output_ready",
        same_pair_rank=2,
        kept_reason="same_pair_multi_arc_allowed",
    )
    witness = CorridorWitness(
        segment_id="seg_multi_arc",
        status="selected",
        reason="witness_interval_selected",
        line_coords=((0.0, 0.0), (50.0, 0.0), (100.0, 0.0)),
        sample_s_norm=0.5,
        intervals=tuple(),
        selected_interval_rank=None,
        selected_interval_start_s=None,
        selected_interval_end_s=None,
        exclusive_interval=True,
        stability_score=1.0,
        neighbor_match_count=1,
        axis_vector=(0.0, 1.0),
    )
    identity = CorridorIdentity(
        segment_id="seg_multi_arc",
        state="witness_based",
        reason="witness_selected",
        risk_flags=tuple(),
        witness_interval_rank=None,
        prior_supported=True,
    )
    src_slot = SlotInterval(
        segment_id="seg_multi_arc",
        endpoint_tag="src",
        xsec_nodeid=10,
        xsec_coords=((0.0, -10.0), (0.0, 10.0)),
        interval=CorridorInterval(
            start_s=12.5,
            end_s=13.5,
            center_s=13.0,
            length_m=1.0,
            rank=0,
            geometry_coords=((0.0, 2.5), (0.0, 3.5)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    dst_slot = SlotInterval(
        segment_id="seg_multi_arc",
        endpoint_tag="dst",
        xsec_nodeid=20,
        xsec_coords=((100.0, -10.0), (100.0, 10.0)),
        interval=CorridorInterval(
            start_s=12.5,
            end_s=13.5,
            center_s=13.0,
            length_m=1.0,
            rank=0,
            geometry_coords=((100.0, 2.5), (100.0, 3.5)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    inputs = PatchInputs(
        patch_id="same_pair_multi_arc_case",
        patch_dir=Path("same_pair_multi_arc_case"),
        metric_crs="EPSG:3857",
        intersection_lines=tuple(),
        lane_boundaries_metric=tuple(),
        trajectories=tuple(),
        drivezone_zone_metric=Polygon([(-5.0, 2.0), (105.0, 2.0), (105.0, 4.5), (-5.0, 4.5)]),
        divstrip_zone_metric=Polygon([(45.0, -1.0), (55.0, -1.0), (55.0, 1.0), (45.0, 1.0)]),
        road_prior_path=None,
        input_summary={},
    )

    road, result = _build_final_road(
        patch_id="same_pair_multi_arc_case",
        segment=segment,
        identity=identity,
        witness=witness,
        src_slot=src_slot,
        dst_slot=dst_slot,
        inputs=inputs,
        prior_roads=[],
        params=dict(DEFAULT_PARAMS),
        divstrip_buffer=Polygon([(45.0, -1.5), (55.0, -1.5), (55.0, 1.5), (45.0, 1.5)]),
    )

    assert road is not None
    assert result["reason"] == "built"
    assert bool(result["production_multi_arc_allowed"]) is True
    assert result["multi_arc_evidence_mode"] == "fallback_based"
    assert any(
        ("side_constrained" in str(item["mode"])) or ("safe_envelope" in str(item["mode"]))
        for item in result["candidate_attempts"]
    )
    assert ("side_constrained" in str(result["shape_ref_mode"])) or ("safe_envelope" in str(result["shape_ref_mode"]))


def test_t05v2_step2_bridge_chain_cannot_become_production_arc(tmp_path: Path) -> None:
    patch_id = "bridge_pair_scoped_retain"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -5.0), (0.0, 5.0)], {"nodeid": 10}),
            _line_feature([(50.0, -5.0), (50.0, 5.0)], {"nodeid": 20}),
            _line_feature([(100.0, -5.0), (100.0, 5.0)], {"nodeid": 30}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -6.0), (105.0, -6.0), (105.0, 6.0), (-5.0, 6.0)])], "EPSG:3857")
    road_fc = _fc(
        [
            _line_feature([(0.0, 0.0), (50.0, 0.0)], {"snodeid": 10, "enodeid": 20}),
            _line_feature([(50.0, 0.0), (100.0, 0.0)], {"snodeid": 20, "enodeid": 30}),
        ],
        "EPSG:3857",
    )
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=[[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_stage(stage="step1_input_frame", data_root=data_root, patch_id=patch_id, run_id="run_bridge_retain", out_root=out_root)
    run_stage(
        stage="step2_segment",
        data_root=data_root,
        patch_id=patch_id,
        run_id="run_bridge_retain",
        out_root=out_root,
        params={
            "STEP2_PAIR_SCOPED_BRIDGE_RETAIN_ENABLE": 1,
            "STEP2_PAIR_SCOPED_BRIDGE_RETAIN_PAIR_IDS": "10:30",
        },
    )
    patch_dir = out_root / "run_bridge_retain" / "patches" / patch_id
    segments_payload = _read_json(patch_dir / "step2" / "segments.json")
    assert not any(int(item["src_nodeid"]) == 10 and int(item["dst_nodeid"]) == 30 for item in segments_payload["segments"])
    excluded = [
        item
        for item in segments_payload["excluded_candidates"]
        if int(item["src_nodeid"]) == 10 and int(item["dst_nodeid"]) == 30
    ]
    assert excluded
    assert {str(item["reason"]) for item in excluded} == {"synthetic_arc_not_allowed"}
    assert {str(item["stage"]) for item in excluded} == {"bridge_retain_gate"}
    assert {bool(item["bridge_chain_exists"]) for item in excluded} == {True}
    assert {bool(item["bridge_chain_unique"]) for item in excluded} == {True}
    assert {tuple(item["bridge_chain_nodes"]) for item in excluded} == {(20,)}
    topology_debug = _read_json(patch_dir / "debug" / "step2_topology_pairs.json")
    row = next(item for item in topology_debug["pairs"] if str(item["pair_id"]) == "10:30")
    assert bool(row["bridge_chain_exists"]) is True
    assert bool(row["bridge_chain_unique"]) is True
    assert row["bridge_chain_nodes"] == [20]
    assert row["bridge_diagnostic_reason"] == "unique_directed_bridge_candidate"


def test_t05v2_build_final_road_rejects_synthetic_arc_before_geometry() -> None:
    segment = Segment(
        segment_id="seg_bridge",
        src_nodeid=10,
        dst_nodeid=30,
        direction="src->dst",
        geometry_coords=((0.0, 0.0), (50.0, 0.0), (100.0, 0.0)),
        candidate_ids=("traj_01",),
        source_modes=("traj",),
        support_traj_ids=("traj_01",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=1,
        tolerated_other_xsec_crossings=1,
        prior_supported=False,
        formation_reason="traj_supported_cluster",
        length_m=100.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_is_direct_legal=False,
        topology_arc_is_unique=False,
        topology_arc_id="bridge_chain:10->20->30",
        topology_arc_source_type="bridge_chain_topology",
        topology_arc_edge_ids=(),
        topology_arc_node_path=(10, 20, 30),
        bridge_candidate_retained=False,
        bridge_chain_exists=True,
        bridge_chain_unique=True,
        bridge_chain_nodes=(10, 20, 30),
        bridge_chain_source="diagnostic_only",
        bridge_diagnostic_reason="unique_directed_bridge_candidate",
        bridge_decision_stage="bridge_retain_gate",
        bridge_decision_reason="synthetic_arc_not_allowed",
        same_pair_rank=1,
        kept_reason="",
    )
    identity = CorridorIdentity(
        segment_id="seg_bridge",
        state="unresolved",
        reason="generic_corridor_insufficient",
        risk_flags=tuple(),
        witness_interval_rank=None,
        prior_supported=False,
    )
    unresolved_slot = SlotInterval(
        segment_id="seg_bridge",
        endpoint_tag="src",
        xsec_nodeid=10,
        xsec_coords=((0.0, -10.0), (0.0, 10.0)),
        interval=None,
        resolved=False,
        method="unresolved",
        reason="unresolved",
        interval_count=0,
    )
    inputs = PatchInputs(
        patch_id="bridge_unresolved",
        patch_dir=Path("bridge_unresolved"),
        metric_crs="EPSG:3857",
        intersection_lines=tuple(),
        lane_boundaries_metric=tuple(),
        trajectories=tuple(),
        drivezone_zone_metric=Polygon([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)]),
        divstrip_zone_metric=None,
        road_prior_path=None,
        input_summary={},
    )

    road, result = _build_final_road(
        patch_id="bridge_unresolved",
        segment=segment,
        identity=identity,
        witness=None,
        src_slot=unresolved_slot,
        dst_slot=unresolved_slot,
        inputs=inputs,
        prior_roads=[],
        params=dict(DEFAULT_PARAMS),
    )

    assert road is None
    assert result["reason"] == "final_gate_synthetic_arc_not_allowed"
    assert result["reject_stage"] == "final_build_gate"
    assert (
        _classify_segment_outcome(
            identity=identity,
            src_slot=unresolved_slot,
            dst_slot=unresolved_slot,
            build_result=result,
            road=road,
        )
        == "arc_legality_rejected"
    )


def test_t05v2_build_full_legal_arc_registry_marks_blocked_diagnostic_only() -> None:
    topology = {
        "pair_arcs": {
            (791871, 37687913): [
                {
                    "arc_id": "arc_791871_37687913_1",
                    "source": "direct_topology_arc",
                    "node_path": [791871, 37687913],
                    "edge_ids": ["edge_a"],
                    "line_coords": [(0.0, 0.0), (10.0, 0.0)],
                    "chain_len": 1,
                }
            ]
        }
    }
    registry = build_full_legal_arc_registry(
        topology=topology,
        selected_segments=[],
        blocked_pair_bridge_audit=[
            {
                "pair_id": "791871:37687913",
                "reject_stage": "pairing_filter",
                "reject_reason": "non_adjacent_pair_blocked",
                "bridge_classification": "topology_gap_unresolved",
            }
        ],
    )
    row = registry["rows"][0]
    assert bool(row["is_direct_legal"]) is True
    assert bool(row["is_unique"]) is True
    assert bool(row["blocked_diagnostic_only"]) is True
    assert bool(row["entered_main_flow"]) is False
    assert row["unbuilt_stage"] == "hard_blocked"
    assert row["unbuilt_reason"] == "topology_gap_unresolved"


def test_t05v2_build_final_road_rejects_blocked_diagnostic_only() -> None:
    segment = Segment(
        segment_id="seg_blocked",
        src_nodeid=791871,
        dst_nodeid=37687913,
        direction="src->dst",
        geometry_coords=((0.0, 0.0), (100.0, 0.0)),
        candidate_ids=("arc::blocked",),
        source_modes=("traj",),
        support_traj_ids=("traj_01",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=False,
        formation_reason="arc_first_terminal_support",
        length_m=100.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_791871_37687913_1",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
        blocked_diagnostic_only=True,
    )
    identity = CorridorIdentity(
        segment_id="seg_blocked",
        state="witness_based",
        reason="terminal_crossing_support",
        risk_flags=tuple(),
        witness_interval_rank=0,
        prior_supported=False,
    )
    slot = SlotInterval(
        segment_id="seg_blocked",
        endpoint_tag="src",
        xsec_nodeid=791871,
        xsec_coords=((0.0, -10.0), (0.0, 10.0)),
        interval=CorridorInterval(
            start_s=9.0,
            end_s=11.0,
            center_s=10.0,
            length_m=2.0,
            rank=0,
            geometry_coords=((0.0, -1.0), (0.0, 1.0)),
        ),
        resolved=True,
        method="selected",
        reason="resolved",
        interval_count=1,
    )
    witness = CorridorWitness(
        segment_id="seg_blocked",
        status="selected",
        reason="stable_exclusive_interval",
        line_coords=((50.0, -2.0), (50.0, 2.0)),
        sample_s_norm=0.5,
        intervals=(slot.interval,),
        selected_interval_rank=0,
        selected_interval_start_s=9.0,
        selected_interval_end_s=11.0,
        exclusive_interval=True,
        stability_score=1.0,
        neighbor_match_count=2,
        axis_vector=(0.0, 1.0),
    )
    inputs = PatchInputs(
        patch_id="blocked_gate",
        patch_dir=Path("blocked_gate"),
        metric_crs="EPSG:3857",
        intersection_lines=tuple(),
        lane_boundaries_metric=tuple(),
        trajectories=tuple(),
        drivezone_zone_metric=Polygon([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)]),
        divstrip_zone_metric=None,
        road_prior_path=None,
        input_summary={},
    )

    road, result = _build_final_road(
        patch_id="blocked_gate",
        segment=segment,
        identity=identity,
        witness=witness,
        src_slot=slot,
        dst_slot=slot,
        inputs=inputs,
        prior_roads=[],
        params=dict(DEFAULT_PARAMS),
    )

    assert road is None
    assert result["reason"] == "final_gate_blocked_diagnostic_only"
    assert result["reject_stage"] == "final_build_gate"


def test_t05v2_corridor_identity_aggregates_within_same_legal_arc() -> None:
    segment_a = Segment(
        segment_id="seg_arc_a",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((0.0, 0.0), (20.0, 0.0)),
        candidate_ids=("cand_a",),
        source_modes=("traj",),
        support_traj_ids=("traj_a",),
        support_count=2,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=False,
        formation_reason="traj_supported_cluster",
        length_m=20.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_10_20_1",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
    )
    segment_b = Segment(
        segment_id="seg_arc_b",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((0.0, 0.5), (20.0, 0.5)),
        candidate_ids=("cand_b",),
        source_modes=("traj",),
        support_traj_ids=("traj_b",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.5,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=False,
        formation_reason="traj_supported_cluster",
        length_m=20.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_10_20_1",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
    )
    selected_interval = CorridorInterval(
        start_s=9.0,
        end_s=11.0,
        center_s=10.0,
        length_m=2.0,
        rank=0,
        geometry_coords=((10.0, -1.0), (10.0, 1.0)),
    )
    witness_a = CorridorWitness(
        segment_id="seg_arc_a",
        status="selected",
        reason="stable_exclusive_interval",
        line_coords=((10.0, -3.0), (10.0, 3.0)),
        sample_s_norm=0.5,
        intervals=(selected_interval,),
        selected_interval_rank=0,
        selected_interval_start_s=9.0,
        selected_interval_end_s=11.0,
        exclusive_interval=True,
        stability_score=1.0,
        neighbor_match_count=2,
        axis_vector=(0.0, 1.0),
    )
    witness_b = CorridorWitness(
        segment_id="seg_arc_b",
        status="insufficient",
        reason="witness_missing",
        line_coords=((10.0, -3.0), (10.0, 3.0)),
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

    identities, registry = build_corridor_identities(
        segments=[segment_a, segment_b],
        witnesses=[witness_a, witness_b],
        prior_roads=[],
    )

    assert len(registry) == 1
    assert registry[0]["corridor_identity"] == "witness_based"
    assert int(registry[0]["segment_count"]) == 2
    by_segment = {item.segment_id: item for item in identities}
    assert by_segment["seg_arc_a"].state == "witness_based"
    assert by_segment["seg_arc_b"].state == "witness_based"
    assert by_segment["seg_arc_b"].reason == "stable_same_arc_witness"


def test_t05v2_corridor_identity_prior_fallback_does_not_cross_arc() -> None:
    segment_a = Segment(
        segment_id="seg_prior_a",
        src_nodeid=10,
        dst_nodeid=20,
        direction="src->dst",
        geometry_coords=((0.0, 0.0), (20.0, 0.0)),
        candidate_ids=("cand_a",),
        source_modes=("traj",),
        support_traj_ids=("traj_a",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=False,
        formation_reason="traj_supported_cluster",
        length_m=20.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_10_20_1",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
    )
    segment_b = Segment(
        segment_id="seg_prior_b",
        src_nodeid=30,
        dst_nodeid=40,
        direction="src->dst",
        geometry_coords=((0.0, 5.0), (20.0, 5.0)),
        candidate_ids=("cand_b",),
        source_modes=("traj",),
        support_traj_ids=("traj_b",),
        support_count=1,
        dedup_count=1,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=0,
        prior_supported=False,
        formation_reason="traj_supported_cluster",
        length_m=20.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
        topology_arc_id="arc_30_40_1",
        topology_arc_source_type="direct_topology_arc",
        topology_arc_is_direct_legal=True,
        topology_arc_is_unique=True,
    )
    witness_missing_a = CorridorWitness(
        segment_id="seg_prior_a",
        status="insufficient",
        reason="no_witness_candidates",
        line_coords=((10.0, -3.0), (10.0, 3.0)),
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
    witness_missing_b = CorridorWitness(
        segment_id="seg_prior_b",
        status="insufficient",
        reason="no_witness_candidates",
        line_coords=((10.0, 2.0), (10.0, 8.0)),
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
    prior_road = SimpleNamespace(line=LineString([(0.0, 0.0), (20.0, 0.0)]), snodeid=10, enodeid=20)

    identities, registry = build_corridor_identities(
        segments=[segment_a, segment_b],
        witnesses=[witness_missing_a, witness_missing_b],
        prior_roads=[prior_road],
    )

    assert len(registry) == 2
    registry_by_arc = {item["topology_arc_id"]: item for item in registry}
    assert registry_by_arc["arc_10_20_1"]["corridor_identity"] == "prior_based"
    assert registry_by_arc["arc_30_40_1"]["corridor_identity"] == "unresolved"
    by_segment = {item.segment_id: item for item in identities}
    assert by_segment["seg_prior_a"].state == "prior_based"
    assert by_segment["seg_prior_b"].state == "unresolved"
    assert by_segment["seg_prior_b"].reason == "no_same_arc_prior"


def test_t05v2_review_writes_arc_legality_bundle(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    simple_pairs = {
        "5417632690143239": [
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
        "5417632690143326": [
            "758869:5384392508835518",
            "5384392508835518:955482837631237043",
            "5384392508835518:1603093460035387302",
            "964818603820823078:758869",
            "1572513903999899080:758869",
        ],
    }
    for patch_id, pair_ids in simple_pairs.items():
        patch_dir = run_root / "patches" / patch_id
        _write_json(patch_dir / "metrics.json", {"patch_id": patch_id, "unresolved_segment_count": 0})
        _write_json(patch_dir / "gate.json", {"overall_pass": True, "hard_breakpoints": []})
        _write_json(
            patch_dir / "step2" / "segments.json",
            {
                "segments": [
                    {
                        "segment_id": f"{patch_id}_{idx}",
                        "src_nodeid": int(pair_id.split(":")[0]),
                        "dst_nodeid": int(pair_id.split(":")[1]),
                        "topology_arc_id": f"arc_{idx}",
                        "topology_arc_source_type": "direct_topology_arc",
                        "topology_arc_is_direct_legal": True,
                        "topology_arc_is_unique": True,
                        "bridge_chain_exists": False,
                        "bridge_chain_unique": False,
                        "bridge_chain_nodes": [],
                    }
                    for idx, pair_id in enumerate(pair_ids)
                ],
                "excluded_candidates": [],
            },
        )
        _write_json(
            patch_dir / "step6" / "final_roads.json",
            {
                "roads": [
                    {
                        "road_id": f"{patch_id}_{idx}",
                        "segment_id": f"{patch_id}_{idx}",
                        "src_nodeid": int(pair_id.split(":")[0]),
                        "dst_nodeid": int(pair_id.split(":")[1]),
                    }
                    for idx, pair_id in enumerate(pair_ids)
                ]
            },
        )

    complex_patch_dir = run_root / "patches" / "5417632623039346"
    _write_json(
        complex_patch_dir / "step2" / "segments.json",
        {
            "excluded_candidates": [
                {
                    "src_nodeid": 5384367610468452,
                    "dst_nodeid": 765141,
                    "stage": "semantic_hard_gate",
                    "reason": "trace_only_reachability",
                    "arc_source_type": "rcsdroad_trace",
                    "topology_arc_is_direct_legal": False,
                    "topology_arc_is_unique": False,
                    "bridge_chain_exists": False,
                    "bridge_chain_unique": False,
                    "bridge_chain_nodes": [],
                },
                {
                    "src_nodeid": 5384367610468452,
                    "dst_nodeid": 608638238,
                    "stage": "semantic_hard_gate",
                    "reason": "directed_path_not_supported",
                    "arc_source_type": "",
                    "topology_arc_is_direct_legal": False,
                    "topology_arc_is_unique": False,
                    "bridge_chain_exists": False,
                    "bridge_chain_unique": False,
                    "bridge_chain_nodes": [],
                },
                {
                    "src_nodeid": 5395717732638194,
                    "dst_nodeid": 37687913,
                    "stage": "bridge_retain_gate",
                    "reason": "synthetic_arc_not_allowed",
                    "arc_source_type": "",
                    "topology_arc_is_direct_legal": False,
                    "topology_arc_is_unique": False,
                    "bridge_chain_exists": True,
                    "bridge_chain_unique": True,
                    "bridge_chain_nodes": [29626540],
                },
            ],
            "segments": [
                {
                    "segment_id": "seg_ref",
                    "src_nodeid": 5395717732638194,
                    "dst_nodeid": 29626540,
                    "topology_arc_id": "arc_ref",
                    "topology_arc_source_type": "direct_topology_arc",
                    "topology_arc_is_direct_legal": True,
                    "topology_arc_is_unique": True,
                    "bridge_chain_exists": False,
                    "bridge_chain_unique": False,
                    "bridge_chain_nodes": [],
                }
            ],
        },
    )
    _write_json(
        complex_patch_dir / "step6" / "final_roads.json",
        {
            "roads": [
                {
                    "road_id": "complex_0",
                    "segment_id": "seg_ref",
                    "src_nodeid": 5395717732638194,
                    "dst_nodeid": 29626540,
                }
            ]
        },
    )
    _write_json(
        complex_patch_dir / "debug" / "step2_segment_should_not_exist.json",
        {
            "pairs": [
                {"src_nodeid": 5384367610468452, "dst_nodeid": 765141, "reason": "trace_only_reachability"},
                {"src_nodeid": 5384367610468452, "dst_nodeid": 608638238, "reason": "directed_path_not_supported"},
                {
                    "src_nodeid": 5395717732638194,
                    "dst_nodeid": 37687913,
                    "reason": "synthetic_arc_not_allowed",
                    "topology_arc_is_direct_legal": False,
                    "topology_arc_is_unique": False,
                    "bridge_chain_exists": True,
                    "bridge_chain_unique": True,
                    "bridge_chain_nodes": [29626540],
                },
            ]
        },
    )
    _write_json(
        complex_patch_dir / "debug" / "step2_topology_pairs.json",
        {
            "pairs": [
                {
                    "src_nodeid": 5384367610468452,
                    "dst_nodeid": 765141,
                    "pair_id": "5384367610468452:765141",
                    "topology_sources": ["rcsdroad_trace"],
                    "arc_source_type": "rcsdroad_trace",
                    "topology_paths": [{"node_path": [5384367610468452, 23287538, 765141]}],
                },
                {
                    "src_nodeid": 791871,
                    "dst_nodeid": 37687913,
                    "pair_id": "791871:37687913",
                    "topology_sources": ["direct_topology_arc"],
                    "topology_arc_is_direct_legal": True,
                    "topology_arc_is_unique": True,
                    "bridge_chain_exists": False,
                    "bridge_chain_unique": False,
                    "bridge_chain_nodes": [],
                    "topology_paths": [{"node_path": [791871, 29626540, 37687913]}],
                },
                {
                    "src_nodeid": 55353246,
                    "dst_nodeid": 37687913,
                    "pair_id": "55353246:37687913",
                    "topology_sources": ["direct_topology_arc"],
                    "topology_arc_is_direct_legal": True,
                    "topology_arc_is_unique": True,
                    "bridge_chain_exists": False,
                    "bridge_chain_unique": False,
                    "bridge_chain_nodes": [],
                    "topology_paths": [{"node_path": [55353246, 29626540, 37687913]}],
                },
                {
                    "src_nodeid": 5395717732638194,
                    "dst_nodeid": 29626540,
                    "pair_id": "5395717732638194:29626540",
                    "topology_sources": ["direct_topology_arc"],
                    "arc_source_type": "direct_topology_arc",
                    "topology_arc_is_direct_legal": True,
                    "topology_arc_is_unique": True,
                    "bridge_chain_exists": False,
                    "bridge_chain_unique": False,
                    "bridge_chain_nodes": [],
                    "topology_paths": [{"node_path": [5395717732638194, 29626540]}],
                },
                {
                    "src_nodeid": 5395717732638194,
                    "dst_nodeid": 37687913,
                    "pair_id": "5395717732638194:37687913",
                    "topology_sources": [],
                    "topology_arc_is_direct_legal": False,
                    "topology_arc_is_unique": False,
                    "bridge_chain_exists": True,
                    "bridge_chain_unique": True,
                    "bridge_chain_nodes": [29626540],
                    "bridge_diagnostic_reason": "unique_directed_bridge_candidate",
                    "topology_paths": [],
                },
            ]
        },
    )
    _write_json(
        complex_patch_dir / "debug" / "step2_blocked_pair_bridge_audit.json",
        {
            "pairs": [
                {
                    "pair_id": "791871:37687913",
                    "reject_stage": "pairing_filter",
                    "reject_reason": "non_adjacent_pair_blocked",
                    "bridge_classification": "topology_gap_unresolved",
                 },
                {
                    "pair_id": "55353246:37687913",
                    "reject_stage": "pairing_filter",
                    "reject_reason": "non_adjacent_pair_blocked",
                    "bridge_classification": "topology_gap_unresolved",
                },
                {
                    "pair_id": "5395717732638194:37687913",
                    "reject_stage": "pairing_filter",
                    "reject_reason": "non_adjacent_pair_blocked",
                    "bridge_classification": "unique_directed_bridge_candidate",
                    "direct_bridge_nodeids": [29626540],
                },
            ]
        },
    )

    acceptance = evaluate_patch_acceptance(run_root, "5417632690143239")
    assert acceptance["target_count"] == 12
    assert bool(acceptance["acceptance_pass"]) is True

    output_root = tmp_path / "bundle"
    summary = write_arc_first_attach_evidence_review(run_root=run_root, output_root=output_root)
    assert (output_root / "acceptance_5417632690143239.json").exists()
    assert (output_root / "acceptance_5417632690143326.json").exists()
    assert (output_root / "full_legal_arc_registry.json").exists()
    assert (output_root / "legal_arc_funnel.json").exists()
    assert (output_root / "arc_evidence_attach_audit.json").exists()
    assert (output_root / "pair_decisions.json").exists()
    assert (output_root / "arc_legality_audit.json").exists()
    assert (output_root / "legal_arc_coverage.json").exists()
    assert (output_root / "simple_patch_acceptance.json").exists()
    assert (output_root / "strong_constraint_status.json").exists()
    assert (output_root / "simple_patch_regression.json").exists()
    assert (output_root / "runtime_breakdown.json").exists()
    assert (output_root / "runtime_before_after.md").exists()
    assert (output_root / "complex_patch_funnel_review.json").exists()
    assert (output_root / "complex_patch_legality_review.json").exists()
    assert (output_root / "complex_patch_coverage_review.json").exists()
    assert (output_root / "complex_patch_perf_review.json").exists()
    assert (output_root / "SUMMARY.md").exists()
    pair_decisions = _read_json(output_root / "pair_decisions.json")
    target = next(item for item in pair_decisions["pairs"] if str(item["pair"]) == "5395717732638194:37687913")
    assert target["reject_reason"] == "synthetic_arc_not_allowed"
    assert bool(target["built_final_road"]) is False
    reference = next(item for item in pair_decisions["pairs"] if str(item["pair"]) == "5395717732638194:29626540")
    assert bool(reference["built_final_road"]) is True
    audit = _read_json(output_root / "arc_legality_audit.json")
    assert bool(audit["summary"]["all_built_roads_direct_unique"]) is True
    assert int(audit["summary"]["bad_built_arc_count"]) == 0
    assert bool(audit["summary"]["built_all_direct_unique"]) is True
    assert bool(audit["summary"]["audit_summary_inconsistent"]) is False
    assert bool(audit["summary"]["synthetic_arc_in_production"]) is False
    assert bool(summary["complex_patch_legality_review"]["target_pair_correctly_blocked"]) is True
    coverage = _read_json(output_root / "legal_arc_coverage.json")
    complex_row = next(item for item in coverage["patches"] if str(item["patch_id"]) == "5417632623039346")
    assert int(complex_row["legal_arc_total"]) == 1
    assert int(complex_row["legal_arc_built"]) == 1
    runtime_breakdown = _read_json(output_root / "runtime_breakdown.json")
    assert "patches" in runtime_breakdown
    assert "review_runtime_ms" in runtime_breakdown
    perf_review = _read_json(output_root / "complex_patch_perf_review.json")
    assert "runtime" in perf_review


def test_t05v2_write_legal_arc_coverage_review_outputs_new_bundle(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    patch_dir = run_root / "patches" / "5417632690143239"
    _write_json(patch_dir / "metrics.json", {"patch_id": "5417632690143239", "unresolved_segment_count": 0, "segments": []})
    _write_json(patch_dir / "gate.json", {"overall_pass": True, "hard_breakpoints": []})
    _write_json(
        patch_dir / "step2" / "segments.json",
        {
            "segments": [
                {
                    "segment_id": "seg_a",
                    "src_nodeid": 10,
                    "dst_nodeid": 20,
                    "topology_arc_id": "arc_a",
                    "topology_arc_source_type": "direct_topology_arc",
                    "topology_arc_is_direct_legal": True,
                    "topology_arc_is_unique": True,
                }
            ],
            "excluded_candidates": [],
        },
    )
    _write_json(
        patch_dir / "step4" / "corridor_identity.json",
        {
            "legal_arc_registry": [
                {
                    "src": 10,
                    "dst": 20,
                    "pair": "10:20",
                    "topology_arc_id": "arc_a",
                    "topology_arc_is_direct_legal": True,
                    "topology_arc_is_unique": True,
                    "segment_ids": ["seg_a"],
                    "segment_count": 1,
                    "corridor_identity": "prior_based",
                    "corridor_reason": "same_arc_prior_fallback",
                }
            ]
        },
    )
    _write_json(
        patch_dir / "step6" / "final_roads.json",
        {"roads": [{"road_id": "road_a", "segment_id": "seg_a", "src_nodeid": 10, "dst_nodeid": 20}]},
    )
    for simple_patch_id in ("5417632690143326", "5417632623039346"):
        simple_dir = run_root / "patches" / simple_patch_id
        _write_json(simple_dir / "metrics.json", {"patch_id": simple_patch_id, "unresolved_segment_count": 0, "segments": []})
        _write_json(simple_dir / "gate.json", {"overall_pass": True, "hard_breakpoints": []})
        _write_json(simple_dir / "step2" / "segments.json", {"segments": [], "excluded_candidates": []})
        _write_json(simple_dir / "step4" / "corridor_identity.json", {"legal_arc_registry": []})
        _write_json(simple_dir / "step6" / "final_roads.json", {"roads": []})
        _write_json(simple_dir / "debug" / "step2_segment_should_not_exist.json", {"pairs": []})
        _write_json(simple_dir / "debug" / "step2_topology_pairs.json", {"pairs": []})
        _write_json(simple_dir / "debug" / "step2_blocked_pair_bridge_audit.json", {"pairs": []})

    output_root = tmp_path / "bundle_new"
    summary = write_legal_arc_coverage_review(run_root=run_root, output_root=output_root)
    assert (output_root / "full_legal_arc_registry.json").exists()
    assert (output_root / "legal_arc_funnel.json").exists()
    assert (output_root / "arc_evidence_attach_audit.json").exists()
    assert (output_root / "legal_arc_coverage.json").exists()
    assert (output_root / "simple_patch_acceptance.json").exists()
    assert (output_root / "complex_patch_funnel_review.json").exists()
    assert (output_root / "complex_patch_coverage_review.json").exists()
    assert "legal_arc_coverage" in summary


def test_t05v2_write_perf_opt_arc_first_review_outputs_runtime_bundle(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    for patch_id in ("5417632690143239", "5417632690143326", "5417632623039346"):
        patch_dir = run_root / "patches" / patch_id
        _write_json(patch_dir / "metrics.json", {"patch_id": patch_id, "unresolved_segment_count": 0, "segments": []})
        _write_json(patch_dir / "gate.json", {"overall_pass": True, "hard_breakpoints": []})
        _write_json(
            patch_dir / "step2" / "segments.json",
            {
                "segments": [
                    {
                        "segment_id": f"seg_{patch_id}",
                        "src_nodeid": 10,
                        "dst_nodeid": 20,
                        "topology_arc_id": f"arc_{patch_id}",
                        "topology_arc_source_type": "direct_topology_arc",
                        "topology_arc_is_direct_legal": True,
                        "topology_arc_is_unique": True,
                    }
                ],
                "excluded_candidates": [],
            },
        )
        _write_json(
            patch_dir / "step4" / "corridor_identity.json",
            {
                "legal_arc_registry": [
                    {
                        "src": 10,
                        "dst": 20,
                        "pair": "10:20",
                        "topology_arc_id": f"arc_{patch_id}",
                        "topology_arc_is_direct_legal": True,
                        "topology_arc_is_unique": True,
                        "segment_ids": [f"seg_{patch_id}"],
                        "segment_count": 1,
                        "corridor_identity": "witness_based",
                        "corridor_reason": "terminal_crossing_support",
                    }
                ]
            },
        )
        _write_json(
            patch_dir / "step3" / "step_state.json",
            {"ok": True, "duration_ms": 12.5, "runtime": {"trajectory_prefilter_time_ms": 3.0}},
        )
        _write_json(
            patch_dir / "step4" / "step_state.json",
            {"ok": True, "duration_ms": 5.0, "runtime": {"stage_runtime_ms": 5.0}},
        )
        _write_json(
            patch_dir / "step5" / "step_state.json",
            {"ok": True, "duration_ms": 4.0, "runtime": {"stage_runtime_ms": 4.0}},
        )
        _write_json(
            patch_dir / "step6" / "step_state.json",
            {"ok": True, "duration_ms": 6.0, "runtime": {"stage_runtime_ms": 6.0}},
        )
        _write_json(
            patch_dir / "step6" / "final_roads.json",
            {"roads": [{"road_id": f"road_{patch_id}", "segment_id": f"seg_{patch_id}", "src_nodeid": 10, "dst_nodeid": 20}]},
        )
        _write_json(
            patch_dir / "debug" / "arc_evidence_attach.json",
            {
                "rows": [
                    {
                        "pair": "10:20",
                        "topology_arc_id": f"arc_{patch_id}",
                        "traj_support_type": "partial_arc_support",
                        "prior_support_type": "no_support",
                        "corridor_identity": "witness_based",
                        "slot_status": "established",
                        "built_final_road": True,
                    }
                ]
            },
        )
        _write_json(patch_dir / "debug" / "step2_segment_should_not_exist.json", {"pairs": []})
        _write_json(patch_dir / "debug" / "step2_topology_pairs.json", {"pairs": []})
        _write_json(patch_dir / "debug" / "step2_blocked_pair_bridge_audit.json", {"pairs": []})

    output_root = tmp_path / "bundle_perf"
    summary = write_perf_opt_arc_first_review(run_root=run_root, output_root=output_root)
    assert (output_root / "runtime_breakdown.json").exists()
    assert (output_root / "runtime_before_after.md").exists()
    assert (output_root / "complex_patch_perf_review.json").exists()
    runtime = _read_json(output_root / "runtime_breakdown.json")
    assert float(runtime["review_runtime_ms"]) >= 0.0
    assert len(runtime["patches"]) == 3
    perf_review = _read_json(output_root / "complex_patch_perf_review.json")
    assert "runtime" in perf_review
    assert "runtime_breakdown" in summary


def test_t05v2_write_semantic_fix_after_perf_review_outputs_reports(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    patch_id = "5417632623039346"
    patch_dir = run_root / "patches" / patch_id
    _write_json(patch_dir / "metrics.json", {
        "patch_id": patch_id,
        "unresolved_segment_count": 0,
        "segments": [],
        "full_legal_arc_registry": [
            {
                "pair": "791871:37687913",
                "topology_arc_id": "arc_bad",
                "topology_arc_source_type": "direct_topology_arc",
                "is_direct_legal": True,
                "is_unique": True,
                "working_segment_id": "arcseg::arc_bad",
                "blocked_diagnostic_only": True,
                "blocked_diagnostic_reason": "topology_gap_unresolved",
                "entered_main_flow": False,
            },
            {
                "pair": "10:20",
                "topology_arc_id": "arc_good",
                "topology_arc_source_type": "direct_topology_arc",
                "is_direct_legal": True,
                "is_unique": True,
                "working_segment_id": "arcseg::arc_good",
                "entered_main_flow": True,
            },
        ],
    })
    _write_json(patch_dir / "gate.json", {"overall_pass": True, "hard_breakpoints": []})
    _write_json(patch_dir / "step2" / "segments.json", {"segments": [], "excluded_candidates": []})
    _write_json(
        patch_dir / "step4" / "corridor_identity.json",
        {
            "full_legal_arc_registry": [
                {
                    "pair": "791871:37687913",
                    "topology_arc_id": "arc_bad",
                    "topology_arc_source_type": "direct_topology_arc",
                    "topology_arc_is_direct_legal": True,
                    "topology_arc_is_unique": True,
                    "working_segment_id": "arcseg::arc_bad",
                    "blocked_diagnostic_only": True,
                    "blocked_diagnostic_reason": "topology_gap_unresolved",
                },
                {
                    "pair": "10:20",
                    "topology_arc_id": "arc_good",
                    "topology_arc_source_type": "direct_topology_arc",
                    "topology_arc_is_direct_legal": True,
                    "topology_arc_is_unique": True,
                    "working_segment_id": "arcseg::arc_good",
                },
            ]
        },
    )
    _write_json(
        patch_dir / "step6" / "final_roads.json",
        {"roads": [{"road_id": "road_bad", "segment_id": "arcseg::arc_bad", "src_nodeid": 791871, "dst_nodeid": 37687913}]},
    )
    _write_json(
        patch_dir / "debug" / "arc_evidence_attach.json",
        {"rows": [{"pair": "791871:37687913", "topology_arc_id": "arc_bad", "traj_support_type": "partial_arc_support"}]},
    )
    _write_json(
        patch_dir / "debug" / "step2_blocked_pair_bridge_audit.json",
        {"pairs": [{"pair_id": "791871:37687913", "bridge_classification": "topology_gap_unresolved"}]},
    )
    _write_json(patch_dir / "debug" / "step2_segment_should_not_exist.json", {"pairs": []})
    _write_json(patch_dir / "debug" / "step2_topology_pairs.json", {"pairs": []})
    for simple_patch_id in ("5417632690143239", "5417632690143326"):
        simple_dir = run_root / "patches" / simple_patch_id
        _write_json(simple_dir / "metrics.json", {"patch_id": simple_patch_id, "unresolved_segment_count": 0, "segments": []})
        _write_json(simple_dir / "gate.json", {"overall_pass": True, "hard_breakpoints": []})
        _write_json(simple_dir / "step2" / "segments.json", {"segments": [], "excluded_candidates": []})
        _write_json(simple_dir / "step4" / "corridor_identity.json", {"full_legal_arc_registry": []})
        _write_json(simple_dir / "step6" / "final_roads.json", {"roads": []})
        _write_json(simple_dir / "debug" / "step2_segment_should_not_exist.json", {"pairs": []})
        _write_json(simple_dir / "debug" / "step2_topology_pairs.json", {"pairs": []})
        _write_json(simple_dir / "debug" / "step2_blocked_pair_bridge_audit.json", {"pairs": []})

    output_root = tmp_path / "bundle_semantic"
    summary = write_semantic_fix_after_perf_review(run_root=run_root, output_root=output_root)
    assert (output_root / "semantic_regression_report.json").exists()
    assert (output_root / "bad_built_rootcause.json").exists()
    assert (output_root / "complex_patch_semantic_fix_review.json").exists()
    semantic = _read_json(output_root / "semantic_regression_report.json")
    assert bool(semantic["semantic_regression"]) is True
    assert "blocked_pairs_built" in semantic["semantic_regression_reasons"]
    rootcause = _read_json(output_root / "bad_built_rootcause.json")
    assert int(rootcause["bad_built_case_count"]) == 1
    assert "blocked_diagnostic_only_state_not_respected" in rootcause["cases"][0]["root_causes"]
    assert "semantic_regression_report" in summary


def test_t05v2_write_witness_vis_step5_recovery_review_outputs_visual_layers(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    patch_id = "5417632623039346"
    patch_dir = run_root / "patches" / patch_id
    _write_json(
        patch_dir / "metrics.json",
        {
            "patch_id": patch_id,
            "unresolved_segment_count": 0,
            "segments": [],
            "full_legal_arc_registry": [
                {
                    "patch_id": patch_id,
                    "src": 4625048846882874781,
                    "dst": 5384392508835506,
                    "pair": "4625048846882874781:5384392508835506",
                    "topology_arc_id": "arc_target",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "entered_main_flow": True,
                    "traj_support_type": "terminal_crossing_support",
                    "traj_support_ids": ["traj_01"],
                    "traj_support_segments": [
                        {
                            "traj_id": "traj_01",
                            "support_type": "terminal_crossing_support",
                            "segment_order": 0,
                            "is_stitched": False,
                            "support_score": 1.0,
                            "support_length_m": 100.0,
                            "source_span_start_idx": 0,
                            "source_span_end_idx": 4,
                            "line_coords": [[0.0, 3.0], [50.0, 3.0], [100.0, 3.0]],
                            "start_anchor_coords": [0.0, 3.0],
                            "end_anchor_coords": [100.0, 3.0],
                        }
                    ],
                    "support_reference_coords": [[0.0, 3.0], [50.0, 3.0], [100.0, 3.0]],
                    "support_anchor_src_coords": [0.0, 3.0],
                    "support_anchor_dst_coords": [100.0, 3.0],
                    "corridor_identity": "witness_based",
                    "slot_status": "resolved",
                    "built_final_road": False,
                    "unbuilt_stage": "step5_geometry_rejected",
                    "unbuilt_reason": "road_crosses_divstrip",
                    "working_segment_id": "arcseg::arc_target",
                },
                {
                    "patch_id": patch_id,
                    "src": 55353246,
                    "dst": 37687913,
                    "pair": "55353246:37687913",
                    "topology_arc_id": "arc_gap_a",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "entered_main_flow": False,
                    "blocked_diagnostic_reason": "topology_gap_unresolved",
                    "traj_support_type": "terminal_crossing_support",
                    "traj_support_ids": ["traj_gap_a"],
                    "traj_support_coverage_ratio": 0.82,
                    "prior_support_type": "prior_fallback_support",
                    "support_anchor_src_coords": [0.0, 2.0],
                    "support_anchor_dst_coords": [100.0, 2.0],
                    "node_path": [55353246, 29626540, 37687913],
                    "line_coords": [[0.0, 2.0], [100.0, 2.0]],
                },
                {
                    "patch_id": patch_id,
                    "src": 791871,
                    "dst": 37687913,
                    "pair": "791871:37687913",
                    "topology_arc_id": "arc_gap_b",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "entered_main_flow": False,
                    "blocked_diagnostic_reason": "topology_gap_unresolved",
                    "traj_support_type": "terminal_crossing_support",
                    "traj_support_ids": ["traj_gap_b"],
                    "traj_support_coverage_ratio": 0.79,
                    "prior_support_type": "prior_fallback_support",
                    "support_anchor_src_coords": [0.0, 4.0],
                    "support_anchor_dst_coords": [100.0, 4.0],
                    "node_path": [791871, 29626540, 37687913],
                    "line_coords": [[0.0, 4.0], [100.0, 4.0]],
                },
                {
                    "patch_id": patch_id,
                    "src": 760239,
                    "dst": 6963539359479390368,
                    "pair": "760239:6963539359479390368",
                    "topology_arc_id": "arc_gap_c",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "entered_main_flow": False,
                    "blocked_diagnostic_reason": "topology_gap_unresolved",
                    "traj_support_type": "terminal_crossing_support",
                    "traj_support_ids": ["traj_gap_c"],
                    "traj_support_coverage_ratio": 0.91,
                    "prior_support_type": "prior_fallback_support",
                    "support_anchor_src_coords": [0.0, 6.0],
                    "support_anchor_dst_coords": [100.0, 6.0],
                    "line_coords": [[0.0, 6.0], [100.0, 6.0]],
                },
                {
                    "patch_id": patch_id,
                    "src": 21779764,
                    "dst": 785642,
                    "pair": "21779764:785642",
                    "topology_arc_id": "arc_multi_1",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": False,
                    "direct_arc_count_for_pair": 2,
                    "built_final_road": True,
                    "traj_support_type": "terminal_crossing_support",
                    "corridor_identity": "witness_based",
                    "support_anchor_src_coords": [0.0, 8.0],
                    "support_anchor_dst_coords": [100.0, 8.0],
                    "line_coords": [[0.0, 8.0], [100.0, 8.0]],
                },
                {
                    "patch_id": patch_id,
                    "src": 21779764,
                    "dst": 785642,
                    "pair": "21779764:785642",
                    "topology_arc_id": "arc_multi_2",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": False,
                    "direct_arc_count_for_pair": 2,
                    "built_final_road": False,
                    "prior_support_type": "prior_fallback_support",
                    "drivezone_overlap_ratio": 0.72,
                    "divstrip_overlap_ratio": 0.0,
                    "support_anchor_src_coords": [0.0, 9.0],
                    "support_anchor_dst_coords": [100.0, 9.0],
                    "line_coords": [[0.0, 9.0], [100.0, 9.0]],
                },
                {
                    "patch_id": patch_id,
                    "src": 791873,
                    "dst": 791871,
                    "pair": "791873:791871",
                    "topology_arc_id": "arc_multi_3",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": False,
                    "direct_arc_count_for_pair": 2,
                    "built_final_road": False,
                    "traj_support_type": "terminal_crossing_support",
                    "corridor_identity": "witness_based",
                    "support_anchor_src_coords": [0.0, 10.0],
                    "support_anchor_dst_coords": [100.0, 10.0],
                    "line_coords": [[0.0, 10.0], [100.0, 10.0]],
                },
                {
                    "patch_id": patch_id,
                    "src": 791873,
                    "dst": 791871,
                    "pair": "791873:791871",
                    "topology_arc_id": "arc_multi_4",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": False,
                    "direct_arc_count_for_pair": 2,
                    "built_final_road": False,
                    "prior_support_type": "prior_fallback_support",
                    "drivezone_overlap_ratio": 0.68,
                    "divstrip_overlap_ratio": 0.0,
                    "support_anchor_src_coords": [0.0, 11.0],
                    "support_anchor_dst_coords": [100.0, 11.0],
                    "line_coords": [[0.0, 11.0], [100.0, 11.0]],
                },
            ],
        },
    )
    _write_json(patch_dir / "gate.json", {"overall_pass": True, "hard_breakpoints": []})
    _write_json(patch_dir / "step2" / "segments.json", {"segments": [], "excluded_candidates": []})
    _write_json(
        patch_dir / "step3" / "witness.json",
        {
            "witnesses": [
                CorridorWitness(
                    segment_id="arcseg::arc_target",
                    status="selected",
                    reason="stable_exclusive_interval",
                    line_coords=((50.0, 0.0), (50.0, 6.0)),
                    sample_s_norm=0.5,
                    intervals=(
                        CorridorInterval(
                            start_s=2.0,
                            end_s=4.0,
                            center_s=3.0,
                            length_m=2.0,
                            rank=0,
                            geometry_coords=((50.0, 2.0), (50.0, 4.0)),
                        ),
                    ),
                    selected_interval_rank=0,
                    selected_interval_start_s=2.0,
                    selected_interval_end_s=4.0,
                    exclusive_interval=True,
                    stability_score=1.0,
                    neighbor_match_count=2,
                    axis_vector=(0.0, 1.0),
                ).to_dict()
            ],
            "arc_evidence_attach_audit": [
                {
                    "pair": "55353246:37687913",
                    "src": 55353246,
                    "dst": 37687913,
                    "topology_arc_id": "arc_gap_a",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "blocked_diagnostic_reason": "topology_gap_unresolved",
                    "traj_support_type": "terminal_crossing_support",
                    "traj_support_ids": ["traj_gap_a"],
                    "traj_support_coverage_ratio": 0.82,
                    "prior_support_type": "prior_fallback_support",
                    "support_anchor_src_coords": [0.0, 2.0],
                    "support_anchor_dst_coords": [100.0, 2.0],
                    "node_path": [55353246, 29626540, 37687913],
                },
                {
                    "pair": "791871:37687913",
                    "src": 791871,
                    "dst": 37687913,
                    "topology_arc_id": "arc_gap_b",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "blocked_diagnostic_reason": "topology_gap_unresolved",
                    "traj_support_type": "terminal_crossing_support",
                    "traj_support_ids": ["traj_gap_b"],
                    "traj_support_coverage_ratio": 0.79,
                    "prior_support_type": "prior_fallback_support",
                    "support_anchor_src_coords": [0.0, 4.0],
                    "support_anchor_dst_coords": [100.0, 4.0],
                    "node_path": [791871, 29626540, 37687913],
                },
                {
                    "pair": "760239:6963539359479390368",
                    "src": 760239,
                    "dst": 6963539359479390368,
                    "topology_arc_id": "arc_gap_c",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "blocked_diagnostic_reason": "topology_gap_unresolved",
                    "traj_support_type": "terminal_crossing_support",
                    "traj_support_ids": ["traj_gap_c"],
                    "traj_support_coverage_ratio": 0.91,
                    "prior_support_type": "prior_fallback_support",
                    "support_anchor_src_coords": [0.0, 6.0],
                    "support_anchor_dst_coords": [100.0, 6.0],
                },
            ],
        },
    )
    _write_json(
        patch_dir / "step4" / "corridor_identity.json",
        {
            "working_segments": [
                Segment(
                    segment_id="arcseg::arc_target",
                    src_nodeid=4625048846882874781,
                    dst_nodeid=5384392508835506,
                    direction="src->dst",
                    geometry_coords=((0.0, 3.0), (50.0, 3.0), (100.0, 3.0)),
                    candidate_ids=("arc::arc_target",),
                    source_modes=("traj",),
                    support_traj_ids=("traj_01",),
                    support_count=1,
                    dedup_count=1,
                    representative_offset_m=0.0,
                    other_xsec_crossing_count=0,
                    tolerated_other_xsec_crossings=1,
                    prior_supported=False,
                    formation_reason="arc_first_terminal_support",
                    length_m=100.0,
                    drivezone_ratio=1.0,
                    crosses_divstrip=False,
                    topology_arc_id="arc_target",
                    topology_arc_source_type="direct_topology_arc",
                    topology_arc_is_direct_legal=True,
                    topology_arc_is_unique=True,
                    same_pair_rank=1,
                    kept_reason="arc_first_main_flow",
                ).to_dict()
            ],
            "corridor_identities": [
                CorridorIdentity(
                    segment_id="arcseg::arc_target",
                    state="witness_based",
                    reason="terminal_crossing_support",
                    risk_flags=tuple(),
                    witness_interval_rank=0,
                    prior_supported=False,
                ).to_dict()
            ],
            "full_legal_arc_registry": _read_json(patch_dir / "metrics.json")["full_legal_arc_registry"],
        },
    )
    _write_json(
        patch_dir / "step5" / "slot_mapping.json",
        {
            "slot_mapping": {
                "arcseg::arc_target": {
                    "src": SlotInterval(
                        segment_id="arcseg::arc_target",
                        endpoint_tag="src",
                        xsec_nodeid=4625048846882874781,
                        xsec_coords=((0.0, 0.0), (0.0, 6.0)),
                        interval=CorridorInterval(
                            start_s=2.5,
                            end_s=3.5,
                            center_s=3.0,
                            length_m=1.0,
                            rank=0,
                            geometry_coords=((0.0, 2.5), (0.0, 3.5)),
                        ),
                        resolved=True,
                        method="selected",
                        reason="resolved",
                        interval_count=1,
                    ).to_dict(),
                    "dst": SlotInterval(
                        segment_id="arcseg::arc_target",
                        endpoint_tag="dst",
                        xsec_nodeid=5384392508835506,
                        xsec_coords=((100.0, 0.0), (100.0, 6.0)),
                        interval=CorridorInterval(
                            start_s=2.5,
                            end_s=3.5,
                            center_s=3.0,
                            length_m=1.0,
                            rank=0,
                            geometry_coords=((100.0, 2.5), (100.0, 3.5)),
                        ),
                        resolved=True,
                        method="selected",
                        reason="resolved",
                        interval_count=1,
                    ).to_dict(),
                }
            }
        },
    )
    _write_json(
        patch_dir / "step6" / "final_roads.json",
        {"roads": [], "road_results": [{"segment_id": "arcseg::arc_target", "reason": "road_crosses_divstrip", "reject_stage": "", "shape_ref_mode": "witness_centerline"}]},
    )
    _write_json(patch_dir / "debug" / "step2_segment_should_not_exist.json", {"pairs": []})
    _write_json(patch_dir / "debug" / "step2_topology_pairs.json", {"pairs": []})
    _write_json(patch_dir / "debug" / "step2_blocked_pair_bridge_audit.json", {"pairs": []})

    for simple_patch_id in ("5417632690143239", "5417632690143326"):
        simple_dir = run_root / "patches" / simple_patch_id
        _write_json(simple_dir / "metrics.json", {"patch_id": simple_patch_id, "unresolved_segment_count": 0, "segments": [], "full_legal_arc_registry": []})
        _write_json(simple_dir / "gate.json", {"overall_pass": True, "hard_breakpoints": []})
        _write_json(simple_dir / "step2" / "segments.json", {"segments": [], "excluded_candidates": []})
        _write_json(simple_dir / "step4" / "corridor_identity.json", {"full_legal_arc_registry": []})
        _write_json(simple_dir / "step6" / "final_roads.json", {"roads": []})
        _write_json(simple_dir / "debug" / "step2_segment_should_not_exist.json", {"pairs": []})
        _write_json(simple_dir / "debug" / "step2_topology_pairs.json", {"pairs": []})
        _write_json(simple_dir / "debug" / "step2_blocked_pair_bridge_audit.json", {"pairs": []})

    output_root = tmp_path / "bundle_witness"
    summary = write_witness_vis_step5_recovery_review(run_root=run_root, output_root=output_root)

    assert (output_root / "arc_crosssection_chords.geojson").exists()
    assert (output_root / "arc_traj_support_segments.geojson").exists()
    assert (output_root / "arc_corridor_witness_lines.geojson").exists()
    assert (output_root / "arc_corridor_witness_polygons.geojson").exists()
    assert (output_root / "corridor_witness_review.json").exists()
    assert (output_root / "complex_patch_step5_recovery_review.json").exists()
    assert (output_root / "topology_gap_decision_review.json").exists()
    assert (output_root / "same_pair_multi_arc_observation.json").exists()
    assert (output_root / "strict_vs_visual_gap_summary.json").exists()
    chords = _read_json(output_root / "arc_crosssection_chords.geojson")
    assert any(str(item["properties"]["topology_arc_id"]) == "arc_target" for item in chords["features"])
    support_fc = _read_json(output_root / "arc_traj_support_segments.geojson")
    assert any(str(item["properties"]["topology_arc_id"]) == "arc_target" for item in support_fc["features"])
    recovery = _read_json(output_root / "complex_patch_step5_recovery_review.json")
    assert int(recovery["target_arc_count"]) >= 1
    assert recovery["rows"][0]["issue_classification"] in {"witness_layer_issue", "step5_issue_confirmed"}
    assert "corridor_witness_review" in summary
    gap_review = _read_json(output_root / "topology_gap_decision_review.json")
    assert int(gap_review["row_count"]) == 4
    gap_by_pair = {str(item["pair"]): item for item in gap_review["rows"]}
    assert gap_by_pair["760239:6963539359479390368"]["gap_classification"] == "gap_enter_mainflow"
    assert gap_by_pair["760239:6963539359479390368"]["gap_reason"] == "gap_should_enter_mainflow"
    assert gap_by_pair["55353246:37687913"]["gap_classification"] == "gap_enter_mainflow"
    assert gap_by_pair["55353246:37687913"]["gap_reason"] == "gap_should_enter_mainflow"
    assert gap_by_pair["791871:37687913"]["gap_classification"] == "gap_enter_mainflow"
    assert gap_by_pair["791871:37687913"]["gap_reason"] == "gap_should_enter_mainflow"
    same_pair_obs = _read_json(output_root / "same_pair_multi_arc_observation.json")
    obs_by_pair = {str(item["pair"]): item for item in same_pair_obs["rows"]}
    assert obs_by_pair["21779764:785642"]["pair_arc_count"] == 2
    assert obs_by_pair["21779764:785642"]["excluded_from_unique_denominator_reason"] == "same_pair_multi_arc"
    assert obs_by_pair["21779764:785642"]["has_built_sibling_arc"] is True
    assert obs_by_pair["791873:791871"]["pair_arc_count"] == 2
    strict_vs_visual = _read_json(output_root / "strict_vs_visual_gap_summary.json")
    assert strict_vs_visual["strict_coverage"]["total"] == 4
    assert strict_vs_visual["strict_coverage"]["built"] == 0
    assert "21779764:785642" in strict_vs_visual["visual_observation"]["observation_pairs"]

    output_root_wrap = tmp_path / "bundle_gap_cover"
    wrapped = write_topology_gap_controlled_cover_review(run_root=run_root, output_root=output_root_wrap)
    assert (output_root_wrap / "complex_patch_gap_cover_review.json").exists()
    assert "complex_patch_gap_cover_review" in wrapped

    output_root_obligation = tmp_path / "bundle_obligation"
    obligation = write_arc_obligation_closure_review(run_root=run_root, output_root=output_root_obligation)
    assert (output_root_obligation / "arc_obligation_registry.json").exists()
    assert (output_root_obligation / "arc_obligation_registry.csv").exists()
    assert (output_root_obligation / "competing_arc_review.json").exists()
    assert (output_root_obligation / "complex_patch_arc_obligation_review.json").exists()
    obligation_registry = _read_json(output_root_obligation / "arc_obligation_registry.json")
    obligation_by_pair = {str(item["pair"]): item for item in obligation_registry["rows"]}
    assert obligation_by_pair["760239:6963539359479390368"]["obligation_status"] == "must_build_now"
    assert obligation_by_pair["55353246:37687913"]["obligation_status"] == "must_build_now"
    assert obligation_by_pair["55353246:37687913"]["current_status"] == "blocked"
    assert obligation_by_pair["55353246:37687913"]["blocking_layer"] == "entry_gate"
    assert obligation_by_pair["55353246:37687913"]["blocking_reason"] == "gap_should_enter_mainflow"
    assert obligation_by_pair["791871:37687913"]["obligation_status"] == "must_build_now"
    assert obligation_by_pair["791871:37687913"]["blocking_reason"] == "gap_should_enter_mainflow"
    assert obligation_by_pair["21779764:785642"]["current_status"] == "observation_only"
    competing = _read_json(output_root_obligation / "competing_arc_review.json")
    competing_by_pair = {str(item["pair"]): item for item in competing["rows"]}
    assert "55353246:37687913" not in competing_by_pair
    assert "791871:37687913" not in competing_by_pair
    assert competing_by_pair["21779764:785642"]["root_cause_code"] == "multi_arc_no_selection_rule"
    assert "arc_obligation_registry" in obligation
    assert "competing_arc_review" in obligation

    output_root_alias = tmp_path / "bundle_alias"
    alias_summary = write_alias_fix_and_rootcause_push_review(run_root=run_root, output_root=output_root_alias)
    assert (output_root_alias / "alias_normalization_review.json").exists()
    assert (output_root_alias / "alias_normalization_review.csv").exists()
    assert (output_root_alias / "competing_arc_review.csv").exists()
    assert (output_root_alias / "complex_patch_alias_and_competing_review.json").exists()
    strict_vs_visual_alias = _read_json(output_root_alias / "strict_vs_visual_gap_summary.json")
    assert "alias_normalized_review" in strict_vs_visual_alias
    assert "alias_normalization_review" in alias_summary

    output_root_competing = tmp_path / "bundle_competing"
    competing_summary = write_competing_arc_closure_review(run_root=run_root, output_root=output_root_competing)
    assert (output_root_competing / "complex_patch_competing_arc_closure_review.json").exists()
    assert "complex_patch_competing_arc_closure_review" in competing_summary

    output_root_merge = tmp_path / "bundle_merge"
    merge_summary = write_merge_diverge_rules_review(run_root=run_root, output_root=output_root_merge)
    assert (output_root_merge / "arc_selection_structure.json").exists()
    assert (output_root_merge / "multi_arc_review.json").exists()
    assert (output_root_merge / "complex_patch_merge_diverge_rules_review.json").exists()
    arc_selection = _read_json(output_root_merge / "arc_selection_structure.json")
    merge_rows = {str(item["pair"]): item for item in arc_selection["rows"]}
    assert merge_rows["55353246:37687913"]["structure_type"] == "MERGE_MULTI_UPSTREAM"
    assert merge_rows["791871:37687913"]["structure_type"] == "MERGE_MULTI_UPSTREAM"
    multi_arc_review = _read_json(output_root_merge / "multi_arc_review.json")
    multi_arc_by_pair = {str(item["pair"]): item for item in multi_arc_review["rows"]}
    assert multi_arc_by_pair["21779764:785642"]["allow_multi_output"] is True
    assert multi_arc_by_pair["21779764:785642"]["witness_based_arc_ids"] == ["arc_multi_1"]
    assert multi_arc_by_pair["21779764:785642"]["fallback_based_arc_ids"] == ["arc_multi_2"]
    assert "complex_patch_merge_diverge_rules_review" in merge_summary

    merge_fix_review = build_merge_diverge_review(run_root, complex_patch_id="5417632623039346")
    merge_fix_by_pair = {str(item["pair"]): item for item in merge_fix_review["rows"]}
    assert merge_fix_by_pair["55353246:37687913"]["detected_structure_type"] == "MERGE_MULTI_UPSTREAM"
    assert merge_fix_by_pair["55353246:37687913"]["allow_multi_output"] is True
    assert merge_fix_by_pair["791871:37687913"]["detected_structure_type"] == "MERGE_MULTI_UPSTREAM"

    output_root_merge_fix = tmp_path / "bundle_merge_fix"
    merge_fix_summary = write_merge_diverge_fix_review(run_root=run_root, output_root=output_root_merge_fix)
    assert (output_root_merge_fix / "merge_diverge_review.json").exists()
    assert (output_root_merge_fix / "merge_diverge_review.csv").exists()
    assert (output_root_merge_fix / "complex_patch_merge_diverge_fix_review.json").exists()
    merge_fix_payload = _read_json(output_root_merge_fix / "merge_diverge_review.json")
    merge_fix_rows = {str(item["pair"]): item for item in merge_fix_payload["rows"]}
    assert merge_fix_rows["55353246:37687913"]["detected_structure_type"] == "MERGE_MULTI_UPSTREAM"
    assert merge_fix_rows["55353246:37687913"]["allow_multi_output"] is True
    assert merge_fix_rows["791871:37687913"]["detected_structure_type"] == "MERGE_MULTI_UPSTREAM"
    assert "complex_patch_merge_diverge_fix_review" in merge_fix_summary

    output_root_step5_finish = tmp_path / "bundle_step5_finish"
    step5_finish_summary = write_step5_finish_review(run_root=run_root, output_root=output_root_step5_finish)
    assert (output_root_step5_finish / "step5_target_review_55353246_37687913.json").exists()
    assert (output_root_step5_finish / "debug" / "step5_target_55353246_37687913_line.geojson").exists()
    assert (output_root_step5_finish / "debug" / "step5_target_55353246_37687913_overlap.geojson").exists()
    target_review = _read_json(output_root_step5_finish / "step5_target_review_55353246_37687913.json")
    assert target_review["pair"] == "55353246:37687913"
    assert "before" in target_review
    assert "after" in target_review
    assert "step5_target_review_55353246_37687913" in step5_finish_summary

    output_root_step5_plus = tmp_path / "bundle_step5_plus_multiarc"
    step5_plus_summary = write_step5_plus_multiarc_finish_review(run_root=run_root, output_root=output_root_step5_plus)
    assert (output_root_step5_plus / "step5_target_review_55353246_37687913.json").exists()
    assert (output_root_step5_plus / "same_pair_provisional_allow_review.json").exists()
    assert (output_root_step5_plus / "multi_arc_review.json").exists()
    assert (output_root_step5_plus / "multi_arc_review.csv").exists()
    assert (output_root_step5_plus / "complex_patch_step5_plus_multiarc_finish_review.json").exists()
    combined_multi_arc = _read_json(output_root_step5_plus / "multi_arc_review.json")
    combined_multi_arc_by_pair = {str(item["pair"]): item for item in combined_multi_arc["rows"]}
    assert combined_multi_arc_by_pair["21779764:785642"]["witness_based_arc_ids"] == ["arc_multi_1"]
    assert combined_multi_arc_by_pair["21779764:785642"]["fallback_based_arc_ids"] == ["arc_multi_2"]
    assert "complex_patch_step5_plus_multiarc_finish_review" in step5_plus_summary


def test_t05v2_classify_topology_gap_rows_returns_reasoned_decisions() -> None:
    rows = [
        {
            "pair": "55353246:37687913",
            "src": 55353246,
            "dst": 37687913,
            "is_direct_legal": True,
            "is_unique": True,
            "blocked_diagnostic_reason": "topology_gap_unresolved",
            "traj_support_type": "terminal_crossing_support",
            "traj_support_ids": ["traj_gap_a"],
            "traj_support_coverage_ratio": 0.82,
            "prior_support_type": "prior_fallback_support",
            "support_anchor_src_coords": [0.0, 2.0],
            "support_anchor_dst_coords": [100.0, 2.0],
            "node_path": [55353246, 310001, 37687913],
            "edge_ids": ["edge_gap_a_up", "edge_gap_a_down"],
            "line_coords": [[0.0, 2.0], [65.0, 2.0], [100.0, 0.0]],
        },
        {
            "pair": "791871:37687913",
            "src": 791871,
            "dst": 37687913,
            "is_direct_legal": True,
            "is_unique": True,
            "blocked_diagnostic_reason": "topology_gap_unresolved",
            "traj_support_type": "terminal_crossing_support",
            "traj_support_ids": ["traj_gap_b"],
            "traj_support_coverage_ratio": 0.79,
            "prior_support_type": "prior_fallback_support",
            "support_anchor_src_coords": [0.0, 4.0],
            "support_anchor_dst_coords": [100.0, 4.0],
            "node_path": [791871, 310002, 37687913],
            "edge_ids": ["edge_gap_b_up", "edge_gap_b_down"],
            "line_coords": [[0.0, 4.0], [68.0, 4.0], [100.0, 0.5]],
        },
        {
            "pair": "760239:6963539359479390368",
            "src": 760239,
            "dst": 6963539359479390368,
            "is_direct_legal": True,
            "is_unique": True,
            "blocked_diagnostic_reason": "topology_gap_unresolved",
            "traj_support_type": "terminal_crossing_support",
            "traj_support_ids": ["traj_gap_c"],
            "traj_support_coverage_ratio": 0.91,
            "prior_support_type": "prior_fallback_support",
            "support_anchor_src_coords": [0.0, 6.0],
            "support_anchor_dst_coords": [100.0, 6.0],
        },
    ]

    decisions = classify_topology_gap_rows(rows, params=dict(DEFAULT_PARAMS))

    assert decisions["760239:6963539359479390368"]["decision"] == "gap_enter_mainflow"
    assert decisions["760239:6963539359479390368"]["reason"] == "gap_should_enter_mainflow"
    assert decisions["55353246:37687913"]["decision"] == "gap_enter_mainflow"
    assert decisions["55353246:37687913"]["reason"] == "gap_should_enter_mainflow"
    assert decisions["55353246:37687913"]["arc_selection_allow_multi_output"] is True
    assert "shared_terminal_geometry_signal" in decisions["55353246:37687913"]["arc_selection_shared_downstream_signal"]
    assert decisions["791871:37687913"]["decision"] == "gap_enter_mainflow"
    assert decisions["791871:37687913"]["reason"] == "gap_should_enter_mainflow"
    assert decisions["791871:37687913"]["arc_selection_allow_multi_output"] is True


def test_t05v2_classify_topology_gap_rows_allows_small_terminal_gap_candidate() -> None:
    rows = [
        {
            "pair": "5389884430552920:2703260460721685999",
            "src": 5389884430552920,
            "dst": 2703260460721685999,
            "is_direct_legal": True,
            "is_unique": True,
            "blocked_diagnostic_reason": "topology_gap_unresolved",
            "traj_support_type": "partial_arc_support",
            "traj_support_ids": ["traj_gap_partial"],
            "traj_support_coverage_ratio": 0.86,
            "prior_support_type": "prior_fallback_support",
            "support_anchor_src_coords": [0.0, 2.0],
            "support_anchor_dst_coords": None,
            "selected_support_interval_reference_trusted": True,
            "support_interval_reference_source": "selected_support",
        }
    ]

    decisions = classify_topology_gap_rows(rows, params=dict(DEFAULT_PARAMS))

    assert decisions["5389884430552920:2703260460721685999"]["decision"] == "gap_enter_mainflow"
    assert decisions["5389884430552920:2703260460721685999"]["reason"] == "gap_small_terminal_gap_candidate"


def test_t05v2_competing_arc_closure_finalizes_obligation_statuses() -> None:
    topology_gap_review = {
        "patch_id": "5417632623039346",
        "rows": [
            {
                "patch_id": "5417632623039346",
                "pair": "55353246:37687913",
                "src": 55353246,
                "dst": 37687913,
                "topology_arc_id": "arc_gap_a",
                "gap_classification": "gap_ambiguous_need_more_constraints",
                "gap_reason": "gap_competing_arc_conflict",
                "traj_support_type": "terminal_crossing_support",
                "traj_support_count": 1,
                "traj_support_coverage_ratio": 0.82,
                "support_total_length_m": 92.0,
                "corridor_identity": "witness_based",
                "slot_status": "resolved",
                "built_final_road": False,
                "drivezone_overlap_ratio": 0.95,
                "divstrip_overlap_ratio": 0.0,
                "src_anchor_source": "support_anchor",
                "dst_anchor_source": "support_anchor",
            },
            {
                "patch_id": "5417632623039346",
                "pair": "791871:37687913",
                "src": 791871,
                "dst": 37687913,
                "topology_arc_id": "arc_gap_b",
                "gap_classification": "gap_ambiguous_need_more_constraints",
                "gap_reason": "gap_competing_arc_conflict",
                "traj_support_type": "terminal_crossing_support",
                "traj_support_count": 1,
                "traj_support_coverage_ratio": 0.79,
                "support_total_length_m": 60.0,
                "corridor_identity": "witness_based",
                "slot_status": "resolved",
                "built_final_road": False,
                "drivezone_overlap_ratio": 0.94,
                "divstrip_overlap_ratio": 0.0,
                "src_anchor_source": "support_anchor",
                "dst_anchor_source": "support_anchor",
            },
        ],
    }
    same_pair_multi_arc_observation = {"patch_id": "5417632623039346", "rows": []}

    obligation = build_arc_obligation_registry(
        complex_patch_id="5417632623039346",
        topology_gap_review=topology_gap_review,
        same_pair_multi_arc_observation=same_pair_multi_arc_observation,
    )
    obligation_by_pair = {str(item["pair"]): item for item in obligation["rows"]}
    assert obligation_by_pair["55353246:37687913"]["obligation_status"] == "must_remain_blocked"
    assert obligation_by_pair["55353246:37687913"]["blocking_layer"] == "business_rule"
    assert obligation_by_pair["55353246:37687913"]["blocking_reason"] == "competing_arc_requires_new_pair_selection_rule"
    assert obligation_by_pair["791871:37687913"]["obligation_status"] == "must_remain_blocked"
    assert obligation_by_pair["791871:37687913"]["blocking_layer"] == "support_ranking"
    assert obligation_by_pair["791871:37687913"]["blocking_reason"] == "competing_arc_support_weaker_below_selection_threshold"

    competing = build_competing_arc_review(
        complex_patch_id="5417632623039346",
        topology_gap_review=topology_gap_review,
        same_pair_multi_arc_observation=same_pair_multi_arc_observation,
    )
    competing_by_pair = {str(item["pair"]): item for item in competing["rows"]}
    assert competing_by_pair["55353246:37687913"]["root_cause_code"] == "competing_arc_requires_new_pair_selection_rule"
    assert competing_by_pair["791871:37687913"]["root_cause_code"] == "competing_arc_support_weaker_below_selection_threshold"
    assert competing_by_pair["791871:37687913"]["strongest_peer_pair"] == "55353246:37687913"
    assert len(competing_by_pair["791871:37687913"]["competing_siblings"]) == 2


def test_t05v2_merge_diverge_detection_does_not_require_shared_internal_node_path() -> None:
    rows = [
        {
            "pair": "55353246:37687913",
            "src": 55353246,
            "dst": 37687913,
            "is_direct_legal": True,
            "is_unique": True,
            "node_path": [55353246, 310001, 37687913],
            "edge_ids": ["edge_gap_a_up", "edge_gap_a_down"],
            "line_coords": [[0.0, 2.0], [65.0, 2.0], [100.0, 0.0]],
            "traj_support_type": "terminal_crossing_support",
            "traj_support_ids": ["traj_gap_a"],
            "traj_support_coverage_ratio": 0.82,
            "support_anchor_src_coords": [0.0, 2.0],
            "support_anchor_dst_coords": [100.0, 0.0],
        },
        {
            "pair": "791871:37687913",
            "src": 791871,
            "dst": 37687913,
            "is_direct_legal": True,
            "is_unique": True,
            "node_path": [791871, 310002, 37687913],
            "edge_ids": ["edge_gap_b_up", "edge_gap_b_down"],
            "line_coords": [[0.0, 4.0], [68.0, 4.0], [100.0, 0.5]],
            "traj_support_type": "terminal_crossing_support",
            "traj_support_ids": ["traj_gap_b"],
            "traj_support_coverage_ratio": 0.79,
            "support_anchor_src_coords": [0.0, 4.0],
            "support_anchor_dst_coords": [100.0, 0.5],
        },
    ]

    annotated = apply_arc_selection_rules(rows)["rows"]
    by_pair = {str(item["pair"]): dict(item) for item in annotated}
    assert by_pair["55353246:37687913"]["arc_structure_type"] == "MERGE_MULTI_UPSTREAM"
    assert by_pair["791871:37687913"]["arc_structure_type"] == "MERGE_MULTI_UPSTREAM"
    assert "shared_intermediate_xsec_signal" not in by_pair["55353246:37687913"]["arc_selection_shared_downstream_signal"]
    assert "shared_terminal_geometry_signal" in by_pair["55353246:37687913"]["arc_selection_shared_downstream_signal"]


def test_t05v2_arc_selection_structure_and_multi_arc_review_autofill_structure_annotations(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    patch_id = "patch_merge_diverge"
    patch_dir = run_root / "patches" / patch_id
    _write_json(
        patch_dir / "metrics.json",
        {
            "patch_id": patch_id,
            "full_legal_arc_registry": [
                {
                    "pair": "55353246:37687913",
                    "src": 55353246,
                    "dst": 37687913,
                    "topology_arc_id": "arc_gap_a",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "node_path": [55353246, 310001, 37687913],
                    "edge_ids": ["edge_gap_a_up", "edge_gap_a_down"],
                    "line_coords": [[0.0, 2.0], [65.0, 2.0], [100.0, 0.0]],
                    "traj_support_type": "terminal_crossing_support",
                    "traj_support_ids": ["traj_gap_a"],
                    "traj_support_coverage_ratio": 0.82,
                    "support_anchor_src_coords": [0.0, 2.0],
                    "support_anchor_dst_coords": [100.0, 2.0],
                },
                {
                    "pair": "791871:37687913",
                    "src": 791871,
                    "dst": 37687913,
                    "topology_arc_id": "arc_gap_b",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "node_path": [791871, 310002, 37687913],
                    "edge_ids": ["edge_gap_b_up", "edge_gap_b_down"],
                    "line_coords": [[0.0, 4.0], [68.0, 4.0], [100.0, 0.5]],
                    "traj_support_type": "terminal_crossing_support",
                    "traj_support_ids": ["traj_gap_b"],
                    "traj_support_coverage_ratio": 0.79,
                    "support_anchor_src_coords": [0.0, 4.0],
                    "support_anchor_dst_coords": [100.0, 4.0],
                },
                {
                    "pair": "21779764:785642",
                    "src": 21779764,
                    "dst": 785642,
                    "topology_arc_id": "arc_multi_1",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": False,
                    "corridor_identity": "witness_based",
                    "traj_support_type": "terminal_crossing_support",
                    "support_anchor_src_coords": [0.0, 8.0],
                    "support_anchor_dst_coords": [100.0, 8.0],
                },
                {
                    "pair": "21779764:785642",
                    "src": 21779764,
                    "dst": 785642,
                    "topology_arc_id": "arc_multi_2",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": False,
                    "prior_support_type": "prior_fallback_support",
                    "drivezone_overlap_ratio": 0.71,
                    "divstrip_overlap_ratio": 0.0,
                    "support_anchor_src_coords": [0.0, 9.0],
                    "support_anchor_dst_coords": [100.0, 9.0],
                },
            ],
        },
    )

    arc_selection = build_arc_selection_structure(run_root, complex_patch_id=patch_id)
    assert int(arc_selection["merge_multi_upstream_pair_count"]) == 2
    assert int(arc_selection["same_pair_multi_arc_pair_count"]) == 1
    by_pair = {}
    for row in arc_selection["rows"]:
        by_pair.setdefault(str(row["pair"]), []).append(dict(row))
    assert by_pair["55353246:37687913"][0]["structure_type"] == "MERGE_MULTI_UPSTREAM"
    assert by_pair["791871:37687913"][0]["structure_type"] == "MERGE_MULTI_UPSTREAM"
    assert "shared_terminal_geometry_signal" in by_pair["55353246:37687913"][0]["shared_downstream_signal"]

    multi_arc_review = build_multi_arc_review(
        run_root,
        complex_patch_id=patch_id,
        same_pair_multi_arc_observation={
            "patch_id": patch_id,
            "rows": [
                {
                    "patch_id": patch_id,
                    "pair": "21779764:785642",
                    "pair_arc_count": 2,
                    "arc_ids": ["arc_multi_1", "arc_multi_2"],
                    "has_built_sibling_arc": False,
                    "built_sibling_arc_ids": [],
                    "excluded_from_unique_denominator_reason": "same_pair_multi_arc",
                    "current_business_status": "multi_arc_no_built_sibling_visual_gap_candidate",
                    "next_rule_needed": "multi_arc_selection_rule",
                    "visual_gap_note": "no_built_sibling_visual_gap_candidate",
                }
            ],
        },
    )
    assert int(multi_arc_review["row_count"]) == 1
    row = multi_arc_review["rows"][0]
    assert row["pair"] == "21779764:785642"
    assert row["allow_multi_output"] is True
    assert row["witness_based_arc_ids"] == ["arc_multi_1"]
    assert row["fallback_based_arc_ids"] == ["arc_multi_2"]
    assert row["rule_reason"] == "same_pair_multi_arc_dual_output_ready"


def test_t05v2_arc_selection_structure_accepts_json_nested_support_signatures(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    patch_id = "patch_nested_support_signature"
    patch_dir = run_root / "patches" / patch_id
    _write_json(
        patch_dir / "metrics.json",
        {
            "patch_id": patch_id,
            "full_legal_arc_registry": [
                {
                    "pair": "791873:791871",
                    "src": 791873,
                    "dst": 791871,
                    "topology_arc_id": "arc_same_pair_1",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": False,
                    "support_anchor_src_coords": [0.0, 0.0],
                    "support_anchor_dst_coords": [100.0, 0.0],
                    "support_corridor_signature": [[0.0, 0.0], [50.0, 0.0], [100.0, 0.0]],
                    "support_surface_side_signature": ["lane_a", [1.0, 0.0]],
                    "multi_arc_evidence_mode": "fallback_based",
                },
                {
                    "pair": "791873:791871",
                    "src": 791873,
                    "dst": 791871,
                    "topology_arc_id": "arc_same_pair_2",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": False,
                    "support_anchor_src_coords": [0.0, 4.0],
                    "support_anchor_dst_coords": [100.0, 4.0],
                    "support_corridor_signature": [[0.0, 4.0], [50.0, 4.0], [100.0, 4.0]],
                    "support_surface_side_signature": ["lane_b", [1.0, 4.0]],
                    "multi_arc_evidence_mode": "fallback_based",
                },
            ],
        },
    )

    annotated = apply_arc_selection_rules(
        json.loads((patch_dir / "metrics.json").read_text(encoding="utf-8"))["full_legal_arc_registry"]
    )["rows"]
    annotated_by_arc = {str(item["topology_arc_id"]): item for item in annotated}
    assert annotated_by_arc["arc_same_pair_1"]["arc_structure_type"] == "SAME_PAIR_MULTI_ARC"
    assert "distinct_support_corridor_signal" in annotated_by_arc["arc_same_pair_1"]["arc_selection_same_pair_distinct_path_signal"]
    assert "distinct_support_side_signal" in annotated_by_arc["arc_same_pair_1"]["arc_selection_same_pair_distinct_path_signal"]

    arc_selection = build_arc_selection_structure(run_root, complex_patch_id=patch_id)
    assert int(arc_selection["same_pair_multi_arc_pair_count"]) == 1
    by_arc = {str(item["topology_arc_id"]): item for item in arc_selection["rows"]}
    assert by_arc["arc_same_pair_1"]["structure_type"] == "SAME_PAIR_MULTI_ARC"


def test_t05v2_multi_arc_review_prefers_step3_evidence_mode_fields(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    patch_id = "patch_multi_arc_step3"
    patch_dir = run_root / "patches" / patch_id
    _write_json(
        patch_dir / "metrics.json",
        {
            "patch_id": patch_id,
            "full_legal_arc_registry": [
                {
                    "pair": "791873:791871",
                    "src": 791873,
                    "dst": 791871,
                    "topology_arc_id": "arc_multi_a",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": False,
                    "arc_structure_type": "SAME_PAIR_MULTI_ARC",
                    "entered_main_flow": True,
                    "built_final_road": True,
                    "production_multi_arc_allowed": True,
                    "multi_arc_evidence_mode": "witness_based",
                    "multi_arc_structure_type": "SAME_PAIR_MULTI_ARC",
                    "multi_arc_rule_reason": "same_pair_multi_arc_dual_output_ready",
                },
                {
                    "pair": "791873:791871",
                    "src": 791873,
                    "dst": 791871,
                    "topology_arc_id": "arc_multi_b",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": False,
                    "arc_structure_type": "SAME_PAIR_MULTI_ARC",
                    "entered_main_flow": True,
                    "built_final_road": False,
                    "production_multi_arc_allowed": True,
                    "multi_arc_evidence_mode": "fallback_based",
                    "multi_arc_structure_type": "SAME_PAIR_MULTI_ARC",
                    "multi_arc_rule_reason": "same_pair_multi_arc_dual_output_ready",
                    "unbuilt_stage": "step5_geometry_rejected",
                    "unbuilt_reason": "road_crosses_divstrip",
                },
            ],
        },
    )

    multi_arc_review = build_multi_arc_review(
        run_root,
        complex_patch_id=patch_id,
        same_pair_multi_arc_observation={
            "patch_id": patch_id,
            "rows": [
                {
                    "patch_id": patch_id,
                    "pair": "791873:791871",
                    "pair_arc_count": 2,
                    "arc_ids": ["arc_multi_a", "arc_multi_b"],
                    "has_built_sibling_arc": True,
                    "built_sibling_arc_ids": ["arc_multi_a"],
                    "excluded_from_unique_denominator_reason": "same_pair_multi_arc",
                    "current_business_status": "multi_arc_with_built_sibling_under_observation",
                    "next_rule_needed": "multi_arc_selection_rule",
                    "visual_gap_note": "built_sibling_present_visual_gap_possible",
                }
            ],
        },
    )

    assert int(multi_arc_review["row_count"]) == 1
    row = multi_arc_review["rows"][0]
    assert row["pair"] == "791873:791871"
    assert row["allow_multi_output"] is True
    assert row["witness_based_arc_ids"] == ["arc_multi_a"]
    assert row["fallback_based_arc_ids"] == ["arc_multi_b"]
    assert row["entered_main_flow"] is True
    assert row["built"] is True


def test_t05v2_arc_legality_audit_uses_full_registry_for_arc_first_built_segment(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    patch_id = "patch_arc_first"
    patch_dir = run_root / "patches" / patch_id
    _write_json(
        patch_dir / "metrics.json",
        {
            "patch_id": patch_id,
            "segments": [],
            "full_legal_arc_registry": [
                {
                    "pair": "10:20",
                    "topology_arc_id": "arc_good",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "working_segment_id": "arcseg::arc_good",
                    "entered_main_flow": True,
                }
            ],
        },
    )
    _write_json(patch_dir / "step2" / "segments.json", {"segments": [], "excluded_candidates": []})
    _write_json(
        patch_dir / "step6" / "final_roads.json",
        {"roads": [{"road_id": "road_good", "segment_id": "arcseg::arc_good", "src_nodeid": 10, "dst_nodeid": 20}]},
    )

    audit = build_arc_legality_audit(run_root, [patch_id])
    assert int(audit["summary"]["bad_built_arc_count"]) == 0
    assert bool(audit["summary"]["built_all_direct_unique"]) is True


def test_t05v2_pair_decisions_include_controlled_entry_built_pair(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    patch_id = "patch_controlled_pair"
    patch_dir = run_root / "patches" / patch_id
    _write_json(
        patch_dir / "metrics.json",
        {
            "patch_id": patch_id,
            "full_legal_arc_registry": [
                {
                    "pair": "760239:6963539359479390368",
                    "src": 760239,
                    "dst": 6963539359479390368,
                    "topology_arc_id": "arc_gap_c",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "entered_main_flow": True,
                    "controlled_entry_allowed": True,
                    "topology_gap_decision": "gap_enter_mainflow",
                    "topology_gap_reason": "gap_should_enter_mainflow",
                    "working_segment_id": "arcseg::arc_gap_c",
                    "built_final_road": True,
                }
            ],
        },
    )
    _write_json(patch_dir / "step2" / "segments.json", {"segments": [], "excluded_candidates": []})
    _write_json(
        patch_dir / "step6" / "final_roads.json",
        {
            "roads": [
                {
                    "road_id": "road_gap_c",
                    "segment_id": "arcseg::arc_gap_c",
                    "src_nodeid": 760239,
                    "dst_nodeid": 6963539359479390368,
                }
            ],
            "road_results": [],
        },
    )
    _write_json(patch_dir / "debug" / "step2_segment_should_not_exist.json", {"pairs": []})
    _write_json(patch_dir / "debug" / "step2_topology_pairs.json", {"pairs": []})
    _write_json(patch_dir / "debug" / "step2_blocked_pair_bridge_audit.json", {"pairs": []})

    decisions = build_pair_decisions(run_root, patch_id)
    by_pair = {str(item.get("pair", "")): item for item in decisions.get("pairs", [])}
    row = by_pair["760239:6963539359479390368"]
    assert bool(row["built_final_road"]) is True
    assert bool(row["topology_arc_is_direct_legal"]) is True
    assert bool(row["topology_arc_is_unique"]) is True
    assert bool(row["controlled_entry_allowed"]) is True
    assert row["topology_gap_decision"] == "gap_enter_mainflow"
    assert row["topology_gap_reason"] == "gap_should_enter_mainflow"
    assert row["identity_resolution_source"] == "full_legal_arc_registry"


def test_t05v2_arc_legality_audit_does_not_flag_controlled_entry_built_pair(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    patch_id = "patch_controlled_audit"
    patch_dir = run_root / "patches" / patch_id
    _write_json(
        patch_dir / "metrics.json",
        {
            "patch_id": patch_id,
            "full_legal_arc_registry": [
                {
                    "pair": "760239:6963539359479390368",
                    "src": 760239,
                    "dst": 6963539359479390368,
                    "topology_arc_id": "arc_gap_c",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "entered_main_flow": True,
                    "controlled_entry_allowed": True,
                    "blocked_diagnostic_only": True,
                    "blocked_diagnostic_reason": "topology_gap_unresolved",
                    "hard_block_reason": "topology_gap_unresolved",
                    "topology_gap_decision": "gap_enter_mainflow",
                    "topology_gap_reason": "gap_should_enter_mainflow",
                    "working_segment_id": "arcseg::arc_gap_c",
                    "built_final_road": True,
                }
            ],
        },
    )
    _write_json(patch_dir / "step2" / "segments.json", {"segments": [], "excluded_candidates": []})
    _write_json(
        patch_dir / "step6" / "final_roads.json",
        {
            "roads": [
                {
                    "road_id": "road_gap_c",
                    "segment_id": "arcseg::arc_gap_c",
                    "src_nodeid": 760239,
                    "dst_nodeid": 6963539359479390368,
                }
            ],
            "road_results": [],
        },
    )

    audit = build_arc_legality_audit(run_root, [patch_id])
    built_row = audit["built_roads"][0]
    assert bool(built_row["controlled_entry_allowed"]) is True
    assert bool(built_row["blocked_diagnostic_only"]) is False
    assert built_row["hard_block_reason"] == ""
    assert int(audit["summary"]["bad_built_arc_count"]) == 0
    assert bool(audit["summary"]["built_all_direct_unique"]) is True
    assert "760239:6963539359479390368" not in audit["summary"]["violating_built_pairs"]


def test_t05v2_arc_legality_audit_allows_built_same_pair_multi_arc_production_exception(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    patch_id = "patch_multi_arc_audit"
    patch_dir = run_root / "patches" / patch_id
    _write_json(
        patch_dir / "metrics.json",
        {
            "patch_id": patch_id,
            "full_legal_arc_registry": [
                {
                    "pair": "21779764:785642",
                    "src": 21779764,
                    "dst": 785642,
                    "topology_arc_id": "arc_multi_1",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": False,
                    "entered_main_flow": True,
                    "built_final_road": True,
                    "working_segment_id": "arcseg::arc_multi_1",
                    "production_multi_arc_allowed": True,
                    "multi_arc_evidence_mode": "witness_based",
                    "multi_arc_structure_type": "SAME_PAIR_MULTI_ARC",
                    "multi_arc_rule_reason": "same_pair_multi_arc_dual_output_ready",
                },
                {
                    "pair": "21779764:785642",
                    "src": 21779764,
                    "dst": 785642,
                    "topology_arc_id": "arc_multi_2",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": False,
                    "entered_main_flow": True,
                    "built_final_road": True,
                    "working_segment_id": "arcseg::arc_multi_2",
                    "production_multi_arc_allowed": True,
                    "multi_arc_evidence_mode": "fallback_based",
                    "multi_arc_structure_type": "SAME_PAIR_MULTI_ARC",
                    "multi_arc_rule_reason": "same_pair_multi_arc_dual_output_ready",
                },
            ],
        },
    )
    _write_json(
        patch_dir / "step2" / "segments.json",
        {
            "segments": [
                {
                    "segment_id": "arcseg::arc_multi_1",
                    "src_nodeid": 21779764,
                    "dst_nodeid": 785642,
                    "topology_arc_id": "arc_multi_1",
                    "topology_arc_source_type": "direct_topology_arc",
                    "topology_arc_is_direct_legal": True,
                    "topology_arc_is_unique": False,
                    "production_multi_arc_allowed": True,
                    "multi_arc_evidence_mode": "witness_based",
                    "multi_arc_structure_type": "SAME_PAIR_MULTI_ARC",
                    "multi_arc_rule_reason": "same_pair_multi_arc_dual_output_ready",
                },
                {
                    "segment_id": "arcseg::arc_multi_2",
                    "src_nodeid": 21779764,
                    "dst_nodeid": 785642,
                    "topology_arc_id": "arc_multi_2",
                    "topology_arc_source_type": "direct_topology_arc",
                    "topology_arc_is_direct_legal": True,
                    "topology_arc_is_unique": False,
                    "production_multi_arc_allowed": True,
                    "multi_arc_evidence_mode": "fallback_based",
                    "multi_arc_structure_type": "SAME_PAIR_MULTI_ARC",
                    "multi_arc_rule_reason": "same_pair_multi_arc_dual_output_ready",
                },
            ],
            "excluded_candidates": [],
        },
    )
    _write_json(
        patch_dir / "step6" / "final_roads.json",
        {
            "roads": [
                {"road_id": "road_multi_1", "segment_id": "arcseg::arc_multi_1", "src_nodeid": 21779764, "dst_nodeid": 785642},
                {"road_id": "road_multi_2", "segment_id": "arcseg::arc_multi_2", "src_nodeid": 21779764, "dst_nodeid": 785642},
            ],
            "road_results": [],
        },
    )

    audit = build_arc_legality_audit(run_root, [patch_id])
    assert int(audit["summary"]["bad_built_arc_count"]) == 0
    assert bool(audit["summary"]["built_all_direct_unique"]) is True
    assert audit["built_roads"][0]["production_multi_arc_allowed"] is True


def test_t05v2_directed_topology_alias_normalization_promotes_shared_xsec_alias_to_direct_arc(tmp_path: Path) -> None:
    params = dict(DEFAULT_PARAMS)
    frame = InputFrame(
        patch_id="alias_patch",
        metric_crs="EPSG:3857",
        base_cross_sections=(
            BaseCrossSection(nodeid=55353307, geometry_coords=((0.0, -5.0), (0.0, 5.0)), properties={}),
            BaseCrossSection(nodeid=765141, geometry_coords=((100.0, -5.0), (100.0, 5.0)), properties={}),
        ),
        probe_cross_sections=tuple(),
        drivezone_area_m2=1000.0,
        divstrip_present=False,
        lane_boundary_count=0,
        trajectory_count=0,
        road_prior_count=2,
        node_count=1,
        input_summary={},
    )
    inputs = PatchInputs(
        patch_id="alias_patch",
        patch_dir=tmp_path / "alias_patch",
        metric_crs="EPSG:3857",
        intersection_lines=tuple(),
        lane_boundaries_metric=tuple(),
        trajectories=tuple(),
        drivezone_zone_metric=Polygon([(-10.0, -10.0), (110.0, -10.0), (110.0, 10.0), (-10.0, 10.0)]),
        divstrip_zone_metric=None,
        road_prior_path=None,
        node_records=(SimpleNamespace(nodeid=23287538, point=Point(0.5, 0.0)),),
        input_summary={},
    )
    prior_roads = [
        SimpleNamespace(line=LineString([(0.0, 0.0), (0.5, 0.0)]), snodeid=55353307, enodeid=23287538, direction=2),
        SimpleNamespace(line=LineString([(0.5, 0.0), (100.0, 0.0)]), snodeid=23287538, enodeid=765141, direction=2),
    ]

    topology = _build_directed_topology(frame=frame, inputs=inputs, prior_roads=prior_roads, params=params)

    assert topology["xsec_alias_map"][23287538] == 55353307
    assert (55353307, 765141) in topology["allowed_pairs"]
    assert not topology.get("trace_only_pair_paths", {}).get((55353307, 765141))
    direct_arc = topology["pair_arcs"][(55353307, 765141)][0]
    assert direct_arc["raw_pair"] == "23287538:765141"
    assert bool(direct_arc["src_alias_applied"]) is True


def test_t05v2_pair_decisions_and_audit_preserve_alias_normalized_identity(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    patch_id = "patch_alias_identity"
    patch_dir = run_root / "patches" / patch_id
    _write_json(
        patch_dir / "metrics.json",
        {
            "patch_id": patch_id,
            "full_legal_arc_registry": [
                {
                    "pair": "55353307:765141",
                    "src": 55353307,
                    "dst": 765141,
                    "raw_src_nodeid": 23287538,
                    "raw_dst_nodeid": 765141,
                    "canonical_src_xsec_id": 55353307,
                    "canonical_dst_xsec_id": 765141,
                    "src_alias_applied": True,
                    "dst_alias_applied": False,
                    "raw_pair": "23287538:765141",
                    "canonical_pair": "55353307:765141",
                    "topology_arc_id": "arc_alias",
                    "topology_arc_source_type": "direct_topology_arc",
                    "is_direct_legal": True,
                    "is_unique": True,
                    "entered_main_flow": True,
                    "working_segment_id": "arcseg::arc_alias",
                    "built_final_road": True,
                }
            ],
        },
    )
    _write_json(patch_dir / "step2" / "segments.json", {"segments": [], "excluded_candidates": []})
    _write_json(
        patch_dir / "step6" / "final_roads.json",
        {
            "roads": [
                {
                    "road_id": "road_alias",
                    "segment_id": "arcseg::arc_alias",
                    "src_nodeid": 55353307,
                    "dst_nodeid": 765141,
                }
            ],
            "road_results": [],
        },
    )
    _write_json(patch_dir / "debug" / "step2_segment_should_not_exist.json", {"pairs": []})
    _write_json(patch_dir / "debug" / "step2_topology_pairs.json", {"pairs": []})
    _write_json(patch_dir / "debug" / "step2_blocked_pair_bridge_audit.json", {"pairs": []})

    decisions = build_pair_decisions(run_root, patch_id)
    row = {str(item.get("pair", "")): item for item in decisions.get("pairs", [])}["55353307:765141"]
    assert row["raw_pair"] == "23287538:765141"
    assert row["canonical_pair"] == "55353307:765141"
    assert bool(row["alias_normalized"]) is True
    assert bool(row["topology_arc_is_direct_legal"]) is True
    assert bool(row["topology_arc_is_unique"]) is True
    assert bool(row["built_final_road"]) is True

    audit = build_arc_legality_audit(run_root, [patch_id])
    built_row = audit["built_roads"][0]
    assert built_row["raw_pair"] == "23287538:765141"
    assert built_row["canonical_pair"] == "55353307:765141"
    assert bool(built_row["alias_normalized"]) is True
    assert int(audit["summary"]["bad_built_arc_count"]) == 0
    assert bool(audit["summary"]["built_all_direct_unique"]) is True


def test_t05v2_scripts_stepwise_state_resume(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("bash script resume test requires a POSIX-mounted workspace path")
    repo_root = Path(__file__).resolve().parents[1]
    patch_id = "script_resume"
    data_root = tmp_path / "data"
    road_fc = _fc([_line_feature([(0.0, 0.0), (100.0, 0.0)], {"snodeid": 1, "enodeid": 2})], "EPSG:3857")
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=_fc([_poly_feature([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)])], "EPSG:3857"),
        traj_tracks=[[(0.0, 0.0), (20.0, 0.0), (50.0, 0.0), (100.0, 0.0)]],
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_id = "script_run"
    env = os.environ.copy()
    env["PYTHON_BIN"] = sys.executable
    step1 = repo_root / "scripts" / "t05v2_step1_input_frame.sh"
    resume = repo_root / "scripts" / "t05v2_resume.sh"
    subprocess.run(
        ["bash", step1.as_posix(), "--data_root", data_root.as_posix(), "--patch_id", patch_id, "--run_id", run_id, "--out_root", out_root.as_posix(), "--debug"],
        env=env,
        check=True,
    )
    subprocess.run(
        ["bash", resume.as_posix(), "--data_root", data_root.as_posix(), "--patch_id", patch_id, "--run_id", run_id, "--out_root", out_root.as_posix(), "--debug"],
        env=env,
        check=True,
    )
    subprocess.run(
        ["bash", resume.as_posix(), "--data_root", data_root.as_posix(), "--patch_id", patch_id, "--run_id", run_id, "--out_root", out_root.as_posix(), "--debug"],
        env=env,
        check=True,
    )
    step6_state = _read_json(out_root / run_id / "patches" / patch_id / "step6" / "step_state.json")
    road_geojson = _read_json(out_root / run_id / "patches" / patch_id / "Road.geojson")
    assert bool(step6_state["ok"]) is True
    assert len(road_geojson["features"]) == 1
