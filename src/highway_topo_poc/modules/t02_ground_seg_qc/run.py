from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from .autotune import tune_until_pass
from .config import Config
from .ground_classify import GroundClassifyResult, classify_ground_points
from .ground_ref import compute_ground_z
from .intervals import compute_intervals
from .io import PointCloudData, discover_patch, load_patch_inputs
from .qc import QCResult, compute_qc
from .report import build_summary
from .xsec_qc import XSecQCResult, compute_xsec_qc


def run_patch(
    data_root: str | Path,
    patch: str = "auto",
    run_id: str = "auto",
    out_root: str | Path = "outputs/_work/t02_ground_seg_qc",
    config: Config | None = None,
    auto_tune: bool | None = None,
) -> dict[str, object]:
    cfg = config if config is not None else Config()
    cfg.validate()

    auto_tune_enabled = cfg.auto_tune_default if auto_tune is None else bool(auto_tune)

    candidate = discover_patch(
        data_root=data_root,
        patch=patch,
        require_loadable=True,
        probe_max_points=min(cfg.processing_max_points, 20_000),
    )

    traj_xyz_raw, point_data = load_patch_inputs(candidate, max_points=cfg.processing_max_points)
    traj_xyz = _ensure_xyz(traj_xyz_raw, name="traj")
    points_xyz = _ensure_xyz(point_data.xyz, name="points")

    traj_xyz, projection_meta = _maybe_project_lonlat_to_utm(traj_xyz=traj_xyz, points_xyz=points_xyz)
    point_data = PointCloudData(
        xyz=points_xyz,
        original_indices=point_data.original_indices,
        total_points=point_data.total_points,
        classification=point_data.classification,
        sampled=point_data.sampled,
    )

    def evaluate_once(cur_cfg: Config) -> dict[str, object]:
        return _run_once(
            traj_xyz=traj_xyz,
            point_data=point_data,
            cur_cfg=cur_cfg,
            patch_id=candidate.patch_id,
            projection_meta=projection_meta,
        )

    base_result = evaluate_once(cfg)

    tune_outcome = tune_until_pass(
        base_cfg=cfg,
        base_result=base_result,
        evaluate_once=evaluate_once,
        enabled=auto_tune_enabled,
    )

    final_cfg = tune_outcome.chosen_config
    final_result = tune_outcome.chosen_result

    run_id_val = _gen_run_id() if run_id == "auto" else str(run_id)
    out_dir = Path(out_root) / run_id_val / candidate.patch_id
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics_payload = _as_dict(final_result.get("metrics"))
    traj_intervals = _as_dict(final_result.get("traj_intervals"))
    xsec_intervals = _as_dict(final_result.get("xsec_intervals"))
    ground_stats = _as_dict(final_result.get("ground_stats"))
    ground_result = final_result.get("ground_result")
    qc_result = final_result.get("qc_result")
    xsec_result = final_result.get("xsec_result")

    if not isinstance(ground_result, GroundClassifyResult):
        raise ValueError("internal_error_missing_ground_result")
    if not isinstance(qc_result, QCResult):
        raise ValueError("internal_error_missing_qc_result")
    if not isinstance(xsec_result, XSecQCResult):
        raise ValueError("internal_error_missing_xsec_result")

    _write_json(out_dir / "metrics.json", metrics_payload)
    _write_json(out_dir / "intervals.json", traj_intervals)
    _write_json(out_dir / "xsec_intervals.json", xsec_intervals)
    _write_json(out_dir / "ground_stats.json", ground_stats)
    _write_json(out_dir / "chosen_config.json", final_cfg.to_dict())

    np.save(out_dir / "ground_idx.npy", ground_result.ground_idx_export)
    np.save(out_dir / "ground_points.npy", ground_result.ground_points_export)

    ground_z = traj_xyz[:, 2] - qc_result.z_diff
    np.savez_compressed(
        out_dir / "series.npz",
        traj_xyz=traj_xyz,
        ground_z=ground_z,
        z_diff=qc_result.z_diff,
        residual=qc_result.residual,
        abs_res=qc_result.abs_res,
    )

    np.savez_compressed(
        out_dir / "xsec_series.npz",
        coverage=xsec_result.coverage,
        line_a=xsec_result.line_a,
        line_b=xsec_result.line_b,
        abs_res_p90=xsec_result.abs_res_p90,
        support_count=xsec_result.support_count,
        is_anomaly=xsec_result.is_anomaly,
    )

    _write_jsonl(out_dir / "tune_log.jsonl", tune_outcome.tune_log)

    summary = build_summary(
        run_id=run_id_val,
        patch_id=candidate.patch_id,
        patch_dir=candidate.patch_dir,
        traj_path=candidate.traj_path,
        points_path=candidate.points_path,
        output_dir=out_dir,
        metrics=metrics_payload,
        traj_intervals_payload=traj_intervals,
        xsec_intervals_payload=xsec_intervals,
        ground_stats=ground_stats,
        chosen_config=final_cfg,
        tune_log=tune_outcome.tune_log,
    )
    (out_dir / "summary.txt").write_text(summary, encoding="utf-8")

    result = {
        "run_id": run_id_val,
        "patch_id": candidate.patch_id,
        "patch_dir": str(candidate.patch_dir),
        "traj_path": str(candidate.traj_path),
        "points_path": str(candidate.points_path),
        "output_dir": str(out_dir),
        "metrics": metrics_payload,
        "intervals": traj_intervals,
        "xsec_intervals": xsec_intervals,
        "ground_stats": ground_stats,
        "chosen_config": final_cfg.to_dict(),
        "tune_log": tune_outcome.tune_log,
        "summary": summary,
    }

    return result


