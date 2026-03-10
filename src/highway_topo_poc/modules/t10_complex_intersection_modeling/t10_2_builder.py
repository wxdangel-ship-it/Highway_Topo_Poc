from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from shapely.geometry import Point

from .manual_overrides import load_manual_override_source
from .models import (
    ApproachModel,
    ArmModel,
    IntersectionBundle,
    IntersectionModel,
    MovementCandidate,
    NormalizedGeometryRef,
)
from .normalize import (
    NormalizedNode,
    NormalizedRoad,
    circular_diff_deg,
    normalize_node_features,
    normalize_road_features,
    road_away_vector,
    road_trend_vector,
    vector_angle_deg,
)
from .service_profile_resolver import (
    apply_manual_service_maps,
    apply_placeholder_paired_mainline_detection,
    detect_left_uturn_service_from_raw,
    find_raw_formway_value,
)

APPROACH_OVERRIDE_FIELDS = {
    "approach_profile",
    "exit_leg_role",
    "is_core_signalized_approach",
    "paired_mainline_approach_id",
}

_APPROACH_PROFILE_ALLOWED = {
    "default_signalized",
    "left_uturn_service",
    "paired_mainline_no_left_uturn",
    "unknown",
}

_EXIT_ROLE_ALLOWED = {
    "core_standard_exit",
    "service_standard_exit",
    "auxiliary_parallel_exit",
    "access_exit",
    "unknown",
}

_ARM_CLUSTER_DEG = 40.0


def approach_key(road_id: str, movement_side: str) -> str:
    return f"{road_id}:{movement_side}"


def build_intersection_bundles(
    *,
    node_features: list[dict[str, Any]],
    road_features: list[dict[str, Any]],
    source_type: str = "real",
    approach_overrides: dict[str, dict[str, Any]] | None = None,
    manual_override_source: str | Path | dict[str, Any] | None = None,
    manual_service_profile_map: dict[str, str] | None = None,
    manual_paired_mainline_map: dict[str, str] | None = None,
) -> list[IntersectionBundle]:
    nodes = normalize_node_features(node_features)
    roads = normalize_road_features(road_features)
    file_service_profile_map, file_paired_mainline_map = load_manual_override_source(manual_override_source)
    return _build_bundles(
        nodes=nodes,
        roads=roads,
        source_type=source_type,
        approach_overrides=approach_overrides or {},
        manual_service_profile_map={**file_service_profile_map, **(manual_service_profile_map or {})},
        manual_paired_mainline_map={**file_paired_mainline_map, **(manual_paired_mainline_map or {})},
    )


