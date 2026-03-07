from __future__ import annotations

from pathlib import Path

import json
import numpy as np
from shapely.geometry import LineString, Point

from highway_topo_poc.modules.t05_topology_between_rc import geometry as geom_mod
from highway_topo_poc.modules.t05_topology_between_rc import pipeline
from highway_topo_poc.modules.t05_topology_between_rc.geometry import (
    CrossingEvent,
    CrossingExtractResult,
    HARD_MULTI_ROAD,
    HARD_MULTI_NEIGHBOR_FOR_NODE,
    PairSupport,
    PairSupportBuildResult,
    SOFT_AMBIGUOUS_NEXT_XSEC,
)
from highway_topo_poc.modules.t05_topology_between_rc.io import CrossSection, PatchInputs, ProjectionInfo


def _mk_patch_inputs(
    *,
    tmp_path: Path,
    xsecs: list[CrossSection],
    road_prior_path: Path | None = None,
) -> PatchInputs:
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
        road_prior_path=road_prior_path,
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


def test_build_road_prior_pair_shape_ref_map_reconstructs_deg2_chain(tmp_path: Path) -> None:
    road_path = tmp_path / "RCSDRoad.geojson"
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [5.0, 0.0]]},
                "properties": {"snodeid": 1, "enodeid": 10, "direction": 2, "road_id": "r_1_10"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[5.0, 0.0], [10.0, 0.0]]},
                "properties": {"snodeid": 10, "enodeid": 2, "direction": 2, "road_id": "r_10_2"},
            },
        ],
    }
    road_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    edge_graph, _edge_stats = pipeline._load_road_prior_graph(road_path, respect_direction=True)
    edge_geom_map, geom_stats = pipeline._load_road_prior_edge_geometry_map(
        road_path,
        to_metric=lambda geom: geom,
        respect_direction=True,
        unknown_direction_as_bidirectional=False,
    )
    compressed, _comp_stats = pipeline._compress_topology_graph(
        edge_graph,
        cross_nodes={1, 2},
        enable=True,
    )
    pair_map, pair_stats = pipeline._build_road_prior_pair_shape_ref_map(
        compressed,
        edge_geometry_by_id=edge_geom_map,
    )

    assert int(geom_stats.get("edge_geometry_count", 0)) == 2
    assert int(pair_stats.get("pair_shape_ref_count", 0)) >= 1
    assert (1, 2) in pair_map
    line = pair_map[(1, 2)]
    assert isinstance(line, LineString)
    assert float(line.length) >= 9.9
    assert tuple(line.coords[0]) == (0.0, 0.0)
    assert tuple(line.coords[-1]) == (10.0, 0.0)


def test_collect_same_dst_multi_chain_pairs_detects_parallel_same_pair_routes() -> None:
    anchor_decisions = {
        "a0": {
            "status": "accepted",
            "search_direction": "forward",
            "pair_src_nodeid": 791873,
            "pair_dst_nodeid": 791871,
            "chosen_dst_nodeid": 791871,
            "start_edge_id": "998553@0:fwd",
            "dst_paths": {
                "791871": [
                    {
                        "edge_ids": ["998553@0:fwd"],
                        "node_path": [791873, 791871],
                    }
                ]
            },
        },
        "a1": {
            "status": "accepted",
            "search_direction": "forward",
            "pair_src_nodeid": 791873,
            "pair_dst_nodeid": 791871,
            "chosen_dst_nodeid": 791871,
            "start_edge_id": "998554@1:fwd",
            "dst_paths": {
                "791871": [
                    {
                        "edge_ids": ["998554@1:fwd"],
                        "node_path": [791873, 791871],
                    }
                ]
            },
        },
    }

    out = pipeline._collect_same_dst_multi_chain_pairs(
        anchor_decisions,
        accepted_pairs={(791873, 791871)},
    )

    assert (791873, 791871) in out
    assert int(out[(791873, 791871)]["chain_count"]) == 2


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


