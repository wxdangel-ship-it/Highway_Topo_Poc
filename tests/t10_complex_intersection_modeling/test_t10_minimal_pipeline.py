from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from highway_topo_poc.modules.t10_complex_intersection_modeling import (
    build_movement_matrix,
    build_t10_patch_run_summary,
    build_intersection_bundles,
    build_intersection_bundles_with_manual_overrides,
    check_patch_manifest_payload,
    check_t10_patch_output_root,
    check_t10_run_output_dir,
    detect_left_uturn_service_from_raw,
    discover_patch_dir_inputs,
    evaluate_bundle,
    find_raw_formway_value,
    list_available_mainids,
    load_geojson_feature_collection,
    probe_road_geojson_file,
    probe_road_raw_properties,
    run_t10_all_intersections_from_patch_dir,
    run_t10_single_intersection_from_geojson_files,
    run_t10_single_intersection_from_patch_dir,
    run_t10_single_intersection_manual_mode,
    select_single_intersection_node_features,
    serialize_bundle,
    serialize_movement_result,
    write_t10_patch_batch_result,
    write_t10_run_result,
)

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "t10"


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


def _decision_map(decisions: Iterable, *, prefix: str = "intersection:100") -> dict[tuple[str, str], object]:
    out: dict[tuple[str, str], object] = {}
    for decision in decisions:
        body = decision.movement_id.split("|", 1)[1]
        source_key, target_key = body.split("->")
        assert decision.movement_id.startswith(prefix)
        out[(source_key, target_key)] = decision
    return out


def _fixture_path(name: str) -> Path:
    return _FIXTURE_DIR / name


def _feature_collection(features: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": features,
    }


def _write_geojson(path: Path, features: list[dict]) -> Path:
    path.write_text(json.dumps(_feature_collection(features)), encoding="utf-8")
    return path


def _write_patch_dir(path: Path, *, node_features: list[dict], road_features: list[dict], vector_layout: bool = True) -> Path:
    target_dir = path / "Vector" if vector_layout else path
    target_dir.mkdir(parents=True, exist_ok=True)
    _write_geojson(target_dir / "RCSDNode.geojson", node_features)
    _write_geojson(target_dir / "RCSDRoad.geojson", road_features)
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


def test_t10v01_basic_four_arm_pipeline() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)]
    roads = [
        _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
        _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
    ]
    bundles = build_intersection_bundles(node_features=nodes, road_features=roads)
    assert len(bundles) == 1
    bundle = bundles[0]
    assert len(bundle.arms) == 4
    assert len(bundle.approaches) == 8
    decisions = _decision_map(evaluate_bundle(bundle))
    assert decisions[("south:entry", "north:exit")].status == "allowed"
    assert decisions[("south:entry", "north:exit")].reason_codes == ("DEFAULT_THROUGH_ALLOWED",)
    assert decisions[("south:entry", "east:exit")].status == "allowed"
    assert decisions[("south:entry", "east:exit")].reason_codes == ("DEFAULT_RIGHT_ALLOWED",)
    assert decisions[("south:entry", "west:exit")].status == "allowed"
    assert decisions[("south:entry", "west:exit")].reason_codes == ("DEFAULT_CORE_LEFT_ALLOWED",)
    assert decisions[("south:entry", "south:exit")].status == "unknown"
    assert decisions[("south:entry", "south:exit")].reason_codes == ("DEFAULT_UTURN_UNKNOWN",)


def test_t10v02_single_parallel_cross_defaults_unknown() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 2.0, -1.0), _node(3, 0.0, 1.0), _node(4, 2.0, 1.0)]
    roads = [
        _road("south_main", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("south_aux", [(2.0, -1.0), (2.0, -10.0)], snodeid=2, enodeid=102),
        _road("north_main", [(0.0, 1.0), (0.0, 10.0)], snodeid=3, enodeid=103),
        _road("north_aux", [(2.0, 1.0), (2.0, 10.0)], snodeid=4, enodeid=104),
    ]
    overrides = {
        "north_main:exit": {"exit_leg_role": "core_standard_exit"},
        "north_aux:exit": {"exit_leg_role": "service_standard_exit"},
    }
    bundle = build_intersection_bundles(node_features=nodes, road_features=roads, approach_overrides=overrides)[0]
    decisions = _decision_map(evaluate_bundle(bundle))
    result = decisions[("south_main:entry", "north_aux:exit")]
    assert result.status == "unknown"
    assert result.reason_codes == ("SINGLE_PARALLEL_CROSS_DEFAULT_UNKNOWN",)
    assert result.breakpoints == ("parallel_cross_count",)


def test_t10v03_non_core_parallel_through_allowed() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 2.0, -1.0), _node(3, 0.0, 1.0), _node(4, 2.0, 1.0)]
    roads = [
        _road("south_main", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("south_aux", [(2.0, -1.0), (2.0, -10.0)], snodeid=2, enodeid=102),
        _road("north_main", [(0.0, 1.0), (0.0, 10.0)], snodeid=3, enodeid=103),
        _road("north_aux", [(2.0, 1.0), (2.0, 10.0)], snodeid=4, enodeid=104),
    ]
    overrides = {
        "south_aux:entry": {"is_core_signalized_approach": False},
        "north_main:exit": {"exit_leg_role": "core_standard_exit"},
        "north_aux:exit": {"exit_leg_role": "service_standard_exit"},
    }
    bundle = build_intersection_bundles(node_features=nodes, road_features=roads, approach_overrides=overrides)[0]
    decisions = _decision_map(evaluate_bundle(bundle))
    result = decisions[("south_aux:entry", "north_aux:exit")]
    assert result.status == "allowed"
    assert result.reason_codes == ("DEFAULT_THROUGH_ALLOWED",)


def test_t10v05_non_standard_exit_forbidden() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 1.0, 0.0)]
    roads = [
        _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("east_access", [(1.0, 0.0), (10.0, 0.0)], snodeid=2, enodeid=102),
    ]
    bundle = build_intersection_bundles(
        node_features=nodes,
        road_features=roads,
        approach_overrides={"east_access:exit": {"exit_leg_role": "access_exit"}},
    )[0]
    decisions = _decision_map(evaluate_bundle(bundle))
    result = decisions[("south:entry", "east_access:exit")]
    assert result.status == "forbidden"
    assert result.reason_codes == ("NON_STANDARD_EXIT_LEG",)
    assert result.breakpoints == ("target.exit_leg_role",)


