from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from .io import load_point_cloud_xyz

POINT_EXTS = {".laz", ".las", ".npy", ".npz", ".csv"}


@dataclass(frozen=True)
class PatchPoints:
    patch_key: str
    patch_dir: Path
    points_path: Path


def discover_patches(data_root: str | Path) -> list[PatchPoints]:
    root = Path(data_root)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"data_root_not_found: {root}")

    point_files = [
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in POINT_EXTS and _is_points_file_candidate(root=root, path=p)
    ]
    if not point_files:
        return []

    best_by_patch: dict[Path, Path] = {}
    for p in sorted(point_files, key=lambda x: x.as_posix()):
        patch_dir = _infer_patch_dir(root=root, points_path=p)
        cur = best_by_patch.get(patch_dir)
        if cur is None or _point_rank(root=root, path=p) < _point_rank(root=root, path=cur):
            best_by_patch[patch_dir] = p

    out: list[PatchPoints] = []
    used_keys: set[str] = set()
    for patch_dir, points_path in sorted(best_by_patch.items(), key=lambda kv: kv[0].as_posix()):
        key = _build_patch_key(root=root, patch_dir=patch_dir, used_keys=used_keys)
        out.append(PatchPoints(patch_key=key, patch_dir=patch_dir, points_path=points_path))

    return sorted(out, key=lambda x: (x.patch_key, x.points_path.as_posix()))


def run_batch(
    *,
    data_root: str | Path,
    out_root: str | Path = "outputs/_work/t02_ground_seg_qc",
    run_id: str = "auto",
    resume: bool = True,
    workers: int = 1,
    chunk_points: int = 2_000_000,
    export_classified_laz: bool = False,
    grid_size_m: float = 1.0,
    above_margin_m: float = 0.08,
) -> dict[str, object]:
    if chunk_points < 1:
        raise ValueError("chunk_points must be >= 1")
    if grid_size_m <= 0:
        raise ValueError("grid_size_m must be > 0")
    if above_margin_m <= 0:
        raise ValueError("above_margin_m must be > 0")

    patches = discover_patches(data_root=data_root)
    if not patches:
        raise ValueError(f"no_point_cloud_found_under: {Path(data_root)}")

    run_id_val = _gen_run_id() if run_id == "auto" else str(run_id)
    run_root = Path(out_root) / run_id_val
    cache_root = run_root / "ground_cache"
    cache_root.mkdir(parents=True, exist_ok=True)

    if workers != 1:
        print(f"WARN: workers={workers} is currently executed sequentially (workers=1).", file=sys.stderr)

    manifest_rows: list[dict[str, object]] = []
    failed_rows: list[dict[str, object]] = []
    for patch in patches:
        row = _process_patch(
            patch=patch,
            cache_root=cache_root,
            resume=bool(resume),
            chunk_points=int(chunk_points),
            export_classified_laz=bool(export_classified_laz),
            grid_size_m=float(grid_size_m),
            above_margin_m=float(above_margin_m),
        )
        manifest_rows.append(row)
        if not bool(row.get("overall_pass", False)):
            failed_rows.append(row)

    manifest_path = run_root / "ground_cache_manifest.jsonl"
    _write_jsonl(manifest_path, manifest_rows)

    failed_path = run_root / "failed_patches.txt"
    if failed_rows:
        with failed_path.open("w", encoding="utf-8") as f:
            for row in failed_rows:
                f.write(f"{row['patch_key']}\t{row.get('reason', 'unknown')}\n")

    summary = {
        "run_id": run_id_val,
        "data_root": str(Path(data_root)),
        "cache_root": str(cache_root),
        "manifest_path": str(manifest_path),
        "total_patches": int(len(manifest_rows)),
        "pass_patches": int(len(manifest_rows) - len(failed_rows)),
        "fail_patches": int(len(failed_rows)),
        "failed_list_path": str(failed_path) if failed_rows else None,
    }
    _write_json(run_root / "ground_cache_summary.json", summary)

    return summary


