from __future__ import annotations

import hashlib
import json
import math
import resource
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence

import numpy as np
from shapely import contains_xy, get_x, get_y, line_interpolate_point, line_locate_point, points
from shapely.geometry import LineString, MultiLineString, Point, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, polygonize, substring, unary_union

from .geometry import (
    HARD_BRIDGE_SEGMENT,
    HARD_CENTER_EMPTY,
    HARD_DIVSTRIP_INTERSECT,
    HARD_ENDPOINT,
    HARD_ENDPOINT_OFF_ANCHOR,
    HARD_ENDPOINT_LOCAL,
    HARD_MULTI_CORRIDOR,
    HARD_MULTI_ROAD,
    HARD_NO_STRATEGY_MERGE_TO_DIVERGE,
    HARD_NON_RC,
    HARD_ROAD_OUTSIDE_DRIVEZONE,
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
    _build_lb_graph_path,
    build_pair_supports,
    compute_max_segment_m,
    estimate_centerline,
    extract_crossing_events,
    infer_node_types,
    point_xy_safe,
)
from .io import (
    CrossSection,
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
_SOFT_ENDCAP_WIDTH_CLAMPED = "ENDCAP_WIDTH_CLAMPED"
_HARD_NO_ADJACENT_PAIR_AFTER_PASS2 = "NO_ADJACENT_PAIR_AFTER_PASS2"


DEFAULT_PARAMS: dict[str, Any] = {
    "TRAJ_XSEC_HIT_BUFFER_M": 0.5,
    "TRAJ_XSEC_DEDUP_GAP_M": 2.0,
    "PASS2_TRAJ_XSEC_HIT_BUFFER_M": 2.0,
    "MIN_SUPPORT_TRAJ": 2,
    "TRJ_SAMPLE_STEP_M": 2.0,
    "STITCH_TAIL_M": 30.0,
    "STITCH_MAX_DIST_LEVELS_M": [12.0, 25.0, 50.0],
    "STITCH_MAX_DIST_M": 12.0,
    "PASS2_STITCH_MAX_DIST_M": 50.0,
    "STITCH_MAX_ANGLE_DEG": 35.0,
    "STITCH_FORWARD_DOT_MIN": 0.0,
    "PASS2_STITCH_FORWARD_DOT_MIN": -0.2,
    "STITCH_MIN_ADVANCE_M": 5.0,
    "STITCH_PENALTY": 2.0,
    "STITCH_TOPK": 3,
    "NEIGHBOR_MAX_DIST_M": 2000.0,
    "PASS2_NEIGHBOR_MAX_DIST_M": 8000.0,
    "PASS2_UNRESOLVED_MIN_COUNT": 20,
    "PASS2_UNRESOLVED_PER_SUPPORT": 10.0,
    "PASS2_FORCE_WHEN_STITCH_ACCEPT_ZERO": 1,
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
    "LAMBDA_OUTSIDE": 5.0,
    "OUTSIDE_EDGE_RATIO_MAX": 0.2,
    "SURF_NODE_BUFFER_M": 2.0,
    "TREND_FIT_WIN_M": 20.0,
    "SURF_SLICE_STEP_M": 5.0,
    "SURF_SLICE_HALF_WIN_M": 2.0,
    "SURF_SLICE_HALF_WIN_LEVELS_M": [2.0, 5.0, 10.0],
    "AXIS_MAX_PROJECT_DIST_M": 20.0,
    "ENDCAP_M": 30.0,
    "ENDCAP_MIN_VALID_RATIO": 0.50,
    "ENDCAP_WIDTH_ABS_CAP_M": 40.0,
    "ENDCAP_WIDTH_REL_CAP": 2.0,
    "SURF_QUANT_LOW": 0.02,
    "SURF_QUANT_HIGH": 0.98,
    "SURF_BUF_M": 1.0,
    "IN_RATIO_MIN": 0.95,
    "TRAJ_SURF_ENFORCE_MIN_COVERED_LEN_RATIO": 0.90,
    "TRAJ_SURF_MIN_POINTS_PER_SLICE": 20,
    "TRAJ_SURF_MIN_SLICE_VALID_RATIO": 0.60,
    "TRAJ_SURF_MIN_COVERED_LEN_RATIO": 0.70,
    "TRAJ_SURF_MIN_UNIQUE_TRAJ": 2,
    "XSEC_ANCHOR_WINDOW_M": 15.0,
    "XSEC_ENDPOINT_MAX_DIST_M": 20.0,
    "XSEC_TRUNC_LMAX_M": 80.0,
    "XSEC_TRUNC_STEP_M": 1.0,
    "XSEC_TRUNC_NONPASS_K": 6,
    "XSEC_TRUNC_EVIDENCE_RADIUS_M": 1.0,
    "XSEC_GATE_EVIDENCE_MID_MARGIN_M": 8.0,
    "XSEC_GATE_EVIDENCE_MIN_LEN_M": 1.0,
    "XSEC_REF_HALF_LEN_M": 80.0,
    "XSEC_ROAD_SAMPLE_STEP_M": 1.0,
    "XSEC_ROAD_NONPASS_K": 6,
    "XSEC_ROAD_EVIDENCE_RADIUS_M": 1.0,
    "XSEC_ROAD_MIN_GROUND_PTS": 1,
    "XSEC_ROAD_MIN_TRAJ_PTS": 1,
    "XSEC_CORE_BAND_M": 20.0,
    "XSEC_SHIFT_STEP_M": 5.0,
    "XSEC_FALLBACK_SHORT_HALF_LEN_M": 15.0,
    "XSEC_BARRIER_MIN_NG_COUNT": 2,
    "XSEC_BARRIER_MIN_LEN_M": 4.0,
    "XSEC_BARRIER_ALONG_LEN_M": 60.0,
    "XSEC_BARRIER_ALONG_WIDTH_M": 2.5,
    "XSEC_BARRIER_BIN_STEP_M": 2.0,
    "XSEC_BARRIER_OCC_RATIO_MIN": 0.65,
    "XSEC_ENDCAP_WINDOW_M": 60.0,
    "XSEC_CASEB_PRE_M": 3.0,
    "STEP1_MULTI_CORRIDOR_DIST_M": 8.0,
    "STEP1_MULTI_CORRIDOR_MIN_RATIO": 0.60,
    "STEP1_MULTI_CORRIDOR_HARD": 0,
    "STEP1_DISABLE_PAIR_CLUSTER_WHEN_GATE": 1,
    "STEP1_GORE_NEAR_M": 30.0,
    "STEP1_TRAJ_IN_DRIVEZONE_MIN": 0.85,
    "STEP1_TRAJ_IN_DRIVEZONE_FALLBACK_MIN": 0.60,
    "STEP1_CORRIDOR_REACH_XSEC_M": 12.0,
    "TRAJ_SURF_ENDPOINT_HOLE_TOL_M": 2.0,
    "TRAJ_SURF_ENDPOINT_HOLE_IN_RATIO_MIN": 0.99,
    "ENDPOINT_ON_XSEC_TOL_M": 1.0,
    "TOPK_INTERVALS": 20,
    "CONF_W1_SUPPORT": 0.4,
    "CONF_W2_COVERAGE": 0.4,
    "CONF_W3_SMOOTH": 0.2,
    "ROAD_MAX_VERTICES": 2000,
    "POINTCLOUD_ENABLE": 0,
    "POINT_CLASS_PRIMARY": 2,
    "POINT_CLASS_FALLBACK_ANY": 0,
    "DRIVEZONE_SAMPLE_STEP_M": 2.0,
    "DEBUG_DUMP": 0,
    "DEBUG_LAYER_MAX_ITEMS": 2000,
    "XSEC_GATE_TRAJ_EVIDENCE_ENABLE": 1,
    "XSEC_GATE_TRAJ_EVIDENCE_MAX_POINTS": 300000,
    "XSEC_GATE_TRAJ_EVIDENCE_SAMPLE_STEP": 4,
    "XSEC_GATE_TRAJ_EVIDENCE_MAX_TRAJ": 300,
    "CACHE_ENABLED": 1,
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


class _StageTimer:
    def __init__(self) -> None:
        self.ms: dict[str, float] = {}

    def add(self, key: str, dt_ms: float) -> None:
        if not key:
            return
        self.ms[key] = float(self.ms.get(key, 0.0) + float(max(0.0, dt_ms)))

    def scope(self, key: str) -> "_StageTimerScope":
        return _StageTimerScope(self, key)


class _StageTimerScope:
    def __init__(self, timer: _StageTimer, key: str) -> None:
        self._timer = timer
        self._key = key
        self._t0 = 0.0

    def __enter__(self) -> None:
        self._t0 = perf_counter()
        return None

    def __exit__(self, exc_type, exc, tb) -> None:
        dt_ms = (perf_counter() - self._t0) * 1000.0
        self._timer.add(self._key, dt_ms)


def _max_rss_mb() -> float | None:
    try:
        rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception:
        return None
    if not math.isfinite(rss) or rss <= 0:
        return None
    return float(rss / 1024.0)


class _ProgressLogger:
    def __init__(self, path: Path | None) -> None:
        self.path = path

    def mark(self, stage: str, **extra: Any) -> None:
        p = self.path
        if p is None:
            return
        record: dict[str, Any] = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "stage": str(stage),
        }
        rss_mb = _max_rss_mb()
        if rss_mb is not None:
            record["rss_mb_max"] = float(round(rss_mb, 1))
        for k, v in extra.items():
            record[str(k)] = v
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=True, default=str) + "\n")
        except Exception:
            pass


class _DebugLayerBuffer(list[dict[str, Any]]):
    def __init__(self, *, max_items: int, seed: Sequence[dict[str, Any]] | None = None) -> None:
        super().__init__()
        self.max_items = int(max(0, int(max_items)))
        self.dropped_count = 0
        if seed:
            for item in seed:
                self.append(item)

    def append(self, item: dict[str, Any]) -> None:  # type: ignore[override]
        if self.max_items <= 0:
            self.dropped_count += 1
            return
        if len(self) >= self.max_items:
            self.dropped_count += 1
            return
        super().append(item)

    def extend(self, items: Sequence[dict[str, Any]]) -> None:  # type: ignore[override]
        for item in items:
            self.append(item)


def _normalize_support_clusters_for_xsec_gate(
    *,
    supports: dict[tuple[int, int], PairSupport],
    enabled: bool,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "step1_pair_cluster_disabled": False,
        "step1_pair_cluster_disabled_pair_count": 0,
        "step1_pair_cluster_disabled_event_count": 0,
        "step1_pair_cluster_disabled_hard_multi_removed_count": 0,
    }
    if not bool(enabled):
        return stats
    pair_count = 0
    event_count = 0
    removed_count = 0
    for support in supports.values():
        pair_count += 1
        n = int(max(0, int(support.support_event_count)))
        event_count += n
        if HARD_MULTI_ROAD in support.hard_anomalies:
            support.hard_anomalies.discard(HARD_MULTI_ROAD)
            removed_count += 1
        support.cluster_count = 1
        support.main_cluster_id = 0
        support.main_cluster_ratio = 1.0 if n > 0 else 0.0
        support.cluster_sep_m_est = None
        support.cluster_sizes = [int(n)] if n > 0 else []
        support.evidence_cluster_ids = [0 for _ in range(n)]
    stats["step1_pair_cluster_disabled"] = True
    stats["step1_pair_cluster_disabled_pair_count"] = int(pair_count)
    stats["step1_pair_cluster_disabled_event_count"] = int(event_count)
    stats["step1_pair_cluster_disabled_hard_multi_removed_count"] = int(removed_count)
    return stats


def _stable_json_digest(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:20]


def _geometry_hash(geom: BaseGeometry | None) -> str | None:
    if geom is None or geom.is_empty:
        return None
    try:
        return hashlib.sha1(bytes(geom.wkb)).hexdigest()[:20]
    except Exception:
        return None


