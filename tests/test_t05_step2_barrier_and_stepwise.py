from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon

from highway_topo_poc.modules.t05_topology_between_rc.geometry import (
    CenterEstimate,
    HARD_ENDPOINT_OFF_ANCHOR,
    _EndStableDecision,
    _apply_endpoint_trend_projection,
    _build_xsec_road_for_endpoint,
    _choose_shape_ref_with_graph,
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


def test_step1_seed_selected_is_projected_from_selected_corridor() -> None:
    support = PairSupport(
        src_nodeid=110,
        dst_nodeid=210,
        support_traj_ids={"main"},
        support_event_count=1,
        traj_segments=[LineString([(0.0, 2.0), (50.0, 2.0), (100.0, 2.0)])],
        src_cross_points=[Point(12.0, 12.0)],
        dst_cross_points=[Point(88.0, 12.0)],
        evidence_traj_ids=["main"],
        cluster_count=1,
        main_cluster_ratio=1.0,
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

    cp_src = out.get("cross_point_src")
    cp_dst = out.get("cross_point_dst")
    assert isinstance(cp_src, Point)
    assert isinstance(cp_dst, Point)
    assert float(cp_src.distance(src_xsec)) <= 1e-6
    assert float(cp_dst.distance(dst_xsec)) <= 1e-6
    # should not keep the raw off-xsec fallback cross points.
    assert float(cp_src.distance(Point(12.0, 12.0))) > 1.0
    assert float(cp_dst.distance(Point(88.0, 12.0))) > 1.0


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
        params={
            "STEP1_MULTI_CORRIDOR_DIST_M": 8.0,
            "STEP1_MULTI_CORRIDOR_MIN_RATIO": 0.6,
            "STEP1_CORRIDOR_REACH_XSEC_M": 80.0,
        },
    )

    line = out.get("shape_ref_line")
    assert isinstance(line, LineString)
    assert out.get("hard_reason") is None
    assert bool(out.get("multi_corridor_detected")) is True
    assert int(out.get("corridor_count", 0)) == 1
    assert len(list(out.get("candidate_topk") or [])) >= 2


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
            "STEP1_CORRIDOR_REACH_XSEC_M": 80.0,
        },
    )

    assert str(out.get("hard_reason")) == str(pipeline.HARD_MULTI_CORRIDOR)
    assert out.get("shape_ref_line") is None


def test_pair_cluster_is_disabled_when_xsec_gate_enabled() -> None:
    support = PairSupport(
        src_nodeid=501,
        dst_nodeid=601,
        support_traj_ids={"a", "b", "c"},
        support_event_count=3,
        traj_segments=[
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            LineString([(0.0, 8.0), (100.0, 8.0)]),
            LineString([(0.0, -8.0), (100.0, -8.0)]),
        ],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 8.0), Point(0.0, -8.0)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 8.0), Point(100.0, -8.0)],
        evidence_traj_ids=["a", "b", "c"],
        evidence_cluster_ids=[2, 1, 2],
        hard_anomalies={pipeline.HARD_MULTI_ROAD, pipeline.HARD_NON_RC},
        cluster_count=4,
        main_cluster_id=2,
        main_cluster_ratio=0.5,
        cluster_sep_m_est=42.0,
        cluster_sizes=[1, 2, 0, 0],
    )
    supports = {(501, 601): support}

    stats = pipeline._normalize_support_clusters_for_xsec_gate(supports=supports, enabled=True)

    assert bool(stats.get("step1_pair_cluster_disabled")) is True
    assert int(stats.get("step1_pair_cluster_disabled_pair_count", 0)) == 1
    assert int(stats.get("step1_pair_cluster_disabled_event_count", 0)) == 3
    assert int(stats.get("step1_pair_cluster_disabled_hard_multi_removed_count", 0)) == 1
    assert pipeline.HARD_MULTI_ROAD not in support.hard_anomalies
    assert pipeline.HARD_NON_RC in support.hard_anomalies
    assert int(support.cluster_count) == 1
    assert int(support.main_cluster_id) == 0
    assert float(support.main_cluster_ratio) == 1.0
    assert support.cluster_sep_m_est is None
    assert support.cluster_sizes == [3]
    assert support.evidence_cluster_ids == [0, 0, 0]


