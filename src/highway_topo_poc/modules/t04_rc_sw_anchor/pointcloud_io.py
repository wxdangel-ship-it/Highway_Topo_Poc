from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .io_geojson import infer_lonlat_like_bbox


@dataclass(frozen=True)
class PointCloudData:
    xy: np.ndarray
    classification: np.ndarray | None
    source_path: Path
    source_kind: str
    usable: bool
    reason: str | None
    class_counts: dict[str, int]
    bbox: tuple[float, float, float, float] | None
    lonlat_like: bool


_EMPTY_XY = np.zeros((0, 2), dtype=np.float64)


def _empty_pc(path: Path, kind: str, reason: str) -> PointCloudData:
    return PointCloudData(
        xy=_EMPTY_XY,
        classification=None,
        source_path=path,
        source_kind=kind,
        usable=False,
        reason=reason,
        class_counts={},
        bbox=None,
        lonlat_like=False,
    )


def default_pointcloud_path(patch_dir: Path) -> Path | None:
    pc_dir = patch_dir / "PointCloud"
    cands = [
        pc_dir / "merged_cleaned_classified_3857.laz",
        pc_dir / "merged_cleaned_classified_3857.las",
        pc_dir / "merged.laz",
        pc_dir / "merged.las",
        pc_dir / "merged.geojson",
    ]
    for p in cands:
        if p.is_file():
            return p
    return None


def _bbox_from_xy(xy: np.ndarray) -> tuple[float, float, float, float] | None:
    if xy.size == 0:
        return None
    min_x = float(np.min(xy[:, 0]))
    min_y = float(np.min(xy[:, 1]))
    max_x = float(np.max(xy[:, 0]))
    max_y = float(np.max(xy[:, 1]))
    return (min_x, min_y, max_x, max_y)


def _class_counts(cls: np.ndarray | None) -> dict[str, int]:
    if cls is None or cls.size == 0:
        return {}
    vals, counts = np.unique(cls.astype(np.int64), return_counts=True)
    out: dict[str, int] = {}
    for v, c in zip(vals.tolist(), counts.tolist()):
        out[str(int(v))] = int(c)
    return out


def pointcloud_bbox(path: Path) -> tuple[float, float, float, float] | None:
    if not path.is_file():
        return None
    suffix = path.suffix.lower()
    if suffix in {".laz", ".las"}:
        try:
            import laspy  # type: ignore
        except Exception:
            return None
        try:
            with laspy.open(str(path)) as reader:
                hdr = reader.header
                min_x, min_y = float(hdr.mins[0]), float(hdr.mins[1])
                max_x, max_y = float(hdr.maxs[0]), float(hdr.maxs[1])
                return (min_x, min_y, max_x, max_y)
        except Exception:
            return None

    if suffix == ".geojson":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            return None
        feats = payload.get("features")
        if not isinstance(feats, list):
            return None
        xs: list[float] = []
        ys: list[float] = []
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
            xs.append(x)
            ys.append(y)
        if not xs:
            return None
        return (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))

    return None


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
            class_counts={},
            bbox=_bbox_from_xy(xy),
            lonlat_like=False,
        )

    bbox = _bbox_from_xy(xy)
    lonlat_like = False
    if bbox is not None:
        lonlat_like = infer_lonlat_like_bbox(*bbox)

    return PointCloudData(
        xy=xy,
        classification=cls,
        source_path=path,
        source_kind="las",
        usable=True,
        reason=None,
        class_counts=_class_counts(cls),
        bbox=bbox,
        lonlat_like=lonlat_like,
    )


def _load_geojson_fallback(path: Path, *, use_classification: bool) -> PointCloudData:
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
            class_counts={},
            bbox=_bbox_from_xy(xy),
            lonlat_like=False,
        )

    bbox = _bbox_from_xy(xy)
    lonlat_like = False
    if bbox is not None:
        lonlat_like = infer_lonlat_like_bbox(*bbox)

    return PointCloudData(
        xy=xy,
        classification=cls,
        source_path=path,
        source_kind="geojson",
        usable=True,
        reason=None,
        class_counts=_class_counts(cls),
        bbox=bbox,
        lonlat_like=lonlat_like,
    )


def load_pointcloud(*, path: Path, use_classification: bool) -> PointCloudData:
    suffix = path.suffix.lower()
    if suffix in {".laz", ".las"}:
        return _load_las_like(path, use_classification=use_classification)
    if suffix == ".geojson":
        return _load_geojson_fallback(path, use_classification=use_classification)
    return _empty_pc(path, "unknown", "unsupported_pointcloud_suffix")


def pick_non_ground_candidates(
    *,
    pointcloud: PointCloudData,
    non_ground_class: int,
    ignore_classes: list[int],
) -> np.ndarray:
    if pointcloud.xy.size == 0:
        return np.zeros((0,), dtype=bool)
    if pointcloud.classification is None:
        return np.zeros((pointcloud.xy.shape[0],), dtype=bool)

    cls = np.asarray(pointcloud.classification, dtype=np.int32)
    mask = cls == int(non_ground_class)
    for ic in ignore_classes:
        mask = mask & (cls != int(ic))
    return mask


__all__ = [
    "PointCloudData",
    "default_pointcloud_path",
    "load_pointcloud",
    "pick_non_ground_candidates",
    "pointcloud_bbox",
]
