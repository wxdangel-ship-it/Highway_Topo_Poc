from __future__ import annotations

import json
import os
import random
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MANIFEST_FILENAME = "patch_manifest.json"
SCHEMA_VERSION = "t00_synth_patch_manifest_v1"


@dataclass(frozen=True)
class SynthConfig:
    seed: int
    num_patches: int = 8
    out_dir: Path = Path("data/synth")
    lidar_dir: Path | None = None
    traj_dir: Path | None = None
    # auto|local|synthetic. Caller should resolve auto before calling run_synth.
    source_mode: str = "auto"
    # stub|link|copy. link/copy are only meaningful in local mode.
    pointcloud_mode: str = "stub"
    # synthetic|copy. copy is only meaningful in local mode.
    traj_mode: str = "synthetic"


@dataclass(frozen=True)
class StripSpec:
    patch_id: str
    traj_id: str
    lidar_strip_basename: str | None = None
    traj_file_basename: str | None = None
    lidar_laz_count: int | None = None
    lidar_strip_dir: Path | None = None
    traj_source_path: Path | None = None


def normalize_input_path(p: str) -> Path:
    """Normalize a user-provided path.

    Supports Windows drive-letter paths like "E:\\Work\\X" by mapping to /mnt/e/Work/X.

    Note: This is an internal helper; keep stdout/log output paste-friendly (avoid noisy path dumps).
    """

    s = p.strip()
    if not s:
        raise ValueError("empty_path")

    m = re.match(r"^([A-Za-z]):[\\/](.*)$", s)
    if m:
        drive = m.group(1).lower()
        rest = m.group(2).replace("\\", "/")
        return Path("/mnt") / drive / rest

    return Path(s)


def _extract_longest_digits(name: str) -> int | None:
    matches = list(re.finditer(r"\d+", name))
    if not matches:
        return None

    # Longest run wins; tie-breaker is earliest occurrence (stable).
    best = max(matches, key=lambda m: (len(m.group(0)), -m.start()))
    return int(best.group(0))


def _extract_patch_number(name: str) -> int | None:
    """Extract patch number from strip/trajectory basenames.

    Prefer KITTI-style drive ids like "...drive_0000_sync..." to avoid accidentally
    picking dates (2013/05/28) or other unrelated numbers.

    Fallback: longest consecutive digit run.
    """

    # Prefer drive_<id>_sync (more specific).
    m = re.findall(r"(?:^|[^A-Za-z0-9])drive_(\d+)_sync", name)
    if m:
        return int(m[-1])

    # Then drive_<id> anywhere.
    m = re.findall(r"(?:^|[^A-Za-z0-9])drive_(\d+)", name)
    if m:
        return int(m[-1])

    return _extract_longest_digits(name)


def _to_patch_id(n: int) -> str:
    return f"{n:08d}"


def _safe_clear_out_dir(out_dir: Path) -> None:
    """B: clear-and-rebuild, but only delete prior synth artifacts.

    Deletes:
    - <out_dir>/patch_manifest.json
    - Any immediate subdir whose name matches ^\\d{8}$

    Leaves everything else intact.
    """

    if not out_dir.exists():
        return

    mf = out_dir / MANIFEST_FILENAME
    if mf.is_file():
        mf.unlink()

    for child in out_dir.iterdir():
        if child.is_dir() and re.fullmatch(r"\d{8}", child.name):
            shutil.rmtree(child)


def _choose_best_traj_file(cands: list[Path]) -> Path:
    def _ext_pri(p: Path) -> int:
        ext = p.suffix.lower()
        if ext == ".gpkg":
            return 0
        if ext == ".geojson":
            return 1
        return 2

    return sorted(cands, key=lambda p: (_ext_pri(p), p.name))[0]


