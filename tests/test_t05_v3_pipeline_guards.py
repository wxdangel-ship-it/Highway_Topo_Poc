from __future__ import annotations

from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from highway_topo_poc.modules.t05_topology_between_rc import pipeline
from highway_topo_poc.modules.t05_topology_between_rc.geometry import (
    CenterEstimate,
    CrossingExtractResult,
    HARD_ENDPOINT_LOCAL,
    PairSupport,
    PairSupportBuildResult,
    _EndStableDecision,
    _apply_endpoint_trend_projection,
    _project_endpoint_to_valid_xsec,
)
from highway_topo_poc.modules.t05_topology_between_rc.io import (
    CrossSection,
    PatchInputs,
    PointCloudWindow,
    ProjectionInfo,
    TrajectoryData,
)


def _mk_patch_inputs(
    *,
    tmp_path: Path,
    intersection_lines: list[CrossSection],
    trajectories: list[TrajectoryData],
) -> PatchInputs:
    return PatchInputs(
        patch_id="unit_patch",
        patch_dir=tmp_path,
        projection=ProjectionInfo(input_crs="EPSG:3857", metric_crs="EPSG:3857", projected=False),
        projection_to_metric=lambda geom: geom,
        projection_to_input=lambda geom: geom,
        intersection_lines=intersection_lines,
        lane_boundaries_metric=[],
        node_kind_map={},
        trajectories=trajectories,
        drivezone_zone_metric=None,
        drivezone_source_path=None,
        divstrip_zone_metric=None,
        divstrip_source_path=None,
        point_cloud_path=None,
        road_prior_path=None,
        tiles_dir=None,
        input_summary={},
    )


def _mk_center(line: LineString, *, diagnostics: dict | None = None) -> CenterEstimate:
    return CenterEstimate(
        centerline_metric=line,
        shape_ref_metric=LineString([(0.0, 0.0), (210.0, 0.0)]),
        lb_path_found=True,
        lb_path_edge_count=2,
        lb_path_length_m=210.0,
        stable_offset_m_src=0.0,
        stable_offset_m_dst=0.0,
        center_sample_coverage=1.0,
        width_med_m=10.0,
        width_p90_m=12.0,
        max_turn_deg_per_10m=0.0,
        used_lane_boundary=True,
        src_is_gore_tip=False,
        dst_is_gore_tip=False,
        src_is_expanded=False,
        dst_is_expanded=False,
        src_width_near_m=10.0,
        dst_width_near_m=10.0,
        src_width_base_m=10.0,
        dst_width_base_m=10.0,
        src_gore_overlap_near=0.0,
        dst_gore_overlap_near=0.0,
        src_stable_s_m=20.0,
        dst_stable_s_m=20.0,
        src_cut_mode="stable_section",
        dst_cut_mode="stable_section",
        endpoint_tangent_deviation_deg_src=0.0,
        endpoint_tangent_deviation_deg_dst=0.0,
        endpoint_center_offset_m_src=0.5,
        endpoint_center_offset_m_dst=0.6,
        endpoint_proj_dist_to_core_m_src=0.2,
        endpoint_proj_dist_to_core_m_dst=0.3,
        soft_flags=set(),
        hard_flags=set(),
        diagnostics=dict(diagnostics or {}),
    )


def test_endpoint_projection_prefers_gore_free_xsec_piece() -> None:
    xsec = LineString([(0.0, -8.0), (0.0, 8.0)])
    gore = Polygon([(-1.0, -2.0), (1.0, -2.0), (1.0, 2.0), (-1.0, 2.0)])

    out_xy, _mode, _support_len = _project_endpoint_to_valid_xsec(
        endpoint_xy=(0.0, 0.0),
        xsec=xsec,
        gore_zone_metric=gore,
        channel_ref_xy=(0.0, 4.0),
    )
    out_pt = Point(float(out_xy[0]), float(out_xy[1]))

    assert out_pt.distance(xsec) <= 1e-6
    assert not gore.contains(out_pt)
    assert out_xy[1] >= 2.0


def test_endpoint_projection_marks_out_local_when_far_from_xsec() -> None:
    xsec = LineString([(0.0, -8.0), (0.0, 8.0)])
    out_xy, mode, _support_len = _project_endpoint_to_valid_xsec(
        endpoint_xy=(0.0, 60.0),
        xsec=xsec,
        gore_zone_metric=None,
        channel_ref_xy=None,
        local_max_dist_m=10.0,
    )
    out_pt = Point(float(out_xy[0]), float(out_xy[1]))
    assert out_pt.distance(xsec) <= 1e-6
    assert str(mode).endswith("_out_local")


def test_endpoint_trend_projection_rejects_far_core_connector() -> None:
    base_line = LineString([(0.0, 0.0), (100.0, 0.0)])
    sample_stations = np.asarray([0.0, 50.0, 100.0], dtype=np.float64)
    sample_center_points = np.asarray([[0.0, 0.0], [50.0, 0.0], [100.0, 0.0]], dtype=np.float64)
    src_decision = _EndStableDecision(
        is_gore_tip=False,
        is_expanded=False,
        width_near_m=8.0,
        width_base_m=8.0,
        gore_overlap_near=0.0,
        stable_s_m=20.0,
        anchor_station_m=0.0,
        anchor_offset_m=0.0,
        cut_mode="simple_near",
        used_fallback=False,
        short_base_proxy=False,
    )
    dst_decision = _EndStableDecision(
        is_gore_tip=False,
        is_expanded=False,
        width_near_m=8.0,
        width_base_m=8.0,
        gore_overlap_near=0.0,
        stable_s_m=80.0,
        anchor_station_m=100.0,
        anchor_offset_m=0.0,
        cut_mode="simple_near",
        used_fallback=False,
        short_base_proxy=False,
    )
    src_xsec = LineString([(-200.0, -10.0), (-200.0, 10.0)])
    dst_xsec = LineString([(100.0, -10.0), (100.0, 10.0)])

    out_line, _dev_src, _dev_dst, hard_reason, _proj_src, _proj_dst, _meta = _apply_endpoint_trend_projection(
        base_line=base_line,
        shape_ref_line=base_line,
        sample_stations=sample_stations,
        sample_center_points=sample_center_points,
        src_decision=src_decision,
        dst_decision=dst_decision,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
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
    )

    assert out_line is None
    assert hard_reason == HARD_ENDPOINT_LOCAL