def _process_patch(
    *,
    patch: PatchPoints,
    cache_root: Path,
    resume: bool,
    chunk_points: int,
    export_classified_laz: bool,
    grid_size_m: float,
    above_margin_m: float,
) -> dict[str, object]:
    out_dir = cache_root / patch.patch_key
    out_dir.mkdir(parents=True, exist_ok=True)

    label_path = out_dir / "ground_label.npy"
    stats_path = out_dir / "ground_stats.json"
    idx_path = out_dir / "ground_idx.npy"

    if resume and label_path.is_file() and stats_path.is_file():
        return _manifest_row_from_cached(
            patch=patch,
            label_path=label_path,
            stats_path=stats_path,
        )

    try:
        source, n_points, n_ground = _build_ground_label_all_points(
            points_path=patch.points_path,
            label_path=label_path,
            chunk_points=chunk_points,
            grid_size_m=grid_size_m,
            above_margin_m=above_margin_m,
        )
    except Exception as exc:
        return {
            "patch_key": patch.patch_key,
            "points_path": str(patch.points_path),
            "label_path": str(label_path),
            "stats_path": str(stats_path),
            "n_points": 0,
            "n_ground": 0,
            "ratio": 0.0,
            "pass_fail": "fail",
            "overall_pass": False,
            "reason": f"internal_error:{type(exc).__name__}:{exc}",
            "output_dir": str(out_dir),
        }

    _write_ground_idx(
        label_path=label_path,
        idx_path=idx_path,
        n_points=n_points,
        chunk_points=chunk_points,
    )

    ratio = float(n_ground / n_points) if n_points > 0 else 0.0
    gate_ratio = bool(0.01 <= ratio <= 0.99)
    gate_nonempty = bool(n_points > 0 and n_ground > 0 and n_ground < n_points)
    overall_pass = bool(gate_ratio and gate_nonempty)
    reason = _gate_reason(n_points=n_points, n_ground=n_ground, gate_ratio=gate_ratio, gate_nonempty=gate_nonempty)

    classified_path: str | None = None
    if export_classified_laz:
        out_classified = out_dir / f"classified{patch.points_path.suffix.lower()}"
        ok = _export_classified_copy(
            points_path=patch.points_path,
            label_path=label_path,
            out_path=out_classified,
            chunk_points=chunk_points,
        )
        if ok:
            classified_path = str(out_classified)

    stats = {
        "patch_key": patch.patch_key,
        "points_path": str(patch.points_path),
        "n_points": int(n_points),
        "n_ground": int(n_ground),
        "ground_ratio": ratio,
        "ground_source": source,
        "params": {
            "grid_size_m": float(grid_size_m),
            "above_margin_m": float(above_margin_m),
            "chunk_points": int(chunk_points),
            "no_sampling": True,
            "no_caps": True,
        },
        "gates": {
            "gate_ratio": gate_ratio,
            "gate_nonempty": gate_nonempty,
            "overall_pass": overall_pass,
        },
        "reason": reason,
        "classified_laz_path": classified_path,
    }
    _write_json(stats_path, stats)

    return {
        "patch_key": patch.patch_key,
        "points_path": str(patch.points_path),
        "label_path": str(label_path),
        "stats_path": str(stats_path),
        "n_points": int(n_points),
        "n_ground": int(n_ground),
        "ratio": ratio,
        "pass_fail": "pass" if overall_pass else "fail",
        "overall_pass": overall_pass,
        "reason": reason,
        "output_dir": str(out_dir),
    }


def _build_ground_label_all_points(
    *,
    points_path: Path,
    label_path: Path,
    chunk_points: int,
    grid_size_m: float,
    above_margin_m: float,
) -> tuple[str, int, int]:
    suffix = points_path.suffix.lower()
    if suffix in {".las", ".laz"}:
        return _build_ground_label_las(
            points_path=points_path,
            label_path=label_path,
            chunk_points=chunk_points,
            grid_size_m=grid_size_m,
            above_margin_m=above_margin_m,
        )

    return _build_ground_label_array(
        points_path=points_path,
        label_path=label_path,
        chunk_points=chunk_points,
        grid_size_m=grid_size_m,
        above_margin_m=above_margin_m,
    )


