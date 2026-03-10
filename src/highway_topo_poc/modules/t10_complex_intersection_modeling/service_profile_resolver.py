from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import ApproachModel
from .normalize import normalize_key

_MANUAL_SERVICE_PROFILE_ALLOWED = {"left_uturn_service"}


def find_raw_formway_value(*, raw_properties: dict[str, Any]) -> Any | None:
    for raw_key, value in raw_properties.items():
        if normalize_key(str(raw_key)) == "formway":
            return value
    return None


def detect_left_uturn_service_from_raw(*, raw_properties: dict[str, Any]) -> str | None:
    _ = find_raw_formway_value(raw_properties=raw_properties)
    # TODO: enable detection only after the real formway field mapping and bit semantics are confirmed.
    return None


def detect_paired_mainline_from_context(
    *,
    source_approach: ApproachModel,
    candidate_entry_approaches: list[ApproachModel],
) -> str | None:
    _ = (source_approach, candidate_entry_approaches)
    # TODO: enable detection only after service-road evidence and pairing constraints are confirmed.
    return None


def apply_manual_service_maps(
    *,
    approaches: list[ApproachModel],
    manual_service_profile_map: dict[str, str] | None = None,
    manual_paired_mainline_map: dict[str, str] | None = None,
) -> list[ApproachModel]:
    if not manual_service_profile_map and not manual_paired_mainline_map:
        return approaches

    updated: dict[str, ApproachModel] = {approach.approach_id: approach for approach in approaches}
    entry_ref_index = _build_entry_ref_index(approaches)

    for source_ref, profile in (manual_service_profile_map or {}).items():
        if profile not in _MANUAL_SERVICE_PROFILE_ALLOWED:
            raise ValueError(f"unsupported_manual_service_profile:{source_ref}:{profile}")
        source_id = _resolve_entry_ref(ref=source_ref, entry_ref_index=entry_ref_index)
        source = updated[source_id]
        if "manual_override:approach_profile" in source.remarks:
            continue
        updated[source_id] = replace(
            source,
            approach_profile=profile,
            approach_profile_source="manual_service_profile_map",
            remarks=source.remarks + (f"manual_service_profile_map:{profile}",),
        )

    for source_ref, target_ref in (manual_paired_mainline_map or {}).items():
        source_id = _resolve_entry_ref(ref=source_ref, entry_ref_index=entry_ref_index)
        target_id = _resolve_entry_ref(ref=target_ref, entry_ref_index=entry_ref_index)
        source = updated[source_id]
        if source.approach_profile != "left_uturn_service":
            raise ValueError(f"paired_mainline_requires_left_uturn_service_source:{source_ref}")
        if "manual_override:paired_mainline_approach_id" not in source.remarks:
            updated[source_id] = replace(
                source,
                paired_mainline_approach_id=target_id,
                paired_mainline_source="manual_paired_mainline_map",
                remarks=source.remarks + ("manual_paired_mainline_map",),
            )
        target = updated[target_id]
        if "manual_override:approach_profile" not in target.remarks:
            updated[target_id] = replace(
                target,
                approach_profile="paired_mainline_no_left_uturn",
                approach_profile_source="manual_paired_mainline_map",
                remarks=target.remarks + ("manual_paired_mainline_map:paired_mainline_no_left_uturn",),
            )

    return list(updated.values())


def apply_placeholder_paired_mainline_detection(approaches: list[ApproachModel]) -> list[ApproachModel]:
    entry_approaches = [approach for approach in approaches if approach.movement_side == "entry"]
    updated: dict[str, ApproachModel] = {approach.approach_id: approach for approach in approaches}
    for approach in entry_approaches:
        current = updated[approach.approach_id]
        if current.approach_profile != "left_uturn_service":
            continue
        if current.paired_mainline_source in {"approach_override", "manual_paired_mainline_map"}:
            continue
        if current.paired_mainline_approach_id:
            continue
        detected_target_id = detect_paired_mainline_from_context(
            source_approach=current,
            candidate_entry_approaches=[updated[item.approach_id] for item in entry_approaches],
        )
        if detected_target_id is None:
            updated[current.approach_id] = replace(
                current,
                paired_mainline_source="auto_pair_placeholder_no_hit",
                remarks=current.remarks + ("TODO: paired mainline auto-detection remains disabled pending field evidence",),
            )
            continue
        target = updated[detected_target_id]
        updated[current.approach_id] = replace(
            current,
            paired_mainline_approach_id=detected_target_id,
            paired_mainline_source="auto_pair_detected",
            remarks=current.remarks + ("auto_paired_mainline_detected",),
        )
        if target.approach_profile == "default_signalized":
            updated[detected_target_id] = replace(
                target,
                approach_profile="paired_mainline_no_left_uturn",
                approach_profile_source="auto_pair_detected",
                remarks=target.remarks + ("auto_paired_mainline_profile",),
            )
    return list(updated.values())


def _build_entry_ref_index(approaches: list[ApproachModel]) -> dict[str, str]:
    index: dict[str, str] = {}
    for approach in approaches:
        if approach.movement_side != "entry":
            continue
        index.setdefault(approach.approach_id, approach.approach_id)
        index.setdefault(f"{approach.road_id}:entry", approach.approach_id)
        index.setdefault(approach.road_id, approach.approach_id)
    return index


def _resolve_entry_ref(*, ref: str, entry_ref_index: dict[str, str]) -> str:
    resolved = entry_ref_index.get(str(ref))
    if resolved is None:
        raise ValueError(f"manual_service_ref_not_found:{ref}")
    return resolved


__all__ = [
    "apply_manual_service_maps",
    "apply_placeholder_paired_mainline_detection",
    "detect_paired_mainline_from_context",
    "detect_left_uturn_service_from_raw",
    "find_raw_formway_value",
]