def build_intersection_bundles_with_manual_overrides(
    *,
    node_features: list[dict[str, Any]],
    road_features: list[dict[str, Any]],
    manual_override_source: str | Path | dict[str, Any] | None = None,
    source_type: str = "real",
    approach_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[IntersectionBundle]:
    return build_intersection_bundles(
        node_features=node_features,
        road_features=road_features,
        source_type=source_type,
        approach_overrides=approach_overrides,
        manual_override_source=manual_override_source,
    )


def _build_bundles(
    *,
    nodes: list[NormalizedNode],
    roads: list[NormalizedRoad],
    source_type: str,
    approach_overrides: dict[str, dict[str, Any]],
    manual_service_profile_map: dict[str, str],
    manual_paired_mainline_map: dict[str, str],
) -> list[IntersectionBundle]:
    node_by_id = {node.node_id: node for node in nodes}
    groups: dict[Any, list[NormalizedNode]] = defaultdict(list)
    for node in nodes:
        groups[node.mainid].append(node)

    bundles: list[IntersectionBundle] = []
    for mainid, group_nodes in groups.items():
        group_node_ids = {node.node_id for node in group_nodes}
        intersection = IntersectionModel(
            intersection_id=f"intersection:{mainid}",
            node_group_id=mainid,
            member_node_ids=tuple(sorted(group_node_ids, key=str)),
            control_type="signalized",
            signalized_control_zone_id=mainid,
            source_type=source_type,
            remarks=(),
        )
        incident_roads = [road for road in roads if road.snodeid in group_node_ids or road.enodeid in group_node_ids]
        approaches = _build_approaches(
            intersection=intersection,
            group_node_ids=group_node_ids,
            incident_roads=incident_roads,
            node_by_id=node_by_id,
            approach_overrides=approach_overrides,
        )
        arms, approaches = _assign_arms(intersection=intersection, approaches=approaches)
        approaches = _apply_lateral_ranks(approaches)
        approaches = _apply_entry_defaults(approaches)
        approaches = apply_manual_service_maps(
            approaches=approaches,
            manual_service_profile_map=manual_service_profile_map,
            manual_paired_mainline_map=manual_paired_mainline_map,
        )
        approaches = apply_placeholder_paired_mainline_detection(approaches)
        approaches = _apply_exit_defaults(approaches)
        movements = _build_movements(intersection=intersection, approaches=approaches, arms=arms)
        bundles.append(
            IntersectionBundle(
                intersection=intersection,
                arms=tuple(arms),
                approaches=tuple(approaches),
                movements=tuple(movements),
                warnings=(),
                approach_index={approach.approach_id: approach for approach in approaches},
                arm_index={arm.arm_id: arm for arm in arms},
            )
        )
    return bundles


def _build_approaches(
    *,
    intersection: IntersectionModel,
    group_node_ids: set[Any],
    incident_roads: list[NormalizedRoad],
    node_by_id: dict[Any, NormalizedNode],
    approach_overrides: dict[str, dict[str, Any]],
) -> list[ApproachModel]:
    approaches: list[ApproachModel] = []
    for road in incident_roads:
        attached_node_id = _attached_node_id(road=road, group_node_ids=group_node_ids)
        if attached_node_id is None:
            continue
        node = node_by_id.get(attached_node_id)
        if node is None:
            continue

        away_vec = road_away_vector(road, node_id=attached_node_id)
        trend_vec = road_trend_vector(road, node_id=attached_node_id)
        side_angle = vector_angle_deg(*away_vec)
        trend_angle = vector_angle_deg(*trend_vec)
        raw_formway = find_raw_formway_value(raw_properties=road.raw_properties)

        for movement_side in _movement_sides_for_road(road=road, group_node_ids=group_node_ids):
            travel_angle = vector_angle_deg(*_travel_vector(away_vec=away_vec, movement_side=movement_side))
            key = approach_key(road.road_id, movement_side)
            override = dict(approach_overrides.get(key) or {})
            detected_profile = None
            if movement_side == "entry":
                detected_profile = detect_left_uturn_service_from_raw(raw_properties=road.raw_properties)
            approach_profile, approach_profile_source = _resolve_approach_profile(
                movement_side=movement_side,
                override=override,
                detected_profile=detected_profile,
                raw_formway=raw_formway,
            )
            if approach_profile not in _APPROACH_PROFILE_ALLOWED:
                approach_profile = "unknown"
                approach_profile_source = "unknown"
            exit_leg_role = str(override.get("exit_leg_role", "unknown"))
            if exit_leg_role not in _EXIT_ROLE_ALLOWED:
                exit_leg_role = "unknown"
            is_core = override.get("is_core_signalized_approach", "unknown")
            if is_core not in {True, False, "unknown"}:
                is_core = "unknown"
            paired_mainline_approach_id = override.get("paired_mainline_approach_id")
            paired_mainline_source = _resolve_paired_mainline_source(
                movement_side=movement_side,
                override=override,
                paired_mainline_approach_id=paired_mainline_approach_id,
            )

            remarks: list[str] = []
            if circular_diff_deg(side_angle, trend_angle) > 35.0:
                remarks.append("TODO: far-trend correction boundary for arm grouping remains candidate-only")
            if raw_formway is not None and detected_profile is None:
                remarks.append("TODO: raw formway detected but bit mapping is unconfirmed; auto service-road inference stays disabled")
            if "approach_profile" in override:
                remarks.append("manual_override:approach_profile")
            if "is_core_signalized_approach" in override:
                remarks.append("manual_override:is_core_signalized_approach")
            if "exit_leg_role" in override:
                remarks.append("manual_override:exit_leg_role")
            if "paired_mainline_approach_id" in override:
                remarks.append("manual_override:paired_mainline_approach_id")

            approaches.append(
                ApproachModel(
                    approach_id=f"{intersection.intersection_id}|{key}",
                    road_id=road.road_id,
                    intersection_id=intersection.intersection_id,
                    node_id=attached_node_id,
                    arm_id="",
                    movement_side=movement_side,
                    direction_type=_direction_type(road.direction),
                    is_core_signalized_approach=is_core,
                    approach_profile=approach_profile,
                    approach_profile_source=approach_profile_source,
                    paired_mainline_approach_id=paired_mainline_approach_id,
                    paired_mainline_source=paired_mainline_source,
                    exit_leg_role=exit_leg_role,
                    is_standard_exit_leg="unknown",
                    signalized_control_zone_id=intersection.signalized_control_zone_id,
                    side_angle_deg=side_angle,
                    travel_angle_deg=travel_angle,
                    lateral_rank=None,
                    geometry_ref=NormalizedGeometryRef(point=node.point, line=road.line),
                    evidence_refs=(f"road:{road.road_id}", f"node:{attached_node_id}"),
                    remarks=tuple(remarks),
                )
            )
    return approaches


def _resolve_approach_profile(
    *,
    movement_side: str,
    override: dict[str, Any],
    detected_profile: str | None,
    raw_formway: Any | None,
) -> tuple[str, str]:
    if "approach_profile" in override:
        return str(override.get("approach_profile")), "approach_override"
    if detected_profile is not None:
        return detected_profile, "auto_detected"
    if movement_side == "entry" and raw_formway is not None:
        return "default_signalized", "auto_detection_placeholder_no_hit"
    return "default_signalized", "default_derived"


def _resolve_paired_mainline_source(
    *,
    movement_side: str,
    override: dict[str, Any],
    paired_mainline_approach_id: str | None,
) -> str:
    if movement_side != "entry":
        return "not_applicable"
    if "paired_mainline_approach_id" in override and paired_mainline_approach_id:
        return "approach_override"
    return "not_applicable"


def _attached_node_id(*, road: NormalizedRoad, group_node_ids: set[Any]) -> Any | None:
    if road.snodeid in group_node_ids and road.enodeid not in group_node_ids:
        return road.snodeid
    if road.enodeid in group_node_ids and road.snodeid not in group_node_ids:
        return road.enodeid
    if road.snodeid in group_node_ids:
        return road.snodeid
    if road.enodeid in group_node_ids:
        return road.enodeid
    return None


def _movement_sides_for_road(*, road: NormalizedRoad, group_node_ids: set[Any]) -> list[str]:
    direction = road.direction
    if direction in (0, 1, None):
        return ["entry", "exit"]
    sides: list[str] = []
    if direction == 2:
        if road.enodeid in group_node_ids:
            sides.append("entry")
        if road.snodeid in group_node_ids:
            sides.append("exit")
    elif direction == 3:
        if road.snodeid in group_node_ids:
            sides.append("entry")
        if road.enodeid in group_node_ids:
            sides.append("exit")
    return sides or ["entry", "exit"]


def _direction_type(direction: int | None) -> str:
    if direction in (0, 1, None):
        return "bidirectional"
    if direction in (2, 3):
        return "one_way"
    return "unknown"


def _travel_vector(*, away_vec: tuple[float, float], movement_side: str) -> tuple[float, float]:
    ax, ay = away_vec
    if movement_side == "entry":
        return (-ax, -ay)
    return (ax, ay)


def _assign_arms(
    *,
    intersection: IntersectionModel,
    approaches: list[ApproachModel],
) -> tuple[list[ArmModel], list[ApproachModel]]:
    clusters: list[dict[str, Any]] = []
    updated: list[ApproachModel] = []
    for approach in sorted(approaches, key=lambda item: (item.side_angle_deg, item.approach_id)):
        best_idx = _best_cluster_index(approach.side_angle_deg, clusters)
        if best_idx is None:
            clusters.append({"angles": [approach.side_angle_deg], "members": [approach.approach_id]})
            best_idx = len(clusters) - 1
        else:
            clusters[best_idx]["angles"].append(approach.side_angle_deg)
            clusters[best_idx]["members"].append(approach.approach_id)
        updated.append(replace(approach, arm_id=f"{intersection.intersection_id}|arm:{best_idx}"))

    arms: list[ArmModel] = []
    for idx, cluster in enumerate(clusters):
        arms.append(
            ArmModel(
                arm_id=f"{intersection.intersection_id}|arm:{idx}",
                intersection_id=intersection.intersection_id,
                member_approach_ids=tuple(cluster["members"]),
                arm_heading_group=f"group_{idx}",
                representative_angle_deg=_mean_angle_deg(cluster["angles"]),
                remarks=("TODO: arm_heading_group remains abstract; no absolute NSEW binding in MVP",),
            )
        )
    return arms, updated


def _best_cluster_index(angle: float, clusters: list[dict[str, Any]]) -> int | None:
    best_idx: int | None = None
    best_diff = 999.0
    for idx, cluster in enumerate(clusters):
        diff = circular_diff_deg(angle, _mean_angle_deg(cluster["angles"]))
        if diff <= _ARM_CLUSTER_DEG and diff < best_diff:
            best_idx = idx
            best_diff = diff
    return best_idx


def _mean_angle_deg(angles: list[float]) -> float:
    sx = 0.0
    sy = 0.0
    for angle in angles:
        rad = math.radians(angle)
        sx += math.cos(rad)
        sy += math.sin(rad)
    if abs(sx) <= 1e-9 and abs(sy) <= 1e-9:
        return float(angles[0])
    result = math.degrees(math.atan2(sy, sx))
    if result < 0:
        result += 360.0
    return float(result)


def _apply_lateral_ranks(approaches: list[ApproachModel]) -> list[ApproachModel]:
    by_arm_side: dict[tuple[str, str], list[ApproachModel]] = defaultdict(list)
    for approach in approaches:
        by_arm_side[(approach.arm_id, approach.movement_side)].append(approach)

    updated: dict[str, ApproachModel] = {approach.approach_id: approach for approach in approaches}
    for (_arm_id, movement_side), items in by_arm_side.items():
        scored = sorted(items, key=lambda item: _left_rank_key(item, movement_side), reverse=True)
        for rank, approach in enumerate(scored):
            updated[approach.approach_id] = replace(approach, lateral_rank=rank)
    return list(updated.values())


def _left_rank_key(approach: ApproachModel, movement_side: str) -> float:
    point = approach.geometry_ref.point or Point(0.0, 0.0)
    travel_rad = math.radians(approach.travel_angle_deg)
    left_axis = (-math.sin(travel_rad), math.cos(travel_rad))
    return float(point.x * left_axis[0] + point.y * left_axis[1])


def _apply_entry_defaults(approaches: list[ApproachModel]) -> list[ApproachModel]:
    by_arm: dict[str, list[ApproachModel]] = defaultdict(list)
    for approach in approaches:
        if approach.movement_side == "entry":
            by_arm[approach.arm_id].append(approach)

    updated: dict[str, ApproachModel] = {approach.approach_id: approach for approach in approaches}
    for items in by_arm.values():
        unresolved = [
            item
            for item in items
            if item.is_core_signalized_approach == "unknown" and "manual_override:is_core_signalized_approach" not in item.remarks
        ]
        if not unresolved:
            continue
        if len(items) == 1:
            item = unresolved[0]
            updated[item.approach_id] = replace(item, is_core_signalized_approach=True)
            continue
        ordered = sorted(items, key=lambda item: (item.lateral_rank is None, item.lateral_rank if item.lateral_rank is not None else 999))
        if ordered and ordered[0].lateral_rank is not None:
            leftmost_id = ordered[0].approach_id
            for item in unresolved:
                updated[item.approach_id] = replace(item, is_core_signalized_approach=item.approach_id == leftmost_id)
        else:
            for item in unresolved:
                updated[item.approach_id] = replace(item, remarks=item.remarks + ("TODO: core approach inference ambiguous",))
    return list(updated.values())


def _apply_exit_defaults(approaches: list[ApproachModel]) -> list[ApproachModel]:
    by_arm: dict[str, list[ApproachModel]] = defaultdict(list)
    for approach in approaches:
        if approach.movement_side == "exit":
            by_arm[approach.arm_id].append(approach)

    updated: dict[str, ApproachModel] = {approach.approach_id: approach for approach in approaches}
    for items in by_arm.values():
        unresolved = [
            item
            for item in items
            if item.exit_leg_role == "unknown" and "manual_override:exit_leg_role" not in item.remarks
        ]
        if len(items) == 1 and unresolved:
            item = unresolved[0]
            updated[item.approach_id] = replace(item, exit_leg_role="core_standard_exit", is_standard_exit_leg=True)
        for item in items:
            role = updated[item.approach_id].exit_leg_role
            if role in {"core_standard_exit", "service_standard_exit"}:
                standard: bool | str = True
            elif role in {"auxiliary_parallel_exit", "access_exit"}:
                standard = False
            else:
                standard = "unknown"
            updated[item.approach_id] = replace(updated[item.approach_id], is_standard_exit_leg=standard)
    return list(updated.values())


def _build_movements(
    *,
    intersection: IntersectionModel,
    approaches: list[ApproachModel],
    arms: list[ArmModel],
) -> list[MovementCandidate]:
    arm_by_id = {arm.arm_id: arm for arm in arms}
    entries = [approach for approach in approaches if approach.movement_side == "entry"]
    exits = [approach for approach in approaches if approach.movement_side == "exit"]
    movements: list[MovementCandidate] = []
    for source in entries:
        for target in exits:
            relation = _arm_relation(arm_by_id[source.arm_id], arm_by_id[target.arm_id])
            turn_sense = _derive_turn_sense(source=source, target=target, arm_relation=relation)
            cross_count = _derive_parallel_cross_count(source=source, target=target)
            remarks: list[str] = []
            if relation == "same":
                remarks.append("same-arm target kept in uturn family; lateral shift remains in parallel_cross_count")
            if cross_count == "unknown":
                remarks.append("TODO: corridor-layer relation could not be stably determined")
            movements.append(
                MovementCandidate(
                    movement_id=f"{intersection.intersection_id}|{approach_key(source.road_id, source.movement_side)}->{approach_key(target.road_id, target.movement_side)}",
                    source=source,
                    target=target,
                    source_arm_id=source.arm_id,
                    target_arm_id=target.arm_id,
                    arm_relation=relation,
                    turn_sense=turn_sense,
                    parallel_cross_count=cross_count,
                    same_signalized_control_zone=source.signalized_control_zone_id == target.signalized_control_zone_id,
                    evidence_refs=source.evidence_refs + target.evidence_refs,
                    remarks=tuple(remarks),
                )
            )
    return movements


def _arm_relation(source_arm: ArmModel, target_arm: ArmModel) -> str:
    if source_arm.arm_id == target_arm.arm_id:
        return "same"
    diff = circular_diff_deg(source_arm.representative_angle_deg, target_arm.representative_angle_deg)
    if diff >= 150.0:
        return "opposite"
    return "adjacent"


def _derive_turn_sense(*, source: ApproachModel, target: ApproachModel, arm_relation: str) -> str:
    if arm_relation == "same":
        return "uturn"
    if arm_relation == "opposite":
        return "through"
    delta = _signed_angle_delta(source.travel_angle_deg, target.travel_angle_deg)
    if abs(delta) < 15.0:
        return "through"
    return "left" if delta > 0 else "right"


def _signed_angle_delta(source_deg: float, target_deg: float) -> float:
    return float((target_deg - source_deg + 180.0) % 360.0 - 180.0)


def _derive_parallel_cross_count(*, source: ApproachModel, target: ApproachModel) -> int | str:
    if source.lateral_rank is None or target.lateral_rank is None:
        return "unknown"
    delta = abs(int(source.lateral_rank) - int(target.lateral_rank))
    if delta == 0:
        return 0
    if delta == 1:
        return 1
    return "2+"
