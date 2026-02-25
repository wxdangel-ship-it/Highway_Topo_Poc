from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform


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
    has_node_file: bool
    has_road_file: bool
    has_tiles_dir: bool
    intersection_feature_count: int
    laneboundary_feature_count: int
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
        has_node_file=node_path.is_file(),
        has_road_file=road_path.is_file(),
        has_tiles_dir=tiles_dir.is_dir(),
        intersection_feature_count=intersection_features,
        laneboundary_feature_count=laneboundary_features,
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

    inter_payload = _load_geojson(intersection_path)
    lane_payload = _load_geojson(laneboundary_path) if laneboundary_path.is_file() else {"type": "FeatureCollection", "features": []}
    node_payload = _load_geojson(node_path) if node_path.is_file() else {"type": "FeatureCollection", "features": []}

    trajectories = _load_trajectories(traj_dir)
    point_cloud_path = _pick_point_cloud_file(pointcloud_dir)

    projection, projectors = _build_projection(inter_payload, lane_payload, trajectories)

    intersections = _extract_intersections(inter_payload, projectors.to_metric)
    lane_boundaries = _extract_linestrings(lane_payload, projectors.to_metric)
    node_kind = _extract_node_kind_map(node_payload)
    projected_traj = _project_trajectories(trajectories, projectors.to_metric)

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
        point_cloud_path=point_cloud_path,
        road_prior_path=road_path if road_path.is_file() else None,
        tiles_dir=tiles_dir if tiles_dir.is_dir() else None,
        input_summary={
            "has_road_prior": road_path.is_file(),
            "has_tiles_dir": tiles_dir.is_dir(),
            "road_prior_name": road_path.name if road_path.is_file() else None,
            "tiles_layout": "xyz" if tiles_dir.is_dir() else None,
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
                    "coordinates": [[float(x), float(y)] for x, y in geom.coords],
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

        feats = payload.get("features", [])
        xs: list[float] = []
        ys: list[float] = []
        zs: list[float] = []
        seq: list[float] = []

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
            seq_val = _extract_seq(props, fallback_idx=idx)

            xs.append(x)
            ys.append(y)
            zs.append(z)
            seq.append(seq_val)

        if len(xs) < 2:
            continue

        order = np.argsort(np.asarray(seq, dtype=np.float64))
        xyz = np.column_stack(
            (
                np.asarray(xs, dtype=np.float64)[order],
                np.asarray(ys, dtype=np.float64)[order],
                np.asarray(zs, dtype=np.float64)[order],
            )
        )
        seq_arr = np.asarray(seq, dtype=np.float64)[order]

        traj_id = fp.parent.name
        out.append(TrajectoryData(traj_id=traj_id, seq=seq_arr, xyz_metric=xyz, source_path=fp))

    return out


def _extract_seq(props: dict[str, Any], *, fallback_idx: int) -> float:
    for key in ["seq", "frame_id", "idx", "index"]:
        if key in props:
            v = _to_float(props.get(key))
            if math.isfinite(v):
                return float(v)

    ts = props.get("timestamp")
    if ts is not None:
        try:
            from datetime import datetime as dt

            return float(dt.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp())
        except Exception:
            pass

    return float(fallback_idx)


def _build_projection(
    intersection_payload: dict[str, Any],
    lane_payload: dict[str, Any],
    trajectories: Sequence[TrajectoryData],
) -> tuple[ProjectionInfo, Projectors]:
    declared = _extract_declared_crs(intersection_payload) or _extract_declared_crs(lane_payload)

    sample_xy = _collect_sample_xy(intersection_payload, lane_payload, trajectories)
    has_lonlat = _looks_like_lonlat(sample_xy)

    if declared:
        try:
            in_crs = CRS.from_user_input(declared)
        except Exception:
            in_crs = CRS.from_epsg(4326) if has_lonlat else CRS.from_epsg(3857)
    else:
        in_crs = CRS.from_epsg(4326) if has_lonlat else CRS.from_epsg(3857)

    if in_crs.is_geographic:
        lon, lat = _centroid_lonlat(sample_xy)
        metric_crs = _utm_crs_for_lonlat(lon, lat)
        forward = Transformer.from_crs(in_crs, metric_crs, always_xy=True).transform
        backward = Transformer.from_crs(metric_crs, in_crs, always_xy=True).transform
        proj = ProjectionInfo(input_crs=str(in_crs.to_string()), metric_crs=str(metric_crs.to_string()), projected=True)
        return proj, Projectors(to_metric=forward, to_input=backward)

    proj = ProjectionInfo(input_crs=str(in_crs.to_string()), metric_crs=str(in_crs.to_string()), projected=False)
    return proj, Projectors(to_metric=lambda x, y, z=None: (x, y), to_input=lambda x, y, z=None: (x, y))


def _collect_sample_xy(
    intersection_payload: dict[str, Any],
    lane_payload: dict[str, Any],
    trajectories: Sequence[TrajectoryData],
) -> np.ndarray:
    pts: list[tuple[float, float]] = []

    for payload in [intersection_payload, lane_payload]:
        for feat in payload.get("features", [])[:32]:
            try:
                geom = shape(feat.get("geometry"))
            except Exception:
                continue
            if geom.is_empty:
                continue
            coords: Iterable[tuple[float, float]]
            if isinstance(geom, LineString):
                coords = geom.coords
            else:
                coords = []
            for x, y, *_ in coords:
                if math.isfinite(x) and math.isfinite(y):
                    pts.append((float(x), float(y)))
                    if len(pts) >= 256:
                        break
            if len(pts) >= 256:
                break

    for traj in trajectories[:4]:
        for row in traj.xyz_metric[:64]:
            x, y = float(row[0]), float(row[1])
            if math.isfinite(x) and math.isfinite(y):
                pts.append((x, y))
                if len(pts) >= 256:
                    break
        if len(pts) >= 256:
            break

    if not pts:
        return np.empty((0, 2), dtype=np.float64)
    return np.asarray(pts, dtype=np.float64)


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


def _looks_like_lonlat(xy: np.ndarray) -> bool:
    if xy.size == 0:
        return False
    x = xy[:, 0]
    y = xy[:, 1]
    finite = np.isfinite(x) & np.isfinite(y)
    if np.count_nonzero(finite) == 0:
        return False
    xs = x[finite]
    ys = y[finite]
    return bool(np.all(np.abs(xs) <= 180.0) and np.all(np.abs(ys) <= 90.0))


def _centroid_lonlat(xy: np.ndarray) -> tuple[float, float]:
    if xy.size == 0:
        return (0.0, 0.0)
    lon = float(np.nanmean(xy[:, 0]))
    lat = float(np.nanmean(xy[:, 1]))
    lon = min(179.0, max(-179.0, lon))
    lat = min(84.0, max(-80.0, lat))
    return (lon, lat)


def _utm_crs_for_lonlat(lon: float, lat: float) -> CRS:
    zone = int(math.floor((lon + 180.0) / 6.0) + 1)
    zone = min(60, max(1, zone))
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)


