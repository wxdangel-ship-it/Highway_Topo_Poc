from __future__ import annotations

from pathlib import Path

import json
import numpy as np
from shapely.geometry import LineString, Point, Polygon

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
from highway_topo_poc.modules.t05_topology_between_rc.io import (
    CrossSection,
    PatchInputs,
    ProjectionInfo,
    TrajectoryData,
)


def _mk_patch_inputs(
    *,
    tmp_path: Path,
    xsecs: list[CrossSection],
    road_prior_path: Path | None = None,
    trajectories: list[TrajectoryData] | None = None,
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
        trajectories=list(trajectories or []),
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


def _mk_traj(traj_id: str, coords: list[tuple[float, float]]) -> TrajectoryData:
    xyz = np.asarray([(float(x), float(y), 0.0) for x, y in coords], dtype=np.float64)
    seq = np.arange(xyz.shape[0], dtype=np.int64)
    return TrajectoryData(
        traj_id=str(traj_id),
        seq=seq,
        xyz_metric=xyz,
        source_path=Path(f"/virtual/{traj_id}.geojson"),
        source_crs="EPSG:3857",
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


def test_collect_topology_anchor_seeds_can_borrow_shared_member_edges() -> None:
    compressed = {
        55353307: [
            {
                "to": 608638238,
                "edge_ids": ["edge_shared_out"],
                "path_nodes": [55353307, 608638238],
            }
        ]
    }

    seeds = pipeline._collect_topology_anchor_seeds(
        compressed,
        cross_nodes={55353307, 23287538, 608638238},
        seed_role="out",
        shared_group_members_by_nodeid={
            55353307: [55353307, 23287538],
            23287538: [55353307, 23287538],
        },
    )

    by_src = {int(item["src_nodeid"]): item for item in seeds if int(item["src_nodeid"]) in {55353307, 23287538}}
    assert int(by_src[55353307]["start_to"]) == 608638238
    assert int(by_src[23287538]["start_to"]) == 608638238
    assert by_src[23287538]["start_path_nodes"] == [23287538, 608638238]
    assert int(by_src[23287538]["borrowed_from_src"]) == 55353307


def test_topology_unique_anchor_decisions_accept_shared_member_via_borrowed_edges() -> None:
    compressed = {
        55353307: [
            {
                "to": 608638238,
                "edge_ids": ["edge_shared_out"],
                "path_nodes": [55353307, 608638238],
            }
        ]
    }
    xsec_map = {
        55353307: _mk_xsec(55353307, 0.0),
        23287538: _mk_xsec(23287538, 0.0),
        608638238: _mk_xsec(608638238, 10.0),
    }

    (
        allowed_dst,
        allowed_pairs,
        node_decisions,
        _anchor_decisions,
        topo_stats,
        _straight,
        _chain,
    ) = pipeline._build_topology_unique_anchor_decisions(
        compressed,
        cross_nodes={55353307, 23287538, 608638238},
        xsec_map=xsec_map,
        require_unique_chain=True,
        max_expansions=1000,
        shared_group_members_by_nodeid={
            55353307: [55353307, 23287538],
            23287538: [55353307, 23287538],
        },
    )

    assert (23287538, 608638238) in allowed_pairs
    assert 608638238 in allowed_dst.get(23287538, set())
    assert str(node_decisions[23287538]["status"]) == "accepted"
    assert int(topo_stats.get("accepted_src_count", 0)) >= 2


def test_topology_unique_anchor_decisions_filter_shared_group_sibling_pair() -> None:
    compressed = {
        55353307: [
            {
                "to": 23287538,
                "edge_ids": ["edge_shared_sibling"],
                "path_nodes": [55353307, 23287538],
            }
        ]
    }
    xsec_map = {
        55353307: _mk_xsec(55353307, 0.0),
        23287538: _mk_xsec(23287538, 10.0),
    }

    (
        allowed_dst,
        allowed_pairs,
        _node_decisions,
        anchor_decisions,
        topo_stats,
        _straight,
        _chain,
    ) = pipeline._build_topology_unique_anchor_decisions(
        compressed,
        cross_nodes={55353307, 23287538},
        xsec_map=xsec_map,
        require_unique_chain=True,
        max_expansions=1000,
        shared_group_members_by_nodeid={
            55353307: [55353307, 23287538],
            23287538: [55353307, 23287538],
        },
    )

    assert not allowed_pairs
    assert allowed_dst == {}
    assert int(topo_stats.get("shared_group_sibling_filtered_anchor_count", 0)) >= 1
    assert any(str(v.get("status")) == "filtered_shared_group_sibling" for v in anchor_decisions.values())


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


def test_allowed_dst_filter_can_skip_non_target_crossing_absorbing_state() -> None:
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
        allowed_dst_nodeids={3},
    )

    assert res.target_key == dst_key
    assert len(res.hit_targets) == 1
    assert int(res.hit_targets[0][1]) == 3


def test_allowed_dst_proximity_closure_can_recover_missing_crossing_event() -> None:
    src_key = "t:cross:1"
    sample_key = "t:sample:1"
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
        sample_key: geom_mod._GraphNode(
            key=sample_key,
            traj_id="t",
            kind="sample",
            station_m=10.0,
            point=Point(10.2, 0.0),
            heading_xy=(1.0, 0.0),
            cross_nodeid=None,
            seq_idx=1,
        ),
    }
    edges = {
        src_key: [geom_mod._GraphEdge(to_key=sample_key, weight=1.0, kind="traj", traj_id="t", station_from=0.0, station_to=10.0)],
        sample_key: [],
    }

    res = geom_mod._search_next_crossing(
        source_key=src_key,
        source_nodeid=1,
        nodes=nodes,
        edges=edges,
        max_dist_m=100.0,
        unique_dst_early_stop=False,
        allowed_dst_nodeids={2},
        allowed_dst_points_by_nodeid={2: [Point(10.0, 0.0)]},
        allowed_dst_close_hit_buffer_m=0.5,
    )

    assert res.target_key == sample_key
    assert int(res.target_cross_nodeid or -1) == 2
    assert bool(res.used_proximity_closure) is True
    assert float(res.proximity_closure_dist_m or 0.0) <= 0.5


def test_stop_on_first_allowed_hit_disables_proximity_closure() -> None:
    src_key = "t:cross:1"
    sample_key = "t:sample:1"
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
        sample_key: geom_mod._GraphNode(
            key=sample_key,
            traj_id="t",
            kind="sample",
            station_m=10.0,
            point=Point(10.2, 0.0),
            heading_xy=(1.0, 0.0),
            cross_nodeid=None,
            seq_idx=1,
        ),
    }
    edges = {
        src_key: [geom_mod._GraphEdge(to_key=sample_key, weight=1.0, kind="traj", traj_id="t", station_from=0.0, station_to=10.0)],
        sample_key: [],
    }

    res = geom_mod._search_next_crossing(
        source_key=src_key,
        source_nodeid=1,
        nodes=nodes,
        edges=edges,
        max_dist_m=100.0,
        unique_dst_early_stop=False,
        allowed_dst_nodeids={2},
        allowed_dst_points_by_nodeid={2: [Point(10.0, 0.0)]},
        allowed_dst_close_hit_buffer_m=0.5,
        stop_on_first_allowed_hit=True,
    )

    assert res.target_key is None
    assert int(res.target_cross_nodeid or -1) == -1
    assert bool(res.used_proximity_closure) is False


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


def test_pair_target_first_support_search_allows_intermediate_crossing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    src_key = "t:cross:1"
    mid_key = "t:cross:2"
    dst_key = "u:cross:3"
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
        },
        edges={
            src_key: [geom_mod._GraphEdge(to_key=mid_key, weight=1.0, kind="traj", traj_id="t", station_from=0.0, station_to=10.0)],
            mid_key: [geom_mod._GraphEdge(to_key=dst_key, weight=1.0, kind="stitch", traj_id=None, station_from=None, station_to=None)],
            dst_key: [],
        },
        event_keys_by_traj={"t": [(ev, src_key)]},
        traj_line_map={"t": LineString([(0.0, 0.0), (20.0, 0.0)])},
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
        allowed_pairs={(1, 3)},
    )

    assert (1, 3) in res.supports
    assert (1, 2) not in res.supports
    assert not res.ambiguous_events
    assert res.next_crossing_candidates
    cand = res.next_crossing_candidates[0]
    assert str(cand.get("search_mode")) == "pair_target_first"
    assert int(cand.get("expected_dst_nodeid") or -1) == 3
    assert [int(v) for v in cand.get("intermediate_dst_nodeids") or []] == [2]


