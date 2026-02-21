from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

TRAJ_EXTS = {".npy", ".npz", ".csv", ".json", ".txt", ".geojson", ".gpkg"}
POINT_EXTS = {".npy", ".npz", ".csv", ".bin", ".ply", ".pcd", ".las", ".laz"}


@dataclass(frozen=True)
class PatchCandidate:
    patch_id: str
    patch_dir: Path
    traj_path: Path
    points_path: Path


@dataclass(frozen=True)
class PointCloudData:
    xyz: np.ndarray
    original_indices: np.ndarray
    total_points: int
    classification: np.ndarray | None
    sampled: bool


def discover_patch(
    data_root: Path | str,
    patch: str = "auto",
    *,
    require_loadable: bool = False,
    probe_max_points: int = 20_000,
) -> PatchCandidate:
    root = Path(data_root)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"data_root_not_found: {root}")

    if patch != "auto":
        candidate = _resolve_explicit_patch(root, patch)
        if require_loadable and not _is_candidate_loadable(candidate, probe_max_points=probe_max_points):
            raise ValueError(f"patch_not_loadable: {candidate.patch_dir}")
        return candidate

    candidates = list_patch_candidates(root)
    if not candidates:
        raise ValueError(f"no_patch_candidate_found_under: {root}")

    if not require_loadable:
        return candidates[0]

    for candidate in candidates:
        if _is_candidate_loadable(candidate, probe_max_points=probe_max_points):
            return candidate

    raise ValueError(f"no_loadable_patch_candidate_found_under: {root}")


def list_patch_candidates(data_root: Path | str) -> list[PatchCandidate]:
    root = Path(data_root)
    if not root.exists() or not root.is_dir():
        return []

    dirs = [p for p in root.rglob("*") if p.is_dir()]

    out: list[PatchCandidate] = []
    seen: set[str] = set()
    for d in dirs:
        candidate = _candidate_from_dir(d)
        if candidate is None:
            continue
        key = (candidate.patch_dir.resolve().as_posix(), candidate.traj_path.name, candidate.points_path.name)
        dedup = "|".join(key)
        if dedup in seen:
            continue
        seen.add(dedup)
        out.append(candidate)

    out.sort(key=lambda c: (_safe_size(c.points_path), c.patch_id, c.patch_dir.as_posix()))
    return out


def load_patch_arrays(candidate: PatchCandidate) -> tuple[np.ndarray, np.ndarray]:
    traj_xyz = load_traj_xyz(candidate.traj_path)
    points_xyz = load_point_cloud_xyz(candidate.points_path)
    return traj_xyz, points_xyz


def load_patch_inputs(candidate: PatchCandidate, *, max_points: int | None = None) -> tuple[np.ndarray, PointCloudData]:
    traj_xyz = load_traj_xyz(candidate.traj_path)
    point_data = load_point_cloud_data(candidate.points_path, max_points=max_points)
    return traj_xyz, point_data


def load_traj_xyz(path: Path | str) -> np.ndarray:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".npy":
        arr = np.load(p)
        return _coerce_xyz(arr, source=str(p))
    if suffix == ".npz":
        with np.load(p) as npz:
            arr = _select_npz_array(npz, priorities=("traj", "trajectory", "poses", "xyz", "arr_0"))
        return _coerce_xyz(arr, source=str(p))
    if suffix in {".csv", ".txt"}:
        arr = _load_text_matrix(p)
        return _coerce_xyz(arr, source=str(p))
    if suffix in {".json", ".geojson"}:
        arr = _load_geojson_xyz(p)
        return _coerce_xyz(arr, source=str(p))

    raise ValueError(f"unsupported_traj_format: {p.suffix}")


def load_point_cloud_xyz(path: Path | str) -> np.ndarray:
    return load_point_cloud_data(path).xyz