def test_t10v07_unknown_target_role_keeps_low_conflict_through() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0)]
    roads = [
        _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
    ]
    bundle = build_intersection_bundles(
        node_features=nodes,
        road_features=roads,
        approach_overrides={"north:exit": {"exit_leg_role": "unknown"}},
    )[0]
    decisions = _decision_map(evaluate_bundle(bundle))
    result = decisions[("south:entry", "north:exit")]
    assert result.status == "allowed"
    assert result.confidence == "medium"
    assert result.reason_codes == ("DEFAULT_THROUGH_ALLOWED", "UNKNOWN_TARGET_STANDARD_EXIT")
    assert result.breakpoints == ("target.exit_leg_role",)


def test_service_profile_auto_detection_hook_is_safe_placeholder() -> None:
    raw = {"FormWay": "opaque_formway_payload"}
    assert find_raw_formway_value(raw_properties=raw) == "opaque_formway_payload"
    assert detect_left_uturn_service_from_raw(raw_properties=raw) is None


def test_manual_service_profile_map_injects_left_uturn_service_without_formway() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)]
    roads = [
        _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
        _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
    ]
    bundle = build_intersection_bundles(
        node_features=nodes,
        road_features=roads,
        approach_overrides={
            "north:exit": {"exit_leg_role": "core_standard_exit"},
            "south:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
        },
        manual_service_profile_map={"south": "left_uturn_service"},
    )[0]
    south_entry = bundle.approach_index["intersection:100|south:entry"]
    assert south_entry.approach_profile == "left_uturn_service"
    assert south_entry.approach_profile_source == "manual_service_profile_map"
    decisions = _decision_map(evaluate_bundle(bundle))
    assert decisions[("south:entry", "west:exit")].status == "allowed"
    assert decisions[("south:entry", "south:exit")].status == "allowed"
    assert decisions[("south:entry", "north:exit")].status == "forbidden"
    assert decisions[("south:entry", "east:exit")].status == "forbidden"


def test_t10v04_special_profile_rule_chain() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)]
    roads = [
        _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
        _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
    ]
    exit_overrides = {
        "north:exit": {"exit_leg_role": "core_standard_exit"},
        "south:exit": {"exit_leg_role": "core_standard_exit"},
        "west:exit": {"exit_leg_role": "core_standard_exit"},
        "east:exit": {"exit_leg_role": "core_standard_exit"},
    }

    left_service_bundle = build_intersection_bundles(
        node_features=nodes,
        road_features=roads,
        approach_overrides={
            **exit_overrides,
            "south:entry": {
                "approach_profile": "left_uturn_service",
                "is_core_signalized_approach": False,
            },
        },
    )[0]
    left_service = _decision_map(evaluate_bundle(left_service_bundle))
    assert left_service[("south:entry", "west:exit")].status == "allowed"
    assert left_service[("south:entry", "west:exit")].reason_codes == ("PROFILE_LEFT_UTURN_SERVICE_ALLOWED",)
    assert left_service[("south:entry", "west:exit")].breakpoints == ("source.approach_profile",)
    assert left_service[("south:entry", "south:exit")].status == "allowed"
    assert left_service[("south:entry", "south:exit")].reason_codes == ("PROFILE_LEFT_UTURN_SERVICE_ALLOWED",)
    assert left_service[("south:entry", "south:exit")].breakpoints == ("source.approach_profile",)
    assert left_service[("south:entry", "north:exit")].status == "forbidden"
    assert left_service[("south:entry", "north:exit")].reason_codes == ("PROFILE_LEFT_UTURN_SERVICE_FORBID_THROUGH",)
    assert left_service[("south:entry", "north:exit")].breakpoints == ("source.approach_profile",)
    assert left_service[("south:entry", "east:exit")].status == "forbidden"
    assert left_service[("south:entry", "east:exit")].reason_codes == ("PROFILE_LEFT_UTURN_SERVICE_FORBID_RIGHT",)
    assert left_service[("south:entry", "east:exit")].breakpoints == ("source.approach_profile",)

    paired_mainline_bundle = build_intersection_bundles(
        node_features=nodes,
        road_features=roads,
        approach_overrides={
            **exit_overrides,
            "south:entry": {
                "approach_profile": "paired_mainline_no_left_uturn",
                "is_core_signalized_approach": True,
            },
        },
    )[0]
    paired_mainline = _decision_map(evaluate_bundle(paired_mainline_bundle))
    assert paired_mainline[("south:entry", "west:exit")].status == "forbidden"
    assert paired_mainline[("south:entry", "west:exit")].reason_codes == ("PROFILE_PAIRED_MAINLINE_FORBID_LEFT",)
    assert paired_mainline[("south:entry", "west:exit")].breakpoints == ("source.approach_profile",)
    assert paired_mainline[("south:entry", "south:exit")].status == "forbidden"
    assert paired_mainline[("south:entry", "south:exit")].reason_codes == ("PROFILE_PAIRED_MAINLINE_FORBID_UTURN",)
    assert paired_mainline[("south:entry", "south:exit")].breakpoints == ("source.approach_profile",)
    assert paired_mainline[("south:entry", "north:exit")].status == "allowed"
    assert paired_mainline[("south:entry", "north:exit")].reason_codes == ("DEFAULT_THROUGH_ALLOWED",)
    assert paired_mainline[("south:entry", "east:exit")].status == "allowed"
    assert paired_mainline[("south:entry", "east:exit")].reason_codes == ("DEFAULT_RIGHT_ALLOWED",)


