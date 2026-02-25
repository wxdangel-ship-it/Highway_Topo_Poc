from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from pyproj import Transformer
from shapely.geometry import Point, box
from shapely.geometry.base import BaseGeometry

from .divstrip_ops import anchor_point_from_crossline, is_divstrip_hit
from .io_geojson import (
    NodeRecord,
    RoadRecord,
    infer_lonlat_like_bbox,
    load_divstrip_union,
    load_nodes,
    load_roads,
)
from .local_frame import LocalFrame
from .metrics_breakpoints import (
    BP_AMBIGUOUS_KIND,
    BP_DIVSTRIPZONE_MISSING,
    BP_DIVSTRIP_TOLERANCE_VIOLATION,
    BP_FOCUS_NODE_NOT_FOUND,
    BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION,
    BP_POINTCLOUD_MISSING_OR_UNUSABLE,
    BP_ROAD_GRAPH_WEAK_STOP,
    BP_ROAD_LINK_NOT_FOUND,
    BP_SCAN_EXCEED_200M,
    BP_TRAJ_MISSING,
    BP_UNSUPPORTED_KIND,
    build_metrics,
    build_summary_text,
    compute_confidence,
    make_breakpoint,
    summarize_breakpoints,
)
from .pointcloud_io import PointCloudData, default_pointcloud_path, load_pointcloud, pick_non_ground_candidates, pointcloud_bbox
from .road_graph import RoadGraph
from .traj_io import build_traj_grid_index, discover_traj_paths, load_traj_points, mark_points_near_traj
from .writers import write_anchor_geojson, write_intersection_opt_geojson, write_json, write_text


@dataclass(frozen=True)
class RunResult:
    run_id: str
    patch_id: str
    mode: str
    out_dir: Path
    overall_pass: bool


def _make_run_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{uuid.uuid4().hex[:6]}"


def _normalize_user_path(raw: str | None) -> Path | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", s)
    if m:
        drive = m.group(1).lower()
        rest = m.group(2).replace("\\", "/")
        return Path("/mnt") / drive / rest
    return Path(s)


