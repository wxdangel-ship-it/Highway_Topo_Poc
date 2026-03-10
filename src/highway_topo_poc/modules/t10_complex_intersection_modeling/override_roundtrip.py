from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SUPPORTED_SERVICE_PROFILES = {"left_uturn_service"}


def validate_manual_override_with_catalog(
    *,
    payload: Any,
    approach_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    normalized_override = {
        "service_profile_map": {},
        "paired_mainline_map": {},
    }
    selector_inventory = build_catalog_selector_inventory(approach_catalog)
    catalog_by_approach = selector_inventory["catalog_by_approach_id"]

    if not isinstance(payload, dict):
        errors.append("override_roundtrip_payload_must_be_object")
        return _build_validation_result(
            payload=payload,
            errors=errors,
            normalized_override=normalized_override,
            selector_inventory=selector_inventory,
            approach_catalog=approach_catalog,
        )

    service_profile_map = payload.get("service_profile_map", {})
    paired_mainline_map = payload.get("paired_mainline_map", {})

    if not isinstance(service_profile_map, dict):
        errors.append("override_roundtrip_section_must_be_object:service_profile_map")
        service_profile_map = {}
    if not isinstance(paired_mainline_map, dict):
        errors.append("override_roundtrip_section_must_be_object:paired_mainline_map")
        paired_mainline_map = {}

    normalized_service: dict[str, str] = {}
    for selector, profile in service_profile_map.items():
        if not isinstance(selector, str):
            errors.append("override_roundtrip_key_must_be_string:service_profile_map")
            continue
        if not isinstance(profile, str):
            errors.append(f"override_roundtrip_value_must_be_string:service_profile_map:{selector}")
            continue
        if profile not in _SUPPORTED_SERVICE_PROFILES:
            errors.append(f"override_roundtrip_unsupported_service_profile:{selector}:{profile}")
            continue
        resolved_selector = _resolve_selector(selector, selector_inventory, entry_only=True)
        if resolved_selector is None:
            errors.append(f"override_roundtrip_unknown_selector:service_profile_map:{selector}")
            continue
        normalized_service[resolved_selector] = profile

    normalized_pairs: dict[str, str] = {}
    for source_selector, target_selector in paired_mainline_map.items():
        if not isinstance(source_selector, str):
            errors.append("override_roundtrip_key_must_be_string:paired_mainline_map")
            continue
        if not isinstance(target_selector, str):
            errors.append(
                f"override_roundtrip_value_must_be_string:paired_mainline_map:{source_selector}"
            )
            continue

        resolved_source = _resolve_selector(source_selector, selector_inventory, entry_only=True)
        if resolved_source is None:
            errors.append(
                f"override_roundtrip_unknown_selector:paired_mainline_map.source:{source_selector}"
            )
            continue
        resolved_target = _resolve_selector(target_selector, selector_inventory, entry_only=True)
        if resolved_target is None:
            errors.append(
                f"override_roundtrip_unknown_selector:paired_mainline_map.target:{target_selector}"
            )
            continue

        current_source_profile = None
        if resolved_source in catalog_by_approach:
            current_source_profile = catalog_by_approach[resolved_source].get("approach_profile")
        mapped_source_profile = normalized_service.get(resolved_source)
        if mapped_source_profile != "left_uturn_service" and current_source_profile != "left_uturn_service":
            errors.append(
                f"override_roundtrip_paired_mainline_source_not_left_uturn_service:{source_selector}"
            )
            continue

        normalized_pairs[resolved_source] = resolved_target

    normalized_override["service_profile_map"] = normalized_service
    normalized_override["paired_mainline_map"] = normalized_pairs
    return _build_validation_result(
        payload=payload,
        errors=errors,
        normalized_override=normalized_override,
        selector_inventory=selector_inventory,
        approach_catalog=approach_catalog,
    )


def roundtrip_manual_override_source(
    *,
    manual_override_source: str | Path | dict[str, Any] | None,
    approach_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload, load_errors, source_label = _load_override_payload_for_roundtrip(manual_override_source)
    result = validate_manual_override_with_catalog(
        payload=payload,
        approach_catalog=approach_catalog,
    )
    combined_errors = [*load_errors, *result["errors"]]
    return {
        **result,
        "source_label": source_label,
        "errors": combined_errors,
        "error_count": len(combined_errors),
        "is_valid": len(combined_errors) == 0,
    }


def build_catalog_selector_inventory(approach_catalog: dict[str, Any] | None) -> dict[str, Any]:
    approaches = []
    if isinstance(approach_catalog, dict):
        approaches = approach_catalog.get("approaches", [])
    if not isinstance(approaches, list):
        approaches = []

    selector_to_approach_id: dict[str, str] = {}
    catalog_by_approach_id: dict[str, dict[str, Any]] = {}
    road_id_selectors: list[str] = []
    road_side_selectors: list[str] = []
    approach_id_selectors: list[str] = []

    for item in approaches:
        if not isinstance(item, dict):
            continue
        approach_id = item.get("approach_id")
        road_id = item.get("road_id")
        movement_side = item.get("movement_side")
        if not isinstance(approach_id, str) or not isinstance(road_id, str) or movement_side != "entry":
            continue
        catalog_by_approach_id[approach_id] = item
        selector_to_approach_id.setdefault(road_id, approach_id)
        selector_to_approach_id.setdefault(f"{road_id}:entry", approach_id)
        selector_to_approach_id.setdefault(approach_id, approach_id)
        road_id_selectors.append(road_id)
        road_side_selectors.append(f"{road_id}:entry")
        approach_id_selectors.append(approach_id)

    return {
        "intersection_id": approach_catalog.get("intersection_id") if isinstance(approach_catalog, dict) else None,
        "mainid": approach_catalog.get("mainid") if isinstance(approach_catalog, dict) else None,
        "entry_approach_count": len(catalog_by_approach_id),
        "selector_to_approach_id": selector_to_approach_id,
        "catalog_by_approach_id": catalog_by_approach_id,
        "road_id_selectors": sorted(set(road_id_selectors)),
        "road_side_selectors": sorted(set(road_side_selectors)),
        "approach_id_selectors": sorted(set(approach_id_selectors)),
    }


def write_override_roundtrip_report(
    report: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, str]:
    resolved_dir = Path(output_dir)
    resolved_dir.mkdir(parents=True, exist_ok=True)
    report_path = resolved_dir / "override_roundtrip.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"override_roundtrip.json": str(report_path)}


def _load_override_payload_for_roundtrip(
    manual_override_source: str | Path | dict[str, Any] | None,
) -> tuple[Any, list[str], str]:
    if manual_override_source is None:
        return {}, [], "none"
    if isinstance(manual_override_source, dict):
        return manual_override_source, [], "dict"
    if isinstance(manual_override_source, (str, Path)):
        path = Path(manual_override_source)
        if not path.exists():
            return {}, [f"manual_override_file_not_found:{path}"], str(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {}, [f"manual_override_file_invalid_json:{path}:{exc.msg}"], str(path)
        except OSError as exc:
            return {}, [f"manual_override_file_read_error:{path}:{exc}"], str(path)
        if not isinstance(payload, dict):
            return {}, [f"manual_override_payload_must_be_object:{path}"], str(path)
        return payload, [], str(path)
    return {}, [f"unsupported_manual_override_source:{type(manual_override_source).__name__}"], type(manual_override_source).__name__


def _resolve_selector(
    selector: str,
    selector_inventory: dict[str, Any],
    *,
    entry_only: bool,
) -> str | None:
    _ = entry_only
    selector_to_approach_id = selector_inventory["selector_to_approach_id"]
    return selector_to_approach_id.get(selector)


def _build_validation_result(
    *,
    payload: Any,
    errors: list[str],
    normalized_override: dict[str, Any],
    selector_inventory: dict[str, Any],
    approach_catalog: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "intersection_id": approach_catalog.get("intersection_id") if isinstance(approach_catalog, dict) else None,
        "mainid": approach_catalog.get("mainid") if isinstance(approach_catalog, dict) else None,
        "is_valid": len(errors) == 0,
        "error_count": len(errors),
        "errors": errors,
        "normalized_override": normalized_override,
        "selector_inventory": {
            "entry_approach_count": selector_inventory["entry_approach_count"],
            "road_id_selectors": selector_inventory["road_id_selectors"],
            "road_side_selectors": selector_inventory["road_side_selectors"],
            "approach_id_selectors": selector_inventory["approach_id_selectors"],
        },
        "input_sections": sorted(payload.keys()) if isinstance(payload, dict) else [],
    }


__all__ = [
    "build_catalog_selector_inventory",
    "roundtrip_manual_override_source",
    "validate_manual_override_with_catalog",
    "write_override_roundtrip_report",
]
