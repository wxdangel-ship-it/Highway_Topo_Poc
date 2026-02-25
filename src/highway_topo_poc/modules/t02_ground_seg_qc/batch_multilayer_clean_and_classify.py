from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from .io import load_traj_xyz

POINT_EXTS = {".laz", ".las"}
MAX_TRAJ_SAMPLES_PER_CELL = 2048

GROUND_CLASS = 2
NON_GROUND_CLASS = 1
OVERLAP_CLASS = 12


@dataclass(frozen=True)
class PatchInput:
    patch_key: str
    patch_dir: Path
    points_path: Path | None
    traj_paths: list[Path]


@dataclass(frozen=True)
class RefSurface:
    x0: float
    y0: float
    ref_grid_m: float
    keys_sorted: np.ndarray
    ref_z_sorted: np.ndarray
    spread_sorted: np.ndarray
    reliable_sorted: np.ndarray
    dz_up_keep_sorted: np.ndarray
    dz_down_keep_sorted: np.ndarray
    traj_file_count: int
    traj_point_count: int
    stats: dict[str, object]


@dataclass(frozen=True)
class OverlapModel:
    kept_high_keys_sorted: np.ndarray
    kept_low_keys_sorted: np.ndarray
    mean_high_sorted: np.ndarray
    mean_low_sorted: np.ndarray
    report: dict[str, object]


def run_batch(
    *,
    data_root: str | Path,
    out_root: str | Path = "outputs/_work/t02_ground_seg_qc",
    run_id: str = "auto",
    resume: bool = True,
    workers: int = 1,
    chunk_points: int = 2_000_000,
    ref_grid_m: float = 5.0,
    ground_grid_m: float = 1.0,
    ground_above_margin_m: float = 0.08,
    layer_band_m: float = 2.0,
    suspect_far_ratio_gate: float = 0.03,
    suspect_min_far_points: int = 2000,
    min_total_points_per_cell: int = 5000,
    min_cluster_cells: int = 200,
    detect_up_min_m: float = 6.0,
    detect_up_extra_m: float = 3.0,
    detect_down_min_m: float = 4.0,
    detect_down_extra_m: float = 2.0,
    dz_up_base_m: float = 2.0,
    dz_up_k: float = 3.0,
    dz_up_max_m: float = 8.0,
    dz_down_base_m: float = 0.8,
    dz_down_k: float = 2.0,
    dz_down_min_m: float = 0.3,
    dz_down_max_m: float = 1.0,
    traj_spread_cap_m: float = 1.5,
    out_format: str = "laz",
    write_full_tagged: bool = True,
    verify: bool = True,
) -> dict[str, object]:
    if chunk_points < 1:
        raise ValueError("chunk_points must be >= 1")
    if ref_grid_m <= 0:
        raise ValueError("ref_grid_m must be > 0")
    if ground_grid_m <= 0:
        raise ValueError("ground_grid_m must be > 0")
    if ground_above_margin_m < 0:
        raise ValueError("ground_above_margin_m must be >= 0")
    if layer_band_m <= 0:
        raise ValueError("layer_band_m must be > 0")
    if suspect_far_ratio_gate < 0 or suspect_far_ratio_gate > 1:
        raise ValueError("suspect_far_ratio_gate must be in [0,1]")
    if suspect_min_far_points < 1:
        raise ValueError("suspect_min_far_points must be >= 1")
    if min_total_points_per_cell < 1:
        raise ValueError("min_total_points_per_cell must be >= 1")
    if min_cluster_cells < 1:
        raise ValueError("min_cluster_cells must be >= 1")
    if detect_up_min_m < 0:
        raise ValueError("detect_up_min_m must be >= 0")
    if detect_up_extra_m < 0:
        raise ValueError("detect_up_extra_m must be >= 0")
    if detect_down_min_m < 0:
        raise ValueError("detect_down_min_m must be >= 0")
    if detect_down_extra_m < 0:
        raise ValueError("detect_down_extra_m must be >= 0")
    if dz_up_base_m < 2.0:
        raise ValueError("dz_up_base_m must be >= 2.0")
    if dz_up_max_m < dz_up_base_m:
        raise ValueError("dz_up_max_m must be >= dz_up_base_m")
    if dz_up_k < 0:
        raise ValueError("dz_up_k must be >= 0")
    if dz_down_k < 0:
        raise ValueError("dz_down_k must be >= 0")
    if dz_down_min_m <= 0:
        raise ValueError("dz_down_min_m must be > 0")
    if dz_down_max_m > 1.0:
        raise ValueError("dz_down_max_m must be <= 1.0")
    if dz_down_min_m > dz_down_max_m:
        raise ValueError("dz_down_min_m must be <= dz_down_max_m")
    if traj_spread_cap_m <= 0:
        raise ValueError("traj_spread_cap_m must be > 0")

    fmt = str(out_format).strip().lower()
    if fmt not in {"laz", "las"}:
        raise ValueError("out_format must be one of: laz, las")

    patches = discover_patches(data_root)
    if not patches:
        raise ValueError(f"no_patch_found_under: {Path(data_root)}")

    if workers != 1:
        print(f"WARN: workers={workers} is currently executed sequentially (workers=1).", file=sys.stderr)

    run_id_val = _gen_run_id() if str(run_id) == "auto" else str(run_id)
    run_root = Path(out_root) / run_id_val
    multilayer_root = run_root / "multilayer_clean"
    multilayer_root.mkdir(parents=True, exist_ok=True)

    params_snapshot = {
        "data_root": str(Path(data_root)),
        "out_root": str(Path(out_root)),
        "run_id": run_id_val,
        "resume": bool(resume),
        "workers": int(workers),
        "chunk_points": int(chunk_points),
        "ref_grid_m": float(ref_grid_m),
        "ground_grid_m": float(ground_grid_m),
        "ground_above_margin_m": float(ground_above_margin_m),
        "layer_band_m": float(layer_band_m),
        "suspect_far_ratio_gate": float(suspect_far_ratio_gate),
        "suspect_min_far_points": int(suspect_min_far_points),
        "min_total_points_per_cell": int(min_total_points_per_cell),
        "min_cluster_cells": int(min_cluster_cells),
        "detect_up_min_m": float(detect_up_min_m),
        "detect_up_extra_m": float(detect_up_extra_m),
        "detect_down_min_m": float(detect_down_min_m),
        "detect_down_extra_m": float(detect_down_extra_m),
        "dz_up_base_m": float(dz_up_base_m),
        "dz_up_k": float(dz_up_k),
        "dz_up_max_m": float(dz_up_max_m),
        "dz_down_base_m": float(dz_down_base_m),
        "dz_down_k": float(dz_down_k),
        "dz_down_min_m": float(dz_down_min_m),
        "dz_down_max_m": float(dz_down_max_m),
        "traj_spread_cap_m": float(traj_spread_cap_m),
        "out_format": fmt,
        "write_full_tagged": bool(write_full_tagged),
        "verify": bool(verify),
    }

    rows: list[dict[str, object]] = []
    failed_rows: list[dict[str, object]] = []
    laz_fallback_count = 0

    for patch in patches:
        row = _process_patch(
            patch=patch,
            multilayer_root=multilayer_root,
            params=params_snapshot,
        )
        rows.append(row)
        if str(row.get("reason", "")).startswith("fallback_laz_to_las"):
            laz_fallback_count += 1
        if not bool(row.get("overall_pass", False)):
            failed_rows.append(row)

    manifest_path = run_root / "multilayer_manifest.jsonl"
    _write_jsonl(manifest_path, rows)

    summary = {
        "run_id": run_id_val,
        "multilayer_clean_root": str(multilayer_root),
        "manifest_path": str(manifest_path),
        "total_patches": int(len(rows)),
        "pass_patches": int(len(rows) - len(failed_rows)),
        "fail_patches": int(len(failed_rows)),
        "failed_patch_keys": [str(x.get("patch_key")) for x in failed_rows],
        "laz_fallback_count": int(laz_fallback_count),
        "params": params_snapshot,
    }
    _write_json(run_root / "multilayer_summary.json", summary)
    return summary


