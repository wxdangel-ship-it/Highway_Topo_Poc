from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .io import make_run_id, resolve_repo_root
from .pipeline import DEFAULT_PARAMS, STAGES, run_full_pipeline, run_stage


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    repo_root = resolve_repo_root(Path.cwd())
    default_out_root = repo_root / "outputs" / "_work" / "t05_topology_between_rc_v2"
    parser = argparse.ArgumentParser(prog="t05_topology_between_rc_v2")
    parser.add_argument("--data_root", default="data/synth_local")
    parser.add_argument("--patch_id", required=True)
    parser.add_argument("--run_id", default="auto")
    parser.add_argument("--out_root", default=str(default_out_root))
    parser.add_argument("--stage", choices=[*STAGES, "full"], default="full")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--traj_xsec_hit_buffer_m", type=float, default=float(DEFAULT_PARAMS["TRAJ_XSEC_HIT_BUFFER_M"]))
    parser.add_argument("--segment_min_length_m", type=float, default=float(DEFAULT_PARAMS["SEGMENT_MIN_LENGTH_M"]))
    parser.add_argument("--segment_min_drivezone_ratio", type=float, default=float(DEFAULT_PARAMS["SEGMENT_MIN_DRIVEZONE_RATIO"]))
    parser.add_argument("--segment_max_other_xsec_crossings", type=int, default=int(DEFAULT_PARAMS["SEGMENT_MAX_OTHER_XSEC_CROSSINGS"]))
    parser.add_argument("--segment_cluster_offset_m", type=float, default=float(DEFAULT_PARAMS["SEGMENT_CLUSTER_OFFSET_M"]))
    parser.add_argument("--segment_cluster_line_dist_m", type=float, default=float(DEFAULT_PARAMS["SEGMENT_CLUSTER_LINE_DIST_M"]))
    parser.add_argument("--step2_strict_adjacent_pairing", type=int, default=int(DEFAULT_PARAMS["STEP2_STRICT_ADJACENT_PAIRING"]))
    parser.add_argument("--step2_allow_one_intermediate_xsec", type=int, default=int(DEFAULT_PARAMS["STEP2_ALLOW_ONE_INTERMEDIATE_XSEC"]))
    parser.add_argument("--step2_same_pair_topk", type=int, default=int(DEFAULT_PARAMS["STEP2_SAME_PAIR_TOPK"]))
    parser.add_argument("--step2_cross1_min_support", type=int, default=int(DEFAULT_PARAMS["STEP2_CROSS1_MIN_SUPPORT"]))
    parser.add_argument("--step2_cross1_min_drivezone_ratio", type=float, default=float(DEFAULT_PARAMS["STEP2_CROSS1_MIN_DRIVEZONE_RATIO"]))
    parser.add_argument("--step2_cross1_max_length_ratio", type=float, default=float(DEFAULT_PARAMS["STEP2_CROSS1_MAX_LENGTH_RATIO"]))
    parser.add_argument("--step2_cross1_require_no_cross0_better", type=int, default=int(DEFAULT_PARAMS["STEP2_CROSS1_REQUIRE_NO_CROSS0_BETTER"]))
    parser.add_argument("--prior_endpoint_anchor_m", type=float, default=float(DEFAULT_PARAMS["PRIOR_ENDPOINT_ANCHOR_M"]))
    parser.add_argument("--divstrip_buffer_m", type=float, default=float(DEFAULT_PARAMS["DIVSTRIP_BUFFER_M"]))
    parser.add_argument("--witness_half_length_m", type=float, default=float(DEFAULT_PARAMS["WITNESS_HALF_LENGTH_M"]))
    parser.add_argument("--witness_min_segment_length_m", type=float, default=float(DEFAULT_PARAMS["WITNESS_MIN_SEGMENT_LENGTH_M"]))
    parser.add_argument("--witness_center_tol_m", type=float, default=float(DEFAULT_PARAMS["WITNESS_CENTER_TOL_M"]))
    parser.add_argument("--witness_gap_min_m", type=float, default=float(DEFAULT_PARAMS["WITNESS_GAP_MIN_M"]))
    parser.add_argument("--witness_min_stability_score", type=float, default=float(DEFAULT_PARAMS["WITNESS_MIN_STABILITY_SCORE"]))
    parser.add_argument("--interval_min_len_m", type=float, default=float(DEFAULT_PARAMS["INTERVAL_MIN_LEN_M"]))
    parser.add_argument("--road_min_drivezone_ratio", type=float, default=float(DEFAULT_PARAMS["ROAD_MIN_DRIVEZONE_RATIO"]))
    return parser.parse_args(argv)


