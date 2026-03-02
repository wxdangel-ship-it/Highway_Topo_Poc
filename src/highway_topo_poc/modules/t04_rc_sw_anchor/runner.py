from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import LineString, MultiLineString, Point, box
from shapely.geometry.base import BaseGeometry

from .between_branches import build_between_branches_segment, select_branch_pair_and_axis
from .crs_norm import guess_crs_from_bbox, normalize_epsg_name, transform_xy_arrays
from .divstrip_ops import anchor_point_from_crossline
from .drivezone_ops import gap_midpoint_between_pieces, pick_top_two_segment_pieces, segment_drivezone_pieces
from .io_geojson import NodeRecord, RoadRecord, load_divstrip_union, load_drivezone_union, load_nodes, load_roads
from .local_frame import LocalFrame
from .metrics_breakpoints import (
    BP_ANCHOR_GAP_UNSTABLE,
    BP_AMBIGUOUS_KIND,
    BP_CRS_UNKNOWN,
    BP_DIVSTRIPZONE_MISSING,
    BP_DRIVEZONE_CLIP_EMPTY,
    BP_DRIVEZONE_CLIP_MULTIPIECE,
    BP_DRIVEZONE_CRS_UNKNOWN,
    BP_DRIVEZONE_MISSING,
    BP_MULTI_BRANCH_TODO,
    BP_NEXT_INTERSECTION_NOT_FOUND_DEG3,
    BP_DRIVEZONE_SPLIT_NOT_FOUND,
    BP_DRIVEZONE_UNION_EMPTY,
    BP_FOCUS_NODE_NOT_FOUND,
    BP_MISSING_KIND_FIELD,
    BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION,
    BP_NEXT_INTERSECTION_DEG_TOO_LOW_SKIPPED,
    BP_NEXT_INTERSECTION_DISABLED,
    BP_POINTCLOUD_CRS_UNKNOWN_UNUSABLE,
    BP_POINTCLOUD_MISSING_OR_UNUSABLE,
    BP_ROAD_FIELD_MISSING,
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
from .traj_io import TrajLoadResult, build_traj_grid_index, discover_traj_paths, load_traj_points, mark_points_near_traj
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


def _resolve_src_hint(*, hint: Any, global_hint: str) -> str:
    if hint is None:
        return str(global_hint)
    s = str(hint).strip()
    if not s:
        return str(global_hint)
    return s


def _bbox_to_geom(
    bbox_xy: tuple[float, float, float, float],
    *,
    margin_m: float,
    bbox_src_crs_hint: str,
    dst_crs: str,
) -> BaseGeometry:
    min_x, min_y, max_x, max_y = bbox_xy
    dst = normalize_epsg_name(dst_crs) or str(dst_crs)
    src_hint = str(bbox_src_crs_hint).strip() if bbox_src_crs_hint is not None else "auto"
    src: str | None
    if src_hint and src_hint.lower() != "auto":
        src = normalize_epsg_name(src_hint)
    else:
        src = guess_crs_from_bbox(bbox_xy)
    if src is None:
        src = dst

    if src != dst:
        xx, yy = transform_xy_arrays(
            np.asarray([min_x, max_x], dtype=np.float64),
            np.asarray([min_y, max_y], dtype=np.float64),
            src_epsg=src,
            dst_epsg=dst,
        )
        min_x, max_x = float(np.min(xx)), float(np.max(xx))
        min_y, max_y = float(np.min(yy)), float(np.max(yy))

    return box(min_x - margin_m, min_y - margin_m, max_x + margin_m, max_y + margin_m)


def _build_aoi(
    *,
    pointcloud_path: Path | None,
    pointcloud_crs_hint: str,
    traj_points_xy: np.ndarray,
    dst_crs: str,
) -> BaseGeometry | None:
    if pointcloud_path is not None and pointcloud_path.is_file():
        bb = pointcloud_bbox(pointcloud_path)
        if bb is not None:
            return _bbox_to_geom(bb, margin_m=250.0, bbox_src_crs_hint=pointcloud_crs_hint, dst_crs=dst_crs)

    if traj_points_xy.size > 0:
        min_x = float(np.min(traj_points_xy[:, 0]))
        min_y = float(np.min(traj_points_xy[:, 1]))
        max_x = float(np.max(traj_points_xy[:, 0]))
        max_y = float(np.max(traj_points_xy[:, 1]))
        return box(min_x - 250.0, min_y - 250.0, max_x + 250.0, max_y + 250.0)

    return None


def _resolve_nodes_aliases(
    *,
    nodes: list[NodeRecord],
    roads: list[RoadRecord],
) -> tuple[list[NodeRecord], dict[int, tuple[int, str]]]:
    endpoint_id_set: set[int] = set()
    for road in roads:
        endpoint_id_set.add(int(road.snodeid))
        endpoint_id_set.add(int(road.enodeid))

    resolved_nodes: list[NodeRecord] = []
    alias_to_canonical: dict[int, tuple[int, str]] = {}
    used_canonical: set[int] = set()

    for node in nodes:
        id_fields = list(node.id_fields)
        if not id_fields:
            id_fields = [("nodeid", int(node.nodeid))]

        canonical_id: int | None = None
        canonical_field: str | None = None
        for field in ["mainid", "mainnodeid", "id", "nodeid"]:
            for f, v in id_fields:
                if f == field and int(v) in endpoint_id_set:
                    canonical_id = int(v)
                    canonical_field = str(f)
                    break
            if canonical_id is not None:
                break

        if canonical_id is None:
            for field in ["mainid", "mainnodeid", "id", "nodeid"]:
                for f, v in id_fields:
                    if f == field:
                        canonical_id = int(v)
                        canonical_field = str(f)
                        break
                if canonical_id is not None:
                    break

        if canonical_id is None:
            canonical_id = int(node.nodeid)
            canonical_field = "nodeid"

        if canonical_id in used_canonical:
            continue
        used_canonical.add(canonical_id)

        resolved_nodes.append(
            NodeRecord(
                nodeid=int(canonical_id),
                kind=node.kind,
                point=node.point,
                id_fields=tuple(id_fields),
                kind_raw=node.kind_raw,
            )
        )

        for f, v in id_fields:
            if int(v) not in alias_to_canonical:
                alias_to_canonical[int(v)] = (int(canonical_id), str(f))
        if canonical_id not in alias_to_canonical:
            alias_to_canonical[int(canonical_id)] = (int(canonical_id), str(canonical_field))

    return resolved_nodes, alias_to_canonical


def _pick_seed_nodes(
    *,
    mode: str,
    nodes: list[NodeRecord],
    focus_ids: list[str],
    alias_to_canonical: dict[int, tuple[int, str]],
    breakpoints: list[dict[str, Any]],
) -> tuple[list[NodeRecord], dict[int, dict[str, Any]]]:
    node_by_id = {int(n.nodeid): n for n in nodes}
    resolved_from: dict[int, dict[str, Any]] = {}

    if mode == "global_focus":
        out: list[NodeRecord] = []
        seen: set[int] = set()
        for raw in focus_ids:
            try:
                fid = int(str(raw))
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

            hit_meta = alias_to_canonical.get(fid)
            if hit_meta is None:
                breakpoints.append(
                    make_breakpoint(
                        code=BP_FOCUS_NODE_NOT_FOUND,
                        severity="hard",
                        nodeid=fid,
                        message="focus_node_not_found_in_alias_map",
                    )
                )
                continue

            canonical_id, matched_field = hit_meta
            hit_node = node_by_id.get(int(canonical_id))
            if hit_node is None:
                breakpoints.append(
                    make_breakpoint(
                        code=BP_FOCUS_NODE_NOT_FOUND,
                        severity="hard",
                        nodeid=fid,
                        message="focus_node_canonical_missing",
                        extra={"canonical_id": int(canonical_id)},
                    )
                )
                continue

            if int(canonical_id) in seen:
                continue
            seen.add(int(canonical_id))
            out.append(hit_node)
            resolved_from[int(canonical_id)] = {
                "focus_id": str(fid),
                "canonical_id": int(canonical_id),
                "matched_field": str(matched_field),
            }
        return out, resolved_from

    if focus_ids:
        out2: list[NodeRecord] = []
        seen2: set[int] = set()
        for raw in focus_ids:
            try:
                fid = int(str(raw))
            except Exception:
                continue
            hit_meta = alias_to_canonical.get(fid)
            if hit_meta is None:
                continue
            canonical_id, matched_field = hit_meta
            hit_node = node_by_id.get(int(canonical_id))
            if hit_node is None or int(canonical_id) in seen2:
                continue
            seen2.add(int(canonical_id))
            out2.append(hit_node)
            resolved_from[int(canonical_id)] = {
                "focus_id": str(fid),
                "canonical_id": int(canonical_id),
                "matched_field": str(matched_field),
            }
        return out2, resolved_from

    return sorted(nodes, key=lambda n: int(n.nodeid)), resolved_from


def _empty_fail_result(
    *,
    nodeid: int,
    kind: int | None,
    anchor_type: str,
    scan_dir: str,
    line: Any,
    divstrip_union: BaseGeometry | None,
    drivezone_union: BaseGeometry | None,
    stop_reason: str,
    id_fields: tuple[tuple[str, int], ...] = (),
    resolved_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pt, dist = anchor_point_from_crossline(line=line, divstrip_union=divstrip_union)
    dist_line = None if divstrip_union is None else float(line.distance(divstrip_union))
    id_map = {str(k): int(v) for k, v in id_fields}
    is_merge = bool(kind is not None and (int(kind) & (1 << 3)) != 0)
    is_diverge = bool(kind is not None and (int(kind) & (1 << 4)) != 0)
    return {
        "nodeid": int(nodeid),
        "id": id_map.get("id"),
        "mainid": id_map.get("mainid"),
        "mainnodeid": id_map.get("mainnodeid"),
        "kind": None if kind is None else int(kind),
        "is_merge_kind": bool(is_merge),
        "is_diverge_kind": bool(is_diverge),
        "anchor_type": str(anchor_type),
        "status": "fail",
        "found_split": False,
        "anchor_found": False,
        "trigger": "none",
        "scan_dir": str(scan_dir),
        "scan_dist_m": None,
        "stop_dist_m": 0.0,
        "stop_reason": str(stop_reason),
        "next_intersection_dist_m": None,
        "dist_to_divstrip_m": dist,
        "dist_line_to_divstrip_m": dist_line,
        "dist_line_to_drivezone_edge_m": None if drivezone_union is None else float(line.distance(drivezone_union.boundary)),
        "confidence": 0.0,
        "flags": [],
        "evidence_source": "none",
        "anchor_point": pt,
        "crossline_opt": line,
        "tip_s_m": None,
        "first_divstrip_hit_dist_m": None,
        "best_divstrip_dz_dist_m": None,
        "best_divstrip_pc_dist_m": None,
        "first_pc_only_dist_m": None,
        "fan_area_m2": 0.0,
        "non_drivezone_area_m2": 0.0,
        "non_drivezone_frac": 0.0,
        "clipped_len_m": float(line.length),
        "clip_empty": False,
        "clip_piece_type": "none",
        "pieces_count": 0,
        "piece_lens_m": [],
        "gap_len_m": None,
        "seg_len_m": float(line.length),
        "branch_a_id": None,
        "branch_b_id": None,
        "branch_axis_id": None,
        "branch_a_crossline_hit": False,
        "branch_b_crossline_hit": False,
        "pa_center_dist_m": None,
        "pb_center_dist_m": None,
        "has_divstrip_nearby": False,
        "ng_candidates_before_suppress": 0,
        "ng_candidates_after_suppress": 0,
        "resolved_from": resolved_from,
    }


def _evaluate_node(
    *,
    node: NodeRecord,
    road_graph: RoadGraph,
    divstrip_union: BaseGeometry | None,
    drivezone_union: BaseGeometry | None,
    drivezone_usable: bool,
    ng_points_xy: np.ndarray,
    params: dict[str, Any],
    breakpoints: list[dict[str, Any]],
    pointcloud_usable: bool,
    resolved_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    nodeid = int(node.nodeid)
    kind = None if node.kind is None else int(node.kind)
    is_merge = bool(kind is not None and (int(kind) & (1 << 3)) != 0)
    is_diverge = bool(kind is not None and (int(kind) & (1 << 4)) != 0)
    hard_failed = False

    def _add_bp(
        *,
        code: str,
        severity: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        nonlocal hard_failed
        breakpoints.append(
            make_breakpoint(
                code=code,
                severity=severity,
                nodeid=nodeid,
                message=message,
                extra=extra,
            )
        )
        if str(severity).lower() == "hard":
            hard_failed = True

    dummy_line = LocalFrame.from_tangent(origin_xy=(float(node.point.x), float(node.point.y)), tangent_xy=(1.0, 0.0)).crossline(
        scan_dist_m=0.0,
        cross_half_len_m=float(params["cross_half_len_m"]),
    )

    if kind is None:
        _add_bp(code=BP_MISSING_KIND_FIELD, severity="hard", message="kind_missing_or_parse_failed", extra={"kind_raw": node.kind_raw})
        return _empty_fail_result(
            nodeid=nodeid,
            kind=kind,
            anchor_type="kind_missing",
            scan_dir="na",
            line=dummy_line,
            divstrip_union=divstrip_union,
            drivezone_union=drivezone_union,
            stop_reason="kind_missing",
            id_fields=node.id_fields,
            resolved_from=resolved_from,
        )

    if is_merge and is_diverge:
        _add_bp(code=BP_AMBIGUOUS_KIND, severity="hard", message="bit3_and_bit4_both_set")
        return _empty_fail_result(
            nodeid=nodeid,
            kind=kind,
            anchor_type="ambiguous",
            scan_dir="na",
            line=dummy_line,
            divstrip_union=divstrip_union,
            drivezone_union=drivezone_union,
            stop_reason="ambiguous_kind",
            id_fields=node.id_fields,
            resolved_from=resolved_from,
        )

    if not is_merge and not is_diverge:
        _add_bp(
            code=BP_UNSUPPORTED_KIND,
            severity="hard",
            message="kind_is_not_merge_or_diverge",
            extra={"kind": int(kind), "kind_raw": node.kind_raw},
        )
        return _empty_fail_result(
            nodeid=nodeid,
            kind=kind,
            anchor_type="unsupported",
            scan_dir="na",
            line=dummy_line,
            divstrip_union=divstrip_union,
            drivezone_union=drivezone_union,
            stop_reason="unsupported_kind",
            id_fields=node.id_fields,
            resolved_from=resolved_from,
        )

    try:
        branch_sel = select_branch_pair_and_axis(
            nodeid=nodeid,
            is_diverge=bool(is_diverge),
            roads=road_graph.roads,
        )
    except Exception as exc:
        _add_bp(
            code=BP_ROAD_LINK_NOT_FOUND,
            severity="hard",
            message=f"between_branches_selection_failed:{type(exc).__name__}",
        )
        return _empty_fail_result(
            nodeid=nodeid,
            kind=kind,
            anchor_type="diverge" if is_diverge else "merge",
            scan_dir="forward" if is_diverge else "backward",
            line=dummy_line,
            divstrip_union=divstrip_union,
            drivezone_union=drivezone_union,
            stop_reason="road_link_missing",
            id_fields=node.id_fields,
            resolved_from=resolved_from,
        )

    if branch_sel.multi_branch_todo:
        _add_bp(
            code=BP_MULTI_BRANCH_TODO,
            severity="soft",
            message="multi_branch_selected_max_angle_pair",
        )

    anchor_type = str(branch_sel.anchor_type)
    scan_dir_label = str(branch_sel.scan_dir_label)
    scan_vec = (float(branch_sel.scan_dir[0]), float(branch_sel.scan_dir[1]))
    branch_a = road_graph.roads[int(branch_sel.branch_a_idx)]
    branch_b = road_graph.roads[int(branch_sel.branch_b_idx)]
    axis_road = road_graph.roads[int(branch_sel.scan_axis_idx)]
    branch_a_id = f"{int(branch_a.snodeid)}->{int(branch_a.enodeid)}"
    branch_b_id = f"{int(branch_b.snodeid)}->{int(branch_b.enodeid)}"
    axis_id = f"{int(axis_road.snodeid)}->{int(axis_road.enodeid)}"

    use_drivezone = bool(params.get("use_drivezone", True))
    if (not use_drivezone) or (drivezone_union is None) or (not drivezone_usable):
        _add_bp(
            code=BP_DRIVEZONE_MISSING,
            severity="hard",
            message="drivezone_missing_or_disabled",
        )
        out = _empty_fail_result(
            nodeid=nodeid,
            kind=kind,
            anchor_type=anchor_type,
            scan_dir=scan_dir_label,
            line=dummy_line,
            divstrip_union=divstrip_union,
            drivezone_union=drivezone_union,
            stop_reason="drivezone_missing",
            id_fields=node.id_fields,
            resolved_from=resolved_from,
        )
        out.update(
            {
                "branch_a_id": branch_a_id,
                "branch_b_id": branch_b_id,
                "branch_axis_id": axis_id,
            }
        )
        return out

    scan_max = float(params["scan_max_limit_m"])
    stop_dist = float(scan_max)
    stop_reason = "max_200"
    next_inter: float | None = None
    stop_diag: dict[str, Any] = {}
    if bool(params.get("stop_at_next_intersection", True)):
        next_inter, stop_diag = road_graph.find_next_intersection_connected_deg3(
            nodeid=nodeid,
            scan_dir=scan_vec,
            degree_min=int(params.get("next_intersection_degree_min", 3)),
            max_hops=64,
        )
        deg_skip = int(stop_diag.get("deg_too_low_skipped", 0))
        if deg_skip > 0:
            _add_bp(
                code=BP_NEXT_INTERSECTION_DEG_TOO_LOW_SKIPPED,
                severity="soft",
                message="next_intersection_degree_too_low_skipped",
                extra={"count": int(deg_skip)},
            )
        if next_inter is not None and next_inter > 0:
            stop_reason = "next_intersection_connected_deg3"
            stop_dist = min(stop_dist, float(next_inter))
        else:
            stop_reason = "next_intersection_not_found_deg3"
            _add_bp(
                code=BP_NEXT_INTERSECTION_NOT_FOUND_DEG3,
                severity="soft",
                message="next_intersection_not_found_deg3",
                extra={"diag": dict(stop_diag)},
            )
    else:
        stop_reason = "next_intersection_disabled"
        _add_bp(
            code=BP_NEXT_INTERSECTION_DISABLED,
            severity="soft",
            message="next_intersection_disabled",
        )

    if stop_dist >= scan_max - 1e-9 and stop_reason == "next_intersection_connected_deg3":
        stop_reason = "max_200"

    stop_dist = max(0.0, float(stop_dist))
    step = max(0.25, float(params["scan_step_m"]))
    n_steps = max(1, int(math.floor(stop_dist / step)) + 1)
    half_len = float(params["cross_half_len_m"])
    div_tol = float(params.get("divstrip_hit_tol_m", 1.0))
    min_piece_len_m = float(params.get("min_piece_len_m", 1.0))
    found_split = False
    found_seg: LineString | None = None
    found_pieces_raw: list[LineString] = []
    found_diag: dict[str, Any] = {}
    scan_dist = 0.0
    last_seg = dummy_line
    last_diag: dict[str, Any] = {"seg_len_m": float(dummy_line.length), "pa_center_dist_m": None, "pb_center_dist_m": None}

    for i in range(n_steps):
        s = float(i) * step
        center_xy = (
            float(node.point.x) + float(scan_vec[0]) * s,
            float(node.point.y) + float(scan_vec[1]) * s,
        )
        seg, seg_diag = build_between_branches_segment(
            center_xy=center_xy,
            scan_dir=scan_vec,
            branch_a=branch_a,
            branch_b=branch_b,
            crossline_half_len_m=half_len,
        )
        last_seg = seg
        last_diag = seg_diag
        pieces = segment_drivezone_pieces(
            segment=seg,
            drivezone_union=drivezone_union,
            min_piece_len_m=min_piece_len_m,
        )
        if len(pieces) >= 2:
            found_split = True
            found_seg = seg
            found_pieces_raw = pieces
            found_diag = seg_diag
            scan_dist = float(s)
            break

    id_map = {str(k): int(v) for k, v in node.id_fields}
    if not found_split or found_seg is None:
        _add_bp(
            code=BP_DRIVEZONE_SPLIT_NOT_FOUND,
            severity="hard",
            message="drivezone_split_not_found_within_stop_dist",
            extra={"stop_dist_m": float(stop_dist)},
        )
        _add_bp(
            code=BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION,
            severity="soft",
            message="scan_end_without_drivezone_split",
            extra={"stop_dist_m": float(stop_dist)},
        )
        if stop_dist >= min(200.0, scan_max):
            _add_bp(
                code=BP_SCAN_EXCEED_200M,
                severity="soft",
                message="scan_reached_200m_or_max",
                extra={"stop_dist_m": float(stop_dist)},
            )
        anchor_pt = last_seg.interpolate(0.5, normalized=True) if last_seg.length > 1e-9 else Point(float(node.point.x), float(node.point.y))
        dist_line_to_div = None if divstrip_union is None else float(last_seg.distance(divstrip_union))
        dist_to_div = None if divstrip_union is None else float(anchor_pt.distance(divstrip_union))
        dist_line_to_dz_edge = None if drivezone_union is None else float(last_seg.distance(drivezone_union.boundary))
        return {
            "nodeid": int(nodeid),
            "id": id_map.get("id"),
            "mainid": id_map.get("mainid"),
            "mainnodeid": id_map.get("mainnodeid"),
            "kind": None if kind is None else int(kind),
            "is_merge_kind": bool(is_merge),
            "is_diverge_kind": bool(is_diverge),
            "anchor_type": anchor_type,
            "status": "fail",
            "found_split": False,
            "anchor_found": False,
            "trigger": "none",
            "scan_dir": scan_dir_label,
            "scan_dist_m": None,
            "stop_dist_m": float(stop_dist),
            "stop_reason": str(stop_reason),
            "next_intersection_dist_m": None if next_inter is None else float(next_inter),
            "dist_to_divstrip_m": dist_to_div,
            "dist_line_to_divstrip_m": dist_line_to_div,
            "dist_line_to_drivezone_edge_m": dist_line_to_dz_edge,
            "confidence": 0.0,
            "flags": ["drivezone_split_not_found"],
            "evidence_source": "none",
            "anchor_point": anchor_pt,
            "crossline_opt": last_seg,
            "crossline_opt_pieces": [],
            "tip_s_m": None,
            "first_divstrip_hit_dist_m": None,
            "best_divstrip_dz_dist_m": None,
            "best_divstrip_pc_dist_m": None,
            "first_pc_only_dist_m": None,
            "fan_area_m2": 0.0,
            "non_drivezone_area_m2": 0.0,
            "non_drivezone_frac": 0.0,
            "clipped_len_m": float(last_seg.length),
            "clip_empty": True,
            "clip_piece_type": "none",
            "clip_input_len_m": float(last_seg.length),
            "stop_diag": stop_diag,
            "pieces_count": 0,
            "piece_lens_m": [],
            "gap_len_m": None,
            "seg_len_m": float(last_diag.get("seg_len_m", last_seg.length)),
            "branch_a_id": branch_a_id,
            "branch_b_id": branch_b_id,
            "branch_axis_id": axis_id,
            "branch_a_crossline_hit": bool(last_diag.get("branch_a_crossline_hit", False)),
            "branch_b_crossline_hit": bool(last_diag.get("branch_b_crossline_hit", False)),
            "pa_center_dist_m": last_diag.get("pa_center_dist_m"),
            "pb_center_dist_m": last_diag.get("pb_center_dist_m"),
            "has_divstrip_nearby": False,
            "ng_candidates_before_suppress": int(ng_points_xy.shape[0]),
            "ng_candidates_after_suppress": int(ng_points_xy.shape[0]),
            "resolved_from": resolved_from,
        }

    picked_pieces, has_extra_piece = pick_top_two_segment_pieces(segment=found_seg, pieces=found_pieces_raw)
    if len(picked_pieces) < 2:
        _add_bp(
            code=BP_DRIVEZONE_CLIP_EMPTY,
            severity="hard",
            message="drivezone_split_pieces_lt_2_after_filter",
        )
        out = _empty_fail_result(
            nodeid=nodeid,
            kind=kind,
            anchor_type=anchor_type,
            scan_dir=scan_dir_label,
            line=found_seg,
            divstrip_union=divstrip_union,
            drivezone_union=drivezone_union,
            stop_reason="drivezone_clip_empty",
            id_fields=node.id_fields,
            resolved_from=resolved_from,
        )
        out.update(
            {
                "branch_a_id": branch_a_id,
                "branch_b_id": branch_b_id,
                "branch_axis_id": axis_id,
            }
        )
        return out

    if has_extra_piece:
        _add_bp(
            code=BP_DRIVEZONE_CLIP_MULTIPIECE,
            severity="soft",
            message="drivezone_clip_multipiece_select_top2",
            extra={"piece_count": int(len(found_pieces_raw))},
        )

    gap_mid, gap_len = gap_midpoint_between_pieces(segment=found_seg, pieces=picked_pieces)
    if gap_mid is None:
        _add_bp(
            code=BP_ANCHOR_GAP_UNSTABLE,
            severity="soft",
            message="anchor_gap_unstable_fallback_seg_midpoint",
        )
        gap_mid = found_seg.interpolate(0.5, normalized=True) if found_seg.length > 1e-9 else Point(float(node.point.x), float(node.point.y))

    has_divstrip_nearby = False
    dist_line_to_div = None
    dist_to_div = None
    if divstrip_union is not None:
        dist_line_to_div = float(found_seg.distance(divstrip_union))
        has_divstrip_nearby = bool(dist_line_to_div <= float(div_tol))
        dist_to_div = float(gap_mid.distance(divstrip_union))

    if has_divstrip_nearby and bool(params.get("divstrip_anchor_snap_enabled", False)) and divstrip_union is not None:
        try:
            from shapely.ops import nearest_points

            _p0, p1 = nearest_points(gap_mid, divstrip_union.boundary)
            gap_mid = Point(float(p1.x), float(p1.y))
        except Exception:
            pass

    final_geom: LineString | MultiLineString
    if len(picked_pieces) == 1:
        final_geom = picked_pieces[0]
    else:
        final_geom = MultiLineString(picked_pieces)

    piece_lens = [float(ln.length) for ln in picked_pieces]
    clipped_len = float(sum(piece_lens))
    flags: list[str] = []
    if scan_dist > float(params.get("scan_near_limit_m", 20.0)):
        flags.append("scan_dist_gt_near_limit")
    if has_extra_piece:
        flags.append("drivezone_clip_multipiece")
    if has_divstrip_nearby:
        flags.append("divstrip_nearby")
    status = "suspect" if flags else "ok"
    if hard_failed:
        status = "fail"

    dist_line_to_dz_edge = None if drivezone_union is None else float(final_geom.distance(drivezone_union.boundary))
    trigger = "drivezone_split"
    evidence_source = "drivezone_split+divstrip" if has_divstrip_nearby else "drivezone_split"
    conf = compute_confidence(trigger=trigger, scan_dist_m=scan_dist)
    anchor_found = bool(found_split and (not hard_failed) and status in {"ok", "suspect"})
    return {
        "nodeid": int(nodeid),
        "id": id_map.get("id"),
        "mainid": id_map.get("mainid"),
        "mainnodeid": id_map.get("mainnodeid"),
        "kind": None if kind is None else int(kind),
        "is_merge_kind": bool(is_merge),
        "is_diverge_kind": bool(is_diverge),
        "anchor_type": anchor_type,
        "status": status,
        "found_split": True,
        "anchor_found": anchor_found,
        "trigger": trigger,
        "scan_dir": scan_dir_label,
        "scan_dist_m": float(scan_dist),
        "stop_dist_m": float(stop_dist),
        "stop_reason": str(stop_reason),
        "next_intersection_dist_m": None if next_inter is None else float(next_inter),
        "dist_to_divstrip_m": dist_to_div,
        "dist_line_to_divstrip_m": dist_line_to_div,
        "dist_line_to_drivezone_edge_m": dist_line_to_dz_edge,
        "confidence": float(conf),
        "flags": flags,
        "evidence_source": evidence_source,
        "anchor_point": gap_mid,
        "crossline_opt": final_geom,
        "crossline_opt_pieces": picked_pieces,
        "tip_s_m": None,
        "first_divstrip_hit_dist_m": None,
        "best_divstrip_dz_dist_m": float(scan_dist),
        "best_divstrip_pc_dist_m": None,
        "first_pc_only_dist_m": None,
        "fan_area_m2": 0.0,
        "non_drivezone_area_m2": 0.0,
        "non_drivezone_frac": 0.0,
        "clipped_len_m": clipped_len,
        "clip_empty": False,
        "clip_piece_type": "multi_piece_top2" if has_extra_piece else "two_piece",
        "clip_input_len_m": float(found_seg.length),
        "stop_diag": stop_diag,
        "pieces_count": int(len(picked_pieces)),
        "piece_lens_m": piece_lens,
        "gap_len_m": None if gap_len is None else float(gap_len),
        "seg_len_m": float(found_diag.get("seg_len_m", found_seg.length)),
        "branch_a_id": branch_a_id,
        "branch_b_id": branch_b_id,
        "branch_axis_id": axis_id,
        "branch_a_crossline_hit": bool(found_diag.get("branch_a_crossline_hit", False)),
        "branch_b_crossline_hit": bool(found_diag.get("branch_b_crossline_hit", False)),
        "pa_center_dist_m": found_diag.get("pa_center_dist_m"),
        "pb_center_dist_m": found_diag.get("pb_center_dist_m"),
        "has_divstrip_nearby": bool(has_divstrip_nearby),
        "ng_candidates_before_suppress": int(ng_points_xy.shape[0]),
        "ng_candidates_after_suppress": int(ng_points_xy.shape[0]),
        "resolved_from": resolved_from,
    }


def _serialize_seed_result(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    out.pop("anchor_point", None)
    out.pop("crossline_opt", None)
    out.pop("crossline_opt_pieces", None)
    return out


def _empty_traj_result() -> TrajLoadResult:
    return TrajLoadResult(
        points_xy=np.zeros((0, 2), dtype=np.float64),
        paths=[],
        total_points=0,
        src_crs_list=[],
        per_file_meta=[],
    )


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

    src_crs_global = str(runtime.get("src_crs", "auto"))
    dst_crs = str(runtime.get("dst_crs", "EPSG:3857"))
    node_src_crs = _resolve_src_hint(hint=runtime.get("node_src_crs"), global_hint=src_crs_global)
    road_src_crs = _resolve_src_hint(hint=runtime.get("road_src_crs"), global_hint=src_crs_global)
    divstrip_src_crs = _resolve_src_hint(hint=runtime.get("divstrip_src_crs"), global_hint=src_crs_global)
    drivezone_src_crs = _resolve_src_hint(hint=runtime.get("drivezone_src_crs"), global_hint=src_crs_global)
    traj_src_crs = _resolve_src_hint(hint=runtime.get("traj_src_crs"), global_hint=src_crs_global)
    pointcloud_crs = _resolve_src_hint(hint=runtime.get("pointcloud_crs"), global_hint=src_crs_global)
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

    drivezone_path = _normalize_user_path(runtime.get("drivezone_path"))
    if drivezone_path is None:
        drivezone_path = vector_dir / "DriveZone.geojson"

    pointcloud_path = _normalize_user_path(runtime.get("pointcloud_path"))
    if pointcloud_path is None:
        pointcloud_path = default_pointcloud_path(patch_dir)

    breakpoints: list[dict[str, Any]] = []

    traj_glob = _normalize_user_glob(runtime.get("traj_glob"))
    traj_paths = discover_traj_paths(patch_dir=patch_dir, traj_glob=traj_glob)
    traj = _empty_traj_result()
    try:
        traj = load_traj_points(paths=traj_paths, src_crs_override=traj_src_crs, dst_crs=dst_crs)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "crs_unknown:" in msg:
            breakpoints.append(
                make_breakpoint(
                    code=BP_CRS_UNKNOWN,
                    severity="hard",
                    nodeid=None,
                    message="traj_crs_unknown",
                    extra={"detail": msg},
                )
            )
        else:
            breakpoints.append(
                make_breakpoint(
                    code=BP_TRAJ_MISSING,
                    severity="soft",
                    nodeid=None,
                    message=f"traj_load_failed:{type(exc).__name__}",
                )
            )

    if traj.total_points <= 0:
        breakpoints.append(
            make_breakpoint(
                code=BP_TRAJ_MISSING,
                severity="soft",
                nodeid=None,
                message="traj_missing_or_empty",
            )
        )

    aoi = _build_aoi(
        pointcloud_path=pointcloud_path,
        pointcloud_crs_hint=pointcloud_crs,
        traj_points_xy=traj.points_xy,
        dst_crs=dst_crs,
    )

    # Focus matching must not depend on geometry coverage; keep node load out of AOI clipping in global_focus mode.
    node_aoi = None if mode == "global_focus" else aoi

    nodes_raw: list[NodeRecord] = []
    roads: list[RoadRecord] = []
    node_errors: list[str] = []
    road_errors: list[str] = []
    node_meta: dict[str, Any] = {"path": str(node_path), "src_crs_used": None, "dst_crs": dst_crs}
    road_meta: dict[str, Any] = {"path": str(road_path), "src_crs_used": None, "dst_crs": dst_crs}

    try:
        nodes_raw, _meta, node_errors = load_nodes(path=node_path, src_crs_override=node_src_crs, dst_crs=dst_crs, aoi=node_aoi)
        node_meta = {
            "path": _meta.path,
            "src_crs_detected": _meta.src_crs_detected,
            "src_crs_used": _meta.src_crs,
            "dst_crs": _meta.dst_crs,
            "bbox_src": _meta.bbox_src,
            "bbox_dst": _meta.bbox_dst,
            "guess_source": _meta.guess_source,
            "total_features": _meta.total_features,
            "kept_features": _meta.kept_features,
            "errors": node_errors,
        }
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "crs_unknown:" in msg:
            breakpoints.append(
                make_breakpoint(
                    code=BP_CRS_UNKNOWN,
                    severity="hard",
                    nodeid=None,
                    message="node_crs_unknown",
                    extra={"detail": msg},
                )
            )
        else:
            raise

    try:
        roads, _meta, road_errors = load_roads(path=road_path, src_crs_override=road_src_crs, dst_crs=dst_crs, aoi=aoi)
        road_meta = {
            "path": _meta.path,
            "src_crs_detected": _meta.src_crs_detected,
            "src_crs_used": _meta.src_crs,
            "dst_crs": _meta.dst_crs,
            "bbox_src": _meta.bbox_src,
            "bbox_dst": _meta.bbox_dst,
            "guess_source": _meta.guess_source,
            "total_features": _meta.total_features,
            "kept_features": _meta.kept_features,
            "errors": road_errors,
        }
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "crs_unknown:" in msg:
            breakpoints.append(
                make_breakpoint(
                    code=BP_CRS_UNKNOWN,
                    severity="hard",
                    nodeid=None,
                    message="road_crs_unknown",
                    extra={"detail": msg},
                )
            )
        else:
            raise

    for err in road_errors:
        if str(err).startswith("road_field_missing:"):
            breakpoints.append(
                make_breakpoint(
                    code=BP_ROAD_FIELD_MISSING,
                    severity="soft",
                    nodeid=None,
                    message=str(err),
                )
            )

    nodes, alias_to_canonical = _resolve_nodes_aliases(nodes=nodes_raw, roads=roads)
    focus_ids = [str(x) for x in runtime.get("focus_node_ids", [])]
    seeds, resolved_from_map = _pick_seed_nodes(
        mode=mode,
        nodes=nodes,
        focus_ids=focus_ids,
        alias_to_canonical=alias_to_canonical,
        breakpoints=breakpoints,
    )

    node_points = {int(n.nodeid): Point(float(n.point.x), float(n.point.y)) for n in nodes}
    node_kinds = {int(n.nodeid): int(n.kind) if n.kind is not None else 0 for n in nodes}
    road_graph = RoadGraph(roads=roads, node_points=node_points, node_kinds=node_kinds)

    divstrip_union = None
    divstrip_meta: dict[str, Any] = {
        "path": str(divstrip_path),
        "exists": bool(divstrip_path and divstrip_path.is_file()),
        "src_crs_detected": None,
        "src_crs_used": None,
        "dst_crs": dst_crs,
        "bbox_src": None,
        "bbox_dst": None,
    }
    if divstrip_path is not None and divstrip_path.is_file():
        try:
            divstrip_union, meta, div_errors = load_divstrip_union(
                path=divstrip_path,
                src_crs_override=divstrip_src_crs,
                dst_crs=dst_crs,
                aoi=aoi,
            )
            divstrip_meta.update(
                {
                    "src_crs_detected": meta.src_crs_detected,
                    "src_crs_used": meta.src_crs,
                    "dst_crs": meta.dst_crs,
                    "bbox_src": meta.bbox_src,
                    "bbox_dst": meta.bbox_dst,
                    "guess_source": meta.guess_source,
                    "total_features": meta.total_features,
                    "kept_features": meta.kept_features,
                    "errors": div_errors,
                }
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "crs_unknown:" in msg:
                breakpoints.append(
                    make_breakpoint(
                        code=BP_CRS_UNKNOWN,
                        severity="hard",
                        nodeid=None,
                        message="divstrip_crs_unknown",
                        extra={"detail": msg},
                    )
                )
            else:
                raise
    else:
        breakpoints.append(
            make_breakpoint(
                code=BP_DIVSTRIPZONE_MISSING,
                severity="soft",
                nodeid=None,
                message="divstripzone_missing",
            )
        )

    use_drivezone_cfg = bool(params.get("use_drivezone", True))
    drivezone_union = None
    drivezone_usable = False
    drivezone_meta: dict[str, Any] = {
        "path": str(drivezone_path),
        "enabled": bool(use_drivezone_cfg),
        "exists": bool(drivezone_path and drivezone_path.is_file()),
        "src_crs_detected": None,
        "src_crs_used": None,
        "dst_crs": dst_crs,
        "bbox_src": None,
        "bbox_dst": None,
    }
    if use_drivezone_cfg:
        if drivezone_path is None or (not drivezone_path.is_file()):
            breakpoints.append(
                make_breakpoint(
                    code=BP_DRIVEZONE_MISSING,
                    severity="hard",
                    nodeid=None,
                    message="drivezone_missing",
                )
            )
        else:
            try:
                drivezone_union, meta, dz_errors = load_drivezone_union(
                    path=drivezone_path,
                    src_crs_override=drivezone_src_crs,
                    dst_crs=dst_crs,
                    aoi=aoi,
                )
                drivezone_meta.update(
                    {
                        "src_crs_detected": meta.src_crs_detected,
                        "src_crs_used": meta.src_crs,
                        "dst_crs": meta.dst_crs,
                        "bbox_src": meta.bbox_src,
                        "bbox_dst": meta.bbox_dst,
                        "guess_source": meta.guess_source,
                        "total_features": meta.total_features,
                        "kept_features": meta.kept_features,
                        "errors": dz_errors,
                    }
                )
                drivezone_usable = bool(drivezone_union is not None and (not drivezone_union.is_empty))
                if not drivezone_usable:
                    breakpoints.append(
                        make_breakpoint(
                            code=BP_DRIVEZONE_UNION_EMPTY,
                            severity="hard",
                            nodeid=None,
                            message="drivezone_union_empty_or_invalid",
                        )
                    )
                if any(str(x) == "drivezone_union_empty" for x in dz_errors):
                    breakpoints.append(
                        make_breakpoint(
                            code=BP_DRIVEZONE_UNION_EMPTY,
                            severity="hard",
                            nodeid=None,
                            message="drivezone_union_empty",
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if "crs_unknown:" in msg:
                    breakpoints.append(
                        make_breakpoint(
                            code=BP_DRIVEZONE_CRS_UNKNOWN,
                            severity="hard",
                            nodeid=None,
                            message="drivezone_crs_unknown",
                            extra={"detail": msg},
                        )
                    )
                else:
                    raise

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
        pointcloud = load_pointcloud(
            path=pointcloud_path,
            use_classification=bool(params["pc_use_classification"]),
            src_crs_hint=pointcloud_crs,
            dst_crs=dst_crs,
        )
        pointcloud_usable = bool(pointcloud.usable)
        if not pointcloud_usable:
            reason = str(pointcloud.reason or "pointcloud_unusable")
            bp_code = BP_POINTCLOUD_MISSING_OR_UNUSABLE
            if reason.startswith("pointcloud_crs_unknown"):
                bp_code = BP_POINTCLOUD_CRS_UNKNOWN_UNUSABLE
            breakpoints.append(
                make_breakpoint(
                    code=bp_code,
                    severity="soft",
                    nodeid=None,
                    message=reason,
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
                "bbox_src": pointcloud.bbox_src,
                "bbox_dst": pointcloud.bbox_dst,
                "src_crs_detected": pointcloud.src_crs_detected,
                "src_crs_used": pointcloud.src_crs_used,
                "dst_crs": pointcloud.dst_crs,
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
            drivezone_union=drivezone_union,
            drivezone_usable=bool(drivezone_usable and use_drivezone_cfg),
            ng_points_xy=ng_points_xy,
            params=params,
            breakpoints=breakpoints,
            pointcloud_usable=pointcloud_usable,
            resolved_from=resolved_from_map.get(int(node.nodeid)),
        )
        res["ng_candidates_before_suppress"] = int(ng_before_suppress)
        res["ng_candidates_after_suppress"] = int(ng_after_suppress)
        seed_results.append(res)

    dst_tag = "3857" if str(dst_crs).upper() == "EPSG:3857" else str(dst_crs).split(":")[-1].lower()
    anchors_dst_path = out_dir / f"anchors_{dst_tag}.geojson"
    inter_opt_dst_path = out_dir / f"intersection_l_opt_{dst_tag}.geojson"
    anchors_wgs84_path = out_dir / "anchors_wgs84.geojson"
    inter_opt_wgs84_path = out_dir / "intersection_l_opt_wgs84.geojson"
    anchors_geojson_path = out_dir / "anchors.geojson"
    inter_opt_path = out_dir / "intersection_l_opt.geojson"
    anchors_json_path = out_dir / "anchors.json"
    metrics_path = out_dir / "metrics.json"
    breakpoints_path = out_dir / "breakpoints.json"
    summary_path = out_dir / "summary.txt"
    chosen_config_path = out_dir / "chosen_config.json"

    write_anchor_geojson(path=anchors_dst_path, seed_results=seed_results, src_crs_name=dst_crs, dst_crs_name=dst_crs)
    write_intersection_opt_geojson(path=inter_opt_dst_path, seed_results=seed_results, src_crs_name=dst_crs, dst_crs_name=dst_crs)
    write_anchor_geojson(path=anchors_wgs84_path, seed_results=seed_results, src_crs_name=dst_crs, dst_crs_name="EPSG:4326")
    write_intersection_opt_geojson(path=inter_opt_wgs84_path, seed_results=seed_results, src_crs_name=dst_crs, dst_crs_name="EPSG:4326")
    write_anchor_geojson(path=anchors_geojson_path, seed_results=seed_results, src_crs_name=dst_crs, dst_crs_name=dst_crs)
    write_intersection_opt_geojson(path=inter_opt_path, seed_results=seed_results, src_crs_name=dst_crs, dst_crs_name=dst_crs)

    anchors_json_payload = {
        "run_id": str(run_id),
        "patch_id": str(patch_id),
        "mode": str(mode),
        "items": [_serialize_seed_result(x) for x in seed_results],
    }
    write_json(anchors_json_path, anchors_json_payload)

    bp_summary = summarize_breakpoints(breakpoints)
    write_json(breakpoints_path, bp_summary)

    traj_src_detected = None
    traj_bbox_src = None
    traj_bbox_dst = None
    if traj.per_file_meta:
        first_meta = traj.per_file_meta[0]
        traj_src_detected = first_meta.get("src_crs_detected")
        traj_bbox_src = first_meta.get("bbox_src")
        traj_bbox_dst = first_meta.get("bbox_dst")

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
        "drivezone_path": str(drivezone_path),
        "pointcloud_path": str(pointcloud_path) if pointcloud_path else None,
        "traj_glob": traj_glob,
        "focus_node_ids": focus_ids,
        "src_crs": str(src_crs_global),
        "dst_crs": str(dst_crs),
        "node_src_crs": str(node_src_crs),
        "road_src_crs": str(road_src_crs),
        "divstrip_src_crs": str(divstrip_src_crs),
        "drivezone_src_crs": str(drivezone_src_crs),
        "traj_src_crs": str(traj_src_crs),
        "pointcloud_crs": str(pointcloud_crs),
        "params": params,
        "load_meta": {
            "nodes": node_meta,
            "roads": road_meta,
            "divstrip": divstrip_meta,
            "drivezone": drivezone_meta,
            "pointcloud": pointcloud_meta,
            "traj": {
                "path_count": len(traj.paths),
                "total_points": int(traj.total_points),
                "src_crs_list": traj.src_crs_list,
                "src_crs_detected": traj_src_detected,
                "src_crs_used": traj.src_crs_list[0] if traj.src_crs_list else None,
                "dst_crs": str(dst_crs),
                "bbox_src": traj_bbox_src,
                "bbox_dst": traj_bbox_dst,
                "per_file_meta": traj.per_file_meta,
            },
        },
    }
    write_json(chosen_config_path, chosen_config)

    required_paths = [
        anchors_dst_path,
        inter_opt_dst_path,
        anchors_wgs84_path,
        inter_opt_wgs84_path,
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
            "drivezone_usable": bool(drivezone_usable and use_drivezone_cfg),
            "pointcloud_class_counts": pointcloud_meta.get("class_counts", {}),
            "ng_candidates_before_suppress": int(ng_before_suppress),
            "ng_candidates_after_suppress": int(ng_after_suppress),
            "traj_suppressed_count": int(traj_suppressed_count),
            "aoi_used": bool(aoi is not None),
            "focus_node_ids": focus_ids,
            "dst_crs": str(dst_crs),
        }
    )
    write_json(metrics_path, metrics)

    crs_diag = {
        "dst_crs": str(dst_crs),
        "layer_crs": {
            "node": {
                "src_crs_detected": node_meta.get("src_crs_detected"),
                "src_crs_used": node_meta.get("src_crs_used"),
                "dst_crs": node_meta.get("dst_crs"),
                "bbox_src": node_meta.get("bbox_src"),
                "bbox_dst": node_meta.get("bbox_dst"),
            },
            "road": {
                "src_crs_detected": road_meta.get("src_crs_detected"),
                "src_crs_used": road_meta.get("src_crs_used"),
                "dst_crs": road_meta.get("dst_crs"),
                "bbox_src": road_meta.get("bbox_src"),
                "bbox_dst": road_meta.get("bbox_dst"),
            },
            "divstrip": {
                "src_crs_detected": divstrip_meta.get("src_crs_detected"),
                "src_crs_used": divstrip_meta.get("src_crs_used"),
                "dst_crs": divstrip_meta.get("dst_crs"),
                "bbox_src": divstrip_meta.get("bbox_src"),
                "bbox_dst": divstrip_meta.get("bbox_dst"),
            },
            "drivezone": {
                "src_crs_detected": drivezone_meta.get("src_crs_detected"),
                "src_crs_used": drivezone_meta.get("src_crs_used"),
                "dst_crs": drivezone_meta.get("dst_crs"),
                "bbox_src": drivezone_meta.get("bbox_src"),
                "bbox_dst": drivezone_meta.get("bbox_dst"),
            },
            "traj": {
                "src_crs_detected": traj_src_detected,
                "src_crs_used": traj.src_crs_list[0] if traj.src_crs_list else None,
                "dst_crs": str(dst_crs),
                "bbox_src": traj_bbox_src,
                "bbox_dst": traj_bbox_dst,
            },
            "pointcloud": {
                "src_crs_detected": pointcloud_meta.get("src_crs_detected"),
                "src_crs_used": pointcloud_meta.get("src_crs_used"),
                "dst_crs": pointcloud_meta.get("dst_crs"),
                "bbox_src": pointcloud_meta.get("bbox_src"),
                "bbox_dst": pointcloud_meta.get("bbox_dst"),
            },
        },
    }

    summary = build_summary_text(
        run_id=str(run_id),
        patch_id=str(patch_id),
        mode=str(mode),
        metrics=metrics,
        breakpoints_summary=bp_summary,
        seed_results=[_serialize_seed_result(x) for x in seed_results],
        crs_diag=crs_diag,
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
                "drivezone_usable": bool(drivezone_usable and use_drivezone_cfg),
                "pointcloud_class_counts": pointcloud_meta.get("class_counts", {}),
                "ng_candidates_before_suppress": int(ng_before_suppress),
                "ng_candidates_after_suppress": int(ng_after_suppress),
                "traj_suppressed_count": int(traj_suppressed_count),
                "aoi_used": bool(aoi is not None),
                "focus_node_ids": focus_ids,
                "dst_crs": str(dst_crs),
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
            crs_diag=crs_diag,
        )
        write_text(summary_path, summary)

    return RunResult(
        run_id=str(run_id),
        patch_id=str(patch_id),
        mode=str(mode),
        out_dir=out_dir,
        overall_pass=bool(metrics.get("overall_pass", False)),
    )


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
        "node_src_crs": cfg.get("node_src_crs"),
        "road_src_crs": cfg.get("road_src_crs"),
        "divstrip_src_crs": cfg.get("divstrip_src_crs"),
        "drivezone_src_crs": cfg.get("drivezone_src_crs"),
        "traj_src_crs": cfg.get("traj_src_crs"),
        "pointcloud_crs": cfg.get("pointcloud_crs"),
        "global_node_path": cfg.get("global_node_path"),
        "global_road_path": cfg.get("global_road_path"),
        "divstrip_path": cfg.get("divstrip_path"),
        "drivezone_path": cfg.get("drivezone_path"),
        "pointcloud_path": cfg.get("pointcloud_path"),
        "traj_glob": cfg.get("traj_glob"),
        "focus_node_ids": [str(x) for x in cfg.get("focus_node_ids", [])],
        "params": cfg.get("params", cfg),
        "config_json": cfg.get("config_json"),
    }
    return run_from_runtime(runtime)


__all__ = ["RunResult", "run_from_runtime", "run_patch"]