def load_point_cloud_data(path: Path | str, *, max_points: int | None = None) -> PointCloudData:
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".npy":
        arr = _coerce_xyz(np.load(p), source=str(p))
        xyz, idx, sampled = _downsample_xyz(arr, max_points=max_points)
        return PointCloudData(xyz=xyz, original_indices=idx, total_points=int(arr.shape[0]), classification=None, sampled=sampled)

    if suffix == ".npz":
        with np.load(p) as npz:
            arr = _select_npz_array(npz, priorities=("points", "pointcloud", "pc", "xyz", "arr_0"))
        arr2 = _coerce_xyz(arr, source=str(p))
        xyz, idx, sampled = _downsample_xyz(arr2, max_points=max_points)
        return PointCloudData(xyz=xyz, original_indices=idx, total_points=int(arr2.shape[0]), classification=None, sampled=sampled)

    if suffix in {".csv", ".txt"}:
        arr = _coerce_xyz(_load_text_matrix(p), source=str(p))
        xyz, idx, sampled = _downsample_xyz(arr, max_points=max_points)
        return PointCloudData(xyz=xyz, original_indices=idx, total_points=int(arr.shape[0]), classification=None, sampled=sampled)

    if suffix == ".bin":
        raw = np.fromfile(p, dtype=np.float32)
        if raw.size == 0:
            return PointCloudData(
                xyz=np.empty((0, 3), dtype=np.float64),
                original_indices=np.empty((0,), dtype=np.int64),
                total_points=0,
                classification=None,
                sampled=False,
            )
        if raw.size % 4 == 0:
            arr = raw.reshape(-1, 4)[:, :3]
        elif raw.size % 3 == 0:
            arr = raw.reshape(-1, 3)
        else:
            raise ValueError(f"pointcloud_bin_shape_error: {p}")
        arr2 = _coerce_xyz(arr, source=str(p))
        xyz, idx, sampled = _downsample_xyz(arr2, max_points=max_points)
        return PointCloudData(xyz=xyz, original_indices=idx, total_points=int(arr2.shape[0]), classification=None, sampled=sampled)

    if suffix in {".las", ".laz"}:
        return _load_las_laz_data(p, max_points=max_points)

    if suffix in {".ply", ".pcd"}:
        raise ValueError(f"unsupported_pointcloud_format_without_plugin: {p.suffix}")

    raise ValueError(f"unsupported_pointcloud_format: {p.suffix}")


def _load_las_laz_data(path: Path, *, max_points: int | None = None) -> PointCloudData:
    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on env
        raise ValueError("laspy_required_for_las_laz") from exc

    with laspy.open(str(path)) as reader:
        total_points = int(reader.header.point_count)
        if total_points == 0:
            return PointCloudData(
                xyz=np.empty((0, 3), dtype=np.float64),
                original_indices=np.empty((0,), dtype=np.int64),
                total_points=0,
                classification=None,
                sampled=False,
            )

        has_cls = "classification" in set(reader.header.point_format.dimension_names)

        if max_points is None or total_points <= max_points:
            las = reader.read()
            xyz = np.column_stack((las.x, las.y, las.z)).astype(np.float64)
            idx = np.arange(total_points, dtype=np.int64)
            cls = np.asarray(las.classification, dtype=np.int16) if has_cls and hasattr(las, "classification") else None
            return PointCloudData(
                xyz=xyz,
                original_indices=idx,
                total_points=total_points,
                classification=cls,
                sampled=False,
            )

        step = max(1, int(math.ceil(total_points / float(max_points))))
        xs: list[np.ndarray] = []
        ys: list[np.ndarray] = []
        zs: list[np.ndarray] = []
        idxs: list[np.ndarray] = []
        cls_chunks: list[np.ndarray] = []

        start = 0
        for chunk in reader.chunk_iterator(1_000_000):
            n = len(chunk.x)
            if n == 0:
                continue

            global_idx = np.arange(start, start + n, dtype=np.int64)
            take = (global_idx % step) == 0
            if np.any(take):
                xs.append(np.asarray(chunk.x, dtype=np.float64)[take])
                ys.append(np.asarray(chunk.y, dtype=np.float64)[take])
                zs.append(np.asarray(chunk.z, dtype=np.float64)[take])
                idxs.append(global_idx[take])

                if has_cls and hasattr(chunk, "classification"):
                    cls_chunks.append(np.asarray(chunk.classification, dtype=np.int16)[take])

            start += n

    xyz = np.column_stack((np.concatenate(xs), np.concatenate(ys), np.concatenate(zs))) if xs else np.empty((0, 3), dtype=np.float64)
    idx = np.concatenate(idxs) if idxs else np.empty((0,), dtype=np.int64)
    cls = np.concatenate(cls_chunks) if cls_chunks else None

    return PointCloudData(
        xyz=xyz,
        original_indices=idx,
        total_points=total_points,
        classification=cls,
        sampled=True,
    )


