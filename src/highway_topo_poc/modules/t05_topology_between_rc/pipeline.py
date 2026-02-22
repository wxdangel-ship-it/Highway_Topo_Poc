from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from shapely.geometry import LineString, Point

from .geometry import (
    HARD_CENTER_EMPTY,
    HARD_ENDPOINT,
    HARD_MULTI_ROAD,
    HARD_NON_RC,
    SOFT_LOW_SUPPORT,
    SOFT_NO_LB,
    SOFT_OPEN_END,
    SOFT_SPARSE_POINTS,
    SOFT_WIGGLY,
    PairSupport,
    build_pair_supports,
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
    metric_lines_to_input_crs,
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


DEFAULT_PARAMS: dict[str, float | int] = {
    "TRAJ_XSEC_HIT_BUFFER_M": 0.5,
    "TRAJ_XSEC_DEDUP_GAP_M": 2.0,
    "MIN_SUPPORT_TRAJ": 2,
    "STABLE_OFFSET_M": 50.0,
    "STABLE_OFFSET_MARGIN_M": 5.0,
    "CENTER_SAMPLE_STEP_M": 5.0,
    "XSEC_ALONG_HALF_WINDOW_M": 1.0,
    "XSEC_ACROSS_HALF_WINDOW_M": 30.0,
    "XSEC_MIN_POINTS": 200,
    "WIDTH_PCT_LOW": 5,
    "WIDTH_PCT_HIGH": 95,
    "MIN_CENTER_COVERAGE": 0.6,
    "SMOOTH_WINDOW_M": 25.0,
    "TURN_LIMIT_DEG_PER_10M": 30.0,
    "ENDPOINT_ON_XSEC_TOL_M": 1.0,
    "TOPK_INTERVALS": 20,
    "CONF_W1_SUPPORT": 0.4,
    "CONF_W2_COVERAGE": 0.4,
    "CONF_W3_SMOOTH": 0.2,
    "ROAD_MAX_VERTICES": 2000,
}

_POINT_CLOUD_ALLOWED_CLASSES = (2, 8, 9, 11)


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

    road_lines_input = metric_lines_to_input_crs(artifacts["road_lines_metric"], patch_inputs.projection_to_input)
    write_geojson_lines(
        patch_out / "Road.geojson",
        lines_input_crs=road_lines_input,
        properties_list=artifacts["road_properties"],
        crs_name=patch_inputs.projection.input_crs,
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

    events_by_traj = extract_crossing_events(
        patch_inputs.trajectories,
        list(xsec_map.values()),
        hit_buffer_m=float(params["TRAJ_XSEC_HIT_BUFFER_M"]),
        dedup_gap_m=float(params["TRAJ_XSEC_DEDUP_GAP_M"]),
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
        )

    supports_seed = build_pair_supports(
        patch_inputs.trajectories,
        events_by_traj,
        node_type_map=seed_type_map,
    )
    node_type_map, in_degree, out_degree = infer_node_types(
        node_ids=node_ids,
        pair_supports=supports_seed,
        node_kind_map=patch_inputs.node_kind_map,
    )
    supports = build_pair_supports(
        patch_inputs.trajectories,
        events_by_traj,
        node_type_map=node_type_map,
    )

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
        )

    points_xyz = _load_surface_points(patch_inputs, supports, params)

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
            stable_offset_m=float(params["STABLE_OFFSET_M"]),
            stable_margin_m=float(params["STABLE_OFFSET_MARGIN_M"]),
            endpoint_tol_m=float(params["ENDPOINT_ON_XSEC_TOL_M"]),
            road_max_vertices=int(params["ROAD_MAX_VERTICES"]),
        )

        road = _make_base_road_record(src=src, dst=dst, support=support, src_type=src_type, dst_type=dst_type)
        road["stable_offset_m_src"] = center.stable_offset_m_src
        road["stable_offset_m_dst"] = center.stable_offset_m_dst
        road["center_sample_coverage"] = float(center.center_sample_coverage)
        road["width_med_m"] = center.width_med_m
        road["width_p90_m"] = center.width_p90_m
        road["max_turn_deg_per_10m"] = center.max_turn_deg_per_10m

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
        else:
            road["length_m"] = 0.0

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
            hard_breakpoints.append(
                build_breakpoint(
                    road=road,
                    reason=reason,
                    severity="hard",
                    hint=_reason_hint(reason),
                )
            )

        for reason in sorted(soft_flags):
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
        window = load_point_cloud_window(
            patch_inputs.point_cloud_path,
            bbox_metric=bbox,
            allowed_classes=_POINT_CLOUD_ALLOWED_CLASSES,
            fallback_to_any_class=True,
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
        "width_med_m": None,
        "width_p90_m": None,
        "max_turn_deg_per_10m": None,
        "repr_traj_ids": repr_ids,
        "hard_anomaly": False,
        "hard_reasons": [],
        "soft_issue_flags": [],
        "conf": 0.0,
        "_geometry_metric": None,
    }


def _reason_hint(reason: str) -> str:
    hints = {
        HARD_MULTI_ROAD: "pair_has_multiple_channel_clusters",
        HARD_NON_RC: "non_rc_node_used_in_pair",
        HARD_CENTER_EMPTY: "centerline_generation_failed",
        HARD_ENDPOINT: "endpoints_not_on_intersection_l",
        SOFT_LOW_SUPPORT: "support_traj_count_below_threshold",
        SOFT_SPARSE_POINTS: "surface_points_coverage_low",
        SOFT_NO_LB: "lane_boundary_continuous_not_found",
        SOFT_WIGGLY: "turn_rate_exceeds_limit",
        SOFT_OPEN_END: "patch_boundary_open_end",
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

    summary_text = build_summary_text(
        run_id=run_id,
        git_sha=git_sha,
        patch_id=patch_id,
        overall_pass=overall_pass,
        roads=roads,
        hard_breakpoints=hard_breakpoints,
        soft_breakpoints=soft_breakpoints,
        params={**params, "params_digest": digest},
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


def get_default_params() -> dict[str, float | int]:
    return dict(DEFAULT_PARAMS)


__all__ = ["DEFAULT_PARAMS", "RunResult", "get_default_params", "run_patch"]
