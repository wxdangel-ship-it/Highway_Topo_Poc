from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from highway_topo_poc.modules.t05_topology_between_rc import io, pipeline
from highway_topo_poc.modules.t05_topology_between_rc.geometry import (
    CenterEstimate,
    HARD_ROAD_OUTSIDE_DRIVEZONE,
    PairSupport,
    _build_xsec_passable_samples,
)
from highway_topo_poc.modules.t05_topology_between_rc.io import CrossSection, PatchInputs, ProjectionInfo


def _write_fc(path: Path, *, crs: str, features: list[dict]) -> None:
    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": crs}},
        "features": features,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _mk_patch_inputs(tmp_path: Path, *, drivezone: Polygon, point_cloud_path: Path | None = None) -> PatchInputs:
    xsecs = [
        CrossSection(nodeid=1, geometry_metric=LineString([(0.0, -5.0), (0.0, 5.0)]), properties={"nodeid": 1}),
        CrossSection(nodeid=2, geometry_metric=LineString([(100.0, -5.0), (100.0, 5.0)]), properties={"nodeid": 2}),
    ]
    return PatchInputs(
        patch_id="unit_patch",
        patch_dir=tmp_path,
        projection=ProjectionInfo(input_crs="EPSG:3857", metric_crs="EPSG:3857", projected=False),
        projection_to_metric=lambda geom: geom,
        projection_to_input=lambda geom: geom,
        intersection_lines=xsecs,
        lane_boundaries_metric=[],
        node_kind_map={},
        trajectories=[],
        drivezone_zone_metric=drivezone,
        drivezone_source_path=tmp_path / "Vector" / "DriveZone.geojson",
        divstrip_zone_metric=None,
        divstrip_source_path=None,
        point_cloud_path=point_cloud_path,
        road_prior_path=None,
        tiles_dir=None,
        input_summary={"drivezone_src_crs": "EPSG:3857"},
    )


def _mk_center(line: LineString, shape_ref: LineString) -> CenterEstimate:
    return CenterEstimate(
        centerline_metric=line,
        shape_ref_metric=shape_ref,
        lb_path_found=True,
        lb_path_edge_count=1,
        lb_path_length_m=float(shape_ref.length),
        stable_offset_m_src=0.0,
        stable_offset_m_dst=0.0,
        center_sample_coverage=1.0,
        width_med_m=8.0,
        width_p90_m=9.0,
        max_turn_deg_per_10m=0.0,
        used_lane_boundary=True,
        src_is_gore_tip=False,
        dst_is_gore_tip=False,
        src_is_expanded=False,
        dst_is_expanded=False,
        src_width_near_m=8.0,
        dst_width_near_m=8.0,
        src_width_base_m=8.0,
        dst_width_base_m=8.0,
        src_gore_overlap_near=0.0,
        dst_gore_overlap_near=0.0,
        src_stable_s_m=10.0,
        dst_stable_s_m=10.0,
        src_cut_mode="stable_section",
        dst_cut_mode="stable_section",
        endpoint_tangent_deviation_deg_src=0.0,
        endpoint_tangent_deviation_deg_dst=0.0,
        endpoint_center_offset_m_src=0.0,
        endpoint_center_offset_m_dst=0.0,
        endpoint_proj_dist_to_core_m_src=0.0,
        endpoint_proj_dist_to_core_m_dst=0.0,
        soft_flags=set(),
        hard_flags=set(),
        diagnostics={
            "endpoint_dist_to_xsec_src_m": 0.0,
            "endpoint_dist_to_xsec_dst_m": 0.0,
            "endpoint_snap_dist_src_after_m": 0.0,
            "endpoint_snap_dist_dst_after_m": 0.0,
        },
    )


def test_drivezone_union_crs(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    patch_id = "p1"
    patch_dir = data_root / patch_id
    vector_dir = patch_dir / "Vector"
    traj_file = patch_dir / "Traj" / "t0" / "raw_dat_pose.geojson"

    _write_fc(
        vector_dir / "intersection_l.geojson",
        crs="EPSG:3857",
        features=[
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.0, -5.0], [0.0, 5.0]]},
                "properties": {"nodeid": 1},
            }
        ],
    )
    _write_fc(
        vector_dir / "DriveZone.geojson",
        crs="EPSG:4326",
        features=[
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0.0, 0.0], [0.001, 0.0], [0.001, 0.001], [0.0, 0.001], [0.0, 0.0]]],
                },
                "properties": {},
            }
        ],
    )
    _write_fc(
        traj_file,
        crs="EPSG:3857",
        features=[
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.0, 0.0, 0.0]}, "properties": {"seq": 0}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 0.0, 0.0]}, "properties": {"seq": 1}},
        ],
    )

    loaded = io.load_patch_inputs(data_root, patch_id=patch_id)
    assert loaded.input_summary.get("drivezone_src_crs") == "EPSG:4326"
    assert loaded.drivezone_zone_metric is not None and not loaded.drivezone_zone_metric.is_empty
    assert float(loaded.drivezone_zone_metric.area) > 0.0