def test_manual_paired_mainline_map_by_approach_id_links_service_and_mainline() -> None:
    nodes = [
        _node(1, 0.0, -1.0),
        _node(2, 2.0, -1.0),
        _node(3, 0.0, 1.0),
        _node(6, 2.0, 1.0),
        _node(4, -1.0, 0.0),
        _node(5, 3.0, 0.0),
    ]
    roads = [
        _road("south_service", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("south_main", [(2.0, -1.0), (2.0, -10.0)], snodeid=2, enodeid=102),
        _road("north_service", [(0.0, 1.0), (0.0, 10.0)], snodeid=3, enodeid=103),
        _road("north_main", [(2.0, 1.0), (2.0, 10.0)], snodeid=6, enodeid=106),
        _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=4, enodeid=104),
        _road("east", [(3.0, 0.0), (10.0, 0.0)], snodeid=5, enodeid=105),
    ]
    bundle = build_intersection_bundles(
        node_features=nodes,
        road_features=roads,
        approach_overrides={
            "north_service:exit": {"exit_leg_role": "service_standard_exit"},
            "north_main:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
            "south_main:exit": {"exit_leg_role": "core_standard_exit"},
            "south_service:exit": {"exit_leg_role": "service_standard_exit"},
        },
        manual_service_profile_map={"south_service": "left_uturn_service"},
        manual_paired_mainline_map={
            "intersection:100|south_service:entry": "intersection:100|south_main:entry",
        },
    )[0]
    service_entry = bundle.approach_index["intersection:100|south_service:entry"]
    mainline_entry = bundle.approach_index["intersection:100|south_main:entry"]
    assert service_entry.approach_profile == "left_uturn_service"
    assert service_entry.approach_profile_source == "manual_service_profile_map"
    assert service_entry.paired_mainline_approach_id == mainline_entry.approach_id
    assert service_entry.paired_mainline_source == "manual_paired_mainline_map"
    assert mainline_entry.approach_profile == "paired_mainline_no_left_uturn"
    assert mainline_entry.approach_profile_source == "manual_paired_mainline_map"

    decisions = _decision_map(evaluate_bundle(bundle))
    assert decisions[("south_main:entry", "west:exit")].status == "forbidden"
    assert decisions[("south_main:entry", "west:exit")].reason_codes == ("PROFILE_PAIRED_MAINLINE_FORBID_LEFT",)
    assert decisions[("south_main:entry", "south_main:exit")].status == "forbidden"
    assert decisions[("south_main:entry", "south_main:exit")].reason_codes == ("PROFILE_PAIRED_MAINLINE_FORBID_UTURN",)
    assert decisions[("south_main:entry", "north_main:exit")].status == "allowed"
    assert decisions[("south_main:entry", "north_main:exit")].reason_codes == ("DEFAULT_THROUGH_ALLOWED",)


def test_file_manual_service_profile_map_injects_left_uturn_service(tmp_path: Path) -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)]
    roads = [
        _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
        _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
    ]
    override_path = tmp_path / "manual_overrides.json"
    override_path.write_text(
        json.dumps(
            {
                "service_profile_map": {"south": "left_uturn_service"},
                "paired_mainline_map": {},
            }
        ),
        encoding="utf-8",
    )

    bundle = build_intersection_bundles(
        node_features=nodes,
        road_features=roads,
        approach_overrides={
            "north:exit": {"exit_leg_role": "core_standard_exit"},
            "south:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
        },
        manual_override_source=override_path,
    )[0]

    south_entry = bundle.approach_index["intersection:100|south:entry"]
    assert south_entry.approach_profile == "left_uturn_service"
    assert south_entry.approach_profile_source == "manual_service_profile_map"
    decisions = _decision_map(evaluate_bundle(bundle))
    assert decisions[("south:entry", "west:exit")].status == "allowed"
    assert decisions[("south:entry", "south:exit")].status == "allowed"
    assert decisions[("south:entry", "north:exit")].status == "forbidden"
    assert decisions[("south:entry", "east:exit")].status == "forbidden"


def test_file_manual_paired_mainline_map_links_service_and_mainline(tmp_path: Path) -> None:
    nodes = [
        _node(1, 0.0, -1.0),
        _node(2, 2.0, -1.0),
        _node(3, 0.0, 1.0),
        _node(6, 2.0, 1.0),
        _node(4, -1.0, 0.0),
        _node(5, 3.0, 0.0),
    ]
    roads = [
        _road("south_service", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("south_main", [(2.0, -1.0), (2.0, -10.0)], snodeid=2, enodeid=102),
        _road("north_service", [(0.0, 1.0), (0.0, 10.0)], snodeid=3, enodeid=103),
        _road("north_main", [(2.0, 1.0), (2.0, 10.0)], snodeid=6, enodeid=106),
        _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=4, enodeid=104),
        _road("east", [(3.0, 0.0), (10.0, 0.0)], snodeid=5, enodeid=105),
    ]
    override_path = tmp_path / "manual_overrides.json"
    override_path.write_text(
        json.dumps(
            {
                "service_profile_map": {"south_service": "left_uturn_service"},
                "paired_mainline_map": {
                    "intersection:100|south_service:entry": "intersection:100|south_main:entry"
                },
            }
        ),
        encoding="utf-8",
    )

    bundle = build_intersection_bundles(
        node_features=nodes,
        road_features=roads,
        approach_overrides={
            "north_service:exit": {"exit_leg_role": "service_standard_exit"},
            "north_main:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
            "south_main:exit": {"exit_leg_role": "core_standard_exit"},
            "south_service:exit": {"exit_leg_role": "service_standard_exit"},
        },
        manual_override_source=override_path,
    )[0]

    service_entry = bundle.approach_index["intersection:100|south_service:entry"]
    mainline_entry = bundle.approach_index["intersection:100|south_main:entry"]
    assert service_entry.approach_profile == "left_uturn_service"
    assert service_entry.approach_profile_source == "manual_service_profile_map"
    assert service_entry.paired_mainline_approach_id == mainline_entry.approach_id
    assert service_entry.paired_mainline_source == "manual_paired_mainline_map"
    assert mainline_entry.approach_profile == "paired_mainline_no_left_uturn"
    assert mainline_entry.approach_profile_source == "manual_paired_mainline_map"

    decisions = _decision_map(evaluate_bundle(bundle))
    assert decisions[("south_main:entry", "west:exit")].status == "forbidden"
    assert decisions[("south_main:entry", "south_main:exit")].status == "forbidden"
    assert decisions[("south_main:entry", "north_main:exit")].status == "allowed"