def _build_ground_label_las(
    *,
    points_path: Path,
    label_path: Path,
    chunk_points: int,
    grid_size_m: float,
    above_margin_m: float,
) -> tuple[str, int, int]:
    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on env
        raise ValueError("laspy_required_for_las_laz") from exc

    with laspy.open(str(points_path)) as reader:
        n_points = int(reader.header.point_count)
        dim_names = set(reader.header.point_format.dimension_names)
        has_cls = "classification" in dim_names

    if n_points == 0:
        _ = np.lib.format.open_memmap(label_path, mode="w+", dtype=np.uint8, shape=(0,))
        return "empty", 0, 0

    if has_cls:
        cls_ground_count = _count_las_cls_ground(points_path=points_path, chunk_points=chunk_points)
        if cls_ground_count > 0:
            n_ground = _write_las_cls_labels(
                points_path=points_path,
                label_path=label_path,
                chunk_points=chunk_points,
            )
            return "las_classification", n_points, n_ground

    cell_min, x0, y0 = _build_las_cell_min(
        points_path=points_path,
        chunk_points=chunk_points,
        grid_size_m=grid_size_m,
    )
    n_ground = _write_las_grid_labels(
        points_path=points_path,
        label_path=label_path,
        chunk_points=chunk_points,
        grid_size_m=grid_size_m,
        above_margin_m=above_margin_m,
        cell_min=cell_min,
        x0=x0,
        y0=y0,
    )
    return "grid_min_band", n_points, n_ground


def _build_ground_label_array(
    *,
    points_path: Path,
    label_path: Path,
    chunk_points: int,
    grid_size_m: float,
    above_margin_m: float,
) -> tuple[str, int, int]:
    xyz = np.asarray(load_point_cloud_xyz(points_path), dtype=np.float64)
    n_points = int(xyz.shape[0])
    if n_points == 0:
        _ = np.lib.format.open_memmap(label_path, mode="w+", dtype=np.uint8, shape=(0,))
        return "empty", 0, 0

    cell_min: dict[tuple[int, int], float] = {}
    x0: float | None = None
    y0: float | None = None

    for start in range(0, n_points, chunk_points):
        end = min(n_points, start + chunk_points)
        chunk = xyz[start:end]
        if x0 is None or y0 is None:
            x0, y0 = _first_chunk_anchor_xy(chunk)
        _accumulate_cell_min(
            x=chunk[:, 0],
            y=chunk[:, 1],
            z=chunk[:, 2],
            x0=float(x0),
            y0=float(y0),
            grid_size_m=grid_size_m,
            out_cell_min=cell_min,
        )

    labels = np.lib.format.open_memmap(label_path, mode="w+", dtype=np.uint8, shape=(n_points,))
    n_ground = 0
    for start in range(0, n_points, chunk_points):
        end = min(n_points, start + chunk_points)
        chunk = xyz[start:end]
        lbl = _classify_chunk_with_grid_min(
            x=chunk[:, 0],
            y=chunk[:, 1],
            z=chunk[:, 2],
            x0=float(x0),
            y0=float(y0),
            grid_size_m=grid_size_m,
            above_margin_m=above_margin_m,
            cell_min=cell_min,
        )
        labels[start:end] = lbl
        n_ground += int(lbl.sum(dtype=np.int64))

    labels.flush()
    del labels
    return "grid_min_band", n_points, n_ground


def _count_las_cls_ground(*, points_path: Path, chunk_points: int) -> int:
    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on env
        raise ValueError("laspy_required_for_las_laz") from exc

    count = 0
    with laspy.open(str(points_path)) as reader:
        for chunk in reader.chunk_iterator(chunk_points):
            if hasattr(chunk, "classification"):
                cls = np.asarray(chunk.classification, dtype=np.int16)
                count += int(np.count_nonzero(cls == 2))
    return count


def _write_las_cls_labels(*, points_path: Path, label_path: Path, chunk_points: int) -> int:
    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on env
        raise ValueError("laspy_required_for_las_laz") from exc

    with laspy.open(str(points_path)) as reader:
        n_points = int(reader.header.point_count)
        labels = np.lib.format.open_memmap(label_path, mode="w+", dtype=np.uint8, shape=(n_points,))

        offset = 0
        n_ground = 0
        for chunk in reader.chunk_iterator(chunk_points):
            n = int(len(chunk.x))
            cls = np.asarray(chunk.classification, dtype=np.int16) if hasattr(chunk, "classification") else np.zeros(n, dtype=np.int16)
            lbl = (cls == 2).astype(np.uint8)
            labels[offset : offset + n] = lbl
            n_ground += int(lbl.sum(dtype=np.int64))
            offset += n

        if offset != n_points:
            raise ValueError(f"las_chunk_count_mismatch: expected={n_points} got={offset}")

        labels.flush()
        del labels
        return n_ground


