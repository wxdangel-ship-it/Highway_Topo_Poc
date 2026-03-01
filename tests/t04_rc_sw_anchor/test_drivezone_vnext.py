from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon

from highway_topo_poc.modules.t04_rc_sw_anchor.config import DEFAULT_PARAMS
from highway_topo_poc.modules.t04_rc_sw_anchor.drivezone_ops import (
    build_fan_band,
    clip_crossline_to_drivezone,
    detect_non_drivezone_in_fan,
)
from highway_topo_poc.modules.t04_rc_sw_anchor.io_geojson import RoadRecord, load_drivezone_union
from highway_topo_poc.modules.t04_rc_sw_anchor.metrics_breakpoints import BP_DRIVEZONE_SPLIT_NOT_FOUND, build_metrics
from highway_topo_poc.modules.t04_rc_sw_anchor.road_graph import RoadGraph
from highway_topo_poc.modules.t04_rc_sw_anchor.runner import run_from_runtime

from ._synth_patch_factory import create_synth_patch


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_drivezone_union_and_crs_reproject(tmp_path: Path) -> None:
    path = tmp_path / "DriveZone.geojson"
    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[120.0, 30.0], [120.001, 30.0], [120.001, 30.001], [120.0, 30.001], [120.0, 30.0]]],
                },
            },
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[120.001, 30.0], [120.002, 30.0], [120.002, 30.001], [120.001, 30.001], [120.001, 30.0]]],
                },
            },
        ],
    }
    _write_json(path, payload)

    dz_union, meta, errors = load_drivezone_union(
        path=path,
        src_crs_override="auto",
        dst_crs="EPSG:3857",
        aoi=None,
    )
    assert dz_union is not None
    assert not dz_union.is_empty
    assert meta.src_crs == "EPSG:4326"
    assert meta.dst_crs == "EPSG:3857"
    assert meta.bbox_dst is not None
    assert abs(float(meta.bbox_dst[0])) > 1.0e6
    assert not errors


