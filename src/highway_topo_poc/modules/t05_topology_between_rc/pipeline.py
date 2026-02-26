from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from shapely import contains_xy
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from .geometry import (
    HARD_BRIDGE_SEGMENT,
    HARD_CENTER_EMPTY,
    HARD_ENDPOINT,
    HARD_MULTI_ROAD,
    HARD_NON_RC,
    SOFT_LOW_SUPPORT,
    SOFT_NO_STABLE_SECTION,
    SOFT_DIVSTRIP_MISSING,
    SOFT_NO_LB,
    SOFT_NO_LB_PATH,
    SOFT_OPEN_END,
    SOFT_ROAD_OUTSIDE_TRAJ_SURFACE,
    SOFT_SPARSE_POINTS,
    SOFT_TRAJ_SURFACE_GAP,
    SOFT_TRAJ_SURFACE_INSUFFICIENT,
    SOFT_UNRESOLVED_NEIGHBOR,
    SOFT_WIGGLY,
    PairSupport,
    build_pair_supports,
    compute_max_segment_m,
    estimate_centerline,
    extract_crossing_events,
    infer_node_types,
)
from .io import (
    InputDataError,
    PatchInputs,
    git_short_sha,
    load_patch_inputs,
    load_point_cloud_window,
    make_run_id,
    resolve_repo_root,
    write_geojson_lines,
    write_json,
)
from .metrics import (
    build_breakpoint,
    build_gate_payload,
    build_intervals_payload,
    build_metrics_payload,
    build_summary_text,
    compute_confidence,
    params_digest,
)

_ROAD_OUT_NAME = "Road.geojson"
_ROAD_COMPAT_OUT_NAME = "RCSDRoad.geojson"
_SOFT_CROSS_EMPTY_SKIPPED = "CROSS_EMPTY_SKIPPED"
_SOFT_CROSS_GEOM_UNEXPECTED = "CROSS_GEOM_UNEXPECTED"
_SOFT_CROSS_DISTANCE_GATE_REJECT = "CROSS_DISTANCE_GATE_REJECT"


DEFAULT_PARAMS: dict[str, Any] = {
    "TRAJ_XSEC_HIT_BUFFER_M": 0.5,
    "TRAJ_XSEC_DEDUP_GAP_M": 2.0,
    "MIN_SUPPORT_TRAJ": 2,
    "TRJ_SAMPLE_STEP_M": 2.0,
    "STITCH_TAIL_M": 30.0,
    "STITCH_MAX_DIST_LEVELS_M": [12.0, 25.0, 50.0],
    "STITCH_MAX_DIST_M": 12.0,
    "STITCH_MAX_ANGLE_DEG": 35.0,
    "STITCH_FORWARD_DOT_MIN": 0.0,
    "STITCH_MIN_ADVANCE_M": 5.0,
    "STITCH_PENALTY": 2.0,
    "STITCH_TOPK": 3,
    "NEIGHBOR_MAX_DIST_M": 2000.0,
    "MULTI_ROAD_SEP_M": 8.0,
    "MULTI_ROAD_TOPN": 10,
    "STABLE_OFFSET_M": 50.0,
    "STABLE_OFFSET_MARGIN_M": 5.0,
    "CENTER_SAMPLE_STEP_M": 5.0,
    "XSEC_ALONG_HALF_WINDOW_M": 1.0,
    "XSEC_ACROSS_HALF_WINDOW_M": 20.0,
    "CORRIDOR_HALF_WIDTH_M": 15.0,
    "XSEC_MIN_POINTS": 200,
    "WIDTH_PCT_LOW": 5,
    "WIDTH_PCT_HIGH": 95,
    "MIN_CENTER_COVERAGE": 0.6,
    "SMOOTH_WINDOW_M": 25.0,
    "OFFSET_SMOOTH_WIN_M_1": 50.0,
    "OFFSET_SMOOTH_WIN_M_2": 100.0,
    "MAX_OFFSET_DELTA_PER_STEP_M": 1.0,
    "SIMPLIFY_TOL_M": 0.8,
    "D_MIN": 20.0,
    "D_MAX": 200.0,
    "NEAR_LEN": 20.0,
    "BASE_FROM": 80.0,
    "BASE_TO": 150.0,
    "L_STABLE": 30.0,
    "RATIO_TOL": 0.10,
    "W_TOL": 1.5,
    "R_GORE": 0.02,
    "GORE_BUFFER_M": 0.8,
    "TRANSITION_M": 10.0,
    "STABLE_FALLBACK_M": 50.0,
    "TURN_LIMIT_DEG_PER_10M": 30.0,
    "BRIDGE_MAX_SEG_M": 100.0,
    "LB_SNAP_M": 1.0,
    "LB_START_END_TOPK": 5,
    "TREND_FIT_WIN_M": 20.0,
    "SURF_SLICE_STEP_M": 5.0,
    "SURF_SLICE_HALF_WIN_M": 2.0,
    "SURF_QUANT_LOW": 0.02,
    "SURF_QUANT_HIGH": 0.98,
    "SURF_BUF_M": 1.0,
    "IN_RATIO_MIN": 0.95,
    "TRAJ_SURF_MIN_POINTS_PER_SLICE": 20,
    "TRAJ_SURF_MIN_SLICE_VALID_RATIO": 0.60,
    "TRAJ_SURF_MIN_COVERED_LEN_RATIO": 0.70,
    "TRAJ_SURF_MIN_UNIQUE_TRAJ": 2,
    "ENDPOINT_ON_XSEC_TOL_M": 1.0,
    "TOPK_INTERVALS": 20,
    "CONF_W1_SUPPORT": 0.4,
    "CONF_W2_COVERAGE": 0.4,
    "CONF_W3_SMOOTH": 0.2,
    "ROAD_MAX_VERTICES": 2000,
    "POINT_CLASS_PRIMARY": 2,
    "POINT_CLASS_FALLBACK_ANY": 0,
}

@dataclass(frozen=True)
class RunResult:
    run_id: str
    patch_id: str
    output_dir: Path
    road_count: int
    overall_pass: bool
    hard_breakpoints: list[dict[str, Any]]
    soft_breakpoints: list[dict[str, Any]]


def run_patch(
    *,
    data_root: str | Path,
    patch_id: str | None = None,
    run_id: str = "auto",
    out_root: str | Path = "outputs/_work/t05_topology_between_rc",
    params_override: dict[str, Any] | None = None,
) -> RunResult:
    repo_root = resolve_repo_root(Path.cwd())
    patch_inputs = load_patch_inputs(data_root, patch_id)

    run_id_val = make_run_id("t05_topology_between_rc", repo_root=repo_root) if run_id == "auto" else str(run_id)

    out_dir = Path(out_root)
    if not out_dir.is_absolute():
        out_dir = (repo_root / out_dir).resolve()
    patch_out = out_dir / run_id_val / "patches" / patch_inputs.patch_id

    params = dict(DEFAULT_PARAMS)
    if params_override:
        params.update(params_override)

    artifacts = _run_patch_core(
        patch_inputs,
        params=params,
        run_id=run_id_val,
        repo_root=repo_root,
    )

    write_geojson_lines(
        patch_out / _ROAD_OUT_NAME,
        lines_input_crs=artifacts["road_lines_metric"],
        properties_list=artifacts["road_properties"],
        crs_name="EPSG:3857",
    )
    write_geojson_lines(
        patch_out / _ROAD_COMPAT_OUT_NAME,
        lines_input_crs=artifacts["road_lines_metric"],
        properties_list=artifacts["road_properties"],
        crs_name="EPSG:3857",
    )

    write_json(patch_out / "metrics.json", artifacts["metrics_payload"])
    write_json(patch_out / "intervals.json", artifacts["intervals_payload"])
    write_json(patch_out / "gate.json", artifacts["gate_payload"])
    (patch_out / "summary.txt").write_text(str(artifacts["summary_text"]), encoding="utf-8")

    return RunResult(
        run_id=run_id_val,
        patch_id=patch_inputs.patch_id,
        output_dir=patch_out,
        road_count=int(artifacts["road_count"]),
        overall_pass=bool(artifacts["overall_pass"]),
        hard_breakpoints=list(artifacts["hard_breakpoints"]),
        soft_breakpoints=list(artifacts["soft_breakpoints"]),
    )


