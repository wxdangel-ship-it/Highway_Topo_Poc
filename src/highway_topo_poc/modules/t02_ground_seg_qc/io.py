from __future__ import annotations

import json
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


def discover_patch(data_root: Path | str, patch: str = "auto") -> PatchCandidate:
    root = Path(data_root)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"data_root_not_found: {root}")

    if patch != "auto":
        return _resolve_explicit_patch(root, patch)

    candidates = list_patch_candidates(root)
    if not candidates:
        raise ValueError(f"no_patch_candidate_found_under: {root}")
    return sorted(candidates, key=lambda c: (c.patch_id, c.patch_dir.as_posix()))[0]


def list_patch_candidates(data_root: Path | str) -> list[PatchCandidate]:
    root = Path(data_root)
    if not root.exists() or not root.is_dir():
        return []

    out: list[PatchCandidate] = []
    for patch_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        candidate = _candidate_from_dir(patch_dir)
        if candidate is not None:
            out.append(candidate)
    return out


def load_patch_arrays(candidate: PatchCandidate) -> tuple[np.ndarray, np.ndarray]:
    traj_xyz = load_traj_xyz(candidate.traj_path)
    points_xyz = load_point_cloud_xyz(candidate.points_path)
    return traj_xyz, points_xyz


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
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".npy":
        arr = np.load(p)
        return _coerce_xyz(arr, source=str(p))
    if suffix == ".npz":
        with np.load(p) as npz:
            arr = _select_npz_array(npz, priorities=("points", "pointcloud", "pc", "xyz", "arr_0"))
        return _coerce_xyz(arr, source=str(p))
    if suffix in {".csv", ".txt"}:
        arr = _load_text_matrix(p)
        return _coerce_xyz(arr, source=str(p))
    if suffix == ".bin":
        raw = np.fromfile(p, dtype=np.float32)
        if raw.size == 0:
            return np.empty((0, 3), dtype=np.float64)
        if raw.size % 4 == 0:
            arr = raw.reshape(-1, 4)[:, :3]
            return _coerce_xyz(arr, source=str(p))
        if raw.size % 3 == 0:
            arr = raw.reshape(-1, 3)
            return _coerce_xyz(arr, source=str(p))
        raise ValueError(f"pointcloud_bin_shape_error: {p}")
    if suffix in {".las", ".laz"}:
        try:
            import laspy  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on env
            raise ValueError("laspy_required_for_las_laz") from exc

        las = laspy.read(str(p))
        arr = np.column_stack((las.x, las.y, las.z))
        return _coerce_xyz(arr, source=str(p))

    if suffix in {".ply", ".pcd"}:
        raise ValueError(f"unsupported_pointcloud_format_without_plugin: {p.suffix}")

    raise ValueError(f"unsupported_pointcloud_format: {p.suffix}")


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

    # Fallback: find by patch_id among auto-discovered candidates.
    matches = [c for c in list_patch_candidates(root) if c.patch_id == patch_name]
    if matches:
        return sorted(matches, key=lambda c: c.patch_dir.as_posix())[0]

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

    # With header names (x,y,z)
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
