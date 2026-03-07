from __future__ import annotations

import json
from pathlib import Path

import pytest

from highway_topo_poc.modules.t05_topology_between_rc import export_traj_lines as export_mod
from highway_topo_poc.modules.t05_topology_between_rc.io import InputDataError, load_patch_trajectory_lines


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


def _build_patch(tmp_path: Path, *, patch_id: str) -> Path:
    patch_dir = tmp_path / patch_id
    vector_dir = patch_dir / "Vector"
    traj_dir = patch_dir / "Traj"
    vector_dir.mkdir(parents=True, exist_ok=True)
    (traj_dir / "0001").mkdir(parents=True, exist_ok=True)
    (traj_dir / "0002").mkdir(parents=True, exist_ok=True)

    _write_fc(
        vector_dir / "intersection_l.geojson",
        crs="EPSG:3857",
        features=[
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[940_000.0, 6_275_000.0], [940_000.0, 6_275_080.0]],
                },
                "properties": {"nodeid": 100},
            }
        ],
    )
    _write_fc(
        traj_dir / "0001" / "raw_dat_pose.geojson",
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
    _write_fc(
        traj_dir / "0002" / "raw_dat_pose.geojson",
        crs="EPSG:3857",
        features=[
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [939_950.0, 6_275_050.0, 0.0]},
                "properties": {"seq": 10},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [940_120.0, 6_275_090.0, 0.0]},
                "properties": {"seq": 11},
            },
        ],
    )
    return patch_dir


def test_load_patch_trajectory_lines_requires_patch_id(tmp_path: Path) -> None:
    patch_dir = _build_patch(tmp_path, patch_id="p_need_patch_id")
    with pytest.raises(InputDataError, match="patch_id_required"):
        load_patch_trajectory_lines(patch_dir.parent, patch_id=None)


def test_load_patch_trajectory_lines_builds_lines(tmp_path: Path) -> None:
    patch_dir = _build_patch(tmp_path, patch_id="p_lines")
    crs_name, lines, props = load_patch_trajectory_lines(patch_dir.parent, patch_id=patch_dir.name, out_crs="patch")

    assert crs_name == "EPSG:3857"
    assert len(lines) == 2
    assert len(props) == 2
    assert props[0]["patch_id"] == patch_dir.name
    assert props[0]["traj_id"] == "0001"
    assert props[0]["point_count"] == 2


def test_export_traj_lines_cli_writes_geojson_and_summary(tmp_path: Path) -> None:
    patch_dir = _build_patch(tmp_path, patch_id="p_cli")
    out_path = tmp_path / "traj_lines.geojson"

    rc = export_mod.main(
        [
            "--data_root",
            str(patch_dir.parent),
            "--patch_id",
            patch_dir.name,
            "--out",
            str(out_path),
            "--out_crs",
            "patch",
        ]
    )

    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    summary = json.loads(out_path.with_suffix(".summary.json").read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 2
    assert summary["trajectory_count"] == 2
    assert summary["patch_id"] == patch_dir.name