def test_pair_target_first_support_search_limits_intermediate_crossings(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    src_key = "t:cross:1"
    mid_a_key = "t:cross:2"
    mid_b_key = "u:cross:4"
    dst_key = "v:cross:3"
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
            mid_a_key: geom_mod._GraphNode(
                key=mid_a_key,
                traj_id="t",
                kind="cross",
                station_m=10.0,
                point=Point(10.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=2,
                seq_idx=1,
            ),
            mid_b_key: geom_mod._GraphNode(
                key=mid_b_key,
                traj_id="u",
                kind="cross",
                station_m=20.0,
                point=Point(20.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=4,
                seq_idx=2,
            ),
            dst_key: geom_mod._GraphNode(
                key=dst_key,
                traj_id="v",
                kind="cross",
                station_m=30.0,
                point=Point(30.0, 0.0),
                heading_xy=(1.0, 0.0),
                cross_nodeid=3,
                seq_idx=3,
            ),
        },
        edges={
            src_key: [geom_mod._GraphEdge(to_key=mid_a_key, weight=1.0, kind="traj", traj_id="t", station_from=0.0, station_to=10.0)],
            mid_a_key: [geom_mod._GraphEdge(to_key=mid_b_key, weight=1.0, kind="stitch", traj_id=None, station_from=None, station_to=None)],
            mid_b_key: [geom_mod._GraphEdge(to_key=dst_key, weight=1.0, kind="stitch", traj_id=None, station_from=None, station_to=None)],
            dst_key: [],
        },
        event_keys_by_traj={"t": [(ev, src_key)]},
        traj_line_map={"t": LineString([(0.0, 0.0), (30.0, 0.0)])},
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
        node_type_map={1: "unknown", 2: "unknown", 3: "unknown", 4: "unknown"},
        neighbor_max_dist_m=100.0,
        allowed_pairs={(1, 3)},
        pair_target_max_intermediate_crossings=1,
    )

    assert (1, 3) not in res.supports
    assert res.unresolved_events
    unresolved = res.unresolved_events[0]
    assert int(unresolved.get("dst_nodeid") or -1) == 3
    assert [int(v) for v in unresolved.get("intermediate_dst_nodeids") or []] == [2, 4]


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


def test_topology_unique_mode_same_pair_multichain_outputs_multi_roads_with_channel_identity(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
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

    eval_calls: list[dict[str, object]] = []

    def _fake_eval(**kwargs):  # type: ignore[no-untyped-def]
        cluster_id = int(kwargs["cluster_id"])
        y = 0.0 if cluster_id == 0 else 10.0
        eval_calls.append(
            {
                "cluster_id": int(cluster_id),
                "candidate_branch_id": kwargs.get("candidate_branch_id"),
                "same_pair_multichain": bool(kwargs.get("same_pair_multichain", False)),
            }
        )
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

    assert len(eval_calls) == 2
    assert {str(item["candidate_branch_id"]) for item in eval_calls} == {"1_2__b0", "1_2__b1"}
    assert all(bool(item["same_pair_multichain"]) for item in eval_calls)
    assert out["road_count"] == 2
    assert len(out["road_properties"]) == 2
    road_ids = {str(props["road_id"]) for props in out["road_properties"]}
    assert road_ids == {"1_2__ch1", "1_2__ch2"}
    channel_ids = {str(props.get("channel_id")) for props in out["road_properties"]}
    assert channel_ids == {"ch1", "ch2"}
    assert {int(props.get("channel_count", 0)) for props in out["road_properties"]} == {2}
    assert all(bool(props.get("same_pair_multi_road", False)) for props in out["road_properties"])
    assert all(bool(props.get("same_pair_handled", False)) for props in out["road_properties"])
    assert {str(props.get("same_pair_resolution_state")) for props in out["road_properties"]} == {"multi_output_valid"}
    assert {int(props.get("same_pair_final_output_count_for_pair", 0)) for props in out["road_properties"]} == {2}
    assert {int(props.get("same_pair_unresolved_branch_count_for_pair", 0)) for props in out["road_properties"]} == {0}
    assert int(out["metrics_payload"].get("step1_same_pair_multichain_pair_count", 0)) == 1
    assert int(out["metrics_payload"].get("pair_count", 0)) == 1
    assert int(out["metrics_payload"].get("same_pair_handled_pair_count", 0)) == 1
    assert int(out["metrics_payload"].get("same_pair_handled_output_count", 0)) == 2
    assert int(out["metrics_payload"].get("same_pair_single_output_pair_count", 0)) == 0
    assert int(out["metrics_payload"].get("same_pair_multi_road_pair_count", 0)) == 1
    assert int(out["metrics_payload"].get("same_pair_multi_road_output_count", 0)) == 2
    assert int(out["metrics_payload"].get("same_pair_partial_unresolved_pair_count", 0)) == 0
    assert int(out["metrics_payload"].get("same_pair_hard_conflict_pair_count", 0)) == 0
    assert bool(out["gate_payload"]["overall_pass"]) is True
    assert not out["hard_breakpoints"]


def test_topology_unique_mode_same_pair_multichain_uses_road_prior_fallback_for_missing_branch(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
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
    patch_inputs.drivezone_zone_metric = Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 30.0), (-20.0, 30.0)])
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t0", "t1"},
        support_event_count=2,
        traj_segments=[
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            LineString([(0.0, 0.5), (100.0, 0.5)]),
        ],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 0.5)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 0.5)],
        repr_traj_ids=["t0", "t1"],
        hard_anomalies={HARD_MULTI_ROAD},
        evidence_traj_ids=["t0", "t1"],
        evidence_cluster_ids=[0, 0],
        evidence_lengths_m=[100.0, 100.0],
        open_end_flags=[False, False],
    )
    support.cluster_count = 1
    support.main_cluster_id = 0
    support.main_cluster_ratio = 1.0
    support.cluster_sep_m_est = 10.0
    support.cluster_sizes = [2]

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
            node_dst_votes={1: {2: 2}},
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
            "shape_ref_line": kwargs.get("road_prior_shape_ref_metric"),
            "corridor_zone_metric": None,
            "corridor_zone_area_m2": None,
            "corridor_zone_source_count": 0,
            "corridor_zone_half_width_m": None,
            "corridor_shape_ref_inside_ratio": 1.0,
            "gore_fallback_used_src": False,
            "gore_fallback_used_dst": False,
            "traj_drop_count_by_drivezone": 0,
            "drivezone_fallback_used": False,
            "road_prior_shape_ref_used": len(kwargs["support"].support_traj_ids) == 0,
            "road_prior_shape_ref_mode": ("step1_no_traj" if len(kwargs["support"].support_traj_ids) == 0 else None),
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
            "unique_traj_count": int(len(kwargs["support"].support_traj_ids)),
        },
    )

    eval_calls: list[dict[str, object]] = []

    def _fake_eval(**kwargs):  # type: ignore[no-untyped-def]
        ref_line = kwargs.get("road_prior_shape_ref_metric")
        assert isinstance(ref_line, LineString)
        y = float(ref_line.coords[0][1])
        eval_calls.append(
            {
                "cluster_id": int(kwargs["cluster_id"]),
                "candidate_branch_id": kwargs.get("candidate_branch_id"),
                "support_traj_count": int(len(kwargs["support"].support_traj_ids)),
            }
        )
        road = pipeline._make_base_road_record(
            src=int(kwargs["src"]),
            dst=int(kwargs["dst"]),
            support=kwargs["support"],
            src_type=str(kwargs["src_type"]),
            dst_type=str(kwargs["dst_type"]),
            neighbor_search_pass=int(kwargs["neighbor_search_pass"]),
        )
        road["candidate_cluster_id"] = int(kwargs["cluster_id"])
        road["chosen_cluster_id"] = int(kwargs["cluster_id"])
        road["_geometry_metric"] = LineString([(0.0, y), (100.0, y)])
        road["_candidate_has_geometry"] = True
        road["_candidate_feasible"] = True
        road["_candidate_score"] = 100.0 - float(abs(y))
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

    assert len(eval_calls) == 2
    assert {int(item["support_traj_count"]) for item in eval_calls} == {0, 2}
    assert out["road_count"] == 2
    assert len(out["road_properties"]) == 2
    assert {str(props["road_id"]) for props in out["road_properties"]} == {"1_2__ch1", "1_2__ch2"}
    assert {str(props.get("same_pair_multi_road_support_mode")) for props in out["road_properties"]} == {
        "traj_support",
        "road_prior_fallback",
    }
    assert {
        str(props.get("same_pair_multi_road_fallback_reason") or "")
        for props in out["road_properties"]
    } == {"", "missing_branch_traj_support"}
    assert int(out["metrics_payload"].get("same_pair_multi_road_output_count", 0)) == 2
    assert int(out["metrics_payload"].get("same_pair_partial_unresolved_pair_count", 0)) == 0


def test_evaluate_candidate_road_prefers_direct_road_prior_geometry_for_same_pair_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
    )
    params = dict(pipeline.DEFAULT_PARAMS)
    src_xsec = LineString([(0.0, -5.0), (0.0, 15.0)])
    dst_xsec = LineString([(100.0, -5.0), (100.0, 15.0)])
    road_prior_line = LineString([(0.0, 10.0), (100.0, 10.0)])
    bad_centerline = LineString([(0.0, 0.0), (100.0, 0.0)])
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids=set(),
        support_event_count=0,
        traj_segments=[],
        src_cross_points=[Point(0.0, 10.0)],
        dst_cross_points=[Point(100.0, 10.0)],
        hard_anomalies={HARD_MULTI_ROAD},
    )
    parent_support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"parent"},
        support_event_count=1,
        traj_segments=[road_prior_line],
        src_cross_points=[Point(0.0, 10.0)],
        dst_cross_points=[Point(100.0, 10.0)],
        hard_anomalies={HARD_MULTI_ROAD},
    )

    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: geom_mod.CenterEstimate(
            centerline_metric=bad_centerline,
            shape_ref_metric=bad_centerline,
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
            src_cut_mode="none",
            dst_cut_mode="none",
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=set(),
            hard_flags=set(),
            diagnostics={},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: ({}, set(), set(), []),
    )

    road = pipeline._evaluate_candidate_road(
        src=1,
        dst=2,
        src_type="merge",
        dst_type="merge",
        support=support,
        parent_support=parent_support,
        cluster_id=1,
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
        traj_surface_hint={"traj_surface_enforced": False, "surface_metric": None, "timing_ms": 0.0},
        shape_ref_hint_metric=road_prior_line,
        segment_corridor_metric=None,
        road_prior_shape_ref_metric=road_prior_line,
        step1_used_road_prior=True,
        step1_road_prior_mode="step1_no_traj",
        same_pair_multichain=True,
        candidate_branch_id="1_2__b1",
        support_mode="road_prior_fallback",
    )

    geom = road.get("_geometry_metric")
    assert isinstance(geom, LineString)
    assert float(geom.distance(road_prior_line)) <= 1e-6
    assert str(road.get("same_pair_multi_road_geometry_mode")) == "road_prior_direct_fallback"
    assert str(road.get("endpoint_fallback_mode_src")) == "road_prior_direct_fallback"
    assert str(road.get("endpoint_fallback_mode_dst")) == "road_prior_direct_fallback"
    assert bool(road.get("_candidate_has_geometry", False)) is True


