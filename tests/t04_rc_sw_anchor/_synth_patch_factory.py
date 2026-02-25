from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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


def create_synth_patch(
    root: Path,
    *,
    kind_key: str = "Kind",
    id_mode: str = "id",
) -> dict[str, Any]:
    patch_id = "2855795596723843"
    node_a = 5278670377721456
    node_b = 5278670377721468

    patch_dir = root / patch_id
    (patch_dir / "Vector").mkdir(parents=True, exist_ok=True)
    (patch_dir / "PointCloud").mkdir(parents=True, exist_ok=True)
    (patch_dir / "Traj" / "0001").mkdir(parents=True, exist_ok=True)

    global_dir = root / "global"
    global_dir.mkdir(parents=True, exist_ok=True)

    node_features = [
        {
            "type": "Feature",
            "properties": _node_props(node_id=node_a, kind_value=16, kind_key=kind_key, id_mode=id_mode),
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
        },
        {
            "type": "Feature",
            "properties": _node_props(node_id=node_b, kind_value=8, kind_key=kind_key, id_mode=id_mode),
            "geometry": {"type": "Point", "coordinates": [0.0, 100.0]},
        },
        {
            "type": "Feature",
            "properties": _node_props(node_id=9001, kind_value=4, kind_key=kind_key, id_mode=id_mode),
            "geometry": {"type": "Point", "coordinates": [0.0, 40.0]},
        },
        {
            "type": "Feature",
            "properties": _node_props(node_id=9002, kind_value=4, kind_key=kind_key, id_mode=id_mode),
            "geometry": {"type": "Point", "coordinates": [0.0, 60.0]},
        },
    ]

    _write_json(
        global_dir / "RCSDNode.geojson",
        {
            "type": "FeatureCollection",
            "features": node_features,
        },
    )

    road_features = [
        {
            "type": "Feature",
            "properties": {"snodeid": 8000, "enodeid": node_a, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [[0.0, -50.0], [0.0, 0.0]]},
        },
        {
            "type": "Feature",
            "properties": {"snodeid": node_a, "enodeid": 9001, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [0.0, 40.0]]},
        },
        {
            "type": "Feature",
            "properties": {"snodeid": node_b, "enodeid": 8001, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [[0.0, 100.0], [0.0, 150.0]]},
        },
        {
            "type": "Feature",
            "properties": {"snodeid": 9002, "enodeid": node_b, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [[0.0, 60.0], [0.0, 100.0]]},
        },
    ]

    _write_json(
        global_dir / "RCSDRoad.geojson",
        {
            "type": "FeatureCollection",
            "features": road_features,
        },
    )

    divstrip_features = [
        {
            "type": "Feature",
            "properties": {"name": "diverge_zone"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0.0, 9.0], [5.0, 9.0], [5.0, 11.0], [0.0, 11.0], [0.0, 9.0]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"name": "merge_zone"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0.0, 89.0], [5.0, 89.0], [5.0, 91.0], [0.0, 91.0], [0.0, 89.0]]],
            },
        },
    ]

    _write_json(
        patch_dir / "Vector" / "DivStripZone.geojson",
        {
            "type": "FeatureCollection",
            "features": divstrip_features,
        },
    )

    pc_features: list[dict[str, Any]] = []
    for dx in [2.6, 2.8, 3.0, 3.2, 3.4, 3.6]:
        pc_features.append(
            {
                "type": "Feature",
                "properties": {"classification": 1},
                "geometry": {"type": "Point", "coordinates": [dx, 12.0]},
            }
        )
    for dx in [2.6, 2.8, 3.0, 3.2, 3.4, 3.6]:
        pc_features.append(
            {
                "type": "Feature",
                "properties": {"classification": 1},
                "geometry": {"type": "Point", "coordinates": [dx, 88.0]},
            }
        )

    for dy in [12.0, 88.0]:
        for dx in [0.0, 0.4, 0.8]:
            pc_features.append(
                {
                    "type": "Feature",
                    "properties": {"classification": 1},
                    "geometry": {"type": "Point", "coordinates": [dx, dy]},
                }
            )

    for dy in [12.0, 88.0]:
        pc_features.append(
            {
                "type": "Feature",
                "properties": {"classification": 12},
                "geometry": {"type": "Point", "coordinates": [3.0, dy]},
            }
        )

    for y in [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]:
        pc_features.append(
            {
                "type": "Feature",
                "properties": {"classification": 2},
                "geometry": {"type": "Point", "coordinates": [-5.0, y]},
            }
        )

    _write_json(
        patch_dir / "PointCloud" / "merged.geojson",
        {
            "type": "FeatureCollection",
            "features": pc_features,
        },
    )

    traj_features: list[dict[str, Any]] = []
    for i in range(-50, 151, 5):
        traj_features.append(
            {
                "type": "Feature",
                "properties": {"seq": i + 1000},
                "geometry": {"type": "Point", "coordinates": [0.0, float(i), 0.0]},
            }
        )

    _write_json(
        patch_dir / "Traj" / "0001" / "raw_dat_pose.geojson",
        {
            "type": "FeatureCollection",
            "features": traj_features,
        },
    )

    matched_field = "id" if id_mode == "id" else "mainnodeid"
    return {
        "patch_dir": patch_dir,
        "global_node_path": global_dir / "RCSDNode.geojson",
        "global_road_path": global_dir / "RCSDRoad.geojson",
        "divstrip_path": patch_dir / "Vector" / "DivStripZone.geojson",
        "pointcloud_path": patch_dir / "PointCloud" / "merged.geojson",
        "traj_glob": str((patch_dir / "Traj" / "*" / "raw_dat_pose.geojson").as_posix()),
        "focus_node_ids": [str(node_a), str(node_b)],
        "expected_matched_field": matched_field,
    }