def _process_patch(
    *,
    patch: PatchInput,
    multilayer_root: Path,
    params: dict[str, object],
) -> dict[str, object]:
    out_dir = multilayer_root / patch.patch_key
    out_dir.mkdir(parents=True, exist_ok=True)

    preferred_fmt = str(params["out_format"])
    write_full_tagged = bool(params["write_full_tagged"])
    resume = bool(params["resume"])

    existing = _resolve_existing_outputs(
        out_dir=out_dir,
        preferred_format=preferred_fmt,
        write_full_tagged=write_full_tagged,
    )
    stats_path = out_dir / "patch_stats.json"
    if resume and existing is not None and stats_path.is_file():
        try:
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
            return {
                "patch_key": patch.patch_key,
                "patch_dir": str(patch.patch_dir),
                "points_path": str(patch.points_path) if patch.points_path is not None else None,
                "traj_count": int(len(patch.traj_paths)),
                "out_cleaned_path": str(existing["cleaned"]),
                "out_full_tagged_path": str(existing["full"]) if existing["full"] is not None else None,
                "out_format": str(existing["format"]),
                "n_in": int(_as_number(stats.get("n_in"), default=0)),
                "n_kept": int(_as_number(stats.get("n_kept"), default=0)),
                "n_removed": int(_as_number(stats.get("n_removed"), default=0)),
                "removed_ratio": float(_as_number(stats.get("removed_ratio"), default=0.0)),
                "pass_fail": "pass" if bool(_as_bool(stats.get("overall_pass"), default=True)) else "fail",
                "overall_pass": bool(_as_bool(stats.get("overall_pass"), default=True)),
                "reason": "resume_skip",
                "output_dir": str(out_dir),
            }
        except Exception:
            pass

    points_path = patch.points_path
    if points_path is None:
        return _fail_row(
            patch=patch,
            out_dir=out_dir,
            reason="points_not_found",
        )

    if not points_path.is_file():
        return _fail_row(
            patch=patch,
            out_dir=out_dir,
            reason=f"points_not_found:{points_path}",
        )

    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - env-dependent
        return _fail_row(
            patch=patch,
            out_dir=out_dir,
            reason=f"laspy_required:{type(exc).__name__}:{exc}",
            points_path=points_path,
        )

    try:
        with laspy.open(str(points_path)) as reader:
            header = reader.header
            point_count = int(header.point_count)
            mins = np.asarray(header.mins, dtype=np.float64)
            maxs = np.asarray(header.maxs, dtype=np.float64)
            x0 = float(mins[0]) if mins.size >= 1 else 0.0
            y0 = float(mins[1]) if mins.size >= 2 else 0.0
            maxx = float(maxs[0]) if maxs.size >= 1 else x0
            maxy = float(maxs[1]) if maxs.size >= 2 else y0
            dim_names = set(header.point_format.dimension_names)
            if "classification" not in dim_names:
                return _fail_row(
                    patch=patch,
                    out_dir=out_dir,
                    reason="classification_dimension_missing",
                    points_path=points_path,
                )
    except Exception as exc:
        return _fail_row(
            patch=patch,
            out_dir=out_dir,
            reason=f"points_read_error:{type(exc).__name__}:{exc}",
            points_path=points_path,
        )

    ref_surface = _build_ref_surface(
        points_path=points_path,
        traj_paths=patch.traj_paths,
        ref_grid_m=float(params["ref_grid_m"]),
        traj_spread_cap_m=float(params["traj_spread_cap_m"]),
        dz_up_base_m=float(params["dz_up_base_m"]),
        dz_up_k=float(params["dz_up_k"]),
        dz_up_max_m=float(params["dz_up_max_m"]),
        dz_down_base_m=float(params["dz_down_base_m"]),
        dz_down_k=float(params["dz_down_k"]),
        dz_down_min_m=float(params["dz_down_min_m"]),
        dz_down_max_m=float(params["dz_down_max_m"]),
        x0=x0,
        y0=y0,
        maxx=maxx,
        maxy=maxy,
    )
    _write_json(out_dir / "ref_surface_stats.json", ref_surface.stats)

    overlap_model = _pass1_find_overlap_cells(
        points_path=points_path,
        chunk_points=int(params["chunk_points"]),
        ref_surface=ref_surface,
        suspect_far_ratio_gate=float(params["suspect_far_ratio_gate"]),
        suspect_min_far_points=int(params["suspect_min_far_points"]),
        min_total_points_per_cell=int(params["min_total_points_per_cell"]),
        min_cluster_cells=int(params["min_cluster_cells"]),
        detect_up_min_m=float(params["detect_up_min_m"]),
        detect_up_extra_m=float(params["detect_up_extra_m"]),
        detect_down_min_m=float(params["detect_down_min_m"]),
        detect_down_extra_m=float(params["detect_down_extra_m"]),
    )
    _write_json(out_dir / "overlap_cells_report.json", overlap_model.report)

    pass2_stats, ground_min_cell = _pass2_collect_ground_min(
        points_path=points_path,
        chunk_points=int(params["chunk_points"]),
        ref_surface=ref_surface,
        overlap_model=overlap_model,
        ground_grid_m=float(params["ground_grid_m"]),
        layer_band_m=float(params["layer_band_m"]),
        ground_anchor_x0=x0,
        ground_anchor_y0=y0,
    )
    _write_json(out_dir / "clean_pass2_stats.json", pass2_stats)

    preferred_cleaned = out_dir / f"merged_cleaned_classified.{preferred_fmt}"
    preferred_full = out_dir / f"merged_full_tagged.{preferred_fmt}" if write_full_tagged else None
    fallback_cleaned = out_dir / "merged_cleaned_classified.las"
    fallback_full = out_dir / "merged_full_tagged.las" if write_full_tagged else None

    reason = "ok"
    actual_fmt = preferred_fmt
    out_cleaned = preferred_cleaned
    out_full = preferred_full

    try:
        pass3_stats = _pass3_write_outputs(
            points_path=points_path,
            out_cleaned_path=out_cleaned,
            out_full_path=out_full,
            chunk_points=int(params["chunk_points"]),
            ref_surface=ref_surface,
            overlap_model=overlap_model,
            ground_min_cell=ground_min_cell,
            ground_grid_m=float(params["ground_grid_m"]),
            ground_above_margin_m=float(params["ground_above_margin_m"]),
            layer_band_m=float(params["layer_band_m"]),
            ground_anchor_x0=x0,
            ground_anchor_y0=y0,
            verify=bool(params["verify"]),
            expected_n_in=int(pass2_stats["n_in"]),
            expected_n_kept=int(pass2_stats["n_kept"]),
            expected_n_removed=int(pass2_stats["n_removed"]),
            write_full_tagged=write_full_tagged,
        )
    except Exception as exc:
        if preferred_fmt == "laz" and _is_laz_backend_error(exc):
            reason = f"fallback_laz_to_las:{type(exc).__name__}"
            actual_fmt = "las"
            out_cleaned = fallback_cleaned
            out_full = fallback_full
            _safe_unlink(preferred_cleaned)
            if preferred_full is not None:
                _safe_unlink(preferred_full)
            try:
                pass3_stats = _pass3_write_outputs(
                    points_path=points_path,
                    out_cleaned_path=out_cleaned,
                    out_full_path=out_full,
                    chunk_points=int(params["chunk_points"]),
                    ref_surface=ref_surface,
                    overlap_model=overlap_model,
                    ground_min_cell=ground_min_cell,
                    ground_grid_m=float(params["ground_grid_m"]),
                    ground_above_margin_m=float(params["ground_above_margin_m"]),
                    layer_band_m=float(params["layer_band_m"]),
                    ground_anchor_x0=x0,
                    ground_anchor_y0=y0,
                    verify=bool(params["verify"]),
                    expected_n_in=int(pass2_stats["n_in"]),
                    expected_n_kept=int(pass2_stats["n_kept"]),
                    expected_n_removed=int(pass2_stats["n_removed"]),
                    write_full_tagged=write_full_tagged,
                )
            except Exception as exc2:
                return _fail_row(
                    patch=patch,
                    out_dir=out_dir,
                    reason=f"write_fallback_error:{type(exc2).__name__}:{exc2}",
                    points_path=points_path,
                )
        else:
            return _fail_row(
                patch=patch,
                out_dir=out_dir,
                reason=f"write_error:{type(exc).__name__}:{exc}",
                points_path=points_path,
            )

    patch_stats = {
        "patch_key": patch.patch_key,
        "patch_dir": str(patch.patch_dir),
        "points_path": str(points_path),
        "traj_count": int(len(patch.traj_paths)),
        "traj_paths": [str(p) for p in patch.traj_paths],
        "n_in": int(pass2_stats["n_in"]),
        "n_kept": int(pass2_stats["n_kept"]),
        "n_removed": int(pass2_stats["n_removed"]),
        "removed_high": int(pass2_stats["removed_high"]),
        "removed_low": int(pass2_stats["removed_low"]),
        "removed_ratio": float(pass2_stats["removed_ratio"]),
        "ground_count": int(pass3_stats["class2_count"]),
        "class1_count": int(pass3_stats["class1_count"]),
        "class2_count": int(pass3_stats["class2_count"]),
        "class12_count": int(pass3_stats["class12_count"]),
        "out_kept_count": int(pass3_stats["out_kept_count"]),
        "out_full_count": int(pass3_stats["out_full_count"]),
        "out_format": actual_fmt,
        "out_cleaned_path": str(out_cleaned),
        "out_full_tagged_path": str(out_full) if out_full is not None else None,
        "verify": bool(params["verify"]),
        "overall_pass": True,
        "reason": reason,
        "params": {
            "chunk_points": int(params["chunk_points"]),
            "ref_grid_m": float(params["ref_grid_m"]),
            "ground_grid_m": float(params["ground_grid_m"]),
            "ground_above_margin_m": float(params["ground_above_margin_m"]),
            "layer_band_m": float(params["layer_band_m"]),
            "suspect_far_ratio_gate": float(params["suspect_far_ratio_gate"]),
            "suspect_min_far_points": int(params["suspect_min_far_points"]),
            "min_total_points_per_cell": int(params["min_total_points_per_cell"]),
            "min_cluster_cells": int(params["min_cluster_cells"]),
            "detect_up_min_m": float(params["detect_up_min_m"]),
            "detect_up_extra_m": float(params["detect_up_extra_m"]),
            "detect_down_min_m": float(params["detect_down_min_m"]),
            "detect_down_extra_m": float(params["detect_down_extra_m"]),
            "dz_up_base_m": float(params["dz_up_base_m"]),
            "dz_up_k": float(params["dz_up_k"]),
            "dz_up_max_m": float(params["dz_up_max_m"]),
            "dz_down_base_m": float(params["dz_down_base_m"]),
            "dz_down_k": float(params["dz_down_k"]),
            "dz_down_min_m": float(params["dz_down_min_m"]),
            "dz_down_max_m": float(params["dz_down_max_m"]),
            "traj_spread_cap_m": float(params["traj_spread_cap_m"]),
            "write_full_tagged": write_full_tagged,
            "classification": {
                "ground": GROUND_CLASS,
                "non_ground": NON_GROUND_CLASS,
                "overlap_removed": OVERLAP_CLASS,
            },
        },
    }
    _write_json(stats_path, patch_stats)

    return {
        "patch_key": patch.patch_key,
        "patch_dir": str(patch.patch_dir),
        "points_path": str(points_path),
        "traj_count": int(len(patch.traj_paths)),
        "out_cleaned_path": str(out_cleaned),
        "out_full_tagged_path": str(out_full) if out_full is not None else None,
        "out_format": actual_fmt,
        "n_in": int(pass2_stats["n_in"]),
        "n_kept": int(pass2_stats["n_kept"]),
        "n_removed": int(pass2_stats["n_removed"]),
        "removed_ratio": float(pass2_stats["removed_ratio"]),
        "pass_fail": "pass",
        "overall_pass": True,
        "reason": reason,
        "output_dir": str(out_dir),
    }


