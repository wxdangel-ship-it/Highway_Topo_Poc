from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from highway_topo_poc.modules.t04_rc_sw_anchor.crs_norm import webmercator_to_wgs84, wgs84_to_webmercator


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _node_props(*, node_id: int, kind_value: int, kind_key: str, id_mode: str) -> dict[str, Any]:
    props: dict[str, Any] = {kind_key: int(kind_value)}
    if id_mode == "id":
        props["id"] = int(node_id)
    elif id_mode == "mainnodeid":
        props["mainnodeid"] = int(node_id)
    else:
        raise ValueError(f"unsupported_id_mode: {id_mode}")
    return props


def _make_xy_transform(layer_crs: str) -> Callable[[float, float], tuple[float, float]]:
    layer = str(layer_crs).upper()
    if layer == "EPSG:3857":
        cx, cy = wgs84_to_webmercator(120.0, 30.0)

        def _f(dx_m: float, dy_m: float) -> tuple[float, float]:
            return float(cx + dx_m), float(cy + dy_m)

        return _f

    if layer == "EPSG:4326":
        cx, cy = wgs84_to_webmercator(120.0, 30.0)

        def _f(dx_m: float, dy_m: float) -> tuple[float, float]:
            return webmercator_to_wgs84(float(cx + dx_m), float(cy + dy_m))

        return _f

    raise ValueError(f"unsupported_layer_crs:{layer_crs}")


def _fc(features: list[dict[str, Any]], crs_name: str) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": crs_name}},
        "features": features,
    }