def test_fixture_manual_service_profile_only_json_is_usable() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)]
    roads = [
        _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
        _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
    ]
    bundle = build_intersection_bundles_with_manual_overrides(
        node_features=nodes,
        road_features=roads,
        manual_override_source=_fixture_path("manual_service_profile_only.json"),
        approach_overrides={
            "north:exit": {"exit_leg_role": "core_standard_exit"},
            "south:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
        },
    )[0]
    south_entry = bundle.approach_index["intersection:100|south:entry"]
    assert south_entry.approach_profile == "left_uturn_service"
    assert south_entry.approach_profile_source == "manual_service_profile_map"


def test_fixture_manual_service_with_pair_json_is_usable() -> None:
    nodes = [
        _node(1, 0.0, -1.0),
        _node(2, 2.0, -1.0),
        _node(3, 0.0, 1.0),
        _node(6, 2.0, 1.0),
        _node(4, -1.0, 0.0),
        _node(5, 3.0, 0.0),
    ]
    roads = [
        _road("south_service", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("south_main", [(2.0, -1.0), (2.0, -10.0)], snodeid=2, enodeid=102),
        _road("north_service", [(0.0, 1.0), (0.0, 10.0)], snodeid=3, enodeid=103),
        _road("north_main", [(2.0, 1.0), (2.0, 10.0)], snodeid=6, enodeid=106),
        _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=4, enodeid=104),
        _road("east", [(3.0, 0.0), (10.0, 0.0)], snodeid=5, enodeid=105),
    ]
    bundle = build_intersection_bundles_with_manual_overrides(
        node_features=nodes,
        road_features=roads,
        manual_override_source=_fixture_path("manual_service_with_pair.json"),
        approach_overrides={
            "north_service:exit": {"exit_leg_role": "service_standard_exit"},
            "north_main:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
            "south_main:exit": {"exit_leg_role": "core_standard_exit"},
            "south_service:exit": {"exit_leg_role": "service_standard_exit"},
        },
    )[0]
    service_entry = bundle.approach_index["intersection:100|south_service:entry"]
    mainline_entry = bundle.approach_index["intersection:100|south_main:entry"]
    assert service_entry.paired_mainline_approach_id == mainline_entry.approach_id
    assert service_entry.paired_mainline_source == "manual_paired_mainline_map"
    assert mainline_entry.approach_profile == "paired_mainline_no_left_uturn"



def test_dict_manual_override_source_via_public_helper_injects_left_uturn_service() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)]
    roads = [
        _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
        _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
    ]
    bundle = build_intersection_bundles_with_manual_overrides(
        node_features=nodes,
        road_features=roads,
        manual_override_source={"service_profile_map": {"south": "left_uturn_service"}},
        approach_overrides={
            "north:exit": {"exit_leg_role": "core_standard_exit"},
            "south:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
        },
    )[0]
    south_entry = bundle.approach_index["intersection:100|south:entry"]
    assert south_entry.approach_profile == "left_uturn_service"
    assert south_entry.approach_profile_source == "manual_service_profile_map"


def test_manual_override_source_rejects_invalid_json_file(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad_manual_overrides.json"
    bad_path.write_text("{invalid json", encoding="utf-8")
    try:
        build_intersection_bundles(
            node_features=[],
            road_features=[],
            manual_override_source=bad_path,
        )
    except ValueError as exc:
        assert "manual_override_file_invalid_json" in str(exc)
    else:
        raise AssertionError("expected invalid JSON manual override source to raise ValueError")


def test_builder_keeps_raw_formway_as_safe_placeholder_without_profile_injection() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0)]
    roads = [
        _road(
            "south",
            [(0.0, -1.0), (0.0, -10.0)],
            snodeid=1,
            enodeid=101,
            extra_properties={"formway": "opaque_formway_payload"},
        ),
        _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
    ]
    bundle = build_intersection_bundles(node_features=nodes, road_features=roads)[0]
    south_entry = bundle.approach_index["intersection:100|south:entry"]
    assert south_entry.approach_profile == "default_signalized"
    assert south_entry.approach_profile_source == "auto_detection_placeholder_no_hit"
    assert south_entry.paired_mainline_source == "not_applicable"
    assert any("auto service-road inference stays disabled" in remark for remark in south_entry.remarks)


def test_left_service_without_pair_override_keeps_placeholder_pair_source() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)]
    roads = [
        _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
        _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
    ]
    bundle = build_intersection_bundles(
        node_features=nodes,
        road_features=roads,
        approach_overrides={
            "south:entry": {"approach_profile": "left_uturn_service"},
            "north:exit": {"exit_leg_role": "core_standard_exit"},
            "south:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
        },
    )[0]
    south_entry = bundle.approach_index["intersection:100|south:entry"]
    assert south_entry.approach_profile_source == "approach_override"
    assert south_entry.paired_mainline_approach_id is None
    assert south_entry.paired_mainline_source == "auto_pair_placeholder_no_hit"


def test_raw_property_probe_detects_formway_and_integer_distribution() -> None:
    roads = [
        _road("r1", [(0.0, 0.0), (1.0, 0.0)], snodeid=1, enodeid=2, extra_properties={"formway": 128}),
        _road("r2", [(0.0, 1.0), (1.0, 1.0)], snodeid=3, enodeid=4, extra_properties={"FormWay": 128}),
        _road("r3", [(0.0, 2.0), (1.0, 2.0)], snodeid=5, enodeid=6, extra_properties={"flag_mask": 4}),
    ]
    summary = probe_road_raw_properties(roads)
    formway = summary["candidate_fields"]["formway"]
    assert formway["present"] is True
    assert formway["present_count"] == 2
    assert formway["value_types"] == {"int": 2}
    assert formway["int_value_counts"] == {"128": 2}
    assert "formway" in summary["suspicious_bitlike_fields"]
    assert "flagmask" in summary["suspicious_bitlike_fields"]
    assert "detected_profile" not in formway


