from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from .corridor import build_corridor_cell_ids, pack_cells
from .crs_mercator import is_lonlat_bbox
from .export_3857 import (
    prepare_output_header_3857,
    read_point_count,
    transform_xy_to_3857_if_needed,
    transformed_xy_bounds_from_header,
    verify_output_bbox_is_3857,
)
from .overlap_cluster import cluster_cells_8n, detect_overlap_cells, keep_clusters_by_size
from .road_z_degraded import build_cell_z_peaks_from_pointcloud, choose_road_z_by_traj_direction
from .road_z_trajz import build_road_z_from_trajz
from .traj_io import collect_traj_bbox, iter_traj_points_geojson, load_traj_xy_3857, load_traj_xyz_3857
from .traj_z_mode import check_traj_z

POINT_EXTS = {".laz", ".las"}

GROUND_CLASS = 2
NON_GROUND_CLASS = 1
OVERLAP_CLASS = 12


@dataclass(frozen=True)
class PatchInput:
    patch_key: str
    patch_dir: Path
    points_path: Path | None
    traj_paths: list[Path]


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
    out_epsg: int = 3857,
    traj_z_mode: str = "auto",
    ground_band_m: float = 0.3,
    corridor_radius_m: float = 25.0,
    traj_step_m: float = 2.0,
    nonzero_ratio_gate: float = 0.01,
    z_std_gate: float = 0.05,
    z_check_sample_max_points: int = 1000,
    z_bin_m: float = 0.2,
    max_samples_per_cell: int = 512,
    overlap_sep_gate_m: float = 3.0,
    overlap_min_support_points: int = 60,
    overlap_min_support_ratio: float = 0.10,
    smooth_lambda: float = 0.5,
) -> dict[str, object]:
    if workers != 1:
        print(f"WARN: workers={workers} is currently executed sequentially (workers=1).", file=sys.stderr)
    if chunk_points < 1:
        raise ValueError("chunk_points must be >= 1")
    if ref_grid_m <= 0:
        raise ValueError("ref_grid_m must be > 0")
    if ground_band_m < 0:
        raise ValueError("ground_band_m must be >= 0")
    if layer_band_m <= 0:
        raise ValueError("layer_band_m must be > 0")
    if corridor_radius_m < 0:
        raise ValueError("corridor_radius_m must be >= 0")
    if out_epsg != 3857:
        raise ValueError("out_epsg must be 3857")

    traj_mode = str(traj_z_mode).strip().lower()
    if traj_mode not in {"auto", "force_traj_z", "force_degraded"}:
        raise ValueError("traj_z_mode must be one of: auto, force_traj_z, force_degraded")

    out_fmt = str(out_format).strip().lower()
    if out_fmt not in {"laz", "las"}:
        raise ValueError("out_format must be one of: laz, las")

    patches = discover_patches(data_root)
    if not patches:
        raise ValueError(f"no_patch_found_under: {Path(data_root)}")

    run_id_val = _gen_run_id() if str(run_id) == "auto" else str(run_id)
    run_root = Path(out_root) / run_id_val
    multilayer_root = run_root / "multilayer_clean"
    multilayer_root.mkdir(parents=True, exist_ok=True)

    params = {
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
        "out_format": out_fmt,
        "write_full_tagged": bool(write_full_tagged),
        "verify": bool(verify),
        "out_epsg": int(out_epsg),
        "traj_z_mode": traj_mode,
        "ground_band_m": float(ground_band_m),
        "corridor_radius_m": float(corridor_radius_m),
        "traj_step_m": float(traj_step_m),
        "nonzero_ratio_gate": float(nonzero_ratio_gate),
        "z_std_gate": float(z_std_gate),
        "z_check_sample_max_points": int(z_check_sample_max_points),
        "z_bin_m": float(z_bin_m),
        "max_samples_per_cell": int(max_samples_per_cell),
        "overlap_sep_gate_m": float(overlap_sep_gate_m),
        "overlap_min_support_points": int(overlap_min_support_points),
        "overlap_min_support_ratio": float(overlap_min_support_ratio),
        "smooth_lambda": float(smooth_lambda),
    }

    rows: list[dict[str, object]] = []
    failed_rows: list[dict[str, object]] = []
    laz_fallback_count = 0

    for patch in patches:
        row = _process_patch(patch=patch, multilayer_root=multilayer_root, params=params)
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
        "params": params,
    }
    _write_json(run_root / "multilayer_summary.json", summary)
    return summary


