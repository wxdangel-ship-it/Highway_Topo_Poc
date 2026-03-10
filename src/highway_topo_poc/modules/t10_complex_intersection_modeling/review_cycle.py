from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .api import (
    T10PatchBatchRunResult,
    T10RunResult,
    run_t10_all_intersections_from_geojson_files,
    build_t10_patch_run_summary,
    run_t10_single_intersection_from_geojson_files,
    run_t10_single_intersection_from_patch_dir,
)
from .geojson_io import discover_patch_dir_inputs
from .manual_mode_support import build_approach_catalog
from .multi_patch import discover_patch_dirs
from .override_roundtrip import roundtrip_manual_override_source, write_override_roundtrip_report
from .run_diff import compare_t10_run_dirs, write_t10_run_diff_outputs
from .writer import write_t10_patch_review_bundle, write_t10_review_bundle


@dataclass(frozen=True)
class T10ReviewCycleResult:
    mode: str
    patch_dir: str
    mainid: Any | None
    all_mainids: bool
    manual_override_source: str | None
    validate_override: bool
    diff_against_dir: str | None
    base_result: T10RunResult | None = None
    base_batch_result: T10PatchBatchRunResult | None = None
    rerun_result: T10RunResult | None = None
    rerun_batch_result: T10PatchBatchRunResult | None = None
    override_roundtrip: dict[str, Any] | None = None
    diff_payload: dict[str, Any] | None = None
    base_output_dir: str | None = None
    rerun_output_dir: str | None = None
    diff_output_dir: str | None = None
    manifest_path: str | None = None
    summary_path: str | None = None
    written_files: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class T10PatchRootReviewCycleItem:
    patch_name: str
    patch_dir: str
    status: str
    cycle_result: T10ReviewCycleResult | None
    error: str | None = None
    output_dir: str | None = None
    manifest_path: str | None = None
    summary_path: str | None = None
    written_files: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class T10PatchRootReviewCycleResult:
    patch_root: str
    patch_names: tuple[str, ...]
    override_root: str | None
    validate_override: bool
    items: tuple[T10PatchRootReviewCycleItem, ...]
    manifest_path: str | None = None
    summary_path: str | None = None


def run_t10_review_cycle_from_patch_dir(
    *,
    patch_dir: str | Path,
    mainid: Any | None = None,
    all_mainids: bool = False,
    manual_override_source: str | Path | dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    validate_override: bool = False,
    diff_against_dir: str | Path | None = None,
    source_type: str = "real",
    approach_overrides: dict[str, dict[str, Any]] | None = None,
) -> T10ReviewCycleResult:
    node_geojson_path, road_geojson_path = discover_patch_dir_inputs(patch_dir)
    result = run_t10_review_cycle_from_geojson_files(
        node_geojson_path=node_geojson_path,
        road_geojson_path=road_geojson_path,
        mainid=mainid,
        all_mainids=all_mainids,
        manual_override_source=manual_override_source,
        output_dir=output_dir,
        validate_override=validate_override,
        diff_against_dir=diff_against_dir,
        source_type=source_type,
        approach_overrides=approach_overrides,
    )
    return replace(result, patch_dir=str(Path(patch_dir)))


