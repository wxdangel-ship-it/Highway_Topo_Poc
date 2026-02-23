from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


MANIFEST_FILENAME = "patch_manifest.json"
SCHEMA_VERSION = "t00_synth_patch_manifest_v3"
ROAD_FILENAME = "Road.geojson"
TILES_DIRNAME = "Tiles"


@dataclass(frozen=True)
class SynthConfig:
    seed: int
    num_patches: int = 8
    out_dir: Path = Path("data/synth")
    lidar_dir: Path | None = None
    traj_dir: Path | None = None
    # auto|local|synthetic. Caller should resolve auto before calling run_synth.
    source_mode: str = "auto"
    # stub|link|copy|merge. link/copy/merge are only meaningful in local mode.
    pointcloud_mode: str = "stub"
    # synthetic|copy|convert. copy/convert are only meaningful in local mode.
    traj_mode: str = "synthetic"
    # mkdir_empty|copy_if_exists. default avoids copying large raster data.
    tiles_mode: str = "mkdir_empty"


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

    Supports Windows drive-letter paths like "<DRIVE>:\\path\\to\\dir" by mapping to
    "/mnt/<drive>/path/to/dir".

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
    def _score(p: Path) -> tuple[int, int, int, str]:
        ext = p.suffix.lower()
        if ext == ".gpkg":
            ext_pri = 0
        elif ext == ".geojson":
            ext_pri = 1
        else:
            ext_pri = 2

        name = p.name.lower()
        # Prefer utm32 (local-real inputs); deprioritize buffer/100m derived files.
        utm_pri = 0 if "utm32" in name else 1
        bad_pri = 1 if ("buf" in name or "buffer" in name or re.search(r"(^|[^0-9])100([^0-9]|$)", name)) else 0

        return (ext_pri, bad_pri, utm_pri, p.name)

    return sorted(cands, key=_score)[0]


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


def write_empty_fc(
    path: Path,
    geom_type: str | None = None,
    properties_schema_hint: dict[str, str] | None = None,
) -> None:
    """Write a minimal valid GeoJSON FeatureCollection.

    geom_type/properties_schema_hint are hints for call-site readability and
    future schema extensions; current file payload intentionally stays minimal.
    """

    _ = (geom_type, properties_schema_hint)
    _write_geojson(path, {"type": "FeatureCollection", "features": []})


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


def _candidate_source_patch_dirs(spec: StripSpec) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path | None) -> None:
        if p is None:
            return
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            return
        seen.add(key)
        candidates.append(p)

    _add(spec.lidar_strip_dir)
    _add(spec.lidar_strip_dir.parent if spec.lidar_strip_dir is not None else None)
    if spec.lidar_strip_dir is not None:
        _add(spec.lidar_strip_dir.parent / spec.patch_id)
        _add(spec.lidar_strip_dir.parent / "patches" / spec.patch_id)

    if spec.traj_source_path is not None:
        _add(spec.traj_source_path.parent)
        _add(spec.traj_source_path.parent.parent)
        _add(spec.traj_source_path.parent.parent.parent)
        _add(spec.traj_source_path.parent.parent / spec.patch_id)
        _add(spec.traj_source_path.parent.parent / "patches" / spec.patch_id)

    valid: list[Path] = []
    for p in candidates:
        if not p.exists() or not p.is_dir():
            continue
        has_vector = (p / "Vector").is_dir()
        has_traj = (p / "Traj").is_dir()
        has_pc = (p / "PointCloud").is_dir()
        if has_vector and (has_traj or has_pc):
            valid.append(p)
    return valid


def _find_source_road_geojson(spec: StripSpec) -> Path | None:
    for patch_dir in _candidate_source_patch_dirs(spec):
        cand = patch_dir / "Vector" / ROAD_FILENAME
        if cand.is_file():
            return cand
    return None


def _find_source_tiles_dir(spec: StripSpec) -> Path | None:
    for patch_dir in _candidate_source_patch_dirs(spec):
        cand = patch_dir / TILES_DIRNAME
        if cand.is_dir():
            return cand
    return None


def _copy_tree_contents(src_dir: Path, dst_dir: Path) -> int:
    """Copy a directory tree and return copied regular-file count."""
    copied_files = 0
    for item in sorted(src_dir.rglob("*")):
        rel = item.relative_to(src_dir)
        dst = dst_dir / rel
        if item.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        if not item.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dst)
        copied_files += 1
    return copied_files


def _require_laspy() -> Any:
    try:
        import laspy  # type: ignore
    except Exception as e:  # pragma: no cover
        raise ValueError("pointcloud_merge_requires_laspy_lazrs") from e
    return laspy


