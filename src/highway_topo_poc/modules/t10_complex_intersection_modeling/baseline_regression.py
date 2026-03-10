from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .artifact_checker import check_t10_run_output_dir
from .api import run_t10_single_intersection_manual_mode
from .snapshot_compare import compare_t10_output_dir_to_snapshot
from .writer import write_t10_run_result


def load_t10_baseline_manifest(
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(manifest_path) if manifest_path is not None else _default_manifest_path()
    if not path.exists():
        raise ValueError(f"baseline_manifest_not_found:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"baseline_manifest_invalid_json:{path}:{exc.msg}") from exc
    check_t10_baseline_manifest_payload(payload)
    payload["manifest_path"] = str(path)
    return payload


def check_t10_baseline_manifest_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("baseline_manifest_payload_must_be_object")
    required_keys = (
        "baseline_name",
        "test_baseline_count",
        "formal_approach_profiles",
        "supported_run_modes",
        "supported_outputs",
        "unsupported_capabilities",
        "snapshot_cases",
    )
    for key in required_keys:
        if key not in payload:
            raise ValueError(f"baseline_manifest_missing_key:{key}")
    for key in (
        "formal_approach_profiles",
        "supported_run_modes",
        "supported_outputs",
        "unsupported_capabilities",
        "snapshot_cases",
    ):
        if not isinstance(payload[key], list):
            raise ValueError(f"baseline_manifest_section_must_be_list:{key}")
    return {
        "baseline_name": payload["baseline_name"],
        "test_baseline_count": payload["test_baseline_count"],
        "snapshot_case_count": len(payload["snapshot_cases"]),
    }


def run_t10_baseline_regression_smoke(
    *,
    output_root: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    manifest = load_t10_baseline_manifest(manifest_path)
    snapshot_root = _default_snapshot_root()
    if output_root is None:
        with tempfile.TemporaryDirectory(prefix="t10_regression_") as temp_dir:
            return _run_regression_cases(manifest, snapshot_root=snapshot_root, output_root=Path(temp_dir))
    return _run_regression_cases(manifest, snapshot_root=snapshot_root, output_root=Path(output_root))


def _run_regression_cases(
    manifest: dict[str, Any],
    *,
    snapshot_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for case_name in manifest["snapshot_cases"]:
        case_output_dir = output_root / case_name
        result = _build_baseline_case(case_name)
        write_t10_run_result(result, case_output_dir)
        snapshot_summary = compare_t10_output_dir_to_snapshot(case_output_dir, snapshot_root / case_name)
        artifact_summary = check_t10_run_output_dir(case_output_dir)
        cases.append(
            {
                "case_name": case_name,
                "output_dir": str(case_output_dir),
                "snapshot_summary": snapshot_summary,
                "artifact_summary": artifact_summary,
            }
        )
    payload = {
        "baseline_name": manifest["baseline_name"],
        "test_baseline_count": manifest["test_baseline_count"],
        "case_count": len(cases),
        "cases": cases,
    }
    manifest_out = output_root / "regression_manifest.json"
    summary_out = output_root / "regression_summary.txt"
    manifest_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_out.write_text(_build_regression_summary_text(payload), encoding="utf-8")
    payload["manifest_path"] = str(manifest_out)
    payload["summary_path"] = str(summary_out)
    return payload


def _build_regression_summary_text(payload: dict[str, Any]) -> str:
    lines = [
        f"baseline_name: {payload['baseline_name']}",
        f"test_baseline_count: {payload['test_baseline_count']}",
        f"case_count: {payload['case_count']}",
        "cases:",
    ]
    for case in payload["cases"]:
        lines.append(f"  - {case['case_name']}: {case['output_dir']}")
    return "\n".join(lines) + "\n"


def _build_baseline_case(case_name: str):
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
    raise ValueError(f"baseline_regression_unknown_case:{case_name}")


def _node(node_id: int, x: float, y: float, *, mainid: int = 100, kind: int = 4) -> dict[str, Any]:
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
) -> dict[str, Any]:
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


def _default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[4] / "modules" / "T10" / "T10_BASELINE_MANIFEST.json"


def _default_snapshot_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "t10" / "snapshots"


__all__ = [
    "check_t10_baseline_manifest_payload",
    "load_t10_baseline_manifest",
    "run_t10_baseline_regression_smoke",
]
