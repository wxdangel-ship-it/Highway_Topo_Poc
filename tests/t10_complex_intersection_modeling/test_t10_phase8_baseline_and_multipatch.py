from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from highway_topo_poc.modules.t10_complex_intersection_modeling import (
    compare_t10_output_dir_to_snapshot,
    run_t10_multi_patch_manual_mode,
    run_t10_single_intersection_manual_mode,
    write_t10_run_result,
)


_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "t10"
_SNAPSHOT_DIR = _FIXTURE_DIR / "snapshots"


def _node(node_id: int, x: float, y: float, *, mainid: int = 100, kind: int = 4) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float(x), float(y)]},
        "properties": {"id": int(node_id), "mainid": int(mainid), "Kind": int(kind)},
    }


def _road(
    road_id: str,
    coords: list[tuple[float, float]],
    *,
    snodeid: int,
    enodeid: int,
    direction: int = 1,
    extra_properties: dict | None = None,
) -> dict:
    properties = {
        "road_id": road_id,
        "snodeid": int(snodeid),
        "enodeid": int(enodeid),
        "direction": int(direction),
    }
    if extra_properties:
        properties.update(extra_properties)
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[float(x), float(y)] for x, y in coords]},
        "properties": properties,
    }


def _feature_collection(features: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": features,
    }


def _write_geojson(path: Path, features: list[dict]) -> Path:
    path.write_text(json.dumps(_feature_collection(features)), encoding="utf-8")
    return path


def _write_patch_dir(path: Path, *, node_features: list[dict], road_features: list[dict]) -> Path:
    vector_dir = path / "Vector"
    vector_dir.mkdir(parents=True, exist_ok=True)
    _write_geojson(vector_dir / "RCSDNode.geojson", node_features)
    _write_geojson(vector_dir / "RCSDRoad.geojson", road_features)
    return path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_dir = _repo_root() / "src"
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_dir) if not existing else str(src_dir) + os.pathsep + existing
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "highway_topo_poc.modules.t10_complex_intersection_modeling.cli",
            *args,
        ],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _snapshot_result(case_name: str):
    if case_name == "basic_two_arm":
        return run_t10_single_intersection_manual_mode(
            node_features=[
                _node(1, 0.0, -1.0),
                _node(2, 0.0, 1.0),
            ],
            road_features=[
                _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
                _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            ],
        )
    if case_name == "left_service_tri_arm":
        return run_t10_single_intersection_manual_mode(
            node_features=[
                _node(1, 0.0, -1.0),
                _node(2, 0.0, 1.0),
                _node(3, -1.0, 0.0),
            ],
            road_features=[
                _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
                _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
                _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
            ],
            manual_override_source={
                "service_profile_map": {"south": "left_uturn_service"},
                "paired_mainline_map": {},
            },
            approach_overrides={
                "north:exit": {"exit_leg_role": "core_standard_exit"},
                "south:exit": {"exit_leg_role": "core_standard_exit"},
                "west:exit": {"exit_leg_role": "core_standard_exit"},
            },
        )
    if case_name == "access_exit_boundary":
        return run_t10_single_intersection_manual_mode(
            node_features=[
                _node(1, 0.0, -1.0),
                _node(2, 1.0, 0.0),
            ],
            road_features=[
                _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
                _road("east_access", [(1.0, 0.0), (10.0, 0.0)], snodeid=2, enodeid=102),
            ],
            approach_overrides={
                "east_access:exit": {"exit_leg_role": "access_exit"},
            },
        )
    raise AssertionError(f"unknown snapshot case: {case_name}")


def test_snapshot_baseline_cases_match_current_outputs(tmp_path: Path) -> None:
    for case_name in ("basic_two_arm", "left_service_tri_arm", "access_exit_boundary"):
        output_dir = tmp_path / case_name
        write_t10_run_result(_snapshot_result(case_name), output_dir)
        summary = compare_t10_output_dir_to_snapshot(output_dir, _SNAPSHOT_DIR / case_name)
        assert summary["files_compared"] == [
            "serialized_bundle.json",
            "movement_results.json",
            "movement_matrix.json",
        ]


