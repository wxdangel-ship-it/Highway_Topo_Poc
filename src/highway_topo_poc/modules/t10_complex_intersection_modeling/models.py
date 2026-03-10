from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, Point


@dataclass(frozen=True)
class NormalizedGeometryRef:
    point: Point | None = None
    line: LineString | None = None


@dataclass(frozen=True)
class IntersectionModel:
    intersection_id: str
    node_group_id: Any
    member_node_ids: tuple[Any, ...]
    control_type: str
    signalized_control_zone_id: Any
    source_type: str
    remarks: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArmModel:
    arm_id: str
    intersection_id: str
    member_approach_ids: tuple[str, ...]
    arm_heading_group: str
    representative_angle_deg: float
    remarks: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApproachModel:
    approach_id: str
    road_id: str
    intersection_id: str
    node_id: Any
    arm_id: str
    movement_side: str
    direction_type: str
    is_core_signalized_approach: bool | str
    approach_profile: str
    approach_profile_source: str
    paired_mainline_approach_id: str | None
    paired_mainline_source: str
    exit_leg_role: str
    is_standard_exit_leg: bool | str
    signalized_control_zone_id: Any
    side_angle_deg: float
    travel_angle_deg: float
    lateral_rank: int | None
    geometry_ref: NormalizedGeometryRef
    evidence_refs: tuple[str, ...] = ()
    remarks: tuple[str, ...] = ()


@dataclass(frozen=True)
class MovementCandidate:
    movement_id: str
    source: ApproachModel
    target: ApproachModel
    source_arm_id: str
    target_arm_id: str
    arm_relation: str
    turn_sense: str
    parallel_cross_count: int | str
    same_signalized_control_zone: bool | str
    evidence_refs: tuple[str, ...] = ()
    remarks: tuple[str, ...] = ()


@dataclass(frozen=True)
class MovementDecision:
    movement_id: str
    status: str
    confidence: str
    reason_codes: tuple[str, ...]
    reason_text: str
    breakpoints: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntersectionBundle:
    intersection: IntersectionModel
    arms: tuple[ArmModel, ...]
    approaches: tuple[ApproachModel, ...]
    movements: tuple[MovementCandidate, ...]
    warnings: tuple[str, ...] = ()
    approach_index: dict[str, ApproachModel] = field(default_factory=dict)
    arm_index: dict[str, ArmModel] = field(default_factory=dict)
