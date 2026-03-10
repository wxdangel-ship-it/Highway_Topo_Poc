from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from highway_topo_poc.modules.t10_complex_intersection_modeling import (
    check_t10_baseline_manifest_payload,
    load_t10_baseline_manifest,
    run_t10_baseline_regression_smoke,
    run_t10_review_cycle_from_patch_dir,
    run_t10_review_cycle_from_patch_root,
)


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
) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[float(x), float(y)] for x, y in coords]},
        "properties": {
            "road_id": road_id,
            "snodeid": int(snodeid),
            "enodeid": int(enodeid),
            "direction": int(direction),
        },
    }


def _feature_collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def _write_geojson(path: Path, features: list[dict]) -> Path:
    path.write_text(json.dumps(_feature_collection(features), ensure_ascii=False, indent=2), encoding="utf-8")
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


def _service_patch(path: Path, *, mainid: int = 100) -> Path:
    return _write_patch_dir(
        path,
        node_features=[
            _node(1, 0.0, -1.0, mainid=mainid),
            _node(2, 2.0, -1.0, mainid=mainid),
            _node(3, 0.0, 1.0, mainid=mainid),
            _node(4, 2.0, 1.0, mainid=mainid),
            _node(5, -1.0, 0.0, mainid=mainid),
            _node(6, 3.0, 0.0, mainid=mainid),
        ],
        road_features=[
            _road("south_service", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("south_main", [(2.0, -1.0), (2.0, -10.0)], snodeid=2, enodeid=102),
            _road("north_service", [(0.0, 1.0), (0.0, 10.0)], snodeid=3, enodeid=103),
            _road("north_main", [(2.0, 1.0), (2.0, 10.0)], snodeid=4, enodeid=104),
            _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=5, enodeid=105),
            _road("east", [(3.0, 0.0), (10.0, 0.0)], snodeid=6, enodeid=106),
        ],
    )


def test_phase11_single_patch_review_cycle_runs_base_rerun_and_diff(tmp_path: Path) -> None:
    patch_dir = _service_patch(tmp_path / "patch_dir")
    override_path = tmp_path / "manual_override.json"
    override_path.write_text(
        json.dumps(
            {
                "service_profile_map": {"south_service": "left_uturn_service"},
                "paired_mainline_map": {"south_service": "south_main"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "cycle_out"

    result = run_t10_review_cycle_from_patch_dir(
        patch_dir=patch_dir,
        manual_override_source=override_path,
        output_dir=output_dir,
        validate_override=True,
    )

    assert result.base_output_dir == str(output_dir / "base")
    assert result.rerun_output_dir == str(output_dir / "rerun")
    assert result.diff_output_dir == str(output_dir / "diff")
    assert (output_dir / "base" / "approach_catalog.json").exists()
    assert (output_dir / "rerun" / "override_roundtrip.json").exists()
    assert (output_dir / "diff" / "run_diff.json").exists()
    assert (output_dir / "manifest.json").exists()
    assert result.diff_payload is not None
    assert result.diff_payload["movement_status_change_count"] >= 1


def test_phase11_patch_root_review_cycle_runs_per_patch_and_keeps_errors_visible(tmp_path: Path) -> None:
    patch_root = tmp_path / "patch_root"
    override_root = tmp_path / "override_root"
    override_root.mkdir(parents=True, exist_ok=True)
    _service_patch(patch_root / "patch_ok")
    (override_root / "patch_ok.json").write_text(
        json.dumps(
            {
                "service_profile_map": {"south_service": "left_uturn_service"},
                "paired_mainline_map": {"south_service": "south_main"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    broken_vector = patch_root / "patch_broken" / "Vector"
    broken_vector.mkdir(parents=True, exist_ok=True)
    _write_geojson(broken_vector / "RCSDNode.geojson", [_node(11, 20.0, -1.0, mainid=200)])

    output_root = tmp_path / "cycle_root_out"
    result = run_t10_review_cycle_from_patch_root(
        patch_root=patch_root,
        override_root=override_root,
        output_root=output_root,
        validate_override=True,
    )
    status_map = {item.patch_name: item for item in result.items}
    assert status_map["patch_ok"].status == "success"
    assert status_map["patch_broken"].status == "error"
    assert (output_root / "patch_ok" / "base" / "manifest.json").exists()
    assert (output_root / "patch_ok" / "rerun" / "manifest.json").exists()
    assert (output_root / "patch_ok" / "diff" / "manifest.json").exists()
    assert (output_root / "patch_broken" / "error.txt").exists()
    assert (output_root / "manifest.json").exists()


def test_phase11_baseline_manifest_and_regression_entry_are_stable(tmp_path: Path) -> None:
    manifest = load_t10_baseline_manifest()
    summary = check_t10_baseline_manifest_payload(manifest)
    assert manifest["baseline_name"] == "T10_phase11_manual_review_cycle_release_candidate"
    assert summary["snapshot_case_count"] == 3

    regression = run_t10_baseline_regression_smoke(output_root=tmp_path / "regression")
    assert regression["case_count"] == 3
    assert (tmp_path / "regression" / "regression_manifest.json").exists()
    assert (tmp_path / "regression" / "regression_summary.txt").exists()


def test_phase11_cli_patch_dir_review_cycle_smoke(tmp_path: Path) -> None:
    patch_dir = _service_patch(tmp_path / "patch_dir")
    override_path = tmp_path / "manual_override.json"
    override_path.write_text(
        json.dumps(
            {
                "service_profile_map": {"south_service": "left_uturn_service"},
                "paired_mainline_map": {"south_service": "south_main"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "cli_cycle_out"

    proc = _run_cli(
        "--patch-dir",
        str(patch_dir),
        "--manual-override",
        str(override_path),
        "--output-dir",
        str(output_dir),
        "--review-cycle",
        "--validate-override",
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "single_intersection"
    assert payload["has_diff"] is True
    assert (output_dir / "base" / "serialized_bundle.json").exists()
    assert (output_dir / "rerun" / "override_roundtrip.json").exists()
    assert (output_dir / "diff" / "run_diff.json").exists()


def test_phase11_cli_regression_smoke_runs(tmp_path: Path) -> None:
    proc = _run_cli(
        "--run-regression-smoke",
        "--output-dir",
        str(tmp_path / "regression_out"),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "baseline_regression_smoke"
    assert payload["case_count"] == 3
    assert (tmp_path / "regression_out" / "regression_manifest.json").exists()
