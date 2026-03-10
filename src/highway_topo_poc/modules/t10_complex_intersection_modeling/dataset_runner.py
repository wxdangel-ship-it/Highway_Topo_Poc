from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .geojson_io import discover_geojson_dataset_inputs, parse_mainid_values
from .review_cycle import T10ReviewCycleResult, build_t10_review_cycle_summary, run_t10_review_cycle_from_geojson_files

_NON_ALNUM = re.compile(r"[^A-Za-z0-9._-]+")
DEFAULT_COMPUTE_BUFFER_M = 200.0


@dataclass(frozen=True)
class T10DatasetMainnodeidRunItem:
    mainnodeid: Any
    status: str
    cycle_result: T10ReviewCycleResult | None
    error: str | None = None
    output_dir: str | None = None
    written_files: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class T10DatasetMainnodeidRunResult:
    dataset_dir: str
    node_geojson_path: str
    road_geojson_path: str
    mainnodeids: tuple[Any, ...]
    compute_buffer_m: float
    manual_override_source: str | None
    items: tuple[T10DatasetMainnodeidRunItem, ...]
    manifest_path: str | None = None
    summary_path: str | None = None


def run_t10_mainnodeids_from_geojson_dataset(
    *,
    dataset_dir: str | Path,
    mainnodeids: list[Any] | tuple[Any, ...] | None,
    manual_override_source: str | Path | dict[str, Any] | None = None,
    output_root: str | Path | None = None,
    validate_override: bool = False,
    compute_buffer_m: float = DEFAULT_COMPUTE_BUFFER_M,
    source_type: str = "real",
    approach_overrides: dict[str, dict[str, Any]] | None = None,
) -> T10DatasetMainnodeidRunResult:
    parsed_mainnodeids = parse_mainid_values(mainnodeids)
    if not parsed_mainnodeids:
        raise ValueError("dataset_mode_requires_mainnodeids")

    node_geojson_path, road_geojson_path = discover_geojson_dataset_inputs(dataset_dir)
    manual_override_label = _label_manual_override_source(manual_override_source)
    items: list[T10DatasetMainnodeidRunItem] = []
    resolved_output_root = Path(output_root) if output_root is not None else None
    if resolved_output_root is not None:
        resolved_output_root.mkdir(parents=True, exist_ok=True)

    for mainnodeid in parsed_mainnodeids:
        item_output_dir = resolved_output_root / _mainnodeid_dir_name(mainnodeid) if resolved_output_root is not None else None
        try:
            override_for_mainnodeid = _resolve_mainnodeid_override_source(manual_override_source, mainnodeid)
            cycle_result = run_t10_review_cycle_from_geojson_files(
                node_geojson_path=node_geojson_path,
                road_geojson_path=road_geojson_path,
                mainid=mainnodeid,
                manual_override_source=override_for_mainnodeid,
                output_dir=item_output_dir,
                validate_override=validate_override and override_for_mainnodeid is not None,
                source_type=source_type,
                approach_overrides=approach_overrides,
            )
        except Exception as exc:
            written_files: dict[str, Any] = {}
            if item_output_dir is not None:
                item_output_dir.mkdir(parents=True, exist_ok=True)
                error_path = item_output_dir / "error.txt"
                error_path.write_text(str(exc) + "\n", encoding="utf-8")
                written_files["error.txt"] = str(error_path)
            items.append(
                T10DatasetMainnodeidRunItem(
                    mainnodeid=mainnodeid,
                    status="error",
                    cycle_result=None,
                    error=str(exc),
                    output_dir=str(item_output_dir) if item_output_dir is not None else None,
                    written_files=written_files,
                )
            )
            continue

        items.append(
            T10DatasetMainnodeidRunItem(
                mainnodeid=mainnodeid,
                status="success",
                cycle_result=cycle_result,
                output_dir=str(item_output_dir) if item_output_dir is not None else None,
                written_files=cycle_result.written_files,
            )
        )

    result = T10DatasetMainnodeidRunResult(
        dataset_dir=str(Path(dataset_dir)),
        node_geojson_path=str(node_geojson_path),
        road_geojson_path=str(road_geojson_path),
        mainnodeids=parsed_mainnodeids,
        compute_buffer_m=float(compute_buffer_m),
        manual_override_source=manual_override_label,
        items=tuple(items),
    )
    if resolved_output_root is not None:
        result = write_t10_dataset_mainnodeid_result(result, resolved_output_root)
    return result


