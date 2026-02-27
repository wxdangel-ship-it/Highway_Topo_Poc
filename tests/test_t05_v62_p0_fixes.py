from __future__ import annotations

from pathlib import Path

import numpy as np
from shapely.geometry import LineString, MultiLineString

from highway_topo_poc.modules.t05_topology_between_rc.geometry import _project_endpoint_to_valid_xsec
from highway_topo_poc.modules.t05_topology_between_rc.io import CrossSection, TrajectoryData
from highway_topo_poc.modules.t05_topology_between_rc.pipeline import (
    _fallback_geometry_from_shape_ref,
    _truncate_cross_sections_for_crossing,
)


def _traj(traj_id: str, coords: list[tuple[float, float]]) -> TrajectoryData:
    xy = np.asarray(coords, dtype=np.float64)
    xyz = np.column_stack((xy, np.zeros((xy.shape[0],), dtype=np.float64)))
    return TrajectoryData(
        traj_id=traj_id,
        seq=np.arange(xy.shape[0], dtype=np.int64),
        xyz_metric=xyz,
        source_path=Path(f"/tmp/{traj_id}.geojson"),
        source_crs="EPSG:3857",
    )


def test_crossing_xsec_truncation_stays_near_evidence() -> None:
    xsec = CrossSection(
        nodeid=1,
        geometry_metric=LineString([(0.0, -120.0), (0.0, 120.0)]),
        properties={"nodeid": 1},
    )
    trajectories = [
        _traj("t1", [(-20.0, -6.0), (0.0, -2.0), (20.0, -6.0)]),
        _traj("t2", [(-20.0, 6.0), (0.0, 2.0), (20.0, 6.0)]),
    ]
    out_map, _anchors, _trunc, stats = _truncate_cross_sections_for_crossing(
        xsec_map={1: xsec},
        lane_boundaries_metric=[],
        trajectories=trajectories,
        gore_zone_metric=None,
        params={
            "XSEC_TRUNC_LMAX_M": 80.0,
            "XSEC_TRUNC_STEP_M": 1.0,
            "XSEC_TRUNC_NONPASS_K": 6,
            "XSEC_TRUNC_EVIDENCE_RADIUS_M": 1.0,
        },
    )

    got = out_map[1].geometry_metric
    assert got.length < xsec.geometry_metric.length
    assert got.length > 4.0
    assert int(stats.get("xsec_truncated_count", 0)) >= 1


def test_endpoint_multiline_support_chooses_lb_nearest_segment() -> None:
    xsec = LineString([(0.0, -20.0), (0.0, 20.0)])
    support = MultiLineString([[(0.0, -12.0), (0.0, -8.0)], [(0.0, 8.0), (0.0, 12.0)]])
    lb_ref = LineString([(-30.0, 10.0), (30.0, 10.0)])

    out_xy, mode, support_len = _project_endpoint_to_valid_xsec(
        endpoint_xy=(0.0, 0.0),
        xsec=xsec,
        gore_zone_metric=None,
        channel_ref_xy=None,
        xsec_support_geom=support,
        lb_ref_line=lb_ref,
        prefer_lb_guard=False,
        local_max_dist_m=20.0,
    )

    assert support_len > 0.0
    assert "enforced_support" in str(mode)
    assert float(out_xy[1]) > 6.0


def test_shape_ref_fallback_geometry_substring_is_valid() -> None:
    shape_ref = LineString([(-120.0, 0.0), (0.0, 0.0), (100.0, 0.0), (260.0, 0.0)])
    src_xsec = LineString([(0.0, -10.0), (0.0, 10.0)])
    dst_xsec = LineString([(100.0, -10.0), (100.0, 10.0)])

    out = _fallback_geometry_from_shape_ref(
        shape_ref_line=shape_ref,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
    )

    assert out is not None
    assert 90.0 <= float(out.length) <= 120.0