def _process_patch(*, patch: PatchInput, multilayer_root: Path, params: dict[str, object]) -> dict[str, object]:
    out_dir = multilayer_root / patch.patch_key
    out_dir.mkdir(parents=True, exist_ok=True)

    preferred_fmt = str(params["out_format"])
    write_full_tagged = bool(params["write_full_tagged"])
    resume = bool(params["resume"])

    preferred_clean = out_dir / f"merged_cleaned_classified_3857.{preferred_fmt}"
    preferred_full = out_dir / f"merged_full_tagged_3857.{preferred_fmt}"
    fallback_clean = out_dir / "merged_cleaned_classified_3857.las"
    fallback_full = out_dir / "merged_full_tagged_3857.las"

    stats_path = out_dir / "patch_stats.json"
    if resume and stats_path.is_file() and preferred_clean.is_file() and (preferred_full.is_file() or not write_full_tagged):
        try:
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
            return {
                "patch_key": patch.patch_key,
                "patch_dir": str(patch.patch_dir),
                "points_path": str(patch.points_path) if patch.points_path is not None else None,
                "traj_count": int(len(patch.traj_paths)),
                "out_cleaned_path": str(stats.get("out_cleaned_path", preferred_clean)),
                "out_full_tagged_path": str(stats.get("out_full_tagged_path", preferred_full)) if write_full_tagged else None,
                "out_format": str(stats.get("out_format", preferred_fmt)),
                "n_in": int(_as_num(stats.get("n_in"), 0)),
                "n_kept": int(_as_num(stats.get("n_kept"), 0)),
                "n_removed": int(_as_num(stats.get("n_removed"), 0)),
                "removed_ratio": float(_as_num(stats.get("removed_ratio"), 0.0)),
                "pass_fail": "pass" if bool(stats.get("overall_pass", True)) else "fail",
                "overall_pass": bool(stats.get("overall_pass", True)),
                "reason": "resume_skip",
                "output_dir": str(out_dir),
            }
        except Exception:
            pass

    if patch.points_path is None:
        return _fail_row(patch=patch, out_dir=out_dir, reason="points_not_found")
    points_path = patch.points_path
    if not points_path.is_file():
        return _fail_row(patch=patch, out_dir=out_dir, reason=f"points_not_found:{points_path}")

    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - env-dependent
        return _fail_row(patch=patch, out_dir=out_dir, reason=f"laspy_required:{type(exc).__name__}:{exc}")

    try:
        with laspy.open(str(points_path)) as reader:
            header = reader.header
            n_in = int(header.point_count)
            dim_names = set(header.point_format.dimension_names)
            if "classification" not in dim_names:
                return _fail_row(patch=patch, out_dir=out_dir, reason="classification_dimension_missing")
            point_bbox = {
                "min_x": float(np.asarray(header.mins, dtype=np.float64)[0]),
                "max_x": float(np.asarray(header.maxs, dtype=np.float64)[0]),
                "min_y": float(np.asarray(header.mins, dtype=np.float64)[1]),
                "max_y": float(np.asarray(header.maxs, dtype=np.float64)[1]),
            }
    except Exception as exc:
        return _fail_row(patch=patch, out_dir=out_dir, reason=f"points_read_error:{type(exc).__name__}:{exc}")

    traj_paths = sorted([Path(x) for x in patch.traj_paths], key=lambda x: x.as_posix())
    traj_bbox = collect_traj_bbox(traj_paths, sample_max_points=int(params["z_check_sample_max_points"])) if traj_paths else {
        "point_count": 0,
        "min_x": 0.0,
        "max_x": 0.0,
        "min_y": 0.0,
        "max_y": 0.0,
        "lonlat_like": False,
    }

    point_lonlat = bool(
        is_lonlat_bbox(
            min_x=float(point_bbox["min_x"]),
            max_x=float(point_bbox["max_x"]),
            min_y=float(point_bbox["min_y"]),
            max_y=float(point_bbox["max_y"]),
        )
    )
    traj_lonlat = bool(traj_bbox.get("lonlat_like", False))
    lonlat_detect = bool(point_lonlat or traj_lonlat)

    with laspy.open(str(points_path)) as reader_for_bounds:
        minx3857, maxx3857, miny3857, maxy3857 = transformed_xy_bounds_from_header(
            reader_for_bounds.header,
            input_lonlat=point_lonlat,
        )
    x0 = float(minx3857)
    y0 = float(miny3857)

    zcheck = check_traj_z(
        traj_paths,
        nonzero_ratio_gate=float(params["nonzero_ratio_gate"]),
        z_std_gate=float(params["z_std_gate"]),
        sample_max_points_per_file=int(params["z_check_sample_max_points"]),
    )
    forced_mode = str(params["traj_z_mode"])
    if forced_mode == "force_traj_z":
        traj_z_mode_used = "traj_z"
    elif forced_mode == "force_degraded":
        traj_z_mode_used = "degraded"
    else:
        traj_z_mode_used = "degraded" if bool(zcheck.get("is_degraded", True)) else "traj_z"

    trajs_xy = load_traj_xy_3857(
        traj_paths,
        step_m=float(params["traj_step_m"]),
        sample_for_zcheck=int(params["z_check_sample_max_points"]),
        assume_lonlat=traj_lonlat,
    )
    trajs_xyz = load_traj_xyz_3857(
        traj_paths,
        step_m=float(params["traj_step_m"]),
        assume_lonlat=traj_lonlat,
    )

    corridor_ids = build_corridor_cell_ids(
        trajs_xy,
        ref_grid_m=float(params["ref_grid_m"]),
        corridor_radius_m=float(params["corridor_radius_m"]),
        x0=x0,
        y0=y0,
    )

    road_z: dict[int, float] = {}
    road_spread: dict[int, float] = {}
    road_variation_report: dict[str, object] = {}
    corridor_fallback_all_cells = False

    cell_peaks: dict[int, dict[str, float | int]] = {}
    if corridor_ids.size > 0:
        if traj_z_mode_used == "traj_z":
            road_z, road_spread = build_road_z_from_trajz(
                trajs_xyz,
                ref_grid_m=float(params["ref_grid_m"]),
                x0=x0,
                y0=y0,
                max_samples_per_cell=2048,
            )
            road_variation_report = _build_variation_report_from_roadz(
                road_z=road_z,
                trajs_xy=trajs_xy,
                ref_grid_m=float(params["ref_grid_m"]),
                x0=x0,
                y0=y0,
                source="traj_z",
                extra={"spread_stats": _series_stats(np.asarray(list(road_spread.values()), dtype=np.float64))},
            )
        cell_peaks = build_cell_z_peaks_from_pointcloud(
            points_path=points_path,
            corridor_ids=corridor_ids,
            ref_grid_m=float(params["ref_grid_m"]),
            z_bin_m=float(params["z_bin_m"]),
            max_samples_per_cell=int(params["max_samples_per_cell"]),
            chunk_points=int(params["chunk_points"]),
            x0=x0,
            y0=y0,
            input_lonlat=point_lonlat,
        )
        if traj_z_mode_used == "degraded":
            road_z, road_variation_report = choose_road_z_by_traj_direction(
                trajs_xy,
                cell_peaks,
                ref_grid_m=float(params["ref_grid_m"]),
                x0=x0,
                y0=y0,
                smooth_lambda=float(params["smooth_lambda"]),
            )
        if not road_z:
            # fall back to peak0 to avoid empty road surface
            for key, info in cell_peaks.items():
                road_z[int(key)] = float(info.get("peak0", 0.0))

    if corridor_ids.size > 0 and len(cell_peaks) == 0 and point_lonlat != traj_lonlat:
        corridor_fallback_all_cells = True
        corridor_ids = _collect_point_cells(
            points_path=points_path,
            ref_grid_m=float(params["ref_grid_m"]),
            x0=x0,
            y0=y0,
            chunk_points=int(params["chunk_points"]),
            input_lonlat=point_lonlat,
        )
        cell_peaks = build_cell_z_peaks_from_pointcloud(
            points_path=points_path,
            corridor_ids=corridor_ids,
            ref_grid_m=float(params["ref_grid_m"]),
            z_bin_m=float(params["z_bin_m"]),
            max_samples_per_cell=int(params["max_samples_per_cell"]),
            chunk_points=int(params["chunk_points"]),
            x0=x0,
            y0=y0,
            input_lonlat=point_lonlat,
        )
        traj_z_mode_used = "degraded"
        road_z, road_variation_report = choose_road_z_by_traj_direction(
            trajs_xy,
            cell_peaks,
            ref_grid_m=float(params["ref_grid_m"]),
            x0=x0,
            y0=y0,
            smooth_lambda=float(params["smooth_lambda"]),
        )
        if not road_z:
            for key, info in cell_peaks.items():
                road_z[int(key)] = float(info.get("peak0", 0.0))

    road_surface_rows = _build_road_surface_rows(
        road_z=road_z,
        cell_peaks=cell_peaks,
        x0=x0,
        y0=y0,
        ref_grid_m=float(params["ref_grid_m"]),
    )
    road_surface_path = out_dir / "road_z_surface.csv"
    _write_road_surface_csv(road_surface_path, road_surface_rows)

    if not road_variation_report:
        road_variation_report = _build_variation_report_from_roadz(
            road_z=road_z,
            trajs_xy=trajs_xy,
            ref_grid_m=float(params["ref_grid_m"]),
            x0=x0,
            y0=y0,
            source="degraded",
            extra={},
        )
    road_variation_report["traj_z_mode_used"] = traj_z_mode_used
    road_variation_report["traj_z_check"] = zcheck
    _write_json(out_dir / "road_z_variation_report.json", road_variation_report)

    cand_high, cand_low, detect_report = detect_overlap_cells(
        cell_peaks,
        road_z,
        sep_gate_m=float(params["overlap_sep_gate_m"]),
        min_support_points=int(params["overlap_min_support_points"]),
        min_support_ratio=float(params["overlap_min_support_ratio"]),
        min_total_points_per_cell=int(params["min_total_points_per_cell"]),
    )
    density_scale = float(_as_num(detect_report.get("density_scale"), 1.0))
    min_cluster_adapt = max(1, int(round(float(params["min_cluster_cells"]) * max(0.5, min(2.0, density_scale)))))

    high_clusters = cluster_cells_8n(cand_high)
    low_clusters = cluster_cells_8n(cand_low)
    kept_high, high_sizes = keep_clusters_by_size(high_clusters, min_cluster_cells=min_cluster_adapt)
    kept_low, low_sizes = keep_clusters_by_size(low_clusters, min_cluster_cells=min_cluster_adapt)

    overlap_report = {
        **detect_report,
        "min_cluster_cells_adaptive": int(min_cluster_adapt),
        "kept_high_cell_count": int(len(kept_high)),
        "kept_low_cell_count": int(len(kept_low)),
        "kept_high_cluster_count": int(sum(1 for c in high_clusters if len(c) >= min_cluster_adapt)),
        "kept_low_cluster_count": int(sum(1 for c in low_clusters if len(c) >= min_cluster_adapt)),
        "cluster_size_topK": {
            "high": [int(x) for x in sorted(high_sizes, reverse=True)[:10]],
            "low": [int(x) for x in sorted(low_sizes, reverse=True)[:10]],
        },
    }
    _write_json(out_dir / "overlap_cells_report.json", overlap_report)

    high_layer_z, low_layer_z = _build_interference_layer_maps(
        road_z=road_z,
        cell_peaks=cell_peaks,
        kept_high=kept_high,
        kept_low=kept_low,
    )

    ref_surface_stats = {
        "points_path": str(points_path),
        "traj_count": int(len(traj_paths)),
        "traj_pts": int(_as_num(traj_bbox.get("point_count"), 0)),
        "traj_bbox": traj_bbox,
        "point_bbox": point_bbox,
        "lonlat_detect": bool(lonlat_detect),
        "point_lonlat_detect": bool(point_lonlat),
        "traj_lonlat_detect": bool(traj_lonlat),
        "corridor_fallback_all_cells": bool(corridor_fallback_all_cells),
        "ref_grid_m": float(params["ref_grid_m"]),
        "corridor_radius_m": float(params["corridor_radius_m"]),
        "corridor_cells_count": int(corridor_ids.size),
        "ref_cell_count": int(len(road_z)),
        "road_z_cells_count": int(len(road_z)),
        "coverage": float(len(road_z) / corridor_ids.size) if corridor_ids.size > 0 else 0.0,
        "coverage_est": float(len(road_z) / corridor_ids.size) if corridor_ids.size > 0 else 0.0,
        "road_spread_stats": _series_stats(np.asarray(list(road_spread.values()), dtype=np.float64)),
        "cell_peaks_count": int(len(cell_peaks)),
    }
    _write_json(out_dir / "ref_surface_stats.json", ref_surface_stats)

    reason = "ok"
    actual_fmt = preferred_fmt
    out_clean = preferred_clean
    out_full = preferred_full

    try:
        write_stats = _write_outputs(
            points_path=points_path,
            out_clean_path=out_clean,
            out_full_path=out_full,
            write_full_tagged=write_full_tagged,
            out_epsg=int(params["out_epsg"]),
            input_lonlat=point_lonlat,
            chunk_points=int(params["chunk_points"]),
            ref_grid_m=float(params["ref_grid_m"]),
            x0=x0,
            y0=y0,
            corridor_ids=corridor_ids,
            road_z=road_z,
            high_layer_z=high_layer_z,
            low_layer_z=low_layer_z,
            layer_band_m=float(params["layer_band_m"]),
            ground_band_m=float(params["ground_band_m"]),
            verify=bool(params["verify"]),
        )
    except Exception as exc:
        if preferred_fmt == "laz" and _is_laz_backend_error(exc):
            reason = f"fallback_laz_to_las:{type(exc).__name__}"
            actual_fmt = "las"
            out_clean = fallback_clean
            out_full = fallback_full
            _safe_unlink(preferred_clean)
            _safe_unlink(preferred_full)
            try:
                write_stats = _write_outputs(
                    points_path=points_path,
                    out_clean_path=out_clean,
                    out_full_path=out_full,
                    write_full_tagged=write_full_tagged,
                    out_epsg=int(params["out_epsg"]),
                    input_lonlat=point_lonlat,
                    chunk_points=int(params["chunk_points"]),
                    ref_grid_m=float(params["ref_grid_m"]),
                    x0=x0,
                    y0=y0,
                    corridor_ids=corridor_ids,
                    road_z=road_z,
                    high_layer_z=high_layer_z,
                    low_layer_z=low_layer_z,
                    layer_band_m=float(params["layer_band_m"]),
                    ground_band_m=float(params["ground_band_m"]),
                    verify=bool(params["verify"]),
                )
            except Exception as exc2:
                return _fail_row(patch=patch, out_dir=out_dir, reason=f"write_fallback_error:{type(exc2).__name__}:{exc2}")
        else:
            return _fail_row(patch=patch, out_dir=out_dir, reason=f"write_error:{type(exc).__name__}:{exc}")

    patch_stats = {
        "patch_key": patch.patch_key,
        "patch_dir": str(patch.patch_dir),
        "points_path": str(points_path),
        "traj_count": int(len(traj_paths)),
        "traj_paths": [str(p) for p in traj_paths],
        "traj_z_mode_used": str(traj_z_mode_used),
        "traj_z_check": zcheck,
        "lonlat_detect": bool(lonlat_detect),
        "point_lonlat_detect": bool(point_lonlat),
        "traj_lonlat_detect": bool(traj_lonlat),
        "corridor_fallback_all_cells": bool(corridor_fallback_all_cells),
        "corridor_cells_count": int(corridor_ids.size),
        "road_z_cells_count": int(len(road_z)),
        "n_in": int(write_stats["n_in"]),
        "n_kept": int(write_stats["n_kept"]),
        "n_removed": int(write_stats["n_removed"]),
        "removed_high": int(write_stats["removed_high"]),
        "removed_low": int(write_stats["removed_low"]),
        "removed_ratio": float(write_stats["removed_ratio"]),
        "class1_count": int(write_stats["class1_count"]),
        "class2_count": int(write_stats["class2_count"]),
        "class12_count": int(write_stats["class12_count"]),
        "ground_count": int(write_stats["class2_count"]),
        "out_format": str(actual_fmt),
        "out_epsg": int(params["out_epsg"]),
        "out_cleaned_path": str(out_clean),
        "out_full_tagged_path": str(out_full) if write_full_tagged else None,
        "road_z_surface_path": str(road_surface_path),
        "road_z_variation_report_path": str(out_dir / "road_z_variation_report.json"),
        "ref_surface_stats_path": str(out_dir / "ref_surface_stats.json"),
        "overlap_cluster_stats": overlap_report,
        "verify": bool(params["verify"]),
        "overall_pass": True,
        "reason": reason,
        "params": {
            "ref_grid_m": float(params["ref_grid_m"]),
            "corridor_radius_m": float(params["corridor_radius_m"]),
            "ground_band_m": float(params["ground_band_m"]),
            "layer_band_m": float(params["layer_band_m"]),
            "min_cluster_cells": int(params["min_cluster_cells"]),
            "min_total_points_per_cell": int(params["min_total_points_per_cell"]),
            "overlap_sep_gate_m": float(params["overlap_sep_gate_m"]),
            "overlap_min_support_points": int(params["overlap_min_support_points"]),
            "overlap_min_support_ratio": float(params["overlap_min_support_ratio"]),
            "traj_z_mode": str(params["traj_z_mode"]),
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
        "traj_count": int(len(traj_paths)),
        "out_cleaned_path": str(out_clean),
        "out_full_tagged_path": str(out_full) if write_full_tagged else None,
        "out_format": str(actual_fmt),
        "n_in": int(write_stats["n_in"]),
        "n_kept": int(write_stats["n_kept"]),
        "n_removed": int(write_stats["n_removed"]),
        "removed_ratio": float(write_stats["removed_ratio"]),
        "pass_fail": "pass",
        "overall_pass": True,
        "reason": reason,
        "output_dir": str(out_dir),
        "traj_z_mode_used": str(traj_z_mode_used),
        "lonlat_detect": bool(lonlat_detect),
    }


def _write_outputs(
    *,
    points_path: Path,
    out_clean_path: Path,
    out_full_path: Path,
    write_full_tagged: bool,
    out_epsg: int,
    input_lonlat: bool,
    chunk_points: int,
    ref_grid_m: float,
    x0: float,
    y0: float,
    corridor_ids: np.ndarray,
    road_z: dict[int, float],
    high_layer_z: dict[int, float],
    low_layer_z: dict[int, float],
    layer_band_m: float,
    ground_band_m: float,
    verify: bool,
) -> dict[str, int | float]:
    del out_epsg
    import laspy  # type: ignore

    corridor_sorted = np.asarray(np.unique(np.asarray(corridor_ids, dtype=np.int64)), dtype=np.int64)
    road_keys = np.asarray(sorted(road_z.keys()), dtype=np.int64)
    road_vals = np.asarray([road_z[int(k)] for k in road_keys.tolist()], dtype=np.float64)
    high_keys = np.asarray(sorted(high_layer_z.keys()), dtype=np.int64)
    high_vals = np.asarray([high_layer_z[int(k)] for k in high_keys.tolist()], dtype=np.float64)
    low_keys = np.asarray(sorted(low_layer_z.keys()), dtype=np.int64)
    low_vals = np.asarray([low_layer_z[int(k)] for k in low_keys.tolist()], dtype=np.float64)

    n_in = 0
    n_kept = 0
    n_removed = 0
    removed_high = 0
    removed_low = 0
    class1_count = 0
    class2_count = 0
    class12_count = 0
    cleaned_classes_seen: set[int] = set()

    with laspy.open(str(points_path)) as reader:
        out_header = prepare_output_header_3857(reader.header, input_lonlat=input_lonlat)
        with laspy.open(str(out_clean_path), mode="w", header=out_header) as w_clean:
            w_full_ctx = laspy.open(str(out_full_path), mode="w", header=out_header) if write_full_tagged else None
            try:
                w_full = w_full_ctx.__enter__() if w_full_ctx is not None else None
                for chunk in reader.chunk_iterator(int(chunk_points)):
                    x_raw = np.asarray(chunk.x, dtype=np.float64)
                    y_raw = np.asarray(chunk.y, dtype=np.float64)
                    z = np.asarray(chunk.z, dtype=np.float64)
                    x, y = transform_xy_to_3857_if_needed(x_raw, y_raw, input_lonlat=input_lonlat)
                    if input_lonlat:
                        chunk.change_scaling(scales=out_header.scales, offsets=out_header.offsets)
                        chunk.x = np.asarray(x, dtype=np.float64)
                        chunk.y = np.asarray(y, dtype=np.float64)

                    n = int(x.shape[0])
                    n_in += n
                    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)

                    cls_base = np.full((n,), NON_GROUND_CLASS, dtype=np.uint8)
                    remove = np.zeros((n,), dtype=bool)
                    remove_h = np.zeros((n,), dtype=bool)
                    remove_l = np.zeros((n,), dtype=bool)

                    if np.any(valid):
                        idx = np.flatnonzero(valid)
                        xv = x[valid]
                        yv = y[valid]
                        zv = z[valid]

                        ix = np.floor((xv - float(x0)) / float(ref_grid_m)).astype(np.int64)
                        iy = np.floor((yv - float(y0)) / float(ref_grid_m)).astype(np.int64)
                        keys = pack_cells(ix, iy)

                        in_corridor, _ = _lookup_match(keys, corridor_sorted)
                        has_road, pos_road = _lookup_match(keys, road_keys)

                        if np.any(in_corridor & has_road):
                            use = in_corridor & has_road
                            idx_use = idx[use]
                            road_here = road_vals[pos_road[use]]
                            dz = np.abs(zv[use] - road_here)
                            ground_mask = dz <= float(ground_band_m)
                            if np.any(ground_mask):
                                cls_base[idx_use[ground_mask]] = GROUND_CLASS

                        # overlap remove only in corridor and road-covered cells
                        if np.any(in_corridor & has_road):
                            use = in_corridor & has_road
                            idx_use = idx[use]
                            keys_use = keys[use]
                            z_use = zv[use]
                            road_use = road_vals[pos_road[use]]

                            if high_keys.size > 0:
                                mh, ph = _lookup_match(keys_use, high_keys)
                                if np.any(mh):
                                    inter_h = high_vals[ph[mh]]
                                    cond_h = (
                                        np.abs(z_use[mh] - inter_h) <= float(layer_band_m)
                                    ) & (z_use[mh] > (road_use[mh] + float(ground_band_m)))
                                    if np.any(cond_h):
                                        idx_h = idx_use[mh][cond_h]
                                        remove[idx_h] = True
                                        remove_h[idx_h] = True

                            if low_keys.size > 0:
                                ml, pl = _lookup_match(keys_use, low_keys)
                                if np.any(ml):
                                    inter_l = low_vals[pl[ml]]
                                    cond_l = (
                                        np.abs(z_use[ml] - inter_l) <= float(layer_band_m)
                                    ) & (z_use[ml] < (road_use[ml] - float(ground_band_m)))
                                    if np.any(cond_l):
                                        idx_l = idx_use[ml][cond_l]
                                        idx_l = idx_l[~remove[idx_l]]
                                        if idx_l.size > 0:
                                            remove[idx_l] = True
                                            remove_l[idx_l] = True

                    keep = ~remove
                    idx_keep = np.flatnonzero(keep)
                    n_kept += int(idx_keep.size)
                    n_removed += int(np.count_nonzero(remove))
                    removed_high += int(np.count_nonzero(remove_h))
                    removed_low += int(np.count_nonzero(remove_l))

                    cls_keep = cls_base[idx_keep]
                    class1_count += int(np.count_nonzero(cls_keep == NON_GROUND_CLASS))
                    class2_count += int(np.count_nonzero(cls_keep == GROUND_CLASS))
                    for c in np.unique(cls_keep).tolist():
                        cleaned_classes_seen.add(int(c))

                    if idx_keep.size > 0:
                        pts_keep = chunk[idx_keep]
                        pts_keep.classification = cls_keep
                        w_clean.write_points(pts_keep)

                    if w_full is not None:
                        cls_full = np.asarray(cls_base, dtype=np.uint8)
                        cls_full[remove] = OVERLAP_CLASS
                        class12_count += int(np.count_nonzero(cls_full == OVERLAP_CLASS))
                        chunk.classification = cls_full
                        w_full.write_points(chunk)
            finally:
                if w_full_ctx is not None:
                    w_full_ctx.__exit__(None, None, None)

    if not write_full_tagged:
        class12_count = int(n_removed)

    removed_ratio = float(n_removed / n_in) if n_in > 0 else 0.0

    if verify:
        clean_count = read_point_count(out_clean_path)
        if clean_count != n_kept:
            raise ValueError(f"verify_cleaned_count_mismatch: expected={n_kept} actual={clean_count}")
        if write_full_tagged:
            full_count = read_point_count(out_full_path)
            if full_count != n_in:
                raise ValueError(f"verify_full_count_mismatch: expected={n_in} actual={full_count}")
        if class12_count != n_removed:
            raise ValueError(f"verify_class12_mismatch: expected={n_removed} actual={class12_count}")
        if not cleaned_classes_seen.issubset({NON_GROUND_CLASS, GROUND_CLASS}):
            raise ValueError(f"verify_cleaned_classes_invalid: {sorted(cleaned_classes_seen)}")
        verify_output_bbox_is_3857(out_clean_path)
        if write_full_tagged:
            verify_output_bbox_is_3857(out_full_path)

    return {
        "n_in": int(n_in),
        "n_kept": int(n_kept),
        "n_removed": int(n_removed),
        "removed_high": int(removed_high),
        "removed_low": int(removed_low),
        "removed_ratio": float(removed_ratio),
        "class1_count": int(class1_count),
        "class2_count": int(class2_count),
        "class12_count": int(class12_count),
    }


