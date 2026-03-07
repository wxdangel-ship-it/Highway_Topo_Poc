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
_MAX_SAFE_FLOAT_INT = 9007199254740991  # 2^53 - 1
_ROAD_PRIOR_SRC_FIELD_CANDIDATES = (
    "snodeid",
    "src_nodeid",
    "src",
    "from",
    "from_nodeid",
    "start_id",
    "startnodeid",
    "start_node_id",
    "fnodeid",
    "snode",
)
_ROAD_PRIOR_DST_FIELD_CANDIDATES = (
    "enodeid",
    "dst_nodeid",
    "dst",
    "to",
    "to_nodeid",
    "end_id",
    "endnodeid",
    "end_node_id",
    "tnodeid",
    "enode",
)
TRAJ_SPLIT_MAX_GAP_M_DEFAULT = 20.0
TRAJ_SPLIT_MAX_TIME_GAP_S_DEFAULT = 2.0
TRAJ_SPLIT_MAX_SEQ_GAP_DEFAULT = 5


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
    source_traj_id: str | None = None
    segment_index: int = 0
    timestamps_s: np.ndarray | None = None


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


def load_patch_inputs(
    data_root: Path | str,
    patch_id: str | None = None,
    *,
    traj_split_max_gap_m: float = TRAJ_SPLIT_MAX_GAP_M_DEFAULT,
    traj_split_max_time_gap_s: float = TRAJ_SPLIT_MAX_TIME_GAP_S_DEFAULT,
    traj_split_max_seq_gap: int = TRAJ_SPLIT_MAX_SEQ_GAP_DEFAULT,
) -> PatchInputs:
    root = Path(data_root)
    if not root.exists() or not root.is_dir():
        raise InputDataError(f"data_root_not_found: {root}")
    patch_id_value = str(patch_id or "").strip()
    if not patch_id_value:
        raise InputDataError("patch_id_required")

    patch_dir = _resolve_patch_dir(root, patch_id_value)
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
    drive_payload_raw = _load_geojson(drivezone_path)
    lane_payload_raw = (
        _load_geojson(laneboundary_path) if laneboundary_path.is_file() else {"type": "FeatureCollection", "features": []}
    )
    div_payload_raw = _load_geojson(divstrip_path) if divstrip_path.is_file() else {"type": "FeatureCollection", "features": []}
    node_payload = _load_geojson(node_path) if node_path.is_file() else {"type": "FeatureCollection", "features": []}
    road_payload = _load_geojson(road_path) if road_path.is_file() else {"type": "FeatureCollection", "features": []}
    inter_declared_crs = _normalize_epsg_name(_extract_declared_crs(inter_payload))
    drive_declared_crs = _normalize_epsg_name(_extract_declared_crs(drive_payload_raw))
    div_declared_crs = _normalize_epsg_name(_extract_declared_crs(div_payload_raw)) if divstrip_path.is_file() else None
    div_feature_count_raw = int(len(div_payload_raw.get("features", [])))

    point_cloud_path = _pick_point_cloud_file(pointcloud_dir)

    dst_crs = "EPSG:3857"
    inter_crs = _require_geojson_crs(
        inter_payload,
        path=intersection_path,
        allow_empty_if_no_features=False,
        prefer_projected_crs="EPSG:3857",
    )
    drive_crs = _require_geojson_crs(
        drive_payload_raw,
        path=drivezone_path,
        allow_empty_if_no_features=False,
        prefer_projected_crs=inter_crs,
    ) or inter_crs
    drive_payload = drive_payload_raw
    drive_crs_before_alignment = drive_crs
    drive_crs_alignment_reason: str | None = None
    drivezone_crs_reprojected = False
    if (
        drive_declared_crs is None
        and inter_crs is not None
        and _is_geographic_crs_name(drive_crs) != _is_geographic_crs_name(inter_crs)
    ):
        drive_payload = reproject_fc(drive_payload_raw, drive_crs, inter_crs)
        drive_crs = inter_crs
        drive_crs_alignment_reason = "align_to_intersection_crs_type_reproject"
        drivezone_crs_reprojected = True
    patch_crs_name = drive_crs
    trajectories, traj_split_stats = _load_trajectories(
        traj_dir,
        prefer_projected_crs=inter_crs,
        align_missing_to_crs=inter_crs,
        traj_split_max_gap_m=float(traj_split_max_gap_m),
        traj_split_max_time_gap_s=float(traj_split_max_time_gap_s),
        traj_split_max_seq_gap=int(traj_split_max_seq_gap),
    )
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
            lane_crs = (
                _require_geojson_crs(
                    lane_payload,
                    path=laneboundary_path,
                    allow_empty_if_no_features=True,
                    prefer_projected_crs=patch_crs_name,
                )
                or patch_crs_name
            )
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
    div_fix_info: dict[str, Any]
    if divstrip_path.is_file():
        div_payload_fixed, div_fix_info = fix_optional_geojson_crs(
            div_payload_raw,
            path=divstrip_path,
            patch_crs_name=patch_crs_name,
        )
        if div_payload_fixed is None:
            div_payload = {"type": "FeatureCollection", "features": []}
            div_crs = None
        else:
            div_payload = div_payload_fixed
            div_crs = (
                _require_geojson_crs(
                    div_payload,
                    path=divstrip_path,
                    allow_empty_if_no_features=True,
                    prefer_projected_crs=patch_crs_name,
                )
                or patch_crs_name
            )
    else:
        div_payload = {"type": "FeatureCollection", "features": []}
        div_crs = None
        div_fix_info = {
            "used": False,
            "inferred": False,
            "method": "skipped",
            "final_crs": patch_crs_name,
            "skipped_reason": "file_missing",
            "sample_coord": None,
        }
    inter_to_metric = _make_transformer(inter_crs, dst_crs)
    lane_to_metric = _make_transformer(lane_crs or dst_crs, dst_crs)
    drive_to_metric = _make_transformer(drive_crs, dst_crs)
    div_to_metric = _make_transformer(div_crs or dst_crs, dst_crs)

    projection = ProjectionInfo(
        input_crs=inter_crs,
        metric_crs=dst_crs,
        projected=inter_crs != dst_crs,
    )
    projectors = Projectors(
        to_metric=inter_to_metric,
        to_input=_make_transformer(dst_crs, inter_crs),
    )

    node_kind = _extract_node_kind_map(node_payload)
    road_prior_node_ids = _extract_road_prior_node_ids(road_payload) if road_path.is_file() else set()
    intersections_raw = _extract_intersections(inter_payload, inter_to_metric)
    intersections, intersection_nodeid_fix = _canonicalize_intersection_nodeids(
        intersections_raw,
        node_kind_map=node_kind,
        road_prior_node_ids=road_prior_node_ids,
    )
    lane_boundaries = _extract_linestrings(lane_payload, lane_to_metric)
    lane_used = bool(lane_boundaries)
    lane_fix_info = dict(lane_fix_info)
    lane_fix_info["used"] = bool(lane_used)
    lane_fix_info["source_crs"] = str(lane_crs or dst_crs)
    lane_fix_info["final_crs"] = dst_crs
    if not lane_used:
        lane_fix_info["method"] = "skipped"
        if not str(lane_fix_info.get("skipped_reason") or "").strip():
            lane_fix_info["skipped_reason"] = "lane_boundary_empty_or_unusable"
    else:
        lane_fix_info["skipped_reason"] = None
    drivezone_zone = _extract_polygon_union(drive_payload, drive_to_metric)
    divstrip_zone = _extract_polygon_union(div_payload, div_to_metric)
    div_fix_info = dict(div_fix_info)
    div_fix_info["used"] = bool(divstrip_zone is not None and (not divstrip_zone.is_empty))
    div_fix_info["source_crs"] = str(div_crs or dst_crs)
    div_fix_info["final_crs"] = dst_crs
    if not bool(div_fix_info["used"]):
        div_fix_info["method"] = "skipped"
        if not str(div_fix_info.get("skipped_reason") or "").strip():
            div_fix_info["skipped_reason"] = "divstrip_empty_or_unusable"
    else:
        div_fix_info["skipped_reason"] = None
    if drivezone_zone is None or drivezone_zone.is_empty:
        raise InputDataError(f"drivezone_empty: {drivezone_path}")
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
            "lane_boundary_src_crs_name": lane_fix_info.get("source_crs"),
            "drivezone_src_crs": drive_crs,
            "drivezone_src_crs_before_alignment": drive_crs_before_alignment,
            "drivezone_crs_alignment_reason": drive_crs_alignment_reason,
            "drivezone_crs_reprojected": bool(drivezone_crs_reprojected),
            "divstrip_src_crs": div_fix_info.get("source_crs"),
            "intersection_crs_inferred": bool(inter_declared_crs is None and inter_crs is not None),
            "drivezone_crs_inferred": bool(drive_declared_crs is None and drive_crs is not None),
            "divstrip_crs_inferred": bool(div_fix_info.get("inferred", False)),
            "divstrip_crs_method": str(div_fix_info.get("method") or "skipped"),
            "divstrip_used": bool(div_fix_info.get("used", False)),
            "divstrip_skipped_reason": div_fix_info.get("skipped_reason"),
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
            "divstrip_feature_count": int(div_feature_count_raw),
            "road_prior_node_count": int(len(road_prior_node_ids)),
            "intersection_nodeid_remap_count": int(intersection_nodeid_fix.get("remap_count", 0)),
            "intersection_nodeid_remap_examples": list(intersection_nodeid_fix.get("remap_examples", [])),
            **dict(traj_split_stats),
        },
    )