def _resolve_explicit_patch(root: Path, patch: str) -> PatchCandidate:
    p = Path(patch)

    direct_candidates: list[Path] = []
    if p.exists() and p.is_dir():
        direct_candidates.append(p)
    if not p.is_absolute():
        rp = (root / p)
        if rp.exists() and rp.is_dir():
            direct_candidates.append(rp)

    patch_name = patch.strip().strip("/")
    if patch_name:
        named = root / patch_name
        if named.exists() and named.is_dir():
            direct_candidates.append(named)

    seen: set[str] = set()
    for c in direct_candidates:
        key = c.resolve().as_posix()
        if key in seen:
            continue
        seen.add(key)
        candidate = _candidate_from_dir(c)
        if candidate is not None:
            return candidate

    matches = [c for c in list_patch_candidates(root) if c.patch_id == patch_name]
    if matches:
        return matches[0]

    raise ValueError(f"patch_not_resolvable: {patch}")


def _candidate_from_dir(patch_dir: Path) -> PatchCandidate | None:
    files = [p for p in patch_dir.rglob("*") if p.is_file()]
    if not files:
        return None

    traj_files = [p for p in files if p.suffix.lower() in TRAJ_EXTS and _is_traj_name(p.name)]
    point_files = [p for p in files if p.suffix.lower() in POINT_EXTS and _is_point_name(p)]

    if not traj_files or not point_files:
        return None

    traj = sorted(traj_files, key=_traj_rank_key)[0]
    points = sorted(point_files, key=_point_rank_key)[0]
    patch_id = _normalize_patch_id(patch_dir.name)

    return PatchCandidate(
        patch_id=patch_id,
        patch_dir=patch_dir,
        traj_path=traj,
        points_path=points,
    )


def _is_candidate_loadable(candidate: PatchCandidate, *, probe_max_points: int) -> bool:
    try:
        _ = load_traj_xyz(candidate.traj_path)
        _ = load_point_cloud_data(candidate.points_path, max_points=probe_max_points)
        return True
    except Exception:
        return False


def _normalize_patch_id(name: str) -> str:
    digits = "".join(ch for ch in name if ch.isdigit())
    if digits:
        return digits[-8:].zfill(8)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return safe or "patch"


def _is_traj_name(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in ("traj", "trajectory", "pose", "ego", "raw_dat_pose"))


def _is_point_name(path: Path) -> bool:
    n = path.name.lower()
    p = path.as_posix().lower()
    return (
        any(k in n for k in ("point", "points", "cloud", "lidar", "pc", "merged"))
        or "/pointcloud/" in p
    )


def _traj_rank_key(path: Path) -> tuple[int, int, int, str]:
    n = path.name.lower()
    return (
        0 if "raw_dat_pose" in n else 1,
        0 if path.suffix.lower() == ".geojson" else 1,
        0 if "traj" in n else 1,
        path.as_posix(),
    )


def _point_rank_key(path: Path) -> tuple[int, int, int, str]:
    n = path.name.lower()
    p = path.as_posix().lower()
    return (
        0 if n == "merged.laz" else 1,
        0 if n == "merged.las" else 1,
        0 if "/pointcloud/" in p else 1,
        path.as_posix(),
    )


def _safe_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 2**63 - 1