def run_t10_review_cycle_from_geojson_files(
    *,
    node_geojson_path: str | Path,
    road_geojson_path: str | Path,
    mainid: Any | None = None,
    all_mainids: bool = False,
    manual_override_source: str | Path | dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    validate_override: bool = False,
    diff_against_dir: str | Path | None = None,
    source_type: str = "real",
    approach_overrides: dict[str, dict[str, Any]] | None = None,
) -> T10ReviewCycleResult:
    patch_dir_text = str(Path(node_geojson_path).parent)
    manual_override_label = (
        None
        if manual_override_source is None
        else str(manual_override_source)
        if isinstance(manual_override_source, (str, Path))
        else "dict"
    )
    diff_against_label = None if diff_against_dir is None else str(Path(diff_against_dir))
    mode = "patch_batch" if all_mainids else "single_intersection"

    base_output_dir = str(Path(output_dir) / "base") if output_dir is not None else None
    rerun_output_dir = str(Path(output_dir) / "rerun") if output_dir is not None else None
    diff_output_dir = str(Path(output_dir) / "diff") if output_dir is not None else None

    base_result: T10RunResult | None = None
    base_batch_result: T10PatchBatchRunResult | None = None
    rerun_result: T10RunResult | None = None
    rerun_batch_result: T10PatchBatchRunResult | None = None
    override_roundtrip: dict[str, Any] | None = None
    diff_payload: dict[str, Any] | None = None
    written_files: dict[str, Any] = {}

    if all_mainids:
        base_batch_result = run_t10_all_intersections_from_geojson_files(
            node_geojson_path=node_geojson_path,
            road_geojson_path=road_geojson_path,
            source_type=source_type,
            approach_overrides=approach_overrides,
        )
        if base_output_dir is not None:
            base_batch_result = write_t10_patch_review_bundle(base_batch_result, base_output_dir)
            written_files["base"] = {
                "output_dir": base_output_dir,
                "manifest_path": base_batch_result.manifest_path,
                "summary_path": base_batch_result.summary_path,
            }

        if manual_override_source is not None:
            if validate_override:
                override_roundtrip = roundtrip_manual_override_source(
                    manual_override_source=manual_override_source,
                    approach_catalog=_build_patch_batch_catalog(base_batch_result),
                )
            rerun_batch_result = run_t10_all_intersections_from_geojson_files(
                node_geojson_path=node_geojson_path,
                road_geojson_path=road_geojson_path,
                manual_override_source=manual_override_source,
                source_type=source_type,
                approach_overrides=approach_overrides,
            )
            if rerun_output_dir is not None:
                rerun_batch_result = write_t10_patch_review_bundle(rerun_batch_result, rerun_output_dir)
                written_files["rerun"] = {
                    "output_dir": rerun_output_dir,
                    "manifest_path": rerun_batch_result.manifest_path,
                    "summary_path": rerun_batch_result.summary_path,
                }
                if override_roundtrip is not None:
                    written_files.setdefault("rerun", {}).update(
                        write_override_roundtrip_report(override_roundtrip, rerun_output_dir)
                    )

        diff_before_root = diff_against_label
        diff_after_root = None
        if rerun_batch_result is not None and rerun_output_dir is not None:
            diff_after_root = rerun_output_dir
            if diff_before_root is None and base_output_dir is not None:
                diff_before_root = base_output_dir
        elif diff_before_root is not None and base_output_dir is not None:
            diff_after_root = base_output_dir

        if diff_before_root is not None and diff_after_root is not None:
            diff_payload = compare_t10_patch_batch_output_dirs(diff_before_root, diff_after_root)
            if diff_output_dir is not None:
                written_files["diff"] = write_t10_patch_batch_diff_outputs(diff_payload, diff_output_dir)
    else:
        base_result = run_t10_single_intersection_from_geojson_files(
            node_geojson_path=node_geojson_path,
            road_geojson_path=road_geojson_path,
            mainid=mainid,
            source_type=source_type,
            approach_overrides=approach_overrides,
        )
        if base_output_dir is not None:
            written_files["base"] = write_t10_review_bundle(base_result, base_output_dir)

        if manual_override_source is not None:
            if validate_override:
                override_roundtrip = roundtrip_manual_override_source(
                manual_override_source=manual_override_source,
                approach_catalog=build_approach_catalog(base_result),
            )
            rerun_result = run_t10_single_intersection_from_geojson_files(
                node_geojson_path=node_geojson_path,
                road_geojson_path=road_geojson_path,
                mainid=mainid,
                manual_override_source=manual_override_source,
                source_type=source_type,
                approach_overrides=approach_overrides,
            )
            if rerun_output_dir is not None:
                written_files["rerun"] = write_t10_review_bundle(
                    rerun_result,
                    rerun_output_dir,
                    override_roundtrip_report=override_roundtrip if validate_override else None,
                )

        diff_before_root = diff_against_label
        diff_after_root = None
        if rerun_result is not None and rerun_output_dir is not None:
            diff_after_root = rerun_output_dir
            if diff_before_root is None and base_output_dir is not None:
                diff_before_root = base_output_dir
        elif diff_before_root is not None and base_output_dir is not None:
            diff_after_root = base_output_dir

        if diff_before_root is not None and diff_after_root is not None:
            diff_payload = compare_t10_run_dirs(diff_before_root, diff_after_root)
            if diff_output_dir is not None:
                written_files["diff"] = write_t10_run_diff_outputs(diff_payload, diff_output_dir)

    result = T10ReviewCycleResult(
        mode=mode,
        patch_dir=patch_dir_text,
        mainid=mainid,
        all_mainids=all_mainids,
        manual_override_source=manual_override_label,
        validate_override=validate_override,
        diff_against_dir=diff_against_label,
        base_result=base_result,
        base_batch_result=base_batch_result,
        rerun_result=rerun_result,
        rerun_batch_result=rerun_batch_result,
        override_roundtrip=override_roundtrip,
        diff_payload=diff_payload,
        base_output_dir=base_output_dir,
        rerun_output_dir=rerun_output_dir if (rerun_result or rerun_batch_result) else None,
        diff_output_dir=diff_output_dir if diff_payload is not None else None,
        written_files=written_files,
    )
    if output_dir is not None:
        result = _write_review_cycle_manifest(result, output_dir)
    return result


