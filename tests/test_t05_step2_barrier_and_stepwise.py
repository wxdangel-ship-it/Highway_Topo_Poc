from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon

from highway_topo_poc.modules.t05_topology_between_rc.geometry import (
    HARD_ENDPOINT_OFF_ANCHOR,
    _EndStableDecision,
    _apply_endpoint_trend_projection,
    _build_xsec_road_for_endpoint,
    PairSupport,
)
from highway_topo_poc.modules.t05_topology_between_rc import pipeline
from highway_topo_poc.modules.t05_topology_between_rc.io import CrossSection


def _decision(anchor_s: float) -> _EndStableDecision:
    return _EndStableDecision(
        is_gore_tip=False,
        is_expanded=False,
        width_near_m=8.0,
        width_base_m=8.0,
        gore_overlap_near=0.0,
        stable_s_m=anchor_s,
        anchor_station_m=anchor_s,
        anchor_offset_m=0.0,
        cut_mode="simple_near",
        used_fallback=False,
        short_base_proxy=False,
    )


def test_step2_barrier_filter_vehicle_noise() -> None:
    shape_ref = LineString([(0.0, 0.0), (120.0, 0.0)])
    xsec_seed = LineString([(10.0, -30.0), (10.0, 30.0)])
    traj_segments = [LineString([(8.5, -1.0), (11.5, -1.0), (11.5, 1.0), (8.5, 1.0)])]
    ground_xy = np.asarray([[10.0, y] for y in np.linspace(-25.0, 25.0, 101)], dtype=np.float64)
    non_ground_xy = np.asarray([[10.0 + 0.2 * ((i % 2) * 2 - 1), y] for i, y in enumerate(np.linspace(-4.0, 4.0, 25))], dtype=np.float64)

    out = _build_xsec_road_for_endpoint(
        xsec_seed=xsec_seed,
        shape_ref_line=shape_ref,
        traj_segments=traj_segments,
        drivezone_zone_metric=None,
        ground_xy=ground_xy,
        non_ground_xy=non_ground_xy,
        gore_zone_metric=None,
        ref_half_len_m=80.0,
        sample_step_m=1.0,
        nonpass_k=6,
        evidence_radius_m=1.0,
        min_ground_pts=1,
        min_traj_pts=1,
        core_band_m=20.0,
        shift_step_m=5.0,
        fallback_short_half_len_m=15.0,
        barrier_min_ng_count=2,
        barrier_min_len_m=4.0,
        barrier_along_len_m=60.0,
        barrier_along_width_m=2.5,
        barrier_bin_step_m=2.0,
        barrier_occ_ratio_min=0.65,
        endcap_window_m=60.0,
        caseb_pre_m=3.0,
        endpoint_tag="src",
    )

    assert int(out.get("barrier_candidate_count", 0)) >= 1
    assert int(out.get("barrier_final_count", 0)) == 0
    assert str(out.get("selected_by")) != "fallback_short"


def test_step1_prefers_non_gore_corridor_at_constrained_end() -> None:
    support = PairSupport(
        src_nodeid=100,
        dst_nodeid=200,
        support_traj_ids={"bad", "good"},
        support_event_count=2,
        traj_segments=[
            LineString([(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]),
            LineString([(0.0, 8.0), (50.0, 8.0), (100.0, 8.0)]),
        ],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 8.0)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 8.0)],
        evidence_traj_ids=["bad", "good"],
        cluster_count=1,
        main_cluster_ratio=1.0,
    )
    src_xsec = LineString([(0.0, -20.0), (0.0, 20.0)])
    dst_xsec = LineString([(100.0, -20.0), (100.0, 20.0)])
    gore = LineString([(-2.0, 0.0), (2.0, 0.0)]).buffer(3.0)

    out = pipeline._build_step1_corridor_for_pair(
        support=support,
        src_type="merge",
        dst_type="diverge",
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=None,
        gore_zone_metric=gore,
        params={"STEP1_GORE_NEAR_M": 20.0, "STEP1_MULTI_CORRIDOR_DIST_M": 8.0, "STEP1_MULTI_CORRIDOR_MIN_RATIO": 0.6},
    )

    line = out.get("shape_ref_line")
    assert isinstance(line, LineString)
    assert float(line.distance(support.traj_segments[1])) <= 1e-6
    assert float(line.distance(support.traj_segments[0])) > 1.0
    assert bool(out.get("gore_fallback_used_src")) is False


