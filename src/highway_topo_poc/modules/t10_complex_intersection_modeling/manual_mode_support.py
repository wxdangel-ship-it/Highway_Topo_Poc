from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .api import T10RunResult


_SUPPORTED_MANUAL_PROFILES = ("left_uturn_service",)


def build_approach_catalog(result: T10RunResult) -> dict[str, Any]:
    approaches: list[dict[str, Any]] = []
    for approach in sorted(result.bundle.approaches, key=lambda item: item.approach_id):
        approaches.append(
            {
                "intersection_id": result.bundle.intersection.intersection_id,
                "mainid": result.bundle.intersection.node_group_id,
                "approach_id": approach.approach_id,
                "road_id": approach.road_id,
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
                "lateral_rank": approach.lateral_rank,
                "selector_hints": _build_selector_hints(approach),
            }
        )
    return {
        "intersection_id": result.bundle.intersection.intersection_id,
        "mainid": result.bundle.intersection.node_group_id,
        "approach_count": len(approaches),
        "approaches": approaches,
    }


def build_manual_override_template(result: T10RunResult) -> dict[str, Any]:
    entry_approaches = sorted(
        (approach for approach in result.bundle.approaches if approach.movement_side == "entry"),
        key=lambda item: item.approach_id,
    )
    exit_approaches = sorted(
        (approach for approach in result.bundle.approaches if approach.movement_side == "exit"),
        key=lambda item: item.approach_id,
    )
    return {
        "metadata": {
            "intersection_id": result.bundle.intersection.intersection_id,
            "mainid": result.bundle.intersection.node_group_id,
            "source_type": result.bundle.intersection.source_type,
            "generation_source": "t10_manual_override_template",
            "approach_count": len(result.bundle.approaches),
            "entry_approach_count": len(entry_approaches),
            "exit_approach_count": len(exit_approaches),
            "notes": [
                "Fill service_profile_map only with currently supported manual profiles.",
                "paired_mainline_map keys and values should point to entry approaches.",
                "This template is manual-only and does not imply automatic detection.",
            ],
            "supported_service_profiles": list(_SUPPORTED_MANUAL_PROFILES),
        },
        "service_profile_map": {},
        "paired_mainline_map": {},
        "selector_examples": {
            "entry_road_ids": sorted({approach.road_id for approach in entry_approaches}),
            "entry_road_side_selectors": sorted(
                {f"{approach.road_id}:{approach.movement_side}" for approach in entry_approaches}
            ),
            "entry_approach_ids": [approach.approach_id for approach in entry_approaches],
            "preferred_entry_selectors": [approach.approach_id for approach in entry_approaches],
        },
    }


def build_review_unknown_movements(result: T10RunResult) -> dict[str, Any]:
    items = [
        {
            "movement_id": movement["movement_id"],
            "source_approach_id": movement["source_approach_id"],
            "target_approach_id": movement["target_approach_id"],
            "status": movement["status"],
            "reason_codes": list(movement["reason_codes"]),
            "breakpoints": list(movement["breakpoints"]),
            "turn_sense": movement["turn_sense"],
            "parallel_cross_count": movement["parallel_cross_count"],
            "source_approach_profile": movement["source_approach_profile"],
            "target_exit_leg_role": movement["target_exit_leg_role"],
        }
        for movement in result.movement_results
        if movement["status"] == "unknown"
    ]
    return {
        "intersection_id": result.bundle.intersection.intersection_id,
        "mainid": result.bundle.intersection.node_group_id,
        "unknown_movement_count": len(items),
        "items": items,
    }


def build_review_nonstandard_targets(result: T10RunResult) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    exit_approaches = sorted(
        (approach for approach in result.bundle.approaches if approach.movement_side == "exit"),
        key=lambda item: item.approach_id,
    )
    for approach in exit_approaches:
        if approach.exit_leg_role not in {"auxiliary_parallel_exit", "access_exit", "unknown"}:
            continue
        affected_movements = [
            movement["movement_id"]
            for movement in result.movement_results
            if movement["target_approach_id"] == approach.approach_id
        ]
        candidates.append(
            {
                "approach_id": approach.approach_id,
                "road_id": approach.road_id,
                "exit_leg_role": approach.exit_leg_role,
                "is_standard_exit_leg": approach.is_standard_exit_leg,
                "selector_hints": _build_selector_hints(approach),
                "affected_movement_count": len(affected_movements),
                "affected_movement_ids": affected_movements,
            }
        )
    return {
        "intersection_id": result.bundle.intersection.intersection_id,
        "mainid": result.bundle.intersection.node_group_id,
        "target_count": len(candidates),
        "items": candidates,
    }