def run_t10_review_cycle_from_patch_root(
    *,
    patch_root: str | Path,
    patch_names: list[str] | tuple[str, ...] | None = None,
    override_root: str | Path | None = None,
    output_root: str | Path | None = None,
    validate_override: bool = False,
    source_type: str = "real",
    approach_overrides: dict[str, dict[str, Any]] | None = None,
) -> T10PatchRootReviewCycleResult:
    patch_entries = discover_patch_dirs(patch_root, patch_names=patch_names)
    override_root_path = _validate_override_root(override_root)
    items: list[T10PatchRootReviewCycleItem] = []

    for patch_name, patch_dir in patch_entries:
        patch_output_dir = Path(output_root) / patch_name if output_root is not None else None
        patch_override = _resolve_patch_override_source(override_root_path, patch_name)
        try:
            cycle_result = run_t10_review_cycle_from_patch_dir(
                patch_dir=patch_dir,
                all_mainids=True,
                manual_override_source=patch_override,
                output_dir=patch_output_dir,
                validate_override=validate_override and patch_override is not None,
                source_type=source_type,
                approach_overrides=approach_overrides,
            )
        except Exception as exc:
            written_files: dict[str, Any] = {}
            if patch_output_dir is not None:
                patch_output_dir.mkdir(parents=True, exist_ok=True)
                error_path = patch_output_dir / "error.txt"
                error_path.write_text(str(exc) + "\n", encoding="utf-8")
                written_files["error.txt"] = str(error_path)
            items.append(
                T10PatchRootReviewCycleItem(
                    patch_name=patch_name,
                    patch_dir=str(patch_dir),
                    status="error",
                    cycle_result=None,
                    error=str(exc),
                    output_dir=str(patch_output_dir) if patch_output_dir is not None else None,
                    written_files=written_files,
                )
            )
            continue

        items.append(
            T10PatchRootReviewCycleItem(
                patch_name=patch_name,
                patch_dir=str(patch_dir),
                status="success",
                cycle_result=cycle_result,
                output_dir=str(patch_output_dir) if patch_output_dir is not None else None,
                manifest_path=cycle_result.manifest_path,
                summary_path=cycle_result.summary_path,
                written_files=cycle_result.written_files,
            )
        )

    result = T10PatchRootReviewCycleResult(
        patch_root=str(Path(patch_root)),
        patch_names=tuple(name for name, _ in patch_entries),
        override_root=str(override_root_path) if override_root_path is not None else None,
        validate_override=validate_override,
        items=tuple(items),
    )
    if output_root is not None:
        result = _write_patch_root_review_cycle_manifest(result, output_root)
    return result


def build_t10_review_cycle_summary(result: T10ReviewCycleResult) -> dict[str, Any]:
    base_summary = None
    rerun_summary = None
    if result.base_result is not None:
        base_summary = _single_result_summary(result.base_result)
    elif result.base_batch_result is not None:
        base_summary = build_t10_patch_run_summary(result.base_batch_result)
    if result.rerun_result is not None:
        rerun_summary = _single_result_summary(result.rerun_result)
    elif result.rerun_batch_result is not None:
        rerun_summary = build_t10_patch_run_summary(result.rerun_batch_result)
    return {
        "mode": result.mode,
        "patch_dir": result.patch_dir,
        "mainid": result.mainid,
        "all_mainids": result.all_mainids,
        "manual_override_source": result.manual_override_source,
        "validate_override": result.validate_override,
        "diff_against_dir": result.diff_against_dir,
        "base_output_dir": result.base_output_dir,
        "rerun_output_dir": result.rerun_output_dir,
        "diff_output_dir": result.diff_output_dir,
        "base": base_summary,
        "rerun": rerun_summary,
        "override_roundtrip": result.override_roundtrip,
        "diff_summary": _summarize_diff_payload(result.diff_payload),
        "manifest_path": result.manifest_path,
        "summary_path": result.summary_path,
        "written_files": result.written_files,
    }