def test_step1_prefers_gore_free_corridor_when_constraints_equal() -> None:
    support = PairSupport(
        src_nodeid=101,
        dst_nodeid=201,
        support_traj_ids={"cross", "clean"},
        support_event_count=2,
        traj_segments=[
            LineString([(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]),
            LineString([(0.0, 6.0), (50.0, 6.0), (100.0, 6.0)]),
        ],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 6.0)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 6.0)],
        evidence_traj_ids=["cross", "clean"],
        cluster_count=1,
        main_cluster_ratio=1.0,
    )
    src_xsec = LineString([(0.0, -20.0), (0.0, 20.0)])
    dst_xsec = LineString([(100.0, -20.0), (100.0, 20.0)])
    gore = LineString([(45.0, -4.0), (55.0, -4.0)]).buffer(8.0)

    out = pipeline._build_step1_corridor_for_pair(
        support=support,
        src_type="merge",
        dst_type="merge",
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=None,
        gore_zone_metric=gore,
        params={"STEP1_GORE_NEAR_M": 20.0, "STEP1_MULTI_CORRIDOR_DIST_M": 8.0, "STEP1_MULTI_CORRIDOR_MIN_RATIO": 0.6},
    )

    line = out.get("shape_ref_line")
    assert isinstance(line, LineString)
    assert float(line.distance(support.traj_segments[1])) <= 1e-6
    assert float(line.distance(support.traj_segments[0])) > 1.0


def test_step1_multi_corridor_soft_by_default() -> None:
    support = PairSupport(
        src_nodeid=300,
        dst_nodeid=400,
        support_traj_ids={"c0", "c1", "c2"},
        support_event_count=3,
        traj_segments=[
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            LineString([(0.0, 45.0), (100.0, 45.0)]),
            LineString([(0.0, -45.0), (100.0, -45.0)]),
        ],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 45.0), Point(0.0, -45.0)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 45.0), Point(100.0, -45.0)],
        evidence_traj_ids=["c0", "c1", "c2"],
        cluster_count=6,
        main_cluster_ratio=0.35,
    )
    src_xsec = LineString([(0.0, -20.0), (0.0, 20.0)])
    dst_xsec = LineString([(100.0, -20.0), (100.0, 20.0)])

    out = pipeline._build_step1_corridor_for_pair(
        support=support,
        src_type="merge",
        dst_type="merge",
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=None,
        gore_zone_metric=None,
        params={"STEP1_MULTI_CORRIDOR_DIST_M": 8.0, "STEP1_MULTI_CORRIDOR_MIN_RATIO": 0.6},
    )

    line = out.get("shape_ref_line")
    assert isinstance(line, LineString)
    assert out.get("hard_reason") is None
    assert bool(out.get("multi_corridor_detected")) is True


def test_step1_multi_corridor_hard_when_enabled() -> None:
    support = PairSupport(
        src_nodeid=301,
        dst_nodeid=401,
        support_traj_ids={"c0", "c1", "c2"},
        support_event_count=3,
        traj_segments=[
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            LineString([(0.0, 45.0), (100.0, 45.0)]),
            LineString([(0.0, -45.0), (100.0, -45.0)]),
        ],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 45.0), Point(0.0, -45.0)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 45.0), Point(100.0, -45.0)],
        evidence_traj_ids=["c0", "c1", "c2"],
        cluster_count=6,
        main_cluster_ratio=0.35,
    )
    src_xsec = LineString([(0.0, -20.0), (0.0, 20.0)])
    dst_xsec = LineString([(100.0, -20.0), (100.0, 20.0)])

    out = pipeline._build_step1_corridor_for_pair(
        support=support,
        src_type="merge",
        dst_type="merge",
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=None,
        gore_zone_metric=None,
        params={
            "STEP1_MULTI_CORRIDOR_DIST_M": 8.0,
            "STEP1_MULTI_CORRIDOR_MIN_RATIO": 0.6,
            "STEP1_MULTI_CORRIDOR_HARD": 1,
        },
    )

    assert str(out.get("hard_reason")) == str(pipeline.HARD_MULTI_CORRIDOR)
    assert out.get("shape_ref_line") is None


