from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from .io import (
    TRAJ_SPLIT_MAX_GAP_M_DEFAULT,
    TRAJ_SPLIT_MAX_SEQ_GAP_DEFAULT,
    TRAJ_SPLIT_MAX_TIME_GAP_S_DEFAULT,
    InputDataError,
    load_patch_trajectory_lines,
    resolve_repo_root,
    write_geojson_lines,
    write_json,
)


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="t05_export_traj_lines")
    p.add_argument("--data_root", default="data/synth_local")
    p.add_argument("--patch_id", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--out_crs", choices=["patch", "metric"], default="patch")
    p.add_argument("--traj_split_max_gap_m", type=float, default=TRAJ_SPLIT_MAX_GAP_M_DEFAULT)
    p.add_argument("--traj_split_max_time_gap_s", type=float, default=TRAJ_SPLIT_MAX_TIME_GAP_S_DEFAULT)
    p.add_argument("--traj_split_max_seq_gap", type=int, default=TRAJ_SPLIT_MAX_SEQ_GAP_DEFAULT)
    return p.parse_args(list(argv) if argv is not None else None)


def _default_out_path(*, repo_root: Path, patch_id: str, out_crs: str) -> Path:
    return (
        repo_root
        / "outputs"
        / "_work"
        / "t05_topology_between_rc"
        / "traj_lines"
        / patch_id
        / f"traj_lines_all__{out_crs}.geojson"
    )


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = resolve_repo_root(Path.cwd())
    out_path = Path(args.out).resolve() if args.out else _default_out_path(
        repo_root=repo_root,
        patch_id=str(args.patch_id),
        out_crs=str(args.out_crs),
    )

    try:
        crs_name, lines, properties_list, summary = load_patch_trajectory_lines(
            args.data_root,
            patch_id=args.patch_id,
            out_crs=args.out_crs,
            traj_split_max_gap_m=float(args.traj_split_max_gap_m),
            traj_split_max_time_gap_s=float(args.traj_split_max_time_gap_s),
            traj_split_max_seq_gap=int(args.traj_split_max_seq_gap),
        )
    except InputDataError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    write_geojson_lines(
        out_path,
        lines_input_crs=lines,
        properties_list=properties_list,
        crs_name=crs_name,
    )
    write_json(
        out_path.with_suffix(".summary.json"),
        {
            **dict(summary),
            "out_path": out_path.as_posix(),
        },
    )
    print(out_path.as_posix())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