def test_topology_unique_mode_uses_road_prior_fallback_when_support_missing(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    road_path = tmp_path / "RCSDRoad.geojson"
    road_payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [100.0, 0.0]]},
                "properties": {"snodeid": 1, "enodeid": 2, "direction": 2, "road_id": "r_main"},
            }
        ],
    }
    road_path.write_text(json.dumps(road_payload, ensure_ascii=False), encoding="utf-8")

    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
        road_prior_path=road_path,
    )
    patch_inputs.drivezone_zone_metric = Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 20.0), (-20.0, 20.0)])

    monkeypatch.setattr(
        pipeline,
        "_build_topology_unique_anchor_decisions",
        lambda *args, **kwargs: (
            {1: {2}},
            {(1, 2)},
            {
                1: {
                    "src_nodeid": 1,
                    "status": "accepted",
                    "reason": "accepted",
                    "dst_nodeids": [2],
                    "chosen_dst_nodeid": 2,
                    "anchor_count": 1,
                    "anchor_ids": ["a0"],
                    "dst_vote_map": {"2": 1},
                    "has_multi_dst_anchor": False,
                    "has_multi_chain_anchor": False,
                    "search_overflow": False,
                }
            },
            {
                "a0": {
                    "anchor_id": "a0",
                    "src_nodeid": 1,
                    "status": "accepted",
                    "reason": "accepted",
                    "search_direction": "forward",
                    "pair_src_nodeid": 1,
                    "pair_dst_nodeid": 2,
                    "chosen_dst_nodeid": 2,
                    "dst_paths": {"2": [{"edge_ids": ["r_main"], "node_path": [1, 2]}]},
                }
            },
            {
                "accepted_src_count": 1,
                "unresolved_src_count": 0,
                "multi_dst_src_count": 0,
                "multi_chain_src_count": 0,
                "search_overflow_src_count": 0,
                "accepted_pair_count": 1,
            },
            [],
            [],
        ),
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
    monkeypatch.setattr(
        pipeline,
        "build_pair_supports",
        lambda *args, **kwargs: PairSupportBuildResult(
            supports={},
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
            node_dst_votes={},
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
            "strategy": "generic_forward_trace|fallback_no_traj",
            "hard_reason": None,
            "hard_hint": "step1_corridor_road_prior_fallback",
            "corridor_count": 1,
            "main_corridor_ratio": 1.0,
            "shape_ref_line": kwargs.get("road_prior_shape_ref_metric"),
            "corridor_zone_metric": None,
            "corridor_zone_area_m2": None,
            "corridor_zone_source_count": 0,
            "corridor_zone_half_width_m": None,
            "corridor_shape_ref_inside_ratio": 1.0,
            "gore_fallback_used_src": False,
            "gore_fallback_used_dst": False,
            "traj_drop_count_by_drivezone": 0,
            "drivezone_fallback_used": False,
            "road_prior_shape_ref_used": True,
            "road_prior_shape_ref_mode": "step1_no_traj",
        },
    )

    eval_calls: list[str] = []

    def _fake_eval(**kwargs):  # type: ignore[no-untyped-def]
        eval_calls.append(str(kwargs.get("support_mode") or ""))
        ref_line = kwargs.get("road_prior_shape_ref_metric")
        assert isinstance(ref_line, LineString)
        road = pipeline._make_base_road_record(
            src=int(kwargs["src"]),
            dst=int(kwargs["dst"]),
            support=kwargs["support"],
            src_type=str(kwargs["src_type"]),
            dst_type=str(kwargs["dst_type"]),
            neighbor_search_pass=int(kwargs["neighbor_search_pass"]),
        )
        road["_geometry_metric"] = ref_line
        road["_candidate_has_geometry"] = True
        road["_candidate_feasible"] = True
        road["_candidate_score"] = 100.0
        road["_candidate_in_ratio"] = 1.0
        road["_candidate_hard_breakpoints"] = []
        road["_candidate_soft_breakpoints"] = []
        road["hard_reasons"] = []
        road["soft_issue_flags"] = []
        road["length_m"] = float(ref_line.length)
        road["conf"] = 0.8
        return road

    monkeypatch.setattr(pipeline, "_evaluate_candidate_road", _fake_eval)

    out = pipeline._run_patch_core(
        patch_inputs,
        params=dict(pipeline.DEFAULT_PARAMS),
        run_id="unit_run",
        repo_root=tmp_path,
    )

    assert eval_calls == ["topology_road_prior_fallback"]
    assert out["road_count"] == 1
    assert int(out["metrics_payload"].get("topology_fallback_support_count", 0)) == 1


def test_evaluate_candidate_road_rescues_corridor_only_failure_with_shape_ref(
    tmp_path: Path, monkeypatch
) -> None:
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
    )
    patch_inputs.drivezone_zone_metric = Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 20.0), (-20.0, 20.0)])
    params = dict(pipeline.DEFAULT_PARAMS)
    src_xsec = LineString([(0.0, -5.0), (0.0, 15.0)])
    dst_xsec = LineString([(100.0, -5.0), (100.0, 15.0)])
    road_prior_line = LineString([(0.0, 10.0), (100.0, 10.0)])
    bad_centerline = LineString([(0.0, 10.0), (49.0, 10.0), (50.0, 10.8), (51.0, 10.0), (100.0, 10.0)])
    corridor_zone = road_prior_line.buffer(0.5, cap_style=2)
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t0"},
        support_event_count=1,
        traj_segments=[road_prior_line],
        src_cross_points=[Point(0.0, 10.0)],
        dst_cross_points=[Point(100.0, 10.0)],
    )

    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: geom_mod.CenterEstimate(
            centerline_metric=bad_centerline,
            shape_ref_metric=None,
            lb_path_found=False,
            lb_path_edge_count=0,
            lb_path_length_m=None,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=1.0,
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
            src_cut_mode="none",
            dst_cut_mode="none",
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=set(),
            hard_flags=set(),
            diagnostics={},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: ({}, set(), set(), []),
    )

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
        traj_surface_hint={"traj_surface_enforced": False, "surface_metric": None, "timing_ms": 0.0},
        shape_ref_hint_metric=road_prior_line,
        segment_corridor_metric=corridor_zone,
        road_prior_shape_ref_metric=None,
        step1_used_road_prior=False,
        step1_road_prior_mode=None,
        same_pair_multichain=False,
        candidate_branch_id=None,
    )

    geom = road.get("_geometry_metric")
    assert isinstance(geom, LineString)
    assert float(geom.distance(road_prior_line)) <= 1e-6
    assert str(road.get("segment_corridor_rescue_mode")) == "shape_ref_substring"
    assert pipeline._HARD_ROAD_OUTSIDE_SEGMENT_CORRIDOR not in set(road.get("hard_reasons") or [])
    assert bool(road.get("_candidate_feasible", False)) is True


def test_build_topology_road_prior_fallback_support_uses_pair_endpoint_xsecs() -> None:
    params = dict(pipeline.DEFAULT_PARAMS)
    shape_ref = LineString([(5.0, 0.0), (95.0, 0.0)])
    src_xsec = LineString([(0.0, -8.0), (0.0, 8.0)])
    dst_xsec = LineString([(100.0, -8.0), (100.0, 8.0)])
    debug_out: dict[str, object] = {}

    out = pipeline._build_topology_road_prior_fallback_support(
        pair=(1, 2),
        shape_ref_metric=shape_ref,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 20.0), (-20.0, 20.0)]),
        gore_zone_metric=Polygon(),
        src_type="diverge",
        dst_type="merge",
        params=params,
        debug_out=debug_out,
    )

    assert out is not None
    assert int(out.src_nodeid) == 1
    assert int(out.dst_nodeid) == 2
    assert abs(float(out.src_cross_points[0].x) - 5.0) <= 1e-6
    assert abs(float(out.dst_cross_points[0].x) - 95.0) <= 1e-6
    assert out.hints[-1] == "topology_road_prior_fallback"
    assert debug_out["failure_stage"] == "accepted"
    assert debug_out["src_contact_found"] is True
    assert debug_out["dst_contact_found"] is True
    assert abs(float(debug_out["src_gap_m"] or 0.0)) <= 1e-6
    assert abs(float(debug_out["dst_gap_m"] or 0.0)) <= 1e-6


def test_build_topology_road_prior_fallback_support_reports_xsec_contact_failure() -> None:
    params = dict(pipeline.DEFAULT_PARAMS)
    shape_ref = LineString([(5.0, 0.0), (95.0, 0.0)])
    src_xsec = LineString([(0.0, -8.0), (0.0, 8.0)])
    dst_xsec = LineString([(100.0, -8.0), (100.0, 8.0)])
    debug_out: dict[str, object] = {}

    out = pipeline._build_topology_road_prior_fallback_support(
        pair=(1, 2),
        shape_ref_metric=shape_ref,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 20.0), (-20.0, 20.0)]),
        gore_zone_metric=Polygon(),
        src_type="merge",
        dst_type="diverge",
        params=params,
        debug_out=debug_out,
    )

    assert out is None
    assert debug_out["failure_stage"] == "src_xsec_contact"
    assert debug_out["src_contact_found"] is False
    assert debug_out["dst_contact_found"] is False
    assert debug_out["reach_xsec_m"] is None


def test_build_topology_road_prior_fallback_support_reports_reach_xsec_failure() -> None:
    params = dict(pipeline.DEFAULT_PARAMS)
    shape_ref = LineString([(40.0, 0.0), (60.0, 0.0)])
    src_xsec = LineString([(0.0, -8.0), (0.0, 8.0)])
    dst_xsec = LineString([(100.0, -8.0), (100.0, 8.0)])
    debug_out: dict[str, object] = {}

    out = pipeline._build_topology_road_prior_fallback_support(
        pair=(1, 2),
        shape_ref_metric=shape_ref,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 20.0), (-20.0, 20.0)]),
        gore_zone_metric=Polygon(),
        src_type="merge",
        dst_type="diverge",
        params=params,
        debug_out=debug_out,
    )

    assert out is None
    assert debug_out["failure_stage"] == "reach_xsec"
    assert debug_out["src_contact_found"] is True
    assert debug_out["dst_contact_found"] is True
    assert float(debug_out["src_gap_m"] or 0.0) > float(debug_out["reach_xsec_m"] or 0.0)
    assert float(debug_out["dst_gap_m"] or 0.0) > float(debug_out["reach_xsec_m"] or 0.0)