def _lookup_match(query_keys: np.ndarray, sorted_keys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
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


def _build_interference_layer_maps(
    *,
    road_z: dict[int, float],
    cell_peaks: dict[int, dict[str, float | int]],
    kept_high: set[int],
    kept_low: set[int],
) -> tuple[dict[int, float], dict[int, float]]:
    high: dict[int, float] = {}
    low: dict[int, float] = {}
    for key, rz in road_z.items():
        info = cell_peaks.get(int(key))
        if info is None:
            continue
        peak0 = float(info.get("peak0", np.nan))
        peak1 = float(info.get("peak1", np.nan))
        support0 = int(info.get("support0", 0))
        support1 = int(info.get("support1", 0))
        if not math.isfinite(peak0):
            continue
        if support1 <= 0 or not math.isfinite(peak1):
            continue
        d0 = abs(peak0 - float(rz))
        d1 = abs(peak1 - float(rz))
        if d0 <= d1:
            inter_peak = float(peak1)
        else:
            inter_peak = float(peak0)
        if int(key) in kept_high and inter_peak > float(rz):
            high[int(key)] = inter_peak
        if int(key) in kept_low and inter_peak < float(rz):
            low[int(key)] = inter_peak
    return high, low


def _build_road_surface_rows(
    *,
    road_z: dict[int, float],
    cell_peaks: dict[int, dict[str, float | int]],
    x0: float,
    y0: float,
    ref_grid_m: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for key in sorted(road_z.keys()):
        cx, cy = _unpack_cell(int(key))
        center_x = float(x0 + (cx + 0.5) * ref_grid_m)
        center_y = float(y0 + (cy + 0.5) * ref_grid_m)
        info = cell_peaks.get(int(key), {})
        rows.append(
            {
                "cell_id": int(key),
                "cell_x": int(cx),
                "cell_y": int(cy),
                "center_x": float(center_x),
                "center_y": float(center_y),
                "road_z": float(road_z[int(key)]),
                "peak0": float(info.get("peak0", np.nan)),
                "peak1": float(info.get("peak1", np.nan)),
                "support0": int(info.get("support0", 0)),
                "support1": int(info.get("support1", 0)),
                "peak_sep": float(info.get("peak_sep", 0.0)),
                "total_points": int(info.get("total_points", 0)),
            }
        )
    return rows


def _write_road_surface_csv(path: Path, rows: list[dict[str, object]]) -> None:
    cols = [
        "cell_id",
        "cell_x",
        "cell_y",
        "center_x",
        "center_y",
        "road_z",
        "peak0",
        "peak1",
        "support0",
        "support1",
        "peak_sep",
        "total_points",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in cols})


def _build_variation_report_from_roadz(
    *,
    road_z: dict[int, float],
    trajs_xy: list[np.ndarray],
    ref_grid_m: float,
    x0: float,
    y0: float,
    source: str,
    extra: dict[str, object],
) -> dict[str, object]:
    per_traj: list[dict[str, object]] = []
    all_dz: list[float] = []
    road_keys = set(int(k) for k in road_z.keys())

    for ti, traj in enumerate(trajs_xy):
        arr = np.asarray(traj, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] < 2 or arr.shape[0] <= 0:
            continue
        x = np.asarray(arr[:, 0], dtype=np.float64)
        y = np.asarray(arr[:, 1], dtype=np.float64)
        valid = np.isfinite(x) & np.isfinite(y)
        if not np.any(valid):
            continue
        x = x[valid]
        y = y[valid]
        ix = np.floor((x - float(x0)) / float(ref_grid_m)).astype(np.int64)
        iy = np.floor((y - float(y0)) / float(ref_grid_m)).astype(np.int64)
        keys = pack_cells(ix, iy)
        seq: list[int] = []
        last = None
        for k in keys.tolist():
            kk = int(k)
            if kk in road_keys and (last is None or kk != last):
                seq.append(kk)
                last = kk
        if len(seq) <= 0:
            continue
        z_seq = np.asarray([road_z[int(k)] for k in seq], dtype=np.float64)
        if z_seq.size >= 2:
            dz = np.abs(np.diff(z_seq))
            all_dz.extend(dz.tolist())
            p50 = float(np.quantile(dz, 0.50))
            p90 = float(np.quantile(dz, 0.90))
            p99 = float(np.quantile(dz, 0.99))
            mmax = float(np.max(dz))
        else:
            p50 = 0.0
            p90 = 0.0
            p99 = 0.0
            mmax = 0.0
        per_traj.append(
            {
                "traj_index": int(ti),
                "n_cells": int(len(seq)),
                "delta_z_abs_p50": float(p50),
                "delta_z_abs_p90": float(p90),
                "delta_z_abs_p99": float(p99),
                "delta_z_abs_max": float(mmax),
            }
        )

    dz_all = np.asarray(all_dz, dtype=np.float64)
    report = {
        "source": str(source),
        "traj_count": int(len(trajs_xy)),
        "used_traj_count": int(len(per_traj)),
        "road_z_cells_count": int(len(road_z)),
        "global": {
            "delta_z_abs_p50": float(np.quantile(dz_all, 0.50)) if dz_all.size > 0 else 0.0,
            "delta_z_abs_p90": float(np.quantile(dz_all, 0.90)) if dz_all.size > 0 else 0.0,
            "delta_z_abs_p99": float(np.quantile(dz_all, 0.99)) if dz_all.size > 0 else 0.0,
            "delta_z_abs_max": float(np.max(dz_all)) if dz_all.size > 0 else 0.0,
            "samples": int(dz_all.size),
        },
        "per_traj": per_traj,
    }
    report.update(extra)
    return report


def _collect_point_cells(
    *,
    points_path: Path,
    ref_grid_m: float,
    x0: float,
    y0: float,
    chunk_points: int,
    input_lonlat: bool,
) -> np.ndarray:
    import laspy  # type: ignore

    cells: set[int] = set()
    with laspy.open(str(points_path)) as reader:
        for chunk in reader.chunk_iterator(int(chunk_points)):
            x_raw = np.asarray(chunk.x, dtype=np.float64)
            y_raw = np.asarray(chunk.y, dtype=np.float64)
            x, y = transform_xy_to_3857_if_needed(x_raw, y_raw, input_lonlat=input_lonlat)
            valid = np.isfinite(x) & np.isfinite(y)
            if not np.any(valid):
                continue
            xv = x[valid]
            yv = y[valid]
            ix = np.floor((xv - float(x0)) / float(ref_grid_m)).astype(np.int64)
            iy = np.floor((yv - float(y0)) / float(ref_grid_m)).astype(np.int64)
            keys = np.unique(pack_cells(ix, iy))
            for k in keys.tolist():
                cells.add(int(k))
    if not cells:
        return np.empty((0,), dtype=np.int64)
    return np.asarray(sorted(cells), dtype=np.int64)


def discover_patches(data_root: str | Path) -> list[PatchInput]:
    root = Path(data_root)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"data_root_not_found: {root}")

    patch_dirs: set[Path] = set()
    for p in sorted(root.rglob("*"), key=lambda q: q.as_posix()):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        name = p.name.lower()
        rel = p.relative_to(root).as_posix().lower()
        is_point = suffix in POINT_EXTS and (
            "pointcloud/" in rel or name.startswith("merged.") or "point" in name or "cloud" in name
        )
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
    p1 = patch_dir / "PointCloud" / "merged.laz"
    p2 = patch_dir / "PointCloud" / "merged.las"
    if p1.is_file():
        return p1
    if p2.is_file():
        return p2

    candidates: list[Path] = []
    for p in patch_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in POINT_EXTS:
            continue
        candidates.append(p)
    if not candidates:
        return None

    def rank(path: Path) -> tuple[int, str]:
        rel = path.as_posix().lower()
        name = path.name.lower()
        if "pointcloud/merged.laz" in rel:
            pri = 0
        elif "pointcloud/merged.las" in rel:
            pri = 1
        elif name == "merged.laz":
            pri = 2
        elif name == "merged.las":
            pri = 3
        elif path.suffix.lower() == ".laz":
            pri = 4
        else:
            pri = 5
        return pri, rel

    return sorted(candidates, key=rank)[0]