def test_traj_surface_enforced_endpoint_outside_is_hard(tmp_path: Path) -> None:
    seq = np.arange(0, 101, dtype=np.int64)
    traj_xy_1 = np.asarray([[float(x), -1.0, 0.0] for x in seq], dtype=np.float64)
    traj_xy_2 = np.asarray([[float(x), 1.0, 0.0] for x in seq], dtype=np.float64)
    traj_1 = TrajectoryData(
        traj_id="t1",
        seq=seq,
        xyz_metric=traj_xy_1,
        source_path=tmp_path / "t1.geojson",
        source_crs="EPSG:3857",
    )
    traj_2 = TrajectoryData(
        traj_id="t2",
        seq=seq,
        xyz_metric=traj_xy_2,
        source_path=tmp_path / "t2.geojson",
        source_crs="EPSG:3857",
    )
    patch_inputs = _mk_patch_inputs(tmp_path=tmp_path, intersection_lines=[], trajectories=[traj_1, traj_2])
    support = PairSupport(src_nodeid=1, dst_nodeid=2, support_traj_ids={"t1", "t2"})
    road = {"road_id": "1_2", "src_nodeid": 1, "dst_nodeid": 2}

    params = dict(pipeline.DEFAULT_PARAMS)
    params.update(
        {
            "TRAJ_SURF_MIN_POINTS_PER_SLICE": 3,
            "TRAJ_SURF_MIN_SLICE_VALID_RATIO": 0.1,
            "TRAJ_SURF_MIN_COVERED_LEN_RATIO": 0.1,
            "TRAJ_SURF_MIN_UNIQUE_TRAJ": 1,
        }
    )
    road_line = LineString([(0.0, 4.0), (100.0, 4.0)])
    shape_ref = LineString([(0.0, 0.0), (100.0, 0.0)])

    result, soft_flags, hard_flags, breakpoints = pipeline._eval_traj_surface_gate(
        road=road,
        road_line=road_line,
        shape_ref_line=shape_ref,
        support=support,
        patch_inputs=patch_inputs,
        gore_zone_metric=None,
        params=params,
    )

    assert result["traj_surface_enforced"] is True
    assert "ROAD_OUTSIDE_TRAJ_SURFACE" in hard_flags
    assert str(result.get("traj_surface_gate_failure_mode")) == "endpoint_both"
    assert not soft_flags
    assert any(str(bp.get("severity")) == "hard" for bp in breakpoints)
    assert any("gate_failure_mode=endpoint_both" in str(bp.get("hint")) for bp in breakpoints)


def test_traj_surface_endpoint_hole_tolerance_allows_small_miss(tmp_path: Path) -> None:
    patch_inputs = _mk_patch_inputs(tmp_path=tmp_path, intersection_lines=[], trajectories=[])
    support = PairSupport(src_nodeid=10, dst_nodeid=20, support_traj_ids={"t1"})
    road = {"road_id": "10_20", "src_nodeid": 10, "dst_nodeid": 20}

    params = dict(pipeline.DEFAULT_PARAMS)
    params.update(
        {
            "TRAJ_SURF_MIN_SLICE_VALID_RATIO": 0.1,
            "TRAJ_SURF_MIN_COVERED_LEN_RATIO": 0.1,
            "TRAJ_SURF_MIN_UNIQUE_TRAJ": 1,
            "IN_RATIO_MIN": 0.95,
            "TRAJ_SURF_ENDPOINT_HOLE_TOL_M": 2.0,
            "TRAJ_SURF_ENDPOINT_HOLE_IN_RATIO_MIN": 0.99,
        }
    )
    road_line = LineString([(0.0, 0.0), (100.0, 0.0)])
    shape_ref = LineString([(0.0, 0.0), (100.0, 0.0)])
    # Keep almost all road inside, but make dst endpoint miss by 0.5m.
    surface = Polygon([(0.0, -3.0), (99.5, -3.0), (99.5, 3.0), (0.0, 3.0), (0.0, -3.0)])
    hint = {
        "surface_metric": surface,
        "valid_slices": 10,
        "total_slices": 10,
        "slice_valid_ratio": 1.0,
        "covered_length_ratio": 1.0,
        "covered_station_length_m": 100.0,
        "endcap_valid_ratio_src": 1.0,
        "endcap_valid_ratio_dst": 1.0,
        "xsec_support_available_src": True,
        "xsec_support_available_dst": True,
        "unique_traj_count": 1,
        "_stations": np.asarray([0.0, 50.0, 100.0], dtype=np.float64),
        "_valid_mask": np.asarray([True, True, True], dtype=bool),
    }

    result, soft_flags, hard_flags, _breakpoints = pipeline._eval_traj_surface_gate(
        road=road,
        road_line=road_line,
        shape_ref_line=shape_ref,
        support=support,
        patch_inputs=patch_inputs,
        gore_zone_metric=None,
        params=params,
        traj_surface_hint=hint,
    )

    assert result["traj_surface_enforced"] is True
    assert result["endpoint_in_traj_surface_dst_raw"] is False
    assert result["endpoint_in_traj_surface_dst"] is True
    assert result["endpoint_traj_surface_tolerance_used_dst"] is True
    assert float(result["traj_in_ratio"] or 0.0) >= 0.99
    assert "ROAD_OUTSIDE_TRAJ_SURFACE" not in hard_flags
    assert not soft_flags


