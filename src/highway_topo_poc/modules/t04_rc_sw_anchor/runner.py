from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry

from .between_branches import build_between_branches_segment, select_branch_pair_and_axis
from .continuous_chain import ChainComponent, build_continuous_graph
from .crs_norm import guess_crs_from_bbox, normalize_epsg_name, transform_xy_arrays
from .divstrip_ops import anchor_point_from_crossline, tip_point_from_divstrip
from .drivezone_ops import segment_drivezone_pieces
from .io_geojson import NodeRecord, RoadRecord, load_divstrip_union, load_drivezone_union, load_nodes, load_roads
from .k16_ops import (
    build_crossline as build_k16_crossline,
    compute_tangent_at_node as compute_k16_tangent_at_node,
    find_unique_k16_road,
    search_crossline_hit_drivezone,
)
from .local_frame import LocalFrame
from .metrics_breakpoints import (
    BP_AMBIGUOUS_KIND,
    BP_CRS_UNKNOWN,
    BP_DIVSTRIP_NON_INTERSECT_NOT_FOUND,
    BP_DIVSTRIPZONE_MISSING,
    BP_DRIVEZONE_CLIP_EMPTY,
    BP_DRIVEZONE_CLIP_MULTIPIECE,
    BP_DRIVEZONE_CRS_UNKNOWN,
    BP_DRIVEZONE_MISSING,
    BP_K16_DRIVEZONE_NOT_REACHED,
    BP_K16_ROAD_DIR_UNSUPPORTED,
    BP_K16_ROAD_NOT_UNIQUE,
    BP_SEQUENTIAL_ORDER_VIOLATION,
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
    BP_REVERSE_TIP_ATTEMPTED,
    BP_REVERSE_TIP_NOT_FOUND,
    BP_REVERSE_TIP_USED,
    BP_ROAD_FIELD_MISSING,
    BP_ROAD_LINK_NOT_FOUND,
    BP_SCAN_EXCEED_200M,
    BP_TRAJ_MISSING,
    BP_UNTRUSTED_DIVSTRIP_AT_NODE,
    BP_UNSUPPORTED_KIND,
    build_metrics,
    build_summary_text,
    compute_confidence,
    make_breakpoint,
    summarize_breakpoints,
)
from .multibranch_ops import (
    build_crossline_span,
    collect_valid_branches_by_direction,
    compute_pieces_count,
    crossline_span_points_all_branches,
    extract_split_events,
)
from .pointcloud_io import PointCloudData, default_pointcloud_path, load_pointcloud, pick_non_ground_candidates, pointcloud_bbox
from .road_graph import RoadGraph
from .traj_io import TrajLoadResult, build_traj_grid_index, discover_traj_paths, load_traj_points, mark_points_near_traj
from .writers import (
    write_anchor_geojson,
    write_intersection_multi_geojson,
    write_intersection_opt_geojson,
    write_json,
    write_text,
)


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
    is_in_continuous_chain: bool = False,
    chain_component_id: str | None = None,
    chain_node_offset_m: float | None = None,
    abs_s_prev_required_m: float | None = None,
    sequential_violation_reason: str | None = None,
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
        "s_divstrip_m": None,
        "s_drivezone_split_m": None,
        "s_chosen_m": None,
        "split_pick_source": "none",
        "divstrip_ref_source": "none",
        "divstrip_ref_offset_m": None,
        "output_cross_half_len_m": None,
        "branch_a_id": None,
        "branch_b_id": None,
        "branch_axis_id": None,
        "branch_a_crossline_hit": False,
        "branch_b_crossline_hit": False,
        "pa_center_dist_m": None,
        "pb_center_dist_m": None,
        "has_divstrip_nearby": False,
        "reverse_tip_attempted": False,
        "reverse_tip_used": False,
        "reverse_tip_not_improved": False,
        "reverse_search_max_m": None,
        "reverse_trigger": None,
        "ref_s_forward_m": None,
        "position_source_forward": None,
        "ref_s_reverse_m": None,
        "position_source_reverse": None,
        "ref_s_final_m": None,
        "position_source_final": None,
        "untrusted_divstrip_at_node": False,
        "node_to_divstrip_m_at_s0": None,
        "seg0_intersects_divstrip": None,
        "ng_candidates_before_suppress": 0,
        "ng_candidates_after_suppress": 0,
        "is_in_continuous_chain": bool(is_in_continuous_chain),
        "chain_component_id": chain_component_id,
        "chain_node_offset_m": None if chain_node_offset_m is None else float(chain_node_offset_m),
        "abs_s_chosen_m": None,
        "abs_s_prev_required_m": None if abs_s_prev_required_m is None else float(abs_s_prev_required_m),
        "sequential_ok": False,
        "sequential_violation_reason": sequential_violation_reason,
        "merged": False,
        "merged_group_id": None,
        "merged_with_nodeids": None,
        "abs_s_merged_m": None,
        "merged_crossline_id": None,
        "merged_output_nodeids": None,
        "merged_output_kinds": None,
        "merged_output_roles": None,
        "merged_output_anchor_types": None,
        "merge_reason": None,
        "merge_geom_dist_m": None,
        "merge_abs_diff_m": None,
        "merge_abs_gap_cfg_m": None,
        "merge_abs_gate_skipped": None,
        "suppress_intersection_feature": False,
        "multibranch_enabled": False,
        "multibranch_N": 0,
        "multibranch_expected_events": 0,
        "split_events_forward": [],
        "split_events_reverse": [],
        "s_main_m": None,
        "main_pick_source": "none",
        "abnormal_two_sided": False,
        "span_extra_m": None,
        "direction_filter_applied": True,
        "branches_used_count": 0,
        "branches_ignored_due_to_direction": 0,
        "s_drivezone_split_first_m": None,
        "multibranch_event_lines": [],
        "resolved_from": resolved_from,
    }


def _compute_abs_s(
    *,
    is_diverge: bool,
    is_merge: bool,
    node_offset_m: float | None,
    s_local: float | None,
) -> float | None:
    if node_offset_m is None or s_local is None:
        return None
    if is_diverge:
        return float(node_offset_m + float(s_local))
    if is_merge:
        return float(node_offset_m - float(s_local))
    return None


def _resolve_ref_s_local(item: dict[str, Any]) -> float | None:
    s_div = item.get("s_divstrip_m")
    s_dz = item.get("s_drivezone_split_m")
    src = str(item.get("position_source") or "")
    if src == "divstrip_ref" and s_div is not None:
        return float(s_div)
    if s_dz is not None:
        return float(s_dz)
    if s_div is not None:
        return float(s_div)
    s_chosen = item.get("s_chosen_m")
    if s_chosen is not None:
        return float(s_chosen)
    return None


def _abs_window_from_item(item: dict[str, Any], *, window_m: float = 1.0) -> tuple[float, float] | None:
    if not bool(item.get("is_in_continuous_chain", False)):
        return None
    offset = item.get("chain_node_offset_m")
    if offset is None:
        return None
    ref_s = _resolve_ref_s_local(item)
    if ref_s is None:
        return None
    lo = max(0.0, float(ref_s) - float(window_m))
    hi = float(ref_s)
    if hi + 1e-9 < lo:
        lo, hi = hi, lo

    if bool(item.get("is_diverge_kind", False)):
        a0 = float(offset) + float(lo)
        a1 = float(offset) + float(hi)
    elif bool(item.get("is_merge_kind", False)):
        a0 = float(offset) - float(hi)
        a1 = float(offset) - float(lo)
    else:
        return None
    return (float(min(a0, a1)), float(max(a0, a1)))


def _apply_continuous_merges(
    *,
    seed_results: list[dict[str, Any]],
    components: list[ChainComponent],
    merge_gap_m: float,
    geom_tol_m: float = 1.0,
) -> None:
    item_by_id: dict[int, dict[str, Any]] = {}
    for item in seed_results:
        try:
            nodeid = int(item.get("nodeid"))
        except Exception:
            continue
        item_by_id[nodeid] = item

    used_nodeids: set[int] = set()
    tol = 1e-6

    for comp in components:
        incoming: dict[int, list[tuple[int, float]]] = {}
        for edge in comp.edges:
            incoming.setdefault(int(edge.dst), []).append((int(edge.src), float(edge.dist_m)))

        for edge in sorted(comp.edges, key=lambda x: (float(x.dist_m), int(x.src), int(x.dst))):
            src = int(edge.src)
            dst = int(edge.dst)
            if src in used_nodeids or dst in used_nodeids:
                continue
            src_item = item_by_id.get(src)
            dst_item = item_by_id.get(dst)
            if src_item is None or dst_item is None:
                continue
            if str(src_item.get("status")) == "fail" or str(dst_item.get("status")) == "fail":
                continue
            if not bool(src_item.get("is_diverge_kind", False)):
                continue
            if not bool(dst_item.get("is_merge_kind", False)):
                continue

            preds = incoming.get(dst, [])
            if not preds:
                continue
            primary_pred = min(preds, key=lambda x: (float(x[1]), int(x[0])))[0]
            if int(primary_pred) != int(src):
                continue

            line_src = src_item.get("crossline_opt")
            line_dst = dst_item.get("crossline_opt")
            if not isinstance(line_src, LineString) or not isinstance(line_dst, LineString):
                continue
            geom_dist = float(line_src.distance(line_dst))
            geom_intersects = bool(line_src.intersects(line_dst))
            if (not geom_intersects) and (geom_dist > float(geom_tol_m) + tol):
                continue

            abs_src = src_item.get("abs_s_chosen_m")
            abs_dst = dst_item.get("abs_s_chosen_m")
            abs_src_f = None if abs_src is None else float(abs_src)
            abs_dst_f = None if abs_dst is None else float(abs_dst)
            abs_diff = None
            abs_mean = None
            if abs_src_f is not None and abs_dst_f is not None:
                abs_diff = float(abs(abs_src_f - abs_dst_f))
                abs_mean = float(0.5 * (abs_src_f + abs_dst_f))

            group_id = f"{comp.component_id}:{src}->{dst}"
            keep_src = float(line_src.length) >= float(line_dst.length)
            keeper = src_item if keep_src else dst_item
            suppressed = dst_item if keep_src else src_item

            merged_nodeids = [int(src), int(dst)]
            merged_kinds = [src_item.get("kind"), dst_item.get("kind")]
            merged_roles = ["diverge", "merge"]
            merged_anchor_types = [src_item.get("anchor_type"), dst_item.get("anchor_type")]

            for item in [src_item, dst_item]:
                item["merged"] = True
                item["merged_group_id"] = str(group_id)
                item["merged_with_nodeids"] = list(merged_nodeids)
                item["abs_s_merged_m"] = None if abs_mean is None else float(abs_mean)
                item["merged_crossline_id"] = str(group_id)
                item["merge_reason"] = "geom_intersects" if geom_intersects else "geom_near_tol"
                item["merge_geom_dist_m"] = float(geom_dist)
                item["merge_abs_diff_m"] = abs_diff
                item["merge_abs_gap_cfg_m"] = float(merge_gap_m)
                item["merge_abs_gate_skipped"] = True

            keeper["merged_output_nodeids"] = list(merged_nodeids)
            keeper["merged_output_kinds"] = list(merged_kinds)
            keeper["merged_output_roles"] = list(merged_roles)
            keeper["merged_output_anchor_types"] = list(merged_anchor_types)
            keeper["suppress_intersection_feature"] = False

            suppressed["merged_output_nodeids"] = None
            suppressed["merged_output_kinds"] = None
            suppressed["merged_output_roles"] = None
            suppressed["merged_output_anchor_types"] = None
            suppressed["suppress_intersection_feature"] = True

            used_nodeids.add(int(src))
            used_nodeids.add(int(dst))


def _should_fallback_to_drivezone(
    *,
    divstrip_ref_s: float,
    drivezone_split_s: float,
    max_offset_m: float,
) -> bool:
    return (abs(float(divstrip_ref_s)) - abs(float(drivezone_split_s))) > float(max_offset_m)


def _pick_reference_s(
    *,
    divstrip_ref_s: float | None,
    divstrip_ref_source: str,
    drivezone_split_s: float | None,
    max_offset_m: float,
) -> tuple[float | None, str, str]:
    if divstrip_ref_s is not None:
        ref_s = float(divstrip_ref_s)
        pick = f"divstrip_{str(divstrip_ref_source)}_window"
        if drivezone_split_s is not None and _should_fallback_to_drivezone(
            divstrip_ref_s=float(ref_s),
            drivezone_split_s=float(drivezone_split_s),
            max_offset_m=float(max_offset_m),
        ):
            return float(drivezone_split_s), "drivezone_split", "drivezone_split_window_divstrip_far_ignored"
        return float(ref_s), "divstrip_ref", str(pick)
    if drivezone_split_s is not None:
        return float(drivezone_split_s), "drivezone_split", "drivezone_split_window"
    return None, "none", "none"


def _build_ref_window_away_from_node(*, ref_s: float, window_m: float) -> tuple[float, float, float]:
    w = max(0.0, float(window_m))
    ref = float(ref_s)
    sign = -1.0 if ref < 0.0 else 1.0
    far_s = ref + sign * w
    lo = min(ref, far_s)
    hi = max(ref, far_s)
    return float(lo), float(hi), float(far_s)


def _build_ref_window_toward_node(*, ref_s: float, window_m: float) -> tuple[float, float, float]:
    w = max(0.0, float(window_m))
    ref = float(ref_s)
    sign = -1.0 if ref < 0.0 else 1.0
    near_s = ref - sign * w
    lo = min(ref, near_s)
    hi = max(ref, near_s)
    return float(lo), float(hi), float(near_s)