def _merge_laz_files(*, src_files: list[Path], dst_file: Path) -> tuple[int, int]:
    """Merge multiple LAZ parts into a single LAZ file deterministically.

    Returns: (parts_count, total_points)
    """

    laspy = _require_laspy()
    if not src_files:
        raise ValueError("no_laz_files")

    # Determinism: stable order, and deterministic header fields.
    src_files = sorted(src_files, key=lambda p: p.name)
    chunk_size = 500_000

    try:
        with laspy.open(src_files[0]) as r0:
            header = r0.header.copy()
            # Avoid non-deterministic header fields (e.g., today's date).
            header.creation_date = date(2000, 1, 1)
            header.system_identifier = "Highway_Topo_Poc"
            header.generating_software = "t00_synth_data"

            with laspy.open(dst_file, mode="w", header=header) as w:
                total_points = 0
                for src in src_files:
                    with laspy.open(src) as r:
                        if r.header.point_format != header.point_format or r.header.version != header.version:
                            raise ValueError("incompatible_laz_header")
                        if tuple(r.header.scales) != tuple(header.scales) or tuple(r.header.offsets) != tuple(header.offsets):
                            raise ValueError("incompatible_laz_scale_offset")

                        for pts in r.chunk_iterator(chunk_size):
                            w.write_points(pts)
                            total_points += len(pts)

        return (len(src_files), total_points)
    except ValueError:
        raise
    except Exception as e:  # pragma: no cover
        raise ValueError("pointcloud_merge_failed") from e


def _gpkg_select_feature_table(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features' ORDER BY table_name"
    ).fetchall()
    if not rows:
        raise ValueError("gpkg_no_feature_tables")

    tables = [r[0] for r in rows if isinstance(r[0], str)]
    if not tables:
        raise ValueError("gpkg_no_feature_tables")

    def _score(name: str) -> tuple[int, str]:
        n = name.lower()
        if "frame_points" in n:
            pri = 0
        elif "pose" in n:
            pri = 1
        else:
            pri = 2
        return (pri, name)

    return sorted(tables, key=_score)[0]


def _gpkg_get_geom_col_and_srs(conn: sqlite3.Connection, table: str) -> tuple[str, int]:
    row = conn.execute(
        "SELECT column_name, srs_id FROM gpkg_geometry_columns WHERE table_name=?",
        (table,),
    ).fetchone()
    if not row:
        raise ValueError("gpkg_missing_geometry_columns")
    geom_col = str(row[0])
    srs_id = int(row[1])
    return geom_col, srs_id


def _gpkg_table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return [str(c) for c in cols if c]


def _gpkg_order_by(columns: list[str]) -> str:
    for c in [
        "frame_id",
        "frame",
        "idx",
        "index",
        "seq",
        "sequence",
        "t",
        "time",
        "timestamp",
        "stamp",
    ]:
        if c in columns:
            return f"ORDER BY {c}"
    return "ORDER BY rowid"


def _gpkg_pick_props(columns: list[str], geom_col: str) -> list[str]:
    # Keep small, useful fields only; avoid dumping large attributes.
    allow = {
        "drive_id",
        "frame_id",
        "frame",
        "frame_idx",
        "idx",
        "index",
        "seq",
        "sequence",
        "t",
        "time",
        "timestamp",
        "stamp",
        "gps_time",
    }
    return [c for c in columns if c != geom_col and c in allow]


def _parse_gpkg_point(blob: bytes) -> tuple[list[float], bool]:
    """Parse a GeoPackage geometry blob containing a Point/PointZ.

    Returns: (coords, has_z)
    """

    if len(blob) < 16 or blob[0:2] != b"GP":
        raise ValueError("gpkg_geom_invalid_header")

    flags = blob[3]

    def _env_len(ind: int) -> int:
        if ind == 0:
            return 0
        if ind == 1:
            return 4 * 8
        if ind == 2:
            return 6 * 8
        if ind == 3:
            return 6 * 8
        if ind == 4:
            return 8 * 8
        # Unknown indicator; fall back to 0 and let WKB probe below fail if needed.
        return 0

    # Try a few interpretations to locate the WKB start reliably.
    cand_env_inds = [
        (flags >> 1) & 0x07,
        flags & 0x07,
        (flags >> 4) & 0x07,
    ]
    wkb_offsets = [8 + _env_len(ind) for ind in cand_env_inds]

    last_err: Exception | None = None
    for off in wkb_offsets:
        if off >= len(blob):
            continue
        bo = blob[off]
        if bo not in (0, 1):
            continue
        endian = "<" if bo == 1 else ">"

        try:
            import struct

            if off + 1 + 4 + 16 > len(blob):
                raise ValueError("gpkg_wkb_too_short")
            gtype = struct.unpack(endian + "I", blob[off + 1 : off + 5])[0]

            # Support OGC WKB (1000 offset) and EWKB-style Z/M flags.
            has_z = False
            has_m = False
            base = gtype
            if gtype >= 1000 and gtype < 4000:
                base = gtype % 1000
                has_z = 1000 <= gtype < 2000 or 3000 <= gtype < 4000
                has_m = 2000 <= gtype < 3000 or 3000 <= gtype < 4000
            else:
                # EWKB high-bit flags.
                base = gtype & 0x1FFFFFFF
                has_z = bool(gtype & 0x80000000)
                has_m = bool(gtype & 0x40000000)

            if base != 1:
                raise ValueError("gpkg_not_point")

            cur = off + 5
            x = struct.unpack(endian + "d", blob[cur : cur + 8])[0]
            y = struct.unpack(endian + "d", blob[cur + 8 : cur + 16])[0]
            cur += 16
            coords: list[float] = [float(x), float(y)]
            if has_z:
                if cur + 8 > len(blob):
                    raise ValueError("gpkg_pointz_truncated")
                z = struct.unpack(endian + "d", blob[cur : cur + 8])[0]
                coords.append(float(z))
                cur += 8
            if has_m:
                # Ignore M if present.
                pass

            return coords, has_z
        except Exception as e:
            last_err = e
            continue

    raise ValueError("gpkg_geom_parse_failed") from last_err