def test_bridge_guard_skips_clean_long_segment_without_violation(tmp_path: Path, monkeypatch) -> None:
    xsecs = [
        CrossSection(nodeid=1, geometry_metric=LineString([(0.0, -5.0), (0.0, 5.0)]), properties={"nodeid": 1}),
        CrossSection(nodeid=2, geometry_metric=LineString([(210.0, -5.0), (210.0, 5.0)]), properties={"nodeid": 2}),
    ]
    patch_inputs = _mk_patch_inputs(tmp_path=tmp_path, intersection_lines=xsecs, trajectories=[])
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1"},
        support_event_count=1,
        repr_traj_ids=["t1"],
    )
    build_result = PairSupportBuildResult(
        supports={(1, 2): support},
        unresolved_events=[],
        graph_node_count=0,
        graph_edge_count=0,
        stitch_candidate_count=0,
        stitch_edge_count=0,
        stitch_query_count=0,
        stitch_candidates_total=0,
        stitch_reject_dist_count=0,
        stitch_reject_angle_count=0,
        stitch_reject_forward_count=0,
        stitch_accept_count=0,
        stitch_levels_used_hist={},
    )

    monkeypatch.setattr(
        pipeline,
        "extract_crossing_events",
        lambda *args, **kwargs: CrossingExtractResult(
            events_by_traj={},
            raw_hit_count=0,
            dedup_drop_count=0,
            n_cross_empty_skipped=0,
            n_cross_geom_unexpected=0,
            n_cross_distance_gate_reject=0,
        ),
    )
    monkeypatch.setattr(pipeline, "build_pair_supports", lambda *args, **kwargs: build_result)
    monkeypatch.setattr(
        pipeline,
        "infer_node_types",
        lambda **kwargs: ({1: "unknown", 2: "unknown"}, {1: 0, 2: 0}, {1: 0, 2: 0}),
    )
    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: _mk_center(LineString([(0.0, 0.0), (200.0, 0.0), (210.0, 0.0)])),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: (
            {
                "traj_surface_enforced": False,
                "traj_in_ratio": None,
                "traj_in_ratio_est": None,
                "endpoint_in_traj_surface_src": None,
                "endpoint_in_traj_surface_dst": None,
            },
            set(),
            set(),
            [],
        ),
    )

    out = pipeline._run_patch_core(
        patch_inputs,
        params=dict(pipeline.DEFAULT_PARAMS),
        run_id="unit_run",
        repo_root=tmp_path,
    )
    reasons = {str(bp.get("reason")) for bp in out["hard_breakpoints"]}
    assert "BRIDGE_SEGMENT_TOO_LONG" not in reasons


def test_endpoint_anchor_guard_adds_hard_breakpoint(tmp_path: Path, monkeypatch) -> None:
    xsecs = [
        CrossSection(nodeid=1, geometry_metric=LineString([(0.0, -5.0), (0.0, 5.0)]), properties={"nodeid": 1}),
        CrossSection(nodeid=2, geometry_metric=LineString([(10.0, -5.0), (10.0, 5.0)]), properties={"nodeid": 2}),
    ]
    patch_inputs = _mk_patch_inputs(tmp_path=tmp_path, intersection_lines=xsecs, trajectories=[])
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1"},
        support_event_count=1,
        repr_traj_ids=["t1"],
    )
    build_result = PairSupportBuildResult(
        supports={(1, 2): support},
        unresolved_events=[],
        graph_node_count=0,
        graph_edge_count=0,
        stitch_candidate_count=0,
        stitch_edge_count=0,
        stitch_query_count=0,
        stitch_candidates_total=0,
        stitch_reject_dist_count=0,
        stitch_reject_angle_count=0,
        stitch_reject_forward_count=0,
        stitch_accept_count=0,
        stitch_levels_used_hist={},
    )

    monkeypatch.setattr(
        pipeline,
        "extract_crossing_events",
        lambda *args, **kwargs: CrossingExtractResult(
            events_by_traj={},
            raw_hit_count=0,
            dedup_drop_count=0,
            n_cross_empty_skipped=0,
            n_cross_geom_unexpected=0,
            n_cross_distance_gate_reject=0,
        ),
    )
    monkeypatch.setattr(pipeline, "build_pair_supports", lambda *args, **kwargs: build_result)
    monkeypatch.setattr(
        pipeline,
        "infer_node_types",
        lambda **kwargs: ({1: "unknown", 2: "unknown"}, {1: 0, 2: 0}, {1: 0, 2: 0}),
    )

    def _fake_evaluate_candidate_road(**kwargs):  # type: ignore[no-untyped-def]
        road = pipeline._make_base_road_record(
            src=1,
            dst=2,
            support=support,
            src_type="unknown",
            dst_type="unknown",
            neighbor_search_pass=1,
        )
        road["_geometry_metric"] = LineString([(100.0, 0.0), (110.0, 0.0)])
        road["length_m"] = 10.0
        road["conf"] = 0.8
        road["hard_anomaly"] = False
        road["hard_reasons"] = []
        road["soft_issue_flags"] = []
        return road

    monkeypatch.setattr(pipeline, "_evaluate_candidate_road", _fake_evaluate_candidate_road)

    out = pipeline._run_patch_core(
        patch_inputs,
        params=dict(pipeline.DEFAULT_PARAMS),
        run_id="unit_run",
        repo_root=tmp_path,
    )

    reasons = {str(bp.get("reason")) for bp in out["hard_breakpoints"]}
    assert out["overall_pass"] is False
    assert "ENDPOINT_NOT_ON_XSEC" in reasons
    assert out["gate_payload"]["hard_breakpoints"]


