from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from highway_topo_poc.modules.t04_rc_sw_anchor.crs_norm import (
    load_geojson_and_reproject,
    normalize_epsg_name,
)
from highway_topo_poc.modules.t04_rc_sw_anchor.io_geojson import load_nodes, load_roads

from .models import BaseCrossSection, line_to_coords


_TRAJ_FILE_NAME = "raw_dat_pose.geojson"
_ROAD_PRIMARY_NAME = "RCSDRoad.geojson"
_ROAD_FALLBACK_NAME = "Road.geojson"
_NODE_PRIMARY_NAME = "RCSDNode.geojson"
_NODE_FALLBACK_NAME = "Node.geojson"


class InputDataError(ValueError):
    pass


@dataclass(frozen=True)
class TrajectoryData:
    traj_id: str
    xyz_metric: tuple[tuple[float, float, float], ...]
    seq: tuple[int, ...]
    source_path: Path


@dataclass(frozen=True)
class InputCrossSection:
    nodeid: int
    geometry_metric: LineString
    properties: dict[str, Any]


@dataclass(frozen=True)
class PatchInputs:
    patch_id: str
    patch_dir: Path
    metric_crs: str
    intersection_lines: tuple[InputCrossSection, ...]
    lane_boundaries_metric: tuple[LineString, ...]
    trajectories: tuple[TrajectoryData, ...]
    drivezone_zone_metric: BaseGeometry | None
    divstrip_zone_metric: BaseGeometry | None
    road_prior_path: Path | None
    node_records: tuple[Any, ...] = ()
    input_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InputFrame:
    patch_id: str
    metric_crs: str
    base_cross_sections: tuple[BaseCrossSection, ...]
    probe_cross_sections: tuple[dict[str, Any], ...]
    drivezone_area_m2: float
    divstrip_present: bool
    lane_boundary_count: int
    trajectory_count: int
    road_prior_count: int
    node_count: int
    input_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": str(self.patch_id),
            "metric_crs": str(self.metric_crs),
            "base_cross_sections": [x.to_dict() for x in self.base_cross_sections],
            "probe_cross_sections": [dict(v) for v in self.probe_cross_sections],
            "drivezone_area_m2": float(self.drivezone_area_m2),
            "divstrip_present": bool(self.divstrip_present),
            "lane_boundary_count": int(self.lane_boundary_count),
            "trajectory_count": int(self.trajectory_count),
            "road_prior_count": int(self.road_prior_count),
            "node_count": int(self.node_count),
            "input_summary": dict(self.input_summary),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "InputFrame":
        return cls(
            patch_id=str(payload.get("patch_id")),
            metric_crs=str(payload.get("metric_crs", "EPSG:3857")),
            base_cross_sections=tuple(BaseCrossSection.from_dict(v) for v in payload.get("base_cross_sections", [])),
            probe_cross_sections=tuple(dict(v) for v in payload.get("probe_cross_sections", [])),
            drivezone_area_m2=float(payload.get("drivezone_area_m2", 0.0)),
            divstrip_present=bool(payload.get("divstrip_present", False)),
            lane_boundary_count=int(payload.get("lane_boundary_count", 0)),
            trajectory_count=int(payload.get("trajectory_count", 0)),
            road_prior_count=int(payload.get("road_prior_count", 0)),
            node_count=int(payload.get("node_count", 0)),
            input_summary=dict(payload.get("input_summary") or {}),
        )


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
    return f"{prefix}_{ts}_{sha}"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _feature(geom: LineString, props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "geometry": mapping(geom), "properties": dict(props)}


def write_features_geojson(
    path: Path,
    features: list[tuple[BaseGeometry, dict[str, Any]]],
    *,
    crs_name: str = "EPSG:3857",
) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [_feature(geom, props) for geom, props in features if geom is not None and not geom.is_empty],
        "crs": {"type": "name", "properties": {"name": str(crs_name)}},
    }
    write_json(path, payload)


