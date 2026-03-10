from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_RUN_JSON_FILES = (
    "serialized_bundle.json",
    "movement_results.json",
    "movement_matrix.json",
)


def check_t10_run_output_dir(output_dir: str | Path) -> dict[str, Any]:
    resolved = Path(output_dir)
    bundle = _load_json_file(resolved / "serialized_bundle.json")
    movement_results = _load_json_file(resolved / "movement_results.json")
    matrix = _load_json_file(resolved / "movement_matrix.json")
    summary_path = resolved / "summary.txt"
    if not summary_path.exists():
        raise ValueError(f"artifact_missing_file:{summary_path}")
    summary_text = summary_path.read_text(encoding="utf-8")
    if "intersection_id:" not in summary_text or "movement_count:" not in summary_text:
        raise ValueError("artifact_summary_missing_required_lines:summary.txt")

    bundle_summary = check_serialized_bundle_payload(bundle)
    movement_summary = check_movement_results_payload(movement_results)
    matrix_summary = check_movement_matrix_payload(matrix)
    if matrix_summary["intersection_id"] != bundle_summary["intersection_id"]:
        raise ValueError("artifact_intersection_id_mismatch:bundle_vs_matrix")
    if movement_summary["movement_count"] != matrix_summary["cell_count"]:
        raise ValueError("artifact_movement_count_mismatch:movement_results_vs_matrix")
    return {
        "output_dir": str(resolved),
        "intersection_id": bundle_summary["intersection_id"],
        "approach_count": bundle_summary["approach_count"],
        "movement_count": movement_summary["movement_count"],
        "entry_count": matrix_summary["entry_count"],
        "exit_count": matrix_summary["exit_count"],
        "files_checked": [*list(_RUN_JSON_FILES), "summary.txt"],
    }


def check_t10_patch_output_root(output_root: str | Path) -> dict[str, Any]:
    resolved = Path(output_root)
    manifest = _load_json_file(resolved / "manifest.json")
    summary_path = resolved / "summary.txt"
    if not summary_path.exists():
        raise ValueError(f"artifact_missing_file:{summary_path}")
    summary_text = summary_path.read_text(encoding="utf-8")
    if "patch_dir:" not in summary_text or "mainid_count:" not in summary_text:
        raise ValueError("artifact_summary_missing_required_lines:patch_summary.txt")

    manifest_summary = check_patch_manifest_payload(manifest)
    item_summaries: list[dict[str, Any]] = []
    for item in manifest_summary["items"]:
        item_dir = resolved / _mainid_dir_name(item["mainid"])
        if item["status"] == "success":
            item_summaries.append(check_t10_run_output_dir(item_dir))
        else:
            error_path = item_dir / "error.txt"
            if not error_path.exists():
                raise ValueError(f"artifact_missing_file:{error_path}")
            item_summaries.append(
                {
                    "mainid": item["mainid"],
                    "status": "error",
                    "error_file": str(error_path),
                }
            )
    return {
        "output_root": str(resolved),
        "mainids": manifest_summary["mainids"],
        "item_count": len(item_summaries),
        "items": item_summaries,
        "files_checked": ["manifest.json", "summary.txt"],
    }


def check_serialized_bundle_payload(payload: Any) -> dict[str, Any]:
    _require_object(payload, "serialized_bundle")
    for key in ("intersection", "arms", "approaches", "movements", "warnings"):
        if key not in payload:
            raise ValueError(f"artifact_missing_key:serialized_bundle:{key}")
    _require_object(payload["intersection"], "serialized_bundle.intersection")
    _require_list(payload["arms"], "serialized_bundle.arms")
    _require_list(payload["approaches"], "serialized_bundle.approaches")
    _require_list(payload["movements"], "serialized_bundle.movements")
    _require_list(payload["warnings"], "serialized_bundle.warnings")

    intersection = payload["intersection"]
    for key in (
        "intersection_id",
        "node_group_id",
        "member_node_ids",
        "control_type",
        "signalized_control_zone_id",
        "source_type",
        "remarks",
    ):
        if key not in intersection:
            raise ValueError(f"artifact_missing_key:serialized_bundle.intersection:{key}")

    for idx, approach in enumerate(payload["approaches"]):
        _require_object(approach, f"serialized_bundle.approaches[{idx}]")
        for key in (
            "approach_id",
            "road_id",
            "intersection_id",
            "arm_id",
            "movement_side",
            "approach_profile",
            "approach_profile_source",
            "exit_leg_role",
            "geometry_ref",
        ):
            if key not in approach:
                raise ValueError(f"artifact_missing_key:serialized_bundle.approaches[{idx}]:{key}")

    return {
        "intersection_id": intersection["intersection_id"],
        "approach_count": len(payload["approaches"]),
        "movement_seed_count": len(payload["movements"]),
        "arm_count": len(payload["arms"]),
    }