def _find_traj_paths_for_patch(patch_dir: Path) -> list[Path]:
    preferred = [p for p in patch_dir.glob("Traj/*/raw_dat_pose.geojson") if p.is_file()]
    preferred = sorted({p.resolve() for p in preferred}, key=lambda x: x.as_posix())
    if preferred:
        return [Path(p) for p in preferred if _traj_has_any_z(Path(p))]

    fallback: list[Path] = []
    for p in patch_dir.rglob("*.geojson"):
        if not p.is_file():
            continue
        name = p.name.lower()
        rel = p.relative_to(patch_dir).as_posix().lower()
        if (
            "traj" not in name
            and "pose" not in name
            and "raw_dat_pose" not in name
            and "traj" not in rel
            and "pose" not in rel
        ):
            continue
        if _traj_has_any_z(p):
            fallback.append(p)
    uniq = sorted({p.resolve() for p in fallback}, key=lambda x: x.as_posix())
    return [Path(p) for p in uniq]


def _traj_has_any_z(path: Path) -> bool:
    try:
        for _, _, z in iter_traj_points_geojson(path, sample_max_points=200):
            if z is not None and math.isfinite(float(z)):
                return True
    except Exception:
        return False
    return False


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
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")


def _unpack_cell(key: int) -> tuple[int, int]:
    hi = (int(key) >> 32) & 0xFFFFFFFF
    lo = int(key) & 0xFFFFFFFF
    if hi >= 0x80000000:
        hi -= 0x100000000
    if lo >= 0x80000000:
        lo -= 0x100000000
    return int(hi), int(lo)