def _params_from_args(args: argparse.Namespace) -> dict[str, float | int]:
    return {
        "TRAJ_XSEC_HIT_BUFFER_M": float(args.traj_xsec_hit_buffer_m),
        "SEGMENT_MIN_LENGTH_M": float(args.segment_min_length_m),
        "SEGMENT_MIN_DRIVEZONE_RATIO": float(args.segment_min_drivezone_ratio),
        "SEGMENT_MAX_OTHER_XSEC_CROSSINGS": int(args.segment_max_other_xsec_crossings),
        "SEGMENT_CLUSTER_OFFSET_M": float(args.segment_cluster_offset_m),
        "SEGMENT_CLUSTER_LINE_DIST_M": float(args.segment_cluster_line_dist_m),
        "STEP2_STRICT_ADJACENT_PAIRING": int(args.step2_strict_adjacent_pairing),
        "STEP2_ALLOW_ONE_INTERMEDIATE_XSEC": int(args.step2_allow_one_intermediate_xsec),
        "STEP2_SAME_PAIR_TOPK": int(args.step2_same_pair_topk),
        "STEP2_CROSS1_MIN_SUPPORT": int(args.step2_cross1_min_support),
        "STEP2_CROSS1_MIN_DRIVEZONE_RATIO": float(args.step2_cross1_min_drivezone_ratio),
        "STEP2_CROSS1_MAX_LENGTH_RATIO": float(args.step2_cross1_max_length_ratio),
        "STEP2_CROSS1_REQUIRE_NO_CROSS0_BETTER": int(args.step2_cross1_require_no_cross0_better),
        "PRIOR_ENDPOINT_ANCHOR_M": float(args.prior_endpoint_anchor_m),
        "DIVSTRIP_BUFFER_M": float(args.divstrip_buffer_m),
        "WITNESS_HALF_LENGTH_M": float(args.witness_half_length_m),
        "WITNESS_MIN_SEGMENT_LENGTH_M": float(args.witness_min_segment_length_m),
        "WITNESS_CENTER_TOL_M": float(args.witness_center_tol_m),
        "WITNESS_GAP_MIN_M": float(args.witness_gap_min_m),
        "WITNESS_MIN_STABILITY_SCORE": float(args.witness_min_stability_score),
        "INTERVAL_MIN_LEN_M": float(args.interval_min_len_m),
        "ROAD_MIN_DRIVEZONE_RATIO": float(args.road_min_drivezone_ratio),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = resolve_repo_root(Path.cwd())
    run_id = str(args.run_id)
    if run_id == "auto":
        run_id = make_run_id("t05v2", repo_root=repo_root)
    params = _params_from_args(args)
    try:
        if str(args.stage) == "full":
            result = run_full_pipeline(
                data_root=args.data_root,
                patch_id=str(args.patch_id),
                run_id=run_id,
                out_root=args.out_root,
                force=bool(args.force),
                params=params,
            )
            if bool(args.debug):
                print(f"DEBUG out_root={args.out_root} run_id={run_id} patch_id={args.patch_id}")
            print(f"OK stage=full run_id={run_id} patch_id={args.patch_id} steps={len(result)}")
            return 0
        result = run_stage(
            stage=str(args.stage),
            data_root=args.data_root,
            patch_id=str(args.patch_id),
            run_id=run_id,
            out_root=args.out_root,
            force=bool(args.force),
            params=params,
        )
        if bool(args.debug):
            print(f"DEBUG out_root={args.out_root} run_id={run_id} patch_id={args.patch_id} stage={args.stage}")
        print(f"OK stage={args.stage} run_id={run_id} patch_id={args.patch_id} status={result['status']}")
        return 0
    except Exception as exc:
        text = " ".join(str(exc or type(exc).__name__).split())
        print(f"ERROR: {text}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