def discover_strips(lidar_dir: Path, traj_dir: Path, num_patches: int) -> list[StripSpec]:
    """Discover candidate strips from local sample dirs.

    Priority: lidar_dir subdirectories first; if insufficient, supplement from traj_dir files.

    Strip number is extracted from the basename (prefer KITTI-style drive ids like drive_0000_sync;
    fallback is the longest consecutive digit run), then zero-padded to 8 digits to form patch_id.

    Returned list is stably sorted by patch_id numeric ascending, then basename.
    """

    # patch_id -> (patch_int, basename, laz_count, strip_dir)
    lidar_map: dict[str, tuple[int, str, int, Path]] = {}
    for child in sorted(lidar_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        n = _extract_patch_number(child.name)
        if n is None:
            continue
        pid = _to_patch_id(n)
        laz_count = len([p for p in child.rglob("*.laz") if p.is_file()])
        prev = lidar_map.get(pid)
        if prev is None or child.name < prev[1]:
            lidar_map[pid] = (n, child.name, laz_count, child)

    # patch_id -> list[candidate_file_path]
    traj_candidates: dict[str, list[Path]] = {}
    for child in sorted(traj_dir.iterdir(), key=lambda p: p.name):
        if not child.is_file():
            continue
        n = _extract_patch_number(child.name)
        if n is None:
            continue
        pid = _to_patch_id(n)
        traj_candidates.setdefault(pid, []).append(child)

    # patch_id -> (patch_int, basename, path)
    traj_map: dict[str, tuple[int, str, Path]] = {}
    for pid, cands in traj_candidates.items():
        best = _choose_best_traj_file(cands)
        traj_map[pid] = (int(pid), best.name, best)

    lidar_sorted = sorted(lidar_map.items(), key=lambda kv: (kv[1][0], kv[1][1]))
    traj_sorted = sorted(traj_map.items(), key=lambda kv: (kv[1][0], kv[1][1]))

    chosen: list[str] = []

    for pid, _meta in lidar_sorted:
        if len(chosen) >= num_patches:
            break
        chosen.append(pid)

    if len(chosen) < num_patches:
        for pid, _meta in traj_sorted:
            if len(chosen) >= num_patches:
                break
            if pid in chosen:
                continue
            chosen.append(pid)

    if len(chosen) < num_patches:
        raise ValueError("insufficient_local_strips")

    specs: list[StripSpec] = []
    for pid in chosen:
        lidar_basename: str | None = None
        traj_basename: str | None = None
        laz_count: int | None = None
        lidar_strip_dir: Path | None = None
        traj_source_path: Path | None = None

        if pid in lidar_map:
            _n, lidar_basename, laz_count, lidar_strip_dir = lidar_map[pid]
        if pid in traj_map:
            _n, traj_basename, traj_source_path = traj_map[pid]

        specs.append(
            StripSpec(
                patch_id=pid,
                traj_id=pid,
                lidar_strip_basename=lidar_basename,
                traj_file_basename=traj_basename,
                lidar_laz_count=laz_count,
                lidar_strip_dir=lidar_strip_dir,
                traj_source_path=traj_source_path,
            )
        )

    # Stable output ordering.
    specs.sort(key=lambda s: (int(s.patch_id), s.lidar_strip_basename or "", s.traj_file_basename or ""))
    return specs


def _write_geojson(path: Path, obj: dict[str, Any]) -> None:
    payload = json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    path.write_text(payload, encoding="utf-8")


def _deterministic_line_coords(seed: int, patch_int: int, n_points: int = 20) -> list[list[float]]:
    """Deterministically generate 3D coordinates without embedding fixed examples in code."""

    rng = random.Random((seed << 32) + patch_int)
    x = rng.randrange(0, 1_000_000)
    y = rng.randrange(0, 1_000_000)
    z = rng.randrange(0, 10_000)

    coords: list[list[float]] = []
    for _ in range(n_points):
        x += rng.randrange(50, 150)
        y += rng.randrange(-80, 80)
        z += rng.randrange(-5, 5)
        coords.append([x / 100.0, y / 100.0, z / 100.0])

    return coords


def _gather_laz_files(strip_dir: Path) -> list[Path]:
    laz = [p for p in strip_dir.rglob("*.laz") if p.is_file()]
    laz.sort(key=lambda p: p.relative_to(strip_dir).as_posix())
    return laz


def _plan_laz_outputs(strip_dir: Path, src_files: list[Path]) -> list[tuple[Path, str]]:
    counts: dict[str, int] = {}
    for p in src_files:
        counts[p.name] = counts.get(p.name, 0) + 1

    planned: list[tuple[Path, str]] = []
    for src in src_files:
        if counts.get(src.name, 0) == 1:
            dst_name = src.name
        else:
            # Deterministic disambiguation for basename collisions.
            dst_name = src.relative_to(strip_dir).as_posix().replace("/", "__")
        planned.append((src, dst_name))

    return planned


def _symlink_relative(dst: Path, src: Path) -> None:
    if dst.exists() or dst.is_symlink():
        dst.unlink()

    # Prefer a relative link target to avoid absolute source paths embedded in the symlink.
    target = os.path.relpath(src, start=dst.parent)
    dst.symlink_to(target)


def _copy_file(dst: Path, src: Path) -> None:
    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)