def discover_patches(data_root: str | Path) -> list[PatchInput]:
    root = Path(data_root)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"data_root_not_found: {root}")

    patch_dirs: set[Path] = set()
    for p in sorted(root.rglob("*"), key=lambda q: q.as_posix()):
        if not p.is_file():
            continue
        name = p.name.lower()
        suffix = p.suffix.lower()
        rel = p.relative_to(root).as_posix().lower()
        is_point = suffix in POINT_EXTS and ("pointcloud/" in rel or name.startswith("merged.") or "point" in name or "cloud" in name)
        is_traj = suffix == ".geojson" and ("traj" in name or "pose" in name or "raw_dat_pose" in name)
        if is_point or is_traj:
            patch_dirs.add(_infer_patch_dir(root=root, path=p))

    used_keys: set[str] = set()
    out: list[PatchInput] = []
    for patch_dir in sorted(patch_dirs, key=lambda x: x.as_posix()):
        if not patch_dir.exists() or not patch_dir.is_dir():
            continue
        patch_key = _build_patch_key(root=root, patch_dir=patch_dir, used_keys=used_keys)
        points_path = _find_points_path_for_patch(patch_dir)
        traj_paths = _find_traj_paths_for_patch(patch_dir)
        out.append(
            PatchInput(
                patch_key=patch_key,
                patch_dir=patch_dir,
                points_path=points_path,
                traj_paths=traj_paths,
            )
        )
    return out


def discover_patch_inputs(data_root: str | Path) -> list[PatchInput]:
    return discover_patches(data_root)


def _find_points_path_for_patch(patch_dir: Path) -> Path | None:
    candidates: list[Path] = []

    p1 = patch_dir / "PointCloud" / "merged.laz"
    p2 = patch_dir / "PointCloud" / "merged.las"
    if p1.is_file():
        return p1
    if p2.is_file():
        return p2

    for p in patch_dir.rglob("*"):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix not in POINT_EXTS:
            continue
        candidates.append(p)

    if not candidates:
        return None

    def rank(path: Path) -> tuple[int, str]:
        name = path.name.lower()
        rel = path.as_posix().lower()
        if "pointcloud/merged.laz" in rel:
            p = 0
        elif "pointcloud/merged.las" in rel:
            p = 1
        elif name == "merged.laz":
            p = 2
        elif name == "merged.las":
            p = 3
        elif path.suffix.lower() == ".laz":
            p = 4
        else:
            p = 5
        return p, rel

    return sorted(candidates, key=rank)[0]


def _find_traj_paths_for_patch(patch_dir: Path) -> list[Path]:
    preferred = [
        p
        for p in patch_dir.glob("Traj/*/raw_dat_pose.geojson")
        if p.is_file()
    ]
    preferred = sorted({p.resolve() for p in preferred})
    if preferred:
        valid = [Path(p) for p in preferred if _traj_has_valid_z(Path(p))]
        return sorted(valid, key=lambda x: x.as_posix())

    fallback: list[Path] = []
    for p in patch_dir.rglob("*.geojson"):
        if not p.is_file():
            continue
        name = p.name.lower()
        rel = p.relative_to(patch_dir).as_posix().lower()
        if ("traj" not in name and "pose" not in name and "raw_dat_pose" not in name and "traj" not in rel and "pose" not in rel):
            continue
        if _traj_has_valid_z(p):
            fallback.append(p)

    uniq = sorted({p.resolve() for p in fallback}, key=lambda x: x.as_posix())
    return [Path(p) for p in uniq]


def _traj_has_valid_z(path: Path) -> bool:
    try:
        xyz = np.asarray(load_traj_xyz(path), dtype=np.float64)
    except Exception:
        return False
    if xyz.ndim != 2 or xyz.shape[1] < 3:
        return False
    if xyz.shape[0] == 0:
        return False
    z = np.asarray(xyz[:, 2], dtype=np.float64)
    return bool(np.any(np.isfinite(z)))


