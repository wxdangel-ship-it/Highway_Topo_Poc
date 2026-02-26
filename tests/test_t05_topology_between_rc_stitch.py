from __future__ import annotations

from pathlib import Path

import numpy as np
from shapely.geometry import LineString

from highway_topo_poc.modules.t05_topology_between_rc.geometry import (
    SOFT_UNRESOLVED_NEIGHBOR,
    build_pair_supports,
    extract_crossing_events,
)
from highway_topo_poc.modules.t05_topology_between_rc.io import CrossSection, TrajectoryData


def _traj(traj_id: str, coords: list[tuple[float, float]]) -> TrajectoryData:
    xyz = np.asarray([[x, y, 0.0] for x, y in coords], dtype=np.float64)
    seq = np.arange(xyz.shape[0], dtype=np.int64)
    return TrajectoryData(
        traj_id=traj_id,
        seq=seq,
        xyz_metric=xyz,
        source_path=Path(f"/tmp/{traj_id}.geojson"),
        source_crs="EPSG:3857",
    )


def _xsec(nodeid: int, x: float) -> CrossSection:
    return CrossSection(
        nodeid=int(nodeid),
        geometry_metric=LineString([(x, -2.0), (x, 2.0)]),
        properties={"nodeid": int(nodeid)},
    )


def test_stitch_graph_can_bridge_broken_trajectories() -> None:
    trajectories = [
        _traj("t1", [(-2.0, 0.0), (5.0, 0.0), (10.0, 0.0)]),
        _traj("t2", [(10.5, 0.0), (15.0, 0.0), (22.0, 0.0)]),
    ]
    xsecs = [_xsec(100, 0.0), _xsec(200, 20.0)]

    cross = extract_crossing_events(
        trajectories,
        xsecs,
        hit_buffer_m=0.5,
        dedup_gap_m=2.0,
    )
    res = build_pair_supports(
        trajectories,
        cross.events_by_traj,
        node_type_map={100: "unknown", 200: "unknown"},
        trj_sample_step_m=2.0,
        stitch_tail_m=30.0,
        stitch_max_dist_levels_m=[12.0, 25.0, 50.0],
        stitch_max_dist_m=12.0,
        stitch_max_angle_deg=35.0,
        stitch_forward_dot_min=0.0,
        stitch_min_advance_m=5.0,
        stitch_penalty=2.0,
        stitch_topk=3,
        neighbor_max_dist_m=2000.0,
        multi_road_sep_m=8.0,
        multi_road_topn=10,
    )

    assert (100, 200) in res.supports
    support = res.supports[(100, 200)]
    assert support.support_event_count >= 1
    assert support.stitch_hops
    assert max(support.stitch_hops) >= 1
    assert res.stitch_accept_count >= 1
    assert res.stitch_query_count >= 1


def test_stitch_can_connect_to_midpoint_when_start_far() -> None:
    trajectories = [
        _traj("t1", [(-5.0, 0.0), (0.0, 0.0), (10.0, 0.0)]),
        _traj("t2", [(-40.0, 0.0), (20.0, 0.0), (80.0, 0.0)]),
    ]
    xsecs = [_xsec(100, 0.0), _xsec(200, 70.0)]

    cross = extract_crossing_events(
        trajectories,
        xsecs,
        hit_buffer_m=0.5,
        dedup_gap_m=2.0,
    )
    res = build_pair_supports(
        trajectories,
        cross.events_by_traj,
        node_type_map={100: "unknown", 200: "unknown"},
        trj_sample_step_m=2.0,
        stitch_tail_m=30.0,
        stitch_max_dist_levels_m=[12.0, 25.0, 50.0],
        stitch_max_dist_m=12.0,
        stitch_max_angle_deg=35.0,
        stitch_forward_dot_min=0.0,
        stitch_min_advance_m=5.0,
        stitch_penalty=2.0,
        stitch_topk=3,
        neighbor_max_dist_m=2000.0,
        multi_road_sep_m=8.0,
        multi_road_topn=10,
    )

    assert (100, 200) in res.supports
    assert res.stitch_accept_count > 0
    assert any(int(v) > 0 for v in res.stitch_levels_used_hist.values())


def test_unresolved_neighbor_is_reported_when_stitch_fails() -> None:
    trajectories = [
        _traj("t1", [(-2.0, 0.0), (5.0, 0.0), (10.0, 0.0)]),
        _traj("t2", [(100.0, 0.0), (110.0, 0.0), (120.0, 0.0)]),
    ]
    xsecs = [_xsec(100, 0.0), _xsec(200, 20.0)]

    cross = extract_crossing_events(
        trajectories,
        xsecs,
        hit_buffer_m=0.5,
        dedup_gap_m=2.0,
    )
    res = build_pair_supports(
        trajectories,
        cross.events_by_traj,
        node_type_map={100: "unknown", 200: "unknown"},
        trj_sample_step_m=2.0,
        stitch_tail_m=30.0,
        stitch_max_dist_levels_m=[12.0],
        stitch_max_dist_m=12.0,
        stitch_max_angle_deg=35.0,
        stitch_forward_dot_min=0.0,
        stitch_min_advance_m=5.0,
        stitch_penalty=2.0,
        stitch_topk=3,
        neighbor_max_dist_m=2000.0,
        multi_road_sep_m=8.0,
        multi_road_topn=10,
    )

    assert (100, 200) not in res.supports
    assert res.unresolved_events
    assert any(str(item.get("reason")) == SOFT_UNRESOLVED_NEIGHBOR for item in res.unresolved_events)
    assert res.stitch_accept_count == 0