def _build_continuous_line_from_crossline(
    *,
    crossline: LineString,
    pieces_raw: list[LineString],
    center_xy: tuple[float, float],
    found_seg: LineString,
    drivezone_union: BaseGeometry | None,
    edge_pad_m: float,
) -> tuple[LineString | None, dict[str, Any]]:
    out_diag: dict[str, Any] = {
        "ok": False,
        "reason": "unknown",
        "pieces_count": int(len(pieces_raw)),
        "center_piece_hit": False,
    }
    if not pieces_raw:
        out_diag["reason"] = "pieces_empty"
        return None, out_diag

    center_pt = Point(float(center_xy[0]), float(center_xy[1]))
    center_s = float(crossline.project(center_pt))

    piece_info: list[tuple[LineString, float, float, float]] = []
    for piece in pieces_raw:
        vals: list[float] = []
        for coord in list(piece.coords):
            if len(coord) < 2:
                continue
            vals.append(float(crossline.project(Point(float(coord[0]), float(coord[1])))))
        if not vals:
            continue
        s0 = float(min(vals))
        s1 = float(max(vals))
        sm = 0.5 * (s0 + s1)
        piece_info.append((piece, s0, s1, sm))

    if not piece_info:
        out_diag["reason"] = "piece_interval_empty"
        return None, out_diag

    pa_pt = Point(float(found_seg.coords[0][0]), float(found_seg.coords[0][1]))
    pb_pt = Point(float(found_seg.coords[-1][0]), float(found_seg.coords[-1][1]))
    pa_s = float(crossline.project(pa_pt))
    pb_s = float(crossline.project(pb_pt))
    left_ref_s, right_ref_s = (pa_s, pb_s) if pa_s <= pb_s else (pb_s, pa_s)

    center_hits = [x for x in piece_info if float(x[1]) - 1e-6 <= center_s <= float(x[2]) + 1e-6]
    if center_hits:
        selected_piece = min(
            center_hits,
            key=lambda x: (
                abs(float(x[3]) - center_s),
                abs(float(x[3]) - 0.5 * (left_ref_s + right_ref_s)),
                -float(x[0].length),
            ),
        )
        center_piece_hit = True
    else:
        selected_piece = min(
            piece_info,
            key=lambda x: (
                min(abs(center_s - float(x[1])), abs(center_s - float(x[2])), abs(center_s - float(x[3]))),
                abs(float(x[3]) - center_s),
                -float(x[0].length),
            ),
        )
        center_piece_hit = False

    base_s0 = float(selected_piece[1])
    base_s1 = float(selected_piece[2])
    pad = max(0.0, float(edge_pad_m))
    span_start = max(base_s0, float(left_ref_s) - pad)
    span_end = min(base_s1, float(right_ref_s) + pad)
    span_start = max(base_s0, min(span_start, center_s))
    span_end = min(base_s1, max(span_end, center_s))
    if span_end - span_start <= 1e-6:
        span_start = base_s0
        span_end = base_s1

    edge_touch_tol_m = 0.1
    if drivezone_union is not None and (not drivezone_union.is_empty):
        p0_probe = crossline.interpolate(span_start)
        p1_probe = crossline.interpolate(span_end)
        left_probe_dist = float(p0_probe.distance(drivezone_union.boundary))
        right_probe_dist = float(p1_probe.distance(drivezone_union.boundary))
        if left_probe_dist > edge_touch_tol_m + 1e-9 and span_start > base_s0 + 1e-9:
            span_start = base_s0
        if right_probe_dist > edge_touch_tol_m + 1e-9 and span_end < base_s1 - 1e-9:
            span_end = base_s1

    if (not math.isfinite(span_start)) or (not math.isfinite(span_end)) or (span_end - span_start) <= 1e-6:
        out_diag["reason"] = "span_degenerate"
        return None, out_diag

    p0 = crossline.interpolate(span_start)
    p1 = crossline.interpolate(span_end)
    out_diag["ok"] = True
    out_diag["reason"] = "ok"
    out_diag["center_piece_hit"] = bool(center_piece_hit)
    return LineString([(float(p0.x), float(p0.y)), (float(p1.x), float(p1.y))]), out_diag


def _extract_multibranch_events(
    *,
    node_point: Point,
    scan_vec: tuple[float, float],
    branch_a: RoadRecord,
    branch_b: RoadRecord,
    branches: list[tuple[int, RoadRecord]],
    stop_dist_m: float,
    scan_step_m: float,
    reverse_max_m: float,
    span_extra_m: float,
    drivezone_union: BaseGeometry | None,
    min_piece_len_m: float,
    edge_pad_m: float,
    expected_events: int,
) -> dict[str, Any]:
    perp = (-float(scan_vec[1]), float(scan_vec[0]))
    step = max(0.05, float(scan_step_m))
    stop_dist = max(0.0, float(stop_dist_m))
    reverse_max = max(0.0, float(reverse_max_m))
    expected = max(0, int(expected_events))

    def _build_s_samples(start: float, end: float, step_signed: float) -> list[float]:
        out: list[float] = []
        cur = float(start)
        if step_signed > 0:
            while cur <= float(end) + 1e-9:
                out.append(float(cur))
                cur += float(step_signed)
        else:
            while cur >= float(end) - 1e-9:
                out.append(float(cur))
                cur += float(step_signed)
        if not out:
            out = [float(start)]
        return out

    s_forward = _build_s_samples(0.0, float(stop_dist), float(step))
    s_reverse = _build_s_samples(0.0, -float(reverse_max), -float(step))

    rec_forward: dict[float, dict[str, Any]] = {}
    rec_reverse: dict[float, dict[str, Any]] = {}

    def _scan_one(s_values: list[float], rec_map: dict[float, dict[str, Any]]) -> list[int]:
        counts: list[int] = []
        for s in s_values:
            center_xy = (
                float(node_point.x) + float(scan_vec[0]) * float(s),
                float(node_point.y) + float(scan_vec[1]) * float(s),
            )
            try:
                v_min, v_max, _samples = crossline_span_points_all_branches(
                    branches=branches,
                    center_xy=center_xy,
                    perp_vec=perp,
                )
                crossline = build_crossline_span(
                    center_xy=center_xy,
                    perp_vec=perp,
                    v_min_m=float(v_min),
                    v_max_m=float(v_max),
                    extra_m=float(span_extra_m),
                )
                pieces_count = compute_pieces_count(
                    crossline=crossline,
                    drivezone_union=drivezone_union,
                    min_piece_len_m=float(min_piece_len_m),
                )
            except Exception:
                crossline = LineString([center_xy, center_xy])
                pieces_count = 0
            counts.append(int(max(0, pieces_count)))
            rec_map[round(float(s), 6)] = {
                "s_m": float(s),
                "crossline": crossline,
                "pieces_count": int(max(0, pieces_count)),
                "center_xy": (float(center_xy[0]), float(center_xy[1])),
            }
        return counts

    counts_fwd = _scan_one(s_forward, rec_forward)
    counts_rev = _scan_one(s_reverse, rec_reverse)

    events_fwd, events_fwd_diag = extract_split_events(
        s_values=[float(x) for x in s_forward],
        pieces_count_seq=[int(x) for x in counts_fwd],
        expected_events=int(expected),
    )
    events_rev, events_rev_diag = extract_split_events(
        s_values=[float(x) for x in s_reverse],
        pieces_count_seq=[int(x) for x in counts_rev],
        expected_events=int(expected),
    )

    fwd_pick = [float(x) for x in events_fwd if float(x) > 1e-9] or [float(x) for x in events_fwd]
    rev_pick = [float(x) for x in events_rev if float(x) < -1e-9] or [float(x) for x in events_rev]
    abnormal_two_sided = bool(fwd_pick and rev_pick)

    s_main: float | None = None
    main_pick_source = "none"
    if fwd_pick and rev_pick:
        s_main = float(min(rev_pick))
        main_pick_source = "reverse_farthest_abnormal"
    elif fwd_pick:
        s_main = float(min(fwd_pick))
        main_pick_source = "forward_first"
    elif rev_pick:
        s_main = float(min(rev_pick))
        main_pick_source = "reverse_farthest_fallback"

    event_lines: list[dict[str, Any]] = []
    event_idx = 0
    for evt_dir, events, rec_map in [
        ("forward", events_fwd, rec_forward),
        ("reverse", events_rev, rec_reverse),
    ]:
        for evt_s in events:
            rec = rec_map.get(round(float(evt_s), 6))
            if not isinstance(rec, dict):
                event_idx += 1
                continue
            crossline = rec.get("crossline")
            if not isinstance(crossline, LineString):
                event_idx += 1
                continue
            center_xy = rec.get("center_xy")
            if not (isinstance(center_xy, tuple) and len(center_xy) == 2):
                event_idx += 1
                continue
            found_seg, _found_diag = build_between_branches_segment(
                center_xy=(float(center_xy[0]), float(center_xy[1])),
                scan_dir=scan_vec,
                branch_a=branch_a,
                branch_b=branch_b,
                crossline_half_len_m=max(30.0, 0.5 * float(crossline.length)),
            )
            pieces_raw = segment_drivezone_pieces(
                segment=crossline,
                drivezone_union=drivezone_union,
                min_piece_len_m=float(min_piece_len_m),
            )
            event_line, event_diag = _build_continuous_line_from_crossline(
                crossline=crossline,
                pieces_raw=pieces_raw,
                center_xy=(float(center_xy[0]), float(center_xy[1])),
                found_seg=found_seg,
                drivezone_union=drivezone_union,
                edge_pad_m=float(edge_pad_m),
            )
            if event_line is not None and bool(event_diag.get("ok", False)):
                event_lines.append(
                    {
                        "event_idx": int(event_idx),
                        "event_s_m": float(evt_s),
                        "event_dir": str(evt_dir),
                        "pieces_count_at_event": int(rec.get("pieces_count", 0)),
                        "line": event_line,
                    }
                )
            event_idx += 1

    return {
        "split_events_forward": [float(x) for x in events_fwd],
        "split_events_reverse": [float(x) for x in events_rev],
        "split_events_forward_diag": list(events_fwd_diag),
        "split_events_reverse_diag": list(events_rev_diag),
        "s_main_m": None if s_main is None else float(s_main),
        "main_pick_source": str(main_pick_source),
        "abnormal_two_sided": bool(abnormal_two_sided),
        "s_drivezone_split_first_m": None if not fwd_pick else float(min(fwd_pick)),
        "event_lines": event_lines,
    }


def _attach_k16_diag(
    item: dict[str, Any],
    *,
    k16_enabled: bool,
    k16_road_id: str | None = None,
    k16_road_dir: int | None = None,
    k16_endpoint_role: str | None = None,
    k16_search_dir: str | None = None,
    k16_search_max_m: float | None = None,
    k16_step_m: float | None = None,
    k16_cross_half_len_m: float | None = None,
    k16_output_cross_half_len_m: float | None = None,
    k16_s_found_m: float | None = None,
    k16_s_best_m: float | None = None,
    k16_found: bool | None = None,
    k16_min_dist_cross_to_drivezone_m: float | None = None,
    k16_break_reason: str | None = None,
    k16_refine_enable: bool | None = None,
    k16_refine_ahead_m: float | None = None,
    k16_refine_step_m: float | None = None,
    k16_first_hit_s_m: float | None = None,
    k16_refined_used: bool | None = None,
    k16_s_refined_m: float | None = None,
    k16_first_hit_len_m: float | None = None,
    k16_refined_len_m: float | None = None,
    k16_refine_candidate_count: int | None = None,
) -> dict[str, Any]:
    out = dict(item)
    out.update(
        {
            "k16_enabled": bool(k16_enabled),
            "k16_road_id": None if k16_road_id is None else str(k16_road_id),
            "k16_road_dir": None if k16_road_dir is None else int(k16_road_dir),
            "k16_endpoint_role": None if k16_endpoint_role is None else str(k16_endpoint_role),
            "k16_search_dir": None if k16_search_dir is None else str(k16_search_dir),
            "k16_search_max_m": None if k16_search_max_m is None else float(k16_search_max_m),
            "k16_step_m": None if k16_step_m is None else float(k16_step_m),
            "k16_cross_half_len_m": None if k16_cross_half_len_m is None else float(k16_cross_half_len_m),
            "k16_output_cross_half_len_m": (
                None if k16_output_cross_half_len_m is None else float(k16_output_cross_half_len_m)
            ),
            "k16_s_found_m": None if k16_s_found_m is None else float(k16_s_found_m),
            "k16_s_best_m": None if k16_s_best_m is None else float(k16_s_best_m),
            "k16_found": None if k16_found is None else bool(k16_found),
            "k16_min_dist_cross_to_drivezone_m": (
                None if k16_min_dist_cross_to_drivezone_m is None else float(k16_min_dist_cross_to_drivezone_m)
            ),
            "k16_break_reason": None if k16_break_reason is None else str(k16_break_reason),
            "k16_refine_enable": None if k16_refine_enable is None else bool(k16_refine_enable),
            "k16_refine_ahead_m": None if k16_refine_ahead_m is None else float(k16_refine_ahead_m),
            "k16_refine_step_m": None if k16_refine_step_m is None else float(k16_refine_step_m),
            "k16_first_hit_s_m": None if k16_first_hit_s_m is None else float(k16_first_hit_s_m),
            "k16_refined_used": None if k16_refined_used is None else bool(k16_refined_used),
            "k16_s_refined_m": None if k16_s_refined_m is None else float(k16_s_refined_m),
            "k16_first_hit_len_m": None if k16_first_hit_len_m is None else float(k16_first_hit_len_m),
            "k16_refined_len_m": None if k16_refined_len_m is None else float(k16_refined_len_m),
            "k16_refine_candidate_count": None if k16_refine_candidate_count is None else int(k16_refine_candidate_count),
        }
    )
    return out


