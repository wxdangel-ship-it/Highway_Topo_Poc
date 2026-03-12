from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from highway_topo_poc.modules.t05_topology_between_rc_v2.pipeline import run_full_pipeline, run_stage


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
    excluded = segments_payload["excluded_candidates"]
    blocked_pairs = {
        (int(item["src_nodeid"]), int(item["dst_nodeid"])): str(item["reason"])
        for item in excluded
        if str(item.get("reason")) == "cross1_pair_not_allowlisted"
    }
    assert blocked_pairs[(2, 4)] == "cross1_pair_not_allowlisted"


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
    assert int(metrics["road_count"]) == 1
    assert int(metrics["raw_candidate_count"]) >= 1
    assert int(metrics["witness_selected_count_total"]) == 1
    assert int(metrics["witness_selected_count_cross0"]) == 1
    assert int(metrics["witness_selected_count_cross1"]) == 0
    assert metrics["segments"][0]["corridor_identity"] == "witness_based"
    assert bool(gate["overall_pass"]) is True
    assert len(roads["features"]) == 1


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
    assert metrics["segments"][0]["corridor_identity"] == "prior_based"
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
    assert metrics["segments"][0]["corridor_identity"] == "unresolved"
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
    assert bool(gate["overall_pass"]) is False
    assert gate["hard_breakpoints"]
    assert int(metrics["road_count"]) == 0


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