def test_raw_property_probe_reports_missing_formway_cleanly() -> None:
    roads = [
        _road("r1", [(0.0, 0.0), (1.0, 0.0)], snodeid=1, enodeid=2),
        _road("r2", [(0.0, 1.0), (1.0, 1.0)], snodeid=3, enodeid=4, extra_properties={"road_flag": 9}),
    ]
    summary = probe_road_raw_properties(roads)
    formway = summary["candidate_fields"]["formway"]
    assert formway["present"] is False
    assert formway["present_count"] == 0
    assert formway["value_types"] == {}


def test_raw_property_probe_handles_mixed_types_without_semantic_inference() -> None:
    roads = [
        _road("r1", [(0.0, 0.0), (1.0, 0.0)], snodeid=1, enodeid=2, extra_properties={"formway": 128}),
        _road("r2", [(0.0, 1.0), (1.0, 1.0)], snodeid=3, enodeid=4, extra_properties={"formway": "128"}),
        _road("r3", [(0.0, 2.0), (1.0, 2.0)], snodeid=5, enodeid=6, extra_properties={"formway": None}),
    ]
    summary = probe_road_raw_properties(roads)
    formway = summary["candidate_fields"]["formway"]
    assert formway["has_mixed_types"] is True
    assert formway["value_types"] == {"int": 1, "null": 1, "str": 1}
    assert formway["int_value_counts"] == {"128": 1}
    assert "left_uturn_service" not in json.dumps(summary, ensure_ascii=False)


def test_probe_road_geojson_file_reads_feature_collection(tmp_path: Path) -> None:
    geojson_path = tmp_path / "roads.geojson"
    geojson_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    _road(
                        "r1",
                        [(0.0, 0.0), (1.0, 0.0)],
                        snodeid=1,
                        enodeid=2,
                        extra_properties={"formway": 128},
                    )
                ],
            }
        ),
        encoding="utf-8",
    )
    summary = probe_road_geojson_file(geojson_path)
    assert summary["feature_count"] == 1
    assert summary["raw_property_probe"]["candidate_fields"]["formway"]["present"] is True


def test_public_api_runs_basic_sample_and_returns_serialized_outputs() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)]
    roads = [
        _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
        _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
    ]
    result = run_t10_single_intersection_manual_mode(node_features=nodes, road_features=roads)
    assert result.bundle.intersection.intersection_id == "intersection:100"
    assert len(result.decisions) == len(result.bundle.movements)
    assert "intersection" in result.serialized_bundle
    assert "approaches" in result.serialized_bundle
    first = result.movement_results[0]
    assert {
        "source_approach_id",
        "target_approach_id",
        "status",
        "confidence",
        "reason_codes",
        "reason_text",
        "breakpoints",
    }.issubset(first.keys())
    matrix_cell = result.matrix_view["cells"]["intersection:100|south:entry"]["intersection:100|north:exit"]
    assert matrix_cell["status"] == "allowed"
    assert matrix_cell["reason_codes"] == ["DEFAULT_THROUGH_ALLOWED"]


def test_public_api_runs_json_override_special_profile_end_to_end() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)]
    roads = [
        _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
        _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
    ]
    result = run_t10_single_intersection_manual_mode(
        node_features=nodes,
        road_features=roads,
        manual_override_source=_fixture_path("manual_service_profile_only.json"),
        approach_overrides={
            "north:exit": {"exit_leg_role": "core_standard_exit"},
            "south:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
        },
    )
    south_entry = result.bundle.approach_index["intersection:100|south:entry"]
    assert south_entry.approach_profile == "left_uturn_service"
    assert south_entry.approach_profile_source == "manual_service_profile_map"
    matrix_cell = result.matrix_view["cells"]["intersection:100|south:entry"]["intersection:100|west:exit"]
    assert matrix_cell["status"] == "allowed"
    assert matrix_cell["reason_codes"] == ["PROFILE_LEFT_UTURN_SERVICE_ALLOWED"]
    assert matrix_cell["breakpoints"] == ["source.approach_profile"]


def test_serialization_helpers_generate_stable_bundle_and_matrix_views() -> None:
    nodes = [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0)]
    roads = [
        _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
        _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
    ]
    bundle = build_intersection_bundles(node_features=nodes, road_features=roads)[0]
    decisions = evaluate_bundle(bundle)
    bundle_dict = serialize_bundle(bundle)
    matrix = build_movement_matrix(bundle, decisions)
    movement_result = serialize_movement_result(bundle.movements[0], decisions[0])
    assert bundle_dict["intersection"]["intersection_id"] == "intersection:100"
    assert bundle_dict["approaches"][0]["geometry_ref"]["point"] is not None
    assert matrix["entry_approach_ids"] == ["intersection:100|north:entry", "intersection:100|south:entry"]
    assert "cells" in matrix
    assert movement_result["movement_id"] == decisions[0].movement_id


def test_file_api_runs_basic_sample_from_geojson_files(tmp_path: Path) -> None:
    node_path = _write_geojson(
        tmp_path / "RCSDNode.geojson",
        [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)],
    )
    road_path = _write_geojson(
        tmp_path / "RCSDRoad.geojson",
        [
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
            _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
        ],
    )
    assert len(load_geojson_feature_collection(node_path)) == 4
    result = run_t10_single_intersection_from_geojson_files(
        node_geojson_path=node_path,
        road_geojson_path=road_path,
    )
    assert result.bundle.intersection.intersection_id == "intersection:100"
    matrix_cell = result.matrix_view["cells"]["intersection:100|south:entry"]["intersection:100|north:exit"]
    assert matrix_cell["status"] == "allowed"
    assert matrix_cell["reason_codes"] == ["DEFAULT_THROUGH_ALLOWED"]


