from __future__ import annotations

from pathlib import Path

import json
from shapely.geometry import LineString, Point

from highway_topo_poc.modules.t05_topology_between_rc import geometry as geom_mod
from highway_topo_poc.modules.t05_topology_between_rc import pipeline
from highway_topo_poc.modules.t05_topology_between_rc.geometry import (
    CrossingEvent,
    CrossingExtractResult,
    HARD_MULTI_NEIGHBOR_FOR_NODE,
    PairSupport,
    PairSupportBuildResult,
    SOFT_AMBIGUOUS_NEXT_XSEC,
)
from highway_topo_poc.modules.t05_topology_between_rc.io import CrossSection, PatchInputs, ProjectionInfo


def _mk_patch_inputs(*, tmp_path: Path, xsecs: list[CrossSection]) -> PatchInputs:
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
        drivezone_zone_metric=None,
        drivezone_source_path=None,
        divstrip_zone_metric=None,
        divstrip_source_path=None,
        point_cloud_path=None,
        road_prior_path=None,
        tiles_dir=None,
        input_summary={},
    )


def _mk_xsec(nodeid: int, x: float) -> CrossSection:
    return CrossSection(
        nodeid=int(nodeid),
        geometry_metric=LineString([(float(x), -5.0), (float(x), 5.0)]),
        properties={"nodeid": int(nodeid)},
    )


def test_load_road_prior_adjacency_parses_direction_and_fields(tmp_path: Path) -> None:
    road_path = tmp_path / "RCSDRoad.geojson"
    payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 1, "enodeid": 2, "direction": 2}},
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 3, "enodeid": 4, "direction": 3}},
            {"type": "Feature", "geometry": None, "properties": {"src": 5, "dst": 6}},
        ],
    }
    road_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    adj, stats = pipeline._load_road_prior_adjacency(road_path, respect_direction=True)

    assert 2 in adj.get(1, set())
    assert 3 in adj.get(4, set())
    assert 6 in adj.get(5, set())
    assert 5 in adj.get(6, set())
    assert int(stats.get("edge_count", 0)) >= 4


def test_load_road_prior_adjacency_defaults_to_undirected(tmp_path: Path) -> None:
    road_path = tmp_path / "RCSDRoad.geojson"
    payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 10, "enodeid": 20, "direction": 2}},
        ],
    }
    road_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    adj, stats = pipeline._load_road_prior_adjacency(road_path)

    assert 20 in adj.get(10, set())
    assert 10 in adj.get(20, set())
    assert bool(stats.get("respect_direction")) is False


def test_crossing_absorbing_state_prevents_third_party_crossing_expansion() -> None:
    src_key = "t:cross:1"
    mid_key = "t:cross:2"
    dst_key = "u:cross:3"
    nodes = {
        src_key: geom_mod._GraphNode(
            key=src_key,
            traj_id="t",
            kind="cross",
            station_m=0.0,
            point=Point(0.0, 0.0),
            heading_xy=(1.0, 0.0),
            cross_nodeid=1,
            seq_idx=0,
        ),
        mid_key: geom_mod._GraphNode(
            key=mid_key,
            traj_id="t",
            kind="cross",
            station_m=10.0,
            point=Point(10.0, 0.0),
            heading_xy=(1.0, 0.0),
            cross_nodeid=2,
            seq_idx=1,
        ),
        dst_key: geom_mod._GraphNode(
            key=dst_key,
            traj_id="u",
            kind="cross",
            station_m=20.0,
            point=Point(20.0, 0.0),
            heading_xy=(1.0, 0.0),
            cross_nodeid=3,
            seq_idx=2,
        ),
    }
    edges = {
        src_key: [geom_mod._GraphEdge(to_key=mid_key, weight=1.0, kind="traj", traj_id="t", station_from=0.0, station_to=10.0)],
        mid_key: [geom_mod._GraphEdge(to_key=dst_key, weight=1.0, kind="stitch", traj_id=None, station_from=None, station_to=None)],
        dst_key: [],
    }

    res = geom_mod._search_next_crossing(
        source_key=src_key,
        source_nodeid=1,
        nodes=nodes,
        edges=edges,
        max_dist_m=100.0,
        unique_dst_early_stop=False,
    )

    assert res.target_key == mid_key
    assert len(res.hit_targets) == 1
    assert int(res.hit_targets[0][1]) == 2