def _run_patch_core(
    patch_inputs: PatchInputs,
    *,
    params: dict[str, Any],
    run_id: str,
    repo_root: Path,
) -> dict[str, Any]:
    xsec_map = _build_cross_section_map(patch_inputs)
    node_ids = sorted(xsec_map.keys())

    hard_breakpoints: list[dict[str, Any]] = []
    soft_breakpoints: list[dict[str, Any]] = []
    divstrip_missing = patch_inputs.divstrip_source_path is None
    if divstrip_missing:
        soft_breakpoints.append(
            {
                "road_id": "na",
                "src_nodeid": None,
                "dst_nodeid": None,
                "traj_id": None,
                "seq_range": None,
                "station_range_m": None,
                "reason": SOFT_DIVSTRIP_MISSING,
                "severity": "soft",
                "hint": "DivStripZone.geojson_missing",
            }
        )

    if not node_ids:
        road_lines_metric: list[LineString] = []
        road_feature_props: list[dict[str, Any]] = []
        hard_breakpoints.append(
            {
                "road_id": "na",
                "src_nodeid": None,
                "dst_nodeid": None,
                "reason": HARD_CENTER_EMPTY,
                "severity": "hard",
                "hint": "no_intersection_features",
            }
        )
        return _finalize_payloads(
            run_id=run_id,
            repo_root=repo_root,
            patch_id=patch_inputs.patch_id,
            roads=[],
            road_lines_metric=road_lines_metric,
            road_feature_props=road_feature_props,
            hard_breakpoints=hard_breakpoints,
            soft_breakpoints=soft_breakpoints,
            params=params,
            overall_pass=False,
        )

    # 先用 Node.Kind 建初值，再用图度数二次推断。
    seed_type_map = _seed_node_type_map(node_ids=node_ids, node_kind_map=patch_inputs.node_kind_map)

    cross_result = extract_crossing_events(
        patch_inputs.trajectories,
        list(xsec_map.values()),
        hit_buffer_m=float(params["TRAJ_XSEC_HIT_BUFFER_M"]),
        dedup_gap_m=float(params["TRAJ_XSEC_DEDUP_GAP_M"]),
    )
    events_by_traj = cross_result.events_by_traj

    if int(cross_result.n_cross_empty_skipped) > 0:
        soft_breakpoints.append(
            {
                "road_id": "na",
                "src_nodeid": None,
                "dst_nodeid": None,
                "traj_id": None,
                "seq_range": None,
                "station_range_m": None,
                "reason": _SOFT_CROSS_EMPTY_SKIPPED,
                "severity": "soft",
                "hint": f"n_cross_empty_skipped={int(cross_result.n_cross_empty_skipped)}",
            }
        )
    if int(cross_result.n_cross_geom_unexpected) > 0:
        soft_breakpoints.append(
            {
                "road_id": "na",
                "src_nodeid": None,
                "dst_nodeid": None,
                "traj_id": None,
                "seq_range": None,
                "station_range_m": None,
                "reason": _SOFT_CROSS_GEOM_UNEXPECTED,
                "severity": "soft",
                "hint": f"n_cross_geom_unexpected={int(cross_result.n_cross_geom_unexpected)}",
            }
        )
    if int(cross_result.n_cross_distance_gate_reject) > 0:
        soft_breakpoints.append(
            {
                "road_id": "na",
                "src_nodeid": None,
                "dst_nodeid": None,
                "traj_id": None,
                "seq_range": None,
                "station_range_m": None,
                "reason": _SOFT_CROSS_DISTANCE_GATE_REJECT,
                "severity": "soft",
                "hint": f"n_cross_distance_gate_reject={int(cross_result.n_cross_distance_gate_reject)}",
            }
        )

    if not events_by_traj:
        hard_breakpoints.append(
            {
                "road_id": "na",
                "src_nodeid": None,
                "dst_nodeid": None,
                "reason": HARD_CENTER_EMPTY,
                "severity": "hard",
                "hint": "no_traj_crossing_events",
            }
        )
        return _finalize_payloads(
            run_id=run_id,
            repo_root=repo_root,
            patch_id=patch_inputs.patch_id,
            roads=[],
            road_lines_metric=[],
            road_feature_props=[],
            hard_breakpoints=hard_breakpoints,
            soft_breakpoints=soft_breakpoints,
            params=params,
            overall_pass=False,
            extra_metrics={
                "crossing_raw_hit_count": int(cross_result.raw_hit_count),
                "crossing_dedup_drop_count": int(cross_result.dedup_drop_count),
                "n_cross_empty_skipped": int(cross_result.n_cross_empty_skipped),
                "n_cross_geom_unexpected": int(cross_result.n_cross_geom_unexpected),
                "n_cross_distance_gate_reject": int(cross_result.n_cross_distance_gate_reject),
                "divstrip_missing": bool(divstrip_missing),
            },
        )

    supports_seed_result = build_pair_supports(
        patch_inputs.trajectories,
        events_by_traj,
        node_type_map=seed_type_map,
        trj_sample_step_m=float(params["TRJ_SAMPLE_STEP_M"]),
        stitch_tail_m=float(params["STITCH_TAIL_M"]),
        stitch_max_dist_levels_m=_as_float_list(
            params.get("STITCH_MAX_DIST_LEVELS_M"),
            fallback=[float(params["STITCH_MAX_DIST_M"])],
        ),
        stitch_max_dist_m=float(params["STITCH_MAX_DIST_M"]),
        stitch_max_angle_deg=float(params["STITCH_MAX_ANGLE_DEG"]),
        stitch_forward_dot_min=float(params["STITCH_FORWARD_DOT_MIN"]),
        stitch_min_advance_m=float(params["STITCH_MIN_ADVANCE_M"]),
        stitch_penalty=float(params["STITCH_PENALTY"]),
        stitch_topk=int(params["STITCH_TOPK"]),
        neighbor_max_dist_m=float(params["NEIGHBOR_MAX_DIST_M"]),
        multi_road_sep_m=float(params["MULTI_ROAD_SEP_M"]),
        multi_road_topn=int(params["MULTI_ROAD_TOPN"]),
    )
    supports_seed = supports_seed_result.supports
    node_type_map, in_degree, out_degree = infer_node_types(
        node_ids=node_ids,
        pair_supports=supports_seed,
        node_kind_map=patch_inputs.node_kind_map,
    )
    supports_result = build_pair_supports(
        patch_inputs.trajectories,
        events_by_traj,
        node_type_map=node_type_map,
        trj_sample_step_m=float(params["TRJ_SAMPLE_STEP_M"]),
        stitch_tail_m=float(params["STITCH_TAIL_M"]),
        stitch_max_dist_levels_m=_as_float_list(
            params.get("STITCH_MAX_DIST_LEVELS_M"),
            fallback=[float(params["STITCH_MAX_DIST_M"])],
        ),
        stitch_max_dist_m=float(params["STITCH_MAX_DIST_M"]),
        stitch_max_angle_deg=float(params["STITCH_MAX_ANGLE_DEG"]),
        stitch_forward_dot_min=float(params["STITCH_FORWARD_DOT_MIN"]),
        stitch_min_advance_m=float(params["STITCH_MIN_ADVANCE_M"]),
        stitch_penalty=float(params["STITCH_PENALTY"]),
        stitch_topk=int(params["STITCH_TOPK"]),
        neighbor_max_dist_m=float(params["NEIGHBOR_MAX_DIST_M"]),
        multi_road_sep_m=float(params["MULTI_ROAD_SEP_M"]),
        multi_road_topn=int(params["MULTI_ROAD_TOPN"]),
    )
    supports = supports_result.supports
    for unresolved in supports_result.unresolved_events:
        soft_breakpoints.append(dict(unresolved))

    if not supports:
        hard_breakpoints.append(
            {
                "road_id": "na",
                "src_nodeid": None,
                "dst_nodeid": None,
                "reason": HARD_CENTER_EMPTY,
                "severity": "hard",
                "hint": "no_adjacent_pair_from_crossings",
            }
        )
        return _finalize_payloads(
            run_id=run_id,
            repo_root=repo_root,
            patch_id=patch_inputs.patch_id,
            roads=[],
            road_lines_metric=[],
            road_feature_props=[],
            hard_breakpoints=hard_breakpoints,
            soft_breakpoints=soft_breakpoints,
            params=params,
            overall_pass=False,
            extra_metrics={
                "crossing_raw_hit_count": int(cross_result.raw_hit_count),
                "crossing_dedup_drop_count": int(cross_result.dedup_drop_count),
                "n_cross_empty_skipped": int(cross_result.n_cross_empty_skipped),
                "n_cross_geom_unexpected": int(cross_result.n_cross_geom_unexpected),
                "n_cross_distance_gate_reject": int(cross_result.n_cross_distance_gate_reject),
                "stitch_candidate_count": int(supports_result.stitch_candidate_count),
                "stitch_edge_count": int(supports_result.stitch_edge_count),
                "graph_node_count": int(supports_result.graph_node_count),
                "graph_edge_count": int(supports_result.graph_edge_count),
                "stitch_query_count": int(supports_result.stitch_query_count),
                "stitch_candidates_total": int(supports_result.stitch_candidates_total),
                "stitch_reject_dist_count": int(supports_result.stitch_reject_dist_count),
                "stitch_reject_angle_count": int(supports_result.stitch_reject_angle_count),
                "stitch_reject_forward_count": int(supports_result.stitch_reject_forward_count),
                "stitch_accept_count": int(supports_result.stitch_accept_count),
                "stitch_levels_used_hist": dict(supports_result.stitch_levels_used_hist),
                "divstrip_missing": bool(divstrip_missing),
            },
        )

    points_xyz = _load_surface_points(patch_inputs, supports, params)
    gore_zone_metric = patch_inputs.divstrip_zone_metric
    if gore_zone_metric is not None:
        try:
            gore_zone_metric = gore_zone_metric.buffer(float(params["GORE_BUFFER_M"]))
        except Exception:
            gore_zone_metric = patch_inputs.divstrip_zone_metric

    road_lines_metric: list[LineString] = []
    road_feature_props: list[dict[str, Any]] = []
    road_records: list[dict[str, Any]] = []

    for pair, support in sorted(supports.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        src, dst = pair
        src_xsec = xsec_map.get(src)
        dst_xsec = xsec_map.get(dst)

        if src_xsec is None or dst_xsec is None:
            road = _make_base_road_record(
                src=src,
                dst=dst,
                support=support,
                src_type=node_type_map.get(src, "unknown"),
                dst_type=node_type_map.get(dst, "unknown"),
            )
            road["hard_anomaly"] = True
            road["hard_reasons"] = [HARD_CENTER_EMPTY]
            road["conf"] = compute_confidence(
                support_traj_count=int(road["support_traj_count"]),
                center_sample_coverage=0.0,
                max_turn_deg_per_10m=None,
                turn_limit_deg_per_10m=float(params["TURN_LIMIT_DEG_PER_10M"]),
                w1=float(params["CONF_W1_SUPPORT"]),
                w2=float(params["CONF_W2_COVERAGE"]),
                w3=float(params["CONF_W3_SMOOTH"]),
            )
            road["soft_issue_flags"] = []
            road["_geometry_metric"] = None
            road_records.append(road)
            hard_breakpoints.append(
                build_breakpoint(
                    road=road,
                    reason=HARD_CENTER_EMPTY,
                    severity="hard",
                    hint="cross_section_missing",
                )
            )
            continue

        src_type = node_type_map.get(src, "unknown")
        dst_type = node_type_map.get(dst, "unknown")

        center = estimate_centerline(
            support=support,
            src_xsec=src_xsec.geometry_metric,
            dst_xsec=dst_xsec.geometry_metric,
            src_type=src_type,
            dst_type=dst_type,
            src_out_degree=out_degree.get(src, 0),
            dst_in_degree=in_degree.get(dst, 0),
            lane_boundaries_metric=patch_inputs.lane_boundaries_metric,
            surface_points_xyz=points_xyz,
            center_sample_step_m=float(params["CENTER_SAMPLE_STEP_M"]),
            xsec_along_half_window_m=float(params["XSEC_ALONG_HALF_WINDOW_M"]),
            xsec_across_half_window_m=float(params["XSEC_ACROSS_HALF_WINDOW_M"]),
            xsec_min_points=int(params["XSEC_MIN_POINTS"]),
            width_pct_low=float(params["WIDTH_PCT_LOW"]),
            width_pct_high=float(params["WIDTH_PCT_HIGH"]),
            min_center_coverage=float(params["MIN_CENTER_COVERAGE"]),
            smooth_window_m=float(params["SMOOTH_WINDOW_M"]),
            corridor_half_width_m=float(params["CORRIDOR_HALF_WIDTH_M"]),
            offset_smooth_win_m_1=float(params["OFFSET_SMOOTH_WIN_M_1"]),
            offset_smooth_win_m_2=float(params["OFFSET_SMOOTH_WIN_M_2"]),
            max_offset_delta_per_step_m=float(params["MAX_OFFSET_DELTA_PER_STEP_M"]),
            simplify_tol_m=float(params["SIMPLIFY_TOL_M"]),
            stable_offset_m=float(params["STABLE_OFFSET_M"]),
            stable_margin_m=float(params["STABLE_OFFSET_MARGIN_M"]),
            endpoint_tol_m=float(params["ENDPOINT_ON_XSEC_TOL_M"]),
            road_max_vertices=int(params["ROAD_MAX_VERTICES"]),
            lb_snap_m=float(params["LB_SNAP_M"]),
            lb_start_end_topk=int(params["LB_START_END_TOPK"]),
            trend_fit_win_m=float(params["TREND_FIT_WIN_M"]),
            divstrip_zone_metric=gore_zone_metric,
            d_min=float(params["D_MIN"]),
            d_max=float(params["D_MAX"]),
            near_len=float(params["NEAR_LEN"]),
            base_from=float(params["BASE_FROM"]),
            base_to=float(params["BASE_TO"]),
            l_stable=float(params["L_STABLE"]),
            ratio_tol=float(params["RATIO_TOL"]),
            w_tol=float(params["W_TOL"]),
            r_gore=float(params["R_GORE"]),
            transition_m=float(params["TRANSITION_M"]),
            stable_fallback_m=float(params["STABLE_FALLBACK_M"]),
        )

        road = _make_base_road_record(src=src, dst=dst, support=support, src_type=src_type, dst_type=dst_type)
        road["stable_offset_m_src"] = center.stable_offset_m_src
        road["stable_offset_m_dst"] = center.stable_offset_m_dst
        road["center_sample_coverage"] = float(center.center_sample_coverage)
        road["width_med_m"] = center.width_med_m
        road["width_p90_m"] = center.width_p90_m
        road["max_turn_deg_per_10m"] = center.max_turn_deg_per_10m
        road["src_is_gore_tip"] = bool(center.src_is_gore_tip)
        road["dst_is_gore_tip"] = bool(center.dst_is_gore_tip)
        road["src_is_expanded"] = bool(center.src_is_expanded)
        road["dst_is_expanded"] = bool(center.dst_is_expanded)
        road["src_width_near_m"] = center.src_width_near_m
        road["dst_width_near_m"] = center.dst_width_near_m
        road["src_width_base_m"] = center.src_width_base_m
        road["dst_width_base_m"] = center.dst_width_base_m
        road["src_gore_overlap_near"] = center.src_gore_overlap_near
        road["dst_gore_overlap_near"] = center.dst_gore_overlap_near
        road["src_stable_s_m"] = center.src_stable_s_m
        road["dst_stable_s_m"] = center.dst_stable_s_m
        road["src_cut_mode"] = center.src_cut_mode
        road["dst_cut_mode"] = center.dst_cut_mode
        road["endpoint_tangent_deviation_deg_src"] = center.endpoint_tangent_deviation_deg_src
        road["endpoint_tangent_deviation_deg_dst"] = center.endpoint_tangent_deviation_deg_dst
        road["endpoint_center_offset_m_src"] = center.endpoint_center_offset_m_src
        road["endpoint_center_offset_m_dst"] = center.endpoint_center_offset_m_dst
        road["lb_path_found"] = bool(center.lb_path_found)
        road["lb_path_edge_count"] = int(center.lb_path_edge_count)

        soft_flags = set(center.soft_flags)
        hard_flags = set(center.hard_flags)

        if support.open_end:
            soft_flags.add(SOFT_OPEN_END)

        if int(road["support_traj_count"]) < int(params["MIN_SUPPORT_TRAJ"]):
            soft_flags.add(SOFT_LOW_SUPPORT)

        if center.center_sample_coverage < float(params["MIN_CENTER_COVERAGE"]):
            soft_flags.add(SOFT_SPARSE_POINTS)

        turn = center.max_turn_deg_per_10m
        if turn is not None and turn > float(params["TURN_LIMIT_DEG_PER_10M"]):
            soft_flags.add(SOFT_WIGGLY)

        if src == dst:
            hard_flags.add(HARD_CENTER_EMPTY)

        road_line = center.centerline_metric
        if road_line is not None:
            road["length_m"] = float(road_line.length)
            road["max_segment_m"] = compute_max_segment_m(road_line)
            seg_idx, seg_len = _max_segment_detail(road_line)
            road["max_segment_idx"] = seg_idx
            if seg_len is not None:
                road["max_segment_m"] = float(seg_len)
        else:
            road["length_m"] = 0.0
            road["max_segment_m"] = None
            road["max_segment_idx"] = None

        max_seg_m = road.get("max_segment_m")
        try:
            max_seg_f = float(max_seg_m)
        except Exception:
            max_seg_f = float("nan")
        if np.isfinite(max_seg_f) and max_seg_f > float(params["BRIDGE_MAX_SEG_M"]):
            hard_flags.add(HARD_BRIDGE_SEGMENT)

        if road_line is not None:
            traj_surface_info, traj_surface_soft, traj_surface_breakpoints = _eval_traj_surface_gate(
                road=road,
                road_line=road_line,
                shape_ref_line=center.shape_ref_metric,
                support=support,
                patch_inputs=patch_inputs,
                gore_zone_metric=gore_zone_metric,
                params=params,
            )
            road.update(traj_surface_info)
            soft_flags.update(traj_surface_soft)
            soft_breakpoints.extend(traj_surface_breakpoints)

        road["hard_anomaly"] = bool(hard_flags)
        road["hard_reasons"] = sorted(hard_flags)
        road["soft_issue_flags"] = sorted(soft_flags)
        road["_geometry_metric"] = road_line
        road["conf"] = compute_confidence(
            support_traj_count=int(road["support_traj_count"]),
            center_sample_coverage=float(road.get("center_sample_coverage") or 0.0),
            max_turn_deg_per_10m=road.get("max_turn_deg_per_10m"),
            turn_limit_deg_per_10m=float(params["TURN_LIMIT_DEG_PER_10M"]),
            w1=float(params["CONF_W1_SUPPORT"]),
            w2=float(params["CONF_W2_COVERAGE"]),
            w3=float(params["CONF_W3_SMOOTH"]),
        )

        road_records.append(road)
        if road_line is not None:
            road_lines_metric.append(road_line)
            road_feature_props.append(_strip_internal_fields(road))

        for reason in sorted(hard_flags):
            hint = _reason_hint(reason)
            if reason == HARD_BRIDGE_SEGMENT:
                hint = (
                    f"max_segment_m={road.get('max_segment_m')};"
                    f"seg_index={road.get('max_segment_idx')};"
                    f"threshold={float(params['BRIDGE_MAX_SEG_M']):.1f}"
                )
            bp = build_breakpoint(
                road=road,
                reason=reason,
                severity="hard",
                hint=hint,
            )
            if reason == HARD_BRIDGE_SEGMENT:
                bp["seg_index"] = road.get("max_segment_idx")
                bp["seg_length_m"] = road.get("max_segment_m")
                bp["max_segment_m"] = road.get("max_segment_m")
            hard_breakpoints.append(bp)

        existing_soft_reasons = {
            str(bp.get("reason"))
            for bp in soft_breakpoints
            if str(bp.get("road_id")) == str(road.get("road_id"))
        }
        for reason in sorted(soft_flags):
            if str(reason) in existing_soft_reasons:
                continue
            soft_breakpoints.append(
                build_breakpoint(
                    road=road,
                    reason=reason,
                    severity="soft",
                    hint=_reason_hint(reason),
                )
            )

    overall_pass = True
    if hard_breakpoints:
        overall_pass = False

    # Endpoint gate hard-check（对成功出图的路再次校验）
    for road in road_records:
        geom = road.get("_geometry_metric")
        if not isinstance(geom, LineString):
            continue
        src = int(road.get("src_nodeid"))
        dst = int(road.get("dst_nodeid"))
        src_x = xsec_map.get(src)
        dst_x = xsec_map.get(dst)
        if src_x is None or dst_x is None:
            overall_pass = False
            continue

        p0 = Point(geom.coords[0])
        p1 = Point(geom.coords[-1])
        d0 = float(p0.distance(src_x.geometry_metric))
        d1 = float(p1.distance(dst_x.geometry_metric))
        if d0 > float(params["ENDPOINT_ON_XSEC_TOL_M"]) or d1 > float(params["ENDPOINT_ON_XSEC_TOL_M"]):
            overall_pass = False

    endpoint_vals: list[float] = []
    endpoint_tangent_vals: list[float] = []
    gore_near_vals: list[float] = []
    width_near_minus_base_vals: list[float] = []
    max_segment_vals: list[float] = []
    traj_in_ratio_vals: list[float] = []
    traj_in_ratio_est_vals: list[float] = []
    traj_surface_enforced_count = 0
    traj_surface_insufficient_count = 0
    expanded_end_count = 0
    gore_tip_end_count = 0
    fallback_end_count = 0
    for road in road_records:
        for k in ("endpoint_center_offset_m_src", "endpoint_center_offset_m_dst"):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                continue
            if np.isfinite(fv):
                endpoint_vals.append(float(fv))
        for k in ("endpoint_tangent_deviation_deg_src", "endpoint_tangent_deviation_deg_dst"):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                continue
            if np.isfinite(fv):
                endpoint_tangent_vals.append(float(fv))
        for k in ("src_gore_overlap_near", "dst_gore_overlap_near"):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                continue
            if np.isfinite(fv):
                gore_near_vals.append(float(fv))
        for near_k, base_k in (
            ("src_width_near_m", "src_width_base_m"),
            ("dst_width_near_m", "dst_width_base_m"),
        ):
            near_v = road.get(near_k)
            base_v = road.get(base_k)
            try:
                near_f = float(near_v)
                base_f = float(base_v)
            except Exception:
                continue
            if np.isfinite(near_f) and np.isfinite(base_f):
                width_near_minus_base_vals.append(float(near_f - base_f))
        v_max_seg = road.get("max_segment_m")
        try:
            f_max_seg = float(v_max_seg)
        except Exception:
            f_max_seg = float("nan")
        if np.isfinite(f_max_seg):
            max_segment_vals.append(float(f_max_seg))
        v_ratio = road.get("traj_in_ratio")
        try:
            f_ratio = float(v_ratio)
        except Exception:
            f_ratio = float("nan")
        if np.isfinite(f_ratio):
            traj_in_ratio_vals.append(float(f_ratio))
        v_ratio_est = road.get("traj_in_ratio_est")
        try:
            f_ratio_est = float(v_ratio_est)
        except Exception:
            f_ratio_est = float("nan")
        if np.isfinite(f_ratio_est):
            traj_in_ratio_est_vals.append(float(f_ratio_est))
        if bool(road.get("traj_surface_enforced", False)):
            traj_surface_enforced_count += 1
        if SOFT_TRAJ_SURFACE_INSUFFICIENT in set(road.get("soft_issue_flags", [])):
            traj_surface_insufficient_count += 1
        if bool(road.get("src_is_expanded", False)):
            expanded_end_count += 1
        if bool(road.get("dst_is_expanded", False)):
            expanded_end_count += 1
        if bool(road.get("src_is_gore_tip", False)):
            gore_tip_end_count += 1
        if bool(road.get("dst_is_gore_tip", False)):
            gore_tip_end_count += 1
        if str(road.get("src_cut_mode", "")) == "fallback_50m":
            fallback_end_count += 1
        if str(road.get("dst_cut_mode", "")) == "fallback_50m":
            fallback_end_count += 1
    endpoint_arr = np.asarray(endpoint_vals, dtype=np.float64) if endpoint_vals else np.empty((0,), dtype=np.float64)
    endpoint_tangent_arr = (
        np.asarray(endpoint_tangent_vals, dtype=np.float64) if endpoint_tangent_vals else np.empty((0,), dtype=np.float64)
    )
    gore_near_arr = np.asarray(gore_near_vals, dtype=np.float64) if gore_near_vals else np.empty((0,), dtype=np.float64)
    width_delta_arr = (
        np.asarray(width_near_minus_base_vals, dtype=np.float64)
        if width_near_minus_base_vals
        else np.empty((0,), dtype=np.float64)
    )
    max_segment_arr = (
        np.asarray(max_segment_vals, dtype=np.float64) if max_segment_vals else np.empty((0,), dtype=np.float64)
    )
    traj_in_ratio_arr = (
        np.asarray(traj_in_ratio_vals, dtype=np.float64) if traj_in_ratio_vals else np.empty((0,), dtype=np.float64)
    )
    traj_in_ratio_est_arr = (
        np.asarray(traj_in_ratio_est_vals, dtype=np.float64)
        if traj_in_ratio_est_vals
        else np.empty((0,), dtype=np.float64)
    )

    return _finalize_payloads(
        run_id=run_id,
        repo_root=repo_root,
        patch_id=patch_inputs.patch_id,
        roads=road_records,
        road_lines_metric=road_lines_metric,
        road_feature_props=road_feature_props,
        hard_breakpoints=hard_breakpoints,
        soft_breakpoints=soft_breakpoints,
        params=params,
        overall_pass=overall_pass,
        extra_metrics={
            "crossing_raw_hit_count": int(cross_result.raw_hit_count),
            "crossing_dedup_drop_count": int(cross_result.dedup_drop_count),
            "n_cross_empty_skipped": int(cross_result.n_cross_empty_skipped),
            "n_cross_geom_unexpected": int(cross_result.n_cross_geom_unexpected),
            "n_cross_distance_gate_reject": int(cross_result.n_cross_distance_gate_reject),
            "stitch_candidate_count": int(supports_result.stitch_candidate_count),
            "stitch_edge_count": int(supports_result.stitch_edge_count),
            "graph_node_count": int(supports_result.graph_node_count),
            "graph_edge_count": int(supports_result.graph_edge_count),
            "stitch_query_count": int(supports_result.stitch_query_count),
            "stitch_candidates_total": int(supports_result.stitch_candidates_total),
            "stitch_reject_dist_count": int(supports_result.stitch_reject_dist_count),
            "stitch_reject_angle_count": int(supports_result.stitch_reject_angle_count),
            "stitch_reject_forward_count": int(supports_result.stitch_reject_forward_count),
            "stitch_accept_count": int(supports_result.stitch_accept_count),
            "stitch_levels_used_hist": dict(supports_result.stitch_levels_used_hist),
            "expanded_end_count": int(expanded_end_count),
            "gore_tip_end_count": int(gore_tip_end_count),
            "fallback_end_count": int(fallback_end_count),
            "divstrip_missing": bool(divstrip_missing),
            "endpoint_center_offset_p50": (
                float(np.percentile(endpoint_arr, 50.0)) if endpoint_arr.size > 0 else None
            ),
            "endpoint_center_offset_p90": (
                float(np.percentile(endpoint_arr, 90.0)) if endpoint_arr.size > 0 else None
            ),
            "endpoint_center_offset_max": (float(np.max(endpoint_arr)) if endpoint_arr.size > 0 else None),
            "gore_overlap_near_p50": (float(np.percentile(gore_near_arr, 50.0)) if gore_near_arr.size > 0 else None),
            "gore_overlap_near_p90": (float(np.percentile(gore_near_arr, 90.0)) if gore_near_arr.size > 0 else None),
            "gore_overlap_near_max": (float(np.max(gore_near_arr)) if gore_near_arr.size > 0 else None),
            "width_near_minus_base_p50": (
                float(np.percentile(width_delta_arr, 50.0)) if width_delta_arr.size > 0 else None
            ),
            "width_near_minus_base_p90": (
                float(np.percentile(width_delta_arr, 90.0)) if width_delta_arr.size > 0 else None
            ),
            "endpoint_tangent_deviation_deg_p50": (
                float(np.percentile(endpoint_tangent_arr, 50.0)) if endpoint_tangent_arr.size > 0 else None
            ),
            "endpoint_tangent_deviation_deg_p90": (
                float(np.percentile(endpoint_tangent_arr, 90.0)) if endpoint_tangent_arr.size > 0 else None
            ),
            "max_segment_m_p90": (float(np.percentile(max_segment_arr, 90.0)) if max_segment_arr.size > 0 else None),
            "max_segment_m_max": (float(np.max(max_segment_arr)) if max_segment_arr.size > 0 else None),
            "traj_surface_enforced_count": int(traj_surface_enforced_count),
            "traj_surface_insufficient_count": int(traj_surface_insufficient_count),
            "traj_in_ratio_p50": (float(np.percentile(traj_in_ratio_arr, 50.0)) if traj_in_ratio_arr.size > 0 else None),
            "traj_in_ratio_p90": (float(np.percentile(traj_in_ratio_arr, 90.0)) if traj_in_ratio_arr.size > 0 else None),
            "traj_in_ratio_est_p50": (
                float(np.percentile(traj_in_ratio_est_arr, 50.0)) if traj_in_ratio_est_arr.size > 0 else None
            ),
            "traj_in_ratio_est_p90": (
                float(np.percentile(traj_in_ratio_est_arr, 90.0)) if traj_in_ratio_est_arr.size > 0 else None
            ),
        },
    )


def _load_surface_points(
    patch_inputs: PatchInputs,
    supports: dict[tuple[int, int], PairSupport],
    params: dict[str, Any],
) -> np.ndarray:
    if patch_inputs.point_cloud_path is None:
        return np.empty((0, 3), dtype=np.float64)

    bbox = _support_union_bbox(patch_inputs, supports, margin_m=float(params["XSEC_ACROSS_HALF_WINDOW_M"]) + 5.0)
    if bbox is None:
        return np.empty((0, 3), dtype=np.float64)

    try:
        primary_cls = int(params.get("POINT_CLASS_PRIMARY", 2))
        allowed = (primary_cls,)
        fallback_any = bool(int(params.get("POINT_CLASS_FALLBACK_ANY", 0)))
        window = load_point_cloud_window(
            patch_inputs.point_cloud_path,
            bbox_metric=bbox,
            allowed_classes=allowed,
            fallback_to_any_class=fallback_any,
            max_points=900_000,
        )
        return window.xyz_metric
    except InputDataError:
        return np.empty((0, 3), dtype=np.float64)


def _support_union_bbox(
    patch_inputs: PatchInputs,
    supports: dict[tuple[int, int], PairSupport],
    *,
    margin_m: float,
) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []

    for cs in patch_inputs.intersection_lines:
        for x, y in cs.geometry_metric.coords:
            xs.append(float(x))
            ys.append(float(y))

    for support in supports.values():
        for seg in support.traj_segments[:6]:
            for x, y in seg.coords:
                xs.append(float(x))
                ys.append(float(y))

    if not xs:
        return None

    minx = min(xs) - margin_m
    maxx = max(xs) + margin_m
    miny = min(ys) - margin_m
    maxy = max(ys) + margin_m
    return (minx, miny, maxx, maxy)


def _unit_xy(vx: float, vy: float) -> tuple[float, float]:
    n = float(np.hypot(vx, vy))
    if n <= 1e-12:
        return (1.0, 0.0)
    return (float(vx / n), float(vy / n))


def _max_segment_detail(line: LineString) -> tuple[int | None, float | None]:
    if line.is_empty:
        return None, None
    coords = np.asarray(line.coords, dtype=np.float64)
    if coords.shape[0] < 2:
        return None, None
    seg = coords[1:, :] - coords[:-1, :]
    d = np.linalg.norm(seg, axis=1)
    if d.size == 0:
        return None, None
    idx = int(np.argmax(d))
    return idx, float(d[idx])


def _collect_support_traj_points(
    patch_inputs: PatchInputs,
    support: PairSupport,
) -> tuple[np.ndarray, int]:
    if not support.support_traj_ids:
        return np.empty((0, 2), dtype=np.float64), 0
    ids = {str(v) for v in support.support_traj_ids}
    pts: list[np.ndarray] = []
    used = 0
    for traj in patch_inputs.trajectories:
        if str(traj.traj_id) not in ids:
            continue
        xy = np.asarray(traj.xyz_metric[:, :2], dtype=np.float64)
        if xy.size == 0:
            continue
        finite = np.isfinite(xy[:, 0]) & np.isfinite(xy[:, 1])
        if np.count_nonzero(finite) < 2:
            continue
        pts.append(xy[finite, :])
        used += 1
    if not pts:
        return np.empty((0, 2), dtype=np.float64), 0
    return np.vstack(pts), int(used)


def _station_gap_intervals(
    stations: np.ndarray,
    valid_mask: np.ndarray,
) -> list[list[float]]:
    out: list[list[float]] = []
    n = int(stations.size)
    i = 0
    while i < n:
        if bool(valid_mask[i]):
            i += 1
            continue
        j = i
        while j + 1 < n and not bool(valid_mask[j + 1]):
            j += 1
        out.append([float(stations[i]), float(stations[j])])
        i = j + 1
    return out


def _eval_traj_surface_gate(
    *,
    road: dict[str, Any],
    road_line: LineString,
    shape_ref_line: LineString | None,
    support: PairSupport,
    patch_inputs: PatchInputs,
    gore_zone_metric: BaseGeometry | None,
    params: dict[str, Any],
) -> tuple[dict[str, Any], set[str], list[dict[str, Any]]]:
    result: dict[str, Any] = {
        "traj_surface_enforced": False,
        "traj_in_ratio": None,
        "traj_in_ratio_est": None,
        "endpoint_in_traj_surface_src": None,
        "endpoint_in_traj_surface_dst": None,
    }
    soft_flags: set[str] = set()
    breakpoints: list[dict[str, Any]] = []

    if road_line.is_empty or road_line.length <= 0:
        soft_flags.add(SOFT_TRAJ_SURFACE_INSUFFICIENT)
        breakpoints.append(
            build_breakpoint(
                road=road,
                reason=SOFT_TRAJ_SURFACE_INSUFFICIENT,
                severity="soft",
                hint="road_geometry_empty",
            )
        )
        return result, soft_flags, breakpoints

    ref_line = shape_ref_line if isinstance(shape_ref_line, LineString) and not shape_ref_line.is_empty else road_line
    ref_len = float(ref_line.length)
    if ref_len <= 1.0:
        soft_flags.add(SOFT_TRAJ_SURFACE_INSUFFICIENT)
        breakpoints.append(
            build_breakpoint(
                road=road,
                reason=SOFT_TRAJ_SURFACE_INSUFFICIENT,
                severity="soft",
                hint="shape_ref_too_short",
            )
        )
        return result, soft_flags, breakpoints

    traj_xy, unique_traj_count = _collect_support_traj_points(patch_inputs, support)
    if traj_xy.shape[0] < 8 or unique_traj_count <= 0:
        soft_flags.add(SOFT_TRAJ_SURFACE_INSUFFICIENT)
        breakpoints.append(
            build_breakpoint(
                road=road,
                reason=SOFT_TRAJ_SURFACE_INSUFFICIENT,
                severity="soft",
                hint="traj_points_insufficient",
            )
        )
        return result, soft_flags, breakpoints

    step = max(1.0, float(params["SURF_SLICE_STEP_M"]))
    half_win = max(0.5, float(params["SURF_SLICE_HALF_WIN_M"]))
    q_lo = max(0.0, min(0.5, float(params["SURF_QUANT_LOW"])))
    q_hi = max(0.5, min(1.0, float(params["SURF_QUANT_HIGH"])))
    if q_hi <= q_lo:
        q_lo, q_hi = 0.02, 0.98
    min_pts = max(3, int(params["TRAJ_SURF_MIN_POINTS_PER_SLICE"]))

    stations = np.arange(0.0, ref_len + step * 0.5, step, dtype=np.float64)
    if stations.size == 0 or abs(float(stations[-1]) - ref_len) > 1e-6:
        stations = np.concatenate((stations, np.asarray([ref_len], dtype=np.float64)))
    stations = np.unique(np.clip(stations, 0.0, ref_len))
    if stations.size < 2:
        soft_flags.add(SOFT_TRAJ_SURFACE_INSUFFICIENT)
        breakpoints.append(
            build_breakpoint(
                road=road,
                reason=SOFT_TRAJ_SURFACE_INSUFFICIENT,
                severity="soft",
                hint="slice_count_insufficient",
            )
        )
        return result, soft_flags, breakpoints

    left_pts: list[tuple[float, float]] = []
    right_pts: list[tuple[float, float]] = []
    valid_mask = np.zeros((stations.size,), dtype=bool)
    valid_stations: list[float] = []

    delta = min(2.0, max(0.5, step * 0.5))
    for i, s in enumerate(stations):
        p = ref_line.interpolate(float(s))
        p_xy = (float(p.x), float(p.y))
        p0 = ref_line.interpolate(max(0.0, float(s - delta)))
        p1 = ref_line.interpolate(min(ref_len, float(s + delta)))
        tx, ty = _unit_xy(float(p1.x - p0.x), float(p1.y - p0.y))
        nx, ny = (-ty, tx)

        rel = traj_xy - np.asarray([p_xy[0], p_xy[1]], dtype=np.float64)[None, :]
        along = rel[:, 0] * tx + rel[:, 1] * ty
        across = rel[:, 0] * nx + rel[:, 1] * ny
        keep = np.abs(along) <= half_win
        if gore_zone_metric is not None and np.any(keep):
            try:
                gore_mask = np.asarray(contains_xy(gore_zone_metric, traj_xy[:, 0], traj_xy[:, 1]), dtype=bool)
            except Exception:
                gore_mask = np.zeros((traj_xy.shape[0],), dtype=bool)
            keep = keep & (~gore_mask)
        if np.count_nonzero(keep) < min_pts:
            continue
        vals = across[keep]
        lo = float(np.quantile(vals, q_lo))
        hi = float(np.quantile(vals, q_hi))
        left_pts.append((float(p_xy[0] + nx * lo), float(p_xy[1] + ny * lo)))
        right_pts.append((float(p_xy[0] + nx * hi), float(p_xy[1] + ny * hi)))
        valid_mask[i] = True
        valid_stations.append(float(s))

    total_slices = int(stations.size)
    valid_slices = int(np.count_nonzero(valid_mask))
    slice_valid_ratio = float(valid_slices / max(1, total_slices))
    covered_len = (max(valid_stations) - min(valid_stations)) if len(valid_stations) >= 2 else 0.0
    covered_len_ratio = float(covered_len / max(ref_len, 1e-6))

    surface = None
    if len(left_pts) >= 2 and len(right_pts) >= 2:
        ring = [*left_pts, *reversed(right_pts)]
        if len(ring) >= 4:
            try:
                poly = Polygon(ring)
                if not poly.is_valid:
                    poly = poly.buffer(0)
            except Exception:
                poly = None
            if poly is not None and not poly.is_empty:
                try:
                    surface = poly.buffer(float(params["SURF_BUF_M"]))
                except Exception:
                    surface = poly
                if gore_zone_metric is not None and surface is not None and not surface.is_empty:
                    try:
                        surface = surface.difference(gore_zone_metric)
                    except Exception:
                        pass

    in_ratio_est = None
    endpoint_in_src = None
    endpoint_in_dst = None
    if surface is not None and not surface.is_empty:
        try:
            inter_len = float(road_line.intersection(surface).length)
        except Exception:
            inter_len = 0.0
        in_ratio_est = float(inter_len / max(1e-6, float(road_line.length)))
        p_src = Point(road_line.coords[0])
        p_dst = Point(road_line.coords[-1])
        endpoint_in_src = bool(surface.buffer(1e-6).contains(p_src))
        endpoint_in_dst = bool(surface.buffer(1e-6).contains(p_dst))

    min_slice_ratio = float(params["TRAJ_SURF_MIN_SLICE_VALID_RATIO"])
    min_cov_ratio = float(params["TRAJ_SURF_MIN_COVERED_LEN_RATIO"])
    min_unique = int(params["TRAJ_SURF_MIN_UNIQUE_TRAJ"])
    sufficient = (
        (valid_slices >= 2)
        and (slice_valid_ratio >= min_slice_ratio)
        and (covered_len_ratio >= min_cov_ratio)
        and (unique_traj_count >= min_unique)
        and (surface is not None and not surface.is_empty)
    )

    result["traj_in_ratio_est"] = in_ratio_est
    result["endpoint_in_traj_surface_src"] = endpoint_in_src
    result["endpoint_in_traj_surface_dst"] = endpoint_in_dst

    gaps = _station_gap_intervals(stations=stations, valid_mask=valid_mask)
    if gaps:
        soft_flags.add(SOFT_TRAJ_SURFACE_GAP)
        for rg in gaps[:3]:
            breakpoints.append(
                build_breakpoint(
                    road=road,
                    reason=SOFT_TRAJ_SURFACE_GAP,
                    severity="soft",
                    hint=f"gap_station={rg[0]:.1f}-{rg[1]:.1f}",
                    station_range_m=[float(rg[0]), float(rg[1])],
                )
            )

    if not sufficient:
        soft_flags.add(SOFT_TRAJ_SURFACE_INSUFFICIENT)
        reasons: list[str] = []
        if valid_slices < 2:
            reasons.append("valid_slices<2")
        if slice_valid_ratio < min_slice_ratio:
            reasons.append("slice_valid_ratio_low")
        if covered_len_ratio < min_cov_ratio:
            reasons.append("covered_len_ratio_low")
        if unique_traj_count < min_unique:
            reasons.append("unique_traj_low")
        if surface is None or surface.is_empty:
            reasons.append("surface_empty")
        bp = build_breakpoint(
            road=road,
            reason=SOFT_TRAJ_SURFACE_INSUFFICIENT,
            severity="soft",
            hint=(
                f"valid_slices={valid_slices}/{total_slices};"
                f"slice_valid_ratio={slice_valid_ratio:.3f};"
                f"covered_length_ratio={covered_len_ratio:.3f};"
                f"unique_traj_count={unique_traj_count};"
                f"reasons={','.join(reasons) if reasons else 'na'}"
            ),
        )
        bp["traj_surface_enforced"] = False
        bp["slice_valid_ratio"] = float(slice_valid_ratio)
        bp["covered_length_ratio"] = float(covered_len_ratio)
        bp["unique_traj_count"] = int(unique_traj_count)
        breakpoints.append(bp)
        return result, soft_flags, breakpoints

    result["traj_surface_enforced"] = True
    result["traj_in_ratio"] = in_ratio_est
    in_ratio_min = float(params["IN_RATIO_MIN"])
    pass_gate = (
        in_ratio_est is not None
        and float(in_ratio_est) >= in_ratio_min
        and bool(endpoint_in_src)
        and bool(endpoint_in_dst)
    )
    if not pass_gate:
        soft_flags.add(SOFT_ROAD_OUTSIDE_TRAJ_SURFACE)
        bp = build_breakpoint(
            road=road,
            reason=SOFT_ROAD_OUTSIDE_TRAJ_SURFACE,
            severity="soft",
            hint=(
                f"in_ratio={in_ratio_est if in_ratio_est is not None else 'na'};"
                f"endpoint_src={endpoint_in_src};endpoint_dst={endpoint_in_dst};"
                f"threshold={in_ratio_min:.2f}"
            ),
        )
        bp["traj_surface_enforced"] = True
        bp["traj_in_ratio"] = in_ratio_est
        breakpoints.append(bp)

    return result, soft_flags, breakpoints


def _as_float_list(value: Any, *, fallback: Sequence[float]) -> list[float]:
    if isinstance(value, (list, tuple)):
        out: list[float] = []
        for v in value:
            try:
                fv = float(v)
            except Exception:
                continue
            if np.isfinite(fv) and fv > 0:
                out.append(float(fv))
        if out:
            return out
    return [float(v) for v in fallback if np.isfinite(float(v)) and float(v) > 0]


def _build_cross_section_map(patch_inputs: PatchInputs) -> dict[int, Any]:
    out: dict[int, Any] = {}
    for cs in patch_inputs.intersection_lines:
        if cs.nodeid in out:
            if cs.geometry_metric.length > out[cs.nodeid].geometry_metric.length:
                out[cs.nodeid] = cs
        else:
            out[cs.nodeid] = cs
    return out


def _seed_node_type_map(*, node_ids: Sequence[int], node_kind_map: dict[int, int]) -> dict[int, str]:
    out: dict[int, str] = {int(n): "unknown" for n in node_ids}
    for nid, kind in node_kind_map.items():
        if kind & (1 << 4):
            out[int(nid)] = "diverge"
        elif kind & (1 << 3):
            out[int(nid)] = "merge"
        elif kind & (1 << 2):
            out[int(nid)] = "non_rc"
    return out


def _make_base_road_record(
    *,
    src: int,
    dst: int,
    support: PairSupport,
    src_type: str,
    dst_type: str,
) -> dict[str, Any]:
    repr_ids = list(support.repr_traj_ids)[:5]
    stitch_p50, stitch_p90, stitch_max = _stitch_stats(support.stitch_hops)
    return {
        "road_id": f"{src}_{dst}",
        "src_nodeid": int(src),
        "dst_nodeid": int(dst),
        "direction": f"{src}->{dst}",
        "length_m": 0.0,
        "support_traj_count": int(len(support.support_traj_ids)),
        "support_event_count": int(support.support_event_count),
        "src_type": src_type,
        "dst_type": dst_type,
        "stable_offset_m_src": None,
        "stable_offset_m_dst": None,
        "center_sample_coverage": 0.0,
        "endpoint_center_offset_m_src": None,
        "endpoint_center_offset_m_dst": None,
        "width_med_m": None,
        "width_p90_m": None,
        "max_turn_deg_per_10m": None,
        "src_is_gore_tip": False,
        "dst_is_gore_tip": False,
        "src_is_expanded": False,
        "dst_is_expanded": False,
        "src_width_near_m": None,
        "dst_width_near_m": None,
        "src_width_base_m": None,
        "dst_width_base_m": None,
        "src_gore_overlap_near": None,
        "dst_gore_overlap_near": None,
        "src_stable_s_m": None,
        "dst_stable_s_m": None,
        "src_cut_mode": "fallback_50m",
        "dst_cut_mode": "fallback_50m",
        "endpoint_tangent_deviation_deg_src": None,
        "endpoint_tangent_deviation_deg_dst": None,
        "max_segment_m": None,
        "traj_surface_enforced": False,
        "traj_in_ratio": None,
        "traj_in_ratio_est": None,
        "endpoint_in_traj_surface_src": None,
        "endpoint_in_traj_surface_dst": None,
        "lb_path_found": False,
        "lb_path_edge_count": 0,
        "repr_traj_ids": repr_ids,
        "stitch_hops_p50": stitch_p50,
        "stitch_hops_p90": stitch_p90,
        "stitch_hops_max": stitch_max,
        "cluster_count": int(support.cluster_count),
        "main_cluster_ratio": float(support.main_cluster_ratio),
        "cluster_sep_m_est": support.cluster_sep_m_est,
        "hard_anomaly": False,
        "hard_reasons": [],
        "soft_issue_flags": [],
        "conf": 0.0,
        "_geometry_metric": None,
    }


def _stitch_stats(values: Sequence[int]) -> tuple[int, int, int]:
    if not values:
        return (0, 0, 0)
    arr = np.asarray([int(v) for v in values], dtype=np.float64)
    p50 = int(round(float(np.percentile(arr, 50.0))))
    p90 = int(round(float(np.percentile(arr, 90.0))))
    vmax = int(round(float(np.max(arr))))
    return (p50, p90, vmax)


def _reason_hint(reason: str) -> str:
    hints = {
        HARD_MULTI_ROAD: "pair_has_multiple_channel_clusters",
        HARD_NON_RC: "non_rc_node_used_in_pair",
        HARD_CENTER_EMPTY: "centerline_generation_failed",
        HARD_ENDPOINT: "endpoints_not_on_intersection_l",
        HARD_BRIDGE_SEGMENT: "bridge_segment_too_long",
        SOFT_LOW_SUPPORT: "support_traj_count_below_threshold",
        SOFT_SPARSE_POINTS: "surface_points_coverage_low",
        SOFT_NO_LB: "lane_boundary_continuous_not_found",
        SOFT_NO_LB_PATH: "lane_boundary_graph_path_not_found",
        SOFT_WIGGLY: "turn_rate_exceeds_limit",
        SOFT_OPEN_END: "patch_boundary_open_end",
        SOFT_UNRESOLVED_NEIGHBOR: "stitch_graph_neighbor_unresolved",
        SOFT_NO_STABLE_SECTION: "stable_section_not_found_use_fallback",
        SOFT_DIVSTRIP_MISSING: "divstripzone_missing_gore_disabled",
        SOFT_ROAD_OUTSIDE_TRAJ_SURFACE: "road_outside_trajectory_surface",
        SOFT_TRAJ_SURFACE_INSUFFICIENT: "trajectory_surface_insufficient",
        SOFT_TRAJ_SURFACE_GAP: "trajectory_surface_gap",
        _SOFT_CROSS_EMPTY_SKIPPED: "cross_point_empty_skipped",
        _SOFT_CROSS_GEOM_UNEXPECTED: "cross_geometry_unexpected",
        _SOFT_CROSS_DISTANCE_GATE_REJECT: "cross_distance_gate_reject",
    }
    return hints.get(reason, "")


def _strip_internal_fields(road: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in road.items() if not k.startswith("_")}


def _finalize_payloads(
    *,
    run_id: str,
    repo_root: Path,
    patch_id: str,
    roads: list[dict[str, Any]],
    road_lines_metric: list[LineString],
    road_feature_props: list[dict[str, Any]],
    hard_breakpoints: list[dict[str, Any]],
    soft_breakpoints: list[dict[str, Any]],
    params: dict[str, Any],
    overall_pass: bool,
    extra_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    git_sha = git_short_sha(repo_root)
    digest = params_digest(params)

    metrics_payload = build_metrics_payload(
        patch_id=patch_id,
        roads=roads,
        hard_breakpoints=hard_breakpoints,
        soft_breakpoints=soft_breakpoints,
    )
    metrics_payload["params_digest"] = digest
    if extra_metrics:
        metrics_payload.update(extra_metrics)

    intervals_payload = build_intervals_payload(
        breakpoints=[*hard_breakpoints, *soft_breakpoints],
        topk=int(params["TOPK_INTERVALS"]),
    )

    gate_payload = build_gate_payload(
        overall_pass=overall_pass,
        hard_breakpoints=hard_breakpoints,
        soft_breakpoints=soft_breakpoints,
        params_digest_value=digest,
    )

    summary_params = {**params, "params_digest": digest}
    if extra_metrics:
        for k, v in extra_metrics.items():
            sk = str(k)
            if (
                sk.startswith("n_cross_")
                or sk.startswith("crossing_")
                or sk.startswith("stitch_")
                or sk.startswith("endpoint_center_offset_")
                or sk.startswith("endpoint_tangent_deviation_")
                or sk.startswith("gore_overlap_")
                or sk.startswith("max_segment_")
                or sk.startswith("traj_in_ratio")
                or sk.startswith("traj_surface_")
                or sk.startswith("width_near_minus_base_")
                or sk in {"expanded_end_count", "gore_tip_end_count", "fallback_end_count", "divstrip_missing"}
            ):
                summary_params[str(k)] = v

    summary_text = build_summary_text(
        run_id=run_id,
        git_sha=git_sha,
        patch_id=patch_id,
        overall_pass=overall_pass,
        roads=roads,
        hard_breakpoints=hard_breakpoints,
        soft_breakpoints=soft_breakpoints,
        params=summary_params,
    )

    return {
        "patch_id": patch_id,
        "road_count": len(road_feature_props),
        "road_candidate_count": len(roads),
        "road_properties": road_feature_props,
        "road_lines_metric": road_lines_metric,
        "metrics_payload": metrics_payload,
        "intervals_payload": intervals_payload,
        "gate_payload": gate_payload,
        "summary_text": summary_text,
        "hard_breakpoints": hard_breakpoints,
        "soft_breakpoints": soft_breakpoints,
        "overall_pass": overall_pass,
    }


def get_default_params() -> dict[str, Any]:
    return dict(DEFAULT_PARAMS)


__all__ = ["DEFAULT_PARAMS", "RunResult", "get_default_params", "run_patch"]
