from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "cross_half_len_m": 20.0,
    "scan_step_m": 1.0,
    "scan_near_limit_m": 20.0,
    "scan_max_limit_m": 200.0,
    "stop_at_next_intersection": True,
    "divstrip_hit_tol_m": 1.0,
    "divstrip_trigger_window_m": 3.0,
    "pc_line_buffer_m": 0.5,
    "pc_non_ground_min_points": 5,
    "pc_ground_class": 2,
    "pc_use_classification": True,
    "ignore_initial_side_ng": True,
    "ignore_end_margin_m": 3.0,
    "allow_divstrip_only_when_no_pointcloud": True,
    "anchor_found_ratio_min": 0.90,
    "no_trigger_before_next_intersection_ratio_max": 0.05,
    "scan_exceed_200m_ratio_max": 0.02,
    "divstrip_tolerance_violation_hard": True,
}


def _coerce_bool(raw: str) -> bool:
    s = raw.strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid_bool: {raw}")


def _coerce_like(template_value: Any, raw_value: Any) -> Any:
    if isinstance(template_value, bool):
        if isinstance(raw_value, bool):
            return raw_value
        return _coerce_bool(str(raw_value))

    if isinstance(template_value, int) and not isinstance(template_value, bool):
        if isinstance(raw_value, int):
            return raw_value
        return int(str(raw_value).strip())

    if isinstance(template_value, float):
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        return float(str(raw_value).strip())

    return raw_value


def parse_set_overrides(items: list[str] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"invalid_set_item: {item}")
        key, raw = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"invalid_set_item: {item}")
        out[key] = raw.strip()
    return out


def load_config(
    *,
    config_json: Path | None = None,
    set_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)

    if config_json is not None:
        payload = json.loads(config_json.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("config_json_must_be_object")
        for key, value in payload.items():
            if key not in cfg:
                raise ValueError(f"unknown_config_key: {key}")
            cfg[key] = _coerce_like(DEFAULT_CONFIG[key], value)

    for key, value in (set_overrides or {}).items():
        if key not in cfg:
            raise ValueError(f"unknown_config_key: {key}")
        cfg[key] = _coerce_like(DEFAULT_CONFIG[key], value)

    return cfg


__all__ = ["DEFAULT_CONFIG", "load_config", "parse_set_overrides"]
