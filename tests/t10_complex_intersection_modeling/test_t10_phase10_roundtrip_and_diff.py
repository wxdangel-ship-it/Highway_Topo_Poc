from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from highway_topo_poc.modules.t10_complex_intersection_modeling import (
    build_approach_catalog,
    build_manual_override_template,
    compare_t10_run_dirs,
    roundtrip_manual_override_source,
    run_t10_single_intersection_manual_mode,
    write_t10_review_bundle,
    write_t10_run_diff_outputs,
    write_t10_run_result,
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


def _base_service_pair_result(*, manual_override_source: dict | None = None):
    return run_t10_single_intersection_manual_mode(
        node_features=[
            _node(1, 0.0, -1.0),
            _node(2, 2.0, -1.0),
            _node(3, 0.0, 1.0),
            _node(4, 2.0, 1.0),
            _node(5, -1.0, 0.0),
            _node(6, 3.0, 0.0),
        ],
        road_features=[
            _road("south_service", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("south_main", [(2.0, -1.0), (2.0, -10.0)], snodeid=2, enodeid=102),
            _road("north_service", [(0.0, 1.0), (0.0, 10.0)], snodeid=3, enodeid=103),
            _road("north_main", [(2.0, 1.0), (2.0, 10.0)], snodeid=4, enodeid=104),
            _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=5, enodeid=105),
            _road("east", [(3.0, 0.0), (10.0, 0.0)], snodeid=6, enodeid=106),
        ],
        manual_override_source=manual_override_source,
        approach_overrides={
            "north_service:exit": {"exit_leg_role": "service_standard_exit"},
            "north_main:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
            "south_service:exit": {"exit_leg_role": "service_standard_exit"},
            "south_main:exit": {"exit_leg_role": "core_standard_exit"},
        },
    )


def test_phase10_override_template_metadata_and_roundtrip_normalization() -> None:
    result = _base_service_pair_result()
    template = build_manual_override_template(result)
    assert template["metadata"]["intersection_id"] == "intersection:100"
    assert template["metadata"]["mainid"] == 100
    assert template["metadata"]["generation_source"] == "t10_manual_override_template"
    assert template["metadata"]["approach_count"] == len(result.bundle.approaches)
    assert template["metadata"]["entry_approach_count"] == 6
    assert "preferred_entry_selectors" in template["selector_examples"]

    catalog = build_approach_catalog(result)
    report = roundtrip_manual_override_source(
        manual_override_source={
            "service_profile_map": {"south_service": "left_uturn_service"},
            "paired_mainline_map": {"south_service": "south_main"},
        },
        approach_catalog=catalog,
    )
    assert report["is_valid"] is True
    assert report["normalized_override"]["service_profile_map"] == {
        "intersection:100|south_service:entry": "left_uturn_service"
    }
    assert report["normalized_override"]["paired_mainline_map"] == {
        "intersection:100|south_service:entry": "intersection:100|south_main:entry"
    }


def test_phase10_override_roundtrip_reports_invalid_selector_and_profile() -> None:
    result = _base_service_pair_result()
    catalog = build_approach_catalog(result)
    report = roundtrip_manual_override_source(
        manual_override_source={
            "service_profile_map": {"missing_selector": "right_turn_service"},
            "paired_mainline_map": {"missing_selector": "south_main"},
        },
        approach_catalog=catalog,
    )
    assert report["is_valid"] is False
    assert "override_roundtrip_unsupported_service_profile:missing_selector:right_turn_service" in report["errors"]
    assert "override_roundtrip_unknown_selector:paired_mainline_map.source:missing_selector" in report["errors"]


def test_phase10_run_diff_detects_status_changes_and_writes_summary(tmp_path: Path) -> None:
    before_result = _base_service_pair_result()
    after_result = _base_service_pair_result(
        manual_override_source={
            "service_profile_map": {"south_service": "left_uturn_service"},
            "paired_mainline_map": {"south_service": "south_main"},
        }
    )

    before_dir = tmp_path / "before_run"
    after_dir = tmp_path / "after_run"
    diff_dir = tmp_path / "diff_run"
    write_t10_run_result(before_result, before_dir, include_review=True)
    write_t10_run_result(after_result, after_dir, include_review=True)

    diff_payload = compare_t10_run_dirs(before_dir, after_dir)
    assert diff_payload["movement_status_change_count"] >= 1
    assert any(
        item["source_approach_id"] == "intersection:100|south_service:entry"
        and item["before_status"] != item["after_status"]
        for item in diff_payload["movement_status_changes"]
        if "before_status" in item
    )
    written = write_t10_run_diff_outputs(diff_payload, diff_dir)
    assert set(written.keys()) == {"run_diff.json", "run_diff_summary.txt", "run_diff.html"}
    summary_text = (diff_dir / "run_diff_summary.txt").read_text(encoding="utf-8")
    diff_html = (diff_dir / "run_diff.html").read_text(encoding="utf-8")
    assert "movement_status_change_count:" in summary_text
    assert "T10 Run Diff" in diff_html
    assert "Movement Status Changes" in diff_html


def test_phase10_review_bundle_can_include_override_roundtrip_report(tmp_path: Path) -> None:
    manual_override = {
        "service_profile_map": {"south_service": "left_uturn_service"},
        "paired_mainline_map": {"south_service": "south_main"},
    }
    result = _base_service_pair_result(manual_override_source=manual_override)
    roundtrip = roundtrip_manual_override_source(
        manual_override_source=manual_override,
        approach_catalog=build_approach_catalog(result),
    )
    written = write_t10_review_bundle(
        result,
        tmp_path,
        override_roundtrip_report=roundtrip,
    )
    assert "serialized_bundle.json" in written
    assert "approach_catalog.json" in written
    assert "manual_override.template.json" in written
    assert "review_unknown_movements.json" in written
    assert "override_roundtrip.json" in written
    assert "review_bundle.html" in written
    assert (tmp_path / "override_roundtrip.json").exists()
    assert (tmp_path / "review_bundle.html").exists()


def test_phase10_cli_patch_dir_review_bundle_validate_and_diff_smoke(tmp_path: Path) -> None:
    patch_dir = _write_patch_dir(
        tmp_path / "patch_dir",
        node_features=[
            _node(1, 0.0, -1.0),
            _node(2, 2.0, -1.0),
            _node(3, 0.0, 1.0),
            _node(4, 2.0, 1.0),
            _node(5, -1.0, 0.0),
            _node(6, 3.0, 0.0),
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

    base_output = tmp_path / "base_output"
    rerun_output = tmp_path / "rerun_output"
    diff_output = tmp_path / "diff_output"

    base_proc = _run_cli(
        "--patch-dir",
        str(patch_dir),
        "--output-dir",
        str(base_output),
        "--emit-review-bundle",
    )
    assert base_proc.returncode == 0, base_proc.stderr

    rerun_proc = _run_cli(
        "--patch-dir",
        str(patch_dir),
        "--manual-override",
        str(override_path),
        "--output-dir",
        str(rerun_output),
        "--emit-review-bundle",
        "--validate-override",
    )
    assert rerun_proc.returncode == 0, rerun_proc.stderr
    assert (rerun_output / "approach_catalog.json").exists()
    assert (rerun_output / "manual_override.template.json").exists()
    assert (rerun_output / "review_special_profile_gaps.json").exists()
    assert (rerun_output / "override_roundtrip.json").exists()
    assert (rerun_output / "review_bundle.html").exists()

    diff_proc = _run_cli(
        "--diff-before-dir",
        str(base_output),
        "--diff-after-dir",
        str(rerun_output),
        "--output-dir",
        str(diff_output),
    )
    assert diff_proc.returncode == 0, diff_proc.stderr
    diff_payload = json.loads(diff_proc.stdout)
    assert diff_payload["mode"] == "run_diff"
    assert diff_payload["movement_status_change_count"] >= 1
    assert (diff_output / "run_diff.json").exists()
    assert (diff_output / "run_diff_summary.txt").exists()
    assert (diff_output / "run_diff.html").exists()


def test_phase10_cli_patch_root_emit_review_bundle_smoke(tmp_path: Path) -> None:
    patch_root = tmp_path / "patch_root"
    output_root = tmp_path / "patch_root_output"
    _write_patch_dir(
        patch_root / "patch_a",
        node_features=[_node(1, 0.0, -1.0), _node(2, 0.0, 1.0)],
        road_features=[
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        ],
    )
    proc = _run_cli(
        "--patch-root",
        str(patch_root),
        "--output-dir",
        str(output_root),
        "--emit-review-bundle",
    )
    assert proc.returncode == 0, proc.stderr
    assert (output_root / "patch_a" / "mainid_100" / "approach_catalog.json").exists()
    assert (output_root / "patch_a" / "mainid_100" / "manual_override.template.json").exists()
    assert (output_root / "patch_a" / "mainid_100" / "review_summary.txt").exists()
    assert (output_root / "patch_a" / "mainid_100" / "review_bundle.html").exists()