def test_xsec_gate_cut_by_drivezone() -> None:
    xsec = CrossSection(
        nodeid=1,
        geometry_metric=LineString([(0.0, -80.0), (0.0, 80.0)]),
        properties={"nodeid": 1},
    )
    drivezone = Polygon([(-20.0, -8.0), (20.0, -8.0), (20.0, 8.0), (-20.0, 8.0)])
    divstrip = Polygon([(-2.0, -1.5), (2.0, -1.5), (2.0, 1.5), (-2.0, 1.5)])

    out_map, _anchors, _trunc, _gate_all_map, gate_meta_map, stats = pipeline._truncate_cross_sections_for_crossing(
        xsec_map={1: xsec},
        lane_boundaries_metric=[],
        trajectories=[],
        drivezone_zone_metric=drivezone,
        gore_zone_metric=divstrip,
        params=dict(pipeline.DEFAULT_PARAMS),
    )

    got = out_map[1].geometry_metric
    assert float(got.length) < float(xsec.geometry_metric.length)
    assert float(got.length) > 1.0
    assert float(got.intersection(divstrip).length) <= 1e-6
    assert bool(stats.get("xsec_gate_enabled")) is True
    meta = gate_meta_map.get(1) or {}
    assert bool(meta.get("fallback", False)) is False


def test_traj_drop_when_outside_drivezone() -> None:
    support = PairSupport(
        src_nodeid=10,
        dst_nodeid=20,
        support_traj_ids={"in", "out"},
        support_event_count=2,
        traj_segments=[
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            LineString([(0.0, 25.0), (100.0, 25.0)]),
        ],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 25.0)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 25.0)],
        evidence_traj_ids=["in", "out"],
        cluster_count=2,
        main_cluster_ratio=0.5,
    )
    src_xsec = LineString([(0.0, -30.0), (0.0, 30.0)])
    dst_xsec = LineString([(100.0, -30.0), (100.0, 30.0)])
    drivezone = Polygon([(-10.0, -6.0), (110.0, -6.0), (110.0, 6.0), (-10.0, 6.0)])

    out = pipeline._build_step1_corridor_for_pair(
        support=support,
        src_type="merge",
        dst_type="merge",
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=drivezone,
        gore_zone_metric=None,
        params={
            "STEP1_TRAJ_IN_DRIVEZONE_MIN": 0.85,
            "STEP1_TRAJ_IN_DRIVEZONE_FALLBACK_MIN": 0.60,
            "STEP1_MULTI_CORRIDOR_DIST_M": 8.0,
            "STEP1_MULTI_CORRIDOR_MIN_RATIO": 0.6,
        },
    )
    line = out.get("shape_ref_line")
    assert isinstance(line, LineString)
    assert float(line.distance(support.traj_segments[0])) <= 1e-6
    assert int(out.get("traj_drop_count_by_drivezone", -1)) == 1
    assert bool(out.get("drivezone_fallback_used", False)) is False

    support_only_out = PairSupport(
        src_nodeid=11,
        dst_nodeid=21,
        support_traj_ids={"out_only"},
        support_event_count=1,
        traj_segments=[LineString([(0.0, 25.0), (100.0, 25.0)])],
        src_cross_points=[Point(0.0, 25.0)],
        dst_cross_points=[Point(100.0, 25.0)],
        evidence_traj_ids=["out_only"],
    )
    out_fallback = pipeline._build_step1_corridor_for_pair(
        support=support_only_out,
        src_type="merge",
        dst_type="merge",
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=drivezone,
        gore_zone_metric=None,
        params={
            "STEP1_TRAJ_IN_DRIVEZONE_MIN": 0.85,
            "STEP1_TRAJ_IN_DRIVEZONE_FALLBACK_MIN": 0.60,
            "STEP1_MULTI_CORRIDOR_DIST_M": 8.0,
            "STEP1_MULTI_CORRIDOR_MIN_RATIO": 0.6,
        },
    )
    assert bool(out_fallback.get("drivezone_fallback_used", False)) is True
    assert int(out_fallback.get("traj_drop_count_by_drivezone", 0)) >= 0


