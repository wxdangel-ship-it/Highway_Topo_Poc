from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point

from highway_topo_poc.modules.t04_rc_sw_anchor.config import DEFAULT_PARAMS
from highway_topo_poc.modules.t04_rc_sw_anchor.io_geojson import RoadRecord
from highway_topo_poc.modules.t04_rc_sw_anchor.road_graph import RoadGraph
from highway_topo_poc.modules.t04_rc_sw_anchor.runner import run_from_runtime

from ._synth_patch_factory import create_synth_patch


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _assert_away_from_node_window(*, s_chosen: float, ref_s: float, window_m: float = 1.0) -> None:
    if float(ref_s) < 0.0:
        assert (float(ref_s) - float(window_m)) <= float(s_chosen) <= float(ref_s)
        return
    assert float(ref_s) <= float(s_chosen) <= (float(ref_s) + float(window_m))


def _assert_toward_node_window(*, s_chosen: float, ref_s: float, window_m: float = 1.0) -> None:
    if float(ref_s) < 0.0:
        lo = float(ref_s)
        hi = float(min(0.0, float(ref_s) + float(window_m)))
        assert lo <= float(s_chosen) <= hi
        return
    lo = float(max(0.0, float(ref_s) - float(window_m)))
    hi = float(ref_s)
    assert lo <= float(s_chosen) <= hi


def _layer_center_xy(path: Path) -> tuple[float, float]:
    payload = _read_json(path)
    xs: list[float] = []
    ys: list[float] = []
    for feat in payload.get("features", []):
        geom = feat.get("geometry", {})
        if str(geom.get("type")) != "Polygon":
            continue
        ring = (geom.get("coordinates") or [[]])[0]
        for p in ring:
            xs.append(float(p[0]))
            ys.append(float(p[1]))
    if not xs or not ys:
        return (0.0, 0.0)
    return (0.5 * (min(xs) + max(xs)), 0.5 * (min(ys) + max(ys)))


def _box(cx: float, cy: float, min_dx: float, min_dy: float, max_dx: float, max_dy: float) -> list[list[float]]:
    return [
        [cx + min_dx, cy + min_dy],
        [cx + max_dx, cy + min_dy],
        [cx + max_dx, cy + max_dy],
        [cx + min_dx, cy + max_dy],
        [cx + min_dx, cy + min_dy],
    ]


def _run_runtime(
    tmp_path: Path,
    *,
    run_id: str,
    data: dict | None = None,
    focus_node_ids: list[str] | None = None,
    params_override: dict | None = None,
) -> tuple[dict, Path]:
    patch_data = data or create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    out_root = tmp_path / "outputs" / "_work" / "t04_rc_sw_anchor"
    params = dict(DEFAULT_PARAMS)
    if params_override:
        params.update(params_override)
    runtime = {
        "mode": "global_focus",
        "patch_dir": str(patch_data["patch_dir"]),
        "out_root": str(out_root),
        "run_id": run_id,
        "global_node_path": str(patch_data["global_node_path"]),
        "global_road_path": str(patch_data["global_road_path"]),
        "divstrip_path": str(patch_data["divstrip_path"]),
        "drivezone_path": str(patch_data["drivezone_path"]),
        "pointcloud_path": str(patch_data["pointcloud_path"]),
        "traj_glob": str(patch_data["traj_glob"]),
        "focus_node_ids": focus_node_ids if focus_node_ids is not None else list(patch_data["focus_node_ids"]),
        "src_crs": "auto",
        "dst_crs": "EPSG:3857",
        "node_src_crs": "auto",
        "road_src_crs": "auto",
        "divstrip_src_crs": "auto",
        "drivezone_src_crs": "auto",
        "traj_src_crs": "auto",
        "pointcloud_crs": str(patch_data["pointcloud_crs"]),
        "params": params,
    }
    result = run_from_runtime(runtime)
    return patch_data, result.out_dir


