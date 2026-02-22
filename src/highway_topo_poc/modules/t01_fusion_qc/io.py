from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Iterator

import laspy
import numpy as np

from .types import CloudMeta, TrajectoryData


_TRAJ_SORT_FIELDS = ("seq", "idx", "frame", "timestamp", "time", "t")
_Z_PROP_KEYS = ("z", "alt", "altitude", "height", "h", "ele", "elevation")


def _to_float(v: object) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        vv = float(v)
        if math.isnan(vv):
            return None
        return vv
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            vv = float(s)
        except ValueError:
            return None
        if math.isnan(vv):
            return None
        return vv
    return None


def _to_sort_token(v: object) -> tuple[int, float | str] | None:
    n = _to_float(v)
    if n is not None:
        return (0, n)

    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None

        dt_value: datetime | None = None
        try:
            dt_value = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            dt_value = None

        if dt_value is not None:
            return (1, dt_value.timestamp())
        return (2, s)

    return None


def _choose_sort_field(rows: list[tuple[int, float, float, float, dict[str, object]]]) -> str | None:
    if not rows:
        return None

    for key in _TRAJ_SORT_FIELDS:
        tokens: list[tuple[int, float | str]] = []
        ok = True
        for _idx, _x, _y, _z, props in rows:
            if key not in props:
                ok = False
                break
            sort_token = _to_sort_token(props.get(key))
            if sort_token is None:
                ok = False
                break
            tokens.append(sort_token)

        if ok and len(tokens) == len(rows):
            return key

    return None


def read_traj_geojson(traj_path: Path) -> TrajectoryData:
    obj = json.loads(traj_path.read_text(encoding="utf-8"))
    feats = obj.get("features", [])

    rows: list[tuple[int, float, float, float, dict[str, object]]] = []
    for idx, feat in enumerate(feats):
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry")
        if not isinstance(geom, dict):
            continue
        if str(geom.get("type", "")).lower() != "point":
            continue
        coords = geom.get("coordinates")
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            continue

        x = _to_float(coords[0])
        y = _to_float(coords[1])
        if x is None or y is None:
            continue

        z = None
        if len(coords) >= 3:
            z = _to_float(coords[2])

        props_raw = feat.get("properties")
        props: dict[str, object] = {}
        if isinstance(props_raw, dict):
            for k, v in props_raw.items():
                props[str(k).lower()] = v

        if z is None:
            for k in _Z_PROP_KEYS:
                z = _to_float(props.get(k))
                if z is not None:
                    break

        rows.append((idx, x, y, float("nan") if z is None else z, props))

    if not rows:
        raise ValueError(f"traj_empty_or_invalid:{traj_path}")

    sort_field = _choose_sort_field(rows)
    if sort_field is not None:
        rows = sorted(rows, key=lambda r: (_to_sort_token(r[4].get(sort_field)), r[0]))

    x = np.asarray([r[1] for r in rows], dtype=np.float64)
    y = np.asarray([r[2] for r in rows], dtype=np.float64)
    z = np.asarray([r[3] for r in rows], dtype=np.float64)

    return TrajectoryData(x=x, y=y, z=z, sort_field=sort_field)


def _cloud_candidates(cloud_path: Path) -> list[Path]:
    candidates: list[Path] = []

    cp = cloud_path
    if cp.exists():
        candidates.append(cp)

    if cp.suffix.lower() == ".laz":
        alt = cp.with_suffix(".las")
        if alt.exists():
            candidates.append(alt)
    elif cp.suffix.lower() == ".las":
        laz = cp.with_suffix(".laz")
        if laz.exists():
            candidates.insert(0, laz)

    out: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        k = p.resolve().as_posix()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def resolve_cloud_meta(cloud_path: Path) -> CloudMeta:
    last_err: Exception | None = None
    for candidate in _cloud_candidates(cloud_path):
        try:
            with laspy.open(candidate) as reader:
                hdr = reader.header
                return CloudMeta(
                    used_cloud_path=candidate,
                    point_count=int(hdr.point_count),
                    min_x=float(hdr.mins[0]),
                    min_y=float(hdr.mins[1]),
                    max_x=float(hdr.maxs[0]),
                    max_y=float(hdr.maxs[1]),
                )
        except Exception as exc:  # pragma: no cover - depends on local LAZ codecs
            last_err = exc

    if last_err is None:
        raise FileNotFoundError(f"cloud_missing:{cloud_path}")
    raise RuntimeError(f"cloud_open_failed:{cloud_path}:{type(last_err).__name__}")


def read_cloud_arrays(cloud_path: Path) -> tuple[CloudMeta, np.ndarray, np.ndarray, np.ndarray]:
    meta = resolve_cloud_meta(cloud_path)
    las = laspy.read(meta.used_cloud_path)
    x = np.asarray(las.x, dtype=np.float64)
    y = np.asarray(las.y, dtype=np.float64)
    z = np.asarray(las.z, dtype=np.float64)
    return meta, x, y, z


def iter_cloud_xyz(cloud_path: Path, chunk_size: int = 500_000) -> tuple[CloudMeta, Iterator[tuple[np.ndarray, np.ndarray, np.ndarray]]]:
    meta = resolve_cloud_meta(cloud_path)

    def _iterator() -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        with laspy.open(meta.used_cloud_path) as reader:
            for points in reader.chunk_iterator(chunk_size):
                x = np.asarray(points.x, dtype=np.float64)
                y = np.asarray(points.y, dtype=np.float64)
                z = np.asarray(points.z, dtype=np.float64)
                yield x, y, z

    return meta, _iterator()
