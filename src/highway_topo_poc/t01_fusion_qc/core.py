from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from highway_topo_poc.protocol.text_lint import lint_text
from highway_topo_poc.utils.size_guard import apply_size_limit


PROTOCOL_MAX_LINES = 120
PROTOCOL_MAX_CHARS = 8 * 1024


@dataclass(frozen=True)
class FusionQcConfig:
    patch_dir: Path
    out_dir: Path
    sample_stride: int = 5
    binN: int = 1000
    radius: float = 1.0
    radius_max: float = 3.0
    min_neighbors: int = 30
    close_frac: float = 0.2
    min_close_points: int = 20
    th: float = 0.20
    min_interval_bins: int = 3
    topk_intervals: int = 20
    pc_max_points: int = 3_000_000
    seed: int = 0
    max_lines: int = 220
    max_chars: int = 20_000


@dataclass(frozen=True)
class IntervalRecord:
    start_bin: int
    end_bin: int
    start_sample_idx: int
    end_sample_idx: int
    length_bins: int
    peak_bin_score: float
    median_bin_score: float
    severity: str


@dataclass(frozen=True)
class FusionQcResult:
    patch_dir: Path
    merged_laz_path: Path
    traj_files: list[Path]
    sample_count: int
    valid_residual_count: int
    abs_residual_p50: float
    abs_residual_p90: float
    abs_residual_p99: float
    binN_eff: int
    interval_count: int
    interval_total_len_pct: float
    intervals_topk: list[IntervalRecord]
    errors: dict[str, int]
    breakpoints: list[str]
    search_backend: str
    pointcloud_points_total: int
    pointcloud_points_scanned: int
    pointcloud_points_used: int
    text_artifact_path: Path
    intervals_csv_path: Path


def normalize_input_path(p: str) -> Path:
    s = str(p).strip()
    if not s:
        raise ValueError("empty_path")

    m = re.match(r"^([A-Za-z]):[\\/](.*)$", s)
    if m:
        drive = m.group(1).lower()
        rest = m.group(2).replace("\\", "/")
        return Path("/mnt") / drive / rest

    return Path(s)


def downsample_indices(total_points: int, max_points: int, seed: int) -> np.ndarray:
    total_points = int(total_points)
    max_points = int(max_points)
    if total_points < 0:
        raise ValueError("invalid_total_points")
    if max_points <= 0:
        raise ValueError("invalid_pc_max_points")
    if total_points <= max_points:
        return np.arange(total_points, dtype=np.int64)

    rng = np.random.default_rng(int(seed))
    idx = rng.choice(total_points, size=max_points, replace=False)
    idx.sort()
    return idx.astype(np.int64, copy=False)


def merge_true_runs(flags: Sequence[bool], min_len: int = 1) -> list[tuple[int, int]]:
    min_len = max(1, int(min_len))
    out: list[tuple[int, int]] = []

    start: int | None = None
    for i, v in enumerate(flags):
        if v and start is None:
            start = i
            continue
        if (not v) and (start is not None):
            if i - start >= min_len:
                out.append((start, i - 1))
            start = None

    if start is not None and len(flags) - start >= min_len:
        out.append((start, len(flags) - 1))

    return out


class _GridIndex:
    def __init__(self, xy: np.ndarray, cell_size: float) -> None:
        self.xy = xy
        self.cell_size = max(float(cell_size), 1e-6)

        scaled = np.floor(xy / self.cell_size).astype(np.int64, copy=False)
        buckets: dict[tuple[int, int], list[int]] = {}
        for idx, (ix, iy) in enumerate(scaled):
            key = (int(ix), int(iy))
            buckets.setdefault(key, []).append(idx)

        self.buckets: dict[tuple[int, int], np.ndarray] = {
            k: np.asarray(v, dtype=np.int64) for k, v in buckets.items()
        }

    def query(self, x: float, y: float, radius: float) -> np.ndarray:
        r = float(radius)
        if r <= 0.0:
            return np.empty(0, dtype=np.int64)

        cx = int(math.floor(float(x) / self.cell_size))
        cy = int(math.floor(float(y) / self.cell_size))
        reach = int(math.ceil(r / self.cell_size))

        parts: list[np.ndarray] = []
        for ix in range(cx - reach, cx + reach + 1):
            for iy in range(cy - reach, cy + reach + 1):
                arr = self.buckets.get((ix, iy))
                if arr is not None and arr.size:
                    parts.append(arr)

        if not parts:
            return np.empty(0, dtype=np.int64)

        cand = np.concatenate(parts)
        dx = self.xy[cand, 0] - float(x)
        dy = self.xy[cand, 1] - float(y)
        keep = (dx * dx + dy * dy) <= (r * r)
        return cand[keep]