def load_patch_trajectory_lines(
    data_root: Path | str,
    patch_id: str | None = None,
    *,
    out_crs: str = "patch",
    traj_split_max_gap_m: float = TRAJ_SPLIT_MAX_GAP_M_DEFAULT,
    traj_split_max_time_gap_s: float = TRAJ_SPLIT_MAX_TIME_GAP_S_DEFAULT,
    traj_split_max_seq_gap: int = TRAJ_SPLIT_MAX_SEQ_GAP_DEFAULT,
) -> tuple[str, list[LineString], list[dict[str, Any]], dict[str, Any]]:
    root = Path(data_root)
    if not root.exists() or not root.is_dir():
        raise InputDataError(f"data_root_not_found: {root}")
    patch_id_value = str(patch_id or "").strip()
    if not patch_id_value:
        raise InputDataError("patch_id_required")

    patch_dir = _resolve_patch_dir(root, patch_id_value)
    traj_dir = patch_dir / "Traj"
    vector_dir = patch_dir / "Vector"
    intersection_path = vector_dir / "intersection_l.geojson"

    patch_crs = "EPSG:3857"
    if intersection_path.is_file():
        inter_payload = _load_geojson(intersection_path)
        patch_crs = (
            _require_geojson_crs(
                inter_payload,
                path=intersection_path,
                allow_empty_if_no_features=False,
                prefer_projected_crs="EPSG:3857",
            )
            or "EPSG:3857"
        )

    raw_trajectories, traj_split_stats = _load_trajectories(
        traj_dir,
        prefer_projected_crs=patch_crs,
        align_missing_to_crs=patch_crs,
        traj_split_max_gap_m=float(traj_split_max_gap_m),
        traj_split_max_time_gap_s=float(traj_split_max_time_gap_s),
        traj_split_max_seq_gap=int(traj_split_max_seq_gap),
    )
    if not raw_trajectories:
        raise InputDataError(f"trajectory_not_found: {traj_dir}")

    mode = str(out_crs or "patch").strip().lower()
    if mode not in {"patch", "metric"}:
        raise InputDataError(f"invalid_out_crs: {out_crs}")
    target_crs = patch_crs if mode == "patch" else "EPSG:3857"
    trajectories = _project_trajectories(raw_trajectories, dst_crs=target_crs)

    lines: list[LineString] = []
    properties_list: list[dict[str, Any]] = []
    for traj in trajectories:
        xy = np.asarray(traj.xyz_metric[:, :2], dtype=np.float64)
        finite = np.isfinite(xy[:, 0]) & np.isfinite(xy[:, 1])
        xy = xy[finite, :]
        if xy.shape[0] < 2:
            continue
        try:
            line = LineString([(float(x), float(y)) for x, y in xy])
        except Exception:
            continue
        if line.is_empty:
            continue
        seq_arr = np.asarray(traj.seq, dtype=np.int64)
        lines.append(line)
        properties_list.append(
            {
                "patch_id": patch_id_value,
                "traj_id": str(traj.traj_id),
                "source_traj_id": str(traj.source_traj_id or traj.traj_id),
                "segment_index": int(traj.segment_index),
                "point_count": int(xy.shape[0]),
                "seq_min": (int(seq_arr.min()) if seq_arr.size else None),
                "seq_max": (int(seq_arr.max()) if seq_arr.size else None),
                "ts_min": _safe_nanmin(traj.timestamps_s),
                "ts_max": _safe_nanmax(traj.timestamps_s),
                "source_path": traj.source_path.as_posix(),
                "source_crs": str(traj.source_crs),
                "output_crs": target_crs,
            }
        )

    summary = {
        "patch_id": str(patch_id_value),
        "out_crs": str(mode),
        "crs_name": str(target_crs),
        "trajectory_count": int(len(lines)),
        **dict(traj_split_stats),
    }
    return target_crs, lines, properties_list, summary


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