def test_topology_unique_anchor_decisions_include_incoming_anchor_paths() -> None:
    # 1 -> 2 only. node 2 has no outgoing edge; incoming-anchor(reverse-search) should still
    # contribute an accepted pair 1->2.
    raw_graph = {
        1: [{"to": 2, "edge_id": "e_1_2"}],
    }
    compressed, _ = pipeline._compress_topology_graph(
        raw_graph,
        cross_nodes={1, 2},
        enable=True,
    )
    xsec_map = {1: _mk_xsec(1, 0.0), 2: _mk_xsec(2, 10.0)}
    (
        allowed_dst,
        allowed_pairs,
        node_decisions,
        anchor_decisions,
        topo_stats,
        _straight,
        _chain,
    ) = pipeline._build_topology_unique_anchor_decisions(
        compressed,
        cross_nodes={1, 2},
        xsec_map=xsec_map,
        require_unique_chain=True,
        max_expansions=1000,
    )

    assert (1, 2) in allowed_pairs
    assert 2 in allowed_dst.get(1, set())
    assert int(topo_stats.get("src_anchor_in_count", 0)) >= 1
    assert int(topo_stats.get("src_anchor_out_count", 0)) >= 1
    # node 2 should have at least one accepted incoming-anchor decision evidence
    assert str(node_decisions[2]["status"]) == "accepted"
    assert any(
        isinstance(v, dict)
        and str(v.get("anchor_role")) == "in"
        and str(v.get("status")) == "accepted"
        and int(v.get("pair_src_nodeid")) == 1
        and int(v.get("pair_dst_nodeid")) == 2
        for v in anchor_decisions.values()
    )


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


def test_build_pair_supports_remaps_shared_intersection_roles(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    src_key = "t:cross:src"
    dst_key = "t:cross:dst"
    ev = CrossingEvent(
        traj_id="t",
        nodeid=11,
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
                cross_nodeid=11,
                seq_idx=0,
            ),
            dst_key: geom_mod._GraphNode(
                key=dst_key,
                traj_id="t",
                kind="cross",
                station_m=10.0,
                point=Point(10.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=22,
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
        node_type_map={101: "diverge", 202: "merge"},
        neighbor_max_dist_m=100.0,
        allowed_dst_by_src={101: {202}},
        src_nodeid_alias_by_nodeid={11: 101},
        dst_nodeid_alias_by_nodeid={22: 202},
    )

    assert (101, 202) in res.supports
    support = res.supports[(101, 202)]
    assert int(support.src_nodeid) == 101
    assert int(support.dst_nodeid) == 202
    assert int(support.support_event_count) == 1


def test_normalize_support_clusters_preserves_keep_pairs() -> None:
    keep_support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"a", "b", "c", "d"},
        support_event_count=4,
        hard_anomalies={HARD_MULTI_ROAD},
        evidence_cluster_ids=[0, 0, 1, 1],
    )
    keep_support.cluster_count = 2
    keep_support.main_cluster_id = 0
    keep_support.main_cluster_ratio = 0.5
    keep_support.cluster_sep_m_est = 12.0
    keep_support.cluster_sizes = [2, 2]

    other_support = PairSupport(
        src_nodeid=3,
        dst_nodeid=4,
        support_traj_ids={"x", "y"},
        support_event_count=2,
        hard_anomalies={HARD_MULTI_ROAD},
        evidence_cluster_ids=[0, 1],
    )
    other_support.cluster_count = 2
    other_support.main_cluster_id = 0
    other_support.main_cluster_ratio = 0.5
    other_support.cluster_sep_m_est = 10.0
    other_support.cluster_sizes = [1, 1]

    stats = pipeline._normalize_support_clusters_for_xsec_gate(
        supports={(1, 2): keep_support, (3, 4): other_support},
        enabled=True,
        keep_pairs={(1, 2)},
    )

    assert int(stats.get("step1_pair_cluster_preserved_pair_count", 0)) == 1
    assert int(keep_support.cluster_count) == 2
    assert HARD_MULTI_ROAD in keep_support.hard_anomalies
    assert int(other_support.cluster_count) == 1
    assert HARD_MULTI_ROAD not in other_support.hard_anomalies