def _build_ref_surface(
    *,
    points_path: Path,
    traj_paths: list[Path],
    ref_grid_m: float,
    traj_spread_cap_m: float,
    dz_up_base_m: float,
    dz_up_k: float,
    dz_up_max_m: float,
    dz_down_base_m: float,
    dz_down_k: float,
    dz_down_min_m: float,
    dz_down_max_m: float,
    x0: float,
    y0: float,
    maxx: float,
    maxy: float,
) -> RefSurface:
    cell_z: dict[int, list[float]] = {}
    traj_point_count = 0
    traj_valid_file_count = 0

    for traj_path in traj_paths:
        try:
            xyz = np.asarray(load_traj_xyz(traj_path), dtype=np.float64)
        except Exception:
            continue
        if xyz.ndim != 2 or xyz.shape[1] < 3 or xyz.shape[0] <= 0:
            continue

        x = np.asarray(xyz[:, 0], dtype=np.float64)
        y = np.asarray(xyz[:, 1], dtype=np.float64)
        z = np.asarray(xyz[:, 2], dtype=np.float64)
        valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
        if not np.any(valid):
            continue

        traj_valid_file_count += 1
        xv = x[valid]
        yv = y[valid]
        zv = z[valid]
        traj_point_count += int(zv.size)

        ix = np.floor((xv - x0) / ref_grid_m).astype(np.int64)
        iy = np.floor((yv - y0) / ref_grid_m).astype(np.int64)
        keys = _pack_cells(ix, iy)

        order = np.argsort(keys, kind="mergesort")
        keys_sorted = keys[order]
        z_sorted = zv[order]

        if keys_sorted.size == 0:
            continue
        change = np.empty(keys_sorted.size, dtype=bool)
        change[0] = True
        change[1:] = keys_sorted[1:] != keys_sorted[:-1]
        starts = np.flatnonzero(change)
        ends = np.concatenate([starts[1:], np.array([keys_sorted.size], dtype=np.int64)])
        for s, e in zip(starts.tolist(), ends.tolist()):
            key = int(keys_sorted[s])
            _append_cell_samples(
                cell_z=cell_z,
                key=key,
                zvals=np.asarray(z_sorted[s:e], dtype=np.float64),
                max_samples=MAX_TRAJ_SAMPLES_PER_CELL,
            )

    if not cell_z:
        stats = {
            "points_path": str(points_path),
            "traj_count": int(len(traj_paths)),
            "traj_valid_count": int(traj_valid_file_count),
            "traj_pts": int(traj_point_count),
            "traj_file_count": int(len(traj_paths)),
            "traj_point_count": int(traj_point_count),
            "ref_cell_count": 0,
            "reliable_cell_count": 0,
            "unreliable_cell_count": 0,
            "coverage": 0.0,
            "coverage_est": 0.0,
            "cell_z_samples": {"min": 0, "median": 0, "p90": 0},
            "dz_up_keep_stats": {"min": 0.0, "median": 0.0, "p90": 0.0, "max": 0.0},
            "dz_down_keep_stats": {"min": 0.0, "median": 0.0, "p90": 0.0, "max": 0.0},
            "ref_grid_m": float(ref_grid_m),
            "traj_spread_cap_m": float(traj_spread_cap_m),
            "sample_cap_per_cell": int(MAX_TRAJ_SAMPLES_PER_CELL),
            "spread_method_counts": {"default": 0},
        }
        empty_i64 = np.empty((0,), dtype=np.int64)
        empty_f64 = np.empty((0,), dtype=np.float64)
        empty_b = np.empty((0,), dtype=bool)
        return RefSurface(
            x0=x0,
            y0=y0,
            ref_grid_m=ref_grid_m,
            keys_sorted=empty_i64,
            ref_z_sorted=empty_f64,
            spread_sorted=empty_f64,
            reliable_sorted=empty_b,
            dz_up_keep_sorted=empty_f64,
            dz_down_keep_sorted=empty_f64,
            traj_file_count=int(len(traj_paths)),
            traj_point_count=int(traj_point_count),
            stats=stats,
        )

    keys = np.asarray(sorted(cell_z.keys()), dtype=np.int64)
    n = int(keys.size)
    ref_z = np.empty((n,), dtype=np.float64)
    spread = np.empty((n,), dtype=np.float64)
    sample_counts = np.empty((n,), dtype=np.int64)
    spread_method_counts: dict[str, int] = {"mad": 0, "p90_p10": 0, "std": 0, "default": 0}

    for i, key in enumerate(keys.tolist()):
        zvals = np.asarray(cell_z[int(key)], dtype=np.float64)
        zvals = zvals[np.isfinite(zvals)]
        sample_counts[i] = int(zvals.size)
        if zvals.size == 0:
            ref_z[i] = np.nan
            spread[i] = 0.1
            spread_method_counts["default"] = int(spread_method_counts["default"] + 1)
            continue

        med = float(np.median(zvals))
        ref_z[i] = med
        sig, method = _estimate_spread(zvals=zvals, median=med)
        spread[i] = float(sig)
        spread_method_counts[method] = int(spread_method_counts.get(method, 0) + 1)

    dz_up = np.clip(dz_up_base_m + dz_up_k * spread, dz_up_base_m, dz_up_max_m).astype(np.float64)
    dz_down = np.clip(dz_down_base_m + dz_down_k * spread, dz_down_min_m, dz_down_max_m).astype(np.float64)
    reliable = np.isfinite(ref_z) & np.isfinite(spread) & (spread <= float(traj_spread_cap_m))

    bbox_cells = int(max(1.0, math.ceil(max((maxx - x0), 0.0) / ref_grid_m) + 1) * max(1.0, math.ceil(max((maxy - y0), 0.0) / ref_grid_m) + 1))
    coverage_est = float(n / bbox_cells) if bbox_cells > 0 else 0.0

    stats = {
        "points_path": str(points_path),
        "traj_count": int(len(traj_paths)),
        "traj_valid_count": int(traj_valid_file_count),
        "traj_pts": int(traj_point_count),
        "traj_file_count": int(len(traj_paths)),
        "traj_point_count": int(traj_point_count),
        "ref_cell_count": int(n),
        "reliable_cell_count": int(np.count_nonzero(reliable)),
        "unreliable_cell_count": int(n - np.count_nonzero(reliable)),
        "coverage": float(coverage_est),
        "coverage_est": float(coverage_est),
        "cell_z_samples": {
            "min": int(np.min(sample_counts)) if sample_counts.size > 0 else 0,
            "median": int(np.median(sample_counts)) if sample_counts.size > 0 else 0,
            "p90": int(np.quantile(sample_counts, 0.90)) if sample_counts.size > 0 else 0,
        },
        "spread_stats": _series_stats(spread),
        "spread_method_counts": spread_method_counts,
        "dz_up_keep_stats": _series_stats(dz_up),
        "dz_down_keep_stats": _series_stats(dz_down),
        "ref_grid_m": float(ref_grid_m),
        "traj_spread_cap_m": float(traj_spread_cap_m),
        "sample_cap_per_cell": int(MAX_TRAJ_SAMPLES_PER_CELL),
        "threshold_formula": {
            "spread": "MAD -> (p90-p10)/2 -> std -> 0.1",
            "dz_up_keep": f"clamp({dz_up_base_m} + {dz_up_k}*spread, {dz_up_base_m}, {dz_up_max_m})",
            "dz_down_keep": f"clamp({dz_down_base_m} + {dz_down_k}*spread, {dz_down_min_m}, {dz_down_max_m})",
        },
    }

    return RefSurface(
        x0=x0,
        y0=y0,
        ref_grid_m=ref_grid_m,
        keys_sorted=keys,
        ref_z_sorted=ref_z,
        spread_sorted=spread,
        reliable_sorted=reliable,
        dz_up_keep_sorted=dz_up,
        dz_down_keep_sorted=dz_down,
        traj_file_count=int(len(traj_paths)),
        traj_point_count=int(traj_point_count),
        stats=stats,
    )


