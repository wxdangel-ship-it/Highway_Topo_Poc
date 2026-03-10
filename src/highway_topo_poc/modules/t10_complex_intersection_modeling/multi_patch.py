from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .api import T10PatchBatchRunResult, run_t10_all_intersections_from_patch_dir


@dataclass(frozen=True)
class T10MultiPatchRunItem:
    patch_name: str
    patch_dir: str
    status: str
    patch_result: T10PatchBatchRunResult | None
    error: str | None = None
    output_dir: str | None = None
    written_files: dict[str, str] = field(default_factory=dict)
    patch_manifest_path: str | None = None
    patch_summary_path: str | None = None


@dataclass(frozen=True)
class T10MultiPatchRunResult:
    patch_root: str
    patch_names: tuple[str, ...]
    override_root: str | None
    items: tuple[T10MultiPatchRunItem, ...]
    manifest_path: str | None = None
    summary_path: str | None = None


def discover_patch_dirs(
    patch_root: str | Path,
    *,
    patch_names: list[str] | tuple[str, ...] | None = None,
) -> list[tuple[str, Path]]:
    resolved_root = Path(patch_root)
    if not resolved_root.exists():
        raise ValueError(f"patch_root_not_found:{resolved_root}")
    if not resolved_root.is_dir():
        raise ValueError(f"patch_root_not_directory:{resolved_root}")

    available = sorted((item.name, item) for item in resolved_root.iterdir() if item.is_dir())
    if not available:
        raise ValueError(f"patch_root_no_patch_dirs_found:{resolved_root}")
    available_names = [name for name, _ in available]
    if patch_names is None:
        return available

    requested = [str(name) for name in patch_names]
    missing = [name for name in requested if name not in set(available_names)]
    if missing:
        raise ValueError(
            f"requested_patch_dir_not_found:{','.join(missing)}:available={','.join(available_names)}"
        )
    by_name = {name: path for name, path in available}
    return [(name, by_name[name]) for name in requested]


def run_t10_multi_patch_manual_mode(
    *,
    patch_root: str | Path,
    patch_names: list[str] | tuple[str, ...] | None = None,
    manual_override_root: str | Path | None = None,
    output_root: str | Path | None = None,
    source_type: str = "real",
    approach_overrides: dict[str, dict[str, Any]] | None = None,
    include_catalog: bool = False,
    include_override_template: bool = False,
    include_review: bool = False,
) -> T10MultiPatchRunResult:
    patch_entries = discover_patch_dirs(patch_root, patch_names=patch_names)
    override_root_path = _validate_override_root(manual_override_root)

    items: list[T10MultiPatchRunItem] = []
    for patch_name, patch_dir in patch_entries:
        manual_override_source = _resolve_patch_override_source(override_root_path, patch_name)
        patch_output_dir = Path(output_root) / patch_name if output_root is not None else None
        try:
            patch_result = run_t10_all_intersections_from_patch_dir(
                patch_dir=patch_dir,
                manual_override_source=manual_override_source,
                source_type=source_type,
                approach_overrides=approach_overrides,
                output_root=patch_output_dir,
                include_catalog=include_catalog,
                include_override_template=include_override_template,
                include_review=include_review,
            )
        except Exception as exc:
            written_files: dict[str, str] = {}
            output_dir_text = None
            if patch_output_dir is not None:
                patch_output_dir.mkdir(parents=True, exist_ok=True)
                error_path = patch_output_dir / "error.txt"
                error_path.write_text(str(exc) + "\n", encoding="utf-8")
                written_files = {"error.txt": str(error_path)}
                output_dir_text = str(patch_output_dir)
            items.append(
                T10MultiPatchRunItem(
                    patch_name=patch_name,
                    patch_dir=str(patch_dir),
                    status="error",
                    patch_result=None,
                    error=str(exc),
                    output_dir=output_dir_text,
                    written_files=written_files,
                )
            )
            continue

        items.append(
            T10MultiPatchRunItem(
                patch_name=patch_name,
                patch_dir=str(patch_dir),
                status="success",
                patch_result=patch_result,
                output_dir=str(patch_output_dir) if patch_output_dir is not None else None,
                patch_manifest_path=patch_result.manifest_path,
                patch_summary_path=patch_result.summary_path,
            )
        )

    result = T10MultiPatchRunResult(
        patch_root=str(Path(patch_root)),
        patch_names=tuple(name for name, _ in patch_entries),
        override_root=str(override_root_path) if override_root_path is not None else None,
        items=tuple(items),
    )
    if output_root is not None:
        result = write_t10_multi_patch_result(result, output_root)
    return result


