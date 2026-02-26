from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon

from highway_topo_poc.modules.t05_topology_between_rc.geometry import _estimate_offsets_from_surface


def test_gore_zone_points_are_excluded_from_effective_surface() -> None:
    sample_points = np.asarray([[0.0, 0.0]], dtype=np.float64)
    tangents = np.asarray([[1.0, 0.0]], dtype=np.float64)
    normals = np.asarray([[0.0, 1.0]], dtype=np.float64)

    # 基础道路点：横向对称，中心应接近 0。
    base = np.asarray(
        [[-0.5, -2.0, 0.0], [0.0, -2.2, 0.0], [0.3, -1.8, 0.0], [-0.4, 2.0, 0.0], [0.1, 2.1, 0.0], [0.6, 1.9, 0.0]],
        dtype=np.float64,
    )
    # 导流带污染点：全部在正侧，若不剔除会把中心拉正。
    gore_points = np.asarray(
        [[-0.2, 7.0, 0.0], [0.2, 7.5, 0.0], [0.4, 8.0, 0.0], [0.0, 8.5, 0.0], [0.1, 9.0, 0.0], [-0.3, 9.5, 0.0]],
        dtype=np.float64,
    )
    xyz = np.vstack([base, gore_points])
    gore_poly = Polygon([(-1.0, 6.0), (1.0, 6.0), (1.0, 10.0), (-1.0, 10.0)])

    off_no_gore, _, _, _ = _estimate_offsets_from_surface(
        sample_points=sample_points,
        tangents=tangents,
        normals=normals,
        points_xyz=xyz,
        gore_zone_metric=None,
        along_half_window_m=2.0,
        across_half_window_m=12.0,
        corridor_half_width_m=12.0,
        min_points=4,
        width_pct_low=5.0,
        width_pct_high=95.0,
    )
    off_with_gore, _, gore_overlap, _ = _estimate_offsets_from_surface(
        sample_points=sample_points,
        tangents=tangents,
        normals=normals,
        points_xyz=xyz,
        gore_zone_metric=gore_poly,
        along_half_window_m=2.0,
        across_half_window_m=12.0,
        corridor_half_width_m=12.0,
        min_points=4,
        width_pct_low=5.0,
        width_pct_high=95.0,
    )

    assert np.isfinite(off_no_gore[0])
    assert np.isfinite(off_with_gore[0])
    assert float(off_no_gore[0]) > float(off_with_gore[0])
    assert abs(float(off_with_gore[0])) < 0.5
    assert np.isfinite(gore_overlap[0])
    assert float(gore_overlap[0]) > 0.0