def build_t10_dataset_mainnodeid_summary(result: T10DatasetMainnodeidRunResult) -> dict[str, Any]:
    return {
        "dataset_dir": result.dataset_dir,
        "node_geojson_path": result.node_geojson_path,
        "road_geojson_path": result.road_geojson_path,
        "mainnodeids": list(result.mainnodeids),
        "compute_buffer_m": result.compute_buffer_m,
        "compute_buffer_note": "reserved_for_future_compute_acceleration_only_no_truth_selection_effect",
        "manual_override_source": result.manual_override_source,
        "items": [
            {
                "mainnodeid": item.mainnodeid,
                "status": item.status,
                "error": item.error,
                "output_dir": item.output_dir,
                "has_rerun": bool(item.cycle_result and item.cycle_result.rerun_result is not None),
                "has_diff": bool(item.cycle_result and item.cycle_result.diff_payload is not None),
                "cycle_summary": build_t10_review_cycle_summary(item.cycle_result) if item.cycle_result is not None else None,
            }
            for item in result.items
        ],
        "manifest_path": result.manifest_path,
        "summary_path": result.summary_path,
    }


def write_t10_dataset_mainnodeid_result(
    result: T10DatasetMainnodeidRunResult,
    output_root: str | Path,
) -> T10DatasetMainnodeidRunResult:
    resolved_root = Path(output_root)
    resolved_root.mkdir(parents=True, exist_ok=True)
    manifest_path = resolved_root / "manifest.json"
    summary_path = resolved_root / "summary.txt"
    manifest_payload = build_t10_dataset_mainnodeid_summary(result)
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(_build_dataset_summary_text(result), encoding="utf-8")
    return replace(result, manifest_path=str(manifest_path), summary_path=str(summary_path))


def _resolve_mainnodeid_override_source(
    override_source: str | Path | dict[str, Any] | None,
    mainnodeid: Any,
) -> str | Path | dict[str, Any] | None:
    if override_source is None:
        return None
    if isinstance(override_source, dict):
        return override_source
    resolved = Path(override_source)
    if not resolved.exists():
        raise ValueError(f"mainnodeid_override_source_not_found:{resolved}")
    if resolved.is_file():
        return resolved
    if resolved.is_dir():
        candidate = resolved / f"{mainnodeid}.json"
        if candidate.is_file():
            return candidate
        return None
    raise ValueError(f"mainnodeid_override_source_invalid:{resolved}")


def _label_manual_override_source(override_source: str | Path | dict[str, Any] | None) -> str | None:
    if override_source is None:
        return None
    if isinstance(override_source, dict):
        return "dict"
    return str(Path(override_source))


def _build_dataset_summary_text(result: T10DatasetMainnodeidRunResult) -> str:
    success_count = sum(1 for item in result.items if item.status == "success")
    error_count = sum(1 for item in result.items if item.status == "error")
    lines = [
        f"dataset_dir: {result.dataset_dir}",
        f"node_geojson_path: {result.node_geojson_path}",
        f"road_geojson_path: {result.road_geojson_path}",
        f"mainnodeid_count: {len(result.mainnodeids)}",
        f"compute_buffer_m: {result.compute_buffer_m}",
        "compute_buffer_note: reserved_for_future_compute_acceleration_only_no_truth_selection_effect",
        f"manual_override_source: {result.manual_override_source}",
        f"success_count: {success_count}",
        f"error_count: {error_count}",
        "items:",
    ]
    for item in result.items:
        line = f"  - mainnodeid={item.mainnodeid} status={item.status}"
        if item.output_dir:
            line += f" output_dir={item.output_dir}"
        if item.error:
            line += f" error={item.error}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _mainnodeid_dir_name(mainnodeid: Any) -> str:
    raw = _NON_ALNUM.sub("_", str(mainnodeid)).strip("_")
    if not raw:
        raw = "unknown"
    return f"mainnodeid_{raw}"


__all__ = [
    "DEFAULT_COMPUTE_BUFFER_M",
    "T10DatasetMainnodeidRunItem",
    "T10DatasetMainnodeidRunResult",
    "build_t10_dataset_mainnodeid_summary",
    "run_t10_mainnodeids_from_geojson_dataset",
    "write_t10_dataset_mainnodeid_result",
]