def test_snapshot_comparator_detects_key_regression(tmp_path: Path) -> None:
    output_dir = tmp_path / "basic_two_arm"
    write_t10_run_result(_snapshot_result("basic_two_arm"), output_dir)
    movement_results_path = output_dir / "movement_results.json"
    payload = json.loads(movement_results_path.read_text(encoding="utf-8"))
    payload[0].pop("status")
    movement_results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        compare_t10_output_dir_to_snapshot(output_dir, _SNAPSHOT_DIR / "basic_two_arm")
    except ValueError as exc:
        assert "snapshot_compare_key_mismatch:movement_results.json[0]" in str(exc)
    else:
        raise AssertionError("expected snapshot comparator mismatch to raise ValueError")


def test_multi_patch_manual_mode_runs_multiple_patches_with_per_patch_override(tmp_path: Path) -> None:
    patch_root = tmp_path / "patch_root"
    override_root = tmp_path / "override_root"
    output_root = tmp_path / "multi_patch_output"
    override_root.mkdir(parents=True, exist_ok=True)

    _write_patch_dir(
        patch_root / "patch_basic",
        node_features=[_node(1, 0.0, -1.0), _node(2, 0.0, 1.0)],
        road_features=[
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        ],
    )
    _write_patch_dir(
        patch_root / "patch_service",
        node_features=[
            _node(1, 0.0, -1.0),
            _node(2, 0.0, 1.0),
            _node(3, -1.0, 0.0),
        ],
        road_features=[
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
        ],
    )
    (override_root / "patch_service.json").write_text(
        json.dumps(
            {
                "service_profile_map": {"south": "left_uturn_service"},
                "paired_mainline_map": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = run_t10_multi_patch_manual_mode(
        patch_root=patch_root,
        manual_override_root=override_root,
        output_root=output_root,
    )
    status_map = {item.patch_name: item for item in result.items}
    assert sorted(result.patch_names) == ["patch_basic", "patch_service"]
    assert status_map["patch_basic"].status == "success"
    assert status_map["patch_service"].status == "success"
    service_bundle = status_map["patch_service"].patch_result.items[0].result.bundle
    south_entry = service_bundle.approach_index["intersection:100|south:entry"]
    assert south_entry.approach_profile == "left_uturn_service"
    assert south_entry.approach_profile_source == "manual_service_profile_map"
    assert (output_root / "patch_service" / "manifest.json").exists()
    assert (output_root / "manifest.json").exists()


def test_multi_patch_manual_mode_keeps_patch_error_visible(tmp_path: Path) -> None:
    patch_root = tmp_path / "patch_root"
    output_root = tmp_path / "multi_patch_output"

    _write_patch_dir(
        patch_root / "patch_ok",
        node_features=[_node(1, 0.0, -1.0), _node(2, 0.0, 1.0)],
        road_features=[
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        ],
    )
    broken_vector = patch_root / "patch_broken" / "Vector"
    broken_vector.mkdir(parents=True, exist_ok=True)
    _write_geojson(broken_vector / "RCSDNode.geojson", [_node(11, 20.0, -1.0, mainid=200)])

    result = run_t10_multi_patch_manual_mode(
        patch_root=patch_root,
        output_root=output_root,
    )
    status_map = {item.patch_name: item for item in result.items}
    assert status_map["patch_ok"].status == "success"
    assert status_map["patch_broken"].status == "error"
    assert "patch_dir_missing_required_files" in (status_map["patch_broken"].error or "")
    assert (output_root / "patch_broken" / "error.txt").exists()
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    assert sorted(item["patch_name"] for item in manifest["items"]) == ["patch_broken", "patch_ok"]


def test_cli_patch_root_mode_smoke(tmp_path: Path) -> None:
    patch_root = tmp_path / "patch_root"
    override_root = tmp_path / "override_root"
    output_root = tmp_path / "cli_multi_patch_output"
    override_root.mkdir(parents=True, exist_ok=True)

    _write_patch_dir(
        patch_root / "patch_cli_service",
        node_features=[
            _node(1, 0.0, -1.0),
            _node(2, 0.0, 1.0),
            _node(3, -1.0, 0.0),
        ],
        road_features=[
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
        ],
    )
    (override_root / "patch_cli_service.json").write_text(
        json.dumps(
            {
                "service_profile_map": {"south": "left_uturn_service"},
                "paired_mainline_map": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    proc = _run_cli(
        "--patch-root",
        str(patch_root),
        "--override-root",
        str(override_root),
        "--output-dir",
        str(output_root),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "multi_patch_batch"
    assert payload["patch_names"] == ["patch_cli_service"]
    assert (output_root / "manifest.json").exists()