def run_patch(
    *,
    data_root: str | Path,
    patch_id: str | None = None,
    run_id: str = "auto",
    out_root: str | Path = "outputs/_work/t05_topology_between_rc",
    params_override: dict[str, Any] | None = None,
) -> RunResult:
    repo_root = resolve_repo_root(Path.cwd())
    t0_load = perf_counter()
    patch_inputs = load_patch_inputs(data_root, patch_id)
    t_load_inputs_ms = (perf_counter() - t0_load) * 1000.0

    run_id_val = make_run_id("t05_topology_between_rc", repo_root=repo_root) if run_id == "auto" else str(run_id)

    out_dir = Path(out_root)
    if not out_dir.is_absolute():
        out_dir = (repo_root / out_dir).resolve()
    patch_out = out_dir / run_id_val / "patches" / patch_inputs.patch_id
    progress = _ProgressLogger(patch_out / "progress.ndjson")

    params = dict(DEFAULT_PARAMS)
    if params_override:
        params.update(params_override)
    progress.mark(
        "run_patch_start",
        run_id=run_id_val,
        patch_id=str(patch_inputs.patch_id),
        debug_dump=bool(int(params.get("DEBUG_DUMP", 0))),
        pointcloud_enable=bool(int(params.get("POINTCLOUD_ENABLE", 0))),
    )

    artifacts = _run_patch_core(
        patch_inputs,
        params=params,
        run_id=run_id_val,
        repo_root=repo_root,
        prefill_metrics={
            "t_load_traj": float(max(0.0, t_load_inputs_ms)),
        },
        progress=progress,
    )
    progress.mark("run_patch_core_done", road_count=int(artifacts.get("road_count", 0)))

    progress.mark("write_outputs_start")
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
    for rel_path, payload in dict(artifacts.get("debug_json_payloads", {})).items():
        write_json(patch_out / str(rel_path), payload)
    for rel_path, payload in dict(artifacts.get("debug_feature_collections", {})).items():
        write_json(patch_out / str(rel_path), payload)
    (patch_out / "summary.txt").write_text(str(artifacts["summary_text"]), encoding="utf-8")
    progress.mark(
        "run_patch_done",
        overall_pass=bool(artifacts.get("overall_pass", False)),
        hard_breakpoints=int(len(artifacts.get("hard_breakpoints", []))),
    )

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
    prefill_metrics: dict[str, Any] | None = None,
    progress: _ProgressLogger | None = None,
) -> dict[str, Any]:
    if progress is not None:
        progress.mark("core_start", patch_id=str(patch_inputs.patch_id))
    stage_timer = _StageTimer()
    if prefill_metrics:
        for k, v in dict(prefill_metrics).items():
            if str(k).startswith("t_"):
                stage_timer.add(str(k), float(v))

    pointcloud_stats: dict[str, Any] = {
        "pointcloud_enabled": bool(int(params.get("POINTCLOUD_ENABLE", 0))),
        "pointcloud_attempted": False,
        "pointcloud_cache_hit": False,
        "pointcloud_cache_key": None,
        "pointcloud_bbox_point_count": 0,
        "pointcloud_selected_point_count": 0,
        "pointcloud_non_ground_selected_point_count": 0,
        "pointcloud_usage_tags": [],
    }

    xsec_map = _build_cross_section_map(patch_inputs)
    node_ids = sorted(xsec_map.keys())
    if progress is not None:
        progress.mark("xsec_map_ready", node_count=int(len(node_ids)))

    hard_breakpoints: list[dict[str, Any]] = []
    soft_breakpoints: list[dict[str, Any]] = []
    surface_timing_per_k: dict[str, float] = {}
    shortest_timing_per_k: dict[str, float] = {}
    surface_cache_hit_count = 0
    surface_cache_miss_count = 0
    traj_points_cache: dict[tuple[str, ...], tuple[np.ndarray, int]] = {}
    divstrip_missing = patch_inputs.divstrip_source_path is None
    divstrip_geom_type = None
    divstrip_area_m2 = None
    divstrip_bounds_metric = None
    divstrip_src_crs = patch_inputs.input_summary.get("divstrip_src_crs")
    divstrip_crs_inferred = bool(patch_inputs.input_summary.get("divstrip_crs_inferred", False))
    drivezone_geom_type = None
    drivezone_area_m2 = None
    drivezone_bounds_metric = None
    drivezone_src_crs = patch_inputs.input_summary.get("drivezone_src_crs")
    drivezone_src_crs_before_alignment = patch_inputs.input_summary.get("drivezone_src_crs_before_alignment")
    drivezone_crs_alignment_reason = patch_inputs.input_summary.get("drivezone_crs_alignment_reason")
    drivezone_crs_reprojected = bool(patch_inputs.input_summary.get("drivezone_crs_reprojected", False))
    drivezone_crs_inferred = bool(patch_inputs.input_summary.get("drivezone_crs_inferred", False))
    intersection_src_crs = patch_inputs.input_summary.get("intersection_src_crs")
    intersection_crs_inferred = bool(patch_inputs.input_summary.get("intersection_crs_inferred", False))
    lane_boundary_used = bool(
        patch_inputs.input_summary.get("lane_boundary_used", bool(patch_inputs.lane_boundaries_metric))
    )
    lane_boundary_crs_inferred = bool(patch_inputs.input_summary.get("lane_boundary_crs_inferred", False))
    lane_boundary_crs_method = str(patch_inputs.input_summary.get("lane_boundary_crs_method") or "skipped")
    lane_boundary_src_crs_name = str(
        patch_inputs.input_summary.get("lane_boundary_src_crs_name")
        or patch_inputs.input_summary.get("lane_src_crs")
        or "EPSG:3857"
    )
    lane_boundary_crs_name_final = str(
        patch_inputs.input_summary.get("lane_boundary_crs_name_final")
        or patch_inputs.input_summary.get("lane_src_crs")
        or "EPSG:3857"
    )
    lane_boundary_skipped_reason = patch_inputs.input_summary.get("lane_boundary_skipped_reason")
    lane_boundary_debug_payloads: dict[str, dict[str, Any]] = {}
    if bool(int(params.get("DEBUG_DUMP", 0))):
        lane_crs_fix_raw = patch_inputs.input_summary.get("lane_boundary_crs_fix")
        if isinstance(lane_crs_fix_raw, dict) and lane_crs_fix_raw:
            lane_boundary_debug_payloads["debug/lane_boundary_crs_fix.json"] = dict(lane_crs_fix_raw)
    if patch_inputs.drivezone_zone_metric is not None and (not patch_inputs.drivezone_zone_metric.is_empty):
        drivezone_geom_type = str(getattr(patch_inputs.drivezone_zone_metric, "geom_type", ""))
        try:
            drivezone_area_m2 = float(patch_inputs.drivezone_zone_metric.area)
        except Exception:
            drivezone_area_m2 = None
        try:
            drivezone_bounds_metric = [float(v) for v in patch_inputs.drivezone_zone_metric.bounds]
        except Exception:
            drivezone_bounds_metric = None
    if patch_inputs.divstrip_zone_metric is not None and (not patch_inputs.divstrip_zone_metric.is_empty):
        divstrip_geom_type = str(getattr(patch_inputs.divstrip_zone_metric, "geom_type", ""))
        try:
            divstrip_area_m2 = float(patch_inputs.divstrip_zone_metric.area)
        except Exception:
            divstrip_area_m2 = None
        try:
            divstrip_bounds_metric = [float(v) for v in patch_inputs.divstrip_zone_metric.bounds]
        except Exception:
            divstrip_bounds_metric = None
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
    # IMPORTANT: cross-section slicing and step logic use raw DivStrip geometry.
    # Do not use buffered divstrip here, otherwise gates can be over-truncated
    # and drift to adjacent roads.
    gore_zone_metric_raw = patch_inputs.divstrip_zone_metric

    if progress is not None:
        progress.mark("xsec_truncate_start")
    (
        xsec_cross_map,
        xsec_anchor_debug_items,
        xsec_trunc_debug_items,
        xsec_gate_all_map,
        xsec_gate_meta_map,
        xsec_cross_stats,
    ) = _truncate_cross_sections_for_crossing(
        xsec_map=xsec_map,
        lane_boundaries_metric=patch_inputs.lane_boundaries_metric,
        trajectories=patch_inputs.trajectories,
        drivezone_zone_metric=patch_inputs.drivezone_zone_metric,
        gore_zone_metric=gore_zone_metric_raw,
        params=params,
    )
    if progress is not None:
        progress.mark(
            "xsec_truncate_done",
            xsec_cross_count=int(len(xsec_cross_map)),
            xsec_gate_enabled=bool(xsec_cross_stats.get("xsec_gate_enabled", False)),
        )
    pair_cluster_norm_stats: dict[str, Any] = {
        "step1_pair_cluster_disabled": False,
        "step1_pair_cluster_disabled_pair_count": 0,
        "step1_pair_cluster_disabled_event_count": 0,
        "step1_pair_cluster_disabled_hard_multi_removed_count": 0,
    }

    def _timing_extra_metrics() -> dict[str, Any]:
        required = (
            "t_load_traj",
            "t_load_pointcloud",
            "t_build_traj_projection",
            "t_build_surfaces_total",
            "t_build_lane_graph",
            "t_shortest_path_total",
            "t_centerline_offset",
            "t_gate_in_ratio",
            "t_debug_dump",
        )
        payload: dict[str, Any] = {}
        for k in required:
            payload[str(k)] = float(round(stage_timer.ms.get(str(k), 0.0), 3))
        payload["t_build_surfaces_per_k_ms"] = {k: float(round(v, 3)) for k, v in sorted(surface_timing_per_k.items())}
        payload["t_shortest_path_per_k_ms"] = {k: float(round(v, 3)) for k, v in sorted(shortest_timing_per_k.items())}
        payload["traj_surface_cache_hit_count"] = int(surface_cache_hit_count)
        payload["traj_surface_cache_miss_count"] = int(surface_cache_miss_count)
        payload.update(pointcloud_stats)
        payload["drivezone_src_crs"] = drivezone_src_crs
        payload["drivezone_src_crs_before_alignment"] = drivezone_src_crs_before_alignment
        payload["drivezone_crs_inferred"] = bool(drivezone_crs_inferred)
        payload["drivezone_crs_alignment_reason"] = drivezone_crs_alignment_reason
        payload["drivezone_crs_reprojected"] = bool(drivezone_crs_reprojected)
        payload["drivezone_metric_geom_type"] = drivezone_geom_type
        payload["drivezone_area_m2"] = drivezone_area_m2
        payload["drivezone_metric_bounds"] = drivezone_bounds_metric
        payload["drivezone_union_hash"] = _geometry_hash(patch_inputs.drivezone_zone_metric)
        payload["intersection_src_crs"] = intersection_src_crs
        payload["intersection_crs_inferred"] = bool(intersection_crs_inferred)
        payload["divstrip_crs_inferred"] = bool(divstrip_crs_inferred)
        payload["lane_boundary_used"] = bool(lane_boundary_used)
        payload["lane_boundary_crs_inferred"] = bool(lane_boundary_crs_inferred)
        payload["lane_boundary_crs_method"] = str(lane_boundary_crs_method)
        payload["lane_boundary_src_crs_name"] = str(lane_boundary_src_crs_name)
        payload["lane_boundary_crs_name_final"] = str(lane_boundary_crs_name_final)
        payload["lane_boundary_skipped_reason"] = lane_boundary_skipped_reason
        payload.update(xsec_cross_stats)
        payload.update(pair_cluster_norm_stats)
        return payload

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
        if progress is not None:
            progress.mark("early_exit_no_nodes")
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
            extra_metrics=_timing_extra_metrics(),
            debug_json_payloads=lane_boundary_debug_payloads,
        )

    # 先用 Node.Kind 建初值，再用图度数二次推断。
    seed_type_map = _seed_node_type_map(node_ids=node_ids, node_kind_map=patch_inputs.node_kind_map)
    def _append_cross_breakpoints(cross_result_obj: Any) -> None:
        if int(cross_result_obj.n_cross_empty_skipped) > 0:
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
                    "hint": f"n_cross_empty_skipped={int(cross_result_obj.n_cross_empty_skipped)}",
                }
            )
        if int(cross_result_obj.n_cross_geom_unexpected) > 0:
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
                    "hint": f"n_cross_geom_unexpected={int(cross_result_obj.n_cross_geom_unexpected)}",
                }
            )
        if int(cross_result_obj.n_cross_distance_gate_reject) > 0:
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
                    "hint": f"n_cross_distance_gate_reject={int(cross_result_obj.n_cross_distance_gate_reject)}",
                }
            )

    def _run_neighbor_pass(
        *,
        hit_buffer_m: float,
        stitch_max_dist_m: float,
        stitch_forward_dot_min: float,
        neighbor_max_dist_m: float,
    ) -> tuple[Any, Any, dict[int, str], dict[int, int], dict[int, int]]:
        cross_obj = extract_crossing_events(
            patch_inputs.trajectories,
            list(xsec_cross_map.values()),
            hit_buffer_m=float(hit_buffer_m),
            dedup_gap_m=float(params["TRAJ_XSEC_DEDUP_GAP_M"]),
        )
        levels = _as_float_list(
            params.get("STITCH_MAX_DIST_LEVELS_M"),
            fallback=[float(stitch_max_dist_m)],
        )
        if levels:
            levels[0] = float(stitch_max_dist_m)
        else:
            levels = [float(stitch_max_dist_m)]

        supports_seed_obj = build_pair_supports(
            patch_inputs.trajectories,
            cross_obj.events_by_traj,
            node_type_map=seed_type_map,
            trj_sample_step_m=float(params["TRJ_SAMPLE_STEP_M"]),
            stitch_tail_m=float(params["STITCH_TAIL_M"]),
            stitch_max_dist_levels_m=levels,
            stitch_max_dist_m=float(stitch_max_dist_m),
            stitch_max_angle_deg=float(params["STITCH_MAX_ANGLE_DEG"]),
            stitch_forward_dot_min=float(stitch_forward_dot_min),
            stitch_min_advance_m=float(params["STITCH_MIN_ADVANCE_M"]),
            stitch_penalty=float(params["STITCH_PENALTY"]),
            stitch_topk=int(params["STITCH_TOPK"]),
            neighbor_max_dist_m=float(neighbor_max_dist_m),
            multi_road_sep_m=float(params["MULTI_ROAD_SEP_M"]),
            multi_road_topn=int(params["MULTI_ROAD_TOPN"]),
        )
        nt_map, indeg_map, outdeg_map = infer_node_types(
            node_ids=node_ids,
            pair_supports=supports_seed_obj.supports,
            node_kind_map=patch_inputs.node_kind_map,
        )
        supports_obj = build_pair_supports(
            patch_inputs.trajectories,
            cross_obj.events_by_traj,
            node_type_map=nt_map,
            trj_sample_step_m=float(params["TRJ_SAMPLE_STEP_M"]),
            stitch_tail_m=float(params["STITCH_TAIL_M"]),
            stitch_max_dist_levels_m=levels,
            stitch_max_dist_m=float(stitch_max_dist_m),
            stitch_max_angle_deg=float(params["STITCH_MAX_ANGLE_DEG"]),
            stitch_forward_dot_min=float(stitch_forward_dot_min),
            stitch_min_advance_m=float(params["STITCH_MIN_ADVANCE_M"]),
            stitch_penalty=float(params["STITCH_PENALTY"]),
            stitch_topk=int(params["STITCH_TOPK"]),
            neighbor_max_dist_m=float(neighbor_max_dist_m),
            multi_road_sep_m=float(params["MULTI_ROAD_SEP_M"]),
            multi_road_topn=int(params["MULTI_ROAD_TOPN"]),
        )
        return cross_obj, supports_obj, nt_map, indeg_map, outdeg_map

    pass1_cross, pass1_supports, pass1_node_type_map, pass1_in_degree, pass1_out_degree = _run_neighbor_pass(
        hit_buffer_m=float(params["TRAJ_XSEC_HIT_BUFFER_M"]),
        stitch_max_dist_m=float(params["STITCH_MAX_DIST_M"]),
        stitch_forward_dot_min=float(params["STITCH_FORWARD_DOT_MIN"]),
        neighbor_max_dist_m=float(params["NEIGHBOR_MAX_DIST_M"]),
    )
    if progress is not None:
        progress.mark(
            "neighbor_pass1_done",
            pass1_pairs=int(len(pass1_supports.supports)),
            pass1_unresolved=int(len(pass1_supports.unresolved_events)),
            pass1_stitch_accept=int(pass1_supports.stitch_accept_count),
        )
    neighbor_search_pass = 1
    cross_result = pass1_cross
    supports_result = pass1_supports
    node_type_map = pass1_node_type_map
    in_degree = pass1_in_degree
    out_degree = pass1_out_degree

    pass1_pair_count = int(len(pass1_supports.supports))
    pass1_unresolved_count = int(len(pass1_supports.unresolved_events))
    pass1_stitch_accept_count = int(pass1_supports.stitch_accept_count)
    pass2_unresolved_min = int(max(1, int(params.get("PASS2_UNRESOLVED_MIN_COUNT", 20))))
    pass2_unresolved_per_support = float(max(1.0, float(params.get("PASS2_UNRESOLVED_PER_SUPPORT", 10.0))))
    pass2_force_when_no_stitch = bool(int(params.get("PASS2_FORCE_WHEN_STITCH_ACCEPT_ZERO", 1)))
    unresolved_trigger = pass1_unresolved_count >= max(
        pass2_unresolved_min,
        int(math.ceil(pass2_unresolved_per_support * max(1, pass1_pair_count))),
    )
    sparse_support_trigger = pass1_pair_count <= 1 and pass1_unresolved_count >= max(5, pass2_unresolved_min // 2)
    should_try_pass2 = (
        pass1_pair_count == 0
        or (
            pass2_force_when_no_stitch
            and pass1_stitch_accept_count <= 0
            and (unresolved_trigger or sparse_support_trigger)
        )
    )
    pass2_attempted = False

    if should_try_pass2:
        pass2_attempted = True
        if progress is not None:
            progress.mark("neighbor_pass2_start")
        pass2_cross, pass2_supports, pass2_node_type_map, pass2_in_degree, pass2_out_degree = _run_neighbor_pass(
            hit_buffer_m=float(params["PASS2_TRAJ_XSEC_HIT_BUFFER_M"]),
            stitch_max_dist_m=float(params["PASS2_STITCH_MAX_DIST_M"]),
            stitch_forward_dot_min=float(params["PASS2_STITCH_FORWARD_DOT_MIN"]),
            neighbor_max_dist_m=float(params["PASS2_NEIGHBOR_MAX_DIST_M"]),
        )
        if progress is not None:
            progress.mark(
                "neighbor_pass2_done",
                pass2_pairs=int(len(pass2_supports.supports)),
                pass2_unresolved=int(len(pass2_supports.unresolved_events)),
                pass2_stitch_accept=int(pass2_supports.stitch_accept_count),
            )

        def _supports_quality_key(res: PairSupportBuildResult) -> tuple[int, int, int, int]:
            pair_count = int(len(res.supports))
            support_events = int(sum(max(1, int(v.support_event_count)) for v in res.supports.values()))
            stitch_accept = int(max(0, int(res.stitch_accept_count)))
            unresolved_count = int(len(res.unresolved_events))
            return (pair_count, support_events, stitch_accept, -unresolved_count)

        if pass1_pair_count == 0 or _supports_quality_key(pass2_supports) > _supports_quality_key(pass1_supports):
            neighbor_search_pass = 2
            cross_result = pass2_cross
            supports_result = pass2_supports
            node_type_map = pass2_node_type_map
            in_degree = pass2_in_degree
            out_degree = pass2_out_degree

    _append_cross_breakpoints(cross_result)
    supports = supports_result.supports
    disable_pair_cluster = bool(int(params.get("STEP1_DISABLE_PAIR_CLUSTER_WHEN_GATE", 1))) and bool(
        xsec_cross_stats.get("xsec_gate_enabled", False)
    )
    pair_cluster_norm_stats = _normalize_support_clusters_for_xsec_gate(
        supports=supports,
        enabled=disable_pair_cluster,
    )
    for unresolved in supports_result.unresolved_events:
        soft_breakpoints.append(dict(unresolved))

    if not supports:
        hard_breakpoints.append(
            {
                "road_id": "na",
                "src_nodeid": None,
                "dst_nodeid": None,
                "reason": _HARD_NO_ADJACENT_PAIR_AFTER_PASS2 if int(neighbor_search_pass) == 2 else HARD_CENTER_EMPTY,
                "severity": "hard",
                "hint": (
                    "no_adjacent_pair_after_pass2"
                    if int(neighbor_search_pass) == 2
                    else "no_adjacent_pair_from_crossings"
                ),
            }
        )
        if progress is not None:
            progress.mark("early_exit_no_supports", neighbor_search_pass=int(neighbor_search_pass))
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
                "neighbor_search_pass": int(neighbor_search_pass),
                "neighbor_search_pass2_attempted": bool(pass2_attempted),
                "neighbor_search_pass2_used": bool(int(neighbor_search_pass) == 2),
                "divstrip_missing": bool(divstrip_missing),
                "divstrip_src_crs": divstrip_src_crs,
                "divstrip_metric_geom_type": divstrip_geom_type,
                "divstrip_metric_area_m2": divstrip_area_m2,
                "divstrip_metric_bounds": divstrip_bounds_metric,
                "drivezone_src_crs": drivezone_src_crs,
                "drivezone_metric_geom_type": drivezone_geom_type,
                "drivezone_area_m2": drivezone_area_m2,
                "drivezone_metric_bounds": drivezone_bounds_metric,
                "drivezone_union_hash": _geometry_hash(patch_inputs.drivezone_zone_metric),
                **_timing_extra_metrics(),
            },
            debug_json_payloads=lane_boundary_debug_payloads,
        )

    pointcloud_enabled = bool(int(params.get("POINTCLOUD_ENABLE", 0)))
    if progress is not None:
        progress.mark("surface_points_start", pointcloud_enabled=bool(pointcloud_enabled))
    with stage_timer.scope("t_load_pointcloud"):
        points_xyz, non_ground_xy, pointcloud_stats = _load_surface_points(
            patch_inputs,
            supports,
            params,
            use_pointcloud=pointcloud_enabled,
            with_non_ground=True,
        )
    if progress is not None:
        progress.mark(
            "surface_points_done",
            ground_points=int(points_xyz.shape[0]) if isinstance(points_xyz, np.ndarray) else None,
            non_ground_points=int(non_ground_xy.shape[0]) if isinstance(non_ground_xy, np.ndarray) else None,
        )
    gore_zone_metric = gore_zone_metric_raw

    road_lines_metric: list[LineString] = []
    road_feature_props: list[dict[str, Any]] = []
    road_records: list[dict[str, Any]] = []
    debug_enabled = bool(int(params.get("DEBUG_DUMP", 0)))
    debug_layer_max_items = int(max(0, int(params.get("DEBUG_LAYER_MAX_ITEMS", 2000))))

    def _mk_debug_layer(seed: Sequence[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if not debug_enabled:
            return []
        return _DebugLayerBuffer(max_items=debug_layer_max_items, seed=seed)

    debug_layers: dict[str, list[dict[str, Any]]] = {
        "traj_surface_best_polygon": _mk_debug_layer(),
        "traj_surface_best_boundary": _mk_debug_layer(),
        "lb_path_best": _mk_debug_layer(),
        "ref_axis_best": _mk_debug_layer(),
        "step1_corridor_centerline": _mk_debug_layer(),
        "step1_corridor_candidates": _mk_debug_layer(),
        "step1_support_trajs": _mk_debug_layer(),
        "step1_support_trajs_all": _mk_debug_layer(),
        "step1_seed_selected": _mk_debug_layer(),
        "xsec_gate_all_src": _mk_debug_layer(),
        "xsec_gate_all_dst": _mk_debug_layer(),
        "xsec_gate_selected_src": _mk_debug_layer(),
        "xsec_gate_selected_dst": _mk_debug_layer(),
        "step2_xsec_ref_src": _mk_debug_layer(),
        "step2_xsec_ref_dst": _mk_debug_layer(),
        "step2_xsec_ref_shifted_candidates_src": _mk_debug_layer(),
        "step2_xsec_ref_shifted_candidates_dst": _mk_debug_layer(),
        "step2_xsec_road_all_src": _mk_debug_layer(),
        "step2_xsec_road_all_dst": _mk_debug_layer(),
        "step2_xsec_road_selected_src": _mk_debug_layer(),
        "step2_xsec_road_selected_dst": _mk_debug_layer(),
        "step2_xsec_barrier_samples_src": _mk_debug_layer(),
        "step2_xsec_barrier_samples_dst": _mk_debug_layer(),
        "xsec_passable_samples_src": _mk_debug_layer(),
        "xsec_passable_samples_dst": _mk_debug_layer(),
        "step3_endpoint_src_dst": _mk_debug_layer(),
        "xsec_anchor_points": _mk_debug_layer(seed=list(xsec_anchor_debug_items)),
        "xsec_truncated": _mk_debug_layer(seed=list(xsec_trunc_debug_items)),
        "drivezone_union": _mk_debug_layer(),
        "xsec_valid_src": _mk_debug_layer(),
        "xsec_valid_dst": _mk_debug_layer(),
        "xsec_support_src": _mk_debug_layer(),
        "xsec_support_dst": _mk_debug_layer(),
        "xsec_ref_src": _mk_debug_layer(),
        "xsec_ref_dst": _mk_debug_layer(),
        "xsec_road_all_src": _mk_debug_layer(),
        "xsec_road_all_dst": _mk_debug_layer(),
        "xsec_road_selected_src": _mk_debug_layer(),
        "xsec_road_selected_dst": _mk_debug_layer(),
        "xsec_anchor_mid_src": _mk_debug_layer(),
        "xsec_anchor_mid_dst": _mk_debug_layer(),
        "xsec_target_selected_src": _mk_debug_layer(),
        "xsec_target_selected_dst": _mk_debug_layer(),
        "xsec_target_used_src": _mk_debug_layer(),
        "xsec_target_used_dst": _mk_debug_layer(),
        "endpoint_before_after": _mk_debug_layer(),
        "road_outside_segments": _mk_debug_layer(),
        "road_bridge_segments": _mk_debug_layer(),
        "road_divstrip_intersections": _mk_debug_layer(),
    }
    if debug_enabled and patch_inputs.drivezone_zone_metric is not None and (not patch_inputs.drivezone_zone_metric.is_empty):
        for poly in _iter_polygon_parts(patch_inputs.drivezone_zone_metric):
            debug_layers["drivezone_union"].append(
                {
                    "geometry": poly,
                    "properties": {
                        "patch_id": str(patch_inputs.patch_id),
                        "area_m2": float(poly.area),
                    },
                }
            )

    total_pairs = int(len(supports))
    if progress is not None:
        progress.mark("road_eval_start", total_pairs=total_pairs)
    for idx, (pair, support) in enumerate(sorted(supports.items(), key=lambda kv: (kv[0][0], kv[0][1])), start=1):
        if progress is not None and (idx == 1 or idx % 20 == 0 or idx == total_pairs):
            progress.mark("road_eval_progress", pair_index=int(idx), total_pairs=total_pairs)
        src, dst = pair
        src_xsec = xsec_map.get(src)
        dst_xsec = xsec_map.get(dst)
        src_xsec_gate = xsec_cross_map.get(src)
        dst_xsec_gate = xsec_cross_map.get(dst)
        src_gate_meta = xsec_gate_meta_map.get(int(src), {})
        dst_gate_meta = xsec_gate_meta_map.get(int(dst), {})

        if src_xsec is None or dst_xsec is None or src_xsec_gate is None or dst_xsec_gate is None:
            road = _make_base_road_record(
                src=src,
                dst=dst,
                support=support,
                src_type=node_type_map.get(src, "unknown"),
                dst_type=node_type_map.get(dst, "unknown"),
                neighbor_search_pass=int(neighbor_search_pass),
            )
            _apply_xsec_gate_meta_to_road(road=road, src_meta=src_gate_meta, dst_meta=dst_gate_meta)
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
                    hint="cross_section_missing_or_gate_missing",
                )
            )
            continue

        src_type = node_type_map.get(src, "unknown")
        dst_type = node_type_map.get(dst, "unknown")
        if debug_enabled:
            for ls in _iter_line_parts(xsec_gate_all_map.get(int(src))):
                debug_layers["xsec_gate_all_src"].append(
                    {
                        "geometry": ls,
                        "properties": {
                            "road_id": f"{src}_{dst}",
                            "nodeid": int(src),
                            "selected_by": src_gate_meta.get("selected_by"),
                            "fallback_flag": bool(src_gate_meta.get("fallback", False)),
                            "selected_mid_dist_m": src_gate_meta.get("selected_mid_dist_m"),
                            "selected_evidence_len_m": src_gate_meta.get("selected_evidence_len_m"),
                            "candidate_segment_count": src_gate_meta.get("candidate_segment_count"),
                        },
                    }
                )
            for ls in _iter_line_parts(xsec_gate_all_map.get(int(dst))):
                debug_layers["xsec_gate_all_dst"].append(
                    {
                        "geometry": ls,
                        "properties": {
                            "road_id": f"{src}_{dst}",
                            "nodeid": int(dst),
                            "selected_by": dst_gate_meta.get("selected_by"),
                            "fallback_flag": bool(dst_gate_meta.get("fallback", False)),
                            "selected_mid_dist_m": dst_gate_meta.get("selected_mid_dist_m"),
                            "selected_evidence_len_m": dst_gate_meta.get("selected_evidence_len_m"),
                            "candidate_segment_count": dst_gate_meta.get("candidate_segment_count"),
                        },
                    }
                )
            src_gate_cs = src_xsec_gate
            dst_gate_cs = dst_xsec_gate
            src_gate_geom = src_gate_cs.geometry_metric if src_gate_cs is not None else None
            dst_gate_geom = dst_gate_cs.geometry_metric if dst_gate_cs is not None else None
            for ls in _iter_line_parts(src_gate_geom):
                debug_layers["xsec_gate_selected_src"].append(
                    {
                        "geometry": ls,
                        "properties": {
                            "road_id": f"{src}_{dst}",
                            "nodeid": int(src),
                            "selected_by": src_gate_meta.get("selected_by"),
                            "fallback_flag": bool(src_gate_meta.get("fallback", False)),
                            "gate_len_m": src_gate_meta.get("len_m"),
                            "selected_mid_dist_m": src_gate_meta.get("selected_mid_dist_m"),
                            "selected_evidence_len_m": src_gate_meta.get("selected_evidence_len_m"),
                            "candidate_segment_count": src_gate_meta.get("candidate_segment_count"),
                        },
                    }
                )
            for ls in _iter_line_parts(dst_gate_geom):
                debug_layers["xsec_gate_selected_dst"].append(
                    {
                        "geometry": ls,
                        "properties": {
                            "road_id": f"{src}_{dst}",
                            "nodeid": int(dst),
                            "selected_by": dst_gate_meta.get("selected_by"),
                            "fallback_flag": bool(dst_gate_meta.get("fallback", False)),
                            "gate_len_m": dst_gate_meta.get("len_m"),
                            "selected_mid_dist_m": dst_gate_meta.get("selected_mid_dist_m"),
                            "selected_evidence_len_m": dst_gate_meta.get("selected_evidence_len_m"),
                            "candidate_segment_count": dst_gate_meta.get("candidate_segment_count"),
                        },
                    }
                )
        step1_corridor = _build_step1_corridor_for_pair(
            support=support,
            src_type=src_type,
            dst_type=dst_type,
            src_xsec=src_xsec_gate.geometry_metric,
            dst_xsec=dst_xsec_gate.geometry_metric,
            drivezone_zone_metric=patch_inputs.drivezone_zone_metric,
            gore_zone_metric=gore_zone_metric,
            params=params,
        )
        if debug_enabled:
            shape_ref_dbg = step1_corridor.get("shape_ref_line")
            if isinstance(shape_ref_dbg, LineString) and (not shape_ref_dbg.is_empty):
                debug_layers["step1_corridor_centerline"].append(
                    {
                        "geometry": shape_ref_dbg,
                        "properties": {
                            "road_id": f"{src}_{dst}",
                            "src_nodeid": int(src),
                            "dst_nodeid": int(dst),
                            "strategy": step1_corridor.get("strategy"),
                            "multi_corridor_detected": bool(step1_corridor.get("multi_corridor_detected", False)),
                            "multi_corridor_hint": step1_corridor.get("multi_corridor_hint"),
                        },
                    }
                )
            for cand in step1_corridor.get("corridor_candidates", []):
                if not isinstance(cand, dict):
                    continue
                geom = cand.get("geometry")
                if not isinstance(geom, LineString) or geom.is_empty:
                    continue
                debug_layers["step1_corridor_candidates"].append(
                    {
                        "geometry": geom,
                        "properties": {
                            "road_id": f"{src}_{dst}",
                            "corridor_id": cand.get("corridor_id"),
                            "start_traj_id": cand.get("start_traj_id"),
                            "length_m": cand.get("length_m"),
                            "reaches_other_end": cand.get("reaches_other_end"),
                            "inside_ratio": cand.get("inside_ratio"),
                            "drivezone_fallback_used": cand.get("drivezone_fallback_used"),
                        },
                    }
                )
            traj_flag_by_idx: dict[int, dict[str, Any]] = {}
            for item in step1_corridor.get("traj_gore_flags", []):
                if not isinstance(item, dict):
                    continue
                try:
                    idx = int(item.get("idx", -1))
                except Exception:
                    continue
                traj_flag_by_idx[idx] = item
            for i, seg in enumerate(support.traj_segments):
                if not isinstance(seg, LineString) or seg.is_empty:
                    continue
                tid = None
                if i < len(support.evidence_traj_ids):
                    tid = str(support.evidence_traj_ids[i])
                flag = traj_flag_by_idx.get(int(i), {})
                debug_layers["step1_support_trajs_all"].append(
                    {
                        "geometry": seg,
                        "properties": {
                            "road_id": f"{src}_{dst}",
                            "traj_id": tid,
                            "gore_fallback_used": bool(flag.get("constraint_violation", False)),
                            "gore_src_near": bool(flag.get("gore_src_near", False)),
                            "gore_dst_near": bool(flag.get("gore_dst_near", False)),
                            "gore_any": bool(flag.get("gore_any", False)),
                            "gore_intersection_m": float(flag.get("gore_intersection_m", 0.0)),
                            "inside_ratio": flag.get("inside_ratio"),
                            "dropped_by_drivezone": bool(flag.get("dropped_by_drivezone", False)),
                            "corridor_id": flag.get("corridor_id"),
                            "selected": bool(flag.get("selected", False)),
                        },
                    }
                )
                if flag.get("corridor_id") is None:
                    continue
                debug_layers["step1_support_trajs"].append(
                    {
                        "geometry": seg,
                        "properties": {
                            "road_id": f"{src}_{dst}",
                            "traj_id": tid,
                            "gore_fallback_used": bool(flag.get("constraint_violation", False)),
                            "gore_src_near": bool(flag.get("gore_src_near", False)),
                            "gore_dst_near": bool(flag.get("gore_dst_near", False)),
                            "gore_any": bool(flag.get("gore_any", False)),
                            "gore_intersection_m": float(flag.get("gore_intersection_m", 0.0)),
                            "inside_ratio": flag.get("inside_ratio"),
                            "dropped_by_drivezone": bool(flag.get("dropped_by_drivezone", False)),
                            "corridor_id": flag.get("corridor_id"),
                            "selected": bool(flag.get("selected", False)),
                        },
                    }
                )
            for tag, pt in (
                ("src", step1_corridor.get("cross_point_src")),
                ("dst", step1_corridor.get("cross_point_dst")),
            ):
                if isinstance(pt, Point) and not pt.is_empty:
                    debug_layers["step1_seed_selected"].append(
                        {
                            "geometry": pt,
                            "properties": {
                                "road_id": f"{src}_{dst}",
                                "endpoint_tag": tag,
                                "strategy": step1_corridor.get("strategy"),
                            },
                        }
                    )
        if step1_corridor.get("hard_reason"):
            road = _make_base_road_record(
                src=src,
                dst=dst,
                support=support,
                src_type=src_type,
                dst_type=dst_type,
                neighbor_search_pass=int(neighbor_search_pass),
            )
            _apply_xsec_gate_meta_to_road(road=road, src_meta=src_gate_meta, dst_meta=dst_gate_meta)
            road["step1_strategy"] = step1_corridor.get("strategy")
            road["step1_reason"] = step1_corridor.get("hard_reason")
            road["step1_corridor_count"] = step1_corridor.get("corridor_count")
            road["step1_main_corridor_ratio"] = step1_corridor.get("main_corridor_ratio")
            road["gore_fallback_used_src"] = bool(step1_corridor.get("gore_fallback_used_src", False))
            road["gore_fallback_used_dst"] = bool(step1_corridor.get("gore_fallback_used_dst", False))
            road["traj_drop_count_by_drivezone"] = int(step1_corridor.get("traj_drop_count_by_drivezone", 0))
            road["drivezone_fallback_used"] = bool(step1_corridor.get("drivezone_fallback_used", False))
            road["hard_anomaly"] = True
            road["hard_reasons"] = [str(step1_corridor.get("hard_reason"))]
            road["soft_issue_flags"] = []
            road["_geometry_metric"] = None
            road_records.append(road)
            hard_breakpoints.append(
                build_breakpoint(
                    road=road,
                    reason=str(step1_corridor.get("hard_reason")),
                    severity="hard",
                    hint=str(step1_corridor.get("hard_hint") or "step1_corridor_rejected"),
                )
            )
            continue
        cluster_ids = _select_cluster_candidates(support, max_clusters=3)
        candidate_roads: list[dict[str, Any]] = []
        cluster_inputs: list[tuple[int, PairSupport, dict[str, Any]]] = []
        for cluster_id in cluster_ids:
            support_k = _subset_support_by_cluster(support, cluster_id)
            if support_k is None or support_k.support_event_count <= 0:
                continue
            with stage_timer.scope("t_build_surfaces_total"):
                surface_hint = _build_traj_surface_hint_for_cluster(
                    support=support_k,
                    cluster_id=int(cluster_id),
                    src_xsec=src_xsec_gate.geometry_metric,
                    dst_xsec=dst_xsec_gate.geometry_metric,
                    lane_boundaries_metric=patch_inputs.lane_boundaries_metric,
                    patch_inputs=patch_inputs,
                    gore_zone_metric=gore_zone_metric,
                    params=params,
                    traj_points_cache=traj_points_cache,
                )
            stage_timer.add("t_build_traj_projection", float(surface_hint.get("timing_ms", 0.0)))
            key_k = f"{src}_{dst}_k{int(cluster_id)}"
            surface_timing_per_k[key_k] = float(surface_hint.get("timing_ms", 0.0))
            if bool(surface_hint.get("cache_hit", False)):
                surface_cache_hit_count += 1
            else:
                surface_cache_miss_count += 1
            cluster_inputs.append((int(cluster_id), support_k, surface_hint))

        heavy_inputs: list[tuple[int, PairSupport, dict[str, Any]]] = []
        ranked_inputs: list[tuple[float, int, tuple[int, PairSupport, dict[str, Any]]]] = []
        for cid, support_k, surface_hint in cluster_inputs:
            enforced = bool(surface_hint.get("traj_surface_enforced", False))
            surface_geom = surface_hint.get("surface_metric")
            support_ok = True
            if enforced and surface_geom is not None and (not surface_geom.is_empty):
                support_ok = _xsec_has_surface_support(
                    xsec=src_xsec_gate.geometry_metric,
                    gore_zone_metric=gore_zone_metric,
                    surface_metric=surface_geom,
                    buffer_m=float(params.get("SURF_NODE_BUFFER_M", 2.0)),
                ) and _xsec_has_surface_support(
                    xsec=dst_xsec_gate.geometry_metric,
                    gore_zone_metric=gore_zone_metric,
                    surface_metric=surface_geom,
                    buffer_m=float(params.get("SURF_NODE_BUFFER_M", 2.0)),
                )
            if support_ok:
                heavy_inputs.append((cid, support_k, surface_hint))
            coverage_score = (
                2.0 * float(surface_hint.get("slice_valid_ratio", 0.0))
                + float(surface_hint.get("covered_length_ratio", 0.0))
                + 0.2 * float(surface_hint.get("unique_traj_count", 0))
                + (0.5 if enforced else 0.0)
            )
            ranked_inputs.append((coverage_score, cid, (cid, support_k, surface_hint)))

        if not heavy_inputs and ranked_inputs:
            ranked_inputs.sort(key=lambda it: (-it[0], int(it[1])))
            heavy_inputs = [it[2] for it in ranked_inputs[:2]]

        for cluster_id, support_k, surface_hint in heavy_inputs:
            road_k = _evaluate_candidate_road(
                src=src,
                dst=dst,
                src_type=src_type,
                dst_type=dst_type,
                support=support_k,
                parent_support=support,
                cluster_id=int(cluster_id),
                neighbor_search_pass=int(neighbor_search_pass),
                src_out_degree=out_degree.get(src, 0),
                dst_in_degree=in_degree.get(dst, 0),
                lane_boundaries_metric=patch_inputs.lane_boundaries_metric,
                surface_points_xyz=points_xyz,
                non_ground_xy=non_ground_xy,
                patch_inputs=patch_inputs,
                gore_zone_metric=gore_zone_metric,
                params=params,
                traj_surface_hint=surface_hint,
                shape_ref_hint_metric=step1_corridor.get("shape_ref_line"),
                src_xsec=src_xsec_gate.geometry_metric,
                dst_xsec=dst_xsec_gate.geometry_metric,
            )
            _apply_xsec_gate_meta_to_road(road=road_k, src_meta=src_gate_meta, dst_meta=dst_gate_meta)
            road_k["step1_strategy"] = step1_corridor.get("strategy")
            road_k["step1_reason"] = step1_corridor.get("hard_reason")
            road_k["step1_corridor_count"] = step1_corridor.get("corridor_count")
            road_k["step1_main_corridor_ratio"] = step1_corridor.get("main_corridor_ratio")
            road_k["gore_fallback_used_src"] = bool(step1_corridor.get("gore_fallback_used_src", False))
            road_k["gore_fallback_used_dst"] = bool(step1_corridor.get("gore_fallback_used_dst", False))
            road_k["traj_drop_count_by_drivezone"] = int(step1_corridor.get("traj_drop_count_by_drivezone", 0))
            road_k["drivezone_fallback_used"] = bool(step1_corridor.get("drivezone_fallback_used", False))
            key_k = f"{src}_{dst}_k{int(cluster_id)}"
            stage_timer.add("t_build_lane_graph", float(road_k.get("_timing_lb_graph_ms", 0.0)))
            sp_ms = float(road_k.get("_timing_shortest_path_ms", 0.0))
            shortest_timing_per_k[key_k] = sp_ms
            stage_timer.add("t_shortest_path_total", sp_ms)
            stage_timer.add("t_centerline_offset", float(road_k.get("_timing_centerline_ms", 0.0)))
            stage_timer.add("t_gate_in_ratio", float(road_k.get("_timing_gate_ms", 0.0)))
            candidate_roads.append(road_k)

        if not candidate_roads:
            road = _make_base_road_record(
                src=src,
                dst=dst,
                support=support,
                src_type=src_type,
                dst_type=dst_type,
                neighbor_search_pass=int(neighbor_search_pass),
            )
            _apply_xsec_gate_meta_to_road(road=road, src_meta=src_gate_meta, dst_meta=dst_gate_meta)
            road["step1_strategy"] = step1_corridor.get("strategy")
            road["step1_reason"] = step1_corridor.get("hard_reason")
            road["step1_corridor_count"] = step1_corridor.get("corridor_count")
            road["step1_main_corridor_ratio"] = step1_corridor.get("main_corridor_ratio")
            road["gore_fallback_used_src"] = bool(step1_corridor.get("gore_fallback_used_src", False))
            road["gore_fallback_used_dst"] = bool(step1_corridor.get("gore_fallback_used_dst", False))
            road["traj_drop_count_by_drivezone"] = int(step1_corridor.get("traj_drop_count_by_drivezone", 0))
            road["drivezone_fallback_used"] = bool(step1_corridor.get("drivezone_fallback_used", False))
            road["hard_anomaly"] = True
            road["hard_reasons"] = [HARD_CENTER_EMPTY]
            road["soft_issue_flags"] = [SOFT_TRAJ_SURFACE_INSUFFICIENT]
            road["_geometry_metric"] = None
            road_records.append(road)
            hard_breakpoints.append(
                build_breakpoint(
                    road=road,
                    reason=HARD_CENTER_EMPTY,
                    severity="hard",
                    hint="cluster_candidate_empty",
                )
            )
            continue

        ranked_candidates = sorted(candidate_roads, key=_candidate_sort_key, reverse=True)
        selected = ranked_candidates[0]
        selected["chosen_cluster_id"] = int(selected.get("candidate_cluster_id", 0))
        selected["no_geometry_candidate"] = False
        selected["cluster_score_top2"] = [
            {
                "cluster_id": int(c.get("candidate_cluster_id", -1)),
                "score": float(c.get("_candidate_score", -1e9)),
                "feasible": bool(c.get("_candidate_feasible", False)),
                "has_geometry": bool(c.get("_candidate_has_geometry", False)),
                "in_ratio": _to_finite_float(c.get("_candidate_in_ratio"), 0.0),
                "max_segment_m": c.get("max_segment_m"),
                "endpoint_in_src": c.get("endpoint_in_traj_surface_src"),
                "endpoint_in_dst": c.get("endpoint_in_traj_surface_dst"),
                "covered_length_ratio": c.get("traj_surface_covered_length_ratio"),
            }
            for c in ranked_candidates[:2]
        ]
        road_line = selected.get("_geometry_metric")
        if not (isinstance(road_line, LineString) and (not road_line.is_empty)):
            selected["no_geometry_candidate"] = True
            sel_hard = set(selected.get("hard_reasons", []))
            sel_hard.add(HARD_CENTER_EMPTY)
            selected["hard_reasons"] = sorted(sel_hard)
            selected["hard_anomaly"] = True
        road_records.append(selected)
        if isinstance(road_line, LineString) and (not road_line.is_empty):
            road_lines_metric.append(road_line)
            road_feature_props.append(_strip_internal_fields(selected))

        for bp in selected.get("_candidate_hard_breakpoints", []):
            hard_breakpoints.append(dict(bp))
        for bp in selected.get("_candidate_soft_breakpoints", []):
            soft_breakpoints.append(dict(bp))

        hard_flags = set(selected.get("hard_reasons", []))
        soft_flags = set(selected.get("soft_issue_flags", []))
        existing_hard_reasons = {
            str(bp.get("reason"))
            for bp in hard_breakpoints
            if str(bp.get("road_id")) == str(selected.get("road_id"))
        }
        for reason in sorted(hard_flags):
            if str(reason) in existing_hard_reasons:
                continue
            hint = _reason_hint(reason)
            if reason == HARD_BRIDGE_SEGMENT:
                hint = (
                    f"max_segment_m={selected.get('max_segment_m')};"
                    f"seg_index={selected.get('max_segment_idx')};"
                    f"threshold={float(params['BRIDGE_MAX_SEG_M']):.1f};"
                    f"outside_ratio={selected.get('bridge_seg_outside_ratio')};"
                    f"intersects_divstrip={selected.get('bridge_seg_intersects_divstrip')}"
                )
            if reason == HARD_DIVSTRIP_INTERSECT:
                hint = f"divstrip_intersect_len_m={selected.get('divstrip_intersect_len_m')}"
            if reason == HARD_ENDPOINT_OFF_ANCHOR:
                hint = (
                    f"src_after={selected.get('endpoint_snap_dist_src_after_m')};"
                    f"dst_after={selected.get('endpoint_snap_dist_dst_after_m')}"
                )
            if reason == HARD_ROAD_OUTSIDE_DRIVEZONE:
                hint = (
                    f"outside_len_m={selected.get('road_outside_drivezone_len_m')};"
                    f"in_ratio={selected.get('road_in_drivezone_ratio')};"
                    f"endpoint_src={selected.get('endpoint_in_drivezone_src')};"
                    f"endpoint_dst={selected.get('endpoint_in_drivezone_dst')}"
                )
            bp = build_breakpoint(
                road=selected,
                reason=reason,
                severity="hard",
                hint=hint,
            )
            if reason == HARD_BRIDGE_SEGMENT:
                bp["seg_index"] = selected.get("max_segment_idx")
                bp["seg_length_m"] = selected.get("max_segment_m")
                bp["max_segment_m"] = selected.get("max_segment_m")
            if reason == HARD_DIVSTRIP_INTERSECT:
                bp["divstrip_intersect_len_m"] = selected.get("divstrip_intersect_len_m")
            if reason == HARD_ENDPOINT_OFF_ANCHOR:
                bp["endpoint_snap_dist_src_after_m"] = selected.get("endpoint_snap_dist_src_after_m")
                bp["endpoint_snap_dist_dst_after_m"] = selected.get("endpoint_snap_dist_dst_after_m")
            if reason == HARD_ROAD_OUTSIDE_DRIVEZONE:
                bp["road_outside_drivezone_len_m"] = selected.get("road_outside_drivezone_len_m")
                bp["road_in_drivezone_ratio"] = selected.get("road_in_drivezone_ratio")
                bp["endpoint_in_drivezone_src"] = selected.get("endpoint_in_drivezone_src")
                bp["endpoint_in_drivezone_dst"] = selected.get("endpoint_in_drivezone_dst")
            hard_breakpoints.append(bp)

        existing_soft_reasons = {
            str(bp.get("reason"))
            for bp in soft_breakpoints
            if str(bp.get("road_id")) == str(selected.get("road_id"))
        }
        for reason in sorted(soft_flags):
            if str(reason) in existing_soft_reasons:
                continue
            soft_breakpoints.append(
                build_breakpoint(
                    road=selected,
                    reason=reason,
                    severity="soft",
                    hint=_reason_hint(reason),
                )
            )

        if debug_enabled:
            with stage_timer.scope("t_debug_dump"):
                _collect_debug_layers_for_selected(
                    debug_layers=debug_layers,
                    road=selected,
                    src_xsec=src_xsec.geometry_metric,
                    dst_xsec=dst_xsec.geometry_metric,
                    gore_zone_metric=gore_zone_metric,
                    bridge_max_seg_m=float(params["BRIDGE_MAX_SEG_M"]),
                )

    overall_pass = True
    if hard_breakpoints:
        overall_pass = False

    # v6: intersection_l 作为锚点窗口，不再要求端点精确落线，仅做邻域诊断统计。
    endpoint_anchor_dist_vals: list[float] = []
    endpoint_anchor_max_dist = float(params.get("XSEC_ENDPOINT_MAX_DIST_M", 20.0))
    for road in road_records:
        geom = road.get("_geometry_metric")
        if not isinstance(geom, LineString):
            continue
        src = int(road.get("src_nodeid"))
        dst = int(road.get("dst_nodeid"))
        src_x = xsec_map.get(src)
        dst_x = xsec_map.get(dst)
        if src_x is None or dst_x is None:
            continue
        p0 = Point(geom.coords[0])
        p1 = Point(geom.coords[-1])
        d0 = float(p0.distance(src_x.geometry_metric))
        d1 = float(p1.distance(dst_x.geometry_metric))
        road["endpoint_anchor_dist_src_m"] = float(d0)
        road["endpoint_anchor_dist_dst_m"] = float(d1)
        if np.isfinite(d0):
            endpoint_anchor_dist_vals.append(float(d0))
        if np.isfinite(d1):
            endpoint_anchor_dist_vals.append(float(d1))
        # 仅在明显跑飞时标记总体失败（避免 intersection_l 精度误差造成误报）。
        if d0 > float(endpoint_anchor_max_dist) * 3.0 or d1 > float(endpoint_anchor_max_dist) * 3.0:
            overall_pass = False

    endpoint_vals: list[float] = []
    endpoint_snap_before_vals: list[float] = []
    endpoint_snap_after_vals: list[float] = []
    endpoint_xsec_dist_vals: list[float] = []
    endpoint_tangent_vals: list[float] = []
    gore_near_vals: list[float] = []
    width_near_minus_base_vals: list[float] = []
    max_segment_vals: list[float] = []
    seg0_vals: list[float] = []
    divstrip_intersect_vals: list[float] = []
    traj_surface_area_vals: list[float] = []
    traj_surface_cov_vals: list[float] = []
    traj_surface_valid_ratio_vals: list[float] = []
    traj_surface_covered_station_len_vals: list[float] = []
    endcap_valid_ratio_src_vals: list[float] = []
    endcap_valid_ratio_dst_vals: list[float] = []
    endcap_width_src_before_vals: list[float] = []
    endcap_width_src_after_vals: list[float] = []
    endcap_width_dst_before_vals: list[float] = []
    endcap_width_dst_after_vals: list[float] = []
    xsec_support_len_src_vals: list[float] = []
    xsec_support_len_dst_vals: list[float] = []
    offset_clamp_hit_vals: list[float] = []
    traj_in_ratio_vals: list[float] = []
    traj_in_ratio_est_vals: list[float] = []
    xsec_support_empty_reason_src_hist: dict[str, int] = {}
    xsec_support_empty_reason_dst_hist: dict[str, int] = {}
    endpoint_fallback_mode_src_hist: dict[str, int] = {}
    endpoint_fallback_mode_dst_hist: dict[str, int] = {}
    xsec_selected_by_src_hist: dict[str, int] = {}
    xsec_selected_by_dst_hist: dict[str, int] = {}
    xsec_shift_used_vals: list[float] = []
    xsec_mid_to_ref_vals: list[float] = []
    xsec_ref_intersection_n_vals: list[float] = []
    xsec_barrier_candidate_vals: list[float] = []
    xsec_barrier_final_vals: list[float] = []
    xsec_gate_len_src_vals: list[float] = []
    xsec_gate_len_dst_vals: list[float] = []
    xsec_gate_geom_type_src_hist: dict[str, int] = {}
    xsec_gate_geom_type_dst_hist: dict[str, int] = {}
    xsec_gate_fallback_src_count = 0
    xsec_gate_fallback_dst_count = 0
    traj_drop_count_by_drivezone_total = 0
    drivezone_fallback_used_count = 0
    step1_corridor_count_vals: list[float] = []
    step1_main_corridor_ratio_vals: list[float] = []
    xsec_samples_passable_ratio_src_vals: list[float] = []
    xsec_samples_passable_ratio_dst_vals: list[float] = []
    xsec_intersects_ref_true_count = 0
    xsec_intersects_ref_total = 0
    endpoint_in_drivezone_src_true = 0
    endpoint_in_drivezone_src_total = 0
    endpoint_in_drivezone_dst_true = 0
    endpoint_in_drivezone_dst_total = 0
    traj_surface_enforced_count = 0
    traj_surface_insufficient_count = 0
    road_outside_traj_surface_count = 0
    slice_half_hist_total: dict[str, int] = {}
    expanded_end_count = 0
    gore_tip_end_count = 0
    fallback_end_count = 0
    endcap_width_clamped_src_total = 0
    endcap_width_clamped_dst_total = 0
    offset_clamp_fallback_total = 0
    for road in road_records:
        for k in ("endpoint_center_offset_m_src", "endpoint_center_offset_m_dst"):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                continue
            if np.isfinite(fv):
                endpoint_vals.append(float(fv))
        for k in (
            "endpoint_snap_dist_src_before_m",
            "endpoint_snap_dist_dst_before_m",
        ):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                continue
            if np.isfinite(fv):
                endpoint_snap_before_vals.append(float(fv))
        for k in (
            "endpoint_snap_dist_src_after_m",
            "endpoint_snap_dist_dst_after_m",
        ):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                continue
            if np.isfinite(fv):
                endpoint_snap_after_vals.append(float(fv))
        for k in (
            "endpoint_dist_to_xsec_src_m",
            "endpoint_dist_to_xsec_dst_m",
        ):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                continue
            if np.isfinite(fv):
                endpoint_xsec_dist_vals.append(float(fv))
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
        v_seg0 = road.get("seg_index0_len_m")
        try:
            f_seg0 = float(v_seg0)
        except Exception:
            f_seg0 = float("nan")
        if np.isfinite(f_seg0):
            seg0_vals.append(float(f_seg0))
        v_div = road.get("divstrip_intersect_len_m")
        try:
            f_div = float(v_div)
        except Exception:
            f_div = float("nan")
        if np.isfinite(f_div):
            divstrip_intersect_vals.append(float(f_div))
        v_surf_area = road.get("traj_surface_area_m2")
        try:
            f_surf_area = float(v_surf_area)
        except Exception:
            f_surf_area = float("nan")
        if np.isfinite(f_surf_area):
            traj_surface_area_vals.append(float(f_surf_area))
        v_surf_cov = road.get("traj_surface_covered_length_ratio")
        try:
            f_surf_cov = float(v_surf_cov)
        except Exception:
            f_surf_cov = float("nan")
        if np.isfinite(f_surf_cov):
            traj_surface_cov_vals.append(float(f_surf_cov))
        v_surf_valid = road.get("traj_surface_valid_slices_ratio")
        try:
            f_surf_valid = float(v_surf_valid)
        except Exception:
            f_surf_valid = float("nan")
        if np.isfinite(f_surf_valid):
            traj_surface_valid_ratio_vals.append(float(f_surf_valid))
        v_cov_len_m = road.get("traj_surface_covered_station_length_m")
        try:
            f_cov_len_m = float(v_cov_len_m)
        except Exception:
            f_cov_len_m = float("nan")
        if np.isfinite(f_cov_len_m):
            traj_surface_covered_station_len_vals.append(float(f_cov_len_m))
        for k, target in (
            ("endcap_valid_ratio_src", endcap_valid_ratio_src_vals),
            ("endcap_valid_ratio_dst", endcap_valid_ratio_dst_vals),
            ("endcap_width_src_before_m", endcap_width_src_before_vals),
            ("endcap_width_src_after_m", endcap_width_src_after_vals),
            ("endcap_width_dst_before_m", endcap_width_dst_before_vals),
            ("endcap_width_dst_after_m", endcap_width_dst_after_vals),
            ("xsec_support_len_src", xsec_support_len_src_vals),
            ("xsec_support_len_dst", xsec_support_len_dst_vals),
        ):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                fv = float("nan")
            if np.isfinite(fv):
                target.append(float(fv))
        v_clamp = road.get("offset_clamp_hit_ratio")
        try:
            f_clamp = float(v_clamp)
        except Exception:
            f_clamp = float("nan")
        if np.isfinite(f_clamp):
            offset_clamp_hit_vals.append(float(f_clamp))
        try:
            offset_clamp_fallback_total += int(max(0, int(road.get("offset_clamp_fallback_count", 0) or 0)))
        except Exception:
            pass
        for key, target in (
            ("xsec_support_empty_reason_src", xsec_support_empty_reason_src_hist),
            ("xsec_support_empty_reason_dst", xsec_support_empty_reason_dst_hist),
            ("endpoint_fallback_mode_src", endpoint_fallback_mode_src_hist),
            ("endpoint_fallback_mode_dst", endpoint_fallback_mode_dst_hist),
        ):
            reason = str(road.get(key) or "").strip()
            if reason:
                target[reason] = int(target.get(reason, 0) + 1)
        for key, target in (
            ("xsec_road_selected_by_src", xsec_selected_by_src_hist),
            ("xsec_road_selected_by_dst", xsec_selected_by_dst_hist),
        ):
            reason = str(road.get(key) or "").strip()
            if reason:
                target[reason] = int(target.get(reason, 0) + 1)
        for k in (
            "xsec_shift_used_m_src",
            "xsec_shift_used_m_dst",
        ):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                fv = float("nan")
            if np.isfinite(fv):
                xsec_shift_used_vals.append(float(fv))
        for k in (
            "xsec_mid_to_ref_m_src",
            "xsec_mid_to_ref_m_dst",
        ):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                fv = float("nan")
            if np.isfinite(fv):
                xsec_mid_to_ref_vals.append(float(fv))
        for k in (
            "xsec_ref_intersection_n_src",
            "xsec_ref_intersection_n_dst",
            "xsec_barrier_candidate_count_src",
            "xsec_barrier_candidate_count_dst",
            "xsec_barrier_final_count_src",
            "xsec_barrier_final_count_dst",
        ):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                fv = float("nan")
            if not np.isfinite(fv):
                continue
            if "ref_intersection_n" in k:
                xsec_ref_intersection_n_vals.append(float(fv))
            elif "barrier_candidate_count" in k:
                xsec_barrier_candidate_vals.append(float(fv))
            elif "barrier_final_count" in k:
                xsec_barrier_final_vals.append(float(fv))
        for k, target in (
            ("xsec_gate_len_src_m", xsec_gate_len_src_vals),
            ("xsec_gate_len_dst_m", xsec_gate_len_dst_vals),
            ("step1_corridor_count", step1_corridor_count_vals),
            ("step1_main_corridor_ratio", step1_main_corridor_ratio_vals),
        ):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                fv = float("nan")
            if np.isfinite(fv):
                target.append(float(fv))
        gtype_src = str(road.get("xsec_gate_geom_type_src") or "").strip()
        if gtype_src:
            xsec_gate_geom_type_src_hist[gtype_src] = int(xsec_gate_geom_type_src_hist.get(gtype_src, 0) + 1)
        gtype_dst = str(road.get("xsec_gate_geom_type_dst") or "").strip()
        if gtype_dst:
            xsec_gate_geom_type_dst_hist[gtype_dst] = int(xsec_gate_geom_type_dst_hist.get(gtype_dst, 0) + 1)
        if road.get("xsec_gate_fallback_src") is True:
            xsec_gate_fallback_src_count += 1
        if road.get("xsec_gate_fallback_dst") is True:
            xsec_gate_fallback_dst_count += 1
        try:
            traj_drop_count_by_drivezone_total += int(max(0, int(road.get("traj_drop_count_by_drivezone", 0) or 0)))
        except Exception:
            pass
        if bool(road.get("drivezone_fallback_used", False)):
            drivezone_fallback_used_count += 1
        for k in ("xsec_intersects_ref_src", "xsec_intersects_ref_dst"):
            if road.get(k) is None:
                continue
            xsec_intersects_ref_total += 1
            if bool(road.get(k)):
                xsec_intersects_ref_true_count += 1
        for k, target in (
            ("xsec_samples_passable_ratio_src", xsec_samples_passable_ratio_src_vals),
            ("xsec_samples_passable_ratio_dst", xsec_samples_passable_ratio_dst_vals),
        ):
            v = road.get(k)
            try:
                fv = float(v)
            except Exception:
                fv = float("nan")
            if np.isfinite(fv):
                target.append(float(fv))
        src_drivezone_v = road.get("endpoint_in_drivezone_src")
        if src_drivezone_v is not None:
            endpoint_in_drivezone_src_total += 1
            if bool(src_drivezone_v):
                endpoint_in_drivezone_src_true += 1
        dst_drivezone_v = road.get("endpoint_in_drivezone_dst")
        if dst_drivezone_v is not None:
            endpoint_in_drivezone_dst_total += 1
            if bool(dst_drivezone_v):
                endpoint_in_drivezone_dst_true += 1
        try:
            endcap_width_clamped_src_total += int(max(0, int(road.get("endcap_width_clamped_src_count", 0) or 0)))
        except Exception:
            pass
        try:
            endcap_width_clamped_dst_total += int(max(0, int(road.get("endcap_width_clamped_dst_count", 0) or 0)))
        except Exception:
            pass
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
        if SOFT_ROAD_OUTSIDE_TRAJ_SURFACE in set(road.get("hard_reasons", [])):
            road_outside_traj_surface_count += 1
        hh = dict(road.get("traj_surface_slice_half_win_used_hist") or {})
        for k, v in hh.items():
            try:
                iv = int(v)
            except Exception:
                continue
            slice_half_hist_total[str(k)] = int(slice_half_hist_total.get(str(k), 0) + max(0, iv))
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
    endpoint_snap_before_arr = (
        np.asarray(endpoint_snap_before_vals, dtype=np.float64)
        if endpoint_snap_before_vals
        else np.empty((0,), dtype=np.float64)
    )
    endpoint_snap_after_arr = (
        np.asarray(endpoint_snap_after_vals, dtype=np.float64)
        if endpoint_snap_after_vals
        else np.empty((0,), dtype=np.float64)
    )
    endpoint_xsec_dist_arr = (
        np.asarray(endpoint_xsec_dist_vals, dtype=np.float64)
        if endpoint_xsec_dist_vals
        else np.empty((0,), dtype=np.float64)
    )
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
    seg0_arr = np.asarray(seg0_vals, dtype=np.float64) if seg0_vals else np.empty((0,), dtype=np.float64)
    divstrip_intersect_arr = (
        np.asarray(divstrip_intersect_vals, dtype=np.float64)
        if divstrip_intersect_vals
        else np.empty((0,), dtype=np.float64)
    )
    surf_area_arr = (
        np.asarray(traj_surface_area_vals, dtype=np.float64)
        if traj_surface_area_vals
        else np.empty((0,), dtype=np.float64)
    )
    surf_cov_arr = (
        np.asarray(traj_surface_cov_vals, dtype=np.float64)
        if traj_surface_cov_vals
        else np.empty((0,), dtype=np.float64)
    )
    surf_valid_arr = (
        np.asarray(traj_surface_valid_ratio_vals, dtype=np.float64)
        if traj_surface_valid_ratio_vals
        else np.empty((0,), dtype=np.float64)
    )
    surf_cov_len_arr = (
        np.asarray(traj_surface_covered_station_len_vals, dtype=np.float64)
        if traj_surface_covered_station_len_vals
        else np.empty((0,), dtype=np.float64)
    )
    endcap_valid_src_arr = (
        np.asarray(endcap_valid_ratio_src_vals, dtype=np.float64)
        if endcap_valid_ratio_src_vals
        else np.empty((0,), dtype=np.float64)
    )
    endcap_valid_dst_arr = (
        np.asarray(endcap_valid_ratio_dst_vals, dtype=np.float64)
        if endcap_valid_ratio_dst_vals
        else np.empty((0,), dtype=np.float64)
    )
    endcap_width_src_before_arr = (
        np.asarray(endcap_width_src_before_vals, dtype=np.float64)
        if endcap_width_src_before_vals
        else np.empty((0,), dtype=np.float64)
    )
    endcap_width_src_after_arr = (
        np.asarray(endcap_width_src_after_vals, dtype=np.float64)
        if endcap_width_src_after_vals
        else np.empty((0,), dtype=np.float64)
    )
    endcap_width_dst_before_arr = (
        np.asarray(endcap_width_dst_before_vals, dtype=np.float64)
        if endcap_width_dst_before_vals
        else np.empty((0,), dtype=np.float64)
    )
    endcap_width_dst_after_arr = (
        np.asarray(endcap_width_dst_after_vals, dtype=np.float64)
        if endcap_width_dst_after_vals
        else np.empty((0,), dtype=np.float64)
    )
    xsec_support_len_src_arr = (
        np.asarray(xsec_support_len_src_vals, dtype=np.float64)
        if xsec_support_len_src_vals
        else np.empty((0,), dtype=np.float64)
    )
    xsec_support_len_dst_arr = (
        np.asarray(xsec_support_len_dst_vals, dtype=np.float64)
        if xsec_support_len_dst_vals
        else np.empty((0,), dtype=np.float64)
    )
    offset_clamp_hit_arr = (
        np.asarray(offset_clamp_hit_vals, dtype=np.float64) if offset_clamp_hit_vals else np.empty((0,), dtype=np.float64)
    )
    endpoint_anchor_arr = (
        np.asarray(endpoint_anchor_dist_vals, dtype=np.float64)
        if endpoint_anchor_dist_vals
        else np.empty((0,), dtype=np.float64)
    )
    traj_in_ratio_arr = (
        np.asarray(traj_in_ratio_vals, dtype=np.float64) if traj_in_ratio_vals else np.empty((0,), dtype=np.float64)
    )
    traj_in_ratio_est_arr = (
        np.asarray(traj_in_ratio_est_vals, dtype=np.float64)
        if traj_in_ratio_est_vals
        else np.empty((0,), dtype=np.float64)
    )
    xsec_shift_used_arr = (
        np.asarray(xsec_shift_used_vals, dtype=np.float64) if xsec_shift_used_vals else np.empty((0,), dtype=np.float64)
    )
    xsec_mid_to_ref_arr = (
        np.asarray(xsec_mid_to_ref_vals, dtype=np.float64) if xsec_mid_to_ref_vals else np.empty((0,), dtype=np.float64)
    )
    xsec_ref_intersection_n_arr = (
        np.asarray(xsec_ref_intersection_n_vals, dtype=np.float64)
        if xsec_ref_intersection_n_vals
        else np.empty((0,), dtype=np.float64)
    )
    xsec_barrier_candidate_arr = (
        np.asarray(xsec_barrier_candidate_vals, dtype=np.float64)
        if xsec_barrier_candidate_vals
        else np.empty((0,), dtype=np.float64)
    )
    xsec_barrier_final_arr = (
        np.asarray(xsec_barrier_final_vals, dtype=np.float64)
        if xsec_barrier_final_vals
        else np.empty((0,), dtype=np.float64)
    )
    xsec_gate_len_src_arr = (
        np.asarray(xsec_gate_len_src_vals, dtype=np.float64) if xsec_gate_len_src_vals else np.empty((0,), dtype=np.float64)
    )
    xsec_gate_len_dst_arr = (
        np.asarray(xsec_gate_len_dst_vals, dtype=np.float64) if xsec_gate_len_dst_vals else np.empty((0,), dtype=np.float64)
    )
    step1_corridor_count_arr = (
        np.asarray(step1_corridor_count_vals, dtype=np.float64)
        if step1_corridor_count_vals
        else np.empty((0,), dtype=np.float64)
    )
    step1_main_corridor_ratio_arr = (
        np.asarray(step1_main_corridor_ratio_vals, dtype=np.float64)
        if step1_main_corridor_ratio_vals
        else np.empty((0,), dtype=np.float64)
    )
    xsec_samples_passable_ratio_src_arr = (
        np.asarray(xsec_samples_passable_ratio_src_vals, dtype=np.float64)
        if xsec_samples_passable_ratio_src_vals
        else np.empty((0,), dtype=np.float64)
    )
    xsec_samples_passable_ratio_dst_arr = (
        np.asarray(xsec_samples_passable_ratio_dst_vals, dtype=np.float64)
        if xsec_samples_passable_ratio_dst_vals
        else np.empty((0,), dtype=np.float64)
    )

    if progress is not None:
        progress.mark("core_finalize_start", road_candidates=int(len(road_records)))
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
        debug_layers=debug_layers,
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
            "neighbor_search_pass2_attempted": bool(pass2_attempted),
            "expanded_end_count": int(expanded_end_count),
            "gore_tip_end_count": int(gore_tip_end_count),
            "fallback_end_count": int(fallback_end_count),
            "divstrip_missing": bool(divstrip_missing),
            "divstrip_src_crs": divstrip_src_crs,
            "divstrip_metric_geom_type": divstrip_geom_type,
            "divstrip_metric_area_m2": divstrip_area_m2,
            "divstrip_metric_bounds": divstrip_bounds_metric,
            "drivezone_src_crs": drivezone_src_crs,
            "drivezone_metric_geom_type": drivezone_geom_type,
            "drivezone_area_m2": drivezone_area_m2,
            "drivezone_metric_bounds": drivezone_bounds_metric,
            "drivezone_union_hash": _geometry_hash(patch_inputs.drivezone_zone_metric),
            "endpoint_center_offset_p50": (
                float(np.percentile(endpoint_arr, 50.0)) if endpoint_arr.size > 0 else None
            ),
            "endpoint_center_offset_p90": (
                float(np.percentile(endpoint_arr, 90.0)) if endpoint_arr.size > 0 else None
            ),
            "endpoint_center_offset_max": (float(np.max(endpoint_arr)) if endpoint_arr.size > 0 else None),
            "endpoint_snap_dist_before_p90": (
                float(np.percentile(endpoint_snap_before_arr, 90.0))
                if endpoint_snap_before_arr.size > 0
                else None
            ),
            "endpoint_snap_dist_after_p90": (
                float(np.percentile(endpoint_snap_after_arr, 90.0))
                if endpoint_snap_after_arr.size > 0
                else None
            ),
            "endpoint_dist_to_xsec_p90": (
                float(np.percentile(endpoint_xsec_dist_arr, 90.0))
                if endpoint_xsec_dist_arr.size > 0
                else None
            ),
            "endpoint_dist_to_xsec_max": (
                float(np.max(endpoint_xsec_dist_arr)) if endpoint_xsec_dist_arr.size > 0 else None
            ),
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
            "seg_index0_len_m_p90": (float(np.percentile(seg0_arr, 90.0)) if seg0_arr.size > 0 else None),
            "seg_index0_len_m_max": (float(np.max(seg0_arr)) if seg0_arr.size > 0 else None),
            "divstrip_intersect_len_m_p90": (
                float(np.percentile(divstrip_intersect_arr, 90.0)) if divstrip_intersect_arr.size > 0 else None
            ),
            "divstrip_intersect_len_m_max": (
                float(np.max(divstrip_intersect_arr)) if divstrip_intersect_arr.size > 0 else None
            ),
            "traj_surface_area_m2_p50": (
                float(np.percentile(surf_area_arr, 50.0)) if surf_area_arr.size > 0 else None
            ),
            "traj_surface_area_m2_p90": (
                float(np.percentile(surf_area_arr, 90.0)) if surf_area_arr.size > 0 else None
            ),
            "traj_surface_covered_length_ratio_p50": (
                float(np.percentile(surf_cov_arr, 50.0)) if surf_cov_arr.size > 0 else None
            ),
            "traj_surface_covered_length_ratio_p90": (
                float(np.percentile(surf_cov_arr, 90.0)) if surf_cov_arr.size > 0 else None
            ),
            "traj_surface_covered_station_length_m_p50": (
                float(np.percentile(surf_cov_len_arr, 50.0)) if surf_cov_len_arr.size > 0 else None
            ),
            "traj_surface_covered_station_length_m_p90": (
                float(np.percentile(surf_cov_len_arr, 90.0)) if surf_cov_len_arr.size > 0 else None
            ),
            "traj_surface_valid_slices_ratio_p50": (
                float(np.percentile(surf_valid_arr, 50.0)) if surf_valid_arr.size > 0 else None
            ),
            "traj_surface_valid_slices_ratio_p90": (
                float(np.percentile(surf_valid_arr, 90.0)) if surf_valid_arr.size > 0 else None
            ),
            "endcap_valid_ratio_src_p50": (
                float(np.percentile(endcap_valid_src_arr, 50.0)) if endcap_valid_src_arr.size > 0 else None
            ),
            "endcap_valid_ratio_src_p90": (
                float(np.percentile(endcap_valid_src_arr, 90.0)) if endcap_valid_src_arr.size > 0 else None
            ),
            "endcap_valid_ratio_dst_p50": (
                float(np.percentile(endcap_valid_dst_arr, 50.0)) if endcap_valid_dst_arr.size > 0 else None
            ),
            "endcap_valid_ratio_dst_p90": (
                float(np.percentile(endcap_valid_dst_arr, 90.0)) if endcap_valid_dst_arr.size > 0 else None
            ),
            "endcap_width_src_before_m_p90": (
                float(np.percentile(endcap_width_src_before_arr, 90.0))
                if endcap_width_src_before_arr.size > 0
                else None
            ),
            "endcap_width_src_after_m_p90": (
                float(np.percentile(endcap_width_src_after_arr, 90.0))
                if endcap_width_src_after_arr.size > 0
                else None
            ),
            "endcap_width_dst_before_m_p90": (
                float(np.percentile(endcap_width_dst_before_arr, 90.0))
                if endcap_width_dst_before_arr.size > 0
                else None
            ),
            "endcap_width_dst_after_m_p90": (
                float(np.percentile(endcap_width_dst_after_arr, 90.0))
                if endcap_width_dst_after_arr.size > 0
                else None
            ),
            "endcap_width_clamped_src_total": int(endcap_width_clamped_src_total),
            "endcap_width_clamped_dst_total": int(endcap_width_clamped_dst_total),
            "xsec_support_len_src_p90": (
                float(np.percentile(xsec_support_len_src_arr, 90.0)) if xsec_support_len_src_arr.size > 0 else None
            ),
            "xsec_support_len_dst_p90": (
                float(np.percentile(xsec_support_len_dst_arr, 90.0)) if xsec_support_len_dst_arr.size > 0 else None
            ),
            "xsec_support_empty_reason_src_hist": dict(xsec_support_empty_reason_src_hist),
            "xsec_support_empty_reason_dst_hist": dict(xsec_support_empty_reason_dst_hist),
            "xsec_selected_by_src_hist": dict(xsec_selected_by_src_hist),
            "xsec_selected_by_dst_hist": dict(xsec_selected_by_dst_hist),
            "xsec_support_empty_src_count": int(xsec_support_empty_reason_src_hist.get("xsec_support_empty", 0)),
            "xsec_support_empty_dst_count": int(xsec_support_empty_reason_dst_hist.get("xsec_support_empty", 0)),
            "xsec_support_disabled_src_count": int(
                xsec_support_empty_reason_src_hist.get("support_disabled_due_to_insufficient", 0)
            ),
            "xsec_support_disabled_dst_count": int(
                xsec_support_empty_reason_dst_hist.get("support_disabled_due_to_insufficient", 0)
            ),
            "endpoint_fallback_mode_src_hist": dict(endpoint_fallback_mode_src_hist),
            "endpoint_fallback_mode_dst_hist": dict(endpoint_fallback_mode_dst_hist),
            "offset_clamp_hit_ratio_p50": (
                float(np.percentile(offset_clamp_hit_arr, 50.0)) if offset_clamp_hit_arr.size > 0 else None
            ),
            "offset_clamp_hit_ratio_p90": (
                float(np.percentile(offset_clamp_hit_arr, 90.0)) if offset_clamp_hit_arr.size > 0 else None
            ),
            "offset_clamp_hit_ratio_max": (float(np.max(offset_clamp_hit_arr)) if offset_clamp_hit_arr.size > 0 else None),
            "offset_clamp_fallback_count": int(offset_clamp_fallback_total),
            "xsec_shift_used_m_p90": (
                float(np.percentile(xsec_shift_used_arr, 90.0)) if xsec_shift_used_arr.size > 0 else None
            ),
            "xsec_mid_to_ref_m_p90": (
                float(np.percentile(xsec_mid_to_ref_arr, 90.0)) if xsec_mid_to_ref_arr.size > 0 else None
            ),
            "xsec_mid_to_ref_m_max": (float(np.max(xsec_mid_to_ref_arr)) if xsec_mid_to_ref_arr.size > 0 else None),
            "xsec_intersects_ref_ratio": (
                float(xsec_intersects_ref_true_count) / float(max(1, xsec_intersects_ref_total))
                if xsec_intersects_ref_total > 0
                else None
            ),
            "xsec_ref_intersection_n_p90": (
                float(np.percentile(xsec_ref_intersection_n_arr, 90.0))
                if xsec_ref_intersection_n_arr.size > 0
                else None
            ),
            "xsec_barrier_candidate_count_p90": (
                float(np.percentile(xsec_barrier_candidate_arr, 90.0))
                if xsec_barrier_candidate_arr.size > 0
                else None
            ),
            "xsec_barrier_final_count_p90": (
                float(np.percentile(xsec_barrier_final_arr, 90.0))
                if xsec_barrier_final_arr.size > 0
                else None
            ),
            "xsec_gate_len_src_p90": (
                float(np.percentile(xsec_gate_len_src_arr, 90.0)) if xsec_gate_len_src_arr.size > 0 else None
            ),
            "xsec_gate_len_dst_p90": (
                float(np.percentile(xsec_gate_len_dst_arr, 90.0)) if xsec_gate_len_dst_arr.size > 0 else None
            ),
            "xsec_gate_geom_type_src_hist": dict(xsec_gate_geom_type_src_hist),
            "xsec_gate_geom_type_dst_hist": dict(xsec_gate_geom_type_dst_hist),
            "xsec_gate_fallback_src_count": int(xsec_gate_fallback_src_count),
            "xsec_gate_fallback_dst_count": int(xsec_gate_fallback_dst_count),
            "step1_corridor_count_p90": (
                float(np.percentile(step1_corridor_count_arr, 90.0))
                if step1_corridor_count_arr.size > 0
                else None
            ),
            "step1_main_corridor_ratio_p50": (
                float(np.percentile(step1_main_corridor_ratio_arr, 50.0))
                if step1_main_corridor_ratio_arr.size > 0
                else None
            ),
            "traj_drop_count_by_drivezone": int(traj_drop_count_by_drivezone_total),
            "drivezone_fallback_used_count": int(drivezone_fallback_used_count),
            "xsec_samples_passable_ratio_src_p50": (
                float(np.percentile(xsec_samples_passable_ratio_src_arr, 50.0))
                if xsec_samples_passable_ratio_src_arr.size > 0
                else None
            ),
            "xsec_samples_passable_ratio_src_p90": (
                float(np.percentile(xsec_samples_passable_ratio_src_arr, 90.0))
                if xsec_samples_passable_ratio_src_arr.size > 0
                else None
            ),
            "xsec_samples_passable_ratio_dst_p50": (
                float(np.percentile(xsec_samples_passable_ratio_dst_arr, 50.0))
                if xsec_samples_passable_ratio_dst_arr.size > 0
                else None
            ),
            "xsec_samples_passable_ratio_dst_p90": (
                float(np.percentile(xsec_samples_passable_ratio_dst_arr, 90.0))
                if xsec_samples_passable_ratio_dst_arr.size > 0
                else None
            ),
            "endpoint_in_drivezone_src_true_count": int(endpoint_in_drivezone_src_true),
            "endpoint_in_drivezone_src_total": int(endpoint_in_drivezone_src_total),
            "endpoint_in_drivezone_src_ratio": (
                float(endpoint_in_drivezone_src_true) / float(max(1, endpoint_in_drivezone_src_total))
                if endpoint_in_drivezone_src_total > 0
                else None
            ),
            "endpoint_in_drivezone_dst_true_count": int(endpoint_in_drivezone_dst_true),
            "endpoint_in_drivezone_dst_total": int(endpoint_in_drivezone_dst_total),
            "endpoint_in_drivezone_dst_ratio": (
                float(endpoint_in_drivezone_dst_true) / float(max(1, endpoint_in_drivezone_dst_total))
                if endpoint_in_drivezone_dst_total > 0
                else None
            ),
            "endpoint_anchor_dist_p90": (
                float(np.percentile(endpoint_anchor_arr, 90.0)) if endpoint_anchor_arr.size > 0 else None
            ),
            "endpoint_anchor_dist_max": (
                float(np.max(endpoint_anchor_arr)) if endpoint_anchor_arr.size > 0 else None
            ),
            "traj_surface_enforced_count": int(traj_surface_enforced_count),
            "traj_surface_insufficient_count": int(traj_surface_insufficient_count),
            "slice_half_win_used_hist": dict(slice_half_hist_total),
            "road_outside_traj_surface_count": int(road_outside_traj_surface_count),
            "traj_in_ratio_p50": (float(np.percentile(traj_in_ratio_arr, 50.0)) if traj_in_ratio_arr.size > 0 else None),
            "traj_in_ratio_p90": (float(np.percentile(traj_in_ratio_arr, 90.0)) if traj_in_ratio_arr.size > 0 else None),
            "traj_in_ratio_est_p50": (
                float(np.percentile(traj_in_ratio_est_arr, 50.0)) if traj_in_ratio_est_arr.size > 0 else None
            ),
            "traj_in_ratio_est_p90": (
                float(np.percentile(traj_in_ratio_est_arr, 90.0)) if traj_in_ratio_est_arr.size > 0 else None
            ),
            "neighbor_search_pass": int(neighbor_search_pass),
            "neighbor_search_pass2_used": bool(int(neighbor_search_pass) == 2),
            **_timing_extra_metrics(),
        },
        debug_json_payloads=lane_boundary_debug_payloads,
    )