def _load_trajectories(
    traj_dir: Path,
    *,
    prefer_projected_crs: str | None = "EPSG:3857",
    align_missing_to_crs: str | None = None,
    traj_split_max_gap_m: float = TRAJ_SPLIT_MAX_GAP_M_DEFAULT,
    traj_split_max_time_gap_s: float = TRAJ_SPLIT_MAX_TIME_GAP_S_DEFAULT,
    traj_split_max_seq_gap: int = TRAJ_SPLIT_MAX_SEQ_GAP_DEFAULT,
) -> tuple[list[TrajectoryData], dict[str, Any]]:
    files = sorted(traj_dir.rglob(_TRAJ_FILE_NAME)) if traj_dir.is_dir() else []
    out: list[TrajectoryData] = []
    split_stats = _init_traj_split_stats()

    for fp in files:
        try:
            payload = _load_geojson(fp)
        except Exception:
            continue
        split_stats["traj_source_count"] += 1
        declared_crs = _normalize_epsg_name(_extract_declared_crs(payload))
        src_crs = _require_geojson_crs(
            payload,
            path=fp,
            allow_empty_if_no_features=True,
            prefer_projected_crs=prefer_projected_crs,
        )
        if (
            declared_crs is None
            and src_crs is not None
            and align_missing_to_crs is not None
            and _is_geographic_crs_name(src_crs) != _is_geographic_crs_name(align_missing_to_crs)
        ):
            aligned = _normalize_epsg_name(align_missing_to_crs)
            if aligned is not None:
                src_crs = aligned

        feats = payload.get("features", [])
        xs: list[float] = []
        ys: list[float] = []
        zs: list[float] = []
        seq: list[int] = []
        timestamps_s: list[float] = []

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
            ts_val = _extract_timestamp_s(props)

            xs.append(x)
            ys.append(y)
            zs.append(z)
            seq.append(seq_val)
            timestamps_s.append(float(ts_val) if ts_val is not None and math.isfinite(float(ts_val)) else float("nan"))

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
        ts_arr = np.asarray(timestamps_s, dtype=np.float64)[order]

        source_traj_id = fp.parent.name
        for seg_idx, seg in enumerate(
            _split_ordered_trajectory(
                xyz=xyz,
                seq=seq_arr,
                timestamps_s=ts_arr,
                source_traj_id=source_traj_id,
                source_path=fp,
                source_crs=(src_crs or "EPSG:3857"),
                prefer_projected_crs=prefer_projected_crs,
                traj_split_max_gap_m=float(traj_split_max_gap_m),
                traj_split_max_time_gap_s=float(traj_split_max_time_gap_s),
                traj_split_max_seq_gap=int(traj_split_max_seq_gap),
                split_stats=split_stats,
            )
        ):
            out.append(seg)

    return out, _finalize_traj_split_stats(split_stats)


