from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from highway_topo_poc.modules.t04_rc_sw_anchor.config import DEFAULT_PARAMS
from highway_topo_poc.modules.t04_rc_sw_anchor.runner import run_from_runtime


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fc(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
        "features": list(features),
    }


def _poly_box(min_x: float, min_y: float, max_x: float, max_y: float) -> list[list[float]]:
    return [
        [float(min_x), float(min_y)],
        [float(max_x), float(min_y)],
        [float(max_x), float(max_y)],
        [float(min_x), float(max_y)],
        [float(min_x), float(min_y)],
    ]


def _build_case(
    tmp_path: Path,
    *,
    case_name: str,
    node_is_effective_end: bool,
    road_direction: int,
    add_second_supported_road: bool,
    drivezone_y_range: tuple[float, float],
    drivezone_features_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    patch_dir = tmp_path / case_name / "patch"
    global_dir = tmp_path / case_name / "global"
    vector_dir = patch_dir / "Vector"
    vector_dir.mkdir(parents=True, exist_ok=True)
    global_dir.mkdir(parents=True, exist_ok=True)

    k16_nodeid = 90010001
    node_other = 90010002
    node_extra = 90010003

    if node_is_effective_end:
        k16_xy = (0.0, 20.0)
        other_xy = (0.0, 0.0)
        road_snodeid = node_other
        road_enodeid = k16_nodeid
        road_coords = [[0.0, 0.0], [0.0, 20.0]]
    else:
        k16_xy = (0.0, 0.0)
        other_xy = (0.0, 20.0)
        road_snodeid = k16_nodeid
        road_enodeid = node_other
        road_coords = [[0.0, 0.0], [0.0, 20.0]]

    node_features = [
        {
            "type": "Feature",
            "properties": {"id": int(k16_nodeid), "kind": int(1 << 16)},
            "geometry": {"type": "Point", "coordinates": [float(k16_xy[0]), float(k16_xy[1])]},
        },
        {
            "type": "Feature",
            "properties": {"id": int(node_other), "kind": 4},
            "geometry": {"type": "Point", "coordinates": [float(other_xy[0]), float(other_xy[1])]},
        },
    ]
    road_features = [
        {
            "type": "Feature",
            "properties": {
                "snodeid": int(road_snodeid),
                "enodeid": int(road_enodeid),
                "direction": int(road_direction),
            },
            "geometry": {"type": "LineString", "coordinates": road_coords},
        }
    ]

    if add_second_supported_road:
        node_features.append(
            {
                "type": "Feature",
                "properties": {"id": int(node_extra), "kind": 4},
                "geometry": {"type": "Point", "coordinates": [10.0, 10.0]},
            }
        )
        road_features.append(
            {
                "type": "Feature",
                "properties": {
                    "snodeid": int(k16_nodeid),
                    "enodeid": int(node_extra),
                    "direction": 2,
                },
                "geometry": {"type": "LineString", "coordinates": [[float(k16_xy[0]), float(k16_xy[1])], [10.0, 10.0]]},
            }
        )

    _write_json(global_dir / "RCSDNode.geojson", _fc(node_features))
    _write_json(global_dir / "RCSDRoad.geojson", _fc(road_features))

    min_y, max_y = drivezone_y_range
    drivezone_features = drivezone_features_override or [
        {
            "type": "Feature",
            "properties": {"name": "k16_drivezone"},
            "geometry": {"type": "Polygon", "coordinates": [_poly_box(-5.0, float(min_y), 5.0, float(max_y))]},
        }
    ]
    _write_json(vector_dir / "DriveZone.geojson", _fc(drivezone_features))

    params = dict(DEFAULT_PARAMS)
    params.update({"continuous_enable": False, "k16_step_m": 0.5})
    runtime = {
        "mode": "global_focus",
        "patch_dir": str(patch_dir),
        "out_root": str(tmp_path / case_name / "outputs"),
        "run_id": f"run_{case_name}",
        "global_node_path": str(global_dir / "RCSDNode.geojson"),
        "global_road_path": str(global_dir / "RCSDRoad.geojson"),
        "drivezone_path": str(vector_dir / "DriveZone.geojson"),
        "focus_node_ids": [str(k16_nodeid)],
        "src_crs": "auto",
        "dst_crs": "EPSG:3857",
        "node_src_crs": "auto",
        "road_src_crs": "auto",
        "divstrip_src_crs": "auto",
        "drivezone_src_crs": "auto",
        "traj_src_crs": "auto",
        "pointcloud_crs": "auto",
        "params": params,
    }
    return {"runtime": runtime, "k16_nodeid": int(k16_nodeid)}


def _run_case(tmp_path: Path, **kwargs) -> tuple[dict[str, Any], list[str]]:
    built = _build_case(tmp_path, **kwargs)
    out_dir = run_from_runtime(built["runtime"]).out_dir
    anchors = _read_json(out_dir / "anchors.json")
    item = anchors.get("items", [])[0]
    bp = _read_json(out_dir / "breakpoints.json")
    bp_codes = [str(x.get("code")) for x in bp.get("items", [])]
    return item, bp_codes


def test_k16_forward_search_hits_drivezone(tmp_path: Path) -> None:
    item, _bp = _run_case(
        tmp_path,
        case_name="k16_forward",
        node_is_effective_end=False,
        road_direction=2,
        add_second_supported_road=False,
        drivezone_y_range=(2.0, 2.8),
    )
    assert str(item.get("status")) == "ok"
    assert bool(item.get("k16_enabled", False)) is True
    assert str(item.get("k16_search_dir")) == "forward"
    assert float(item.get("k16_s_found_m")) == 2.0
    assert float(item.get("left_end_to_drivezone_edge_m", 9.9)) <= 0.15
    assert float(item.get("right_end_to_drivezone_edge_m", 9.9)) <= 0.15


def test_k16_reverse_search_hits_drivezone(tmp_path: Path) -> None:
    item, _bp = _run_case(
        tmp_path,
        case_name="k16_reverse",
        node_is_effective_end=True,
        road_direction=2,
        add_second_supported_road=False,
        drivezone_y_range=(18.0, 18.8),
    )
    assert str(item.get("status")) == "ok"
    assert bool(item.get("k16_enabled", False)) is True
    assert str(item.get("k16_search_dir")) == "reverse"
    assert -10.0 <= float(item.get("k16_s_found_m", 1.0)) <= 0.0


def test_k16_refine_ahead_prefers_stable_wider_crossline(tmp_path: Path) -> None:
    drivezone_features = [
        {
            "type": "Feature",
            "properties": {"name": "near_narrow"},
            "geometry": {"type": "Polygon", "coordinates": [_poly_box(-0.3, 0.5, 0.3, 0.8)]},
        },
        {
            "type": "Feature",
            "properties": {"name": "ahead_wide"},
            "geometry": {"type": "Polygon", "coordinates": [_poly_box(-5.0, 2.0, 5.0, 2.8)]},
        },
    ]
    item, _bp = _run_case(
        tmp_path,
        case_name="k16_refine_ahead",
        node_is_effective_end=False,
        road_direction=2,
        add_second_supported_road=False,
        drivezone_y_range=(0.5, 2.8),
        drivezone_features_override=drivezone_features,
    )
    assert str(item.get("status")) == "ok"
    assert bool(item.get("k16_refined_used", False)) is True
    assert abs(float(item.get("k16_first_hit_s_m")) - 0.5) <= 1e-6
    assert float(item.get("k16_s_found_m")) >= 2.0
    assert float(item.get("k16_refined_len_m")) > float(item.get("k16_first_hit_len_m"))
    assert str(item.get("split_pick_source")) == "k16_first_intersection_refined"


def test_k16_output_rebuild_reaches_both_piece_edges_without_threshold(tmp_path: Path) -> None:
    drivezone_features = [
        {
            "type": "Feature",
            "properties": {"name": "asymmetric_wide"},
            "geometry": {"type": "Polygon", "coordinates": [_poly_box(-2.0, 2.0, 30.0, 2.8)]},
        }
    ]
    item, _bp = _run_case(
        tmp_path,
        case_name="k16_edge_rebuild",
        node_is_effective_end=False,
        road_direction=2,
        add_second_supported_road=False,
        drivezone_y_range=(2.0, 2.8),
        drivezone_features_override=drivezone_features,
    )
    assert str(item.get("status")) == "ok"
    # If output still used half_len=10, seg_len would be around 12m here.
    assert float(item.get("seg_len_m", 0.0)) > 20.0
    assert float(item.get("left_end_to_drivezone_edge_m", 9.9)) <= 1e-6
    assert float(item.get("right_end_to_drivezone_edge_m", 9.9)) <= 1e-6


def test_k16_fail_when_multiple_roads(tmp_path: Path) -> None:
    item, bp_codes = _run_case(
        tmp_path,
        case_name="k16_multi_road_fail",
        node_is_effective_end=False,
        road_direction=2,
        add_second_supported_road=True,
        drivezone_y_range=(2.0, 2.8),
    )
    assert str(item.get("status")) == "fail"
    assert "K16_ROAD_NOT_UNIQUE" in bp_codes
    assert str(item.get("k16_break_reason", "")).startswith("k16_road_not_unique")


def test_k16_fail_when_direction_0_1(tmp_path: Path) -> None:
    item, bp_codes = _run_case(
        tmp_path,
        case_name="k16_dir01_fail",
        node_is_effective_end=False,
        road_direction=1,
        add_second_supported_road=False,
        drivezone_y_range=(2.0, 2.8),
    )
    assert str(item.get("status")) == "fail"
    assert "K16_ROAD_DIR_UNSUPPORTED" in bp_codes
    assert str(item.get("k16_break_reason", "")).startswith("k16_road_direction_unsupported")


def test_k16_fail_when_drivezone_not_reached(tmp_path: Path) -> None:
    item, bp_codes = _run_case(
        tmp_path,
        case_name="k16_not_reached",
        node_is_effective_end=False,
        road_direction=2,
        add_second_supported_road=False,
        drivezone_y_range=(30.0, 31.0),
    )
    assert str(item.get("status")) == "fail"
    assert "K16_DRIVEZONE_NOT_REACHED" in bp_codes
    assert item.get("k16_min_dist_cross_to_drivezone_m") is not None
    assert float(item.get("k16_min_dist_cross_to_drivezone_m")) > 0.0
    assert item.get("k16_s_best_m") is not None
