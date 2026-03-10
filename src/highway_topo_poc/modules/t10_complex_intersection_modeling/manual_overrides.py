from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_manual_override_source(
    manual_override_source: str | Path | dict[str, Any] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    if manual_override_source is None:
        return {}, {}
    if isinstance(manual_override_source, (str, Path)):
        payload = _load_manual_override_file(Path(manual_override_source))
    elif isinstance(manual_override_source, dict):
        payload = manual_override_source
    else:
        raise ValueError(f"unsupported_manual_override_source:{type(manual_override_source).__name__}")
    return _validate_manual_override_payload(payload)


def _load_manual_override_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"manual_override_file_not_found:{path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"manual_override_file_invalid_json:{path}:{exc.msg}") from exc
    except OSError as exc:
        raise ValueError(f"manual_override_file_read_error:{path}:{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"manual_override_payload_must_be_object:{path}")
    return payload


def _validate_manual_override_payload(payload: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    service_profile_map = _validate_string_map(
        section_name="service_profile_map",
        value=payload.get("service_profile_map", {}),
    )
    paired_mainline_map = _validate_string_map(
        section_name="paired_mainline_map",
        value=payload.get("paired_mainline_map", {}),
    )
    return service_profile_map, paired_mainline_map


def _validate_string_map(*, section_name: str, value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"manual_override_section_must_be_object:{section_name}")
    out: dict[str, str] = {}
    for key, mapped_value in value.items():
        if not isinstance(key, str):
            raise ValueError(f"manual_override_key_must_be_string:{section_name}")
        if not isinstance(mapped_value, str):
            raise ValueError(f"manual_override_value_must_be_string:{section_name}:{key}")
        out[key] = mapped_value
    return out


__all__ = ["load_manual_override_source"]