def _convert_gpkg_to_raw_dat_pose_geojson(*, gpkg_path: Path, out_geojson: Path) -> tuple[int, int]:
    """Convert a *_utm32.gpkg trajectory file to raw_dat_pose.geojson (Point features).

    Returns: (srs_id, feature_count)
    """

    conn = sqlite3.connect(str(gpkg_path))
    try:
        table = _gpkg_select_feature_table(conn)
        geom_col, srs_id = _gpkg_get_geom_col_and_srs(conn, table)
        cols = _gpkg_table_columns(conn, table)
        props_cols = _gpkg_pick_props(cols, geom_col)
        order_by = _gpkg_order_by(cols)

        select_cols = [geom_col, *props_cols]
        sql = f"SELECT {', '.join(select_cols)} FROM {table} {order_by}"
        cur = conn.execute(sql)

        features: list[dict[str, Any]] = []
        for row in cur.fetchall():
            geom = row[0]
            if geom is None:
                continue
            if not isinstance(geom, (bytes, bytearray)):
                continue

            coords, has_z = _parse_gpkg_point(bytes(geom))

            props: dict[str, Any] = {}
            for i, col in enumerate(props_cols, start=1):
                props[col] = row[i]

            if not has_z:
                # If geometry is 2D, keep coordinates 2D.
                coords = coords[:2]

            features.append(
                {
                    "type": "Feature",
                    "properties": props,
                    "geometry": {"type": "Point", "coordinates": coords},
                }
            )

        obj: dict[str, Any] = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": f"EPSG:{srs_id}"}},
            "features": features,
        }
        _write_geojson(out_geojson, obj)
        return (srs_id, len(features))
    finally:
        conn.close()


