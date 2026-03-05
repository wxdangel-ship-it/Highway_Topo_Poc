from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from .config import parse_set_overrides, resolve_runtime_config
from .runner import run_from_runtime


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="t04_rc_sw_anchor")
    p.add_argument("--mode", default=None, choices=["global_focus", "patch"])
    p.add_argument("--patch_dir", default=None)
    p.add_argument("--out_root", default=None)
    p.add_argument("--run_id", default=None)

    p.add_argument("--global_node_path", default=None)
    p.add_argument("--global_road_path", default=None)
    p.add_argument("--divstrip_path", default=None)
    p.add_argument("--drivezone_path", default=None)
    p.add_argument("--pointcloud_path", default=None)
    p.add_argument("--traj_glob", default=None)

    p.add_argument("--focus_node_ids", default=None)
    p.add_argument("--focus_node_ids_file", default=None)

    p.add_argument("--src_crs", default=None)
    p.add_argument("--dst_crs", default=None)
    p.add_argument("--node_src_crs", default=None)
    p.add_argument("--road_src_crs", default=None)
    p.add_argument("--divstrip_src_crs", default=None)
    p.add_argument("--drivezone_src_crs", default=None)
    p.add_argument("--traj_src_crs", default=None)
    p.add_argument("--pointcloud_crs", default=None)

    p.add_argument("--use_drivezone", default=None)
    p.add_argument("--drivezone_merge_mode", default=None)
    p.add_argument("--min_piece_len_m", default=None)
    p.add_argument("--divstrip_anchor_snap_enabled", default=None)
    p.add_argument("--divstrip_preferred_window_m", default=None)
    p.add_argument("--divstrip_ref_hard_window_m", default=None)
    p.add_argument("--divstrip_drivezone_max_offset_m", default=None)
    p.add_argument("--reverse_tip_max_m", default=None)
    p.add_argument("--multibranch_enable", default=None)
    p.add_argument("--multibranch_span_extra_m", default=None)
    p.add_argument("--multibranch_reverse_max_m", default=None)
    p.add_argument("--k16_step_m", default=None)
    p.add_argument("--output_cross_half_len_m", default=None)
    p.add_argument("--continuous_enable", default=None)
    p.add_argument("--continuous_dist_max_m", default=None)
    p.add_argument("--continuous_merge_max_gap_m", default=None)
    p.add_argument("--continuous_merge_geom_tol_m", default=None)
    p.add_argument("--next_intersection_degree_min", default=None)
    p.add_argument("--stop_intersection_require_connected", default=None)
    p.add_argument("--disable_geometric_stop_fallback", default=None)

    p.add_argument("--config_json", default=None)
    p.add_argument("--set", dest="set_items", action="append", default=[])
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config_json = Path(args.config_json) if args.config_json else None
        set_overrides = parse_set_overrides(args.set_items)
        cli_overrides = {
            "mode": args.mode,
            "patch_dir": args.patch_dir,
            "out_root": args.out_root,
            "run_id": args.run_id,
            "global_node_path": args.global_node_path,
            "global_road_path": args.global_road_path,
            "divstrip_path": args.divstrip_path,
            "drivezone_path": args.drivezone_path,
            "pointcloud_path": args.pointcloud_path,
            "traj_glob": args.traj_glob,
            "focus_node_ids": args.focus_node_ids,
            "focus_node_ids_file": args.focus_node_ids_file,
            "src_crs": args.src_crs,
            "dst_crs": args.dst_crs,
            "node_src_crs": args.node_src_crs,
            "road_src_crs": args.road_src_crs,
            "divstrip_src_crs": args.divstrip_src_crs,
            "drivezone_src_crs": args.drivezone_src_crs,
            "traj_src_crs": args.traj_src_crs,
            "pointcloud_crs": args.pointcloud_crs,
            "use_drivezone": args.use_drivezone,
            "drivezone_merge_mode": args.drivezone_merge_mode,
            "min_piece_len_m": args.min_piece_len_m,
            "divstrip_anchor_snap_enabled": args.divstrip_anchor_snap_enabled,
            "divstrip_preferred_window_m": args.divstrip_preferred_window_m,
            "divstrip_ref_hard_window_m": args.divstrip_ref_hard_window_m,
            "divstrip_drivezone_max_offset_m": args.divstrip_drivezone_max_offset_m,
            "reverse_tip_max_m": args.reverse_tip_max_m,
            "multibranch_enable": args.multibranch_enable,
            "multibranch_span_extra_m": args.multibranch_span_extra_m,
            "multibranch_reverse_max_m": args.multibranch_reverse_max_m,
            "k16_step_m": args.k16_step_m,
            "output_cross_half_len_m": args.output_cross_half_len_m,
            "continuous_enable": args.continuous_enable,
            "continuous_dist_max_m": args.continuous_dist_max_m,
            "continuous_merge_max_gap_m": args.continuous_merge_max_gap_m,
            "continuous_merge_geom_tol_m": args.continuous_merge_geom_tol_m,
            "next_intersection_degree_min": args.next_intersection_degree_min,
            "stop_intersection_require_connected": args.stop_intersection_require_connected,
            "disable_geometric_stop_fallback": args.disable_geometric_stop_fallback,
        }
        runtime = resolve_runtime_config(
            config_json=config_json,
            cli_overrides=cli_overrides,
            set_overrides=set_overrides,
        )

        result = run_from_runtime(runtime)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        "OK run_id={run_id} patch_id={patch_id} mode={mode} overall_pass={overall} out_dir={out_dir}".format(
            run_id=result.run_id,
            patch_id=result.patch_id,
            mode=result.mode,
            overall=str(bool(result.overall_pass)).lower(),
            out_dir=result.out_dir.as_posix(),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