def _load_surface_points(
    patch_inputs: PatchInputs,
    supports: dict[tuple[int, int], PairSupport],
    params: dict[str, Any],
    *,
    use_pointcloud: bool = False,
    with_non_ground: bool = False,
) -> Any:
    stats: dict[str, Any] = {
        "pointcloud_enabled": bool(use_pointcloud),
        "pointcloud_attempted": False,
        "pointcloud_cache_hit": False,
        "pointcloud_cache_key": None,
        "pointcloud_bbox_point_count": 0,
        "pointcloud_selected_point_count": 0,
        "pointcloud_non_ground_selected_point_count": 0,
        "pointcloud_usage_tags": ["surface_points", "xsec_barrier"],
        "drivezone_surface_point_count": 0,
    }

    bbox = _support_union_bbox(patch_inputs, supports, margin_m=float(params["XSEC_ACROSS_HALF_WINDOW_M"]) + 5.0)
    if bbox is None:
        if with_non_ground:
            return np.empty((0, 3), dtype=np.float64), np.empty((0, 2), dtype=np.float64), stats
        return np.empty((0, 3), dtype=np.float64), stats
    drive_xyz = _sample_drivezone_surface_points(
        drivezone_metric=patch_inputs.drivezone_zone_metric,
        bbox_metric=bbox,
        step_m=float(params.get("DRIVEZONE_SAMPLE_STEP_M", 2.0)),
        max_points=900_000,
    )
    stats["drivezone_surface_point_count"] = int(drive_xyz.shape[0])
    if not bool(use_pointcloud):
        if with_non_ground:
            return drive_xyz, np.empty((0, 2), dtype=np.float64), stats
        return drive_xyz, stats
    if patch_inputs.point_cloud_path is None:
        if with_non_ground:
            return drive_xyz, np.empty((0, 2), dtype=np.float64), stats
        return drive_xyz, stats
    stats["pointcloud_attempted"] = True

    cache_enabled = bool(int(params.get("CACHE_ENABLED", 1)))
    cache_path: Path | None = None
    cache_ng_path: Path | None = None
    cache_key: str | None = None
    if cache_enabled:
        try:
            st = patch_inputs.point_cloud_path.stat()
            cache_key_payload = {
                "v": 1,
                "patch_id": str(patch_inputs.patch_id),
                "point_cloud_name": str(patch_inputs.point_cloud_path.name),
                "point_cloud_size": int(st.st_size),
                "point_cloud_mtime_ns": int(st.st_mtime_ns),
                "bbox": [round(float(v), 3) for v in bbox],
                "point_class_primary": int(params.get("POINT_CLASS_PRIMARY", 2)),
                "point_class_non_ground": 1,
                "point_class_fallback_any": int(params.get("POINT_CLASS_FALLBACK_ANY", 0)),
                "max_points": 900_000,
            }
            cache_key = _stable_json_digest(cache_key_payload)
            cache_dir = patch_inputs.patch_dir / ".t05_cache" / "pointcloud"
            cache_path = cache_dir / f"ground_{cache_key}.npz"
            cache_ng_path = cache_dir / f"nonground_{cache_key}.npz" if with_non_ground else None
            has_ng_cache = (cache_ng_path is not None and cache_ng_path.is_file()) if with_non_ground else True
            if cache_path.is_file() and has_ng_cache:
                with np.load(cache_path, allow_pickle=False) as zf:
                    xyz = np.asarray(zf["xyz"], dtype=np.float64)
                    bbox_cnt = int(zf["bbox_point_count"].item())
                    sel_cnt = int(zf["selected_point_count"].item())
                ng_xy = np.empty((0, 2), dtype=np.float64)
                ng_sel_cnt = 0
                if with_non_ground and cache_ng_path is not None:
                    with np.load(cache_ng_path, allow_pickle=False) as zng:
                        ng_xy = np.asarray(zng["xy"], dtype=np.float64)
                        ng_sel_cnt = int(zng["selected_point_count"].item())
                stats.update(
                    {
                        "pointcloud_cache_hit": True,
                        "pointcloud_cache_key": cache_key,
                        "pointcloud_bbox_point_count": int(bbox_cnt),
                        "pointcloud_selected_point_count": int(sel_cnt),
                        "pointcloud_non_ground_selected_point_count": int(ng_sel_cnt),
                    }
                )
                if with_non_ground:
                    base_xyz = drive_xyz if drive_xyz.shape[0] > 0 else xyz
                    return base_xyz, ng_xy, stats
                base_xyz = drive_xyz if drive_xyz.shape[0] > 0 else xyz
                return base_xyz, stats
        except Exception:
            cache_path = None
            cache_ng_path = None

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
        xyz = window.xyz_metric
        stats.update(
            {
                "pointcloud_cache_hit": False,
                "pointcloud_cache_key": cache_key,
                "pointcloud_bbox_point_count": int(window.bbox_point_count),
                "pointcloud_selected_point_count": int(window.selected_point_count),
            }
        )
        ng_xy = np.empty((0, 2), dtype=np.float64)
        if with_non_ground:
            try:
                ng_window = load_point_cloud_window(
                    patch_inputs.point_cloud_path,
                    bbox_metric=bbox,
                    allowed_classes=(1,),
                    fallback_to_any_class=False,
                    max_points=600_000,
                )
                ng_xy = np.asarray(ng_window.xyz_metric[:, :2], dtype=np.float64)
                stats["pointcloud_non_ground_selected_point_count"] = int(ng_window.selected_point_count)
            except InputDataError:
                ng_xy = np.empty((0, 2), dtype=np.float64)
            if ng_xy.ndim != 2 or ng_xy.shape[0] == 0:
                ng_xy = np.empty((0, 2), dtype=np.float64)
            elif ng_xy.shape[1] >= 2:
                ng_xy = ng_xy[:, :2]
                finite_ng = np.isfinite(ng_xy[:, 0]) & np.isfinite(ng_xy[:, 1])
                ng_xy = ng_xy[finite_ng, :]
            else:
                ng_xy = np.empty((0, 2), dtype=np.float64)
        if cache_enabled and cache_path is not None:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(
                    cache_path,
                    xyz=np.asarray(xyz, dtype=np.float64),
                    bbox_point_count=np.asarray([int(window.bbox_point_count)], dtype=np.int64),
                    selected_point_count=np.asarray([int(window.selected_point_count)], dtype=np.int64),
                )
                if with_non_ground and cache_ng_path is not None:
                    np.savez_compressed(
                        cache_ng_path,
                        xy=np.asarray(ng_xy, dtype=np.float64),
                        selected_point_count=np.asarray(
                            [int(stats.get("pointcloud_non_ground_selected_point_count", int(ng_xy.shape[0])))],
                            dtype=np.int64,
                        ),
                    )
            except Exception:
                pass
        if with_non_ground:
            base_xyz = drive_xyz if drive_xyz.shape[0] > 0 else xyz
            return base_xyz, ng_xy, stats
        base_xyz = drive_xyz if drive_xyz.shape[0] > 0 else xyz
        return base_xyz, stats
    except InputDataError:
        if with_non_ground:
            return drive_xyz, np.empty((0, 2), dtype=np.float64), stats
        return drive_xyz, stats


def _sample_drivezone_surface_points(
    *,
    drivezone_metric: BaseGeometry | None,
    bbox_metric: tuple[float, float, float, float],
    step_m: float,
    max_points: int,
) -> np.ndarray:
    if drivezone_metric is None or drivezone_metric.is_empty:
        return np.empty((0, 3), dtype=np.float64)
    minx, miny, maxx, maxy = [float(v) for v in bbox_metric]
    if not (np.isfinite(minx) and np.isfinite(miny) and np.isfinite(maxx) and np.isfinite(maxy)):
        return np.empty((0, 3), dtype=np.float64)
    if maxx - minx <= 1e-6 or maxy - miny <= 1e-6:
        return np.empty((0, 3), dtype=np.float64)
    bbox_poly = Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)])
    try:
        clip = drivezone_metric.intersection(bbox_poly)
    except Exception:
        clip = drivezone_metric
    if clip is None or clip.is_empty:
        return np.empty((0, 3), dtype=np.float64)
    step = float(max(0.5, step_m))
    area = float(max(1.0, (maxx - minx) * (maxy - miny)))
    target = float(max(10_000, max_points))
    est_n = area / float(max(0.25, step * step))
    if est_n > target * 4.0:
        step *= float(math.sqrt(est_n / (target * 4.0)))
    xs = np.arange(minx, maxx + step * 0.5, step, dtype=np.float64)
    ys = np.arange(miny, maxy + step * 0.5, step, dtype=np.float64)
    if xs.size == 0 or ys.size == 0:
        return np.empty((0, 3), dtype=np.float64)
    gx, gy = np.meshgrid(xs, ys)
    x_flat = gx.reshape(-1)
    y_flat = gy.reshape(-1)
    try:
        inside = np.asarray(contains_xy(clip, x_flat, y_flat), dtype=bool)
    except Exception:
        inside = np.zeros((x_flat.shape[0],), dtype=bool)
    if not np.any(inside):
        return np.empty((0, 3), dtype=np.float64)
    xy = np.column_stack((x_flat[inside], y_flat[inside]))
    if xy.shape[0] > int(max_points):
        step_idx = max(1, int(math.ceil(float(xy.shape[0]) / float(max_points))))
        xy = xy[::step_idx, :]
    z = np.zeros((xy.shape[0], 1), dtype=np.float64)
    return np.hstack((xy.astype(np.float64), z))


def _support_union_bbox(
    patch_inputs: PatchInputs,
    supports: dict[tuple[int, int], PairSupport],
    *,
    margin_m: float,
) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []

    for cs in patch_inputs.intersection_lines:
        for coord in cs.geometry_metric.coords:
            if len(coord) < 2:
                continue
            xs.append(float(coord[0]))
            ys.append(float(coord[1]))

    for support in supports.values():
        for seg in support.traj_segments[:6]:
            for coord in seg.coords:
                if len(coord) < 2:
                    continue
                xs.append(float(coord[0]))
                ys.append(float(coord[1]))

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


def _choose_step1_cross_point(points: Sequence[Point], xsec: LineString) -> Point | None:
    best: Point | None = None
    best_d = float("inf")
    for pt in points:
        if not isinstance(pt, Point) or pt.is_empty:
            continue
        try:
            d = float(pt.distance(xsec))
        except Exception:
            continue
        if d < best_d:
            best_d = d
            best = pt
    return best


