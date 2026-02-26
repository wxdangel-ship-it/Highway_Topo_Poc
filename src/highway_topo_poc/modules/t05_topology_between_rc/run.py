from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from .pipeline import DEFAULT_PARAMS, run_patch


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="t05_topology_between_rc")
    p.add_argument("--data_root", default="data/synth_local")
    p.add_argument("--patch_id", default=None)
    p.add_argument("--run_id", default="auto")
    p.add_argument("--out_root", default="outputs/_work/t05_topology_between_rc")

    p.add_argument("--xsec_min_points", type=int, default=int(DEFAULT_PARAMS["XSEC_MIN_POINTS"]))
    p.add_argument("--min_support_traj", type=int, default=int(DEFAULT_PARAMS["MIN_SUPPORT_TRAJ"]))
    p.add_argument("--stitch_max_dist_m", type=float, default=float(DEFAULT_PARAMS["STITCH_MAX_DIST_M"]))
    p.add_argument("--stitch_max_angle_deg", type=float, default=float(DEFAULT_PARAMS["STITCH_MAX_ANGLE_DEG"]))
    p.add_argument("--stitch_topk", type=int, default=int(DEFAULT_PARAMS["STITCH_TOPK"]))
    p.add_argument("--neighbor_max_dist_m", type=float, default=float(DEFAULT_PARAMS["NEIGHBOR_MAX_DIST_M"]))
    p.add_argument("--point_class_fallback_any", type=int, choices=[0, 1], default=int(DEFAULT_PARAMS["POINT_CLASS_FALLBACK_ANY"]))

    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)

    params_override = {
        "XSEC_MIN_POINTS": int(args.xsec_min_points),
        "MIN_SUPPORT_TRAJ": int(args.min_support_traj),
        "STITCH_MAX_DIST_M": float(args.stitch_max_dist_m),
        "STITCH_MAX_ANGLE_DEG": float(args.stitch_max_angle_deg),
        "STITCH_TOPK": int(args.stitch_topk),
        "NEIGHBOR_MAX_DIST_M": float(args.neighbor_max_dist_m),
        "POINT_CLASS_FALLBACK_ANY": int(args.point_class_fallback_any),
    }

    try:
        result = run_patch(
            data_root=Path(args.data_root),
            patch_id=args.patch_id,
            run_id=str(args.run_id),
            out_root=Path(args.out_root),
            params_override=params_override,
        )
    except Exception as exc:
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