def write_lines_geojson(path: Path, features: list[tuple[LineString, dict[str, Any]]], *, crs_name: str = "EPSG:3857") -> None:
    write_features_geojson(path, features, crs_name=crs_name)


def write_step_state(
    *,
    step_dir: Path,
    step: str,
    ok: bool,
    reason: str,
    run_id: str,
    patch_id: str,
    data_root: Path | str,
    out_root: Path | str,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {
        "step": str(step),
        "ok": bool(ok),
        "reason": str(reason),
        "run_id": str(run_id),
        "patch_id": str(patch_id),
        "data_root": str(data_root),
        "out_root": str(out_root),
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if isinstance(extra, dict):
        payload.update(extra)
    write_json(step_dir / "step_state.json", payload)


def _load_fc(path: Path, *, src_hint: str | None, dst_crs: str) -> dict[str, Any]:
    payload, _meta = load_geojson_and_reproject(path=path, src_crs_hint=src_hint, dst_crs=dst_crs)
    return payload


def _resolve_optional_fc(path: Path, *, patch_src_hint: str | None, dst_crs: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not path.is_file():
        return {"type": "FeatureCollection", "features": []}, {"used": False, "method": "missing"}
    try:
        payload = _load_fc(path, src_hint="auto", dst_crs=dst_crs)
        return payload, {"used": True, "method": "reproject"}
    except Exception:
        try:
            payload = _load_fc(path, src_hint=patch_src_hint or "EPSG:3857", dst_crs=dst_crs)
            return payload, {"used": True, "method": "patch_crs_fallback"}
        except Exception:
            return {"type": "FeatureCollection", "features": []}, {"used": False, "method": "skipped_invalid"}


def _extract_lines(payload: dict[str, Any]) -> tuple[InputCrossSection | LineString, ...]:
    out: list[Any] = []
    for feat in payload.get("features", []):
        props = feat.get("properties") or {}
        geom_raw = feat.get("geometry")
        try:
            geom = shape(geom_raw)
        except Exception:
            continue
        if geom.is_empty:
            continue
        if isinstance(geom, LineString):
            out.append((geom, props))
        elif geom.geom_type == "MultiLineString":
            for part in geom.geoms:
                if isinstance(part, LineString) and not part.is_empty and len(part.coords) >= 2:
                    out.append((part, props))
    return tuple(out)


def _extract_cross_sections(payload: dict[str, Any]) -> tuple[InputCrossSection, ...]:
    out: list[InputCrossSection] = []
    for geom, props in _extract_lines(payload):
        nodeid = None
        for key in ("nodeid", "id", "mainid"):
            raw = props.get(key)
            if raw is None:
                continue
            try:
                nodeid = int(raw)
                break
            except Exception:
                continue
        if nodeid is None:
            continue
        out.append(InputCrossSection(nodeid=int(nodeid), geometry_metric=geom, properties=dict(props)))
    return tuple(out)


def _unit_vector(dx: float, dy: float) -> tuple[float, float]:
    norm = math.hypot(float(dx), float(dy))
    if norm <= 1e-9:
        return (1.0, 0.0)
    return (float(dx / norm), float(dy / norm))


def _road_tangent_at_node(road: Any, *, nodeid: int) -> tuple[float, float] | None:
    line = getattr(road, "line", None)
    if not isinstance(line, LineString) or line.is_empty or len(line.coords) < 2:
        return None
    coords = list(line.coords)
    try:
        snodeid = int(getattr(road, "snodeid", 0))
        enodeid = int(getattr(road, "enodeid", 0))
    except Exception:
        return None
    if int(snodeid) == int(nodeid):
        x0, y0 = coords[0][:2]
        x1, y1 = coords[1][:2]
        return _unit_vector(float(x1 - x0), float(y1 - y0))
    if int(enodeid) == int(nodeid):
        x0, y0 = coords[-2][:2]
        x1, y1 = coords[-1][:2]
        return _unit_vector(float(x1 - x0), float(y1 - y0))
    return None


def _pseudo_cross_section_from_node(
    *,
    node: Any,
    tangent_xy: tuple[float, float],
    half_length_m: float,
) -> InputCrossSection:
    ux, uy = _unit_vector(float(tangent_xy[0]), float(tangent_xy[1]))
    px, py = (-float(uy), float(ux))
    center = getattr(node, "point")
    half_len = float(max(1.0, half_length_m))
    line = LineString(
        [
            (float(center.x) - px * half_len, float(center.y) - py * half_len),
            (float(center.x) + px * half_len, float(center.y) + py * half_len),
        ]
    )
    return InputCrossSection(
        nodeid=int(getattr(node, "nodeid")),
        geometry_metric=line,
        properties={
            "nodeid": int(getattr(node, "nodeid")),
            "source": "pseudo_rcsd_node",
            "kind": getattr(node, "kind", None),
        },
    )


def _augment_cross_sections_with_topology_nodes(
    *,
    xsecs: tuple[InputCrossSection, ...],
    prior_roads: list[Any],
    node_records: tuple[Any, ...],
    params: dict[str, Any],
) -> tuple[tuple[InputCrossSection, ...], int]:
    if not bool(int(params.get("STEP2_ENABLE_PSEUDO_RCS_NODE_XSECS", 1))):
        return xsecs, 0
    existing_ids = {int(item.nodeid) for item in xsecs}
    node_map = {
        int(getattr(node, "nodeid", 0)): node
        for node in node_records
        if getattr(node, "point", None) is not None
    }
    roads_by_node: dict[int, list[Any]] = {}
    for road in prior_roads:
        try:
            snodeid = int(getattr(road, "snodeid", 0))
            enodeid = int(getattr(road, "enodeid", 0))
        except Exception:
            continue
        if snodeid > 0:
            roads_by_node.setdefault(int(snodeid), []).append(road)
        if enodeid > 0:
            roads_by_node.setdefault(int(enodeid), []).append(road)
    pseudo_xsecs: list[InputCrossSection] = []
    half_length_m = float(params.get("STEP2_PSEUDO_XSEC_HALF_LENGTH_M", 6.0))
    endpoint_ids = {
        int(getattr(road, "snodeid", 0))
        for road in prior_roads
        if int(getattr(road, "snodeid", 0)) > 0
    } | {
        int(getattr(road, "enodeid", 0))
        for road in prior_roads
        if int(getattr(road, "enodeid", 0)) > 0
    }
    for nodeid in sorted(endpoint_ids):
        if int(nodeid) in existing_ids:
            continue
        node = node_map.get(int(nodeid))
        if node is None:
            continue
        incident = sorted(
            roads_by_node.get(int(nodeid), []),
            key=lambda road: float(getattr(road, "length_m", 0.0)),
            reverse=True,
        )
        tangent_xy = None
        for road in incident:
            tangent_xy = _road_tangent_at_node(road, nodeid=int(nodeid))
            if tangent_xy is not None:
                break
        if tangent_xy is None:
            tangent_xy = (1.0, 0.0)
        pseudo_xsecs.append(
            _pseudo_cross_section_from_node(
                node=node,
                tangent_xy=tangent_xy,
                half_length_m=half_length_m,
            )
        )
        existing_ids.add(int(nodeid))
    if not pseudo_xsecs:
        return xsecs, 0
    merged = tuple(
        sorted(
            [*xsecs, *pseudo_xsecs],
            key=lambda item: (int(item.nodeid), str(item.properties.get("source", "base_cross_section"))),
        )
    )
    return merged, int(len(pseudo_xsecs))


def _extract_line_strings(payload: dict[str, Any]) -> tuple[LineString, ...]:
    return tuple(geom for geom, _props in _extract_lines(payload))


def _extract_polygon_union(payload: dict[str, Any]) -> BaseGeometry | None:
    geoms: list[BaseGeometry] = []
    for feat in payload.get("features", []):
        try:
            geom = shape(feat.get("geometry"))
        except Exception:
            continue
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type in {"Polygon", "MultiPolygon"}:
            geoms.append(geom)
    if not geoms:
        return None
    merged = unary_union(geoms)
    return None if merged is None or merged.is_empty else merged


def _load_trajectories(traj_dir: Path, *, dst_crs: str) -> tuple[TrajectoryData, ...]:
    if not traj_dir.is_dir():
        raise InputDataError(f"trajectory_dir_missing:{traj_dir}")
    out: list[TrajectoryData] = []
    for path in sorted(traj_dir.glob(f"*/{_TRAJ_FILE_NAME}")):
        try:
            payload = _load_fc(path, src_hint="auto", dst_crs=dst_crs)
        except Exception:
            continue
        pts: list[tuple[float, float, float, int]] = []
        for idx, feat in enumerate(payload.get("features", [])):
            try:
                geom = shape(feat.get("geometry"))
            except Exception:
                continue
            if geom.is_empty or geom.geom_type != "Point":
                continue
            props = feat.get("properties") or {}
            seq = props.get("seq", props.get("frame_id", props.get("index", idx)))
            try:
                seq_i = int(seq)
            except Exception:
                seq_i = int(idx)
            z = float(geom.z) if getattr(geom, "has_z", False) else 0.0
            pts.append((float(geom.x), float(geom.y), float(z), seq_i))
        pts.sort(key=lambda item: int(item[3]))
        coords = tuple((float(x), float(y), float(z)) for x, y, z, _seq in pts)
        seqs = tuple(int(seq) for *_xyz, seq in pts)
        if len(coords) < 2:
            continue
        out.append(TrajectoryData(traj_id=str(path.parent.name), xyz_metric=coords, seq=seqs, source_path=path))
    return tuple(out)


def load_divstrip_buffer(divstrip_zone_metric: BaseGeometry | None, gore_buffer_m: float) -> BaseGeometry | None:
    if divstrip_zone_metric is None or divstrip_zone_metric.is_empty:
        return None
    buf = float(max(0.0, gore_buffer_m))
    if buf <= 0.0:
        return divstrip_zone_metric
    try:
        return divstrip_zone_metric.buffer(buf)
    except Exception:
        return divstrip_zone_metric


def load_inputs_and_frame(
    data_root: Path | str,
    patch_id: str,
    *,
    params: dict[str, Any],
) -> tuple[PatchInputs, InputFrame, list[Any]]:
    root = Path(data_root)
    patch_dir = root / str(patch_id)
    vector_dir = patch_dir / "Vector"
    traj_dir = patch_dir / "Traj"
    if not patch_dir.is_dir():
        raise InputDataError(f"patch_id_not_found:{patch_id}")
    intersection_path = vector_dir / "intersection_l.geojson"
    drivezone_path = vector_dir / "DriveZone.geojson"
    lane_path = vector_dir / "LaneBoundary.geojson"
    divstrip_path = vector_dir / "DivStripZone.geojson"
    road_prior_path = vector_dir / _ROAD_PRIMARY_NAME
    node_path = vector_dir / _NODE_PRIMARY_NAME
    if not road_prior_path.is_file():
        fallback = vector_dir / _ROAD_FALLBACK_NAME
        road_prior_path = fallback if fallback.is_file() else None
    if not node_path.is_file():
        fallback = vector_dir / _NODE_FALLBACK_NAME
        node_path = fallback if fallback.is_file() else None
    if not intersection_path.is_file():
        raise InputDataError(f"intersection_l_missing:{intersection_path}")
    if not drivezone_path.is_file():
        raise InputDataError(f"drivezone_missing:{drivezone_path}")
    inter_fc = _load_fc(intersection_path, src_hint="auto", dst_crs="EPSG:3857")
    drive_fc = _load_fc(drivezone_path, src_hint="auto", dst_crs="EPSG:3857")
    lane_fc, lane_fix = _resolve_optional_fc(lane_path, patch_src_hint="EPSG:3857", dst_crs="EPSG:3857")
    div_fc, div_fix = _resolve_optional_fc(divstrip_path, patch_src_hint="EPSG:3857", dst_crs="EPSG:3857")
    xsecs = _extract_cross_sections(inter_fc)
    if not xsecs:
        raise InputDataError(f"intersection_l_empty:{intersection_path}")
    drivezone = _extract_polygon_union(drive_fc)
    if drivezone is None or drivezone.is_empty:
        raise InputDataError(f"drivezone_empty:{drivezone_path}")
    lane_lines = _extract_line_strings(lane_fc)
    divstrip = _extract_polygon_union(div_fc)
    trajectories = _load_trajectories(traj_dir, dst_crs="EPSG:3857")
    if not trajectories:
        raise InputDataError(f"trajectory_missing:{traj_dir}")
    prior_roads: list[Any] = []
    if road_prior_path is not None and road_prior_path.is_file():
        try:
            prior_roads, _meta, _errors = load_roads(path=road_prior_path, src_crs_override="auto", dst_crs="EPSG:3857", aoi=None)
        except Exception:
            prior_roads = []
    node_records: list[Any] = []
    if node_path is not None and node_path.is_file():
        try:
            node_records, _meta, _errors = load_nodes(path=node_path, src_crs_override="auto", dst_crs="EPSG:3857", aoi=None)
        except Exception:
            node_records = []
    xsecs, pseudo_xsec_count = _augment_cross_sections_with_topology_nodes(
        xsecs=xsecs,
        prior_roads=prior_roads,
        node_records=tuple(node_records),
        params=params,
    )
    inputs = PatchInputs(
        patch_id=str(patch_id),
        patch_dir=patch_dir,
        metric_crs="EPSG:3857",
        intersection_lines=xsecs,
        lane_boundaries_metric=lane_lines,
        trajectories=trajectories,
        drivezone_zone_metric=drivezone,
        divstrip_zone_metric=divstrip,
        road_prior_path=road_prior_path,
        node_records=tuple(node_records),
        input_summary={
            "dst_crs": "EPSG:3857",
            "lane_boundary_fix": lane_fix,
            "divstrip_fix": div_fix,
            "trajectory_count": int(len(trajectories)),
            "road_prior_count": int(len(prior_roads)),
            "node_count": int(len(node_records)),
            "pseudo_xsec_count": int(pseudo_xsec_count),
        },
    )
    frame = InputFrame(
        patch_id=str(patch_id),
        metric_crs="EPSG:3857",
        base_cross_sections=tuple(
            BaseCrossSection(nodeid=int(cs.nodeid), geometry_coords=line_to_coords(cs.geometry_metric), properties=dict(cs.properties))
            for cs in xsecs
        ),
        probe_cross_sections=tuple(),
        drivezone_area_m2=float(drivezone.area),
        divstrip_present=bool(divstrip is not None and not divstrip.is_empty),
        lane_boundary_count=int(len(lane_lines)),
        trajectory_count=int(len(trajectories)),
        road_prior_count=int(len(prior_roads)),
        node_count=int(len(node_records)),
        input_summary=dict(inputs.input_summary),
    )
    return inputs, frame, prior_roads


__all__ = [
    "InputDataError",
    "InputFrame",
    "PatchInputs",
    "TrajectoryData",
    "git_short_sha",
    "load_divstrip_buffer",
    "load_inputs_and_frame",
    "make_run_id",
    "read_json",
    "resolve_repo_root",
    "write_json",
    "write_lines_geojson",
    "write_step_state",
]