def test_ambiguous_next_crossing_marks_soft_event(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    src_key = "t:cross:1"
    dst_a_key = "t:cross:2"
    dst_b_key = "t:cross:3"
    ev = CrossingEvent(
        traj_id="t",
        nodeid=1,
        seq=10,
        seg_idx=0,
        seq_idx=0,
        station_m=0.0,
        cross_point=Point(0.0, 0.0),
        heading_xy=(1.0, 0.0),
        cross_dist_m=0.0,
    )
    fake_graph = geom_mod._GraphBuildResult(
        nodes={
            src_key: geom_mod._GraphNode(
                key=src_key,
                traj_id="t",
                kind="cross",
                station_m=0.0,
                point=Point(0.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=1,
                seq_idx=0,
            ),
            dst_a_key: geom_mod._GraphNode(
                key=dst_a_key,
                traj_id="t",
                kind="cross",
                station_m=10.0,
                point=Point(10.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=2,
                seq_idx=1,
            ),
            dst_b_key: geom_mod._GraphNode(
                key=dst_b_key,
                traj_id="t",
                kind="cross",
                station_m=12.0,
                point=Point(12.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=3,
                seq_idx=2,
            ),
        },
        edges={
            src_key: [
                geom_mod._GraphEdge(
                    to_key=dst_a_key,
                    weight=1.0,
                    kind="traj",
                    traj_id="t",
                    station_from=0.0,
                    station_to=10.0,
                ),
                geom_mod._GraphEdge(
                    to_key=dst_b_key,
                    weight=1.1,
                    kind="traj",
                    traj_id="t",
                    station_from=0.0,
                    station_to=12.0,
                ),
            ],
            dst_a_key: [],
            dst_b_key: [],
        },
        event_keys_by_traj={"t": [(ev, src_key)]},
        traj_line_map={"t": LineString([(0.0, 0.0), (12.0, 0.0)])},
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
    monkeypatch.setattr(geom_mod, "_build_forward_graph", lambda **kwargs: fake_graph)

    res = geom_mod.build_pair_supports(
        trajectories=[],
        events_by_traj={"t": [ev]},
        node_type_map={1: "unknown", 2: "unknown", 3: "unknown"},
        neighbor_max_dist_m=100.0,
    )

    assert not res.supports
    assert any(str(item.get("reason")) == SOFT_AMBIGUOUS_NEXT_XSEC for item in res.ambiguous_events)


def test_road_prior_adjacency_filter_converts_ambiguous_to_unique(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    src_key = "t:cross:1"
    dst_a_key = "t:cross:2"
    dst_b_key = "t:cross:3"
    ev = CrossingEvent(
        traj_id="t",
        nodeid=1,
        seq=10,
        seg_idx=0,
        seq_idx=0,
        station_m=0.0,
        cross_point=Point(0.0, 0.0),
        heading_xy=(1.0, 0.0),
        cross_dist_m=0.0,
    )
    fake_graph = geom_mod._GraphBuildResult(
        nodes={
            src_key: geom_mod._GraphNode(
                key=src_key,
                traj_id="t",
                kind="cross",
                station_m=0.0,
                point=Point(0.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=1,
                seq_idx=0,
            ),
            dst_a_key: geom_mod._GraphNode(
                key=dst_a_key,
                traj_id="t",
                kind="cross",
                station_m=10.0,
                point=Point(10.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=2,
                seq_idx=1,
            ),
            dst_b_key: geom_mod._GraphNode(
                key=dst_b_key,
                traj_id="t",
                kind="cross",
                station_m=12.0,
                point=Point(12.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=3,
                seq_idx=2,
            ),
        },
        edges={
            src_key: [
                geom_mod._GraphEdge(
                    to_key=dst_a_key,
                    weight=1.0,
                    kind="traj",
                    traj_id="t",
                    station_from=0.0,
                    station_to=10.0,
                ),
                geom_mod._GraphEdge(
                    to_key=dst_b_key,
                    weight=1.1,
                    kind="traj",
                    traj_id="t",
                    station_from=0.0,
                    station_to=12.0,
                ),
            ],
            dst_a_key: [],
            dst_b_key: [],
        },
        event_keys_by_traj={"t": [(ev, src_key)]},
        traj_line_map={"t": LineString([(0.0, 0.0), (12.0, 0.0)])},
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
    monkeypatch.setattr(geom_mod, "_build_forward_graph", lambda **kwargs: fake_graph)

    res = geom_mod.build_pair_supports(
        trajectories=[],
        events_by_traj={"t": [ev]},
        node_type_map={1: "unknown", 2: "unknown", 3: "unknown"},
        neighbor_max_dist_m=100.0,
        allowed_dst_by_src={1: {2}},
    )

    assert (1, 2) in res.supports
    assert not res.ambiguous_events


def test_distance_margin_resolves_ambiguous_next_crossing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    src_key = "t:cross:1"
    dst_a_key = "t:cross:2"
    dst_b_key = "t:cross:3"
    ev = CrossingEvent(
        traj_id="t",
        nodeid=1,
        seq=10,
        seg_idx=0,
        seq_idx=0,
        station_m=0.0,
        cross_point=Point(0.0, 0.0),
        heading_xy=(1.0, 0.0),
        cross_dist_m=0.0,
    )
    fake_graph = geom_mod._GraphBuildResult(
        nodes={
            src_key: geom_mod._GraphNode(
                key=src_key,
                traj_id="t",
                kind="cross",
                station_m=0.0,
                point=Point(0.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=1,
                seq_idx=0,
            ),
            dst_a_key: geom_mod._GraphNode(
                key=dst_a_key,
                traj_id="t",
                kind="cross",
                station_m=10.0,
                point=Point(10.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=2,
                seq_idx=1,
            ),
            dst_b_key: geom_mod._GraphNode(
                key=dst_b_key,
                traj_id="t",
                kind="cross",
                station_m=120.0,
                point=Point(120.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=3,
                seq_idx=2,
            ),
        },
        edges={
            src_key: [
                geom_mod._GraphEdge(
                    to_key=dst_a_key,
                    weight=10.0,
                    kind="traj",
                    traj_id="t",
                    station_from=0.0,
                    station_to=10.0,
                ),
                geom_mod._GraphEdge(
                    to_key=dst_b_key,
                    weight=120.0,
                    kind="traj",
                    traj_id="t",
                    station_from=0.0,
                    station_to=120.0,
                ),
            ],
            dst_a_key: [],
            dst_b_key: [],
        },
        event_keys_by_traj={"t": [(ev, src_key)]},
        traj_line_map={"t": LineString([(0.0, 0.0), (120.0, 0.0)])},
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
    monkeypatch.setattr(geom_mod, "_build_forward_graph", lambda **kwargs: fake_graph)

    res = geom_mod.build_pair_supports(
        trajectories=[],
        events_by_traj={"t": [ev]},
        node_type_map={1: "unknown", 2: "unknown", 3: "unknown"},
        neighbor_max_dist_m=500.0,
        unique_dst_dist_eps_m=5.0,
    )

    assert (1, 2) in res.supports
    assert not res.ambiguous_events


def test_node_level_multi_neighbor_hard_fail(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 10.0), _mk_xsec(3, 20.0)],
    )
    support_12 = PairSupport(src_nodeid=1, dst_nodeid=2, support_traj_ids={"t1"}, support_event_count=1, repr_traj_ids=["t1"])
    support_13 = PairSupport(src_nodeid=1, dst_nodeid=3, support_traj_ids={"t2"}, support_event_count=1, repr_traj_ids=["t2"])
    build_result = PairSupportBuildResult(
        supports={(1, 2): support_12, (1, 3): support_13},
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
        ambiguous_events=[],
        next_crossing_candidates=[],
        node_dst_votes={1: {2: 1, 3: 1}},
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
        lambda **kwargs: ({1: "unknown", 2: "unknown", 3: "unknown"}, {1: 0, 2: 0, 3: 0}, {1: 0, 2: 0, 3: 0}),
    )

    out = pipeline._run_patch_core(
        patch_inputs,
        params=dict(pipeline.DEFAULT_PARAMS),
        run_id="unit_run",
        repo_root=tmp_path,
    )

    reasons = {str(bp.get("reason")) for bp in out["hard_breakpoints"]}
    assert HARD_MULTI_NEIGHBOR_FOR_NODE in reasons
    assert int(out["metrics_payload"].get("step1_ambiguous_node_count", 0)) == 1
    assert int(out["metrics_payload"].get("step1_unique_pair_count", -1)) == 0


def test_unique_neighbor_enters_corridor_stage(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 10.0)],
    )
    support_12 = PairSupport(src_nodeid=1, dst_nodeid=2, support_traj_ids={"t1"}, support_event_count=1, repr_traj_ids=["t1"])
    build_result = PairSupportBuildResult(
        supports={(1, 2): support_12},
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
        ambiguous_events=[],
        next_crossing_candidates=[],
        node_dst_votes={1: {2: 2}},
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
    calls = {"n": 0}

    def _fake_step1_corridor(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        calls["n"] += 1
        return {
            "strategy": "general",
            "hard_reason": "CENTER_ESTIMATE_EMPTY",
            "hard_hint": "unit_test_force_stop_after_step1",
            "corridor_count": 1,
            "main_corridor_ratio": 1.0,
            "shape_ref_line": None,
            "gore_fallback_used_src": False,
            "gore_fallback_used_dst": False,
            "traj_drop_count_by_drivezone": 0,
            "drivezone_fallback_used": False,
        }

    monkeypatch.setattr(pipeline, "_build_step1_corridor_for_pair", _fake_step1_corridor)

    out = pipeline._run_patch_core(
        patch_inputs,
        params=dict(pipeline.DEFAULT_PARAMS),
        run_id="unit_run",
        repo_root=tmp_path,
    )

    assert calls["n"] == 1
    assert int(out["metrics_payload"].get("step1_unique_pair_count", 0)) == 1