def _extract_intersections(payload: dict[str, Any], to_metric: callable) -> list[CrossSection]:
    out: list[CrossSection] = []
    for feat in payload.get("features", []):
        props = feat.get("properties") or {}
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

        out.append(CrossSection(nodeid=int(nodeid), geometry_metric=projected, properties=dict(props)))

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


def _extract_node_kind_map(payload: dict[str, Any]) -> dict[int, int]:
    out: dict[int, int] = {}
    for feat in payload.get("features", []):
        props = feat.get("properties") or {}
        nodeid = _safe_int(props.get("mainid", props.get("nodeid", props.get("id"))))
        kind = _safe_int(props.get("Kind", props.get("kind")))
        if nodeid is None or kind is None:
            continue
        out[int(nodeid)] = int(kind)
    return out


def _project_trajectories(trajectories: Sequence[TrajectoryData], to_metric: callable) -> list[TrajectoryData]:
    out: list[TrajectoryData] = []
    for traj in trajectories:
        xyz = np.asarray(traj.xyz_metric, dtype=np.float64)
        if xyz.shape[0] < 2:
            continue

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

        out.append(TrajectoryData(traj_id=traj.traj_id, seq=np.asarray(seq, dtype=np.float64), xyz_metric=pxyz, source_path=traj.source_path))

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


def _pick_point_cloud_file(pointcloud_dir: Path) -> Path | None:
    files = list_point_cloud_files(pointcloud_dir)
    return files[0] if files else None


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
    "git_short_sha",
    "load_patch_inputs",
    "load_point_cloud_window",
    "make_run_id",
    "metric_lines_to_input_crs",
    "probe_patch",
    "resolve_repo_root",
    "write_geojson_lines",
    "write_json",
]