def _load_text_matrix(path: Path) -> np.ndarray:
    loaders = [
        lambda: np.loadtxt(path, delimiter=",", dtype=float, ndmin=2),
        lambda: np.loadtxt(path, dtype=float, ndmin=2),
    ]

    for fn in loaders:
        try:
            arr = fn()
            return np.asarray(arr, dtype=np.float64)
        except Exception:
            continue

    arr = np.genfromtxt(path, delimiter=",", names=True, dtype=float)
    return np.asarray(arr)


def _select_npz_array(npz: np.lib.npyio.NpzFile, priorities: Iterable[str]) -> np.ndarray:
    for key in priorities:
        if key in npz.files:
            return np.asarray(npz[key])

    if not npz.files:
        raise ValueError("empty_npz")

    for key in npz.files:
        arr = np.asarray(npz[key])
        if arr.ndim >= 2 and arr.shape[-1] >= 3:
            return arr

    return np.asarray(npz[npz.files[0]])


def _coerce_xyz(arr: np.ndarray, *, source: str) -> np.ndarray:
    a = np.asarray(arr)

    if a.dtype.names:
        names = {n.lower(): n for n in a.dtype.names}
        if {"x", "y", "z"}.issubset(names):
            return np.column_stack([a[names["x"]], a[names["y"]], a[names["z"]]]).astype(np.float64)

    if a.size == 0:
        return np.empty((0, 3), dtype=np.float64)

    if a.ndim == 1:
        if a.size % 3 != 0:
            raise ValueError(f"xyz_shape_error: {source}")
        a = a.reshape(-1, 3)

    if a.ndim >= 2:
        if a.shape[-1] < 3:
            raise ValueError(f"xyz_columns_lt3: {source}")
        a = a.reshape(-1, a.shape[-1])[:, :3]
        return a.astype(np.float64)

    raise ValueError(f"xyz_parse_error: {source}")


def _downsample_xyz(arr: np.ndarray, *, max_points: int | None) -> tuple[np.ndarray, np.ndarray, bool]:
    n = int(arr.shape[0])
    if max_points is None or n <= max_points:
        return arr.astype(np.float64), np.arange(n, dtype=np.int64), False

    step = max(1, int(math.ceil(n / float(max_points))))
    idx = np.arange(0, n, step, dtype=np.int64)
    return arr[idx].astype(np.float64), idx, True


def _load_geojson_xyz(path: Path) -> np.ndarray:
    payload = json.loads(path.read_text(encoding="utf-8"))

    pts: list[tuple[float, float, float]] = []

    if isinstance(payload, dict):
        ptype = str(payload.get("type", "")).lower()
        if ptype == "featurecollection":
            for feature in payload.get("features", []):
                if not isinstance(feature, dict):
                    continue
                properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
                default_z = _pick_default_z(properties)
                geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
                _append_coords(geometry.get("coordinates"), pts, default_z)
        elif ptype == "feature":
            properties = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
            default_z = _pick_default_z(properties)
            geometry = payload.get("geometry") if isinstance(payload.get("geometry"), dict) else {}
            _append_coords(geometry.get("coordinates"), pts, default_z)
        else:
            _append_coords(payload.get("coordinates"), pts, np.nan)
    elif isinstance(payload, list):
        _append_coords(payload, pts, np.nan)

    return np.asarray(pts, dtype=np.float64)


def _pick_default_z(properties: dict[str, object]) -> float:
    for key in ("z", "Z", "alt", "altitude", "height", "elevation"):
        val = properties.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    return float("nan")


def _append_coords(obj: object, out: list[tuple[float, float, float]], default_z: float) -> None:
    if obj is None:
        return

    if isinstance(obj, (list, tuple)) and obj:
        first = obj[0]

        if isinstance(first, (int, float)):
            if len(obj) < 2:
                return
            x = float(obj[0])
            y = float(obj[1])
            z = float(obj[2]) if len(obj) > 2 else float(default_z)
            out.append((x, y, z))
            return

        for child in obj:
            _append_coords(child, out, default_z)
