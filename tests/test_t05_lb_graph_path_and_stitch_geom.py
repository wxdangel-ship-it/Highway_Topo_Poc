from __future__ import annotations

from shapely.geometry import LineString, Point, Polygon

from highway_topo_poc.modules.t05_topology_between_rc.geometry import (
    _GraphEdge,
    _GraphNode,
    _build_lb_graph_path,
    _build_path_linestring,
    _shape_ref_substring_by_xsecs,
)


def test_lb_graph_path_can_stitch_multiple_laneboundary_segments() -> None:
    lane_boundaries = [
        LineString([(0.0, 0.0), (50.0, 0.0)]),
        LineString([(50.1, 0.0), (100.0, 0.0)]),
    ]
    src_xsec = LineString([(0.0, -10.0), (0.0, 10.0)])
    dst_xsec = LineString([(100.0, -10.0), (100.0, 10.0)])

    out = _build_lb_graph_path(
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        lane_boundaries_metric=lane_boundaries,
        snap_m=1.0,
        topk=5,
    )
    assert out is not None
    line, edge_count = out
    assert line.length > 95.0
    assert edge_count >= 2


def test_path_linestring_excludes_stitch_bridge_geometry() -> None:
    nodes = {
        "t1:a": _GraphNode(
            key="t1:a",
            traj_id="t1",
            kind="sample",
            station_m=0.0,
            point=Point(0.0, 0.0),
            heading_xy=(1.0, 0.0),
            cross_nodeid=None,
            seq_idx=None,
        ),
        "t1:b": _GraphNode(
            key="t1:b",
            traj_id="t1",
            kind="sample",
            station_m=10.0,
            point=Point(10.0, 0.0),
            heading_xy=(1.0, 0.0),
            cross_nodeid=None,
            seq_idx=None,
        ),
        "t2:c": _GraphNode(
            key="t2:c",
            traj_id="t2",
            kind="sample",
            station_m=0.0,
            point=Point(20.0, 0.0),
            heading_xy=(1.0, 0.0),
            cross_nodeid=None,
            seq_idx=None,
        ),
        "t2:d": _GraphNode(
            key="t2:d",
            traj_id="t2",
            kind="sample",
            station_m=10.0,
            point=Point(30.0, 0.0),
            heading_xy=(1.0, 0.0),
            cross_nodeid=None,
            seq_idx=None,
        ),
    }
    prev_edge = {
        "t1:b": _GraphEdge(
            to_key="t1:b",
            weight=10.0,
            kind="traj",
            traj_id="t1",
            station_from=0.0,
            station_to=10.0,
        ),
        "t2:c": _GraphEdge(
            to_key="t2:c",
            weight=10.0,
            kind="stitch",
            traj_id=None,
            station_from=None,
            station_to=None,
        ),
        "t2:d": _GraphEdge(
            to_key="t2:d",
            weight=10.0,
            kind="traj",
            traj_id="t2",
            station_from=0.0,
            station_to=10.0,
        ),
    }
    path_keys = ["t1:a", "t1:b", "t2:c", "t2:d"]
    traj_line_map = {
        "t1": LineString([(0.0, 0.0), (10.0, 0.0)]),
        "t2": LineString([(20.0, 0.0), (30.0, 0.0)]),
    }

    line = _build_path_linestring(
        path_keys=path_keys,
        nodes=nodes,
        prev_edge=prev_edge,
        traj_line_map=traj_line_map,
    )
    assert line is not None
    # 不应把 10->20 的 stitch 直连段拼进几何。
    assert line.length <= 10.1


def test_lb_graph_path_enforced_surface_blocks_wrong_channel() -> None:
    lane_boundaries = [
        LineString([(0.0, 0.0), (100.0, 0.0)]),
        LineString([(0.0, 20.0), (100.0, 20.0)]),
    ]
    src_xsec = LineString([(0.0, -30.0), (0.0, 30.0)])
    dst_xsec = LineString([(100.0, -30.0), (100.0, 30.0)])
    traj_surface = Polygon([(-5.0, -5.0), (105.0, -5.0), (105.0, 5.0), (-5.0, 5.0)])

    out = _build_lb_graph_path(
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        lane_boundaries_metric=lane_boundaries,
        snap_m=1.0,
        topk=5,
        traj_surface_metric=traj_surface,
        outside_lambda=5.0,
        enforce_surface=True,
        outside_edge_ratio_max=0.2,
        surface_node_buffer_m=2.0,
    )
    assert out is not None
    line, _ = out
    ys = [float(y) for _, y in line.coords]
    assert max(abs(v) for v in ys) < 2.0


def test_lb_graph_path_forbids_divstrip_intersections() -> None:
    lane_boundaries = [
        LineString([(0.0, 0.0), (100.0, 0.0)]),
        LineString([(0.0, 20.0), (100.0, 20.0)]),
    ]
    src_xsec = LineString([(0.0, -30.0), (0.0, 30.0)])
    dst_xsec = LineString([(100.0, -30.0), (100.0, 30.0)])
    divstrip = Polygon([(-5.0, -5.0), (105.0, -5.0), (105.0, 5.0), (-5.0, 5.0)])

    out = _build_lb_graph_path(
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        lane_boundaries_metric=lane_boundaries,
        snap_m=1.0,
        topk=5,
        divstrip_barrier_metric=divstrip,
    )
    assert out is not None
    line, _ = out
    ys = [float(y) for _, y in line.coords]
    assert min(ys) > 10.0


def test_shape_ref_substring_clips_to_src_dst_cross_sections() -> None:
    raw = LineString([(-200.0, 0.0), (0.0, 0.0), (100.0, 0.0), (350.0, 0.0)])
    src_xsec = LineString([(0.0, -10.0), (0.0, 10.0)])
    dst_xsec = LineString([(100.0, -10.0), (100.0, 10.0)])

    clipped = _shape_ref_substring_by_xsecs(raw, src_xsec=src_xsec, dst_xsec=dst_xsec)
    assert clipped is not None
    assert 99.0 <= float(clipped.length) <= 101.0
    assert Point(clipped.coords[0]).distance(src_xsec) < 1.0
    assert Point(clipped.coords[-1]).distance(dst_xsec) < 1.0
