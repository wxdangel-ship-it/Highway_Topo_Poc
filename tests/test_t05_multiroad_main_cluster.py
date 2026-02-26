from __future__ import annotations

from pathlib import Path

import numpy as np
from shapely.geometry import LineString

from highway_topo_poc.modules.t05_topology_between_rc.geometry import (
    HARD_MULTI_ROAD,
    build_pair_supports,
    extract_crossing_events,
)
from highway_topo_poc.modules.t05_topology_between_rc.io import CrossSection, TrajectoryData


def _traj(traj_id: str, *, y: float) -> TrajectoryData:
    xyz = np.asarray([[-10.0, y, 0.0], [40.0, y, 0.0], [110.0, y, 0.0]], dtype=np.float64)
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
        geometry_metric=LineString([(x, -30.0), (x, 30.0)]),
        properties={"nodeid": int(nodeid)},
    )


def test_multi_road_keeps_major_cluster_for_geometry() -> None:
    trajectories = [
        _traj("c1_0", y=0.0),
        _traj("c1_1", y=0.8),
        _traj("c1_2", y=-0.6),
        _traj("c1_3", y=1.2),
        _traj("c2_0", y=14.0),
        _traj("c2_1", y=15.0),
    ]
    xsecs = [_xsec(100, 0.0), _xsec(200, 100.0)]
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
    assert HARD_MULTI_ROAD in support.hard_anomalies
    assert support.cluster_count >= 2
    assert support.main_cluster_ratio > 0.5
    # v4: 保留全部候选簇供后续“按簇评分选 k*”，不在 build_pair_supports 阶段直接裁剪。
    assert support.support_event_count == len(trajectories)
    assert len(support.evidence_cluster_ids) == support.support_event_count
    main_cnt = sum(1 for c in support.evidence_cluster_ids if int(c) == int(support.main_cluster_id))
    assert main_cnt >= 4
    assert main_cnt < support.support_event_count