def test_file_api_requires_mainid_when_multiple_mainids_present(tmp_path: Path) -> None:
    node_features = [
        _node(1, 0.0, -1.0, mainid=100),
        _node(2, 0.0, 1.0, mainid=100),
        _node(11, 20.0, -1.0, mainid=200),
        _node(12, 20.0, 1.0, mainid=200),
    ]
    node_path = _write_geojson(tmp_path / "RCSDNode.geojson", node_features)
    road_path = _write_geojson(
        tmp_path / "RCSDRoad.geojson",
        [
            _road("south_a", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north_a", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("south_b", [(20.0, -1.0), (20.0, -10.0)], snodeid=11, enodeid=201),
            _road("north_b", [(20.0, 1.0), (20.0, 10.0)], snodeid=12, enodeid=202),
        ],
    )
    selected, chosen_mainid, available_mainids = select_single_intersection_node_features(node_features, mainid=100)
    assert chosen_mainid == 100
    assert available_mainids == [100, 200]
    assert len(selected) == 2
    try:
        run_t10_single_intersection_from_geojson_files(
            node_geojson_path=node_path,
            road_geojson_path=road_path,
        )
    except ValueError as exc:
        assert "multiple_mainids_in_node_file:100,200" in str(exc)
    else:
        raise AssertionError("expected multiple mainids without selection to raise ValueError")


def test_file_api_can_select_mainid_and_apply_manual_override(tmp_path: Path) -> None:
    node_path = _write_geojson(
        tmp_path / "RCSDNode.geojson",
        [
            _node(1, 0.0, -1.0, mainid=100),
            _node(2, 0.0, 1.0, mainid=100),
            _node(3, -1.0, 0.0, mainid=100),
            _node(4, 1.0, 0.0, mainid=100),
            _node(11, 20.0, -1.0, mainid=200),
            _node(12, 20.0, 1.0, mainid=200),
        ],
    )
    road_path = _write_geojson(
        tmp_path / "RCSDRoad.geojson",
        [
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
            _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
            _road("south_other", [(20.0, -1.0), (20.0, -10.0)], snodeid=11, enodeid=201),
            _road("north_other", [(20.0, 1.0), (20.0, 10.0)], snodeid=12, enodeid=202),
        ],
    )
    result = run_t10_single_intersection_from_geojson_files(
        node_geojson_path=node_path,
        road_geojson_path=road_path,
        manual_override_source=_fixture_path("manual_service_profile_only.json"),
        approach_overrides={
            "north:exit": {"exit_leg_role": "core_standard_exit"},
            "south:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
        },
        mainid=100,
    )
    south_entry = result.bundle.approach_index["intersection:100|south:entry"]
    assert south_entry.approach_profile == "left_uturn_service"
    assert south_entry.approach_profile_source == "manual_service_profile_map"
    assert "intersection:200" not in result.serialized_bundle["intersection"]["intersection_id"]


def test_writer_persists_json_and_txt_outputs_for_file_based_smoke_path(tmp_path: Path) -> None:
    node_path = _write_geojson(
        tmp_path / "RCSDNode.geojson",
        [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)],
    )
    road_path = _write_geojson(
        tmp_path / "RCSDRoad.geojson",
        [
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
            _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
        ],
    )
    result = run_t10_single_intersection_from_geojson_files(
        node_geojson_path=node_path,
        road_geojson_path=road_path,
        manual_override_source=_fixture_path("manual_service_profile_only.json"),
        approach_overrides={
            "north:exit": {"exit_leg_role": "core_standard_exit"},
            "south:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
        },
    )
    output_dir = tmp_path / "t10_output"
    written = write_t10_run_result(result, output_dir)
    assert set(written.keys()) == {
        "serialized_bundle.json",
        "movement_results.json",
        "movement_matrix.json",
        "summary.txt",
    }
    for path_text in written.values():
        assert Path(path_text).exists()
    bundle_json = json.loads((output_dir / "serialized_bundle.json").read_text(encoding="utf-8"))
    movement_results = json.loads((output_dir / "movement_results.json").read_text(encoding="utf-8"))
    movement_matrix = json.loads((output_dir / "movement_matrix.json").read_text(encoding="utf-8"))
    summary_text = (output_dir / "summary.txt").read_text(encoding="utf-8")
    assert bundle_json["intersection"]["intersection_id"] == "intersection:100"
    assert movement_results
    assert movement_matrix["cells"]["intersection:100|south:entry"]["intersection:100|west:exit"]["status"] == "allowed"
    assert "manual_override_used: true" in summary_text


def test_patch_dir_api_discovers_vector_layout_and_runs(tmp_path: Path) -> None:
    patch_dir = _write_patch_dir(
        tmp_path / "patch_100",
        node_features=[_node(1, 0.0, -1.0), _node(2, 0.0, 1.0)],
        road_features=[
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        ],
    )
    node_path, road_path = discover_patch_dir_inputs(patch_dir)
    assert node_path.name == "RCSDNode.geojson"
    assert road_path.name == "RCSDRoad.geojson"
    result = run_t10_single_intersection_from_patch_dir(patch_dir=patch_dir)
    assert result.bundle.intersection.intersection_id == "intersection:100"
    assert result.matrix_view["cells"]["intersection:100|south:entry"]["intersection:100|north:exit"]["status"] == "allowed"


def test_patch_dir_api_requires_required_files(tmp_path: Path) -> None:
    patch_dir = tmp_path / "patch_missing"
    vector_dir = patch_dir / "Vector"
    vector_dir.mkdir(parents=True, exist_ok=True)
    _write_geojson(vector_dir / "RCSDNode.geojson", [_node(1, 0.0, -1.0)])
    try:
        run_t10_single_intersection_from_patch_dir(patch_dir=patch_dir)
    except ValueError as exc:
        assert "patch_dir_missing_required_files" in str(exc)
    else:
        raise AssertionError("expected missing RCSDRoad.geojson to raise ValueError")


