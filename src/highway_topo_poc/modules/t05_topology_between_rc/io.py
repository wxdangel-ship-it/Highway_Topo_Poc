from __future__ import annotations

import copy
import json
import math
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from .step_utils import normalize_fields


_TRAJ_FILE_NAME = "raw_dat_pose.geojson"
_NODE_PRIMARY_NAME = "RCSDNode.geojson"
_NODE_FALLBACK_NAME = "Node.geojson"
_ROAD_PRIMARY_NAME = "RCSDRoad.geojson"
_ROAD_FALLBACK_NAME = "Road.geojson"


@dataclass(frozen=True)
class ProjectionInfo:
    input_crs: str | None
    metric_crs: str
    projected: bool


@dataclass(frozen=True)
class CrossSection:
    nodeid: int
    geometry_metric: LineString
    properties: dict[str, Any]


@dataclass(frozen=True)
class TrajectoryData:
    traj_id: str
    seq: np.ndarray
    xyz_metric: np.ndarray
    source_path: Path
    source_crs: str


@dataclass(frozen=True)
class PatchInputs:
    patch_id: str
    patch_dir: Path
    projection: ProjectionInfo
    projection_to_metric: callable
    projection_to_input: callable
    intersection_lines: list[CrossSection]
    lane_boundaries_metric: list[LineString]
    node_kind_map: dict[int, int]
    trajectories: list[TrajectoryData]
    drivezone_zone_metric: BaseGeometry | None
    drivezone_source_path: Path | None
    divstrip_zone_metric: BaseGeometry | None
    divstrip_source_path: Path | None
    point_cloud_path: Path | None
    road_prior_path: Path | None
    tiles_dir: Path | None
    input_summary: dict[str, Any]


@dataclass(frozen=True)
class PatchProbe:
    patch_id: str
    patch_dir: Path
    has_intersection_file: bool
    has_laneboundary_file: bool
    has_drivezone_file: bool
    has_node_file: bool
    has_road_file: bool
    has_tiles_dir: bool
    intersection_feature_count: int
    laneboundary_feature_count: int
    drivezone_feature_count: int
    trajectory_count: int
    trajectory_point_count: int
    has_point_cloud_file: bool


@dataclass(frozen=True)
class PointCloudWindow:
    xyz_metric: np.ndarray
    bbox_point_count: int
    selected_point_count: int
    has_classification: bool
    used_class_filter: bool
    point_cloud_path: Path


@dataclass(frozen=True)
class Projectors:
    to_metric: callable
    to_input: callable


class InputDataError(ValueError):
    pass


def _resolve_vector_file(
    *,
    vector_dir: Path,
    primary_name: str,
    fallback_name: str | None = None,
) -> Path:
    primary = vector_dir / primary_name
    if primary.is_file():
        return primary
    if fallback_name:
        fallback = vector_dir / fallback_name
        if fallback.is_file():
            return fallback
    return primary


def resolve_repo_root(start: Path) -> Path:
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / "SPEC.md").is_file() and (cand / "docs").is_dir():
            return cand
    return p