def test_neighbor_pass2_is_triggered_when_no_supports(tmp_path: Path) -> None:
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        intersection_lines=[
            CrossSection(
                nodeid=1,
                geometry_metric=LineString([(0.0, -2.0), (0.0, 2.0)]),
                properties={"nodeid": 1},
            )
        ],
        trajectories=[],
    )

    out = pipeline._run_patch_core(
        patch_inputs,
        params=dict(pipeline.DEFAULT_PARAMS),
        run_id="unit_run",
        repo_root=tmp_path,
    )
    reasons = {str(bp.get("reason")) for bp in out["hard_breakpoints"]}

    assert "NO_ADJACENT_PAIR_AFTER_PASS2" in reasons
    assert out["metrics_payload"].get("neighbor_search_pass") == 2
    assert out["metrics_payload"].get("neighbor_search_pass2_used") is True


def test_neighbor_pass2_is_triggered_when_unresolved_high_and_stitch_zero(tmp_path: Path, monkeypatch) -> None:
    xsecs = [
        CrossSection(nodeid=1, geometry_metric=LineString([(0.0, -2.0), (0.0, 2.0)]), properties={"nodeid": 1}),
        CrossSection(nodeid=2, geometry_metric=LineString([(120.0, -2.0), (120.0, 2.0)]), properties={"nodeid": 2}),
    ]
    patch_inputs = _mk_patch_inputs(tmp_path=tmp_path, intersection_lines=xsecs, trajectories=[])

    pass1_support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1"},
        support_event_count=1,
        repr_traj_ids=["t1"],
    )
    pass2_support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1", "t2", "t3"},
        support_event_count=3,
        repr_traj_ids=["t1", "t2", "t3"],
    )
    unresolved = [
        {"reason": "UNRESOLVED_NEIGHBOR", "traj_id": f"t{i}", "src_nodeid": 1, "dst_nodeid": None}
        for i in range(24)
    ]
    pass1_result = PairSupportBuildResult(
        supports={(1, 2): pass1_support},
        unresolved_events=unresolved,
        graph_node_count=100,
        graph_edge_count=120,
        stitch_candidate_count=0,
        stitch_edge_count=0,
        stitch_query_count=40,
        stitch_candidates_total=0,
        stitch_reject_dist_count=0,
        stitch_reject_angle_count=0,
        stitch_reject_forward_count=0,
        stitch_accept_count=0,
        stitch_levels_used_hist={},
    )
    pass2_result = PairSupportBuildResult(
        supports={(1, 2): pass2_support},
        unresolved_events=[],
        graph_node_count=120,
        graph_edge_count=200,
        stitch_candidate_count=5,
        stitch_edge_count=5,
        stitch_query_count=40,
        stitch_candidates_total=5,
        stitch_reject_dist_count=0,
        stitch_reject_angle_count=0,
        stitch_reject_forward_count=0,
        stitch_accept_count=5,
        stitch_levels_used_hist={"25": 3},
    )

    monkeypatch.setattr(
        pipeline,
        "extract_crossing_events",
        lambda *args, **kwargs: CrossingExtractResult(
            events_by_traj={},
            raw_hit_count=0,
            dedup_drop_count=0,
            n_cross_empty_skipped=0,
            n_cross_geom_unexpected=0,
            n_cross_distance_gate_reject=0,
        ),
    )
    calls = {"n": 0}

    def _fake_build_pair_supports(*args, **kwargs):
        calls["n"] += 1
        return pass1_result if calls["n"] == 1 else pass2_result

    monkeypatch.setattr(pipeline, "build_pair_supports", _fake_build_pair_supports)
    monkeypatch.setattr(
        pipeline,
        "infer_node_types",
        lambda **kwargs: ({1: "unknown", 2: "unknown"}, {1: 0, 2: 0}, {1: 0, 2: 0}),
    )
    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: _mk_center(LineString([(0.0, 0.0), (120.0, 0.0)])),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: (
            {
                "traj_surface_enforced": False,
                "traj_in_ratio": None,
                "traj_in_ratio_est": None,
                "endpoint_in_traj_surface_src": None,
                "endpoint_in_traj_surface_dst": None,
            },
            set(),
            set(),
            [],
        ),
    )

    out = pipeline._run_patch_core(
        patch_inputs,
        params=dict(pipeline.DEFAULT_PARAMS),
        run_id="unit_run",
        repo_root=tmp_path,
    )
    assert calls["n"] >= 2
    assert out["metrics_payload"].get("neighbor_search_pass2_attempted") is True
    assert out["metrics_payload"].get("neighbor_search_pass2_used") is True
    assert out["metrics_payload"].get("neighbor_search_pass") == 2