def _as_num(v: object, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _series_stats(arr: np.ndarray) -> dict[str, float]:
    a = np.asarray(arr, dtype=np.float64)
    a = a[np.isfinite(a)]
    if a.size <= 0:
        return {"min": 0.0, "median": 0.0, "p90": 0.0, "max": 0.0}
    return {
        "min": float(np.min(a)),
        "median": float(np.median(a)),
        "p90": float(np.quantile(a, 0.90)),
        "max": float(np.max(a)),
    }


def _is_laz_backend_error(exc: Exception) -> bool:
    msg = f"{type(exc).__name__}: {exc}".lower()
    return any(k in msg for k in ["lazrs", "laszip", "backend", "compress", "decompress", "laz"])


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        return


def _fail_row(*, patch: PatchInput, out_dir: Path, reason: str) -> dict[str, object]:
    return {
        "patch_key": patch.patch_key,
        "patch_dir": str(patch.patch_dir),
        "points_path": str(patch.points_path) if patch.points_path is not None else None,
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


def _gen_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


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
        vv = float(v)
        return vv if math.isfinite(vv) else None
    return v


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(_to_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(_to_json_safe(row), ensure_ascii=False, sort_keys=True) + "\n")


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

    # legacy args kept for backward compatibility
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

    # v2 args
    parser.add_argument("--out_epsg", type=int, default=3857)
    parser.add_argument("--traj_z_mode", default="auto")
    parser.add_argument("--ground_band_m", type=float, default=0.3)
    parser.add_argument("--corridor_radius_m", type=float, default=25.0)
    parser.add_argument("--traj_step_m", type=float, default=2.0)
    parser.add_argument("--nonzero_ratio_gate", type=float, default=0.01)
    parser.add_argument("--z_std_gate", type=float, default=0.05)
    parser.add_argument("--z_check_sample_max_points", type=int, default=1000)
    parser.add_argument("--z_bin_m", type=float, default=0.2)
    parser.add_argument("--max_samples_per_cell", type=int, default=512)
    parser.add_argument("--overlap_sep_gate_m", type=float, default=3.0)
    parser.add_argument("--overlap_min_support_points", type=int, default=60)
    parser.add_argument("--overlap_min_support_ratio", type=float, default=0.10)
    parser.add_argument("--smooth_lambda", type=float, default=0.5)

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
            out_epsg=int(args.out_epsg),
            traj_z_mode=str(args.traj_z_mode),
            ground_band_m=float(args.ground_band_m),
            corridor_radius_m=float(args.corridor_radius_m),
            traj_step_m=float(args.traj_step_m),
            nonzero_ratio_gate=float(args.nonzero_ratio_gate),
            z_std_gate=float(args.z_std_gate),
            z_check_sample_max_points=int(args.z_check_sample_max_points),
            z_bin_m=float(args.z_bin_m),
            max_samples_per_cell=int(args.max_samples_per_cell),
            overlap_sep_gate_m=float(args.overlap_sep_gate_m),
            overlap_min_support_points=int(args.overlap_min_support_points),
            overlap_min_support_ratio=float(args.overlap_min_support_ratio),
            smooth_lambda=float(args.smooth_lambda),
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