def _rewrite_drivezone_single_polygon(path: Path) -> None:
    payload = _read_json(path)
    cx, cy = _layer_center_xy(path)
    payload["features"] = [
        {
            "type": "Feature",
            "properties": {"name": "single_roadbed"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box(cx, cy, -30.0, -120.0, 30.0, 120.0)],
            },
        }
    ]
    payload.pop("crs", None)
    payload["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    _write_json(path, payload)


def _rewrite_drivezone_three_pieces(path: Path) -> None:
    payload = _read_json(path)
    cx, cy = _layer_center_xy(path)
    payload["features"] = [
        {
            "type": "Feature",
            "properties": {"name": "left"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box(cx, cy, -12.2, -120.0, -2.2, 120.0)],
            },
        },
        {
            "type": "Feature",
            "properties": {"name": "mid"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box(cx, cy, -2.0, -120.0, 2.0, 120.0)],
            },
        },
        {
            "type": "Feature",
            "properties": {"name": "right"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box(cx, cy, 2.2, -120.0, 12.2, 120.0)],
            },
        },
    ]
    payload.pop("crs", None)
    payload["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    _write_json(path, payload)


def _rewrite_drivezone_split_band(path: Path) -> None:
    payload = _read_json(path)
    cx, cy = _layer_center_xy(path)
    payload["features"] = [
        {
            "type": "Feature",
            "properties": {"name": "left_band"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box(cx, cy, -30.0, 10.0, -4.0, 24.0)],
            },
        },
        {
            "type": "Feature",
            "properties": {"name": "right_band"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box(cx, cy, 4.0, 10.0, 30.0, 24.0)],
            },
        },
    ]
    payload.pop("crs", None)
    payload["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    _write_json(path, payload)


def _rewrite_divstrip_far_only(path: Path) -> None:
    _rewrite_divstrip_offset(path, dy=150.0)


def _rewrite_divstrip_offset(path: Path, *, dy: float) -> None:
    payload = _read_json(path)
    cx, cy = _layer_center_xy(path)
    payload["features"] = [
        {
            "type": "Feature",
            "properties": {"name": "far_divstrip"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box(cx, cy + float(dy), -2.0, -3.0, 2.0, 3.0)],
            },
        }
    ]
    payload.pop("crs", None)
    payload["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    _write_json(path, payload)


def _rewrite_divstrip_merge_priority(path: Path) -> None:
    payload = _read_json(path)
    cx, cy = _layer_center_xy(path)
    payload["features"] = [
        {
            "type": "Feature",
            "properties": {"name": "merge_priority"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box(cx, cy + 25.0, -2.0, -3.0, 2.0, 3.0)],
            },
        }
    ]
    payload.pop("crs", None)
    payload["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    _write_json(path, payload)


def _rewrite_drivezone_crs_unknown(path: Path) -> None:
    payload = _read_json(path)
    payload.pop("crs", None)
    payload["features"] = [
        {
            "type": "Feature",
            "properties": {"name": "unknown_crs_poly"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[500.0, 500.0], [520.0, 500.0], [520.0, 520.0], [500.0, 520.0], [500.0, 500.0]]],
            },
        }
    ]
    _write_json(path, payload)


