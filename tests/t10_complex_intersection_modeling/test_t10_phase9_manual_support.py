from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from highway_topo_poc.modules.t10_complex_intersection_modeling import (
    build_approach_catalog,
    build_manual_override_template,
    build_review_nonstandard_targets,
    build_review_special_profile_gaps,
    build_review_unknown_movements,
    run_t10_single_intersection_manual_mode,
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


def _result_for_manual_support_review():
    return run_t10_single_intersection_manual_mode(
        node_features=[
            _node(1, 0.0, -1.0),
            _node(2, 0.0, 1.0),
            _node(3, 1.0, 0.0),
        ],
        road_features=[
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("east_access", [(1.0, 0.0), (10.0, 0.0)], snodeid=3, enodeid=103),
        ],
        approach_overrides={
            "north:exit": {"exit_leg_role": "unknown"},
            "east_access:exit": {"exit_leg_role": "access_exit"},
        },
    )


def test_approach_catalog_contains_selector_hints_and_core_fields() -> None:
    result = _result_for_manual_support_review()
    payload = build_approach_catalog(result)
    assert payload["intersection_id"] == "intersection:100"
    assert payload["mainid"] == 100
    assert payload["approach_count"] == len(result.bundle.approaches)
    first = payload["approaches"][0]
    assert set(
        [
            "intersection_id",
            "mainid",
            "approach_id",
            "road_id",
            "arm_id",
            "movement_side",
            "is_core_signalized_approach",
            "approach_profile",
            "approach_profile_source",
            "paired_mainline_approach_id",
            "paired_mainline_source",
            "exit_leg_role",
            "is_standard_exit_leg",
            "selector_hints",
        ]
    ).issubset(first.keys())
    assert set(["road_id", "road_side_selector", "approach_id"]).issubset(first["selector_hints"].keys())


def test_manual_override_template_has_expected_sections() -> None:
    result = _result_for_manual_support_review()
    payload = build_manual_override_template(result)
    assert payload["service_profile_map"] == {}
    assert payload["paired_mainline_map"] == {}
    assert payload["metadata"]["supported_service_profiles"] == ["left_uturn_service"]
    assert payload["selector_examples"]["entry_road_ids"]
    assert payload["selector_examples"]["entry_approach_ids"]


def test_review_payloads_cover_unknown_nonstandard_and_profile_gap_views() -> None:
    result = _result_for_manual_support_review()
    unknown_payload = build_review_unknown_movements(result)
    nonstandard_payload = build_review_nonstandard_targets(result)
    gap_payload = build_review_special_profile_gaps(result)

    assert unknown_payload["unknown_movement_count"] >= 1
    assert any(item["target_exit_leg_role"] == "unknown" for item in unknown_payload["items"])
    assert nonstandard_payload["target_count"] >= 2
    assert {item["exit_leg_role"] for item in nonstandard_payload["items"]} >= {"access_exit", "unknown"}
    assert gap_payload["candidate_count"] >= 1
    assert all(item["candidate_only"] is True for item in gap_payload["items"])


def test_writer_can_emit_catalog_template_and_review_outputs(tmp_path: Path) -> None:
    result = _result_for_manual_support_review()
    written = write_t10_run_result(
        result,
        tmp_path,
        include_catalog=True,
        include_override_template=True,
        include_review=True,
    )
    assert "approach_catalog.json" in written
    assert "manual_override.template.json" in written
    assert "review_unknown_movements.json" in written
    assert "review_nonstandard_targets.json" in written
    assert "review_special_profile_gaps.json" in written
    assert "review_summary.txt" in written

    catalog = json.loads((tmp_path / "approach_catalog.json").read_text(encoding="utf-8"))
    template = json.loads((tmp_path / "manual_override.template.json").read_text(encoding="utf-8"))
    review_unknown = json.loads((tmp_path / "review_unknown_movements.json").read_text(encoding="utf-8"))
    assert catalog["intersection_id"] == "intersection:100"
    assert template["service_profile_map"] == {}
    assert review_unknown["unknown_movement_count"] >= 1


def test_cli_patch_dir_mode_can_emit_manual_support_outputs(tmp_path: Path) -> None:
    patch_dir = _write_patch_dir(
        tmp_path / "patch_dir_mode",
        node_features=[
            _node(1, 0.0, -1.0),
            _node(2, 0.0, 1.0),
            _node(3, 1.0, 0.0),
        ],
        road_features=[
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("east_access", [(1.0, 0.0), (10.0, 0.0)], snodeid=3, enodeid=103),
        ],
    )
    output_dir = tmp_path / "patch_dir_output"
    proc = _run_cli(
        "--patch-dir",
        str(patch_dir),
        "--output-dir",
        str(output_dir),
        "--emit-catalog",
        "--emit-override-template",
        "--emit-review",
    )
    assert proc.returncode == 0, proc.stderr
    assert (output_dir / "approach_catalog.json").exists()
    assert (output_dir / "manual_override.template.json").exists()
    assert (output_dir / "review_unknown_movements.json").exists()
    assert (output_dir / "review_nonstandard_targets.json").exists()
    assert (output_dir / "review_special_profile_gaps.json").exists()
    assert (output_dir / "review_summary.txt").exists()


def test_cli_patch_root_mode_can_emit_manual_support_outputs(tmp_path: Path) -> None:
    patch_root = tmp_path / "patch_root"
    output_root = tmp_path / "patch_root_output"
    _write_patch_dir(
        patch_root / "patch_a",
        node_features=[
            _node(1, 0.0, -1.0),
            _node(2, 0.0, 1.0),
        ],
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
        "--emit-catalog",
        "--emit-override-template",
        "--emit-review",
    )
    assert proc.returncode == 0, proc.stderr
    assert (output_root / "patch_a" / "mainid_100" / "approach_catalog.json").exists()
    assert (output_root / "patch_a" / "mainid_100" / "manual_override.template.json").exists()
    assert (output_root / "patch_a" / "mainid_100" / "review_unknown_movements.json").exists()
    assert (output_root / "patch_a" / "manifest.json").exists()
    assert (output_root / "manifest.json").exists()