def create_synth_patch(
    root: Path,
    *,
    kind_key: str = "Kind",
    id_mode: str = "id",
    crs_mode: str = "3857",
) -> dict[str, Any]:
    patch_id = "2855795596723843"
    node_div = 5278670377721456
    node_merge = 5278670377721468
    node_in = 50000001
    node_div_left = 50000002
    node_div_right = 50000003
    node_merge_left = 50000004
    node_merge_right = 50000005
    node_out = 50000006

    if crs_mode == "3857":
        node_road_crs = "EPSG:3857"
        divstrip_crs = "EPSG:3857"
        drivezone_crs = "EPSG:3857"
        traj_crs = "EPSG:3857"
        pointcloud_crs = "EPSG:3857"
    elif crs_mode == "4326":
        node_road_crs = "EPSG:4326"
        divstrip_crs = "EPSG:4326"
        drivezone_crs = "EPSG:4326"
        traj_crs = "EPSG:4326"
        pointcloud_crs = "EPSG:4326"
    elif crs_mode == "mixed":
        node_road_crs = "EPSG:4326"
        divstrip_crs = "EPSG:3857"
        drivezone_crs = "EPSG:3857"
        traj_crs = "EPSG:4326"
        pointcloud_crs = "EPSG:4326"
    else:
        raise ValueError(f"unsupported_crs_mode:{crs_mode}")

    xy_node_road = _make_xy_transform(node_road_crs)
    xy_div = _make_xy_transform(divstrip_crs)
    xy_dz = _make_xy_transform(drivezone_crs)
    xy_traj = _make_xy_transform(traj_crs)
    xy_pc = _make_xy_transform(pointcloud_crs)

    patch_dir = root / patch_id
    (patch_dir / "Vector").mkdir(parents=True, exist_ok=True)
    (patch_dir / "PointCloud").mkdir(parents=True, exist_ok=True)
    (patch_dir / "Traj" / "0001").mkdir(parents=True, exist_ok=True)

    global_dir = root / "global"
    global_dir.mkdir(parents=True, exist_ok=True)

    def nr(dx: float, dy: float) -> list[float]:
        x, y = xy_node_road(dx, dy)
        return [x, y]

    def dv(dx: float, dy: float) -> list[float]:
        x, y = xy_div(dx, dy)
        return [x, y]

    def tr(dx: float, dy: float) -> list[float]:
        x, y = xy_traj(dx, dy)
        return [x, y]

    def dz(dx: float, dy: float) -> list[float]:
        x, y = xy_dz(dx, dy)
        return [x, y]

    def pc(dx: float, dy: float) -> list[float]:
        x, y = xy_pc(dx, dy)
        return [x, y]

    node_features = [
        {
            "type": "Feature",
            "properties": _node_props(node_id=node_div, kind_value=16, kind_key=kind_key, id_mode=id_mode),
            "geometry": {"type": "Point", "coordinates": nr(0.0, 0.0)},
        },
        {
            "type": "Feature",
            "properties": _node_props(node_id=node_merge, kind_value=8, kind_key=kind_key, id_mode=id_mode),
            "geometry": {"type": "Point", "coordinates": nr(0.0, 100.0)},
        },
        {
            "type": "Feature",
            "properties": _node_props(node_id=node_in, kind_value=4, kind_key=kind_key, id_mode=id_mode),
            "geometry": {"type": "Point", "coordinates": nr(0.0, -60.0)},
        },
        {
            "type": "Feature",
            "properties": _node_props(node_id=node_div_left, kind_value=4, kind_key=kind_key, id_mode=id_mode),
            "geometry": {"type": "Point", "coordinates": nr(-18.0, 40.0)},
        },
        {
            "type": "Feature",
            "properties": _node_props(node_id=node_div_right, kind_value=4, kind_key=kind_key, id_mode=id_mode),
            "geometry": {"type": "Point", "coordinates": nr(18.0, 42.0)},
        },
        {
            "type": "Feature",
            "properties": _node_props(node_id=node_merge_left, kind_value=4, kind_key=kind_key, id_mode=id_mode),
            "geometry": {"type": "Point", "coordinates": nr(-18.0, 58.0)},
        },
        {
            "type": "Feature",
            "properties": _node_props(node_id=node_merge_right, kind_value=4, kind_key=kind_key, id_mode=id_mode),
            "geometry": {"type": "Point", "coordinates": nr(18.0, 60.0)},
        },
        {
            "type": "Feature",
            "properties": _node_props(node_id=node_out, kind_value=4, kind_key=kind_key, id_mode=id_mode),
            "geometry": {"type": "Point", "coordinates": nr(0.0, 160.0)},
        },
    ]

    _write_json(global_dir / "RCSDNode.geojson", _fc(node_features, node_road_crs))

    road_features = [
        {
            "type": "Feature",
            "properties": {"snodeid": node_in, "enodeid": node_div, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [nr(0.0, -60.0), nr(0.0, 0.0)]},
        },
        {
            "type": "Feature",
            "properties": {"snodeid": node_div, "enodeid": node_div_left, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [nr(0.0, 0.0), nr(-18.0, 40.0)]},
        },
        {
            "type": "Feature",
            "properties": {"snodeid": node_div, "enodeid": node_div_right, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [nr(0.0, 0.0), nr(18.0, 42.0)]},
        },
        {
            "type": "Feature",
            "properties": {"snodeid": node_merge_left, "enodeid": node_merge, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [nr(-18.0, 58.0), nr(0.0, 100.0)]},
        },
        {
            "type": "Feature",
            "properties": {"snodeid": node_merge_right, "enodeid": node_merge, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [nr(18.0, 60.0), nr(0.0, 100.0)]},
        },
        {
            "type": "Feature",
            "properties": {"snodeid": node_merge, "enodeid": node_out, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [nr(0.0, 100.0), nr(0.0, 160.0)]},
        },
    ]
    _write_json(global_dir / "RCSDRoad.geojson", _fc(road_features, node_road_crs))

    divstrip_features = [
        {
            "type": "Feature",
            "properties": {"name": "diverge_zone"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[dv(-2.0, 12.0), dv(2.0, 12.0), dv(2.0, 18.0), dv(-2.0, 18.0), dv(-2.0, 12.0)]],
            },
        },
        {
            "type": "Feature",
            "properties": {"name": "merge_zone"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[dv(-2.0, 82.0), dv(2.0, 82.0), dv(2.0, 88.0), dv(-2.0, 88.0), dv(-2.0, 82.0)]],
            },
        },
    ]
    _write_json(patch_dir / "Vector" / "DivStripZone.geojson", _fc(divstrip_features, divstrip_crs))

    drivezone_features = [
        {
            "type": "Feature",
            "properties": {"name": "drivezone_left"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[dz(-30.0, -80.0), dz(-4.0, -80.0), dz(-4.0, 180.0), dz(-30.0, 180.0), dz(-30.0, -80.0)]],
            },
        },
        {
            "type": "Feature",
            "properties": {"name": "drivezone_right"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[dz(4.0, -80.0), dz(30.0, -80.0), dz(30.0, 180.0), dz(4.0, 180.0), dz(4.0, -80.0)]],
            },
        },
    ]
    _write_json(patch_dir / "Vector" / "DriveZone.geojson", _fc(drivezone_features, drivezone_crs))

    pc_features: list[dict[str, Any]] = []
    for dx in [8.0, 9.0, 10.0, 11.0, 12.0]:
        pc_features.append(
            {
                "type": "Feature",
                "properties": {"classification": 1},
                "geometry": {"type": "Point", "coordinates": pc(dx, 12.0)},
            }
        )
    for dx in [8.0, 9.0, 10.0, 11.0, 12.0]:
        pc_features.append(
            {
                "type": "Feature",
                "properties": {"classification": 1},
                "geometry": {"type": "Point", "coordinates": pc(dx, 88.0)},
            }
        )

    for dy in [12.0, 88.0]:
        for dx in [-0.5, 0.0, 0.5]:
            pc_features.append(
                {
                    "type": "Feature",
                    "properties": {"classification": 1},
                    "geometry": {"type": "Point", "coordinates": pc(dx, dy)},
                }
            )

    for dy in [12.0, 88.0]:
        pc_features.append(
            {
                "type": "Feature",
                "properties": {"classification": 12},
                "geometry": {"type": "Point", "coordinates": pc(10.0, dy)},
            }
        )

    for y in [-40.0, 0.0, 40.0, 80.0, 120.0, 160.0]:
        pc_features.append(
            {
                "type": "Feature",
                "properties": {"classification": 2},
                "geometry": {"type": "Point", "coordinates": pc(-20.0, y)},
            }
        )

    _write_json(patch_dir / "PointCloud" / "merged.geojson", _fc(pc_features, pointcloud_crs))

    traj_features: list[dict[str, Any]] = []
    for i in range(-60, 181, 5):
        xy = tr(0.0, float(i))
        traj_features.append(
            {
                "type": "Feature",
                "properties": {"seq": i + 1000},
                "geometry": {"type": "Point", "coordinates": [xy[0], xy[1], 0.0]},
            }
        )

    _write_json(patch_dir / "Traj" / "0001" / "raw_dat_pose.geojson", _fc(traj_features, traj_crs))

    matched_field = "id" if id_mode == "id" else "mainnodeid"
    return {
        "patch_dir": patch_dir,
        "global_node_path": global_dir / "RCSDNode.geojson",
        "global_road_path": global_dir / "RCSDRoad.geojson",
        "divstrip_path": patch_dir / "Vector" / "DivStripZone.geojson",
        "drivezone_path": patch_dir / "Vector" / "DriveZone.geojson",
        "pointcloud_path": patch_dir / "PointCloud" / "merged.geojson",
        "traj_glob": str((patch_dir / "Traj" / "*" / "raw_dat_pose.geojson").as_posix()),
        "focus_node_ids": [str(node_div), str(node_merge)],
        "node_diverge": int(node_div),
        "node_merge": int(node_merge),
        "expected_matched_field": matched_field,
        "node_src_crs": "auto",
        "road_src_crs": "auto",
        "divstrip_src_crs": "auto",
        "drivezone_src_crs": "auto",
        "traj_src_crs": "auto",
        "pointcloud_crs": pointcloud_crs,
        "dst_crs": "EPSG:3857",
    }