def _run_once(
    *,
    traj_xyz: np.ndarray,
    point_data: PointCloudData,
    cur_cfg: Config,
    patch_id: str,
    projection_meta: dict[str, object],
) -> dict[str, object]:
    cur_cfg.validate()

    ground_result = classify_ground_points(point_data, cur_cfg)

    ground_z = compute_ground_z(traj_xyz=traj_xyz, points_xyz=point_data.xyz, cfg=cur_cfg)
    qc_result = compute_qc(traj_z=traj_xyz[:, 2], ground_z=ground_z, cfg=cur_cfg)
    traj_intervals = compute_intervals(abs_res=qc_result.abs_res, valid_mask=qc_result.valid_mask, cfg=cur_cfg)

    xsec_result = compute_xsec_qc(traj_xyz=traj_xyz, ground_xyz=ground_result.ground_points_export, cfg=cur_cfg)

    metrics = _compose_metrics(
        patch_id=patch_id,
        cfg=cur_cfg,
        qc_result=qc_result,
        ground_result=ground_result,
        xsec_result=xsec_result,
        projection_meta=projection_meta,
    )

    return {
        "metrics": metrics,
        "traj_intervals": traj_intervals,
        "xsec_intervals": xsec_result.intervals,
        "ground_stats": ground_result.ground_stats,
        "ground_result": ground_result,
        "qc_result": qc_result,
        "xsec_result": xsec_result,
    }