def test_build_topology_road_prior_fallback_support_allows_shifted_entry_xsec_bonus(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    params = dict(pipeline.DEFAULT_PARAMS)
    shape_ref = LineString([(23.0, 0.0), (100.0, 0.0)])
    src_xsec = LineString([(0.0, -8.0), (0.0, 8.0)])
    dst_xsec = LineString([(100.0, -8.0), (100.0, 8.0)])
    src_entry_xsec = LineString([(-15.0, -8.0), (-15.0, 8.0)])
    dst_entry_xsec = LineString([(127.0, -8.0), (127.0, 8.0)])
    debug_out: dict[str, object] = {}

    monkeypatch.setattr(
        pipeline,
        "_resolve_fallback_support_entry_xsecs",
        lambda **kwargs: (shape_ref, src_entry_xsec, dst_entry_xsec),
    )

    out = pipeline._build_topology_road_prior_fallback_support(
        pair=(1, 2),
        shape_ref_metric=shape_ref,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=Polygon([(-30.0, -20.0), (140.0, -20.0), (140.0, 20.0), (-30.0, 20.0)]),
        gore_zone_metric=Polygon(),
        src_type="diverge",
        dst_type="merge",
        params=params,
        debug_out=debug_out,
    )

    assert out is not None
    assert debug_out["failure_stage"] == "accepted"
    assert float(debug_out["src_gap_m"] or 0.0) > float(debug_out["reach_xsec_m"] or 0.0)
    assert float(debug_out["dst_gap_m"] or 0.0) > float(debug_out["reach_xsec_m"] or 0.0)
    assert float(debug_out["src_reach_allow_m"] or 0.0) >= float(debug_out["src_gap_m"] or 0.0)
    assert float(debug_out["dst_reach_allow_m"] or 0.0) >= float(debug_out["dst_gap_m"] or 0.0)
    assert float(debug_out["src_entry_xsec_shift_m"] or 0.0) > 0.0
    assert float(debug_out["dst_entry_xsec_shift_m"] or 0.0) > 0.0


def test_build_topology_road_prior_fallback_support_allows_endpoint_snap_bonus(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    params = dict(pipeline.DEFAULT_PARAMS)
    shape_ref = LineString([(38.0, 0.0), (73.0, 0.0)])
    src_xsec = LineString([(0.0, -8.0), (0.0, 8.0)])
    dst_xsec = LineString([(100.0, -8.0), (100.0, 8.0)])
    debug_out: dict[str, object] = {}

    monkeypatch.setattr(
        pipeline,
        "_resolve_fallback_support_entry_xsecs",
        lambda **kwargs: (shape_ref, src_xsec, dst_xsec),
    )

    out = pipeline._build_topology_road_prior_fallback_support(
        pair=(1, 2),
        shape_ref_metric=shape_ref,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=Polygon([(-30.0, -20.0), (130.0, -20.0), (130.0, 20.0), (-30.0, 20.0)]),
        gore_zone_metric=Polygon(),
        src_type="diverge",
        dst_type="merge",
        params=params,
        debug_out=debug_out,
    )

    assert out is not None
    assert debug_out["failure_stage"] == "accepted"
    assert float(debug_out["src_gap_m"] or 0.0) > float(debug_out["reach_xsec_m"] or 0.0)
    assert float(debug_out["dst_gap_m"] or 0.0) > float(debug_out["reach_xsec_m"] or 0.0)
    assert float(debug_out["src_reach_allow_m"] or 0.0) >= float(debug_out["src_gap_m"] or 0.0)
    assert float(debug_out["dst_reach_allow_m"] or 0.0) >= float(debug_out["dst_gap_m"] or 0.0)
    assert abs(float(debug_out["src_entry_xsec_shift_m"] or 0.0)) <= 1e-6
    assert abs(float(debug_out["dst_entry_xsec_shift_m"] or 0.0)) <= 1e-6


def test_build_topology_road_prior_fallback_support_reports_drivezone_failure() -> None:
    params = dict(pipeline.DEFAULT_PARAMS)
    shape_ref = LineString([(5.0, 0.0), (95.0, 0.0)])
    src_xsec = LineString([(0.0, -8.0), (0.0, 8.0)])
    dst_xsec = LineString([(100.0, -8.0), (100.0, 8.0)])
    debug_out: dict[str, object] = {}

    out = pipeline._build_topology_road_prior_fallback_support(
        pair=(1, 2),
        shape_ref_metric=shape_ref,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=Polygon([(-20.0, -20.0), (25.0, -20.0), (25.0, 20.0), (-20.0, 20.0)]),
        gore_zone_metric=Polygon(),
        src_type="diverge",
        dst_type="merge",
        params=params,
        debug_out=debug_out,
    )

    assert out is None
    assert debug_out["failure_stage"] == "drivezone_inside_ratio"
    assert debug_out["src_contact_found"] is True
    assert debug_out["dst_contact_found"] is True
    assert float(debug_out["inside_ratio"] or 0.0) < float(debug_out["inside_ratio_min"] or 0.0)


def test_same_pair_resolution_stats_mark_partial_unresolved_pair() -> None:
    valid = {
        "road_id": "1_2__ch1",
        "src_nodeid": 1,
        "dst_nodeid": 2,
        "same_pair_handled": True,
        "same_pair_multi_road": True,
        "step1_same_pair_multichain": True,
        "_geometry_metric": LineString([(0.0, 0.0), (10.0, 0.0)]),
        "hard_reasons": [],
        "no_geometry_candidate": False,
    }
    unresolved = {
        "road_id": "1_2__ch2",
        "src_nodeid": 1,
        "dst_nodeid": 2,
        "same_pair_handled": True,
        "same_pair_multi_road": True,
        "step1_same_pair_multichain": True,
        "_geometry_metric": None,
        "hard_reasons": ["MULTI_ROAD_SAME_PAIR"],
        "no_geometry_candidate": True,
    }

    stats = pipeline._annotate_same_pair_resolution_states([valid, unresolved])

    assert stats["same_pair_handled_pair_count"] == 1
    assert stats["same_pair_handled_output_count"] == 1
    assert stats["same_pair_single_output_pair_count"] == 0
    assert stats["same_pair_multi_road_pair_count"] == 0
    assert stats["same_pair_multi_road_output_count"] == 0
    assert stats["same_pair_partial_unresolved_pair_count"] == 1
    assert stats["same_pair_hard_conflict_pair_count"] == 0
    assert valid["same_pair_resolution_state"] == "partial_unresolved"
    assert unresolved["same_pair_resolution_state"] == "partial_unresolved"
    assert valid["same_pair_final_output_count_for_pair"] == 1
    assert valid["same_pair_unresolved_branch_count_for_pair"] == 1


def test_evaluate_candidate_road_same_pair_traj_support_rescues_with_branch_shape_ref(
    tmp_path: Path, monkeypatch
) -> None:
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
    )
    patch_inputs.drivezone_zone_metric = Polygon([(-20.0, -15.0), (120.0, -15.0), (120.0, 15.0), (-20.0, 15.0)])
    params = dict(pipeline.DEFAULT_PARAMS)
    src_xsec = LineString([(0.0, -5.0), (0.0, 5.0)])
    dst_xsec = LineString([(100.0, -5.0), (100.0, 5.0)])
    road_prior_line = LineString([(0.0, 0.0), (100.0, 0.0)])
    bad_centerline = LineString([(0.0, 0.0), (30.0, 0.0), (50.0, 25.0), (70.0, 0.0), (100.0, 0.0)])
    corridor_zone = road_prior_line.buffer(0.5, cap_style=2)
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t0", "t1"},
        support_event_count=2,
        traj_segments=[road_prior_line, road_prior_line],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 0.0)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 0.0)],
    )

    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: geom_mod.CenterEstimate(
            centerline_metric=bad_centerline,
            shape_ref_metric=road_prior_line,
            lb_path_found=False,
            lb_path_edge_count=0,
            lb_path_length_m=None,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=1.0,
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
            src_cut_mode="none",
            dst_cut_mode="none",
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=set(),
            hard_flags=set(),
            diagnostics={},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: ({}, set(), set(), []),
    )

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
        traj_surface_hint={"traj_surface_enforced": False, "surface_metric": None, "timing_ms": 0.0},
        shape_ref_hint_metric=road_prior_line,
        segment_corridor_metric=corridor_zone,
        road_prior_shape_ref_metric=road_prior_line,
        step1_used_road_prior=False,
        step1_road_prior_mode=None,
        same_pair_multichain=True,
        candidate_branch_id="1_2__b0",
        support_mode="traj_support",
    )

    geom = road.get("_geometry_metric")
    assert isinstance(geom, LineString)
    assert float(geom.distance(road_prior_line)) <= 1e-6
    assert str(road.get("same_pair_multi_road_geometry_mode")) == "road_prior_direct_rescue"
    assert pipeline.HARD_ROAD_OUTSIDE_DRIVEZONE not in set(road.get("hard_reasons") or [])
    assert pipeline._HARD_ROAD_OUTSIDE_SEGMENT_CORRIDOR not in set(road.get("hard_reasons") or [])
    assert bool(road.get("_candidate_feasible", False)) is True


def test_evaluate_candidate_road_same_pair_traj_support_rescues_with_branch_corridor_override(
    tmp_path: Path, monkeypatch
) -> None:
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
    )
    patch_inputs.drivezone_zone_metric = Polygon([(-20.0, -15.0), (120.0, -15.0), (120.0, 15.0), (-20.0, 15.0)])
    params = dict(pipeline.DEFAULT_PARAMS)
    src_xsec = LineString([(0.0, -5.0), (0.0, 5.0)])
    dst_xsec = LineString([(100.0, -5.0), (100.0, 5.0)])
    road_prior_line = LineString([(0.0, 0.0), (100.0, 0.0)])
    bad_centerline = LineString([(0.0, 0.0), (30.0, 0.0), (50.0, 25.0), (70.0, 0.0), (100.0, 0.0)])
    misaligned_corridor = LineString([(0.0, 20.0), (100.0, 20.0)]).buffer(0.5, cap_style=2)
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t0", "t1"},
        support_event_count=2,
        traj_segments=[road_prior_line, road_prior_line],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 0.0)],
        dst_cross_points=[Point(100.0, 0.0), Point(100.0, 0.0)],
    )

    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: geom_mod.CenterEstimate(
            centerline_metric=bad_centerline,
            shape_ref_metric=road_prior_line,
            lb_path_found=False,
            lb_path_edge_count=0,
            lb_path_length_m=None,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=1.0,
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
            src_cut_mode="none",
            dst_cut_mode="none",
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=set(),
            hard_flags=set(),
            diagnostics={},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: ({}, set(), set(), []),
    )

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
        traj_surface_hint={"traj_surface_enforced": False, "surface_metric": None, "timing_ms": 0.0},
        shape_ref_hint_metric=road_prior_line,
        segment_corridor_metric=misaligned_corridor,
        road_prior_shape_ref_metric=road_prior_line,
        step1_used_road_prior=False,
        step1_road_prior_mode=None,
        same_pair_multichain=True,
        candidate_branch_id="1_2__b0",
        support_mode="traj_support",
    )

    geom = road.get("_geometry_metric")
    assert isinstance(geom, LineString)
    assert float(geom.distance(road_prior_line)) <= 1e-6
    assert str(road.get("same_pair_multi_road_geometry_mode")) == "road_prior_direct_rescue"
    assert str(road.get("segment_corridor_source")) == "road_prior_branch_rescue"
    assert str(road.get("segment_corridor_rescue_mode")) == "road_prior_branch_corridor"
    assert pipeline._HARD_ROAD_OUTSIDE_SEGMENT_CORRIDOR not in set(road.get("hard_reasons") or [])
    assert pipeline.HARD_ROAD_OUTSIDE_DRIVEZONE not in set(road.get("hard_reasons") or [])
    assert bool(road.get("_candidate_feasible", False)) is True