def _line_xsec_contact_point(
    *,
    line: LineString | None,
    xsec: LineString,
    fallback: Point | None = None,
) -> Point | None:
    if isinstance(line, LineString) and (not line.is_empty) and line.length > 1e-6:
        xsec_mid = xsec.interpolate(0.5, normalized=True) if (isinstance(xsec, LineString) and xsec.length > 1e-6) else None
        try:
            inter = line.intersection(xsec)
        except Exception:
            inter = None
        pts: list[Point] = []
        if isinstance(inter, Point) and (not inter.is_empty):
            pts.append(inter)
        elif str(getattr(inter, "geom_type", "")) == "MultiPoint":
            for g in getattr(inter, "geoms", []):
                if isinstance(g, Point) and (not g.is_empty):
                    pts.append(g)
        elif isinstance(inter, LineString) and (not inter.is_empty) and inter.length > 1e-6:
            pts.append(inter.interpolate(0.5, normalized=True))
        elif str(getattr(inter, "geom_type", "")) == "MultiLineString":
            parts = [g for g in getattr(inter, "geoms", []) if isinstance(g, LineString) and (not g.is_empty) and g.length > 1e-6]
            if parts:
                best = max(parts, key=lambda g: float(g.length))
                pts.append(best.interpolate(0.5, normalized=True))
        elif str(getattr(inter, "geom_type", "")) == "GeometryCollection":
            for g in getattr(inter, "geoms", []):
                if isinstance(g, Point) and (not g.is_empty):
                    pts.append(g)
                elif isinstance(g, LineString) and (not g.is_empty) and g.length > 1e-6:
                    pts.append(g.interpolate(0.5, normalized=True))
        if pts:
            if isinstance(xsec_mid, Point) and (not xsec_mid.is_empty):
                try:
                    return min(pts, key=lambda p: float(p.distance(xsec_mid)))
                except Exception:
                    return pts[0]
            return pts[0]
        try:
            _lp, xp = nearest_points(line, xsec)
            if isinstance(xp, Point) and (not xp.is_empty):
                return xp
        except Exception:
            pass
    if isinstance(fallback, Point) and (not fallback.is_empty):
        return fallback
    return None


def _pick_step1_primary_item(items: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [it for it in items if isinstance(it, dict) and isinstance(it.get("seg"), LineString)]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    mids: list[tuple[float, float]] = []
    for it in valid:
        seg = it.get("seg")
        if not isinstance(seg, LineString) or seg.is_empty or seg.length <= 1e-6:
            mids.append((0.0, 0.0))
            continue
        p = seg.interpolate(0.5, normalized=True)
        mids.append((float(p.x), float(p.y)))
    arr = np.asarray(mids, dtype=np.float64)
    dm = np.linalg.norm(arr[:, None, :] - arr[None, :, :], axis=2)
    score = np.sum(dm, axis=1)
    for i, it in enumerate(valid):
        score[i] += 0.05 * float(max(0.0, it.get("d_seed", 0.0)))
        score[i] -= 0.0005 * float(max(0.0, it.get("length_m", 0.0)))
    idx = int(np.argmin(score))
    return valid[idx]


def _point_in_gore(pt: Point | None, gore_zone_metric: BaseGeometry | None) -> bool:
    if pt is None or pt.is_empty or gore_zone_metric is None or gore_zone_metric.is_empty:
        return False
    p_xy = point_xy_safe(pt, context="step1_gore_check")
    if p_xy is None:
        return False
    try:
        return bool(
            contains_xy(
                gore_zone_metric,
                np.asarray([float(p_xy[0])], dtype=np.float64),
                np.asarray([float(p_xy[1])], dtype=np.float64),
            ).item()
        )
    except Exception:
        return False


def _segment_gore_near_anchor(
    *,
    seg: LineString,
    anchor_pt: Point | None,
    gore_zone_metric: BaseGeometry | None,
    near_m: float,
) -> bool:
    if not isinstance(seg, LineString) or seg.is_empty:
        return False
    if gore_zone_metric is None or gore_zone_metric.is_empty:
        return False
    if _point_in_gore(anchor_pt, gore_zone_metric):
        return True
    if anchor_pt is None or anchor_pt.is_empty:
        return False
    try:
        s = float(seg.project(anchor_pt))
    except Exception:
        return False
    if not np.isfinite(s):
        return False
    win = float(max(1.0, near_m))
    s0 = max(0.0, s - win)
    s1 = min(float(seg.length), s + win)
    if s1 - s0 <= 1e-6:
        return False
    try:
        part = substring(seg, s0, s1)
    except Exception:
        part = seg
    if not isinstance(part, LineString) or part.is_empty:
        return False
    try:
        return float(part.intersection(gore_zone_metric).length) > 1e-6
    except Exception:
        return False


def _segment_gore_intersection_m(seg: LineString, gore_zone_metric: BaseGeometry | None) -> float:
    if not isinstance(seg, LineString) or seg.is_empty:
        return 0.0
    if gore_zone_metric is None or gore_zone_metric.is_empty:
        return 0.0
    try:
        inter = seg.intersection(gore_zone_metric)
        return float(max(0.0, float(inter.length)))
    except Exception:
        return 0.0


def _line_inside_ratio(line: LineString, zone: BaseGeometry | None) -> float | None:
    if not isinstance(line, LineString) or line.is_empty:
        return None
    line_len = float(line.length)
    if line_len <= 1e-6:
        return None
    if zone is None or zone.is_empty:
        return 1.0
    try:
        inter = line.intersection(zone)
        in_len = float(max(0.0, float(inter.length)))
    except Exception:
        in_len = 0.0
    if not np.isfinite(in_len):
        return 0.0
    return float(max(0.0, min(1.0, in_len / max(line_len, 1e-6))))


def _build_step1_corridor_for_pair(
    *,
    support: PairSupport,
    src_type: str,
    dst_type: str,
    src_xsec: LineString,
    dst_xsec: LineString,
    drivezone_zone_metric: BaseGeometry | None,
    gore_zone_metric: BaseGeometry | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "strategy": None,
        "hard_reason": None,
        "hard_hint": None,
        "multi_corridor_detected": False,
        "multi_corridor_hint": None,
        "shape_ref_line": None,
        "support_traj_ids": sorted({str(v) for v in support.support_traj_ids}),
        "cross_point_src": _choose_step1_cross_point(support.src_cross_points, src_xsec),
        "cross_point_dst": _choose_step1_cross_point(support.dst_cross_points, dst_xsec),
        "gore_fallback_used_src": False,
        "gore_fallback_used_dst": False,
        "drivezone_fallback_used": False,
        "traj_drop_count_by_drivezone": 0,
        "inside_ratio_threshold_used": None,
        "candidate_count": int(len(support.traj_segments)),
        "candidate_topk": [],
        "traj_gore_flags": [],
        "corridor_count": 0,
        "main_corridor_ratio": None,
        "corridor_candidates": [],
    }

    if str(dst_type) == "diverge":
        strategy = "dst_diverge_reverse_trace"
        seed_xsec = dst_xsec
    elif str(dst_type) == "merge" and str(src_type) == "merge":
        strategy = "merge_to_merge_forward_trace"
        seed_xsec = src_xsec
    elif str(dst_type) == "merge" and str(src_type) == "diverge":
        out["strategy"] = "unsupported"
        out["hard_reason"] = HARD_NO_STRATEGY_MERGE_TO_DIVERGE
        out["hard_hint"] = "dst=merge_src=diverge_no_strategy"
        return out
    else:
        strategy = "generic_forward_trace"
        seed_xsec = src_xsec

    out["strategy"] = str(strategy)
    seg_items = [
        (int(i), s)
        for i, s in enumerate(support.traj_segments)
        if isinstance(s, LineString) and (not s.is_empty) and s.length > 1.0
    ]
    if not seg_items:
        out["strategy"] = f"{strategy}|fallback_no_traj"
        out["hard_reason"] = None
        out["hard_hint"] = "step1_corridor_empty_fallback"
        return out
    seed_pt = seed_xsec.interpolate(0.5, normalized=True) if seed_xsec.length > 0 else Point(0.0, 0.0)
    near_m = float(max(5.0, params.get("STEP1_GORE_NEAR_M", 30.0)))
    constrained_end: str | None = None
    if str(dst_type) == "diverge":
        constrained_end = "src"
    elif str(dst_type) == "merge" and str(src_type) == "merge":
        constrained_end = "dst"

    passable_zone: BaseGeometry | None = None
    if drivezone_zone_metric is not None and (not drivezone_zone_metric.is_empty):
        passable_zone = drivezone_zone_metric
        if gore_zone_metric is not None and (not gore_zone_metric.is_empty):
            try:
                diff = drivezone_zone_metric.difference(gore_zone_metric)
                if diff is not None and (not diff.is_empty):
                    passable_zone = diff
            except Exception:
                pass

    inside_min = float(max(0.0, min(1.0, params.get("STEP1_TRAJ_IN_DRIVEZONE_MIN", 0.85))))
    inside_fallback_min = float(
        max(0.0, min(1.0, params.get("STEP1_TRAJ_IN_DRIVEZONE_FALLBACK_MIN", 0.60)))
    )
    ranked_all: list[dict[str, Any]] = []
    for i, seg in seg_items:
        try:
            d_seed = float(seg.distance(seed_pt))
        except Exception:
            d_seed = 1e9
        src_cp = support.src_cross_points[i] if i < len(support.src_cross_points) else None
        dst_cp = support.dst_cross_points[i] if i < len(support.dst_cross_points) else None
        gore_src = _segment_gore_near_anchor(
            seg=seg,
            anchor_pt=src_cp if isinstance(src_cp, Point) else None,
            gore_zone_metric=gore_zone_metric,
            near_m=near_m,
        )
        gore_dst = _segment_gore_near_anchor(
            seg=seg,
            anchor_pt=dst_cp if isinstance(dst_cp, Point) else None,
            gore_zone_metric=gore_zone_metric,
            near_m=near_m,
        )
        gore_len_m = _segment_gore_intersection_m(seg, gore_zone_metric)
        gore_any = bool(gore_len_m > 1e-6)
        violation = bool((constrained_end == "src" and gore_src) or (constrained_end == "dst" and gore_dst))
        tid = str(support.evidence_traj_ids[i]) if i < len(support.evidence_traj_ids) else None
        inside_ratio = _line_inside_ratio(seg, passable_zone)
        if inside_ratio is None:
            inside_ratio = 0.0
        ranked_all.append(
            {
                "d_seed": float(d_seed),
                "length_m": float(seg.length),
                "idx": int(i),
                "seg": seg,
                "traj_id": tid,
                "src_cp": (src_cp if isinstance(src_cp, Point) else None),
                "dst_cp": (dst_cp if isinstance(dst_cp, Point) else None),
                "gore_src_near": bool(gore_src),
                "gore_dst_near": bool(gore_dst),
                "gore_any": bool(gore_any),
                "gore_intersection_m": float(gore_len_m),
                "constraint_violation": bool(violation),
                "inside_ratio": float(inside_ratio),
                "dropped_by_drivezone": False,
            }
        )

    ranked_all.sort(key=lambda it: (float(it["d_seed"]), -float(it["length_m"]), int(it["idx"])))
    ranked = list(ranked_all)
    if passable_zone is not None and (not passable_zone.is_empty):
        strict = [it for it in ranked if float(it.get("inside_ratio", 0.0)) >= inside_min]
        if strict:
            ranked = strict
            out["inside_ratio_threshold_used"] = float(inside_min)
        else:
            relaxed = [it for it in ranked if float(it.get("inside_ratio", 0.0)) >= inside_fallback_min]
            if relaxed:
                ranked = relaxed
                out["inside_ratio_threshold_used"] = float(inside_fallback_min)
                out["drivezone_fallback_used"] = True
            else:
                ranked = sorted(
                    ranked,
                    key=lambda it: (-float(it.get("inside_ratio", 0.0)), float(it["d_seed"]), -float(it["length_m"])),
                )[:3]
                out["inside_ratio_threshold_used"] = None
                out["drivezone_fallback_used"] = True
        keep_idx = {int(it["idx"]) for it in ranked}
        for it in ranked_all:
            if int(it["idx"]) not in keep_idx:
                it["dropped_by_drivezone"] = True
        out["traj_drop_count_by_drivezone"] = int(sum(1 for it in ranked_all if bool(it.get("dropped_by_drivezone"))))
    else:
        out["inside_ratio_threshold_used"] = 1.0

    good = [it for it in ranked if not bool(it["constraint_violation"])]
    ranked_end = good if good else ranked
    gore_free = [it for it in ranked_end if not bool(it.get("gore_any", False))]
    ranked_used = gore_free if gore_free else ranked_end
    reach_xsec_m = float(max(1.0, params.get("STEP1_CORRIDOR_REACH_XSEC_M", 12.0)))
    for it in ranked_all:
        seg = it.get("seg")
        d_src = float("inf")
        d_dst = float("inf")
        if isinstance(seg, LineString) and (not seg.is_empty):
            try:
                d_src = float(seg.distance(src_xsec))
            except Exception:
                d_src = float("inf")
            try:
                d_dst = float(seg.distance(dst_xsec))
            except Exception:
                d_dst = float("inf")
        it["dist_to_src_xsec_m"] = float(d_src)
        it["dist_to_dst_xsec_m"] = float(d_dst)
        it["reaches_other_end"] = bool(np.isfinite(d_src) and np.isfinite(d_dst) and d_src <= reach_xsec_m and d_dst <= reach_xsec_m)
    ranked_reach = [it for it in ranked_used if bool(it.get("reaches_other_end", False))]
    ranked_main = ranked_reach if ranked_reach else ranked_used
    topk_debug = ranked_main[:3]
    if not topk_debug:
        out["hard_reason"] = HARD_CENTER_EMPTY
        out["hard_hint"] = "step1_no_candidate_after_filter"
        out["traj_gore_flags"] = [
            {
                "idx": int(it["idx"]),
                "traj_id": it.get("traj_id"),
                "gore_src_near": bool(it.get("gore_src_near", False)),
                "gore_dst_near": bool(it.get("gore_dst_near", False)),
                "gore_any": bool(it.get("gore_any", False)),
                "gore_intersection_m": float(it.get("gore_intersection_m", 0.0)),
                "constraint_violation": bool(it.get("constraint_violation", False)),
                "inside_ratio": float(it.get("inside_ratio", 0.0)),
                "dropped_by_drivezone": bool(it.get("dropped_by_drivezone", False)),
                "corridor_id": None,
                "dist_to_src_xsec_m": float(it.get("dist_to_src_xsec_m", float("inf"))),
                "dist_to_dst_xsec_m": float(it.get("dist_to_dst_xsec_m", float("inf"))),
                "reaches_other_end": bool(it.get("reaches_other_end", False)),
                "selected": False,
            }
            for it in ranked_all
        ]
        return out

    weights = np.asarray([max(1.0, float(it.get("length_m", 0.0))) for it in topk_debug], dtype=np.float64)
    if weights.size > 0 and float(np.sum(weights)) > 1e-6:
        out["main_corridor_ratio"] = float(np.max(weights) / float(np.sum(weights)))
    else:
        out["main_corridor_ratio"] = 1.0
    # 主流程只保留单通路；其余候选仅用于 debug 与强证据 multi-corridor 诊断。
    out["corridor_count"] = 1
    picked = _pick_step1_primary_item(topk_debug) or topk_debug[0]
    corridor_id_by_idx = {int(it["idx"]): int(i) for i, it in enumerate(topk_debug, start=1)}
    out["corridor_candidates"] = []
    for cid, it in enumerate(topk_debug, start=1):
        seg = it.get("seg")
        line = _orient_axis_line(seg, src_xsec=src_xsec, dst_xsec=dst_xsec) if isinstance(seg, LineString) else None
        if not isinstance(line, LineString) or line.is_empty:
            continue
        out["corridor_candidates"].append(
            {
                "corridor_id": int(cid),
                "start_traj_id": it.get("traj_id"),
                "length_m": float(line.length),
                "reaches_other_end": bool(it.get("reaches_other_end", False)),
                "inside_ratio": float(it.get("inside_ratio", 0.0)),
                "drivezone_fallback_used": bool(out.get("drivezone_fallback_used", False)),
                "dist_to_src_xsec_m": float(it.get("dist_to_src_xsec_m", float("inf"))),
                "dist_to_dst_xsec_m": float(it.get("dist_to_dst_xsec_m", float("inf"))),
                "selected": bool(int(it.get("idx", -1)) == int(picked.get("idx", -2))),
                "geometry": line,
            }
        )
    out["candidate_topk"] = [
        {
            "rank": int(i),
            "dist_to_seed_m": float(it["d_seed"]),
            "length_m": float(it["length_m"]),
            "traj_id": it.get("traj_id"),
            "gore_src_near": bool(it.get("gore_src_near", False)),
            "gore_dst_near": bool(it.get("gore_dst_near", False)),
            "gore_any": bool(it.get("gore_any", False)),
            "gore_intersection_m": float(it.get("gore_intersection_m", 0.0)),
            "constraint_violation": bool(it.get("constraint_violation", False)),
            "inside_ratio": float(it.get("inside_ratio", 0.0)),
            "dist_to_src_xsec_m": float(it.get("dist_to_src_xsec_m", float("inf"))),
            "dist_to_dst_xsec_m": float(it.get("dist_to_dst_xsec_m", float("inf"))),
            "reaches_other_end": bool(it.get("reaches_other_end", False)),
            "selected": bool(int(it.get("idx", -1)) == int(picked.get("idx", -2))),
        }
        for i, it in enumerate(topk_debug, start=1)
    ]
    out["traj_gore_flags"] = [
        {
            "idx": int(it["idx"]),
            "traj_id": it.get("traj_id"),
            "gore_src_near": bool(it.get("gore_src_near", False)),
            "gore_dst_near": bool(it.get("gore_dst_near", False)),
            "gore_any": bool(it.get("gore_any", False)),
            "gore_intersection_m": float(it.get("gore_intersection_m", 0.0)),
            "constraint_violation": bool(it.get("constraint_violation", False)),
            "inside_ratio": float(it.get("inside_ratio", 0.0)),
            "dropped_by_drivezone": bool(it.get("dropped_by_drivezone", False)),
            "corridor_id": corridor_id_by_idx.get(int(it["idx"])),
            "dist_to_src_xsec_m": float(it.get("dist_to_src_xsec_m", float("inf"))),
            "dist_to_dst_xsec_m": float(it.get("dist_to_dst_xsec_m", float("inf"))),
            "reaches_other_end": bool(it.get("reaches_other_end", False)),
            "selected": False,
        }
        for it in ranked_all
    ]
    multi_sep_m = float(max(1.0, params.get("STEP1_MULTI_CORRIDOR_DIST_M", 8.0)))
    multi_ratio = float(max(0.0, min(1.0, params.get("STEP1_MULTI_CORRIDOR_MIN_RATIO", 0.60))))
    multi_hard = bool(int(params.get("STEP1_MULTI_CORRIDOR_HARD", 0)))
    topk_multi = [it for it in topk_debug if bool(it.get("reaches_other_end", False))]
    if len(topk_multi) >= 2:
        mids: list[tuple[float, float]] = []
        for item in topk_multi:
            seg = item["seg"]
            mid = seg.interpolate(0.5, normalized=True)
            mid_xy = point_xy_safe(mid, context="step1_corridor_mid")
            if mid_xy is not None:
                mids.append((float(mid_xy[0]), float(mid_xy[1])))
        if len(mids) >= 2:
            arr = np.asarray(mids, dtype=np.float64)
            dm = np.linalg.norm(arr[:, None, :] - arr[None, :, :], axis=2)
            sep = float(np.max(dm))
            weights_multi = np.asarray([max(1.0, float(it.get("length_m", 0.0))) for it in topk_multi], dtype=np.float64)
            if weights_multi.size > 0 and float(np.sum(weights_multi)) > 1e-6:
                main_ratio = float(np.max(weights_multi) / float(np.sum(weights_multi)))
            else:
                main_ratio = 1.0
            if sep > multi_sep_m and (len(topk_multi) >= 3 or main_ratio < multi_ratio):
                hint = (
                    f"corridor_count={int(len(topk_multi))};"
                    f"main_corridor_ratio={float(main_ratio):.3f};"
                    f"corridor_sep_m={sep:.3f}"
                )
                if int(max(1, support.cluster_count)) > 1:
                    hint += (
                        f";cluster_count={int(support.cluster_count)};"
                        f"cluster_main_ratio={float(support.main_cluster_ratio):.3f}"
                    )
                out["multi_corridor_detected"] = True
                out["multi_corridor_hint"] = str(hint)
                if multi_hard:
                    out["hard_reason"] = HARD_MULTI_CORRIDOR
                    out["hard_hint"] = str(hint)
                    return out
                out["strategy"] = f"{strategy}|multi_corridor_soft"
    picked_seg = picked["seg"]
    out["shape_ref_line"] = _orient_axis_line(picked_seg, src_xsec=src_xsec, dst_xsec=dst_xsec)
    for item in out["traj_gore_flags"]:
        if int(item.get("idx", -1)) == int(picked.get("idx", -2)):
            item["selected"] = True
    src_fallback = picked.get("src_cp") if isinstance(picked.get("src_cp"), Point) else out.get("cross_point_src")
    dst_fallback = picked.get("dst_cp") if isinstance(picked.get("dst_cp"), Point) else out.get("cross_point_dst")
    out["cross_point_src"] = _line_xsec_contact_point(
        line=out.get("shape_ref_line"),
        xsec=src_xsec,
        fallback=src_fallback if isinstance(src_fallback, Point) else None,
    )
    out["cross_point_dst"] = _line_xsec_contact_point(
        line=out.get("shape_ref_line"),
        xsec=dst_xsec,
        fallback=dst_fallback if isinstance(dst_fallback, Point) else None,
    )
    out["gore_fallback_used_src"] = bool(picked.get("gore_src_near", False) and not good)
    out["gore_fallback_used_dst"] = bool(picked.get("gore_dst_near", False) and not good)
    return out


def _fallback_geometry_from_shape_ref(
    *,
    shape_ref_line: LineString | None,
    src_xsec: LineString,
    dst_xsec: LineString,
) -> LineString | None:
    if not isinstance(shape_ref_line, LineString) or shape_ref_line.is_empty or shape_ref_line.length <= 1e-6:
        return None
    line = _orient_axis_line(shape_ref_line, src_xsec=src_xsec, dst_xsec=dst_xsec)
    try:
        src_on_line, _ = nearest_points(line, src_xsec)
        dst_on_line, _ = nearest_points(line, dst_xsec)
        s0 = float(line.project(src_on_line))
        s1 = float(line.project(dst_on_line))
    except Exception:
        s0 = 0.0
        s1 = float(line.length)
    if not np.isfinite(s0) or not np.isfinite(s1):
        s0 = 0.0
        s1 = float(line.length)
    if abs(s1 - s0) < 1e-3:
        core = line
    else:
        try:
            core = substring(line, min(s0, s1), max(s0, s1))
        except Exception:
            core = line
    if core is None or core.is_empty or not isinstance(core, LineString) or len(core.coords) < 2:
        return line if len(line.coords) >= 2 else None
    return _orient_axis_line(core, src_xsec=src_xsec, dst_xsec=dst_xsec)


def _is_valid_linestring(geom: BaseGeometry | None) -> bool:
    return bool(isinstance(geom, LineString) and (not geom.is_empty) and len(geom.coords) >= 2)


def _fallback_bind_endpoints_to_xsec(
    *,
    line: LineString,
    src_xsec: LineString,
    dst_xsec: LineString,
    gore_zone_metric: BaseGeometry | None,
    snap_max_m: float,
) -> tuple[LineString, Point | None, Point | None, float | None, float | None]:
    if not _is_valid_linestring(line):
        return line, None, None, None, None
    try:
        src_on_line, src_on_xsec = nearest_points(line, src_xsec)
        dst_on_line, dst_on_xsec = nearest_points(line, dst_xsec)
    except Exception:
        return line, None, None, None, None
    src_on_line_xy = point_xy_safe(src_on_line, context="fallback_bind_src_line")
    src_on_xsec_xy = point_xy_safe(src_on_xsec, context="fallback_bind_src_xsec")
    dst_on_line_xy = point_xy_safe(dst_on_line, context="fallback_bind_dst_line")
    dst_on_xsec_xy = point_xy_safe(dst_on_xsec, context="fallback_bind_dst_xsec")
    if src_on_line_xy is None or src_on_xsec_xy is None or dst_on_line_xy is None or dst_on_xsec_xy is None:
        return line, None, None, None, None

    src_before = float(
        math.hypot(
            float(src_on_line_xy[0]) - float(src_on_xsec_xy[0]),
            float(src_on_line_xy[1]) - float(src_on_xsec_xy[1]),
        )
    )
    dst_before = float(
        math.hypot(
            float(dst_on_line_xy[0]) - float(dst_on_xsec_xy[0]),
            float(dst_on_line_xy[1]) - float(dst_on_xsec_xy[1]),
        )
    )
    try:
        s0 = float(line.project(Point(float(src_on_line_xy[0]), float(src_on_line_xy[1]))))
        s1 = float(line.project(Point(float(dst_on_line_xy[0]), float(dst_on_line_xy[1]))))
    except Exception:
        s0 = 0.0
        s1 = float(line.length)
    if not np.isfinite(s0) or not np.isfinite(s1):
        s0 = 0.0
        s1 = float(line.length)
    try:
        core = substring(line, min(s0, s1), max(s0, s1))
    except Exception:
        core = line
    if not _is_valid_linestring(core):
        core = line
    core = _orient_axis_line(core, src_xsec=src_xsec, dst_xsec=dst_xsec)
    coords = [tuple(c) for c in core.coords if len(c) >= 2]
    if len(coords) < 2:
        return line, None, None, src_before, dst_before

    snap_cap = float(max(0.5, snap_max_m))
    src_xy = (float(src_on_xsec_xy[0]), float(src_on_xsec_xy[1]))
    dst_xy = (float(dst_on_xsec_xy[0]), float(dst_on_xsec_xy[1]))
    src_conn_ok = bool(src_before <= snap_cap)
    dst_conn_ok = bool(dst_before <= snap_cap)

    if src_conn_ok and gore_zone_metric is not None and (not gore_zone_metric.is_empty):
        try:
            src_conn_ok = float(LineString([src_xy, coords[0]]).intersection(gore_zone_metric).length) <= 1e-6
        except Exception:
            src_conn_ok = False
    if dst_conn_ok and gore_zone_metric is not None and (not gore_zone_metric.is_empty):
        try:
            dst_conn_ok = float(LineString([coords[-1], dst_xy]).intersection(gore_zone_metric).length) <= 1e-6
        except Exception:
            dst_conn_ok = False

    out_coords: list[tuple[float, float]] = []
    if src_conn_ok:
        out_coords.append(src_xy)
    out_coords.extend((float(c[0]), float(c[1])) for c in coords)
    if dst_conn_ok:
        out_coords.append(dst_xy)
    dedup: list[tuple[float, float]] = []
    for c in out_coords:
        if dedup and math.hypot(float(c[0]) - float(dedup[-1][0]), float(c[1]) - float(dedup[-1][1])) <= 1e-6:
            continue
        dedup.append((float(c[0]), float(c[1])))
    if len(dedup) < 2:
        return line, None, None, src_before, dst_before
    try:
        out_line = LineString(dedup)
    except Exception:
        return line, None, None, src_before, dst_before
    if out_line.is_empty or len(out_line.coords) < 2:
        return line, None, None, src_before, dst_before
    src_after_pt = Point(float(dedup[0][0]), float(dedup[0][1]))
    dst_after_pt = Point(float(dedup[-1][0]), float(dedup[-1][1]))
    return out_line, src_after_pt, dst_after_pt, src_before, dst_before


def _count_line_intersections_simple(line_a: BaseGeometry | None, line_b: BaseGeometry | None) -> int:
    if not _is_valid_linestring(line_a) or not _is_valid_linestring(line_b):
        return 0
    try:
        inter = line_a.intersection(line_b)
    except Exception:
        return 0
    if inter is None or inter.is_empty:
        return 0
    gtype = str(getattr(inter, "geom_type", ""))
    if gtype == "Point":
        return 1
    if gtype == "MultiPoint":
        try:
            return int(len(inter.geoms))
        except Exception:
            return 0
    if gtype == "GeometryCollection":
        n = 0
        try:
            for g in inter.geoms:
                gg = str(getattr(g, "geom_type", ""))
                if gg == "Point":
                    n += 1
                elif gg == "MultiPoint":
                    n += int(len(g.geoms))
        except Exception:
            return 0
        return int(n)
    # overlap as line counts as at least one intersection
    if gtype in {"LineString", "MultiLineString"}:
        try:
            return 1 if float(inter.length) > 1e-6 else 0
        except Exception:
            return 0
    return 0


def _bridge_segment_diagnostics(
    *,
    road_line: LineString | None,
    max_segment_idx: int | None,
    traj_surface_metric: BaseGeometry | None,
    gore_zone_metric: BaseGeometry | None,
    lb_shape_ref_metric: LineString | None,
) -> tuple[float | None, bool, float | None]:
    if not isinstance(road_line, LineString) or road_line.is_empty or len(road_line.coords) < 2:
        return (None, False, None)
    coords = np.asarray(road_line.coords, dtype=np.float64)
    if coords.shape[0] < 2:
        return (None, False, None)
    if max_segment_idx is None or int(max_segment_idx) < 0 or int(max_segment_idx) >= coords.shape[0] - 1:
        idx = int(np.argmax(np.linalg.norm(coords[1:, :] - coords[:-1, :], axis=1)))
    else:
        idx = int(max_segment_idx)
    seg = LineString([tuple(coords[idx, :]), tuple(coords[idx + 1, :])])
    seg_len = float(seg.length)
    if seg_len <= 1e-9:
        return (0.0, False, 0.0)
    outside_ratio: float | None = None
    if traj_surface_metric is not None and (not traj_surface_metric.is_empty):
        try:
            outside_len = float(seg.difference(traj_surface_metric).length)
        except Exception:
            outside_len = seg_len
        outside_ratio = float(max(0.0, min(1.0, outside_len / max(1e-6, seg_len))))
    inter_divstrip = False
    if gore_zone_metric is not None and (not gore_zone_metric.is_empty):
        try:
            inter_divstrip = float(seg.intersection(gore_zone_metric).length) > 1e-6
        except Exception:
            inter_divstrip = False
    dist_to_lb: float | None = None
    if isinstance(lb_shape_ref_metric, LineString) and (not lb_shape_ref_metric.is_empty):
        try:
            dist_to_lb = float(seg.distance(lb_shape_ref_metric))
        except Exception:
            dist_to_lb = None
    return (outside_ratio, bool(inter_divstrip), dist_to_lb)


def _enforce_gore_free_geometry(
    *,
    road_line: LineString | None,
    gore_zone_metric: BaseGeometry | None,
    shape_ref_line: LineString | None,
    src_xsec: LineString,
    dst_xsec: LineString,
) -> tuple[LineString | None, float, str | None]:
    if not isinstance(road_line, LineString) or road_line.is_empty:
        return (road_line, 0.0, None)
    if gore_zone_metric is None or gore_zone_metric.is_empty:
        return (road_line, 0.0, None)
    try:
        inter_len = float(road_line.intersection(gore_zone_metric).length)
    except Exception:
        inter_len = 0.0
    if inter_len <= 1e-6:
        return (road_line, 0.0, None)

    shape_fb = _fallback_geometry_from_shape_ref(
        shape_ref_line=shape_ref_line,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
    )
    if isinstance(shape_fb, LineString) and not shape_fb.is_empty:
        try:
            fb_inter = float(shape_fb.intersection(gore_zone_metric).length)
        except Exception:
            fb_inter = inter_len
        if fb_inter <= 1e-6:
            return (shape_fb, 0.0, "shape_ref_substring_gore_free")

    try:
        diff = road_line.difference(gore_zone_metric)
    except Exception:
        diff = None
    parts = _iter_line_parts(diff)
    if parts:
        parts_sorted = sorted(parts, key=lambda g: float(g.length), reverse=True)
        for part in parts_sorted:
            if part.is_empty or part.length <= 1e-6 or len(part.coords) < 2:
                continue
            cand = _orient_axis_line(part, src_xsec=src_xsec, dst_xsec=dst_xsec)
            try:
                cand_inter = float(cand.intersection(gore_zone_metric).length)
            except Exception:
                cand_inter = 0.0
            if cand_inter <= 1e-6:
                return (cand, 0.0, "line_difference_gore_free")

    return (None, float(max(0.0, inter_len)), "gore_free_fallback_failed")


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


def _orient_axis_line(line: LineString, *, src_xsec: LineString, dst_xsec: LineString) -> LineString:
    if line.is_empty or line.length <= 0 or len(line.coords) < 2:
        return line
    p0 = Point(line.coords[0])
    p1 = Point(line.coords[-1])
    fwd = float(p0.distance(src_xsec) + p1.distance(dst_xsec))
    bwd = float(p0.distance(dst_xsec) + p1.distance(src_xsec))
    if bwd + 1e-9 < fwd:
        return LineString(list(line.coords)[::-1])
    return line


def _pick_medoid_support_axis(
    *,
    support: PairSupport,
    src_xsec: LineString,
    dst_xsec: LineString,
) -> LineString | None:
    segs = [s for s in support.traj_segments if isinstance(s, LineString) and (not s.is_empty) and s.length > 1.0]
    if not segs:
        return None
    mids: list[tuple[float, float]] = []
    for s in segs:
        p = s.interpolate(0.5, normalized=True)
        mids.append((float(p.x), float(p.y)))
    if len(segs) <= 2:
        chosen = segs[int(np.argmax(np.asarray([float(s.length) for s in segs], dtype=np.float64)))]
        return _orient_axis_line(chosen, src_xsec=src_xsec, dst_xsec=dst_xsec)
    arr = np.asarray(mids, dtype=np.float64)
    dm = np.linalg.norm(arr[:, None, :] - arr[None, :, :], axis=2)
    medoid_idx = int(np.argmin(np.sum(dm, axis=1)))
    return _orient_axis_line(segs[medoid_idx], src_xsec=src_xsec, dst_xsec=dst_xsec)


def _choose_traj_surface_ref_axis(
    *,
    support: PairSupport,
    src_xsec: LineString,
    dst_xsec: LineString,
    lane_boundaries_metric: Sequence[LineString],
    gore_zone_metric: BaseGeometry | None,
    params: dict[str, Any],
) -> tuple[LineString | None, str]:
    medoid_axis = _pick_medoid_support_axis(support=support, src_xsec=src_xsec, dst_xsec=dst_xsec)
    lb_axis_line: LineString | None = None
    try:
        lb_axis = _build_lb_graph_path(
            src_xsec=src_xsec,
            dst_xsec=dst_xsec,
            lane_boundaries_metric=lane_boundaries_metric,
            snap_m=float(params.get("LB_SNAP_M", 1.0)),
            topk=int(params.get("LB_START_END_TOPK", 5)),
            enforce_surface=False,
            outside_edge_ratio_max=float(params.get("OUTSIDE_EDGE_RATIO_MAX", 1.0)),
            surface_node_buffer_m=float(params.get("SURF_NODE_BUFFER_M", 2.0)),
            divstrip_barrier_metric=gore_zone_metric,
        )
    except Exception:
        lb_axis = None
    if lb_axis is not None and lb_axis[0] is not None and lb_axis[0].length > 1.0:
        lb_axis_line = _orient_axis_line(lb_axis[0], src_xsec=src_xsec, dst_xsec=dst_xsec)

    if lb_axis_line is not None and medoid_axis is not None:
        try:
            dist = float(lb_axis_line.distance(medoid_axis))
        except Exception:
            dist = float("inf")
        corridor = float(params.get("CORRIDOR_HALF_WIDTH_M", 15.0))
        if not np.isfinite(dist) or dist > max(5.0, 1.2 * corridor):
            return medoid_axis, "traj_medoid_axis"
    if lb_axis_line is not None:
        return lb_axis_line, "lb_path_axis"
    if medoid_axis is not None:
        return medoid_axis, "traj_medoid_axis"
    return None, "axis_missing"


def _normalize_surface_polygon(surface: BaseGeometry | None) -> BaseGeometry | None:
    if surface is None or surface.is_empty:
        return None
    gtype = str(getattr(surface, "geom_type", ""))
    if gtype in {"Polygon", "MultiPolygon"}:
        return surface
    line_parts: list[LineString] = []
    if isinstance(surface, LineString):
        if not surface.is_empty and len(surface.coords) >= 2:
            line_parts.append(surface)
    elif isinstance(surface, MultiLineString):
        for ls in surface.geoms:
            if isinstance(ls, LineString) and (not ls.is_empty) and len(ls.coords) >= 2:
                line_parts.append(ls)
    else:
        for ls in _iter_line_parts(surface):
            if not ls.is_empty and len(ls.coords) >= 2:
                line_parts.append(ls)
    if not line_parts:
        return None
    try:
        polys = list(polygonize(line_parts))
    except Exception:
        polys = []
    if not polys:
        return None
    try:
        merged = unary_union(polys)
    except Exception:
        merged = polys[0]
    if merged is None or merged.is_empty:
        return None
    if str(getattr(merged, "geom_type", "")) not in {"Polygon", "MultiPolygon"}:
        return None
    return merged


def _surface_component_count(surface: BaseGeometry | None) -> int:
    if surface is None or surface.is_empty:
        return 0
    gtype = str(getattr(surface, "geom_type", ""))
    if gtype == "Polygon":
        return 1
    if gtype == "MultiPolygon":
        return int(len(getattr(surface, "geoms", [])))
    return 0


def _kmeans_1d_two_cluster(values: np.ndarray, *, iters: int = 8) -> tuple[np.ndarray, np.ndarray]:
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return np.zeros((0,), dtype=np.int8), np.asarray([], dtype=np.float64)
    finite = np.isfinite(arr)
    arr = arr[finite]
    if arr.size == 0:
        return np.zeros((0,), dtype=np.int8), np.asarray([], dtype=np.float64)
    if arr.size < 4:
        return np.zeros((arr.size,), dtype=np.int8), np.asarray([float(np.median(arr))], dtype=np.float64)
    c0 = float(np.quantile(arr, 0.25))
    c1 = float(np.quantile(arr, 0.75))
    if not np.isfinite(c0):
        c0 = float(np.min(arr))
    if not np.isfinite(c1):
        c1 = float(np.max(arr))
    if abs(c1 - c0) <= 1e-6:
        c0 = float(np.min(arr))
        c1 = float(np.max(arr))
    if abs(c1 - c0) <= 1e-6:
        return np.zeros((arr.size,), dtype=np.int8), np.asarray([float(np.median(arr))], dtype=np.float64)
    labels = np.zeros((arr.size,), dtype=np.int8)
    for _ in range(max(1, int(iters))):
        d0 = np.abs(arr - c0)
        d1 = np.abs(arr - c1)
        labels = (d1 < d0).astype(np.int8)
        n0 = int(np.count_nonzero(labels == 0))
        n1 = int(np.count_nonzero(labels == 1))
        if n0 == 0 or n1 == 0:
            return np.zeros((arr.size,), dtype=np.int8), np.asarray([float(np.median(arr))], dtype=np.float64)
        c0_new = float(np.median(arr[labels == 0]))
        c1_new = float(np.median(arr[labels == 1]))
        if abs(c0_new - c0) <= 1e-6 and abs(c1_new - c1) <= 1e-6:
            c0, c1 = c0_new, c1_new
            break
        c0, c1 = c0_new, c1_new
    centers = np.asarray([c0, c1], dtype=np.float64)
    return labels, centers


def _pick_endcap_cluster(values: np.ndarray, *, ref_u: float, min_pts: int) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size < max(6, int(min_pts)):
        return arr
    labels, centers = _kmeans_1d_two_cluster(arr)
    if centers.size < 2:
        return arr
    idx = int(np.argmin(np.abs(centers - float(ref_u))))
    picked = arr[labels == idx]
    if picked.size < int(min_pts):
        return arr
    return picked


def _covered_station_length(stations: np.ndarray, valid_mask: np.ndarray) -> float:
    st = np.asarray(stations, dtype=np.float64)
    vm = np.asarray(valid_mask, dtype=bool)
    if st.size < 2 or vm.size != st.size:
        return 0.0
    seg = st[1:] - st[:-1]
    if seg.size == 0:
        return 0.0
    use = vm[:-1] & vm[1:] & np.isfinite(seg) & (seg > 0.0)
    if not np.any(use):
        return 0.0
    return float(np.sum(seg[use]))


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


def _select_cluster_candidates(support: PairSupport, *, max_clusters: int) -> list[int]:
    n = int(support.support_event_count)
    if n <= 0:
        return [int(support.main_cluster_id)]
    labels = list(support.evidence_cluster_ids)
    if len(labels) != n:
        labels = [int(support.main_cluster_id) for _ in range(n)]
    counts: dict[int, int] = {}
    for lab in labels:
        li = int(lab)
        counts[li] = counts.get(li, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-int(kv[1]), int(kv[0])))
    out = [int(k) for k, _ in ranked[: max(1, int(max_clusters))]]
    if int(support.main_cluster_id) not in out:
        out.append(int(support.main_cluster_id))
    return out[: max(1, int(max_clusters))]