def test_neighbor_pass2_is_triggered_when_unresolved_dense_with_cross_distance_reject(
    tmp_path: Path, monkeypatch
) -> None:
    xsecs = [
        CrossSection(nodeid=1, geometry_metric=LineString([(0.0, -2.0), (0.0, 2.0)]), properties={"nodeid": 1}),
        CrossSection(nodeid=2, geometry_metric=LineString([(120.0, -2.0), (120.0, 2.0)]), properties={"nodeid": 2}),
    ]
    patch_inputs = _mk_patch_inputs(tmp_path=tmp_path, intersection_lines=xsecs, trajectories=[])

    pass1_support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1"},
        support_event_count=1,
        repr_traj_ids=["t1"],
    )
    pass2_support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1", "t2", "t3"},
        support_event_count=3,
        repr_traj_ids=["t1", "t2", "t3"],
    )
    unresolved = [
        {"reason": "UNRESOLVED_NEIGHBOR", "traj_id": f"t{i}", "src_nodeid": 1, "dst_nodeid": None}
        for i in range(24)
    ]
    pass1_result = PairSupportBuildResult(
        supports={(1, 2): pass1_support},
        unresolved_events=unresolved,
        graph_node_count=100,
        graph_edge_count=120,
        stitch_candidate_count=10,
        stitch_edge_count=5,
        stitch_query_count=40,
        stitch_candidates_total=10,
        stitch_reject_dist_count=0,
        stitch_reject_angle_count=0,
        stitch_reject_forward_count=0,
        stitch_accept_count=5,
        stitch_levels_used_hist={"12": 5},
        next_crossing_candidates=[
            {
                "src_nodeid": 1,
                "src_cross_id": "t:cross:1",
                "traj_id": "t0",
                "seq_idx": 0,
                "station_m": 0.0,
                "src_point": Point(0.0, 0.0),
                "dst_candidates": [],
            }
        ],
    )
    pass2_result = PairSupportBuildResult(
        supports={(1, 2): pass2_support},
        unresolved_events=[],
        graph_node_count=120,
        graph_edge_count=200,
        stitch_candidate_count=20,
        stitch_edge_count=10,
        stitch_query_count=40,
        stitch_candidates_total=20,
        stitch_reject_dist_count=0,
        stitch_reject_angle_count=0,
        stitch_reject_forward_count=0,
        stitch_accept_count=10,
        stitch_levels_used_hist={"25": 3},
    )

    monkeypatch.setattr(
        pipeline,
        "extract_crossing_events",
        lambda *args, **kwargs: CrossingExtractResult(
            events_by_traj={},
            raw_hit_count=0,
            dedup_drop_count=0,
            n_cross_empty_skipped=0,
            n_cross_geom_unexpected=0,
            n_cross_distance_gate_reject=50,
        ),
    )
    calls = {"n": 0}

    def _fake_build_pair_supports(*args, **kwargs):
        calls["n"] += 1
        return pass1_result if calls["n"] == 1 else pass2_result

    monkeypatch.setattr(pipeline, "build_pair_supports", _fake_build_pair_supports)
    monkeypatch.setattr(
        pipeline,
        "infer_node_types",
        lambda **kwargs: ({1: "unknown", 2: "unknown"}, {1: 0, 2: 0}, {1: 0, 2: 0}),
    )
    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: _mk_center(LineString([(0.0, 0.0), (120.0, 0.0)])),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: (
            {
                "traj_surface_enforced": False,
                "traj_in_ratio": None,
                "traj_in_ratio_est": None,
                "endpoint_in_traj_surface_src": None,
                "endpoint_in_traj_surface_dst": None,
            },
            set(),
            set(),
            [],
        ),
    )

    out = pipeline._run_patch_core(
        patch_inputs,
        params=dict(pipeline.DEFAULT_PARAMS),
        run_id="unit_run",
        repo_root=tmp_path,
    )

    assert calls["n"] >= 2
    assert out["metrics_payload"].get("neighbor_search_pass2_attempted") is True
    assert out["metrics_payload"].get("neighbor_search_pass2_used") is True
    assert out["metrics_payload"].get("neighbor_search_pass") == 2


def test_surface_point_cache_skips_second_laz_read(tmp_path: Path, monkeypatch) -> None:
    xsec = CrossSection(
        nodeid=1,
        geometry_metric=LineString([(0.0, -2.0), (0.0, 2.0)]),
        properties={"nodeid": 1},
    )
    pc_path = tmp_path / "merged_cleaned_classified_3857.laz"
    pc_path.write_bytes(b"stub")
    patch_inputs = PatchInputs(
        patch_id="unit_patch",
        patch_dir=tmp_path,
        projection=ProjectionInfo(input_crs="EPSG:3857", metric_crs="EPSG:3857", projected=False),
        projection_to_metric=lambda geom: geom,
        projection_to_input=lambda geom: geom,
        intersection_lines=[xsec],
        lane_boundaries_metric=[],
        node_kind_map={},
        trajectories=[],
        drivezone_zone_metric=None,
        drivezone_source_path=None,
        divstrip_zone_metric=None,
        divstrip_source_path=None,
        point_cloud_path=pc_path,
        road_prior_path=None,
        tiles_dir=None,
        input_summary={},
    )
    params = dict(pipeline.DEFAULT_PARAMS)
    params["CACHE_ENABLED"] = 1

    call_count = {"n": 0}

    def _fake_load(*args, **kwargs):
        call_count["n"] += 1
        return PointCloudWindow(
            xyz_metric=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float64),
            bbox_point_count=2,
            selected_point_count=2,
            has_classification=True,
            used_class_filter=True,
            point_cloud_path=pc_path,
        )

    monkeypatch.setattr(pipeline, "load_point_cloud_window", _fake_load)

    xyz_1, stats_1 = pipeline._load_surface_points(patch_inputs, {}, params, use_pointcloud=True)
    xyz_2, stats_2 = pipeline._load_surface_points(patch_inputs, {}, params, use_pointcloud=True)

    assert xyz_1.shape == xyz_2.shape
    assert call_count["n"] == 1
    assert stats_1.get("pointcloud_cache_hit") is False
    assert stats_2.get("pointcloud_cache_hit") is True


