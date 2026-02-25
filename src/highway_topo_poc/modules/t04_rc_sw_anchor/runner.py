from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from shapely.geometry import Point, mapping

from .geometry_ops import RoadGraph, build_crossline, line_midpoint, normalize_vec
from .io_geojson import (
    IntersectionLineRecord,
    NodeRecord,
    RoadRecord,
    extract_crs_name,
    load_divstrip_union,
    load_intersection_lines,
    load_nodes,
    load_roads,
    make_feature_collection,
    read_geojson,
    write_geojson,
)
from .metrics_breakpoints import (
    BP_AMBIGUOUS_KIND,
    BP_DIVSTRIP_TOLERANCE_VIOLATION,
    BP_DIVSTRIPZONE_MISSING,
    BP_MISSING_INTERSECTION_L,
    BP_MULTIPLE_INTERSECTION_L,
    BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION,
    BP_POINTCLOUD_MISSING_OR_UNUSABLE,
    BP_ROAD_LINK_NOT_FOUND,
    BP_SCAN_EXCEED_200M,
    BP_UNSUPPORTED_KIND,
    build_metrics,
    build_summary_text,
    compute_confidence,
    make_breakpoint,
    summarize_breakpoints,
)
from .pointcloud_io import PointCloudData, count_non_ground_points_near_line, load_pointcloud

NODE_PRIMARY = "RCSDNode.geojson"
NODE_FALLBACK = "Node.geojson"
ROAD_PRIMARY = "RCSDRoad.geojson"
ROAD_FALLBACK = "Road.geojson"


@dataclass(frozen=True)
class RunResult:
    run_id: str
    patch_id: str
    out_dir: Path
    overall_pass: bool


def _make_run_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{uuid.uuid4().hex[:6]}"


def _is_merge(kind: int) -> bool:
    return (int(kind) & (1 << 3)) != 0


def _is_diverge(kind: int) -> bool:
    return (int(kind) & (1 << 4)) != 0


def _is_cross(kind: int) -> bool:
    return (int(kind) & (1 << 2)) != 0


def _kind_label(kind: int) -> str:
    m = _is_merge(kind)
    d = _is_diverge(kind)
    if m and d:
        return "ambiguous"
    if d:
        return "diverge"
    if m:
        return "merge"
    if _is_cross(kind):
        return "cross"
    return "unsupported"


def _line_endpoints_xy(line: Any) -> list[list[float]]:
    coords = list(line.coords)
    if len(coords) < 2:
        return []
    p0 = [float(coords[0][0]), float(coords[0][1])]
    p1 = [float(coords[-1][0]), float(coords[-1][1])]
    return [p0, p1]


def _anchor_point_from_line_and_divstrip(final_line: Any, divstrip_union: Any | None) -> tuple[Point, float | None]:
    if divstrip_union is None:
        p = line_midpoint(final_line)
        return p, None

    inter = final_line.intersection(divstrip_union)
    if inter is not None and not inter.is_empty:
        p = inter.centroid
    else:
        p = line_midpoint(final_line)

    dist = float(p.distance(divstrip_union))
    return p, dist


def _make_line_for_step(
    *,
    base_center: tuple[float, float],
    scan_dir: tuple[float, float],
    scan_dist_m: float,
    cross_half_len_m: float,
) -> Any:
    cx = base_center[0] + scan_dir[0] * float(scan_dist_m)
    cy = base_center[1] + scan_dir[1] * float(scan_dist_m)
    return build_crossline(center_xy=(cx, cy), tangent=scan_dir, cross_half_len_m=float(cross_half_len_m))


def _group_intersection_by_node(lines: list[IntersectionLineRecord]) -> dict[int, list[IntersectionLineRecord]]:
    out: dict[int, list[IntersectionLineRecord]] = {}
    for item in lines:
        out.setdefault(int(item.nodeid), []).append(item)
    return out