def _subset_support_by_cluster(support: PairSupport, cluster_id: int) -> PairSupport | None:
    n = int(support.support_event_count)
    if n <= 0:
        return None
    labels = list(support.evidence_cluster_ids)
    if len(labels) != n:
        labels = [int(support.main_cluster_id) for _ in range(n)]
    idx = [i for i, lab in enumerate(labels) if int(lab) == int(cluster_id)]
    if not idx:
        return None

    out = PairSupport(
        src_nodeid=int(support.src_nodeid),
        dst_nodeid=int(support.dst_nodeid),
        open_end=False,
        hard_anomalies=set(support.hard_anomalies),
    )
    out.cluster_count = int(support.cluster_count)
    out.main_cluster_id = int(support.main_cluster_id)
    out.main_cluster_ratio = float(support.main_cluster_ratio)
    out.cluster_sep_m_est = support.cluster_sep_m_est
    out.cluster_sizes = [int(v) for v in support.cluster_sizes]
    out.unresolved_neighbor_count = int(support.unresolved_neighbor_count)

    for i in idx:
        seg = support.traj_segments[i] if i < len(support.traj_segments) else LineString([(0.0, 0.0), (0.0, 0.0)])
        src_pt = support.src_cross_points[i] if i < len(support.src_cross_points) else Point(0.0, 0.0)
        dst_pt = support.dst_cross_points[i] if i < len(support.dst_cross_points) else Point(0.0, 0.0)
        out.traj_segments.append(seg)
        out.src_cross_points.append(src_pt)
        out.dst_cross_points.append(dst_pt)
        out.stitch_hops.append(int(support.stitch_hops[i]) if i < len(support.stitch_hops) else 0)
        tid = str(support.evidence_traj_ids[i]) if i < len(support.evidence_traj_ids) else ""
        if not tid:
            tid = next(iter(support.support_traj_ids), "")
        out.evidence_traj_ids.append(tid)
        out.evidence_cluster_ids.append(int(cluster_id))
        vlen = float(support.evidence_lengths_m[i]) if i < len(support.evidence_lengths_m) else float("nan")
        out.evidence_lengths_m.append(vlen)
        open_flag = bool(support.open_end_flags[i]) if i < len(support.open_end_flags) else False
        out.open_end_flags.append(open_flag)
        if tid:
            out.support_traj_ids.add(tid)
            if tid not in out.repr_traj_ids and len(out.repr_traj_ids) < 16:
                out.repr_traj_ids.append(tid)
    out.support_event_count = int(len(idx))
    out.open_end = bool(any(out.open_end_flags))
    return out


def _build_traj_surface_from_refline(
    *,
    ref_line: LineString,
    traj_xy: np.ndarray,
    gore_zone_metric: BaseGeometry | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    ref_len = float(ref_line.length)
    step = max(1.0, float(params["SURF_SLICE_STEP_M"]))
    half_win = max(0.5, float(params["SURF_SLICE_HALF_WIN_M"]))
    levels = params.get("SURF_SLICE_HALF_WIN_LEVELS_M", [half_win, 5.0, 10.0])
    half_levels = [float(v) for v in levels if np.isfinite(float(v)) and float(v) >= half_win]
    if half_win not in half_levels:
        half_levels = [half_win] + half_levels
    half_levels = sorted({round(v, 6) for v in half_levels})
    q_lo = max(0.0, min(0.5, float(params["SURF_QUANT_LOW"])))
    q_hi = max(0.5, min(1.0, float(params["SURF_QUANT_HIGH"])))
    if q_hi <= q_lo:
        q_lo, q_hi = 0.02, 0.98
    min_pts = max(3, int(params["TRAJ_SURF_MIN_POINTS_PER_SLICE"]))
    axis_max_project_dist = max(5.0, float(params.get("AXIS_MAX_PROJECT_DIST_M", 20.0)))
    endcap_m = max(0.0, float(params.get("ENDCAP_M", 30.0)))
    endcap_rel_cap = max(1.1, float(params.get("ENDCAP_WIDTH_REL_CAP", 2.0)))
    endcap_abs_cap = max(5.0, float(params.get("ENDCAP_WIDTH_ABS_CAP_M", 40.0)))

    stations = np.arange(0.0, ref_len + step * 0.5, step, dtype=np.float64)
    if stations.size == 0 or abs(float(stations[-1]) - ref_len) > 1e-6:
        stations = np.concatenate((stations, np.asarray([ref_len], dtype=np.float64)))
    stations = np.unique(np.clip(stations, 0.0, ref_len))

    valid_mask = np.zeros((stations.size,), dtype=bool)
    half_hist: dict[str, int] = {}
    lo_arr = np.full((stations.size,), np.nan, dtype=np.float64)
    hi_arr = np.full((stations.size,), np.nan, dtype=np.float64)
    center_u_arr = np.full((stations.size,), np.nan, dtype=np.float64)

    def _empty_result() -> dict[str, Any]:
        return {
            "surface": None,
            "stations": stations,
            "valid_mask": valid_mask,
            "left_pts": np.empty((0, 2), dtype=np.float64),
            "right_pts": np.empty((0, 2), dtype=np.float64),
            "total_slices": int(stations.size),
            "valid_slices": 0,
            "slice_valid_ratio": 0.0,
            "covered_length_ratio": 0.0,
            "covered_station_length_m": 0.0,
            "endcap_valid_ratio_src": 0.0,
            "endcap_valid_ratio_dst": 0.0,
            "endcap_width_src_before_m": None,
            "endcap_width_src_after_m": None,
            "endcap_width_dst_before_m": None,
            "endcap_width_dst_after_m": None,
            "endcap_width_clamped_src_count": 0,
            "endcap_width_clamped_dst_count": 0,
            "slice_half_win_used_hist": half_hist,
            "slice_half_win_levels": [float(v) for v in half_levels],
        }

    xy = np.asarray(traj_xy, dtype=np.float64)
    if xy.ndim != 2 or xy.shape[0] == 0:
        return _empty_result()
    finite = np.isfinite(xy[:, 0]) & np.isfinite(xy[:, 1])
    xy = xy[finite, :]
    if xy.shape[0] == 0:
        return _empty_result()

    if gore_zone_metric is not None:
        try:
            gore_mask = np.asarray(contains_xy(gore_zone_metric, xy[:, 0], xy[:, 1]), dtype=bool)
            xy = xy[~gore_mask, :]
        except Exception:
            pass
    if xy.shape[0] == 0:
        return _empty_result()

    pt_arr = points(xy[:, 0], xy[:, 1])
    s_all = np.asarray(line_locate_point(ref_line, pt_arr), dtype=np.float64)
    s_all = np.clip(s_all, 0.0, ref_len)
    on_axis = line_interpolate_point(ref_line, s_all)
    ox = np.asarray(get_x(on_axis), dtype=np.float64)
    oy = np.asarray(get_y(on_axis), dtype=np.float64)
    delta = min(2.0, max(0.5, step * 0.5))
    s0 = np.clip(s_all - delta, 0.0, ref_len)
    s1 = np.clip(s_all + delta, 0.0, ref_len)
    p0 = line_interpolate_point(ref_line, s0)
    p1 = line_interpolate_point(ref_line, s1)
    tpx = np.asarray(get_x(p1), dtype=np.float64) - np.asarray(get_x(p0), dtype=np.float64)
    tpy = np.asarray(get_y(p1), dtype=np.float64) - np.asarray(get_y(p0), dtype=np.float64)
    tn = np.hypot(tpx, tpy)
    good_t = tn > 1e-9
    tpx[~good_t] = 1.0
    tpy[~good_t] = 0.0
    tn[~good_t] = 1.0
    tx = tpx / tn
    ty = tpy / tn
    nx = -ty
    ny = tx
    u_all = (xy[:, 0] - ox) * nx + (xy[:, 1] - oy) * ny
    proj_keep = np.isfinite(u_all) & (np.abs(u_all) <= float(axis_max_project_dist))
    if np.count_nonzero(proj_keep) < min_pts:
        return _empty_result()
    s_all = s_all[proj_keep]
    u_all = u_all[proj_keep]
    sort_idx = np.argsort(s_all)
    s_sorted = s_all[sort_idx]
    u_sorted = u_all[sort_idx]

    mid_lo = float(min(ref_len, endcap_m))
    mid_hi = float(max(0.0, ref_len - endcap_m))
    if mid_hi > mid_lo + 1e-6:
        mid_u = u_sorted[(s_sorted >= mid_lo) & (s_sorted <= mid_hi)]
    else:
        mid_u = np.asarray([], dtype=np.float64)
    if mid_u.size >= min_pts:
        u_mid_median = float(np.median(mid_u))
    elif u_sorted.size > 0:
        u_mid_median = float(np.median(u_sorted))
    else:
        u_mid_median = 0.0

    st_pt = line_interpolate_point(ref_line, stations)
    st_x = np.asarray(get_x(st_pt), dtype=np.float64)
    st_y = np.asarray(get_y(st_pt), dtype=np.float64)
    st0 = line_interpolate_point(ref_line, np.clip(stations - delta, 0.0, ref_len))
    st1 = line_interpolate_point(ref_line, np.clip(stations + delta, 0.0, ref_len))
    st_tx = np.asarray(get_x(st1), dtype=np.float64) - np.asarray(get_x(st0), dtype=np.float64)
    st_ty = np.asarray(get_y(st1), dtype=np.float64) - np.asarray(get_y(st0), dtype=np.float64)
    st_tn = np.hypot(st_tx, st_ty)
    bad_st = st_tn <= 1e-9
    st_tx[bad_st] = 1.0
    st_ty[bad_st] = 0.0
    st_tn[bad_st] = 1.0
    st_tx = st_tx / st_tn
    st_ty = st_ty / st_tn
    st_nx = -st_ty
    st_ny = st_tx

    src_end_mask = stations <= float(min(ref_len, endcap_m) + 1e-6)
    dst_end_mask = stations >= float(max(0.0, ref_len - endcap_m) - 1e-6)
    mid_end_mask = (~src_end_mask) & (~dst_end_mask)

    for i, s in enumerate(stations):
        chosen_vals: np.ndarray | None = None
        chosen_half: float | None = None
        for hw in half_levels:
            lo_s = float(s - hw)
            hi_s = float(s + hw)
            i0 = int(np.searchsorted(s_sorted, lo_s, side="left"))
            i1 = int(np.searchsorted(s_sorted, hi_s, side="right"))
            if i1 - i0 < min_pts:
                continue
            vals = u_sorted[i0:i1]
            vals = vals[np.isfinite(vals)]
            if vals.size < min_pts:
                continue
            if bool(src_end_mask[i]) or bool(dst_end_mask[i]):
                vals = _pick_endcap_cluster(vals, ref_u=u_mid_median, min_pts=min_pts)
            if vals.size < min_pts:
                continue
            chosen_vals = vals
            chosen_half = float(hw)
            break
        if chosen_vals is None or chosen_half is None:
            continue
        lo_arr[i] = float(np.quantile(chosen_vals, q_lo))
        hi_arr[i] = float(np.quantile(chosen_vals, q_hi))
        center_u_arr[i] = float(np.median(chosen_vals))
        valid_mask[i] = True
        hkey = f"{chosen_half:.1f}"
        half_hist[hkey] = int(half_hist.get(hkey, 0) + 1)

    widths = hi_arr - lo_arr
    mid_widths = widths[valid_mask & mid_end_mask & np.isfinite(widths)]
    if mid_widths.size > 0:
        w_base = float(np.median(mid_widths))
    else:
        all_widths = widths[valid_mask & np.isfinite(widths)]
        w_base = float(np.median(all_widths)) if all_widths.size > 0 else float("nan")
    if np.isfinite(w_base) and w_base > 0:
        w_cap = float(min(endcap_rel_cap * w_base, endcap_abs_cap))
    else:
        w_cap = float(endcap_abs_cap)

    src_before: list[float] = []
    src_after: list[float] = []
    dst_before: list[float] = []
    dst_after: list[float] = []
    src_clamped = 0
    dst_clamped = 0
    for i in range(stations.size):
        if not bool(valid_mask[i]) or not np.isfinite(widths[i]):
            continue
        is_src = bool(src_end_mask[i])
        is_dst = bool(dst_end_mask[i])
        if not (is_src or is_dst):
            continue
        w_before = float(widths[i])
        lo_v = float(lo_arr[i])
        hi_v = float(hi_arr[i])
        ctr = float(center_u_arr[i]) if np.isfinite(center_u_arr[i]) else float(0.5 * (lo_v + hi_v))
        w_after = w_before
        if np.isfinite(w_cap) and w_cap > 0.0 and w_before > w_cap:
            lo_v = float(ctr - 0.5 * w_cap)
            hi_v = float(ctr + 0.5 * w_cap)
            lo_arr[i] = lo_v
            hi_arr[i] = hi_v
            w_after = float(w_cap)
            if is_src:
                src_clamped += 1
            if is_dst:
                dst_clamped += 1
        if is_src:
            src_before.append(w_before)
            src_after.append(w_after)
        if is_dst:
            dst_before.append(w_before)
            dst_after.append(w_after)

    left_pts: list[tuple[float, float]] = []
    right_pts: list[tuple[float, float]] = []
    for i in range(stations.size):
        if not bool(valid_mask[i]):
            continue
        lo = float(lo_arr[i])
        hi = float(hi_arr[i])
        if not (np.isfinite(lo) and np.isfinite(hi)):
            valid_mask[i] = False
            continue
        left_pts.append((float(st_x[i] + st_nx[i] * lo), float(st_y[i] + st_ny[i] * lo)))
        right_pts.append((float(st_x[i] + st_nx[i] * hi), float(st_y[i] + st_ny[i] * hi)))

    surface: BaseGeometry | None = None
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
                if gore_zone_metric is not None and surface is not None and (not surface.is_empty):
                    try:
                        surface = surface.difference(gore_zone_metric)
                    except Exception:
                        pass
                surface = _normalize_surface_polygon(surface)

    total_slices = int(stations.size)
    valid_slices = int(np.count_nonzero(valid_mask))
    slice_valid_ratio = float(valid_slices / max(1, total_slices))
    covered_len = _covered_station_length(stations, valid_mask)
    covered_len_ratio = float(covered_len / max(ref_len, 1e-6))
    src_total = int(np.count_nonzero(src_end_mask))
    dst_total = int(np.count_nonzero(dst_end_mask))
    src_valid = int(np.count_nonzero(valid_mask & src_end_mask))
    dst_valid = int(np.count_nonzero(valid_mask & dst_end_mask))
    endcap_valid_ratio_src = float(src_valid / max(1, src_total))
    endcap_valid_ratio_dst = float(dst_valid / max(1, dst_total))

    return {
        "surface": surface,
        "stations": stations,
        "valid_mask": valid_mask,
        "left_pts": np.asarray(left_pts, dtype=np.float64),
        "right_pts": np.asarray(right_pts, dtype=np.float64),
        "total_slices": total_slices,
        "valid_slices": valid_slices,
        "slice_valid_ratio": slice_valid_ratio,
        "covered_length_ratio": covered_len_ratio,
        "covered_station_length_m": float(covered_len),
        "endcap_valid_ratio_src": float(endcap_valid_ratio_src),
        "endcap_valid_ratio_dst": float(endcap_valid_ratio_dst),
        "endcap_width_src_before_m": float(np.max(np.asarray(src_before, dtype=np.float64))) if src_before else None,
        "endcap_width_src_after_m": float(np.max(np.asarray(src_after, dtype=np.float64))) if src_after else None,
        "endcap_width_dst_before_m": float(np.max(np.asarray(dst_before, dtype=np.float64))) if dst_before else None,
        "endcap_width_dst_after_m": float(np.max(np.asarray(dst_after, dtype=np.float64))) if dst_after else None,
        "endcap_width_clamped_src_count": int(src_clamped),
        "endcap_width_clamped_dst_count": int(dst_clamped),
        "slice_half_win_used_hist": half_hist,
        "slice_half_win_levels": [float(v) for v in half_levels],
    }


def _surface_from_lr(
    *,
    left_pts: np.ndarray,
    right_pts: np.ndarray,
    surf_buf_m: float,
    gore_zone_metric: BaseGeometry | None,
) -> BaseGeometry | None:
    if left_pts.ndim != 2 or right_pts.ndim != 2:
        return None
    if left_pts.shape[0] < 2 or right_pts.shape[0] < 2:
        return None
    ring = [tuple(map(float, p)) for p in left_pts] + [tuple(map(float, p)) for p in right_pts[::-1, :]]
    if len(ring) < 4:
        return None
    try:
        poly = Polygon(ring)
        if not poly.is_valid:
            poly = poly.buffer(0)
    except Exception:
        return None
    if poly is None or poly.is_empty:
        return None
    try:
        surf = poly.buffer(float(max(0.0, surf_buf_m)))
    except Exception:
        surf = poly
    if gore_zone_metric is not None and surf is not None and (not surf.is_empty):
        try:
            surf = surf.difference(gore_zone_metric)
        except Exception:
            pass
    surf = _normalize_surface_polygon(surf)
    return surf if (surf is not None and not surf.is_empty) else None


def _traj_surface_cache_path(
    *,
    patch_inputs: PatchInputs,
    support: PairSupport,
    cluster_id: int,
    ref_axis_line: LineString,
    axis_source: str,
    src_xsec: LineString,
    dst_xsec: LineString,
    params: dict[str, Any],
) -> tuple[Path, str]:
    traj_meta: list[dict[str, Any]] = []
    by_id = {str(t.traj_id): t for t in patch_inputs.trajectories}
    for tid in sorted({str(v) for v in support.support_traj_ids}):
        t = by_id.get(tid)
        if t is None:
            traj_meta.append({"traj_id": tid, "missing": True})
            continue
        try:
            st = Path(t.source_path).stat()
            traj_meta.append({"traj_id": tid, "size": int(st.st_size), "mtime_ns": int(st.st_mtime_ns)})
        except Exception:
            traj_meta.append({"traj_id": tid, "missing": True})

    key_payload = {
        "v": 2,
        "patch_id": str(patch_inputs.patch_id),
        "src": int(support.src_nodeid),
        "dst": int(support.dst_nodeid),
        "cluster_id": int(cluster_id),
        "traj_meta": traj_meta,
        "src_xsec_bbox": [round(float(v), 3) for v in src_xsec.bounds],
        "dst_xsec_bbox": [round(float(v), 3) for v in dst_xsec.bounds],
        "axis_source": str(axis_source),
        "axis_len": round(float(ref_axis_line.length), 3),
        "axis_bbox": [round(float(v), 3) for v in ref_axis_line.bounds],
        "slice_step": float(params["SURF_SLICE_STEP_M"]),
        "slice_half_win": float(params["SURF_SLICE_HALF_WIN_M"]),
        "slice_half_win_levels": [float(v) for v in params.get("SURF_SLICE_HALF_WIN_LEVELS_M", [])],
        "axis_max_project_dist_m": float(params.get("AXIS_MAX_PROJECT_DIST_M", 20.0)),
        "endcap_m": float(params.get("ENDCAP_M", 30.0)),
        "endcap_min_valid_ratio": float(params.get("ENDCAP_MIN_VALID_RATIO", 0.5)),
        "endcap_width_abs_cap_m": float(params.get("ENDCAP_WIDTH_ABS_CAP_M", 40.0)),
        "endcap_width_rel_cap": float(params.get("ENDCAP_WIDTH_REL_CAP", 2.0)),
        "quant_low": float(params["SURF_QUANT_LOW"]),
        "quant_high": float(params["SURF_QUANT_HIGH"]),
        "surf_buf_m": float(params["SURF_BUF_M"]),
        "min_points_per_slice": int(params["TRAJ_SURF_MIN_POINTS_PER_SLICE"]),
    }
    cache_key = _stable_json_digest(key_payload)
    cache_path = patch_inputs.patch_dir / ".t05_cache" / "traj_surface" / f"traj_surface_{cache_key}.npz"
    return cache_path, cache_key


def _build_traj_surface_hint_for_cluster(
    *,
    support: PairSupport,
    cluster_id: int,
    src_xsec: LineString,
    dst_xsec: LineString,
    lane_boundaries_metric: Sequence[LineString],
    patch_inputs: PatchInputs,
    gore_zone_metric: BaseGeometry | None,
    params: dict[str, Any],
    traj_points_cache: dict[tuple[str, ...], tuple[np.ndarray, int]] | None = None,
) -> dict[str, Any]:
    t0 = perf_counter()
    ids_key = tuple(sorted(str(v) for v in support.support_traj_ids))
    if traj_points_cache is not None and ids_key in traj_points_cache:
        traj_xy, unique_traj_count = traj_points_cache[ids_key]
    else:
        traj_xy, unique_traj_count = _collect_support_traj_points(patch_inputs, support)
        if traj_points_cache is not None:
            traj_points_cache[ids_key] = (traj_xy, unique_traj_count)
    out: dict[str, Any] = {
        "surface_metric": None,
        "traj_surface_enforced": False,
        "slice_valid_ratio": 0.0,
        "covered_length_ratio": 0.0,
        "covered_station_length_m": 0.0,
        "endcap_valid_ratio_src": 0.0,
        "endcap_valid_ratio_dst": 0.0,
        "endcap_width_src_before_m": None,
        "endcap_width_src_after_m": None,
        "endcap_width_dst_before_m": None,
        "endcap_width_dst_after_m": None,
        "endcap_width_clamped_src_count": 0,
        "endcap_width_clamped_dst_count": 0,
        "xsec_support_available_src": False,
        "xsec_support_available_dst": False,
        "unique_traj_count": int(unique_traj_count),
        "valid_slices": 0,
        "total_slices": 0,
        "cache_hit": False,
        "cache_key": None,
        "timing_ms": 0.0,
        "_stations": None,
        "_valid_mask": None,
        "traj_surface_geom_type": None,
        "traj_surface_area_m2": None,
        "surface_component_count": 0,
        "axis_source": None,
        "slice_half_win_used_hist": {},
        "slice_half_win_levels": [],
    }
    if traj_xy.shape[0] < 8 or unique_traj_count <= 0:
        out["reason"] = "traj_points_insufficient"
        out["timing_ms"] = float((perf_counter() - t0) * 1000.0)
        return out
    ref_line, axis_source = _choose_traj_surface_ref_axis(
        support=support,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        lane_boundaries_metric=lane_boundaries_metric,
        gore_zone_metric=gore_zone_metric,
        params=params,
    )
    if ref_line is None or ref_line.length <= 1.0:
        out["reason"] = "ref_axis_missing"
        out["timing_ms"] = float((perf_counter() - t0) * 1000.0)
        return out
    out["axis_source"] = str(axis_source)

    cache_enabled = bool(int(params.get("CACHE_ENABLED", 1)))
    cache_path: Path | None = None
    cache_key: str | None = None
    if cache_enabled:
        try:
            cache_path, cache_key = _traj_surface_cache_path(
                patch_inputs=patch_inputs,
                support=support,
                cluster_id=int(cluster_id),
                ref_axis_line=ref_line,
                axis_source=str(axis_source),
                src_xsec=src_xsec,
                dst_xsec=dst_xsec,
                params=params,
            )
            out["cache_key"] = cache_key
            if cache_path.is_file():
                with np.load(cache_path, allow_pickle=False) as zf:
                    left_pts = np.asarray(zf["left_pts"], dtype=np.float64)
                    right_pts = np.asarray(zf["right_pts"], dtype=np.float64)
                    stations = np.asarray(zf["stations"], dtype=np.float64)
                    valid_mask = np.asarray(zf["valid_mask"], dtype=bool)
                    valid_slices = int(zf["valid_slices"].item())
                    total_slices = int(zf["total_slices"].item())
                    slice_valid_ratio = float(zf["slice_valid_ratio"].item())
                    covered_length_ratio = float(zf["covered_length_ratio"].item())
                    covered_station_length = float(zf["covered_station_length_m"].item()) if "covered_station_length_m" in zf else 0.0
                    endcap_valid_ratio_src = (
                        float(zf["endcap_valid_ratio_src"].item()) if "endcap_valid_ratio_src" in zf else 0.0
                    )
                    endcap_valid_ratio_dst = (
                        float(zf["endcap_valid_ratio_dst"].item()) if "endcap_valid_ratio_dst" in zf else 0.0
                    )
                    endcap_width_src_before = (
                        float(zf["endcap_width_src_before_m"].item()) if "endcap_width_src_before_m" in zf else None
                    )
                    endcap_width_src_after = (
                        float(zf["endcap_width_src_after_m"].item()) if "endcap_width_src_after_m" in zf else None
                    )
                    endcap_width_dst_before = (
                        float(zf["endcap_width_dst_before_m"].item()) if "endcap_width_dst_before_m" in zf else None
                    )
                    endcap_width_dst_after = (
                        float(zf["endcap_width_dst_after_m"].item()) if "endcap_width_dst_after_m" in zf else None
                    )
                    endcap_clamped_src_count = (
                        int(zf["endcap_width_clamped_src_count"].item()) if "endcap_width_clamped_src_count" in zf else 0
                    )
                    endcap_clamped_dst_count = (
                        int(zf["endcap_width_clamped_dst_count"].item()) if "endcap_width_clamped_dst_count" in zf else 0
                    )
                    half_hist = {}
                    if "slice_half_win_hist_keys" in zf and "slice_half_win_hist_vals" in zf:
                        keys = [str(v) for v in np.asarray(zf["slice_half_win_hist_keys"]).tolist()]
                        vals = [int(v) for v in np.asarray(zf["slice_half_win_hist_vals"]).tolist()]
                        for k, v in zip(keys, vals):
                            half_hist[str(k)] = int(v)
                surface = _surface_from_lr(
                    left_pts=left_pts,
                    right_pts=right_pts,
                    surf_buf_m=float(params["SURF_BUF_M"]),
                    gore_zone_metric=gore_zone_metric,
                )
                out.update(
                    {
                        "surface_metric": surface,
                        "slice_valid_ratio": float(slice_valid_ratio),
                        "covered_length_ratio": float(covered_length_ratio),
                        "covered_station_length_m": float(covered_station_length),
                        "endcap_valid_ratio_src": float(endcap_valid_ratio_src),
                        "endcap_valid_ratio_dst": float(endcap_valid_ratio_dst),
                        "endcap_width_src_before_m": endcap_width_src_before,
                        "endcap_width_src_after_m": endcap_width_src_after,
                        "endcap_width_dst_before_m": endcap_width_dst_before,
                        "endcap_width_dst_after_m": endcap_width_dst_after,
                        "endcap_width_clamped_src_count": int(endcap_clamped_src_count),
                        "endcap_width_clamped_dst_count": int(endcap_clamped_dst_count),
                        "valid_slices": int(valid_slices),
                        "total_slices": int(total_slices),
                        "_stations": stations,
                        "_valid_mask": valid_mask,
                        "slice_half_win_used_hist": dict(half_hist),
                        "slice_half_win_levels": [float(v) for v in params.get("SURF_SLICE_HALF_WIN_LEVELS_M", [])],
                        "cache_hit": True,
                    }
                )
        except Exception:
            pass

    if out.get("surface_metric") is None:
        out["cache_hit"] = False
        built = _build_traj_surface_from_refline(
            ref_line=ref_line,
            traj_xy=traj_xy,
            gore_zone_metric=gore_zone_metric,
            params=params,
        )
        out["surface_metric"] = built["surface"]
        out["slice_valid_ratio"] = float(built["slice_valid_ratio"])
        out["covered_length_ratio"] = float(built["covered_length_ratio"])
        out["covered_station_length_m"] = float(built.get("covered_station_length_m", 0.0))
        out["endcap_valid_ratio_src"] = float(built.get("endcap_valid_ratio_src", 0.0))
        out["endcap_valid_ratio_dst"] = float(built.get("endcap_valid_ratio_dst", 0.0))
        out["endcap_width_src_before_m"] = built.get("endcap_width_src_before_m")
        out["endcap_width_src_after_m"] = built.get("endcap_width_src_after_m")
        out["endcap_width_dst_before_m"] = built.get("endcap_width_dst_before_m")
        out["endcap_width_dst_after_m"] = built.get("endcap_width_dst_after_m")
        out["endcap_width_clamped_src_count"] = int(built.get("endcap_width_clamped_src_count", 0))
        out["endcap_width_clamped_dst_count"] = int(built.get("endcap_width_clamped_dst_count", 0))
        out["valid_slices"] = int(built["valid_slices"])
        out["total_slices"] = int(built["total_slices"])
        out["_stations"] = built.get("stations")
        out["_valid_mask"] = built.get("valid_mask")
        out["slice_half_win_used_hist"] = dict(built.get("slice_half_win_used_hist") or {})
        out["slice_half_win_levels"] = [float(v) for v in built.get("slice_half_win_levels") or []]
        if cache_enabled and cache_path is not None:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                hh = dict(built.get("slice_half_win_used_hist") or {})
                np.savez_compressed(
                    cache_path,
                    left_pts=np.asarray(built.get("left_pts"), dtype=np.float64),
                    right_pts=np.asarray(built.get("right_pts"), dtype=np.float64),
                    stations=np.asarray(built.get("stations"), dtype=np.float64),
                    valid_mask=np.asarray(built.get("valid_mask"), dtype=np.bool_),
                    valid_slices=np.asarray([int(built["valid_slices"])], dtype=np.int64),
                    total_slices=np.asarray([int(built["total_slices"])], dtype=np.int64),
                    slice_valid_ratio=np.asarray([float(built["slice_valid_ratio"])], dtype=np.float64),
                    covered_length_ratio=np.asarray([float(built["covered_length_ratio"])], dtype=np.float64),
                    covered_station_length_m=np.asarray([float(built.get("covered_station_length_m", 0.0))], dtype=np.float64),
                    endcap_valid_ratio_src=np.asarray([float(built.get("endcap_valid_ratio_src", 0.0))], dtype=np.float64),
                    endcap_valid_ratio_dst=np.asarray([float(built.get("endcap_valid_ratio_dst", 0.0))], dtype=np.float64),
                    endcap_width_src_before_m=np.asarray(
                        [float(_to_finite_float(built.get("endcap_width_src_before_m"), 0.0))], dtype=np.float64
                    ),
                    endcap_width_src_after_m=np.asarray(
                        [float(_to_finite_float(built.get("endcap_width_src_after_m"), 0.0))], dtype=np.float64
                    ),
                    endcap_width_dst_before_m=np.asarray(
                        [float(_to_finite_float(built.get("endcap_width_dst_before_m"), 0.0))], dtype=np.float64
                    ),
                    endcap_width_dst_after_m=np.asarray(
                        [float(_to_finite_float(built.get("endcap_width_dst_after_m"), 0.0))], dtype=np.float64
                    ),
                    endcap_width_clamped_src_count=np.asarray(
                        [int(built.get("endcap_width_clamped_src_count", 0))], dtype=np.int64
                    ),
                    endcap_width_clamped_dst_count=np.asarray(
                        [int(built.get("endcap_width_clamped_dst_count", 0))], dtype=np.int64
                    ),
                    slice_half_win_hist_keys=np.asarray(sorted(hh.keys()), dtype="U16"),
                    slice_half_win_hist_vals=np.asarray(
                        [int(hh[k]) for k in sorted(hh.keys())],
                        dtype=np.int64,
                    ),
                )
            except Exception:
                pass

    surf = out.get("surface_metric")
    surf = _normalize_surface_polygon(surf)
    out["surface_metric"] = surf
    if surf is not None and not surf.is_empty:
        out["traj_surface_geom_type"] = str(getattr(surf, "geom_type", ""))
        out["traj_surface_area_m2"] = float(surf.area)
        out["surface_component_count"] = int(_surface_component_count(surf))
    else:
        out["traj_surface_geom_type"] = None
        out["traj_surface_area_m2"] = None
        out["surface_component_count"] = 0

    min_slice_ratio = max(float(params["TRAJ_SURF_MIN_SLICE_VALID_RATIO"]), 0.60)
    min_cov_ratio = max(
        float(params["TRAJ_SURF_MIN_COVERED_LEN_RATIO"]),
        float(params.get("TRAJ_SURF_ENFORCE_MIN_COVERED_LEN_RATIO", 0.90)),
    )
    min_endcap_ratio = max(0.0, min(1.0, float(params.get("ENDCAP_MIN_VALID_RATIO", 0.5))))
    src_endcap_ok = float(out.get("endcap_valid_ratio_src", 0.0)) >= float(min_endcap_ratio)
    dst_endcap_ok = float(out.get("endcap_valid_ratio_dst", 0.0)) >= float(min_endcap_ratio)
    out["xsec_support_available_src"] = bool(
        _xsec_has_surface_support(
            xsec=src_xsec,
            surface_metric=out.get("surface_metric"),
            gore_zone_metric=gore_zone_metric,
            buffer_m=float(params.get("SURF_BUF_M", 1.0)),
        )
    )
    out["xsec_support_available_dst"] = bool(
        _xsec_has_surface_support(
            xsec=dst_xsec,
            surface_metric=out.get("surface_metric"),
            gore_zone_metric=gore_zone_metric,
            buffer_m=float(params.get("SURF_BUF_M", 1.0)),
        )
    )
    sufficient = (
        int(out["valid_slices"]) >= 2
        and float(out["slice_valid_ratio"]) >= min_slice_ratio
        and float(out["covered_length_ratio"]) >= min_cov_ratio
        and bool(src_endcap_ok)
        and bool(dst_endcap_ok)
        and int(unique_traj_count) >= int(params["TRAJ_SURF_MIN_UNIQUE_TRAJ"])
        and out["surface_metric"] is not None
        and (not out["surface_metric"].is_empty)
        and float(out.get("traj_surface_area_m2") or 0.0) > 0.0
        and bool(out.get("xsec_support_available_src", False))
        and bool(out.get("xsec_support_available_dst", False))
    )
    out["traj_surface_enforced"] = bool(sufficient)
    if not sufficient:
        reasons: list[str] = []
        if int(out["valid_slices"]) < 2:
            reasons.append("valid_slices_low")
        if float(out["slice_valid_ratio"]) < min_slice_ratio:
            reasons.append("slice_valid_ratio_low")
        if float(out["covered_length_ratio"]) < min_cov_ratio:
            reasons.append("covered_len_ratio_low")
        if not src_endcap_ok:
            reasons.append("endcap_missing_src")
        if not dst_endcap_ok:
            reasons.append("endcap_missing_dst")
        if not bool(out.get("xsec_support_available_src", False)):
            reasons.append("xsec_support_empty_src")
        if not bool(out.get("xsec_support_available_dst", False)):
            reasons.append("xsec_support_empty_dst")
        out["reason"] = ",".join(reasons) if reasons else "traj_surface_insufficient"
    out["timing_ms"] = float((perf_counter() - t0) * 1000.0)
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
    traj_surface_hint: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], set[str], set[str], list[dict[str, Any]]]:
    result: dict[str, Any] = {
        "traj_surface_enforced": False,
        "traj_surface_geom_type": None,
        "traj_surface_area_m2": None,
        "traj_surface_component_count": 0,
        "traj_surface_valid_slices_ratio": 0.0,
        "traj_surface_covered_length_ratio": 0.0,
        "traj_surface_covered_station_length_m": 0.0,
        "endcap_valid_ratio_src": 0.0,
        "endcap_valid_ratio_dst": 0.0,
        "endcap_width_src_before_m": None,
        "endcap_width_src_after_m": None,
        "endcap_width_dst_before_m": None,
        "endcap_width_dst_after_m": None,
        "endcap_width_clamped_src_count": 0,
        "endcap_width_clamped_dst_count": 0,
        "xsec_support_available_src": False,
        "xsec_support_available_dst": False,
        "traj_surface_slice_half_win_used_hist": {},
        "traj_surface_slice_half_win_levels": [],
        "traj_in_ratio": None,
        "traj_in_ratio_est": None,
        "endpoint_in_traj_surface_src": None,
        "endpoint_in_traj_surface_dst": None,
        "endpoint_in_traj_surface_src_raw": None,
        "endpoint_in_traj_surface_dst_raw": None,
        "endpoint_dist_to_traj_surface_src_m": None,
        "endpoint_dist_to_traj_surface_dst_m": None,
        "endpoint_traj_surface_tolerance_used_src": False,
        "endpoint_traj_surface_tolerance_used_dst": False,
        "_traj_surface_geom_metric": None,
    }
    soft_flags: set[str] = set()
    hard_flags: set[str] = set()
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
        return result, soft_flags, hard_flags, breakpoints

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
        return result, soft_flags, hard_flags, breakpoints

    surface = None
    stations = np.empty((0,), dtype=np.float64)
    valid_mask = np.empty((0,), dtype=bool)
    valid_slices = 0
    total_slices = 0
    slice_valid_ratio = 0.0
    covered_len_ratio = 0.0
    covered_station_length = 0.0
    endcap_valid_ratio_src = 0.0
    endcap_valid_ratio_dst = 0.0
    endcap_width_src_before = None
    endcap_width_src_after = None
    endcap_width_dst_before = None
    endcap_width_dst_after = None
    endcap_width_clamped_src_count = 0
    endcap_width_clamped_dst_count = 0
    xsec_support_available_src = False
    xsec_support_available_dst = False
    unique_traj_count = 0

    hint = traj_surface_hint if isinstance(traj_surface_hint, dict) else None
    if hint is not None:
        surface = hint.get("surface_metric")
        valid_slices = int(hint.get("valid_slices", 0))
        total_slices = int(hint.get("total_slices", 0))
        slice_valid_ratio = float(hint.get("slice_valid_ratio", 0.0))
        covered_len_ratio = float(hint.get("covered_length_ratio", 0.0))
        covered_station_length = float(hint.get("covered_station_length_m", 0.0))
        endcap_valid_ratio_src = float(hint.get("endcap_valid_ratio_src", 0.0))
        endcap_valid_ratio_dst = float(hint.get("endcap_valid_ratio_dst", 0.0))
        endcap_width_src_before = hint.get("endcap_width_src_before_m")
        endcap_width_src_after = hint.get("endcap_width_src_after_m")
        endcap_width_dst_before = hint.get("endcap_width_dst_before_m")
        endcap_width_dst_after = hint.get("endcap_width_dst_after_m")
        endcap_width_clamped_src_count = int(hint.get("endcap_width_clamped_src_count", 0))
        endcap_width_clamped_dst_count = int(hint.get("endcap_width_clamped_dst_count", 0))
        xsec_support_available_src = bool(hint.get("xsec_support_available_src", False))
        xsec_support_available_dst = bool(hint.get("xsec_support_available_dst", False))
        unique_traj_count = int(hint.get("unique_traj_count", 0))
        result["traj_surface_slice_half_win_used_hist"] = dict(hint.get("slice_half_win_used_hist") or {})
        result["traj_surface_slice_half_win_levels"] = [
            float(v) for v in (hint.get("slice_half_win_levels") or [])
        ]
        st = hint.get("_stations")
        vm = hint.get("_valid_mask")
        if isinstance(st, np.ndarray):
            stations = np.asarray(st, dtype=np.float64)
        if isinstance(vm, np.ndarray):
            valid_mask = np.asarray(vm, dtype=bool)
    else:
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
            return result, soft_flags, hard_flags, breakpoints
        built = _build_traj_surface_from_refline(
            ref_line=ref_line,
            traj_xy=traj_xy,
            gore_zone_metric=gore_zone_metric,
            params=params,
        )
        surface = built.get("surface")
        stations = np.asarray(built.get("stations"), dtype=np.float64)
        valid_mask = np.asarray(built.get("valid_mask"), dtype=bool)
        valid_slices = int(built.get("valid_slices", 0))
        total_slices = int(built.get("total_slices", 0))
        slice_valid_ratio = float(built.get("slice_valid_ratio", 0.0))
        covered_len_ratio = float(built.get("covered_length_ratio", 0.0))
        covered_station_length = float(built.get("covered_station_length_m", 0.0))
        endcap_valid_ratio_src = float(built.get("endcap_valid_ratio_src", 0.0))
        endcap_valid_ratio_dst = float(built.get("endcap_valid_ratio_dst", 0.0))
        endcap_width_src_before = built.get("endcap_width_src_before_m")
        endcap_width_src_after = built.get("endcap_width_src_after_m")
        endcap_width_dst_before = built.get("endcap_width_dst_before_m")
        endcap_width_dst_after = built.get("endcap_width_dst_after_m")
        endcap_width_clamped_src_count = int(built.get("endcap_width_clamped_src_count", 0))
        endcap_width_clamped_dst_count = int(built.get("endcap_width_clamped_dst_count", 0))
        xsec_support_available_src = bool(surface is not None and not surface.is_empty)
        xsec_support_available_dst = bool(surface is not None and not surface.is_empty)
        result["traj_surface_slice_half_win_used_hist"] = dict(built.get("slice_half_win_used_hist") or {})
        result["traj_surface_slice_half_win_levels"] = [float(v) for v in built.get("slice_half_win_levels") or []]

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
        return result, soft_flags, hard_flags, breakpoints

    surface = _normalize_surface_polygon(surface)
    result["_traj_surface_geom_metric"] = surface
    result["traj_surface_valid_slices"] = int(valid_slices)
    result["traj_surface_total_slices"] = int(total_slices)
    result["traj_surface_slice_valid_ratio"] = float(slice_valid_ratio)
    result["traj_surface_covered_length_ratio"] = float(covered_len_ratio)
    result["traj_surface_covered_station_length_m"] = float(covered_station_length)
    result["traj_surface_unique_traj_count"] = int(unique_traj_count)
    result["traj_surface_valid_slices_ratio"] = float(slice_valid_ratio)
    result["traj_surface_geom_type"] = str(getattr(surface, "geom_type", "")) if surface is not None else None
    result["traj_surface_area_m2"] = (float(surface.area) if surface is not None and not surface.is_empty else None)
    result["traj_surface_component_count"] = int(_surface_component_count(surface))
    result["endcap_valid_ratio_src"] = float(endcap_valid_ratio_src)
    result["endcap_valid_ratio_dst"] = float(endcap_valid_ratio_dst)
    result["endcap_width_src_before_m"] = endcap_width_src_before
    result["endcap_width_src_after_m"] = endcap_width_src_after
    result["endcap_width_dst_before_m"] = endcap_width_dst_before
    result["endcap_width_dst_after_m"] = endcap_width_dst_after
    result["endcap_width_clamped_src_count"] = int(endcap_width_clamped_src_count)
    result["endcap_width_clamped_dst_count"] = int(endcap_width_clamped_dst_count)
    src_nodeid = int(road.get("src_nodeid")) if road.get("src_nodeid") is not None else None
    dst_nodeid = int(road.get("dst_nodeid")) if road.get("dst_nodeid") is not None else None
    xsec_src_geom = None
    xsec_dst_geom = None
    if src_nodeid is not None or dst_nodeid is not None:
        for cs in patch_inputs.intersection_lines:
            nid = int(cs.nodeid)
            if src_nodeid is not None and nid == src_nodeid:
                xsec_src_geom = cs.geometry_metric
            if dst_nodeid is not None and nid == dst_nodeid:
                xsec_dst_geom = cs.geometry_metric
            if xsec_src_geom is not None and xsec_dst_geom is not None:
                break
    if xsec_src_geom is not None:
        xsec_support_available_src = _xsec_has_surface_support(
            xsec=xsec_src_geom,
            surface_metric=surface,
            gore_zone_metric=gore_zone_metric,
            buffer_m=float(params.get("SURF_BUF_M", 1.0)),
        )
    if xsec_dst_geom is not None:
        xsec_support_available_dst = _xsec_has_surface_support(
            xsec=xsec_dst_geom,
            surface_metric=surface,
            gore_zone_metric=gore_zone_metric,
            buffer_m=float(params.get("SURF_BUF_M", 1.0)),
        )
    result["xsec_support_available_src"] = bool(xsec_support_available_src)
    result["xsec_support_available_dst"] = bool(xsec_support_available_dst)

    in_ratio_est = None
    endpoint_in_src_raw = None
    endpoint_in_dst_raw = None
    endpoint_in_src = None
    endpoint_in_dst = None
    endpoint_dist_src_m = None
    endpoint_dist_dst_m = None
    endpoint_tol_used_src = False
    endpoint_tol_used_dst = False
    if surface is not None and not surface.is_empty:
        try:
            inter_len = float(road_line.intersection(surface).length)
        except Exception:
            inter_len = 0.0
        in_ratio_est = float(inter_len / max(1e-6, float(road_line.length)))
        p_src = Point(road_line.coords[0])
        p_dst = Point(road_line.coords[-1])
        endpoint_in_src_raw = bool(surface.buffer(1e-6).covers(p_src))
        endpoint_in_dst_raw = bool(surface.buffer(1e-6).covers(p_dst))
        endpoint_in_src = bool(endpoint_in_src_raw)
        endpoint_in_dst = bool(endpoint_in_dst_raw)
        try:
            endpoint_dist_src_m = float(max(0.0, p_src.distance(surface)))
        except Exception:
            endpoint_dist_src_m = None
        try:
            endpoint_dist_dst_m = float(max(0.0, p_dst.distance(surface)))
        except Exception:
            endpoint_dist_dst_m = None
        endpoint_hole_tol_m = float(max(0.0, params.get("TRAJ_SURF_ENDPOINT_HOLE_TOL_M", 2.0)))
        endpoint_hole_ratio_min = float(max(0.0, min(1.0, params.get("TRAJ_SURF_ENDPOINT_HOLE_IN_RATIO_MIN", 0.99))))
        drivezone_ok_src = road.get("endpoint_in_drivezone_src") is not False
        drivezone_ok_dst = road.get("endpoint_in_drivezone_dst") is not False
        if (
            (endpoint_in_src is False)
            and endpoint_dist_src_m is not None
            and np.isfinite(endpoint_dist_src_m)
            and endpoint_dist_src_m <= endpoint_hole_tol_m + 1e-6
            and in_ratio_est is not None
            and float(in_ratio_est) >= endpoint_hole_ratio_min
            and bool(drivezone_ok_src)
        ):
            endpoint_in_src = True
            endpoint_tol_used_src = True
        if (
            (endpoint_in_dst is False)
            and endpoint_dist_dst_m is not None
            and np.isfinite(endpoint_dist_dst_m)
            and endpoint_dist_dst_m <= endpoint_hole_tol_m + 1e-6
            and in_ratio_est is not None
            and float(in_ratio_est) >= endpoint_hole_ratio_min
            and bool(drivezone_ok_dst)
        ):
            endpoint_in_dst = True
            endpoint_tol_used_dst = True

    min_slice_ratio = max(float(params["TRAJ_SURF_MIN_SLICE_VALID_RATIO"]), 0.60)
    min_cov_ratio = max(
        float(params["TRAJ_SURF_MIN_COVERED_LEN_RATIO"]),
        float(params.get("TRAJ_SURF_ENFORCE_MIN_COVERED_LEN_RATIO", 0.90)),
    )
    min_endcap_ratio = max(0.0, min(1.0, float(params.get("ENDCAP_MIN_VALID_RATIO", 0.5))))
    min_unique = int(params["TRAJ_SURF_MIN_UNIQUE_TRAJ"])
    src_endcap_ok = float(endcap_valid_ratio_src) >= min_endcap_ratio
    dst_endcap_ok = float(endcap_valid_ratio_dst) >= min_endcap_ratio
    sufficient = (
        (valid_slices >= 2)
        and (slice_valid_ratio >= min_slice_ratio)
        and (covered_len_ratio >= min_cov_ratio)
        and bool(src_endcap_ok)
        and bool(dst_endcap_ok)
        and bool(xsec_support_available_src)
        and bool(xsec_support_available_dst)
        and (unique_traj_count >= min_unique)
        and (surface is not None and not surface.is_empty)
        and (float(result.get("traj_surface_area_m2") or 0.0) > 0.0)
    )

    result["traj_in_ratio_est"] = in_ratio_est
    result["endpoint_in_traj_surface_src"] = endpoint_in_src
    result["endpoint_in_traj_surface_dst"] = endpoint_in_dst
    result["endpoint_in_traj_surface_src_raw"] = endpoint_in_src_raw
    result["endpoint_in_traj_surface_dst_raw"] = endpoint_in_dst_raw
    result["endpoint_dist_to_traj_surface_src_m"] = endpoint_dist_src_m
    result["endpoint_dist_to_traj_surface_dst_m"] = endpoint_dist_dst_m
    result["endpoint_traj_surface_tolerance_used_src"] = bool(endpoint_tol_used_src)
    result["endpoint_traj_surface_tolerance_used_dst"] = bool(endpoint_tol_used_dst)

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
        if not src_endcap_ok:
            reasons.append("endcap_missing_src")
        if not dst_endcap_ok:
            reasons.append("endcap_missing_dst")
        if not bool(xsec_support_available_src):
            reasons.append("xsec_support_empty_src")
        if not bool(xsec_support_available_dst):
            reasons.append("xsec_support_empty_dst")
        if unique_traj_count < min_unique:
            reasons.append("unique_traj_low")
        if surface is None or surface.is_empty:
            reasons.append("surface_empty")
        elif float(result.get("traj_surface_area_m2") or 0.0) <= 0.0:
            reasons.append("surface_area_zero")
        bp = build_breakpoint(
            road=road,
            reason=SOFT_TRAJ_SURFACE_INSUFFICIENT,
            severity="soft",
            hint=(
                f"valid_slices={valid_slices}/{total_slices};"
                f"slice_valid_ratio={slice_valid_ratio:.3f};"
                f"covered_length_ratio={covered_len_ratio:.3f};"
                f"endcap_valid_ratio_src={endcap_valid_ratio_src:.3f};"
                f"endcap_valid_ratio_dst={endcap_valid_ratio_dst:.3f};"
                f"xsec_support_src={bool(xsec_support_available_src)};"
                f"xsec_support_dst={bool(xsec_support_available_dst)};"
                f"unique_traj_count={unique_traj_count};"
                f"geom_type={result.get('traj_surface_geom_type')};"
                f"area_m2={result.get('traj_surface_area_m2')};"
                f"hint_reason={(hint.get('reason') if isinstance(hint, dict) else None)};"
                f"reasons={','.join(reasons) if reasons else 'na'}"
            ),
        )
        bp["traj_surface_enforced"] = False
        bp["slice_valid_ratio"] = float(slice_valid_ratio)
        bp["covered_length_ratio"] = float(covered_len_ratio)
        bp["unique_traj_count"] = int(unique_traj_count)
        breakpoints.append(bp)
        return result, soft_flags, hard_flags, breakpoints

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
        hard_flags.add(SOFT_ROAD_OUTSIDE_TRAJ_SURFACE)
        bp = build_breakpoint(
            road=road,
            reason=SOFT_ROAD_OUTSIDE_TRAJ_SURFACE,
            severity="hard",
            hint=(
                f"in_ratio={in_ratio_est if in_ratio_est is not None else 'na'};"
                f"endpoint_src={endpoint_in_src};endpoint_dst={endpoint_in_dst};"
                f"endpoint_src_raw={endpoint_in_src_raw};endpoint_dst_raw={endpoint_in_dst_raw};"
                f"endpoint_src_dist_m={endpoint_dist_src_m if endpoint_dist_src_m is not None else 'na'};"
                f"endpoint_dst_dist_m={endpoint_dist_dst_m if endpoint_dist_dst_m is not None else 'na'};"
                f"endpoint_tol_src={bool(endpoint_tol_used_src)};endpoint_tol_dst={bool(endpoint_tol_used_dst)};"
                f"threshold={in_ratio_min:.2f}"
            ),
        )
        bp["traj_surface_enforced"] = True
        bp["traj_in_ratio"] = in_ratio_est
        breakpoints.append(bp)

    return result, soft_flags, hard_flags, breakpoints