def test_divstrip_intersection_prefers_gore_free_fallback(tmp_path: Path, monkeypatch) -> None:
    xsecs = [
        CrossSection(nodeid=1, geometry_metric=LineString([(0.0, -5.0), (0.0, 5.0)]), properties={"nodeid": 1}),
        CrossSection(nodeid=2, geometry_metric=LineString([(210.0, -5.0), (210.0, 5.0)]), properties={"nodeid": 2}),
    ]
    patch_inputs = PatchInputs(
        patch_id="unit_patch",
        patch_dir=tmp_path,
        projection=ProjectionInfo(input_crs="EPSG:3857", metric_crs="EPSG:3857", projected=False),
        projection_to_metric=lambda geom: geom,
        projection_to_input=lambda geom: geom,
        intersection_lines=xsecs,
        lane_boundaries_metric=[],
        node_kind_map={},
        trajectories=[],
        drivezone_zone_metric=None,
        drivezone_source_path=None,
        divstrip_zone_metric=Polygon([(90.0, -20.0), (120.0, -20.0), (120.0, 20.0), (90.0, 20.0)]),
        divstrip_source_path=tmp_path / "DivStripZone.geojson",
        point_cloud_path=None,
        road_prior_path=None,
        tiles_dir=None,
        input_summary={},
    )
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1"},
        support_event_count=1,
        repr_traj_ids=["t1"],
    )
    build_result = PairSupportBuildResult(
        supports={(1, 2): support},
        unresolved_events=[],
        graph_node_count=0,
        graph_edge_count=0,
        stitch_candidate_count=0,
        stitch_edge_count=0,
        stitch_query_count=0,
        stitch_candidates_total=0,
        stitch_reject_dist_count=0,
        stitch_reject_angle_count=0,
        stitch_reject_forward_count=0,
        stitch_accept_count=0,
        stitch_levels_used_hist={},
    )

    monkeypatch.setattr(
        pipeline,
        "extract_crossing_events",
        lambda *args, **kwargs: CrossingExtractResult(
            events_by_traj={},
            raw_hit_count=0,
            dedup_drop_count=0,
            n_cross_empty_skipped=0,
            n_cross_geom_unexpected=0,
            n_cross_distance_gate_reject=0,
        ),
    )
    monkeypatch.setattr(pipeline, "build_pair_supports", lambda *args, **kwargs: build_result)
    monkeypatch.setattr(
        pipeline,
        "infer_node_types",
        lambda **kwargs: ({1: "unknown", 2: "unknown"}, {1: 0, 2: 0}, {1: 0, 2: 0}),
    )
    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: _mk_center(LineString([(0.0, 0.0), (210.0, 0.0)])),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: (
            {
                "traj_surface_enforced": False,
                "traj_in_ratio": None,
                "traj_in_ratio_est": None,
                "endpoint_in_traj_surface_src": None,
                "endpoint_in_traj_surface_dst": None,
                "traj_surface_geom_type": None,
                "traj_surface_area_m2": None,
                "traj_surface_component_count": 0,
            },
            set(),
            set(),
            [],
        ),
    )

    out = pipeline._run_patch_core(
        patch_inputs,
        params=dict(pipeline.DEFAULT_PARAMS),
        run_id="unit_run",
        repo_root=tmp_path,
    )
    reasons = {str(bp.get("reason")) for bp in out["hard_breakpoints"]}
    assert "ROAD_INTERSECTS_DIVSTRIP" not in reasons
    assert out["road_count"] >= 1


def test_metrics_collect_offset_clamp_and_support_reason_stats(tmp_path: Path, monkeypatch) -> None:
    xsecs = [
        CrossSection(nodeid=1, geometry_metric=LineString([(0.0, -5.0), (0.0, 5.0)]), properties={"nodeid": 1}),
        CrossSection(nodeid=2, geometry_metric=LineString([(60.0, -5.0), (60.0, 5.0)]), properties={"nodeid": 2}),
    ]
    patch_inputs = _mk_patch_inputs(tmp_path=tmp_path, intersection_lines=xsecs, trajectories=[])
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1"},
        support_event_count=1,
        repr_traj_ids=["t1"],
    )
    build_result = PairSupportBuildResult(
        supports={(1, 2): support},
        unresolved_events=[],
        graph_node_count=0,
        graph_edge_count=0,
        stitch_candidate_count=0,
        stitch_edge_count=0,
        stitch_query_count=0,
        stitch_candidates_total=0,
        stitch_reject_dist_count=0,
        stitch_reject_angle_count=0,
        stitch_reject_forward_count=0,
        stitch_accept_count=0,
        stitch_levels_used_hist={},
    )
    monkeypatch.setattr(
        pipeline,
        "extract_crossing_events",
        lambda *args, **kwargs: CrossingExtractResult(
            events_by_traj={},
            raw_hit_count=0,
            dedup_drop_count=0,
            n_cross_empty_skipped=0,
            n_cross_geom_unexpected=0,
            n_cross_distance_gate_reject=0,
        ),
    )
    monkeypatch.setattr(pipeline, "build_pair_supports", lambda *args, **kwargs: build_result)
    monkeypatch.setattr(
        pipeline,
        "infer_node_types",
        lambda **kwargs: ({1: "unknown", 2: "unknown"}, {1: 0, 2: 0}, {1: 0, 2: 0}),
    )
    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: _mk_center(
            LineString([(0.0, 0.0), (30.0, 0.0), (60.0, 0.0)]),
            diagnostics={
                "offset_clamp_hit_ratio": 0.6,
                "offset_clamp_fallback_count": 2,
                "xsec_support_empty_reason_src": "xsec_support_empty",
                "xsec_support_empty_reason_dst": "support_disabled_due_to_insufficient",
                "endpoint_fallback_mode_src": "lb_path_guarded_fallback",
                "endpoint_fallback_mode_dst": "channel_fallback",
            },
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: (
            {
                "traj_surface_enforced": False,
                "traj_in_ratio": None,
                "traj_in_ratio_est": None,
                "endpoint_in_traj_surface_src": None,
                "endpoint_in_traj_surface_dst": None,
            },
            set(),
            set(),
            [],
        ),
    )

    out = pipeline._run_patch_core(
        patch_inputs,
        params=dict(pipeline.DEFAULT_PARAMS),
        run_id="unit_run",
        repo_root=tmp_path,
    )
    m = out["metrics_payload"]
    assert m.get("offset_clamp_hit_ratio_p90") == 0.6
    assert m.get("offset_clamp_fallback_count") == 2
    assert m.get("xsec_support_empty_src_count") == 1
    assert m.get("xsec_support_disabled_dst_count") == 1
    src_hist = dict(m.get("endpoint_fallback_mode_src_hist") or {})
    assert src_hist.get("lb_path_guarded_fallback") == 1