def _pass1_find_overlap_cells(
    *,
    points_path: Path,
    chunk_points: int,
    ref_surface: RefSurface,
    suspect_far_ratio_gate: float,
    suspect_min_far_points: int,
    min_total_points_per_cell: int,
    min_cluster_cells: int,
    detect_up_min_m: float,
    detect_up_extra_m: float,
    detect_down_min_m: float,
    detect_down_extra_m: float,
) -> OverlapModel:
    total_ref_count: dict[int, int] = {}
    above_far_count: dict[int, int] = {}
    below_far_count: dict[int, int] = {}
    sum_dz_above_far: dict[int, float] = {}
    sum_dz_below_far: dict[int, float] = {}

    if ref_surface.keys_sorted.size > 0 and np.any(ref_surface.reliable_sorted):
        try:
            import laspy  # type: ignore
        except Exception as exc:  # pragma: no cover - env-dependent
            raise ValueError(f"laspy_required:{type(exc).__name__}:{exc}") from exc

        with laspy.open(str(points_path)) as reader:
            for chunk in reader.chunk_iterator(int(chunk_points)):
                x = np.asarray(chunk.x, dtype=np.float64)
                y = np.asarray(chunk.y, dtype=np.float64)
                z = np.asarray(chunk.z, dtype=np.float64)

                valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
                if not np.any(valid):
                    continue

                xv = x[valid]
                yv = y[valid]
                zv = z[valid]

                ix = np.floor((xv - ref_surface.x0) / ref_surface.ref_grid_m).astype(np.int64)
                iy = np.floor((yv - ref_surface.y0) / ref_surface.ref_grid_m).astype(np.int64)
                keys = _pack_cells(ix, iy)

                matched, pos = _lookup_match_positions(keys, ref_surface.keys_sorted)
                if not np.any(matched):
                    continue

                matched_idx = np.flatnonzero(matched)
                reliable_hit = ref_surface.reliable_sorted[pos[matched_idx]]
                if not np.any(reliable_hit):
                    continue
                keep_idx = matched_idx[reliable_hit]

                keys_ref = keys[keep_idx]
                pos_ref = pos[keep_idx]
                dz = zv[keep_idx] - ref_surface.ref_z_sorted[pos_ref]
                dz_up_keep = ref_surface.dz_up_keep_sorted[pos_ref]
                dz_down_keep = ref_surface.dz_down_keep_sorted[pos_ref]
                dz_up_detect = np.maximum(float(detect_up_min_m), dz_up_keep + float(detect_up_extra_m))
                dz_down_detect = np.maximum(float(detect_down_min_m), dz_down_keep + float(detect_down_extra_m))

                above_far = dz > dz_up_detect
                below_far = dz < -dz_down_detect

                _accumulate_count(total_ref_count, keys_ref)
                if np.any(above_far):
                    _accumulate_count_and_sum(
                        counts=above_far_count,
                        sums=sum_dz_above_far,
                        keys=keys_ref[above_far],
                        vals=dz[above_far],
                    )
                if np.any(below_far):
                    _accumulate_count_and_sum(
                        counts=below_far_count,
                        sums=sum_dz_below_far,
                        keys=keys_ref[below_far],
                        vals=dz[below_far],
                    )

    candidate_high = _find_candidate_cells(
        far_count=above_far_count,
        total_ref_count=total_ref_count,
        suspect_far_ratio_gate=suspect_far_ratio_gate,
        suspect_min_far_points=suspect_min_far_points,
        min_total_points_per_cell=min_total_points_per_cell,
    )
    candidate_low = _find_candidate_cells(
        far_count=below_far_count,
        total_ref_count=total_ref_count,
        suspect_far_ratio_gate=suspect_far_ratio_gate,
        suspect_min_far_points=suspect_min_far_points,
        min_total_points_per_cell=min_total_points_per_cell,
    )

    kept_high_set, high_cluster_sizes, kept_high_cluster_count = _cluster_cells(candidate_high, min_cluster_cells)
    kept_low_set, low_cluster_sizes, kept_low_cluster_count = _cluster_cells(candidate_low, min_cluster_cells)

    kept_high_keys = np.asarray(sorted(kept_high_set), dtype=np.int64)
    kept_low_keys = np.asarray(sorted(kept_low_set), dtype=np.int64)

    mean_high = np.asarray(
        [
            float(sum_dz_above_far.get(int(k), 0.0) / max(1, above_far_count.get(int(k), 0)))
            for k in kept_high_keys.tolist()
        ],
        dtype=np.float64,
    )
    mean_low = np.asarray(
        [
            float(sum_dz_below_far.get(int(k), 0.0) / max(1, below_far_count.get(int(k), 0)))
            for k in kept_low_keys.tolist()
        ],
        dtype=np.float64,
    )

    report = {
        "candidate_high_count": int(len(candidate_high)),
        "candidate_low_count": int(len(candidate_low)),
        "kept_high_cluster_count": int(kept_high_cluster_count),
        "kept_low_cluster_count": int(kept_low_cluster_count),
        "kept_high_cell_count": int(kept_high_keys.size),
        "kept_low_cell_count": int(kept_low_keys.size),
        "cluster_size_topK": {
            "high": [int(x) for x in sorted(high_cluster_sizes, reverse=True)[:10]],
            "low": [int(x) for x in sorted(low_cluster_sizes, reverse=True)[:10]],
        },
        "reliable_ref_cell_count": int(np.count_nonzero(ref_surface.reliable_sorted)),
        "unreliable_ref_cell_count": int(ref_surface.reliable_sorted.size - np.count_nonzero(ref_surface.reliable_sorted)),
        "suspect_gate": {
            "suspect_far_ratio_gate": float(suspect_far_ratio_gate),
            "suspect_min_far_points": int(suspect_min_far_points),
            "min_total_points_per_cell": int(min_total_points_per_cell),
            "min_cluster_cells": int(min_cluster_cells),
            "detect_up_min_m": float(detect_up_min_m),
            "detect_up_extra_m": float(detect_up_extra_m),
            "detect_down_min_m": float(detect_down_min_m),
            "detect_down_extra_m": float(detect_down_extra_m),
        },
    }

    return OverlapModel(
        kept_high_keys_sorted=kept_high_keys,
        kept_low_keys_sorted=kept_low_keys,
        mean_high_sorted=mean_high,
        mean_low_sorted=mean_low,
        report=report,
    )


def _pass2_collect_ground_min(
    *,
    points_path: Path,
    chunk_points: int,
    ref_surface: RefSurface,
    overlap_model: OverlapModel,
    ground_grid_m: float,
    layer_band_m: float,
    ground_anchor_x0: float,
    ground_anchor_y0: float,
) -> tuple[dict[str, object], dict[int, float]]:
    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - env-dependent
        raise ValueError(f"laspy_required:{type(exc).__name__}:{exc}") from exc

    n_in = 0
    n_kept = 0
    removed_high = 0
    removed_low = 0
    ground_min_cell: dict[int, float] = {}

    with laspy.open(str(points_path)) as reader:
        for chunk in reader.chunk_iterator(int(chunk_points)):
            x = np.asarray(chunk.x, dtype=np.float64)
            y = np.asarray(chunk.y, dtype=np.float64)
            z = np.asarray(chunk.z, dtype=np.float64)
            n = int(x.size)
            n_in += n

            keep, del_high, del_low = _compute_keep_masks(
                x=x,
                y=y,
                z=z,
                ref_surface=ref_surface,
                overlap_model=overlap_model,
                layer_band_m=layer_band_m,
            )

            removed_high += int(np.count_nonzero(del_high))
            removed_low += int(np.count_nonzero(del_low))
            n_kept += int(np.count_nonzero(keep))

            valid_keep = keep & np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
            if np.any(valid_keep):
                xv = x[valid_keep]
                yv = y[valid_keep]
                zv = z[valid_keep]
                ix = np.floor((xv - ground_anchor_x0) / ground_grid_m).astype(np.int64)
                iy = np.floor((yv - ground_anchor_y0) / ground_grid_m).astype(np.int64)
                keys = _pack_cells(ix, iy)
                _accumulate_min(ground_min_cell, keys, zv)

    n_removed = int(max(0, n_in - n_kept))
    removed_ratio = float(n_removed / n_in) if n_in > 0 else 0.0
    stats = {
        "n_in": int(n_in),
        "n_kept": int(n_kept),
        "n_removed": int(n_removed),
        "removed_high": int(removed_high),
        "removed_low": int(removed_low),
        "removed_ratio": float(removed_ratio),
        "ground_min_cell_count": int(len(ground_min_cell)),
        "ground_grid_m": float(ground_grid_m),
        "layer_band_m": float(layer_band_m),
    }
    return stats, ground_min_cell