def _compose_metrics(
    *,
    patch_id: str,
    cfg: Config,
    qc_result: QCResult,
    ground_result: GroundClassifyResult,
    xsec_result: XSecQCResult,
    projection_meta: dict[str, object],
) -> dict[str, object]:
    traj_metrics = _as_dict(qc_result.metrics)
    xsec_metrics = _as_dict(xsec_result.metrics)
    ground_stats = _as_dict(ground_result.ground_stats)

    coverage = _to_float(traj_metrics.get("coverage"), 0.0)
    outlier_ratio = _to_float(traj_metrics.get("outlier_ratio"), 0.0)
    p99 = _to_float(traj_metrics.get("p99"), float("nan"))

    traj_gate_cov = bool(coverage >= cfg.coverage_gate)
    traj_gate_outlier = bool(outlier_ratio <= cfg.outlier_gate)
    traj_gate_p99 = bool(np.isfinite(p99) and p99 <= cfg.p99_gate_m)
    traj_overall = bool(traj_gate_cov and traj_gate_outlier and traj_gate_p99)

    ground_ratio = _to_float(ground_stats.get("ground_ratio"), 0.0)
    ground_count = int(_to_float(ground_stats.get("ground_count"), 0.0))
    ground_cov = coverage

    ground_gate_ratio = bool(cfg.ground_ratio_min <= ground_ratio <= cfg.ground_ratio_max)
    ground_gate_count = bool(ground_count >= cfg.ground_count_gate_min)
    ground_overall = bool(ground_gate_ratio and ground_gate_count)

    xsec_valid_ratio = _to_float(xsec_metrics.get("xsec_valid_ratio"), 0.0)
    xsec_p99 = _to_float(xsec_metrics.get("xsec_p99_abs_res_m"), float("nan"))
    xsec_anomaly_ratio = _to_float(xsec_metrics.get("xsec_anomaly_ratio"), 0.0)

    xsec_gate_valid = bool(xsec_valid_ratio >= cfg.xsec_valid_ratio_gate)
    xsec_gate_p99 = bool(np.isfinite(xsec_p99) and xsec_p99 <= cfg.xsec_p99_abs_res_gate_m)
    xsec_gate_anomaly = bool(xsec_anomaly_ratio <= cfg.xsec_anomaly_ratio_gate)
    xsec_overall = bool(xsec_gate_valid and xsec_gate_p99 and xsec_gate_anomaly)

    overall_pass = bool(traj_overall and ground_overall and xsec_overall)

    metrics: dict[str, object] = {
        "patch_id": patch_id,
        "p50": traj_metrics.get("p50"),
        "p90": traj_metrics.get("p90"),
        "p99": traj_metrics.get("p99"),
        "coverage": coverage,
        "outlier_ratio": outlier_ratio,
        "bias": traj_metrics.get("bias"),
        "baseline": traj_metrics.get("baseline"),
        "threshold": traj_metrics.get("threshold"),
        "n_total": traj_metrics.get("n_total"),
        "n_valid": traj_metrics.get("n_valid"),
        "ground_source": ground_stats.get("ground_source"),
        "ground_count": ground_count,
        "ground_ratio": ground_ratio,
        "ground_coverage": ground_cov,
        "export_count": ground_stats.get("export_count"),
        "sampled": ground_stats.get("sampled"),
        "xsec_valid_ratio": xsec_valid_ratio,
        "xsec_p50_abs_res_m": xsec_metrics.get("xsec_p50_abs_res_m"),
        "xsec_p90_abs_res_m": xsec_metrics.get("xsec_p90_abs_res_m"),
        "xsec_p99_abs_res_m": xsec_p99,
        "xsec_anomaly_ratio": xsec_anomaly_ratio,
        "projection_applied": projection_meta.get("applied", False),
        "projection_zone": projection_meta.get("zone"),
        "gates": {
            "traj_gates": {
                "coverage_gate": traj_gate_cov,
                "outlier_gate": traj_gate_outlier,
                "p99_gate_m": traj_gate_p99,
                "overall_pass": traj_overall,
            },
            "ground_gates": {
                "ratio_gate": ground_gate_ratio,
                "count_gate": ground_gate_count,
                "overall_pass": ground_overall,
            },
            "xsec_gates": {
                "valid_ratio_gate": xsec_gate_valid,
                "p99_gate": xsec_gate_p99,
                "anomaly_ratio_gate": xsec_gate_anomaly,
                "overall_pass": xsec_overall,
            },
            "overall_pass": overall_pass,
        },
        "gate_thresholds": {
            "coverage_gate": cfg.coverage_gate,
            "outlier_gate": cfg.outlier_gate,
            "p99_gate_m": cfg.p99_gate_m,
            "ground_ratio_min": cfg.ground_ratio_min,
            "ground_ratio_max": cfg.ground_ratio_max,
            "ground_count_gate_min": cfg.ground_count_gate_min,
            "xsec_valid_ratio_gate": cfg.xsec_valid_ratio_gate,
            "xsec_p99_abs_res_gate_m": cfg.xsec_p99_abs_res_gate_m,
            "xsec_anomaly_ratio_gate": cfg.xsec_anomaly_ratio_gate,
        },
    }

    return metrics


def _ensure_xyz(arr: np.ndarray, *, name: str) -> np.ndarray:
    a = np.asarray(arr, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] < 3:
        raise ValueError(f"{name}_xyz_shape_invalid")
    return a[:, :3]


