from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .crs_norm import guess_crs_from_bbox, normalize_epsg_name, parse_geojson_crs, transform_xy_arrays
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
    bbox_src: tuple[float, float, float, float] | None
    bbox_dst: tuple[float, float, float, float] | None
    lonlat_like: bool
    src_crs_detected: str | None
    src_crs_used: str | None
    dst_crs: str


_EMPTY_XY = np.zeros((0, 2), dtype=np.float64)


def _empty_pc(path: Path, kind: str, reason: str, *, dst_crs: str) -> PointCloudData:
    return PointCloudData(
        xy=_EMPTY_XY,
        classification=None,
        source_path=path,
        source_kind=kind,
        usable=False,
        reason=reason,
        class_counts={},
        bbox_src=None,
        bbox_dst=None,
        lonlat_like=False,
        src_crs_detected=None,
        src_crs_used=None,
        dst_crs=str(dst_crs),
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


def _resolve_pc_src_crs(
    *,
    path: Path,
    hint: str,
    bbox_src: tuple[float, float, float, float] | None,
    geojson_payload: dict[str, Any] | None,
    dst_crs: str,
) -> tuple[str | None, str | None, str]:
    explicit = str(hint).strip() if hint is not None else "auto"
    explicit_norm = normalize_epsg_name(explicit) if explicit and explicit.lower() != "auto" else None
    if explicit_norm is not None:
        return explicit_norm, explicit_norm, "cli_hint"

    detected: str | None = None
    if geojson_payload is not None:
        detected = parse_geojson_crs(geojson_payload)
    if detected is None:
        guessed = guess_crs_from_bbox(bbox_src)
        detected = guessed

    if detected is not None:
        return detected, detected, "detected"

    name = path.name.lower()
    if "3857" in name:
        return None, "EPSG:3857", "filename_hint"
    if "4326" in name:
        return None, "EPSG:4326", "filename_hint"

    dst_norm = normalize_epsg_name(dst_crs)
    return None, dst_norm, "fallback_dst"


def _project_xy_to_dst(xy: np.ndarray, *, src_crs: str | None, dst_crs: str) -> np.ndarray:
    if xy.size == 0:
        return xy
    dst = normalize_epsg_name(dst_crs)
    if dst is None:
        raise ValueError(f"invalid_dst_crs:{dst_crs}")
    src = normalize_epsg_name(src_crs) if src_crs is not None else dst
    if src is None:
        raise ValueError(f"invalid_src_crs:{src_crs}")
    if src == dst:
        return xy
    x2, y2 = transform_xy_arrays(xy[:, 0], xy[:, 1], src_epsg=src, dst_epsg=dst)
    return np.column_stack([x2, y2]).astype(np.float64)


def _load_las_like(path: Path, *, use_classification: bool, src_crs_hint: str, dst_crs: str) -> PointCloudData:
    try:
        import laspy  # type: ignore
    except Exception:
        return _empty_pc(path, "las", "laspy_missing", dst_crs=dst_crs)

    try:
        las = laspy.read(str(path))
    except Exception as exc:  # noqa: BLE001
        return _empty_pc(path, "las", f"las_read_failed:{type(exc).__name__}", dst_crs=dst_crs)

    x = np.asarray(las.x, dtype=np.float64)
    y = np.asarray(las.y, dtype=np.float64)
    if x.size == 0:
        return _empty_pc(path, "las", "pointcloud_empty", dst_crs=dst_crs)

    xy_src = np.column_stack([x, y])
    bbox_src = _bbox_from_xy(xy_src)
    lonlat_like = bool(bbox_src is not None and infer_lonlat_like_bbox(*bbox_src))
    src_detected, src_used, _reason = _resolve_pc_src_crs(
        path=path,
        hint=src_crs_hint,
        bbox_src=bbox_src,
        geojson_payload=None,
        dst_crs=dst_crs,
    )

    try:
        xy_dst = _project_xy_to_dst(xy_src, src_crs=src_used, dst_crs=dst_crs)
    except Exception as exc:  # noqa: BLE001
        return _empty_pc(path, "las", f"pointcloud_crs_transform_failed:{type(exc).__name__}", dst_crs=dst_crs)

    cls: np.ndarray | None = None
    try:
        dims = set(las.point_format.dimension_names)
        if "classification" in dims:
            cls = np.asarray(las.classification, dtype=np.int32)
    except Exception:
        cls = None

    if use_classification and cls is None:
        return PointCloudData(
            xy=xy_dst,
            classification=None,
            source_path=path,
            source_kind="las",
            usable=False,
            reason="classification_missing",
            class_counts={},
            bbox_src=bbox_src,
            bbox_dst=_bbox_from_xy(xy_dst),
            lonlat_like=lonlat_like,
            src_crs_detected=src_detected,
            src_crs_used=src_used,
            dst_crs=str(dst_crs),
        )

    return PointCloudData(
        xy=xy_dst,
        classification=cls,
        source_path=path,
        source_kind="las",
        usable=True,
        reason=None,
        class_counts=_class_counts(cls),
        bbox_src=bbox_src,
        bbox_dst=_bbox_from_xy(xy_dst),
        lonlat_like=lonlat_like,
        src_crs_detected=src_detected,
        src_crs_used=src_used,
        dst_crs=str(dst_crs),
    )


def _load_geojson_fallback(path: Path, *, use_classification: bool, src_crs_hint: str, dst_crs: str) -> PointCloudData:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return _empty_pc(path, "geojson", f"geojson_parse_failed:{type(exc).__name__}", dst_crs=dst_crs)

    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        return _empty_pc(path, "geojson", "geojson_not_feature_collection", dst_crs=dst_crs)

    feats = payload.get("features")
    if not isinstance(feats, list):
        return _empty_pc(path, "geojson", "geojson_features_not_list", dst_crs=dst_crs)

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
        return _empty_pc(path, "geojson", "pointcloud_empty", dst_crs=dst_crs)

    xy_src = np.asarray(xy_list, dtype=np.float64)
    bbox_src = _bbox_from_xy(xy_src)
    lonlat_like = bool(bbox_src is not None and infer_lonlat_like_bbox(*bbox_src))
    src_detected, src_used, _reason = _resolve_pc_src_crs(
        path=path,
        hint=src_crs_hint,
        bbox_src=bbox_src,
        geojson_payload=payload,
        dst_crs=dst_crs,
    )

    try:
        xy_dst = _project_xy_to_dst(xy_src, src_crs=src_used, dst_crs=dst_crs)
    except Exception as exc:  # noqa: BLE001
        return _empty_pc(path, "geojson", f"pointcloud_crs_transform_failed:{type(exc).__name__}", dst_crs=dst_crs)

    cls = np.asarray(cls_list, dtype=np.int32) if cls_present else None
    if use_classification and cls is None:
        return PointCloudData(
            xy=xy_dst,
            classification=None,
            source_path=path,
            source_kind="geojson",
            usable=False,
            reason="classification_missing",
            class_counts={},
            bbox_src=bbox_src,
            bbox_dst=_bbox_from_xy(xy_dst),
            lonlat_like=lonlat_like,
            src_crs_detected=src_detected,
            src_crs_used=src_used,
            dst_crs=str(dst_crs),
        )

    return PointCloudData(
        xy=xy_dst,
        classification=cls,
        source_path=path,
        source_kind="geojson",
        usable=True,
        reason=None,
        class_counts=_class_counts(cls),
        bbox_src=bbox_src,
        bbox_dst=_bbox_from_xy(xy_dst),
        lonlat_like=lonlat_like,
        src_crs_detected=src_detected,
        src_crs_used=src_used,
        dst_crs=str(dst_crs),
    )


def load_pointcloud(
    *,
    path: Path,
    use_classification: bool,
    src_crs_hint: str = "auto",
    dst_crs: str = "EPSG:3857",
) -> PointCloudData:
    suffix = path.suffix.lower()
    if suffix in {".laz", ".las"}:
        return _load_las_like(path, use_classification=use_classification, src_crs_hint=src_crs_hint, dst_crs=dst_crs)
    if suffix == ".geojson":
        return _load_geojson_fallback(
            path,
            use_classification=use_classification,
            src_crs_hint=src_crs_hint,
            dst_crs=dst_crs,
        )
    return _empty_pc(path, "unknown", "unsupported_pointcloud_suffix", dst_crs=dst_crs)


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