def _pass3_write_outputs(
    *,
    points_path: Path,
    out_cleaned_path: Path,
    out_full_path: Path | None,
    chunk_points: int,
    ref_surface: RefSurface,
    overlap_model: OverlapModel,
    ground_min_cell: dict[int, float],
    ground_grid_m: float,
    ground_above_margin_m: float,
    layer_band_m: float,
    ground_anchor_x0: float,
    ground_anchor_y0: float,
    verify: bool,
    expected_n_in: int,
    expected_n_kept: int,
    expected_n_removed: int,
    write_full_tagged: bool,
) -> dict[str, int]:
    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - env-dependent
        raise ValueError(f"laspy_required:{type(exc).__name__}:{exc}") from exc

    ground_keys_sorted = np.asarray(sorted(ground_min_cell.keys()), dtype=np.int64)
    ground_min_sorted = np.asarray([ground_min_cell[int(k)] for k in ground_keys_sorted.tolist()], dtype=np.float64)

    out_kept_count = 0
    out_full_count = 0
    class1_count = 0
    class2_count = 0
    class12_count = 0

    with laspy.open(str(points_path)) as reader:
        with laspy.open(str(out_cleaned_path), mode="w", header=reader.header) as w_clean:
            if write_full_tagged and out_full_path is not None:
                w_full_ctx = laspy.open(str(out_full_path), mode="w", header=reader.header)
            else:
                w_full_ctx = None

            try:
                if w_full_ctx is not None:
                    w_full = w_full_ctx.__enter__()
                else:
                    w_full = None

                for chunk in reader.chunk_iterator(int(chunk_points)):
                    x = np.asarray(chunk.x, dtype=np.float64)
                    y = np.asarray(chunk.y, dtype=np.float64)
                    z = np.asarray(chunk.z, dtype=np.float64)
                    n = int(x.size)

                    keep, _, _ = _compute_keep_masks(
                        x=x,
                        y=y,
                        z=z,
                        ref_surface=ref_surface,
                        overlap_model=overlap_model,
                        layer_band_m=layer_band_m,
                    )

                    idx_keep = np.flatnonzero(keep)
                    cls_keep = np.full((idx_keep.size,), NON_GROUND_CLASS, dtype=np.uint8)
                    if idx_keep.size > 0:
                        ground_keep = _classify_ground_mask(
                            x=np.asarray(x[idx_keep], dtype=np.float64),
                            y=np.asarray(y[idx_keep], dtype=np.float64),
                            z=np.asarray(z[idx_keep], dtype=np.float64),
                            x0=ground_anchor_x0,
                            y0=ground_anchor_y0,
                            grid_m=ground_grid_m,
                            ground_keys_sorted=ground_keys_sorted,
                            ground_min_sorted=ground_min_sorted,
                            above_margin_m=ground_above_margin_m,
                        )
                        cls_keep[ground_keep] = GROUND_CLASS

                    class2_count += int(np.count_nonzero(cls_keep == GROUND_CLASS))
                    class1_count += int(np.count_nonzero(cls_keep == NON_GROUND_CLASS))
                    out_kept_count += int(idx_keep.size)

                    if idx_keep.size > 0:
                        pts_keep = chunk[idx_keep]
                        pts_keep.classification = cls_keep
                        w_clean.write_points(pts_keep)

                    if w_full is not None:
                        cls_full = np.full((n,), OVERLAP_CLASS, dtype=np.uint8)
                        if idx_keep.size > 0:
                            cls_full[idx_keep] = cls_keep
                        chunk.classification = cls_full
                        w_full.write_points(chunk)
                        out_full_count += n
                        class12_count += int(np.count_nonzero(cls_full == OVERLAP_CLASS))
            finally:
                if w_full_ctx is not None:
                    w_full_ctx.__exit__(None, None, None)

    if not write_full_tagged:
        class12_count = int(expected_n_removed)
        out_full_count = int(expected_n_in)

    if verify:
        cleaned_count = _read_point_count(out_cleaned_path)
        if cleaned_count != expected_n_kept:
            raise ValueError(f"verify_cleaned_count_mismatch: expected={expected_n_kept} actual={cleaned_count}")
        _verify_cleaned_classes(path=out_cleaned_path, chunk_points=int(chunk_points))
        if write_full_tagged and out_full_path is not None:
            full_count = _read_point_count(out_full_path)
            if full_count != expected_n_in:
                raise ValueError(f"verify_full_count_mismatch: expected={expected_n_in} actual={full_count}")
        if class12_count != expected_n_removed:
            raise ValueError(f"verify_class12_mismatch: expected={expected_n_removed} actual={class12_count}")
        if out_kept_count != expected_n_kept:
            raise ValueError(f"verify_out_kept_mismatch: expected={expected_n_kept} actual={out_kept_count}")

    return {
        "out_kept_count": int(out_kept_count),
        "out_full_count": int(out_full_count),
        "class1_count": int(class1_count),
        "class2_count": int(class2_count),
        "class12_count": int(class12_count),
    }


