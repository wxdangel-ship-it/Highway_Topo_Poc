from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon, mapping

from highway_topo_poc.modules.t06_patch_preprocess import geom, pipeline


def _write_fc(path: Path, *, crs: str | None, features: list[dict]) -> None:
    payload = {"type": "FeatureCollection", "features": features}
    if crs is not None:
        payload["crs"] = {"type": "name", "properties": {"name": crs}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _mk_patch(tmp_path: Path, *, patch_id: str, node_features: list[dict], road_features: list[dict], drivezone_features: list[dict]) -> Path:
    patch_dir = tmp_path / patch_id
    vec = patch_dir / "Vector"
    _write_fc(vec / "RCSDNode.geojson", crs="EPSG:3857", features=node_features)
    _write_fc(vec / "RCSDRoad.geojson", crs="EPSG:3857", features=road_features)
    _write_fc(vec / "DriveZone.geojson", crs="EPSG:3857", features=drivezone_features)
    return patch_dir


def _node_feature(node_id: int, x: float, y: float, *, kind: int = 0, mainid: int = 0) -> dict:
    return {
        "type": "Feature",
        "geometry": mapping(Point(x, y)),
        "properties": {"id": node_id, "Kind": kind, "mainid": mainid},
    }


def _road_feature(s_id: int, e_id: int, coords: list[tuple[float, float]], *, direction: int = 2) -> dict:
    return {
        "type": "Feature",
        "geometry": mapping(LineString(coords)),
        "properties": {"snodeid": s_id, "enodeid": e_id, "direction": direction},
    }


def _poly_feature(poly: Polygon) -> dict:
    return {"type": "Feature", "geometry": mapping(poly), "properties": {}}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_case1_inside_no_change_no_new_node(tmp_path: Path) -> None:
    patch = _mk_patch(
        tmp_path,
        patch_id="p_case1",
        node_features=[_node_feature(1, 0.0, 0.0), _node_feature(2, 10.0, 0.0)],
        road_features=[_road_feature(1, 2, [(0.0, 0.0), (10.0, 0.0)])],
        drivezone_features=[_poly_feature(Polygon([(-1.0, -1.0), (11.0, -1.0), (11.0, 1.0), (-1.0, 1.0)]))],
    )

    result = pipeline.run_patch(data_root=patch, patch="auto", run_id="ut_case1", out_root=tmp_path / "out", overwrite=True)

    summary = _read_json(result.summary_path)
    road_fc = _read_json(result.output_dir / "Vector" / "RCSDRoad.geojson")
    node_fc = _read_json(result.output_dir / "Vector" / "RCSDNode.geojson")

    assert summary["roads_in"] == 1
    assert summary["roads_out"] == 1
    assert summary["nodes_created"] == 0
    assert summary["missing_endpoint_refs_out"] == 0
    assert road_fc["crs"]["properties"]["name"] == "EPSG:3857"
    assert node_fc["crs"]["properties"]["name"] == "EPSG:3857"

    node_ids = {f["properties"]["id"] for f in node_fc["features"]}
    r0 = road_fc["features"][0]["properties"]
    assert r0["snodeid"] in node_ids
    assert r0["enodeid"] in node_ids


def test_case2_clip_changes_one_endpoint_and_creates_virtual_node(tmp_path: Path) -> None:
    patch = _mk_patch(
        tmp_path,
        patch_id="p_case2",
        node_features=[_node_feature(1, 0.0, 0.0)],
        road_features=[_road_feature(1, 999, [(0.0, 0.0), (20.0, 0.0)])],
        drivezone_features=[_poly_feature(Polygon([(-1.0, -1.0), (10.0, -1.0), (10.0, 1.0), (-1.0, 1.0)]))],
    )

    result = pipeline.run_patch(data_root=patch, patch="auto", run_id="ut_case2", out_root=tmp_path / "out", overwrite=True)

    summary = _read_json(result.summary_path)
    node_fc = _read_json(result.output_dir / "Vector" / "RCSDNode.geojson")
    road_fc = _read_json(result.output_dir / "Vector" / "RCSDRoad.geojson")

    assert summary["roads_out"] == 1
    assert summary["nodes_created"] == 1
    assert summary["updated_enodeid_count"] == 1
    assert summary["missing_endpoint_refs_out"] == 0

    node_ids = {f["properties"]["id"] for f in node_fc["features"]}
    new_nodes = [f for f in node_fc["features"] if f["properties"]["id"] != 1]
    assert len(new_nodes) == 1
    assert int(new_nodes[0]["properties"]["Kind"]) & geom.BIT16_VALUE == geom.BIT16_VALUE

    out_props = road_fc["features"][0]["properties"]
    assert out_props["snodeid"] == 1
    assert out_props["enodeid"] in node_ids


def test_case3_multisegment_choice_prefers_src_connection() -> None:
    src_node = Point(0.0, 0.0)
    dst_node = Point(10.0, 0.0)
    seg_src = LineString([(0.0, 0.0), (1.0, 0.0)])
    seg_dst = LineString([(9.0, 0.0), (10.0, 0.0)])

    choice = geom.choose_segment(
        segments=[seg_dst, seg_src],
        src_exists=True,
        dst_exists=True,
        src_node=src_node,
        dst_node=dst_node,
        tol_m=0.05,
    )

    assert choice.segment is not None
    assert choice.segment.equals(seg_src)
    assert choice.connect_src is True


def test_case4_both_endpoints_missing_drops_road(tmp_path: Path) -> None:
    patch = _mk_patch(
        tmp_path,
        patch_id="p_case4",
        node_features=[_node_feature(1, 0.0, 0.0), _node_feature(2, 10.0, 0.0)],
        road_features=[_road_feature(8000, 9000, [(0.0, 0.0), (10.0, 0.0)])],
        drivezone_features=[_poly_feature(Polygon([(-1.0, -1.0), (11.0, -1.0), (11.0, 1.0), (-1.0, 1.0)]))],
    )

    result = pipeline.run_patch(data_root=patch, patch="auto", run_id="ut_case4", out_root=tmp_path / "out", overwrite=True)

    summary = _read_json(result.summary_path)
    drop_reasons = _read_json(result.drop_reasons_path)
    road_fc = _read_json(result.output_dir / "Vector" / "RCSDRoad.geojson")

    assert summary["roads_in"] == 1
    assert summary["roads_out"] == 0
    assert summary["missing_endpoint_refs_out"] == 0
    assert drop_reasons.get("no_existing_endpoint_connected") == 1
    assert road_fc["features"] == []


def test_case5_missing_drivezone_crs_uses_node_road_crs(tmp_path: Path) -> None:
    patch = tmp_path / "p_case5"
    vec = patch / "Vector"
    _write_fc(
        vec / "RCSDNode.geojson",
        crs="EPSG:3857",
        features=[_node_feature(1, 0.0, 0.0), _node_feature(2, 10.0, 0.0)],
    )
    _write_fc(
        vec / "RCSDRoad.geojson",
        crs="EPSG:3857",
        features=[_road_feature(1, 2, [(0.0, 0.0), (10.0, 0.0)])],
    )
    _write_fc(
        vec / "DriveZone.geojson",
        crs=None,
        features=[_poly_feature(Polygon([(-1.0, -1.0), (11.0, -1.0), (11.0, 1.0), (-1.0, 1.0)]))],
    )

    result = pipeline.run_patch(data_root=patch, patch="auto", run_id="ut_case5", out_root=tmp_path / "out", overwrite=True)
    summary = _read_json(result.summary_path)
    road_fc = _read_json(result.output_dir / "Vector" / "RCSDRoad.geojson")

    assert summary["roads_in"] == 1
    assert summary["roads_out"] == 1
    assert road_fc["crs"]["properties"]["name"] == "EPSG:3857"


def test_case6_invalid_type_drivezone_crs_uses_node_road_crs(tmp_path: Path) -> None:
    patch = tmp_path / "p_case6"
    vec = patch / "Vector"
    _write_fc(
        vec / "RCSDNode.geojson",
        crs="EPSG:3857",
        features=[_node_feature(1, 0.0, 0.0), _node_feature(2, 10.0, 0.0)],
    )
    _write_fc(
        vec / "RCSDRoad.geojson",
        crs="EPSG:3857",
        features=[_road_feature(1, 2, [(0.0, 0.0), (10.0, 0.0)])],
    )
    dz_payload = {
        "type": "FeatureCollection",
        "crs": 3857,
        "features": [_poly_feature(Polygon([(-1.0, -1.0), (11.0, -1.0), (11.0, 1.0), (-1.0, 1.0)]))],
    }
    (vec / "DriveZone.geojson").parent.mkdir(parents=True, exist_ok=True)
    (vec / "DriveZone.geojson").write_text(json.dumps(dz_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = pipeline.run_patch(data_root=patch, patch="auto", run_id="ut_case6", out_root=tmp_path / "out", overwrite=True)
    summary = _read_json(result.summary_path)
    road_fc = _read_json(result.output_dir / "Vector" / "RCSDRoad.geojson")

    assert summary["roads_in"] == 1
    assert summary["roads_out"] == 1
    assert road_fc["crs"]["properties"]["name"] == "EPSG:3857"


def test_case7_stringified_json_drivezone_crs_is_unwrapped(tmp_path: Path) -> None:
    patch = tmp_path / "p_case7"
    vec = patch / "Vector"
    _write_fc(
        vec / "RCSDNode.geojson",
        crs="EPSG:3857",
        features=[_node_feature(1, 0.0, 0.0), _node_feature(2, 10.0, 0.0)],
    )
    _write_fc(
        vec / "RCSDRoad.geojson",
        crs="EPSG:3857",
        features=[_road_feature(1, 2, [(0.0, 0.0), (10.0, 0.0)])],
    )
    dz_payload = {
        "type": "FeatureCollection",
        "crs": "{\"type\": \"name\", \"properties\": {\"name\": \"urn:ogc:def:crs:OGC:1.3:CRS84\"}}",
        "features": [_poly_feature(Polygon([(-1.0, -1.0), (11.0, -1.0), (11.0, 1.0), (-1.0, 1.0)]))],
    }
    (vec / "DriveZone.geojson").parent.mkdir(parents=True, exist_ok=True)
    (vec / "DriveZone.geojson").write_text(json.dumps(dz_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = pipeline.run_patch(data_root=patch, patch="auto", run_id="ut_case7", out_root=tmp_path / "out", overwrite=True)
    summary = _read_json(result.summary_path)
    road_fc = _read_json(result.output_dir / "Vector" / "RCSDRoad.geojson")

    assert summary["roads_in"] == 1
    assert summary["roads_out"] == 1
    assert road_fc["crs"]["properties"]["name"] == "EPSG:3857"