def _to_finite_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
    except Exception:
        return float(default)
    if not np.isfinite(f):
        return float(default)
    return float(f)


def _drivezone_gate_diagnostics(
    *,
    road_line: LineString | None,
    drivezone_zone_metric: BaseGeometry | None,
    gore_zone_metric: BaseGeometry | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "endpoint_in_drivezone_src": None,
        "endpoint_in_drivezone_dst": None,
        "road_outside_drivezone_len_m": None,
        "road_in_drivezone_ratio": None,
    }
    if not isinstance(road_line, LineString) or road_line.is_empty:
        return out
    if drivezone_zone_metric is None or drivezone_zone_metric.is_empty:
        return out

    p0 = Point(road_line.coords[0])
    p1 = Point(road_line.coords[-1])
    try:
        out["endpoint_in_drivezone_src"] = bool(drivezone_zone_metric.buffer(1e-6).covers(p0))
    except Exception:
        out["endpoint_in_drivezone_src"] = None
    try:
        out["endpoint_in_drivezone_dst"] = bool(drivezone_zone_metric.buffer(1e-6).covers(p1))
    except Exception:
        out["endpoint_in_drivezone_dst"] = None

    passable_zone: BaseGeometry = drivezone_zone_metric
    if gore_zone_metric is not None and (not gore_zone_metric.is_empty):
        try:
            diff = drivezone_zone_metric.difference(gore_zone_metric)
            if diff is not None and not diff.is_empty:
                passable_zone = diff
        except Exception:
            pass

    try:
        outside_len = float(max(0.0, road_line.difference(passable_zone).length))
    except Exception:
        outside_len = float(max(0.0, road_line.length))
    out["road_outside_drivezone_len_m"] = float(outside_len)
    try:
        in_len = float(max(0.0, road_line.intersection(passable_zone).length))
    except Exception:
        in_len = float(max(0.0, road_line.length - outside_len))
    denom = float(max(1e-6, road_line.length))
    out["road_in_drivezone_ratio"] = float(max(0.0, min(1.0, in_len / denom)))
    return out