def build_review_special_profile_gaps(result: T10RunResult) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    entry_approaches = sorted(
        (approach for approach in result.bundle.approaches if approach.movement_side == "entry"),
        key=lambda item: item.approach_id,
    )
    for approach in entry_approaches:
        if approach.approach_profile not in {"default_signalized", "unknown"}:
            continue
        review_reason = (
            "approach_profile_unknown_review_needed"
            if approach.approach_profile == "unknown"
            else "default_or_placeholder_profile_review_candidate"
        )
        candidates.append(
            {
                "approach_id": approach.approach_id,
                "road_id": approach.road_id,
                "movement_side": approach.movement_side,
                "approach_profile": approach.approach_profile,
                "approach_profile_source": approach.approach_profile_source,
                "paired_mainline_approach_id": approach.paired_mainline_approach_id,
                "paired_mainline_source": approach.paired_mainline_source,
                "is_core_signalized_approach": approach.is_core_signalized_approach,
                "selector_hints": _build_selector_hints(approach),
                "review_reason": review_reason,
                "candidate_only": True,
            }
        )
    return {
        "intersection_id": result.bundle.intersection.intersection_id,
        "mainid": result.bundle.intersection.node_group_id,
        "candidate_count": len(candidates),
        "items": candidates,
    }


def build_review_bundle(result: T10RunResult) -> dict[str, Any]:
    unknown_movements = build_review_unknown_movements(result)
    nonstandard_targets = build_review_nonstandard_targets(result)
    special_profile_gaps = build_review_special_profile_gaps(result)
    return {
        "intersection_id": result.bundle.intersection.intersection_id,
        "mainid": result.bundle.intersection.node_group_id,
        "unknown_movements": unknown_movements,
        "nonstandard_targets": nonstandard_targets,
        "special_profile_gaps": special_profile_gaps,
    }


def write_t10_manual_support_outputs(
    result: T10RunResult,
    output_dir: str | Path,
    *,
    write_catalog: bool = False,
    write_override_template: bool = False,
    write_review: bool = False,
) -> dict[str, str]:
    resolved_dir = Path(output_dir)
    resolved_dir.mkdir(parents=True, exist_ok=True)

    written_files: dict[str, str] = {}
    if write_catalog:
        catalog_path = resolved_dir / "approach_catalog.json"
        catalog_path.write_text(
            json.dumps(build_approach_catalog(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written_files["approach_catalog.json"] = str(catalog_path)
    if write_override_template:
        template_path = resolved_dir / "manual_override.template.json"
        template_path.write_text(
            json.dumps(build_manual_override_template(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written_files["manual_override.template.json"] = str(template_path)
    if write_review:
        review_unknown_path = resolved_dir / "review_unknown_movements.json"
        review_nonstandard_path = resolved_dir / "review_nonstandard_targets.json"
        review_special_profile_path = resolved_dir / "review_special_profile_gaps.json"
        review_summary_path = resolved_dir / "review_summary.txt"
        review_unknown_payload = build_review_unknown_movements(result)
        review_nonstandard_payload = build_review_nonstandard_targets(result)
        review_special_profile_payload = build_review_special_profile_gaps(result)
        review_unknown_path.write_text(
            json.dumps(review_unknown_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        review_nonstandard_path.write_text(
            json.dumps(review_nonstandard_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        review_special_profile_path.write_text(
            json.dumps(review_special_profile_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        review_summary_path.write_text(
            _build_review_summary_text(
                result,
                unknown_count=review_unknown_payload["unknown_movement_count"],
                nonstandard_count=review_nonstandard_payload["target_count"],
                gap_count=review_special_profile_payload["candidate_count"],
            ),
            encoding="utf-8",
        )
        written_files["review_unknown_movements.json"] = str(review_unknown_path)
        written_files["review_nonstandard_targets.json"] = str(review_nonstandard_path)
        written_files["review_special_profile_gaps.json"] = str(review_special_profile_path)
        written_files["review_summary.txt"] = str(review_summary_path)
    return written_files


def _build_selector_hints(approach: Any) -> dict[str, Any]:
    return {
        "road_id": approach.road_id,
        "road_side_selector": f"{approach.road_id}:{approach.movement_side}",
        "approach_id": approach.approach_id,
        "preferred_service_profile_selector": (
            approach.approach_id if approach.movement_side == "entry" else None
        ),
        "preferred_paired_mainline_selector": (
            approach.approach_id if approach.movement_side == "entry" else None
        ),
    }


def _build_review_summary_text(
    result: T10RunResult,
    *,
    unknown_count: int,
    nonstandard_count: int,
    gap_count: int,
) -> str:
    lines = [
        f"intersection_id: {result.bundle.intersection.intersection_id}",
        f"mainid: {result.bundle.intersection.node_group_id}",
        f"unknown_movement_count: {unknown_count}",
        f"nonstandard_or_unknown_target_count: {nonstandard_count}",
        f"special_profile_gap_candidate_count: {gap_count}",
        "notes:",
        "  - review outputs are candidate-only and do not imply automatic service-road detection",
        "  - special profile gaps require manual confirmation before writing overrides",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "build_approach_catalog",
    "build_manual_override_template",
    "build_review_bundle",
    "build_review_nonstandard_targets",
    "build_review_special_profile_gaps",
    "build_review_unknown_movements",
    "write_t10_manual_support_outputs",
]