def _build_las_cell_min(*, points_path: Path, chunk_points: int, grid_size_m: float) -> tuple[dict[tuple[int, int], float], float, float]:
    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on env
        raise ValueError("laspy_required_for_las_laz") from exc

    with laspy.open(str(points_path)) as reader:
        mins = np.asarray(reader.header.mins, dtype=np.float64)
        x0 = float(mins[0]) if mins.size >= 2 else 0.0
        y0 = float(mins[1]) if mins.size >= 2 else 0.0

        cell_min: dict[tuple[int, int], float] = {}
        for chunk in reader.chunk_iterator(chunk_points):
            x = np.asarray(chunk.x, dtype=np.float64)
            y = np.asarray(chunk.y, dtype=np.float64)
            z = np.asarray(chunk.z, dtype=np.float64)
            _accumulate_cell_min(
                x=x,
                y=y,
                z=z,
                x0=x0,
                y0=y0,
                grid_size_m=grid_size_m,
                out_cell_min=cell_min,
            )

    return cell_min, x0, y0


def _write_las_grid_labels(
    *,
    points_path: Path,
    label_path: Path,
    chunk_points: int,
    grid_size_m: float,
    above_margin_m: float,
    cell_min: dict[tuple[int, int], float],
    x0: float,
    y0: float,
) -> int:
    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on env
        raise ValueError("laspy_required_for_las_laz") from exc

    with laspy.open(str(points_path)) as reader:
        n_points = int(reader.header.point_count)
        labels = np.lib.format.open_memmap(label_path, mode="w+", dtype=np.uint8, shape=(n_points,))
        offset = 0
        n_ground = 0

        for chunk in reader.chunk_iterator(chunk_points):
            x = np.asarray(chunk.x, dtype=np.float64)
            y = np.asarray(chunk.y, dtype=np.float64)
            z = np.asarray(chunk.z, dtype=np.float64)
            n = int(x.shape[0])

            lbl = _classify_chunk_with_grid_min(
                x=x,
                y=y,
                z=z,
                x0=x0,
                y0=y0,
                grid_size_m=grid_size_m,
                above_margin_m=above_margin_m,
                cell_min=cell_min,
            )
            labels[offset : offset + n] = lbl
            n_ground += int(lbl.sum(dtype=np.int64))
            offset += n

        if offset != n_points:
            raise ValueError(f"las_chunk_count_mismatch: expected={n_points} got={offset}")

        labels.flush()
        del labels
        return n_ground


def _accumulate_cell_min(
    *,
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    x0: float,
    y0: float,
    grid_size_m: float,
    out_cell_min: dict[tuple[int, int], float],
) -> None:
    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    if not np.any(valid):
        return

    xv = x[valid]
    yv = y[valid]
    zv = z[valid]

    ix = np.floor((xv - x0) / grid_size_m).astype(np.int64)
    iy = np.floor((yv - y0) / grid_size_m).astype(np.int64)

    order = np.lexsort((iy, ix))
    ixs = ix[order]
    iys = iy[order]
    zs = zv[order]
    if zs.size == 0:
        return

    change = np.empty(zs.size, dtype=bool)
    change[0] = True
    change[1:] = (ixs[1:] != ixs[:-1]) | (iys[1:] != iys[:-1])
    starts = np.flatnonzero(change)
    mins = np.minimum.reduceat(zs, starts)

    for pos, start in enumerate(starts):
        key = (int(ixs[start]), int(iys[start]))
        zmin = float(mins[pos])
        cur = out_cell_min.get(key)
        if cur is None or zmin < cur:
            out_cell_min[key] = zmin


