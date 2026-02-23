from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_patch_schema_v3_minimal(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    patch_dir = dataset_root / "00000001"

    (patch_dir / "PointCloud").mkdir(parents=True, exist_ok=True)
    (patch_dir / "Vector").mkdir(parents=True, exist_ok=True)
    (patch_dir / "Traj" / "00000001").mkdir(parents=True, exist_ok=True)

    (patch_dir / "PointCloud" / "00000001.laz").write_bytes(b"stub\n")

    _write_json(
        patch_dir / "Vector" / "LaneBoundary.geojson",
        {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:32632"}},
            "features": [],
        },
    )
    _write_json(
        patch_dir / "Traj" / "00000001" / "raw_dat_pose.geojson",
        {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:32632"}},
            "features": [],
        },
    )

    report_dir = tmp_path / "report_apply"
    script = _repo_root() / "tools" / "migrate_patch_schema_v3_add_road_tiles.py"

    cmd_apply = [
        sys.executable,
        str(script),
        "--roots",
        str(dataset_root),
        "--apply",
        "--report-dir",
        str(report_dir),
        "--backup-dir",
        str(report_dir / "backup"),
        "--tiles-mode",
        "mkdir_empty",
    ]
    res_apply = subprocess.run(cmd_apply, cwd=str(_repo_root()), capture_output=True, text=True)
    assert res_apply.returncode == 0, res_apply.stderr or res_apply.stdout

    road = patch_dir / "Vector" / "Road.geojson"
    tiles = patch_dir / "Tiles"
    assert road.is_file()
    assert tiles.is_dir()

    road_obj = json.loads(road.read_text(encoding="utf-8"))
    assert road_obj.get("type") == "FeatureCollection"
    assert isinstance(road_obj.get("features"), list)
    assert road_obj.get("crs", {}).get("properties", {}).get("name") == "EPSG:32632"

    report_dir_dry = tmp_path / "report_dry"
    cmd_dry = [
        sys.executable,
        str(script),
        "--roots",
        str(dataset_root),
        "--report-dir",
        str(report_dir_dry),
        "--backup-dir",
        str(report_dir_dry / "backup"),
    ]
    res_dry = subprocess.run(cmd_dry, cwd=str(_repo_root()), capture_output=True, text=True)
    assert res_dry.returncode == 0, res_dry.stderr or res_dry.stdout

    report_json = report_dir_dry / "migration_report.json"
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert payload.get("patches_to_modify") == 0
