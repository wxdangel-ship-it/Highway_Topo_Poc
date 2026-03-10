from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .visual_review import write_t10_run_diff_html


def compare_t10_run_dirs(
    before_dir: str | Path,
    after_dir: str | Path,
) -> dict[str, Any]:
    resolved_before = Path(before_dir)
    resolved_after = Path(after_dir)
    before_movement_results = _load_required_json(resolved_before / "movement_results.json", "movement_results")
    after_movement_results = _load_required_json(resolved_after / "movement_results.json", "movement_results")
    before_matrix = _load_required_json(resolved_before / "movement_matrix.json", "movement_matrix")
    after_matrix = _load_required_json(resolved_after / "movement_matrix.json", "movement_matrix")

    before_unknown = _load_optional_json(resolved_before / "review_unknown_movements.json")
    after_unknown = _load_optional_json(resolved_after / "review_unknown_movements.json")
    before_nonstandard = _load_optional_json(resolved_before / "review_nonstandard_targets.json")
    after_nonstandard = _load_optional_json(resolved_after / "review_nonstandard_targets.json")
    before_profile_gap = _load_optional_json(resolved_before / "review_special_profile_gaps.json")
    after_profile_gap = _load_optional_json(resolved_after / "review_special_profile_gaps.json")

    before_movements = _movement_index(before_movement_results)
    after_movements = _movement_index(after_movement_results)

    movement_status_changes: list[dict[str, Any]] = []
    movement_primary_reason_changes: list[dict[str, Any]] = []

    for movement_id in sorted(set(before_movements) | set(after_movements)):
        before = before_movements.get(movement_id)
        after = after_movements.get(movement_id)
        if before is None or after is None:
            movement_status_changes.append(
                {
                    "movement_id": movement_id,
                    "change_type": "movement_presence_changed",
                    "before_present": before is not None,
                    "after_present": after is not None,
                    "source_approach_id": before.get("source_approach_id") if before else after.get("source_approach_id"),
                    "target_approach_id": before.get("target_approach_id") if before else after.get("target_approach_id"),
                }
            )
            continue
        if before["status"] != after["status"]:
            movement_status_changes.append(
                {
                    "movement_id": movement_id,
                    "source_approach_id": before["source_approach_id"],
                    "target_approach_id": before["target_approach_id"],
                    "before_status": before["status"],
                    "after_status": after["status"],
                    "before_primary_reason_code": _primary_reason_code(before),
                    "after_primary_reason_code": _primary_reason_code(after),
                }
            )
        if _primary_reason_code(before) != _primary_reason_code(after):
            movement_primary_reason_changes.append(
                {
                    "movement_id": movement_id,
                    "source_approach_id": before["source_approach_id"],
                    "target_approach_id": before["target_approach_id"],
                    "before_status": before["status"],
                    "after_status": after["status"],
                    "before_primary_reason_code": _primary_reason_code(before),
                    "after_primary_reason_code": _primary_reason_code(after),
                }
            )

    review_changes = {
        "unknown_movements": _review_count_change(
            before_unknown,
            after_unknown,
            count_key="unknown_movement_count",
        ),
        "nonstandard_targets": _review_count_change(
            before_nonstandard,
            after_nonstandard,
            count_key="target_count",
        ),
        "special_profile_gaps": _review_count_change(
            before_profile_gap,
            after_profile_gap,
            count_key="candidate_count",
        ),
    }

    matrix_changes = {
        "before_intersection_id": before_matrix.get("intersection_id"),
        "after_intersection_id": after_matrix.get("intersection_id"),
        "before_entry_count": len(before_matrix.get("entry_approach_ids", [])),
        "after_entry_count": len(after_matrix.get("entry_approach_ids", [])),
        "before_exit_count": len(before_matrix.get("exit_approach_ids", [])),
        "after_exit_count": len(after_matrix.get("exit_approach_ids", [])),
        "before_cell_count": _matrix_cell_count(before_matrix),
        "after_cell_count": _matrix_cell_count(after_matrix),
    }

    return {
        "before_dir": str(resolved_before),
        "after_dir": str(resolved_after),
        "movement_status_change_count": len(movement_status_changes),
        "movement_primary_reason_change_count": len(movement_primary_reason_changes),
        "movement_status_changes": movement_status_changes,
        "movement_primary_reason_changes": movement_primary_reason_changes,
        "review_changes": review_changes,
        "matrix_changes": matrix_changes,
    }


