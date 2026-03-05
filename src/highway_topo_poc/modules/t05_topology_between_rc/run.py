from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Iterable

from .io import make_run_id, resolve_repo_root
from .pipeline import DEFAULT_PARAMS, run_patch


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="t05_topology_between_rc")
    p.add_argument("--data_root", default="data/synth_local")
    p.add_argument("--patch_id", default=None)
    p.add_argument("--run_id", default="auto")
    p.add_argument("--out_root", default="outputs/_work/t05_topology_between_rc")

    p.add_argument("--traj_xsec_hit_buffer_m", type=float, default=float(DEFAULT_PARAMS["TRAJ_XSEC_HIT_BUFFER_M"]))
    p.add_argument("--xsec_min_points", type=int, default=int(DEFAULT_PARAMS["XSEC_MIN_POINTS"]))
    p.add_argument("--min_support_traj", type=int, default=int(DEFAULT_PARAMS["MIN_SUPPORT_TRAJ"]))
    p.add_argument("--trj_sample_step_m", type=float, default=float(DEFAULT_PARAMS["TRJ_SAMPLE_STEP_M"]))
    p.add_argument("--stitch_tail_m", type=float, default=float(DEFAULT_PARAMS["STITCH_TAIL_M"]))
    p.add_argument("--stitch_max_dist_m", type=float, default=float(DEFAULT_PARAMS["STITCH_MAX_DIST_M"]))
    p.add_argument("--stitch_max_angle_deg", type=float, default=float(DEFAULT_PARAMS["STITCH_MAX_ANGLE_DEG"]))
    p.add_argument("--stitch_forward_dot_min", type=float, default=float(DEFAULT_PARAMS["STITCH_FORWARD_DOT_MIN"]))
    p.add_argument("--stitch_min_advance_m", type=float, default=float(DEFAULT_PARAMS["STITCH_MIN_ADVANCE_M"]))
    p.add_argument("--stitch_topk", type=int, default=int(DEFAULT_PARAMS["STITCH_TOPK"]))
    p.add_argument("--neighbor_max_dist_m", type=float, default=float(DEFAULT_PARAMS["NEIGHBOR_MAX_DIST_M"]))
    p.add_argument(
        "--step1_unique_dst_early_stop",
        type=int,
        choices=[0, 1],
        default=int(DEFAULT_PARAMS.get("STEP1_UNIQUE_DST_EARLY_STOP", 1)),
    )
    p.add_argument(
        "--step1_unique_dst_dist_eps_m",
        type=float,
        default=float(DEFAULT_PARAMS.get("STEP1_UNIQUE_DST_DIST_EPS_M", 5.0)),
    )
    p.add_argument(
        "--step1_node_vote_min_ratio",
        type=float,
        default=float(DEFAULT_PARAMS.get("STEP1_NODE_VOTE_MIN_RATIO", 1.0)),
    )
    p.add_argument(
        "--pass2_traj_xsec_hit_buffer_m",
        type=float,
        default=float(DEFAULT_PARAMS["PASS2_TRAJ_XSEC_HIT_BUFFER_M"]),
    )
    p.add_argument(
        "--pass2_stitch_max_dist_m",
        type=float,
        default=float(DEFAULT_PARAMS["PASS2_STITCH_MAX_DIST_M"]),
    )
    p.add_argument(
        "--pass2_stitch_forward_dot_min",
        type=float,
        default=float(DEFAULT_PARAMS["PASS2_STITCH_FORWARD_DOT_MIN"]),
    )
    p.add_argument(
        "--pass2_neighbor_max_dist_m",
        type=float,
        default=float(DEFAULT_PARAMS["PASS2_NEIGHBOR_MAX_DIST_M"]),
    )
    p.add_argument("--xsec_across_half_window_m", type=float, default=float(DEFAULT_PARAMS["XSEC_ACROSS_HALF_WINDOW_M"]))
    p.add_argument("--xsec_core_band_m", type=float, default=float(DEFAULT_PARAMS["XSEC_CORE_BAND_M"]))
    p.add_argument("--xsec_shift_step_m", type=float, default=float(DEFAULT_PARAMS["XSEC_SHIFT_STEP_M"]))
    p.add_argument(
        "--xsec_fallback_short_half_len_m",
        type=float,
        default=float(DEFAULT_PARAMS["XSEC_FALLBACK_SHORT_HALF_LEN_M"]),
    )
    p.add_argument(
        "--xsec_barrier_min_ng_count",
        type=int,
        default=int(DEFAULT_PARAMS["XSEC_BARRIER_MIN_NG_COUNT"]),
    )
    p.add_argument(
        "--xsec_barrier_min_len_m",
        type=float,
        default=float(DEFAULT_PARAMS["XSEC_BARRIER_MIN_LEN_M"]),
    )
    p.add_argument(
        "--xsec_barrier_along_len_m",
        type=float,
        default=float(DEFAULT_PARAMS["XSEC_BARRIER_ALONG_LEN_M"]),
    )
    p.add_argument(
        "--xsec_barrier_along_width_m",
        type=float,
        default=float(DEFAULT_PARAMS["XSEC_BARRIER_ALONG_WIDTH_M"]),
    )
    p.add_argument(
        "--xsec_barrier_bin_step_m",
        type=float,
        default=float(DEFAULT_PARAMS["XSEC_BARRIER_BIN_STEP_M"]),
    )
    p.add_argument(
        "--xsec_barrier_occ_ratio_min",
        type=float,
        default=float(DEFAULT_PARAMS["XSEC_BARRIER_OCC_RATIO_MIN"]),
    )
    p.add_argument("--xsec_endcap_window_m", type=float, default=float(DEFAULT_PARAMS["XSEC_ENDCAP_WINDOW_M"]))
    p.add_argument("--xsec_caseb_pre_m", type=float, default=float(DEFAULT_PARAMS["XSEC_CASEB_PRE_M"]))
    p.add_argument(
        "--step1_multi_corridor_dist_m",
        type=float,
        default=float(DEFAULT_PARAMS["STEP1_MULTI_CORRIDOR_DIST_M"]),
    )
    p.add_argument(
        "--step1_multi_corridor_min_ratio",
        type=float,
        default=float(DEFAULT_PARAMS["STEP1_MULTI_CORRIDOR_MIN_RATIO"]),
    )
    p.add_argument(
        "--step1_multi_corridor_hard",
        type=int,
        default=int(DEFAULT_PARAMS["STEP1_MULTI_CORRIDOR_HARD"]),
    )
    p.add_argument("--step1_gore_near_m", type=float, default=float(DEFAULT_PARAMS["STEP1_GORE_NEAR_M"]))
    p.add_argument(
        "--step1_traj_in_drivezone_min",
        type=float,
        default=float(DEFAULT_PARAMS["STEP1_TRAJ_IN_DRIVEZONE_MIN"]),
    )
    p.add_argument(
        "--step1_traj_in_drivezone_fallback_min",
        type=float,
        default=float(DEFAULT_PARAMS["STEP1_TRAJ_IN_DRIVEZONE_FALLBACK_MIN"]),
    )
    p.add_argument("--corridor_half_width_m", type=float, default=float(DEFAULT_PARAMS["CORRIDOR_HALF_WIDTH_M"]))
    p.add_argument("--offset_smooth_win_m_1", type=float, default=float(DEFAULT_PARAMS["OFFSET_SMOOTH_WIN_M_1"]))
    p.add_argument("--offset_smooth_win_m_2", type=float, default=float(DEFAULT_PARAMS["OFFSET_SMOOTH_WIN_M_2"]))
    p.add_argument("--max_offset_delta_per_step_m", type=float, default=float(DEFAULT_PARAMS["MAX_OFFSET_DELTA_PER_STEP_M"]))
    p.add_argument("--simplify_tol_m", type=float, default=float(DEFAULT_PARAMS["SIMPLIFY_TOL_M"]))
    p.add_argument("--d_min", type=float, default=float(DEFAULT_PARAMS["D_MIN"]))
    p.add_argument("--d_max", type=float, default=float(DEFAULT_PARAMS["D_MAX"]))
    p.add_argument("--near_len", type=float, default=float(DEFAULT_PARAMS["NEAR_LEN"]))
    p.add_argument("--base_from", type=float, default=float(DEFAULT_PARAMS["BASE_FROM"]))
    p.add_argument("--base_to", type=float, default=float(DEFAULT_PARAMS["BASE_TO"]))
    p.add_argument("--l_stable", type=float, default=float(DEFAULT_PARAMS["L_STABLE"]))
    p.add_argument("--ratio_tol", type=float, default=float(DEFAULT_PARAMS["RATIO_TOL"]))
    p.add_argument("--w_tol", type=float, default=float(DEFAULT_PARAMS["W_TOL"]))
    p.add_argument("--r_gore", type=float, default=float(DEFAULT_PARAMS["R_GORE"]))
    p.add_argument("--gore_buffer_m", type=float, default=float(DEFAULT_PARAMS["GORE_BUFFER_M"]))
    p.add_argument("--transition_m", type=float, default=float(DEFAULT_PARAMS["TRANSITION_M"]))
    p.add_argument("--stable_fallback_m", type=float, default=float(DEFAULT_PARAMS["STABLE_FALLBACK_M"]))
    p.add_argument("--bridge_max_seg_m", type=float, default=float(DEFAULT_PARAMS["BRIDGE_MAX_SEG_M"]))
    p.add_argument("--lb_snap_m", type=float, default=float(DEFAULT_PARAMS["LB_SNAP_M"]))
    p.add_argument("--lb_start_end_topk", type=int, default=int(DEFAULT_PARAMS["LB_START_END_TOPK"]))
    p.add_argument("--lambda_outside", type=float, default=float(DEFAULT_PARAMS["LAMBDA_OUTSIDE"]))
    p.add_argument(
        "--outside_edge_ratio_max",
        type=float,
        default=float(DEFAULT_PARAMS["OUTSIDE_EDGE_RATIO_MAX"]),
    )
    p.add_argument(
        "--surf_node_buffer_m",
        type=float,
        default=float(DEFAULT_PARAMS["SURF_NODE_BUFFER_M"]),
    )
    p.add_argument("--trend_fit_win_m", type=float, default=float(DEFAULT_PARAMS["TREND_FIT_WIN_M"]))
    p.add_argument("--surf_slice_step_m", type=float, default=float(DEFAULT_PARAMS["SURF_SLICE_STEP_M"]))
    p.add_argument("--surf_slice_half_win_m", type=float, default=float(DEFAULT_PARAMS["SURF_SLICE_HALF_WIN_M"]))
    p.add_argument(
        "--axis_max_project_dist_m",
        type=float,
        default=float(DEFAULT_PARAMS["AXIS_MAX_PROJECT_DIST_M"]),
    )
    p.add_argument("--endcap_m", type=float, default=float(DEFAULT_PARAMS["ENDCAP_M"]))
    p.add_argument(
        "--endcap_min_valid_ratio",
        type=float,
        default=float(DEFAULT_PARAMS["ENDCAP_MIN_VALID_RATIO"]),
    )
    p.add_argument(
        "--endcap_width_abs_cap_m",
        type=float,
        default=float(DEFAULT_PARAMS["ENDCAP_WIDTH_ABS_CAP_M"]),
    )
    p.add_argument(
        "--endcap_width_rel_cap",
        type=float,
        default=float(DEFAULT_PARAMS["ENDCAP_WIDTH_REL_CAP"]),
    )
    p.add_argument(
        "--surf_slice_half_win_levels_m",
        type=str,
        default=",".join(str(v) for v in DEFAULT_PARAMS.get("SURF_SLICE_HALF_WIN_LEVELS_M", [2.0, 5.0, 10.0])),
    )
    p.add_argument("--surf_quant_low", type=float, default=float(DEFAULT_PARAMS["SURF_QUANT_LOW"]))
    p.add_argument("--surf_quant_high", type=float, default=float(DEFAULT_PARAMS["SURF_QUANT_HIGH"]))
    p.add_argument("--surf_buf_m", type=float, default=float(DEFAULT_PARAMS["SURF_BUF_M"]))
    p.add_argument("--in_ratio_min", type=float, default=float(DEFAULT_PARAMS["IN_RATIO_MIN"]))
    p.add_argument(
        "--xsec_anchor_window_m",
        type=float,
        default=float(DEFAULT_PARAMS["XSEC_ANCHOR_WINDOW_M"]),
    )
    p.add_argument(
        "--xsec_endpoint_max_dist_m",
        type=float,
        default=float(DEFAULT_PARAMS["XSEC_ENDPOINT_MAX_DIST_M"]),
    )
    p.add_argument(
        "--traj_surf_min_points_per_slice",
        type=int,
        default=int(DEFAULT_PARAMS["TRAJ_SURF_MIN_POINTS_PER_SLICE"]),
    )
    p.add_argument(
        "--traj_surf_min_slice_valid_ratio",
        type=float,
        default=float(DEFAULT_PARAMS["TRAJ_SURF_MIN_SLICE_VALID_RATIO"]),
    )
    p.add_argument(
        "--traj_surf_min_covered_len_ratio",
        type=float,
        default=float(DEFAULT_PARAMS["TRAJ_SURF_MIN_COVERED_LEN_RATIO"]),
    )
    p.add_argument(
        "--traj_surf_enforce_min_covered_len_ratio",
        type=float,
        default=float(DEFAULT_PARAMS["TRAJ_SURF_ENFORCE_MIN_COVERED_LEN_RATIO"]),
    )
    p.add_argument(
        "--traj_surf_min_unique_traj",
        type=int,
        default=int(DEFAULT_PARAMS["TRAJ_SURF_MIN_UNIQUE_TRAJ"]),
    )
    p.add_argument("--pointcloud_enable", type=int, choices=[0, 1], default=int(DEFAULT_PARAMS["POINTCLOUD_ENABLE"]))
    p.add_argument("--point_class_fallback_any", type=int, choices=[0, 1], default=int(DEFAULT_PARAMS["POINT_CLASS_FALLBACK_ANY"]))
    p.add_argument("--drivezone_sample_step_m", type=float, default=float(DEFAULT_PARAMS["DRIVEZONE_SAMPLE_STEP_M"]))
    p.add_argument("--cache_enabled", type=int, choices=[0, 1], default=int(DEFAULT_PARAMS["CACHE_ENABLED"]))
    p.add_argument("--debug_dump", type=int, choices=[0, 1], default=int(DEFAULT_PARAMS["DEBUG_DUMP"]))
    p.add_argument(
        "--step0_mode",
        type=str,
        choices=["lite", "full", "off"],
        default=str(DEFAULT_PARAMS.get("STEP0_MODE", "lite")),
    )
    p.add_argument(
        "--step0_lite_min_in_drivezone_ratio",
        type=float,
        default=float(DEFAULT_PARAMS.get("STEP0_LITE_MIN_IN_DRIVEZONE_RATIO", 0.90)),
    )
    p.add_argument(
        "--step0_lite_max_in_divstrip_ratio",
        type=float,
        default=float(DEFAULT_PARAMS.get("STEP0_LITE_MAX_IN_DIVSTRIP_RATIO", 0.01)),
    )
    p.add_argument(
        "--step0_lite_min_len_m",
        type=float,
        default=float(DEFAULT_PARAMS.get("STEP0_LITE_MIN_LEN_M", 5.0)),
    )
    p.add_argument(
        "--step0_lite_allow_passthrough_when_divstrip_missing",
        type=int,
        choices=[0, 1],
        default=int(DEFAULT_PARAMS.get("STEP0_LITE_ALLOW_PASSTHROUGH_WHEN_DIVSTRIP_MISSING", 1)),
    )
    p.add_argument(
        "--step0_stats_enable",
        type=int,
        choices=[0, 1],
        default=int(DEFAULT_PARAMS.get("STEP0_STATS_ENABLE", 1)),
    )
    p.add_argument(
        "--debug_layer_max_items",
        type=int,
        default=int(DEFAULT_PARAMS.get("DEBUG_LAYER_MAX_ITEMS", 2000)),
    )

    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = resolve_repo_root(Path.cwd())
    run_id_val = make_run_id("t05_topology_between_rc", repo_root=repo_root) if str(args.run_id) == "auto" else str(args.run_id)
    out_root = Path(args.out_root)
    if not out_root.is_absolute():
        out_root = (repo_root / out_root).resolve()
    run_dir = out_root / run_id_val
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)

    level_tokens = [tok.strip() for tok in str(args.surf_slice_half_win_levels_m).split(",")]
    level_values: list[float] = []
    for tok in level_tokens:
        if not tok:
            continue
        try:
            v = float(tok)
        except Exception:
            continue
        if v > 0:
            level_values.append(float(v))
    if not level_values:
        level_values = [float(args.surf_slice_half_win_m), 5.0, 10.0]

    params_override = {
        "TRAJ_XSEC_HIT_BUFFER_M": float(args.traj_xsec_hit_buffer_m),
        "XSEC_MIN_POINTS": int(args.xsec_min_points),
        "MIN_SUPPORT_TRAJ": int(args.min_support_traj),
        "TRJ_SAMPLE_STEP_M": float(args.trj_sample_step_m),
        "STITCH_TAIL_M": float(args.stitch_tail_m),
        "STITCH_MAX_DIST_M": float(args.stitch_max_dist_m),
        "STITCH_MAX_ANGLE_DEG": float(args.stitch_max_angle_deg),
        "STITCH_FORWARD_DOT_MIN": float(args.stitch_forward_dot_min),
        "STITCH_MIN_ADVANCE_M": float(args.stitch_min_advance_m),
        "STITCH_TOPK": int(args.stitch_topk),
        "NEIGHBOR_MAX_DIST_M": float(args.neighbor_max_dist_m),
        "STEP1_UNIQUE_DST_EARLY_STOP": int(args.step1_unique_dst_early_stop),
        "STEP1_UNIQUE_DST_DIST_EPS_M": float(args.step1_unique_dst_dist_eps_m),
        "STEP1_NODE_VOTE_MIN_RATIO": float(args.step1_node_vote_min_ratio),
        "PASS2_TRAJ_XSEC_HIT_BUFFER_M": float(args.pass2_traj_xsec_hit_buffer_m),
        "PASS2_STITCH_MAX_DIST_M": float(args.pass2_stitch_max_dist_m),
        "PASS2_STITCH_FORWARD_DOT_MIN": float(args.pass2_stitch_forward_dot_min),
        "PASS2_NEIGHBOR_MAX_DIST_M": float(args.pass2_neighbor_max_dist_m),
        "XSEC_ACROSS_HALF_WINDOW_M": float(args.xsec_across_half_window_m),
        "XSEC_CORE_BAND_M": float(args.xsec_core_band_m),
        "XSEC_SHIFT_STEP_M": float(args.xsec_shift_step_m),
        "XSEC_FALLBACK_SHORT_HALF_LEN_M": float(args.xsec_fallback_short_half_len_m),
        "XSEC_BARRIER_MIN_NG_COUNT": int(args.xsec_barrier_min_ng_count),
        "XSEC_BARRIER_MIN_LEN_M": float(args.xsec_barrier_min_len_m),
        "XSEC_BARRIER_ALONG_LEN_M": float(args.xsec_barrier_along_len_m),
        "XSEC_BARRIER_ALONG_WIDTH_M": float(args.xsec_barrier_along_width_m),
        "XSEC_BARRIER_BIN_STEP_M": float(args.xsec_barrier_bin_step_m),
        "XSEC_BARRIER_OCC_RATIO_MIN": float(args.xsec_barrier_occ_ratio_min),
        "XSEC_ENDCAP_WINDOW_M": float(args.xsec_endcap_window_m),
        "XSEC_CASEB_PRE_M": float(args.xsec_caseb_pre_m),
        "STEP1_MULTI_CORRIDOR_DIST_M": float(args.step1_multi_corridor_dist_m),
        "STEP1_MULTI_CORRIDOR_MIN_RATIO": float(args.step1_multi_corridor_min_ratio),
        "STEP1_MULTI_CORRIDOR_HARD": int(args.step1_multi_corridor_hard),
        "STEP1_GORE_NEAR_M": float(args.step1_gore_near_m),
        "STEP1_TRAJ_IN_DRIVEZONE_MIN": float(args.step1_traj_in_drivezone_min),
        "STEP1_TRAJ_IN_DRIVEZONE_FALLBACK_MIN": float(args.step1_traj_in_drivezone_fallback_min),
        "CORRIDOR_HALF_WIDTH_M": float(args.corridor_half_width_m),
        "OFFSET_SMOOTH_WIN_M_1": float(args.offset_smooth_win_m_1),
        "OFFSET_SMOOTH_WIN_M_2": float(args.offset_smooth_win_m_2),
        "MAX_OFFSET_DELTA_PER_STEP_M": float(args.max_offset_delta_per_step_m),
        "SIMPLIFY_TOL_M": float(args.simplify_tol_m),
        "D_MIN": float(args.d_min),
        "D_MAX": float(args.d_max),
        "NEAR_LEN": float(args.near_len),
        "BASE_FROM": float(args.base_from),
        "BASE_TO": float(args.base_to),
        "L_STABLE": float(args.l_stable),
        "RATIO_TOL": float(args.ratio_tol),
        "W_TOL": float(args.w_tol),
        "R_GORE": float(args.r_gore),
        "GORE_BUFFER_M": float(args.gore_buffer_m),
        "TRANSITION_M": float(args.transition_m),
        "STABLE_FALLBACK_M": float(args.stable_fallback_m),
        "BRIDGE_MAX_SEG_M": float(args.bridge_max_seg_m),
        "LB_SNAP_M": float(args.lb_snap_m),
        "LB_START_END_TOPK": int(args.lb_start_end_topk),
        "LAMBDA_OUTSIDE": float(args.lambda_outside),
        "OUTSIDE_EDGE_RATIO_MAX": float(args.outside_edge_ratio_max),
        "SURF_NODE_BUFFER_M": float(args.surf_node_buffer_m),
        "TREND_FIT_WIN_M": float(args.trend_fit_win_m),
        "SURF_SLICE_STEP_M": float(args.surf_slice_step_m),
        "SURF_SLICE_HALF_WIN_M": float(args.surf_slice_half_win_m),
        "AXIS_MAX_PROJECT_DIST_M": float(args.axis_max_project_dist_m),
        "ENDCAP_M": float(args.endcap_m),
        "ENDCAP_MIN_VALID_RATIO": float(args.endcap_min_valid_ratio),
        "ENDCAP_WIDTH_ABS_CAP_M": float(args.endcap_width_abs_cap_m),
        "ENDCAP_WIDTH_REL_CAP": float(args.endcap_width_rel_cap),
        "SURF_SLICE_HALF_WIN_LEVELS_M": [float(v) for v in level_values],
        "SURF_QUANT_LOW": float(args.surf_quant_low),
        "SURF_QUANT_HIGH": float(args.surf_quant_high),
        "SURF_BUF_M": float(args.surf_buf_m),
        "IN_RATIO_MIN": float(args.in_ratio_min),
        "XSEC_ANCHOR_WINDOW_M": float(args.xsec_anchor_window_m),
        "XSEC_ENDPOINT_MAX_DIST_M": float(args.xsec_endpoint_max_dist_m),
        "TRAJ_SURF_MIN_POINTS_PER_SLICE": int(args.traj_surf_min_points_per_slice),
        "TRAJ_SURF_MIN_SLICE_VALID_RATIO": float(args.traj_surf_min_slice_valid_ratio),
        "TRAJ_SURF_MIN_COVERED_LEN_RATIO": float(args.traj_surf_min_covered_len_ratio),
        "TRAJ_SURF_ENFORCE_MIN_COVERED_LEN_RATIO": float(args.traj_surf_enforce_min_covered_len_ratio),
        "TRAJ_SURF_MIN_UNIQUE_TRAJ": int(args.traj_surf_min_unique_traj),
        "POINTCLOUD_ENABLE": int(args.pointcloud_enable),
        "POINT_CLASS_FALLBACK_ANY": int(args.point_class_fallback_any),
        "DRIVEZONE_SAMPLE_STEP_M": float(args.drivezone_sample_step_m),
        "CACHE_ENABLED": int(args.cache_enabled),
        "DEBUG_DUMP": int(args.debug_dump),
        "STEP0_MODE": str(args.step0_mode),
        "STEP0_LITE_MIN_IN_DRIVEZONE_RATIO": float(args.step0_lite_min_in_drivezone_ratio),
        "STEP0_LITE_MAX_IN_DIVSTRIP_RATIO": float(args.step0_lite_max_in_divstrip_ratio),
        "STEP0_LITE_MIN_LEN_M": float(args.step0_lite_min_len_m),
        "STEP0_LITE_ALLOW_PASSTHROUGH_WHEN_DIVSTRIP_MISSING": int(
            args.step0_lite_allow_passthrough_when_divstrip_missing
        ),
        "STEP0_STATS_ENABLE": int(args.step0_stats_enable),
        "DEBUG_LAYER_MAX_ITEMS": int(args.debug_layer_max_items),
    }
    levels = list(DEFAULT_PARAMS.get("STITCH_MAX_DIST_LEVELS_M", [float(args.stitch_max_dist_m)]))
    if levels:
        levels[0] = float(args.stitch_max_dist_m)
    else:
        levels = [float(args.stitch_max_dist_m)]
    params_override["STITCH_MAX_DIST_LEVELS_M"] = [float(v) for v in levels]
    (run_dir / "params.json").write_text(
        json.dumps(
            {
                "data_root": str(args.data_root),
                "patch_id": args.patch_id,
                "run_id": run_id_val,
                "out_root": out_root.as_posix(),
                "params_override": params_override,
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        result = run_patch(
            data_root=Path(args.data_root),
            patch_id=args.patch_id,
            run_id=run_id_val,
            out_root=out_root,
            params_override=params_override,
        )
    except Exception as exc:
        patch_label = str(args.patch_id) if args.patch_id else "unknown_patch"
        fail_patch_dir = run_dir / "patches" / patch_label
        fail_patch_dir.mkdir(parents=True, exist_ok=True)
        tb_lines = traceback.format_exc().splitlines()
        top_n = tb_lines[:30]
        summary_lines = [
            "=== t05_topology_between_rc summary ===",
            f"run_id: {run_id_val}",
            f"patch_id: {patch_label}",
            "overall_pass: false",
            "",
            "error:",
            f"- type={type(exc).__name__}",
            f"- message={exc}",
            "- traceback_top30:",
            *[f"  {line}" for line in top_n],
        ]
        (fail_patch_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
        (fail_patch_dir / "gate.json").write_text(
            json.dumps(
                {
                    "overall_pass": False,
                    "hard_breakpoints": [],
                    "soft_breakpoints": [],
                    "version": "t05_gate_v1",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "traceback_top30": top_n,
                },
                ensure_ascii=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        "OK run_id={run_id} patch_id={patch_id} roads={roads} overall_pass={overall} out_dir={out}".format(
            run_id=result.run_id,
            patch_id=result.patch_id,
            roads=result.road_count,
            overall=str(result.overall_pass).lower(),
            out=result.output_dir.as_posix(),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
