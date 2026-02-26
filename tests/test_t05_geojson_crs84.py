from __future__ import annotations

import json
from pathlib import Path

import pytest

from highway_topo_poc.modules.t05_topology_between_rc.io import (
    InputDataError,
    load_patch_inputs,
    normalize_geojson_crs_name,
)


def _fc(features: list[dict], crs_name: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": features,
        "crs": {"type": "name", "properties": {"name": crs_name}},
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _make_patch(tmp_path: Path, *, lane_crs: str) -> Path:
    patch_id = "2855795596723843"
    patch_dir = tmp_path / patch_id
    vector = patch_dir / "Vector"
    traj = patch_dir / "Traj" / "0001"
    pointcloud = patch_dir / "PointCloud"
    vector.mkdir(parents=True, exist_ok=True)
    traj.mkdir(parents=True, exist_ok=True)
    pointcloud.mkdir(parents=True, exist_ok=True)

    inter = _fc(
        [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[8.44, 49.01], [8.44, 49.02]]},
                "properties": {"nodeid": 100},
            }
        ],
        "urn:ogc:def:crs:OGC:1.3:CRS84",
    )
    lane = _fc(
        [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[8.44, 49.01], [8.45, 49.02]]},
                "properties": {},
            }
        ],
        lane_crs,
    )
    traj_fc = _fc(
        [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [8.4399, 49.0101, 110.0]},
                "properties": {"seq": 0},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [8.4401, 49.0109, 110.1]},
                "properties": {"seq": 1},
            },
        ],
        "OGC:1.3:CRS84",
    )

    _write_json(vector / "intersection_l.geojson", inter)
    _write_json(vector / "LaneBoundary.geojson", lane)
    _write_json(traj / "raw_dat_pose.geojson", traj_fc)
    return patch_dir


def test_crs84_is_accepted_and_normalized_to_epsg4326(tmp_path: Path) -> None:
    patch_dir = _make_patch(tmp_path, lane_crs="urn:ogc:def:crs:OGC:1.3:CRS84")
    data_root = patch_dir.parent
    patch = load_patch_inputs(data_root, patch_id=patch_dir.name)

    assert patch.projection.input_crs == "EPSG:4326"
    assert patch.projection.metric_crs == "EPSG:3857"
    assert patch.intersection_lines

    x0, y0 = patch.intersection_lines[0].geometry_metric.coords[0]
    assert abs(float(x0)) > 1000.0
    assert abs(float(y0)) > 1000.0

    assert normalize_geojson_crs_name("CRS84") == "EPSG:4326"
    assert normalize_geojson_crs_name("OGC:1.3:CRS84") == "EPSG:4326"
    assert normalize_geojson_crs_name("urn:ogc:def:crs:OGC:1.3:CRS84") == "EPSG:4326"


def test_invalid_crs_still_rejected(tmp_path: Path) -> None:
    patch_dir = _make_patch(tmp_path, lane_crs="urn:ogc:def:crs:OGC:1.3:CRS83")
    data_root = patch_dir.parent

    with pytest.raises(InputDataError, match="geojson_crs_invalid"):
        load_patch_inputs(data_root, patch_id=patch_dir.name)