def check_movement_results_payload(payload: Any) -> dict[str, Any]:
    _require_list(payload, "movement_results")
    for idx, item in enumerate(payload):
        _require_object(item, f"movement_results[{idx}]")
        for key in (
            "movement_id",
            "source_approach_id",
            "target_approach_id",
            "status",
            "confidence",
            "reason_codes",
            "reason_text",
            "breakpoints",
        ):
            if key not in item:
                raise ValueError(f"artifact_missing_key:movement_results[{idx}]:{key}")
        _require_list(item["reason_codes"], f"movement_results[{idx}].reason_codes")
        _require_list(item["breakpoints"], f"movement_results[{idx}].breakpoints")
    return {
        "movement_count": len(payload),
    }


def check_movement_matrix_payload(payload: Any) -> dict[str, Any]:
    _require_object(payload, "movement_matrix")
    for key in ("intersection_id", "entry_approach_ids", "exit_approach_ids", "cells"):
        if key not in payload:
            raise ValueError(f"artifact_missing_key:movement_matrix:{key}")
    _require_list(payload["entry_approach_ids"], "movement_matrix.entry_approach_ids")
    _require_list(payload["exit_approach_ids"], "movement_matrix.exit_approach_ids")
    _require_object(payload["cells"], "movement_matrix.cells")

    cell_count = 0
    for entry_id in payload["entry_approach_ids"]:
        if entry_id not in payload["cells"]:
            raise ValueError(f"artifact_matrix_row_missing:{entry_id}")
        row = payload["cells"][entry_id]
        _require_object(row, f"movement_matrix.cells[{entry_id}]")
        for exit_id in payload["exit_approach_ids"]:
            if exit_id not in row:
                raise ValueError(f"artifact_matrix_cell_missing:{entry_id}:{exit_id}")
            _require_object(row[exit_id], f"movement_matrix.cells[{entry_id}][{exit_id}]")
            for key in ("source_approach_id", "target_approach_id", "status", "reason_codes", "breakpoints"):
                if key not in row[exit_id]:
                    raise ValueError(f"artifact_missing_key:movement_matrix.cell:{entry_id}:{exit_id}:{key}")
            cell_count += 1
    return {
        "intersection_id": payload["intersection_id"],
        "entry_count": len(payload["entry_approach_ids"]),
        "exit_count": len(payload["exit_approach_ids"]),
        "cell_count": cell_count,
    }


def check_patch_manifest_payload(payload: Any) -> dict[str, Any]:
    _require_object(payload, "patch_manifest")
    for key in ("patch_dir", "node_geojson_path", "road_geojson_path", "mainids"):
        if key not in payload:
            raise ValueError(f"artifact_missing_key:patch_manifest:{key}")
    items = payload.get("items", payload.get("runs"))
    if items is None:
        raise ValueError("artifact_missing_key:patch_manifest:items")
    _require_list(payload["mainids"], "patch_manifest.mainids")
    _require_list(items, "patch_manifest.items")
    manifest_mainids = [str(item) for item in payload["mainids"]]
    item_mainids: list[str] = []
    for idx, item in enumerate(items):
        _require_object(item, f"patch_manifest.items[{idx}]")
        for key in ("mainid", "status", "output_dir", "error"):
            if key not in item:
                raise ValueError(f"artifact_missing_key:patch_manifest.items[{idx}]:{key}")
        item_mainids.append(str(item["mainid"]))
    if manifest_mainids != item_mainids:
        raise ValueError("artifact_manifest_mainids_mismatch")
    return {
        "patch_dir": payload["patch_dir"],
        "mainids": list(payload["mainids"]),
        "items": list(items),
        "item_count": len(items),
    }


def _load_json_file(path: Path) -> Any:
    if not path.exists():
        raise ValueError(f"artifact_missing_file:{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"artifact_invalid_json:{path}:{exc.msg}") from exc


def _require_object(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"artifact_payload_must_be_object:{label}")


def _require_list(value: Any, label: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"artifact_payload_must_be_list:{label}")


def _mainid_dir_name(mainid: Any) -> str:
    text = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(mainid)).strip("_")
    if not text:
        text = "unknown"
    return f"mainid_{text}"


__all__ = [
    "check_movement_matrix_payload",
    "check_movement_results_payload",
    "check_patch_manifest_payload",
    "check_serialized_bundle_payload",
    "check_t10_patch_output_root",
    "check_t10_run_output_dir",
]