def test_step1_no_distance_clustering_dependency() -> None:
    support = PairSupport(
        src_nodeid=501,
        dst_nodeid=601,
        support_traj_ids={"c0", "c1", "c2"},
        support_event_count=3,
        traj_segments=[
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            LineString([(0.0, 30.0), (100.0, 30.0)]),
            LineString([(0.0, -30.0), (100.0, -30.0)]),
        ],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 30.0), Point(0.0, -30.0)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 30.0), Point(100.0, -30.0)],
        evidence_traj_ids=["c0", "c1", "c2"],
        cluster_count=1,
        main_cluster_ratio=1.0,
    )
    src_xsec = LineString([(0.0, -40.0), (0.0, 40.0)])
    dst_xsec = LineString([(100.0, -40.0), (100.0, 40.0)])

    out = pipeline._build_step1_corridor_for_pair(
        support=support,
        src_type="merge",
        dst_type="merge",
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=None,
        gore_zone_metric=None,
        params={
            "STEP1_MULTI_CORRIDOR_DIST_M": 8.0,
            "STEP1_MULTI_CORRIDOR_MIN_RATIO": 0.6,
            "STEP1_MULTI_CORRIDOR_HARD": 1,
        },
    )
    assert str(out.get("hard_reason")) == str(pipeline.HARD_MULTI_CORRIDOR)


def test_xsec_selected_must_intersect_ref_or_fallback() -> None:
    shape_ref = LineString([(0.0, 0.0), (120.0, 0.0)])
    xsec_seed = LineString([(10.0, -40.0), (10.0, 40.0)])
    gore = LineString([(0.0, 0.0), (120.0, 0.0)]).buffer(20.0)

    out = _build_xsec_road_for_endpoint(
        xsec_seed=xsec_seed,
        shape_ref_line=shape_ref,
        traj_segments=[],
        drivezone_zone_metric=None,
        ground_xy=np.empty((0, 2), dtype=np.float64),
        non_ground_xy=np.empty((0, 2), dtype=np.float64),
        gore_zone_metric=gore,
        ref_half_len_m=80.0,
        sample_step_m=1.0,
        nonpass_k=6,
        evidence_radius_m=1.0,
        min_ground_pts=1,
        min_traj_pts=1,
        core_band_m=20.0,
        shift_step_m=5.0,
        fallback_short_half_len_m=15.0,
        barrier_min_ng_count=2,
        barrier_min_len_m=4.0,
        barrier_along_len_m=60.0,
        barrier_along_width_m=2.5,
        barrier_bin_step_m=2.0,
        barrier_occ_ratio_min=0.65,
        endcap_window_m=60.0,
        caseb_pre_m=3.0,
        endpoint_tag="dst",
    )

    assert str(out.get("selected_by")) == "fallback_short"