def test_drivezone_priority_over_traj(tmp_path: Path, monkeypatch) -> None:
    src_xsec = LineString([(0.0, -5.0), (0.0, 5.0)])
    dst_xsec = LineString([(100.0, -5.0), (100.0, 5.0)])
    centerline = LineString([(0.0, 0.0), (100.0, 0.0)])
    shape_ref = LineString([(0.0, 0.0), (100.0, 0.0)])
    drivezone = Polygon([(0.0, 20.0), (100.0, 20.0), (100.0, 30.0), (0.0, 30.0)])

    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1"},
        support_event_count=1,
        traj_segments=[LineString([(0.0, 0.0), (100.0, 0.0)])],
        src_cross_points=[Point(0.0, 0.0)],
        dst_cross_points=[Point(100.0, 0.0)],
        evidence_traj_ids=["t1"],
    )
    patch_inputs = _mk_patch_inputs(tmp_path, drivezone=drivezone)
    params = dict(pipeline.DEFAULT_PARAMS)

    def _fake_centerline(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return _mk_center(centerline, shape_ref)

    def _fake_traj_gate(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return (
            {
                "traj_surface_enforced": True,
                "traj_in_ratio": 1.0,
                "traj_in_ratio_est": 1.0,
                "endpoint_in_traj_surface_src": True,
                "endpoint_in_traj_surface_dst": True,
            },
            set(),
            set(),
            [],
        )

    monkeypatch.setattr(pipeline, "estimate_centerline", _fake_centerline)
    monkeypatch.setattr(pipeline, "_eval_traj_surface_gate", _fake_traj_gate)

    road = pipeline._evaluate_candidate_road(
        src=1,
        dst=2,
        src_type="merge",
        dst_type="merge",
        support=support,
        parent_support=support,
        cluster_id=0,
        neighbor_search_pass=1,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        src_out_degree=1,
        dst_in_degree=1,
        lane_boundaries_metric=[],
        surface_points_xyz=np.empty((0, 3), dtype=np.float64),
        non_ground_xy=np.empty((0, 2), dtype=np.float64),
        patch_inputs=patch_inputs,
        gore_zone_metric=None,
        params=params,
        traj_surface_hint={"traj_surface_enforced": True, "surface_metric": drivezone},
        shape_ref_hint_metric=shape_ref,
    )
    assert HARD_ROAD_OUTSIDE_DRIVEZONE in set(road.get("hard_reasons", []))


def test_no_pointcloud_default(tmp_path: Path, monkeypatch) -> None:
    drivezone = Polygon([(-50.0, -50.0), (150.0, -50.0), (150.0, 50.0), (-50.0, 50.0)])
    pc_path = tmp_path / "PointCloud" / "merged_cleaned_classified_3857.laz"
    pc_path.parent.mkdir(parents=True, exist_ok=True)
    pc_path.write_bytes(b"fake")
    patch_inputs = _mk_patch_inputs(tmp_path, drivezone=drivezone, point_cloud_path=pc_path)
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1"},
        support_event_count=1,
        traj_segments=[LineString([(0.0, 0.0), (100.0, 0.0)])],
    )

    def _raise_if_called(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise AssertionError("pointcloud should not be loaded when POINTCLOUD_ENABLE=0")

    monkeypatch.setattr(pipeline, "load_point_cloud_window", _raise_if_called)
    xyz, ng_xy, stats = pipeline._load_surface_points(
        patch_inputs,
        {(1, 2): support},
        params=dict(pipeline.DEFAULT_PARAMS),
        use_pointcloud=False,
        with_non_ground=True,
    )
    assert xyz.shape[0] >= 1
    assert ng_xy.shape[0] == 0
    assert bool(stats.get("pointcloud_attempted")) is False


def test_divstrip_still_hard() -> None:
    line = LineString([(0.0, -10.0), (0.0, 10.0)])
    drivezone = Polygon([(-5.0, -20.0), (5.0, -20.0), (5.0, 20.0), (-5.0, 20.0)])
    divstrip = Polygon([(-2.0, -2.0), (2.0, -2.0), (2.0, 2.0), (-2.0, 2.0)])

    samples, _ratio, cand_n, final_n = _build_xsec_passable_samples(
        line=line,
        drivezone_zone_metric=drivezone,
        gore_zone_metric=divstrip,
        sample_step_m=1.0,
        barrier_min_len_m=1.0,
    )

    assert int(cand_n) >= 1
    assert int(final_n) >= 1
    assert any(
        bool(s.get("in_drivezone")) and bool(s.get("in_divstrip")) and (not bool(s.get("passable")))
        and str(s.get("stop_reason")) == "in_divstrip"
        for s in samples
    )