def build_t10_patch_root_review_cycle_summary(result: T10PatchRootReviewCycleResult) -> dict[str, Any]:
    return {
        "patch_root": result.patch_root,
        "override_root": result.override_root,
        "validate_override": result.validate_override,
        "patch_names": list(result.patch_names),
        "items": [
            {
                "patch_name": item.patch_name,
                "patch_dir": item.patch_dir,
                "status": item.status,
                "error": item.error,
                "output_dir": item.output_dir,
                "manifest_path": item.manifest_path,
                "summary_path": item.summary_path,
                "cycle_mode": item.cycle_result.mode if item.cycle_result is not None else None,
                "has_rerun": bool(item.cycle_result and (item.cycle_result.rerun_result or item.cycle_result.rerun_batch_result)),
                "has_diff": item.cycle_result.diff_payload is not None if item.cycle_result is not None else False,
            }
            for item in result.items
        ],
        "manifest_path": result.manifest_path,
        "summary_path": result.summary_path,
    }


def compare_t10_patch_batch_output_dirs(
    before_root: str | Path,
    after_root: str | Path,
) -> dict[str, Any]:
    before_root_path = Path(before_root)
    after_root_path = Path(after_root)
    before_manifest = _load_json_file(before_root_path / "manifest.json", label="before_manifest")
    after_manifest = _load_json_file(after_root_path / "manifest.json", label="after_manifest")

    before_items = _index_patch_manifest_items(before_manifest)
    after_items = _index_patch_manifest_items(after_manifest)

    items: list[dict[str, Any]] = []
    total_status_changes = 0
    total_movement_changes = 0
    total_reason_changes = 0
    for mainid_text in sorted(set(before_items) | set(after_items)):
        before_item = before_items.get(mainid_text)
        after_item = after_items.get(mainid_text)
        if before_item is None or after_item is None:
            total_status_changes += 1
            items.append(
                {
                    "mainid": mainid_text,
                    "diff_mode": "presence_changed",
                    "before_present": before_item is not None,
                    "after_present": after_item is not None,
                    "before_status": before_item.get("status") if before_item else None,
                    "after_status": after_item.get("status") if after_item else None,
                }
            )
            continue

        before_status = before_item.get("status")
        after_status = after_item.get("status")
        before_dir = _resolve_manifest_item_output_dir(before_root_path, before_item)
        after_dir = _resolve_manifest_item_output_dir(after_root_path, after_item)
        if before_status != after_status or before_status != "success" or after_status != "success":
            total_status_changes += 1
            items.append(
                {
                    "mainid": mainid_text,
                    "diff_mode": "status_only",
                    "before_status": before_status,
                    "after_status": after_status,
                    "before_output_dir": str(before_dir),
                    "after_output_dir": str(after_dir),
                }
            )
            continue

        run_diff = compare_t10_run_dirs(before_dir, after_dir)
        total_movement_changes += run_diff["movement_status_change_count"]
        total_reason_changes += run_diff["movement_primary_reason_change_count"]
        items.append(
            {
                "mainid": mainid_text,
                "diff_mode": "run_diff",
                "before_status": before_status,
                "after_status": after_status,
                "before_output_dir": str(before_dir),
                "after_output_dir": str(after_dir),
                "movement_status_change_count": run_diff["movement_status_change_count"],
                "movement_primary_reason_change_count": run_diff["movement_primary_reason_change_count"],
                "run_diff": run_diff,
            }
        )

    return {
        "before_root": str(before_root_path),
        "after_root": str(after_root_path),
        "mainid_count": len(items),
        "status_change_count": total_status_changes,
        "movement_status_change_count": total_movement_changes,
        "movement_primary_reason_change_count": total_reason_changes,
        "items": items,
    }