def test_debug_surface_dump_keeps_polygon_geometry() -> None:
    debug_layers = {
        "traj_surface_best_polygon": [],
        "traj_surface_best_boundary": [],
        "lb_path_best": [],
        "ref_axis_best": [],
        "xsec_valid_src": [],
        "xsec_valid_dst": [],
        "xsec_support_src": [],
        "xsec_support_dst": [],
        "road_outside_segments": [],
        "road_bridge_segments": [],
        "road_divstrip_intersections": [],
    }
    road = {
        "road_id": "1_2",
        "_traj_surface_geom_metric": Polygon([(0.0, -2.0), (10.0, -2.0), (10.0, 2.0), (0.0, 2.0)]),
        "_shape_ref_metric": LineString([(0.0, 0.0), (10.0, 0.0)]),
        "_geometry_metric": LineString([(0.0, 0.0), (10.0, 0.0)]),
        "lb_path_found": True,
        "traj_surface_enforced": True,
    }
    pipeline._collect_debug_layers_for_selected(
        debug_layers=debug_layers,
        road=road,
        src_xsec=LineString([(0.0, -5.0), (0.0, 5.0)]),
        dst_xsec=LineString([(10.0, -5.0), (10.0, 5.0)]),
        gore_zone_metric=None,
        bridge_max_seg_m=100.0,
    )
    assert len(debug_layers["traj_surface_best_polygon"]) == 1
    assert len(debug_layers["traj_surface_best_boundary"]) >= 1


def test_traj_surface_builder_outputs_polygon_and_histogram() -> None:
    ref_line = LineString([(0.0, 0.0), (100.0, 0.0)])
    xs = np.linspace(0.0, 100.0, 120)
    left = np.column_stack((xs, np.full_like(xs, -1.5)))
    right = np.column_stack((xs, np.full_like(xs, 1.5)))
    traj_xy = np.vstack((left, right)).astype(np.float64)

    params = dict(pipeline.DEFAULT_PARAMS)
    params.update(
        {
            "SURF_SLICE_STEP_M": 5.0,
            "SURF_SLICE_HALF_WIN_M": 2.0,
            "SURF_SLICE_HALF_WIN_LEVELS_M": [2.0, 5.0, 10.0],
            "TRAJ_SURF_MIN_POINTS_PER_SLICE": 5,
        }
    )
    built = pipeline._build_traj_surface_from_refline(
        ref_line=ref_line,
        traj_xy=traj_xy,
        gore_zone_metric=None,
        params=params,
    )

    surf = built.get("surface")
    assert surf is not None
    assert str(getattr(surf, "geom_type", "")) in {"Polygon", "MultiPolygon"}
    assert float(surf.area) > 0.0
    assert float(built.get("covered_length_ratio", 0.0)) > 0.9
    hist = dict(built.get("slice_half_win_used_hist") or {})
    assert len(hist) >= 1


def test_traj_surface_builder_endcap_clamp_limits_width() -> None:
    ref_line = LineString([(0.0, 0.0), (200.0, 0.0)])
    xs_mid = np.linspace(30.0, 170.0, 180)
    xs_src = np.linspace(0.0, 25.0, 40)
    xs_dst = np.linspace(175.0, 200.0, 40)
    mid_pts = np.vstack(
        (
            np.column_stack((xs_mid, np.full_like(xs_mid, -2.0))),
            np.column_stack((xs_mid, np.full_like(xs_mid, 2.0))),
        )
    )
    # 两端混入远离主通道的点，模拟端帽爆宽污染。
    src_noise = np.column_stack((np.repeat(xs_src, 2), np.tile(np.asarray([-120.0, 120.0]), xs_src.size)))
    dst_noise = np.column_stack((np.repeat(xs_dst, 2), np.tile(np.asarray([-120.0, 120.0]), xs_dst.size)))
    traj_xy = np.vstack((mid_pts, src_noise, dst_noise)).astype(np.float64)

    params = dict(pipeline.DEFAULT_PARAMS)
    params.update(
        {
            "SURF_SLICE_STEP_M": 5.0,
            "SURF_SLICE_HALF_WIN_M": 2.0,
            "SURF_SLICE_HALF_WIN_LEVELS_M": [2.0, 5.0, 10.0],
            "TRAJ_SURF_MIN_POINTS_PER_SLICE": 5,
            "AXIS_MAX_PROJECT_DIST_M": 200.0,
            "ENDCAP_M": 30.0,
            "ENDCAP_WIDTH_ABS_CAP_M": 40.0,
            "ENDCAP_WIDTH_REL_CAP": 2.0,
        }
    )
    built = pipeline._build_traj_surface_from_refline(
        ref_line=ref_line,
        traj_xy=traj_xy,
        gore_zone_metric=None,
        params=params,
    )
    assert float(built.get("endcap_width_src_before_m") or 0.0) > 40.0
    assert float(built.get("endcap_width_src_after_m") or 0.0) <= 40.0 + 1e-6
    assert int(built.get("endcap_width_clamped_src_count") or 0) > 0


def test_finalize_payloads_emits_empty_xsec_support_layers(tmp_path: Path) -> None:
    payload = pipeline._finalize_payloads(
        run_id="unit_run",
        repo_root=tmp_path,
        patch_id="unit_patch",
        roads=[],
        road_lines_metric=[],
        road_feature_props=[],
        hard_breakpoints=[],
        soft_breakpoints=[],
        params=dict(pipeline.DEFAULT_PARAMS),
        overall_pass=True,
        debug_layers={
            "xsec_support_src": [],
            "xsec_support_dst": [],
        },
    )
    debug_fc = payload.get("debug_feature_collections") or {}
    assert "debug/xsec_support_src.geojson" in debug_fc
    assert "debug/xsec_support_dst.geojson" in debug_fc
    assert debug_fc["debug/xsec_support_src.geojson"]["features"] == []
    assert debug_fc["debug/xsec_support_dst.geojson"]["features"] == []