def write_t10_run_diff_outputs(
    diff_payload: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, str]:
    resolved_dir = Path(output_dir)
    resolved_dir.mkdir(parents=True, exist_ok=True)
    diff_path = resolved_dir / "run_diff.json"
    summary_path = resolved_dir / "run_diff_summary.txt"
    diff_path.write_text(json.dumps(diff_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(_build_run_diff_summary(diff_payload), encoding="utf-8")
    written_files = {
        "run_diff.json": str(diff_path),
        "run_diff_summary.txt": str(summary_path),
    }
    written_files.update(write_t10_run_diff_html(diff_payload, resolved_dir))
    return written_files


def compare_t10_run_dirs_and_write_outputs(
    before_dir: str | Path,
    after_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    diff_payload = compare_t10_run_dirs(before_dir, after_dir)
    written_files = write_t10_run_diff_outputs(diff_payload, output_dir)
    return {
        **diff_payload,
        "written_files": written_files,
    }


def _load_required_json(path: Path, label: str) -> Any:
    if not path.exists():
        raise ValueError(f"run_diff_missing_file:{label}:{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"run_diff_invalid_json:{label}:{path}:{exc.msg}") from exc


def _load_optional_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"run_diff_invalid_json:optional:{path}:{exc.msg}") from exc


def _movement_index(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("run_diff_payload_must_be_list:movement_results")
    index: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("run_diff_payload_must_be_object:movement_results.item")
        movement_id = item.get("movement_id")
        if not isinstance(movement_id, str):
            raise ValueError("run_diff_missing_key:movement_results.item:movement_id")
        index[movement_id] = item
    return index


def _primary_reason_code(item: dict[str, Any]) -> str | None:
    reason_codes = item.get("reason_codes", [])
    if isinstance(reason_codes, list) and reason_codes:
        first = reason_codes[0]
        if isinstance(first, str):
            return first
    return None


def _review_count_change(before_payload: Any | None, after_payload: Any | None, *, count_key: str) -> dict[str, Any]:
    before_count = before_payload.get(count_key) if isinstance(before_payload, dict) else None
    after_count = after_payload.get(count_key) if isinstance(after_payload, dict) else None
    delta = None
    if isinstance(before_count, int) and isinstance(after_count, int):
        delta = after_count - before_count
    return {
        "before_count": before_count,
        "after_count": after_count,
        "delta": delta,
        "before_present": before_payload is not None,
        "after_present": after_payload is not None,
    }


def _matrix_cell_count(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    cells = payload.get("cells")
    if not isinstance(cells, dict):
        return None
    total = 0
    for row in cells.values():
        if isinstance(row, dict):
            total += len(row)
    return total


def _build_run_diff_summary(diff_payload: dict[str, Any]) -> str:
    review_changes = diff_payload["review_changes"]
    lines = [
        f"before_dir: {diff_payload['before_dir']}",
        f"after_dir: {diff_payload['after_dir']}",
        f"movement_status_change_count: {diff_payload['movement_status_change_count']}",
        f"movement_primary_reason_change_count: {diff_payload['movement_primary_reason_change_count']}",
        "review_changes:",
        (
            "  - unknown_movements: "
            f"{review_changes['unknown_movements']['before_count']} -> {review_changes['unknown_movements']['after_count']}"
        ),
        (
            "  - nonstandard_targets: "
            f"{review_changes['nonstandard_targets']['before_count']} -> {review_changes['nonstandard_targets']['after_count']}"
        ),
        (
            "  - special_profile_gaps: "
            f"{review_changes['special_profile_gaps']['before_count']} -> {review_changes['special_profile_gaps']['after_count']}"
        ),
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "compare_t10_run_dirs",
    "compare_t10_run_dirs_and_write_outputs",
    "write_t10_run_diff_outputs",
]
