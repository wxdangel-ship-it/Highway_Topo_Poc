from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .api import (
    build_t10_patch_run_summary,
    run_t10_all_intersections_from_patch_dir,
    run_t10_single_intersection_from_geojson_files,
    run_t10_single_intersection_from_patch_dir,
)
from .baseline_regression import run_t10_baseline_regression_smoke
from .dataset_runner import (
    DEFAULT_COMPUTE_BUFFER_M,
    build_t10_dataset_mainnodeid_summary,
    run_t10_mainnodeids_from_geojson_dataset,
)
from .geojson_io import coerce_mainid_value, parse_mainid_values
from .manual_mode_support import build_approach_catalog
from .multi_patch import build_t10_multi_patch_summary, run_t10_multi_patch_manual_mode
from .override_roundtrip import roundtrip_manual_override_source, write_override_roundtrip_report
from .review_cycle import (
    build_t10_patch_root_review_cycle_summary,
    build_t10_review_cycle_summary,
    run_t10_review_cycle_from_patch_dir,
    run_t10_review_cycle_from_patch_root,
)
from .run_diff import compare_t10_run_dirs, compare_t10_run_dirs_and_write_outputs
from .writer import write_t10_review_bundle, write_t10_run_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="T10 manual-mode runner")
    parser.add_argument("--node-file", help="Path to RCSDNode.geojson")
    parser.add_argument("--road-file", help="Path to RCSDRoad.geojson")
    parser.add_argument("--dataset-dir", help="Dataset directory containing RCSDNode/RCSDRoad inputs")
    parser.add_argument("--patch-dir", help="Patch directory containing RCSDNode/RCSDRoad inputs")
    parser.add_argument("--patch-root", help="Root directory containing multiple patch dirs")
    parser.add_argument("--patch-name", action="append", help="Optional patch name filter for --patch-root")
    parser.add_argument("--mainid", help="Optional mainid for single-intersection mode")
    parser.add_argument("--mainnodeids", nargs="+", help="One or more mainnodeid values")
    parser.add_argument("--all-mainids", action="store_true", help="Run all mainids inside one patch_dir")
    parser.add_argument("--manual-override", help="JSON override file path")
    parser.add_argument("--override-root", help="Directory containing per-patch override JSON files")
    parser.add_argument("--output-dir", help="Optional output directory")
    parser.add_argument(
        "--compute-buffer-m",
        type=float,
        default=DEFAULT_COMPUTE_BUFFER_M,
        help="Reserved compute buffer in meters for future geometry acceleration only",
    )
    parser.add_argument("--emit-review-bundle", action="store_true", help="Write run result + catalog + template + review outputs")
    parser.add_argument("--emit-catalog", action="store_true", help="Write approach_catalog.json")
    parser.add_argument(
        "--emit-override-template",
        action="store_true",
        help="Write manual_override.template.json",
    )
    parser.add_argument("--emit-review", action="store_true", help="Write review output files")
    parser.add_argument("--validate-override", action="store_true", help="Validate manual override against current approach catalog")
    parser.add_argument("--diff-before-dir", help="Existing run output dir used as diff baseline")
    parser.add_argument("--diff-after-dir", help="Existing run output dir used as diff target")
    parser.add_argument("--review-cycle", action="store_true", help="Run base/review/rerun/diff orchestration")
    parser.add_argument("--diff-against-dir", help="Optional diff baseline dir for --review-cycle")
    parser.add_argument("--run-regression-smoke", action="store_true", help="Run baseline regression smoke checks")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = _run_from_args(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_from_args(args: argparse.Namespace) -> dict[str, Any]:
    patch_dir = args.patch_dir
    patch_root = args.patch_root
    dataset_dir = args.dataset_dir
    node_file = args.node_file
    road_file = args.road_file
    mainid = _coerce_mainid(args.mainid)
    mainnodeids = parse_mainid_values(args.mainnodeids)
    manual_override = args.manual_override
    override_root = args.override_root
    output_dir = args.output_dir
    compute_buffer_m = float(args.compute_buffer_m)
    emit_review_bundle = bool(args.emit_review_bundle)
    emit_catalog = bool(args.emit_catalog or emit_review_bundle)
    emit_override_template = bool(args.emit_override_template or emit_review_bundle)
    emit_review = bool(args.emit_review or emit_review_bundle)
    emit_extra_outputs = emit_catalog or emit_override_template or emit_review
    validate_override = bool(args.validate_override)
    diff_before_dir = args.diff_before_dir
    diff_after_dir = args.diff_after_dir
    diff_mode = bool(diff_before_dir or diff_after_dir)
    review_cycle_mode = bool(args.review_cycle)
    regression_smoke_mode = bool(args.run_regression_smoke)

    active_modes = sum(
        1
        for is_active in (
            regression_smoke_mode,
            diff_mode,
            bool(dataset_dir),
            bool(patch_root),
            bool(patch_dir),
            bool(node_file or road_file),
        )
        if is_active
    )
    if active_modes > 1:
        raise ValueError("cli_conflict:file_mode_patch_dir_mode_patch_root_mode_and_diff_mode_are_mutually_exclusive")
    if regression_smoke_mode:
        if any((patch_root, patch_dir, node_file, road_file, manual_override, override_root, args.mainid, args.all_mainids, review_cycle_mode, diff_mode)):
            raise ValueError("cli_conflict:regression_smoke_mode_does_not_accept_run_inputs")
        payload = run_t10_baseline_regression_smoke(output_root=output_dir)
        return {
            "mode": "baseline_regression_smoke",
            **payload,
        }
    if emit_extra_outputs and not output_dir:
        raise ValueError("cli_emit_outputs_requires_output_dir")
    if review_cycle_mode and not output_dir:
        raise ValueError("cli_review_cycle_requires_output_dir")
    if diff_mode:
        if not diff_before_dir or not diff_after_dir:
            raise ValueError("cli_diff_requires_before_and_after_dirs")
        if manual_override or override_root:
            raise ValueError("cli_conflict:diff_mode_does_not_accept_override_inputs")
        payload = (
            compare_t10_run_dirs_and_write_outputs(diff_before_dir, diff_after_dir, output_dir)
            if output_dir
            else compare_t10_run_dirs(diff_before_dir, diff_after_dir)
        )
        return {
            "mode": "run_diff",
            **payload,
        }
    if dataset_dir:
        if patch_root or patch_dir or node_file or road_file:
            raise ValueError("cli_conflict:dataset_dir_mode_cannot_mix_with_other_input_modes")
        if override_root:
            raise ValueError("cli_conflict:dataset_dir_mode_does_not_accept_override_root")
        if args.all_mainids:
            raise ValueError("cli_conflict:dataset_dir_mode_requires_explicit_mainnodeids")
        if diff_mode:
            raise ValueError("cli_conflict:dataset_dir_mode_does_not_accept_diff_mode")
        if validate_override and not manual_override:
            raise ValueError("cli_validate_override_requires_manual_override")
        if not mainnodeids:
            raise ValueError("cli_dataset_dir_requires_mainnodeids")
        result = run_t10_mainnodeids_from_geojson_dataset(
            dataset_dir=dataset_dir,
            mainnodeids=mainnodeids,
            manual_override_source=manual_override,
            output_root=output_dir,
            validate_override=validate_override,
            compute_buffer_m=compute_buffer_m,
        )
        return {
            "mode": "dataset_mainnodeid_review_cycle",
            **build_t10_dataset_mainnodeid_summary(result),
        }
    if patch_root:
        if mainid is not None:
            raise ValueError("cli_conflict:patch_root_mode_does_not_accept_mainid")
        if mainnodeids:
            raise ValueError("cli_conflict:patch_root_mode_does_not_accept_mainnodeids")
        if args.all_mainids and not review_cycle_mode:
            raise ValueError("cli_conflict:patch_root_mode_always_runs_all_mainids_per_patch")
        if manual_override:
            raise ValueError("cli_conflict:patch_root_mode_uses_override_root_not_manual_override")
        if validate_override and not review_cycle_mode:
            raise ValueError("cli_validate_override_requires_single_intersection_mode")
        if review_cycle_mode:
            result = run_t10_review_cycle_from_patch_root(
                patch_root=patch_root,
                patch_names=args.patch_name,
                override_root=override_root,
                output_root=output_dir,
                validate_override=validate_override,
            )
            return {
                "mode": "patch_root_review_cycle",
                **build_t10_patch_root_review_cycle_summary(result),
            }
        result = run_t10_multi_patch_manual_mode(
            patch_root=patch_root,
            patch_names=args.patch_name,
            manual_override_root=override_root,
            output_root=output_dir,
            include_catalog=emit_catalog,
            include_override_template=emit_override_template,
            include_review=emit_review,
        )
        return {
            "mode": "multi_patch_batch",
            **build_t10_multi_patch_summary(result),
        }
    if patch_dir:
        if override_root:
            raise ValueError("cli_conflict:patch_dir_mode_does_not_accept_override_root")
        if mainnodeids:
            raise ValueError("cli_conflict:patch_dir_mode_does_not_accept_mainnodeids")
        if review_cycle_mode:
            result = run_t10_review_cycle_from_patch_dir(
                patch_dir=patch_dir,
                mainid=mainid,
                all_mainids=bool(args.all_mainids),
                manual_override_source=manual_override,
                output_dir=output_dir,
                validate_override=validate_override,
                diff_against_dir=args.diff_against_dir,
            )
            return {
                **build_t10_review_cycle_summary(result),
                "has_diff": result.diff_payload is not None,
            }
        if args.all_mainids:
            if validate_override:
                raise ValueError("cli_validate_override_requires_single_intersection_mode")
            batch_result = run_t10_all_intersections_from_patch_dir(
                patch_dir=patch_dir,
                manual_override_source=manual_override,
                output_root=output_dir,
                include_catalog=emit_catalog,
                include_override_template=emit_override_template,
                include_review=emit_review,
            )
            return {
                "mode": "patch_dir_batch",
                **build_t10_patch_run_summary(batch_result),
            }
        result = run_t10_single_intersection_from_patch_dir(
            patch_dir=patch_dir,
            mainid=mainid,
            manual_override_source=manual_override,
        )
        return _single_result_payload(
            result,
            output_dir=output_dir,
            manual_override_source=manual_override,
            emit_review_bundle=emit_review_bundle,
            emit_catalog=emit_catalog,
            emit_override_template=emit_override_template,
            emit_review=emit_review,
            validate_override=validate_override,
        )

    if override_root:
        raise ValueError("cli_conflict:override_root_requires_patch_root")
    if review_cycle_mode:
        raise ValueError("cli_review_cycle_requires_patch_dir_or_patch_root")
    if mainnodeids:
        raise ValueError("cli_mainnodeids_requires_dataset_dir")
    if not node_file or not road_file:
        raise ValueError("cli_missing_required_inputs:provide_patch_dir_or_node_file_and_road_file")
    result = run_t10_single_intersection_from_geojson_files(
        node_geojson_path=node_file,
        road_geojson_path=road_file,
        manual_override_source=manual_override,
        mainid=mainid,
    )
    return _single_result_payload(
        result,
        output_dir=output_dir,
        manual_override_source=manual_override,
        emit_review_bundle=emit_review_bundle,
        emit_catalog=emit_catalog,
        emit_override_template=emit_override_template,
        emit_review=emit_review,
        validate_override=validate_override,
    )


def _single_result_summary(result: Any, *, output_dir: str | None) -> dict[str, Any]:
    return {
        "mode": "single_intersection",
        "intersection_id": result.bundle.intersection.intersection_id,
        "mainid": result.bundle.intersection.node_group_id,
        "approach_count": len(result.bundle.approaches),
        "movement_count": len(result.decisions),
        "output_dir": str(Path(output_dir)) if output_dir else None,
    }


def _single_result_payload(
    result: Any,
    *,
    output_dir: str | None,
    manual_override_source: str | None,
    emit_review_bundle: bool,
    emit_catalog: bool,
    emit_override_template: bool,
    emit_review: bool,
    validate_override: bool,
) -> dict[str, Any]:
    written_files: dict[str, str] = {}
    override_roundtrip = None
    if validate_override:
        if not manual_override_source:
            raise ValueError("cli_validate_override_requires_manual_override")
        override_roundtrip = roundtrip_manual_override_source(
            manual_override_source=manual_override_source,
            approach_catalog=build_approach_catalog(result),
        )
    if output_dir:
        if emit_review_bundle:
            written_files.update(
                write_t10_review_bundle(
                    result,
                    output_dir,
                    override_roundtrip_report=override_roundtrip if validate_override else None,
                )
            )
        else:
            written_files.update(
                write_t10_run_result(
                    result,
                    output_dir,
                    include_catalog=emit_catalog,
                    include_override_template=emit_override_template,
                    include_review=emit_review,
                )
            )
            if override_roundtrip is not None:
                written_files.update(write_override_roundtrip_report(override_roundtrip, output_dir))
    payload = _single_result_summary(result, output_dir=output_dir)
    payload["written_files"] = written_files
    if override_roundtrip is not None:
        payload["override_roundtrip"] = override_roundtrip
    return payload


def _coerce_mainid(raw: str | None) -> Any | None:
    return coerce_mainid_value(raw)


if __name__ == "__main__":
    raise SystemExit(main())
