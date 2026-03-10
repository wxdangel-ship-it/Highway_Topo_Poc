from __future__ import annotations

from .models import IntersectionBundle, MovementCandidate, MovementDecision
from .reason_codes import (
    DEFAULT_CORE_LEFT_ALLOWED,
    DEFAULT_NONCORE_LEFT_UNKNOWN,
    DEFAULT_RIGHT_ALLOWED,
    DEFAULT_THROUGH_ALLOWED,
    DEFAULT_UTURN_UNKNOWN,
    INVALID_ENTRY_EXIT_ROLE,
    MULTI_PARALLEL_CROSS_FORBIDDEN,
    NON_STANDARD_EXIT_LEG,
    NOT_SAME_CONTROL_ZONE,
    PROFILE_LEFT_UTURN_SERVICE_ALLOWED,
    PROFILE_LEFT_UTURN_SERVICE_FORBID_RIGHT,
    PROFILE_LEFT_UTURN_SERVICE_FORBID_THROUGH,
    PROFILE_PAIRED_MAINLINE_FORBID_LEFT,
    PROFILE_PAIRED_MAINLINE_FORBID_UTURN,
    SINGLE_PARALLEL_CROSS_DEFAULT_UNKNOWN,
    UNKNOWN_CONTROL_ZONE,
    UNKNOWN_PARALLEL_CROSS_COUNT,
    UNKNOWN_TARGET_STANDARD_EXIT,
    UNKNOWN_TURN_SENSE,
    breakpoints_for,
    reason_text_for,
)


def evaluate_bundle(bundle: IntersectionBundle) -> list[MovementDecision]:
    return [evaluate_movement(candidate) for candidate in bundle.movements]


def evaluate_movement(candidate: MovementCandidate) -> MovementDecision:
    if candidate.source.movement_side != "entry" or candidate.target.movement_side != "exit":
        return _decision(candidate, "forbidden", "high", [INVALID_ENTRY_EXIT_ROLE])

    if candidate.same_signalized_control_zone is False:
        return _decision(candidate, "forbidden", "high", [NOT_SAME_CONTROL_ZONE])
    if candidate.same_signalized_control_zone == "unknown":
        return _decision(candidate, "unknown", "low", [UNKNOWN_CONTROL_ZONE], breakpoints=["same_signalized_control_zone"])

    target_role = candidate.target.exit_leg_role
    target_unknown = target_role == "unknown"
    if target_role in {"auxiliary_parallel_exit", "access_exit"}:
        return _decision(candidate, "forbidden", "high", [NON_STANDARD_EXIT_LEG])

    if candidate.parallel_cross_count == "2+":
        return _decision(candidate, "forbidden", "high", [MULTI_PARALLEL_CROSS_FORBIDDEN])
    if candidate.parallel_cross_count == "unknown":
        return _decision(candidate, "unknown", "low", [UNKNOWN_PARALLEL_CROSS_COUNT], breakpoints=["parallel_cross_count"])
    if candidate.turn_sense == "unknown":
        return _decision(candidate, "unknown", "low", [UNKNOWN_TURN_SENSE], breakpoints=["turn_sense"])

    if candidate.source.approach_profile == "left_uturn_service":
        return _left_uturn_service_decision(candidate, target_unknown)
    if candidate.source.approach_profile == "paired_mainline_no_left_uturn" and candidate.turn_sense in {"left", "uturn"}:
        if candidate.turn_sense == "left":
            return _decision(candidate, "forbidden", "high", [PROFILE_PAIRED_MAINLINE_FORBID_LEFT])
        return _decision(candidate, "forbidden", "high", [PROFILE_PAIRED_MAINLINE_FORBID_UTURN])

    if candidate.parallel_cross_count == 1:
        return _decision(
            candidate,
            "unknown",
            "medium" if target_unknown else "high",
            _with_target_unknown([SINGLE_PARALLEL_CROSS_DEFAULT_UNKNOWN], target_unknown),
        )

    if candidate.turn_sense == "right":
        return _decision(candidate, "allowed", "medium" if target_unknown else "high", _with_target_unknown([DEFAULT_RIGHT_ALLOWED], target_unknown))
    if candidate.turn_sense == "through":
        return _decision(candidate, "allowed", "medium" if target_unknown else "high", _with_target_unknown([DEFAULT_THROUGH_ALLOWED], target_unknown))
    if candidate.turn_sense == "left":
        if target_unknown:
            return _decision(candidate, "unknown", "medium", [UNKNOWN_TARGET_STANDARD_EXIT])
        if candidate.source.is_core_signalized_approach is True:
            return _decision(candidate, "allowed", "high", [DEFAULT_CORE_LEFT_ALLOWED])
        return _decision(candidate, "unknown", "medium", [DEFAULT_NONCORE_LEFT_UNKNOWN])
    if candidate.turn_sense == "uturn":
        if target_unknown:
            return _decision(candidate, "unknown", "medium", [UNKNOWN_TARGET_STANDARD_EXIT])
        return _decision(candidate, "unknown", "medium", [DEFAULT_UTURN_UNKNOWN])

    return _decision(candidate, "unknown", "low", [UNKNOWN_TURN_SENSE], breakpoints=["turn_sense"])


def _left_uturn_service_decision(candidate: MovementCandidate, target_unknown: bool) -> MovementDecision:
    if candidate.turn_sense in {"left", "uturn"}:
        if target_unknown:
            return _decision(candidate, "unknown", "medium", [UNKNOWN_TARGET_STANDARD_EXIT])
        return _decision(candidate, "allowed", "high", [PROFILE_LEFT_UTURN_SERVICE_ALLOWED])
    if candidate.turn_sense == "through":
        return _decision(candidate, "forbidden", "high", [PROFILE_LEFT_UTURN_SERVICE_FORBID_THROUGH])
    if candidate.turn_sense == "right":
        return _decision(candidate, "forbidden", "high", [PROFILE_LEFT_UTURN_SERVICE_FORBID_RIGHT])
    return _decision(candidate, "unknown", "low", [UNKNOWN_TURN_SENSE], breakpoints=["turn_sense"])


def _with_target_unknown(codes: list[str], target_unknown: bool) -> list[str]:
    if target_unknown:
        return [*codes, UNKNOWN_TARGET_STANDARD_EXIT]
    return codes


def _decision(
    candidate: MovementCandidate,
    status: str,
    confidence: str,
    reason_codes: list[str],
    *,
    breakpoints: list[str] | None = None,
) -> MovementDecision:
    merged_breakpoints = list(breakpoints_for(reason_codes))
    for breakpoint_name in breakpoints or []:
        if breakpoint_name not in merged_breakpoints:
            merged_breakpoints.append(breakpoint_name)
    return MovementDecision(
        movement_id=candidate.movement_id,
        status=status,
        confidence=confidence,
        reason_codes=tuple(reason_codes),
        reason_text=reason_text_for(reason_codes),
        breakpoints=tuple(merged_breakpoints),
    )