def _classify_chunk_with_grid_min(
    *,
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    x0: float,
    y0: float,
    grid_size_m: float,
    above_margin_m: float,
    cell_min: dict[tuple[int, int], float],
) -> np.ndarray:
    out = np.zeros((x.shape[0],), dtype=np.uint8)
    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    if not np.any(valid):
        return out

    valid_idx = np.flatnonzero(valid)
    xv = x[valid]
    yv = y[valid]
    zv = z[valid]

    ix = np.floor((xv - x0) / grid_size_m).astype(np.int64)
    iy = np.floor((yv - y0) / grid_size_m).astype(np.int64)

    order = np.lexsort((iy, ix))
    ixs = ix[order]
    iys = iy[order]
    zs = zv[order]

    sorted_labels = np.zeros((order.size,), dtype=np.uint8)
    if order.size > 0:
        change = np.empty(order.size, dtype=bool)
        change[0] = True
        change[1:] = (ixs[1:] != ixs[:-1]) | (iys[1:] != iys[:-1])
        starts = np.flatnonzero(change)
        ends = np.concatenate([starts[1:], np.array([order.size], dtype=np.int64)])

        for s, e in zip(starts.tolist(), ends.tolist()):
            key = (int(ixs[s]), int(iys[s]))
            zmin = cell_min.get(key)
            if zmin is None:
                continue
            sorted_labels[s:e] = (zs[s:e] <= (float(zmin) + above_margin_m)).astype(np.uint8)

    labels_valid = np.zeros((valid_idx.size,), dtype=np.uint8)
    labels_valid[order] = sorted_labels
    out[valid_idx] = labels_valid
    return out


def _write_ground_idx(*, label_path: Path, idx_path: Path, n_points: int, chunk_points: int) -> int:
    labels = np.load(label_path, mmap_mode="r")
    n_ground = int(np.asarray(labels).sum(dtype=np.int64))
    if n_ground <= 0:
        np.save(idx_path, np.empty((0,), dtype=np.int64))
        return 0

    idx_out = np.lib.format.open_memmap(idx_path, mode="w+", dtype=np.int64, shape=(n_ground,))
    out_pos = 0
    for start in range(0, n_points, chunk_points):
        end = min(n_points, start + chunk_points)
        chunk = np.asarray(labels[start:end], dtype=np.uint8)
        local = np.flatnonzero(chunk).astype(np.int64)
        if local.size == 0:
            continue
        n = int(local.size)
        idx_out[out_pos : out_pos + n] = local + start
        out_pos += n

    idx_out.flush()
    del idx_out
    if out_pos != n_ground:
        raise ValueError(f"ground_index_count_mismatch: expected={n_ground} got={out_pos}")
    return n_ground


def _export_classified_copy(*, points_path: Path, label_path: Path, out_path: Path, chunk_points: int) -> bool:
    suffix = points_path.suffix.lower()
    if suffix not in {".las", ".laz"}:
        return False

    try:
        import laspy  # type: ignore
    except Exception:
        return False

    labels = np.load(label_path, mmap_mode="r")
    with laspy.open(str(points_path)) as reader:
        dim_names = set(reader.header.point_format.dimension_names)
        if "classification" not in dim_names:
            return False

        with laspy.open(str(out_path), mode="w", header=reader.header) as writer:
            offset = 0
            for chunk in reader.chunk_iterator(chunk_points):
                n = int(len(chunk.x))
                cls = np.asarray(chunk.classification, dtype=np.uint8)
                lbl = np.asarray(labels[offset : offset + n], dtype=np.uint8)
                cls[lbl == 1] = 2
                chunk.classification = cls
                writer.write_points(chunk)
                offset += n

    return True


def _manifest_row_from_cached(*, patch: PatchPoints, label_path: Path, stats_path: Path) -> dict[str, object]:
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    gates = stats.get("gates") if isinstance(stats.get("gates"), dict) else {}
    overall_pass = bool(gates.get("overall_pass", False))
    n_points = int(_as_number(stats.get("n_points"), default=0))
    n_ground = int(_as_number(stats.get("n_ground"), default=0))
    ratio = float(_as_number(stats.get("ground_ratio"), default=0.0))
    reason = str(stats.get("reason", "resume"))

    return {
        "patch_key": patch.patch_key,
        "points_path": str(patch.points_path),
        "label_path": str(label_path),
        "stats_path": str(stats_path),
        "n_points": n_points,
        "n_ground": n_ground,
        "ratio": ratio,
        "pass_fail": "pass" if overall_pass else "fail",
        "overall_pass": overall_pass,
        "reason": reason,
        "output_dir": str(label_path.parent),
    }


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