def _extract_seq(props: dict[str, Any], *, fallback_idx: int) -> int:
    for key in ["seq", "frame_id", "idx", "index"]:
        if key in props:
            iv = _safe_int(props.get(key))
            if iv is not None:
                return int(iv)
            v = _to_float(props.get(key))
            if math.isfinite(v):
                return int(round(float(v)))

    ts_s = _extract_timestamp_s(props)
    if ts_s is not None and math.isfinite(float(ts_s)):
        return int(round(float(ts_s) * 1000.0))

    return int(fallback_idx)


def _extract_timestamp_s(props: dict[str, Any]) -> float | None:
    for key in ("time_stamp", "timestamp", "ts", "time", "timeStamp"):
        if key not in props:
            continue
        ts = _parse_timestamp_s(props.get(key))
        if ts is not None and math.isfinite(float(ts)):
            return float(ts)
    return None


def _parse_timestamp_s(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if math.isfinite(v):
            return _normalize_epoch_seconds(v)
        return None
    text = str(value).strip()
    if not text:
        return None
    fv = _to_float(text)
    if math.isfinite(fv):
        return _normalize_epoch_seconds(float(fv))
    try:
        return float(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def _normalize_epoch_seconds(value: float) -> float:
    v = float(value)
    av = abs(v)
    if av > 1e14:
        return v / 1_000_000.0
    if av > 1e11:
        return v / 1000.0
    return v


def _trajectory_gap_metric_crs(src_crs_name: str | None, prefer_projected_crs: str | None) -> str:
    prefer = _normalize_epsg_name(prefer_projected_crs)
    if prefer is not None and (not _is_geographic_crs_name(prefer)):
        return prefer
    src = _normalize_epsg_name(src_crs_name)
    if src is not None and (not _is_geographic_crs_name(src)):
        return src
    return "EPSG:3857"


def _split_ordered_trajectory(
    *,
    xyz: np.ndarray,
    seq: np.ndarray,
    timestamps_s: np.ndarray,
    source_traj_id: str,
    source_path: Path,
    source_crs: str,
    prefer_projected_crs: str | None,
    traj_split_max_gap_m: float,
    traj_split_max_time_gap_s: float,
    traj_split_max_seq_gap: int,
    split_stats: dict[str, Any],
) -> list[TrajectoryData]:
    if xyz.shape[0] < 2:
        return []

    metric_crs = _trajectory_gap_metric_crs(source_crs, prefer_projected_crs)
    metric_xy = np.asarray(xyz[:, :2], dtype=np.float64)
    if _normalize_epsg_name(source_crs) != _normalize_epsg_name(metric_crs):
        tf = _make_transformer(source_crs, metric_crs)
        mx, my = tf(metric_xy[:, 0], metric_xy[:, 1])
        metric_xy = np.column_stack((np.asarray(mx, dtype=np.float64), np.asarray(my, dtype=np.float64)))

    split_points: list[int] = [0]
    source_split = False
    for idx in range(1, int(xyz.shape[0])):
        dx = float(metric_xy[idx, 0] - metric_xy[idx - 1, 0])
        dy = float(metric_xy[idx, 1] - metric_xy[idx - 1, 1])
        dist_gap_m = math.hypot(dx, dy)
        ts_prev = float(timestamps_s[idx - 1]) if idx - 1 < timestamps_s.size else float("nan")
        ts_curr = float(timestamps_s[idx]) if idx < timestamps_s.size else float("nan")
        time_gap_s = (
            float(ts_curr - ts_prev)
            if math.isfinite(ts_prev) and math.isfinite(ts_curr)
            else float("nan")
        )
        seq_gap = int(seq[idx] - seq[idx - 1]) if idx < seq.size else 0
        reasons: list[str] = []
        if math.isfinite(dist_gap_m) and dist_gap_m > float(traj_split_max_gap_m):
            reasons.append("distance")
            split_stats["traj_split_by_distance_count"] += 1
            split_stats["_distance_gaps"].append(float(dist_gap_m))
        if math.isfinite(time_gap_s) and time_gap_s > float(traj_split_max_time_gap_s):
            reasons.append("time")
            split_stats["traj_split_by_time_count"] += 1
            split_stats["_time_gaps"].append(float(time_gap_s))
        if int(seq_gap) > int(traj_split_max_seq_gap):
            reasons.append("seq")
            split_stats["traj_split_by_seq_count"] += 1
            split_stats["_seq_gaps"].append(int(seq_gap))
        if not reasons:
            continue
        source_split = True
        split_points.append(int(idx))
        split_stats["_split_examples"].append(
            {
                "source_traj_id": str(source_traj_id),
                "break_after_segment_index": int(len(split_points) - 1),
                "source_path": source_path.as_posix(),
                "reason": "+".join(reasons),
                "distance_gap_m": (round(float(dist_gap_m), 3) if math.isfinite(dist_gap_m) else None),
                "time_gap_s": (round(float(time_gap_s), 3) if math.isfinite(time_gap_s) else None),
                "seq_gap": int(seq_gap),
                "prev_seq": int(seq[idx - 1]),
                "next_seq": int(seq[idx]),
            }
        )
    split_points.append(int(xyz.shape[0]))
    if source_split:
        split_stats["traj_split_source_count"] += 1

    out: list[TrajectoryData] = []
    for seg_idx, (start, end) in enumerate(zip(split_points[:-1], split_points[1:]), start=1):
        seg_xyz = np.asarray(xyz[start:end], dtype=np.float64)
        if seg_xyz.shape[0] < 2:
            continue
        seg_seq = np.asarray(seq[start:end], dtype=np.int64)
        seg_ts = np.asarray(timestamps_s[start:end], dtype=np.float64)
        out.append(
            TrajectoryData(
                traj_id=f"{source_traj_id}__seg{seg_idx:04d}",
                seq=seg_seq,
                xyz_metric=seg_xyz,
                source_path=source_path,
                source_crs=source_crs,
                source_traj_id=source_traj_id,
                segment_index=int(seg_idx),
                timestamps_s=seg_ts,
            )
        )
        split_stats["traj_segment_count"] += 1
    return out


def _init_traj_split_stats() -> dict[str, Any]:
    return {
        "traj_source_count": 0,
        "traj_segment_count": 0,
        "traj_split_source_count": 0,
        "traj_split_by_distance_count": 0,
        "traj_split_by_time_count": 0,
        "traj_split_by_seq_count": 0,
        "_distance_gaps": [],
        "_time_gaps": [],
        "_seq_gaps": [],
        "_split_examples": [],
    }


def _finalize_traj_split_stats(stats: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in stats.items() if not str(k).startswith("_")}
    out["traj_split_distance_gap_m_p50"] = _safe_percentile_value(stats.get("_distance_gaps", []), 50.0)
    out["traj_split_distance_gap_m_p90"] = _safe_percentile_value(stats.get("_distance_gaps", []), 90.0)
    out["traj_split_distance_gap_m_max"] = _safe_max_value(stats.get("_distance_gaps", []))
    out["traj_split_time_gap_s_p50"] = _safe_percentile_value(stats.get("_time_gaps", []), 50.0)
    out["traj_split_time_gap_s_p90"] = _safe_percentile_value(stats.get("_time_gaps", []), 90.0)
    out["traj_split_time_gap_s_max"] = _safe_max_value(stats.get("_time_gaps", []))
    out["traj_split_seq_gap_p50"] = _safe_percentile_value(stats.get("_seq_gaps", []), 50.0)
    out["traj_split_seq_gap_p90"] = _safe_percentile_value(stats.get("_seq_gaps", []), 90.0)
    out["traj_split_seq_gap_max"] = _safe_max_value(stats.get("_seq_gaps", []))
    out["traj_split_examples"] = list(stats.get("_split_examples", []))[:20]
    return out


def _safe_percentile_value(values: Sequence[float] | Sequence[int], q: float) -> float | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.percentile(arr, float(q)))


def _safe_max_value(values: Sequence[float] | Sequence[int]) -> float | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.max(arr))