class XYRadiusSearcher:
    def __init__(self, xy: np.ndarray, base_radius: float) -> None:
        self.xy = xy
        self.backend = "grid"
        self._tree: Any | None = None
        self._grid: _GridIndex | None = None

        try:
            from scipy.spatial import cKDTree  # type: ignore

            self._tree = cKDTree(xy)
            self.backend = "scipy_ckdtree"
        except Exception:
            self._grid = _GridIndex(xy, max(base_radius, 1e-6))
            self.backend = "grid"

    def query(self, x: float, y: float, radius: float) -> np.ndarray:
        if self._tree is not None:
            idx = self._tree.query_ball_point([float(x), float(y)], r=float(radius))
            return np.asarray(idx, dtype=np.int64)
        assert self._grid is not None
        return self._grid.query(float(x), float(y), float(radius))


def _resolve_patch_inputs(patch_dir: Path) -> tuple[Path, list[Path]]:
    merged_laz = patch_dir / "PointCloud" / "merged.laz"
    if not merged_laz.is_file():
        raise ValueError("merged_laz_missing")

    traj_root = patch_dir / "Traj"
    if not traj_root.exists():
        raise ValueError("traj_root_missing")

    traj_files = sorted(traj_root.glob("**/raw_dat_pose.geojson"))
    if not traj_files:
        raise ValueError("traj_pose_missing")

    return merged_laz, traj_files


def _read_geojson_points(traj_files: list[Path]) -> tuple[np.ndarray, list[Any], str]:
    rows: list[tuple[float, float, float]] = []
    frame_ids: list[Any] = []
    crs_names: set[str] = set()

    for path in traj_files:
        obj = json.loads(path.read_text(encoding="utf-8"))

        crs = obj.get("crs")
        if isinstance(crs, dict):
            props = crs.get("properties") or {}
            name = str(props.get("name", "")).strip()
            if name:
                crs_names.add(name)

        feats = obj.get("features") or []
        for feat in feats:
            if not isinstance(feat, dict):
                continue
            geom = feat.get("geometry") or {}
            if not isinstance(geom, dict) or geom.get("type") != "Point":
                continue
            coords = geom.get("coordinates") or []
            if not isinstance(coords, list) or len(coords) < 2:
                continue

            x = float(coords[0])
            y = float(coords[1])
            z = float(coords[2]) if len(coords) >= 3 else float("nan")

            props = feat.get("properties") or {}
            frame_ids.append(props.get("frame_id", props.get("seq", "na")))
            rows.append((x, y, z))

    if not rows:
        raise ValueError("traj_empty")

    if len(crs_names) > 1:
        raise ValueError("traj_plane_conflict")

    crs_name = sorted(crs_names)[0] if crs_names else "na"
    arr = np.asarray(rows, dtype=np.float64)
    return arr, frame_ids, crs_name


def _sample_traj(traj_xyz: np.ndarray, frame_ids: list[Any], sample_stride: int) -> tuple[np.ndarray, np.ndarray, list[Any]]:
    stride = max(1, int(sample_stride))
    idx = np.arange(0, traj_xyz.shape[0], stride, dtype=np.int64)
    return traj_xyz[idx], idx, [frame_ids[i] for i in idx.tolist()]


def _read_laz_xyz(
    merged_laz: Path,
    pc_max_points: int,
    seed: int,
) -> tuple[np.ndarray, int, np.ndarray, int]:
    try:
        import laspy  # type: ignore
    except Exception as e:
        raise ValueError("laspy_missing") from e

    target = int(pc_max_points)
    if target <= 0:
        raise ValueError("invalid_pc_max_points")

    with laspy.open(str(merged_laz)) as reader:
        total = int(reader.header.point_count)
        if total <= 0:
            return np.empty((0, 3), dtype=np.float64), 0, np.empty(0, dtype=np.int64), 0

        # LAZ usually needs sequential decode; cap scan volume to keep runtime bounded.
        if total > target:
            scan_cap = min(total, max(target, target * 2))
        else:
            scan_cap = total

        chunk_size = min(1_000_000, max(200_000, target))

        x_parts: list[np.ndarray] = []
        y_parts: list[np.ndarray] = []
        z_parts: list[np.ndarray] = []
        scanned = 0

        for pts in reader.chunk_iterator(chunk_size):
            x_chunk = np.asarray(pts.x, dtype=np.float64)
            y_chunk = np.asarray(pts.y, dtype=np.float64)
            z_chunk = np.asarray(pts.z, dtype=np.float64)

            x_parts.append(x_chunk)
            y_parts.append(y_chunk)
            z_parts.append(z_chunk)
            scanned += int(x_chunk.shape[0])

            if scanned >= scan_cap:
                break

    x = np.concatenate(x_parts) if x_parts else np.empty(0, dtype=np.float64)
    y = np.concatenate(y_parts) if y_parts else np.empty(0, dtype=np.float64)
    z = np.concatenate(z_parts) if z_parts else np.empty(0, dtype=np.float64)

    scanned = int(x.shape[0])
    idx = downsample_indices(scanned, min(target, scanned), int(seed))
    xyz = np.column_stack((x[idx], y[idx], z[idx]))
    return xyz, total, idx, scanned


