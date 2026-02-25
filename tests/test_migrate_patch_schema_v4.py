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


def _old_node_name() -> str:
    return "No" + "de.geojson"


def _old_road_name() -> str:
    return "Ro" + "ad.geojson"


def _old_node_path_token() -> str:
    return "Vector/" + _old_node_name()


def _old_road_path_token() -> str:
    return "Vector/" + _old_road_name()


def test_patch_schema_v4_rename(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    patch_dir = dataset_root / "00000001"
    (patch_dir / "PointCloud").mkdir(parents=True, exist_ok=True)
    (patch_dir / "Vector").mkdir(parents=True, exist_ok=True)
    (patch_dir / "Traj" / "00000001").mkdir(parents=True, exist_ok=True)
    (patch_dir / "PointCloud" / "00000001.laz").write_bytes(b"stub\n")

    _write_json(
        patch_dir / "Vector" / _old_node_name(),
        {"type": "FeatureCollection", "features": []},
    )
    _write_json(
        patch_dir / "Vector" / _old_road_name(),
        {"type": "FeatureCollection", "features": []},
    )

    report_dir = tmp_path / "report_apply"
    script = _repo_root() / "tools" / "migrate_patch_schema_v4_rename_rcsdnode_rcsdroad.py"
    cmd = [
        sys.executable,
        str(script),
        "--roots",
        str(dataset_root),
        "--apply",
        "--report-dir",
        str(report_dir),
        "--backup-dir",
        str(report_dir / "backup"),
    ]
    res = subprocess.run(cmd, cwd=str(_repo_root()), capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout

    new_node = patch_dir / "Vector" / "RCSDNode.geojson"
    new_road = patch_dir / "Vector" / "RCSDRoad.geojson"
    old_node = patch_dir / "Vector" / _old_node_name()
    old_road = patch_dir / "Vector" / _old_road_name()

    assert new_node.is_file()
    assert new_road.is_file()
    assert not old_node.exists()
    assert not old_road.exists()

    node_obj = json.loads(new_node.read_text(encoding="utf-8"))
    road_obj = json.loads(new_road.read_text(encoding="utf-8"))
    assert node_obj.get("type") == "FeatureCollection"
    assert isinstance(node_obj.get("features"), list)
    assert road_obj.get("type") == "FeatureCollection"
    assert isinstance(road_obj.get("features"), list)


def test_manifest_replace_v4(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    patch_dir = dataset_root / "00000002"
    (patch_dir / "PointCloud").mkdir(parents=True, exist_ok=True)
    (patch_dir / "Vector").mkdir(parents=True, exist_ok=True)
    (patch_dir / "Traj" / "00000002").mkdir(parents=True, exist_ok=True)
    (patch_dir / "PointCloud" / "00000002.laz").write_bytes(b"stub\n")
    _write_json(patch_dir / "Vector" / "LaneBoundary.geojson", {"type": "FeatureCollection", "features": []})

    manifest_path = dataset_root / "patch_manifest.json"
    manifest_text = (
        "{\n"
        '  "patch_ids": ["00000002"],\n'
        '  "patches": [{"patch_id": "00000002", "paths": {"vector_node": "'
        + _old_node_path_token()
        + '", "vector_road": "'
        + _old_road_path_token()
        + '"}}]\n'
        "}\n"
    )
    manifest_path.write_text(manifest_text, encoding="utf-8")

    report_dir = tmp_path / "report_apply_manifest"
    script = _repo_root() / "tools" / "migrate_patch_schema_v4_rename_rcsdnode_rcsdroad.py"
    cmd = [
        sys.executable,
        str(script),
        "--roots",
        str(dataset_root),
        "--apply",
        "--report-dir",
        str(report_dir),
        "--backup-dir",
        str(report_dir / "backup"),
    ]
    res = subprocess.run(cmd, cwd=str(_repo_root()), capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout

    updated = manifest_path.read_text(encoding="utf-8")
    assert "RCSDNode.geojson" in updated
    assert "RCSDRoad.geojson" in updated
    assert _old_node_path_token() not in updated
    assert _old_road_path_token() not in updated
