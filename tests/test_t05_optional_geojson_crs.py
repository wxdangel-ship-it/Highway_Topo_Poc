from __future__ import annotations

import json
from pathlib import Path

import pytest

from highway_topo_poc.modules.t05_topology_between_rc.io import InputDataError, load_patch_inputs
from highway_topo_poc.modules.t05_topology_between_rc.pipeline import run_patch


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_fc(path: Path, *, features: list[dict], crs: str | None) -> None:
    payload: dict[str, object] = {
        "type": "FeatureCollection",
        "features": list(features),
    }
    if crs is not None:
        payload["crs"] = {"type": "name", "properties": {"name": crs}}
    _write_json(path, payload)


def _build_patch(
    tmp_path: Path,
    *,
    patch_id: str,
    lane_payload: dict,
    write_drivezone: bool = True,
    drivezone_features: list[dict] | None = None,
) -> Path:
    patch_dir = tmp_path / patch_id
    vector = patch_dir / "Vector"
    traj = patch_dir / "Traj" / "0001"
    pointcloud = patch_dir / "PointCloud"
    vector.mkdir(parents=True, exist_ok=True)
    traj.mkdir(parents=True, exist_ok=True)
    pointcloud.mkdir(parents=True, exist_ok=True)

    _write_fc(
        vector / "intersection_l.geojson",
        crs="EPSG:3857",
        features=[
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[940_000.0, 6_275_000.0], [940_000.0, 6_275_080.0]]},
                "properties": {"nodeid": 100},
            }
        ],
    )
    _write_json(vector / "LaneBoundary.geojson", lane_payload)
    if write_drivezone:
        _write_fc(
            vector / "DriveZone.geojson",
            crs="EPSG:3857",
            features=(
                drivezone_features
                if drivezone_features is not None
                else [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [939_500.0, 6_274_500.0],
                                    [941_000.0, 6_274_500.0],
                                    [941_000.0, 6_276_000.0],
                                    [939_500.0, 6_276_000.0],
                                    [939_500.0, 6_274_500.0],
                                ]
                            ],
                        },
                        "properties": {},
                    }
                ]
            ),
        )
    _write_fc(
        traj / "raw_dat_pose.geojson",
        crs="EPSG:3857",
        features=[
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [939_900.0, 6_275_010.0, 0.0]},
                "properties": {"seq": 0},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [940_100.0, 6_275_030.0, 0.0]},
                "properties": {"seq": 1},
            },
        ],
    )
    return patch_dir


def test_optional_laneboundary_missing_crs_projected_inherit_drivezone(tmp_path: Path) -> None:
    lane_payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[10_000_000.0, 3_000_000.0], [10_000_040.0, 3_000_020.0]],
                },
                "properties": {},
            }
        ],
    }
    patch_dir = _build_patch(tmp_path, patch_id="p_inherit", lane_payload=lane_payload)
    loaded = load_patch_inputs(patch_dir.parent, patch_id=patch_dir.name)

    assert bool(loaded.input_summary.get("lane_boundary_used")) is True
    assert loaded.input_summary.get("lane_boundary_crs_method") == "inherit_drivezone"
    assert loaded.input_summary.get("lane_boundary_crs_name_final") == "EPSG:3857"
    assert loaded.lane_boundaries_metric


def test_optional_laneboundary_missing_crs_lonlat_reproject(tmp_path: Path) -> None:
    lane_payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[8.44, 49.01], [8.45, 49.02]]},
                "properties": {},
            }
        ],
    }
    patch_dir = _build_patch(tmp_path, patch_id="p_lonlat", lane_payload=lane_payload)
    loaded = load_patch_inputs(patch_dir.parent, patch_id=patch_dir.name)

    assert loaded.input_summary.get("lane_boundary_crs_method") == "coord_scale_crs84_reproject"
    assert bool(loaded.input_summary.get("lane_boundary_crs_inferred")) is True
    x0, y0 = loaded.lane_boundaries_metric[0].coords[0]
    assert abs(float(x0)) > 1000.0
    assert abs(float(y0)) > 1000.0


def test_optional_laneboundary_missing_crs_empty_skipped_and_pipeline_continues(tmp_path: Path) -> None:
    lane_payload = {
        "type": "FeatureCollection",
        "features": [],
    }
    patch_dir = _build_patch(tmp_path, patch_id="p_skip", lane_payload=lane_payload)
    loaded = load_patch_inputs(patch_dir.parent, patch_id=patch_dir.name)
    assert bool(loaded.input_summary.get("lane_boundary_used")) is False
    assert loaded.input_summary.get("lane_boundary_crs_method") == "skipped"
    assert str(loaded.input_summary.get("lane_boundary_skipped_reason") or "") != ""

    result = run_patch(
        data_root=patch_dir.parent,
        patch_id=patch_dir.name,
        run_id="unit_t05_optional_lane_skip",
        out_root=tmp_path / "out",
        params_override={"DEBUG_DUMP": 1},
    )
    metrics = json.loads((result.output_dir / "metrics.json").read_text(encoding="utf-8"))
    assert bool(metrics.get("lane_boundary_used")) is False
    assert metrics.get("lane_boundary_crs_method") == "skipped"
    assert str(metrics.get("lane_boundary_skipped_reason") or "") != ""
    assert (result.output_dir / "debug" / "lane_boundary_crs_fix.json").is_file()


@pytest.mark.parametrize(
    ("write_drivezone", "drivezone_features", "match"),
    [
        (False, None, "drivezone_missing"),
        (True, [], "drivezone_empty"),
    ],
)
def test_drivezone_missing_or_empty_still_hard_fail(
    tmp_path: Path,
    write_drivezone: bool,
    drivezone_features: list[dict] | None,
    match: str,
) -> None:
    lane_payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[8.44, 49.01], [8.45, 49.02]]},
                "properties": {},
            }
        ],
    }
    patch_dir = _build_patch(
        tmp_path,
        patch_id=f"p_drivezone_{match}",
        lane_payload=lane_payload,
        write_drivezone=bool(write_drivezone),
        drivezone_features=drivezone_features,
    )
    with pytest.raises(InputDataError, match=match):
        load_patch_inputs(patch_dir.parent, patch_id=patch_dir.name)