def write_t10_patch_batch_diff_outputs(
    diff_payload: dict[str, Any],
    output_root: str | Path,
) -> dict[str, Any]:
    resolved_root = Path(output_root)
    resolved_root.mkdir(parents=True, exist_ok=True)
    item_dirs: dict[str, Any] = {}
    for item in diff_payload["items"]:
        mainid_dir = resolved_root / _mainid_dir_name(item["mainid"])
        mainid_dir.mkdir(parents=True, exist_ok=True)
        if item["diff_mode"] == "run_diff":
            item_dirs[str(item["mainid"])] = write_t10_run_diff_outputs(item["run_diff"], mainid_dir)
        else:
            item_diff_path = mainid_dir / "item_diff.json"
            item_summary_path = mainid_dir / "item_summary.txt"
            item_diff_path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
            item_summary_path.write_text(_build_batch_diff_item_summary(item), encoding="utf-8")
            item_dirs[str(item["mainid"])] = {
                "item_diff.json": str(item_diff_path),
                "item_summary.txt": str(item_summary_path),
            }

    manifest_path = resolved_root / "manifest.json"
    summary_path = resolved_root / "summary.txt"
    manifest_path.write_text(json.dumps(diff_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(_build_batch_diff_summary(diff_payload), encoding="utf-8")
    return {
        "manifest.json": str(manifest_path),
        "summary.txt": str(summary_path),
        "items": item_dirs,
    }


def _build_patch_batch_catalog(batch_result: T10PatchBatchRunResult) -> dict[str, Any]:
    approaches: list[dict[str, Any]] = []
    intersection_ids: list[str] = []
    mainids: list[Any] = []
    for item in batch_result.items:
        if item.status != "success" or item.result is None:
            continue
        catalog = build_approach_catalog(item.result)
        intersection_ids.append(catalog["intersection_id"])
        mainids.append(catalog["mainid"])
        approaches.extend(catalog["approaches"])
    return {
        "intersection_id": intersection_ids[0] if len(intersection_ids) == 1 else None,
        "mainid": mainids[0] if len(mainids) == 1 else None,
        "approach_count": len(approaches),
        "approaches": approaches,
    }


def _write_review_cycle_manifest(
    result: T10ReviewCycleResult,
    output_dir: str | Path,
) -> T10ReviewCycleResult:
    resolved_root = Path(output_dir)
    resolved_root.mkdir(parents=True, exist_ok=True)
    manifest_path = resolved_root / "manifest.json"
    summary_path = resolved_root / "summary.txt"
    manifest_payload = build_t10_review_cycle_summary(result)
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(_build_review_cycle_summary_text(result), encoding="utf-8")
    return replace(result, manifest_path=str(manifest_path), summary_path=str(summary_path))


def _write_patch_root_review_cycle_manifest(
    result: T10PatchRootReviewCycleResult,
    output_root: str | Path,
) -> T10PatchRootReviewCycleResult:
    resolved_root = Path(output_root)
    resolved_root.mkdir(parents=True, exist_ok=True)
    manifest_path = resolved_root / "manifest.json"
    summary_path = resolved_root / "summary.txt"
    manifest_payload = build_t10_patch_root_review_cycle_summary(result)
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(_build_patch_root_review_cycle_summary_text(result), encoding="utf-8")
    return replace(result, manifest_path=str(manifest_path), summary_path=str(summary_path))


def _single_result_summary(result: T10RunResult) -> dict[str, Any]:
    return {
        "intersection_id": result.bundle.intersection.intersection_id,
        "mainid": result.bundle.intersection.node_group_id,
        "approach_count": len(result.bundle.approaches),
        "movement_count": len(result.decisions),
    }


def _summarize_diff_payload(diff_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if diff_payload is None:
        return None
    summary = {
        "movement_status_change_count": diff_payload.get("movement_status_change_count"),
        "movement_primary_reason_change_count": diff_payload.get("movement_primary_reason_change_count"),
    }
    if "mainid_count" in diff_payload:
        summary.update(
            {
                "mainid_count": diff_payload.get("mainid_count"),
                "status_change_count": diff_payload.get("status_change_count"),
            }
        )
    return summary


def _build_review_cycle_summary_text(result: T10ReviewCycleResult) -> str:
    lines = [
        f"mode: {result.mode}",
        f"patch_dir: {result.patch_dir}",
        f"all_mainids: {str(result.all_mainids).lower()}",
        f"mainid: {result.mainid}",
        f"manual_override_source: {result.manual_override_source}",
        f"validate_override: {str(result.validate_override).lower()}",
        f"base_output_dir: {result.base_output_dir}",
        f"rerun_output_dir: {result.rerun_output_dir}",
        f"diff_output_dir: {result.diff_output_dir}",
    ]
    if result.diff_payload is not None:
        diff_summary = _summarize_diff_payload(result.diff_payload) or {}
        for key, value in diff_summary.items():
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


def _build_patch_root_review_cycle_summary_text(result: T10PatchRootReviewCycleResult) -> str:
    success_count = sum(1 for item in result.items if item.status == "success")
    error_count = sum(1 for item in result.items if item.status == "error")
    lines = [
        f"patch_root: {result.patch_root}",
        f"patch_count: {len(result.patch_names)}",
        f"success_count: {success_count}",
        f"error_count: {error_count}",
        "items:",
    ]
    for item in result.items:
        line = f"  - patch={item.patch_name} status={item.status}"
        if item.output_dir:
            line += f" output_dir={item.output_dir}"
        if item.error:
            line += f" error={item.error}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _build_batch_diff_item_summary(item: dict[str, Any]) -> str:
    lines = [
        f"mainid: {item['mainid']}",
        f"diff_mode: {item['diff_mode']}",
        f"before_status: {item.get('before_status')}",
        f"after_status: {item.get('after_status')}",
    ]
    if "movement_status_change_count" in item:
        lines.append(f"movement_status_change_count: {item['movement_status_change_count']}")
    return "\n".join(lines) + "\n"


def _build_batch_diff_summary(diff_payload: dict[str, Any]) -> str:
    lines = [
        f"before_root: {diff_payload['before_root']}",
        f"after_root: {diff_payload['after_root']}",
        f"mainid_count: {diff_payload['mainid_count']}",
        f"status_change_count: {diff_payload['status_change_count']}",
        f"movement_status_change_count: {diff_payload['movement_status_change_count']}",
        f"movement_primary_reason_change_count: {diff_payload['movement_primary_reason_change_count']}",
    ]
    return "\n".join(lines) + "\n"


def _load_json_file(path: Path, *, label: str) -> Any:
    if not path.exists():
        raise ValueError(f"review_cycle_missing_file:{label}:{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"review_cycle_invalid_json:{label}:{path}:{exc.msg}") from exc


def _index_patch_manifest_items(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = payload.get("items", payload.get("runs"))
    if not isinstance(items, list):
        raise ValueError("review_cycle_patch_manifest_items_missing")
    return {str(item["mainid"]): item for item in items if isinstance(item, dict) and "mainid" in item}


def _resolve_manifest_item_output_dir(root_dir: Path, item: dict[str, Any]) -> Path:
    output_dir = item.get("output_dir")
    if isinstance(output_dir, str) and output_dir:
        return Path(output_dir)
    return root_dir / _mainid_dir_name(item.get("mainid"))


def _mainid_dir_name(mainid: Any) -> str:
    text = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(mainid)).strip("_")
    if not text:
        text = "unknown"
    return f"mainid_{text}"


def _validate_override_root(override_root: str | Path | None) -> Path | None:
    if override_root is None:
        return None
    resolved = Path(override_root)
    if not resolved.exists():
        raise ValueError(f"override_root_not_found:{resolved}")
    if not resolved.is_dir():
        raise ValueError(f"override_root_not_directory:{resolved}")
    return resolved


def _resolve_patch_override_source(override_root: Path | None, patch_name: str) -> Path | None:
    if override_root is None:
        return None
    candidate = override_root / f"{patch_name}.json"
    if candidate.is_file():
        return candidate
    return None


__all__ = [
    "T10PatchRootReviewCycleItem",
    "T10PatchRootReviewCycleResult",
    "T10ReviewCycleResult",
    "build_t10_patch_root_review_cycle_summary",
    "build_t10_review_cycle_summary",
    "compare_t10_patch_batch_output_dirs",
    "run_t10_review_cycle_from_geojson_files",
    "run_t10_review_cycle_from_patch_dir",
    "run_t10_review_cycle_from_patch_root",
    "write_t10_patch_batch_diff_outputs",
]