def _evaluate_candidate_road(
    *,
    src: int,
    dst: int,
    src_type: str,
    dst_type: str,
    support: PairSupport,
    parent_support: PairSupport,
    cluster_id: int,
    neighbor_search_pass: int,
    src_xsec: LineString,
    dst_xsec: LineString,
    src_out_degree: int,
    dst_in_degree: int,
    lane_boundaries_metric: Sequence[LineString],
    surface_points_xyz: np.ndarray,
    non_ground_xy: np.ndarray,
    patch_inputs: PatchInputs,
    gore_zone_metric: BaseGeometry | None,
    params: dict[str, Any],
    traj_surface_hint: dict[str, Any],
    shape_ref_hint_metric: LineString | None = None,
) -> dict[str, Any]:
    t0_center = perf_counter()
    center = estimate_centerline(
        support=support,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        src_type=src_type,
        dst_type=dst_type,
        src_out_degree=int(src_out_degree),
        dst_in_degree=int(dst_in_degree),
        lane_boundaries_metric=lane_boundaries_metric,
        surface_points_xyz=surface_points_xyz,
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
        lb_outside_lambda=float(params.get("LAMBDA_OUTSIDE", 5.0)),
        lb_outside_edge_ratio_max=float(params.get("OUTSIDE_EDGE_RATIO_MAX", 1.0)),
        lb_surface_node_buffer_m=float(params.get("SURF_NODE_BUFFER_M", 2.0)),
        trend_fit_win_m=float(params["TREND_FIT_WIN_M"]),
        traj_surface_metric=traj_surface_hint.get("surface_metric"),
        traj_surface_enforced=bool(traj_surface_hint.get("traj_surface_enforced", False)),
        drivezone_zone_metric=patch_inputs.drivezone_zone_metric,
        divstrip_zone_metric=gore_zone_metric,
        xsec_anchor_window_m=float(params.get("XSEC_ANCHOR_WINDOW_M", 15.0)),
        xsec_endpoint_max_dist_m=float(params.get("XSEC_ENDPOINT_MAX_DIST_M", 20.0)),
        xsec_ref_half_len_m=float(params.get("XSEC_REF_HALF_LEN_M", 80.0)),
        xsec_road_sample_step_m=float(params.get("XSEC_ROAD_SAMPLE_STEP_M", 1.0)),
        xsec_road_nonpass_k=int(params.get("XSEC_ROAD_NONPASS_K", 6)),
        xsec_road_evidence_radius_m=float(params.get("XSEC_ROAD_EVIDENCE_RADIUS_M", 1.0)),
        xsec_road_min_ground_pts=int(params.get("XSEC_ROAD_MIN_GROUND_PTS", 1)),
        xsec_road_min_traj_pts=int(params.get("XSEC_ROAD_MIN_TRAJ_PTS", 1)),
        xsec_core_band_m=float(params.get("XSEC_CORE_BAND_M", 20.0)),
        xsec_shift_step_m=float(params.get("XSEC_SHIFT_STEP_M", 5.0)),
        xsec_fallback_short_half_len_m=float(params.get("XSEC_FALLBACK_SHORT_HALF_LEN_M", 15.0)),
        xsec_barrier_min_ng_count=int(params.get("XSEC_BARRIER_MIN_NG_COUNT", 2)),
        xsec_barrier_min_len_m=float(params.get("XSEC_BARRIER_MIN_LEN_M", 4.0)),
        xsec_barrier_along_len_m=float(params.get("XSEC_BARRIER_ALONG_LEN_M", 60.0)),
        xsec_barrier_along_width_m=float(params.get("XSEC_BARRIER_ALONG_WIDTH_M", 2.5)),
        xsec_barrier_bin_step_m=float(params.get("XSEC_BARRIER_BIN_STEP_M", 2.0)),
        xsec_barrier_occ_ratio_min=float(params.get("XSEC_BARRIER_OCC_RATIO_MIN", 0.65)),
        xsec_endcap_window_m=float(params.get("XSEC_ENDCAP_WINDOW_M", 60.0)),
        xsec_caseb_pre_m=float(params.get("XSEC_CASEB_PRE_M", 3.0)),
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
        non_ground_xy=non_ground_xy,
        shape_ref_hint_metric=shape_ref_hint_metric,
    )
    t_center_ms = float((perf_counter() - t0_center) * 1000.0)

    road = _make_base_road_record(
        src=src,
        dst=dst,
        support=support,
        src_type=src_type,
        dst_type=dst_type,
        neighbor_search_pass=int(neighbor_search_pass),
    )
    road["candidate_cluster_id"] = int(cluster_id)
    road["chosen_cluster_id"] = None
    road["cluster_count"] = int(parent_support.cluster_count)
    road["main_cluster_ratio"] = float(parent_support.main_cluster_ratio)
    road["cluster_sep_m_est"] = parent_support.cluster_sep_m_est
    road["main_cluster_id"] = int(parent_support.main_cluster_id)
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
    road["endpoint_proj_dist_to_core_m_src"] = center.endpoint_proj_dist_to_core_m_src
    road["endpoint_proj_dist_to_core_m_dst"] = center.endpoint_proj_dist_to_core_m_dst
    road["endpoint_snap_dist_src_before_m"] = center.diagnostics.get("endpoint_snap_dist_src_before_m")
    road["endpoint_snap_dist_src_after_m"] = center.diagnostics.get("endpoint_snap_dist_src_after_m")
    road["endpoint_snap_dist_dst_before_m"] = center.diagnostics.get("endpoint_snap_dist_dst_before_m")
    road["endpoint_snap_dist_dst_after_m"] = center.diagnostics.get("endpoint_snap_dist_dst_after_m")
    road["endpoint_dist_to_xsec_src_m"] = center.diagnostics.get("endpoint_dist_to_xsec_src_m")
    road["endpoint_dist_to_xsec_dst_m"] = center.diagnostics.get("endpoint_dist_to_xsec_dst_m")
    road["xsec_target_mode_src"] = center.diagnostics.get("xsec_target_mode_src")
    road["xsec_target_mode_dst"] = center.diagnostics.get("xsec_target_mode_dst")
    road["xsec_road_selected_by_src"] = center.diagnostics.get("xsec_road_selected_by_src")
    road["xsec_road_selected_by_dst"] = center.diagnostics.get("xsec_road_selected_by_dst")
    road["xsec_selected_by_src"] = road["xsec_road_selected_by_src"]
    road["xsec_selected_by_dst"] = road["xsec_road_selected_by_dst"]
    road["xsec_shift_used_m_src"] = center.diagnostics.get("xsec_shift_used_m_src")
    road["xsec_shift_used_m_dst"] = center.diagnostics.get("xsec_shift_used_m_dst")
    road["xsec_mid_to_ref_m_src"] = center.diagnostics.get("xsec_mid_to_ref_m_src")
    road["xsec_mid_to_ref_m_dst"] = center.diagnostics.get("xsec_mid_to_ref_m_dst")
    road["xsec_intersects_ref_src"] = center.diagnostics.get("xsec_intersects_ref_src")
    road["xsec_intersects_ref_dst"] = center.diagnostics.get("xsec_intersects_ref_dst")
    road["xsec_ref_intersection_n_src"] = center.diagnostics.get("xsec_ref_intersection_n_src")
    road["xsec_ref_intersection_n_dst"] = center.diagnostics.get("xsec_ref_intersection_n_dst")
    road["xsec_barrier_candidate_count_src"] = center.diagnostics.get("xsec_barrier_candidate_count_src")
    road["xsec_barrier_candidate_count_dst"] = center.diagnostics.get("xsec_barrier_candidate_count_dst")
    road["xsec_barrier_final_count_src"] = center.diagnostics.get("xsec_barrier_final_count_src")
    road["xsec_barrier_final_count_dst"] = center.diagnostics.get("xsec_barrier_final_count_dst")
    road["xsec_road_selected_len_src_m"] = center.diagnostics.get("xsec_road_selected_len_src_m")
    road["xsec_road_selected_len_dst_m"] = center.diagnostics.get("xsec_road_selected_len_dst_m")
    road["xsec_road_all_geom_type_src"] = center.diagnostics.get("xsec_road_all_geom_type_src")
    road["xsec_road_all_geom_type_dst"] = center.diagnostics.get("xsec_road_all_geom_type_dst")
    road["xsec_road_left_extent_src_m"] = center.diagnostics.get("xsec_road_left_extent_src_m")
    road["xsec_road_right_extent_src_m"] = center.diagnostics.get("xsec_road_right_extent_src_m")
    road["xsec_road_left_extent_dst_m"] = center.diagnostics.get("xsec_road_left_extent_dst_m")
    road["xsec_road_right_extent_dst_m"] = center.diagnostics.get("xsec_road_right_extent_dst_m")
    road["lb_path_found"] = bool(center.lb_path_found)
    road["lb_path_edge_count"] = int(center.lb_path_edge_count)
    road["lb_path_length_m"] = center.lb_path_length_m
    road["lb_graph_edge_total"] = center.diagnostics.get("lb_graph_edge_total")
    road["lb_graph_edge_filtered"] = center.diagnostics.get("lb_graph_edge_filtered")
    road["endpoint_fallback_mode_src"] = center.diagnostics.get("endpoint_fallback_mode_src")
    road["endpoint_fallback_mode_dst"] = center.diagnostics.get("endpoint_fallback_mode_dst")
    road["xsec_support_len_src"] = center.diagnostics.get("xsec_support_len_src")
    road["xsec_support_len_dst"] = center.diagnostics.get("xsec_support_len_dst")
    road["xsec_support_disabled_due_to_insufficient_src"] = center.diagnostics.get(
        "xsec_support_disabled_due_to_insufficient_src"
    )
    road["xsec_support_disabled_due_to_insufficient_dst"] = center.diagnostics.get(
        "xsec_support_disabled_due_to_insufficient_dst"
    )
    road["xsec_support_empty_reason_src"] = center.diagnostics.get("xsec_support_empty_reason_src")
    road["xsec_support_empty_reason_dst"] = center.diagnostics.get("xsec_support_empty_reason_dst")
    road["endpoint_in_drivezone_src"] = center.diagnostics.get("endpoint_in_drivezone_src")
    road["endpoint_in_drivezone_dst"] = center.diagnostics.get("endpoint_in_drivezone_dst")
    road["xsec_samples_passable_ratio_src"] = center.diagnostics.get("xsec_samples_passable_ratio_src")
    road["xsec_samples_passable_ratio_dst"] = center.diagnostics.get("xsec_samples_passable_ratio_dst")
    road["s_anchor_src_m"] = center.diagnostics.get("s_anchor_src_m")
    road["s_anchor_dst_m"] = center.diagnostics.get("s_anchor_dst_m")
    road["s_end_src_m"] = center.diagnostics.get("s_end_src_m")
    road["s_end_dst_m"] = center.diagnostics.get("s_end_dst_m")
    road["anchor_window_m"] = center.diagnostics.get("anchor_window_m")
    road["offset_clamp_hit_ratio"] = center.diagnostics.get("offset_clamp_hit_ratio")
    road["offset_clamp_fallback_count"] = center.diagnostics.get("offset_clamp_fallback_count")
    road["_xsec_target_selected_src_metric"] = center.diagnostics.get("_xsec_target_selected_src_metric")
    road["_xsec_target_selected_dst_metric"] = center.diagnostics.get("_xsec_target_selected_dst_metric")
    road["_xsec_ref_src_metric"] = center.diagnostics.get("_xsec_ref_src_metric")
    road["_xsec_ref_dst_metric"] = center.diagnostics.get("_xsec_ref_dst_metric")
    road["_xsec_road_all_src_metric"] = center.diagnostics.get("_xsec_road_all_src_metric")
    road["_xsec_road_all_dst_metric"] = center.diagnostics.get("_xsec_road_all_dst_metric")
    road["_xsec_road_selected_src_metric"] = center.diagnostics.get("_xsec_road_selected_src_metric")
    road["_xsec_road_selected_dst_metric"] = center.diagnostics.get("_xsec_road_selected_dst_metric")
    road["_xsec_ref_shifted_candidates_src_metric"] = center.diagnostics.get("_xsec_ref_shifted_candidates_src_metric")
    road["_xsec_ref_shifted_candidates_dst_metric"] = center.diagnostics.get("_xsec_ref_shifted_candidates_dst_metric")
    road["_xsec_barrier_samples_src_metric"] = center.diagnostics.get("_xsec_barrier_samples_src_metric")
    road["_xsec_barrier_samples_dst_metric"] = center.diagnostics.get("_xsec_barrier_samples_dst_metric")
    road["_xsec_passable_samples_src_metric"] = center.diagnostics.get("_xsec_passable_samples_src_metric")
    road["_xsec_passable_samples_dst_metric"] = center.diagnostics.get("_xsec_passable_samples_dst_metric")
    road["_endpoint_before_src_metric"] = center.diagnostics.get("_endpoint_before_src_metric")
    road["_endpoint_before_dst_metric"] = center.diagnostics.get("_endpoint_before_dst_metric")
    road["_endpoint_after_src_metric"] = center.diagnostics.get("_endpoint_after_src_metric")
    road["_endpoint_after_dst_metric"] = center.diagnostics.get("_endpoint_after_dst_metric")
    road["traj_surface_hint_enforced"] = bool(traj_surface_hint.get("traj_surface_enforced", False))
    road["traj_surface_hint_axis_source"] = traj_surface_hint.get("axis_source")
    road["traj_surface_hint_reason"] = traj_surface_hint.get("reason")
    road["traj_surface_hint_valid_slices"] = int(traj_surface_hint.get("valid_slices", 0))
    road["traj_surface_hint_total_slices"] = int(traj_surface_hint.get("total_slices", 0))
    road["traj_surface_hint_slice_valid_ratio"] = _to_finite_float(traj_surface_hint.get("slice_valid_ratio"), 0.0)
    road["traj_surface_hint_covered_length_ratio"] = _to_finite_float(
        traj_surface_hint.get("covered_length_ratio"), 0.0
    )
    road["_traj_surface_geom_metric"] = traj_surface_hint.get("surface_metric")

    center_empty_like = bool(HARD_CENTER_EMPTY in set(center.hard_flags)) or (not _is_valid_linestring(center.centerline_metric))
    if center_empty_like:
        for tag, xsec in (("src", src_xsec), ("dst", dst_xsec)):
            sel_key = f"_xsec_road_selected_{tag}_metric"
            all_key = f"_xsec_road_all_{tag}_metric"
            ref_key = f"_xsec_ref_{tag}_metric"
            by_key = f"xsec_road_selected_by_{tag}"
            mode_key = f"xsec_target_mode_{tag}"
            len_key = f"xsec_road_selected_len_{tag}_m"
            all_type_key = f"xsec_road_all_geom_type_{tag}"
            ext_l_key = f"xsec_road_left_extent_{tag}_m"
            ext_r_key = f"xsec_road_right_extent_{tag}_m"
            if not _is_valid_linestring(road.get(sel_key)):
                road[sel_key] = xsec
            if not _is_valid_linestring(road.get(all_key)):
                road[all_key] = xsec
            if not _is_valid_linestring(road.get(ref_key)):
                road[ref_key] = xsec
            if not road.get(by_key):
                road[by_key] = "fallback_seed_due_center_empty"
            if not road.get(mode_key):
                road[mode_key] = "fallback_seed_due_center_empty"
            sel_geom = road.get(sel_key)
            if _is_valid_linestring(sel_geom):
                road[len_key] = float(sel_geom.length)
                road[all_type_key] = str(sel_geom.geom_type)
                road[ext_l_key] = float(0.5 * sel_geom.length)
                road[ext_r_key] = float(0.5 * sel_geom.length)
                n_inter = int(_count_line_intersections_simple(sel_geom, center.shape_ref_metric))
                road[f"xsec_ref_intersection_n_{tag}"] = int(max(0, n_inter))
                road[f"xsec_intersects_ref_{tag}"] = bool(n_inter > 0)
                if road.get(f"xsec_mid_to_ref_m_{tag}") is None:
                    road[f"xsec_mid_to_ref_m_{tag}"] = 0.0
                if road.get(f"xsec_shift_used_m_{tag}") is None:
                    road[f"xsec_shift_used_m_{tag}"] = None
                if road.get(f"xsec_barrier_candidate_count_{tag}") is None:
                    road[f"xsec_barrier_candidate_count_{tag}"] = 0
                if road.get(f"xsec_barrier_final_count_{tag}") is None:
                    road[f"xsec_barrier_final_count_{tag}"] = 0
                road[f"_xsec_target_selected_{tag}_metric"] = sel_geom
                road[f"xsec_selected_by_{tag}"] = road.get(by_key)

    soft_flags = set(center.soft_flags)
    hard_flags = set(center.hard_flags)
    hard_flags.update(set(support.hard_anomalies))
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
    if bool(center.diagnostics.get("endpoint_off_anchor_src", False)) or bool(
        center.diagnostics.get("endpoint_off_anchor_dst", False)
    ):
        hard_flags.add(HARD_ENDPOINT_OFF_ANCHOR)
    if not bool(traj_surface_hint.get("traj_surface_enforced", False)):
        soft_flags.add(SOFT_TRAJ_SURFACE_INSUFFICIENT)

    road_line = center.centerline_metric
    centerline_fallback_used = False
    center_empty_downgraded = False
    if not (isinstance(road_line, LineString) and (not road_line.is_empty)):
        fallback_line = _fallback_geometry_from_shape_ref(
            shape_ref_line=center.shape_ref_metric,
            src_xsec=src_xsec,
            dst_xsec=dst_xsec,
        )
        if isinstance(fallback_line, LineString) and (not fallback_line.is_empty):
            road_line = fallback_line
            centerline_fallback_used = True
            road["endpoint_fallback_mode_src"] = str(road.get("endpoint_fallback_mode_src") or "shape_ref_substring_fallback")
            road["endpoint_fallback_mode_dst"] = str(road.get("endpoint_fallback_mode_dst") or "shape_ref_substring_fallback")
    if _is_valid_linestring(road_line):
        src_sel_metric = road.get("_xsec_road_selected_src_metric")
        dst_sel_metric = road.get("_xsec_road_selected_dst_metric")
        src_sel = src_sel_metric if _is_valid_linestring(src_sel_metric) else src_xsec
        dst_sel = dst_sel_metric if _is_valid_linestring(dst_sel_metric) else dst_xsec
        if centerline_fallback_used or road.get("_endpoint_after_src_metric") is None or road.get("_endpoint_after_dst_metric") is None:
            snap_cap_m = float(max(1.0, params.get("XSEC_ENDPOINT_MAX_DIST_M", 20.0)))
            snapped_line, src_after_pt, dst_after_pt, src_before_dist, dst_before_dist = _fallback_bind_endpoints_to_xsec(
                line=road_line,
                src_xsec=src_sel,
                dst_xsec=dst_sel,
                gore_zone_metric=gore_zone_metric,
                snap_max_m=snap_cap_m,
            )
            if _is_valid_linestring(snapped_line):
                road_line = snapped_line
            if isinstance(src_after_pt, Point) and not src_after_pt.is_empty:
                road["_endpoint_after_src_metric"] = src_after_pt
                road["endpoint_dist_to_xsec_src_m"] = float(src_after_pt.distance(src_sel))
                if road.get("endpoint_snap_dist_src_before_m") is None and src_before_dist is not None:
                    road["endpoint_snap_dist_src_before_m"] = float(src_before_dist)
                road["endpoint_snap_dist_src_after_m"] = float(road["endpoint_dist_to_xsec_src_m"])
                if road.get("_endpoint_before_src_metric") is None:
                    road["_endpoint_before_src_metric"] = Point(road_line.coords[0])
            if isinstance(dst_after_pt, Point) and not dst_after_pt.is_empty:
                road["_endpoint_after_dst_metric"] = dst_after_pt
                road["endpoint_dist_to_xsec_dst_m"] = float(dst_after_pt.distance(dst_sel))
                if road.get("endpoint_snap_dist_dst_before_m") is None and dst_before_dist is not None:
                    road["endpoint_snap_dist_dst_before_m"] = float(dst_before_dist)
                road["endpoint_snap_dist_dst_after_m"] = float(road["endpoint_dist_to_xsec_dst_m"])
                if road.get("_endpoint_before_dst_metric") is None:
                    road["_endpoint_before_dst_metric"] = Point(road_line.coords[-1])
    if centerline_fallback_used and HARD_CENTER_EMPTY in hard_flags and _is_valid_linestring(road_line):
        endpoint_tol = float(max(0.5, float(params.get("ENDPOINT_ON_XSEC_TOL_M", 1.0))))
        src_dist = _to_finite_float(road.get("endpoint_dist_to_xsec_src_m"), float("nan"))
        dst_dist = _to_finite_float(road.get("endpoint_dist_to_xsec_dst_m"), float("nan"))
        if np.isfinite(src_dist) and np.isfinite(dst_dist) and src_dist <= endpoint_tol + 1e-6 and dst_dist <= endpoint_tol + 1e-6:
            hard_flags.discard(HARD_CENTER_EMPTY)
            center_empty_downgraded = True
    road["centerline_fallback_geometry_used"] = bool(centerline_fallback_used)
    road["center_estimate_empty_downgraded"] = bool(center_empty_downgraded)
    if road_line is not None:
        road["length_m"] = float(road_line.length)
        seg_idx, seg_len = _max_segment_detail(road_line)
        road["max_segment_idx"] = seg_idx
        road["max_segment_m"] = float(seg_len) if seg_len is not None else compute_max_segment_m(road_line)
        if len(road_line.coords) >= 2:
            c0 = np.asarray(road_line.coords[0], dtype=np.float64)
            c1 = np.asarray(road_line.coords[1], dtype=np.float64)
            road["seg_index0_len_m"] = float(np.linalg.norm(c1 - c0))
        else:
            road["seg_index0_len_m"] = None
    else:
        road["length_m"] = 0.0
        road["max_segment_m"] = None
        road["max_segment_idx"] = None
        road["seg_index0_len_m"] = None

    road_line, divstrip_inter_retry_len, divstrip_retry_mode = _enforce_gore_free_geometry(
        road_line=road_line,
        gore_zone_metric=gore_zone_metric,
        shape_ref_line=center.shape_ref_metric,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
    )
    road["divstrip_constructor_retry_mode"] = divstrip_retry_mode
    if isinstance(road_line, LineString) and not road_line.is_empty:
        road["_geometry_metric"] = road_line
        road["length_m"] = float(road_line.length)
        seg_idx, seg_len = _max_segment_detail(road_line)
        road["max_segment_idx"] = seg_idx
        road["max_segment_m"] = float(seg_len) if seg_len is not None else compute_max_segment_m(road_line)
        if len(road_line.coords) >= 2:
            c0 = np.asarray(road_line.coords[0], dtype=np.float64)
            c1 = np.asarray(road_line.coords[1], dtype=np.float64)
            road["seg_index0_len_m"] = float(np.linalg.norm(c1 - c0))
        else:
            road["seg_index0_len_m"] = None
    else:
        road_line = None
        road["length_m"] = 0.0
        road["max_segment_m"] = None
        road["max_segment_idx"] = None
        road["seg_index0_len_m"] = None
        hard_flags.add(HARD_DIVSTRIP_INTERSECT)

    bridge_outside_ratio, bridge_intersects_divstrip, bridge_dist_to_lb = _bridge_segment_diagnostics(
        road_line=road_line,
        max_segment_idx=road.get("max_segment_idx"),
        traj_surface_metric=road.get("_traj_surface_geom_metric"),
        gore_zone_metric=gore_zone_metric,
        lb_shape_ref_metric=center.shape_ref_metric,
    )
    road["bridge_seg_outside_ratio"] = bridge_outside_ratio
    road["bridge_seg_intersects_divstrip"] = bool(bridge_intersects_divstrip)
    road["bridge_seg_dist_to_lb_m"] = bridge_dist_to_lb

    max_seg_f = _to_finite_float(road.get("max_segment_m"), float("nan"))
    if np.isfinite(max_seg_f) and max_seg_f > float(params["BRIDGE_MAX_SEG_M"]):
        bridge_bad = bool(bridge_intersects_divstrip)
        if bridge_outside_ratio is not None and float(bridge_outside_ratio) > 0.30:
            bridge_bad = True
        if bridge_dist_to_lb is not None and float(bridge_dist_to_lb) > 20.0:
            bridge_bad = True
        if bridge_bad:
            hard_flags.add(HARD_BRIDGE_SEGMENT)

    divstrip_inter_len = 0.0
    if road_line is not None and gore_zone_metric is not None and (not gore_zone_metric.is_empty):
        try:
            divstrip_inter_len = float(road_line.intersection(gore_zone_metric).length)
        except Exception:
            divstrip_inter_len = 0.0
        if divstrip_inter_len > 1e-6:
            hard_flags.add(HARD_DIVSTRIP_INTERSECT)
    divstrip_inter_len = max(float(divstrip_inter_len), float(divstrip_inter_retry_len))
    road["divstrip_intersect_len_m"] = float(max(0.0, divstrip_inter_len))

    drivezone_diag = _drivezone_gate_diagnostics(
        road_line=road_line,
        drivezone_zone_metric=patch_inputs.drivezone_zone_metric,
        gore_zone_metric=gore_zone_metric,
    )
    road["road_outside_drivezone_len_m"] = drivezone_diag.get("road_outside_drivezone_len_m")
    road["road_in_drivezone_ratio"] = drivezone_diag.get("road_in_drivezone_ratio")
    if road.get("endpoint_in_drivezone_src") is None:
        road["endpoint_in_drivezone_src"] = drivezone_diag.get("endpoint_in_drivezone_src")
    if road.get("endpoint_in_drivezone_dst") is None:
        road["endpoint_in_drivezone_dst"] = drivezone_diag.get("endpoint_in_drivezone_dst")
    try:
        outside_drivezone_len = float(road.get("road_outside_drivezone_len_m"))
    except Exception:
        outside_drivezone_len = 0.0
    endpoint_drivezone_ok = (
        road.get("endpoint_in_drivezone_src") is not False and road.get("endpoint_in_drivezone_dst") is not False
    )
    if outside_drivezone_len > 1e-6 or not endpoint_drivezone_ok:
        hard_flags.add(HARD_ROAD_OUTSIDE_DRIVEZONE)

    candidate_hard_breakpoints: list[dict[str, Any]] = []
    candidate_soft_breakpoints: list[dict[str, Any]] = []
    t_gate_ms = 0.0
    if road_line is not None:
        t0_gate = perf_counter()
        (
            traj_surface_info,
            traj_surface_soft,
            traj_surface_hard,
            traj_surface_breakpoints,
        ) = _eval_traj_surface_gate(
            road=road,
            road_line=road_line,
            shape_ref_line=center.shape_ref_metric,
            support=support,
            patch_inputs=patch_inputs,
            gore_zone_metric=gore_zone_metric,
            params=params,
            traj_surface_hint=traj_surface_hint,
        )
        t_gate_ms = float((perf_counter() - t0_gate) * 1000.0)
        road.update(traj_surface_info)
        soft_flags.update(traj_surface_soft)
        hard_flags.update(traj_surface_hard)
        for bp in traj_surface_breakpoints:
            if str(bp.get("severity")) == "hard":
                candidate_hard_breakpoints.append(dict(bp))
            else:
                candidate_soft_breakpoints.append(dict(bp))
        if int(road.get("endcap_width_clamped_src_count") or 0) > 0 or int(road.get("endcap_width_clamped_dst_count") or 0) > 0:
            soft_flags.add(_SOFT_ENDCAP_WIDTH_CLAMPED)
            candidate_soft_breakpoints.append(
                build_breakpoint(
                    road=road,
                    reason=_SOFT_ENDCAP_WIDTH_CLAMPED,
                    severity="soft",
                    hint=(
                        f"src={int(road.get('endcap_width_clamped_src_count') or 0)};"
                        f"dst={int(road.get('endcap_width_clamped_dst_count') or 0)}"
                    ),
                )
            )
    else:
        soft_flags.add(SOFT_TRAJ_SURFACE_INSUFFICIENT)

    if road.get("_traj_surface_geom_metric") is None and traj_surface_hint.get("surface_metric") is not None:
        road["_traj_surface_geom_metric"] = traj_surface_hint.get("surface_metric")

    road["_timing_centerline_ms"] = float(max(0.0, t_center_ms))
    road["_timing_gate_ms"] = float(max(0.0, t_gate_ms if road_line is not None else 0.0))
    road["_timing_lb_graph_ms"] = float(_to_finite_float(center.diagnostics.get("lb_graph_build_ms"), 0.0))
    road["_timing_shortest_path_ms"] = float(_to_finite_float(center.diagnostics.get("lb_shortest_path_ms"), 0.0))

    road["hard_anomaly"] = bool(hard_flags)
    road["hard_reasons"] = sorted(hard_flags)
    road["soft_issue_flags"] = sorted(soft_flags)
    road["_geometry_metric"] = road_line
    road["_shape_ref_metric"] = center.shape_ref_metric
    road["_candidate_hard_breakpoints"] = candidate_hard_breakpoints
    road["_candidate_soft_breakpoints"] = candidate_soft_breakpoints
    road["conf"] = compute_confidence(
        support_traj_count=int(road["support_traj_count"]),
        center_sample_coverage=float(road.get("center_sample_coverage") or 0.0),
        max_turn_deg_per_10m=road.get("max_turn_deg_per_10m"),
        turn_limit_deg_per_10m=float(params["TURN_LIMIT_DEG_PER_10M"]),
        w1=float(params["CONF_W1_SUPPORT"]),
        w2=float(params["CONF_W2_COVERAGE"]),
        w3=float(params["CONF_W3_SMOOTH"]),
    )

    has_geometry = bool(isinstance(road_line, LineString) and (not road_line.is_empty))
    road["_candidate_has_geometry"] = bool(has_geometry)
    in_ratio = _to_finite_float(road.get("traj_in_ratio"), float("nan"))
    if not np.isfinite(in_ratio):
        in_ratio = _to_finite_float(road.get("traj_in_ratio_est"), 0.0)
    outside_count = 1 if SOFT_ROAD_OUTSIDE_TRAJ_SURFACE in hard_flags else 0
    bridge_count = 1 if HARD_BRIDGE_SEGMENT in hard_flags else 0
    divstrip_count = 1 if HARD_DIVSTRIP_INTERSECT in hard_flags else 0
    drivezone_count = 1 if HARD_ROAD_OUTSIDE_DRIVEZONE in hard_flags else 0
    score = 10.0 * float(in_ratio) - 0.01 * _to_finite_float(road.get("max_segment_m"), 1e6) - 0.1 * float(
        bridge_count
    ) - 0.1 * float(outside_count) - 0.1 * float(divstrip_count) - 0.1 * float(drivezone_count)
    feasible = bool(has_geometry) and (bridge_count <= 0) and (outside_count <= 0) and (divstrip_count <= 0) and (drivezone_count <= 0)
    road["_candidate_score"] = float(score)
    road["_candidate_feasible"] = bool(feasible)
    road["_candidate_in_ratio"] = float(in_ratio)
    return road


def _candidate_sort_key(road: dict[str, Any]) -> tuple[float, float, float, float, float, float, float]:
    has_geometry = 1.0 if bool(road.get("_candidate_has_geometry", False)) else 0.0
    feasible = 1.0 if bool(road.get("_candidate_feasible", False)) else 0.0
    score = _to_finite_float(road.get("_candidate_score"), -1e9)
    in_ratio = _to_finite_float(road.get("_candidate_in_ratio"), 0.0)
    max_seg = _to_finite_float(road.get("max_segment_m"), 1e6)
    support_n = float(int(road.get("support_traj_count", 0)))
    cluster_id = float(int(road.get("candidate_cluster_id", 0)))
    return (has_geometry, feasible, score, in_ratio, -max_seg, support_n, -cluster_id)


def _iter_line_parts(geom: BaseGeometry | None) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    gtype = str(getattr(geom, "geom_type", ""))
    if gtype == "LineString" and isinstance(geom, LineString):
        return [geom]
    if gtype == "MultiLineString":
        out: list[LineString] = []
        for g in getattr(geom, "geoms", []):
            if isinstance(g, LineString) and not g.is_empty and len(g.coords) >= 2:
                out.append(g)
        return out
    if gtype == "Polygon":
        b = getattr(geom, "boundary", None)
        return _iter_line_parts(b)
    if gtype == "MultiPolygon":
        out: list[LineString] = []
        for g in getattr(geom, "geoms", []):
            out.extend(_iter_line_parts(getattr(g, "boundary", None)))
        return out
    if gtype == "GeometryCollection":
        out: list[LineString] = []
        for g in getattr(geom, "geoms", []):
            out.extend(_iter_line_parts(g))
        return out
    return []


def _iter_polygon_parts(geom: BaseGeometry | None) -> list[BaseGeometry]:
    if geom is None or geom.is_empty:
        return []
    gtype = str(getattr(geom, "geom_type", ""))
    if gtype == "Polygon":
        return [geom]
    if gtype == "MultiPolygon":
        out: list[BaseGeometry] = []
        for g in getattr(geom, "geoms", []):
            if getattr(g, "is_empty", True):
                continue
            if str(getattr(g, "geom_type", "")) == "Polygon":
                out.append(g)
        return out
    if gtype == "GeometryCollection":
        out: list[BaseGeometry] = []
        for g in getattr(geom, "geoms", []):
            out.extend(_iter_polygon_parts(g))
        return out
    return []


def _xsec_has_surface_support(
    *,
    xsec: LineString,
    gore_zone_metric: BaseGeometry | None,
    surface_metric: BaseGeometry | None,
    buffer_m: float,
) -> bool:
    if xsec.is_empty or xsec.length <= 0:
        return False
    if surface_metric is None or surface_metric.is_empty:
        return False
    xsec_valid: BaseGeometry = xsec
    if gore_zone_metric is not None:
        try:
            diff = xsec.difference(gore_zone_metric)
            if diff is not None and not diff.is_empty:
                xsec_valid = diff
        except Exception:
            pass
    surf = surface_metric
    if float(buffer_m) > 0.0:
        try:
            surf = surface_metric.buffer(float(buffer_m))
        except Exception:
            surf = surface_metric
    try:
        inter = xsec_valid.intersection(surf)
    except Exception:
        return False
    for part in _iter_line_parts(inter):
        if part.length > 1e-6:
            return True
    return False


def _collect_debug_layers_for_selected(
    *,
    debug_layers: dict[str, list[dict[str, Any]]],
    road: dict[str, Any],
    src_xsec: LineString,
    dst_xsec: LineString,
    gore_zone_metric: BaseGeometry | None,
    bridge_max_seg_m: float,
) -> None:
    road_id = str(road.get("road_id"))
    surface = road.get("_traj_surface_geom_metric")
    shape_ref = road.get("_shape_ref_metric")
    line = road.get("_geometry_metric")

    for poly in _iter_polygon_parts(surface):
        debug_layers["traj_surface_best_polygon"].append({"geometry": poly, "properties": {"road_id": road_id}})
        for ls in _iter_line_parts(getattr(poly, "boundary", None)):
            debug_layers["traj_surface_best_boundary"].append({"geometry": ls, "properties": {"road_id": road_id}})
    if not _iter_polygon_parts(surface):
        for ls in _iter_line_parts(surface):
            debug_layers["traj_surface_best_boundary"].append({"geometry": ls, "properties": {"road_id": road_id}})
    if isinstance(shape_ref, LineString) and not shape_ref.is_empty:
        debug_layers["lb_path_best"].append(
            {"geometry": shape_ref, "properties": {"road_id": road_id, "lb_path_found": bool(road.get("lb_path_found"))}}
        )
        debug_layers["ref_axis_best"].append(
            {
                "geometry": shape_ref,
                "properties": {"road_id": road_id, "axis_source": road.get("traj_surface_hint_axis_source")},
            }
        )

    src_valid = src_xsec
    dst_valid = dst_xsec
    if gore_zone_metric is not None:
        try:
            sdiff = src_xsec.difference(gore_zone_metric)
            if sdiff is not None and not sdiff.is_empty:
                src_valid = sdiff
        except Exception:
            pass
        try:
            ddiff = dst_xsec.difference(gore_zone_metric)
            if ddiff is not None and not ddiff.is_empty:
                dst_valid = ddiff
        except Exception:
            pass
    for ls in _iter_line_parts(src_valid):
        debug_layers["xsec_valid_src"].append({"geometry": ls, "properties": {"road_id": road_id}})
    for ls in _iter_line_parts(dst_valid):
        debug_layers["xsec_valid_dst"].append({"geometry": ls, "properties": {"road_id": road_id}})

    xsec_ref_src = road.get("_xsec_ref_src_metric")
    xsec_ref_dst = road.get("_xsec_ref_dst_metric")
    xsec_road_all_src = road.get("_xsec_road_all_src_metric")
    xsec_road_all_dst = road.get("_xsec_road_all_dst_metric")
    xsec_road_sel_src = road.get("_xsec_road_selected_src_metric")
    xsec_road_sel_dst = road.get("_xsec_road_selected_dst_metric")
    xsec_ref_shifted_src = road.get("_xsec_ref_shifted_candidates_src_metric")
    xsec_ref_shifted_dst = road.get("_xsec_ref_shifted_candidates_dst_metric")
    xsec_barrier_samples_src = road.get("_xsec_barrier_samples_src_metric")
    xsec_barrier_samples_dst = road.get("_xsec_barrier_samples_dst_metric")
    xsec_passable_samples_src = road.get("_xsec_passable_samples_src_metric")
    xsec_passable_samples_dst = road.get("_xsec_passable_samples_dst_metric")

    for ls in _iter_line_parts(xsec_ref_src):
        debug_layers["xsec_ref_src"].append({"geometry": ls, "properties": {"road_id": road_id}})
        debug_layers["step2_xsec_ref_src"].append({"geometry": ls, "properties": {"road_id": road_id}})
        try:
            mid = ls.interpolate(0.5, normalized=True)
        except Exception:
            mid = None
        if isinstance(mid, Point) and not mid.is_empty:
            debug_layers["xsec_anchor_mid_src"].append({"geometry": mid, "properties": {"road_id": road_id}})
    for ls in _iter_line_parts(xsec_ref_dst):
        debug_layers["xsec_ref_dst"].append({"geometry": ls, "properties": {"road_id": road_id}})
        debug_layers["step2_xsec_ref_dst"].append({"geometry": ls, "properties": {"road_id": road_id}})
        try:
            mid = ls.interpolate(0.5, normalized=True)
        except Exception:
            mid = None
        if isinstance(mid, Point) and not mid.is_empty:
            debug_layers["xsec_anchor_mid_dst"].append({"geometry": mid, "properties": {"road_id": road_id}})

    if isinstance(xsec_ref_shifted_src, list):
        for item in xsec_ref_shifted_src:
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            geom, shift_m = item
            for ls in _iter_line_parts(geom):
                debug_layers["step2_xsec_ref_shifted_candidates_src"].append(
                    {
                        "geometry": ls,
                        "properties": {"road_id": road_id, "shift_m": shift_m},
                    }
                )
    if isinstance(xsec_ref_shifted_dst, list):
        for item in xsec_ref_shifted_dst:
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            geom, shift_m = item
            for ls in _iter_line_parts(geom):
                debug_layers["step2_xsec_ref_shifted_candidates_dst"].append(
                    {
                        "geometry": ls,
                        "properties": {"road_id": road_id, "shift_m": shift_m},
                    }
                )

    for ls in _iter_line_parts(xsec_road_all_src):
        debug_layers["xsec_road_all_src"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "selected_by": road.get("xsec_road_selected_by_src"),
                    "geom_type": road.get("xsec_road_all_geom_type_src"),
                },
            }
        )
        debug_layers["step2_xsec_road_all_src"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "selected_by": road.get("xsec_road_selected_by_src"),
                    "shift_used": road.get("xsec_shift_used_m_src"),
                },
            }
        )
    for ls in _iter_line_parts(xsec_road_all_dst):
        debug_layers["xsec_road_all_dst"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "selected_by": road.get("xsec_road_selected_by_dst"),
                    "geom_type": road.get("xsec_road_all_geom_type_dst"),
                },
            }
        )
        debug_layers["step2_xsec_road_all_dst"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "selected_by": road.get("xsec_road_selected_by_dst"),
                    "shift_used": road.get("xsec_shift_used_m_dst"),
                },
            }
        )
    for ls in _iter_line_parts(xsec_road_sel_src):
        debug_layers["xsec_road_selected_src"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "selected_by": road.get("xsec_road_selected_by_src"),
                },
            }
        )
        debug_layers["step2_xsec_road_selected_src"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "selected_by": road.get("xsec_road_selected_by_src"),
                    "shift_used": road.get("xsec_shift_used_m_src"),
                    "mid_to_ref_m": road.get("xsec_mid_to_ref_m_src"),
                },
            }
        )
    for ls in _iter_line_parts(xsec_road_sel_dst):
        debug_layers["xsec_road_selected_dst"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "selected_by": road.get("xsec_road_selected_by_dst"),
                },
            }
        )
        debug_layers["step2_xsec_road_selected_dst"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "selected_by": road.get("xsec_road_selected_by_dst"),
                    "shift_used": road.get("xsec_shift_used_m_dst"),
                    "mid_to_ref_m": road.get("xsec_mid_to_ref_m_dst"),
                },
            }
        )

    if isinstance(xsec_barrier_samples_src, list):
        for smp in xsec_barrier_samples_src:
            if not isinstance(smp, dict):
                continue
            xy = smp.get("xy")
            if not (isinstance(xy, tuple) and len(xy) == 2):
                continue
            debug_layers["step2_xsec_barrier_samples_src"].append(
                {
                    "geometry": Point(float(xy[0]), float(xy[1])),
                    "properties": {
                        "road_id": road_id,
                        "ng_count": smp.get("ng_count"),
                        "occupancy_ratio": smp.get("occupancy_ratio"),
                        "barrier_candidate": smp.get("barrier_candidate"),
                        "barrier_final": smp.get("barrier_final"),
                    },
                }
            )
    if isinstance(xsec_barrier_samples_dst, list):
        for smp in xsec_barrier_samples_dst:
            if not isinstance(smp, dict):
                continue
            xy = smp.get("xy")
            if not (isinstance(xy, tuple) and len(xy) == 2):
                continue
            debug_layers["step2_xsec_barrier_samples_dst"].append(
                {
                    "geometry": Point(float(xy[0]), float(xy[1])),
                    "properties": {
                        "road_id": road_id,
                        "ng_count": smp.get("ng_count"),
                        "occupancy_ratio": smp.get("occupancy_ratio"),
                        "barrier_candidate": smp.get("barrier_candidate"),
                        "barrier_final": smp.get("barrier_final"),
                    },
                }
            )
    if isinstance(xsec_passable_samples_src, list):
        for smp in xsec_passable_samples_src:
            if not isinstance(smp, dict):
                continue
            xy = smp.get("xy")
            if not (isinstance(xy, tuple) and len(xy) == 2):
                continue
            debug_layers["xsec_passable_samples_src"].append(
                {
                    "geometry": Point(float(xy[0]), float(xy[1])),
                    "properties": {
                        "road_id": road_id,
                        "in_drivezone": smp.get("in_drivezone"),
                        "in_divstrip": smp.get("in_divstrip"),
                        "passable": smp.get("passable"),
                        "stop_reason": smp.get("stop_reason"),
                        "barrier_candidate": smp.get("barrier_candidate"),
                        "barrier_final": smp.get("barrier_final"),
                    },
                }
            )
    if isinstance(xsec_passable_samples_dst, list):
        for smp in xsec_passable_samples_dst:
            if not isinstance(smp, dict):
                continue
            xy = smp.get("xy")
            if not (isinstance(xy, tuple) and len(xy) == 2):
                continue
            debug_layers["xsec_passable_samples_dst"].append(
                {
                    "geometry": Point(float(xy[0]), float(xy[1])),
                    "properties": {
                        "road_id": road_id,
                        "in_drivezone": smp.get("in_drivezone"),
                        "in_divstrip": smp.get("in_divstrip"),
                        "passable": smp.get("passable"),
                        "stop_reason": smp.get("stop_reason"),
                        "barrier_candidate": smp.get("barrier_candidate"),
                        "barrier_final": smp.get("barrier_final"),
                    },
                }
            )

    src_support = None
    dst_support = None
    if surface is not None and (not surface.is_empty):
        try:
            src_support = src_valid.intersection(surface)
        except Exception:
            src_support = None
        try:
            dst_support = dst_valid.intersection(surface)
        except Exception:
            dst_support = None
    support_disabled_src = bool(road.get("xsec_support_disabled_due_to_insufficient_src", False))
    support_disabled_dst = bool(road.get("xsec_support_disabled_due_to_insufficient_dst", False))
    for ls in _iter_line_parts(src_support):
        debug_layers["xsec_support_src"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "support_disabled_due_to_insufficient": support_disabled_src,
                },
            }
        )

    target_src = road.get("_xsec_target_selected_src_metric")
    target_dst = road.get("_xsec_target_selected_dst_metric")
    for ls in _iter_line_parts(target_src):
        debug_layers["xsec_target_selected_src"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "target_mode": road.get("xsec_target_mode_src"),
                },
            }
        )
        debug_layers["xsec_target_used_src"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "target_mode": road.get("xsec_target_mode_src"),
                },
            }
        )
    for ls in _iter_line_parts(target_dst):
        debug_layers["xsec_target_selected_dst"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "target_mode": road.get("xsec_target_mode_dst"),
                },
            }
        )
        debug_layers["xsec_target_used_dst"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "target_mode": road.get("xsec_target_mode_dst"),
                },
            }
        )

    for tag, geom in (
        ("src_before", road.get("_endpoint_before_src_metric")),
        ("src_after", road.get("_endpoint_after_src_metric")),
        ("dst_before", road.get("_endpoint_before_dst_metric")),
        ("dst_after", road.get("_endpoint_after_dst_metric")),
    ):
        if isinstance(geom, Point) and not geom.is_empty:
            debug_layers["endpoint_before_after"].append(
                {
                    "geometry": geom,
                    "properties": {
                        "road_id": road_id,
                        "tag": tag,
                    },
                }
            )
    for tag, geom, dist_v in (
        ("src", road.get("_endpoint_after_src_metric"), road.get("endpoint_dist_to_xsec_src_m")),
        ("dst", road.get("_endpoint_after_dst_metric"), road.get("endpoint_dist_to_xsec_dst_m")),
    ):
        if isinstance(geom, Point) and not geom.is_empty:
            debug_layers["step3_endpoint_src_dst"].append(
                {
                    "geometry": geom,
                    "properties": {
                        "road_id": road_id,
                        "endpoint_tag": tag,
                        "dist_to_xsec": dist_v,
                    },
                }
            )
    for ls in _iter_line_parts(dst_support):
        debug_layers["xsec_support_dst"].append(
            {
                "geometry": ls,
                "properties": {
                    "road_id": road_id,
                    "support_disabled_due_to_insufficient": support_disabled_dst,
                },
            }
        )

    if isinstance(line, LineString) and not line.is_empty:
        if gore_zone_metric is not None and (not gore_zone_metric.is_empty):
            try:
                inter_div = line.intersection(gore_zone_metric)
            except Exception:
                inter_div = None
            for part in _iter_line_parts(inter_div):
                plen = float(part.length)
                if plen <= 1e-6:
                    continue
                debug_layers["road_divstrip_intersections"].append(
                    {
                        "geometry": part,
                        "properties": {
                            "road_id": road_id,
                            "intersect_len_m": plen,
                        },
                    }
                )
        coords = list(line.coords)
        for i in range(len(coords) - 1):
            seg = LineString([coords[i], coords[i + 1]])
            seg_len = float(seg.length)
            if surface is not None and (not surface.is_empty):
                try:
                    outside_len = float(seg.difference(surface).length)
                except Exception:
                    outside_len = seg_len
                if outside_len > 1e-6:
                    debug_layers["road_outside_segments"].append(
                        {
                            "geometry": seg,
                            "properties": {
                                "road_id": road_id,
                                "seg_index": int(i),
                                "seg_length_m": seg_len,
                                "outside_len_m": outside_len,
                            },
                        }
                    )
            if seg_len > float(bridge_max_seg_m):
                debug_layers["road_bridge_segments"].append(
                    {
                        "geometry": seg,
                        "properties": {"road_id": road_id, "seg_index": int(i), "seg_length_m": seg_len},
                    }
                )


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