def _maybe_project_lonlat_to_utm(traj_xyz: np.ndarray, points_xyz: np.ndarray) -> tuple[np.ndarray, dict[str, object]]:
    meta: dict[str, object] = {"applied": False, "zone": None}
    if traj_xyz.size == 0 or points_xyz.size == 0:
        return traj_xyz, meta

    traj = np.asarray(traj_xyz, dtype=np.float64)
    points = np.asarray(points_xyz, dtype=np.float64)

    tmask = np.isfinite(traj[:, 0]) & np.isfinite(traj[:, 1])
    if np.count_nonzero(tmask) < 3:
        return traj, meta

    lon = traj[tmask, 0]
    lat = traj[tmask, 1]

    if float(np.max(np.abs(lon))) > 180.0 or float(np.max(np.abs(lat))) > 90.0:
        return traj, meta

    pmask = np.isfinite(points[:, 0]) & np.isfinite(points[:, 1])
    if np.count_nonzero(pmask) < 3:
        return traj, meta

    px = np.abs(points[pmask, 0])
    py = np.abs(points[pmask, 1])
    if float(np.median(px)) < 1000.0 or float(np.median(py)) < 1000.0:
        return traj, meta

    lon0 = float(np.median(lon))
    zone = int(math.floor((lon0 + 180.0) / 6.0) + 1)
    zone = min(60, max(1, zone))

    x, y = _wgs84_to_utm(lon_deg=lon, lat_deg=lat, zone=zone)

    out = traj.copy()
    out[tmask, 0] = x
    out[tmask, 1] = y
    meta["applied"] = True
    meta["zone"] = zone
    return out, meta


def _wgs84_to_utm(lon_deg: np.ndarray, lat_deg: np.ndarray, zone: int) -> tuple[np.ndarray, np.ndarray]:
    lon = np.deg2rad(np.asarray(lon_deg, dtype=np.float64))
    lat = np.deg2rad(np.asarray(lat_deg, dtype=np.float64))

    a = 6378137.0
    f = 1.0 / 298.257223563
    k0 = 0.9996
    e2 = f * (2.0 - f)
    ep2 = e2 / (1.0 - e2)

    lon0_deg = (zone - 1) * 6 - 180 + 3
    lon0 = math.radians(lon0_deg)

    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    tan_lat = np.tan(lat)

    n = a / np.sqrt(1.0 - e2 * sin_lat * sin_lat)
    t = tan_lat * tan_lat
    c = ep2 * cos_lat * cos_lat
    aa = cos_lat * (lon - lon0)

    m = a * (
        (1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 * e2 * e2 / 256) * lat
        - (3 * e2 / 8 + 3 * e2 * e2 / 32 + 45 * e2 * e2 * e2 / 1024) * np.sin(2 * lat)
        + (15 * e2 * e2 / 256 + 45 * e2 * e2 * e2 / 1024) * np.sin(4 * lat)
        - (35 * e2 * e2 * e2 / 3072) * np.sin(6 * lat)
    )

    easting = k0 * n * (
        aa
        + (1 - t + c) * np.power(aa, 3) / 6
        + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * np.power(aa, 5) / 120
    ) + 500000.0

    northing = k0 * (
        m
        + n
        * tan_lat
        * (
            aa * aa / 2
            + (5 - t + 9 * c + 4 * c * c) * np.power(aa, 4) / 24
            + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * np.power(aa, 6) / 720
        )
    )

    south = lat_deg < 0
    northing = np.where(south, northing + 10000000.0, northing)
    return easting, northing


def _gen_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _write_json(path: Path, payload: object) -> None:
    safe = _to_json_safe(payload)
    path.write_text(json.dumps(safe, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(_to_json_safe(row), ensure_ascii=False, sort_keys=True) + "\n")


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
    if isinstance(obj, np.ndarray):
        return [_to_json_safe(v) for v in obj.tolist()]

    return obj


def _as_dict(v: object) -> dict[str, object]:
    return v if isinstance(v, dict) else {}


def _to_float(v: object, default: float) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _parse_bool(s: str) -> bool:
    t = str(s).strip().lower()
    if t in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if t in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid_bool: {s}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="t02_ground_seg_qc")
    parser.add_argument("--data_root", default="data/synth_local")
    parser.add_argument("--patch", default="auto")
    parser.add_argument("--run_id", default="auto")
    parser.add_argument("--out_root", default="outputs/_work/t02_ground_seg_qc")
    parser.add_argument("--auto_tune", type=_parse_bool, default=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_patch(
            data_root=args.data_root,
            patch=args.patch,
            run_id=args.run_id,
            out_root=args.out_root,
            auto_tune=bool(args.auto_tune),
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

    overall_pass = bool(_as_dict(_as_dict(result.get("metrics")).get("gates")).get("overall_pass", False))
    return 0 if overall_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