def _radius_schedule(radius: float, radius_max: float, steps: int = 4) -> list[float]:
    r0 = max(float(radius), 1e-6)
    r1 = max(float(radius_max), r0)
    if abs(r1 - r0) < 1e-12:
        return [r0]

    out = [r0 + (r1 - r0) * (i / float(steps)) for i in range(steps + 1)]
    out[-1] = r1
    return out


def _quantiles(v: np.ndarray) -> tuple[float, float, float]:
    if v.size == 0:
        return float("nan"), float("nan"), float("nan")
    q = np.quantile(v, [0.5, 0.9, 0.99])
    return float(q[0]), float(q[1]), float(q[2])


def _severity(score: float, threshold: float) -> str:
    if not np.isfinite(score):
        return "low"
    if score >= (2.0 * threshold):
        return "high"
    if score >= (1.5 * threshold):
        return "med"
    return "low"


def _build_bin_edges(n_samples: int, binN: int) -> np.ndarray:
    if n_samples <= 0:
        return np.asarray([0], dtype=np.int64)

    bin_eff = max(1, min(int(binN), int(n_samples)))
    edges = np.linspace(0, n_samples, num=bin_eff + 1, dtype=np.int64)
    edges[-1] = n_samples

    for i in range(bin_eff):
        if edges[i + 1] <= edges[i]:
            edges[i + 1] = edges[i] + 1
    edges[-1] = n_samples

    return edges


def _compute_bin_scores(abs_residual: np.ndarray, edges: np.ndarray) -> np.ndarray:
    bin_eff = max(0, int(edges.shape[0]) - 1)
    scores = np.full(bin_eff, np.nan, dtype=np.float64)

    for b in range(bin_eff):
        s = int(edges[b])
        e = int(edges[b + 1])
        vals = abs_residual[s:e]
        vals = vals[np.isfinite(vals)]
        if vals.size:
            scores[b] = float(np.median(vals))

    return scores


def _build_intervals(
    *,
    bin_scores: np.ndarray,
    edges: np.ndarray,
    threshold: float,
    min_interval_bins: int,
    topk_intervals: int,
) -> tuple[list[IntervalRecord], int, float]:
    flags = np.isfinite(bin_scores) & (bin_scores > float(threshold))
    runs = merge_true_runs(flags.tolist(), min_len=int(min_interval_bins))

    intervals_all: list[IntervalRecord] = []
    for start_bin, end_bin in runs:
        seg = bin_scores[start_bin : end_bin + 1]
        seg = seg[np.isfinite(seg)]
        if seg.size == 0:
            continue

        start_sample_idx = int(edges[start_bin])
        end_sample_idx = int(edges[end_bin + 1] - 1)
        length_bins = int(end_bin - start_bin + 1)
        peak = float(np.max(seg))
        med = float(np.median(seg))

        intervals_all.append(
            IntervalRecord(
                start_bin=int(start_bin),
                end_bin=int(end_bin),
                start_sample_idx=start_sample_idx,
                end_sample_idx=end_sample_idx,
                length_bins=length_bins,
                peak_bin_score=peak,
                median_bin_score=med,
                severity=_severity(peak, float(threshold)),
            )
        )

    intervals_all.sort(key=lambda it: (-it.peak_bin_score, -it.median_bin_score, it.start_bin))

    bin_eff = int(bin_scores.shape[0])
    total_len_bins = sum(it.length_bins for it in intervals_all)
    total_len_pct = 100.0 * total_len_bins / float(bin_eff) if bin_eff > 0 else 0.0

    k = max(1, int(topk_intervals))
    return intervals_all[:k], len(intervals_all), float(total_len_pct)


