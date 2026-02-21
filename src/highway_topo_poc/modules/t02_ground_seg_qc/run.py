from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from .config import Config
from .ground_ref import compute_ground_z
from .intervals import compute_intervals
from .io import discover_patch, load_patch_arrays
from .qc import compute_qc
from .report import build_summary


def run_patch(
    data_root: str | Path,
    patch: str = "auto",
    run_id: str = "auto",
    out_root: str | Path = "outputs/_work/t02_ground_seg_qc",
    config: Config | None = None,
) -> dict[str, object]:
    cfg = config if config is not None else Config()
    cfg.validate()

    candidate = discover_patch(data_root=data_root, patch=patch)
    traj_xyz, points_xyz = load_patch_arrays(candidate)

    traj_xyz = _ensure_xyz(traj_xyz, name="traj")
    points_xyz = _ensure_xyz(points_xyz, name="points")

    ground_z = compute_ground_z(traj_xyz=traj_xyz, points_xyz=points_xyz, cfg=cfg)
    qc_res = compute_qc(traj_z=traj_xyz[:, 2], ground_z=ground_z, cfg=cfg)
    intervals_payload = compute_intervals(abs_res=qc_res.abs_res, valid_mask=qc_res.valid_mask, cfg=cfg)

    run_id_val = _gen_run_id() if run_id == "auto" else str(run_id)
    out_dir = Path(out_root) / run_id_val / candidate.patch_id
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics_payload: dict[str, object] = {
        **qc_res.metrics,
        "patch_id": candidate.patch_id,
    }

    summary = build_summary(
        run_id=run_id_val,
        patch_id=candidate.patch_id,
        patch_dir=candidate.patch_dir,
        traj_path=candidate.traj_path,
        points_path=candidate.points_path,
        output_dir=out_dir,
        metrics=metrics_payload,
        intervals_payload=intervals_payload,
        cfg=cfg,
    )

    _write_json(out_dir / "metrics.json", metrics_payload)
    _write_json(out_dir / "intervals.json", intervals_payload)
    (out_dir / "summary.txt").write_text(summary, encoding="utf-8")

    np.savez_compressed(
        out_dir / "series.npz",
        traj_xyz=traj_xyz,
        ground_z=ground_z,
        z_diff=qc_res.z_diff,
        residual=qc_res.residual,
        abs_res=qc_res.abs_res,
    )

    return {
        "run_id": run_id_val,
        "patch_id": candidate.patch_id,
        "patch_dir": str(candidate.patch_dir),
        "traj_path": str(candidate.traj_path),
        "points_path": str(candidate.points_path),
        "output_dir": str(out_dir),
        "metrics": metrics_payload,
        "intervals": intervals_payload,
        "summary": summary,
    }


def _ensure_xyz(arr: np.ndarray, *, name: str) -> np.ndarray:
    a = np.asarray(arr, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] < 3:
        raise ValueError(f"{name}_xyz_shape_invalid")
    return a[:, :3]


def _gen_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _write_json(path: Path, payload: object) -> None:
    safe = _to_json_safe(payload)
    path.write_text(json.dumps(safe, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _to_json_safe(obj: object) -> object:
    if isinstance(obj, dict):
        return {str(k): _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [_to_json_safe(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)

    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.floating, float)):
        val = float(obj)
        return val if math.isfinite(val) else None

    return obj


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="t02_ground_seg_qc")
    parser.add_argument("--data_root", default="data/synth_local")
    parser.add_argument("--patch", default="auto")
    parser.add_argument("--run_id", default="auto")
    parser.add_argument("--out_root", default="outputs/_work/t02_ground_seg_qc")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_patch(
            data_root=args.data_root,
            patch=args.patch,
            run_id=args.run_id,
            out_root=args.out_root,
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    summary_lines = str(result["summary"]).splitlines()
    print("\n".join(summary_lines[:40]))
    if len(summary_lines) > 40:
        print("... (stdout truncated; see summary.txt)")

    output_dir = result["output_dir"]
    patch_dir = result["patch_dir"]
    traj_path = result["traj_path"]
    points_path = result["points_path"]
    print(f"OutputDir: {output_dir}")
    print(f"SelectedPatchDir: {patch_dir}")
    print(f"SelectedTraj: {traj_path}")
    print(f"SelectedPoints: {points_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