def _evaluate_node_k16(
    *,
    node: NodeRecord,
    road_graph: RoadGraph,
    drivezone_union: BaseGeometry | None,
    drivezone_usable: bool,
    params: dict[str, Any],
    breakpoints: list[dict[str, Any]],
    resolved_from: dict[str, Any] | None = None,
    is_in_continuous_chain: bool = False,
    chain_component_id: str | None = None,
    chain_node_offset_m: float | None = None,
    required_prev_abs_s: float | None = None,
) -> dict[str, Any]:
    nodeid = int(node.nodeid)
    kind = None if node.kind is None else int(node.kind)
    chain_offset = None if chain_node_offset_m is None else float(chain_node_offset_m)
    required_prev_abs = None if required_prev_abs_s is None else float(required_prev_abs_s)
    k16_search_max_m = 10.0
    k16_cross_half_len_m = 10.0
    k16_output_cross_half_len_m = max(
        float(k16_cross_half_len_m),
        float(params.get("output_cross_half_len_m", 120.0)),
    )
    k16_step_m = max(0.05, float(params.get("k16_step_m", 0.5)))
    k16_refine_enable = bool(params.get("k16_refine_enable", True))
    k16_refine_ahead_m = max(0.0, float(params.get("k16_refine_ahead_m", 5.0)))
    k16_refine_step_m = max(0.05, float(params.get("k16_refine_step_m", k16_step_m)))
    edge_pad_m = float(params.get("current_road_edge_pad_m", 4.0))
    dummy_line = build_k16_crossline(
        center=(float(node.point.x), float(node.point.y)),
        perp=(1.0, 0.0),
        half_len=float(k16_cross_half_len_m),
    )

    if (not drivezone_usable) or drivezone_union is None or drivezone_union.is_empty:
        breakpoints.append(
            make_breakpoint(
                code=BP_DRIVEZONE_MISSING,
                severity="hard",
                nodeid=nodeid,
                message="k16_drivezone_missing",
            )
        )
        return _attach_k16_diag(
            _empty_fail_result(
                nodeid=nodeid,
                kind=kind,
                anchor_type="k16",
                scan_dir="na",
                line=dummy_line,
                divstrip_union=None,
                drivezone_union=drivezone_union,
                stop_reason="k16_drivezone_missing",
                id_fields=node.id_fields,
                resolved_from=resolved_from,
                is_in_continuous_chain=bool(is_in_continuous_chain),
                chain_component_id=chain_component_id,
                chain_node_offset_m=chain_offset,
                abs_s_prev_required_m=required_prev_abs,
            ),
            k16_enabled=True,
            k16_search_max_m=k16_search_max_m,
            k16_step_m=k16_step_m,
            k16_cross_half_len_m=k16_cross_half_len_m,
            k16_output_cross_half_len_m=k16_output_cross_half_len_m,
            k16_found=False,
            k16_break_reason="drivezone_missing",
            k16_refine_enable=k16_refine_enable,
            k16_refine_ahead_m=k16_refine_ahead_m,
            k16_refine_step_m=k16_refine_step_m,
        )

    sel, sel_diag = find_unique_k16_road(nodeid=nodeid, roads=road_graph.roads)
    if sel is None:
        bp_code = BP_K16_ROAD_NOT_UNIQUE
        if str(sel_diag.get("code")) == "K16_ROAD_DIR_UNSUPPORTED":
            bp_code = BP_K16_ROAD_DIR_UNSUPPORTED
        breakpoints.append(
            make_breakpoint(
                code=bp_code,
                severity="hard",
                nodeid=nodeid,
                message=str(sel_diag.get("reason", "k16_road_selection_failed")),
                extra={k: v for k, v in sel_diag.items() if k != "ok"},
            )
        )
        return _attach_k16_diag(
            _empty_fail_result(
                nodeid=nodeid,
                kind=kind,
                anchor_type="k16",
                scan_dir="na",
                line=dummy_line,
                divstrip_union=None,
                drivezone_union=drivezone_union,
                stop_reason=str(sel_diag.get("reason", "k16_road_selection_failed")),
                id_fields=node.id_fields,
                resolved_from=resolved_from,
                is_in_continuous_chain=bool(is_in_continuous_chain),
                chain_component_id=chain_component_id,
                chain_node_offset_m=chain_offset,
                abs_s_prev_required_m=required_prev_abs,
            ),
            k16_enabled=True,
            k16_search_max_m=k16_search_max_m,
            k16_step_m=k16_step_m,
            k16_cross_half_len_m=k16_cross_half_len_m,
            k16_output_cross_half_len_m=k16_output_cross_half_len_m,
            k16_found=False,
            k16_break_reason=str(sel_diag.get("reason", "k16_road_selection_failed")),
            k16_refine_enable=k16_refine_enable,
            k16_refine_ahead_m=k16_refine_ahead_m,
            k16_refine_step_m=k16_refine_step_m,
        )

    k16_road_id = f"{int(sel.road.snodeid)}->{int(sel.road.enodeid)}#{int(sel.road_index)}"
    try:
        tangent = compute_k16_tangent_at_node(
            road_geom=sel.road.line,
            node_pt=node.point,
            endpoint_role=sel.tangent_endpoint_role,
        )
    except Exception as exc:  # noqa: BLE001
        breakpoints.append(
            make_breakpoint(
                code=BP_K16_ROAD_NOT_UNIQUE,
                severity="hard",
                nodeid=nodeid,
                message=f"k16_tangent_invalid:{type(exc).__name__}",
            )
        )
        return _attach_k16_diag(
            _empty_fail_result(
                nodeid=nodeid,
                kind=kind,
                anchor_type="k16",
                scan_dir=str(sel.search_dir),
                line=dummy_line,
                divstrip_union=None,
                drivezone_union=drivezone_union,
                stop_reason="k16_tangent_invalid",
                id_fields=node.id_fields,
                resolved_from=resolved_from,
                is_in_continuous_chain=bool(is_in_continuous_chain),
                chain_component_id=chain_component_id,
                chain_node_offset_m=chain_offset,
                abs_s_prev_required_m=required_prev_abs,
            ),
            k16_enabled=True,
            k16_road_id=k16_road_id,
            k16_road_dir=int(sel.road_dir),
            k16_endpoint_role=str(sel.endpoint_role),
            k16_search_dir=str(sel.search_dir),
            k16_search_max_m=k16_search_max_m,
            k16_step_m=k16_step_m,
            k16_cross_half_len_m=k16_cross_half_len_m,
            k16_output_cross_half_len_m=k16_output_cross_half_len_m,
            k16_found=False,
            k16_break_reason="tangent_invalid",
            k16_refine_enable=k16_refine_enable,
            k16_refine_ahead_m=k16_refine_ahead_m,
            k16_refine_step_m=k16_refine_step_m,
        )

    perp = (-float(tangent[1]), float(tangent[0]))
    search_diag = search_crossline_hit_drivezone(
        node_pt=node.point,
        t=tangent,
        perp=perp,
        drivezone_union=drivezone_union,
        dir_sign=float(sel.dir_sign),
        max_m=float(k16_search_max_m),
        step=float(k16_step_m),
        cross_half_len_m=float(k16_cross_half_len_m),
    )
    line_probe = search_diag.get("crossline_best")
    if not isinstance(line_probe, LineString):
        line_probe = dummy_line

    if not bool(search_diag.get("hit", False)):
        breakpoints.append(
            make_breakpoint(
                code=BP_K16_DRIVEZONE_NOT_REACHED,
                severity="hard",
                nodeid=nodeid,
                message="k16_drivezone_not_reached_within_10m",
                extra={
                    "k16_min_dist_cross_to_drivezone_m": search_diag.get("min_dist_cross_to_drivezone_m"),
                    "k16_s_best_m": search_diag.get("s_best_m"),
                },
            )
        )
        return _attach_k16_diag(
            _empty_fail_result(
                nodeid=nodeid,
                kind=kind,
                anchor_type="k16",
                scan_dir=str(sel.search_dir),
                line=line_probe,
                divstrip_union=None,
                drivezone_union=drivezone_union,
                stop_reason="k16_drivezone_not_reached",
                id_fields=node.id_fields,
                resolved_from=resolved_from,
                is_in_continuous_chain=bool(is_in_continuous_chain),
                chain_component_id=chain_component_id,
                chain_node_offset_m=chain_offset,
                abs_s_prev_required_m=required_prev_abs,
            ),
            k16_enabled=True,
            k16_road_id=k16_road_id,
            k16_road_dir=int(sel.road_dir),
            k16_endpoint_role=str(sel.endpoint_role),
            k16_search_dir=str(sel.search_dir),
            k16_search_max_m=k16_search_max_m,
            k16_step_m=k16_step_m,
            k16_cross_half_len_m=k16_cross_half_len_m,
            k16_output_cross_half_len_m=k16_output_cross_half_len_m,
            k16_s_best_m=search_diag.get("s_best_m"),
            k16_found=False,
            k16_min_dist_cross_to_drivezone_m=search_diag.get("min_dist_cross_to_drivezone_m"),
            k16_break_reason="drivezone_not_reached",
            k16_refine_enable=k16_refine_enable,
            k16_refine_ahead_m=k16_refine_ahead_m,
            k16_refine_step_m=k16_refine_step_m,
        )

    crossline_hit = search_diag.get("crossline_found")
    center_found = search_diag.get("center_found_xy")
    if not isinstance(crossline_hit, LineString) or not (isinstance(center_found, tuple) and len(center_found) == 2):
        breakpoints.append(
            make_breakpoint(
                code=BP_K16_DRIVEZONE_NOT_REACHED,
                severity="hard",
                nodeid=nodeid,
                message="k16_hit_geometry_invalid",
            )
        )
        return _attach_k16_diag(
            _empty_fail_result(
                nodeid=nodeid,
                kind=kind,
                anchor_type="k16",
                scan_dir=str(sel.search_dir),
                line=line_probe,
                divstrip_union=None,
                drivezone_union=drivezone_union,
                stop_reason="k16_hit_geometry_invalid",
                id_fields=node.id_fields,
                resolved_from=resolved_from,
                is_in_continuous_chain=bool(is_in_continuous_chain),
                chain_component_id=chain_component_id,
                chain_node_offset_m=chain_offset,
                abs_s_prev_required_m=required_prev_abs,
            ),
            k16_enabled=True,
            k16_road_id=k16_road_id,
            k16_road_dir=int(sel.road_dir),
            k16_endpoint_role=str(sel.endpoint_role),
            k16_search_dir=str(sel.search_dir),
            k16_search_max_m=k16_search_max_m,
            k16_step_m=k16_step_m,
            k16_cross_half_len_m=k16_cross_half_len_m,
            k16_output_cross_half_len_m=k16_output_cross_half_len_m,
            k16_s_found_m=search_diag.get("s_found_m"),
            k16_s_best_m=search_diag.get("s_best_m"),
            k16_found=False,
            k16_min_dist_cross_to_drivezone_m=search_diag.get("min_dist_cross_to_drivezone_m"),
            k16_break_reason="hit_geometry_invalid",
            k16_refine_enable=k16_refine_enable,
            k16_refine_ahead_m=k16_refine_ahead_m,
            k16_refine_step_m=k16_refine_step_m,
        )

    def _build_k16_candidate(s_signed: float) -> dict[str, Any] | None:
        center_xy = (
            float(node.point.x + float(tangent[0]) * float(s_signed)),
            float(node.point.y + float(tangent[1]) * float(s_signed)),
        )
        crossline = build_k16_crossline(
            center=center_xy,
            perp=perp,
            half_len=float(k16_output_cross_half_len_m),
        )
        inter = crossline.intersection(drivezone_union)
        if inter.is_empty:
            return None
        pieces_raw_local = segment_drivezone_pieces(
            segment=crossline,
            drivezone_union=drivezone_union,
            min_piece_len_m=0.0,
        )
        final_line_local, line_diag_local = _build_continuous_line_from_crossline(
            crossline=crossline,
            pieces_raw=pieces_raw_local,
            center_xy=center_xy,
            found_seg=crossline,
            drivezone_union=drivezone_union,
            edge_pad_m=edge_pad_m,
        )
        if not isinstance(final_line_local, LineString):
            return None
        clip_piece_type_local = (
            "continuous_center_piece"
            if bool(line_diag_local.get("center_piece_hit", False))
            else "continuous_nearest_piece_fallback"
        )
        return {
            "s_signed": float(s_signed),
            "center_xy": center_xy,
            "crossline": crossline,
            "pieces_raw": pieces_raw_local,
            "final_line": final_line_local,
            "line_diag": line_diag_local,
            "clip_piece_type": clip_piece_type_local,
        }

    signed_first_hit = None if search_diag.get("s_found_m") is None else float(search_diag.get("s_found_m"))
    first_candidate = None if signed_first_hit is None else _build_k16_candidate(float(signed_first_hit))
    if first_candidate is None:
        breakpoints.append(
            make_breakpoint(
                code=BP_K16_DRIVEZONE_NOT_REACHED,
                severity="hard",
                nodeid=nodeid,
                message="k16_piece_select_failed:first_hit_invalid",
            )
        )
        return _attach_k16_diag(
            _empty_fail_result(
                nodeid=nodeid,
                kind=kind,
                anchor_type="k16",
                scan_dir=str(sel.search_dir),
                line=crossline_hit,
                divstrip_union=None,
                drivezone_union=drivezone_union,
                stop_reason="k16_piece_select_failed",
                id_fields=node.id_fields,
                resolved_from=resolved_from,
                is_in_continuous_chain=bool(is_in_continuous_chain),
                chain_component_id=chain_component_id,
                chain_node_offset_m=chain_offset,
                abs_s_prev_required_m=required_prev_abs,
            ),
            k16_enabled=True,
            k16_road_id=k16_road_id,
            k16_road_dir=int(sel.road_dir),
            k16_endpoint_role=str(sel.endpoint_role),
            k16_search_dir=str(sel.search_dir),
            k16_search_max_m=k16_search_max_m,
            k16_step_m=k16_step_m,
            k16_cross_half_len_m=k16_cross_half_len_m,
            k16_output_cross_half_len_m=k16_output_cross_half_len_m,
            k16_s_found_m=search_diag.get("s_found_m"),
            k16_s_best_m=search_diag.get("s_best_m"),
            k16_found=False,
            k16_min_dist_cross_to_drivezone_m=search_diag.get("min_dist_cross_to_drivezone_m"),
            k16_break_reason="piece_select_failed:first_hit_invalid",
            k16_refine_enable=k16_refine_enable,
            k16_refine_ahead_m=k16_refine_ahead_m,
            k16_refine_step_m=k16_refine_step_m,
        )

    candidates: list[dict[str, Any]] = [first_candidate]
    if k16_refine_enable and k16_refine_ahead_m > 1e-9 and signed_first_hit is not None:
        dir_sign = 1.0 if float(sel.dir_sign) >= 0.0 else -1.0
        start_s = float(signed_first_hit)
        end_s = float(signed_first_hit + dir_sign * float(k16_refine_ahead_m))
        step_signed = float(dir_sign * float(k16_refine_step_m))
        cur = float(start_s + step_signed)
        scan_vals: list[float] = []
        if step_signed > 0.0:
            while cur <= end_s + 1e-9:
                scan_vals.append(float(cur))
                cur += step_signed
        else:
            while cur >= end_s - 1e-9:
                scan_vals.append(float(cur))
                cur += step_signed
        if (not scan_vals) or abs(float(scan_vals[-1]) - float(end_s)) > 1e-9:
            scan_vals.append(float(end_s))

        for s_val in scan_vals:
            cand = _build_k16_candidate(float(s_val))
            if cand is None:
                continue
            candidates.append(cand)

    best_candidate = min(
        candidates,
        key=lambda c: (
            -float(c["final_line"].length),
            int(len(c["pieces_raw"])),
            abs(float(c["s_signed"]) - float(signed_first_hit)),
            abs(float(c["s_signed"])),
        ),
    )
    refined_used = bool(abs(float(best_candidate["s_signed"]) - float(signed_first_hit)) > 1e-9)
    final_line = best_candidate["final_line"]
    line_diag = best_candidate["line_diag"]
    pieces_raw = list(best_candidate["pieces_raw"])
    signed_found = float(best_candidate["s_signed"])
    clip_piece_type = str(best_candidate["clip_piece_type"])
    first_hit_len = float(first_candidate["final_line"].length)
    refined_len = float(final_line.length)
    refine_candidate_count = int(len(candidates))

    id_map = {str(k): int(v) for k, v in node.id_fields}
    boundary = drivezone_union.boundary if drivezone_union is not None else None
    if boundary is not None:
        p0 = Point(float(final_line.coords[0][0]), float(final_line.coords[0][1]))
        p1 = Point(float(final_line.coords[-1][0]), float(final_line.coords[-1][1]))
        left_end_to_dz_edge = float(p0.distance(boundary))
        right_end_to_dz_edge = float(p1.distance(boundary))
        dist_line_to_dz_edge = float(final_line.distance(boundary))
    else:
        left_end_to_dz_edge = None
        right_end_to_dz_edge = None
        dist_line_to_dz_edge = None

    scan_dist_abs = float(abs(float(signed_found)))
    anchor_pt = final_line.interpolate(0.5, normalized=True)
    conf = compute_confidence(trigger="drivezone_split", scan_dist_m=0.0 if scan_dist_abs is None else scan_dist_abs)
    piece_lens = [float(ln.length) for ln in pieces_raw]

    result = {
        "nodeid": int(nodeid),
        "id": id_map.get("id"),
        "mainid": id_map.get("mainid"),
        "mainnodeid": id_map.get("mainnodeid"),
        "kind": None if kind is None else int(kind),
        "is_merge_kind": False,
        "is_diverge_kind": False,
        "anchor_type": "k16",
        "status": "ok",
        "found_split": True,
        "anchor_found": True,
        "trigger": "k16_drivezone_intersection",
        "scan_dir": str(sel.search_dir),
        "scan_dist_m": None if scan_dist_abs is None else float(scan_dist_abs),
        "stop_dist_m": float(k16_search_max_m),
        "stop_reason": "k16_drivezone_hit",
        "next_intersection_dist_m": None,
        "dist_to_divstrip_m": None,
        "dist_line_to_divstrip_m": None,
        "dist_line_to_drivezone_edge_m": dist_line_to_dz_edge,
        "confidence": float(conf),
        "flags": ["k16"],
        "evidence_source": "drivezone_intersection",
        "anchor_point": anchor_pt,
        "crossline_opt": final_line,
        "crossline_opt_pieces": [],
        "tip_s_m": None,
        "first_divstrip_hit_dist_m": None,
        "best_divstrip_dz_dist_m": None,
        "best_divstrip_pc_dist_m": None,
        "first_pc_only_dist_m": None,
        "fan_area_m2": 0.0,
        "non_drivezone_area_m2": 0.0,
        "non_drivezone_frac": 0.0,
        "clipped_len_m": float(final_line.length),
        "clip_empty": False,
        "clip_piece_type": clip_piece_type,
        "pieces_count": int(len(pieces_raw)),
        "piece_lens_m": piece_lens,
        "selected_piece_count": 1,
        "selected_piece_lens_m": [float(final_line.length)],
        "gap_len_m": None,
        "seg_len_m": float(final_line.length),
        "s_divstrip_m": None,
        "s_drivezone_split_m": float(signed_found),
        "s_chosen_m": float(signed_found),
        "split_pick_source": "k16_first_intersection_refined" if refined_used else "k16_first_intersection",
        "divstrip_ref_source": "none",
        "divstrip_ref_offset_m": None,
        "output_cross_half_len_m": float(k16_output_cross_half_len_m),
        "branch_a_id": None,
        "branch_b_id": None,
        "branch_axis_id": None,
        "branch_a_crossline_hit": None,
        "branch_b_crossline_hit": None,
        "pa_center_dist_m": None,
        "pb_center_dist_m": None,
        "left_edge_dist_m": None,
        "right_edge_dist_m": None,
        "left_end_to_drivezone_edge_m": left_end_to_dz_edge,
        "right_end_to_drivezone_edge_m": right_end_to_dz_edge,
        "left_extended_to_piece_edge": False,
        "right_extended_to_piece_edge": False,
        "has_divstrip_nearby": False,
        "reverse_tip_attempted": False,
        "reverse_tip_used": False,
        "reverse_tip_not_improved": False,
        "reverse_search_max_m": None,
        "reverse_trigger": None,
        "ref_s_forward_m": None,
        "position_source_forward": None,
        "ref_s_reverse_m": None,
        "position_source_reverse": None,
        "ref_s_final_m": float(signed_found),
        "position_source_final": "k16_ref_s",
        "untrusted_divstrip_at_node": False,
        "node_to_divstrip_m_at_s0": None,
        "seg0_intersects_divstrip": None,
        "ng_candidates_before_suppress": 0,
        "ng_candidates_after_suppress": 0,
        "is_in_continuous_chain": bool(is_in_continuous_chain),
        "chain_component_id": chain_component_id,
        "chain_node_offset_m": None if chain_offset is None else float(chain_offset),
        "abs_s_chosen_m": None,
        "abs_s_prev_required_m": None if required_prev_abs is None else float(required_prev_abs),
        "sequential_ok": True,
        "sequential_violation_reason": None,
        "merged": False,
        "merged_group_id": None,
        "merged_with_nodeids": None,
        "abs_s_merged_m": None,
        "merged_crossline_id": None,
        "merged_output_nodeids": None,
        "merged_output_kinds": None,
        "merged_output_roles": None,
        "merged_output_anchor_types": None,
        "merge_reason": None,
        "merge_geom_dist_m": None,
        "merge_abs_diff_m": None,
        "merge_abs_gap_cfg_m": None,
        "merge_abs_gate_skipped": None,
        "suppress_intersection_feature": False,
        "multibranch_enabled": False,
        "multibranch_N": 0,
        "multibranch_expected_events": 0,
        "split_events_forward": [],
        "split_events_reverse": [],
        "s_main_m": None,
        "main_pick_source": "none",
        "abnormal_two_sided": False,
        "span_extra_m": None,
        "direction_filter_applied": False,
        "branches_used_count": 0,
        "branches_ignored_due_to_direction": 0,
        "s_drivezone_split_first_m": None,
        "multibranch_event_lines": [],
        "resolved_from": resolved_from,
    }
    return _attach_k16_diag(
        result,
        k16_enabled=True,
        k16_road_id=k16_road_id,
        k16_road_dir=int(sel.road_dir),
        k16_endpoint_role=str(sel.endpoint_role),
        k16_search_dir=str(sel.search_dir),
        k16_search_max_m=k16_search_max_m,
        k16_step_m=k16_step_m,
        k16_cross_half_len_m=k16_cross_half_len_m,
        k16_output_cross_half_len_m=k16_output_cross_half_len_m,
        k16_s_found_m=float(signed_found),
        k16_s_best_m=search_diag.get("s_best_m"),
        k16_found=True,
        k16_min_dist_cross_to_drivezone_m=search_diag.get("min_dist_cross_to_drivezone_m"),
        k16_break_reason="ok_refined" if refined_used else "ok",
        k16_refine_enable=k16_refine_enable,
        k16_refine_ahead_m=k16_refine_ahead_m,
        k16_refine_step_m=k16_refine_step_m,
        k16_first_hit_s_m=signed_first_hit,
        k16_refined_used=refined_used,
        k16_s_refined_m=float(signed_found),
        k16_first_hit_len_m=first_hit_len,
        k16_refined_len_m=refined_len,
        k16_refine_candidate_count=refine_candidate_count,
    )


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
    is_in_continuous_chain: bool = False,
    chain_component_id: str | None = None,
    chain_node_offset_m: float | None = None,
    required_prev_abs_s: float | None = None,
) -> dict[str, Any]:
    nodeid = int(node.nodeid)
    kind = None if node.kind is None else int(node.kind)
    is_merge = bool(kind is not None and (int(kind) & (1 << 3)) != 0)
    is_diverge = bool(kind is not None and (int(kind) & (1 << 4)) != 0)
    is_k16 = bool(kind is not None and (int(kind) & (1 << 16)) != 0)
    chain_offset = None if chain_node_offset_m is None else float(chain_node_offset_m)
    required_prev_abs = None if required_prev_abs_s is None else float(required_prev_abs_s)
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
            is_in_continuous_chain=bool(is_in_continuous_chain),
            chain_component_id=chain_component_id,
            chain_node_offset_m=chain_offset,
            abs_s_prev_required_m=required_prev_abs,
        )

    if is_k16 and (is_merge or is_diverge):
        _add_bp(
            code=BP_AMBIGUOUS_KIND,
            severity="hard",
            message="k16_with_merge_or_diverge_bits_not_supported",
            extra={"kind": int(kind)},
        )
        return _attach_k16_diag(
            _empty_fail_result(
                nodeid=nodeid,
                kind=kind,
                anchor_type="k16",
                scan_dir="na",
                line=dummy_line,
                divstrip_union=divstrip_union,
                drivezone_union=drivezone_union,
                stop_reason="k16_with_merge_or_diverge_bits_not_supported",
                id_fields=node.id_fields,
                resolved_from=resolved_from,
                is_in_continuous_chain=bool(is_in_continuous_chain),
                chain_component_id=chain_component_id,
                chain_node_offset_m=chain_offset,
                abs_s_prev_required_m=required_prev_abs,
            ),
            k16_enabled=True,
            k16_search_max_m=10.0,
            k16_step_m=float(max(0.05, float(params.get("k16_step_m", 0.5)))),
            k16_cross_half_len_m=10.0,
            k16_output_cross_half_len_m=max(10.0, float(params.get("output_cross_half_len_m", 120.0))),
            k16_found=False,
            k16_break_reason="k16_with_merge_or_diverge_bits_not_supported",
        )

    if is_k16:
        return _evaluate_node_k16(
            node=node,
            road_graph=road_graph,
            drivezone_union=drivezone_union,
            drivezone_usable=drivezone_usable,
            params=params,
            breakpoints=breakpoints,
            resolved_from=resolved_from,
            is_in_continuous_chain=is_in_continuous_chain,
            chain_component_id=chain_component_id,
            chain_node_offset_m=chain_node_offset_m,
            required_prev_abs_s=required_prev_abs_s,
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
            is_in_continuous_chain=bool(is_in_continuous_chain),
            chain_component_id=chain_component_id,
            chain_node_offset_m=chain_offset,
            abs_s_prev_required_m=required_prev_abs,
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
            is_in_continuous_chain=bool(is_in_continuous_chain),
            chain_component_id=chain_component_id,
            chain_node_offset_m=chain_offset,
            abs_s_prev_required_m=required_prev_abs,
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
            is_in_continuous_chain=bool(is_in_continuous_chain),
            chain_component_id=chain_component_id,
            chain_node_offset_m=chain_offset,
            abs_s_prev_required_m=required_prev_abs,
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
    valid_branches, branch_filter_diag = collect_valid_branches_by_direction(
        nodeid=nodeid,
        roads=road_graph.roads,
        anchor_type=anchor_type,
    )
    branches_used_count = int(branch_filter_diag.get("valid_count", len(valid_branches)))
    branches_ignored_due_to_direction = int(branch_filter_diag.get("ignored_due_to_direction", 0))
    multibranch_n = int(branches_used_count)
    multibranch_expected_events = int(max(0, multibranch_n - 1))
    multibranch_enabled = bool(params.get("multibranch_enable", True)) and multibranch_n > 2
    multibranch_span_extra_m = max(0.0, float(params.get("multibranch_span_extra_m", 10.0)))
    multibranch_reverse_max_m = max(0.0, float(params.get("multibranch_reverse_max_m", 10.0)))
    split_events_forward: list[float] = []
    split_events_reverse: list[float] = []
    split_events_forward_diag: list[dict[str, Any]] = []
    split_events_reverse_diag: list[dict[str, Any]] = []
    s_main_m: float | None = None
    main_pick_source = "none"
    abnormal_two_sided = False
    s_drivezone_split_first_m: float | None = None
    multibranch_event_lines: list[dict[str, Any]] = []
    multibranch_diag_payload: dict[str, Any] = {
        "multibranch_enabled": bool(multibranch_enabled),
        "multibranch_N": int(multibranch_n),
        "multibranch_expected_events": int(multibranch_expected_events),
        "split_events_forward": list(split_events_forward),
        "split_events_reverse": list(split_events_reverse),
        "s_main_m": None,
        "main_pick_source": str(main_pick_source),
        "abnormal_two_sided": bool(abnormal_two_sided),
        "span_extra_m": float(multibranch_span_extra_m),
        "direction_filter_applied": True,
        "branches_used_count": int(branches_used_count),
        "branches_ignored_due_to_direction": int(branches_ignored_due_to_direction),
        "s_drivezone_split_first_m": None,
    }

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
            is_in_continuous_chain=bool(is_in_continuous_chain),
            chain_component_id=chain_component_id,
            chain_node_offset_m=chain_offset,
            abs_s_prev_required_m=required_prev_abs,
        )
        out.update(
            {
                "branch_a_id": branch_a_id,
                "branch_b_id": branch_b_id,
                "branch_axis_id": axis_id,
                **multibranch_diag_payload,
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
    divstrip_preferred_window_m = max(0.0, float(params.get("divstrip_preferred_window_m", 8.0)))
    divstrip_ref_hard_window_m = max(0.0, float(params.get("divstrip_ref_hard_window_m", 1.0)))
    divstrip_drivezone_max_offset_m = max(0.0, float(params.get("divstrip_drivezone_max_offset_m", 30.0)))
    reverse_tip_max_m = max(0.0, float(params.get("reverse_tip_max_m", 10.0)))
    output_cross_half_len_m = max(float(half_len), float(params.get("output_cross_half_len_m", 120.0)))
    event_edge_pad_m = max(0.0, float(params.get("current_road_edge_pad_m", 4.0)))

    if multibranch_enabled:
        mb = _extract_multibranch_events(
            node_point=node.point,
            scan_vec=scan_vec,
            branch_a=branch_a,
            branch_b=branch_b,
            branches=valid_branches,
            stop_dist_m=float(stop_dist),
            scan_step_m=float(step),
            reverse_max_m=float(multibranch_reverse_max_m),
            span_extra_m=float(multibranch_span_extra_m),
            drivezone_union=drivezone_union,
            min_piece_len_m=float(min_piece_len_m),
            edge_pad_m=float(event_edge_pad_m),
            expected_events=int(multibranch_expected_events),
        )
        split_events_forward = [float(x) for x in mb.get("split_events_forward", [])]
        split_events_reverse = [float(x) for x in mb.get("split_events_reverse", [])]
        split_events_forward_diag = list(mb.get("split_events_forward_diag", []))
        split_events_reverse_diag = list(mb.get("split_events_reverse_diag", []))
        s_main_m = None if mb.get("s_main_m") is None else float(mb.get("s_main_m"))
        main_pick_source = str(mb.get("main_pick_source", "none"))
        abnormal_two_sided = bool(mb.get("abnormal_two_sided", False))
        s_drivezone_split_first_m = None if mb.get("s_drivezone_split_first_m") is None else float(mb.get("s_drivezone_split_first_m"))
        raw_event_lines = mb.get("event_lines")
        if isinstance(raw_event_lines, list):
            multibranch_event_lines = [x for x in raw_event_lines if isinstance(x, dict)]
        multibranch_diag_payload.update(
            {
                "split_events_forward": list(split_events_forward),
                "split_events_reverse": list(split_events_reverse),
                "s_main_m": None if s_main_m is None else float(s_main_m),
                "main_pick_source": str(main_pick_source),
                "abnormal_two_sided": bool(abnormal_two_sided),
                "s_drivezone_split_first_m": None if s_drivezone_split_first_m is None else float(s_drivezone_split_first_m),
                "split_events_forward_diag": split_events_forward_diag,
                "split_events_reverse_diag": split_events_reverse_diag,
            }
        )

    tip_s: float | None = None
    tip_s_reverse: float | None = None
    tip_pt = None
    if divstrip_union is not None and (not divstrip_union.is_empty):
        tip_pt = tip_point_from_divstrip(
            divstrip_union=divstrip_union,
            scan_vec=scan_vec,
            origin_xy=(float(node.point.x), float(node.point.y)),
        )
        if tip_pt is not None and (not tip_pt.is_empty):
            tip_proj = (
                (float(tip_pt.x) - float(node.point.x)) * float(scan_vec[0])
                + (float(tip_pt.y) - float(node.point.y)) * float(scan_vec[1])
            )
            if math.isfinite(tip_proj):
                tip_s = float(tip_proj)
        tip_pt_rev = tip_point_from_divstrip(
            divstrip_union=divstrip_union,
            scan_vec=(-float(scan_vec[0]), -float(scan_vec[1])),
            origin_xy=(float(node.point.x), float(node.point.y)),
        )
        if tip_pt_rev is not None and (not tip_pt_rev.is_empty):
            tip_proj_rev = (
                (float(tip_pt_rev.x) - float(node.point.x)) * float(scan_vec[0])
                + (float(tip_pt_rev.y) - float(node.point.y)) * float(scan_vec[1])
            )
            if math.isfinite(tip_proj_rev):
                tip_s_reverse = float(tip_proj_rev)

    split_hits: list[dict[str, Any]] = []
    first_divstrip_hit_s: float | None = None
    best_divstrip_dist_m: float | None = None
    seg0_intersects_divstrip: bool | None = None
    node_to_divstrip_m_at_s0: float | None = None
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

        dist_div = None
        if divstrip_union is not None:
            dist_div = float(seg.distance(divstrip_union))
            if best_divstrip_dist_m is None or dist_div < best_divstrip_dist_m:
                best_divstrip_dist_m = float(dist_div)
            if first_divstrip_hit_s is None and dist_div <= float(div_tol):
                first_divstrip_hit_s = float(s)
            if i == 0:
                seg0_intersects_divstrip = bool(seg.intersects(divstrip_union) or float(dist_div) <= 1e-9)
                node_to_divstrip_m_at_s0 = float(node.point.distance(divstrip_union))

        pieces = segment_drivezone_pieces(
            segment=seg,
            drivezone_union=drivezone_union,
            min_piece_len_m=min_piece_len_m,
        )
        if len(pieces) >= 2:
            split_hits.append(
                {
                    "s": float(s),
                    "seg": seg,
                    "diag": seg_diag,
                    "pieces": pieces,
                    "dist_div": dist_div,
                }
            )

    id_map = {str(k): int(v) for k, v in node.id_fields}
    first_split = split_hits[0] if split_hits else None
    s_drivezone_split = None if first_split is None else float(first_split["s"])
    if multibranch_enabled:
        s_drivezone_split = None if s_main_m is None else float(s_main_m)
        if s_drivezone_split_first_m is None and first_split is not None:
            s_drivezone_split_first_m = float(first_split["s"])

    divstrip_ref_s: float | None = None
    divstrip_ref_source = "none"
    if first_divstrip_hit_s is not None:
        divstrip_ref_s = float(first_divstrip_hit_s)
        divstrip_ref_source = "first_hit"
    elif tip_s is not None and float(tip_s) >= -1e-6 and float(tip_s) <= float(stop_dist) + 1e-6:
        divstrip_ref_s = float(max(0.0, min(float(stop_dist), float(tip_s))))
        divstrip_ref_source = "tip_projection"
    if multibranch_enabled:
        divstrip_ref_s = None
        divstrip_ref_source = "none"

    ref_s_forward, position_source_forward, split_pick_source_forward = _pick_reference_s(
        divstrip_ref_s=divstrip_ref_s,
        divstrip_ref_source=divstrip_ref_source,
        drivezone_split_s=s_drivezone_split,
        max_offset_m=divstrip_drivezone_max_offset_m,
    )
    if multibranch_enabled and ref_s_forward is not None:
        if str(main_pick_source) == "forward_first":
            position_source_forward = "drivezone_split_fwd_first"
            split_pick_source_forward = "drivezone_split_multibranch_fwd_first"
        elif str(main_pick_source) in {"reverse_farthest_abnormal", "reverse_farthest_fallback"}:
            position_source_forward = "drivezone_split_rev_far"
            split_pick_source_forward = "drivezone_split_multibranch_rev_far"
        else:
            position_source_forward = "drivezone_split"
            split_pick_source_forward = "drivezone_split_multibranch"

    untrusted_divstrip_at_node = bool(
        seg0_intersects_divstrip is True
        and node_to_divstrip_m_at_s0 is not None
        and float(node_to_divstrip_m_at_s0) <= float(div_tol) + 1e-9
    )
    reverse_tip_attempted = False
    reverse_tip_used = False
    reverse_tip_not_improved = False
    reverse_trigger: str | None = None
    ref_s_reverse: float | None = None
    position_source_reverse: str | None = None
    split_pick_source_reverse = "none"
    divstrip_ref_s_rev: float | None = None
    divstrip_ref_source_rev = "none"
    s_drivezone_split_rev: float | None = None
    first_divstrip_hit_s_rev: float | None = None
    best_divstrip_dist_m_rev: float | None = None

    forward_missing_ref = bool(divstrip_ref_s is None and s_drivezone_split is None)
    first_hit_no_split = bool(
        divstrip_ref_s is not None
        and str(divstrip_ref_source) == "first_hit"
        and s_drivezone_split is None
    )
    if (not multibranch_enabled) and (forward_missing_ref or untrusted_divstrip_at_node or first_hit_no_split):
        reverse_tip_attempted = True
        if forward_missing_ref:
            reverse_trigger = "missing_ref"
        elif untrusted_divstrip_at_node:
            reverse_trigger = "untrusted_divstrip_at_node"
        else:
            reverse_trigger = "first_hit_no_split"
        _add_bp(
            code=BP_REVERSE_TIP_ATTEMPTED,
            severity="soft",
            message=f"reverse_tip_attempted:{reverse_trigger}",
            extra={"reverse_tip_max_m": float(reverse_tip_max_m)},
        )
        if untrusted_divstrip_at_node:
            _add_bp(
                code=BP_UNTRUSTED_DIVSTRIP_AT_NODE,
                severity="soft",
                message="untrusted_divstrip_at_node",
                extra={
                    "node_to_divstrip_m_at_s0": None if node_to_divstrip_m_at_s0 is None else float(node_to_divstrip_m_at_s0),
                    "divstrip_hit_tol_m": float(div_tol),
                },
            )

        reverse_start_m = float(step) if untrusted_divstrip_at_node else 0.0
        n_rev = max(1, int(math.floor(reverse_tip_max_m / step)) + 1)
        for i_rev in range(n_rev + 1):
            rev_abs = reverse_start_m + float(i_rev) * float(step)
            if rev_abs > float(reverse_tip_max_m) + 1e-9:
                break
            s_rev = -float(rev_abs)
            center_xy_rev = (
                float(node.point.x) + float(scan_vec[0]) * float(s_rev),
                float(node.point.y) + float(scan_vec[1]) * float(s_rev),
            )
            seg_rev, _seg_diag_rev = build_between_branches_segment(
                center_xy=center_xy_rev,
                scan_dir=scan_vec,
                branch_a=branch_a,
                branch_b=branch_b,
                crossline_half_len_m=half_len,
            )
            if divstrip_union is not None:
                dist_div_rev = float(seg_rev.distance(divstrip_union))
                if best_divstrip_dist_m_rev is None or dist_div_rev < best_divstrip_dist_m_rev:
                    best_divstrip_dist_m_rev = float(dist_div_rev)
                if first_divstrip_hit_s_rev is None and dist_div_rev <= float(div_tol):
                    first_divstrip_hit_s_rev = float(s_rev)
            pieces_rev = segment_drivezone_pieces(
                segment=seg_rev,
                drivezone_union=drivezone_union,
                min_piece_len_m=min_piece_len_m,
            )
            if s_drivezone_split_rev is None and len(pieces_rev) >= 2:
                s_drivezone_split_rev = float(s_rev)

        if first_divstrip_hit_s_rev is not None:
            divstrip_ref_s_rev = float(first_divstrip_hit_s_rev)
            divstrip_ref_source_rev = "first_hit"
        elif tip_s_reverse is not None and float(tip_s_reverse) >= -float(reverse_tip_max_m) - 1e-6 and float(tip_s_reverse) <= 1e-6:
            tip_s_rev = float(max(-float(reverse_tip_max_m), min(0.0, float(tip_s_reverse))))
            if (not untrusted_divstrip_at_node) or tip_s_rev < -1e-6:
                divstrip_ref_s_rev = float(tip_s_rev)
                divstrip_ref_source_rev = "tip_projection"

        ref_s_reverse, position_source_reverse, split_pick_source_reverse = _pick_reference_s(
            divstrip_ref_s=divstrip_ref_s_rev,
            divstrip_ref_source=divstrip_ref_source_rev,
            drivezone_split_s=s_drivezone_split_rev,
            max_offset_m=divstrip_drivezone_max_offset_m,
        )
        if ref_s_reverse is not None:
            reverse_tip_used = True
            _add_bp(
                code=BP_REVERSE_TIP_USED,
                severity="soft",
                message=f"reverse_tip_used:{position_source_reverse}",
                extra={"ref_s_reverse_m": float(ref_s_reverse)},
            )
        else:
            _add_bp(
                code=BP_REVERSE_TIP_NOT_FOUND,
                severity="soft",
                message="reverse_tip_not_found_in_window",
                extra={"reverse_tip_max_m": float(reverse_tip_max_m)},
            )
            if (not forward_missing_ref) and ref_s_forward is not None:
                reverse_tip_not_improved = True

    ref_s = ref_s_forward
    position_source = position_source_forward
    split_pick_source = split_pick_source_forward
    if reverse_tip_used and ref_s_reverse is not None:
        ref_s = float(ref_s_reverse)
        position_source = str(position_source_reverse or "none")
        split_pick_source = f"reverse_{split_pick_source_reverse}"

    ref_s_final = ref_s
    position_source_final = position_source
    s_divstrip_out = divstrip_ref_s_rev if reverse_tip_used else divstrip_ref_s
    s_drivezone_split_out = s_drivezone_split_rev if reverse_tip_used else s_drivezone_split
    divstrip_ref_source_out = divstrip_ref_source_rev if reverse_tip_used else divstrip_ref_source
    reverse_diag_payload = {
        "reverse_tip_attempted": bool(reverse_tip_attempted),
        "reverse_tip_used": bool(reverse_tip_used),
        "reverse_tip_not_improved": bool(reverse_tip_not_improved),
        "reverse_search_max_m": float(reverse_tip_max_m),
        "reverse_trigger": reverse_trigger,
        "ref_s_forward_m": None if ref_s_forward is None else float(ref_s_forward),
        "position_source_forward": None if position_source_forward == "none" else str(position_source_forward),
        "ref_s_reverse_m": None if ref_s_reverse is None else float(ref_s_reverse),
        "position_source_reverse": position_source_reverse,
        "ref_s_final_m": None if ref_s_final is None else float(ref_s_final),
        "position_source_final": None if position_source_final == "none" else str(position_source_final),
        "untrusted_divstrip_at_node": bool(untrusted_divstrip_at_node),
        "node_to_divstrip_m_at_s0": None if node_to_divstrip_m_at_s0 is None else float(node_to_divstrip_m_at_s0),
        "seg0_intersects_divstrip": seg0_intersects_divstrip,
    }

    if ref_s is None:
        _add_bp(
            code=BP_DRIVEZONE_SPLIT_NOT_FOUND,
            severity="hard",
            message="no_divstrip_or_drivezone_reference_for_anchor",
            extra={"stop_dist_m": float(stop_dist)},
        )
        _add_bp(
            code=BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION,
            severity="soft",
            message="scan_end_without_divstrip_or_drivezone_reference",
            extra={"stop_dist_m": float(stop_dist)},
        )
        if stop_dist >= min(200.0, scan_max):
            _add_bp(
                code=BP_SCAN_EXCEED_200M,
                severity="soft",
                message="scan_reached_200m_or_max",
                extra={"stop_dist_m": float(stop_dist)},
            )
        out = _empty_fail_result(
            nodeid=nodeid,
            kind=kind,
            anchor_type=anchor_type,
            scan_dir=scan_dir_label,
            line=last_seg,
            divstrip_union=divstrip_union,
            drivezone_union=drivezone_union,
            stop_reason="position_reference_missing",
            id_fields=node.id_fields,
            resolved_from=resolved_from,
            is_in_continuous_chain=bool(is_in_continuous_chain),
            chain_component_id=chain_component_id,
            chain_node_offset_m=chain_offset,
            abs_s_prev_required_m=required_prev_abs,
        )
        out.update(
            {
                "stop_dist_m": float(stop_dist),
                "next_intersection_dist_m": None if next_inter is None else float(next_inter),
                "tip_s_m": None if tip_s is None else float(tip_s),
                "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
                "best_divstrip_dz_dist_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
                "clip_empty": True,
                "clip_piece_type": "none",
                "stop_diag": stop_diag,
                "seg_len_m": float(last_diag.get("seg_len_m", last_seg.length)),
                "s_divstrip_m": None if s_divstrip_out is None else float(s_divstrip_out),
                "s_drivezone_split_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
                "s_chosen_m": None,
                "split_pick_source": "none",
                "divstrip_ref_source": str(divstrip_ref_source_out),
                "divstrip_ref_offset_m": None,
                "output_cross_half_len_m": float(output_cross_half_len_m),
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
                **multibranch_diag_payload,
                **reverse_diag_payload,
            }
        )
        return out

    window_m = float(divstrip_ref_hard_window_m)
    if bool(reverse_tip_used):
        # Reverse-tip anomaly branch: probe farther from node to avoid divstrip overlap.
        window_lo, window_hi, target_s = _build_ref_window_away_from_node(
            ref_s=float(ref_s),
            window_m=window_m,
        )
    else:
        # Regular branch: keep anchor near node and in front of divstrip.
        window_lo, window_hi, target_s = _build_ref_window_toward_node(
            ref_s=float(ref_s),
            window_m=window_m,
        )
        # Regular branch must not cross node (keep s sign consistent with ref_s side).
        if float(ref_s) >= 0.0:
            window_lo = float(max(0.0, float(window_lo)))
            window_hi = float(max(0.0, float(window_hi)))
            target_s = float(max(0.0, float(target_s)))
        else:
            window_lo = float(min(0.0, float(window_lo)))
            window_hi = float(min(0.0, float(window_hi)))
            target_s = float(min(0.0, float(target_s)))
        if window_hi + 1e-9 < window_lo:
            window_lo = float(ref_s)
            window_hi = float(ref_s)
            target_s = float(ref_s)

    probe_step = min(0.25, max(0.05, float(step)))
    scan_candidates: list[float] = []
    cur = float(window_lo)
    while cur <= float(window_hi) + 1e-9:
        scan_candidates.append(float(max(window_lo, min(window_hi, cur))))
        cur += probe_step
    if not scan_candidates:
        scan_candidates = [float(max(window_lo, min(window_hi, float(ref_s))))]
    target_in_window = float(max(window_lo, min(window_hi, float(target_s))))
    if all(abs(float(x) - target_in_window) > 1e-6 for x in scan_candidates):
        scan_candidates.append(target_in_window)
    dedup_candidates: list[float] = []
    seen_key: set[float] = set()
    for s_val in scan_candidates:
        key = round(float(s_val), 6)
        if key in seen_key:
            continue
        seen_key.add(key)
        dedup_candidates.append(float(s_val))
    scan_candidates = dedup_candidates

    tip_projection_guard_min_abs_m = max(
        float(window_m),
        max(0.0, float(params.get("continuous_tip_projection_min_abs_m", 1.0))),
    )
    guard_near_zero_tip_projection = bool(
        (not reverse_tip_used)
        and (required_prev_abs is not None)
        and (s_drivezone_split_out is None)
        and str(position_source) == "divstrip_ref"
        and str(divstrip_ref_source_out) == "tip_projection"
        and abs(float(ref_s)) <= float(tip_projection_guard_min_abs_m) + 1e-9
    )
    if guard_near_zero_tip_projection:
        sign = -1.0 if float(ref_s) < 0.0 else 1.0
        cur_far = sign * float(tip_projection_guard_min_abs_m)
        while abs(float(cur_far)) <= float(stop_dist) + 1e-9:
            scan_candidates.append(float(cur_far))
            cur_far += sign * float(probe_step)
        if float(stop_dist) >= float(tip_projection_guard_min_abs_m) - 1e-9:
            scan_candidates.append(sign * float(stop_dist))
        dedup_candidates = []
        seen_key = set()
        for s_val in scan_candidates:
            key = round(float(s_val), 6)
            if key in seen_key:
                continue
            seen_key.add(key)
            dedup_candidates.append(float(s_val))
        scan_candidates = dedup_candidates
        split_pick_source = f"{split_pick_source}_seq_tip_projection_guard"

    prefer_non_intersect_reverse = bool(
        reverse_tip_used
        and (s_drivezone_split_out is None)
        and (divstrip_union is not None)
        and (not divstrip_union.is_empty)
    )
    if prefer_non_intersect_reverse:
        sign = -1.0 if float(ref_s) < 0.0 else 1.0
        far_bound = -float(reverse_tip_max_m) if sign < 0.0 else float(reverse_tip_max_m)
        cur_far = float(target_in_window) + sign * float(probe_step)
        while (cur_far >= far_bound - 1e-9) if sign < 0.0 else (cur_far <= far_bound + 1e-9):
            if abs(float(cur_far)) <= float(reverse_tip_max_m) + 1e-9:
                scan_candidates.append(float(cur_far))
            cur_far += sign * float(probe_step)
        if abs(float(far_bound)) <= float(reverse_tip_max_m) + 1e-9:
            scan_candidates.append(float(far_bound))
        dedup_candidates = []
        seen_key = set()
        for s_val in scan_candidates:
            key = round(float(s_val), 6)
            if key in seen_key:
                continue
            seen_key.add(key)
            dedup_candidates.append(float(s_val))
        scan_candidates = dedup_candidates

    chosen_scan_dist: float | None = None
    output_crossline: LineString | None = None
    output_pieces_raw: list[LineString] = []
    has_extra_piece = False
    candidate_hits: list[dict[str, Any]] = []
    seq_pre_candidates = 0
    seq_filtered_out = 0
    guard_reject_no_split_count = 0
    guard_reject_divstrip_intersect_count = 0
    for rank, s_probe in enumerate(scan_candidates):
        if guard_near_zero_tip_projection and abs(float(s_probe)) < float(tip_projection_guard_min_abs_m) - 1e-9:
            continue
        crossline_probe = LocalFrame.from_tangent(
            origin_xy=(float(node.point.x), float(node.point.y)),
            tangent_xy=scan_vec,
        ).crossline(
            scan_dist_m=float(s_probe),
            cross_half_len_m=float(output_cross_half_len_m),
        )
        pieces_probe = segment_drivezone_pieces(
            segment=crossline_probe,
            drivezone_union=drivezone_union,
            min_piece_len_m=min_piece_len_m,
        )
        if not pieces_probe:
            continue
        seq_pre_candidates += 1
        if required_prev_abs is not None and chain_offset is not None:
            abs_s_candidate = _compute_abs_s(
                is_diverge=bool(is_diverge),
                is_merge=bool(is_merge),
                node_offset_m=float(chain_offset),
                s_local=float(s_probe),
            )
            if abs_s_candidate is None or float(abs_s_candidate) <= float(required_prev_abs) + 1e-9:
                seq_filtered_out += 1
                continue
        center_probe = Point(
            float(node.point.x) + float(scan_vec[0]) * float(s_probe),
            float(node.point.y) + float(scan_vec[1]) * float(s_probe),
        )
        center_s_probe = float(crossline_probe.project(center_probe))
        has_center_piece = False
        piece_info_probe: list[tuple[LineString, float, float, float]] = []
        for piece in pieces_probe:
            vals: list[float] = []
            for coord in list(piece.coords):
                if len(coord) < 2:
                    continue
                vals.append(float(crossline_probe.project(Point(float(coord[0]), float(coord[1])))))
            if not vals:
                continue
            s0 = float(min(vals))
            s1 = float(max(vals))
            sm = 0.5 * (s0 + s1)
            piece_info_probe.append((piece, s0, s1, sm))
            if s0 - 1e-6 <= center_s_probe <= s1 + 1e-6:
                has_center_piece = True
        selected_piece_div_dist_m: float | None = None
        if piece_info_probe and divstrip_union is not None and (not divstrip_union.is_empty):
            center_hits_probe = [x for x in piece_info_probe if float(x[1]) - 1e-6 <= center_s_probe <= float(x[2]) + 1e-6]
            if center_hits_probe:
                selected_piece_probe = min(
                    center_hits_probe,
                    key=lambda x: (
                        abs(float(x[3]) - center_s_probe),
                        -float(x[0].length),
                    ),
                )
            else:
                selected_piece_probe = min(
                    piece_info_probe,
                    key=lambda x: (
                        min(abs(center_s_probe - float(x[1])), abs(center_s_probe - float(x[2])), abs(center_s_probe - float(x[3]))),
                        abs(float(x[3]) - center_s_probe),
                        -float(x[0].length),
                    ),
                )
            selected_piece_div_dist_m = float(selected_piece_probe[0].distance(divstrip_union))
        raw_count = int(len(pieces_probe))
        if guard_near_zero_tip_projection:
            split_ok = bool(raw_count >= 2)
            div_clear = bool(
                selected_piece_div_dist_m is not None
                and float(selected_piece_div_dist_m) > float(div_tol) + 1e-9
            )
            if not split_ok:
                guard_reject_no_split_count += 1
            if not div_clear:
                guard_reject_divstrip_intersect_count += 1
            if not (split_ok and div_clear):
                continue
        candidate_hits.append(
            {
                "rank": int(rank),
                "s": float(s_probe),
                "crossline": crossline_probe,
                "pieces_raw": list(pieces_probe),
                "has_center_piece": bool(has_center_piece),
                "has_extra": bool(len(pieces_probe) > 1),
                "raw_count": int(raw_count),
                "selected_piece_div_dist_m": None if selected_piece_div_dist_m is None else float(selected_piece_div_dist_m),
            }
        )

    if guard_near_zero_tip_projection and (not candidate_hits):
        output_crossline = LocalFrame.from_tangent(
            origin_xy=(float(node.point.x), float(node.point.y)),
            tangent_xy=scan_vec,
        ).crossline(
            scan_dist_m=0.0,
            cross_half_len_m=float(output_cross_half_len_m),
        )
        _add_bp(
            code=BP_DRIVEZONE_SPLIT_NOT_FOUND,
            severity="hard",
            message="continuous_tip_projection_guard_no_candidate",
            extra={
                "guard_min_abs_m": float(tip_projection_guard_min_abs_m),
                "rejected_no_split_count": int(guard_reject_no_split_count),
                "rejected_divstrip_intersect_count": int(guard_reject_divstrip_intersect_count),
                "stop_dist_m": float(stop_dist),
            },
        )
        out = _empty_fail_result(
            nodeid=nodeid,
            kind=kind,
            anchor_type=anchor_type,
            scan_dir=scan_dir_label,
            line=output_crossline,
            divstrip_union=divstrip_union,
            drivezone_union=drivezone_union,
            stop_reason="continuous_tip_projection_guard_no_candidate",
            id_fields=node.id_fields,
            resolved_from=resolved_from,
            is_in_continuous_chain=bool(is_in_continuous_chain),
            chain_component_id=chain_component_id,
            chain_node_offset_m=chain_offset,
            abs_s_prev_required_m=required_prev_abs,
        )
        out.update(
            {
                "stop_dist_m": float(stop_dist),
                "next_intersection_dist_m": None if next_inter is None else float(next_inter),
                "tip_s_m": None if tip_s is None else float(tip_s),
                "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
                "best_divstrip_dz_dist_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
                "clip_empty": True,
                "clip_piece_type": "none",
                "clip_input_len_m": float(output_crossline.length),
                "stop_diag": stop_diag,
                "s_divstrip_m": None if s_divstrip_out is None else float(s_divstrip_out),
                "s_drivezone_split_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
                "s_chosen_m": 0.0,
                "split_pick_source": f"{split_pick_source}_guard_no_candidate",
                "divstrip_ref_source": str(divstrip_ref_source_out),
                "divstrip_ref_offset_m": None,
                "output_cross_half_len_m": float(output_cross_half_len_m),
                "branch_a_id": branch_a_id,
                "branch_b_id": branch_b_id,
                "branch_axis_id": axis_id,
                "has_divstrip_nearby": False,
                "ng_candidates_before_suppress": int(ng_points_xy.shape[0]),
                "ng_candidates_after_suppress": int(ng_points_xy.shape[0]),
                **multibranch_diag_payload,
                **reverse_diag_payload,
            }
        )
        return out

    if candidate_hits:
        if prefer_non_intersect_reverse:
            best_hit = min(
                candidate_hits,
                key=lambda x: (
                    0
                    if (
                        x.get("selected_piece_div_dist_m") is not None
                        and float(x.get("selected_piece_div_dist_m", 0.0)) > float(div_tol) + 1e-9
                    )
                    else 1,
                    0 if bool(x.get("has_center_piece", False)) else 1,
                    0 if int(x.get("raw_count", 0)) == 1 else 1,
                    int(x.get("raw_count", 0)),
                    abs(float(x.get("s", 0.0)) - float(target_s)),
                    int(x.get("rank", 0)),
                ),
            )
        else:
            best_hit = min(
                candidate_hits,
                key=lambda x: (
                    0 if bool(x.get("has_center_piece", False)) else 1,
                    0 if int(x.get("raw_count", 0)) == 1 else 1,
                    int(x.get("raw_count", 0)),
                    abs(float(x.get("s", 0.0)) - float(target_s)),
                    int(x.get("rank", 0)),
                ),
            )
        chosen_scan_dist = float(best_hit["s"])
        output_crossline = best_hit["crossline"]
        output_pieces_raw = list(best_hit["pieces_raw"])
        has_extra_piece = bool(best_hit["has_extra"])
        if guard_near_zero_tip_projection and s_drivezone_split_out is None and int(best_hit.get("raw_count", 0)) >= 2:
            s_drivezone_split_out = float(chosen_scan_dist)

    if output_crossline is None:
        output_crossline = LocalFrame.from_tangent(
            origin_xy=(float(node.point.x), float(node.point.y)),
            tangent_xy=scan_vec,
        ).crossline(
            scan_dist_m=float(target_in_window),
            cross_half_len_m=float(output_cross_half_len_m),
        )

    if (
        required_prev_abs is not None
        and chain_offset is not None
        and seq_pre_candidates > 0
        and seq_filtered_out > 0
        and not candidate_hits
    ):
        _add_bp(
            code=BP_SEQUENTIAL_ORDER_VIOLATION,
            severity="hard",
            message="sequential_order_violation_no_candidate_gt_prev",
            extra={"required_prev_abs_s": float(required_prev_abs), "filtered_out": int(seq_filtered_out)},
        )
        out = _empty_fail_result(
            nodeid=nodeid,
            kind=kind,
            anchor_type=anchor_type,
            scan_dir=scan_dir_label,
            line=output_crossline,
            divstrip_union=divstrip_union,
            drivezone_union=drivezone_union,
            stop_reason="sequential_order_violation",
            id_fields=node.id_fields,
            resolved_from=resolved_from,
            is_in_continuous_chain=bool(is_in_continuous_chain),
            chain_component_id=chain_component_id,
            chain_node_offset_m=chain_offset,
            abs_s_prev_required_m=required_prev_abs,
            sequential_violation_reason="no_candidate_abs_gt_prev",
        )
        out.update(
            {
                "stop_dist_m": float(stop_dist),
                "next_intersection_dist_m": None if next_inter is None else float(next_inter),
                "tip_s_m": None if tip_s is None else float(tip_s),
                "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
                "best_divstrip_dz_dist_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
                "clip_empty": True,
                "clip_piece_type": "none",
                "clip_input_len_m": float(output_crossline.length),
                "stop_diag": stop_diag,
                "s_divstrip_m": None if s_divstrip_out is None else float(s_divstrip_out),
                "s_drivezone_split_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
                "s_chosen_m": None,
                "split_pick_source": f"{split_pick_source}_seq_violation",
                "divstrip_ref_source": str(divstrip_ref_source_out),
                "divstrip_ref_offset_m": None,
                "output_cross_half_len_m": float(output_cross_half_len_m),
                "branch_a_id": branch_a_id,
                "branch_b_id": branch_b_id,
                "branch_axis_id": axis_id,
                "has_divstrip_nearby": False,
                "ng_candidates_before_suppress": int(ng_points_xy.shape[0]),
                "ng_candidates_after_suppress": int(ng_points_xy.shape[0]),
                **multibranch_diag_payload,
                **reverse_diag_payload,
            }
        )
        return out

    if (not output_pieces_raw) or chosen_scan_dist is None:
        _add_bp(
            code=BP_DRIVEZONE_CLIP_EMPTY,
            severity="hard",
            message="drivezone_piece_not_found_within_ref_window",
            extra={"window_lo_m": float(window_lo), "window_hi_m": float(window_hi)},
        )
        out = _empty_fail_result(
            nodeid=nodeid,
            kind=kind,
            anchor_type=anchor_type,
            scan_dir=scan_dir_label,
            line=output_crossline,
            divstrip_union=divstrip_union,
            drivezone_union=drivezone_union,
            stop_reason="drivezone_piece_not_found_in_window",
            id_fields=node.id_fields,
            resolved_from=resolved_from,
            is_in_continuous_chain=bool(is_in_continuous_chain),
            chain_component_id=chain_component_id,
            chain_node_offset_m=chain_offset,
            abs_s_prev_required_m=required_prev_abs,
        )
        out.update(
            {
                "stop_dist_m": float(stop_dist),
                "next_intersection_dist_m": None if next_inter is None else float(next_inter),
                "tip_s_m": None if tip_s is None else float(tip_s),
                "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
                "best_divstrip_dz_dist_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
                "clip_empty": True,
                "clip_piece_type": "none",
                "clip_input_len_m": float(output_crossline.length),
                "stop_diag": stop_diag,
                "s_divstrip_m": None if s_divstrip_out is None else float(s_divstrip_out),
                "s_drivezone_split_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
                "s_chosen_m": None,
                "split_pick_source": f"{split_pick_source}_no_piece",
                "divstrip_ref_source": str(divstrip_ref_source_out),
                "divstrip_ref_offset_m": None,
                "output_cross_half_len_m": float(output_cross_half_len_m),
                "branch_a_id": branch_a_id,
                "branch_b_id": branch_b_id,
                "branch_axis_id": axis_id,
                "has_divstrip_nearby": False,
                "ng_candidates_before_suppress": int(ng_points_xy.shape[0]),
                "ng_candidates_after_suppress": int(ng_points_xy.shape[0]),
                **multibranch_diag_payload,
                **reverse_diag_payload,
            }
        )
        return out

    scan_dist = float(chosen_scan_dist)
    divstrip_ref_offset = None if s_divstrip_out is None else float(abs(float(scan_dist) - float(s_divstrip_out)))
    center_xy = (
        float(node.point.x) + float(scan_vec[0]) * float(scan_dist),
        float(node.point.y) + float(scan_vec[1]) * float(scan_dist),
    )
    found_seg, found_diag = build_between_branches_segment(
        center_xy=center_xy,
        scan_dir=scan_vec,
        branch_a=branch_a,
        branch_b=branch_b,
        crossline_half_len_m=half_len,
    )

    if has_extra_piece:
        _add_bp(
            code=BP_DRIVEZONE_CLIP_MULTIPIECE,
            severity="soft",
            message="drivezone_clip_multipiece_branch_filtered",
            extra={"piece_count": int(len(output_pieces_raw))},
        )

    # Build continuous span on current roadbed: center-containing piece first, then branch-bounded clamp.
    pa_pt = Point(float(found_seg.coords[0][0]), float(found_seg.coords[0][1]))
    pb_pt = Point(float(found_seg.coords[-1][0]), float(found_seg.coords[-1][1]))
    center_pt = Point(float(center_xy[0]), float(center_xy[1]))
    center_s = float(output_crossline.project(center_pt))

    piece_info: list[tuple[LineString, float, float, float]] = []
    for piece in output_pieces_raw:
        vals: list[float] = []
        for coord in list(piece.coords):
            if len(coord) < 2:
                continue
            vals.append(float(output_crossline.project(Point(float(coord[0]), float(coord[1])))))
        if not vals:
            continue
        s0 = float(min(vals))
        s1 = float(max(vals))
        sm = 0.5 * (s0 + s1)
        piece_info.append((piece, s0, s1, sm))

    if not piece_info:
        _add_bp(
            code=BP_DRIVEZONE_CLIP_EMPTY,
            severity="hard",
            message="drivezone_piece_interval_empty",
        )
        out = _empty_fail_result(
            nodeid=nodeid,
            kind=kind,
            anchor_type=anchor_type,
            scan_dir=scan_dir_label,
            line=output_crossline,
            divstrip_union=divstrip_union,
            drivezone_union=drivezone_union,
            stop_reason="drivezone_piece_interval_empty",
            id_fields=node.id_fields,
            resolved_from=resolved_from,
            is_in_continuous_chain=bool(is_in_continuous_chain),
            chain_component_id=chain_component_id,
            chain_node_offset_m=chain_offset,
            abs_s_prev_required_m=required_prev_abs,
        )
        out.update(
            {
                "stop_dist_m": float(stop_dist),
                "next_intersection_dist_m": None if next_inter is None else float(next_inter),
                "tip_s_m": None if tip_s is None else float(tip_s),
                "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
                "best_divstrip_dz_dist_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
                "clip_empty": True,
                "clip_piece_type": "none",
                "clip_input_len_m": float(output_crossline.length),
                "stop_diag": stop_diag,
                "s_divstrip_m": None if s_divstrip_out is None else float(s_divstrip_out),
                "s_drivezone_split_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
                "s_chosen_m": float(scan_dist),
                "split_pick_source": f"{split_pick_source}_interval_empty",
                "divstrip_ref_source": str(divstrip_ref_source_out),
                "divstrip_ref_offset_m": divstrip_ref_offset,
                "output_cross_half_len_m": float(output_cross_half_len_m),
                "branch_a_id": branch_a_id,
                "branch_b_id": branch_b_id,
                "branch_axis_id": axis_id,
                "has_divstrip_nearby": False,
                "ng_candidates_before_suppress": int(ng_points_xy.shape[0]),
                "ng_candidates_after_suppress": int(ng_points_xy.shape[0]),
                **multibranch_diag_payload,
                **reverse_diag_payload,
            }
        )
        return out

    pa_s = float(output_crossline.project(pa_pt))
    pb_s = float(output_crossline.project(pb_pt))
    left_ref_s, right_ref_s = (pa_s, pb_s) if pa_s <= pb_s else (pb_s, pa_s)

    center_hits = [x for x in piece_info if float(x[1]) - 1e-6 <= center_s <= float(x[2]) + 1e-6]
    if center_hits:
        selected_piece = min(
            center_hits,
            key=lambda x: (
                abs(float(x[3]) - center_s),
                abs(float(x[3]) - 0.5 * (left_ref_s + right_ref_s)),
                -float(x[0].length),
            ),
        )
        center_piece_hit = True
    else:
        selected_piece = min(
            piece_info,
            key=lambda x: (
                min(abs(center_s - float(x[1])), abs(center_s - float(x[2])), abs(center_s - float(x[3]))),
                abs(float(x[3]) - center_s),
                -float(x[0].length),
            ),
        )
        center_piece_hit = False

    base_s0 = float(selected_piece[1])
    base_s1 = float(selected_piece[2])
    edge_pad_m = max(0.0, float(params.get("current_road_edge_pad_m", 4.0)))
    span_start = max(base_s0, float(left_ref_s) - edge_pad_m)
    span_end = min(base_s1, float(right_ref_s) + edge_pad_m)
    span_start = max(base_s0, min(span_start, center_s))
    span_end = min(base_s1, max(span_end, center_s))
    if span_end - span_start <= 1e-6:
        span_start = base_s0
        span_end = base_s1

    left_extended_to_piece_edge = False
    right_extended_to_piece_edge = False
    edge_touch_tol_m = 0.1
    if drivezone_union is not None and (not drivezone_union.is_empty):
        p0_probe = output_crossline.interpolate(span_start)
        p1_probe = output_crossline.interpolate(span_end)
        left_probe_dist = float(p0_probe.distance(drivezone_union.boundary))
        right_probe_dist = float(p1_probe.distance(drivezone_union.boundary))
        if left_probe_dist > edge_touch_tol_m + 1e-9 and span_start > base_s0 + 1e-9:
            span_start = base_s0
            left_extended_to_piece_edge = True
        if right_probe_dist > edge_touch_tol_m + 1e-9 and span_end < base_s1 - 1e-9:
            span_end = base_s1
            right_extended_to_piece_edge = True

    if (not math.isfinite(span_start)) or (not math.isfinite(span_end)) or (span_end - span_start) <= 1e-6:
        _add_bp(
            code=BP_DRIVEZONE_CLIP_EMPTY,
            severity="hard",
            message="drivezone_selected_span_degenerate",
        )
        out = _empty_fail_result(
            nodeid=nodeid,
            kind=kind,
            anchor_type=anchor_type,
            scan_dir=scan_dir_label,
            line=output_crossline,
            divstrip_union=divstrip_union,
            drivezone_union=drivezone_union,
            stop_reason="drivezone_selected_span_degenerate",
            id_fields=node.id_fields,
            resolved_from=resolved_from,
            is_in_continuous_chain=bool(is_in_continuous_chain),
            chain_component_id=chain_component_id,
            chain_node_offset_m=chain_offset,
            abs_s_prev_required_m=required_prev_abs,
        )
        out.update(
            {
                "stop_dist_m": float(stop_dist),
                "next_intersection_dist_m": None if next_inter is None else float(next_inter),
                "tip_s_m": None if tip_s is None else float(tip_s),
                "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
                "best_divstrip_dz_dist_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
                "clip_empty": True,
                "clip_piece_type": "none",
                "clip_input_len_m": float(output_crossline.length),
                "stop_diag": stop_diag,
                "s_divstrip_m": None if s_divstrip_out is None else float(s_divstrip_out),
                "s_drivezone_split_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
                "s_chosen_m": float(scan_dist),
                "split_pick_source": f"{split_pick_source}_span_degenerate",
                "divstrip_ref_source": str(divstrip_ref_source_out),
                "divstrip_ref_offset_m": divstrip_ref_offset,
                "output_cross_half_len_m": float(output_cross_half_len_m),
                "branch_a_id": branch_a_id,
                "branch_b_id": branch_b_id,
                "branch_axis_id": axis_id,
                "has_divstrip_nearby": False,
                "ng_candidates_before_suppress": int(ng_points_xy.shape[0]),
                "ng_candidates_after_suppress": int(ng_points_xy.shape[0]),
                **multibranch_diag_payload,
                **reverse_diag_payload,
            }
        )
        return out

    p0 = output_crossline.interpolate(span_start)
    p1 = output_crossline.interpolate(span_end)
    final_geom = LineString([(float(p0.x), float(p0.y)), (float(p1.x), float(p1.y))])
    left_end_to_dz_edge = None if drivezone_union is None else float(p0.distance(drivezone_union.boundary))
    right_end_to_dz_edge = None if drivezone_union is None else float(p1.distance(drivezone_union.boundary))
    gap_mid = final_geom.interpolate(0.5, normalized=True) if final_geom.length > 1e-9 else center_pt
    gap_len = None
    selected_lines = [selected_piece[0]]
    selected_piece_lens = [float(selected_piece[0].length)]

    has_divstrip_nearby = False
    dist_line_to_div = None
    dist_to_div = None
    if divstrip_union is not None:
        dist_line_to_div = float(final_geom.distance(divstrip_union))
        has_divstrip_nearby = bool(dist_line_to_div <= float(div_tol))
        dist_to_div = float(gap_mid.distance(divstrip_union))
        if bool(reverse_tip_used) and (s_drivezone_split_out is None) and has_divstrip_nearby:
            _add_bp(
                code=BP_DIVSTRIP_NON_INTERSECT_NOT_FOUND,
                severity="hard",
                message="reverse_no_split_non_intersect_not_found",
                extra={
                    "reverse_search_max_m": float(reverse_tip_max_m),
                    "s_ref_m": float(ref_s),
                    "s_chosen_m": float(scan_dist),
                    "dist_line_to_divstrip_m": float(dist_line_to_div),
                },
            )

    if has_divstrip_nearby and bool(params.get("divstrip_anchor_snap_enabled", False)) and divstrip_union is not None:
        try:
            from shapely.ops import nearest_points

            _p0, p1 = nearest_points(gap_mid, divstrip_union.boundary)
            gap_mid = Point(float(p1.x), float(p1.y))
        except Exception:
            pass

    piece_lens = [float(ln.length) for ln in output_pieces_raw]
    clipped_len = float(final_geom.length)
    flags: list[str] = []
    if scan_dist > float(params.get("scan_near_limit_m", 20.0)):
        flags.append("scan_dist_gt_near_limit")
    if has_extra_piece:
        flags.append("drivezone_clip_multipiece")
    if has_divstrip_nearby:
        flags.append("divstrip_nearby")
    if position_source == "divstrip_ref":
        flags.append("divstrip_ref_used")
    if divstrip_ref_offset is not None and divstrip_ref_offset > float(divstrip_preferred_window_m):
        flags.append("divstrip_ref_offset_gt_window")
    if not center_piece_hit:
        flags.append("center_piece_missing_fallback")
    if left_extended_to_piece_edge:
        flags.append("left_extended_to_piece_edge")
    if right_extended_to_piece_edge:
        flags.append("right_extended_to_piece_edge")

    status = "suspect" if flags else "ok"
    if hard_failed:
        status = "fail"

    found_split = bool(s_drivezone_split_out is not None)
    trigger = "drivezone_split" if found_split else "divstrip_ref"
    if position_source == "divstrip_ref" and found_split:
        evidence_source = "drivezone_split+divstrip"
    elif position_source == "divstrip_ref":
        evidence_source = "divstrip_ref"
    else:
        evidence_source = "drivezone_split"
    conf = compute_confidence(trigger=trigger, scan_dist_m=scan_dist)
    anchor_found = bool((not hard_failed) and status in {"ok", "suspect"})
    dist_line_to_dz_edge = None if drivezone_union is None else float(final_geom.distance(drivezone_union.boundary))
    clip_piece_type = "continuous_center_piece" if center_piece_hit else "continuous_nearest_piece_fallback"
    abs_s_chosen = _compute_abs_s(
        is_diverge=bool(is_diverge),
        is_merge=bool(is_merge),
        node_offset_m=chain_offset,
        s_local=float(scan_dist),
    )
    sequential_ok = bool(
        (required_prev_abs is None)
        or (abs_s_chosen is not None and float(abs_s_chosen) > float(required_prev_abs) + 1e-9)
    )

    left_edge_dist_m = float(max(0.0, center_s - span_start))
    right_edge_dist_m = float(max(0.0, span_end - center_s))

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
        "found_split": bool(found_split),
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
        "crossline_opt_pieces": [],
        "tip_s_m": None if tip_s is None else float(tip_s),
        "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
        "best_divstrip_dz_dist_m": float(scan_dist),
        "best_divstrip_pc_dist_m": None,
        "first_pc_only_dist_m": None,
        "fan_area_m2": 0.0,
        "non_drivezone_area_m2": 0.0,
        "non_drivezone_frac": 0.0,
        "clipped_len_m": clipped_len,
        "clip_empty": False,
        "clip_piece_type": clip_piece_type,
        "clip_input_len_m": float(output_crossline.length),
        "stop_diag": stop_diag,
        "pieces_count": int(len(output_pieces_raw)),
        "piece_lens_m": piece_lens,
        "selected_piece_count": int(len(selected_lines)),
        "selected_piece_lens_m": selected_piece_lens,
        "position_source": str(position_source_final),
        "gap_len_m": None if gap_len is None else float(gap_len),
        "seg_len_m": float(found_diag.get("seg_len_m", found_seg.length)),
        "s_divstrip_m": None if s_divstrip_out is None else float(s_divstrip_out),
        "s_drivezone_split_m": None if s_drivezone_split_out is None else float(s_drivezone_split_out),
        "s_chosen_m": float(scan_dist),
        "split_pick_source": str(split_pick_source),
        "divstrip_ref_source": str(divstrip_ref_source_out),
        "divstrip_ref_offset_m": divstrip_ref_offset,
        "output_cross_half_len_m": float(output_cross_half_len_m),
        "branch_a_id": branch_a_id,
        "branch_b_id": branch_b_id,
        "branch_axis_id": axis_id,
        "branch_a_crossline_hit": bool(found_diag.get("branch_a_crossline_hit", False)),
        "branch_b_crossline_hit": bool(found_diag.get("branch_b_crossline_hit", False)),
        "pa_center_dist_m": found_diag.get("pa_center_dist_m"),
        "pb_center_dist_m": found_diag.get("pb_center_dist_m"),
        "left_edge_dist_m": left_edge_dist_m,
        "right_edge_dist_m": right_edge_dist_m,
        "left_end_to_drivezone_edge_m": left_end_to_dz_edge,
        "right_end_to_drivezone_edge_m": right_end_to_dz_edge,
        "left_extended_to_piece_edge": bool(left_extended_to_piece_edge),
        "right_extended_to_piece_edge": bool(right_extended_to_piece_edge),
        "has_divstrip_nearby": bool(has_divstrip_nearby),
        "reverse_tip_attempted": bool(reverse_tip_attempted),
        "reverse_tip_used": bool(reverse_tip_used),
        "reverse_tip_not_improved": bool(reverse_tip_not_improved),
        "reverse_search_max_m": float(reverse_tip_max_m),
        "reverse_trigger": reverse_trigger,
        "ref_s_forward_m": None if ref_s_forward is None else float(ref_s_forward),
        "position_source_forward": None if position_source_forward == "none" else str(position_source_forward),
        "ref_s_reverse_m": None if ref_s_reverse is None else float(ref_s_reverse),
        "position_source_reverse": position_source_reverse,
        "ref_s_final_m": None if ref_s_final is None else float(ref_s_final),
        "position_source_final": None if position_source_final == "none" else str(position_source_final),
        "untrusted_divstrip_at_node": bool(untrusted_divstrip_at_node),
        "node_to_divstrip_m_at_s0": None if node_to_divstrip_m_at_s0 is None else float(node_to_divstrip_m_at_s0),
        "seg0_intersects_divstrip": seg0_intersects_divstrip,
        "ng_candidates_before_suppress": int(ng_points_xy.shape[0]),
        "ng_candidates_after_suppress": int(ng_points_xy.shape[0]),
        "is_in_continuous_chain": bool(is_in_continuous_chain),
        "chain_component_id": chain_component_id,
        "chain_node_offset_m": chain_offset,
        "abs_s_chosen_m": None if abs_s_chosen is None else float(abs_s_chosen),
        "abs_s_prev_required_m": None if required_prev_abs is None else float(required_prev_abs),
        "sequential_ok": bool(sequential_ok),
        "sequential_violation_reason": None,
        "merged": False,
        "merged_group_id": None,
        "merged_with_nodeids": None,
        "abs_s_merged_m": None,
        "merged_crossline_id": None,
        "merged_output_nodeids": None,
        "merged_output_kinds": None,
        "merged_output_roles": None,
        "merged_output_anchor_types": None,
        "merge_reason": None,
        "merge_geom_dist_m": None,
        "merge_abs_diff_m": None,
        "merge_abs_gap_cfg_m": None,
        "merge_abs_gate_skipped": None,
        "suppress_intersection_feature": False,
        "multibranch_enabled": bool(multibranch_enabled),
        "multibranch_N": int(multibranch_n),
        "multibranch_expected_events": int(multibranch_expected_events),
        "split_events_forward": list(split_events_forward),
        "split_events_reverse": list(split_events_reverse),
        "s_main_m": None if s_main_m is None else float(s_main_m),
        "main_pick_source": str(main_pick_source),
        "abnormal_two_sided": bool(abnormal_two_sided),
        "span_extra_m": float(multibranch_span_extra_m),
        "direction_filter_applied": True,
        "branches_used_count": int(branches_used_count),
        "branches_ignored_due_to_direction": int(branches_ignored_due_to_direction),
        "s_drivezone_split_first_m": None if s_drivezone_split_first_m is None else float(s_drivezone_split_first_m),
        "multibranch_event_lines": multibranch_event_lines,
        "resolved_from": resolved_from,
    }


def _serialize_seed_result(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    out.pop("anchor_point", None)
    out.pop("crossline_opt", None)
    out.pop("crossline_opt_pieces", None)
    out.pop("multibranch_event_lines", None)
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

    continuous_enable = bool(params.get("continuous_enable", True))
    chain_edges = []
    chain_components: list[ChainComponent] = []
    chain_diag: dict[str, Any] = {"enabled": bool(continuous_enable), "edge_count": 0, "component_count": 0}
    if continuous_enable and seeds:
        try:
            chain_edges, chain_components, chain_diag_raw = build_continuous_graph(
                starts_set={int(n.nodeid) for n in seeds},
                nodes_kind=node_kinds,
                roads=roads,
                continuous_dist_max_m=float(params.get("continuous_dist_max_m", 50.0)),
            )
            chain_diag = {"enabled": True, **dict(chain_diag_raw)}
            if chain_diag.get("dir_errors"):
                for err in chain_diag.get("dir_errors", []):
                    breakpoints.append(
                        make_breakpoint(
                            code=BP_ROAD_FIELD_MISSING,
                            severity="soft",
                            nodeid=None,
                            message=f"continuous_chain_direction:{err}",
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            chain_diag = {"enabled": True, "error": f"{type(exc).__name__}:{exc}"}
            chain_edges = []
            chain_components = []

    seed_results: list[dict[str, Any]] = []
    seed_by_id = {int(n.nodeid): n for n in seeds}
    seed_order = [int(n.nodeid) for n in seeds]
    processed_ids: set[int] = set()

    if continuous_enable and chain_components:
        for comp in sorted(chain_components, key=lambda c: str(c.component_id)):
            comp_seed_ids = [int(x) for x in comp.node_ids if int(x) in seed_by_id]
            if not comp_seed_ids:
                continue
            abs_selected: dict[int, float] = {}
            ordered_ids = sorted(
                comp_seed_ids,
                key=lambda nid: (
                    float(comp.offsets_m.get(int(nid), 0.0)),
                    int(nid),
                ),
            )
            for nid in ordered_ids:
                node = seed_by_id[int(nid)]
                pred_ids = [int(x) for x in comp.predecessors.get(int(nid), tuple()) if int(x) in comp_seed_ids]
                pred_abs = [float(abs_selected[p]) for p in pred_ids if p in abs_selected]
                required_prev_abs = max(pred_abs) if pred_abs else None
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
                    is_in_continuous_chain=True,
                    chain_component_id=str(comp.component_id),
                    chain_node_offset_m=comp.offsets_m.get(int(nid)),
                    required_prev_abs_s=None if required_prev_abs is None else float(required_prev_abs),
                )
                res["ng_candidates_before_suppress"] = int(ng_before_suppress)
                res["ng_candidates_after_suppress"] = int(ng_after_suppress)
                nodeid = int(node.nodeid)
                processed_ids.add(nodeid)
                seed_results.append(res)
                abs_chosen = res.get("abs_s_chosen_m")
                if str(res.get("status")) != "fail" and abs_chosen is not None:
                    abs_selected[nodeid] = float(abs_chosen)

    for nid in seed_order:
        if nid in processed_ids:
            continue
        node = seed_by_id[nid]
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

    if continuous_enable and chain_components:
        _apply_continuous_merges(
            seed_results=seed_results,
            components=chain_components,
            merge_gap_m=float(params.get("continuous_merge_max_gap_m", 5.0)),
            geom_tol_m=float(params.get("continuous_merge_geom_tol_m", 1.0)),
        )

    dst_tag = "3857" if str(dst_crs).upper() == "EPSG:3857" else str(dst_crs).split(":")[-1].lower()
    anchors_dst_path = out_dir / f"anchors_{dst_tag}.geojson"
    inter_opt_dst_path = out_dir / f"intersection_l_opt_{dst_tag}.geojson"
    anchors_wgs84_path = out_dir / "anchors_wgs84.geojson"
    inter_opt_wgs84_path = out_dir / "intersection_l_opt_wgs84.geojson"
    anchors_geojson_path = out_dir / "anchors.geojson"
    inter_opt_path = out_dir / "intersection_l_opt.geojson"
    inter_multi_path = out_dir / "intersection_l_multi.geojson"
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
    write_intersection_multi_geojson(path=inter_multi_path, seed_results=seed_results, src_crs_name=dst_crs, dst_crs_name=dst_crs)

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
            "continuous_chain": {
                "diag": chain_diag,
                "components": [
                    {
                        "component_id": str(comp.component_id),
                        "node_ids": [int(x) for x in comp.node_ids],
                        "edges": [
                            {"src": int(e.src), "dst": int(e.dst), "dist_m": float(e.dist_m)}
                            for e in comp.edges
                        ],
                        "offsets_m": {str(k): float(v) for k, v in comp.offsets_m.items()},
                        "predecessors": {str(k): [int(x) for x in v] for k, v in comp.predecessors.items()},
                    }
                    for comp in chain_components
                ],
            },
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
        inter_multi_path,
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