def _to_params_dict(cfg: FusionQcConfig) -> dict[str, Any]:
    return {
        "sample_stride": cfg.sample_stride,
        "binN": cfg.binN,
        "radius": cfg.radius,
        "radius_max": cfg.radius_max,
        "min_neighbors": cfg.min_neighbors,
        "close_frac": cfg.close_frac,
        "min_close_points": cfg.min_close_points,
        "th": cfg.th,
        "min_interval_bins": cfg.min_interval_bins,
        "topk_intervals": cfg.topk_intervals,
        "pc_max_points": cfg.pc_max_points,
        "seed": cfg.seed,
        "max_lines": cfg.max_lines,
        "max_chars": cfg.max_chars,
    }


def _config_digest(cfg: FusionQcConfig) -> str:
    payload = json.dumps(_to_params_dict(cfg), sort_keys=True, ensure_ascii=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def _fmt_num(v: float) -> str:
    if not np.isfinite(v):
        return "na"
    return f"{float(v):.6g}"


def _build_text_bundle(
    *,
    cfg: FusionQcConfig,
    patch_dir: Path,
    traj_files: list[Path],
    merged_laz: Path,
    crs_name: str,
    search_backend: str,
    sample_count: int,
    valid_count: int,
    p50: float,
    p90: float,
    p99: float,
    binN_eff: int,
    interval_count: int,
    interval_total_len_pct: float,
    intervals_topk: list[IntervalRecord],
    errors: dict[str, int],
    breakpoints: list[str],
    pointcloud_points_total: int,
    pointcloud_points_scanned: int,
    pointcloud_points_used: int,
) -> str:
    params = _to_params_dict(cfg)
    ordered_param_keys = [
        "sample_stride",
        "binN",
        "radius",
        "radius_max",
        "min_neighbors",
        "close_frac",
        "min_close_points",
        "th",
        "min_interval_bins",
        "topk_intervals",
        "pc_max_points",
        "seed",
    ]
    params_text = "; ".join([f"{k}={params[k]}" for k in ordered_param_keys])

    digest = _config_digest(cfg)
    run_id = f"t01_{patch_dir.name}_{digest[:6]}"

    errors_items = sorted(errors.items(), key=lambda kv: (-int(kv[1]), kv[0]))
    errors_text = ", ".join([f"{k}:{v}" for k, v in errors_items]) if errors_items else "na"
    bp_text = ", ".join(breakpoints) if breakpoints else "na"

    lines: list[str] = []
    lines.append("=== Highway_Topo_Poc TEXT_QC_BUNDLE v1 ===")
    lines.append("Project: Highway_Topo_Poc")
    lines.append(f"Run: {run_id}  Commit: na  ConfigDigest: {digest}")
    lines.append(f"Patch: {patch_dir.name}  Provider: file  Seed: {cfg.seed}")
    lines.append("Module: t01  ModuleVersion: t01_mvp")
    lines.append("")
    lines.append("Inputs: traj=ok  pc=ok  vectors=na  ground=na")
    lines.append(
        f"InputMeta: traj_files={len(traj_files)}; crs={crs_name}; pc_total={pointcloud_points_total}; pc_scanned={pointcloud_points_scanned}; pc_used={pointcloud_points_used}; backend={search_backend}; merged={merged_laz.name}"
    )
    lines.append("")
    lines.append(f"Params(TopN<=12): {params_text}")
    lines.append("")
    lines.append("Metrics(TopN<=10):")
    lines.append(
        "- abs_residual: "
        f"p50={_fmt_num(p50)} p90={_fmt_num(p90)} p99={_fmt_num(p99)} "
        f"threshold={_fmt_num(cfg.th)} unit=m count={valid_count}"
    )
    lines.append("")
    lines.append(f"Intervals(binN={binN_eff}):")
    lines.append(
        f"- type=misalignment  count={interval_count}  total_len_pct={interval_total_len_pct:.2f}%"
    )
    if intervals_topk:
        for it in intervals_topk:
            lines.append(
                "  - "
                f"start_bin={it.start_bin} end_bin={it.end_bin} "
                f"start_sample_idx={it.start_sample_idx} end_sample_idx={it.end_sample_idx} "
                f"length_bins={it.length_bins} peak_bin_score={it.peak_bin_score:.6f} "
                f"median_bin_score={it.median_bin_score:.6f} severity={it.severity}"
            )
    else:
        lines.append("  - none")
    lines.append("")
    lines.append(f"Breakpoints: [{bp_text}]")
    lines.append(f"Errors: [{errors_text}]")
    lines.append(
        "Notes: interval location keys are sample_idx/bin_idx only; no coordinate-index localization."
    )
    lines.append("Truncated: false (reason=na)")
    lines.append("=== END ===")

    text = "\n".join(lines) + "\n"

    eff_max_lines = max(1, min(int(cfg.max_lines), PROTOCOL_MAX_LINES))
    eff_max_chars = max(256, min(int(cfg.max_chars), PROTOCOL_MAX_CHARS))

    limited, truncated, _reason = apply_size_limit(
        text,
        max_lines=eff_max_lines,
        max_bytes=eff_max_chars,
    )

    if truncated:
        limited = limited.replace(
            "Truncated: true (reason=size_limit)",
            "Truncated: true (reason=TRUNCATED)",
        )

    ok, violations = lint_text(limited)
    if not ok:
        raise ValueError("text_bundle_not_pasteable")
    if violations and all(v.startswith("LONG_LINE") for v in violations):
        # Warnings only; keep output unchanged.
        return limited.rstrip("\n")

    return limited.rstrip("\n")


def _validate_cfg(cfg: FusionQcConfig) -> None:
    if cfg.sample_stride < 1:
        raise ValueError("invalid_sample_stride")
    if cfg.binN < 1:
        raise ValueError("invalid_binN")
    if cfg.radius <= 0:
        raise ValueError("invalid_radius")
    if cfg.radius_max < cfg.radius:
        raise ValueError("invalid_radius_max")
    if cfg.min_neighbors < 1:
        raise ValueError("invalid_min_neighbors")
    if not (0.0 < cfg.close_frac <= 1.0):
        raise ValueError("invalid_close_frac")
    if cfg.min_close_points < 1:
        raise ValueError("invalid_min_close_points")
    if cfg.th < 0:
        raise ValueError("invalid_th")
    if cfg.min_interval_bins < 1:
        raise ValueError("invalid_min_interval_bins")
    if cfg.topk_intervals < 1:
        raise ValueError("invalid_topk_intervals")
    if cfg.pc_max_points < 1:
        raise ValueError("invalid_pc_max_points")
    if cfg.max_lines < 1:
        raise ValueError("invalid_max_lines")
    if cfg.max_chars < 1:
        raise ValueError("invalid_max_chars")


def run_fusion_qc(cfg: FusionQcConfig) -> FusionQcResult:
    _validate_cfg(cfg)

    patch_dir = cfg.patch_dir.resolve()
    if not patch_dir.is_dir():
        raise ValueError("patch_dir_not_found")

    merged_laz, traj_files = _resolve_patch_inputs(patch_dir)

    traj_xyz, frame_ids, crs_name = _read_geojson_points(traj_files)
    samples_xyz, sample_indices, _sample_frame_ids = _sample_traj(
        traj_xyz,
        frame_ids,
        cfg.sample_stride,
    )

    pc_xyz, pointcloud_points_total, _pc_keep_idx, pointcloud_points_scanned = _read_laz_xyz(
        merged_laz,
        cfg.pc_max_points,
        cfg.seed,
    )
    pointcloud_points_used = int(pc_xyz.shape[0])

    n_samples = int(samples_xyz.shape[0])
    residual = np.full(n_samples, np.nan, dtype=np.float64)
    errors: Counter[str] = Counter()
    if pointcloud_points_scanned < pointcloud_points_total:
        errors["pc_scan_truncated"] += 1

    if pc_xyz.shape[0] == 0:
        errors["pc_empty"] += n_samples
        backend = "none"
    else:
        searcher = XYRadiusSearcher(pc_xyz[:, :2], cfg.radius)
        backend = searcher.backend
        radii = _radius_schedule(cfg.radius, cfg.radius_max)

        for i in range(n_samples):
            x = float(samples_xyz[i, 0])
            y = float(samples_xyz[i, 1])
            z_traj = float(samples_xyz[i, 2])

            neighbors = np.empty(0, dtype=np.int64)
            for radius in radii:
                cand = searcher.query(x, y, radius)
                neighbors = cand
                if cand.size >= cfg.min_neighbors:
                    break

            if neighbors.size < cfg.min_neighbors:
                errors["insufficient_neighbors"] += 1
                continue

            z_nb = pc_xyz[neighbors, 2]
            z_nb = z_nb[np.isfinite(z_nb)]
            if z_nb.size < cfg.min_neighbors:
                errors["invalid_neighbor_z"] += 1
                continue

            if not np.isfinite(z_traj):
                errors["traj_z_missing"] += 1
                continue

            n_nb = int(z_nb.size)
            k_close = max(cfg.min_close_points, int(math.ceil(cfg.close_frac * n_nb)))
            k_close = min(k_close, n_nb)

            if k_close <= 0:
                errors["insufficient_close_points"] += 1
                continue

            dz = np.abs(z_nb - z_traj)
            if k_close < n_nb:
                keep = np.argpartition(dz, k_close - 1)[:k_close]
                close_z = z_nb[keep]
            else:
                close_z = z_nb

            z_ref = float(np.median(close_z))
            residual[i] = float(z_traj - z_ref)

    abs_residual = np.abs(residual)
    valid_mask = np.isfinite(abs_residual)
    valid_abs_res = abs_residual[valid_mask]
    valid_count = int(valid_abs_res.size)

    if valid_count == 0:
        errors["no_valid_residual"] += 1

    p50, p90, p99 = _quantiles(valid_abs_res)

    edges = _build_bin_edges(n_samples, cfg.binN)
    bin_scores = _compute_bin_scores(abs_residual, edges)
    intervals_topk, interval_count, interval_total_len_pct = _build_intervals(
        bin_scores=bin_scores,
        edges=edges,
        threshold=cfg.th,
        min_interval_bins=cfg.min_interval_bins,
        topk_intervals=cfg.topk_intervals,
    )

    breakpoints: list[str] = []
    if errors.get("traj_z_missing", 0) > 0:
        breakpoints.append("traj_z_missing")
    if errors.get("insufficient_neighbors", 0) > 0:
        breakpoints.append("insufficient_neighbors")
    if errors.get("no_valid_residual", 0) > 0:
        breakpoints.append("no_valid_residual")
    if not breakpoints:
        breakpoints.append("none")

    out_dir = cfg.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    text = _build_text_bundle(
        cfg=cfg,
        patch_dir=patch_dir,
        traj_files=traj_files,
        merged_laz=merged_laz,
        crs_name=crs_name,
        search_backend=backend,
        sample_count=n_samples,
        valid_count=valid_count,
        p50=p50,
        p90=p90,
        p99=p99,
        binN_eff=int(bin_scores.shape[0]),
        interval_count=interval_count,
        interval_total_len_pct=interval_total_len_pct,
        intervals_topk=intervals_topk,
        errors=dict(errors),
        breakpoints=breakpoints,
        pointcloud_points_total=pointcloud_points_total,
        pointcloud_points_scanned=pointcloud_points_scanned,
        pointcloud_points_used=pointcloud_points_used,
    )

    text_artifact_path = out_dir / "TEXT_QC_BUNDLE.txt"
    text_artifact_path.write_text(text + "\n", encoding="utf-8")

    intervals_csv_path = out_dir / "intervals_topk.csv"
    with intervals_csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "start_bin",
                "end_bin",
                "start_sample_idx",
                "end_sample_idx",
                "length_bins",
                "peak_bin_score",
                "median_bin_score",
                "severity",
            ],
        )
        writer.writeheader()
        for it in intervals_topk:
            writer.writerow(
                {
                    "start_bin": it.start_bin,
                    "end_bin": it.end_bin,
                    "start_sample_idx": it.start_sample_idx,
                    "end_sample_idx": it.end_sample_idx,
                    "length_bins": it.length_bins,
                    "peak_bin_score": f"{it.peak_bin_score:.6f}",
                    "median_bin_score": f"{it.median_bin_score:.6f}",
                    "severity": it.severity,
                }
            )

    return FusionQcResult(
        patch_dir=patch_dir,
        merged_laz_path=merged_laz,
        traj_files=traj_files,
        sample_count=n_samples,
        valid_residual_count=valid_count,
        abs_residual_p50=p50,
        abs_residual_p90=p90,
        abs_residual_p99=p99,
        binN_eff=int(bin_scores.shape[0]),
        interval_count=interval_count,
        interval_total_len_pct=interval_total_len_pct,
        intervals_topk=intervals_topk,
        errors=dict(errors),
        breakpoints=breakpoints,
        search_backend=backend,
        pointcloud_points_total=pointcloud_points_total,
        pointcloud_points_scanned=pointcloud_points_scanned,
        pointcloud_points_used=pointcloud_points_used,
        text_artifact_path=text_artifact_path,
        intervals_csv_path=intervals_csv_path,
    )
