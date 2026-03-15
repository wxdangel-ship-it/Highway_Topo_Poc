from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TARGET_PAIRS = [
    "55353246:37687913",
    "55353307:608638238",
    "5389884430552920:2703260460721685999",
    "791873:791871",
    "21779764:785642",
]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _find_pair(rows: list[dict[str, Any]], pair_id: str) -> dict[str, Any]:
    for row in rows:
        if str(row.get("pair")) == pair_id or str(row.get("pair_id")) == pair_id:
            return row
    return {}


def _b(value: Any) -> str:
    return str(bool(value)).lower()


def _fmt(value: Any) -> str:
    if isinstance(value, dict):
        return ",".join(f"{k}:{_fmt(v)}" for k, v in sorted(value.items(), key=lambda item: str(item[0]))) or "-"
    if isinstance(value, list):
        return "[" + ",".join(_fmt(item) for item in value) + "]"
    if value is None or value == "":
        return "-"
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="t05_v2_phase4_extract")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--bundle-out", required=True)
    parser.add_argument("--complex-patch-id", default="5417632623039346")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    bundle = Path(args.bundle_out)
    complex_patch = str(args.complex_patch_id)
    patch_root = run_root / "patches" / complex_patch

    accept = _read_json(bundle / "simple_patch_acceptance.json")
    for row in accept.get("patches", []):
        print(
            f"ACCEPT patch={row.get('patch_id')} "
            f"pass={_b(row.get('acceptance_pass', False))} "
            f"legal_arc_total={row.get('legal_arc_total')} "
            f"built={row.get('legal_arc_built')} "
            f"rate={row.get('legal_arc_build_rate')}"
        )

    pair_rows = _read_json(bundle / "pair_decisions.json").get("pairs", [])
    for pair_id in TARGET_PAIRS:
        row = _find_pair(pair_rows, pair_id)
        print(
            f"PAIR pair={pair_id} "
            f"built={_b(row.get('built_final_road', False))} "
            f"direct={_b(row.get('topology_arc_is_direct_legal', False))} "
            f"unique={_b(row.get('topology_arc_is_unique', False))} "
            f"multi_arc={_b(row.get('production_multi_arc_allowed', False))} "
            f"arc_finalize={_b(row.get('same_pair_arc_finalize_allowed', False))} "
            f"mode={row.get('multi_arc_evidence_mode','-')} "
            f"reject={row.get('reject_stage','-')}/{row.get('reject_reason','-')} "
            f"unbuilt={row.get('unbuilt_stage','-')}/{row.get('unbuilt_reason','-')}"
        )

    geom = _read_json(patch_root / "geometry_refine_review.json")
    summary = geom.get("summary", {})
    print(
        f"GEOM reviewed={summary.get('reviewed_count','-')} "
        f"eligible={summary.get('eligible_count','-')} "
        f"applied={summary.get('applied_count','-')} "
        f"smoothed={summary.get('smoothed_count','-')} "
        f"lane_boundary_used={summary.get('lane_boundary_used_count','-')} "
        f"support_trend_used={summary.get('support_trend_used_count','-')}"
    )
    for pair_id in ["55353246:37687913", "55353307:608638238", "21779764:785642"]:
        row = _find_pair(geom.get("rows", []), pair_id)
        if row:
            print(
                f"GEOM_PAIR pair={pair_id} "
                f"eligible={_b(row.get('eligible', False))} "
                f"applied={_b(row.get('applied', False))} "
                f"smoothed={_b(row.get('smoothed', False))} "
                f"core={row.get('core_skeleton_source','-')} "
                f"entry={row.get('entry_anchor_source','-')} "
                f"exit={row.get('exit_anchor_source','-')}"
            )

    witnesses = _read_json(patch_root / "step3" / "witnesses.json").get("full_legal_arc_registry", [])
    for pair_id in ["55353246:37687913", "55353307:608638238", "5389884430552920:2703260460721685999"]:
        row = _find_pair(witnesses, pair_id)
        print(
            f"SUPPORT pair={pair_id} "
            f"type={row.get('traj_support_type','-')} "
            f"gen={row.get('support_generation_mode','-')}/{row.get('support_generation_reason','-')} "
            f"selected_traj={row.get('selected_support_traj_id','-')} "
            f"selected_seg={row.get('selected_support_segment_traj_id','-')} "
            f"full_crossing={_b(row.get('support_full_xsec_crossing', False))} "
            f"cluster_dominant={_b(row.get('support_cluster_is_dominant', False))} "
            f"cluster_support_count={row.get('support_cluster_support_count','-')} "
            f"selected_trusted={_b(row.get('selected_support_interval_reference_trusted', False))} "
            f"stitched_trusted={_b(row.get('stitched_support_interval_reference_trusted', False))} "
            f"interval_ref={row.get('support_interval_reference_source','-')} "
            f"interval_reason={row.get('support_interval_reference_reason','-')}"
        )

    step5 = _read_json(bundle / "complex_patch_step5_recovery_review.json").get("rows", [])
    for pair_id in ["55353307:608638238", "5389884430552920:2703260460721685999"]:
        row = _find_pair(step5, pair_id)
        print(
            f"STEP5 pair={pair_id} "
            f"built={_b(row.get('built_final_road', False))} "
            f"stage={row.get('unbuilt_stage','-')} "
            f"reason={row.get('unbuilt_reason','-')} "
            f"shape_ref_mode={row.get('shape_ref_mode','-')} "
            f"road_drivezone={row.get('road_drivezone_overlap_ratio','-')} "
            f"road_divstrip={row.get('road_divstrip_overlap_ratio','-')}"
        )

    same_pair = _read_json(bundle / "same_pair_provisional_allow_review.json")
    print(
        f"SAME_PAIR_REVIEW row_count={same_pair.get('row_count')} "
        f"provisional_allow_count={same_pair.get('provisional_allow_count')} "
        f"finalized_allow_count={same_pair.get('finalized_allow_count')} "
        f"arc_level_finalize_count={same_pair.get('arc_level_finalize_count')}"
    )
    for pair_id in ["21779764:785642", "791873:791871"]:
        row = _find_pair(same_pair.get("rows", []), pair_id)
        print(
            f"SAME_PAIR pair={pair_id} "
            f"candidate={_b(row.get('same_pair_multi_arc_candidate', False))} "
            f"provisional={_b(row.get('same_pair_provisional_allowed', False))} "
            f"arc_finalize={_b(row.get('same_pair_arc_finalize_allowed', False))} "
            f"production_multi_arc={_b(row.get('production_multi_arc_allowed', False))} "
            f"evidence={row.get('multi_arc_evidence_mode','-')} "
            f"entered={_b(row.get('entered_main_flow', False))} "
            f"built={_b(row.get('built', False))} "
            f"stage={row.get('unbuilt_stage','-')} "
            f"reason={row.get('unbuilt_reason','-')}"
        )

    multi = _read_json(bundle / "multi_arc_review.json")
    print(
        f"MULTI_REVIEW row_count={multi.get('row_count')} "
        f"dual_output_candidate_count={multi.get('dual_output_candidate_count')}"
    )
    for pair_id in ["21779764:785642", "791873:791871"]:
        row = _find_pair(multi.get("rows", []), pair_id)
        print(
            f"MULTI pair={pair_id} "
            f"allow_multi_output={_b(row.get('allow_multi_output', False))} "
            f"entered={_b(row.get('entered_main_flow', False))} "
            f"built={_b(row.get('built', False))} "
            f"modes={_fmt(row.get('evidence_modes', {}))} "
            f"arc_finalize={_fmt(row.get('same_pair_arc_finalize_allowed', {}))} "
            f"stage={row.get('unbuilt_stage','-')} "
            f"reason={row.get('unbuilt_reason','-')}"
        )

    audit = _read_json(bundle / "arc_legality_audit.json").get("summary", {})
    print(
        f"AUDIT built_arc_count={audit.get('built_arc_count')} "
        f"bad_built_arc_count={audit.get('bad_built_arc_count')} "
        f"built_all_direct_unique={_b(audit.get('built_all_direct_unique', False))} "
        f"audit_summary_inconsistent={_b(audit.get('audit_summary_inconsistent', False))} "
        f"synthetic_in_production={_b(audit.get('synthetic_arc_in_production', False))}"
    )

    strict = _read_json(bundle / "strict_vs_visual_gap_summary.json").get("strict_coverage", {})
    print(
        f"STRICT built={strict.get('built')} "
        f"total={strict.get('total')} "
        f"rate={strict.get('rate')}"
    )

    runtime = _read_json(bundle / "runtime_breakdown.json")
    complex_runtime = next((x for x in runtime.get("patches", []) if str(x.get("patch_id")) == complex_patch), {})
    print(f"RUNTIME patch={complex_patch} total_ms={complex_runtime.get('total_runtime_ms','-')}")

    print(f"RUN_ROOT={run_root}")
    print(f"BUNDLE_OUT={bundle}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