def test_step1_corridor_falls_back_to_road_prior_when_no_traj() -> None:
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1"},
        support_event_count=1,
    )
    src_xsec = LineString([(0.0, -5.0), (0.0, 5.0)])
    dst_xsec = LineString([(20.0, -5.0), (20.0, 5.0)])
    prior_line = LineString([(0.0, 0.0), (10.0, 1.0), (20.0, 0.0)])

    out = pipeline._build_step1_corridor_for_pair(
        support=support,
        src_type="merge",
        dst_type="merge",
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=None,
        gore_zone_metric=None,
        params=dict(pipeline.DEFAULT_PARAMS),
        road_prior_shape_ref_metric=prior_line,
    )

    assert bool(out.get("road_prior_shape_ref_used")) is True
    assert str(out.get("road_prior_shape_ref_mode")) == "step1_no_traj"
    assert isinstance(out.get("shape_ref_line"), LineString)
    assert out.get("hard_reason") is None


def test_run_patch_core_keeps_single_road_for_single_cluster_pair(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
    )
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t0", "t1", "t2", "t3"},
        support_event_count=4,
        traj_segments=[
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            LineString([(0.0, 0.5), (100.0, 0.5)]),
            LineString([(0.0, 10.0), (100.0, 10.0)]),
            LineString([(0.0, 10.5), (100.0, 10.5)]),
        ],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 0.5), Point(0.0, 10.0), Point(0.0, 10.5)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 0.5), Point(100.0, 10.0), Point(100.0, 10.5)],
        repr_traj_ids=["t0", "t1", "t2", "t3"],
        hard_anomalies=set(),
        evidence_traj_ids=["t0", "t1", "t2", "t3"],
        evidence_cluster_ids=[0, 0, 0, 0],
        evidence_lengths_m=[100.0, 100.0, 100.0, 100.0],
        open_end_flags=[False, False, False, False],
    )
    support.cluster_count = 1
    support.main_cluster_id = 0
    support.main_cluster_ratio = 1.0
    support.cluster_sep_m_est = None
    support.cluster_sizes = [4]

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
    monkeypatch.setattr(
        pipeline,
        "build_pair_supports",
        lambda *args, **kwargs: PairSupportBuildResult(
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
            node_dst_votes={1: {2: 4}},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "infer_node_types",
        lambda **kwargs: ({1: "merge", 2: "merge"}, {1: 0, 2: 1}, {1: 1, 2: 0}),
    )
    monkeypatch.setattr(
        pipeline,
        "_load_surface_points",
        lambda *args, **kwargs: (np.empty((0, 3), dtype=np.float64), np.empty((0, 2), dtype=np.float64), {}),
    )
    monkeypatch.setattr(
        pipeline,
        "_build_step1_corridor_for_pair",
        lambda **kwargs: {
            "strategy": "general",
            "hard_reason": None,
            "hard_hint": None,
            "corridor_count": 1,
            "main_corridor_ratio": 1.0,
            "shape_ref_line": LineString([(0.0, 0.0), (100.0, 0.0)]),
            "corridor_zone_metric": None,
            "corridor_zone_area_m2": None,
            "corridor_zone_source_count": 0,
            "corridor_zone_half_width_m": None,
            "corridor_shape_ref_inside_ratio": None,
            "gore_fallback_used_src": False,
            "gore_fallback_used_dst": False,
            "traj_drop_count_by_drivezone": 0,
            "drivezone_fallback_used": False,
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_build_traj_surface_hint_for_cluster",
        lambda **kwargs: {
            "traj_surface_enforced": False,
            "surface_metric": None,
            "timing_ms": 0.0,
            "slice_valid_ratio": 0.0,
            "covered_length_ratio": 0.0,
            "unique_traj_count": 0,
        },
    )

    def _fake_eval(**kwargs):  # type: ignore[no-untyped-def]
        cluster_id = int(kwargs["cluster_id"])
        y = 0.0 if cluster_id == 0 else 10.0
        road = pipeline._make_base_road_record(
            src=int(kwargs["src"]),
            dst=int(kwargs["dst"]),
            support=kwargs["support"],
            src_type=str(kwargs["src_type"]),
            dst_type=str(kwargs["dst_type"]),
            neighbor_search_pass=int(kwargs["neighbor_search_pass"]),
        )
        road["candidate_cluster_id"] = cluster_id
        road["chosen_cluster_id"] = cluster_id
        road["_geometry_metric"] = LineString([(0.0, y), (100.0, y)])
        road["_candidate_has_geometry"] = True
        road["_candidate_feasible"] = True
        road["_candidate_score"] = 100.0 - float(cluster_id)
        road["_candidate_in_ratio"] = 1.0
        road["hard_reasons"] = []
        road["soft_issue_flags"] = []
        road["length_m"] = 100.0
        road["conf"] = 0.8
        road["_candidate_hard_breakpoints"] = []
        road["_candidate_soft_breakpoints"] = []
        return road

    monkeypatch.setattr(pipeline, "_evaluate_candidate_road", _fake_eval)

    params = dict(pipeline.DEFAULT_PARAMS)
    params["STEP1_ADJ_MODE"] = "vote"
    params["STEP1_PAIR_CLUSTER_ENABLE"] = 1
    params["STEP1_DISABLE_PAIR_CLUSTER_WHEN_GATE"] = 0

    out = pipeline._run_patch_core(
        patch_inputs,
        params=params,
        run_id="unit_run",
        repo_root=tmp_path,
    )

    road_ids = [str(props["road_id"]) for props in out["road_properties"]]
    assert out["road_count"] == 1
    assert len(road_ids) == 1
    assert len(set(road_ids)) == 1
    assert "__k" not in road_ids[0]
    assert bool(out["gate_payload"]["overall_pass"]) is True


def test_topology_unique_mode_outputs_multi_roads_for_same_pair_multichain(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    road_path = tmp_path / "RCSDRoad.geojson"
    road_payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [100.0, 0.0]]},
                "properties": {"snodeid": 1, "enodeid": 2, "direction": 2, "road_id": "r_a"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.0, 10.0], [100.0, 10.0]]},
                "properties": {"snodeid": 1, "enodeid": 2, "direction": 2, "road_id": "r_b"},
            },
        ],
    }
    road_path.write_text(json.dumps(road_payload, ensure_ascii=False), encoding="utf-8")

    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
        road_prior_path=road_path,
    )
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t0", "t1", "t2", "t3"},
        support_event_count=4,
        traj_segments=[
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            LineString([(0.0, 0.5), (100.0, 0.5)]),
            LineString([(0.0, 10.0), (100.0, 10.0)]),
            LineString([(0.0, 10.5), (100.0, 10.5)]),
        ],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 0.5), Point(0.0, 10.0), Point(0.0, 10.5)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 0.5), Point(100.0, 10.0), Point(100.0, 10.5)],
        repr_traj_ids=["t0", "t1", "t2", "t3"],
        hard_anomalies={HARD_MULTI_ROAD},
        evidence_traj_ids=["t0", "t1", "t2", "t3"],
        evidence_cluster_ids=[0, 0, 1, 1],
        evidence_lengths_m=[100.0, 100.0, 100.0, 100.0],
        open_end_flags=[False, False, False, False],
    )
    support.cluster_count = 2
    support.main_cluster_id = 0
    support.main_cluster_ratio = 0.5
    support.cluster_sep_m_est = 10.0
    support.cluster_sizes = [2, 2]

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
    monkeypatch.setattr(
        pipeline,
        "build_pair_supports",
        lambda *args, **kwargs: PairSupportBuildResult(
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
            node_dst_votes={1: {2: 4}},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "infer_node_types",
        lambda **kwargs: ({1: "merge", 2: "merge"}, {1: 0, 2: 1}, {1: 1, 2: 0}),
    )
    monkeypatch.setattr(
        pipeline,
        "_load_surface_points",
        lambda *args, **kwargs: (np.empty((0, 3), dtype=np.float64), np.empty((0, 2), dtype=np.float64), {}),
    )
    monkeypatch.setattr(
        pipeline,
        "_build_step1_corridor_for_pair",
        lambda **kwargs: {
            "strategy": "general",
            "hard_reason": None,
            "hard_hint": None,
            "corridor_count": 1,
            "main_corridor_ratio": 1.0,
            "shape_ref_line": LineString([(0.0, 0.0), (100.0, 0.0)]),
            "corridor_zone_metric": None,
            "corridor_zone_area_m2": None,
            "corridor_zone_source_count": 0,
            "corridor_zone_half_width_m": None,
            "corridor_shape_ref_inside_ratio": None,
            "gore_fallback_used_src": False,
            "gore_fallback_used_dst": False,
            "traj_drop_count_by_drivezone": 0,
            "drivezone_fallback_used": False,
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_build_traj_surface_hint_for_cluster",
        lambda **kwargs: {
            "traj_surface_enforced": False,
            "surface_metric": None,
            "timing_ms": 0.0,
            "slice_valid_ratio": 0.0,
            "covered_length_ratio": 0.0,
            "unique_traj_count": 0,
        },
    )

    def _fake_eval(**kwargs):  # type: ignore[no-untyped-def]
        cluster_id = int(kwargs["cluster_id"])
        y = 0.0 if cluster_id == 0 else 10.0
        road = pipeline._make_base_road_record(
            src=int(kwargs["src"]),
            dst=int(kwargs["dst"]),
            support=kwargs["support"],
            src_type=str(kwargs["src_type"]),
            dst_type=str(kwargs["dst_type"]),
            neighbor_search_pass=int(kwargs["neighbor_search_pass"]),
        )
        road["candidate_cluster_id"] = cluster_id
        road["chosen_cluster_id"] = cluster_id
        road["_geometry_metric"] = LineString([(0.0, y), (100.0, y)])
        road["_candidate_has_geometry"] = True
        road["_candidate_feasible"] = True
        road["_candidate_score"] = 100.0 - float(cluster_id)
        road["_candidate_in_ratio"] = 1.0
        road["hard_reasons"] = []
        road["soft_issue_flags"] = []
        road["length_m"] = 100.0
        road["conf"] = 0.8
        road["_candidate_hard_breakpoints"] = []
        road["_candidate_soft_breakpoints"] = []
        return road

    monkeypatch.setattr(pipeline, "_evaluate_candidate_road", _fake_eval)

    out = pipeline._run_patch_core(
        patch_inputs,
        params=dict(pipeline.DEFAULT_PARAMS),
        run_id="unit_run",
        repo_root=tmp_path,
    )

    road_ids = [str(props["road_id"]) for props in out["road_properties"]]
    assert out["road_count"] == 2
    assert len(set(road_ids)) == 2
    assert all("__k" in road_id for road_id in road_ids)
    assert int(out["metrics_payload"].get("step1_same_pair_multichain_pair_count", 0)) == 1
    assert bool(out["gate_payload"]["overall_pass"]) is True


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


def test_single_support_per_pair_stops_after_first_hit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    src_key_0 = "t:cross:1:0"
    src_key_1 = "t:cross:1:1"
    dst_key = "t:cross:2"
    ev0 = CrossingEvent(
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
    ev1 = CrossingEvent(
        traj_id="t",
        nodeid=1,
        seq=20,
        seg_idx=0,
        seq_idx=1,
        station_m=5.0,
        cross_point=Point(0.0, 1.0),
        heading_xy=(1.0, 0.0),
        cross_dist_m=0.0,
    )
    fake_graph = geom_mod._GraphBuildResult(
        nodes={
            src_key_0: geom_mod._GraphNode(
                key=src_key_0,
                traj_id="t",
                kind="cross",
                station_m=0.0,
                point=Point(0.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=1,
                seq_idx=0,
            ),
            src_key_1: geom_mod._GraphNode(
                key=src_key_1,
                traj_id="t",
                kind="cross",
                station_m=5.0,
                point=Point(0.0, 1.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=1,
                seq_idx=1,
            ),
            dst_key: geom_mod._GraphNode(
                key=dst_key,
                traj_id="t",
                kind="cross",
                station_m=10.0,
                point=Point(10.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=2,
                seq_idx=2,
            ),
        },
        edges={
            src_key_0: [
                geom_mod._GraphEdge(
                    to_key=dst_key,
                    weight=1.0,
                    kind="traj",
                    traj_id="t",
                    station_from=0.0,
                    station_to=10.0,
                ),
            ],
            src_key_1: [
                geom_mod._GraphEdge(
                    to_key=dst_key,
                    weight=1.0,
                    kind="traj",
                    traj_id="t",
                    station_from=5.0,
                    station_to=10.0,
                ),
            ],
            dst_key: [],
        },
        event_keys_by_traj={"t": [(ev0, src_key_0), (ev1, src_key_1)]},
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

    res_full = geom_mod.build_pair_supports(
        trajectories=[],
        events_by_traj={"t": [ev0, ev1]},
        node_type_map={1: "unknown", 2: "unknown"},
        neighbor_max_dist_m=100.0,
        single_support_per_pair=False,
    )
    res_one = geom_mod.build_pair_supports(
        trajectories=[],
        events_by_traj={"t": [ev0, ev1]},
        node_type_map={1: "unknown", 2: "unknown"},
        neighbor_max_dist_m=100.0,
        single_support_per_pair=True,
        allowed_pairs={(1, 2)},
        skip_search_after_pair_resolved=True,
    )

    assert (1, 2) in res_full.supports
    assert (1, 2) in res_one.supports
    assert int(res_full.supports[(1, 2)].support_event_count) == 2
    assert int(res_one.supports[(1, 2)].support_event_count) == 1


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


def test_run_patch_core_uses_shared_intersection_alias_lookup(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    src_xsec = CrossSection(
        nodeid=9102,
        geometry_metric=LineString([(0.0, -5.0), (0.0, 5.0)]),
        properties={
            "nodeid": 9102,
            "nodeids": [9101, 9102],
            "roles": ["diverge", "merge"],
            "merged_group_id": "chain:src",
        },
    )
    dst_xsec = CrossSection(
        nodeid=9201,
        geometry_metric=LineString([(20.0, -5.0), (20.0, 5.0)]),
        properties={
            "nodeid": 9201,
            "nodeids": [9201, 9202],
            "roles": ["diverge", "merge"],
            "merged_group_id": "chain:dst",
        },
    )
    patch_inputs = _mk_patch_inputs(tmp_path=tmp_path, xsecs=[src_xsec, dst_xsec])
    support = PairSupport(src_nodeid=9101, dst_nodeid=9202, support_traj_ids={"t1"}, support_event_count=1, repr_traj_ids=["t1"])

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
    monkeypatch.setattr(
        pipeline,
        "build_pair_supports",
        lambda *args, **kwargs: PairSupportBuildResult(
            supports={(9101, 9202): support},
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
            node_dst_votes={9101: {9202: 1}},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "infer_node_types",
        lambda **kwargs: ({9101: "diverge", 9202: "merge"}, {9101: 0, 9202: 1}, {9101: 1, 9202: 0}),
    )

    def _fake_step1_corridor(**kwargs):  # type: ignore[no-untyped-def]
        assert kwargs.get("src_xsec") is not None
        assert kwargs.get("dst_xsec") is not None
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

    assert int(out["metrics_payload"].get("step1_unique_pair_count", 0)) == 1


def test_topology_unique_mode_keeps_same_pair_multichain_for_later_stages(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
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
    assert pipeline._HARD_MULTI_CHAIN_SAME_DST not in reasons
    assert int(out["metrics_payload"].get("step1_unique_pair_count", -1)) == 1
    assert int(out["metrics_payload"].get("step1_same_pair_multichain_pair_count", -1)) == 1