def _compute_keep_masks(
    *,
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    ref_surface: RefSurface,
    overlap_model: OverlapModel,
    layer_band_m: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = int(x.size)
    keep = np.ones((n,), dtype=bool)
    del_high = np.zeros((n,), dtype=bool)
    del_low = np.zeros((n,), dtype=bool)

    if n <= 0 or ref_surface.keys_sorted.size == 0:
        return keep, del_high, del_low

    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    if not np.any(valid):
        return keep, del_high, del_low

    idx_valid = np.flatnonzero(valid)
    xv = x[valid]
    yv = y[valid]
    zv = z[valid]

    ix = np.floor((xv - ref_surface.x0) / ref_surface.ref_grid_m).astype(np.int64)
    iy = np.floor((yv - ref_surface.y0) / ref_surface.ref_grid_m).astype(np.int64)
    keys = _pack_cells(ix, iy)

    matched_ref, pos_ref = _lookup_match_positions(keys, ref_surface.keys_sorted)
    if not np.any(matched_ref):
        return keep, del_high, del_low

    matched_idx = np.flatnonzero(matched_ref)
    reliable_hit = ref_surface.reliable_sorted[pos_ref[matched_idx]]
    if not np.any(reliable_hit):
        return keep, del_high, del_low
    use_idx = matched_idx[reliable_hit]
    pos_use = pos_ref[use_idx]

    idx_ref = idx_valid[use_idx]
    keys_ref = keys[use_idx]
    z_ref = zv[use_idx]
    dz = z_ref - ref_surface.ref_z_sorted[pos_use]
    dz_up_keep = ref_surface.dz_up_keep_sorted[pos_use]
    dz_down_keep = ref_surface.dz_down_keep_sorted[pos_use]

    delete_any = np.zeros((n,), dtype=bool)

    if overlap_model.kept_high_keys_sorted.size > 0:
        matched_high, pos_high = _lookup_match_positions(keys_ref, overlap_model.kept_high_keys_sorted)
        if np.any(matched_high):
            idx_high = idx_ref[matched_high]
            dz_high = dz[matched_high]
            band_high = np.abs(dz_high - overlap_model.mean_high_sorted[pos_high[matched_high]])
            cond_high = (dz_high > dz_up_keep[matched_high]) & (band_high <= layer_band_m)
            if np.any(cond_high):
                idx_apply = idx_high[cond_high]
                del_high[idx_apply] = True
                delete_any[idx_apply] = True

    if overlap_model.kept_low_keys_sorted.size > 0:
        matched_low, pos_low = _lookup_match_positions(keys_ref, overlap_model.kept_low_keys_sorted)
        if np.any(matched_low):
            idx_low = idx_ref[matched_low]
            dz_low = dz[matched_low]
            band_low = np.abs(dz_low - overlap_model.mean_low_sorted[pos_low[matched_low]])
            cond_low = (dz_low < -dz_down_keep[matched_low]) & (band_low <= layer_band_m)
            if np.any(cond_low):
                idx_apply = idx_low[cond_low]
                idx_apply = idx_apply[~delete_any[idx_apply]]
                if idx_apply.size > 0:
                    del_low[idx_apply] = True
                    delete_any[idx_apply] = True

    keep = ~delete_any
    return keep, del_high, del_low


def _classify_ground_mask(
    *,
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    x0: float,
    y0: float,
    grid_m: float,
    ground_keys_sorted: np.ndarray,
    ground_min_sorted: np.ndarray,
    above_margin_m: float,
) -> np.ndarray:
    out = np.zeros((x.shape[0],), dtype=bool)
    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    if not np.any(valid) or ground_keys_sorted.size == 0:
        return out

    idx = np.flatnonzero(valid)
    xv = x[valid]
    yv = y[valid]
    zv = z[valid]

    ix = np.floor((xv - x0) / grid_m).astype(np.int64)
    iy = np.floor((yv - y0) / grid_m).astype(np.int64)
    keys = _pack_cells(ix, iy)
    matched, pos = _lookup_match_positions(keys, ground_keys_sorted)
    if np.any(matched):
        val_idx = idx[matched]
        zmin = ground_min_sorted[pos[matched]]
        out[val_idx] = zv[matched] <= (zmin + above_margin_m)
    return out


def _find_candidate_cells(
    *,
    far_count: dict[int, int],
    total_ref_count: dict[int, int],
    suspect_far_ratio_gate: float,
    suspect_min_far_points: int,
    min_total_points_per_cell: int,
) -> set[int]:
    out: set[int] = set()
    for key, n_far in far_count.items():
        total = int(total_ref_count.get(int(key), 0))
        if total < min_total_points_per_cell:
            continue
        if int(n_far) < suspect_min_far_points:
            continue
        ratio = float(n_far / total) if total > 0 else 0.0
        if ratio < suspect_far_ratio_gate:
            continue
        out.add(int(key))
    return out


def _cluster_cells(candidates: set[int], min_cluster_cells: int) -> tuple[set[int], list[int], int]:
    kept: set[int] = set()
    cluster_sizes: list[int] = []
    kept_cluster_count = 0
    if not candidates:
        return kept, cluster_sizes, kept_cluster_count

    visited: set[int] = set()
    for start in sorted(candidates):
        if start in visited:
            continue
        queue: deque[int] = deque([int(start)])
        visited.add(int(start))
        cluster: list[int] = []

        while queue:
            cur = queue.popleft()
            cluster.append(cur)
            cx, cy = _unpack_cell(cur)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nb = _pack_cell_scalar(cx + dx, cy + dy)
                    if nb in candidates and nb not in visited:
                        visited.add(nb)
                        queue.append(nb)

        csz = int(len(cluster))
        cluster_sizes.append(csz)
        if csz >= min_cluster_cells:
            kept.update(cluster)
            kept_cluster_count += 1

    return kept, cluster_sizes, kept_cluster_count


def _accumulate_count(counts: dict[int, int], keys: np.ndarray) -> None:
    if keys.size <= 0:
        return
    uniq, cnt = np.unique(keys, return_counts=True)
    for k, c in zip(uniq.tolist(), cnt.tolist()):
        key = int(k)
        counts[key] = int(counts.get(key, 0) + int(c))


def _accumulate_count_and_sum(
    *,
    counts: dict[int, int],
    sums: dict[int, float],
    keys: np.ndarray,
    vals: np.ndarray,
) -> None:
    if keys.size <= 0:
        return
    uniq, inv = np.unique(keys, return_inverse=True)
    cnt = np.bincount(inv)
    s = np.bincount(inv, weights=np.asarray(vals, dtype=np.float64))
    for i, k in enumerate(uniq.tolist()):
        key = int(k)
        counts[key] = int(counts.get(key, 0) + int(cnt[i]))
        sums[key] = float(sums.get(key, 0.0) + float(s[i]))


def _accumulate_min(cell_min: dict[int, float], keys: np.ndarray, vals: np.ndarray) -> None:
    if keys.size <= 0:
        return
    order = np.argsort(keys, kind="mergesort")
    k = keys[order]
    v = np.asarray(vals, dtype=np.float64)[order]
    if k.size <= 0:
        return
    change = np.empty(k.size, dtype=bool)
    change[0] = True
    change[1:] = k[1:] != k[:-1]
    starts = np.flatnonzero(change)
    mins = np.minimum.reduceat(v, starts)
    for i, s in enumerate(starts.tolist()):
        key = int(k[s])
        zmin = float(mins[i])
        cur = cell_min.get(key)
        if cur is None or zmin < cur:
            cell_min[key] = zmin


def _append_cell_samples(*, cell_z: dict[int, list[float]], key: int, zvals: np.ndarray, max_samples: int) -> None:
    z = np.asarray(zvals, dtype=np.float64)
    if z.size <= 0:
        return
    bucket = cell_z.get(int(key))
    if bucket is None:
        bucket = []
        cell_z[int(key)] = bucket
    bucket.extend(z.tolist())
    if len(bucket) > max_samples:
        stride = int(math.ceil(len(bucket) / max_samples))
        bucket[:] = bucket[::max(1, stride)][:max_samples]


def _estimate_spread(*, zvals: np.ndarray, median: float) -> tuple[float, str]:
    z = np.asarray(zvals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if z.size <= 0:
        return 0.1, "default"

    if z.size >= 3 and math.isfinite(median):
        mad = float(np.median(np.abs(z - float(median))))
        sig = 1.4826 * mad
        if math.isfinite(sig) and sig > 0:
            return float(sig), "mad"

        p10 = float(np.quantile(z, 0.10))
        p90 = float(np.quantile(z, 0.90))
        sig = 0.5 * (p90 - p10)
        if math.isfinite(sig) and sig > 0:
            return float(sig), "p90_p10"

        sig = float(np.std(z))
        if math.isfinite(sig) and sig > 0:
            return float(sig), "std"

    return 0.1, "default"


def _lookup_match_positions(query_keys: np.ndarray, sorted_keys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n_table = int(sorted_keys.size)
    n_query = int(query_keys.size)
    if n_table <= 0 or n_query <= 0:
        return np.zeros((n_query,), dtype=bool), np.zeros((n_query,), dtype=np.int64)

    pos = np.searchsorted(sorted_keys, query_keys)
    matched = pos < n_table
    if np.any(matched):
        idx = np.flatnonzero(matched)
        ok = sorted_keys[pos[idx]] == query_keys[idx]
        matched[idx] = ok
    return matched, pos.astype(np.int64)


def _pack_cells(ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
    ix64 = np.asarray(ix, dtype=np.int64)
    iy64 = np.asarray(iy, dtype=np.int64)
    return ((ix64 & np.int64(0xFFFFFFFF)) << np.int64(32)) | (iy64 & np.int64(0xFFFFFFFF))


def _pack_cell_scalar(ix: int, iy: int) -> int:
    ix_u = int(ix) & 0xFFFFFFFF
    iy_u = int(iy) & 0xFFFFFFFF
    return int((ix_u << 32) | iy_u)


def _unpack_cell(key: int) -> tuple[int, int]:
    ix = np.int32((int(key) >> 32) & 0xFFFFFFFF).item()
    iy = np.int32(int(key) & 0xFFFFFFFF).item()
    return int(ix), int(iy)


def _read_point_count(path: Path) -> int:
    import laspy  # type: ignore

    with laspy.open(str(path)) as reader:
        return int(reader.header.point_count)


def _verify_cleaned_classes(*, path: Path, chunk_points: int) -> None:
    import laspy  # type: ignore

    allowed = {GROUND_CLASS, NON_GROUND_CLASS}
    seen: set[int] = set()

    with laspy.open(str(path)) as reader:
        for chunk in reader.chunk_iterator(int(chunk_points)):
            cls = np.asarray(chunk.classification, dtype=np.uint8)
            if cls.size <= 0:
                continue
            uniq = np.unique(cls)
            for v in uniq.tolist():
                iv = int(v)
                if iv not in allowed:
                    raise ValueError(f"verify_cleaned_class_invalid: class={iv}")
                seen.add(iv)

    if not seen:
        return


def _resolve_existing_outputs(*, out_dir: Path, preferred_format: str, write_full_tagged: bool) -> dict[str, object] | None:
    cleaned_pref = out_dir / f"merged_cleaned_classified.{preferred_format}"
    cleaned_las = out_dir / "merged_cleaned_classified.las"
    full_pref = out_dir / f"merged_full_tagged.{preferred_format}" if write_full_tagged else None
    full_las = out_dir / "merged_full_tagged.las" if write_full_tagged else None

    cleaned: Path | None = None
    out_fmt = preferred_format
    if cleaned_pref.is_file():
        cleaned = cleaned_pref
        out_fmt = preferred_format
    elif preferred_format == "laz" and cleaned_las.is_file():
        cleaned = cleaned_las
        out_fmt = "las"
    if cleaned is None:
        return None

    full: Path | None = None
    if write_full_tagged:
        if full_pref is not None and full_pref.is_file():
            full = full_pref
            out_fmt = preferred_format
        elif preferred_format == "laz" and full_las is not None and full_las.is_file():
            full = full_las
            out_fmt = "las"
        if full is None:
            return None

    return {"cleaned": cleaned, "full": full, "format": out_fmt}


def _infer_patch_dir(*, root: Path, path: Path) -> Path:
    rel = path.relative_to(root)
    parts = rel.parts

    for i, part in enumerate(parts):
        if part.lower() == "pointcloud":
            return root.joinpath(*parts[:i]) if i >= 1 else root
        if part.lower() == "traj":
            return root.joinpath(*parts[:i]) if i >= 1 else root
    if len(parts) >= 2:
        return root / parts[0]
    return path.parent


def _build_patch_key(*, root: Path, patch_dir: Path, used_keys: set[str]) -> str:
    try:
        rel = patch_dir.relative_to(root)
    except Exception:
        rel = Path(patch_dir.name)

    by_name = _safe_key(patch_dir.name)
    by_rel = _safe_key(rel.as_posix().replace("/", "__"))
    key = by_name or by_rel or "patch"
    if key in used_keys:
        key = by_rel or key
    if key in used_keys:
        base = key
        idx = 2
        while f"{base}_{idx}" in used_keys:
            idx += 1
        key = f"{base}_{idx}"
    used_keys.add(key)
    return key


def _safe_key(s: str) -> str:
    t = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")
    return t


def _is_laz_backend_error(exc: Exception) -> bool:
    msg = f"{type(exc).__name__}: {exc}".lower()
    keys = ["lazrs", "laszip", "backend", "compress", "decompress", "laz"]
    return any(k in msg for k in keys)


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        return


def _series_stats(arr: np.ndarray) -> dict[str, float]:
    a = np.asarray(arr, dtype=np.float64)
    if a.size <= 0:
        return {"min": 0.0, "median": 0.0, "p90": 0.0, "max": 0.0}
    return {
        "min": float(np.min(a)),
        "median": float(np.median(a)),
        "p90": float(np.quantile(a, 0.90)),
        "max": float(np.max(a)),
    }


def _fail_row(
    *,
    patch: PatchInput,
    out_dir: Path,
    reason: str,
    points_path: Path | None = None,
) -> dict[str, object]:
    return {
        "patch_key": patch.patch_key,
        "patch_dir": str(patch.patch_dir),
        "points_path": str(points_path) if points_path is not None else (str(patch.points_path) if patch.points_path is not None else None),
        "traj_count": int(len(patch.traj_paths)),
        "out_cleaned_path": None,
        "out_full_tagged_path": None,
        "out_format": None,
        "n_in": 0,
        "n_kept": 0,
        "n_removed": 0,
        "removed_ratio": 0.0,
        "pass_fail": "fail",
        "overall_pass": False,
        "reason": reason,
        "output_dir": str(out_dir),
    }


def _as_bool(v: object, default: bool) -> bool:
    try:
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return _parse_bool(v)
        return bool(v)
    except Exception:
        return default


def _as_number(v: object, default: float) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _gen_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(_to_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(_to_json_safe(row), ensure_ascii=False, sort_keys=True) + "\n")


def _to_json_safe(v: object) -> object:
    if isinstance(v, dict):
        return {str(k): _to_json_safe(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_to_json_safe(x) for x in v]
    if isinstance(v, tuple):
        return [_to_json_safe(x) for x in v]
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.floating, float)):
        val = float(v)
        return val if math.isfinite(val) else None
    return v


def _parse_bool(s: str) -> bool:
    t = str(s).strip().lower()
    if t in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if t in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid_bool: {s}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="t02_ground_seg_qc.batch_multilayer_clean_and_classify")
    parser.add_argument("--data_root", default="data/synth_local")
    parser.add_argument("--out_root", default="outputs/_work/t02_ground_seg_qc")
    parser.add_argument("--run_id", default="auto")
    parser.add_argument("--resume", type=_parse_bool, default=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--chunk_points", type=int, default=2_000_000)
    parser.add_argument("--ref_grid_m", type=float, default=5.0)
    parser.add_argument("--ground_grid_m", type=float, default=1.0)
    parser.add_argument("--ground_above_margin_m", type=float, default=0.08)
    parser.add_argument("--layer_band_m", type=float, default=2.0)
    parser.add_argument("--suspect_far_ratio_gate", type=float, default=0.03)
    parser.add_argument("--suspect_min_far_points", type=int, default=2000)
    parser.add_argument("--min_total_points_per_cell", type=int, default=5000)
    parser.add_argument("--min_cluster_cells", type=int, default=200)
    parser.add_argument("--detect_up_min_m", type=float, default=6.0)
    parser.add_argument("--detect_up_extra_m", type=float, default=3.0)
    parser.add_argument("--detect_down_min_m", type=float, default=4.0)
    parser.add_argument("--detect_down_extra_m", type=float, default=2.0)
    parser.add_argument("--dz_up_base_m", type=float, default=2.0)
    parser.add_argument("--dz_up_k", type=float, default=3.0)
    parser.add_argument("--dz_up_max_m", type=float, default=8.0)
    parser.add_argument("--dz_down_base_m", type=float, default=0.8)
    parser.add_argument("--dz_down_k", type=float, default=2.0)
    parser.add_argument("--dz_down_min_m", type=float, default=0.3)
    parser.add_argument("--dz_down_max_m", type=float, default=1.0)
    parser.add_argument("--traj_spread_cap_m", type=float, default=1.5)
    parser.add_argument("--out_format", default="laz")
    parser.add_argument("--write_full_tagged", type=_parse_bool, default=True)
    parser.add_argument("--verify", type=_parse_bool, default=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = run_batch(
            data_root=args.data_root,
            out_root=args.out_root,
            run_id=args.run_id,
            resume=bool(args.resume),
            workers=int(args.workers),
            chunk_points=int(args.chunk_points),
            ref_grid_m=float(args.ref_grid_m),
            ground_grid_m=float(args.ground_grid_m),
            ground_above_margin_m=float(args.ground_above_margin_m),
            layer_band_m=float(args.layer_band_m),
            suspect_far_ratio_gate=float(args.suspect_far_ratio_gate),
            suspect_min_far_points=int(args.suspect_min_far_points),
            min_total_points_per_cell=int(args.min_total_points_per_cell),
            min_cluster_cells=int(args.min_cluster_cells),
            detect_up_min_m=float(args.detect_up_min_m),
            detect_up_extra_m=float(args.detect_up_extra_m),
            detect_down_min_m=float(args.detect_down_min_m),
            detect_down_extra_m=float(args.detect_down_extra_m),
            dz_up_base_m=float(args.dz_up_base_m),
            dz_up_k=float(args.dz_up_k),
            dz_up_max_m=float(args.dz_up_max_m),
            dz_down_base_m=float(args.dz_down_base_m),
            dz_down_k=float(args.dz_down_k),
            dz_down_min_m=float(args.dz_down_min_m),
            dz_down_max_m=float(args.dz_down_max_m),
            traj_spread_cap_m=float(args.traj_spread_cap_m),
            out_format=str(args.out_format),
            write_full_tagged=bool(args.write_full_tagged),
            verify=bool(args.verify),
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"RunID: {summary['run_id']}")
    print(f"MultiLayerRoot: {summary['multilayer_clean_root']}")
    print(f"Manifest: {summary['manifest_path']}")
    print(f"TotalPatches: {summary['total_patches']}")
    print(f"PassPatches: {summary['pass_patches']}")
    print(f"FailPatches: {summary['fail_patches']}")
    return 2 if int(summary.get("fail_patches", 0)) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
