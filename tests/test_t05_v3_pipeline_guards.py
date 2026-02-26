from __future__ import annotations

from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from highway_topo_poc.modules.t05_topology_between_rc import pipeline
from highway_topo_poc.modules.t05_topology_between_rc.geometry import (
    CenterEstimate,
    CrossingExtractResult,
    PairSupport,
    PairSupportBuildResult,
    _project_endpoint_to_valid_xsec,
)
from highway_topo_poc.modules.t05_topology_between_rc.io import (
    CrossSection,
    PatchInputs,
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
        divstrip_zone_metric=None,
        divstrip_source_path=None,
        point_cloud_path=None,
        road_prior_path=None,
        tiles_dir=None,
        input_summary={},
    )


def _mk_center(line: LineString) -> CenterEstimate:
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
        soft_flags=set(),
        hard_flags=set(),
        diagnostics={},
    )


def test_endpoint_projection_prefers_gore_free_xsec_piece() -> None:
    xsec = LineString([(0.0, -8.0), (0.0, 8.0)])
    gore = Polygon([(-1.0, -2.0), (1.0, -2.0), (1.0, 2.0), (-1.0, 2.0)])

    out_xy = _project_endpoint_to_valid_xsec(
        endpoint_xy=(0.0, 0.0),
        xsec=xsec,
        gore_zone_metric=gore,
        channel_ref_xy=(0.0, 4.0),
    )
    out_pt = Point(float(out_xy[0]), float(out_xy[1]))

    assert out_pt.distance(xsec) <= 1e-6
    assert not gore.contains(out_pt)
    assert out_xy[1] >= 2.0


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
    assert not soft_flags
    assert any(str(bp.get("severity")) == "hard" for bp in breakpoints)


def test_bridge_guard_marks_hard_for_long_segment(tmp_path: Path, monkeypatch) -> None:
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
    assert "BRIDGE_SEGMENT_TOO_LONG" in reasons


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