def test_pair_cluster_kept_when_gate_disable_switch_off() -> None:
    support = PairSupport(
        src_nodeid=502,
        dst_nodeid=602,
        support_traj_ids={"a", "b"},
        support_event_count=2,
        traj_segments=[LineString([(0.0, 0.0), (100.0, 0.0)]), LineString([(0.0, 10.0), (100.0, 10.0)])],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 10.0)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 10.0)],
        evidence_traj_ids=["a", "b"],
        evidence_cluster_ids=[1, 0],
        hard_anomalies={pipeline.HARD_MULTI_ROAD},
        cluster_count=2,
        main_cluster_id=1,
        main_cluster_ratio=0.5,
        cluster_sep_m_est=20.0,
        cluster_sizes=[1, 1],
    )
    supports = {(502, 602): support}

    stats = pipeline._normalize_support_clusters_for_xsec_gate(supports=supports, enabled=False)

    assert bool(stats.get("step1_pair_cluster_disabled")) is False
    assert pipeline.HARD_MULTI_ROAD in support.hard_anomalies
    assert int(support.cluster_count) == 2
    assert support.evidence_cluster_ids == [1, 0]


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


def test_xsec_gate_prefers_traj_evidence_segment() -> None:
    xsec = CrossSection(
        nodeid=9,
        geometry_metric=LineString([(0.0, -60.0), (0.0, 60.0)]),
        properties={"nodeid": 9},
    )
    drivezone_upper = Polygon([(-20.0, 10.0), (20.0, 10.0), (20.0, 20.0), (-20.0, 20.0)])
    drivezone_lower = Polygon([(-20.0, -20.0), (20.0, -20.0), (20.0, -10.0), (-20.0, -10.0)])
    drivezone = drivezone_upper.union(drivezone_lower)

    traj = SimpleNamespace(
        xyz_metric=np.asarray([[-30.0, 15.0, 0.0], [30.0, 15.0, 0.0]], dtype=np.float64),
    )

    out_map, _anchors, _trunc, _gate_all_map, gate_meta_map, _stats = pipeline._truncate_cross_sections_for_crossing(
        xsec_map={9: xsec},
        lane_boundaries_metric=[],
        trajectories=[traj],
        drivezone_zone_metric=drivezone,
        gore_zone_metric=None,
        params=dict(pipeline.DEFAULT_PARAMS),
    )
    got = out_map[9].geometry_metric
    mid = got.interpolate(0.5, normalized=True)
    assert float(mid.y) > 0.0
    meta = gate_meta_map.get(9) or {}
    assert str(meta.get("selected_by")) == "traj_evidence_midpoint_longest_tiebreak"
    assert float(meta.get("selected_evidence_len_m") or 0.0) > 0.0


def test_xsec_gate_does_not_use_far_evidence_segment() -> None:
    xsec = CrossSection(
        nodeid=11,
        geometry_metric=LineString([(0.0, -80.0), (0.0, 80.0)]),
        properties={"nodeid": 11},
    )
    drivezone_near = Polygon([(-20.0, 10.0), (20.0, 10.0), (20.0, 20.0), (-20.0, 20.0)])
    drivezone_far = Polygon([(-20.0, 45.0), (20.0, 45.0), (20.0, 55.0), (-20.0, 55.0)])
    drivezone = drivezone_near.union(drivezone_far)

    traj = SimpleNamespace(
        xyz_metric=np.asarray([[-30.0, 50.0, 0.0], [30.0, 50.0, 0.0]], dtype=np.float64),
    )

    params = dict(pipeline.DEFAULT_PARAMS)
    params["XSEC_GATE_EVIDENCE_MID_MARGIN_M"] = 8.0
    params["XSEC_GATE_EVIDENCE_MIN_LEN_M"] = 0.5
    out_map, _anchors, _trunc, _gate_all_map, gate_meta_map, _stats = pipeline._truncate_cross_sections_for_crossing(
        xsec_map={11: xsec},
        lane_boundaries_metric=[],
        trajectories=[traj],
        drivezone_zone_metric=drivezone,
        gore_zone_metric=None,
        params=params,
    )
    got = out_map[11].geometry_metric
    mid = got.interpolate(0.5, normalized=True)
    assert float(mid.y) < 30.0
    meta = gate_meta_map.get(11) or {}
    assert str(meta.get("selected_by")) == "nearest_midpoint_longest_tiebreak"


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