def _safe_nanmin(values: np.ndarray | None) -> float | None:
    if values is None:
        return None
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.min(arr))


def _safe_nanmax(values: np.ndarray | None) -> float | None:
    if values is None:
        return None
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.max(arr))


def _build_projection(
    intersection_payload: dict[str, Any],
    lane_payload: dict[str, Any],
    trajectories: Sequence[TrajectoryData],
) -> tuple[ProjectionInfo, Projectors]:
    del lane_payload
    del trajectories
    src = _require_geojson_crs(
        intersection_payload,
        path=Path("intersection_l.geojson"),
        allow_empty_if_no_features=False,
        prefer_projected_crs="EPSG:3857",
    )
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
        nodeid = None
        for key in ("nodeid", "id", "mainid"):
            nodeid = _safe_int(props.get(key))
            if nodeid is not None:
                break
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
        nodeid = None
        for key in ("nodeid", "mainid", "id"):
            nodeid = _safe_int(props.get(key))
            if nodeid is not None:
                break
        kind = _safe_int(props.get("kind", props.get("Kind")))
        if nodeid is None or kind is None:
            continue
        out[int(np.int64(nodeid))] = int(np.int32(kind))
    return out


def _extract_road_prior_node_ids(payload: dict[str, Any]) -> set[int]:
    node_ids: set[int] = set()
    features = payload.get("features", [])
    if not isinstance(features, list):
        return node_ids
    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = normalize_fields(feat.get("properties") or {})
        src = None
        dst = None
        for key in _ROAD_PRIOR_SRC_FIELD_CANDIDATES:
            src = _safe_int(props.get(key))
            if src is not None:
                break
        for key in _ROAD_PRIOR_DST_FIELD_CANDIDATES:
            dst = _safe_int(props.get(key))
            if dst is not None:
                break
        if src is not None:
            node_ids.add(int(src))
        if dst is not None:
            node_ids.add(int(dst))
    return node_ids


