from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from shapely.geometry import Polygon

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
    _topology_gate_reason,
    run_full_pipeline,
    run_stage,
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
    assert excluded_by_pair[(11, 41)] == "terminal_node_not_owned_by_src"
    assert excluded_by_pair[(21, 41)] == "terminal_node_not_owned_by_src"
    assert excluded_by_pair[(41, 31)] == "directionally_invalid_segment"
    step2_metrics = segments_payload["step2_metrics"]
    assert int(step2_metrics["segment_selected_count_before_topology_gate"]) == 4
    assert int(step2_metrics["segment_selected_count_after_topology_gate"]) == 1
    assert int(step2_metrics["directionally_invalid_segment_count"]) == 1
    assert int(step2_metrics["terminal_node_invalid_segment_count"]) == 2
    audit = _read_json(patch_dir / "debug" / "step2_terminal_node_audit.json")
    node_41 = next(item for item in audit["nodes"] if int(item["nodeid"]) == 41)
    assert node_41["reverse_owner_status"] == "unique_owner"
    assert int(node_41["reverse_owner_src_nodeid"]) == 31
    pair_map = {str(item["pair_id"]): item for item in node_41["pairs"]}
    assert bool(pair_map["31:41"]["selected"]) is True
    assert bool(pair_map["31:41"]["topology_reverse_owner_match"]) is True
    assert pair_map["11:41"]["rejected_reason"] == "terminal_node_not_owned_by_src"
    assert pair_map["21:41"]["rejected_reason"] == "terminal_node_not_owned_by_src"
    assert bool(pair_map["11:41"]["topology_reverse_owner_match"]) is False
    should_not_exist = _read_json(patch_dir / "debug" / "step2_segment_should_not_exist.json")
    reasons = { (int(item["src_nodeid"]), int(item["dst_nodeid"])): str(item["reason"]) for item in should_not_exist["pairs"] }
    assert reasons[(11, 41)] == "terminal_node_not_owned_by_src"
    assert reasons[(21, 41)] == "terminal_node_not_owned_by_src"
    assert reasons[(41, 31)] == "directionally_invalid_segment"
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
        == "terminal_node_not_owned_by_src"
    )


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
    assert excluded_by_pair[0]["stage"] == "ownership_gate"
    assert excluded_by_pair[0]["competing_prior_pair_ids"] == ["10:30"]
    assert excluded_by_pair[0]["competing_prior_candidate_ids"] == ["prior_0"]
    assert excluded_by_pair[0]["competing_prior_trace_paths"] == [[10, 30, 40]]
    assert int(segments_payload["step2_metrics"]["unanchored_prior_conflict_segment_count"]) == 1
    should_not_exist = _read_json(patch_dir / "debug" / "step2_segment_should_not_exist.json")
    row = next(item for item in should_not_exist["pairs"] if int(item["src_nodeid"]) == 10 and int(item["dst_nodeid"]) == 40)
    assert row["reason"] == "src_conflicts_with_unique_unanchored_prior_endpoint"
    assert row["competing_prior_pair_ids"] == ["10:30"]
    assert row["competing_prior_trace_paths"] == [[10, 30, 40]]


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


def test_t05v2_step2_topology_gate_allows_traced_rcsdroad_pairs(tmp_path: Path) -> None:
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
    assert pair_map["10:20"]["topology_sources"] == ["rcsdroad_trace"]
    assert pair_map["10:20"]["topology_paths"][0]["node_path"] == [10, 101, 20]
    step2_metrics = segments_payload["step2_metrics"]
    assert int(step2_metrics["segment_selected_count_after_topology_gate"]) == 4
    assert int(step2_metrics["topology_invalid_segment_count"]) == 0


def test_t05v2_step2_topology_gate_allows_terminal_trace_pairs(tmp_path: Path) -> None:
    patch_id = "topology_terminal_trace"
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
    assert (10, 40) in kept_pairs
    topology_debug = _read_json(patch_dir / "debug" / "step2_topology_pairs.json")
    pair_map = {str(item["pair_id"]): item for item in topology_debug["pairs"]}
    assert pair_map["10:40"]["topology_sources"] == ["rcsdroad_terminal_trace"]
    assert pair_map["10:40"]["topology_paths"][0]["node_path"] == [10, 20, 40]


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