def test_evaluate_candidate_road_topology_fallback_extends_endpoint_snap_cap(
    tmp_path: Path, monkeypatch
) -> None:
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
    )
    patch_inputs.drivezone_zone_metric = Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 20.0), (-20.0, 20.0)])
    params = dict(pipeline.DEFAULT_PARAMS)
    src_xsec = LineString([(0.0, -5.0), (0.0, 5.0)])
    dst_xsec = LineString([(100.0, -5.0), (100.0, 5.0)])
    mid_line = LineString([(38.0, 0.0), (73.0, 0.0)])
    gate_corridor = LineString([(0.0, 0.0), (100.0, 0.0)]).buffer(20.0, cap_style=2)
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids=set(),
        support_event_count=0,
        traj_segments=[],
        src_cross_points=[],
        dst_cross_points=[],
    )

    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: geom_mod.CenterEstimate(
            centerline_metric=mid_line,
            shape_ref_metric=mid_line,
            lb_path_found=False,
            lb_path_edge_count=0,
            lb_path_length_m=None,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=1.0,
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
            src_cut_mode="none",
            dst_cut_mode="none",
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=set(),
            hard_flags=set(),
            diagnostics={},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: ({}, set(), set(), []),
    )

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
        traj_surface_hint={"traj_surface_enforced": False, "surface_metric": None, "timing_ms": 0.0},
        shape_ref_hint_metric=mid_line,
        segment_corridor_metric=gate_corridor,
        road_prior_shape_ref_metric=mid_line,
        step1_used_road_prior=False,
        step1_road_prior_mode=None,
        same_pair_multichain=False,
        candidate_branch_id=None,
        support_mode="topology_road_prior_fallback",
    )

    geom = road.get("_geometry_metric")
    assert isinstance(geom, LineString)
    assert abs(float(geom.coords[0][0]) - 0.0) <= 1e-6
    assert abs(float(geom.coords[-1][0]) - 100.0) <= 1e-6
    assert abs(float(road.get("endpoint_dist_to_xsec_src_m") or 0.0)) <= 1e-6
    assert abs(float(road.get("endpoint_dist_to_xsec_dst_m") or 0.0)) <= 1e-6
    assert float(road.get("endpoint_snap_dist_src_before_m") or 0.0) > float(params["XSEC_ENDPOINT_MAX_DIST_M"])
    assert float(road.get("endpoint_snap_dist_dst_before_m") or 0.0) > float(params["XSEC_ENDPOINT_MAX_DIST_M"])
    assert bool(road.get("_candidate_feasible", False)) is True


def test_evaluate_candidate_road_topology_fallback_prefers_pair_target_xsec(
    tmp_path: Path, monkeypatch
) -> None:
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
    )
    patch_inputs.drivezone_zone_metric = Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 20.0), (-20.0, 20.0)])
    params = dict(pipeline.DEFAULT_PARAMS)
    src_xsec = LineString([(0.0, -5.0), (0.0, 5.0)])
    dst_xsec = LineString([(100.0, -5.0), (100.0, 5.0)])
    src_pair_target = LineString([(20.0, -5.0), (20.0, 5.0)])
    dst_pair_target = LineString([(80.0, -5.0), (80.0, 5.0)])
    road_prior_line = LineString([(20.0, 0.0), (80.0, 0.0)])
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids=set(),
        support_event_count=0,
        traj_segments=[],
        src_cross_points=[],
        dst_cross_points=[],
    )

    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: geom_mod.CenterEstimate(
            centerline_metric=LineString([(35.0, 0.0), (65.0, 0.0)]),
            shape_ref_metric=LineString([(35.0, 0.0), (65.0, 0.0)]),
            lb_path_found=False,
            lb_path_edge_count=0,
            lb_path_length_m=None,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=1.0,
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
            src_cut_mode="none",
            dst_cut_mode="none",
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=set(),
            hard_flags=set(),
            diagnostics={},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: ({}, set(), set(), []),
    )

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
        traj_surface_hint={"traj_surface_enforced": False, "surface_metric": None, "timing_ms": 0.0},
        shape_ref_hint_metric=road_prior_line,
        segment_corridor_metric=road_prior_line.buffer(20.0, cap_style=2),
        road_prior_shape_ref_metric=road_prior_line,
        step1_used_road_prior=False,
        step1_road_prior_mode=None,
        same_pair_multichain=False,
        candidate_branch_id=None,
        support_mode="topology_road_prior_fallback",
        pair_xsec_target_src_metric=src_pair_target,
        pair_xsec_target_dst_metric=dst_pair_target,
    )

    geom = road.get("_geometry_metric")
    assert isinstance(geom, LineString)
    assert abs(float(geom.coords[0][0]) - 20.0) <= 1e-6
    assert abs(float(geom.coords[-1][0]) - 80.0) <= 1e-6
    assert str(road.get("xsec_road_selected_by_src")) == "pair_target_topology_fallback"
    assert str(road.get("xsec_road_selected_by_dst")) == "pair_target_topology_fallback"
    assert abs(float(road.get("endpoint_dist_to_xsec_src_m") or 0.0)) <= 1e-6
    assert abs(float(road.get("endpoint_dist_to_xsec_dst_m") or 0.0)) <= 1e-6
    assert bool(road.get("_candidate_feasible", False)) is True


def test_evaluate_candidate_road_topology_fallback_uses_entry_xsec_when_pair_target_missing(
    tmp_path: Path, monkeypatch
) -> None:
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
    )
    patch_inputs.drivezone_zone_metric = Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 20.0), (-20.0, 20.0)])
    params = dict(pipeline.DEFAULT_PARAMS)
    src_xsec = LineString([(0.0, -5.0), (0.0, 5.0)])
    dst_xsec = LineString([(100.0, -5.0), (100.0, 5.0)])
    src_entry_xsec = LineString([(20.0, -5.0), (20.0, 5.0)])
    dst_entry_xsec = LineString([(80.0, -5.0), (80.0, 5.0)])
    road_prior_line = LineString([(20.0, 0.0), (80.0, 0.0)])
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids=set(),
        support_event_count=0,
        traj_segments=[],
        src_cross_points=[],
        dst_cross_points=[],
    )

    monkeypatch.setattr(
        pipeline,
        "_resolve_fallback_support_entry_xsecs",
        lambda **kwargs: (kwargs["shape_ref_metric"], src_entry_xsec, dst_entry_xsec),
    )
    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: geom_mod.CenterEstimate(
            centerline_metric=LineString([(35.0, 0.0), (65.0, 0.0)]),
            shape_ref_metric=LineString([(35.0, 0.0), (65.0, 0.0)]),
            lb_path_found=False,
            lb_path_edge_count=0,
            lb_path_length_m=None,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=1.0,
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
            src_cut_mode="none",
            dst_cut_mode="none",
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=set(),
            hard_flags=set(),
            diagnostics={},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: ({}, set(), set(), []),
    )

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
        traj_surface_hint={"traj_surface_enforced": False, "surface_metric": None, "timing_ms": 0.0},
        shape_ref_hint_metric=road_prior_line,
        segment_corridor_metric=road_prior_line.buffer(20.0, cap_style=2),
        road_prior_shape_ref_metric=road_prior_line,
        step1_used_road_prior=False,
        step1_road_prior_mode=None,
        same_pair_multichain=False,
        candidate_branch_id=None,
        support_mode="topology_road_prior_fallback",
    )

    geom = road.get("_geometry_metric")
    assert isinstance(geom, LineString)
    assert abs(float(geom.coords[0][0]) - 20.0) <= 1e-6
    assert abs(float(geom.coords[-1][0]) - 80.0) <= 1e-6
    assert str(road.get("xsec_road_selected_by_src")) == "topology_fallback_entry_xsec"
    assert str(road.get("xsec_road_selected_by_dst")) == "topology_fallback_entry_xsec"
    assert abs(float(road.get("endpoint_dist_to_xsec_src_m") or 0.0)) <= 1e-6
    assert abs(float(road.get("endpoint_dist_to_xsec_dst_m") or 0.0)) <= 1e-6


def test_evaluate_candidate_road_topology_fallback_uses_road_prior_corridor(
    tmp_path: Path, monkeypatch
) -> None:
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
    )
    patch_inputs.drivezone_zone_metric = Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 20.0), (-20.0, 20.0)])
    params = dict(pipeline.DEFAULT_PARAMS)
    src_xsec = LineString([(0.0, -5.0), (0.0, 5.0)])
    dst_xsec = LineString([(100.0, -5.0), (100.0, 5.0)])
    road_prior_line = LineString([(0.0, 0.0), (100.0, 0.0)])
    misaligned_corridor = LineString([(0.0, 20.0), (100.0, 20.0)]).buffer(0.5, cap_style=2)
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids=set(),
        support_event_count=0,
        traj_segments=[],
        src_cross_points=[],
        dst_cross_points=[],
    )

    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: geom_mod.CenterEstimate(
            centerline_metric=road_prior_line,
            shape_ref_metric=road_prior_line,
            lb_path_found=False,
            lb_path_edge_count=0,
            lb_path_length_m=None,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=1.0,
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
            src_cut_mode="none",
            dst_cut_mode="none",
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=set(),
            hard_flags=set(),
            diagnostics={},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: ({}, set(), set(), []),
    )

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
        traj_surface_hint={"traj_surface_enforced": False, "surface_metric": None, "timing_ms": 0.0},
        shape_ref_hint_metric=road_prior_line,
        segment_corridor_metric=misaligned_corridor,
        road_prior_shape_ref_metric=road_prior_line,
        step1_used_road_prior=False,
        step1_road_prior_mode=None,
        same_pair_multichain=False,
        candidate_branch_id=None,
        support_mode="topology_road_prior_fallback",
    )

    assert str(road.get("segment_corridor_source")) == "road_prior"
    assert pipeline._HARD_ROAD_OUTSIDE_SEGMENT_CORRIDOR not in set(road.get("hard_reasons") or [])
    assert bool(road.get("_candidate_feasible", False)) is True


def test_evaluate_candidate_road_topology_fallback_rescues_with_direct_road_prior_geometry(
    tmp_path: Path, monkeypatch
) -> None:
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
    )
    patch_inputs.drivezone_zone_metric = Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 20.0), (-20.0, 20.0)])
    params = dict(pipeline.DEFAULT_PARAMS)
    src_xsec = LineString([(0.0, -5.0), (0.0, 5.0)])
    dst_xsec = LineString([(100.0, -5.0), (100.0, 5.0)])
    road_prior_line = LineString([(0.0, 0.0), (100.0, 0.0)])
    bad_centerline = LineString([(0.0, 0.0), (30.0, 0.0), (50.0, 25.0), (70.0, 0.0), (100.0, 0.0)])
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids=set(),
        support_event_count=0,
        traj_segments=[],
        src_cross_points=[],
        dst_cross_points=[],
    )

    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: geom_mod.CenterEstimate(
            centerline_metric=bad_centerline,
            shape_ref_metric=bad_centerline,
            lb_path_found=False,
            lb_path_edge_count=0,
            lb_path_length_m=None,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=1.0,
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
            src_cut_mode="none",
            dst_cut_mode="none",
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=set(),
            hard_flags=set(),
            diagnostics={},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: ({}, set(), set(), []),
    )

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
        traj_surface_hint={"traj_surface_enforced": False, "surface_metric": None, "timing_ms": 0.0},
        shape_ref_hint_metric=bad_centerline,
        segment_corridor_metric=bad_centerline.buffer(1.0, cap_style=2),
        road_prior_shape_ref_metric=road_prior_line,
        step1_used_road_prior=False,
        step1_road_prior_mode=None,
        same_pair_multichain=False,
        candidate_branch_id=None,
        support_mode="topology_road_prior_fallback",
    )

    geom = road.get("_geometry_metric")
    assert isinstance(geom, LineString)
    assert float(geom.distance(road_prior_line)) <= 1e-6
    assert str(road.get("topology_fallback_geometry_mode")) == "road_prior_direct_fallback"
    assert pipeline._HARD_ROAD_OUTSIDE_SEGMENT_CORRIDOR not in set(road.get("hard_reasons") or [])
    assert pipeline.HARD_ROAD_OUTSIDE_DRIVEZONE not in set(road.get("hard_reasons") or [])
    assert bool(road.get("_candidate_feasible", False)) is True


