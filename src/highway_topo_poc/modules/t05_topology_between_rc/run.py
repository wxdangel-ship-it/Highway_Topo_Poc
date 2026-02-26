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
    repo_root = resolve_repo_root(Path.cwd())
    run_id_val = make_run_id("t05_topology_between_rc", repo_root=repo_root) if str(args.run_id) == "auto" else str(args.run_id)
    out_root = Path(args.out_root)
    if not out_root.is_absolute():
        out_root = (repo_root / out_root).resolve()
    run_dir = out_root / run_id_val
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)

    params_override = {
        "XSEC_MIN_POINTS": int(args.xsec_min_points),
        "MIN_SUPPORT_TRAJ": int(args.min_support_traj),
        "STITCH_MAX_DIST_M": float(args.stitch_max_dist_m),
        "STITCH_MAX_ANGLE_DEG": float(args.stitch_max_angle_deg),
        "STITCH_TOPK": int(args.stitch_topk),
        "NEIGHBOR_MAX_DIST_M": float(args.neighbor_max_dist_m),
        "POINT_CLASS_FALLBACK_ANY": int(args.point_class_fallback_any),
    }
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
