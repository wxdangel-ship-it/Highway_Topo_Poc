from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from .core import (
    analyze_patch_candidate,
    estimate_cloud_z_from_arrays,
    estimate_cloud_z_streaming,
)
from .discover import discover_patch_candidates
from .io import iter_cloud_xyz, read_cloud_arrays, read_traj_geojson, resolve_cloud_meta
from .report import write_run_reports
from .types import PatchAnalysis, PatchCandidate


def _repo_root(start: Path) -> Path:
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / "SPEC.md").is_file() and (cand / "docs").is_dir():
            return cand
    return start.resolve()


def _pick_candidates(
    candidates: list[PatchCandidate],
    *,
    patch_key: str | None,
    max_patches: int,
    prefer_small_cloud: bool,
) -> list[PatchCandidate]:
    if patch_key:
        candidates = [c for c in candidates if c.patch_key == patch_key]

    if not candidates:
        return []

    if prefer_small_cloud:
        meta_pairs: list[tuple[int, PatchCandidate]] = []
        for c in candidates:
            try:
                meta = resolve_cloud_meta(c.cloud_path)
                meta_pairs.append((int(meta.point_count), c))
            except Exception:
                meta_pairs.append((10**30, c))
        candidates = [c for _n, c in sorted(meta_pairs, key=lambda x: (x[0], x[1].patch_key))]

    return candidates[: max(0, max_patches)]


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="t01_fusion_qc")
    p.add_argument("--data_root", default="data/synth_local")
    p.add_argument("--out_dir", required=True)
    p.add_argument("--max_patches", type=int, default=1)
    p.add_argument("--patch_key", default=None)

    p.add_argument("--radius_m", type=float, default=1.0)
    p.add_argument("--min_neighbors", type=int, default=5)
    p.add_argument("--knn", type=int, default=16)

    p.add_argument("--th_abs_min", type=float, default=0.05)
    p.add_argument("--th_quantile", type=float, default=0.90)

    p.add_argument("--binN", type=int, default=64)
    p.add_argument("--stride", type=int, default=16)
    p.add_argument("--coverage_gate", type=float, default=0.30)
    p.add_argument("--status_coverage_gate", type=float, default=0.60)

    p.add_argument("--min_interval_len", type=int, default=2)
    p.add_argument("--top_k", type=int, default=5)

    p.add_argument("--chunk_size", type=int, default=500_000)
    p.add_argument("--max_in_memory_points", type=int, default=2_000_000)
    p.add_argument("--knn_search_radius_m", type=float, default=6.0)
    p.add_argument("--max_points_per_cell", type=int, default=128)
    p.add_argument("--seed", type=int, default=0)

    p.add_argument("--prefer_small_cloud", action="store_true", default=True)
    p.add_argument("--no_prefer_small_cloud", action="store_false", dest="prefer_small_cloud")

    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.max_patches <= 0:
        print("ERROR: max_patches_must_be_positive", file=sys.stderr)
        return 1
    if args.binN <= 0 or args.stride <= 0:
        print("ERROR: binN_stride_must_be_positive", file=sys.stderr)
        return 1
    if args.min_neighbors <= 0 or args.knn <= 0:
        print("ERROR: min_neighbors_knn_must_be_positive", file=sys.stderr)
        return 1

    root = _repo_root(Path.cwd())
    data_root = Path(args.data_root)
    if not data_root.is_absolute():
        data_root = (root / data_root).resolve()

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = (root / out_dir).resolve()

    candidates = discover_patch_candidates(data_root)
    if not candidates:
        print("ERROR: no_patch_candidates", file=sys.stderr)
        return 1

    selected = _pick_candidates(
        candidates,
        patch_key=args.patch_key,
        max_patches=args.max_patches,
        prefer_small_cloud=bool(args.prefer_small_cloud),
    )
    if not selected:
        print("ERROR: no_patch_selected", file=sys.stderr)
        return 1

    results: list[PatchAnalysis] = []
    failures: list[str] = []

    for cand in selected:
        try:
            traj = read_traj_geojson(cand.traj_path)
            cloud_meta = resolve_cloud_meta(cand.cloud_path)

            if cloud_meta.point_count <= int(args.max_in_memory_points):
                cloud_meta, cx, cy, cz = read_cloud_arrays(cloud_meta.used_cloud_path)
                z_est, backend, warns = estimate_cloud_z_from_arrays(
                    traj.x,
                    traj.y,
                    cx,
                    cy,
                    cz,
                    radius_m=float(args.radius_m),
                    min_neighbors=int(args.min_neighbors),
                    knn=int(args.knn),
                )
            else:
                cloud_meta, chunks = iter_cloud_xyz(cloud_meta.used_cloud_path, chunk_size=int(args.chunk_size))
                z_est, backend, warns = estimate_cloud_z_streaming(
                    traj.x,
                    traj.y,
                    chunks,
                    radius_m=float(args.radius_m),
                    min_neighbors=int(args.min_neighbors),
                    knn=int(args.knn),
                    knn_search_radius_m=float(args.knn_search_radius_m),
                    max_points_per_cell=int(args.max_points_per_cell),
                    seed=int(args.seed),
                )

            extra_warnings = list(warns)
            extra_warnings.append(f"cloud_point_count={cloud_meta.point_count}")
            if cloud_meta.used_cloud_path.resolve() != cand.cloud_path.resolve():
                extra_warnings.append("cloud_fallback_used")

            result = analyze_patch_candidate(
                cand,
                traj,
                z_est,
                th_abs_min=float(args.th_abs_min),
                th_quantile=float(args.th_quantile),
                binN=int(args.binN),
                stride=int(args.stride),
                coverage_gate=float(args.coverage_gate),
                status_coverage_gate=float(args.status_coverage_gate),
                min_interval_len=int(args.min_interval_len),
                top_k=int(args.top_k),
                backend=backend,
                warnings=extra_warnings,
                repo_root=root,
            )
            results.append(result)
        except Exception as exc:
            failures.append(f"{cand.patch_key}:{type(exc).__name__}")

    if not results:
        print("ERROR: all_selected_patches_failed", file=sys.stderr)
        if failures:
            print("DETAIL: " + ",".join(failures), file=sys.stderr)
        return 1

    params = {
        "data_root": data_root.as_posix(),
        "max_patches": int(args.max_patches),
        "patch_key": args.patch_key,
        "radius_m": float(args.radius_m),
        "min_neighbors": int(args.min_neighbors),
        "knn": int(args.knn),
        "th_abs_min": float(args.th_abs_min),
        "th_quantile": float(args.th_quantile),
        "binN": int(args.binN),
        "stride": int(args.stride),
        "coverage_gate": float(args.coverage_gate),
        "status_coverage_gate": float(args.status_coverage_gate),
        "min_interval_len": int(args.min_interval_len),
        "top_k": int(args.top_k),
        "chunk_size": int(args.chunk_size),
        "max_in_memory_points": int(args.max_in_memory_points),
        "knn_search_radius_m": float(args.knn_search_radius_m),
        "max_points_per_cell": int(args.max_points_per_cell),
        "seed": int(args.seed),
        "prefer_small_cloud": bool(args.prefer_small_cloud),
    }

    write_run_reports(results, out_dir, params)

    print(f"OK processed={len(results)} out_dir={out_dir.as_posix()}")
    if failures:
        print("WARN failed=" + ",".join(failures))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
