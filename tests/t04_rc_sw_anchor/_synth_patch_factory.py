from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_synth_patch(root: Path) -> Path:
    patch_dir = root / "patch_synth_t04"
    (patch_dir / "Vector").mkdir(parents=True, exist_ok=True)
    (patch_dir / "PointCloud").mkdir(parents=True, exist_ok=True)

    node_features = [
        {
            "type": "Feature",
            "properties": {"mainid": 1001, "id": 1001, "Kind": 16},
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
        },
        {
            "type": "Feature",
            "properties": {"mainid": 1002, "id": 1002, "Kind": 8},
            "geometry": {"type": "Point", "coordinates": [0.0, 100.0]},
        },
        {
            "type": "Feature",
            "properties": {"mainid": 2001, "id": 2001, "Kind": 4},
            "geometry": {"type": "Point", "coordinates": [0.0, 30.0]},
        },
        {
            "type": "Feature",
            "properties": {"mainid": 2002, "id": 2002, "Kind": 4},
            "geometry": {"type": "Point", "coordinates": [0.0, 70.0]},
        },
    ]

    _write_json(
        patch_dir / "Vector" / "Node.geojson",
        {
            "type": "FeatureCollection",
            "features": node_features,
        },
    )

    inter_features = [
        {
            "type": "Feature",
            "properties": {"nodeid": 1001},
            "geometry": {"type": "LineString", "coordinates": [[-20.0, 0.0], [20.0, 0.0]]},
        },
        {
            "type": "Feature",
            "properties": {"nodeid": 1002},
            "geometry": {"type": "LineString", "coordinates": [[-20.0, 100.0], [20.0, 100.0]]},
        },
    ]

    _write_json(
        patch_dir / "Vector" / "intersection_l.geojson",
        {
            "type": "FeatureCollection",
            "features": inter_features,
        },
    )

    road_features = [
        {
            "type": "Feature",
            "properties": {"snodeid": 3000, "enodeid": 1001, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [[0.0, -50.0], [0.0, 0.0]]},
        },
        {
            "type": "Feature",
            "properties": {"snodeid": 1001, "enodeid": 2001, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [0.0, 30.0]]},
        },
        {
            "type": "Feature",
            "properties": {"snodeid": 1002, "enodeid": 4000, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [[0.0, 100.0], [0.0, 150.0]]},
        },
        {
            "type": "Feature",
            "properties": {"snodeid": 2002, "enodeid": 1002, "direction": 2},
            "geometry": {"type": "LineString", "coordinates": [[0.0, 70.0], [0.0, 100.0]]},
        },
    ]

    _write_json(
        patch_dir / "Vector" / "Road.geojson",
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

    # non-ground cluster for diverge trigger near y=12
    for dx in [1.5, 1.8, 2.0, 2.2, 2.5, 2.7, 3.0]:
        pc_features.append(
            {
                "type": "Feature",
                "properties": {"classification": 1},
                "geometry": {"type": "Point", "coordinates": [dx, 12.0]},
            }
        )

    # non-ground cluster for merge trigger near y=88
    for dx in [1.5, 1.8, 2.0, 2.2, 2.5, 2.7, 3.0]:
        pc_features.append(
            {
                "type": "Feature",
                "properties": {"classification": 1},
                "geometry": {"type": "Point", "coordinates": [dx, 88.0]},
            }
        )

    # optional ground points
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

    return patch_dir