def test_endpoint_dist_to_xsec_le_1m_or_hard(monkeypatch: pytest.MonkeyPatch) -> None:
    base_line = LineString([(0.0, 0.0), (100.0, 0.0)])
    sample_stations = np.asarray([0.0, 50.0, 100.0], dtype=np.float64)
    sample_center_points = np.asarray([[0.0, 0.0], [50.0, 0.0], [100.0, 0.0]], dtype=np.float64)
    far_target = LineString([(0.0, 50.0), (0.0, 60.0)])

    def _fake_target(*, xsec, gore_zone_metric, xsec_support_geom, enforced, lb_ref_line):  # type: ignore[no-untyped-def]
        del xsec, gore_zone_metric, xsec_support_geom, enforced, lb_ref_line
        return far_target, "forced_far_target"

    monkeypatch.setattr(
        "highway_topo_poc.modules.t05_topology_between_rc.geometry._select_xsec_target_segment",
        _fake_target,
    )

    line, _dev0, _dev1, hard_reason, _proj0, _proj1, _meta = _apply_endpoint_trend_projection(
        base_line=base_line,
        shape_ref_line=base_line,
        sample_stations=sample_stations,
        sample_center_points=sample_center_points,
        src_decision=_decision(0.0),
        dst_decision=_decision(100.0),
        src_xsec=LineString([(0.0, -10.0), (0.0, 10.0)]),
        dst_xsec=LineString([(100.0, -10.0), (100.0, 10.0)]),
        src_channel_points=[],
        dst_channel_points=[],
        support_traj_segments=[],
        surface_points_xyz=np.empty((0, 3), dtype=np.float64),
        trend_fit_win_m=20.0,
        drivezone_zone_metric=None,
        traj_surface_metric=None,
        traj_surface_enforced=False,
        gore_zone_metric=None,
        endpoint_tol_m=1.0,
        anchor_window_m=15.0,
        endpoint_local_max_dist_m=20.0,
        xsec_ref_half_len_m=80.0,
        xsec_road_sample_step_m=1.0,
        xsec_road_nonpass_k=6,
        xsec_road_evidence_radius_m=1.0,
        xsec_road_min_ground_pts=1,
        xsec_road_min_traj_pts=1,
        road_max_vertices=2000,
        non_ground_xy=np.empty((0, 2), dtype=np.float64),
    )

    assert line is not None
    assert hard_reason == HARD_ENDPOINT_OFF_ANCHOR


def test_scripts_stepwise_state_resume(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_root = tmp_path / "out"
    run_id = "testrun"
    patch_id = "2855795596723843"
    data_root = tmp_path / "mock_data"
    data_root.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["T05_TEST_MODE"] = "1"
    env["PYTHON_BIN"] = "python3"

    step1 = repo_root / "scripts" / "t05_step1_shape_ref.sh"
    resume = repo_root / "scripts" / "t05_resume.sh"
    subprocess.run(
        ["bash", str(step1), "--data_root", str(data_root), "--patch_id", patch_id, "--run_id", run_id, "--out_root", str(out_root), "--debug"],
        env=env,
        check=True,
    )
    subprocess.run(
        ["bash", str(resume), "--data_root", str(data_root), "--patch_id", patch_id, "--run_id", run_id, "--out_root", str(out_root), "--debug"],
        env=env,
        check=True,
    )
    subprocess.run(
        ["bash", str(resume), "--data_root", str(data_root), "--patch_id", patch_id, "--run_id", run_id, "--out_root", str(out_root), "--debug"],
        env=env,
        check=True,
    )
    subprocess.run(
        ["bash", str(resume), "--data_root", str(data_root), "--patch_id", patch_id, "--run_id", run_id, "--out_root", str(out_root), "--debug"],
        env=env,
        check=True,
    )
    subprocess.run(
        ["bash", str(resume), "--data_root", str(data_root), "--patch_id", patch_id, "--run_id", run_id, "--out_root", str(out_root), "--debug"],
        env=env,
        check=True,
    )

    step4_state = out_root / run_id / "patches" / patch_id / "step4" / "step_state.json"
    step0_state = out_root / run_id / "patches" / patch_id / "step0" / "step_state.json"
    assert step0_state.is_file()
    assert step4_state.is_file()
    payload = json.loads(step4_state.read_text(encoding="utf-8"))
    assert bool(payload.get("ok")) is True