def _estimate_trajectory_point_count(trajectories: Sequence[Any]) -> int:
    total = 0
    for traj in trajectories:
        xyz = np.asarray(getattr(traj, "xyz_metric", np.empty((0, 3), dtype=np.float64)), dtype=np.float64)
        if xyz.ndim != 2:
            continue
        total += int(max(0, xyz.shape[0]))
    return int(total)


def _build_traj_union_for_crossing(
    trajectories: Sequence[Any],
    *,
    sample_step: int = 1,
    max_traj: int = 0,
    max_points_per_traj: int = 5000,
) -> BaseGeometry | None:
    def _subsample_keep_endpoints(xy_arr: np.ndarray, k: int) -> np.ndarray:
        n = int(xy_arr.shape[0])
        if n <= 2 or k <= 1:
            return xy_arr
        idx = np.arange(0, n, int(k), dtype=np.int64)
        if idx.size == 0 or int(idx[-1]) != n - 1:
            idx = np.append(idx, n - 1)
        idx = np.unique(idx)
        if idx.size < 2:
            return xy_arr
        return xy_arr[idx, :]

    lines: list[LineString] = []
    step = int(max(1, int(sample_step)))
    traj_limit = int(max(0, int(max_traj)))
    max_pts = int(max(100, int(max_points_per_traj)))
    used_traj = 0
    for traj in trajectories:
        if traj_limit > 0 and used_traj >= traj_limit:
            break
        xyz = np.asarray(getattr(traj, "xyz_metric", np.empty((0, 3), dtype=np.float64)), dtype=np.float64)
        if xyz.ndim != 2 or xyz.shape[0] < 2:
            continue
        xy = np.asarray(xyz[:, :2], dtype=np.float64)
        if step > 1:
            xy = _subsample_keep_endpoints(xy, step)
        finite = np.isfinite(xy[:, 0]) & np.isfinite(xy[:, 1])
        if np.count_nonzero(finite) < 2:
            continue
        xy = xy[finite, :]
        if xy.shape[0] > max_pts:
            s2 = int(max(1, math.ceil(float(xy.shape[0]) / float(max_pts))))
            xy = _subsample_keep_endpoints(xy, s2)
        if xy.shape[0] < 2:
            continue
        try:
            ls = LineString([(float(x), float(y)) for x, y in xy])
        except Exception:
            continue
        if ls.is_empty or ls.length <= 1e-6:
            continue
        lines.append(ls)
        used_traj += 1
    if not lines:
        return None
    if len(lines) == 1:
        merged: BaseGeometry = lines[0]
    else:
        try:
            merged = MultiLineString(lines)
        except Exception:
            try:
                merged = unary_union(lines[: min(len(lines), 64)])
            except Exception:
                merged = lines[0]
    if merged is None or merged.is_empty:
        return None
    return merged


def _build_traj_evidence_zone_for_gate(
    *,
    traj_union: BaseGeometry | None,
    evidence_radius_m: float,
) -> BaseGeometry | None:
    if traj_union is None or traj_union.is_empty:
        return None
    r = float(max(0.5, evidence_radius_m))
    try:
        zone = traj_union.buffer(r)
    except Exception:
        zone = traj_union
    if zone is None or zone.is_empty:
        return None
    return zone


def _estimate_cross_normal_from_lb(
    *,
    anchor_xy: tuple[float, float],
    source_xsec: LineString,
    lane_boundaries_metric: Sequence[LineString],
) -> tuple[float, float]:
    anchor_pt = Point(float(anchor_xy[0]), float(anchor_xy[1]))
    best_dist = float("inf")
    best_normal: tuple[float, float] | None = None
    for lb in lane_boundaries_metric:
        if lb is None or lb.is_empty or lb.length <= 1e-6:
            continue
        try:
            d = float(lb.distance(anchor_pt))
        except Exception:
            continue
        if not np.isfinite(d):
            continue
        if d > 80.0:
            continue
        try:
            s = float(lb.project(anchor_pt))
            ds = min(3.0, max(0.8, 0.05 * float(lb.length)))
            p0 = lb.interpolate(max(0.0, s - ds))
            p1 = lb.interpolate(min(float(lb.length), s + ds))
        except Exception:
            continue
        p0_xy = point_xy_safe(p0, context="xsec_trunc_lb_tan_p0")
        p1_xy = point_xy_safe(p1, context="xsec_trunc_lb_tan_p1")
        if p0_xy is None or p1_xy is None:
            continue
        tx, ty = _unit_xy(float(p1_xy[0] - p0_xy[0]), float(p1_xy[1] - p0_xy[1]))
        nx, ny = float(-ty), float(tx)
        if d < best_dist:
            best_dist = d
            best_normal = (nx, ny)
    if best_normal is not None:
        return best_normal
    coords = list(source_xsec.coords)
    if len(coords) >= 2:
        vx = float(coords[-1][0] - coords[0][0])
        vy = float(coords[-1][1] - coords[0][1])
        return _unit_xy(vx, vy)
    return (1.0, 0.0)


def _truncate_cross_sections_for_crossing(
    *,
    xsec_map: dict[int, Any],
    lane_boundaries_metric: Sequence[LineString],
    trajectories: Sequence[Any],
    drivezone_zone_metric: BaseGeometry | None,
    gore_zone_metric: BaseGeometry | None,
    params: dict[str, Any],
) -> tuple[
    dict[int, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[int, BaseGeometry],
    dict[int, dict[str, Any]],
    dict[str, Any],
]:
    traj_union: BaseGeometry | None = None
    out: dict[int, Any] = {}
    anchor_feats: list[dict[str, Any]] = []
    trunc_feats: list[dict[str, Any]] = []
    gate_all_map: dict[int, BaseGeometry] = {}
    gate_meta_map: dict[int, dict[str, Any]] = {}
    used_trunc = 0
    fallback_orig = 0
    gate_fallback_count = 0
    gate_empty_count = 0
    gate_selected_count = 0
    use_drivezone_gate = bool(drivezone_zone_metric is not None and (not drivezone_zone_metric.is_empty))
    lmax = float(max(10.0, params.get("XSEC_TRUNC_LMAX_M", 80.0)))
    step = float(max(0.5, params.get("XSEC_TRUNC_STEP_M", 1.0)))
    nonpass_k = int(max(2, params.get("XSEC_TRUNC_NONPASS_K", 6)))
    evidence_radius = float(max(0.5, params.get("XSEC_TRUNC_EVIDENCE_RADIUS_M", 1.0)))
    gate_evidence_mid_margin_m = float(max(0.0, params.get("XSEC_GATE_EVIDENCE_MID_MARGIN_M", 8.0)))
    gate_evidence_min_len_m = float(max(0.0, params.get("XSEC_GATE_EVIDENCE_MIN_LEN_M", 1.0)))
    traj_evidence_enabled = bool(int(params.get("XSEC_GATE_TRAJ_EVIDENCE_ENABLE", 1)))
    traj_point_budget = int(max(10_000, int(params.get("XSEC_GATE_TRAJ_EVIDENCE_MAX_POINTS", 300_000))))
    traj_sample_step = int(max(1, int(params.get("XSEC_GATE_TRAJ_EVIDENCE_SAMPLE_STEP", 4))))
    traj_evidence_max_traj = int(max(1, int(params.get("XSEC_GATE_TRAJ_EVIDENCE_MAX_TRAJ", 300))))
    traj_point_count = _estimate_trajectory_point_count(trajectories)
    gate_traj_evidence_zone: BaseGeometry | None = None
    traj_union_ready = False
    traj_evidence_disabled_reason: str | None = None

    def _ensure_traj_evidence() -> None:
        nonlocal traj_union_ready, traj_union, gate_traj_evidence_zone, traj_evidence_disabled_reason
        if traj_union_ready:
            return
        traj_union_ready = True
        if not traj_evidence_enabled:
            traj_evidence_disabled_reason = "disabled_by_param"
            return
        if traj_point_count > traj_point_budget:
            traj_evidence_disabled_reason = "point_budget_exceeded"
            return
        traj_union = _build_traj_union_for_crossing(
            trajectories,
            sample_step=traj_sample_step,
            max_traj=traj_evidence_max_traj,
            max_points_per_traj=4000,
        )
        gate_traj_evidence_zone = _build_traj_evidence_zone_for_gate(
            traj_union=traj_union,
            evidence_radius_m=float(max(1.0, evidence_radius * 2.0)),
        )
        if gate_traj_evidence_zone is None:
            traj_evidence_disabled_reason = "zone_build_failed"

    n_steps = int(max(1, round(lmax / step)))

    for nodeid, cs in xsec_map.items():
        geom = cs.geometry_metric
        if geom is None or geom.is_empty or geom.length <= 1e-6:
            out[int(nodeid)] = cs
            fallback_orig += 1
            continue
        center = geom.interpolate(0.5, normalized=True)
        c_xy = point_xy_safe(center, context="xsec_trunc_anchor")
        if c_xy is None:
            out[int(nodeid)] = cs
            fallback_orig += 1
            continue
        ax = float(c_xy[0])
        ay = float(c_xy[1])

        if use_drivezone_gate:
            gate_all: BaseGeometry = geom
            gate_selected_by = "drivezone_intersection"
            gate_fallback = False
            if drivezone_zone_metric is not None and (not drivezone_zone_metric.is_empty):
                try:
                    inter = geom.intersection(drivezone_zone_metric)
                except Exception:
                    inter = geom
                if inter is not None and (not inter.is_empty):
                    gate_all = inter
                else:
                    gate_all = LineString()
            if gate_all is not None and (not gate_all.is_empty) and gore_zone_metric is not None and (not gore_zone_metric.is_empty):
                try:
                    diff = gate_all.difference(gore_zone_metric)
                except Exception:
                    diff = gate_all
                if diff is not None and (not diff.is_empty):
                    gate_all = diff
            if gate_all is None or gate_all.is_empty:
                gate_empty_count += 1
                gate_fallback = True
                if gore_zone_metric is not None and (not gore_zone_metric.is_empty):
                    try:
                        fallback_geom = geom.difference(gore_zone_metric)
                    except Exception:
                        fallback_geom = geom
                    if fallback_geom is not None and (not fallback_geom.is_empty):
                        gate_all = fallback_geom
                        gate_selected_by = "fallback_seed_minus_divstrip"
                    else:
                        gate_all = geom
                        gate_selected_by = "fallback_raw_seed"
                else:
                    gate_all = geom
                    gate_selected_by = "fallback_raw_seed"
            line_parts = [ls for ls in _iter_line_parts(gate_all) if isinstance(ls, LineString) and not ls.is_empty and ls.length > 1e-6]
            if not line_parts:
                gate_fallback = True
                gate_all = geom
                line_parts = [geom]
                gate_selected_by = "fallback_raw_seed"
            mid = Point(ax, ay)
            if len(line_parts) == 1:
                selected_line = line_parts[0]
                segment_selected_by = "single_segment"
                selected_evidence_len_m = 0.0
                selected_mid_dist_m = float(selected_line.distance(mid))
            else:
                _ensure_traj_evidence()
                scored_parts: list[dict[str, Any]] = []
                for i_part, ls in enumerate(line_parts):
                    mid_dist_m = float(ls.distance(mid))
                    evidence_len_m = 0.0
                    if gate_traj_evidence_zone is not None and (not gate_traj_evidence_zone.is_empty):
                        try:
                            evidence_len_m = float(ls.intersection(gate_traj_evidence_zone).length)
                        except Exception:
                            evidence_len_m = 0.0
                    scored_parts.append(
                        {
                            "idx": int(i_part),
                            "geom": ls,
                            "mid_dist_m": float(mid_dist_m),
                            "evidence_len_m": float(max(0.0, evidence_len_m)),
                            "len_m": float(ls.length),
                        }
                    )
                min_mid_dist_m = float(min(float(it["mid_dist_m"]) for it in scored_parts))
                selected_payload = max(
                    scored_parts,
                    key=lambda it: (
                        (
                            float(it["mid_dist_m"]) <= float(min_mid_dist_m + gate_evidence_mid_margin_m)
                            and float(it["evidence_len_m"]) >= float(gate_evidence_min_len_m)
                        ),
                        (
                            float(it["evidence_len_m"])
                            if float(it["mid_dist_m"]) <= float(min_mid_dist_m + gate_evidence_mid_margin_m)
                            else 0.0
                        ),
                        -float(it["mid_dist_m"]),
                        float(it["len_m"]),
                        -int(it["idx"]),
                    ),
                )
                selected_line = selected_payload["geom"]
                selected_evidence_len_m = float(selected_payload["evidence_len_m"])
                selected_mid_dist_m = float(selected_payload["mid_dist_m"])
                if (
                    selected_mid_dist_m <= float(min_mid_dist_m + gate_evidence_mid_margin_m)
                    and selected_evidence_len_m >= float(gate_evidence_min_len_m)
                ):
                    segment_selected_by = "traj_evidence_midpoint_longest_tiebreak"
                else:
                    segment_selected_by = "nearest_midpoint_longest_tiebreak"
            gate_selected_line = LineString(
                [
                    (float(coord[0]), float(coord[1]))
                    for coord in selected_line.coords
                    if len(coord) >= 2
                ]
            )
            if gate_selected_line.length < geom.length - 1e-6:
                used_trunc += 1
            if gate_fallback:
                gate_fallback_count += 1
                fallback_orig += 1
            gate_selected_count += 1
            out[int(nodeid)] = CrossSection(
                nodeid=int(cs.nodeid),
                geometry_metric=gate_selected_line,
                properties=dict(cs.properties),
            )
            gate_all_map[int(nodeid)] = gate_all
            gate_meta_map[int(nodeid)] = {
                "len_m": float(gate_selected_line.length),
                "geom_type": str(getattr(gate_all, "geom_type", "")),
                "fallback": bool(gate_fallback),
                "selected_by": str(segment_selected_by if not gate_fallback else gate_selected_by),
                "selection_source": str(gate_selected_by),
                "candidate_segment_count": int(len(line_parts)),
                "selected_mid_dist_m": float(selected_mid_dist_m),
                "selected_evidence_len_m": float(selected_evidence_len_m),
            }
            anchor_feats.append(
                {
                    "geometry": Point(ax, ay),
                    "properties": {
                        "nodeid": int(nodeid),
                    },
                }
            )
            trunc_feats.append(
                {
                    "geometry": gate_selected_line,
                    "properties": {
                        "nodeid": int(nodeid),
                        "left_extent_m": None,
                        "right_extent_m": None,
                        "cut_by_divstrip_left": None,
                        "cut_by_divstrip_right": None,
                        "used_trunc": bool(gate_selected_line.length < geom.length - 1e-6),
                        "xsec_gate_selected_by": str(segment_selected_by if not gate_fallback else gate_selected_by),
                        "xsec_gate_fallback": bool(gate_fallback),
                    },
                }
            )
            continue

        _ensure_traj_evidence()
        nx, ny = _estimate_cross_normal_from_lb(
            anchor_xy=(ax, ay),
            source_xsec=geom,
            lane_boundaries_metric=lane_boundaries_metric,
        )
        blocked_left = False
        blocked_right = False
        left_extent = 0.0
        right_extent = 0.0
        for sign in (-1.0, 1.0):
            best = 0.0
            fail_run = 0
            cut_by_divstrip = False
            for i in range(1, n_steps + 1):
                d = float(i) * step
                px = ax + sign * nx * d
                py = ay + sign * ny * d
                p = Point(px, py)
                blocked = False
                if gore_zone_metric is not None and (not gore_zone_metric.is_empty):
                    try:
                        blocked = bool(gore_zone_metric.buffer(1e-6).covers(p))
                    except Exception:
                        blocked = False
                if blocked:
                    passable = False
                    cut_by_divstrip = True
                else:
                    passable = False
                    if traj_union is not None and (not traj_union.is_empty):
                        try:
                            passable = float(p.distance(traj_union)) <= evidence_radius
                        except Exception:
                            passable = False
                if passable:
                    best = d
                    fail_run = 0
                else:
                    fail_run += 1
                if fail_run >= nonpass_k:
                    break
            if sign < 0:
                left_extent = best
                blocked_left = cut_by_divstrip
            else:
                right_extent = best
                blocked_right = cut_by_divstrip

        if traj_union is None or (left_extent < step and right_extent < step):
            half = min(lmax, max(step, 0.5 * float(geom.length)))
            left_extent = max(left_extent, half)
            right_extent = max(right_extent, half)
        p0 = (ax - nx * left_extent, ay - ny * left_extent)
        p1 = (ax + nx * right_extent, ay + ny * right_extent)
        trunc_line = LineString([p0, p1])
        if trunc_line.is_empty or trunc_line.length <= 1.0:
            trunc_line = geom
            fallback_orig += 1
        else:
            used_trunc += 1
        out[int(nodeid)] = CrossSection(
            nodeid=int(cs.nodeid),
            geometry_metric=trunc_line,
            properties=dict(cs.properties),
        )
        gate_all_map[int(nodeid)] = trunc_line
        gate_meta_map[int(nodeid)] = {
            "len_m": float(trunc_line.length),
            "geom_type": str(getattr(trunc_line, "geom_type", "")),
            "fallback": bool(trunc_line.length >= geom.length - 1e-6),
            "selected_by": "legacy_trunc",
            "selection_source": "legacy_trunc",
        }
        gate_selected_count += 1
        anchor_feats.append(
            {
                "geometry": Point(ax, ay),
                "properties": {
                    "nodeid": int(nodeid),
                },
            }
        )
        trunc_feats.append(
            {
                "geometry": trunc_line,
                "properties": {
                    "nodeid": int(nodeid),
                    "left_extent_m": float(left_extent),
                    "right_extent_m": float(right_extent),
                    "cut_by_divstrip_left": bool(blocked_left),
                    "cut_by_divstrip_right": bool(blocked_right),
                    "used_trunc": bool(trunc_line is not geom),
                },
            }
        )
    stats = {
        "xsec_truncated_count": int(used_trunc),
        "xsec_truncated_fallback_count": int(fallback_orig),
        "xsec_gate_enabled": bool(use_drivezone_gate),
        "xsec_gate_selected_count": int(gate_selected_count),
        "xsec_gate_empty_count": int(gate_empty_count),
        "xsec_gate_fallback_count": int(gate_fallback_count),
        "xsec_gate_traj_evidence_enabled": bool(gate_traj_evidence_zone is not None),
        "xsec_gate_traj_evidence_disabled_reason": traj_evidence_disabled_reason,
        "xsec_gate_traj_point_count": int(traj_point_count),
        "xsec_gate_traj_point_budget": int(traj_point_budget),
        "xsec_gate_traj_sample_step": int(traj_sample_step),
        "xsec_gate_traj_max_traj": int(traj_evidence_max_traj),
    }
    return out, anchor_feats, trunc_feats, gate_all_map, gate_meta_map, stats


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


def _apply_xsec_gate_meta_to_road(
    *,
    road: dict[str, Any],
    src_meta: dict[str, Any] | None,
    dst_meta: dict[str, Any] | None,
) -> None:
    for tag, meta in (("src", src_meta), ("dst", dst_meta)):
        md = meta if isinstance(meta, dict) else {}
        len_v = md.get("len_m")
        try:
            len_f = float(len_v)
        except Exception:
            len_f = float("nan")
        road[f"xsec_gate_len_{tag}_m"] = float(len_f) if np.isfinite(len_f) else None
        geom_t = str(md.get("geom_type") or "").strip()
        road[f"xsec_gate_geom_type_{tag}"] = geom_t if geom_t else None
        fb = md.get("fallback")
        road[f"xsec_gate_fallback_{tag}"] = None if fb is None else bool(fb)
        sel = str(md.get("selected_by") or "").strip()
        road[f"xsec_gate_selected_by_{tag}"] = sel if sel else None


def _make_base_road_record(
    *,
    src: int,
    dst: int,
    support: PairSupport,
    src_type: str,
    dst_type: str,
    neighbor_search_pass: int,
) -> dict[str, Any]:
    repr_ids = list(support.repr_traj_ids)[:5]
    stitch_p50, stitch_p90, stitch_max = _stitch_stats(support.stitch_hops)
    return {
        "road_id": f"{src}_{dst}",
        "src_nodeid": int(src),
        "dst_nodeid": int(dst),
        "direction": f"{src}->{dst}",
        "neighbor_search_pass": int(neighbor_search_pass),
        "candidate_cluster_id": int(support.main_cluster_id),
        "chosen_cluster_id": int(support.main_cluster_id),
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
        "endpoint_proj_dist_to_core_m_src": None,
        "endpoint_proj_dist_to_core_m_dst": None,
        "endpoint_snap_dist_src_before_m": None,
        "endpoint_snap_dist_src_after_m": None,
        "endpoint_snap_dist_dst_before_m": None,
        "endpoint_snap_dist_dst_after_m": None,
        "endpoint_dist_to_xsec_src_m": None,
        "endpoint_dist_to_xsec_dst_m": None,
        "width_med_m": None,
        "width_p90_m": None,
        "max_turn_deg_per_10m": None,
        "seg_index0_len_m": None,
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
        "endpoint_fallback_mode_src": None,
        "endpoint_fallback_mode_dst": None,
        "endpoint_tangent_deviation_deg_src": None,
        "endpoint_tangent_deviation_deg_dst": None,
        "max_segment_m": None,
        "traj_surface_enforced": False,
        "traj_surface_geom_type": None,
        "traj_surface_area_m2": None,
        "traj_surface_component_count": None,
        "traj_surface_valid_slices_ratio": None,
        "traj_surface_covered_length_ratio": None,
        "traj_surface_covered_station_length_m": None,
        "endcap_valid_ratio_src": None,
        "endcap_valid_ratio_dst": None,
        "endcap_width_src_before_m": None,
        "endcap_width_src_after_m": None,
        "endcap_width_dst_before_m": None,
        "endcap_width_dst_after_m": None,
        "endcap_width_clamped_src_count": None,
        "endcap_width_clamped_dst_count": None,
        "xsec_support_available_src": None,
        "xsec_support_available_dst": None,
        "xsec_support_len_src": None,
        "xsec_support_len_dst": None,
        "xsec_support_disabled_due_to_insufficient_src": None,
        "xsec_support_disabled_due_to_insufficient_dst": None,
        "xsec_support_empty_reason_src": None,
        "xsec_support_empty_reason_dst": None,
        "xsec_target_mode_src": None,
        "xsec_target_mode_dst": None,
        "xsec_road_selected_by_src": None,
        "xsec_road_selected_by_dst": None,
        "xsec_gate_len_src_m": None,
        "xsec_gate_len_dst_m": None,
        "xsec_gate_geom_type_src": None,
        "xsec_gate_geom_type_dst": None,
        "xsec_gate_fallback_src": None,
        "xsec_gate_fallback_dst": None,
        "xsec_gate_selected_by_src": None,
        "xsec_gate_selected_by_dst": None,
        "xsec_selected_by_src": None,
        "xsec_selected_by_dst": None,
        "xsec_shift_used_m_src": None,
        "xsec_shift_used_m_dst": None,
        "xsec_mid_to_ref_m_src": None,
        "xsec_mid_to_ref_m_dst": None,
        "xsec_intersects_ref_src": None,
        "xsec_intersects_ref_dst": None,
        "xsec_ref_intersection_n_src": None,
        "xsec_ref_intersection_n_dst": None,
        "xsec_barrier_candidate_count_src": None,
        "xsec_barrier_candidate_count_dst": None,
        "xsec_barrier_final_count_src": None,
        "xsec_barrier_final_count_dst": None,
        "xsec_road_selected_len_src_m": None,
        "xsec_road_selected_len_dst_m": None,
        "xsec_road_all_geom_type_src": None,
        "xsec_road_all_geom_type_dst": None,
        "xsec_road_left_extent_src_m": None,
        "xsec_road_right_extent_src_m": None,
        "xsec_road_left_extent_dst_m": None,
        "xsec_road_right_extent_dst_m": None,
        "offset_clamp_hit_ratio": None,
        "offset_clamp_fallback_count": None,
        "s_anchor_src_m": None,
        "s_anchor_dst_m": None,
        "s_end_src_m": None,
        "s_end_dst_m": None,
        "anchor_window_m": None,
        "traj_surface_slice_half_win_levels": None,
        "traj_surface_slice_half_win_used_hist": None,
        "traj_in_ratio": None,
        "traj_in_ratio_est": None,
        "endpoint_in_traj_surface_src": None,
        "endpoint_in_traj_surface_dst": None,
        "endpoint_in_traj_surface_src_raw": None,
        "endpoint_in_traj_surface_dst_raw": None,
        "endpoint_dist_to_traj_surface_src_m": None,
        "endpoint_dist_to_traj_surface_dst_m": None,
        "endpoint_traj_surface_tolerance_used_src": False,
        "endpoint_traj_surface_tolerance_used_dst": False,
        "endpoint_in_drivezone_src": None,
        "endpoint_in_drivezone_dst": None,
        "xsec_samples_passable_ratio_src": None,
        "xsec_samples_passable_ratio_dst": None,
        "road_outside_drivezone_len_m": None,
        "road_in_drivezone_ratio": None,
        "divstrip_intersect_len_m": 0.0,
        "divstrip_constructor_retry_mode": None,
        "bridge_seg_outside_ratio": None,
        "bridge_seg_intersects_divstrip": False,
        "bridge_seg_dist_to_lb_m": None,
        "lb_path_found": False,
        "lb_path_edge_count": 0,
        "lb_path_length_m": None,
        "traj_surface_hint_axis_source": None,
        "traj_surface_hint_reason": None,
        "step1_strategy": None,
        "step1_reason": None,
        "step1_corridor_count": None,
        "step1_main_corridor_ratio": None,
        "gore_fallback_used_src": False,
        "gore_fallback_used_dst": False,
        "traj_drop_count_by_drivezone": 0,
        "drivezone_fallback_used": False,
        "repr_traj_ids": repr_ids,
        "stitch_hops_p50": stitch_p50,
        "stitch_hops_p90": stitch_p90,
        "stitch_hops_max": stitch_max,
        "cluster_count": int(support.cluster_count),
        "main_cluster_ratio": float(support.main_cluster_ratio),
        "cluster_sep_m_est": support.cluster_sep_m_est,
        "no_geometry_candidate": None,
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
        HARD_MULTI_CORRIDOR: "multiple_step1_corridors_detected",
        HARD_NO_STRATEGY_MERGE_TO_DIVERGE: "merge_to_diverge_not_supported",
        HARD_MULTI_ROAD: "pair_has_multiple_channel_clusters",
        HARD_NON_RC: "non_rc_node_used_in_pair",
        HARD_CENTER_EMPTY: "centerline_generation_failed",
        HARD_ENDPOINT: "endpoints_not_on_intersection_l",
        HARD_ENDPOINT_LOCAL: "endpoint_out_of_local_xsec_neighborhood",
        HARD_ENDPOINT_OFF_ANCHOR: "endpoint_off_xsec_road_after_snap",
        HARD_BRIDGE_SEGMENT: "bridge_segment_too_long",
        HARD_DIVSTRIP_INTERSECT: "road_intersects_divstrip_forbidden",
        HARD_ROAD_OUTSIDE_DRIVEZONE: "road_outside_drivezone_forbidden",
        _HARD_NO_ADJACENT_PAIR_AFTER_PASS2: "no_adjacent_pair_after_pass2",
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
        _SOFT_ENDCAP_WIDTH_CLAMPED: "endcap_width_clamped",
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
    debug_layers: dict[str, list[dict[str, Any]]] | None = None,
    extra_metrics: dict[str, Any] | None = None,
    debug_json_payloads: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    git_sha = git_short_sha(repo_root)
    digest = params_digest(params)
    road_candidate_count = int(len(roads))
    written_roads: list[dict[str, Any]] = []
    for road in roads:
        geom = road.get("_geometry_metric")
        if isinstance(geom, LineString) and (not geom.is_empty):
            written_roads.append(road)
    road_features_count = int(len(road_feature_props))
    no_geometry_candidate_count = int(max(0, road_candidate_count - road_features_count))

    metrics_payload = build_metrics_payload(
        patch_id=patch_id,
        roads=written_roads,
        hard_breakpoints=hard_breakpoints,
        soft_breakpoints=soft_breakpoints,
    )
    metrics_payload["road_candidate_count"] = int(road_candidate_count)
    metrics_payload["road_features_count"] = int(road_features_count)
    metrics_payload["road_count"] = int(road_features_count)
    metrics_payload["no_geometry_candidate_count"] = int(no_geometry_candidate_count)
    metrics_payload["no_geometry_candidate"] = bool(road_candidate_count > 0 and road_features_count == 0)
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
    summary_params["road_features_count"] = int(road_features_count)
    summary_params["road_candidate_count"] = int(road_candidate_count)
    summary_params["no_geometry_candidate_count"] = int(no_geometry_candidate_count)
    summary_params["no_geometry_candidate"] = bool(road_candidate_count > 0 and road_features_count == 0)
    if extra_metrics:
        for k, v in extra_metrics.items():
            sk = str(k)
            if (
                sk.startswith("t_")
                or sk.startswith("n_cross_")
                or sk.startswith("crossing_")
                or sk.startswith("stitch_")
                or sk.startswith("endpoint_center_offset_")
                or sk.startswith("endpoint_tangent_deviation_")
                or sk.startswith("endpoint_anchor_")
                or sk.startswith("endpoint_dist_to_xsec_")
                or sk.startswith("gore_overlap_")
                or sk.startswith("endcap_")
                or sk.startswith("max_segment_")
                or sk.startswith("seg_index0_")
                or sk.startswith("xsec_support_")
                or sk.startswith("xsec_target_")
                or sk.startswith("xsec_road_")
                or sk.startswith("xsec_shift_")
                or sk.startswith("xsec_mid_")
                or sk.startswith("xsec_gate_")
                or sk.startswith("xsec_intersects_")
                or sk.startswith("xsec_ref_intersection_")
                or sk.startswith("xsec_barrier_")
                or sk.startswith("xsec_selected_by_")
                or sk.startswith("xsec_trunc")
                or sk.startswith("xsec_truncated")
                or sk.startswith("offset_clamp_")
                or sk.startswith("endpoint_fallback_mode_")
                or sk.startswith("bridge_seg_")
                or sk.startswith("traj_in_ratio")
                or sk.startswith("traj_surface_")
                or sk.startswith("divstrip_")
                or sk.startswith("slice_half_win_")
                or sk.startswith("pointcloud_")
                or sk.startswith("drivezone_")
                or sk.startswith("intersection_")
                or sk.startswith("step1_corridor_")
                or sk.startswith("step1_main_corridor_")
                or sk.startswith("traj_surface_cache_")
                or sk.startswith("neighbor_search_")
                or sk.startswith("width_near_minus_base_")
                or sk.startswith("endpoint_in_drivezone_")
                or sk.startswith("xsec_samples_passable_ratio_")
                or sk.startswith("road_outside_drivezone_")
                or sk == "traj_drop_count_by_drivezone"
                or sk in {"expanded_end_count", "gore_tip_end_count", "fallback_end_count", "divstrip_missing"}
            ):
                summary_params[str(k)] = v

    summary_text = build_summary_text(
        run_id=run_id,
        git_sha=git_sha,
        patch_id=patch_id,
        overall_pass=overall_pass,
        roads=written_roads,
        road_features_count=int(road_features_count),
        road_candidate_count=int(road_candidate_count),
        hard_breakpoints=hard_breakpoints,
        soft_breakpoints=soft_breakpoints,
        params=summary_params,
        lane_boundary_status={
            "used": metrics_payload.get("lane_boundary_used"),
            "method": metrics_payload.get("lane_boundary_crs_method"),
            "final_crs": metrics_payload.get("lane_boundary_crs_name_final"),
        },
    )

    debug_feature_collections: dict[str, dict[str, Any]] = {}
    if debug_layers:
        always_emit_empty = {
            "step1_corridor_centerline",
            "step1_corridor_candidates",
            "step1_support_trajs",
            "step1_support_trajs_all",
            "step1_seed_selected",
            "xsec_gate_all_src",
            "xsec_gate_all_dst",
            "xsec_gate_selected_src",
            "xsec_gate_selected_dst",
            "step2_xsec_ref_src",
            "step2_xsec_ref_dst",
            "step2_xsec_ref_shifted_candidates_src",
            "step2_xsec_ref_shifted_candidates_dst",
            "step2_xsec_road_all_src",
            "step2_xsec_road_all_dst",
            "step2_xsec_road_selected_src",
            "step2_xsec_road_selected_dst",
            "step2_xsec_barrier_samples_src",
            "step2_xsec_barrier_samples_dst",
            "xsec_passable_samples_src",
            "xsec_passable_samples_dst",
            "step3_endpoint_src_dst",
            "drivezone_union",
            "xsec_support_src",
            "xsec_support_dst",
            "xsec_ref_src",
            "xsec_ref_dst",
            "xsec_road_all_src",
            "xsec_road_all_dst",
            "xsec_road_selected_src",
            "xsec_road_selected_dst",
            "xsec_anchor_mid_src",
            "xsec_anchor_mid_dst",
            "xsec_target_selected_src",
            "xsec_target_selected_dst",
            "xsec_target_used_src",
            "xsec_target_used_dst",
            "endpoint_before_after",
        }
        for layer_name, items in debug_layers.items():
            feats: list[dict[str, Any]] = []
            for item in items:
                geom = item.get("geometry")
                if geom is None:
                    continue
                try:
                    geom_json = mapping(geom)
                except Exception:
                    continue
                feats.append(
                    {
                        "type": "Feature",
                        "geometry": geom_json,
                        "properties": dict(item.get("properties") or {}),
                    }
                )
            if feats or layer_name in always_emit_empty:
                debug_feature_collections[f"debug/{layer_name}.geojson"] = {
                    "type": "FeatureCollection",
                    "features": feats,
                    "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
                }

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
        "debug_json_payloads": dict(debug_json_payloads or {}),
        "debug_feature_collections": debug_feature_collections,
    }


def get_default_params() -> dict[str, Any]:
    return dict(DEFAULT_PARAMS)


__all__ = ["DEFAULT_PARAMS", "RunResult", "get_default_params", "run_patch"]