def test_diverge_no_divstrip_drivezone_split_found(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    data["divstrip_path"].unlink()
    data, out_dir = _run_runtime(
        tmp_path,
        run_id="diverge_no_divstrip_rerun",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
    )
    anchors = _read_json(out_dir / "anchors.json")
    item = anchors["items"][0]
    assert str(item.get("trigger")) == "drivezone_split"
    assert bool(item.get("found_split", False)) is True
    assert int(item.get("pieces_count", 0)) == 2
    assert str(item.get("status")) in {"ok", "suspect"}


def test_merge_no_divstrip_drivezone_split_found(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    data["divstrip_path"].unlink()
    _data, out_dir = _run_runtime(
        tmp_path,
        run_id="merge_no_divstrip",
        data=data,
        focus_node_ids=[str(data["node_merge"])],
    )
    anchors = _read_json(out_dir / "anchors.json")
    item = anchors["items"][0]
    assert str(item.get("trigger")) == "drivezone_split"
    assert bool(item.get("found_split", False)) is True
    assert int(item.get("pieces_count", 0)) == 2


def test_divstrip_window_direction_for_diverge(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    _data, out_dir = _run_runtime(
        tmp_path,
        run_id="divstrip_window_direction_for_diverge",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
    )
    item = _read_json(out_dir / "anchors.json")["items"][0]
    assert str(item.get("status")) in {"ok", "suspect"}
    s_div = float(item.get("s_divstrip_m", 0.0))
    s_chosen = float(item.get("s_chosen_m", -1.0))
    _assert_toward_node_window(s_chosen=s_chosen, ref_s=s_div)


def test_prevent_cross_intersection_drift(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    _rewrite_drivezone_single_polygon(data["drivezone_path"])
    _rewrite_divstrip_far_only(data["divstrip_path"])
    _data, out_dir = _run_runtime(
        tmp_path,
        run_id="prevent_cross_intersection_drift",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
    )
    anchors = _read_json(out_dir / "anchors.json")
    item = anchors["items"][0]
    assert str(item.get("status")) == "fail"
    assert bool(item.get("anchor_found", True)) is False
    assert str(item.get("trigger")) == "none"
    bp = _read_json(out_dir / "breakpoints.json")
    by_code = {str(x.get("code")): int(x.get("count", 0)) for x in bp.get("by_code", [])}
    assert by_code.get("DRIVEZONE_CLIP_EMPTY", 0) >= 1


def test_drivezone_clip_multifeature_output_single_continuous_line(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    data["divstrip_path"].unlink()
    data, out_dir = _run_runtime(
        tmp_path,
        run_id="multifeature_two_lines",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
    )
    inter = _read_json(out_dir / "intersection_l_opt.geojson")
    feats = [f for f in inter.get("features", []) if int(f.get("properties", {}).get("nodeid", -1)) == int(data["node_diverge"])]
    assert len(feats) == 1
    assert int(feats[0]["properties"]["piece_idx"]) == 0
    assert str(feats[0]["properties"].get("piece_role")) == "single_piece"
    assert str(feats[0].get("geometry", {}).get("type")) == "LineString"
    anchors = _read_json(out_dir / "anchors.json")
    item = anchors["items"][0]
    assert float(item.get("clipped_len_m", 0.0)) > 0.0
    assert float(item.get("clipped_len_m", 0.0)) <= float(item.get("clip_input_len_m", 0.0))
    assert int(item.get("selected_piece_count", 0)) == 1
    assert float(item.get("left_end_to_drivezone_edge_m", 99.0)) <= 0.2
    assert float(item.get("right_end_to_drivezone_edge_m", 99.0)) <= 0.2
    assert float(item.get("output_cross_half_len_m", 0.0)) >= 120.0


def test_divstrip_priority_over_earliest_split(tmp_path: Path) -> None:
    base_data = create_synth_patch(tmp_path / "base", kind_key="kind", id_mode="id", crs_mode="3857")
    base_data["divstrip_path"].unlink()
    _data0, out0 = _run_runtime(
        tmp_path / "base",
        run_id="divstrip_priority_base",
        data=base_data,
        focus_node_ids=[str(base_data["node_merge"])],
    )
    base_item = _read_json(out0 / "anchors.json")["items"][0]
    base_scan = float(base_item.get("scan_dist_m", 0.0))

    pref_data = create_synth_patch(tmp_path / "pref", kind_key="kind", id_mode="id", crs_mode="3857")
    _rewrite_divstrip_merge_priority(pref_data["divstrip_path"])
    _data1, out1 = _run_runtime(
        tmp_path / "pref",
        run_id="divstrip_priority_pref",
        data=pref_data,
        focus_node_ids=[str(pref_data["node_merge"])],
    )
    pref_item = _read_json(out1 / "anchors.json")["items"][0]

    pref_scan = float(pref_item.get("scan_dist_m", 0.0))
    assert pref_scan >= base_scan + 5.0
    assert str(pref_item.get("split_pick_source", "")).startswith("divstrip_")


def test_divstrip_far_reference_must_not_override_drivezone_split(tmp_path: Path) -> None:
    base_data = create_synth_patch(tmp_path / "base_far", kind_key="kind", id_mode="id", crs_mode="3857")
    base_data["divstrip_path"].unlink()
    _data0, out0 = _run_runtime(
        tmp_path / "base_far",
        run_id="divstrip_far_base",
        data=base_data,
        focus_node_ids=[str(base_data["node_merge"])],
    )
    base_item = _read_json(out0 / "anchors.json")["items"][0]
    base_scan = float(base_item.get("scan_dist_m", 0.0))

    far_data = create_synth_patch(tmp_path / "far_case", kind_key="kind", id_mode="id", crs_mode="3857")
    # Keep divstrip within stop_dist but far from earliest split, must fallback to drivezone split.
    _rewrite_divstrip_offset(far_data["divstrip_path"], dy=-75.0)
    _data1, out1 = _run_runtime(
        tmp_path / "far_case",
        run_id="divstrip_far_guard",
        data=far_data,
        focus_node_ids=[str(far_data["node_merge"])],
    )
    far_item = _read_json(out1 / "anchors.json")["items"][0]

    far_scan = float(far_item.get("scan_dist_m", 0.0))
    assert abs(far_scan - base_scan) <= 2.0
    assert str(far_item.get("split_pick_source", "")) == "drivezone_split_window_divstrip_far_ignored"


def test_divstrip_hard_window_requires_split_within_1m(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    _rewrite_drivezone_split_band(data["drivezone_path"])
    _data, out_dir = _run_runtime(
        tmp_path,
        run_id="divstrip_hard_window_requires_split_within_1m",
        data=data,
        focus_node_ids=[str(data["node_merge"])],
    )
    item = _read_json(out_dir / "anchors.json")["items"][0]
    assert str(item.get("status")) == "fail"
    assert bool(item.get("anchor_found", True)) is False
    assert bool(item.get("found_split", True)) is False
    assert str(item.get("split_pick_source")) == "divstrip_first_hit_window_no_piece"
    assert float(item.get("s_drivezone_split_m", 0.0)) >= float(item.get("s_divstrip_m", 0.0)) + 5.0
    bp = _read_json(out_dir / "breakpoints.json")
    by_code = {str(x.get("code")): int(x.get("count", 0)) for x in bp.get("by_code", [])}
    assert by_code.get("DRIVEZONE_CLIP_EMPTY", 0) >= 1


def test_drivezone_clip_more_than_two_pieces(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    _rewrite_drivezone_three_pieces(data["drivezone_path"])
    _data, out_dir = _run_runtime(
        tmp_path,
        run_id="clip_more_than_two_pieces",
        data=data,
        focus_node_ids=[str(data["node_merge"])],
    )
    bp = _read_json(out_dir / "breakpoints.json")
    by_code = {str(x.get("code")): int(x.get("count", 0)) for x in bp.get("by_code", [])}
    assert by_code.get("DRIVEZONE_CLIP_MULTIPIECE", 0) >= 1
    inter = _read_json(out_dir / "intersection_l_opt.geojson")
    feats = [f for f in inter.get("features", []) if int(f.get("properties", {}).get("nodeid", -1)) == int(data["node_merge"])]
    assert len(feats) == 1
    assert str(feats[0].get("geometry", {}).get("type")) == "LineString"


def test_hard_stop_deg3_only() -> None:
    roads = [
        RoadRecord(snodeid=1, enodeid=2, line=LineString([(0.0, 0.0), (0.0, 10.0)]), length_m=10.0),
        RoadRecord(snodeid=2, enodeid=3, line=LineString([(0.0, 10.0), (0.0, 20.0)]), length_m=10.0),
        RoadRecord(snodeid=3, enodeid=4, line=LineString([(0.0, 20.0), (-10.0, 20.0)]), length_m=10.0),
        RoadRecord(snodeid=3, enodeid=5, line=LineString([(0.0, 20.0), (10.0, 20.0)]), length_m=10.0),
    ]
    node_points = {
        1: Point(0.0, 0.0),
        2: Point(0.0, 10.0),
        3: Point(0.0, 20.0),
        4: Point(-10.0, 20.0),
        5: Point(10.0, 20.0),
    }
    node_kinds = {k: 0 for k in node_points.keys()}
    graph = RoadGraph(roads=roads, node_points=node_points, node_kinds=node_kinds)
    dist, diag = graph.find_next_intersection_connected_deg3(nodeid=1, scan_dir=(0.0, 1.0), degree_min=3)
    assert dist is not None
    assert abs(float(dist) - 20.0) < 1e-6
    assert int(diag.get("next_intersection_nodeid")) == 3
    assert int(diag.get("deg_too_low_skipped", 0)) >= 1


def test_status_not_overwritten(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    _rewrite_drivezone_single_polygon(data["drivezone_path"])
    _data, out_dir = _run_runtime(
        tmp_path,
        run_id="status_not_overwritten",
        data=data,
        focus_node_ids=[str(data["node_merge"])],
    )
    anchors = _read_json(out_dir / "anchors.json")
    item = anchors["items"][0]
    assert str(item.get("status")) in {"ok", "suspect"}
    assert bool(item.get("anchor_found", False)) is True
    assert str(item.get("trigger")) == "divstrip_ref"
    s_div = float(item.get("s_divstrip_m", 0.0))
    s_chosen = float(item.get("s_chosen_m", -1.0))
    _assert_toward_node_window(s_chosen=s_chosen, ref_s=s_div)


def test_crs_fail_closed(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    _rewrite_drivezone_crs_unknown(data["drivezone_path"])
    _data, out_dir = _run_runtime(
        tmp_path,
        run_id="crs_fail_closed",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
    )
    bp = _read_json(out_dir / "breakpoints.json")
    by_code = {str(x.get("code")): int(x.get("count", 0)) for x in bp.get("by_code", [])}
    assert by_code.get("DRIVEZONE_CRS_UNKNOWN", 0) >= 1
    metrics = _read_json(out_dir / "metrics.json")
    assert bool(metrics.get("overall_pass", True)) is False
