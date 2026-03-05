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


def test_topology_unique_decision_marks_multi_chain_when_same_dst_has_two_paths() -> None:
    raw_graph = {
        1: [
            {"to": 10, "edge_id": "e_1_10"},
            {"to": 11, "edge_id": "e_1_11"},
        ],
        10: [{"to": 2, "edge_id": "e_10_2"}],
        11: [{"to": 2, "edge_id": "e_11_2"}],
    }
    compressed, comp_stats = pipeline._compress_topology_graph(
        raw_graph,
        cross_nodes={1, 2},
        enable=True,
    )
    xsec_map = {1: _mk_xsec(1, 0.0), 2: _mk_xsec(2, 10.0)}
    allowed, decisions, topo_stats, straight_features, chain_features = pipeline._build_topology_unique_decisions(
        compressed,
        cross_nodes={1, 2},
        xsec_map=xsec_map,
        require_unique_chain=True,
        max_expansions=1000,
    )

    assert int(comp_stats.get("compressible_node_count", 0)) == 2
    assert 1 not in allowed
    assert str(decisions[1]["status"]) == "multi_chain"
    assert str(decisions[1]["reason"]) == pipeline._HARD_MULTI_CHAIN_SAME_DST
    assert int(topo_stats.get("multi_chain_src_count", 0)) == 1
    assert len(straight_features) >= 1
    assert len(chain_features) >= 1


def test_topology_unique_decision_respects_direction_and_reports_unresolved() -> None:
    # Only reverse direction path 2->1 exists; src=1 should be unresolved.
    raw_graph = {
        2: [{"to": 10, "edge_id": "e_2_10"}],
        10: [{"to": 1, "edge_id": "e_10_1"}],
    }
    compressed, _ = pipeline._compress_topology_graph(
        raw_graph,
        cross_nodes={1, 2},
        enable=True,
    )
    xsec_map = {1: _mk_xsec(1, 0.0), 2: _mk_xsec(2, 10.0)}
    allowed, decisions, topo_stats, _straight_features, _chain_features = pipeline._build_topology_unique_decisions(
        compressed,
        cross_nodes={1, 2},
        xsec_map=xsec_map,
        require_unique_chain=True,
        max_expansions=1000,
    )

    assert 1 not in allowed
    assert str(decisions[1]["status"]) == "unresolved"
    assert int(topo_stats.get("unresolved_src_count", 0)) >= 1


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


def test_allowed_pairs_skips_non_topology_src(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    src_key = "t:cross:1"
    dst_key = "t:cross:2"
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
            dst_key: geom_mod._GraphNode(
                key=dst_key,
                traj_id="t",
                kind="cross",
                station_m=10.0,
                point=Point(10.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=2,
                seq_idx=1,
            ),
        },
        edges={
            src_key: [
                geom_mod._GraphEdge(
                    to_key=dst_key,
                    weight=1.0,
                    kind="traj",
                    traj_id="t",
                    station_from=0.0,
                    station_to=10.0,
                ),
            ],
            dst_key: [],
        },
        event_keys_by_traj={"t": [(ev, src_key)]},
        traj_line_map={"t": LineString([(0.0, 0.0), (10.0, 0.0)])},
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
        node_type_map={1: "unknown", 2: "unknown"},
        neighbor_max_dist_m=100.0,
        allowed_pairs={(9, 10)},
    )

    assert not res.supports
    assert not res.unresolved_events
    assert not res.ambiguous_events
    assert not res.next_crossing_candidates


def test_allowed_pairs_converts_ambiguous_to_unique(monkeypatch) -> None:  # type: ignore[no-untyped-def]
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
        allowed_dst_by_src={1: {2, 3}},
        allowed_pairs={(1, 2)},
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