def test_build_same_pair_multichain_variants_adds_fallback_for_weak_branch_support(
    monkeypatch,
) -> None:
    weak_ref = LineString([(0.0, 0.0), (100.0, 0.0)])
    strong_ref = LineString([(0.0, 10.0), (100.0, 10.0)])
    branch_defs = [
        {
            "branch_id": "1_2__b0",
            "branch_rank": 1,
            "signature": ["e0"],
            "shape_ref_metric": weak_ref,
            "src_station_m": 1.0,
            "dst_station_m": 1.0,
        },
        {
            "branch_id": "1_2__b1",
            "branch_rank": 2,
            "signature": ["e1"],
            "shape_ref_metric": strong_ref,
            "src_station_m": 2.0,
            "dst_station_m": 2.0,
        },
    ]
    weak_support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t0"},
        support_event_count=1,
        traj_segments=[weak_ref],
        src_cross_points=[Point(0.0, 0.0)],
        dst_cross_points=[Point(100.0, 0.0)],
        open_end=True,
    )
    strong_support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t1", "t2"},
        support_event_count=2,
        traj_segments=[strong_ref, strong_ref],
        src_cross_points=[Point(0.0, 10.0), Point(0.0, 10.0)],
        dst_cross_points=[Point(100.0, 10.0), Point(100.0, 10.0)],
    )
    weak_fallback_support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids=set(),
        support_event_count=0,
        traj_segments=[],
        src_cross_points=[Point(0.0, 0.0)],
        dst_cross_points=[Point(100.0, 0.0)],
    )

    monkeypatch.setattr(
        pipeline,
        "_build_same_pair_multichain_branch_defs",
        lambda **kwargs: branch_defs,
    )
    monkeypatch.setattr(
        pipeline,
        "_build_same_pair_multichain_branch_supports",
        lambda *args, **kwargs: [
            (dict(branch_defs[0]), weak_support),
            (dict(branch_defs[1]), strong_support),
        ],
    )
    monkeypatch.setattr(
        pipeline,
        "_build_same_pair_multichain_fallback_support",
        lambda parent_support, **kwargs: weak_fallback_support,
    )
    monkeypatch.setattr(
        pipeline,
        "_build_step1_corridor_for_pair",
        lambda **kwargs: {
            "hard_reason": None,
            "shape_ref_line": kwargs.get("road_prior_shape_ref_metric"),
            "corridor_zone_metric": kwargs.get("road_prior_shape_ref_metric").buffer(2.0, cap_style=2),
            "road_prior_shape_ref_used": False,
            "road_prior_shape_ref_mode": None,
        },
    )

    variants = pipeline._build_same_pair_multichain_variants(
        pair=(1, 2),
        support=strong_support,
        src_type="merge",
        dst_type="merge",
        src_xsec=LineString([(0.0, -5.0), (0.0, 15.0)]),
        dst_xsec=LineString([(100.0, -5.0), (100.0, 15.0)]),
        drivezone_zone_metric=Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 30.0), (-20.0, 30.0)]),
        gore_zone_metric=None,
        params=dict(pipeline.DEFAULT_PARAMS),
        anchor_decisions={},
        edge_geometry_by_id={},
    )

    weak_branch_variants = [v for v in variants if str(v.get("branch_id")) == "1_2__b0"]
    strong_branch_variants = [v for v in variants if str(v.get("branch_id")) == "1_2__b1"]

    assert len(weak_branch_variants) == 2
    assert {str(v.get("support_mode")) for v in weak_branch_variants} == {"traj_support", "road_prior_fallback"}
    assert {
        str(v.get("support_fallback_reason"))
        for v in weak_branch_variants
        if str(v.get("support_mode")) == "road_prior_fallback"
    } == {"weak_branch_traj_support"}
    assert len(strong_branch_variants) == 1
    assert str(strong_branch_variants[0].get("support_mode")) == "traj_support"


def test_same_pair_branch_support_needs_fallback_variant_for_open_end() -> None:
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t0", "t1"},
        support_event_count=2,
        traj_segments=[],
        src_cross_points=[Point(0.0, 0.0), Point(0.0, 0.0)],
        dst_cross_points=[Point(1.0, 0.0), Point(1.0, 0.0)],
        open_end=True,
    )
    assert pipeline._same_pair_branch_support_needs_fallback_variant(
        support,
        params=dict(pipeline.DEFAULT_PARAMS),
    ) is True


def test_same_pair_branch_display_candidates_prefers_selectable_fallback() -> None:
    fallback = {
        "same_pair_multi_road_branch_id": "1_2__b0",
        "candidate_branch_id": "1_2__b0",
        "step1_same_pair_multichain": True,
        "same_pair_multi_road_support_mode": "road_prior_fallback",
        "_geometry_metric": LineString([(0.0, 0.0), (100.0, 0.0)]),
        "_candidate_has_geometry": True,
        "_candidate_feasible": False,
        "hard_reasons": [],
        "_candidate_score": 5.0,
    }
    blocked = {
        "same_pair_multi_road_branch_id": "1_2__b0",
        "candidate_branch_id": "1_2__b0",
        "step1_same_pair_multichain": True,
        "same_pair_multi_road_support_mode": "traj_support",
        "_geometry_metric": LineString([(0.0, 0.0), (100.0, 0.0)]),
        "_candidate_has_geometry": True,
        "_candidate_feasible": False,
        "hard_reasons": [pipeline.HARD_ROAD_OUTSIDE_DRIVEZONE],
        "_candidate_score": 10.0,
    }
    clean = {
        "same_pair_multi_road_branch_id": "1_2__b1",
        "candidate_branch_id": "1_2__b1",
        "step1_same_pair_multichain": True,
        "same_pair_multi_road_support_mode": "traj_support",
        "_geometry_metric": LineString([(0.0, 10.0), (100.0, 10.0)]),
        "_candidate_has_geometry": True,
        "_candidate_feasible": True,
        "hard_reasons": [],
        "_candidate_score": 9.0,
    }

    ranked = [blocked, clean, fallback]
    display = pipeline._same_pair_branch_display_candidates(ranked)

    assert len(display) == 2
    by_branch = {
        str(item.get("same_pair_multi_road_branch_id")): item
        for item in display
    }
    assert by_branch["1_2__b0"] is fallback
    assert by_branch["1_2__b1"] is clean


def test_same_pair_branch_display_candidates_prefers_primary_selectable_over_fallback() -> None:
    primary = {
        "same_pair_multi_road_branch_id": "1_2__b0",
        "candidate_branch_id": "1_2__b0",
        "step1_same_pair_multichain": True,
        "same_pair_multi_road_support_mode": "traj_support",
        "_geometry_metric": LineString([(0.0, 0.0), (100.0, 0.0)]),
        "_candidate_has_geometry": True,
        "_candidate_feasible": True,
        "hard_reasons": [],
        "_candidate_score": 8.0,
    }
    fallback = {
        "same_pair_multi_road_branch_id": "1_2__b0",
        "candidate_branch_id": "1_2__b0",
        "step1_same_pair_multichain": True,
        "same_pair_multi_road_support_mode": "road_prior_fallback",
        "_geometry_metric": LineString([(0.0, 0.0), (100.0, 0.0)]),
        "_candidate_has_geometry": True,
        "_candidate_feasible": False,
        "hard_reasons": [],
        "_candidate_score": 9.0,
    }

    display = pipeline._same_pair_branch_display_candidates([fallback, primary])

    assert len(display) == 1
    assert display[0] is primary


def test_evaluate_candidate_road_same_pair_fallback_uses_entry_xsec(
    tmp_path: Path, monkeypatch
) -> None:
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
    )
    patch_inputs.drivezone_zone_metric = Polygon([(-20.0, -20.0), (120.0, -20.0), (120.0, 20.0), (-20.0, 20.0)])
    params = dict(pipeline.DEFAULT_PARAMS)
    src_xsec = LineString([(0.0, -5.0), (0.0, 5.0)])
    dst_xsec = LineString([(100.0, -5.0), (100.0, 5.0)])
    src_entry_xsec = LineString([(18.0, -5.0), (18.0, 5.0)])
    dst_entry_xsec = LineString([(88.0, -5.0), (88.0, 5.0)])
    road_prior_line = LineString([(18.0, 0.0), (88.0, 0.0)])
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids=set(),
        support_event_count=0,
        traj_segments=[],
        src_cross_points=[],
        dst_cross_points=[],
    )

    monkeypatch.setattr(
        pipeline,
        "_resolve_fallback_support_entry_xsecs",
        lambda **kwargs: (kwargs["shape_ref_metric"], src_entry_xsec, dst_entry_xsec),
    )
    monkeypatch.setattr(
        pipeline,
        "estimate_centerline",
        lambda **kwargs: geom_mod.CenterEstimate(
            centerline_metric=LineString([(40.0, 0.0), (60.0, 0.0)]),
            shape_ref_metric=LineString([(40.0, 0.0), (60.0, 0.0)]),
            lb_path_found=False,
            lb_path_edge_count=0,
            lb_path_length_m=None,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=1.0,
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
            src_cut_mode="none",
            dst_cut_mode="none",
            endpoint_tangent_deviation_deg_src=None,
            endpoint_tangent_deviation_deg_dst=None,
            endpoint_center_offset_m_src=None,
            endpoint_center_offset_m_dst=None,
            endpoint_proj_dist_to_core_m_src=None,
            endpoint_proj_dist_to_core_m_dst=None,
            soft_flags=set(),
            hard_flags=set(),
            diagnostics={},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_eval_traj_surface_gate",
        lambda **kwargs: ({}, set(), set(), []),
    )

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
        traj_surface_hint={"traj_surface_enforced": False, "surface_metric": None, "timing_ms": 0.0},
        shape_ref_hint_metric=road_prior_line,
        segment_corridor_metric=road_prior_line.buffer(20.0, cap_style=2),
        road_prior_shape_ref_metric=road_prior_line,
        step1_used_road_prior=False,
        step1_road_prior_mode=None,
        same_pair_multichain=True,
        candidate_branch_id="1_2__b0",
        support_mode="road_prior_fallback",
    )

    geom = road.get("_geometry_metric")
    assert isinstance(geom, LineString)
    assert abs(float(geom.coords[0][0]) - 18.0) <= 1e-6
    assert abs(float(geom.coords[-1][0]) - 88.0) <= 1e-6
    assert str(road.get("xsec_road_selected_by_src")) == "road_prior_fallback_entry_xsec"
    assert str(road.get("xsec_road_selected_by_dst")) == "road_prior_fallback_entry_xsec"
    assert abs(float(road.get("endpoint_dist_to_xsec_src_m") or 0.0)) <= 1e-6
    assert abs(float(road.get("endpoint_dist_to_xsec_dst_m") or 0.0)) <= 1e-6


