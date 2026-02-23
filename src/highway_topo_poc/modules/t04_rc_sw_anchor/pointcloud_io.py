from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import LineString


@dataclass(frozen=True)
class PointCloudData:
    xy: np.ndarray
    classification: np.ndarray | None
    source_path: Path
    source_kind: str
    usable: bool
    reason: str | None


_EMPTY_XY = np.zeros((0, 2), dtype=np.float64)


def _empty_pc(path: Path, kind: str, reason: str) -> PointCloudData:
    return PointCloudData(
        xy=_EMPTY_XY,
        classification=None,
        source_path=path,
        source_kind=kind,
        usable=False,
        reason=reason,
    )


def _load_las_like(path: Path, *, use_classification: bool) -> PointCloudData:
    try:
        import laspy  # type: ignore
    except Exception:
        return _empty_pc(path, "las", "laspy_missing")

    try:
        las = laspy.read(str(path))
    except Exception as exc:  # noqa: BLE001
        return _empty_pc(path, "las", f"las_read_failed:{type(exc).__name__}")

    x = np.asarray(las.x, dtype=np.float64)
    y = np.asarray(las.y, dtype=np.float64)
    if x.size == 0:
        return _empty_pc(path, "las", "pointcloud_empty")

    xy = np.column_stack([x, y])

    cls: np.ndarray | None = None
    try:
        dims = set(las.point_format.dimension_names)
        if "classification" in dims:
            cls = np.asarray(las.classification, dtype=np.int32)
    except Exception:
        cls = None

    if use_classification and cls is None:
        return PointCloudData(
            xy=xy,
            classification=None,
            source_path=path,
            source_kind="las",
            usable=False,
            reason="classification_missing",
        )

    return PointCloudData(
        xy=xy,
        classification=cls,
        source_path=path,
        source_kind="las",
        usable=True,
        reason=None,
    )


def _load_geojson_fallback(path: Path, *, use_classification: bool) -> PointCloudData:
    """Test-only fallback: read PointCloud/merged.geojson Point features."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return _empty_pc(path, "geojson", f"geojson_parse_failed:{type(exc).__name__}")

    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        return _empty_pc(path, "geojson", "geojson_not_feature_collection")

    feats = payload.get("features")
    if not isinstance(feats, list):
        return _empty_pc(path, "geojson", "geojson_features_not_list")

    xy_list: list[tuple[float, float]] = []
    cls_list: list[int] = []
    cls_present = True

    for feat in feats:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry")
        if not isinstance(geom, dict) or geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            continue

        try:
            x = float(coords[0])
            y = float(coords[1])
        except Exception:
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue

        props = feat.get("properties")
        props = props if isinstance(props, dict) else {}
        c = props.get("classification", props.get("class"))
        if c is None:
            cls_present = False
            cls_list.append(0)
        else:
            try:
                cls_list.append(int(c))
            except Exception:
                cls_present = False
                cls_list.append(0)

        xy_list.append((x, y))

    if not xy_list:
        return _empty_pc(path, "geojson", "pointcloud_empty")

    xy = np.asarray(xy_list, dtype=np.float64)
    cls = np.asarray(cls_list, dtype=np.int32) if cls_present else None

    if use_classification and cls is None:
        return PointCloudData(
            xy=xy,
            classification=None,
            source_path=path,
            source_kind="geojson",
            usable=False,
            reason="classification_missing",
        )

    return PointCloudData(
        xy=xy,
        classification=cls,
        source_path=path,
        source_kind="geojson",
        usable=True,
        reason=None,
    )


def load_pointcloud(
    *,
    patch_dir: Path,
    use_classification: bool,
) -> PointCloudData | None:
    pc_dir = patch_dir / "PointCloud"
    laz = pc_dir / "merged.laz"
    las = pc_dir / "merged.las"

    if laz.is_file():
        return _load_las_like(laz, use_classification=use_classification)
    if las.is_file():
        return _load_las_like(las, use_classification=use_classification)

    # test-only fallback
    merged_geojson = pc_dir / "merged.geojson"
    if merged_geojson.is_file():
        return _load_geojson_fallback(merged_geojson, use_classification=use_classification)

    return None


def count_non_ground_points_near_line(
    *,
    line: LineString,
    pointcloud: PointCloudData,
    line_buffer_m: float,
    ground_class: int,
    use_classification: bool,
    ignore_end_margin_m: float,
) -> int:
    if pointcloud.xy.size == 0:
        return 0

    coords = list(line.coords)
    if len(coords) < 2:
        return 0

    p0 = np.asarray([float(coords[0][0]), float(coords[0][1])], dtype=np.float64)
    p1 = np.asarray([float(coords[-1][0]), float(coords[-1][1])], dtype=np.float64)
    v = p1 - p0
    seg_len2 = float(np.dot(v, v))
    if seg_len2 <= 1e-12:
        return 0

    seg_len = math.sqrt(seg_len2)
    w = pointcloud.xy - p0[None, :]
    t = np.sum(w * v[None, :], axis=1) / seg_len2
    t_clamped = np.clip(t, 0.0, 1.0)
    proj = p0[None, :] + t_clamped[:, None] * v[None, :]
    diff = pointcloud.xy - proj
    dist = np.sqrt(np.sum(diff * diff, axis=1))

    mask = dist <= float(line_buffer_m)

    if ignore_end_margin_m > 0.0 and seg_len > 1e-9:
        t_min = float(ignore_end_margin_m) / seg_len
        t_max = 1.0 - t_min
        if t_min < t_max:
            mask = mask & (t_clamped >= t_min) & (t_clamped <= t_max)
        else:
            mask = np.zeros_like(mask, dtype=bool)

    if use_classification:
        if pointcloud.classification is None:
            return 0
        ng = pointcloud.classification != int(ground_class)
        mask = mask & ng

    return int(np.count_nonzero(mask))


__all__ = ["PointCloudData", "count_non_ground_points_near_line", "load_pointcloud"]