def test_topology_unique_passes_allowed_pairs_to_support_builder(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    road_path = tmp_path / "RCSDRoad.geojson"
    road_payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 1, "enodeid": 2, "direction": 2}},
        ],
    }
    road_path.write_text(json.dumps(road_payload, ensure_ascii=False), encoding="utf-8")
    base_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 10.0)],
    )
    patch_inputs = PatchInputs(
        patch_id=base_inputs.patch_id,
        patch_dir=base_inputs.patch_dir,
        projection=base_inputs.projection,
        projection_to_metric=base_inputs.projection_to_metric,
        projection_to_input=base_inputs.projection_to_input,
        intersection_lines=base_inputs.intersection_lines,
        lane_boundaries_metric=base_inputs.lane_boundaries_metric,
        node_kind_map=base_inputs.node_kind_map,
        trajectories=base_inputs.trajectories,
        drivezone_zone_metric=base_inputs.drivezone_zone_metric,
        drivezone_source_path=base_inputs.drivezone_source_path,
        divstrip_zone_metric=base_inputs.divstrip_zone_metric,
        divstrip_source_path=base_inputs.divstrip_source_path,
        point_cloud_path=base_inputs.point_cloud_path,
        road_prior_path=road_path,
        tiles_dir=base_inputs.tiles_dir,
        input_summary=base_inputs.input_summary,
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
    captured_allowed_pairs: list[set[tuple[int, int]] | None] = []

    def _fake_build_pair_supports(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured_allowed_pairs.append(kwargs.get("allowed_pairs"))
        support = PairSupport(src_nodeid=1, dst_nodeid=2, support_traj_ids={"t1"}, support_event_count=1, repr_traj_ids=["t1"])
        return PairSupportBuildResult(
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
            ambiguous_events=[],
            next_crossing_candidates=[],
            node_dst_votes={1: {2: 1}},
        )

    monkeypatch.setattr(pipeline, "build_pair_supports", _fake_build_pair_supports)
    monkeypatch.setattr(
        pipeline,
        "infer_node_types",
        lambda **kwargs: ({1: "unknown", 2: "unknown"}, {1: 0, 2: 0}, {1: 0, 2: 0}),
    )

    def _fake_step1_corridor(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
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

    assert captured_allowed_pairs
    assert captured_allowed_pairs[0] == {(1, 2)}
    assert int(out["metrics_payload"].get("step1_unique_pair_count", 0)) == 1


def test_topology_unique_mode_hard_fails_multi_chain_same_dst(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    road_path = tmp_path / "RCSDRoad.geojson"
    road_payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 1, "enodeid": 10, "direction": 2}},
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 10, "enodeid": 2, "direction": 2}},
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 1, "enodeid": 11, "direction": 2}},
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 11, "enodeid": 2, "direction": 2}},
        ],
    }
    road_path.write_text(json.dumps(road_payload, ensure_ascii=False), encoding="utf-8")
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 10.0)],
    )
    patch_inputs = PatchInputs(
        patch_id=patch_inputs.patch_id,
        patch_dir=patch_inputs.patch_dir,
        projection=patch_inputs.projection,
        projection_to_metric=patch_inputs.projection_to_metric,
        projection_to_input=patch_inputs.projection_to_input,
        intersection_lines=patch_inputs.intersection_lines,
        lane_boundaries_metric=patch_inputs.lane_boundaries_metric,
        node_kind_map=patch_inputs.node_kind_map,
        trajectories=patch_inputs.trajectories,
        drivezone_zone_metric=patch_inputs.drivezone_zone_metric,
        drivezone_source_path=patch_inputs.drivezone_source_path,
        divstrip_zone_metric=patch_inputs.divstrip_zone_metric,
        divstrip_source_path=patch_inputs.divstrip_source_path,
        point_cloud_path=patch_inputs.point_cloud_path,
        road_prior_path=road_path,
        tiles_dir=patch_inputs.tiles_dir,
        input_summary=patch_inputs.input_summary,
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
        node_dst_votes={1: {2: 1}},
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

    params = dict(pipeline.DEFAULT_PARAMS)
    params["STEP1_ADJ_MODE"] = "topology_unique"
    params["STEP1_TOPO_REQUIRE_UNIQUE_CHAIN"] = 1
    out = pipeline._run_patch_core(
        patch_inputs,
        params=params,
        run_id="unit_run",
        repo_root=tmp_path,
    )

    reasons = {str(bp.get("reason")) for bp in out["hard_breakpoints"]}
    assert pipeline._HARD_MULTI_CHAIN_SAME_DST in reasons
    assert int(out["metrics_payload"].get("step1_unique_pair_count", -1)) == 0