def _candidate_nodeids_from_props(props: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for key in ("nodeid", "mainid", "id"):
        iv = _safe_int(props.get(key))
        if iv is None:
            continue
        i64 = int(np.int64(iv))
        if i64 not in out:
            out.append(i64)
    return out


def _canonicalize_intersection_nodeids(
    intersections: Sequence[CrossSection],
    *,
    node_kind_map: dict[int, int],
    road_prior_node_ids: set[int],
) -> tuple[list[CrossSection], dict[str, Any]]:
    out: list[CrossSection] = []
    remap_pairs: list[tuple[int, int]] = []
    for cs in intersections:
        props = normalize_fields(getattr(cs, "properties", {}) or {})
        candidates = _candidate_nodeids_from_props(props)
        chosen = int(cs.nodeid)
        nodeid_direct = _safe_int(props.get("nodeid"))
        # Prefer explicit `nodeid` from intersection_l. Do not let fallback ids
        # (e.g. id/mainid) override it when nodeid already exists.
        if nodeid_direct is not None:
            chosen = int(np.int64(nodeid_direct))
        elif candidates:
            best = int(candidates[0])
            best_score = -1
            for idx, cand in enumerate(candidates):
                score = 0
                if int(cand) in road_prior_node_ids:
                    score += 4
                if int(cand) in node_kind_map:
                    score += 3
                if int(cand) == int(cs.nodeid):
                    score += 2
                if idx == 0:
                    score += 1
                if score > best_score:
                    best_score = int(score)
                    best = int(cand)
            chosen = int(best)
        if int(chosen) != int(cs.nodeid):
            remap_pairs.append((int(cs.nodeid), int(chosen)))
        out.append(
            CrossSection(
                nodeid=int(chosen),
                geometry_metric=cs.geometry_metric,
                properties=dict(cs.properties),
            )
        )
    return out, {
        "remap_count": int(len(remap_pairs)),
        "remap_examples": [[int(src), int(dst)] for src, dst in remap_pairs[:20]],
    }


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
            ts_arr = (
                np.asarray(traj.timestamps_s, dtype=np.float64)[finite]
                if traj.timestamps_s is not None
                else None
            )
        else:
            seq = traj.seq
            ts_arr = (
                np.asarray(traj.timestamps_s, dtype=np.float64)
                if traj.timestamps_s is not None
                else None
            )

        out.append(
            TrajectoryData(
                traj_id=traj.traj_id,
                seq=np.asarray(seq, dtype=np.int64),
                xyz_metric=pxyz,
                source_path=traj.source_path,
                source_crs=dst_crs,
                source_traj_id=traj.source_traj_id,
                segment_index=int(traj.segment_index),
                timestamps_s=ts_arr,
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


def _is_geographic_crs_name(name: str | None) -> bool:
    norm = _normalize_epsg_name(name)
    if norm is None:
        return False
    try:
        return bool(CRS.from_user_input(norm).is_geographic)
    except Exception:
        return False


def _infer_missing_geojson_crs(payload: dict[str, Any], *, prefer_projected_crs: str | None = None) -> str | None:
    coord_scale = infer_coord_scale(payload)
    if coord_scale == "lonlat":
        return "EPSG:4326"
    if coord_scale == "projected":
        pref = _normalize_epsg_name(prefer_projected_crs)
        if pref is not None and (not _is_geographic_crs_name(pref)):
            return pref
        return "EPSG:3857"
    return None


def _require_geojson_crs(
    payload: dict[str, Any],
    *,
    path: Path,
    allow_empty_if_no_features: bool,
    prefer_projected_crs: str | None = None,
    allow_infer_if_missing: bool = True,
) -> str | None:
    crs_raw = _extract_declared_crs(payload)
    if crs_raw is None:
        feats = payload.get("features")
        if allow_empty_if_no_features and isinstance(feats, list) and len(feats) == 0:
            return None
        if allow_infer_if_missing:
            inferred = _infer_missing_geojson_crs(payload, prefer_projected_crs=prefer_projected_crs)
            if inferred is not None:
                return inferred
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
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        if abs(float(v)) > float(_MAX_SAFE_FLOAT_INT):
            return None
        if not float(v).is_integer():
            return None
        return int(v)
    if isinstance(v, str):
        text = str(v).strip()
        if not text:
            return None
        if re.fullmatch(r"[+-]?\d+", text):
            try:
                return int(text)
            except Exception:
                return None
        try:
            fv = float(text)
        except Exception:
            return None
        if not math.isfinite(fv):
            return None
        if abs(float(fv)) > float(_MAX_SAFE_FLOAT_INT):
            return None
        if not float(fv).is_integer():
            return None
        return int(fv)
    try:
        iv = int(v)
    except Exception:
        return None
    return int(iv)


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
    "load_patch_trajectory_lines",
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
