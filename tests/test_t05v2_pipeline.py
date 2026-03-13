from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
from shapely.geometry import LineString, Polygon

from highway_topo_poc.modules.t05_topology_between_rc_v2.io import PatchInputs
from highway_topo_poc.modules.t05_topology_between_rc_v2.models import (
    CorridorIdentity,
    CorridorInterval,
    CorridorWitness,
    Segment,
    SlotInterval,
)
from highway_topo_poc.modules.t05_topology_between_rc_v2.pipeline import (
    DEFAULT_PARAMS,
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
    write_arc_legality_fix_review,
    write_legal_arc_coverage_review,
)
from highway_topo_poc.modules.t05_topology_between_rc_v2.step3_corridor_identity import build_corridor_identities


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


def test_t05v2_production_arc_rejects_non_unique_direct_legal_arc(tmp_path: Path) -> None:
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
    assert pair_segments == []
    excluded = [
        item
        for item in segments_payload["excluded_candidates"]
        if int(item["src_nodeid"]) == 1 and int(item["dst_nodeid"]) == 2
    ]
    assert excluded
    assert {str(item["reason"]) for item in excluded} == {"non_unique_direct_legal_arc"}
    assert {str(item["stage"]) for item in excluded} == {"semantic_hard_gate"}
    topology_arcs_payload = _read_json(out_root / "run_multi_arc" / "patches" / patch_id / "debug" / "step2_topology_arcs.json")
    arcs = [
        item
        for item in topology_arcs_payload["arcs"]
        if int(item["src_nodeid"]) == 1 and int(item["dst_nodeid"]) == 2
    ]
    assert len(arcs) == 2


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
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=_fc([_poly_feature([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)])], "EPSG:3857"),
        traj_tracks=[[(0.0, 0.0), (20.0, 0.0), (50.0, 0.0), (80.0, 0.0), (100.0, 0.0)]],
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
    assert metrics["segments"][0]["shape_ref_mode"] == "witness_centerline"
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


def test_t05v2_unresolved_when_short_segment_has_no_prior(tmp_path: Path) -> None:
    patch_id = "short_unresolved"
    data_root = tmp_path / "data"
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
    )
    out_root = tmp_path / "out"
    run_full_pipeline(data_root=data_root, patch_id=patch_id, run_id="run5", out_root=out_root)
    metrics = _read_json(out_root / "run5" / "patches" / patch_id / "metrics.json")
    gate = _read_json(out_root / "run5" / "patches" / patch_id / "gate.json")
    roads = _read_json(out_root / "run5" / "patches" / patch_id / "Road.geojson")
    reason_trace = _read_json(out_root / "run5" / "patches" / patch_id / "debug" / "reason_trace.json")
    assert metrics["segments"][0]["corridor_identity"] == "unresolved"
    assert int(metrics["no_geometry_candidate_count"]) == 1
    assert str(metrics["no_geometry_candidate_reason"]) != ""
    assert bool(metrics["segments"][0]["no_geometry_candidate"]) is True
    assert str(metrics["segments"][0]["no_geometry_candidate_reason"]) != ""
    assert metrics["segments"][0]["failure_classification"] == "unresolved_corridor"
    assert reason_trace["road_results"][0]["failure_classification"] == "unresolved_corridor"
    assert len(roads["features"]) == 0
    assert bool(gate["overall_pass"]) is False
    assert gate["hard_breakpoints"]


def test_t05v2_slot_mapping_uses_witness_fraction_not_nearest_point(tmp_path: Path) -> None:
    patch_id = "slot_fraction"
    data_root = tmp_path / "data"
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
    )
    out_root = tmp_path / "out"
    run_full_pipeline(data_root=data_root, patch_id=patch_id, run_id="run6", out_root=out_root)
    roads = _read_json(out_root / "run6" / "patches" / patch_id / "Road.geojson")
    metrics = _read_json(out_root / "run6" / "patches" / patch_id / "metrics.json")
    start_x, start_y = roads["features"][0]["geometry"]["coordinates"][0]
    assert metrics["segments"][0]["corridor_identity"] == "witness_based"
    assert start_y > 4.0
    assert abs(start_y - (-6.0)) > 5.0


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


