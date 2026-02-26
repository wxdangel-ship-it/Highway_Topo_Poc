from __future__ import annotations

from pathlib import Path

import numpy as np
from shapely.geometry import LineString

from highway_topo_poc.modules.t05_topology_between_rc.geometry import (
    extract_crossing_events,
    point_xy_safe,
)
from highway_topo_poc.modules.t05_topology_between_rc.io import CrossSection, TrajectoryData


def _traj(coords: list[tuple[float, float]], traj_id: str = "t1") -> TrajectoryData:
    xy = np.asarray(coords, dtype=np.float64)
    xyz = np.column_stack((xy, np.zeros((xy.shape[0],), dtype=np.float64)))
    return TrajectoryData(
        traj_id=traj_id,
        seq=np.arange(xy.shape[0], dtype=np.int64),
        xyz_metric=xyz,
        source_path=Path(f"/tmp/{traj_id}.geojson"),
        source_crs="EPSG:3857",
    )


def _xsec(nodeid: int, coords: list[tuple[float, float]]) -> CrossSection:
    return CrossSection(
        nodeid=int(nodeid),
        geometry_metric=LineString(coords),
        properties={"nodeid": int(nodeid)},
    )


def test_cross_distance_gate_reject_no_crash() -> None:
    traj = _traj([(0.0, 0.0), (10.0, 0.0)])
    xsec = _xsec(100, [(5.0, 0.6), (5.0, 2.0)])

    result = extract_crossing_events(
        [traj],
        [xsec],
        hit_buffer_m=0.5,
        dedup_gap_m=2.0,
    )

    assert result.events_by_traj == {}
    assert result.raw_hit_count == 0
    assert result.n_cross_distance_gate_reject >= 1


def test_cross_overlap_uses_nearest_points_and_non_empty_point() -> None:
    traj = _traj([(0.0, 0.0), (10.0, 0.0)])
    xsec = _xsec(200, [(4.0, 0.0), (6.0, 0.0)])

    result = extract_crossing_events(
        [traj],
        [xsec],
        hit_buffer_m=0.5,
        dedup_gap_m=2.0,
    )

    assert "t1" in result.events_by_traj
    events = result.events_by_traj["t1"]
    assert events
    xy = point_xy_safe(events[0].cross_point, context="test_overlap")
    assert xy is not None
    assert not events[0].cross_point.is_empty