def git_short_sha(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or "unknown"
    except Exception:
        return "unknown"


def make_run_id(prefix: str, *, repo_root: Path) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sha = git_short_sha(repo_root)
    return f"{ts}_{prefix}_{sha}"


def discover_patch_dirs(data_root: Path | str) -> list[Path]:
    root = Path(data_root)
    if not root.exists() or not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        if (p / "Vector").is_dir() and (p / "Traj").is_dir() and (p / "PointCloud").is_dir():
            out.append(p)
    return out


def probe_patch(patch_dir: Path) -> PatchProbe:
    patch_id = patch_dir.name
    vector_dir = patch_dir / "Vector"
    traj_dir = patch_dir / "Traj"
    pc_dir = patch_dir / "PointCloud"

    intersection_path = vector_dir / "intersection_l.geojson"
    laneboundary_path = vector_dir / "LaneBoundary.geojson"
    drivezone_path = vector_dir / "DriveZone.geojson"
    divstrip_path = vector_dir / "DivStripZone.geojson"
    node_path = _resolve_vector_file(
        vector_dir=vector_dir,
        primary_name=_NODE_PRIMARY_NAME,
        fallback_name=_NODE_FALLBACK_NAME,
    )
    road_path = _resolve_vector_file(
        vector_dir=vector_dir,
        primary_name=_ROAD_PRIMARY_NAME,
        fallback_name=_ROAD_FALLBACK_NAME,
    )
    tiles_dir = patch_dir / "Tiles"

    intersection_features = _safe_geojson_feature_count(intersection_path)
    laneboundary_features = _safe_geojson_feature_count(laneboundary_path)
    drivezone_features = _safe_geojson_feature_count(drivezone_path)

    traj_files = sorted(traj_dir.rglob(_TRAJ_FILE_NAME)) if traj_dir.is_dir() else []
    traj_count = 0
    traj_pts = 0
    for tf in traj_files:
        traj_count += 1
        try:
            payload = json.loads(tf.read_text(encoding="utf-8"))
            traj_pts += len(payload.get("features", []))
        except Exception:
            pass

    pc_files = list_point_cloud_files(pc_dir)

    return PatchProbe(
        patch_id=patch_id,
        patch_dir=patch_dir,
        has_intersection_file=intersection_path.is_file(),
        has_laneboundary_file=laneboundary_path.is_file(),
        has_drivezone_file=drivezone_path.is_file(),
        has_node_file=node_path.is_file(),
        has_road_file=road_path.is_file(),
        has_tiles_dir=tiles_dir.is_dir(),
        intersection_feature_count=intersection_features,
        laneboundary_feature_count=laneboundary_features,
        drivezone_feature_count=drivezone_features,
        trajectory_count=traj_count,
        trajectory_point_count=traj_pts,
        has_point_cloud_file=bool(pc_files),
    )


def load_patch_inputs(data_root: Path | str, patch_id: str | None = None) -> PatchInputs:
    root = Path(data_root)
    if not root.exists() or not root.is_dir():
        raise InputDataError(f"data_root_not_found: {root}")

    patch_dir = _resolve_patch_dir(root, patch_id)
    vector_dir = patch_dir / "Vector"
    traj_dir = patch_dir / "Traj"
    pointcloud_dir = patch_dir / "PointCloud"

    intersection_path = vector_dir / "intersection_l.geojson"
    laneboundary_path = vector_dir / "LaneBoundary.geojson"
    drivezone_path = vector_dir / "DriveZone.geojson"
    divstrip_path = vector_dir / "DivStripZone.geojson"
    node_path = _resolve_vector_file(
        vector_dir=vector_dir,
        primary_name=_NODE_PRIMARY_NAME,
        fallback_name=_NODE_FALLBACK_NAME,
    )
    road_path = _resolve_vector_file(
        vector_dir=vector_dir,
        primary_name=_ROAD_PRIMARY_NAME,
        fallback_name=_ROAD_FALLBACK_NAME,
    )
    tiles_dir = patch_dir / "Tiles"

    if not intersection_path.is_file():
        raise InputDataError(f"intersection_l_missing: {intersection_path}")

    if not drivezone_path.is_file():
        raise InputDataError(f"drivezone_missing: {drivezone_path}")

    inter_payload = _load_geojson(intersection_path)
    drive_payload = _load_geojson(drivezone_path)
    lane_payload_raw = (
        _load_geojson(laneboundary_path) if laneboundary_path.is_file() else {"type": "FeatureCollection", "features": []}
    )
    div_payload = _load_geojson(divstrip_path) if divstrip_path.is_file() else {"type": "FeatureCollection", "features": []}
    node_payload = _load_geojson(node_path) if node_path.is_file() else {"type": "FeatureCollection", "features": []}

    trajectories = _load_trajectories(traj_dir)
    point_cloud_path = _pick_point_cloud_file(pointcloud_dir)

    dst_crs = "EPSG:3857"
    inter_crs = _require_geojson_crs(inter_payload, path=intersection_path, allow_empty_if_no_features=False)
    drive_crs = _require_geojson_crs(drive_payload, path=drivezone_path, allow_empty_if_no_features=False) or inter_crs
    patch_crs_name = drive_crs
    lane_fix_info: dict[str, Any]
    if laneboundary_path.is_file():
        lane_payload_fixed, lane_fix_info = fix_optional_geojson_crs(
            lane_payload_raw,
            path=laneboundary_path,
            patch_crs_name=patch_crs_name,
        )
        if lane_payload_fixed is None:
            lane_payload = {"type": "FeatureCollection", "features": []}
            lane_crs = None
        else:
            lane_payload = lane_payload_fixed
            lane_crs = _require_geojson_crs(lane_payload, path=laneboundary_path, allow_empty_if_no_features=True) or patch_crs_name
    else:
        lane_payload = {"type": "FeatureCollection", "features": []}
        lane_crs = None
        lane_fix_info = {
            "used": False,
            "inferred": False,
            "method": "skipped",
            "final_crs": patch_crs_name,
            "skipped_reason": "file_missing",
            "sample_coord": None,
        }
    div_crs = _require_geojson_crs(div_payload, path=divstrip_path, allow_empty_if_no_features=True) or inter_crs
    inter_to_metric = _make_transformer(inter_crs, dst_crs)
    lane_to_metric = _make_transformer(lane_crs or dst_crs, dst_crs)
    drive_to_metric = _make_transformer(drive_crs, dst_crs)
    div_to_metric = _make_transformer(div_crs, dst_crs)

    projection = ProjectionInfo(
        input_crs=inter_crs,
        metric_crs=dst_crs,
        projected=inter_crs != dst_crs,
    )
    projectors = Projectors(
        to_metric=inter_to_metric,
        to_input=_make_transformer(dst_crs, inter_crs),
    )

    intersections = _extract_intersections(inter_payload, inter_to_metric)
    lane_boundaries = _extract_linestrings(lane_payload, lane_to_metric)
    lane_used = bool(lane_boundaries)
    lane_fix_info = dict(lane_fix_info)
    lane_fix_info["used"] = bool(lane_used)
    lane_fix_info["final_crs"] = str(lane_fix_info.get("final_crs") or lane_crs or dst_crs)
    if not lane_used:
        lane_fix_info["method"] = "skipped"
        if not str(lane_fix_info.get("skipped_reason") or "").strip():
            lane_fix_info["skipped_reason"] = "lane_boundary_empty_or_unusable"
    else:
        lane_fix_info["skipped_reason"] = None
    drivezone_zone = _extract_polygon_union(drive_payload, drive_to_metric)
    divstrip_zone = _extract_polygon_union(div_payload, div_to_metric)
    if drivezone_zone is None or drivezone_zone.is_empty:
        raise InputDataError(f"drivezone_empty: {drivezone_path}")
    node_kind = _extract_node_kind_map(node_payload)
    projected_traj = _project_trajectories(trajectories, dst_crs=dst_crs)

    return PatchInputs(
        patch_id=patch_dir.name,
        patch_dir=patch_dir,
        projection=projection,
        projection_to_metric=projectors.to_metric,
        projection_to_input=projectors.to_input,
        intersection_lines=intersections,
        lane_boundaries_metric=lane_boundaries,
        node_kind_map=node_kind,
        trajectories=projected_traj,
        drivezone_zone_metric=drivezone_zone,
        drivezone_source_path=drivezone_path,
        divstrip_zone_metric=divstrip_zone,
        divstrip_source_path=(divstrip_path if divstrip_path.is_file() else None),
        point_cloud_path=point_cloud_path,
        road_prior_path=road_path if road_path.is_file() else None,
        tiles_dir=tiles_dir if tiles_dir.is_dir() else None,
        input_summary={
            "has_road_prior": road_path.is_file(),
            "has_tiles_dir": tiles_dir.is_dir(),
            "road_prior_name": road_path.name if road_path.is_file() else None,
            "tiles_layout": "xyz" if tiles_dir.is_dir() else None,
            "dst_crs": dst_crs,
            "intersection_src_crs": inter_crs,
            "lane_src_crs": lane_crs,
            "drivezone_src_crs": drive_crs,
            "divstrip_src_crs": div_crs if divstrip_path.is_file() else None,
            "lane_boundary_used": bool(lane_fix_info.get("used", False)),
            "lane_boundary_crs_inferred": bool(lane_fix_info.get("inferred", False)),
            "lane_boundary_crs_method": str(lane_fix_info.get("method") or "skipped"),
            "lane_boundary_crs_name_final": str(lane_fix_info.get("final_crs") or dst_crs),
            "lane_boundary_skipped_reason": lane_fix_info.get("skipped_reason"),
            "lane_boundary_sample_coord": lane_fix_info.get("sample_coord"),
            "lane_boundary_crs_fix": lane_fix_info,
            "has_drivezone_file": drivezone_path.is_file(),
            "drivezone_feature_count": int(len(drive_payload.get("features", []))),
            "has_divstrip_file": divstrip_path.is_file(),
            "divstrip_feature_count": int(len(div_payload.get("features", []))),
        },
    )


def list_point_cloud_files(pointcloud_dir: Path) -> list[Path]:
    if not pointcloud_dir.is_dir():
        return []
    files = [p for p in pointcloud_dir.glob("*") if p.is_file() and p.suffix.lower() in {".las", ".laz"}]
    return sorted(files)


def load_point_cloud_window(
    point_cloud_path: Path,
    *,
    bbox_metric: tuple[float, float, float, float],
    allowed_classes: Sequence[int],
    fallback_to_any_class: bool = True,
    max_points: int = 800_000,
) -> PointCloudWindow:
    try:
        import laspy  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise InputDataError("laspy_required_for_las_laz") from exc

    minx, miny, maxx, maxy = bbox_metric

    try:
        reader_ctx = laspy.open(str(point_cloud_path))
    except Exception as exc:
        raise InputDataError(f"point_cloud_open_failed: {point_cloud_path.name}: {type(exc).__name__}") from exc

    with reader_ctx as reader:
        has_cls = "classification" in set(reader.header.point_format.dimension_names)

        cls_set = set(int(v) for v in allowed_classes)
        selected_x: list[np.ndarray] = []
        selected_y: list[np.ndarray] = []
        selected_z: list[np.ndarray] = []

        all_x: list[np.ndarray] = []
        all_y: list[np.ndarray] = []
        all_z: list[np.ndarray] = []

        bbox_count = 0
        selected_count = 0

        for chunk in reader.chunk_iterator(1_000_000):
            cx = np.asarray(chunk.x, dtype=np.float64)
            cy = np.asarray(chunk.y, dtype=np.float64)
            cz = np.asarray(chunk.z, dtype=np.float64)
            if cx.size == 0:
                continue

            bbox_mask = (
                np.isfinite(cx)
                & np.isfinite(cy)
                & np.isfinite(cz)
                & (cx >= minx)
                & (cx <= maxx)
                & (cy >= miny)
                & (cy <= maxy)
            )
            if not np.any(bbox_mask):
                continue

            bbox_idx = np.flatnonzero(bbox_mask)
            bbox_count += int(bbox_idx.size)

            bx = cx[bbox_idx]
            by = cy[bbox_idx]
            bz = cz[bbox_idx]

            all_x.append(bx)
            all_y.append(by)
            all_z.append(bz)

            if has_cls and hasattr(chunk, "classification"):
                cls = np.asarray(chunk.classification, dtype=np.int32)[bbox_idx]
                keep = np.isin(cls, list(cls_set))
                if np.any(keep):
                    selected_x.append(bx[keep])
                    selected_y.append(by[keep])
                    selected_z.append(bz[keep])
                    selected_count += int(np.count_nonzero(keep))
            else:
                selected_x.append(bx)
                selected_y.append(by)
                selected_z.append(bz)
                selected_count += int(bx.size)

    used_class_filter = bool(has_cls)

    if selected_count == 0 and fallback_to_any_class and bbox_count > 0:
        used_class_filter = False
        selected_x = all_x
        selected_y = all_y
        selected_z = all_z
        selected_count = bbox_count

    xyz = _stack_xyz(selected_x, selected_y, selected_z)
    if xyz.shape[0] > max_points:
        step = max(1, int(math.ceil(xyz.shape[0] / float(max_points))))
        xyz = xyz[::step]

    return PointCloudWindow(
        xyz_metric=xyz,
        bbox_point_count=int(bbox_count),
        selected_point_count=int(selected_count),
        has_classification=bool(has_cls),
        used_class_filter=bool(used_class_filter),
        point_cloud_path=point_cloud_path,
    )


def write_geojson_lines(
    out_path: Path,
    *,
    lines_input_crs: Sequence[LineString],
    properties_list: Sequence[dict[str, Any]],
    crs_name: str | None,
) -> None:
    features: list[dict[str, Any]] = []
    for geom, props in zip(lines_input_crs, properties_list):
        if geom.is_empty:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [float(coord[0]), float(coord[1])]
                        for coord in geom.coords
                        if len(coord) >= 2
                    ],
                },
                "properties": _jsonable(props),
            }
        )

    payload: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": features,
    }
    if crs_name:
        payload["crs"] = {"type": "name", "properties": {"name": crs_name}}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _safe_geojson_feature_count(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return len(payload.get("features", []))
    except Exception:
        return 0


def _resolve_patch_dir(root: Path, patch_id: str | None) -> Path:
    if patch_id:
        explicit = root / patch_id
        if explicit.is_dir():
            return explicit

    candidates = discover_patch_dirs(root)
    if not candidates:
        raise InputDataError(f"no_patch_dir_found_under: {root}")

    if patch_id:
        for c in candidates:
            if c.name == patch_id:
                return c
        raise InputDataError(f"patch_id_not_found: {patch_id}")

    return candidates[0]


def _load_geojson(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise InputDataError(f"geojson_parse_failed: {path}") from exc

    if payload.get("type") != "FeatureCollection":
        raise InputDataError(f"geojson_not_featurecollection: {path}")
    return payload


def _load_trajectories(traj_dir: Path) -> list[TrajectoryData]:
    files = sorted(traj_dir.rglob(_TRAJ_FILE_NAME)) if traj_dir.is_dir() else []
    out: list[TrajectoryData] = []

    for fp in files:
        try:
            payload = _load_geojson(fp)
        except Exception:
            continue
        src_crs = _require_geojson_crs(payload, path=fp, allow_empty_if_no_features=True)

        feats = payload.get("features", [])
        xs: list[float] = []
        ys: list[float] = []
        zs: list[float] = []
        seq: list[int] = []

        for idx, feat in enumerate(feats):
            geom = feat.get("geometry") or {}
            if geom.get("type") != "Point":
                continue
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                continue
            x = _to_float(coords[0])
            y = _to_float(coords[1])
            z = _to_float(coords[2]) if len(coords) >= 3 else float("nan")
            if not (math.isfinite(x) and math.isfinite(y)):
                continue

            props = feat.get("properties") or {}
            seq_val = int(_extract_seq(props, fallback_idx=idx))

            xs.append(x)
            ys.append(y)
            zs.append(z)
            seq.append(seq_val)

        if len(xs) < 2:
            continue

        order = np.argsort(np.asarray(seq, dtype=np.int64))
        xyz = np.column_stack(
            (
                np.asarray(xs, dtype=np.float64)[order],
                np.asarray(ys, dtype=np.float64)[order],
                np.asarray(zs, dtype=np.float64)[order],
            )
        )
        seq_arr = np.asarray(seq, dtype=np.int64)[order]

        traj_id = fp.parent.name
        out.append(
            TrajectoryData(
                traj_id=traj_id,
                seq=seq_arr,
                xyz_metric=xyz,
                source_path=fp,
                source_crs=src_crs or "EPSG:3857",
            )
        )

    return out


def _extract_seq(props: dict[str, Any], *, fallback_idx: int) -> int:
    for key in ["seq", "frame_id", "idx", "index"]:
        if key in props:
            iv = _safe_int(props.get(key))
            if iv is not None:
                return int(iv)
            v = _to_float(props.get(key))
            if math.isfinite(v):
                return int(round(float(v)))

    ts = props.get("timestamp")
    if ts is not None:
        try:
            from datetime import datetime as dt

            return int(round(float(dt.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp() * 1000.0)))
        except Exception:
            pass

    return int(fallback_idx)


def _build_projection(
    intersection_payload: dict[str, Any],
    lane_payload: dict[str, Any],
    trajectories: Sequence[TrajectoryData],
) -> tuple[ProjectionInfo, Projectors]:
    del lane_payload
    del trajectories
    src = _require_geojson_crs(intersection_payload, path=Path("intersection_l.geojson"), allow_empty_if_no_features=False)
    dst = "EPSG:3857"
    return (
        ProjectionInfo(input_crs=src, metric_crs=dst, projected=src != dst),
        Projectors(
            to_metric=_make_transformer(src, dst),
            to_input=_make_transformer(dst, src),
        ),
    )


def _extract_declared_crs(payload: dict[str, Any]) -> str | None:
    crs = payload.get("crs")
    if not isinstance(crs, dict):
        return None
    props = crs.get("properties")
    if isinstance(props, dict):
        name = props.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _set_geojson_crs(payload: dict[str, Any], crs_name: str) -> None:
    payload["crs"] = {"type": "name", "properties": {"name": str(crs_name)}}


def _sample_coord_from_shape(geom: BaseGeometry) -> tuple[float, float] | None:
    gtype = str(getattr(geom, "geom_type", ""))
    if gtype in {"Point", "LineString", "LinearRing"}:
        coords = getattr(geom, "coords", None)
        if coords is None:
            return None
        for coord in coords:
            if len(coord) < 2:
                continue
            x = _to_float(coord[0])
            y = _to_float(coord[1])
            if math.isfinite(x) and math.isfinite(y):
                return (float(x), float(y))
        return None
    if gtype == "Polygon":
        ext = getattr(geom, "exterior", None)
        if ext is None:
            return None
        for coord in ext.coords:
            if len(coord) < 2:
                continue
            x = _to_float(coord[0])
            y = _to_float(coord[1])
            if math.isfinite(x) and math.isfinite(y):
                return (float(x), float(y))
        return None
    for sub in getattr(geom, "geoms", []):
        sample = _sample_coord_from_shape(sub)
        if sample is not None:
            return sample
    return None


def _sample_coord_from_fc(payload: dict[str, Any]) -> tuple[float, float] | None:
    feats = payload.get("features")
    if not isinstance(feats, list):
        return None
    for feat in feats:
        if not isinstance(feat, dict):
            continue
        geom_raw = feat.get("geometry")
        if not isinstance(geom_raw, dict):
            continue
        try:
            geom = shape(geom_raw)
        except Exception:
            continue
        if geom is None or geom.is_empty:
            continue
        sample = _sample_coord_from_shape(geom)
        if sample is not None:
            return sample
    return None


def infer_coord_scale(fc: dict[str, Any]) -> str:
    sample = _sample_coord_from_fc(fc)
    if sample is None:
        return "unknown"
    x, y = sample
    if abs(float(x)) <= 180.0 and abs(float(y)) <= 90.0:
        return "lonlat"
    return "projected"


def reproject_fc(fc: dict[str, Any], src_crs_name: str, dst_crs_name: str) -> dict[str, Any]:
    src_crs = _normalize_epsg_name(src_crs_name)
    dst_crs = _normalize_epsg_name(dst_crs_name)
    if src_crs is None or dst_crs is None:
        raise InputDataError(f"crs_invalid: src={src_crs_name} dst={dst_crs_name}")
    out = copy.deepcopy(fc)
    _set_geojson_crs(out, dst_crs)
    if src_crs == dst_crs:
        return out
    tf = _make_transformer(src_crs, dst_crs)
    feats = out.get("features")
    if not isinstance(feats, list):
        return out
    for feat in feats:
        if not isinstance(feat, dict):
            continue
        geom_raw = feat.get("geometry")
        if not isinstance(geom_raw, dict):
            continue
        try:
            geom = shape(geom_raw)
        except Exception:
            continue
        if geom is None or geom.is_empty:
            continue
        projected = _transform_geometry(geom, tf)
        if projected is None or projected.is_empty:
            continue
        feat["geometry"] = mapping(projected)
    return out


def fix_optional_geojson_crs(
    fc: dict[str, Any],
    *,
    path: Path,
    patch_crs_name: str,
    debug: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    del debug
    patch_crs = _normalize_epsg_name(patch_crs_name)
    if patch_crs is None:
        raise InputDataError(f"crs_invalid: src={patch_crs_name} dst={patch_crs_name}")
    sample = _sample_coord_from_fc(fc)
    info: dict[str, Any] = {
        "used": True,
        "inferred": False,
        "method": "inherit_drivezone",
        "final_crs": patch_crs,
        "skipped_reason": None,
        "sample_coord": ([float(sample[0]), float(sample[1])] if sample is not None else None),
    }
    feats = fc.get("features")
    has_features = isinstance(feats, list) and len(feats) > 0
    declared = _extract_declared_crs(fc)
    if declared is not None:
        declared_norm = _normalize_epsg_name(declared)
        if declared_norm is None:
            raise InputDataError(f"geojson_crs_invalid: {path}: {declared}")
        normalized = copy.deepcopy(fc)
        _set_geojson_crs(normalized, declared_norm)
        if declared_norm == patch_crs:
            info["method"] = "inherit_drivezone"
            info["final_crs"] = patch_crs
            return normalized, info
        if declared_norm == "EPSG:4326":
            info["method"] = "coord_scale_crs84_reproject"
        else:
            info["method"] = "declared_reproject"
        info["final_crs"] = patch_crs
        return reproject_fc(normalized, declared_norm, patch_crs), info
    if (not has_features) or sample is None:
        info["used"] = False
        info["method"] = "skipped"
        info["skipped_reason"] = "crs_missing_uninferable_or_empty"
        return None, info
    coord_scale = infer_coord_scale(fc)
    if coord_scale == "lonlat":
        info["inferred"] = True
        info["method"] = "coord_scale_crs84_reproject"
        info["final_crs"] = patch_crs
        return reproject_fc(fc, "EPSG:4326", patch_crs), info
    if coord_scale == "projected":
        out = copy.deepcopy(fc)
        _set_geojson_crs(out, patch_crs)
        info["inferred"] = True
        info["method"] = "inherit_drivezone"
        info["final_crs"] = patch_crs
        return out, info
    info["used"] = False
    info["method"] = "skipped"
    info["skipped_reason"] = "crs_missing_uninferable_or_empty"
    return None, info


def _extract_intersections(payload: dict[str, Any], to_metric: callable) -> list[CrossSection]:
    out: list[CrossSection] = []
    for feat in payload.get("features", []):
        props_raw = feat.get("properties") or {}
        props = normalize_fields(props_raw)
        nodeid_raw = props.get("nodeid", props.get("id", props.get("mainid")))
        nodeid = _safe_int(nodeid_raw)
        if nodeid is None:
            continue

        try:
            geom = shape(feat.get("geometry"))
        except Exception:
            continue

        if geom.is_empty:
            continue

        if not isinstance(geom, LineString):
            if geom.geom_type == "MultiLineString":
                lines = [ls for ls in geom.geoms if isinstance(ls, LineString) and len(ls.coords) >= 2]
                if not lines:
                    continue
                geom = max(lines, key=lambda g: g.length)
            else:
                continue

        projected = _transform_linestring(geom, to_metric)
        if projected is None or projected.is_empty or len(projected.coords) < 2:
            continue

        out.append(CrossSection(nodeid=int(np.int64(nodeid)), geometry_metric=projected, properties=dict(props)))

    return out


def _extract_linestrings(payload: dict[str, Any], to_metric: callable) -> list[LineString]:
    out: list[LineString] = []
    for feat in payload.get("features", []):
        try:
            geom = shape(feat.get("geometry"))
        except Exception:
            continue
        if geom.is_empty:
            continue

        if isinstance(geom, LineString):
            projected = _transform_linestring(geom, to_metric)
            if projected is not None and len(projected.coords) >= 2 and projected.length > 0:
                out.append(projected)
        elif geom.geom_type == "MultiLineString":
            for line in geom.geoms:
                if not isinstance(line, LineString):
                    continue
                projected = _transform_linestring(line, to_metric)
                if projected is not None and len(projected.coords) >= 2 and projected.length > 0:
                    out.append(projected)

    return out


def _extract_polygon_union(payload: dict[str, Any], to_metric: callable) -> BaseGeometry | None:
    geoms: list[BaseGeometry] = []
    for feat in payload.get("features", []):
        try:
            geom = shape(feat.get("geometry"))
        except Exception:
            continue
        if geom.is_empty:
            continue
        projected = _transform_geometry(geom, to_metric)
        if projected is None or projected.is_empty:
            continue
        gtype = getattr(projected, "geom_type", "")
        if gtype in {"Polygon", "MultiPolygon"}:
            geoms.append(projected)
        elif gtype == "GeometryCollection":
            for sub in projected.geoms:
                stype = getattr(sub, "geom_type", "")
                if stype in {"Polygon", "MultiPolygon"} and not sub.is_empty:
                    geoms.append(sub)
    if not geoms:
        return None
    try:
        merged = unary_union(geoms)
    except Exception:
        merged = geoms[0]
    if merged is None or merged.is_empty:
        return None
    return merged


def _extract_node_kind_map(payload: dict[str, Any]) -> dict[int, int]:
    out: dict[int, int] = {}
    for feat in payload.get("features", []):
        props = normalize_fields(feat.get("properties") or {})
        nodeid = _safe_int(props.get("nodeid", props.get("mainid", props.get("id"))))
        kind = _safe_int(props.get("kind", props.get("Kind")))
        if nodeid is None or kind is None:
            continue
        out[int(np.int64(nodeid))] = int(np.int32(kind))
    return out


def _project_trajectories(trajectories: Sequence[TrajectoryData], *, dst_crs: str) -> list[TrajectoryData]:
    out: list[TrajectoryData] = []
    for traj in trajectories:
        xyz = np.asarray(traj.xyz_metric, dtype=np.float64)
        if xyz.shape[0] < 2:
            continue

        to_metric = _make_transformer(traj.source_crs, dst_crs)
        x, y = xyz[:, 0], xyz[:, 1]
        px, py = to_metric(x, y)
        pxyz = np.column_stack((np.asarray(px, dtype=np.float64), np.asarray(py, dtype=np.float64), xyz[:, 2]))

        finite = np.isfinite(pxyz[:, 0]) & np.isfinite(pxyz[:, 1])
        if np.count_nonzero(finite) < 2:
            continue

        if not np.all(finite):
            pxyz = pxyz[finite]
            seq = traj.seq[finite]
        else:
            seq = traj.seq

        out.append(
            TrajectoryData(
                traj_id=traj.traj_id,
                seq=np.asarray(seq, dtype=np.int64),
                xyz_metric=pxyz,
                source_path=traj.source_path,
                source_crs=dst_crs,
            )
        )

    return out


def metric_lines_to_input_crs(lines_metric: Sequence[LineString], to_input: callable) -> list[LineString]:
    out: list[LineString] = []
    for line in lines_metric:
        if line.is_empty:
            out.append(line)
            continue
        out.append(_transform_linestring(line, to_input) or line)
    return out


def _transform_linestring(line: LineString, fn: callable) -> LineString | None:
    try:
        transformed = transform(fn, line)
    except Exception:
        return None
    if not isinstance(transformed, LineString):
        return None
    return transformed


def _transform_geometry(geom: BaseGeometry, fn: callable) -> BaseGeometry | None:
    try:
        transformed = transform(fn, geom)
    except Exception:
        return None
    if transformed is None:
        return None
    return transformed


def _pick_point_cloud_file(pointcloud_dir: Path) -> Path | None:
    files = list_point_cloud_files(pointcloud_dir)
    prefer = [
        "merged_cleaned_classified_3857.laz",
        "merged_cleaned_classified_3857.las",
    ]
    by_name = {p.name.lower(): p for p in files}
    for name in prefer:
        cand = by_name.get(name.lower())
        if cand is not None:
            return cand
    return files[0] if files else None


def _require_geojson_crs(
    payload: dict[str, Any],
    *,
    path: Path,
    allow_empty_if_no_features: bool,
) -> str | None:
    crs_raw = _extract_declared_crs(payload)
    if crs_raw is None:
        feats = payload.get("features")
        if allow_empty_if_no_features and isinstance(feats, list) and len(feats) == 0:
            return None
        raise InputDataError(f"geojson_crs_missing: {path}")

    norm = _normalize_epsg_name(crs_raw)
    if norm is None:
        raise InputDataError(f"geojson_crs_invalid: {path}: {crs_raw}")
    return norm


def normalize_geojson_crs_name(name: str) -> str:
    raw = str(name).strip()
    if not raw:
        return raw
    upper = raw.upper()

    crs84_aliases = {
        "CRS84",
        "OGC:CRS84",
        "OGC:1.3:CRS84",
        "URN:OGC:DEF:CRS:OGC:1.3:CRS84",
        "URN:OGC:DEF:CRS:OGC::CRS84",
    }
    if upper in crs84_aliases:
        return "EPSG:4326"

    epsg_urn = re.search(r"EPSG[^0-9]*([0-9]{4,5})$", upper)
    if epsg_urn:
        return f"EPSG:{int(epsg_urn.group(1))}"

    return raw


def _normalize_epsg_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = normalize_geojson_crs_name(str(raw))
    s = str(s).strip()
    if not s:
        return None
    s_upper = s.upper()
    m = re.fullmatch(r"EPSG:([0-9]{4,5})", s_upper)
    if m:
        return f"EPSG:{int(m.group(1))}"
    try:
        crs = CRS.from_user_input(s)
    except Exception:
        return None
    epsg = crs.to_epsg()
    if epsg is None:
        return None
    return f"EPSG:{int(epsg)}"


def _make_transformer(src_crs: str, dst_crs: str) -> callable:
    src = _normalize_epsg_name(src_crs)
    dst = _normalize_epsg_name(dst_crs)
    if src is None or dst is None:
        raise InputDataError(f"crs_invalid: src={src_crs} dst={dst_crs}")
    if src == dst:
        return lambda x, y, z=None: (x, y)
    tf = Transformer.from_crs(src, dst, always_xy=True)
    return tf.transform


def _to_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return float("nan")


def _safe_int(v: Any) -> int | None:
    try:
        iv = int(v)
        return iv
    except Exception:
        return None


def _stack_xyz(xs: list[np.ndarray], ys: list[np.ndarray], zs: list[np.ndarray]) -> np.ndarray:
    if not xs:
        return np.empty((0, 3), dtype=np.float64)
    return np.column_stack((np.concatenate(xs), np.concatenate(ys), np.concatenate(zs))).astype(np.float64)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if math.isfinite(float(value)):
            return float(value)
        return None
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return None
    if isinstance(value, Path):
        return value.as_posix()
    return value


__all__ = [
    "CrossSection",
    "InputDataError",
    "PatchInputs",
    "PatchProbe",
    "PointCloudWindow",
    "ProjectionInfo",
    "TrajectoryData",
    "discover_patch_dirs",
    "fix_optional_geojson_crs",
    "git_short_sha",
    "infer_coord_scale",
    "load_patch_inputs",
    "load_point_cloud_window",
    "make_run_id",
    "metric_lines_to_input_crs",
    "normalize_geojson_crs_name",
    "probe_patch",
    "reproject_fc",
    "resolve_repo_root",
    "write_geojson_lines",
    "write_json",
]