def test_t05v2_build_final_road_falls_back_to_segment_support_when_witness_centerline_leaves_drivezone() -> None:
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
    assert result["shape_ref_mode"] == "segment_support_slot_anchored"
    assert len(result["candidate_attempts"]) == 2
    assert result["candidate_attempts"][0]["mode"] == "witness_centerline"
    assert float(result["candidate_attempts"][0]["drivezone_ratio"]) < float(DEFAULT_PARAMS["ROAD_MIN_DRIVEZONE_RATIO"])
    assert result["candidate_attempts"][1]["mode"] == "segment_support_slot_anchored"
    assert float(result["candidate_attempts"][1]["drivezone_ratio"]) >= float(DEFAULT_PARAMS["ROAD_MIN_DRIVEZONE_RATIO"])
    assert road.line_coords == ((0.0, 1.0), (50.0, 1.0), (100.0, 1.0))


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
    assert result["reason"] == "synthetic_arc_not_allowed"
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
    summary = write_arc_legality_fix_review(run_root=run_root, output_root=output_root)
    assert (output_root / "acceptance_5417632690143239.json").exists()
    assert (output_root / "acceptance_5417632690143326.json").exists()
    assert (output_root / "pair_decisions.json").exists()
    assert (output_root / "arc_legality_audit.json").exists()
    assert (output_root / "legal_arc_coverage.json").exists()
    assert (output_root / "simple_patch_acceptance.json").exists()
    assert (output_root / "strong_constraint_status.json").exists()
    assert (output_root / "simple_patch_regression.json").exists()
    assert (output_root / "complex_patch_legality_review.json").exists()
    assert (output_root / "complex_patch_coverage_review.json").exists()
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
    assert (output_root / "legal_arc_coverage.json").exists()
    assert (output_root / "simple_patch_acceptance.json").exists()
    assert (output_root / "complex_patch_coverage_review.json").exists()
    assert "legal_arc_coverage" in summary


def test_t05v2_scripts_stepwise_state_resume(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    patch_id = "script_resume"
    data_root = tmp_path / "data"
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=_simple_intersections(),
        drivezone_fc=_fc([_poly_feature([(-5.0, -4.0), (105.0, -4.0), (105.0, 4.0), (-5.0, 4.0)])], "EPSG:3857"),
        traj_tracks=[[(0.0, 0.0), (20.0, 0.0), (50.0, 0.0), (100.0, 0.0)]],
    )
    out_root = tmp_path / "out"
    run_id = "script_run"
    env = os.environ.copy()
    env["PYTHON_BIN"] = sys.executable
    step1 = repo_root / "scripts" / "t05v2_step1_input_frame.sh"
    resume = repo_root / "scripts" / "t05v2_resume.sh"
    subprocess.run(["bash", str(step1), "--data_root", str(data_root), "--patch_id", patch_id, "--run_id", run_id, "--out_root", str(out_root), "--debug"], env=env, check=True)
    subprocess.run(["bash", str(resume), "--data_root", str(data_root), "--patch_id", patch_id, "--run_id", run_id, "--out_root", str(out_root), "--debug"], env=env, check=True)
    subprocess.run(["bash", str(resume), "--data_root", str(data_root), "--patch_id", patch_id, "--run_id", run_id, "--out_root", str(out_root), "--debug"], env=env, check=True)
    step6_state = _read_json(out_root / run_id / "patches" / patch_id / "step6" / "step_state.json")
    road_geojson = _read_json(out_root / run_id / "patches" / patch_id / "Road.geojson")
    assert bool(step6_state["ok"]) is True
    assert len(road_geojson["features"]) == 1
