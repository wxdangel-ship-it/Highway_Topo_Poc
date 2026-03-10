from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .api import T10PatchBatchRunResult, T10RunResult
from .manual_mode_support import write_t10_manual_support_outputs
from .override_roundtrip import write_override_roundtrip_report

_NON_ALNUM = re.compile(r"[^A-Za-z0-9._-]+")


def write_t10_run_result(
    result: T10RunResult,
    output_dir: str | Path,
    *,
    include_catalog: bool = False,
    include_override_template: bool = False,
    include_review: bool = False,
) -> dict[str, str]:
    resolved_dir = Path(output_dir)
    resolved_dir.mkdir(parents=True, exist_ok=True)

    serialized_bundle_path = resolved_dir / "serialized_bundle.json"
    movement_results_path = resolved_dir / "movement_results.json"
    movement_matrix_path = resolved_dir / "movement_matrix.json"
    summary_path = resolved_dir / "summary.txt"

    serialized_bundle_path.write_text(
        json.dumps(result.serialized_bundle, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    movement_results_path.write_text(
        json.dumps(list(result.movement_results), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    movement_matrix_path.write_text(
        json.dumps(result.matrix_view, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path.write_text(_build_summary_text(result), encoding="utf-8")

    written_files = {
        "serialized_bundle.json": str(serialized_bundle_path),
        "movement_results.json": str(movement_results_path),
        "movement_matrix.json": str(movement_matrix_path),
        "summary.txt": str(summary_path),
    }
    if include_catalog or include_override_template or include_review:
        written_files.update(
            write_t10_manual_support_outputs(
                result,
                resolved_dir,
                write_catalog=include_catalog,
                write_override_template=include_override_template,
                write_review=include_review,
            )
        )
    return written_files


def write_t10_review_bundle(
    result: T10RunResult,
    output_dir: str | Path,
    *,
    override_roundtrip_report: dict[str, Any] | None = None,
) -> dict[str, str]:
    written_files = write_t10_run_result(
        result,
        output_dir,
        include_catalog=True,
        include_override_template=True,
        include_review=True,
    )
    if override_roundtrip_report is not None:
        written_files.update(write_override_roundtrip_report(override_roundtrip_report, output_dir))
    return written_files


def write_t10_patch_batch_result(
    batch_result: T10PatchBatchRunResult,
    output_root: str | Path,
    *,
    include_catalog: bool = False,
    include_override_template: bool = False,
    include_review: bool = False,
) -> T10PatchBatchRunResult:
    resolved_root = Path(output_root)
    resolved_root.mkdir(parents=True, exist_ok=True)

    updated_items = []
    for item in batch_result.items:
        item_dir = resolved_root / _mainid_dir_name(item.mainid)
        item_dir.mkdir(parents=True, exist_ok=True)
        written_files: dict[str, str]
        if item.status == "success" and item.result is not None:
            written_files = write_t10_run_result(
                item.result,
                item_dir,
                include_catalog=include_catalog,
                include_override_template=include_override_template,
                include_review=include_review,
            )
        else:
            error_path = item_dir / "error.txt"
            error_path.write_text((item.error or "unknown_error") + "\n", encoding="utf-8")
            written_files = {"error.txt": str(error_path)}
        updated_items.append(
            replace(
                item,
                output_dir=str(item_dir),
                written_files=written_files,
            )
        )

    updated_batch = replace(
        batch_result,
        items=tuple(updated_items),
    )
    manifest_path = resolved_root / "manifest.json"
    summary_path = resolved_root / "summary.txt"
    manifest_path.write_text(
        json.dumps(_serialize_patch_batch_result(updated_batch), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path.write_text(_build_patch_batch_summary(updated_batch), encoding="utf-8")
    return replace(
        updated_batch,
        manifest_path=str(manifest_path),
        summary_path=str(summary_path),
    )


def write_t10_patch_review_bundle(
    batch_result: T10PatchBatchRunResult,
    output_root: str | Path,
) -> T10PatchBatchRunResult:
    return write_t10_patch_batch_result(
        batch_result,
        output_root,
        include_catalog=True,
        include_override_template=True,
        include_review=True,
    )


def _build_summary_text(result: T10RunResult) -> str:
    status_counts = Counter(decision.status for decision in result.decisions)
    breakpoint_counts = Counter(
        breakpoint_name
        for decision in result.decisions
        for breakpoint_name in decision.breakpoints
    )
    manual_override_used = any(
        approach.approach_profile_source in {"approach_override", "manual_service_profile_map", "manual_paired_mainline_map"}
        or approach.paired_mainline_source in {"approach_override", "manual_paired_mainline_map"}
        for approach in result.bundle.approaches
    )
    lines = [
        f"intersection_id: {result.bundle.intersection.intersection_id}",
        f"mainid: {result.bundle.intersection.node_group_id}",
        f"approach_count: {len(result.bundle.approaches)}",
        f"movement_count: {len(result.bundle.movements)}",
        f"manual_override_used: {str(manual_override_used).lower()}",
        "status_counts:",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"  {status}: {count}")
    lines.append("breakpoint_counts:")
    if breakpoint_counts:
        for breakpoint_name, count in sorted(breakpoint_counts.items()):
            lines.append(f"  {breakpoint_name}: {count}")
    else:
        lines.append("  none: 0")
    return "\n".join(lines) + "\n"


def _mainid_dir_name(mainid: Any) -> str:
    raw = _NON_ALNUM.sub("_", str(mainid)).strip("_")
    if not raw:
        raw = "unknown"
    return f"mainid_{raw}"


def _serialize_patch_batch_result(batch_result: T10PatchBatchRunResult) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for item in batch_result.items:
        movement_count = len(item.result.decisions) if item.result is not None else None
        status_counts = (
            dict(Counter(decision.status for decision in item.result.decisions))
            if item.result is not None
            else None
        )
        runs.append(
            {
                "mainid": item.mainid,
                "status": item.status,
                "output_dir": item.output_dir,
                "written_files": item.written_files,
                "error": item.error,
                "intersection_id": item.result.bundle.intersection.intersection_id if item.result else None,
                "movement_count": movement_count,
                "status_counts": status_counts,
            }
        )
    return {
        "patch_dir": batch_result.patch_dir,
        "node_geojson_path": batch_result.node_geojson_path,
        "road_geojson_path": batch_result.road_geojson_path,
        "mainids": list(batch_result.mainids),
        "items": runs,
        "runs": runs,
    }


def _build_patch_batch_summary(batch_result: T10PatchBatchRunResult) -> str:
    success_count = sum(1 for item in batch_result.items if item.status == "success")
    error_count = sum(1 for item in batch_result.items if item.status == "error")
    lines = [
        f"patch_dir: {batch_result.patch_dir}",
        f"node_geojson_path: {batch_result.node_geojson_path}",
        f"road_geojson_path: {batch_result.road_geojson_path}",
        f"mainid_count: {len(batch_result.mainids)}",
        f"success_count: {success_count}",
        f"error_count: {error_count}",
        "runs:",
    ]
    for item in batch_result.items:
        line = f"  - mainid={item.mainid} status={item.status}"
        if item.output_dir:
            line += f" output_dir={item.output_dir}"
        if item.error:
            line += f" error={item.error}"
        lines.append(line)
    return "\n".join(lines) + "\n"


__all__ = [
    "write_t10_patch_batch_result",
    "write_t10_patch_review_bundle",
    "write_t10_review_bundle",
    "write_t10_run_result",
]