def _infer_patch_dir(*, root: Path, points_path: Path) -> Path:
    rel = points_path.relative_to(root)
    parts = rel.parts

    for i, part in enumerate(parts):
        if part.lower() == "pointcloud" and i >= 1:
            return root.joinpath(*parts[:i])

    if len(parts) >= 2:
        return root / parts[0]

    return points_path.parent


def _is_points_file_candidate(*, root: Path, path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in {".las", ".laz"}:
        return True

    name = path.name.lower()
    rel = path.relative_to(root).as_posix().lower()
    if "/pointcloud/" in rel:
        return True

    return any(k in name for k in ("point", "points", "cloud", "lidar", "merged", "pc"))


def _point_rank(*, root: Path, path: Path) -> tuple[int, str]:
    name = path.name.lower()
    rel = path.relative_to(root).as_posix().lower()
    suffix = path.suffix.lower()

    if name == "merged.laz" and "/pointcloud/" in rel:
        p = 0
    elif name == "merged.las" and "/pointcloud/" in rel:
        p = 1
    elif suffix == ".laz":
        p = 2
    elif suffix == ".las":
        p = 3
    elif suffix == ".npy":
        p = 4
    elif suffix == ".npz":
        p = 5
    else:
        p = 6
    return (p, rel)


def _first_chunk_anchor_xy(chunk_xyz: np.ndarray) -> tuple[float, float]:
    x = np.asarray(chunk_xyz[:, 0], dtype=np.float64)
    y = np.asarray(chunk_xyz[:, 1], dtype=np.float64)
    valid = np.isfinite(x) & np.isfinite(y)
    if not np.any(valid):
        return 0.0, 0.0
    xv = x[valid]
    yv = y[valid]
    return float(np.min(xv)), float(np.min(yv))


def _gate_reason(*, n_points: int, n_ground: int, gate_ratio: bool, gate_nonempty: bool) -> str:
    reasons: list[str] = []
    if n_points <= 0:
        reasons.append("empty_points")
    if not gate_ratio:
        reasons.append("ratio_out_of_range")
    if not gate_nonempty:
        if n_ground <= 0:
            reasons.append("empty_ground")
        elif n_ground >= n_points:
            reasons.append("full_ground")
        else:
            reasons.append("nonempty_gate_fail")
    return "ok" if not reasons else ";".join(reasons)


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
    if isinstance(v, (np.floating, float)):
        val = float(v)
        return val if math.isfinite(val) else None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    return v


def _parse_bool(s: str) -> bool:
    t = str(s).strip().lower()
    if t in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if t in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid_bool: {s}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="t02_ground_seg_qc.batch_ground_cache")
    parser.add_argument("--data_root", default="data/synth_local")
    parser.add_argument("--out_root", default="outputs/_work/t02_ground_seg_qc")
    parser.add_argument("--run_id", default="auto")
    parser.add_argument("--resume", type=_parse_bool, default=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--chunk_points", type=int, default=2_000_000)
    parser.add_argument("--export_classified_laz", type=_parse_bool, default=False)
    parser.add_argument("--grid_size_m", type=float, default=1.0)
    parser.add_argument("--above_margin_m", type=float, default=0.08)
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
            export_classified_laz=bool(args.export_classified_laz),
            grid_size_m=float(args.grid_size_m),
            above_margin_m=float(args.above_margin_m),
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"RunID: {summary['run_id']}")
    print(f"CacheRoot: {summary['cache_root']}")
    print(f"Manifest: {summary['manifest_path']}")
    print(f"TotalPatches: {summary['total_patches']}")
    print(f"PassPatches: {summary['pass_patches']}")
    print(f"FailPatches: {summary['fail_patches']}")
    if summary.get("failed_list_path"):
        print(f"FailedList: {summary['failed_list_path']}")

    return 2 if int(summary.get("fail_patches", 0)) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
