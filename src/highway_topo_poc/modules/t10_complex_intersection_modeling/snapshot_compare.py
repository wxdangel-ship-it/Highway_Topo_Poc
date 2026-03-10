from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEFAULT_SNAPSHOT_FILES = (
    "serialized_bundle.json",
    "movement_results.json",
    "movement_matrix.json",
)


def compare_t10_output_dir_to_snapshot(
    output_dir: str | Path,
    snapshot_dir: str | Path,
    *,
    file_names: tuple[str, ...] = _DEFAULT_SNAPSHOT_FILES,
) -> dict[str, Any]:
    resolved_output = Path(output_dir)
    resolved_snapshot = Path(snapshot_dir)
    if not resolved_snapshot.exists():
        raise ValueError(f"snapshot_dir_not_found:{resolved_snapshot}")
    if not resolved_output.exists():
        raise ValueError(f"output_dir_not_found:{resolved_output}")

    compared_files: list[str] = []
    for file_name in file_names:
        expected = _load_json(resolved_snapshot / file_name, label=f"snapshot:{file_name}")
        actual = _load_json(resolved_output / file_name, label=f"output:{file_name}")
        _compare_json_values(actual, expected, path=file_name)
        compared_files.append(file_name)
    return {
        "snapshot_dir": str(resolved_snapshot),
        "output_dir": str(resolved_output),
        "files_compared": compared_files,
    }


def _load_json(path: Path, *, label: str) -> Any:
    if not path.exists():
        raise ValueError(f"snapshot_compare_missing_file:{label}:{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"snapshot_compare_invalid_json:{label}:{path}:{exc.msg}") from exc


def _compare_json_values(actual: Any, expected: Any, *, path: str) -> None:
    if type(actual) is not type(expected):
        raise ValueError(
            f"snapshot_compare_type_mismatch:{path}:expected={type(expected).__name__}:actual={type(actual).__name__}"
        )
    if isinstance(expected, dict):
        expected_keys = list(expected.keys())
        actual_keys = list(actual.keys())
        if expected_keys != actual_keys:
            raise ValueError(
                f"snapshot_compare_key_mismatch:{path}:expected={expected_keys}:actual={actual_keys}"
            )
        for key in expected_keys:
            _compare_json_values(actual[key], expected[key], path=f"{path}.{key}")
        return
    if isinstance(expected, list):
        if len(actual) != len(expected):
            raise ValueError(
                f"snapshot_compare_list_length_mismatch:{path}:expected={len(expected)}:actual={len(actual)}"
            )
        for idx, (actual_item, expected_item) in enumerate(zip(actual, expected, strict=True)):
            _compare_json_values(actual_item, expected_item, path=f"{path}[{idx}]")
        return
    if actual != expected:
        raise ValueError(f"snapshot_compare_value_mismatch:{path}:expected={expected!r}:actual={actual!r}")


__all__ = ["compare_t10_output_dir_to_snapshot"]
