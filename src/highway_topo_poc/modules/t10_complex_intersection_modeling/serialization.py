from __future__ import annotations

from typing import Any

from .models import (
    ApproachModel,
    ArmModel,
    IntersectionBundle,
    IntersectionModel,
    MovementCandidate,
    MovementDecision,
    NormalizedGeometryRef,
)


def serialize_geometry_ref(geometry_ref: NormalizedGeometryRef) -> dict[str, Any]:
    point = None
    if geometry_ref.point is not None:
        point = [float(geometry_ref.point.x), float(geometry_ref.point.y)]
    line = None
    if geometry_ref.line is not None:
        line = [[float(x), float(y)] for x, y in geometry_ref.line.coords]
    return {
        "point": point,
        "line": line,
    }


def serialize_intersection(intersection: IntersectionModel) -> dict[str, Any]:
    return {
        "intersection_id": intersection.intersection_id,
        "node_group_id": intersection.node_group_id,
        "member_node_ids": list(intersection.member_node_ids),
        "control_type": intersection.control_type,
        "signalized_control_zone_id": intersection.signalized_control_zone_id,
        "source_type": intersection.source_type,
        "remarks": list(intersection.remarks),
    }


def serialize_arm(arm: ArmModel) -> dict[str, Any]:
    return {
        "arm_id": arm.arm_id,
        "intersection_id": arm.intersection_id,
        "member_approach_ids": list(arm.member_approach_ids),
        "arm_heading_group": arm.arm_heading_group,
        "representative_angle_deg": arm.representative_angle_deg,
        "remarks": list(arm.remarks),
    }


def serialize_approach(approach: ApproachModel) -> dict[str, Any]:
    return {
        "approach_id": approach.approach_id,
        "road_id": approach.road_id,
        "intersection_id": approach.intersection_id,
        "node_id": approach.node_id,
        "arm_id": approach.arm_id,
        "movement_side": approach.movement_side,
        "direction_type": approach.direction_type,
        "is_core_signalized_approach": approach.is_core_signalized_approach,
        "approach_profile": approach.approach_profile,
        "approach_profile_source": approach.approach_profile_source,
        "paired_mainline_approach_id": approach.paired_mainline_approach_id,
        "paired_mainline_source": approach.paired_mainline_source,
        "exit_leg_role": approach.exit_leg_role,
        "is_standard_exit_leg": approach.is_standard_exit_leg,
        "signalized_control_zone_id": approach.signalized_control_zone_id,
        "side_angle_deg": approach.side_angle_deg,
        "travel_angle_deg": approach.travel_angle_deg,
        "lateral_rank": approach.lateral_rank,
        "geometry_ref": serialize_geometry_ref(approach.geometry_ref),
        "evidence_refs": list(approach.evidence_refs),
        "remarks": list(approach.remarks),
    }


def serialize_movement_candidate(candidate: MovementCandidate) -> dict[str, Any]:
    return {
        "movement_id": candidate.movement_id,
        "source_approach_id": candidate.source.approach_id,
        "target_approach_id": candidate.target.approach_id,
        "source_arm_id": candidate.source_arm_id,
        "target_arm_id": candidate.target_arm_id,
        "arm_relation": candidate.arm_relation,
        "turn_sense": candidate.turn_sense,
        "parallel_cross_count": candidate.parallel_cross_count,
        "same_signalized_control_zone": candidate.same_signalized_control_zone,
        "evidence_refs": list(candidate.evidence_refs),
        "remarks": list(candidate.remarks),
    }


def serialize_movement_decision(decision: MovementDecision) -> dict[str, Any]:
    return {
        "movement_id": decision.movement_id,
        "status": decision.status,
        "confidence": decision.confidence,
        "reason_codes": list(decision.reason_codes),
        "reason_text": decision.reason_text,
        "breakpoints": list(decision.breakpoints),
    }


def serialize_movement_result(candidate: MovementCandidate, decision: MovementDecision) -> dict[str, Any]:
    return {
        "movement_id": candidate.movement_id,
        "source_approach_id": candidate.source.approach_id,
        "target_approach_id": candidate.target.approach_id,
        "status": decision.status,
        "confidence": decision.confidence,
        "reason_codes": list(decision.reason_codes),
        "reason_text": decision.reason_text,
        "breakpoints": list(decision.breakpoints),
        "turn_sense": candidate.turn_sense,
        "parallel_cross_count": candidate.parallel_cross_count,
        "arm_relation": candidate.arm_relation,
        "same_signalized_control_zone": candidate.same_signalized_control_zone,
        "source_approach_profile": candidate.source.approach_profile,
        "source_approach_profile_source": candidate.source.approach_profile_source,
        "source_is_core_signalized_approach": candidate.source.is_core_signalized_approach,
        "source_paired_mainline_source": candidate.source.paired_mainline_source,
        "target_exit_leg_role": candidate.target.exit_leg_role,
        "target_is_standard_exit_leg": candidate.target.is_standard_exit_leg,
    }


def serialize_bundle(bundle: IntersectionBundle) -> dict[str, Any]:
    return {
        "intersection": serialize_intersection(bundle.intersection),
        "arms": [serialize_arm(arm) for arm in bundle.arms],
        "approaches": [serialize_approach(approach) for approach in bundle.approaches],
        "movements": [serialize_movement_candidate(movement) for movement in bundle.movements],
        "warnings": list(bundle.warnings),
    }


def build_movement_matrix(
    bundle: IntersectionBundle,
    decisions: list[MovementDecision] | tuple[MovementDecision, ...],
) -> dict[str, Any]:
    decision_by_id = {decision.movement_id: decision for decision in decisions}
    entry_ids = sorted(approach.approach_id for approach in bundle.approaches if approach.movement_side == "entry")
    exit_ids = sorted(approach.approach_id for approach in bundle.approaches if approach.movement_side == "exit")
    cells: dict[str, dict[str, dict[str, Any]]] = {}
    for movement in bundle.movements:
        decision = decision_by_id[movement.movement_id]
        cells.setdefault(movement.source.approach_id, {})[movement.target.approach_id] = serialize_movement_result(movement, decision)
    return {
        "intersection_id": bundle.intersection.intersection_id,
        "entry_approach_ids": entry_ids,
        "exit_approach_ids": exit_ids,
        "cells": cells,
    }


__all__ = [
    "build_movement_matrix",
    "serialize_approach",
    "serialize_arm",
    "serialize_bundle",
    "serialize_geometry_ref",
    "serialize_intersection",
    "serialize_movement_candidate",
    "serialize_movement_decision",
    "serialize_movement_result",
]
