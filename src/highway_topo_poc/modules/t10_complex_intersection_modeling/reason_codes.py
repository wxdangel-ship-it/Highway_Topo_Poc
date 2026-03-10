from __future__ import annotations

INVALID_ENTRY_EXIT_ROLE = "INVALID_ENTRY_EXIT_ROLE"
NOT_SAME_CONTROL_ZONE = "NOT_SAME_CONTROL_ZONE"
UNKNOWN_CONTROL_ZONE = "UNKNOWN_CONTROL_ZONE"
NON_STANDARD_EXIT_LEG = "NON_STANDARD_EXIT_LEG"
UNKNOWN_TARGET_STANDARD_EXIT = "UNKNOWN_TARGET_STANDARD_EXIT"
SINGLE_PARALLEL_CROSS_DEFAULT_UNKNOWN = "SINGLE_PARALLEL_CROSS_DEFAULT_UNKNOWN"
MULTI_PARALLEL_CROSS_FORBIDDEN = "MULTI_PARALLEL_CROSS_FORBIDDEN"
DEFAULT_RIGHT_ALLOWED = "DEFAULT_RIGHT_ALLOWED"
DEFAULT_THROUGH_ALLOWED = "DEFAULT_THROUGH_ALLOWED"
DEFAULT_CORE_LEFT_ALLOWED = "DEFAULT_CORE_LEFT_ALLOWED"
DEFAULT_NONCORE_LEFT_UNKNOWN = "DEFAULT_NONCORE_LEFT_UNKNOWN"
DEFAULT_UTURN_UNKNOWN = "DEFAULT_UTURN_UNKNOWN"
PROFILE_LEFT_UTURN_SERVICE_ALLOWED = "PROFILE_LEFT_UTURN_SERVICE_ALLOWED"
PROFILE_LEFT_UTURN_SERVICE_FORBID_THROUGH = "PROFILE_LEFT_UTURN_SERVICE_FORBID_THROUGH"
PROFILE_LEFT_UTURN_SERVICE_FORBID_RIGHT = "PROFILE_LEFT_UTURN_SERVICE_FORBID_RIGHT"
PROFILE_PAIRED_MAINLINE_FORBID_LEFT = "PROFILE_PAIRED_MAINLINE_FORBID_LEFT"
PROFILE_PAIRED_MAINLINE_FORBID_UTURN = "PROFILE_PAIRED_MAINLINE_FORBID_UTURN"
UNKNOWN_TURN_SENSE = "UNKNOWN_TURN_SENSE"
UNKNOWN_PARALLEL_CROSS_COUNT = "UNKNOWN_PARALLEL_CROSS_COUNT"

REASON_TEXT = {
    INVALID_ENTRY_EXIT_ROLE: "source/target movement_side invalid for movement evaluation",
    NOT_SAME_CONTROL_ZONE: "source and target are not in the same signalized control zone",
    UNKNOWN_CONTROL_ZONE: "signalized control zone cannot be determined",
    NON_STANDARD_EXIT_LEG: "target is a known non-standard exit leg",
    UNKNOWN_TARGET_STANDARD_EXIT: "target exit role is unknown, result is kept conservative",
    SINGLE_PARALLEL_CROSS_DEFAULT_UNKNOWN: "single parallel corridor shift defaults to unknown",
    MULTI_PARALLEL_CROSS_FORBIDDEN: "movement crosses more than one parallel corridor layer",
    DEFAULT_RIGHT_ALLOWED: "default right turn is allowed",
    DEFAULT_THROUGH_ALLOWED: "default through movement is allowed",
    DEFAULT_CORE_LEFT_ALLOWED: "core approach default left turn is allowed",
    DEFAULT_NONCORE_LEFT_UNKNOWN: "non-core approach left turn stays unknown by default",
    DEFAULT_UTURN_UNKNOWN: "default U-turn stays unknown",
    PROFILE_LEFT_UTURN_SERVICE_ALLOWED: "left/U-turn service profile allows the movement",
    PROFILE_LEFT_UTURN_SERVICE_FORBID_THROUGH: "left/U-turn service profile forbids through",
    PROFILE_LEFT_UTURN_SERVICE_FORBID_RIGHT: "left/U-turn service profile forbids right",
    PROFILE_PAIRED_MAINLINE_FORBID_LEFT: "paired mainline profile forbids left",
    PROFILE_PAIRED_MAINLINE_FORBID_UTURN: "paired mainline profile forbids U-turn",
    UNKNOWN_TURN_SENSE: "turn_sense cannot be stably determined",
    UNKNOWN_PARALLEL_CROSS_COUNT: "parallel_cross_count cannot be stably determined",
}

REASON_BREAKPOINTS = {
    INVALID_ENTRY_EXIT_ROLE: ("movement_side",),
    NOT_SAME_CONTROL_ZONE: ("same_signalized_control_zone",),
    UNKNOWN_CONTROL_ZONE: ("same_signalized_control_zone",),
    NON_STANDARD_EXIT_LEG: ("target.exit_leg_role",),
    UNKNOWN_TARGET_STANDARD_EXIT: ("target.exit_leg_role",),
    SINGLE_PARALLEL_CROSS_DEFAULT_UNKNOWN: ("parallel_cross_count",),
    MULTI_PARALLEL_CROSS_FORBIDDEN: ("parallel_cross_count",),
    PROFILE_LEFT_UTURN_SERVICE_ALLOWED: ("source.approach_profile",),
    PROFILE_LEFT_UTURN_SERVICE_FORBID_THROUGH: ("source.approach_profile",),
    PROFILE_LEFT_UTURN_SERVICE_FORBID_RIGHT: ("source.approach_profile",),
    PROFILE_PAIRED_MAINLINE_FORBID_LEFT: ("source.approach_profile",),
    PROFILE_PAIRED_MAINLINE_FORBID_UTURN: ("source.approach_profile",),
    UNKNOWN_TURN_SENSE: ("turn_sense",),
    UNKNOWN_PARALLEL_CROSS_COUNT: ("parallel_cross_count",),
}


def reason_text_for(codes: list[str] | tuple[str, ...]) -> str:
    parts = [REASON_TEXT.get(code, code) for code in codes]
    return "; ".join(parts)


def breakpoints_for(codes: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for code in codes:
        for breakpoint_name in REASON_BREAKPOINTS.get(code, ()):
            if breakpoint_name in seen:
                continue
            seen.add(breakpoint_name)
            ordered.append(breakpoint_name)
    return tuple(ordered)