def test_patch_dir_api_requires_mainid_when_multiple_mainids_present(tmp_path: Path) -> None:
    patch_dir = _write_patch_dir(
        tmp_path / "patch_multi_mainid",
        node_features=[
            _node(1, 0.0, -1.0, mainid=100),
            _node(2, 0.0, 1.0, mainid=100),
            _node(11, 20.0, -1.0, mainid=200),
            _node(12, 20.0, 1.0, mainid=200),
        ],
        road_features=[
            _road("south_a", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north_a", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("south_b", [(20.0, -1.0), (20.0, -10.0)], snodeid=11, enodeid=201),
            _road("north_b", [(20.0, 1.0), (20.0, 10.0)], snodeid=12, enodeid=202),
        ],
    )
    available = list_available_mainids(load_geojson_feature_collection(patch_dir / "Vector" / "RCSDNode.geojson"))
    assert available == [100, 200]
    try:
        run_t10_single_intersection_from_patch_dir(patch_dir=patch_dir)
    except ValueError as exc:
        assert "multiple_mainids_in_node_file:100,200" in str(exc)
    else:
        raise AssertionError("expected multiple mainids without selection to raise ValueError")


def test_patch_dir_api_applies_manual_override(tmp_path: Path) -> None:
    patch_dir = _write_patch_dir(
        tmp_path / "patch_override",
        node_features=[_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)],
        road_features=[
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
            _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
        ],
    )
    result = run_t10_single_intersection_from_patch_dir(
        patch_dir=patch_dir,
        manual_override_source=_fixture_path("manual_service_profile_only.json"),
        approach_overrides={
            "north:exit": {"exit_leg_role": "core_standard_exit"},
            "south:exit": {"exit_leg_role": "core_standard_exit"},
            "west:exit": {"exit_leg_role": "core_standard_exit"},
            "east:exit": {"exit_leg_role": "core_standard_exit"},
        },
    )
    south_entry = result.bundle.approach_index["intersection:100|south:entry"]
    assert south_entry.approach_profile == "left_uturn_service"
    assert south_entry.approach_profile_source == "manual_service_profile_map"