def build_t10_multi_patch_summary(result: T10MultiPatchRunResult) -> dict[str, Any]:
    return {
        "patch_root": result.patch_root,
        "override_root": result.override_root,
        "patch_names": list(result.patch_names),
        "items": [
            {
                "patch_name": item.patch_name,
                "patch_dir": item.patch_dir,
                "status": item.status,
                "output_dir": item.output_dir,
                "error": item.error,
                "mainids": list(item.patch_result.mainids) if item.patch_result is not None else None,
                "mainid_item_count": len(item.patch_result.items) if item.patch_result is not None else None,
                "patch_manifest_path": item.patch_manifest_path,
                "patch_summary_path": item.patch_summary_path,
            }
            for item in result.items
        ],
        "manifest_path": result.manifest_path,
        "summary_path": result.summary_path,
    }


def write_t10_multi_patch_result(
    result: T10MultiPatchRunResult,
    output_root: str | Path,
) -> T10MultiPatchRunResult:
    resolved_root = Path(output_root)
    resolved_root.mkdir(parents=True, exist_ok=True)
    updated_items: list[T10MultiPatchRunItem] = []
    for item in result.items:
        patch_dir = resolved_root / item.patch_name
        patch_dir.mkdir(parents=True, exist_ok=True)
        written_files = dict(item.written_files)
        if item.status == "error" and "error.txt" not in written_files:
            error_path = patch_dir / "error.txt"
            error_path.write_text((item.error or "unknown_error") + "\n", encoding="utf-8")
            written_files["error.txt"] = str(error_path)
        updated_items.append(
            replace(
                item,
                output_dir=item.output_dir or str(patch_dir),
                written_files=written_files,
            )
        )

    updated = replace(result, items=tuple(updated_items))
    manifest_path = resolved_root / "manifest.json"
    summary_path = resolved_root / "summary.txt"
    manifest_path.write_text(
        json.dumps(_serialize_multi_patch_manifest(updated), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path.write_text(_build_multi_patch_summary_text(updated), encoding="utf-8")
    return replace(
        updated,
        manifest_path=str(manifest_path),
        summary_path=str(summary_path),
    )


def _validate_override_root(manual_override_root: str | Path | None) -> Path | None:
    if manual_override_root is None:
        return None
    resolved = Path(manual_override_root)
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


def _serialize_multi_patch_manifest(result: T10MultiPatchRunResult) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for item in result.items:
        items.append(
            {
                "patch_name": item.patch_name,
                "patch_dir": item.patch_dir,
                "status": item.status,
                "output_dir": item.output_dir,
                "error": item.error,
                "patch_manifest_path": item.patch_manifest_path,
                "patch_summary_path": item.patch_summary_path,
                "written_files": item.written_files,
                "mainids": list(item.patch_result.mainids) if item.patch_result is not None else None,
                "mainid_item_count": len(item.patch_result.items) if item.patch_result is not None else None,
            }
        )
    return {
        "patch_root": result.patch_root,
        "override_root": result.override_root,
        "patch_names": list(result.patch_names),
        "items": items,
        "runs": items,
    }


def _build_multi_patch_summary_text(result: T10MultiPatchRunResult) -> str:
    success_count = sum(1 for item in result.items if item.status == "success")
    error_count = sum(1 for item in result.items if item.status == "error")
    lines = [
        f"patch_root: {result.patch_root}",
        f"override_root: {result.override_root}",
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


__all__ = [
    "T10MultiPatchRunItem",
    "T10MultiPatchRunResult",
    "build_t10_multi_patch_summary",
    "discover_patch_dirs",
    "run_t10_multi_patch_manual_mode",
    "write_t10_multi_patch_result",
]
