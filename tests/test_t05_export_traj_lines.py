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
                "geometry": {"type": "Point", "coordinates": [939_999.0, 6_275_010.0, 0.0]},
                "properties": {"seq": 0},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [940_001.0, 6_275_015.0, 0.0]},
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
                "geometry": {"type": "Point", "coordinates": [939_998.0, 6_275_050.0, 0.0]},
                "properties": {"seq": 10},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [940_002.0, 6_275_055.0, 0.0]},
                "properties": {"seq": 11},
            },
        ],
    )
    return patch_dir


def _build_split_patch(tmp_path: Path, *, patch_id: str, features: list[dict]) -> Path:
    patch_dir = tmp_path / patch_id
    vector_dir = patch_dir / "Vector"
    traj_dir = patch_dir / "Traj"
    vector_dir.mkdir(parents=True, exist_ok=True)
    (traj_dir / "0001").mkdir(parents=True, exist_ok=True)

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
        features=features,
    )
    return patch_dir


def test_load_patch_trajectory_lines_requires_patch_id(tmp_path: Path) -> None:
    patch_dir = _build_patch(tmp_path, patch_id="p_need_patch_id")
    with pytest.raises(InputDataError, match="patch_id_required"):
        load_patch_trajectory_lines(patch_dir.parent, patch_id=None)


def test_load_patch_trajectory_lines_builds_lines(tmp_path: Path) -> None:
    patch_dir = _build_patch(tmp_path, patch_id="p_lines")
    crs_name, lines, props, summary = load_patch_trajectory_lines(
        patch_dir.parent,
        patch_id=patch_dir.name,
        out_crs="patch",
    )

    assert crs_name == "EPSG:3857"
    assert len(lines) == 2
    assert len(props) == 2
    assert props[0]["patch_id"] == patch_dir.name
    assert props[0]["traj_id"] == "0001__seg0001"
    assert props[0]["source_traj_id"] == "0001"
    assert props[0]["segment_index"] == 1
    assert props[0]["point_count"] == 2
    assert summary["trajectory_count"] == 2
    assert summary["traj_source_count"] == 2
    assert summary["traj_segment_count"] == 2
    assert summary["traj_split_source_count"] == 0


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


def test_load_patch_trajectory_lines_splits_on_distance_gap(tmp_path: Path) -> None:
    patch_dir = _build_split_patch(
        tmp_path,
        patch_id="p_split_distance",
        features=[
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [940_000.0, 6_275_000.0, 0.0]},
                "properties": {"seq": 0},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [940_005.0, 6_275_000.0, 0.0]},
                "properties": {"seq": 1},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [940_100.0, 6_275_000.0, 0.0]},
                "properties": {"seq": 2},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [940_105.0, 6_275_000.0, 0.0]},
                "properties": {"seq": 3},
            },
        ],
    )

    _, lines, props, summary = load_patch_trajectory_lines(
        patch_dir.parent,
        patch_id=patch_dir.name,
        traj_split_max_gap_m=20.0,
        traj_split_max_time_gap_s=999.0,
        traj_split_max_seq_gap=99,
    )

    assert len(lines) == 2
    assert [p["traj_id"] for p in props] == ["0001__seg0001", "0001__seg0002"]
    assert [p["segment_index"] for p in props] == [1, 2]
    assert all(p["source_traj_id"] == "0001" for p in props)
    assert summary["traj_source_count"] == 1
    assert summary["traj_segment_count"] == 2
    assert summary["traj_split_source_count"] == 1
    assert summary["traj_split_by_distance_count"] == 1
    assert summary["traj_split_by_time_count"] == 0


def test_load_patch_trajectory_lines_splits_on_numeric_time_stamp_gap(tmp_path: Path) -> None:
    patch_dir = _build_split_patch(
        tmp_path,
        patch_id="p_split_time",
        features=[
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [940_000.0, 6_275_000.0, 0.0]},
                "properties": {"seq": 0, "time_stamp": 1770887869.072541},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [940_001.0, 6_275_000.0, 0.0]},
                "properties": {"seq": 1, "time_stamp": 1770887869.272541},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [940_002.0, 6_275_000.0, 0.0]},
                "properties": {"seq": 2, "time_stamp": 1770887874.872541},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [940_003.0, 6_275_000.0, 0.0]},
                "properties": {"seq": 3, "time_stamp": 1770887875.072541},
            },
        ],
    )

    _, lines, props, summary = load_patch_trajectory_lines(
        patch_dir.parent,
        patch_id=patch_dir.name,
        traj_split_max_gap_m=1000.0,
        traj_split_max_time_gap_s=2.0,
        traj_split_max_seq_gap=99,
    )

    assert len(lines) == 2
    assert [p["traj_id"] for p in props] == ["0001__seg0001", "0001__seg0002"]
    assert props[0]["ts_min"] == pytest.approx(1770887869.072541)
    assert props[1]["ts_max"] == pytest.approx(1770887875.072541)
    assert summary["traj_split_by_distance_count"] == 0
    assert summary["traj_split_by_time_count"] == 1