def test_same_pair_multi_road_selection_keeps_close_parallel_branches() -> None:
    cand1 = {
        "src_nodeid": 1,
        "dst_nodeid": 2,
        "step1_same_pair_multichain": True,
        "same_pair_multi_road_branch_id": "1_2__b0",
        "same_pair_multi_road_signature": ["e0"],
        "same_pair_multi_road_src_station_m": 1.0,
        "same_pair_multi_road_dst_station_m": 1.2,
        "_geometry_metric": LineString([(0.0, 0.0), (100.0, 0.0)]),
    }
    cand2 = {
        "src_nodeid": 1,
        "dst_nodeid": 2,
        "step1_same_pair_multichain": True,
        "same_pair_multi_road_branch_id": "1_2__b1",
        "same_pair_multi_road_signature": ["e1"],
        "same_pair_multi_road_src_station_m": 4.0,
        "same_pair_multi_road_dst_station_m": 4.2,
        "_geometry_metric": LineString([(0.0, 0.2), (100.0, 0.2)]),
    }

    selected = pipeline._select_non_conflicting_multi_road_candidates(
        [cand1, cand2],
        min_sep_m=2.0,
        same_pair_station_gap_min_m=0.5,
    )

    assert len(selected) == 2


def test_same_pair_multi_road_selection_can_use_shape_ref_to_keep_parallel_branches() -> None:
    cand1 = {
        "src_nodeid": 1,
        "dst_nodeid": 2,
        "step1_same_pair_multichain": True,
        "same_pair_multi_road_branch_id": "1_2__b0",
        "same_pair_multi_road_signature": ["e0"],
        "same_pair_multi_road_src_station_m": 1.0,
        "same_pair_multi_road_dst_station_m": 1.2,
        "_geometry_metric": LineString([(0.0, 0.0), (100.0, 0.0)]),
        "_road_prior_shape_ref_metric": LineString([(0.0, 0.0), (100.0, 0.0)]),
    }
    cand2 = {
        "src_nodeid": 1,
        "dst_nodeid": 2,
        "step1_same_pair_multichain": True,
        "same_pair_multi_road_branch_id": "1_2__b1",
        "same_pair_multi_road_signature": ["e1"],
        "same_pair_multi_road_src_station_m": 3.0,
        "same_pair_multi_road_dst_station_m": 3.2,
        "_geometry_metric": LineString([(0.0, 0.0), (100.0, 0.0)]),
        "_road_prior_shape_ref_metric": LineString([(0.0, 0.6), (100.0, 0.6)]),
    }

    selected = pipeline._select_non_conflicting_multi_road_candidates(
        [cand1, cand2],
        min_sep_m=2.0,
        same_pair_station_gap_min_m=0.5,
    )

    assert len(selected) == 2


def test_same_pair_multichain_selection_keeps_road_prior_fallback_branch_without_traj_surface_feasible() -> None:
    cand1 = {
        "src_nodeid": 1,
        "dst_nodeid": 2,
        "step1_same_pair_multichain": True,
        "same_pair_multi_road_branch_id": "1_2__b0",
        "same_pair_multi_road_signature": ["e0"],
        "same_pair_multi_road_src_station_m": 1.0,
        "same_pair_multi_road_dst_station_m": 1.2,
        "same_pair_multi_road_support_mode": "traj_support",
        "_candidate_has_geometry": True,
        "_candidate_feasible": True,
        "_candidate_score": 10.0,
        "_geometry_metric": LineString([(0.0, 0.0), (100.0, 0.0)]),
        "hard_reasons": [],
    }
    cand2 = {
        "src_nodeid": 1,
        "dst_nodeid": 2,
        "step1_same_pair_multichain": True,
        "same_pair_multi_road_branch_id": "1_2__b1",
        "same_pair_multi_road_signature": ["e1"],
        "same_pair_multi_road_src_station_m": 3.0,
        "same_pair_multi_road_dst_station_m": 3.2,
        "same_pair_multi_road_support_mode": "road_prior_fallback",
        "_candidate_has_geometry": True,
        "_candidate_feasible": False,
        "_candidate_score": 9.0,
        "_geometry_metric": LineString([(0.0, 0.6), (100.0, 0.6)]),
        "hard_reasons": [SOFT_ROAD_OUTSIDE_TRAJ_SURFACE],
    }

    selected = pipeline._select_same_pair_multichain_candidates(
        sorted([cand1, cand2], key=pipeline._candidate_sort_key, reverse=True),
        min_sep_m=2.0,
        same_pair_station_gap_min_m=0.5,
    )

    assert len(selected) == 2
    assert {str(item.get("same_pair_multi_road_branch_id")) for item in selected} == {"1_2__b0", "1_2__b1"}


def test_same_pair_branch_supports_use_xsec_station_gap_to_split_close_parallel_events() -> None:
    support = PairSupport(
        src_nodeid=1,
        dst_nodeid=2,
        support_traj_ids={"t0", "t1"},
        support_event_count=2,
        traj_segments=[
            LineString([(0.0, 1.0), (10.0, 1.2)]),
            LineString([(0.0, 4.0), (10.0, 4.1)]),
        ],
        src_cross_points=[Point(0.0, 1.0), Point(0.0, 4.0)],
        dst_cross_points=[Point(10.0, 1.2), Point(10.0, 4.1)],
        repr_traj_ids=["t0", "t1"],
    )
    branch_defs = [
        {
            "branch_id": "1_2__b0",
            "shape_ref_metric": LineString([(0.0, 0.0), (10.0, 0.0)]),
            "src_station_m": 1.0,
            "dst_station_m": 1.2,
        },
        {
            "branch_id": "1_2__b1",
            "shape_ref_metric": LineString([(0.0, 0.0), (10.0, 0.0)]),
            "src_station_m": 4.0,
            "dst_station_m": 4.1,
        },
    ]
    src_xsec = LineString([(0.0, 0.0), (0.0, 6.0)])
    dst_xsec = LineString([(10.0, 0.0), (10.0, 6.0)])

    out = pipeline._build_same_pair_multichain_branch_supports(
        support,
        branch_defs=branch_defs,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
    )

    assert len(out) == 2
    assert out[0][0]["branch_id"] == "1_2__b0"
    assert out[1][0]["branch_id"] == "1_2__b1"
    assert int(out[0][1].support_event_count) == 1
    assert int(out[1][1].support_event_count) == 1
    assert abs(float(out[0][1].src_cross_points[0].y) - 1.0) <= 1e-6
    assert abs(float(out[1][1].src_cross_points[0].y) - 4.0) <= 1e-6


def test_build_same_pair_multichain_fallback_support_requires_branch_to_reach_both_xsecs() -> None:
    parent_support = PairSupport(src_nodeid=1, dst_nodeid=2, hard_anomalies={HARD_MULTI_ROAD})
    src_xsec = LineString([(0.0, 0.0), (0.0, 8.0)])
    dst_xsec = LineString([(100.0, 0.0), (100.0, 8.0)])
    branch_def = {
        "branch_id": "1_2__b1",
        "shape_ref_metric": LineString([(0.0, 10.0), (40.0, 10.0)]),
    }

    out = pipeline._build_same_pair_multichain_fallback_support(
        parent_support,
        branch_def=branch_def,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=Polygon([(-10.0, -10.0), (120.0, -10.0), (120.0, 20.0), (-10.0, 20.0)]),
        params=dict(pipeline.DEFAULT_PARAMS),
    )

    assert out is None


def test_build_same_pair_multichain_fallback_support_uses_wider_same_pair_reach_threshold() -> None:
    parent_support = PairSupport(src_nodeid=1, dst_nodeid=2, hard_anomalies={HARD_MULTI_ROAD})
    src_xsec = LineString([(0.0, 0.0), (0.0, 8.0)])
    dst_xsec = LineString([(100.0, 0.0), (100.0, 8.0)])
    branch_def = {
        "branch_id": "1_2__b1",
        "shape_ref_metric": LineString([(0.0, 20.5), (100.0, 20.5)]),
    }

    out = pipeline._build_same_pair_multichain_fallback_support(
        parent_support,
        branch_def=branch_def,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=Polygon([(-10.0, -10.0), (120.0, -10.0), (120.0, 30.0), (-10.0, 30.0)]),
        params=dict(pipeline.DEFAULT_PARAMS),
    )

    assert out is not None
    assert int(out.src_nodeid) == 1
    assert int(out.dst_nodeid) == 2
    assert out.hints[-1] == "same_pair_branch_road_prior_fallback"


def test_traj_surface_cache_key_ignores_xsec_bbox_variation(tmp_path: Path) -> None:
    patch_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 100.0)],
    )
    support = PairSupport(src_nodeid=1, dst_nodeid=2)
    params = dict(pipeline.DEFAULT_PARAMS)
    ref_axis = LineString([(0.0, 0.0), (100.0, 0.0)])

    _path_a, key_a = pipeline._traj_surface_cache_path(
        patch_inputs=patch_inputs,
        support=support,
        cluster_id=0,
        ref_axis_line=ref_axis,
        axis_source="shape_ref",
        src_xsec=LineString([(0.0, -5.0), (0.0, 5.0)]),
        dst_xsec=LineString([(100.0, -5.0), (100.0, 5.0)]),
        params=params,
    )
    _path_b, key_b = pipeline._traj_surface_cache_path(
        patch_inputs=patch_inputs,
        support=support,
        cluster_id=0,
        ref_axis_line=ref_axis,
        axis_source="shape_ref",
        src_xsec=LineString([(0.0, -20.0), (0.0, 20.0)]),
        dst_xsec=LineString([(100.0, -20.0), (100.0, 20.0)]),
        params=params,
    )

    assert key_a == key_b


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