def _normalize_user_glob(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", s)
    if m:
        drive = m.group(1).lower()
        rest = m.group(2).replace("\\", "/")
        return str((Path("/mnt") / drive / rest).as_posix())
    return s.replace("\\", "/")


def _resolve_vector_file(vector_dir: Path, primary: str, fallback: str | None = None) -> Path:
    p = vector_dir / primary
    if p.is_file():
        return p
    if fallback:
        f = vector_dir / fallback
        if f.is_file():
            return f
    return p


def _bbox_to_geom(bbox_xy: tuple[float, float, float, float], *, margin_m: float, dst_crs: str) -> BaseGeometry:
    min_x, min_y, max_x, max_y = bbox_xy

    if dst_crs == "EPSG:3857" and infer_lonlat_like_bbox(min_x, min_y, max_x, max_y):
        tf = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        xs, ys = tf.transform([min_x, max_x], [min_y, max_y])
        min_x, max_x = float(min(xs)), float(max(xs))
        min_y, max_y = float(min(ys)), float(max(ys))

    return box(min_x - margin_m, min_y - margin_m, max_x + margin_m, max_y + margin_m)


def _build_aoi(
    *,
    pointcloud_path: Path | None,
    traj_points_xy: np.ndarray,
    dst_crs: str,
) -> BaseGeometry | None:
    if pointcloud_path is not None and pointcloud_path.is_file():
        bb = pointcloud_bbox(pointcloud_path)
        if bb is not None:
            return _bbox_to_geom(bb, margin_m=250.0, dst_crs=dst_crs)

    if traj_points_xy.size > 0:
        min_x = float(np.min(traj_points_xy[:, 0]))
        min_y = float(np.min(traj_points_xy[:, 1]))
        max_x = float(np.max(traj_points_xy[:, 0]))
        max_y = float(np.max(traj_points_xy[:, 1]))
        return box(min_x - 250.0, min_y - 250.0, max_x + 250.0, max_y + 250.0)

    return None


def _pick_seed_nodes(
    *,
    mode: str,
    nodes: list[NodeRecord],
    focus_ids: list[str],
    breakpoints: list[dict[str, Any]],
) -> list[NodeRecord]:
    node_by_id = {int(n.nodeid): n for n in nodes}

    if mode == "global_focus":
        out: list[NodeRecord] = []
        for raw in focus_ids:
            try:
                nid = int(str(raw))
            except Exception:
                breakpoints.append(
                    make_breakpoint(
                        code=BP_FOCUS_NODE_NOT_FOUND,
                        severity="hard",
                        nodeid=None,
                        message=f"focus_nodeid_invalid:{raw}",
                    )
                )
                continue
            hit = node_by_id.get(nid)
            if hit is None:
                breakpoints.append(
                    make_breakpoint(
                        code=BP_FOCUS_NODE_NOT_FOUND,
                        severity="hard",
                        nodeid=nid,
                        message="focus_node_not_found_in_loaded_nodes",
                    )
                )
                continue
            out.append(hit)
        return out

    if focus_ids:
        out2: list[NodeRecord] = []
        for raw in focus_ids:
            try:
                nid = int(str(raw))
            except Exception:
                continue
            hit = node_by_id.get(nid)
            if hit is not None:
                out2.append(hit)
        return out2

    return sorted(nodes, key=lambda n: int(n.nodeid))


def _empty_fail_result(*, nodeid: int, anchor_type: str, scan_dir: str, line: Any, divstrip_union: BaseGeometry | None) -> dict[str, Any]:
    pt, dist = anchor_point_from_crossline(line=line, divstrip_union=divstrip_union)
    return {
        "nodeid": int(nodeid),
        "anchor_type": str(anchor_type),
        "status": "fail",
        "anchor_found": False,
        "trigger": "none",
        "scan_dir": str(scan_dir),
        "scan_dist_m": None,
        "stop_dist_m": 0.0,
        "next_intersection_dist_m": None,
        "dist_to_divstrip_m": dist,
        "confidence": 0.0,
        "flags": [],
        "anchor_point": pt,
        "crossline_opt": line,
        "first_hit_divstrip_m": None,
        "first_hit_non_ground_m": None,
        "ng_candidates_before_suppress": 0,
        "ng_candidates_after_suppress": 0,
    }


def _evaluate_node(
    *,
    node: NodeRecord,
    road_graph: RoadGraph,
    divstrip_union: BaseGeometry | None,
    ng_points_xy: np.ndarray,
    params: dict[str, Any],
    breakpoints: list[dict[str, Any]],
    pointcloud_usable: bool,
) -> dict[str, Any]:
    nodeid = int(node.nodeid)
    kind = int(node.kind)
    is_merge = (kind & (1 << 3)) != 0
    is_diverge = (kind & (1 << 4)) != 0

    dummy_line = LocalFrame.from_tangent(origin_xy=(float(node.point.x), float(node.point.y)), tangent_xy=(1.0, 0.0)).crossline(
        scan_dist_m=0.0,
        cross_half_len_m=float(params["cross_half_len_m"]),
    )

    if is_merge and is_diverge:
        breakpoints.append(
            make_breakpoint(
                code=BP_AMBIGUOUS_KIND,
                severity="hard",
                nodeid=nodeid,
                message="bit3_and_bit4_both_set",
            )
        )
        return _empty_fail_result(
            nodeid=nodeid,
            anchor_type="ambiguous",
            scan_dir="na",
            line=dummy_line,
            divstrip_union=divstrip_union,
        )

    if not is_merge and not is_diverge:
        breakpoints.append(
            make_breakpoint(
                code=BP_UNSUPPORTED_KIND,
                severity="hard",
                nodeid=nodeid,
                message="kind_is_not_merge_or_diverge",
                extra={"kind": int(kind)},
            )
        )
        return _empty_fail_result(
            nodeid=nodeid,
            anchor_type="unsupported",
            scan_dir="na",
            line=dummy_line,
            divstrip_union=divstrip_union,
        )

    if is_diverge:
        pick = road_graph.pick_incoming_road(nodeid)
        anchor_type = "diverge"
        scan_dir_label = "forward"
    else:
        pick = road_graph.pick_outgoing_road(nodeid)
        anchor_type = "merge"
        scan_dir_label = "backward"

    if pick is None:
        breakpoints.append(
            make_breakpoint(
                code=BP_ROAD_LINK_NOT_FOUND,
                severity="hard",
                nodeid=nodeid,
                message="road_link_not_found_for_seed",
            )
        )
        return _empty_fail_result(
            nodeid=nodeid,
            anchor_type=anchor_type,
            scan_dir=scan_dir_label,
            line=dummy_line,
            divstrip_union=divstrip_union,
        )

    tangent = pick.tangent_at_node
    scan_vec = tangent if is_diverge else (-float(tangent[0]), -float(tangent[1]))

    frame = LocalFrame.from_tangent(origin_xy=(float(node.point.x), float(node.point.y)), tangent_xy=scan_vec)

    next_inter = road_graph.find_next_intersection_distance(
        nodeid=nodeid,
        scan_dir=scan_vec,
        intersection_kind_mask=0b11100,
    )

    scan_max = float(params["scan_max_limit_m"])
    stop_dist = float(scan_max)
    if bool(params.get("stop_at_next_intersection", True)) and next_inter is not None and next_inter > 0:
        stop_dist = min(stop_dist, float(next_inter))
    else:
        breakpoints.append(
            make_breakpoint(
                code=BP_ROAD_GRAPH_WEAK_STOP,
                severity="soft",
                nodeid=nodeid,
                message="next_intersection_not_found_use_scan_max",
            )
        )

    stop_dist = max(0.0, float(stop_dist))

    step = max(0.25, float(params["scan_step_m"]))
    n_steps = max(1, int(math.floor(stop_dist / step)) + 1)

    window_steps = max(1, int(math.ceil(float(params["divstrip_trigger_window_m"]) / step)))
    div_tol = float(params["divstrip_hit_tol_m"])

    half_len = float(params["cross_half_len_m"])
    half_eff = max(0.0, half_len - float(params["ignore_end_margin_m"]))
    line_buf = float(params["pc_line_buffer_m"])

    if ng_points_xy.size > 0:
        u, v = frame.project_xy(ng_points_xy)
    else:
        u = np.zeros((0,), dtype=np.float64)
        v = np.zeros((0,), dtype=np.float64)

    def ng_hit_at(scan_s: float) -> tuple[bool, int]:
        if u.size == 0:
            return False, 0
        mask = (np.abs(u - float(scan_s)) <= line_buf) & (np.abs(v) <= half_eff)
        count = int(np.count_nonzero(mask))
        return (count >= int(params["pc_non_ground_min_points"]), count)

    hit_divstrip: list[bool] = []
    hit_ng: list[bool] = []
    lines: list[Any] = []
    scan_values: list[float] = []

    first_divstrip_s: float | None = None
    first_ng_s: float | None = None

    for i in range(n_steps):
        s = float(i) * step
        scan_values.append(s)
        line = frame.crossline(scan_dist_m=s, cross_half_len_m=half_len)
        lines.append(line)

        div_hit = is_divstrip_hit(line=line, divstrip_union=divstrip_union, tol_m=div_tol)
        if div_hit and first_divstrip_s is None:
            first_divstrip_s = s
        hit_divstrip.append(div_hit)

        ng_ok, _ng_count = ng_hit_at(s)
        if ng_ok and first_ng_s is None:
            first_ng_s = s
        hit_ng.append(ng_ok)

    found_idx: int | None = None
    trigger = "none"

    allow_pc_only_no_div = bool(params.get("allow_pc_only_when_no_divstrip", True))
    allow_divstrip_only = bool(params.get("allow_divstrip_only_when_no_pointcloud", True))

    for i in range(n_steps):
        if hit_divstrip[i] and pointcloud_usable:
            lo = i
            hi = min(n_steps - 1, i + window_steps)
            if any(hit_ng[j] for j in range(lo, hi + 1)):
                found_idx = i
                trigger = "divstrip+pc"
                break

        if pointcloud_usable and hit_ng[i]:
            if divstrip_union is None and (not allow_pc_only_no_div):
                pass
            else:
                if (not bool(params.get("ignore_initial_side_ng", True))) or i > 0:
                    found_idx = i
                    trigger = "pc_only"
                    break

        if (not pointcloud_usable) and allow_divstrip_only and hit_divstrip[i]:
            found_idx = i
            trigger = "divstrip_only_degraded"
            break

    if found_idx is None:
        final_line = lines[-1] if lines else dummy_line
        anchor_pt, dist_to_div = anchor_point_from_crossline(line=final_line, divstrip_union=divstrip_union)
        breakpoints.append(
            make_breakpoint(
                code=BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION,
                severity="soft",
                nodeid=nodeid,
                message="scan_end_without_trigger",
                extra={"stop_dist_m": float(stop_dist)},
            )
        )
        if stop_dist >= min(200.0, scan_max):
            breakpoints.append(
                make_breakpoint(
                    code=BP_SCAN_EXCEED_200M,
                    severity="soft",
                    nodeid=nodeid,
                    message="scan_reached_200m_or_max",
                    extra={"stop_dist_m": float(stop_dist)},
                )
            )
        return {
            "nodeid": int(nodeid),
            "anchor_type": anchor_type,
            "status": "fail",
            "anchor_found": False,
            "trigger": "none",
            "scan_dir": scan_dir_label,
            "scan_dist_m": None,
            "stop_dist_m": float(stop_dist),
            "next_intersection_dist_m": None if next_inter is None else float(next_inter),
            "dist_to_divstrip_m": dist_to_div,
            "confidence": 0.0,
            "flags": [],
            "anchor_point": anchor_pt,
            "crossline_opt": final_line,
            "first_hit_divstrip_m": first_divstrip_s,
            "first_hit_non_ground_m": first_ng_s,
            "ng_candidates_before_suppress": int(ng_points_xy.shape[0]),
            "ng_candidates_after_suppress": int(ng_points_xy.shape[0]),
        }

    final_line = lines[found_idx]
    scan_dist = float(scan_values[found_idx])
    anchor_pt, dist_to_div = anchor_point_from_crossline(line=final_line, divstrip_union=divstrip_union)

    flags: list[str] = []
    status = "ok"
    if trigger == "divstrip_only_degraded":
        status = "suspect"
        flags.append("degraded_divstrip_only")
    if scan_dist > float(params.get("scan_near_limit_m", 20.0)):
        status = "suspect"
        flags.append("scan_dist_gt_near_limit")

    if scan_dist > 200.0:
        breakpoints.append(
            make_breakpoint(
                code=BP_SCAN_EXCEED_200M,
                severity="soft",
                nodeid=nodeid,
                message="scan_dist_exceeds_200m",
                extra={"scan_dist_m": float(scan_dist)},
            )
        )

    if trigger in {"divstrip+pc", "divstrip_only_degraded"} and dist_to_div is not None and dist_to_div > div_tol:
        breakpoints.append(
            make_breakpoint(
                code=BP_DIVSTRIP_TOLERANCE_VIOLATION,
                severity="hard",
                nodeid=nodeid,
                message="dist_to_divstrip_exceeds_tol",
                extra={"dist_to_divstrip_m": float(dist_to_div), "tol_m": float(div_tol)},
            )
        )

    conf = compute_confidence(trigger=trigger, scan_dist_m=scan_dist)

    return {
        "nodeid": int(nodeid),
        "anchor_type": anchor_type,
        "status": status,
        "anchor_found": True,
        "trigger": trigger,
        "scan_dir": scan_dir_label,
        "scan_dist_m": float(scan_dist),
        "stop_dist_m": float(stop_dist),
        "next_intersection_dist_m": None if next_inter is None else float(next_inter),
        "dist_to_divstrip_m": dist_to_div,
        "confidence": float(conf),
        "flags": flags,
        "anchor_point": anchor_pt,
        "crossline_opt": final_line,
        "first_hit_divstrip_m": first_divstrip_s,
        "first_hit_non_ground_m": first_ng_s,
        "ng_candidates_before_suppress": int(ng_points_xy.shape[0]),
        "ng_candidates_after_suppress": int(ng_points_xy.shape[0]),
    }


def _serialize_seed_result(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    out.pop("anchor_point", None)
    out.pop("crossline_opt", None)
    return out


def run_from_runtime(runtime: dict[str, Any]) -> RunResult:
    patch_dir = _normalize_user_path(runtime.get("patch_dir"))
    if patch_dir is None or (not patch_dir.is_dir()):
        raise ValueError(f"patch_dir_not_found: {runtime.get('patch_dir')}")

    patch_id = patch_dir.name
    mode = str(runtime.get("mode", "global_focus"))

    out_root = _normalize_user_path(runtime.get("out_root")) or Path("outputs/_work/t04_rc_sw_anchor")
    if not out_root.is_absolute():
        out_root = (Path.cwd() / out_root).resolve()

    run_id = str(runtime.get("run_id") or "auto")
    if run_id == "auto":
        run_id = _make_run_id()

    out_dir = (out_root / run_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    src_crs = str(runtime.get("src_crs", "auto"))
    dst_crs = str(runtime.get("dst_crs", "EPSG:3857"))
    params = dict(runtime.get("params", {}))

    vector_dir = patch_dir / "Vector"

    if mode == "global_focus":
        node_path = _normalize_user_path(runtime.get("global_node_path"))
        road_path = _normalize_user_path(runtime.get("global_road_path"))
    else:
        node_path = _resolve_vector_file(vector_dir, "RCSDNode.geojson", "Node.geojson")
        road_path = _resolve_vector_file(vector_dir, "RCSDRoad.geojson", "Road.geojson")

    if node_path is None or not node_path.is_file():
        raise ValueError(f"node_path_not_found: {node_path}")
    if road_path is None or not road_path.is_file():
        raise ValueError(f"road_path_not_found: {road_path}")

    divstrip_path = _normalize_user_path(runtime.get("divstrip_path"))
    if divstrip_path is None:
        divstrip_path = vector_dir / "DivStripZone.geojson"

    pointcloud_path = _normalize_user_path(runtime.get("pointcloud_path"))
    if pointcloud_path is None:
        pointcloud_path = default_pointcloud_path(patch_dir)

    traj_glob = _normalize_user_glob(runtime.get("traj_glob"))
    traj_paths = discover_traj_paths(patch_dir=patch_dir, traj_glob=traj_glob)
    traj = load_traj_points(paths=traj_paths, src_crs_override=src_crs, dst_crs=dst_crs)

    breakpoints: list[dict[str, Any]] = []
    if traj.total_points <= 0:
        breakpoints.append(
            make_breakpoint(
                code=BP_TRAJ_MISSING,
                severity="soft",
                nodeid=None,
                message="traj_missing_or_empty",
            )
        )

    aoi = _build_aoi(pointcloud_path=pointcloud_path, traj_points_xy=traj.points_xy, dst_crs=dst_crs)

    nodes, node_meta, node_errors = load_nodes(path=node_path, src_crs_override=src_crs, dst_crs=dst_crs, aoi=aoi)
    roads, road_meta, road_errors = load_roads(path=road_path, src_crs_override=src_crs, dst_crs=dst_crs, aoi=aoi)

    # Parse warnings are kept in chosen_config; avoid stdout/raw dumps.
    focus_ids = [str(x) for x in runtime.get("focus_node_ids", [])]
    seeds = _pick_seed_nodes(mode=mode, nodes=nodes, focus_ids=focus_ids, breakpoints=breakpoints)

    node_points = {int(n.nodeid): Point(float(n.point.x), float(n.point.y)) for n in nodes}
    node_kinds = {int(n.nodeid): int(n.kind) for n in nodes}

    road_graph = RoadGraph(roads=roads, node_points=node_points, node_kinds=node_kinds)

    divstrip_union = None
    divstrip_meta: dict[str, Any] = {"path": str(divstrip_path), "exists": bool(divstrip_path and divstrip_path.is_file())}
    if divstrip_path is not None and divstrip_path.is_file():
        divstrip_union, meta, div_errors = load_divstrip_union(
            path=divstrip_path,
            src_crs_override=src_crs,
            dst_crs=dst_crs,
            aoi=aoi,
        )
        divstrip_meta.update({
            "src_crs": meta.src_crs,
            "total_features": meta.total_features,
            "kept_features": meta.kept_features,
            "errors": div_errors,
        })
    else:
        breakpoints.append(
            make_breakpoint(
                code=BP_DIVSTRIPZONE_MISSING,
                severity="soft",
                nodeid=None,
                message="divstripzone_missing",
            )
        )

    pointcloud: PointCloudData | None = None
    pointcloud_usable = False
    pointcloud_meta: dict[str, Any] = {"path": str(pointcloud_path) if pointcloud_path else None}
    ng_points_xy = np.zeros((0, 2), dtype=np.float64)
    ng_before_suppress = 0
    ng_after_suppress = 0
    traj_suppressed_count = 0

    if pointcloud_path is None or (not pointcloud_path.is_file()):
        breakpoints.append(
            make_breakpoint(
                code=BP_POINTCLOUD_MISSING_OR_UNUSABLE,
                severity="soft",
                nodeid=None,
                message="pointcloud_missing",
            )
        )
    else:
        pointcloud = load_pointcloud(path=pointcloud_path, use_classification=bool(params["pc_use_classification"]))

        if pointcloud.lonlat_like and dst_crs == "EPSG:3857":
            tf = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
            xx, yy = tf.transform(pointcloud.xy[:, 0], pointcloud.xy[:, 1])
            pointcloud = PointCloudData(
                xy=np.column_stack([xx, yy]).astype(np.float64),
                classification=pointcloud.classification,
                source_path=pointcloud.source_path,
                source_kind=pointcloud.source_kind,
                usable=pointcloud.usable,
                reason=pointcloud.reason,
                class_counts=pointcloud.class_counts,
                bbox=(float(min(xx)), float(min(yy)), float(max(xx)), float(max(yy))),
                lonlat_like=False,
            )

        pointcloud_usable = bool(pointcloud.usable)
        if not pointcloud_usable:
            breakpoints.append(
                make_breakpoint(
                    code=BP_POINTCLOUD_MISSING_OR_UNUSABLE,
                    severity="soft",
                    nodeid=None,
                    message=str(pointcloud.reason or "pointcloud_unusable"),
                )
            )
        else:
            ng_mask = pick_non_ground_candidates(
                pointcloud=pointcloud,
                non_ground_class=int(params["pc_non_ground_class"]),
                ignore_classes=[int(x) for x in params.get("pc_ignore_classes", [12])],
            )
            ng_points_xy = pointcloud.xy[ng_mask]
            ng_before_suppress = int(ng_points_xy.shape[0])

            if bool(params.get("suppress_ng_near_traj", True)) and traj.total_points > 0 and ng_points_xy.size > 0:
                tindex = build_traj_grid_index(traj_points_xy=traj.points_xy, radius_m=float(params.get("traj_buffer_m", 1.5)))
                near_mask = mark_points_near_traj(points_xy=ng_points_xy, traj_index=tindex)
                traj_suppressed_count = int(np.count_nonzero(near_mask))
                ng_points_xy = ng_points_xy[~near_mask]

            ng_after_suppress = int(ng_points_xy.shape[0])

        pointcloud_meta.update(
            {
                "source_kind": pointcloud.source_kind,
                "usable": bool(pointcloud.usable),
                "reason": pointcloud.reason,
                "class_counts": pointcloud.class_counts,
                "ng_candidates_before_suppress": int(ng_before_suppress),
                "ng_candidates_after_suppress": int(ng_after_suppress),
                "traj_suppressed_count": int(traj_suppressed_count),
            }
        )

    seed_results: list[dict[str, Any]] = []
    for node in seeds:
        res = _evaluate_node(
            node=node,
            road_graph=road_graph,
            divstrip_union=divstrip_union,
            ng_points_xy=ng_points_xy,
            params=params,
            breakpoints=breakpoints,
            pointcloud_usable=pointcloud_usable,
        )
        res["ng_candidates_before_suppress"] = int(ng_before_suppress)
        res["ng_candidates_after_suppress"] = int(ng_after_suppress)
        seed_results.append(res)

    anchors_geojson_path = out_dir / "anchors.geojson"
    inter_opt_path = out_dir / "intersection_l_opt.geojson"
    anchors_json_path = out_dir / "anchors.json"
    metrics_path = out_dir / "metrics.json"
    breakpoints_path = out_dir / "breakpoints.json"
    summary_path = out_dir / "summary.txt"
    chosen_config_path = out_dir / "chosen_config.json"

    write_anchor_geojson(path=anchors_geojson_path, seed_results=seed_results, crs_name=dst_crs)
    write_intersection_opt_geojson(path=inter_opt_path, seed_results=seed_results, crs_name=dst_crs)

    anchors_json_payload = {
        "run_id": str(run_id),
        "patch_id": str(patch_id),
        "mode": str(mode),
        "items": [_serialize_seed_result(x) for x in seed_results],
    }
    write_json(anchors_json_path, anchors_json_payload)

    bp_summary = summarize_breakpoints(breakpoints)
    write_json(breakpoints_path, bp_summary)

    chosen_config = {
        "run_id": str(run_id),
        "patch_id": str(patch_id),
        "mode": str(mode),
        "config_json": runtime.get("config_json"),
        "patch_dir": str(patch_dir),
        "out_root": str(out_root),
        "global_node_path": str(node_path),
        "global_road_path": str(road_path),
        "divstrip_path": str(divstrip_path),
        "pointcloud_path": str(pointcloud_path) if pointcloud_path else None,
        "traj_glob": traj_glob,
        "focus_node_ids": focus_ids,
        "src_crs": str(src_crs),
        "dst_crs": str(dst_crs),
        "params": params,
        "load_meta": {
            "nodes": {
                "path": node_meta.path,
                "src_crs": node_meta.src_crs,
                "total_features": node_meta.total_features,
                "kept_features": node_meta.kept_features,
                "errors": node_errors,
            },
            "roads": {
                "path": road_meta.path,
                "src_crs": road_meta.src_crs,
                "total_features": road_meta.total_features,
                "kept_features": road_meta.kept_features,
                "errors": road_errors,
            },
            "divstrip": divstrip_meta,
            "pointcloud": pointcloud_meta,
            "traj": {
                "path_count": len(traj.paths),
                "total_points": int(traj.total_points),
                "src_crs_list": traj.src_crs_list,
            },
        },
    }
    write_json(chosen_config_path, chosen_config)

    # Metrics + summary
    required_paths = [
        anchors_geojson_path,
        inter_opt_path,
        anchors_json_path,
        metrics_path,
        breakpoints_path,
        summary_path,
        chosen_config_path,
    ]

    metrics = build_metrics(
        patch_id=patch_id,
        mode=mode,
        seed_results=seed_results,
        breakpoints=breakpoints,
        params=params,
        required_outputs_ok=True,
    )
    metrics.update(
        {
            "run_id": str(run_id),
            "traj_path_count": int(len(traj.paths)),
            "traj_total_points": int(traj.total_points),
            "pointcloud_usable": bool(pointcloud_usable),
            "pointcloud_class_counts": pointcloud_meta.get("class_counts", {}),
            "ng_candidates_before_suppress": int(ng_before_suppress),
            "ng_candidates_after_suppress": int(ng_after_suppress),
            "traj_suppressed_count": int(traj_suppressed_count),
            "aoi_used": bool(aoi is not None),
            "focus_node_ids": focus_ids,
        }
    )

    write_json(metrics_path, metrics)

    summary = build_summary_text(
        run_id=str(run_id),
        patch_id=str(patch_id),
        mode=str(mode),
        metrics=metrics,
        breakpoints_summary=bp_summary,
        seed_results=[_serialize_seed_result(x) for x in seed_results],
    )
    write_text(summary_path, summary)

    required_outputs_ok = all(p.is_file() for p in required_paths)
    if not required_outputs_ok:
        metrics = build_metrics(
            patch_id=patch_id,
            mode=mode,
            seed_results=seed_results,
            breakpoints=breakpoints,
            params=params,
            required_outputs_ok=False,
        )
        metrics.update(
            {
                "run_id": str(run_id),
                "traj_path_count": int(len(traj.paths)),
                "traj_total_points": int(traj.total_points),
                "pointcloud_usable": bool(pointcloud_usable),
                "pointcloud_class_counts": pointcloud_meta.get("class_counts", {}),
                "ng_candidates_before_suppress": int(ng_before_suppress),
                "ng_candidates_after_suppress": int(ng_after_suppress),
                "traj_suppressed_count": int(traj_suppressed_count),
                "aoi_used": bool(aoi is not None),
                "focus_node_ids": focus_ids,
            }
        )
        write_json(metrics_path, metrics)
        summary = build_summary_text(
            run_id=str(run_id),
            patch_id=str(patch_id),
            mode=str(mode),
            metrics=metrics,
            breakpoints_summary=bp_summary,
            seed_results=[_serialize_seed_result(x) for x in seed_results],
        )
        write_text(summary_path, summary)

    return RunResult(
        run_id=str(run_id),
        patch_id=str(patch_id),
        mode=str(mode),
        out_dir=out_dir,
        overall_pass=bool(metrics.get("overall_pass", False)),
    )


# Backward-compatible wrapper for old tests/callers.
def run_patch(
    *,
    patch_dir: Path | str,
    out_root: Path | str = "outputs/_work/t04_rc_sw_anchor",
    run_id: str | None = None,
    config: dict[str, Any] | None = None,
) -> RunResult:
    cfg = dict(config or {})
    runtime: dict[str, Any] = {
        "mode": str(cfg.get("mode", "patch")),
        "patch_dir": str(patch_dir),
        "out_root": str(out_root),
        "run_id": str(run_id or "auto"),
        "src_crs": str(cfg.get("src_crs", "auto")),
        "dst_crs": str(cfg.get("dst_crs", "EPSG:3857")),
        "global_node_path": cfg.get("global_node_path"),
        "global_road_path": cfg.get("global_road_path"),
        "divstrip_path": cfg.get("divstrip_path"),
        "pointcloud_path": cfg.get("pointcloud_path"),
        "traj_glob": cfg.get("traj_glob"),
        "focus_node_ids": [str(x) for x in cfg.get("focus_node_ids", [])],
        "params": cfg.get("params", cfg),
        "config_json": cfg.get("config_json"),
    }
    return run_from_runtime(runtime)


__all__ = ["RunResult", "run_from_runtime", "run_patch"]