def test_patch_batch_api_runs_all_mainids_and_returns_statuses(tmp_path: Path) -> None:
    patch_dir = _write_patch_dir(
        tmp_path / "patch_batch",
        node_features=[
            _node(1, 0.0, -1.0, mainid=100),
            _node(2, 0.0, 1.0, mainid=100),
            _node(11, 20.0, -1.0, mainid=200),
            _node(12, 20.0, 1.0, mainid=200),
        ],
        road_features=[
            _road("south_a", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north_a", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("south_b", [(20.0, -1.0), (20.0, -10.0)], snodeid=11, enodeid=201),
            _road("north_b", [(20.0, 1.0), (20.0, 10.0)], snodeid=12, enodeid=202),
        ],
    )
    batch = run_t10_all_intersections_from_patch_dir(patch_dir=patch_dir)
    assert batch.mainids == (100, 200)
    assert [item.status for item in batch.items] == ["success", "success"]
    summary = build_t10_patch_run_summary(batch)
    assert summary["mainids"] == [100, 200]
    assert summary["runs"][0]["movement_count"] is not None


def test_patch_batch_writer_writes_subdirs_and_manifest(tmp_path: Path) -> None:
    patch_dir = _write_patch_dir(
        tmp_path / "patch_batch_write",
        node_features=[
            _node(1, 0.0, -1.0, mainid=100),
            _node(2, 0.0, 1.0, mainid=100),
            _node(11, 20.0, -1.0, mainid=200),
            _node(12, 20.0, 1.0, mainid=200),
        ],
        road_features=[
            _road("south_a", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north_a", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("south_b", [(20.0, -1.0), (20.0, -10.0)], snodeid=11, enodeid=201),
            _road("north_b", [(20.0, 1.0), (20.0, 10.0)], snodeid=12, enodeid=202),
        ],
    )
    output_root = tmp_path / "patch_batch_output"
    batch = run_t10_all_intersections_from_patch_dir(patch_dir=patch_dir)
    written_batch = write_t10_patch_batch_result(batch, output_root)
    assert written_batch.manifest_path is not None
    assert written_batch.summary_path is not None
    assert Path(written_batch.manifest_path).exists()
    assert Path(written_batch.summary_path).exists()
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mainids"] == [100, 200]
    assert (output_root / "mainid_100" / "serialized_bundle.json").exists()
    assert (output_root / "mainid_200" / "serialized_bundle.json").exists()


def test_patch_batch_api_keeps_success_and_error_visible_per_mainid(tmp_path: Path) -> None:
    patch_dir = _write_patch_dir(
        tmp_path / "patch_batch_partial_error",
        node_features=[
            _node(1, 0.0, -1.0, mainid=100),
            _node(2, 0.0, 1.0, mainid=100),
            _node(11, 20.0, -1.0, mainid=200),
            _node(12, 20.0, 1.0, mainid=200),
        ],
        road_features=[
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("south_other", [(20.0, -1.0), (20.0, -10.0)], snodeid=11, enodeid=201),
            _road("north_other", [(20.0, 1.0), (20.0, 10.0)], snodeid=12, enodeid=202),
        ],
    )
    output_root = tmp_path / "patch_partial_output"
    batch = run_t10_all_intersections_from_patch_dir(
        patch_dir=patch_dir,
        manual_override_source=_fixture_path("manual_service_profile_only.json"),
        output_root=output_root,
    )
    status_map = {item.mainid: item for item in batch.items}
    assert status_map[100].status == "success"
    assert status_map[200].status == "error"
    assert "manual_service_ref_not_found:south" in (status_map[200].error or "")
    assert Path(status_map[100].output_dir or "").exists()
    assert Path(status_map[200].output_dir or "").exists()
    assert (Path(status_map[200].output_dir or "") / "error.txt").exists()


def test_cli_file_mode_smoke(tmp_path: Path) -> None:
    node_path = _write_geojson(
        tmp_path / "RCSDNode.geojson",
        [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0)],
    )
    road_path = _write_geojson(
        tmp_path / "RCSDRoad.geojson",
        [
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        ],
    )
    output_dir = tmp_path / "cli_file_output"
    proc = _run_cli(
        "--node-file",
        str(node_path),
        "--road-file",
        str(road_path),
        "--output-dir",
        str(output_dir),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "single_intersection"
    assert payload["intersection_id"] == "intersection:100"
    assert (output_dir / "movement_results.json").exists()


def test_cli_patch_dir_mode_smoke(tmp_path: Path) -> None:
    patch_dir = _write_patch_dir(
        tmp_path / "patch_cli",
        node_features=[
            _node(1, 0.0, -1.0, mainid=100),
            _node(2, 0.0, 1.0, mainid=100),
            _node(11, 20.0, -1.0, mainid=200),
            _node(12, 20.0, 1.0, mainid=200),
        ],
        road_features=[
            _road("south_a", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north_a", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("south_b", [(20.0, -1.0), (20.0, -10.0)], snodeid=11, enodeid=201),
            _road("north_b", [(20.0, 1.0), (20.0, 10.0)], snodeid=12, enodeid=202),
        ],
    )
    output_dir = tmp_path / "cli_patch_output"
    proc = _run_cli(
        "--patch-dir",
        str(patch_dir),
        "--all-mainids",
        "--output-dir",
        str(output_dir),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "patch_dir_batch"
    assert payload["mainids"] == [100, 200]
    assert (output_dir / "manifest.json").exists()


def test_run_output_checker_accepts_single_intersection_artifacts(tmp_path: Path) -> None:
    node_path = _write_geojson(
        tmp_path / "RCSDNode.geojson",
        [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0), _node(3, -1.0, 0.0), _node(4, 1.0, 0.0)],
    )
    road_path = _write_geojson(
        tmp_path / "RCSDRoad.geojson",
        [
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("west", [(-1.0, 0.0), (-10.0, 0.0)], snodeid=3, enodeid=103),
            _road("east", [(1.0, 0.0), (10.0, 0.0)], snodeid=4, enodeid=104),
        ],
    )
    result = run_t10_single_intersection_from_geojson_files(
        node_geojson_path=node_path,
        road_geojson_path=road_path,
    )
    output_dir = tmp_path / "checker_single"
    write_t10_run_result(result, output_dir)
    summary = check_t10_run_output_dir(output_dir)
    assert summary["intersection_id"] == "intersection:100"
    assert summary["movement_count"] == len(result.decisions)
    assert set(summary["files_checked"]) == {
        "serialized_bundle.json",
        "movement_results.json",
        "movement_matrix.json",
        "summary.txt",
    }


def test_patch_output_checker_accepts_batch_artifacts(tmp_path: Path) -> None:
    patch_dir = _write_patch_dir(
        tmp_path / "patch_checker",
        node_features=[
            _node(1, 0.0, -1.0, mainid=100),
            _node(2, 0.0, 1.0, mainid=100),
            _node(11, 20.0, -1.0, mainid=200),
            _node(12, 20.0, 1.0, mainid=200),
        ],
        road_features=[
            _road("south_a", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north_a", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
            _road("south_b", [(20.0, -1.0), (20.0, -10.0)], snodeid=11, enodeid=201),
            _road("north_b", [(20.0, 1.0), (20.0, 10.0)], snodeid=12, enodeid=202),
        ],
    )
    output_root = tmp_path / "checker_patch_output"
    run_t10_all_intersections_from_patch_dir(
        patch_dir=patch_dir,
        output_root=output_root,
    )
    summary = check_t10_patch_output_root(output_root)
    assert summary["mainids"] == [100, 200]
    assert summary["item_count"] == 2


def test_checker_rejects_missing_required_bundle_key(tmp_path: Path) -> None:
    node_path = _write_geojson(
        tmp_path / "RCSDNode.geojson",
        [_node(1, 0.0, -1.0), _node(2, 0.0, 1.0)],
    )
    road_path = _write_geojson(
        tmp_path / "RCSDRoad.geojson",
        [
            _road("south", [(0.0, -1.0), (0.0, -10.0)], snodeid=1, enodeid=101),
            _road("north", [(0.0, 1.0), (0.0, 10.0)], snodeid=2, enodeid=102),
        ],
    )
    result = run_t10_single_intersection_from_geojson_files(
        node_geojson_path=node_path,
        road_geojson_path=road_path,
    )
    output_dir = tmp_path / "checker_bad_single"
    write_t10_run_result(result, output_dir)
    bundle_path = output_dir / "serialized_bundle.json"
    bundle_payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle_payload.pop("intersection")
    bundle_path.write_text(json.dumps(bundle_payload), encoding="utf-8")
    try:
        check_t10_run_output_dir(output_dir)
    except ValueError as exc:
        assert "artifact_missing_key:serialized_bundle:intersection" in str(exc)
    else:
        raise AssertionError("expected missing bundle key to raise ValueError")


def test_patch_manifest_checker_rejects_mainid_mismatch() -> None:
    payload = {
        "patch_dir": "patch_dir",
        "node_geojson_path": "RCSDNode.geojson",
        "road_geojson_path": "RCSDRoad.geojson",
        "mainids": [100, 200],
        "items": [
            {"mainid": 100, "status": "success", "output_dir": "mainid_100", "error": None},
            {"mainid": 300, "status": "success", "output_dir": "mainid_300", "error": None},
        ],
    }
    try:
        check_patch_manifest_payload(payload)
    except ValueError as exc:
        assert "artifact_manifest_mainids_mismatch" in str(exc)
    else:
        raise AssertionError("expected manifest mismatch to raise ValueError")


def test_file_api_rejects_missing_requested_mainid() -> None:
    nodes = [_node(1, 0.0, -1.0, mainid=100), _node(2, 0.0, 1.0, mainid=100)]
    try:
        select_single_intersection_node_features(nodes, mainid=999)
    except ValueError as exc:
        assert "requested_mainid_not_found:999:available=100" in str(exc)
    else:
        raise AssertionError("expected requested mainid mismatch to raise ValueError")


def test_manual_override_missing_file_error_is_stable() -> None:
    try:
        build_intersection_bundles(
            node_features=[],
            road_features=[],
            manual_override_source=_fixture_path("missing_manual_override.json"),
        )
    except ValueError as exc:
        assert "manual_override_file_not_found" in str(exc)
    else:
        raise AssertionError("expected missing manual override file to raise ValueError")