def test_topology_unique_focus_pair_filters_support_builder(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    road_path = tmp_path / "RCSDRoad.geojson"
    road_payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 1, "enodeid": 2, "direction": 2}},
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 3, "enodeid": 4, "direction": 2}},
        ],
    }
    road_path.write_text(json.dumps(road_payload, ensure_ascii=False), encoding="utf-8")
    base_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 10.0), _mk_xsec(3, 20.0), _mk_xsec(4, 30.0)],
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
    captured_focus_src_nodeids: list[set[int] | None] = []

    def _fake_build_pair_supports(*args, **kwargs):  # type: ignore[no-untyped-def]
        allowed_pairs = kwargs.get("allowed_pairs")
        focus_src_nodeids = kwargs.get("focus_src_nodeids")
        captured_allowed_pairs.append(
            {(int(src), int(dst)) for src, dst in allowed_pairs} if allowed_pairs is not None else None
        )
        captured_focus_src_nodeids.append(
            {int(v) for v in focus_src_nodeids} if focus_src_nodeids is not None else None
        )
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
        lambda **kwargs: ({1: "unknown", 2: "unknown", 3: "unknown", 4: "unknown"}, {}, {}),
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

    params = dict(pipeline.DEFAULT_PARAMS)
    params["FOCUS_PAIR_FILTER"] = [{"src_nodeid": 1, "dst_nodeid": 2}]
    params["FOCUS_SRC_NODEIDS"] = [1]
    out = pipeline._run_patch_core(
        patch_inputs,
        params=params,
        run_id="unit_run",
        repo_root=tmp_path,
    )

    assert captured_allowed_pairs
    assert captured_allowed_pairs[0] == {(1, 2)}
    assert captured_focus_src_nodeids
    assert captured_focus_src_nodeids[0] == {1}
    assert out["debug_json_payloads"]["debug/focus_filter.json"]["pairs"] == [{"src_nodeid": 1, "dst_nodeid": 2}]
    assert len(out["debug_json_payloads"]["debug/step1_pair_straight_segments.geojson"]["features"]) == 1


def test_topology_unique_focus_pair_filters_cross_sections_and_keeps_pass2_focus(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    road_path = tmp_path / "RCSDRoad.geojson"
    road_payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 1, "enodeid": 9, "direction": 2}},
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 9, "enodeid": 2, "direction": 2}},
            {"type": "Feature", "geometry": None, "properties": {"snodeid": 3, "enodeid": 4, "direction": 2}},
        ],
    }
    road_path.write_text(json.dumps(road_payload, ensure_ascii=False), encoding="utf-8")
    base_inputs = _mk_patch_inputs(
        tmp_path=tmp_path,
        xsecs=[_mk_xsec(1, 0.0), _mk_xsec(2, 10.0), _mk_xsec(3, 20.0), _mk_xsec(4, 30.0), _mk_xsec(9, 5.0)],
        trajectories=[
            _mk_traj("near", [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]),
            _mk_traj("far", [(500.0, 0.0), (505.0, 0.0), (510.0, 0.0)]),
        ],
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
        "_build_topology_unique_anchor_decisions",
        lambda *args, **kwargs: (
            {1: {2}, 3: {4}},
            {(1, 2), (3, 4)},
            {
                1: {
                    "src_nodeid": 1,
                    "status": "accepted",
                    "reason": "accepted",
                    "dst_nodeids": [2],
                    "chosen_dst_nodeid": 2,
                    "anchor_count": 1,
                    "anchor_ids": ["a12"],
                    "dst_vote_map": {"2": 1},
                    "has_multi_dst_anchor": False,
                    "has_multi_chain_anchor": False,
                    "search_overflow": False,
                },
                3: {
                    "src_nodeid": 3,
                    "status": "accepted",
                    "reason": "accepted",
                    "dst_nodeids": [4],
                    "chosen_dst_nodeid": 4,
                    "anchor_count": 1,
                    "anchor_ids": ["a34"],
                    "dst_vote_map": {"4": 1},
                    "has_multi_dst_anchor": False,
                    "has_multi_chain_anchor": False,
                    "search_overflow": False,
                },
            },
            {
                "a12": {
                    "anchor_id": "a12",
                    "anchor_role": "out",
                    "search_direction": "forward",
                    "src_nodeid": 1,
                    "status": "accepted",
                    "reason": "accepted",
                    "dst_nodeids": [2],
                    "chosen_dst_nodeid": 2,
                    "pair_src_nodeid": 1,
                    "pair_dst_nodeid": 2,
                    "chain_count": 1,
                    "dst_paths": {"2": [{"node_path": [1, 9, 2], "edge_ids": ["e1", "e2"], "chain_len": 2}]},
                },
                "a34": {
                    "anchor_id": "a34",
                    "anchor_role": "out",
                    "search_direction": "forward",
                    "src_nodeid": 3,
                    "status": "accepted",
                    "reason": "accepted",
                    "dst_nodeids": [4],
                    "chosen_dst_nodeid": 4,
                    "pair_src_nodeid": 3,
                    "pair_dst_nodeid": 4,
                    "chain_count": 1,
                    "dst_paths": {"4": [{"node_path": [3, 4], "edge_ids": ["e3"], "chain_len": 1}]},
                },
            },
            {
                "src_count": 2,
                "accepted_src_count": 2,
                "unresolved_src_count": 0,
                "multi_dst_src_count": 0,
                "multi_chain_src_count": 0,
                "search_overflow_src_count": 0,
                "accepted_pair_count": 2,
            },
            [],
            [],
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_build_road_prior_pair_shape_ref_map",
        lambda *args, **kwargs: ({(1, 2): LineString([(0.0, 0.0), (10.0, 0.0)])}, {}),
    )
    captured_extract_inputs: list[dict[str, object]] = []

    def _fake_extract_crossing_events(*args, **kwargs):  # type: ignore[no-untyped-def]
        trajectories = list(args[0]) if len(args) >= 1 else list(kwargs.get("trajectories") or [])
        cross_sections = list(args[1]) if len(args) >= 2 else list(kwargs.get("cross_sections") or [])
        captured_extract_inputs.append(
            {
                "traj_ids": [str(traj.traj_id) for traj in trajectories],
                "cross_nodeids": sorted(int(x.nodeid) for x in cross_sections),
            }
        )
        return CrossingExtractResult(
            events_by_traj={},
            raw_hit_count=0,
            dedup_drop_count=0,
            n_cross_empty_skipped=0,
            n_cross_geom_unexpected=0,
            n_cross_distance_gate_reject=0,
        )

    monkeypatch.setattr(pipeline, "extract_crossing_events", _fake_extract_crossing_events)
    captured_focus_src_nodeids: list[set[int] | None] = []
    captured_support_traj_ids: list[list[str]] = []

    def _fake_build_pair_supports(*args, **kwargs):  # type: ignore[no-untyped-def]
        trajectories = list(args[0]) if len(args) >= 1 else list(kwargs.get("trajectories") or [])
        focus_src_nodeids = kwargs.get("focus_src_nodeids")
        captured_support_traj_ids.append([str(traj.traj_id) for traj in trajectories])
        captured_focus_src_nodeids.append(
            {int(v) for v in focus_src_nodeids} if focus_src_nodeids is not None else None
        )
        return PairSupportBuildResult(
            supports={},
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
            node_dst_votes={},
        )

    monkeypatch.setattr(pipeline, "build_pair_supports", _fake_build_pair_supports)
    monkeypatch.setattr(
        pipeline,
        "infer_node_types",
        lambda **kwargs: ({1: "unknown", 2: "unknown", 3: "unknown", 4: "unknown", 9: "unknown"}, {}, {}),
    )

    params = dict(pipeline.DEFAULT_PARAMS)
    params["FOCUS_PAIR_FILTER"] = [{"src_nodeid": 1, "dst_nodeid": 2}]
    params["FOCUS_SRC_NODEIDS"] = [1]
    progress_path = tmp_path / "progress.ndjson"
    out = pipeline._run_patch_core(
        patch_inputs,
        params=params,
        run_id="unit_run",
        repo_root=tmp_path,
        progress=pipeline._ProgressLogger(progress_path),
    )

    assert captured_extract_inputs
    assert captured_extract_inputs[0] == {"traj_ids": ["near"], "cross_nodeids": [1, 2, 9]}
    assert len(captured_extract_inputs) >= 2
    assert captured_extract_inputs[1] == {"traj_ids": ["near"], "cross_nodeids": [1, 2, 9]}
    assert captured_support_traj_ids
    assert captured_support_traj_ids[0] == ["near"]
    assert captured_support_traj_ids[1] == ["near"]
    assert captured_focus_src_nodeids
    assert captured_focus_src_nodeids[0] == {1}
    assert captured_focus_src_nodeids[1] == {1}
    assert int(out["metrics_payload"].get("focus_cross_section_count", 0)) == 3
    assert bool(out["metrics_payload"].get("focus_prefilter_enabled", False)) is True
    assert int(out["metrics_payload"].get("focus_prefilter_trajectory_total", 0)) == 2
    assert int(out["metrics_payload"].get("focus_prefilter_trajectory_count", 0)) == 1
    assert int(out["metrics_payload"].get("focus_prefilter_trajectory_filtered_count", 0)) == 1
    progress_rows = [
        json.loads(line)
        for line in progress_path.read_text(encoding="utf-8").splitlines()
        if str(line).strip()
    ]
    pass1_extract_rows = [
        row
        for row in progress_rows
        if str(row.get("stage")) == "neighbor_pass_extract_start" and str(row.get("pass_label")) == "pass1"
    ]
    pass2_extract_rows = [
        row
        for row in progress_rows
        if str(row.get("stage")) == "neighbor_pass_extract_start" and str(row.get("pass_label")) == "pass2"
    ]
    pass2_rows = [row for row in progress_rows if str(row.get("stage")) == "neighbor_pass2_start"]
    support_done_rows = [
        row for row in progress_rows if str(row.get("stage")) == "neighbor_pass_support_done"
    ]
    assert pass1_extract_rows
    assert int(pass1_extract_rows[-1].get("traj_count")) == 1
    assert int(pass1_extract_rows[-1].get("xsec_count")) == 3
    assert pass2_extract_rows
    assert int(pass2_extract_rows[-1].get("traj_count")) == 1
    assert pass2_rows
    assert int(pass2_rows[-1].get("focus_src_count")) == 1
    assert support_done_rows


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
    captured_support_kwargs: list[dict[str, object]] = []

    def _fake_build_pair_supports(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured_support_kwargs.append(dict(kwargs))
        return PairSupportBuildResult(
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
        )

    monkeypatch.setattr(pipeline, "build_pair_supports", _fake_build_pair_supports)
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

    assert captured_support_kwargs
    first_kwargs = captured_support_kwargs[0]
    src_alias_map = dict(first_kwargs.get("src_nodeid_alias_by_nodeid") or {})
    dst_alias_map = dict(first_kwargs.get("dst_nodeid_alias_by_nodeid") or {})
    assert int(src_alias_map.get(9102, -1)) == 9101
    assert int(dst_alias_map.get(9201, -1)) == 9202
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
