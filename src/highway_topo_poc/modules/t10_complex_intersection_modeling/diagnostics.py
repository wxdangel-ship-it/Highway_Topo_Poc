from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from .normalize import normalize_key

_DEFAULT_CANDIDATE_FIELDS = ("formway",)
_BITLIKE_KEYWORDS = ("bit", "mask", "flag", "formway")


def probe_road_raw_properties(
    road_features: Iterable[dict[str, Any]],
    *,
    candidate_fields: Iterable[str] = _DEFAULT_CANDIDATE_FIELDS,
) -> dict[str, Any]:
    raw_key_counts: Counter[str] = Counter()
    normalized_key_presence: Counter[str] = Counter()
    field_raw_keys: dict[str, Counter[str]] = defaultdict(Counter)
    field_type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    field_int_value_counts: dict[str, Counter[int]] = defaultdict(Counter)

    road_count = 0
    for feature in road_features:
        road_count += 1
        props = dict(feature.get("properties") or {})
        seen_in_feature: set[str] = set()
        for raw_key, value in props.items():
            raw_key_text = str(raw_key)
            norm_key = normalize_key(raw_key_text)
            raw_key_counts[raw_key_text] += 1
            field_raw_keys[norm_key][raw_key_text] += 1
            field_type_counts[norm_key][_value_type_name(value)] += 1
            maybe_int = _as_real_int(value)
            if maybe_int is not None:
                field_int_value_counts[norm_key][maybe_int] += 1
            if norm_key not in seen_in_feature:
                normalized_key_presence[norm_key] += 1
                seen_in_feature.add(norm_key)

    normalized_candidate_fields = [normalize_key(field) for field in candidate_fields]
    candidate_summaries = {
        field_name: _build_field_summary(
            field_name=field_name,
            present_count=normalized_key_presence.get(field_name, 0),
            road_count=road_count,
            raw_keys=field_raw_keys.get(field_name, Counter()),
            type_counts=field_type_counts.get(field_name, Counter()),
            int_value_counts=field_int_value_counts.get(field_name, Counter()),
        )
        for field_name in normalized_candidate_fields
    }
    suspicious_fields = {
        field_name: _build_field_summary(
            field_name=field_name,
            present_count=normalized_key_presence[field_name],
            road_count=road_count,
            raw_keys=field_raw_keys[field_name],
            type_counts=field_type_counts[field_name],
            int_value_counts=field_int_value_counts[field_name],
        )
        for field_name in sorted(normalized_key_presence)
        if field_name and any(keyword in field_name for keyword in _BITLIKE_KEYWORDS)
    }
    return {
        "road_count": road_count,
        "raw_key_counts": dict(sorted(raw_key_counts.items())),
        "normalized_key_presence": dict(sorted(normalized_key_presence.items())),
        "candidate_fields": candidate_summaries,
        "suspicious_bitlike_fields": suspicious_fields,
    }


def probe_road_geojson_file(
    path: str | Path,
    *,
    candidate_fields: Iterable[str] = _DEFAULT_CANDIDATE_FIELDS,
) -> dict[str, Any]:
    resolved = Path(path)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"road_geojson_invalid_json:{resolved}:{exc.msg}") from exc
    except OSError as exc:
        raise ValueError(f"road_geojson_read_error:{resolved}:{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"road_geojson_payload_must_be_object:{resolved}")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError(f"road_geojson_features_must_be_list:{resolved}")
    return {
        "path": str(resolved),
        "feature_collection_type": payload.get("type"),
        "feature_count": len(features),
        "raw_property_probe": probe_road_raw_properties(features, candidate_fields=candidate_fields),
    }


def _build_field_summary(
    *,
    field_name: str,
    present_count: int,
    road_count: int,
    raw_keys: Counter[str],
    type_counts: Counter[str],
    int_value_counts: Counter[int],
) -> dict[str, Any]:
    return {
        "field_name": field_name,
        "present": present_count > 0,
        "present_count": present_count,
        "road_count": road_count,
        "presence_ratio": 0.0 if road_count == 0 else float(present_count / road_count),
        "raw_keys": dict(sorted(raw_keys.items())),
        "value_types": dict(sorted(type_counts.items())),
        "has_mixed_types": len(type_counts) > 1,
        "int_value_counts": {str(key): count for key, count in sorted(int_value_counts.items())},
    }


def _value_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _as_real_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


__all__ = ["probe_road_geojson_file", "probe_road_raw_properties"]