def test_trigger_divstrip_plus_drivezone_fan_detects_split(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    out_root = tmp_path / "outputs" / "_work" / "t04_rc_sw_anchor"
    params = dict(DEFAULT_PARAMS)
    params.update(
        {
            "drivezone_non_drivezone_area_min_m2": 1.0,
            "drivezone_non_drivezone_frac_min": 0.05,
            "allow_divstrip_only_when_drivezone_miss": False,
        }
    )
    runtime = {
        "mode": "global_focus",
        "patch_dir": str(data["patch_dir"]),
        "out_root": str(out_root),
        "run_id": "dz_split_detect",
        "global_node_path": str(data["global_node_path"]),
        "global_road_path": str(data["global_road_path"]),
        "divstrip_path": str(data["divstrip_path"]),
        "drivezone_path": str(data["drivezone_path"]),
        "pointcloud_path": str(data["pointcloud_path"]),
        "traj_glob": str(data["traj_glob"]),
        "focus_node_ids": list(data["focus_node_ids"]),
        "src_crs": "auto",
        "dst_crs": "EPSG:3857",
        "node_src_crs": "auto",
        "road_src_crs": "auto",
        "divstrip_src_crs": "auto",
        "drivezone_src_crs": "auto",
        "traj_src_crs": "auto",
        "pointcloud_crs": str(data["pointcloud_crs"]),
        "params": params,
    }
    result = run_from_runtime(runtime)
    anchors = json.loads((result.out_dir / "anchors.json").read_text(encoding="utf-8"))
    items = anchors.get("items", [])
    assert items
    dz_items = [x for x in items if str(x.get("trigger")) == "divstrip+dz"]
    assert dz_items
    assert any(float(x.get("non_drivezone_frac", 0.0)) >= 0.05 for x in dz_items)


def test_fan_band_avoids_side_drivezone_false_positive() -> None:
    fan_band = build_fan_band(
        origin_xy=(0.0, 0.0),
        scan_unit_vec=(1.0, 0.0),
        radius_m=20.0,
        half_angle_deg=30.0,
        band_width_m=4.0,
    )
    drivezone_union = Polygon([(-2.0, -3.0), (22.0, -3.0), (22.0, 3.0), (-2.0, 3.0), (-2.0, -3.0)])
    hit, diag = detect_non_drivezone_in_fan(
        drivezone_union=drivezone_union,
        fan_band=fan_band,
        area_min_m2=3.0,
        frac_min=0.15,
    )
    assert hit is False
    assert float(diag.get("non_drivezone_frac", 0.0)) < 0.15


def test_crossline_clipped_by_drivezone_contains_anchor() -> None:
    crossline = LineString([(-5.0, 0.0), (5.0, 0.0)])
    drivezone_union = Polygon([(-2.0, -1.0), (2.0, -1.0), (2.0, 1.0), (-2.0, 1.0), (-2.0, -1.0)])
    anchor = Point(0.0, 0.0)
    clipped, diag = clip_crossline_to_drivezone(crossline=crossline, drivezone_union=drivezone_union, anchor_pt=anchor)
    assert clipped.length < crossline.length
    assert clipped.distance(anchor) <= 1e-9
    assert bool(diag.get("clip_empty", False)) is False


def test_next_intersection_stop_requires_connectivity_and_degree() -> None:
    roads = [
        RoadRecord(snodeid=1, enodeid=2, line=LineString([(0.0, 0.0), (0.0, 10.0)]), length_m=10.0),
        RoadRecord(snodeid=2, enodeid=3, line=LineString([(0.0, 10.0), (0.0, 20.0)]), length_m=10.0),
        RoadRecord(snodeid=3, enodeid=4, line=LineString([(0.0, 20.0), (-10.0, 20.0)]), length_m=10.0),
        RoadRecord(snodeid=3, enodeid=5, line=LineString([(0.0, 20.0), (10.0, 20.0)]), length_m=10.0),
        # disconnected but geometrically near
        RoadRecord(snodeid=10, enodeid=11, line=LineString([(1.0, 1.0), (1.0, 2.0)]), length_m=1.0),
        RoadRecord(snodeid=10, enodeid=12, line=LineString([(1.0, 1.0), (2.0, 1.0)]), length_m=1.0),
        RoadRecord(snodeid=10, enodeid=13, line=LineString([(1.0, 1.0), (0.0, 1.0)]), length_m=1.0),
    ]
    node_points = {
        1: Point(0.0, 0.0),
        2: Point(0.0, 10.0),
        3: Point(0.0, 20.0),
        4: Point(-10.0, 20.0),
        5: Point(10.0, 20.0),
        10: Point(1.0, 1.0),
        11: Point(1.0, 2.0),
        12: Point(2.0, 1.0),
        13: Point(0.0, 1.0),
    }
    node_kinds = {k: 0 for k in node_points.keys()}
    graph = RoadGraph(roads=roads, node_points=node_points, node_kinds=node_kinds)

    dist, diag = graph.find_next_intersection_distance_connected(
        nodeid=1,
        scan_dir=(0.0, 1.0),
        degree_min=3,
        intersection_kind_mask=None,
        max_hops=64,
        disable_geometric_fallback=True,
    )
    assert dist is not None
    assert abs(float(dist) - 20.0) < 1e-6
    assert bool(diag.get("used_fallback", False)) is False


def test_overall_pass_consumes_hard_breakpoints() -> None:
    seed_results = [
        {
            "nodeid": 1,
            "anchor_found": True,
            "scan_dist_m": 10.0,
            "stop_reason": "next_intersection_connected_deg3",
            "evidence_source": "drivezone",
            "trigger": "divstrip+dz",
        }
    ]
    breakpoints = [
        {
            "code": BP_DRIVEZONE_SPLIT_NOT_FOUND,
            "severity": "hard",
            "nodeid": 1,
            "message": "hard_failure",
        }
    ]
    metrics = build_metrics(
        patch_id="p",
        mode="global_focus",
        seed_results=seed_results,
        breakpoints=breakpoints,
        params=dict(DEFAULT_PARAMS),
        required_outputs_ok=True,
    )
    assert float(metrics.get("anchor_found_ratio", 0.0)) == 1.0
    assert int(metrics.get("hard_breakpoint_count", 0)) == 1
    assert bool(metrics.get("overall_pass", True)) is False