def write_patch(
    *,
    spec: StripSpec,
    out_dir: Path,
    seed: int,
    pointcloud_mode: str,
    traj_mode: str,
    tiles_mode: str,
) -> dict[str, Any]:
    patch_dir = out_dir / spec.patch_id

    pc_dir = patch_dir / "PointCloud"
    vec_dir = patch_dir / "Vector"
    tiles_dir = patch_dir / TILES_DIRNAME
    traj_dir = patch_dir / "Traj" / spec.traj_id

    pc_dir.mkdir(parents=True, exist_ok=True)
    vec_dir.mkdir(parents=True, exist_ok=True)
    tiles_dir.mkdir(parents=True, exist_ok=True)
    traj_dir.mkdir(parents=True, exist_ok=True)

    rel = lambda p: p.relative_to(out_dir).as_posix()

    # PointCloud
    pointcloud_stub = True
    pointcloud_files: list[str] = []
    pointcloud_parts_count: int | None = None

    if pointcloud_mode == "stub":
        laz_path = pc_dir / f"{spec.patch_id}.laz"
        laz_path.write_bytes(b"STUB_LAZ\n")
        pointcloud_files = [rel(laz_path)]
        pointcloud_stub = True
    elif pointcloud_mode == "merge":
        if spec.lidar_strip_dir is None:
            raise ValueError("lidar_strip_missing")

        src_laz = _gather_laz_files(spec.lidar_strip_dir)
        if not src_laz:
            raise ValueError("no_laz_files")

        dst = pc_dir / "merged.laz"
        parts_count, _total_points = _merge_laz_files(src_files=src_laz, dst_file=dst)
        pointcloud_files = [rel(dst)]
        pointcloud_stub = False
        pointcloud_parts_count = int(parts_count)
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

    # Vector schema v3 skeletons (can be empty but must be valid FeatureCollection files).
    lane_boundary = vec_dir / "LaneBoundary.geojson"
    div_strip_zone = vec_dir / "DivStripZone.geojson"
    node_geojson = vec_dir / "Node.geojson"
    intersection_l = vec_dir / "intersection_l.geojson"
    road_geojson = vec_dir / ROAD_FILENAME
    write_empty_fc(lane_boundary, "LineString")
    write_empty_fc(div_strip_zone)
    write_empty_fc(
        node_geojson,
        "Point",
        {"Kind": "int32", "mainid": "int64", "id": "int64"},
    )
    write_empty_fc(intersection_l, "LineString", {"nodeid": "int64"})

    road_source_file: str | None = None
    src_road = _find_source_road_geojson(spec)
    if src_road is not None:
        _copy_file(dst=road_geojson, src=src_road)
        road_source_file = str(src_road)
    else:
        write_empty_fc(
            road_geojson,
            "LineString",
            {"direction": "int8", "snodeid": "int64", "enodeid": "int64"},
        )

    copied_tiles_files = 0
    tiles_source_dir: str | None = None
    if tiles_mode == "copy_if_exists":
        src_tiles = _find_source_tiles_dir(spec)
        if src_tiles is not None:
            copied_tiles_files = _copy_tree_contents(src_tiles, tiles_dir)
            tiles_source_dir = str(src_tiles)

    raw_pose = traj_dir / "raw_dat_pose.geojson"

    # Optional: copy a real trajectory sidecar file for local-real runs.
    traj_source_file: str | None = None
    traj_source_kind: str | None = None
    if traj_mode in {"copy", "convert"}:
        if spec.traj_source_path is None:
            raise ValueError("traj_source_missing")

        ext = spec.traj_source_path.suffix.lower()
        kind = ext[1:] if ext.startswith(".") else (ext or "unknown")

        if traj_mode == "convert" and ext != ".gpkg":
            raise ValueError("traj_convert_requires_gpkg")

        dst = traj_dir / f"source_traj{ext}"
        _copy_file(dst=dst, src=spec.traj_source_path)

        traj_source_file = rel(dst)
        traj_source_kind = kind

    # Trajectory raw_dat_pose.geojson
    if traj_mode == "convert":
        # Convert from the copied GPKG to a CRS-annotated GeoJSON (Point features).
        _convert_gpkg_to_raw_dat_pose_geojson(gpkg_path=traj_dir / "source_traj.gpkg", out_geojson=raw_pose)
    else:
        # Synthetic fallback (LineString).
        coords = _deterministic_line_coords(seed=seed, patch_int=int(spec.patch_id))
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

    patch_entry: dict[str, Any] = {
        "patch_id": spec.patch_id,
        "traj_id": spec.traj_id,
        "pointcloud_stub": pointcloud_stub,
        "pointcloud_files": pointcloud_files,
        "paths": {
            "pointcloud_laz": pointcloud_files,
            "vector_lane_boundary": rel(lane_boundary),
            "vector_div_strip_zone": rel(div_strip_zone),
            "vector_node": rel(node_geojson),
            "vector_intersection_l": rel(intersection_l),
            "vector_road": rel(road_geojson),
            "tiles_dir": rel(tiles_dir),
            "traj_raw_dat_pose": rel(raw_pose),
        },
        "source": {
            "lidar_strip_basename": spec.lidar_strip_basename,
            "traj_file_basename": spec.traj_file_basename,
            "lidar_laz_count": spec.lidar_laz_count,
            "road_source_file": road_source_file,
            "tiles_source_dir": tiles_source_dir,
        },
    }

    if pointcloud_parts_count is not None:
        patch_entry["pointcloud_parts_count"] = pointcloud_parts_count

    if traj_source_file is not None:
        patch_entry["traj_source_file"] = traj_source_file
        patch_entry["traj_source_kind"] = traj_source_kind

    if copied_tiles_files > 0:
        patch_entry["copied_tiles_files"] = int(copied_tiles_files)

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

    if cfg.pointcloud_mode not in {"stub", "link", "copy", "merge"}:
        raise ValueError("invalid_pointcloud_mode")
    if cfg.traj_mode not in {"synthetic", "copy", "convert"}:
        raise ValueError("invalid_traj_mode")
    if cfg.tiles_mode not in {"mkdir_empty", "copy_if_exists"}:
        raise ValueError("invalid_tiles_mode")

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
                tiles_mode=cfg.tiles_mode,
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
        "tiles_mode": cfg.tiles_mode,
        "patches": patches,
    }

    write_manifest(out_dir, manifest)
    return manifest