def write_patch(
    *,
    spec: StripSpec,
    out_dir: Path,
    seed: int,
    pointcloud_mode: str,
    traj_mode: str,
) -> dict[str, Any]:
    patch_dir = out_dir / spec.patch_id

    pc_dir = patch_dir / "PointCloud"
    vec_dir = patch_dir / "Vector"
    traj_dir = patch_dir / "Traj" / spec.traj_id

    pc_dir.mkdir(parents=True, exist_ok=True)
    vec_dir.mkdir(parents=True, exist_ok=True)
    traj_dir.mkdir(parents=True, exist_ok=True)

    rel = lambda p: p.relative_to(out_dir).as_posix()

    # PointCloud
    pointcloud_stub = True
    pointcloud_files: list[str] = []

    if pointcloud_mode == "stub":
        laz_path = pc_dir / f"{spec.patch_id}.laz"
        laz_path.write_bytes(b"STUB_LAZ\n")
        pointcloud_files = [rel(laz_path)]
        pointcloud_stub = True
    else:
        if spec.lidar_strip_dir is None:
            raise ValueError("lidar_strip_missing")

        src_laz = _gather_laz_files(spec.lidar_strip_dir)
        if not src_laz:
            raise ValueError("no_laz_files")

        planned = _plan_laz_outputs(spec.lidar_strip_dir, src_laz)
        for src, dst_name in planned:
            dst = pc_dir / dst_name
            if pointcloud_mode == "link":
                _symlink_relative(dst=dst, src=src)
            elif pointcloud_mode == "copy":
                _copy_file(dst=dst, src=src)
            else:
                raise ValueError("invalid_pointcloud_mode")
            pointcloud_files.append(rel(dst))

        pointcloud_stub = False

    # Empty vectors
    empty_fc = {"type": "FeatureCollection", "features": []}
    lane_boundary = vec_dir / "LaneBoundary.geojson"
    gorearea = vec_dir / "gorearea.geojson"
    _write_geojson(lane_boundary, empty_fc)
    _write_geojson(gorearea, empty_fc)

    # Trajectory (LineString)
    coords = _deterministic_line_coords(seed=seed, patch_int=int(spec.patch_id))
    raw_pose = traj_dir / "raw_dat_pose.geojson"
    raw_obj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "patch_id": spec.patch_id,
                    "traj_id": spec.traj_id,
                    "point_count": len(coords),
                },
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        ],
    }
    _write_geojson(raw_pose, raw_obj)

    # Optional: copy a real trajectory sidecar file for local-real runs.
    traj_source_file: str | None = None
    traj_source_kind: str | None = None
    if traj_mode == "copy":
        if spec.traj_source_path is None:
            raise ValueError("traj_source_missing")

        ext = spec.traj_source_path.suffix.lower()
        kind = ext[1:] if ext.startswith(".") else (ext or "unknown")

        dst = traj_dir / f"source_traj{ext}"
        _copy_file(dst=dst, src=spec.traj_source_path)

        traj_source_file = rel(dst)
        traj_source_kind = kind

    patch_entry: dict[str, Any] = {
        "patch_id": spec.patch_id,
        "traj_id": spec.traj_id,
        "pointcloud_stub": pointcloud_stub,
        "pointcloud_files": pointcloud_files,
        "paths": {
            "pointcloud_laz": pointcloud_files,
            "vector_lane_boundary": rel(lane_boundary),
            "vector_gorearea": rel(gorearea),
            "traj_raw_dat_pose": rel(raw_pose),
        },
        "source": {
            "lidar_strip_basename": spec.lidar_strip_basename,
            "traj_file_basename": spec.traj_file_basename,
            "lidar_laz_count": spec.lidar_laz_count,
        },
    }

    if traj_source_file is not None:
        patch_entry["traj_source_file"] = traj_source_file
        patch_entry["traj_source_kind"] = traj_source_kind

    return patch_entry


def write_manifest(out_dir: Path, manifest: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / MANIFEST_FILENAME
    payload = json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    path.write_text(payload, encoding="utf-8")
    return path


def run_synth(cfg: SynthConfig) -> dict[str, Any]:
    if cfg.num_patches <= 0:
        raise ValueError("num_patches_must_be_positive")

    if cfg.pointcloud_mode not in {"stub", "link", "copy"}:
        raise ValueError("invalid_pointcloud_mode")
    if cfg.traj_mode not in {"synthetic", "copy"}:
        raise ValueError("invalid_traj_mode")

    if cfg.source_mode != "local":
        if cfg.pointcloud_mode != "stub":
            raise ValueError("pointcloud_mode_requires_local")
        if cfg.traj_mode != "synthetic":
            raise ValueError("traj_mode_requires_local")

    out_dir = Path(cfg.out_dir)

    _safe_clear_out_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if cfg.source_mode == "local":
        if cfg.lidar_dir is None or cfg.traj_dir is None:
            raise ValueError("local_inputs_missing")
        if not cfg.lidar_dir.exists() or not cfg.traj_dir.exists():
            raise ValueError("local_inputs_missing")

        specs = discover_strips(cfg.lidar_dir, cfg.traj_dir, cfg.num_patches)
    elif cfg.source_mode == "synthetic":
        specs = [
            StripSpec(patch_id=_to_patch_id(i + 1), traj_id=_to_patch_id(i + 1))
            for i in range(cfg.num_patches)
        ]
    else:
        raise ValueError("invalid_source_mode")

    patches: list[dict[str, Any]] = []
    for spec in specs:
        patches.append(
            write_patch(
                spec=spec,
                out_dir=out_dir,
                seed=cfg.seed,
                pointcloud_mode=cfg.pointcloud_mode,
                traj_mode=cfg.traj_mode,
            )
        )

    patches.sort(key=lambda p: int(p["patch_id"]))

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "seed": int(cfg.seed),
        "num_patches": int(cfg.num_patches),
        "source_mode": cfg.source_mode,
        "pointcloud_mode": cfg.pointcloud_mode,
        "traj_mode": cfg.traj_mode,
        "patches": patches,
    }

    write_manifest(out_dir, manifest)
    return manifest