def _collect_seed_nodes(nodes: list[NodeRecord]) -> tuple[list[NodeRecord], list[NodeRecord]]:
    seeds: list[NodeRecord] = []
    unsupported: list[NodeRecord] = []
    for node in nodes:
        kind = int(node.kind)
        if _is_merge(kind) or _is_diverge(kind):
            seeds.append(node)
        elif _is_cross(kind) or kind != 0:
            unsupported.append(node)
    return seeds, unsupported


def _resolve_vector_path(vector_dir: Path, primary_name: str, fallback_name: str | None = None) -> Path:
    primary = vector_dir / primary_name
    if primary.is_file():
        return primary
    if fallback_name:
        fallback = vector_dir / fallback_name
        if fallback.is_file():
            return fallback
    return primary


def _scan_seed(
    *,
    node: NodeRecord,
    seed_kind: str,
    road_graph: RoadGraph,
    divstrip_union: Any | None,
    pointcloud: PointCloudData | None,
    config: dict[str, Any],
    intersection_line: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    bps: list[dict[str, Any]] = []

    nodeid = int(node.nodeid)
    node_pt = node.point
    center = (float(node_pt.x), float(node_pt.y))

    if seed_kind == "diverge":
        pick = road_graph.pick_incoming_road(nodeid)
        scan_dir_label = "forward"
        if pick is None:
            bps.append(
                make_breakpoint(
                    code=BP_ROAD_LINK_NOT_FOUND,
                    severity="hard",
                    nodeid=nodeid,
                    message="diverge_seed_missing_incoming_road",
                )
            )
            final_line = build_crossline(
                center_xy=center,
                tangent=(1.0, 0.0),
                cross_half_len_m=float(config["cross_half_len_m"]),
            )
            anchor_pt = line_midpoint(final_line)
            return (
                {
                    "nodeid": nodeid,
                    "anchor_type": seed_kind,
                    "status": "fail",
                    "anchor_found": False,
                    "trigger": "none",
                    "scan_dir": scan_dir_label,
                    "scan_dist_m": None,
                    "next_intersection_dist_m": None,
                    "stop_dist_m": 0.0,
                    "dist_to_divstrip_m": float(anchor_pt.distance(divstrip_union)) if divstrip_union is not None else None,
                    "flags": [],
                    "confidence": 0.0,
                    "anchor_point": anchor_pt,
                    "crossline_opt": final_line,
                    "evidence": {"scan_steps": 0, "divstrip_hit_count": 0, "non_ground_hit_count": 0},
                },
                bps,
            )
        tangent = normalize_vec(*pick.tangent_at_node)
        scan_dir = tangent
    else:
        pick = road_graph.pick_outgoing_road(nodeid)
        scan_dir_label = "backward"
        if pick is None:
            bps.append(
                make_breakpoint(
                    code=BP_ROAD_LINK_NOT_FOUND,
                    severity="hard",
                    nodeid=nodeid,
                    message="merge_seed_missing_outgoing_road",
                )
            )
            final_line = build_crossline(
                center_xy=center,
                tangent=(1.0, 0.0),
                cross_half_len_m=float(config["cross_half_len_m"]),
            )
            anchor_pt = line_midpoint(final_line)
            return (
                {
                    "nodeid": nodeid,
                    "anchor_type": seed_kind,
                    "status": "fail",
                    "anchor_found": False,
                    "trigger": "none",
                    "scan_dir": scan_dir_label,
                    "scan_dist_m": None,
                    "next_intersection_dist_m": None,
                    "stop_dist_m": 0.0,
                    "dist_to_divstrip_m": float(anchor_pt.distance(divstrip_union)) if divstrip_union is not None else None,
                    "flags": [],
                    "confidence": 0.0,
                    "anchor_point": anchor_pt,
                    "crossline_opt": final_line,
                    "evidence": {"scan_steps": 0, "divstrip_hit_count": 0, "non_ground_hit_count": 0},
                },
                bps,
            )
        tangent = normalize_vec(*pick.tangent_at_node)
        scan_dir = (-tangent[0], -tangent[1])

    next_intersection_dist = road_graph.find_next_intersection_distance(
        nodeid=nodeid,
        scan_dir=scan_dir,
        intersection_kind_mask=0b11100,
    )

    scan_max_limit = float(config["scan_max_limit_m"])
    stop_dist = scan_max_limit
    if bool(config["stop_at_next_intersection"]) and next_intersection_dist is not None and next_intersection_dist > 0:
        stop_dist = min(stop_dist, float(next_intersection_dist))
    stop_dist = max(0.0, float(stop_dist))

    step = max(0.25, float(config["scan_step_m"]))
    n_steps = int(math.floor(stop_dist / step)) + 1
    n_steps = max(1, n_steps)

    divstrip_tol = float(config["divstrip_hit_tol_m"])
    window_steps = max(1, int(math.ceil(float(config["divstrip_trigger_window_m"]) / step)))

    pc_usable = bool(pointcloud is not None and pointcloud.usable)
    line_list: list[Any] = []
    hit_divstrip: list[bool] = []
    hit_non_ground: list[bool] = []

    for i in range(n_steps):
        dist_i = float(i) * step
        line_i = _make_line_for_step(
            base_center=center,
            scan_dir=scan_dir,
            scan_dist_m=dist_i,
            cross_half_len_m=float(config["cross_half_len_m"]),
        )
        line_list.append(line_i)

        has_div = bool(divstrip_union is not None and line_i.distance(divstrip_union) <= divstrip_tol)
        hit_divstrip.append(has_div)

        has_ng = False
        if pc_usable and pointcloud is not None:
            ng_count = count_non_ground_points_near_line(
                line=line_i,
                pointcloud=pointcloud,
                line_buffer_m=float(config["pc_line_buffer_m"]),
                ground_class=int(config["pc_ground_class"]),
                use_classification=bool(config["pc_use_classification"]),
                ignore_end_margin_m=float(config["ignore_end_margin_m"]),
            )
            has_ng = ng_count >= int(config["pc_non_ground_min_points"])
        hit_non_ground.append(bool(has_ng))

    found_idx: int | None = None
    trigger = "none"
    first_divstrip_idx: int | None = None

    for i in range(n_steps):
        if hit_divstrip[i] and pc_usable:
            lo = i + 1
            hi = min(n_steps - 1, i + window_steps)
            lookahead_ok = any(hit_non_ground[j] for j in range(lo, hi + 1)) if lo <= hi else False
            if lookahead_ok:
                found_idx = i
                trigger = "divstrip+pc"
                break

        if pc_usable and hit_non_ground[i]:
            if (not bool(config["ignore_initial_side_ng"])) or i > 0:
                found_idx = i
                trigger = "pc_only"
                break

        if (not pc_usable) and bool(config["allow_divstrip_only_when_no_pointcloud"]) and hit_divstrip[i]:
            if first_divstrip_idx is None:
                first_divstrip_idx = i

    if found_idx is None and first_divstrip_idx is not None:
        found_idx = int(first_divstrip_idx)
        trigger = "divstrip_only_degraded"
        bps.append(
            make_breakpoint(
                code=BP_POINTCLOUD_MISSING_OR_UNUSABLE,
                severity="soft",
                nodeid=nodeid,
                message="fallback_to_divstrip_only_without_pointcloud",
                extra={"pointcloud_source": None if pointcloud is None else pointcloud.source_kind},
            )
        )

    if found_idx is None:
        bps.append(
            make_breakpoint(
                code=BP_NO_TRIGGER_BEFORE_NEXT_INTERSECTION,
                severity="soft",
                nodeid=nodeid,
                message="scan_stop_without_trigger",
                extra={"stop_dist_m": stop_dist},
            )
        )

    final_idx = found_idx if found_idx is not None else (n_steps - 1)
    final_line = line_list[final_idx]
    scan_dist_m = float(final_idx) * step if found_idx is not None else None

    flags: list[str] = []
    if scan_dist_m is not None and scan_dist_m > float(config["scan_near_limit_m"]):
        flags.append("SCAN_DIST_OVER_NEAR_LIMIT")

    if (scan_dist_m is not None and scan_dist_m > 200.0) or (scan_dist_m is None and stop_dist >= 200.0):
        flags.append("MANUAL_REVIEW_OVER_200M")
        bps.append(
            make_breakpoint(
                code=BP_SCAN_EXCEED_200M,
                severity="soft",
                nodeid=nodeid,
                message="scan_distance_exceeds_200m_or_hits_limit",
                extra={"scan_dist_m": scan_dist_m, "stop_dist_m": stop_dist},
            )
        )

    anchor_point, dist_to_divstrip = _anchor_point_from_line_and_divstrip(final_line, divstrip_union)

    if trigger in {"divstrip+pc", "divstrip_only_degraded"} and dist_to_divstrip is not None:
        if dist_to_divstrip > divstrip_tol + 1e-9:
            flags.append("DIVSTRIP_TOLERANCE_VIOLATION")
            bps.append(
                make_breakpoint(
                    code=BP_DIVSTRIP_TOLERANCE_VIOLATION,
                    severity="hard",
                    nodeid=nodeid,
                    message="divstrip_triggered_but_anchor_too_far",
                    extra={"dist_to_divstrip_m": float(dist_to_divstrip), "tol_m": float(divstrip_tol)},
                )
            )

    status = "fail"
    if found_idx is not None:
        status = "ok" if float(scan_dist_m or 0.0) <= float(config["scan_near_limit_m"]) else "suspect"

    confidence = 0.0 if found_idx is None else compute_confidence(trigger=trigger, scan_dist_m=scan_dist_m)

    result = {
        "nodeid": nodeid,
        "anchor_type": seed_kind,
        "status": status,
        "anchor_found": found_idx is not None,
        "trigger": trigger,
        "scan_dir": scan_dir_label,
        "scan_dist_m": scan_dist_m,
        "next_intersection_dist_m": float(next_intersection_dist) if next_intersection_dist is not None else None,
        "stop_dist_m": float(stop_dist),
        "dist_to_divstrip_m": float(dist_to_divstrip) if dist_to_divstrip is not None else None,
        "confidence": float(confidence),
        "flags": flags,
        "anchor_point": anchor_point,
        "crossline_opt": final_line,
        "evidence": {
            "scan_steps": int(n_steps),
            "divstrip_hit_count": int(sum(1 for x in hit_divstrip if x)),
            "non_ground_hit_count": int(sum(1 for x in hit_non_ground if x)),
            "intersection_line_midpoint_xy": [
                float(line_midpoint(intersection_line).x),
                float(line_midpoint(intersection_line).y),
            ],
        },
    }
    return result, bps


def _make_anchor_features(seed_result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    props = {
        "nodeid": int(seed_result["nodeid"]),
        "anchor_type": str(seed_result["anchor_type"]),
        "status": str(seed_result["status"]),
        "scan_dir": str(seed_result["scan_dir"]),
        "scan_dist_m": seed_result.get("scan_dist_m"),
        "trigger": str(seed_result["trigger"]),
        "dist_to_divstrip_m": seed_result.get("dist_to_divstrip_m"),
        "confidence": float(seed_result.get("confidence", 0.0)),
        "flags": list(seed_result.get("flags", [])),
    }

    point_feature = {
        "type": "Feature",
        "properties": dict(props, feature_role="anchor_point"),
        "geometry": mapping(seed_result["anchor_point"]),
    }
    line_feature = {
        "type": "Feature",
        "properties": dict(props, feature_role="crossline_opt"),
        "geometry": mapping(seed_result["crossline_opt"]),
    }
    return point_feature, line_feature


def _anchors_json_entry(seed_result: dict[str, Any]) -> dict[str, Any]:
    p = seed_result["anchor_point"]
    line = seed_result["crossline_opt"]
    return {
        "nodeid": int(seed_result["nodeid"]),
        "anchor_type": str(seed_result["anchor_type"]),
        "status": str(seed_result["status"]),
        "anchor_found": bool(seed_result["anchor_found"]),
        "trigger": str(seed_result["trigger"]),
        "scan_dir": str(seed_result["scan_dir"]),
        "scan_dist_m": seed_result.get("scan_dist_m"),
        "next_intersection_dist_m": seed_result.get("next_intersection_dist_m"),
        "stop_dist_m": seed_result.get("stop_dist_m"),
        "dist_to_divstrip_m": seed_result.get("dist_to_divstrip_m"),
        "confidence": seed_result.get("confidence"),
        "flags": list(seed_result.get("flags", [])),
        "anchor_xy": [float(p.x), float(p.y)],
        "crossline_endpoints_xy": _line_endpoints_xy(line),
        "evidence": dict(seed_result.get("evidence", {})),
    }


def _make_failed_seed_result(
    *,
    node: NodeRecord,
    anchor_type: str,
    scan_dir: str,
    reason: str,
    intersection_line: Any | None = None,
) -> dict[str, Any]:
    center = (float(node.point.x), float(node.point.y))
    base_line = intersection_line
    if base_line is None:
        base_line = build_crossline(center_xy=center, tangent=(1.0, 0.0), cross_half_len_m=20.0)
    anchor_pt = line_midpoint(base_line)
    return {
        "nodeid": int(node.nodeid),
        "anchor_type": str(anchor_type),
        "status": "fail",
        "anchor_found": False,
        "trigger": "none",
        "scan_dir": str(scan_dir),
        "scan_dist_m": None,
        "next_intersection_dist_m": None,
        "stop_dist_m": 0.0,
        "dist_to_divstrip_m": None,
        "confidence": 0.0,
        "flags": [str(reason)],
        "anchor_point": anchor_pt,
        "crossline_opt": base_line,
        "evidence": {"scan_steps": 0, "divstrip_hit_count": 0, "non_ground_hit_count": 0},
    }


def run_patch(
    *,
    patch_dir: Path,
    out_root: Path,
    config: dict[str, Any],
    run_id: str | None = None,
) -> RunResult:
    run_id_val = run_id or _make_run_id()
    patch_id = patch_dir.name
    out_dir = out_root / run_id_val
    out_dir.mkdir(parents=True, exist_ok=True)

    chosen_config_path = out_dir / "chosen_config.json"
    chosen_config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    breakpoints: list[dict[str, Any]] = []
    seed_results: list[dict[str, Any]] = []
    anchor_point_features: list[dict[str, Any]] = []
    anchor_line_features: list[dict[str, Any]] = []

    crs_name: str | None = None
    must_inputs_ok = True

    try:
        vector_dir = patch_dir / "Vector"
        node_payload = read_geojson(_resolve_vector_path(vector_dir, NODE_PRIMARY, NODE_FALLBACK))
        intersection_payload = read_geojson(patch_dir / "Vector" / "intersection_l.geojson")
        road_payload = read_geojson(_resolve_vector_path(vector_dir, ROAD_PRIMARY, ROAD_FALLBACK))

        crs_name = extract_crs_name(node_payload) or extract_crs_name(intersection_payload) or extract_crs_name(road_payload)

        nodes, node_errors = load_nodes(node_payload)
        intersections, inter_errors = load_intersection_lines(intersection_payload)
        roads, road_errors = load_roads(road_payload)

        for msg in node_errors + inter_errors + road_errors:
            breakpoints.append(
                make_breakpoint(
                    code=BP_UNSUPPORTED_KIND,
                    severity="soft",
                    nodeid=None,
                    message=f"input_parse_warning:{msg}",
                )
            )

        if not nodes or not roads:
            must_inputs_ok = False
            breakpoints.append(
                make_breakpoint(
                    code=BP_ROAD_LINK_NOT_FOUND,
                    severity="hard",
                    nodeid=None,
                    message="must_inputs_parsed_but_nodes_or_roads_empty",
                )
            )

        node_map: dict[int, NodeRecord] = {int(n.nodeid): n for n in nodes}
        node_points = {int(n.nodeid): n.point for n in nodes}
        node_kinds = {int(n.nodeid): int(n.kind) for n in nodes}

        seeds, unsupported_nodes = _collect_seed_nodes(nodes)
        for n in unsupported_nodes:
            breakpoints.append(
                make_breakpoint(
                    code=BP_UNSUPPORTED_KIND,
                    severity="soft",
                    nodeid=int(n.nodeid),
                    message=f"node_kind_out_of_scope:{int(n.kind)}",
                )
            )

        inter_by_node = _group_intersection_by_node(intersections)

        divstrip_union = None
        divstrip_path = patch_dir / "Vector" / "DivStripZone.geojson"
        if divstrip_path.is_file():
            div_payload = read_geojson(divstrip_path)
            divstrip_union, div_err = load_divstrip_union(div_payload)
            for msg in div_err:
                breakpoints.append(
                    make_breakpoint(
                        code=BP_DIVSTRIPZONE_MISSING,
                        severity="soft",
                        nodeid=None,
                        message=f"divstrip_parse_warning:{msg}",
                    )
                )
        else:
            breakpoints.append(
                make_breakpoint(
                    code=BP_DIVSTRIPZONE_MISSING,
                    severity="soft",
                    nodeid=None,
                    message="divstrip_file_missing",
                )
            )

        pointcloud = load_pointcloud(
            patch_dir=patch_dir,
            use_classification=bool(config["pc_use_classification"]),
        )
        if pointcloud is None:
            breakpoints.append(
                make_breakpoint(
                    code=BP_POINTCLOUD_MISSING_OR_UNUSABLE,
                    severity="soft",
                    nodeid=None,
                    message="pointcloud_missing",
                )
            )
        elif not pointcloud.usable:
            breakpoints.append(
                make_breakpoint(
                    code=BP_POINTCLOUD_MISSING_OR_UNUSABLE,
                    severity="soft",
                    nodeid=None,
                    message=f"pointcloud_unusable:{pointcloud.reason}",
                )
            )

        graph = RoadGraph(roads=roads, node_points=node_points, node_kinds=node_kinds)

        for seed in sorted(seeds, key=lambda x: int(x.nodeid)):
            nodeid = int(seed.nodeid)
            kind = int(seed.kind)
            kind_label = _kind_label(kind)

            if kind_label == "ambiguous":
                breakpoints.append(
                    make_breakpoint(
                        code=BP_AMBIGUOUS_KIND,
                        severity="hard",
                        nodeid=nodeid,
                        message="node_kind_contains_merge_and_diverge",
                    )
                )
                seed_result = _make_failed_seed_result(
                    node=seed,
                    anchor_type="ambiguous",
                    scan_dir="na",
                    reason=BP_AMBIGUOUS_KIND,
                )
                seed_results.append(seed_result)
                p_feat, l_feat = _make_anchor_features(seed_result)
                anchor_point_features.append(p_feat)
                anchor_line_features.append(l_feat)
                continue

            if kind_label not in {"merge", "diverge"}:
                breakpoints.append(
                    make_breakpoint(
                        code=BP_UNSUPPORTED_KIND,
                        severity="soft",
                        nodeid=nodeid,
                        message=f"seed_kind_not_supported:{kind_label}",
                    )
                )
                seed_result = _make_failed_seed_result(
                    node=seed,
                    anchor_type=kind_label,
                    scan_dir="na",
                    reason=BP_UNSUPPORTED_KIND,
                )
                seed_results.append(seed_result)
                p_feat, l_feat = _make_anchor_features(seed_result)
                anchor_point_features.append(p_feat)
                anchor_line_features.append(l_feat)
                continue

            node_intersections = inter_by_node.get(nodeid, [])
            if len(node_intersections) == 0:
                breakpoints.append(
                    make_breakpoint(
                        code=BP_MISSING_INTERSECTION_L,
                        severity="hard",
                        nodeid=nodeid,
                        message="intersection_l_not_found_for_seed",
                    )
                )
                seed_result = _make_failed_seed_result(
                    node=seed,
                    anchor_type=kind_label,
                    scan_dir="forward" if kind_label == "diverge" else "backward",
                    reason=BP_MISSING_INTERSECTION_L,
                )
                seed_results.append(seed_result)
                p_feat, l_feat = _make_anchor_features(seed_result)
                anchor_point_features.append(p_feat)
                anchor_line_features.append(l_feat)
                continue
            if len(node_intersections) > 1:
                breakpoints.append(
                    make_breakpoint(
                        code=BP_MULTIPLE_INTERSECTION_L,
                        severity="hard",
                        nodeid=nodeid,
                        message="intersection_l_multiple_for_seed",
                    )
                )
                seed_result = _make_failed_seed_result(
                    node=seed,
                    anchor_type=kind_label,
                    scan_dir="forward" if kind_label == "diverge" else "backward",
                    reason=BP_MULTIPLE_INTERSECTION_L,
                    intersection_line=node_intersections[0].line,
                )
                seed_results.append(seed_result)
                p_feat, l_feat = _make_anchor_features(seed_result)
                anchor_point_features.append(p_feat)
                anchor_line_features.append(l_feat)
                continue

            seed_result, local_bp = _scan_seed(
                node=seed,
                seed_kind=kind_label,
                road_graph=graph,
                divstrip_union=divstrip_union,
                pointcloud=pointcloud,
                config=config,
                intersection_line=node_intersections[0].line,
            )
            breakpoints.extend(local_bp)
            seed_results.append(seed_result)

            p_feat, l_feat = _make_anchor_features(seed_result)
            anchor_point_features.append(p_feat)
            anchor_line_features.append(l_feat)

    except Exception as exc:  # noqa: BLE001
        must_inputs_ok = False
        breakpoints.append(
            make_breakpoint(
                code=BP_ROAD_LINK_NOT_FOUND,
                severity="hard",
                nodeid=None,
                message=f"fatal_runner_exception:{type(exc).__name__}:{exc}",
            )
        )

    anchors_geojson_path = out_dir / "anchors.geojson"
    anchors_json_path = out_dir / "anchors.json"
    metrics_path = out_dir / "metrics.json"
    breakpoints_path = out_dir / "breakpoints.json"
    summary_path = out_dir / "summary.txt"
    intersection_opt_path = out_dir / "intersection_l_opt.geojson"

    anchors_fc = make_feature_collection(anchor_point_features + anchor_line_features, crs_name=crs_name)
    write_geojson(anchors_geojson_path, anchors_fc)

    anchor_json_payload = {
        "run_id": run_id_val,
        "patch_id": patch_id,
        "items": [_anchors_json_entry(x) for x in seed_results],
    }
    anchors_json_path.write_text(json.dumps(anchor_json_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    inter_fc = make_feature_collection(anchor_line_features, crs_name=crs_name)
    write_geojson(intersection_opt_path, inter_fc)

    bp_summary = summarize_breakpoints(breakpoints)
    breakpoints_path.write_text(json.dumps(bp_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    required_paths = [
        anchors_geojson_path,
        anchors_json_path,
        metrics_path,
        breakpoints_path,
        summary_path,
    ]

    metrics = build_metrics(
        seed_results=seed_results,
        breakpoints=breakpoints,
        config=config,
        must_inputs_ok=must_inputs_ok,
        required_outputs_ok=True,
    )

    summary_txt = build_summary_text(
        run_id=run_id_val,
        patch_id=patch_id,
        metrics=metrics,
        breakpoints_summary=bp_summary,
        seed_results=seed_results,
    )

    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(summary_txt, encoding="utf-8")

    required_outputs_ok = all(p.is_file() for p in required_paths)
    if not required_outputs_ok:
        metrics = build_metrics(
            seed_results=seed_results,
            breakpoints=breakpoints,
            config=config,
            must_inputs_ok=must_inputs_ok,
            required_outputs_ok=False,
        )
        summary_txt = build_summary_text(
            run_id=run_id_val,
            patch_id=patch_id,
            metrics=metrics,
            breakpoints_summary=bp_summary,
            seed_results=seed_results,
        )
        metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary_path.write_text(summary_txt, encoding="utf-8")

    return RunResult(
        run_id=run_id_val,
        patch_id=patch_id,
        out_dir=out_dir,
        overall_pass=bool(metrics.get("overall_pass", False)),
    )


__all__ = ["RunResult", "run_patch"]