def test_divstrip_intersection_hard_when_no_gore_free_fallback(tmp_path: Path, monkeypatch) -> None:
    xsecs = [
        CrossSection(nodeid=1, geometry_metric=LineString([(0.0, -5.0), (0.0, 5.0)]), properties={"nodeid": 1}),
        CrossSection(nodeid=2, geometry_metric=LineString([(10.0, -5.0), (10.0, 5.0)]), properties={"nodeid": 2}),
    ]
    patch_inputs = PatchInputs(
        patch_id="unit_patch",
        patch_dir=tmp_path,
        projection=ProjectionInfo(input_crs="EPSG:3857", metric_crs="EPSG:3857", projected=False),
        projection_to_metric=lambda geom: geom,
        projection_to_input=lambda geom: geom,
        intersection_lines=xsecs,
        lane_boundaries_metric=[],
        node_kind_map={},
        trajectories=[],
        drivezone_zone_metric=None,
        drivezone_source_path=None,
        divstrip_zone_metric=Polygon([(-50.0, -30.0), (80.0, -30.0), (80.0, 30.0), (-50.0, 30.0)]),
        divstrip_source_path=tmp_path / "DivStripZone.geojson",
        point_cloud_path=None,
        road_prior_path=None,
        tiles_dir=None,
        input_summary={},
    )
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1"},
        support_event_count=1,
        repr_traj_ids=["t1"],
    )
    build_result = PairSupportBuildResult(
        supports={(1, 2): support},
        unresolved_events=[],
        graph_node_count=0,
        graph_edge_count=0,
        stitch_candidate_count=0,
        stitch_edge_count=0,
        stitch_query_count=0,
        stitch_candidates_total=0,
        stitch_reject_dist_count=0,
        stitch_reject_angle_count=0,
        stitch_reject_forward_count=0,
        stitch_accept_count=0,
        stitch_levels_used_hist={},
    )

    monkeypatch.setattr(
        pipeline,
        "extract_crossing_events",
        lambda *args, **kwargs: CrossingExtractResult(
            events_by_traj={},
            raw_hit_count=0,
            dedup_drop_count=0,
            n_cross_empty_skipped=0,
            n_cross_geom_unexpected=0,
            n_cross_distance_gate_reject=0,
        ),
    )
    monkeypatch.setattr(pipeline, "build_pair_supports", lambda *args, **kwargs: build_result)
    monkeypatch.setattr(
        pipeline,
        "infer_node_types",
        lambda **kwargs: ({1: "unknown", 2: "unknown"}, {1: 0, 2: 0}, {1: 0, 2: 0}),
    )
    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: _mk_center(LineString([(0.0, 0.0), (10.0, 0.0)])),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: (
            {
                "traj_surface_enforced": False,
                "traj_in_ratio": None,
                "traj_in_ratio_est": None,
                "endpoint_in_traj_surface_src": None,
                "endpoint_in_traj_surface_dst": None,
                "traj_surface_geom_type": None,
                "traj_surface_area_m2": None,
                "traj_surface_component_count": 0,
            },
            set(),
            set(),
            [],
        ),
    )

    out = pipeline._run_patch_core(
        patch_inputs,
        params=dict(pipeline.DEFAULT_PARAMS),
        run_id="unit_run",
        repo_root=tmp_path,
    )
    reasons = {str(bp.get("reason")) for bp in out["hard_breakpoints"]}
    assert "ROAD_INTERSECTS_DIVSTRIP" in reasons


def test_candidate_sort_prefers_geometry_even_if_feasible_lower() -> None:
    no_geom = {
        "_candidate_has_geometry": False,
        "_candidate_feasible": True,
        "_candidate_score": 99.0,
        "_candidate_in_ratio": 0.0,
        "max_segment_m": None,
        "support_traj_count": 5,
        "candidate_cluster_id": 1,
    }
    with_geom = {
        "_candidate_has_geometry": True,
        "_candidate_feasible": False,
        "_candidate_score": -50.0,
        "_candidate_in_ratio": 0.2,
        "max_segment_m": 50.0,
        "support_traj_count": 1,
        "candidate_cluster_id": 0,
    }
    ranked = sorted([no_geom, with_geom], key=pipeline._candidate_sort_key, reverse=True)
    assert ranked[0] is with_geom


def test_finalize_payloads_road_count_matches_written_features(tmp_path: Path) -> None:
    roads = [
        {
            "road_id": "1_2",
            "src_nodeid": 1,
            "dst_nodeid": 2,
            "conf": 0.0,
            "center_sample_coverage": 0.0,
            "soft_issue_flags": [],
            "hard_anomaly": True,
            "_geometry_metric": None,
        }
    ]
    payload = pipeline._finalize_payloads(
        run_id="unit_run",
        repo_root=tmp_path,
        patch_id="unit_patch",
        roads=roads,
        road_lines_metric=[],
        road_feature_props=[],
        hard_breakpoints=[],
        soft_breakpoints=[],
        params=dict(pipeline.DEFAULT_PARAMS),
        overall_pass=False,
    )
    metrics = payload["metrics_payload"]
    assert metrics.get("road_count") == 0
    assert metrics.get("road_features_count") == 0
    assert metrics.get("road_candidate_count") == 1
    assert metrics.get("no_geometry_candidate") is True
    summary = str(payload.get("summary_text") or "")
    assert "road_features_count: 0" in summary
    assert "road_candidate_count: 1" in summary
    assert "no_geometry_candidate: true" in summary