def test_preferred_shape_ref_is_rejected_when_far_from_surface() -> None:
    support = PairSupport(
        src_nodeid=10,
        dst_nodeid=20,
        support_traj_ids={"t0"},
        support_event_count=1,
        traj_segments=[LineString([(0.0, 0.0), (100.0, 0.0)])],
        src_cross_points=[Point(0.0, 0.0)],
        dst_cross_points=[Point(100.0, 0.0)],
        evidence_traj_ids=["t0"],
    )
    src_xsec = LineString([(0.0, -10.0), (0.0, 10.0)])
    dst_xsec = LineString([(100.0, -10.0), (100.0, 10.0)])
    preferred_far = LineString([(0.0, 80.0), (100.0, 80.0)])
    lane_boundaries = [LineString([(0.0, 0.0), (100.0, 0.0)])]
    traj_surface = Polygon([(-10.0, -8.0), (110.0, -8.0), (110.0, 8.0), (-10.0, 8.0)])

    choice = _choose_shape_ref_with_graph(
        support=support,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        lane_boundaries_metric=lane_boundaries,
        lb_snap_m=2.0,
        lb_start_end_topk=3,
        traj_surface_metric=traj_surface,
        preferred_shape_ref_metric=preferred_far,
    )

    assert bool(choice.used_lane_boundary) is True
    assert isinstance(choice.line, LineString)
    assert float(choice.line.distance(preferred_far)) > 20.0
    assert float(choice.line.distance(lane_boundaries[0])) <= 1e-6


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


def test_center_empty_fallback_still_outputs_step2_step3(monkeypatch: pytest.MonkeyPatch) -> None:
    shape_ref = LineString([(0.0, 0.0), (100.0, 0.0)])
    src_xsec = LineString([(0.0, -10.0), (0.0, 10.0)])
    dst_xsec = LineString([(100.0, -10.0), (100.0, 10.0)])

    fake_center = CenterEstimate(
        centerline_metric=None,
        shape_ref_metric=shape_ref,
        lb_path_found=False,
        lb_path_edge_count=0,
        lb_path_length_m=None,
        stable_offset_m_src=None,
        stable_offset_m_dst=None,
        center_sample_coverage=0.0,
        width_med_m=None,
        width_p90_m=None,
        max_turn_deg_per_10m=None,
        used_lane_boundary=False,
        src_is_gore_tip=False,
        dst_is_gore_tip=False,
        src_is_expanded=False,
        dst_is_expanded=False,
        src_width_near_m=None,
        dst_width_near_m=None,
        src_width_base_m=None,
        dst_width_base_m=None,
        src_gore_overlap_near=None,
        dst_gore_overlap_near=None,
        src_stable_s_m=None,
        dst_stable_s_m=None,
        src_cut_mode="na",
        dst_cut_mode="na",
        endpoint_tangent_deviation_deg_src=None,
        endpoint_tangent_deviation_deg_dst=None,
        endpoint_center_offset_m_src=None,
        endpoint_center_offset_m_dst=None,
        endpoint_proj_dist_to_core_m_src=None,
        endpoint_proj_dist_to_core_m_dst=None,
        soft_flags=set(),
        hard_flags={pipeline.HARD_CENTER_EMPTY},
        diagnostics={},
    )

    def _fake_estimate_centerline(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return fake_center

    def _fake_eval_traj_surface_gate(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return {}, set(), set(), []

    monkeypatch.setattr(pipeline, "estimate_centerline", _fake_estimate_centerline)
    monkeypatch.setattr(pipeline, "_eval_traj_surface_gate", _fake_eval_traj_surface_gate)

    support = PairSupport(
        src_nodeid=10,
        dst_nodeid=20,
        support_traj_ids={"t0"},
        support_event_count=1,
        traj_segments=[LineString([(0.0, 0.0), (100.0, 0.0)])],
        src_cross_points=[Point(0.0, 0.0)],
        dst_cross_points=[Point(100.0, 0.0)],
        evidence_traj_ids=["t0"],
        cluster_count=1,
        main_cluster_ratio=1.0,
    )

    road = pipeline._evaluate_candidate_road(
        src=10,
        dst=20,
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
        patch_inputs=SimpleNamespace(drivezone_zone_metric=None, trajectories=[]),
        gore_zone_metric=None,
        params=dict(pipeline.DEFAULT_PARAMS),
        traj_surface_hint={
            "surface_metric": None,
            "traj_surface_enforced": False,
            "axis_source": "test",
            "reason": "test",
            "valid_slices": 0,
            "total_slices": 0,
            "slice_valid_ratio": 0.0,
            "covered_length_ratio": 0.0,
        },
        shape_ref_hint_metric=shape_ref,
    )

    assert isinstance(road.get("_xsec_road_selected_dst_metric"), LineString)
    assert str(road.get("xsec_road_selected_by_dst")).startswith("fallback_seed_due_center_empty")
    assert isinstance(road.get("_endpoint_after_dst_metric"), Point)
    assert road.get("endpoint_dist_to_xsec_dst_m") is not None
    assert pipeline.HARD_CENTER_EMPTY not in set(road.get("hard_reasons", []))
    assert bool(road.get("center_estimate_empty_downgraded", False)) is True


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
