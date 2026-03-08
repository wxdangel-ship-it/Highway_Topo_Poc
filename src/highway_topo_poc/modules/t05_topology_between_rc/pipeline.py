from __future__ import annotations

import hashlib
import json
import math
import re
import resource
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence

import numpy as np
from shapely import contains_xy, get_x, get_y, line_interpolate_point, line_locate_point, points
from shapely.geometry import LineString, MultiLineString, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, nearest_points, polygonize, substring, unary_union

from .geometry import (
    HARD_BRIDGE_SEGMENT,
    HARD_CENTER_EMPTY,
    HARD_DIVSTRIP_INTERSECT,
    HARD_ENDPOINT,
    HARD_ENDPOINT_OFF_ANCHOR,
    HARD_ENDPOINT_LOCAL,
    HARD_MULTI_CORRIDOR,
    HARD_MULTI_NEIGHBOR_FOR_NODE,
    HARD_MULTI_ROAD,
    HARD_NO_STRATEGY_MERGE_TO_DIVERGE,
    HARD_NON_RC,
    HARD_ROAD_OUTSIDE_DRIVEZONE,
    SOFT_AMBIGUOUS_NEXT_XSEC,
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
    PairSupportBuildResult,
    _build_lb_graph_path,
    build_pair_endpoint_xsec,
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
    TRAJ_SPLIT_MAX_GAP_M_DEFAULT,
    TRAJ_SPLIT_MAX_SEQ_GAP_DEFAULT,
    TRAJ_SPLIT_MAX_TIME_GAP_S_DEFAULT,
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
_HARD_MULTI_CHAIN_SAME_DST = "MULTI_CHAIN_SAME_DST"
_HARD_ROAD_OUTSIDE_SEGMENT_CORRIDOR = "ROAD_OUTSIDE_SEGMENT_CORRIDOR"
_MAX_SAFE_FLOAT_INT = 9007199254740991  # 2^53 - 1


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
    "STEP1_UNIQUE_DST_EARLY_STOP": 1,
    "STEP1_UNIQUE_DST_DIST_EPS_M": 5.0,
    "STEP1_PAIR_TARGET_MAX_INTERMEDIATE_XSECS": 1,
    "STEP1_NODE_VOTE_MIN_RATIO": 1.0,
    "STEP1_SINGLE_SUPPORT_PER_PAIR": 0,
    "STEP1_SKIP_SEARCH_AFTER_PAIR_RESOLVED": 0,
    "STEP1_REBUILD_SUPPORTS_WITH_INFERRED_TYPES": 0,
    "STEP1_ADJ_MODE": "topology_unique",
    "STEP1_TOPO_RESPECT_DIRECTION": 1,
    "STEP1_TOPO_COMPRESS_DEG2": 1,
    "STEP1_TOPO_REQUIRE_UNIQUE_CHAIN": 1,
    "STEP1_TOPO_MAX_EXPANSIONS": 50000,
    "STEP1_CORRIDOR_ZONE_TOPK": 3,
    "STEP1_USE_ROAD_PRIOR_ADJ_FILTER": 1,
    "STEP1_ROAD_PRIOR_RESPECT_DIRECTION": 1,
    "PASS2_NEIGHBOR_MAX_DIST_M": 8000.0,
    "PASS2_UNRESOLVED_MIN_COUNT": 20,
    "PASS2_UNRESOLVED_PER_SUPPORT": 10.0,
    "PASS2_UNRESOLVED_RATIO_TRIGGER": 6.0,
    "PASS2_FORCE_WHEN_STITCH_ACCEPT_ZERO": 1,
    "MULTI_ROAD_SEP_M": 8.0,
    "SAME_PAIR_MULTI_STATION_GAP_MIN_M": 0.5,
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
    "STEP1_PRIMARY_PICK_TOPK": 8,
    "STEP1_DISABLE_PAIR_CLUSTER_WHEN_GATE": 1,
    "STEP1_PAIR_CLUSTER_ENABLE": 0,
    "STEP1_DEBUG_SUPPORT_TRAJS_ALL_MAX_PER_PAIR": 1,
    "STEP1_GORE_NEAR_M": 30.0,
    "STEP1_TRAJ_IN_DRIVEZONE_MIN": 0.85,
    "STEP1_TRAJ_IN_DRIVEZONE_FALLBACK_MIN": 0.60,
    "STEP1_CORRIDOR_REACH_XSEC_M": 12.0,
    "TOPOLOGY_FALLBACK_REACH_XSEC_M": 25.0,
    "SAME_PAIR_FALLBACK_REACH_XSEC_M": 25.0,
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
    "STEP2_SEGMENT_CORRIDOR_INSIDE_TOL_M": 0.5,
    "STEP2_SEGMENT_CORRIDOR_MIN_INSIDE_RATIO": 0.999,
    "STEP2_SEGMENT_CORRIDOR_RESCUE_ENABLE": 1,
    "STEP2_SEGMENT_CORRIDOR_RESCUE_OUTSIDE_MAX_M": 5.0,
    "STEP3_WIDENING_SUPPRESS_ENABLE": 1,
    "STEP3_WIDENING_RATIO_TRIGGER": 1.25,
    "STEP3_WIDENING_REQUIRE_EXPANDED_FLAG": 1,
    "STEP0_MODE": "off",
    "STEP0_LITE_MIN_IN_DRIVEZONE_RATIO": 0.90,
    "STEP0_LITE_MAX_IN_DIVSTRIP_RATIO": 0.01,
    "STEP0_LITE_MIN_LEN_M": 5.0,
    "STEP0_LITE_ALLOW_PASSTHROUGH_WHEN_DIVSTRIP_MISSING": 1,
    "STEP0_STATS_ENABLE": 1,
    "CACHE_ENABLED": 1,
    "TRAJ_SPLIT_MAX_GAP_M": TRAJ_SPLIT_MAX_GAP_M_DEFAULT,
    "TRAJ_SPLIT_MAX_TIME_GAP_S": TRAJ_SPLIT_MAX_TIME_GAP_S_DEFAULT,
    "TRAJ_SPLIT_MAX_SEQ_GAP": TRAJ_SPLIT_MAX_SEQ_GAP_DEFAULT,
    "FOCUS_PAIR_FILTER": [],
    "FOCUS_SRC_NODEIDS": [],
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
    keep_pairs: set[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "step1_pair_cluster_disabled": False,
        "step1_pair_cluster_disabled_pair_count": 0,
        "step1_pair_cluster_disabled_event_count": 0,
        "step1_pair_cluster_disabled_hard_multi_removed_count": 0,
        "step1_pair_cluster_preserved_pair_count": 0,
    }
    if not bool(enabled):
        return stats
    keep_pair_set = {
        (int(src), int(dst))
        for (src, dst) in (keep_pairs or set())
    }
    pair_count = 0
    event_count = 0
    removed_count = 0
    preserved_count = 0
    for pair, support in supports.items():
        pair_count += 1
        n = int(max(0, int(support.support_event_count)))
        event_count += n
        pair_key = (int(pair[0]), int(pair[1]))
        if pair_key in keep_pair_set:
            preserved_count += 1
            continue
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
    stats["step1_pair_cluster_preserved_pair_count"] = int(preserved_count)
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


def _normalize_focus_pair_filter(raw: Any) -> set[tuple[int, int]]:
    if raw is None:
        return set()
    if isinstance(raw, (str, bytes)):
        items: Sequence[Any] = [raw]
    elif isinstance(raw, Sequence):
        items = list(raw)
    else:
        items = [raw]
    out: set[tuple[int, int]] = set()
    for item in items:
        src_raw = None
        dst_raw = None
        if isinstance(item, dict):
            src_raw = item.get("src_nodeid", item.get("src"))
            dst_raw = item.get("dst_nodeid", item.get("dst"))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            src_raw, dst_raw = item[0], item[1]
        else:
            text = str(item or "").strip()
            for sep in ("->", ":", ","):
                if sep not in text:
                    continue
                lhs, rhs = text.split(sep, 1)
                src_raw, dst_raw = lhs.strip(), rhs.strip()
                break
        if src_raw is None or dst_raw is None:
            continue
        try:
            out.add((int(src_raw), int(dst_raw)))
        except Exception:
            continue
    return out


def _normalize_focus_src_nodeids(
    raw: Any,
    *,
    focus_pairs: set[tuple[int, int]] | None = None,
) -> set[int]:
    out = {int(src) for src, _ in (focus_pairs or set())}
    if raw is None:
        return out
    if isinstance(raw, (str, bytes)):
        items: Sequence[Any] = [raw]
    elif isinstance(raw, Sequence):
        items = list(raw)
    else:
        items = [raw]
    for item in items:
        if item is None:
            continue
        if isinstance(item, dict):
            value = item.get("src_nodeid", item.get("nodeid"))
            if value is None:
                continue
            try:
                out.add(int(value))
            except Exception:
                continue
            continue
        if isinstance(item, str):
            text = str(item or "").strip()
            if not text:
                continue
            for token in text.split(","):
                tok = token.strip()
                if not tok:
                    continue
                try:
                    out.add(int(tok))
                except Exception:
                    continue
            continue
        try:
            out.add(int(item))
        except Exception:
            continue
    return out


def _pairs_to_dst_map(pairs: set[tuple[int, int]]) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    for src_i, dst_i in sorted(((int(src), int(dst)) for src, dst in pairs), key=lambda it: (it[0], it[1])):
        out.setdefault(int(src_i), set()).add(int(dst_i))
    return out


def _filter_debug_features_for_focus(
    features: Sequence[dict[str, Any]],
    *,
    focus_pairs: set[tuple[int, int]],
    focus_src_nodeids: set[int],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties")
        if not isinstance(props, dict):
            continue
        try:
            src_i = int(props.get("src_nodeid"))
        except Exception:
            src_i = None
        try:
            dst_i = int(props.get("dst_nodeid"))
        except Exception:
            dst_i = None
        if src_i is None:
            continue
        if focus_pairs and dst_i is not None and (int(src_i), int(dst_i)) in focus_pairs:
            out.append(dict(feat))
            continue
        if focus_src_nodeids and int(src_i) in focus_src_nodeids:
            out.append(dict(feat))
    return out


def _build_traj_lookup_indexes(
    patch_inputs: PatchInputs,
) -> tuple[dict[str, np.ndarray], dict[str, dict[str, Any]]]:
    traj_xy_index: dict[str, np.ndarray] = {}
    traj_meta_index: dict[str, dict[str, Any]] = {}
    source_stat_cache: dict[Path, dict[str, Any]] = {}
    for traj in patch_inputs.trajectories:
        tid = str(traj.traj_id)
        xy = np.asarray(traj.xyz_metric[:, :2], dtype=np.float64)
        if xy.ndim == 2 and xy.shape[0] > 0:
            finite = np.isfinite(xy[:, 0]) & np.isfinite(xy[:, 1])
            xy = xy[finite, :] if np.any(finite) else np.empty((0, 2), dtype=np.float64)
        else:
            xy = np.empty((0, 2), dtype=np.float64)
        traj_xy_index[tid] = xy

        src_path = Path(traj.source_path)
        meta = source_stat_cache.get(src_path)
        if meta is None:
            try:
                st = src_path.stat()
                meta = {"size": int(st.st_size), "mtime_ns": int(st.st_mtime_ns)}
            except Exception:
                meta = {"missing": True}
            source_stat_cache[src_path] = meta
        traj_meta_index[tid] = {"traj_id": tid, **meta}
    return traj_xy_index, traj_meta_index


def run_patch(
    *,
    data_root: str | Path,
    patch_id: str | None = None,
    run_id: str = "auto",
    out_root: str | Path = "outputs/_work/t05_topology_between_rc",
    params_override: dict[str, Any] | None = None,
) -> RunResult:
    repo_root = resolve_repo_root(Path.cwd())
    patch_id_value = str(patch_id or "").strip()
    if not patch_id_value:
        raise InputDataError("patch_id_required")
    params = dict(DEFAULT_PARAMS)
    if params_override:
        params.update(params_override)
    t0_load = perf_counter()
    patch_inputs = load_patch_inputs(
        data_root,
        patch_id_value,
        traj_split_max_gap_m=float(params.get("TRAJ_SPLIT_MAX_GAP_M", TRAJ_SPLIT_MAX_GAP_M_DEFAULT)),
        traj_split_max_time_gap_s=float(
            params.get("TRAJ_SPLIT_MAX_TIME_GAP_S", TRAJ_SPLIT_MAX_TIME_GAP_S_DEFAULT)
        ),
        traj_split_max_seq_gap=int(params.get("TRAJ_SPLIT_MAX_SEQ_GAP", TRAJ_SPLIT_MAX_SEQ_GAP_DEFAULT)),
    )
    t_load_inputs_ms = (perf_counter() - t0_load) * 1000.0

    run_id_val = make_run_id("t05_topology_between_rc", repo_root=repo_root) if run_id == "auto" else str(run_id)

    out_dir = Path(out_root)
    if not out_dir.is_absolute():
        out_dir = (repo_root / out_dir).resolve()
    patch_out = out_dir / run_id_val / "patches" / patch_inputs.patch_id
    progress = _ProgressLogger(patch_out / "progress.ndjson")
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
        write_payload = _normalize_debug_geojson_payload(payload)
        write_json(patch_out / str(rel_path), write_payload)
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
        "pointcloud_timing_ms": 0.0,
        "drivezone_surface_timing_ms": 0.0,
        "drivezone_surface_cache_hit": False,
        "drivezone_surface_cache_key": None,
    }
    t_index_lookup0 = perf_counter()
    traj_xy_index, traj_meta_index = _build_traj_lookup_indexes(patch_inputs)
    stage_timer.add("t_index_traj_lookup", (perf_counter() - t_index_lookup0) * 1000.0)

    xsec_raw_map = _build_cross_section_map(patch_inputs)
    (
        shared_xsec_primary_by_nodeid,
        shared_xsec_group_by_nodeid,
        _shared_xsec_role_by_nodeid,
        shared_xsec_src_alias_by_primary,
        shared_xsec_dst_alias_by_primary,
    ) = _build_shared_intersection_alias_maps(patch_inputs)
    shared_xsec_group_members_by_nodeid = _build_shared_intersection_group_members_map(
        primary_by_nodeid=shared_xsec_primary_by_nodeid,
        group_by_nodeid=shared_xsec_group_by_nodeid,
    )
    xsec_map = _expand_shared_intersection_lookup(
        xsec_raw_map,
        primary_by_nodeid=shared_xsec_primary_by_nodeid,
    )
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
    debug_json_payloads: dict[str, dict[str, Any]] = {}
    pair_stage_debug: dict[str, dict[str, Any]] = {}

    def _pair_stage_key(src_nodeid: int, dst_nodeid: int) -> str:
        return f"{int(src_nodeid)}->{int(dst_nodeid)}"

    def _ensure_pair_stage_entry(src_nodeid: int, dst_nodeid: int) -> dict[str, Any]:
        key = _pair_stage_key(int(src_nodeid), int(dst_nodeid))
        entry = pair_stage_debug.get(key)
        if entry is None:
            entry = {
                "src_nodeid": int(src_nodeid),
                "dst_nodeid": int(dst_nodeid),
                "topology_anchor_status": None,
                "road_prior_shape_ref_available": False,
                "support_found": False,
                "support_mode": None,
                "support_event_count": 0,
                "support_traj_count": 0,
                "support_fallback_attempted": False,
                "support_fallback_failure_stage": None,
                "support_fallback_src_contact_found": None,
                "support_fallback_dst_contact_found": None,
                "support_fallback_src_gap_m": None,
                "support_fallback_dst_gap_m": None,
                "support_fallback_reach_xsec_m": None,
                "support_fallback_inside_ratio": None,
                "support_fallback_inside_ratio_min": None,
                "step1_corridor_status": None,
                "step1_corridor_reason": None,
                "step1_corridor_hint": None,
                "candidate_count": 0,
                "viable_candidate_count": 0,
                "selected_output_count": 0,
                "selected_or_rejected_stage": None,
                "no_geometry_candidate": False,
            }
            pair_stage_debug[key] = entry
        return entry

    def _flush_pair_stage_debug() -> None:
        if not bool(int(params.get("DEBUG_DUMP", 0))):
            return
        debug_json_payloads["debug/pair_stage_status.json"] = {
            "pairs": [
                dict(pair_stage_debug[key])
                for key in sorted(
                    pair_stage_debug.keys(),
                    key=lambda k: (
                        int(pair_stage_debug[k].get("src_nodeid", -1)),
                        int(pair_stage_debug[k].get("dst_nodeid", -1)),
                    ),
                )
            ]
        }

    if bool(int(params.get("DEBUG_DUMP", 0))):
        lane_crs_fix_raw = patch_inputs.input_summary.get("lane_boundary_crs_fix")
        if isinstance(lane_crs_fix_raw, dict) and lane_crs_fix_raw:
            debug_json_payloads["debug/lane_boundary_crs_fix.json"] = dict(lane_crs_fix_raw)
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

    step0_mode_runtime = str(params.get("STEP0_MODE", "off")).strip().lower()
    if step0_mode_runtime in {"off", "disabled", "skip"}:
        xsec_cross_map = dict(xsec_raw_map)
        xsec_anchor_debug_items = []
        xsec_trunc_debug_items = []
        xsec_gate_all_map = {
            int(nodeid): cs.geometry_metric
            for nodeid, cs in xsec_raw_map.items()
            if getattr(cs, "geometry_metric", None) is not None
        }
        xsec_gate_meta_map = {}
        for nodeid, cs in xsec_raw_map.items():
            geom = getattr(cs, "geometry_metric", None)
            len_m = None
            geom_type = ""
            if geom is not None:
                try:
                    len_m = float(geom.length)
                except Exception:
                    len_m = None
                geom_type = str(getattr(geom, "geom_type", "")) if geom is not None else ""
            xsec_gate_meta_map[int(nodeid)] = {
                "len_m": len_m,
                "geom_type": geom_type,
                "fallback": False,
                "mode": "bypass",
                "selected_by": "step0_bypass",
                "selection_source": "step0_bypass",
                "candidate_segment_count": 1,
                "selected_mid_dist_m": 0.0,
                "selected_evidence_len_m": 0.0,
                "in_drivezone_ratio": None,
                "in_divstrip_ratio": None,
                "lite_failed_reasons": [],
                "failed_reason": None,
            }
        xsec_cross_stats = {
            "step0_mode_used": "off",
            "xsec_truncated_count": 0,
            "xsec_truncated_fallback_count": 0,
            "xsec_gate_enabled": False,
            "xsec_gate_selected_count": int(len(xsec_cross_map)),
            "xsec_gate_empty_count": 0,
            "xsec_gate_fallback_count": 0,
            "xsec_passthrough_count": int(len(xsec_cross_map)),
            "xsec_repaired_count": 0,
            "xsec_failed_count": 0,
            "xsec_drivezone_ratio_p10": None,
            "xsec_drivezone_ratio_p50": None,
            "xsec_drivezone_ratio_p90": None,
            "xsec_divstrip_ratio_p10": None,
            "xsec_divstrip_ratio_p50": None,
            "xsec_divstrip_ratio_p90": None,
            "xsec_gate_traj_evidence_enabled": False,
            "xsec_gate_traj_evidence_disabled_reason": "step0_bypass",
            "xsec_gate_traj_point_count": 0,
            "xsec_gate_traj_point_budget": 0,
            "xsec_gate_traj_sample_step": 0,
            "xsec_gate_traj_max_traj": 0,
        }
        if progress is not None:
            progress.mark(
                "xsec_truncate_bypassed",
                xsec_cross_count=int(len(xsec_cross_map)),
                step0_mode="off",
            )
    else:
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
            xsec_map=xsec_raw_map,
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
    xsec_cross_lookup_map = _expand_shared_intersection_lookup(
        xsec_cross_map,
        primary_by_nodeid=shared_xsec_primary_by_nodeid,
    )
    xsec_gate_all_lookup_map = _expand_shared_intersection_lookup(
        xsec_gate_all_map,
        primary_by_nodeid=shared_xsec_primary_by_nodeid,
    )
    xsec_gate_meta_lookup_map = _expand_shared_intersection_lookup(
        xsec_gate_meta_map,
        primary_by_nodeid=shared_xsec_primary_by_nodeid,
    )
    xsec_cross_selected_debug_items: list[dict[str, Any]] = []
    if bool(int(params.get("DEBUG_DUMP", 0))):
        debug_json_payloads["debug/xsec_gate_meta_map.json"] = {
            str(int(k)): dict(v) for k, v in sorted(xsec_gate_meta_lookup_map.items(), key=lambda it: int(it[0]))
        }
        for nodeid, xsec in sorted(xsec_cross_map.items(), key=lambda it: int(it[0])):
            if xsec is None:
                continue
            geom = getattr(xsec, "geometry_metric", None)
            if not isinstance(geom, LineString) or geom.is_empty:
                continue
            meta = dict(xsec_gate_meta_map.get(int(nodeid), {}))
            xsec_cross_selected_debug_items.append(
                {
                    "geometry": geom,
                    "properties": {
                        "nodeid": int(nodeid),
                        "mode": str(meta.get("mode") or ""),
                        "selected_by": str(meta.get("selected_by") or ""),
                        "fallback": bool(meta.get("fallback", False)),
                        "in_drivezone_ratio": meta.get("in_drivezone_ratio"),
                        "in_divstrip_ratio": meta.get("in_divstrip_ratio"),
                    },
                }
            )
    # Step1 must consume only cross-sections that pass Step0 audit/gate.
    node_ids = sorted(int(k) for k in xsec_cross_lookup_map.keys())
    focus_pair_filter = _normalize_focus_pair_filter(params.get("FOCUS_PAIR_FILTER"))
    focus_src_nodeids_filter = _normalize_focus_src_nodeids(
        params.get("FOCUS_SRC_NODEIDS"),
        focus_pairs=focus_pair_filter,
    )
    if bool(int(params.get("DEBUG_DUMP", 0))) and (focus_pair_filter or focus_src_nodeids_filter):
        debug_json_payloads["debug/focus_filter.json"] = {
            "pairs": [
                {"src_nodeid": int(src), "dst_nodeid": int(dst)}
                for src, dst in sorted(focus_pair_filter, key=lambda it: (it[0], it[1]))
            ],
            "src_nodeids": [int(v) for v in sorted(focus_src_nodeids_filter)],
        }
    for src_i, dst_i in sorted(focus_pair_filter, key=lambda it: (int(it[0]), int(it[1]))):
        pair_stage = _ensure_pair_stage_entry(int(src_i), int(dst_i))
        pair_stage["selected_or_rejected_stage"] = "focus_requested"
    pair_cluster_norm_stats: dict[str, Any] = {
        "step1_pair_cluster_disabled": False,
        "step1_pair_cluster_disabled_pair_count": 0,
        "step1_pair_cluster_disabled_event_count": 0,
        "step1_pair_cluster_disabled_hard_multi_removed_count": 0,
    }
    step1_adj_mode = str(params.get("STEP1_ADJ_MODE", "topology_unique")).strip().lower()
    step1_road_prior_respect_direction = bool(int(params.get("STEP1_ROAD_PRIOR_RESPECT_DIRECTION", 1)))
    road_prior_next_map, road_prior_stats = _load_road_prior_adjacency(
        patch_inputs.road_prior_path,
        respect_direction=bool(step1_road_prior_respect_direction),
    )
    step1_topo_respect_direction = bool(int(params.get("STEP1_TOPO_RESPECT_DIRECTION", 1)))
    road_prior_edge_graph, road_prior_edge_stats = _load_road_prior_graph(
        patch_inputs.road_prior_path,
        respect_direction=bool(step1_topo_respect_direction),
        unknown_direction_as_bidirectional=False,
    )
    road_prior_edge_geometry_map, road_prior_edge_geometry_stats = _load_road_prior_edge_geometry_map(
        patch_inputs.road_prior_path,
        to_metric=patch_inputs.projection_to_metric,
        respect_direction=bool(step1_topo_respect_direction),
        unknown_direction_as_bidirectional=False,
    )
    topo_comp_graph: dict[int, list[dict[str, Any]]] = {}
    topo_comp_stats: dict[str, Any] = {}
    if road_prior_edge_graph:
        topo_comp_graph, topo_comp_stats = _compress_topology_graph(
            road_prior_edge_graph,
            cross_nodes={int(v) for v in node_ids},
            enable=bool(int(params.get("STEP1_TOPO_COMPRESS_DEG2", 1))),
        )
    road_prior_pair_shape_ref_map, road_prior_pair_shape_ref_stats = _build_road_prior_pair_shape_ref_map(
        topo_comp_graph,
        edge_geometry_by_id=road_prior_edge_geometry_map,
    )
    step1_topology_enabled = False
    step1_topology_fallback_reason: str | None = None
    step1_topology_allowed_dst_map: dict[int, set[int]] = {}
    step1_topology_allowed_pairs: set[tuple[int, int]] = set()
    step1_topology_node_decisions: dict[int, dict[str, Any]] = {}
    step1_topology_anchor_decisions: dict[str, dict[str, Any]] = {}
    step1_topology_stats: dict[str, Any] = {
        "src_count": int(len(node_ids)),
        "accepted_src_count": 0,
        "unresolved_src_count": 0,
        "multi_dst_src_count": 0,
        "multi_chain_src_count": 0,
        "search_overflow_src_count": 0,
        "compress_enabled": bool(int(params.get("STEP1_TOPO_COMPRESS_DEG2", 1))),
        "compressible_node_count": 0,
        "keep_node_count": 0,
        "raw_node_count": 0,
        "raw_edge_count": 0,
        "compressed_edge_count": 0,
    }
    step1_pair_straight_features: list[dict[str, Any]] = []
    step1_topo_chain_features: list[dict[str, Any]] = []
    if step1_adj_mode == "topology_unique":
        if topo_comp_graph:
            (
                step1_topology_allowed_dst_map,
                step1_topology_allowed_pairs,
                step1_topology_node_decisions,
                step1_topology_anchor_decisions,
                topo_stats,
                step1_pair_straight_features,
                step1_topo_chain_features,
            ) = _build_topology_unique_anchor_decisions(
                topo_comp_graph,
                cross_nodes={int(v) for v in node_ids},
                xsec_map=xsec_cross_lookup_map,
                require_unique_chain=bool(int(params.get("STEP1_TOPO_REQUIRE_UNIQUE_CHAIN", 1))),
                max_expansions=int(max(100, int(params.get("STEP1_TOPO_MAX_EXPANSIONS", 50000)))),
                shared_group_members_by_nodeid=shared_xsec_group_members_by_nodeid,
            )
            step1_topology_enabled = True
            step1_topology_stats.update({str(k): v for k, v in topo_comp_stats.items()})
            step1_topology_stats.update({str(k): v for k, v in topo_stats.items()})
            step1_topology_stats["accepted_pair_count"] = int(len(step1_topology_allowed_pairs))
        else:
            step1_topology_fallback_reason = "road_prior_graph_empty_or_missing"

    if focus_pair_filter or focus_src_nodeids_filter:
        step1_topology_allowed_pairs = {
            (int(src_i), int(dst_i))
            for src_i, dst_i in step1_topology_allowed_pairs
            if (not focus_pair_filter or (int(src_i), int(dst_i)) in focus_pair_filter)
            and (not focus_src_nodeids_filter or int(src_i) in focus_src_nodeids_filter)
        }
        step1_topology_allowed_dst_map = _pairs_to_dst_map(step1_topology_allowed_pairs)
        if focus_src_nodeids_filter:
            step1_topology_node_decisions = {
                int(src_i): dict(decision)
                for src_i, decision in step1_topology_node_decisions.items()
                if int(src_i) in focus_src_nodeids_filter
            }
            step1_topology_anchor_decisions = {
                str(anchor_id): dict(anchor)
                for anchor_id, anchor in step1_topology_anchor_decisions.items()
                if int(anchor.get("src_nodeid", -1)) in focus_src_nodeids_filter
            }
        step1_pair_straight_features = _filter_debug_features_for_focus(
            step1_pair_straight_features,
            focus_pairs=focus_pair_filter,
            focus_src_nodeids=focus_src_nodeids_filter,
        )
        step1_topo_chain_features = _filter_debug_features_for_focus(
            step1_topo_chain_features,
            focus_pairs=focus_pair_filter,
            focus_src_nodeids=focus_src_nodeids_filter,
        )
        step1_topology_stats["accepted_pair_count"] = int(len(step1_topology_allowed_pairs))

    step1_road_prior_filter_enabled = (
        (not bool(step1_topology_enabled))
        and bool(int(params.get("STEP1_USE_ROAD_PRIOR_ADJ_FILTER", 1)))
        and bool(road_prior_next_map)
    )
    step1_allowed_dst_filter_map: dict[int, set[int]] | None = (
        step1_topology_allowed_dst_map
        if bool(step1_topology_enabled)
        else (road_prior_next_map if bool(step1_road_prior_filter_enabled) else None)
    )
    step1_allowed_pair_filter_set: set[tuple[int, int]] | None = (
        set(step1_topology_allowed_pairs) if bool(step1_topology_enabled) else None
    )
    if focus_pair_filter:
        step1_allowed_pair_filter_set = (
            set(step1_allowed_pair_filter_set).intersection(focus_pair_filter)
            if step1_allowed_pair_filter_set is not None
            else set(focus_pair_filter)
        )
    if focus_src_nodeids_filter:
        if step1_allowed_pair_filter_set is not None:
            step1_allowed_pair_filter_set = {
                (int(src_i), int(dst_i))
                for src_i, dst_i in step1_allowed_pair_filter_set
                if int(src_i) in focus_src_nodeids_filter
            }
        if step1_allowed_dst_filter_map is not None:
            step1_allowed_dst_filter_map = {
                int(src_i): {int(v) for v in dsts}
                for src_i, dsts in step1_allowed_dst_filter_map.items()
                if int(src_i) in focus_src_nodeids_filter
            }
    step1_road_prior_reject_crossing_count = 0
    step1_road_prior_reject_candidate_total = 0
    step1_resolved_by_dist_margin_count = 0
    topology_fallback_support_count = 0
    if bool(int(params.get("DEBUG_DUMP", 0))):
        debug_json_payloads["debug/step1_road_prior_adjacency.json"] = {
            "enabled": bool(step1_road_prior_filter_enabled),
            "stats": dict(road_prior_stats),
            "edge_stats": dict(road_prior_edge_stats),
            "edge_geometry_stats": dict(road_prior_edge_geometry_stats),
            "pair_shape_ref_stats": dict(road_prior_pair_shape_ref_stats),
            "src_node_count": int(len(road_prior_next_map)),
        }
        debug_json_payloads["debug/step1_topology_unique_map.json"] = {
            "mode": str(step1_adj_mode),
            "enabled": bool(step1_topology_enabled),
            "fallback_reason": step1_topology_fallback_reason,
            "stats": dict(step1_topology_stats),
            "road_prior_edge_stats": dict(road_prior_edge_stats),
            "nodes": {
                str(int(k)): dict(v)
                for k, v in sorted(step1_topology_node_decisions.items(), key=lambda it: int(it[0]))
            },
            "anchors": {
                str(k): dict(v)
                for k, v in sorted(step1_topology_anchor_decisions.items(), key=lambda it: str(it[0]))
            },
        }
        debug_json_payloads["debug/step1_pair_straight_segments.geojson"] = {
            "type": "FeatureCollection",
            "features": list(step1_pair_straight_features),
        }
        debug_json_payloads["debug/step1_topo_chain_segments.geojson"] = {
            "type": "FeatureCollection",
            "features": list(step1_topo_chain_features),
        }
    for src_i, dst_i in sorted(step1_topology_allowed_pairs, key=lambda it: (int(it[0]), int(it[1]))):
        pair_stage = _ensure_pair_stage_entry(int(src_i), int(dst_i))
        pair_stage["topology_anchor_status"] = "accepted"
        pair_stage["road_prior_shape_ref_available"] = bool(
            _is_valid_linestring(road_prior_pair_shape_ref_map.get((int(src_i), int(dst_i))))
        )
        pair_stage["selected_or_rejected_stage"] = "topology_accepted"

    def _timing_extra_metrics() -> dict[str, Any]:
        required = (
            "t_load_traj",
            "t_load_pointcloud",
            "t_sample_drivezone_surface",
            "t_build_traj_projection",
            "t_build_traj_surface_compute",
            "t_build_surfaces_total",
            "t_build_lane_graph",
            "t_shortest_path_total",
            "t_centerline_offset",
            "t_gate_in_ratio",
            "t_debug_dump",
            "t_index_traj_lookup",
        )
        payload: dict[str, Any] = {}
        for k in required:
            if str(k) == "t_build_traj_projection":
                payload[str(k)] = float(round(stage_timer.ms.get("t_build_traj_surface_compute", 0.0), 3))
                continue
            payload[str(k)] = float(round(stage_timer.ms.get(str(k), 0.0), 3))
        payload["t_build_surfaces_per_k_ms"] = {k: float(round(v, 3)) for k, v in sorted(surface_timing_per_k.items())}
        payload["t_shortest_path_per_k_ms"] = {k: float(round(v, 3)) for k, v in sorted(shortest_timing_per_k.items())}
        payload["traj_surface_cache_hit_count"] = int(surface_cache_hit_count)
        payload["traj_surface_cache_miss_count"] = int(surface_cache_miss_count)
        payload["focus_pair_filter_count"] = int(len(focus_pair_filter))
        payload["focus_src_nodeid_count"] = int(len(focus_src_nodeids_filter))
        if focus_pair_filter:
            payload["focus_pairs"] = [f"{int(src)}->{int(dst)}" for src, dst in sorted(focus_pair_filter)]
        if focus_src_nodeids_filter:
            payload["focus_src_nodeids"] = [int(v) for v in sorted(focus_src_nodeids_filter)]
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
        for key in (
            "traj_source_count",
            "traj_segment_count",
            "traj_split_source_count",
            "traj_split_by_distance_count",
            "traj_split_by_time_count",
            "traj_split_by_seq_count",
            "traj_split_distance_gap_m_p50",
            "traj_split_distance_gap_m_p90",
            "traj_split_distance_gap_m_max",
            "traj_split_time_gap_s_p50",
            "traj_split_time_gap_s_p90",
            "traj_split_time_gap_s_max",
            "traj_split_seq_gap_p50",
            "traj_split_seq_gap_p90",
            "traj_split_seq_gap_max",
        ):
            if key in patch_inputs.input_summary:
                payload[str(key)] = patch_inputs.input_summary.get(key)
        payload["step1_road_prior_filter_enabled"] = bool(step1_road_prior_filter_enabled)
        payload["step1_road_prior_respect_direction"] = bool(step1_road_prior_respect_direction)
        payload["step1_road_prior_edge_count"] = int(road_prior_stats.get("edge_count", 0))
        payload["step1_road_prior_src_count"] = int(road_prior_stats.get("src_node_count", 0))
        payload["step1_road_prior_reject_crossing_count"] = int(step1_road_prior_reject_crossing_count)
        payload["step1_road_prior_reject_candidate_total"] = int(step1_road_prior_reject_candidate_total)
        payload["step1_resolved_by_dist_margin_count"] = int(step1_resolved_by_dist_margin_count)
        payload["step1_adj_mode"] = str(step1_adj_mode)
        payload["step1_topology_enabled"] = bool(step1_topology_enabled)
        payload["step1_topology_fallback_reason"] = step1_topology_fallback_reason
        payload["step1_topology_respect_direction"] = bool(step1_topo_respect_direction)
        payload["step1_topology_edge_count"] = int(road_prior_edge_stats.get("edge_count", 0))
        payload["step1_topology_src_count"] = int(step1_topology_stats.get("src_count", 0))
        payload["step1_topology_accepted_src_count"] = int(step1_topology_stats.get("accepted_src_count", 0))
        payload["step1_topology_unresolved_src_count"] = int(step1_topology_stats.get("unresolved_src_count", 0))
        payload["step1_topology_multi_dst_src_count"] = int(step1_topology_stats.get("multi_dst_src_count", 0))
        payload["step1_topology_multi_chain_src_count"] = int(step1_topology_stats.get("multi_chain_src_count", 0))
        payload["step1_topology_search_overflow_src_count"] = int(step1_topology_stats.get("search_overflow_src_count", 0))
        payload["step1_topology_compressible_node_count"] = int(step1_topology_stats.get("compressible_node_count", 0))
        payload["step1_topology_keep_node_count"] = int(step1_topology_stats.get("keep_node_count", 0))
        payload["step1_topology_compressed_edge_count"] = int(step1_topology_stats.get("compressed_edge_count", 0))
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
            debug_json_payloads=debug_json_payloads,
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
        focus_src_nodeids: set[int] | None = None,
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
            unique_dst_early_stop=bool(int(params.get("STEP1_UNIQUE_DST_EARLY_STOP", 1))),
            unique_dst_dist_eps_m=float(params.get("STEP1_UNIQUE_DST_DIST_EPS_M", 5.0)),
            allowed_dst_by_src=step1_allowed_dst_filter_map,
            allowed_pairs=step1_allowed_pair_filter_set,
            single_support_per_pair=bool(int(params.get("STEP1_SINGLE_SUPPORT_PER_PAIR", 1))),
            skip_search_after_pair_resolved=bool(int(params.get("STEP1_SKIP_SEARCH_AFTER_PAIR_RESOLVED", 1))),
            src_nodeid_alias_by_nodeid=shared_xsec_src_alias_by_primary,
            dst_nodeid_alias_by_nodeid=shared_xsec_dst_alias_by_primary,
            allowed_dst_close_hit_buffer_m=float(hit_buffer_m),
            focus_src_nodeids=focus_src_nodeids,
            pair_target_max_intermediate_crossings=(
                int(params["STEP1_PAIR_TARGET_MAX_INTERMEDIATE_XSECS"])
                if params.get("STEP1_PAIR_TARGET_MAX_INTERMEDIATE_XSECS") is not None
                else None
            ),
        )
        nt_map, indeg_map, outdeg_map = infer_node_types(
            node_ids=node_ids,
            pair_supports=supports_seed_obj.supports,
            node_kind_map=patch_inputs.node_kind_map,
        )
        rebuild_with_inferred = bool(int(params.get("STEP1_REBUILD_SUPPORTS_WITH_INFERRED_TYPES", 0)))
        if rebuild_with_inferred:
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
                unique_dst_early_stop=bool(int(params.get("STEP1_UNIQUE_DST_EARLY_STOP", 1))),
                unique_dst_dist_eps_m=float(params.get("STEP1_UNIQUE_DST_DIST_EPS_M", 5.0)),
                allowed_dst_by_src=step1_allowed_dst_filter_map,
                allowed_pairs=step1_allowed_pair_filter_set,
                single_support_per_pair=bool(int(params.get("STEP1_SINGLE_SUPPORT_PER_PAIR", 1))),
                skip_search_after_pair_resolved=bool(int(params.get("STEP1_SKIP_SEARCH_AFTER_PAIR_RESOLVED", 1))),
                src_nodeid_alias_by_nodeid=shared_xsec_src_alias_by_primary,
                dst_nodeid_alias_by_nodeid=shared_xsec_dst_alias_by_primary,
                allowed_dst_close_hit_buffer_m=float(hit_buffer_m),
                focus_src_nodeids=focus_src_nodeids,
                pair_target_max_intermediate_crossings=(
                    int(params["STEP1_PAIR_TARGET_MAX_INTERMEDIATE_XSECS"])
                    if params.get("STEP1_PAIR_TARGET_MAX_INTERMEDIATE_XSECS") is not None
                    else None
                ),
            )
        else:
            supports_obj = supports_seed_obj
        return cross_obj, supports_obj, nt_map, indeg_map, outdeg_map

    def _result_src_nodeid(item: dict[str, Any]) -> int | None:
        try:
            return int(item.get("src_nodeid"))
        except Exception:
            return None

    def _result_quality_for_src(res: PairSupportBuildResult, src_nodeid: int) -> tuple[int, int, int, int]:
        src_i = int(src_nodeid)
        pair_count = 0
        support_events = 0
        for (src_raw, _dst_raw), pair_support in res.supports.items():
            if int(src_raw) != src_i:
                continue
            pair_count += 1
            support_events += max(1, int(pair_support.support_event_count))
        resolved_hits = sum(
            1
            for cand in res.next_crossing_candidates
            if _result_src_nodeid(cand) == src_i and (not bool(cand.get("unresolved", False)))
        )
        unresolved_count = sum(1 for item in res.unresolved_events if _result_src_nodeid(item) == src_i)
        return (pair_count, support_events, resolved_hits, -unresolved_count)

    def _merge_pair_support_results(
        base: PairSupportBuildResult,
        override: PairSupportBuildResult,
        *,
        focus_src_nodeids: set[int],
    ) -> PairSupportBuildResult:
        focus_srcs = {int(v) for v in focus_src_nodeids}
        merged_supports = {
            pair: pair_support
            for pair, pair_support in base.supports.items()
            if int(pair[0]) not in focus_srcs
        }
        for pair, pair_support in override.supports.items():
            if int(pair[0]) in focus_srcs:
                merged_supports[pair] = pair_support

        def _merge_event_list(
            base_items: list[dict[str, Any]],
            override_items: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            merged = [item for item in base_items if _result_src_nodeid(item) not in focus_srcs]
            merged.extend(item for item in override_items if _result_src_nodeid(item) in focus_srcs)
            return merged

        merged_votes = {
            int(src): votes
            for src, votes in base.node_dst_votes.items()
            if int(src) not in focus_srcs
        }
        for src, votes in override.node_dst_votes.items():
            src_i = int(src)
            if src_i in focus_srcs:
                merged_votes[src_i] = votes

        merged_hist: dict[str, int] = {}
        for hist in (base.stitch_levels_used_hist, override.stitch_levels_used_hist):
            for raw_key, raw_val in hist.items():
                key = str(raw_key)
                merged_hist[key] = max(int(merged_hist.get(key, 0)), int(raw_val))

        return PairSupportBuildResult(
            supports=merged_supports,
            unresolved_events=_merge_event_list(base.unresolved_events, override.unresolved_events),
            graph_node_count=max(int(base.graph_node_count), int(override.graph_node_count)),
            graph_edge_count=max(int(base.graph_edge_count), int(override.graph_edge_count)),
            stitch_candidate_count=max(int(base.stitch_candidate_count), int(override.stitch_candidate_count)),
            stitch_edge_count=max(int(base.stitch_edge_count), int(override.stitch_edge_count)),
            stitch_query_count=max(int(base.stitch_query_count), int(override.stitch_query_count)),
            stitch_candidates_total=max(int(base.stitch_candidates_total), int(override.stitch_candidates_total)),
            stitch_reject_dist_count=max(int(base.stitch_reject_dist_count), int(override.stitch_reject_dist_count)),
            stitch_reject_angle_count=max(int(base.stitch_reject_angle_count), int(override.stitch_reject_angle_count)),
            stitch_reject_forward_count=max(
                int(base.stitch_reject_forward_count),
                int(override.stitch_reject_forward_count),
            ),
            stitch_accept_count=max(int(base.stitch_accept_count), int(override.stitch_accept_count)),
            stitch_levels_used_hist=merged_hist,
            ambiguous_events=_merge_event_list(base.ambiguous_events, override.ambiguous_events),
            next_crossing_candidates=_merge_event_list(base.next_crossing_candidates, override.next_crossing_candidates),
            node_dst_votes=merged_votes,
        )

    def _merge_nodewise_map_for_improved_sources(
        base_map: dict[int, Any],
        override_map: dict[int, Any],
        *,
        focus_src_nodeids: set[int],
        override_supports: dict[tuple[int, int], PairSupport],
    ) -> dict[int, Any]:
        merged = dict(base_map)
        touched_nodeids = {int(v) for v in focus_src_nodeids}
        for (src_i, dst_i), pair_support in override_supports.items():
            if int(src_i) not in focus_src_nodeids or int(pair_support.support_event_count) <= 0:
                continue
            touched_nodeids.add(int(src_i))
            touched_nodeids.add(int(dst_i))
        for nodeid in touched_nodeids:
            if int(nodeid) in override_map:
                merged[int(nodeid)] = override_map[int(nodeid)]
        return merged

    pass1_cross, pass1_supports, pass1_node_type_map, pass1_in_degree, pass1_out_degree = _run_neighbor_pass(
        hit_buffer_m=float(params["TRAJ_XSEC_HIT_BUFFER_M"]),
        stitch_max_dist_m=float(params["STITCH_MAX_DIST_M"]),
        stitch_forward_dot_min=float(params["STITCH_FORWARD_DOT_MIN"]),
        neighbor_max_dist_m=float(params["NEIGHBOR_MAX_DIST_M"]),
        focus_src_nodeids=(set(focus_src_nodeids_filter) if focus_src_nodeids_filter else None),
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
    pass2_unresolved_ratio_trigger = float(max(1.0, float(params.get("PASS2_UNRESOLVED_RATIO_TRIGGER", 6.0))))
    pass2_force_when_no_stitch = bool(int(params.get("PASS2_FORCE_WHEN_STITCH_ACCEPT_ZERO", 1)))
    pass1_cross_distance_reject_count = int(getattr(pass1_cross, "n_cross_distance_gate_reject", 0) or 0)
    pass1_has_recall_signal = bool(pass1_cross_distance_reject_count > 0 or pass1_supports.next_crossing_candidates)
    unresolved_trigger = pass1_unresolved_count >= max(
        pass2_unresolved_min,
        int(math.ceil(pass2_unresolved_per_support * max(1, pass1_pair_count))),
    )
    dense_unresolved_trigger = (
        bool(pass1_has_recall_signal)
        and pass1_pair_count > 0
        and pass1_unresolved_count >= max(
            pass2_unresolved_min,
            int(math.ceil(pass2_unresolved_ratio_trigger * max(1, pass1_pair_count))),
        )
    )
    sparse_support_trigger = pass1_pair_count <= 1 and pass1_unresolved_count >= max(5, pass2_unresolved_min // 2)
    should_try_pass2 = (
        pass1_pair_count == 0
        or dense_unresolved_trigger
        or (
            pass2_force_when_no_stitch
            and pass1_stitch_accept_count <= 0
            and (unresolved_trigger or sparse_support_trigger)
        )
    )
    pass2_attempted = False

    if should_try_pass2:
        pass2_attempted = True
        pass2_focus_src_nodeids = (
            {
                int(src_i)
                for src_i in (_result_src_nodeid(item) for item in pass1_supports.unresolved_events)
                if src_i is not None
            }
            if pass1_pair_count > 0
            else None
        )
        if pass1_pair_count > 0 and not pass2_focus_src_nodeids:
            pass2_focus_src_nodeids = None
        if progress is not None:
            progress.mark(
                "neighbor_pass2_start",
                focus_src_count=(int(len(pass2_focus_src_nodeids)) if pass2_focus_src_nodeids is not None else None),
            )
        pass2_cross, pass2_supports, pass2_node_type_map, pass2_in_degree, pass2_out_degree = _run_neighbor_pass(
            hit_buffer_m=float(params["PASS2_TRAJ_XSEC_HIT_BUFFER_M"]),
            stitch_max_dist_m=float(params["PASS2_STITCH_MAX_DIST_M"]),
            stitch_forward_dot_min=float(params["PASS2_STITCH_FORWARD_DOT_MIN"]),
            neighbor_max_dist_m=float(params["PASS2_NEIGHBOR_MAX_DIST_M"]),
            focus_src_nodeids=pass2_focus_src_nodeids,
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
        elif pass2_focus_src_nodeids:
            improved_src_nodeids = {
                int(src_i)
                for src_i in pass2_focus_src_nodeids
                if _result_quality_for_src(pass2_supports, int(src_i))
                > _result_quality_for_src(pass1_supports, int(src_i))
            }
            if improved_src_nodeids:
                neighbor_search_pass = 2
                supports_result = _merge_pair_support_results(
                    pass1_supports,
                    pass2_supports,
                    focus_src_nodeids=improved_src_nodeids,
                )
                node_type_map = _merge_nodewise_map_for_improved_sources(
                    pass1_node_type_map,
                    pass2_node_type_map,
                    focus_src_nodeids=improved_src_nodeids,
                    override_supports=pass2_supports.supports,
                )
                in_degree = _merge_nodewise_map_for_improved_sources(
                    pass1_in_degree,
                    pass2_in_degree,
                    focus_src_nodeids=improved_src_nodeids,
                    override_supports=pass2_supports.supports,
                )
                out_degree = _merge_nodewise_map_for_improved_sources(
                    pass1_out_degree,
                    pass2_out_degree,
                    focus_src_nodeids=improved_src_nodeids,
                    override_supports=pass2_supports.supports,
                )

    for cand in supports_result.next_crossing_candidates:
        if not isinstance(cand, dict):
            continue
        if bool(cand.get("resolved_by_dist_margin", False)):
            step1_resolved_by_dist_margin_count += 1
        if not step1_road_prior_filter_enabled:
            continue
        if not bool(cand.get("road_prior_filter_applied", False)):
            continue
        rej = cand.get("road_prior_reject_count", 0)
        try:
            rej_i = int(rej)
        except Exception:
            rej_i = 0
        if rej_i > 0:
            step1_road_prior_reject_crossing_count += 1
            step1_road_prior_reject_candidate_total += int(rej_i)

    _append_cross_breakpoints(cross_result)
    supports = dict(supports_result.supports)
    step1_ambiguous_crossing_count = int(len(supports_result.ambiguous_events))
    step1_ambiguous_node_count = 0
    step1_unique_pair_count = 0
    step1_vote_main_ratio_vals: list[float] = []
    step1_node_dst_votes_debug: dict[str, dict[str, Any]] = {}
    step1_ambiguous_src_nodes: set[int] = set()
    step1_ambiguous_nodes_hint: dict[int, str] = {}
    step1_next_crossing_candidate_features: list[dict[str, Any]] = []
    for item in supports_result.ambiguous_events:
        soft_breakpoints.append(dict(item))
    for cand in supports_result.next_crossing_candidates:
        if not isinstance(cand, dict):
            continue
        src_point = cand.get("src_point")
        if not isinstance(src_point, Point) or src_point.is_empty:
            continue
        dst_candidates: list[dict[str, Any]] = []
        for dc in cand.get("dst_candidates", []):
            if not isinstance(dc, dict):
                continue
            try:
                dst_nodeid = int(dc.get("dst_nodeid"))
            except Exception:
                continue
            try:
                dist_m = float(dc.get("dist_m"))
            except Exception:
                dist_m = None
            try:
                stitch_hops = int(dc.get("stitch_hops"))
            except Exception:
                stitch_hops = None
            dst_candidates.append(
                {
                    "dst_nodeid": int(dst_nodeid),
                    "dist_m": float(dist_m) if dist_m is not None and np.isfinite(dist_m) else None,
                    "stitch_hops": int(stitch_hops) if stitch_hops is not None else None,
                    "target_key": str(dc.get("target_key") or ""),
                }
            )
        step1_next_crossing_candidate_features.append(
            {
                "type": "Feature",
                "geometry": mapping(src_point),
                "properties": {
                    "src_nodeid": int(cand.get("src_nodeid")) if cand.get("src_nodeid") is not None else None,
                    "src_cross_id": str(cand.get("src_cross_id") or ""),
                    "traj_id": str(cand.get("traj_id") or ""),
                    "seq_idx": int(cand.get("seq_idx")) if cand.get("seq_idx") is not None else None,
                    "station_m": float(cand.get("station_m")) if cand.get("station_m") is not None else None,
                    "dst_nodeids_found": [int(v) for v in (cand.get("dst_nodeids_found") or [])],
                    "dst_nodeids_found_count": int(cand.get("dst_nodeids_found_count") or 0),
                    "dst_candidates": dst_candidates,
                    "chosen_dst_nodeid": (
                        int(cand.get("chosen_dst_nodeid")) if cand.get("chosen_dst_nodeid") is not None else None
                    ),
                    "chosen_dist_m": float(cand.get("chosen_dist_m")) if cand.get("chosen_dist_m") is not None else None,
                    "ambiguous": bool(cand.get("ambiguous", False)),
                    "unresolved": bool(cand.get("unresolved", False)),
                    "resolved_by_dist_margin": bool(cand.get("resolved_by_dist_margin", False)),
                    "resolved_by_dist_margin_dst_nodeid": (
                        int(cand.get("resolved_by_dist_margin_dst_nodeid"))
                        if cand.get("resolved_by_dist_margin_dst_nodeid") is not None
                        else None
                    ),
                },
            }
        )
    for unresolved in supports_result.unresolved_events:
        soft_breakpoints.append(dict(unresolved))

    node_vote_min_ratio = float(params.get("STEP1_NODE_VOTE_MIN_RATIO", 1.0))
    node_vote_min_ratio = float(min(1.0, max(0.0, node_vote_min_ratio)))
    strict_unique_required = bool(node_vote_min_ratio >= 1.0 - 1e-9)
    preferred_dst_by_src: dict[int, int] = {}
    if step1_topology_enabled:
        accepted_pairs: set[tuple[int, int]] = set(step1_topology_allowed_pairs)
        for src_i, dst_i in sorted(focus_pair_filter, key=lambda it: (int(it[0]), int(it[1]))):
            if (int(src_i), int(dst_i)) in accepted_pairs:
                continue
            pair_stage = _ensure_pair_stage_entry(int(src_i), int(dst_i))
            pair_stage["topology_anchor_status"] = "not_accepted"
            pair_stage["road_prior_shape_ref_available"] = bool(
                _is_valid_linestring(road_prior_pair_shape_ref_map.get((int(src_i), int(dst_i))))
            )
            if pair_stage.get("selected_or_rejected_stage") in {None, "focus_requested"}:
                pair_stage["selected_or_rejected_stage"] = "topology_not_accepted"
        for src_i, decision in sorted(step1_topology_node_decisions.items(), key=lambda it: int(it[0])):
            status = str(decision.get("status") or "unresolved")
            dst_nodeids = [int(v) for v in (decision.get("dst_nodeids") or []) if v is not None]
            dst_vote_raw = decision.get("dst_vote_map")
            if isinstance(dst_vote_raw, dict):
                dst_vote_items = sorted(
                    (
                        (int(dst), int(cnt))
                        for dst, cnt in dst_vote_raw.items()
                        if dst is not None and int(cnt) > 0
                    ),
                    key=lambda it: (-int(it[1]), int(it[0])),
                )
            else:
                dst_vote_items = []
            if not dst_vote_items and dst_nodeids:
                dst_vote_items = [(int(dst), 1) for dst in dst_nodeids]
            dst_vote_items = sorted(
                ((int(dst), int(cnt)) for dst, cnt in dst_vote_items),
                key=lambda it: (-int(it[1]), int(it[0])),
            )
            total_votes = int(sum(int(v) for _, v in dst_vote_items))
            main_dst = int(dst_vote_items[0][0]) if dst_vote_items else None
            main_votes = int(dst_vote_items[0][1]) if dst_vote_items else 0
            main_ratio = (float(main_votes) / float(total_votes)) if total_votes > 0 else 0.0
            top2_gap = (
                float(main_votes - int(dst_vote_items[1][1])) / float(total_votes)
                if total_votes > 0 and len(dst_vote_items) > 1
                else 1.0
            )
            if np.isfinite(main_ratio):
                step1_vote_main_ratio_vals.append(float(main_ratio))

            has_multi_dst_anchor = bool(decision.get("has_multi_dst_anchor", False))
            has_multi_chain_anchor = bool(decision.get("has_multi_chain_anchor", False))
            search_overflow = bool(decision.get("search_overflow", False))
            if status != "accepted":
                soft_breakpoints.append(
                    {
                        "road_id": f"na_{int(src_i)}",
                        "src_nodeid": int(src_i),
                        "dst_nodeid": None,
                        "traj_id": None,
                        "seq_range": None,
                        "station_range_m": None,
                        "reason": SOFT_UNRESOLVED_NEIGHBOR,
                        "severity": "soft",
                        "hint": (
                            f"topology_unique_unresolved;"
                            f"search_overflow={bool(search_overflow)};"
                            f"anchor_count={int(decision.get('anchor_count', 0))}"
                        ),
                    }
                )
            if has_multi_dst_anchor or has_multi_chain_anchor:
                hint_bits = [
                    f"has_multi_dst_anchor={bool(has_multi_dst_anchor)}",
                    f"has_multi_chain_anchor={bool(has_multi_chain_anchor)}",
                    f"dst_candidates={','.join(str(v) for v in dst_nodeids)}",
                    f"anchor_count={int(decision.get('anchor_count', 0))}",
                    f"search_overflow={bool(search_overflow)}",
                ]
                hint = ";".join(hint_bits)
                step1_ambiguous_src_nodes.add(int(src_i))
                step1_ambiguous_nodes_hint[int(src_i)] = hint
                step1_ambiguous_node_count += 1
                soft_breakpoints.append(
                    {
                        "road_id": f"na_{int(src_i)}",
                        "src_nodeid": int(src_i),
                        "dst_nodeid": int(main_dst) if main_dst is not None else None,
                        "traj_id": None,
                        "seq_range": None,
                        "station_range_m": None,
                        "reason": SOFT_AMBIGUOUS_NEXT_XSEC,
                        "severity": "soft",
                        "hint": f"topology_anchor_ambiguous;{hint}",
                    }
                )

            step1_node_dst_votes_debug[str(int(src_i))] = {
                "dst_vote_map": {str(int(dst)): int(cnt) for dst, cnt in dst_vote_items},
                "dst_count": int(len(dst_vote_items)),
                "total_votes": int(total_votes),
                "main_dst": int(main_dst) if main_dst is not None else None,
                "main_ratio": float(main_ratio),
                "top2_gap": float(top2_gap),
                "threshold": float(node_vote_min_ratio),
                "decision": str(status),
                "topology_unique_mode": True,
                "chosen_dst_nodeid": (
                    int(decision.get("chosen_dst_nodeid")) if decision.get("chosen_dst_nodeid") is not None else None
                ),
                "search_overflow": bool(search_overflow),
                "anchor_count": int(decision.get("anchor_count", 0)),
                "has_multi_dst_anchor": bool(has_multi_dst_anchor),
                "has_multi_chain_anchor": bool(has_multi_chain_anchor),
            }

        step1_same_dst_multi_chain_pairs = _collect_same_dst_multi_chain_pairs(
            step1_topology_anchor_decisions,
            accepted_pairs=accepted_pairs,
        )
        if bool(int(params.get("DEBUG_DUMP", 0))) and step1_same_dst_multi_chain_pairs:
            debug_json_payloads["debug/step1_same_pair_multichain.json"] = {
                "pairs": [
                    dict(payload)
                    for _, payload in sorted(
                        step1_same_dst_multi_chain_pairs.items(),
                        key=lambda it: (int(it[0][0]), int(it[0][1])),
                    )
                ]
            }

        supports = {
            (int(src), int(dst)): support
            for (src, dst), support in supports.items()
            if (int(src), int(dst)) in accepted_pairs
        }
        for src_i, dst_i in sorted(accepted_pairs, key=lambda it: (int(it[0]), int(it[1]))):
            pair_stage = _ensure_pair_stage_entry(int(src_i), int(dst_i))
            support_obj = supports.get((int(src_i), int(dst_i)))
            if support_obj is not None:
                pair_stage["support_found"] = True
                pair_stage["support_mode"] = "traj_support"
                pair_stage["support_event_count"] = int(support_obj.support_event_count)
                pair_stage["support_traj_count"] = int(len(support_obj.support_traj_ids))
                pair_stage["selected_or_rejected_stage"] = "support_ready"
                continue
            src_cs = xsec_cross_lookup_map.get(int(src_i))
            dst_cs = xsec_cross_lookup_map.get(int(dst_i))
            src_geom = getattr(src_cs, "geometry_metric", None)
            dst_geom = getattr(dst_cs, "geometry_metric", None)
            fallback_diag: dict[str, Any] = {}
            fallback_support = _build_topology_road_prior_fallback_support(
                pair=(int(src_i), int(dst_i)),
                shape_ref_metric=road_prior_pair_shape_ref_map.get((int(src_i), int(dst_i))),
                src_xsec=src_geom if isinstance(src_geom, LineString) else LineString(),
                dst_xsec=dst_geom if isinstance(dst_geom, LineString) else LineString(),
                drivezone_zone_metric=patch_inputs.drivezone_zone_metric,
                gore_zone_metric=gore_zone_metric_raw,
                src_type=node_type_map.get(int(src_i)),
                dst_type=node_type_map.get(int(dst_i)),
                params=params,
                debug_out=fallback_diag,
            )
            pair_stage["support_fallback_attempted"] = bool(fallback_diag.get("attempted", False))
            pair_stage["support_fallback_failure_stage"] = fallback_diag.get("failure_stage")
            pair_stage["support_fallback_src_contact_found"] = fallback_diag.get("src_contact_found")
            pair_stage["support_fallback_dst_contact_found"] = fallback_diag.get("dst_contact_found")
            pair_stage["support_fallback_src_gap_m"] = fallback_diag.get("src_gap_m")
            pair_stage["support_fallback_dst_gap_m"] = fallback_diag.get("dst_gap_m")
            pair_stage["support_fallback_reach_xsec_m"] = fallback_diag.get("reach_xsec_m")
            pair_stage["support_fallback_inside_ratio"] = fallback_diag.get("inside_ratio")
            pair_stage["support_fallback_inside_ratio_min"] = fallback_diag.get("inside_ratio_min")
            if fallback_support is not None:
                supports[(int(src_i), int(dst_i))] = fallback_support
                topology_fallback_support_count += 1
                pair_stage["support_found"] = True
                pair_stage["support_mode"] = "topology_road_prior_fallback"
                pair_stage["support_event_count"] = 0
                pair_stage["support_traj_count"] = 0
                pair_stage["selected_or_rejected_stage"] = "support_fallback_ready"
            else:
                pair_stage["selected_or_rejected_stage"] = "support_missing_after_topology"
    else:
        step1_same_dst_multi_chain_pairs = {}
        for src_nodeid, vote_raw in sorted(dict(supports_result.node_dst_votes).items(), key=lambda it: int(it[0])):
            src_i = int(src_nodeid)
            votes = {
                int(dst): int(cnt)
                for dst, cnt in dict(vote_raw).items()
                if int(cnt) > 0
            }
            ordered_votes = sorted(votes.items(), key=lambda it: (-int(it[1]), int(it[0])))
            total_votes = int(sum(int(v) for _, v in ordered_votes))
            main_dst = int(ordered_votes[0][0]) if ordered_votes else None
            main_votes = int(ordered_votes[0][1]) if ordered_votes else 0
            main_ratio = (float(main_votes) / float(total_votes)) if total_votes > 0 else 0.0
            top2_gap = (
                float(main_votes - int(ordered_votes[1][1])) / float(total_votes)
                if total_votes > 0 and len(ordered_votes) > 1
                else 1.0
            )
            if np.isfinite(main_ratio):
                step1_vote_main_ratio_vals.append(float(main_ratio))
            dst_count = int(len(ordered_votes))
            decision = "OK" if dst_count <= 1 else "OK_BY_VOTE"
            if dst_count > 1:
                if strict_unique_required or main_ratio < node_vote_min_ratio:
                    decision = HARD_MULTI_NEIGHBOR_FOR_NODE
                    step1_ambiguous_src_nodes.add(int(src_i))
                    step1_ambiguous_nodes_hint[int(src_i)] = (
                        f"dst_votes={','.join(f'{dst}:{cnt}' for dst, cnt in ordered_votes)};"
                        f"main_dst={main_dst};main_ratio={main_ratio:.3f};"
                        f"threshold={node_vote_min_ratio:.3f}"
                    )
                    hard_breakpoints.append(
                        {
                            "road_id": f"na_{int(src_i)}",
                            "src_nodeid": int(src_i),
                            "dst_nodeid": None,
                            "reason": HARD_MULTI_NEIGHBOR_FOR_NODE,
                            "severity": "hard",
                            "hint": step1_ambiguous_nodes_hint[int(src_i)],
                        }
                    )
                    step1_ambiguous_node_count += 1
                elif main_dst is not None:
                    preferred_dst_by_src[int(src_i)] = int(main_dst)
            elif main_dst is not None:
                preferred_dst_by_src[int(src_i)] = int(main_dst)
            step1_node_dst_votes_debug[str(int(src_i))] = {
                "dst_vote_map": {str(int(dst)): int(cnt) for dst, cnt in ordered_votes},
                "dst_count": int(dst_count),
                "total_votes": int(total_votes),
                "main_dst": int(main_dst) if main_dst is not None else None,
                "main_ratio": float(main_ratio),
                "top2_gap": float(top2_gap),
                "threshold": float(node_vote_min_ratio),
                "decision": str(decision),
                "topology_unique_mode": False,
            }

        if step1_ambiguous_src_nodes or preferred_dst_by_src:
            filtered_supports: dict[tuple[int, int], PairSupport] = {}
            for (src, dst), support in supports.items():
                src_i = int(src)
                dst_i = int(dst)
                if src_i in step1_ambiguous_src_nodes:
                    continue
                preferred_dst = preferred_dst_by_src.get(src_i)
                if preferred_dst is not None and int(dst_i) != int(preferred_dst) and int(
                    len(dict(supports_result.node_dst_votes.get(src_i, {})))
                ) > 1:
                    continue
                filtered_supports[(int(src_i), int(dst_i))] = support
            supports = filtered_supports

    step1_unique_pair_count = int(len(supports))

    if bool(int(params.get("DEBUG_DUMP", 0))):
        debug_json_payloads["debug/step1_next_crossing_candidates.geojson"] = {
            "type": "FeatureCollection",
            "features": list(step1_next_crossing_candidate_features),
        }
        debug_json_payloads["debug/step1_node_dst_votes.json"] = {
            "threshold": float(node_vote_min_ratio),
            "strict_unique_required": bool(strict_unique_required),
            "nodes": dict(step1_node_dst_votes_debug),
        }
        if step1_ambiguous_src_nodes:
            amb_features: list[dict[str, Any]] = []
            for feat in step1_next_crossing_candidate_features:
                if not isinstance(feat, dict):
                    continue
                props = feat.get("properties")
                if not isinstance(props, dict):
                    continue
                src_nodeid = props.get("src_nodeid")
                try:
                    src_i = int(src_nodeid)
                except Exception:
                    continue
                if src_i not in step1_ambiguous_src_nodes:
                    continue
                props_out = dict(props)
                vote_node = dict(step1_node_dst_votes_debug.get(str(int(src_i))) or {})
                decision_val = str(vote_node.get("decision") or HARD_MULTI_NEIGHBOR_FOR_NODE)
                if decision_val == "multi_chain":
                    decision_val = _HARD_MULTI_CHAIN_SAME_DST
                elif decision_val == "multi_dst":
                    decision_val = HARD_MULTI_NEIGHBOR_FOR_NODE
                props_out["decision"] = decision_val
                props_out["hint"] = step1_ambiguous_nodes_hint.get(src_i)
                amb_features.append(
                    {
                        "type": "Feature",
                        "geometry": feat.get("geometry"),
                        "properties": props_out,
                    }
                )
            debug_json_payloads["debug/step1_node_ambiguous_examples.geojson"] = {
                "type": "FeatureCollection",
                "features": amb_features,
            }

    pair_cluster_enable = bool(int(params.get("STEP1_PAIR_CLUSTER_ENABLE", 0)))
    disable_pair_cluster = (not pair_cluster_enable) or (
        bool(int(params.get("STEP1_DISABLE_PAIR_CLUSTER_WHEN_GATE", 1)))
        and bool(xsec_cross_stats.get("xsec_gate_enabled", False))
    )
    pair_cluster_norm_stats = _normalize_support_clusters_for_xsec_gate(
        supports=supports,
        enabled=disable_pair_cluster,
        keep_pairs=set(step1_same_dst_multi_chain_pairs.keys()),
    )
    if not supports:
        has_multi_neighbor_hard = any(
            str(bp.get("reason")) in {HARD_MULTI_NEIGHBOR_FOR_NODE, _HARD_MULTI_CHAIN_SAME_DST}
            for bp in hard_breakpoints
        )
        if not has_multi_neighbor_hard:
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
        _flush_pair_stage_debug()
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
                "step1_ambiguous_crossing_count": int(step1_ambiguous_crossing_count),
                "step1_ambiguous_node_count": int(step1_ambiguous_node_count),
                "step1_unique_pair_count": int(step1_unique_pair_count),
                "step1_same_pair_multichain_pair_count": int(len(step1_same_dst_multi_chain_pairs)),
                "topology_fallback_support_count": int(topology_fallback_support_count),
                "step1_vote_main_ratio_p50": (
                    float(np.percentile(np.asarray(step1_vote_main_ratio_vals, dtype=np.float64), 50.0))
                    if step1_vote_main_ratio_vals
                    else None
                ),
                "step1_vote_main_ratio_p90": (
                    float(np.percentile(np.asarray(step1_vote_main_ratio_vals, dtype=np.float64), 90.0))
                    if step1_vote_main_ratio_vals
                    else None
                ),
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
            debug_json_payloads=debug_json_payloads,
        )

    pointcloud_enabled = bool(int(params.get("POINTCLOUD_ENABLE", 0)))
    if progress is not None:
        progress.mark("surface_points_start", pointcloud_enabled=bool(pointcloud_enabled))
    points_xyz, non_ground_xy, pointcloud_stats = _load_surface_points(
        patch_inputs,
        supports,
        params,
        use_pointcloud=pointcloud_enabled,
        with_non_ground=True,
    )
    stage_timer.add("t_sample_drivezone_surface", float(pointcloud_stats.get("drivezone_surface_timing_ms", 0.0)))
    stage_timer.add("t_load_pointcloud", float(pointcloud_stats.get("pointcloud_timing_ms", 0.0)))
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
        "step1_corridor_zone": _mk_debug_layer(),
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
        "xsec_cross_selected": _mk_debug_layer(seed=list(xsec_cross_selected_debug_items)),
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
        pair_stage = _ensure_pair_stage_entry(int(src), int(dst))
        pair_stage["support_found"] = True
        if not pair_stage.get("support_mode"):
            pair_stage["support_mode"] = (
                "topology_road_prior_fallback"
                if "topology_road_prior_fallback" in {str(v) for v in list(support.hints)}
                else "traj_support"
            )
        pair_stage["support_event_count"] = int(support.support_event_count)
        pair_stage["support_traj_count"] = int(len(support.support_traj_ids))
        src_type = node_type_map.get(src, "unknown")
        dst_type = node_type_map.get(dst, "unknown")
        if _is_shared_intersection_internal_pair(
            src=int(src),
            dst=int(dst),
            src_type=str(src_type),
            dst_type=str(dst_type),
            group_by_nodeid=shared_xsec_group_by_nodeid,
        ):
            continue
        src_xsec = xsec_map.get(src)
        dst_xsec = xsec_map.get(dst)
        src_xsec_gate = xsec_cross_lookup_map.get(src)
        dst_xsec_gate = xsec_cross_lookup_map.get(dst)
        src_gate_meta = xsec_gate_meta_lookup_map.get(int(src), {})
        dst_gate_meta = xsec_gate_meta_lookup_map.get(int(dst), {})

        if src_xsec is None or dst_xsec is None or src_xsec_gate is None or dst_xsec_gate is None:
            pair_stage["selected_or_rejected_stage"] = "xsec_missing"
            road = _make_base_road_record(
                src=src,
                dst=dst,
                support=support,
                src_type=src_type,
                dst_type=dst_type,
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

        if debug_enabled:
            for ls in _iter_line_parts(xsec_gate_all_lookup_map.get(int(src))):
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
            for ls in _iter_line_parts(xsec_gate_all_lookup_map.get(int(dst))):
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
            road_prior_shape_ref_metric=road_prior_pair_shape_ref_map.get((int(src), int(dst))),
        )
        pair_stage["step1_corridor_status"] = "hard_reject" if step1_corridor.get("hard_reason") else "ok"
        pair_stage["step1_corridor_reason"] = step1_corridor.get("hard_reason")
        pair_stage["step1_corridor_hint"] = step1_corridor.get("hard_hint")
        pair_stage["selected_or_rejected_stage"] = (
            "step1_corridor_ready" if not step1_corridor.get("hard_reason") else "step1_corridor_rejected"
        )
        if debug_enabled:
            _append_step1_corridor_debug_layers(
                debug_layers=debug_layers,
                road_id=f"{src}_{dst}",
                src=int(src),
                dst=int(dst),
                support=support,
                step1_corridor=step1_corridor,
                params=params,
            )
        same_pair_multi_chain_info = step1_same_dst_multi_chain_pairs.get((int(src), int(dst)))
        same_pair_variants: list[dict[str, Any]] = []
        if same_pair_multi_chain_info is not None:
            same_pair_variants = _build_same_pair_multichain_variants(
                pair=(int(src), int(dst)),
                support=support,
                src_type=str(src_type),
                dst_type=str(dst_type),
                src_xsec=src_xsec_gate.geometry_metric,
                dst_xsec=dst_xsec_gate.geometry_metric,
                drivezone_zone_metric=patch_inputs.drivezone_zone_metric,
                gore_zone_metric=gore_zone_metric,
                params=params,
                anchor_decisions=step1_topology_anchor_decisions,
                edge_geometry_by_id=road_prior_edge_geometry_map,
            )
        if step1_corridor.get("hard_reason") and not same_pair_variants:
            pair_stage["selected_or_rejected_stage"] = "step1_corridor_rejected"
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
            road["step1_corridor_zone_area_m2"] = step1_corridor.get("corridor_zone_area_m2")
            road["step1_corridor_zone_source_count"] = step1_corridor.get("corridor_zone_source_count")
            road["step1_corridor_zone_half_width_m"] = step1_corridor.get("corridor_zone_half_width_m")
            road["step1_corridor_shape_ref_inside_ratio"] = step1_corridor.get("corridor_shape_ref_inside_ratio")
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
        candidate_roads: list[dict[str, Any]] = []
        if same_pair_variants:
            for variant in same_pair_variants:
                branch_support = variant.get("support")
                branch_corridor = variant.get("step1_corridor")
                if not isinstance(branch_support, PairSupport) or not isinstance(branch_corridor, dict):
                    continue
                cluster_id = int(variant.get("cluster_id", 0))
                branch_id = str(variant.get("branch_id") or f"{src}_{dst}__b{int(cluster_id)}")
                if debug_enabled:
                    _append_step1_corridor_debug_layers(
                        debug_layers=debug_layers,
                        road_id=f"{src}_{dst}__b{int(cluster_id)}",
                        src=int(src),
                        dst=int(dst),
                        support=branch_support,
                        step1_corridor=branch_corridor,
                        params=params,
                        branch_id=branch_id,
                    )
                if branch_corridor.get("hard_reason"):
                    continue
                with stage_timer.scope("t_build_surfaces_total"):
                    surface_hint = _build_traj_surface_hint_for_cluster(
                        support=branch_support,
                        cluster_id=int(cluster_id),
                        src_xsec=src_xsec_gate.geometry_metric,
                        dst_xsec=dst_xsec_gate.geometry_metric,
                        lane_boundaries_metric=patch_inputs.lane_boundaries_metric,
                        patch_inputs=patch_inputs,
                        gore_zone_metric=gore_zone_metric,
                        params=params,
                        traj_points_cache=traj_points_cache,
                        traj_xy_index=traj_xy_index,
                        traj_meta_index=traj_meta_index,
                    )
                stage_timer.add("t_build_traj_surface_compute", float(surface_hint.get("timing_ms", 0.0)))
                key_k = f"{src}_{dst}_k{int(cluster_id)}"
                surface_timing_per_k[key_k] = float(surface_hint.get("timing_ms", 0.0))
                if bool(surface_hint.get("cache_hit", False)):
                    surface_cache_hit_count += 1
                else:
                    surface_cache_miss_count += 1
                road_k = _evaluate_candidate_road(
                    src=src,
                    dst=dst,
                    src_type=src_type,
                    dst_type=dst_type,
                    support=branch_support,
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
                    shape_ref_hint_metric=branch_corridor.get("shape_ref_line"),
                    segment_corridor_metric=branch_corridor.get("corridor_zone_metric"),
                    road_prior_shape_ref_metric=variant.get("road_prior_shape_ref_metric"),
                    step1_used_road_prior=bool(branch_corridor.get("road_prior_shape_ref_used", False)),
                    step1_road_prior_mode=branch_corridor.get("road_prior_shape_ref_mode"),
                    same_pair_multichain=True,
                    candidate_branch_id=branch_id,
                    support_mode=str(variant.get("support_mode") or "traj_support"),
                    src_xsec=src_xsec_gate.geometry_metric,
                    dst_xsec=dst_xsec_gate.geometry_metric,
                )
                _apply_xsec_gate_meta_to_road(road=road_k, src_meta=src_gate_meta, dst_meta=dst_gate_meta)
                road_k["step1_strategy"] = branch_corridor.get("strategy")
                road_k["step1_reason"] = branch_corridor.get("hard_reason")
                road_k["step1_corridor_count"] = branch_corridor.get("corridor_count")
                road_k["step1_main_corridor_ratio"] = branch_corridor.get("main_corridor_ratio")
                road_k["gore_fallback_used_src"] = bool(branch_corridor.get("gore_fallback_used_src", False))
                road_k["gore_fallback_used_dst"] = bool(branch_corridor.get("gore_fallback_used_dst", False))
                road_k["traj_drop_count_by_drivezone"] = int(branch_corridor.get("traj_drop_count_by_drivezone", 0))
                road_k["drivezone_fallback_used"] = bool(branch_corridor.get("drivezone_fallback_used", False))
                road_k["step1_corridor_zone_area_m2"] = branch_corridor.get("corridor_zone_area_m2")
                road_k["step1_corridor_zone_source_count"] = branch_corridor.get("corridor_zone_source_count")
                road_k["step1_corridor_zone_half_width_m"] = branch_corridor.get("corridor_zone_half_width_m")
                road_k["step1_corridor_shape_ref_inside_ratio"] = branch_corridor.get("corridor_shape_ref_inside_ratio")
                road_k["step1_same_pair_multichain"] = True
                road_k["step1_same_pair_multichain_count"] = int(same_pair_multi_chain_info.get("chain_count", 0))
                road_k["same_pair_multi_road_branch_id"] = branch_id
                road_k["same_pair_multi_road_branch_rank"] = int(variant.get("branch_rank", cluster_id + 1))
                road_k["same_pair_multi_road_signature"] = list(variant.get("signature") or [])
                road_k["same_pair_multi_road_src_station_m"] = variant.get("src_station_m")
                road_k["same_pair_multi_road_dst_station_m"] = variant.get("dst_station_m")
                road_k["same_pair_multi_road_support_mode"] = str(variant.get("support_mode") or "traj_support")
                road_k["same_pair_multi_road_fallback_reason"] = variant.get("support_fallback_reason")
                road_k["same_pair_multi_road_support_traj_count"] = int(
                    variant.get("support_traj_count", len(branch_support.support_traj_ids))
                )
                stage_timer.add("t_build_lane_graph", float(road_k.get("_timing_lb_graph_ms", 0.0)))
                sp_ms = float(road_k.get("_timing_shortest_path_ms", 0.0))
                shortest_timing_per_k[key_k] = sp_ms
                stage_timer.add("t_shortest_path_total", sp_ms)
                stage_timer.add("t_centerline_offset", float(road_k.get("_timing_centerline_ms", 0.0)))
                stage_timer.add("t_gate_in_ratio", float(road_k.get("_timing_gate_ms", 0.0)))
                candidate_roads.append(road_k)
        else:
            topology_fallback_mode = bool(
                int(support.support_event_count) <= 0
                and bool(step1_corridor.get("road_prior_shape_ref_used", False))
                and str(step1_corridor.get("road_prior_shape_ref_mode") or "").strip().lower() == "step1_no_traj"
                and _is_valid_linestring(road_prior_pair_shape_ref_map.get((int(src), int(dst))))
            )
            if topology_fallback_mode:
                key_k = f"{src}_{dst}_k0"
                surface_timing_per_k[key_k] = 0.0
                road_k = _evaluate_candidate_road(
                    src=src,
                    dst=dst,
                    src_type=src_type,
                    dst_type=dst_type,
                    support=support,
                    parent_support=support,
                    cluster_id=0,
                    neighbor_search_pass=int(neighbor_search_pass),
                    src_out_degree=out_degree.get(src, 0),
                    dst_in_degree=in_degree.get(dst, 0),
                    lane_boundaries_metric=patch_inputs.lane_boundaries_metric,
                    surface_points_xyz=points_xyz,
                    non_ground_xy=non_ground_xy,
                    patch_inputs=patch_inputs,
                    gore_zone_metric=gore_zone_metric,
                    params=params,
                    traj_surface_hint={
                        "traj_surface_enforced": False,
                        "surface_metric": None,
                        "timing_ms": 0.0,
                        "slice_valid_ratio": 0.0,
                        "covered_length_ratio": 0.0,
                        "covered_station_length_m": 0.0,
                        "unique_traj_count": 0,
                        "reason": "topology_road_prior_fallback",
                    },
                    shape_ref_hint_metric=step1_corridor.get("shape_ref_line"),
                    segment_corridor_metric=step1_corridor.get("corridor_zone_metric"),
                    road_prior_shape_ref_metric=road_prior_pair_shape_ref_map.get((int(src), int(dst))),
                    step1_used_road_prior=bool(step1_corridor.get("road_prior_shape_ref_used", False)),
                    step1_road_prior_mode=step1_corridor.get("road_prior_shape_ref_mode"),
                    same_pair_multichain=False,
                    candidate_branch_id=None,
                    support_mode="topology_road_prior_fallback",
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
                road_k["step1_corridor_zone_area_m2"] = step1_corridor.get("corridor_zone_area_m2")
                road_k["step1_corridor_zone_source_count"] = step1_corridor.get("corridor_zone_source_count")
                road_k["step1_corridor_zone_half_width_m"] = step1_corridor.get("corridor_zone_half_width_m")
                road_k["step1_corridor_shape_ref_inside_ratio"] = step1_corridor.get("corridor_shape_ref_inside_ratio")
                road_k["pair_support_mode"] = "topology_road_prior_fallback"
                stage_timer.add("t_build_lane_graph", float(road_k.get("_timing_lb_graph_ms", 0.0)))
                sp_ms = float(road_k.get("_timing_shortest_path_ms", 0.0))
                shortest_timing_per_k[key_k] = sp_ms
                stage_timer.add("t_shortest_path_total", sp_ms)
                stage_timer.add("t_centerline_offset", float(road_k.get("_timing_centerline_ms", 0.0)))
                stage_timer.add("t_gate_in_ratio", float(road_k.get("_timing_gate_ms", 0.0)))
                candidate_roads.append(road_k)
            cluster_ids = _select_cluster_candidates(support, max_clusters=3)
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
                        traj_xy_index=traj_xy_index,
                        traj_meta_index=traj_meta_index,
                    )
                stage_timer.add("t_build_traj_surface_compute", float(surface_hint.get("timing_ms", 0.0)))
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
                    segment_corridor_metric=step1_corridor.get("corridor_zone_metric"),
                    road_prior_shape_ref_metric=road_prior_pair_shape_ref_map.get((int(src), int(dst))),
                    step1_used_road_prior=bool(step1_corridor.get("road_prior_shape_ref_used", False)),
                    step1_road_prior_mode=step1_corridor.get("road_prior_shape_ref_mode"),
                    same_pair_multichain=False,
                    candidate_branch_id=None,
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
                road_k["step1_corridor_zone_area_m2"] = step1_corridor.get("corridor_zone_area_m2")
                road_k["step1_corridor_zone_source_count"] = step1_corridor.get("corridor_zone_source_count")
                road_k["step1_corridor_zone_half_width_m"] = step1_corridor.get("corridor_zone_half_width_m")
                road_k["step1_corridor_shape_ref_inside_ratio"] = step1_corridor.get("corridor_shape_ref_inside_ratio")
                key_k = f"{src}_{dst}_k{int(cluster_id)}"
                stage_timer.add("t_build_lane_graph", float(road_k.get("_timing_lb_graph_ms", 0.0)))
                sp_ms = float(road_k.get("_timing_shortest_path_ms", 0.0))
                shortest_timing_per_k[key_k] = sp_ms
                stage_timer.add("t_shortest_path_total", sp_ms)
                stage_timer.add("t_centerline_offset", float(road_k.get("_timing_centerline_ms", 0.0)))
                stage_timer.add("t_gate_in_ratio", float(road_k.get("_timing_gate_ms", 0.0)))
                candidate_roads.append(road_k)

        if not candidate_roads:
            pair_stage["candidate_count"] = 0
            pair_stage["viable_candidate_count"] = 0
            pair_stage["no_geometry_candidate"] = True
            pair_stage["selected_or_rejected_stage"] = "candidate_empty"
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
            road["step1_corridor_zone_area_m2"] = step1_corridor.get("corridor_zone_area_m2")
            road["step1_corridor_zone_source_count"] = step1_corridor.get("corridor_zone_source_count")
            road["step1_corridor_zone_half_width_m"] = step1_corridor.get("corridor_zone_half_width_m")
            road["step1_corridor_shape_ref_inside_ratio"] = step1_corridor.get("corridor_shape_ref_inside_ratio")
            road["hard_anomaly"] = True
            road["hard_reasons"] = [HARD_CENTER_EMPTY]
            road["soft_issue_flags"] = [SOFT_TRAJ_SURFACE_INSUFFICIENT]
            road["no_geometry_candidate"] = True
            if same_pair_multi_chain_info is not None:
                road["step1_same_pair_multichain"] = True
                road["step1_same_pair_multichain_count"] = int(same_pair_multi_chain_info.get("chain_count", 0))
            road["_geometry_metric"] = None
            road_records.append(road)
            hard_breakpoints.append(
                build_breakpoint(
                    road=road,
                    reason=HARD_CENTER_EMPTY,
                    severity="hard",
                    hint=(
                        f"branch_candidate_count={int(len(same_pair_variants))};viable_candidate_count=0"
                        if same_pair_multi_chain_info is not None
                        else "cluster_candidate_empty"
                    ),
                )
            )
            continue

        ranked_candidates = sorted(candidate_roads, key=_candidate_sort_key, reverse=True)
        viable_candidates = [
            c
            for c in ranked_candidates
            if bool(c.get("_candidate_feasible", False))
            and bool(c.get("_candidate_has_geometry", False))
            and isinstance(c.get("_geometry_metric"), LineString)
            and (not c.get("_geometry_metric").is_empty)
        ]
        pair_stage["candidate_count"] = int(len(candidate_roads))
        pair_stage["viable_candidate_count"] = int(len(viable_candidates))
        pair_stage["selected_or_rejected_stage"] = "candidate_ready"
        same_pair_multi_chain_info = step1_same_dst_multi_chain_pairs.get((int(src), int(dst)))
        ranked_cluster_summary = [
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
            for c in ranked_candidates[:3]
        ]
        if same_pair_multi_chain_info is not None:
            branch_total = int(max(1, len(same_pair_variants)))
            min_sep_base = _to_finite_float(
                support.cluster_sep_m_est,
                float(params["MULTI_ROAD_SEP_M"]),
            )
            min_sep_m = max(1.0, min(4.0, float(min_sep_base) * 0.25))
            same_pair_station_gap_min_m = float(max(0.1, float(params.get("SAME_PAIR_MULTI_STATION_GAP_MIN_M", 0.5))))
            selected_multi_pick = _select_same_pair_multichain_candidates(
                sorted(ranked_candidates, key=_candidate_sort_key, reverse=True),
                min_sep_m=float(min_sep_m),
                same_pair_station_gap_min_m=float(same_pair_station_gap_min_m),
            )
            selected_ids = {id(c) for c in selected_multi_pick}
            ordered_candidates = sorted(
                ranked_candidates,
                key=lambda c: (
                    int(c.get("same_pair_multi_road_branch_rank", c.get("candidate_cluster_id", 0) + 1) or 0),
                    int(c.get("candidate_cluster_id", 0)),
                ),
            )
            for cand in ordered_candidates:
                cand["chosen_cluster_id"] = int(cand.get("candidate_cluster_id", 0))
                cand["cluster_score_top2"] = list(ranked_cluster_summary)
                cand["step1_same_pair_multichain"] = True
                cand["step1_same_pair_multichain_count"] = int(same_pair_multi_chain_info.get("chain_count", 0))
                channel_rank = int(
                    cand.get("same_pair_multi_road_branch_rank", cand.get("candidate_cluster_id", 0) + 1) or 0
                )
                _assign_multi_road_channel_identity(
                    cand,
                    channel_rank=channel_rank,
                    channel_count=branch_total,
                    same_pair=True,
                )
                if id(cand) in selected_ids:
                    pair_stage["selected_output_count"] = int(pair_stage.get("selected_output_count", 0)) + 1
                    pair_stage["selected_or_rejected_stage"] = "selected"
                    cand["no_geometry_candidate"] = False
                    _append_selected_candidate_road(
                        selected=cand,
                        road_records=road_records,
                        road_lines_metric=road_lines_metric,
                        road_feature_props=road_feature_props,
                        hard_breakpoints=hard_breakpoints,
                        soft_breakpoints=soft_breakpoints,
                        debug_layers=debug_layers,
                        debug_enabled=debug_enabled,
                        stage_timer=stage_timer,
                        src_xsec=src_xsec.geometry_metric,
                        dst_xsec=dst_xsec.geometry_metric,
                        gore_zone_metric=gore_zone_metric,
                        params=params,
                    )
                    continue
                cand["_geometry_metric"] = None
                cand["no_geometry_candidate"] = True
                if bool(cand.get("_candidate_has_geometry", False)) and bool(cand.get("_candidate_feasible", False)):
                    cand["hard_reasons"] = [HARD_MULTI_ROAD]
                    cand["soft_issue_flags"] = []
                    cand["hard_anomaly"] = True
                _append_selected_candidate_road(
                    selected=cand,
                    road_records=road_records,
                    road_lines_metric=road_lines_metric,
                    road_feature_props=road_feature_props,
                    hard_breakpoints=hard_breakpoints,
                    soft_breakpoints=soft_breakpoints,
                    debug_layers=debug_layers,
                    debug_enabled=debug_enabled,
                    stage_timer=stage_timer,
                    src_xsec=src_xsec.geometry_metric,
                    dst_xsec=dst_xsec.geometry_metric,
                    gore_zone_metric=gore_zone_metric,
                    params=params,
                )
            continue
        if len(viable_candidates) > 1:
            min_sep_base = _to_finite_float(
                support.cluster_sep_m_est,
                float(params["MULTI_ROAD_SEP_M"]),
            )
            min_sep_m = max(1.0, min(4.0, float(min_sep_base) * 0.25))
            selected_multi = _select_non_conflicting_multi_road_candidates(
                viable_candidates,
                min_sep_m=float(min_sep_m),
                same_pair_station_gap_min_m=float(max(0.1, float(params.get("SAME_PAIR_MULTI_STATION_GAP_MIN_M", 0.5)))),
            )
            if len(selected_multi) >= 2:
                multi_count = int(len(selected_multi))
                for idx, cand in enumerate(selected_multi, start=1):
                    cand["chosen_cluster_id"] = int(cand.get("candidate_cluster_id", 0))
                    cand["no_geometry_candidate"] = False
                    cand["cluster_score_top2"] = list(ranked_cluster_summary)
                    _assign_multi_road_channel_identity(
                        cand,
                        channel_rank=int(idx),
                        channel_count=multi_count,
                        same_pair=False,
                    )
                    _append_selected_candidate_road(
                        selected=cand,
                        road_records=road_records,
                        road_lines_metric=road_lines_metric,
                        road_feature_props=road_feature_props,
                        hard_breakpoints=hard_breakpoints,
                        soft_breakpoints=soft_breakpoints,
                        debug_layers=debug_layers,
                        debug_enabled=debug_enabled,
                        stage_timer=stage_timer,
                        src_xsec=src_xsec.geometry_metric,
                        dst_xsec=dst_xsec.geometry_metric,
                        gore_zone_metric=gore_zone_metric,
                        params=params,
                    )
                continue
        selected = ranked_candidates[0]
        pair_stage["selected_output_count"] = int(pair_stage.get("selected_output_count", 0)) + 1
        pair_stage["selected_or_rejected_stage"] = "selected"
        selected["chosen_cluster_id"] = int(selected.get("candidate_cluster_id", 0))
        selected["no_geometry_candidate"] = False
        selected["cluster_score_top2"] = list(ranked_cluster_summary)
        if same_pair_multi_chain_info is not None:
            selected["step1_same_pair_multichain"] = True
            selected["step1_same_pair_multichain_count"] = int(same_pair_multi_chain_info.get("chain_count", 0))
        _append_selected_candidate_road(
            selected=selected,
            road_records=road_records,
            road_lines_metric=road_lines_metric,
            road_feature_props=road_feature_props,
            hard_breakpoints=hard_breakpoints,
            soft_breakpoints=soft_breakpoints,
            debug_layers=debug_layers,
            debug_enabled=debug_enabled,
            stage_timer=stage_timer,
            src_xsec=src_xsec.geometry_metric,
            dst_xsec=dst_xsec.geometry_metric,
            gore_zone_metric=gore_zone_metric,
            params=params,
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
            hard_reasons = [str(v) for v in list(road.get("hard_reasons") or [])]
            if HARD_ENDPOINT not in hard_reasons:
                hard_reasons.append(HARD_ENDPOINT)
            road["hard_reasons"] = hard_reasons
            road["hard_anomaly"] = True
            if not any(
                str(bp.get("road_id")) == str(road.get("road_id")) and str(bp.get("reason")) == HARD_ENDPOINT
                for bp in hard_breakpoints
            ):
                bp = build_breakpoint(
                    road=road,
                    reason=HARD_ENDPOINT,
                    severity="hard",
                    hint=(
                        "anchor_distance_guard;"
                        f"src_dist={float(d0):.3f};"
                        f"dst_dist={float(d1):.3f};"
                        f"limit={float(endpoint_anchor_max_dist):.3f}"
                    ),
                )
                bp["endpoint_anchor_dist_src_m"] = float(d0)
                bp["endpoint_anchor_dist_dst_m"] = float(d1)
                hard_breakpoints.append(bp)
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
    step1_vote_main_ratio_arr = (
        np.asarray(step1_vote_main_ratio_vals, dtype=np.float64)
        if step1_vote_main_ratio_vals
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
    _flush_pair_stage_debug()
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
            "step1_ambiguous_crossing_count": int(step1_ambiguous_crossing_count),
            "step1_ambiguous_node_count": int(step1_ambiguous_node_count),
            "step1_unique_pair_count": int(step1_unique_pair_count),
            "step1_same_pair_multichain_pair_count": int(len(step1_same_dst_multi_chain_pairs)),
            "topology_fallback_support_count": int(topology_fallback_support_count),
            "step1_vote_main_ratio_p50": (
                float(np.percentile(step1_vote_main_ratio_arr, 50.0)) if step1_vote_main_ratio_arr.size > 0 else None
            ),
            "step1_vote_main_ratio_p90": (
                float(np.percentile(step1_vote_main_ratio_arr, 90.0)) if step1_vote_main_ratio_arr.size > 0 else None
            ),
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
        debug_json_payloads=debug_json_payloads,
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
        "pointcloud_timing_ms": 0.0,
        "drivezone_surface_point_count": 0,
        "drivezone_surface_timing_ms": 0.0,
        "drivezone_surface_cache_hit": False,
        "drivezone_surface_cache_key": None,
    }

    bbox = _support_union_bbox(patch_inputs, supports, margin_m=float(params["XSEC_ACROSS_HALF_WINDOW_M"]) + 5.0)
    if bbox is None:
        if with_non_ground:
            return np.empty((0, 3), dtype=np.float64), np.empty((0, 2), dtype=np.float64), stats
        return np.empty((0, 3), dtype=np.float64), stats
    cache_enabled = bool(int(params.get("CACHE_ENABLED", 1)))
    drive_xyz = np.empty((0, 3), dtype=np.float64)
    drive_cache_path: Path | None = None
    drive_cache_key: str | None = None
    drive_t0 = perf_counter()
    drive_hash = _geometry_hash(patch_inputs.drivezone_zone_metric)
    if cache_enabled and drive_hash is not None:
        cache_key_payload = {
            "v": 1,
            "patch_id": str(patch_inputs.patch_id),
            "drivezone_hash": str(drive_hash),
            "bbox": [round(float(v), 3) for v in bbox],
            "step_m": round(float(params.get("DRIVEZONE_SAMPLE_STEP_M", 2.0)), 3),
            "max_points": 900_000,
        }
        drive_cache_key = _stable_json_digest(cache_key_payload)
        drive_cache_path = patch_inputs.patch_dir / ".t05_cache" / "drivezone_surface" / f"surface_{drive_cache_key}.npz"
        stats["drivezone_surface_cache_key"] = drive_cache_key
        if drive_cache_path.is_file():
            try:
                with np.load(drive_cache_path, allow_pickle=False) as zf:
                    drive_xyz = np.asarray(zf["xyz"], dtype=np.float64)
                stats["drivezone_surface_cache_hit"] = True
            except Exception:
                drive_xyz = np.empty((0, 3), dtype=np.float64)
    if drive_xyz.shape[0] == 0:
        drive_xyz = _sample_drivezone_surface_points(
            drivezone_metric=patch_inputs.drivezone_zone_metric,
            bbox_metric=bbox,
            step_m=float(params.get("DRIVEZONE_SAMPLE_STEP_M", 2.0)),
            max_points=900_000,
        )
        if cache_enabled and drive_cache_path is not None:
            try:
                drive_cache_path.parent.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(drive_cache_path, xyz=np.asarray(drive_xyz, dtype=np.float64))
            except Exception:
                pass
    stats["drivezone_surface_timing_ms"] = float((perf_counter() - drive_t0) * 1000.0)
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
    pointcloud_t0 = perf_counter()

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
                stats["pointcloud_timing_ms"] = float((perf_counter() - pointcloud_t0) * 1000.0)
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
        stats["pointcloud_timing_ms"] = float((perf_counter() - pointcloud_t0) * 1000.0)
        if with_non_ground:
            base_xyz = drive_xyz if drive_xyz.shape[0] > 0 else xyz
            return base_xyz, ng_xy, stats
        base_xyz = drive_xyz if drive_xyz.shape[0] > 0 else xyz
        return base_xyz, stats
    except InputDataError:
        stats["pointcloud_timing_ms"] = float((perf_counter() - pointcloud_t0) * 1000.0)
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


def _apply_step1_xsec_metrics(
    *,
    items: Sequence[dict[str, Any]],
    src_xsec: LineString,
    dst_xsec: LineString,
    reach_xsec_m: float,
) -> None:
    for it in items:
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
        it["reaches_other_end"] = bool(
            np.isfinite(d_src) and np.isfinite(d_dst) and d_src <= reach_xsec_m and d_dst <= reach_xsec_m
        )


def _build_step1_pair_endpoint_xsec(
    *,
    xsec_seed: LineString,
    endpoint_tag: str,
    node_type: str,
    shape_ref_line: LineString,
    support: PairSupport,
    drivezone_zone_metric: BaseGeometry | None,
    gore_zone_metric: BaseGeometry | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    return build_pair_endpoint_xsec(
        xsec_seed=xsec_seed,
        shape_ref_line=shape_ref_line,
        traj_segments=support.traj_segments,
        drivezone_zone_metric=drivezone_zone_metric,
        gore_zone_metric=gore_zone_metric,
        ref_half_len_m=float(params.get("XSEC_REF_HALF_LEN_M", 80.0)),
        sample_step_m=float(params.get("XSEC_ROAD_SAMPLE_STEP_M", 1.0)),
        nonpass_k=int(params.get("XSEC_ROAD_NONPASS_K", 6)),
        evidence_radius_m=float(params.get("XSEC_ROAD_EVIDENCE_RADIUS_M", 1.0)),
        min_ground_pts=int(params.get("XSEC_ROAD_MIN_GROUND_PTS", 1)),
        min_traj_pts=int(params.get("XSEC_ROAD_MIN_TRAJ_PTS", 1)),
        core_band_m=float(params.get("XSEC_CORE_BAND_M", 20.0)),
        shift_step_m=float(params.get("XSEC_SHIFT_STEP_M", 5.0)),
        fallback_short_half_len_m=float(params.get("XSEC_FALLBACK_SHORT_HALF_LEN_M", 15.0)),
        barrier_min_ng_count=int(params.get("XSEC_BARRIER_MIN_NG_COUNT", 2)),
        barrier_min_len_m=float(params.get("XSEC_BARRIER_MIN_LEN_M", 4.0)),
        barrier_along_len_m=float(params.get("XSEC_BARRIER_ALONG_LEN_M", 60.0)),
        barrier_along_width_m=float(params.get("XSEC_BARRIER_ALONG_WIDTH_M", 2.5)),
        barrier_bin_step_m=float(params.get("XSEC_BARRIER_BIN_STEP_M", 2.0)),
        barrier_occ_ratio_min=float(params.get("XSEC_BARRIER_OCC_RATIO_MIN", 0.65)),
        endcap_window_m=float(params.get("XSEC_ENDCAP_WINDOW_M", 60.0)),
        caseb_pre_m=float(params.get("XSEC_CASEB_PRE_M", 3.0)),
        endpoint_tag=endpoint_tag,
        node_type=node_type,
        ground_xy=np.empty((0, 2), dtype=np.float64),
        non_ground_xy=np.empty((0, 2), dtype=np.float64),
    )


def _resolve_step1_pair_cross_xsec(
    *,
    xsec_seed: LineString,
    pair_xsec_meta: dict[str, Any] | None,
) -> LineString:
    if isinstance(pair_xsec_meta, dict):
        cross_ref = pair_xsec_meta.get("xsec_cross_ref")
        if isinstance(cross_ref, LineString) and (not cross_ref.is_empty) and len(cross_ref.coords) >= 2:
            return cross_ref
    return xsec_seed


def _pick_step1_primary_item(items: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [it for it in items if isinstance(it, dict) and isinstance(it.get("seg"), LineString)]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    # 质量优先：双端可达 > 路面内比例 > 无约束冲突/无gore > 贴近端点 > 短seed距离 > 较长长度
    def _k(it: dict[str, Any]) -> tuple[float, float, float, float, float, float, float]:
        inside_ratio = _to_finite_float(it.get("inside_ratio"), 0.0)
        reaches = bool(it.get("reaches_other_end", False))
        violation = bool(it.get("constraint_violation", False))
        gore_any = bool(it.get("gore_any", False))
        d_src = _to_finite_float(it.get("dist_to_src_xsec_m"), 1e9)
        d_dst = _to_finite_float(it.get("dist_to_dst_xsec_m"), 1e9)
        d_seed = _to_finite_float(it.get("d_seed"), 1e9)
        seg_len = _to_finite_float(it.get("length_m"), 0.0)
        return (
            0.0 if reaches else 1.0,
            1.0 - inside_ratio,
            1.0 if violation else 0.0,
            1.0 if gore_any else 0.0,
            d_src + d_dst,
            d_seed,
            -seg_len,
        )

    ranked = sorted(valid, key=_k)
    return ranked[0]


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


def _build_buffered_corridor_zone(
    *,
    lines: Sequence[LineString],
    half_width_m: float,
    clip_zone: BaseGeometry | None = None,
) -> tuple[BaseGeometry | None, int, float | None]:
    zone_lines = [
        line
        for line in lines
        if isinstance(line, LineString) and (not line.is_empty) and float(line.length) > 1e-6
    ]
    if not zone_lines:
        return (None, 0, None)

    zone_parts: list[BaseGeometry] = []
    for line in zone_lines:
        try:
            zz = line.buffer(float(half_width_m), cap_style=2, join_style=2)
        except Exception:
            zz = line.buffer(float(half_width_m))
        if zz is None or zz.is_empty:
            continue
        zone_parts.append(zz)
    if not zone_parts:
        return (None, 0, None)

    try:
        corridor_zone = unary_union(zone_parts)
    except Exception:
        corridor_zone = zone_parts[0]
    if corridor_zone is not None and (not corridor_zone.is_empty) and clip_zone is not None and (not clip_zone.is_empty):
        try:
            clipped = corridor_zone.intersection(clip_zone)
            if clipped is not None and (not clipped.is_empty):
                corridor_zone = clipped
        except Exception:
            pass
    if corridor_zone is None or corridor_zone.is_empty:
        return (None, 0, None)
    try:
        area_m2 = float(corridor_zone.area)
    except Exception:
        area_m2 = None
    return (corridor_zone, int(len(zone_lines)), area_m2)


def _project_road_prior_geometry_to_metric_line(
    geom_raw: Any,
    *,
    to_metric: callable,
) -> LineString | None:
    try:
        geom = shape(geom_raw)
    except Exception:
        return None
    if geom is None or geom.is_empty:
        return None
    try:
        projected = to_metric(geom)
    except Exception:
        projected = geom
    if projected is None or projected.is_empty:
        return None

    parts = _iter_line_parts(projected)
    if not parts:
        return None
    if len(parts) == 1:
        line = parts[0]
    else:
        try:
            merged = linemerge(MultiLineString(parts))
        except Exception:
            try:
                merged = unary_union(parts)
            except Exception:
                merged = parts[0]
        merged_parts = _iter_line_parts(merged)
        if not merged_parts:
            return None
        line = max(merged_parts, key=lambda g: float(g.length))
    if line.is_empty or len(line.coords) < 2 or float(line.length) <= 1e-6:
        return None
    return line


def _reverse_line_if_needed(line: LineString) -> LineString:
    if not isinstance(line, LineString) or line.is_empty or len(line.coords) < 2:
        return line
    return LineString(list(line.coords)[::-1])


def _concat_line_sequence(lines: Sequence[LineString]) -> LineString | None:
    valid = [
        line
        for line in lines
        if isinstance(line, LineString) and (not line.is_empty) and len(line.coords) >= 2 and float(line.length) > 1e-6
    ]
    if not valid:
        return None
    coords: list[tuple[float, ...]] = [tuple(float(v) for v in valid[0].coords[0])]
    coords.extend(tuple(float(v) for v in xy) for xy in list(valid[0].coords)[1:])
    for line in valid[1:]:
        cand = line
        try:
            prev_end = Point(coords[-1])
            start_pt = Point(cand.coords[0])
            end_pt = Point(cand.coords[-1])
            d_start = float(prev_end.distance(start_pt))
            d_end = float(prev_end.distance(end_pt))
            if d_end + 1e-9 < d_start:
                cand = _reverse_line_if_needed(cand)
        except Exception:
            cand = line
        next_coords = [tuple(float(v) for v in xy) for xy in cand.coords]
        if not next_coords:
            continue
        try:
            prev_end = Point(coords[-1])
            next_start = Point(next_coords[0])
            same_start = float(prev_end.distance(next_start)) <= 1e-6
        except Exception:
            same_start = coords[-1] == next_coords[0]
        coords.extend(next_coords[1:] if same_start else next_coords)
    if len(coords) < 2:
        return None
    dedup: list[tuple[float, ...]] = [coords[0]]
    for xy in coords[1:]:
        try:
            keep = float(Point(dedup[-1]).distance(Point(xy))) > 1e-6
        except Exception:
            keep = xy != dedup[-1]
        if keep:
            dedup.append(xy)
    if len(dedup) < 2:
        return None
    try:
        out = LineString(dedup)
    except Exception:
        return None
    if out.is_empty or len(out.coords) < 2 or float(out.length) <= 1e-6:
        return None
    return out


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
    road_prior_shape_ref_metric: LineString | None = None,
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
        "corridor_zone_metric": None,
        "corridor_zone_area_m2": None,
        "corridor_zone_source_count": 0,
        "corridor_zone_half_width_m": float(max(1.0, params.get("CORRIDOR_HALF_WIDTH_M", 15.0))),
        "corridor_shape_ref_inside_ratio": None,
        "road_prior_shape_ref_used": False,
        "road_prior_shape_ref_mode": None,
    }

    if str(dst_type) == "diverge":
        strategy = "dst_diverge_reverse_trace"
        seed_xsec = dst_xsec
    elif str(src_type) == "diverge" and str(dst_type) == "merge":
        strategy = "diverge_to_merge_forward_trace"
        seed_xsec = src_xsec
    elif str(dst_type) == "merge" and str(src_type) == "merge":
        strategy = "merge_to_merge_forward_trace"
        seed_xsec = src_xsec
    else:
        strategy = "generic_forward_trace"
        seed_xsec = src_xsec

    out["strategy"] = str(strategy)
    seg_items = [
        (int(i), s)
        for i, s in enumerate(support.traj_segments)
        if isinstance(s, LineString) and (not s.is_empty) and s.length > 1.0
    ]
    prior_line = (
        _orient_axis_line(road_prior_shape_ref_metric, src_xsec=src_xsec, dst_xsec=dst_xsec)
        if isinstance(road_prior_shape_ref_metric, LineString)
        and (not road_prior_shape_ref_metric.is_empty)
        and float(road_prior_shape_ref_metric.length) > 1.0
        else None
    )
    if not seg_items:
        out["strategy"] = f"{strategy}|fallback_no_traj"
        if isinstance(prior_line, LineString) and not prior_line.is_empty:
            corridor_zone, zone_source_count, corridor_area = _build_buffered_corridor_zone(
                lines=[prior_line],
                half_width_m=float(out["corridor_zone_half_width_m"]),
                clip_zone=None,
            )
            out["shape_ref_line"] = prior_line
            out["corridor_zone_metric"] = corridor_zone
            out["corridor_zone_source_count"] = int(zone_source_count)
            out["corridor_zone_area_m2"] = corridor_area
            out["corridor_shape_ref_inside_ratio"] = _line_inside_ratio(prior_line, corridor_zone)
            out["cross_point_src"] = _line_xsec_contact_point(
                line=prior_line,
                xsec=src_xsec,
                fallback=out.get("cross_point_src"),
            )
            out["cross_point_dst"] = _line_xsec_contact_point(
                line=prior_line,
                xsec=dst_xsec,
                fallback=out.get("cross_point_dst"),
            )
            out["road_prior_shape_ref_used"] = True
            out["road_prior_shape_ref_mode"] = "step1_no_traj"
            out["hard_reason"] = None
            out["hard_hint"] = "step1_corridor_road_prior_fallback"
            return out
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
    _apply_step1_xsec_metrics(
        items=ranked_all,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        reach_xsec_m=reach_xsec_m,
    )
    ranked_reach = [it for it in ranked_used if bool(it.get("reaches_other_end", False))]
    ranked_main = ranked_reach if ranked_reach else ranked_used
    topk_pick = int(max(1, int(params.get("STEP1_PRIMARY_PICK_TOPK", 8))))
    ranked_main = sorted(
        ranked_main,
        key=lambda it: (
            0.0 if bool(it.get("reaches_other_end", False)) else 1.0,
            1.0 - _to_finite_float(it.get("inside_ratio"), 0.0),
            1.0 if bool(it.get("constraint_violation", False)) else 0.0,
            1.0 if bool(it.get("gore_any", False)) else 0.0,
            _to_finite_float(it.get("dist_to_src_xsec_m"), 1e9) + _to_finite_float(it.get("dist_to_dst_xsec_m"), 1e9),
            _to_finite_float(it.get("d_seed"), 1e9),
            -_to_finite_float(it.get("length_m"), 0.0),
            int(it.get("idx", -1)),
        ),
    )
    topk_debug = ranked_main[:topk_pick]
    if not topk_debug:
        if isinstance(prior_line, LineString) and not prior_line.is_empty:
            corridor_zone, zone_source_count, corridor_area = _build_buffered_corridor_zone(
                lines=[prior_line],
                half_width_m=float(out["corridor_zone_half_width_m"]),
                clip_zone=None,
            )
            out["strategy"] = f"{strategy}|road_prior_gap_fill"
            out["shape_ref_line"] = prior_line
            out["corridor_zone_metric"] = corridor_zone
            out["corridor_zone_source_count"] = int(zone_source_count)
            out["corridor_zone_area_m2"] = corridor_area
            out["corridor_shape_ref_inside_ratio"] = _line_inside_ratio(prior_line, corridor_zone)
            out["cross_point_src"] = _line_xsec_contact_point(
                line=prior_line,
                xsec=src_xsec,
                fallback=out.get("cross_point_src"),
            )
            out["cross_point_dst"] = _line_xsec_contact_point(
                line=prior_line,
                xsec=dst_xsec,
                fallback=out.get("cross_point_dst"),
            )
            out["road_prior_shape_ref_used"] = True
            out["road_prior_shape_ref_mode"] = "step1_post_filter_empty"
            out["hard_reason"] = None
            out["hard_hint"] = "step1_candidate_replaced_by_road_prior"
            return out
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

    provisional_picked = _pick_step1_primary_item(topk_debug) or topk_debug[0]
    provisional_shape_ref = _orient_axis_line(
        provisional_picked["seg"],
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
    )
    step1_pair_xsec_src: dict[str, Any] | None = None
    step1_pair_xsec_dst: dict[str, Any] | None = None
    src_xsec_cross = src_xsec
    dst_xsec_cross = dst_xsec
    if _is_valid_linestring(provisional_shape_ref):
        step1_pair_xsec_src = _build_step1_pair_endpoint_xsec(
            xsec_seed=src_xsec,
            endpoint_tag="src",
            node_type=str(src_type),
            shape_ref_line=provisional_shape_ref,
            support=support,
            drivezone_zone_metric=drivezone_zone_metric,
            gore_zone_metric=gore_zone_metric,
            params=params,
        )
        step1_pair_xsec_dst = _build_step1_pair_endpoint_xsec(
            xsec_seed=dst_xsec,
            endpoint_tag="dst",
            node_type=str(dst_type),
            shape_ref_line=provisional_shape_ref,
            support=support,
            drivezone_zone_metric=drivezone_zone_metric,
            gore_zone_metric=gore_zone_metric,
            params=params,
        )
        src_xsec_cross = _resolve_step1_pair_cross_xsec(
            xsec_seed=src_xsec,
            pair_xsec_meta=step1_pair_xsec_src,
        )
        dst_xsec_cross = _resolve_step1_pair_cross_xsec(
            xsec_seed=dst_xsec,
            pair_xsec_meta=step1_pair_xsec_dst,
        )
        _apply_step1_xsec_metrics(
            items=ranked_all,
            src_xsec=src_xsec_cross,
            dst_xsec=dst_xsec_cross,
            reach_xsec_m=reach_xsec_m,
        )
        ranked_reach = [it for it in ranked_used if bool(it.get("reaches_other_end", False))]
        ranked_main = ranked_reach if ranked_reach else ranked_used
        ranked_main = sorted(
            ranked_main,
            key=lambda it: (
                0.0 if bool(it.get("reaches_other_end", False)) else 1.0,
                1.0 - _to_finite_float(it.get("inside_ratio"), 0.0),
                1.0 if bool(it.get("constraint_violation", False)) else 0.0,
                1.0 if bool(it.get("gore_any", False)) else 0.0,
                _to_finite_float(it.get("dist_to_src_xsec_m"), 1e9) + _to_finite_float(it.get("dist_to_dst_xsec_m"), 1e9),
                _to_finite_float(it.get("d_seed"), 1e9),
                -_to_finite_float(it.get("length_m"), 0.0),
                int(it.get("idx", -1)),
            ),
        )
        topk_debug = ranked_main[:topk_pick] if ranked_main else topk_debug

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
        line = (
            _orient_axis_line(seg, src_xsec=src_xsec_cross, dst_xsec=dst_xsec_cross)
            if isinstance(seg, LineString)
            else None
        )
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
    if multi_hard and bool(out.get("multi_corridor_detected", False)):
        out["hard_reason"] = HARD_MULTI_CORRIDOR
        out["hard_hint"] = str(out.get("multi_corridor_hint") or "step1_multi_corridor_detected")
        return out
    out["strategy"] = f"{strategy}|multi_corridor_soft"
    picked_seg = picked["seg"]
    out["shape_ref_line"] = _orient_axis_line(picked_seg, src_xsec=src_xsec_cross, dst_xsec=dst_xsec_cross)
    if _is_valid_linestring(out["shape_ref_line"]):
        step1_pair_xsec_src = _build_step1_pair_endpoint_xsec(
            xsec_seed=src_xsec,
            endpoint_tag="src",
            node_type=str(src_type),
            shape_ref_line=out["shape_ref_line"],
            support=support,
            drivezone_zone_metric=drivezone_zone_metric,
            gore_zone_metric=gore_zone_metric,
            params=params,
        )
        step1_pair_xsec_dst = _build_step1_pair_endpoint_xsec(
            xsec_seed=dst_xsec,
            endpoint_tag="dst",
            node_type=str(dst_type),
            shape_ref_line=out["shape_ref_line"],
            support=support,
            drivezone_zone_metric=drivezone_zone_metric,
            gore_zone_metric=gore_zone_metric,
            params=params,
        )
        src_xsec_cross = _resolve_step1_pair_cross_xsec(
            xsec_seed=src_xsec,
            pair_xsec_meta=step1_pair_xsec_src,
        )
        dst_xsec_cross = _resolve_step1_pair_cross_xsec(
            xsec_seed=dst_xsec,
            pair_xsec_meta=step1_pair_xsec_dst,
        )
        out["shape_ref_line"] = _orient_axis_line(
            picked_seg,
            src_xsec=src_xsec_cross,
            dst_xsec=dst_xsec_cross,
        )
        out["pair_xsec_policy_src"] = step1_pair_xsec_src.get("policy_mode")
        out["pair_xsec_policy_dst"] = step1_pair_xsec_dst.get("policy_mode")
        out["_pair_xsec_cross_ref_src_metric"] = src_xsec_cross
        out["_pair_xsec_cross_ref_dst_metric"] = dst_xsec_cross
        out["_pair_xsec_target_src_metric"] = step1_pair_xsec_src.get("xsec_road_selected")
        out["_pair_xsec_target_dst_metric"] = step1_pair_xsec_dst.get("xsec_road_selected")
    zone_half_w = float(max(1.0, params.get("CORRIDOR_HALF_WIDTH_M", 15.0)))
    zone_topk = int(max(1, int(params.get("STEP1_CORRIDOR_ZONE_TOPK", 3))))
    zone_lines: list[LineString] = []
    for cand in out.get("corridor_candidates", [])[:zone_topk]:
        if not isinstance(cand, dict):
            continue
        line = cand.get("geometry")
        if isinstance(line, LineString) and (not line.is_empty) and line.length > 1e-6:
            zone_lines.append(line)
    shape_ref_line = out.get("shape_ref_line")
    if not zone_lines and isinstance(shape_ref_line, LineString) and (not shape_ref_line.is_empty):
        zone_lines.append(shape_ref_line)
    corridor_zone, zone_source_count, corridor_area = _build_buffered_corridor_zone(
        lines=zone_lines,
        half_width_m=float(zone_half_w),
        clip_zone=passable_zone,
    )
    if corridor_zone is not None and (not corridor_zone.is_empty):
        out["corridor_zone_metric"] = corridor_zone
        out["corridor_zone_source_count"] = int(zone_source_count)
        out["corridor_zone_area_m2"] = corridor_area
    out["corridor_zone_half_width_m"] = float(zone_half_w)
    out["corridor_shape_ref_inside_ratio"] = _line_inside_ratio(
        out.get("shape_ref_line"),
        out.get("corridor_zone_metric"),
    )
    for item in out["traj_gore_flags"]:
        if int(item.get("idx", -1)) == int(picked.get("idx", -2)):
            item["selected"] = True
    src_fallback = picked.get("src_cp") if isinstance(picked.get("src_cp"), Point) else out.get("cross_point_src")
    dst_fallback = picked.get("dst_cp") if isinstance(picked.get("dst_cp"), Point) else out.get("cross_point_dst")
    out["cross_point_src"] = _line_xsec_contact_point(
        line=out.get("shape_ref_line"),
        xsec=src_xsec_cross,
        fallback=src_fallback if isinstance(src_fallback, Point) else None,
    )
    out["cross_point_dst"] = _line_xsec_contact_point(
        line=out.get("shape_ref_line"),
        xsec=dst_xsec_cross,
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
    *,
    traj_xy_index: dict[str, np.ndarray] | None = None,
) -> tuple[np.ndarray, int]:
    if not support.support_traj_ids:
        return np.empty((0, 2), dtype=np.float64), 0
    ids = {str(v) for v in support.support_traj_ids}
    if traj_xy_index is not None:
        pts: list[np.ndarray] = []
        used = 0
        for tid in ids:
            xy = traj_xy_index.get(tid)
            if xy is None or xy.shape[0] < 2:
                continue
            pts.append(xy)
            used += 1
        if not pts:
            return np.empty((0, 2), dtype=np.float64), 0
        return np.vstack(pts), int(used)
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
    out = _subset_support_by_indices(
        support,
        idx,
        hard_anomalies=set(support.hard_anomalies),
    )
    if out is None:
        return None
    out.cluster_count = int(support.cluster_count)
    out.main_cluster_id = int(support.main_cluster_id)
    out.main_cluster_ratio = float(support.main_cluster_ratio)
    out.cluster_sep_m_est = support.cluster_sep_m_est
    out.cluster_sizes = [int(v) for v in support.cluster_sizes]
    out.evidence_cluster_ids = [int(cluster_id) for _ in range(int(out.support_event_count))]
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
    traj_meta_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[Path, str]:
    traj_meta: list[dict[str, Any]] = []
    by_id = {str(t.traj_id): t for t in patch_inputs.trajectories} if traj_meta_index is None else {}
    for tid in sorted({str(v) for v in support.support_traj_ids}):
        if traj_meta_index is not None:
            meta = traj_meta_index.get(tid)
            if meta is None:
                traj_meta.append({"traj_id": tid, "missing": True})
            else:
                traj_meta.append(dict(meta))
            continue
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
        "v": 3,
        "patch_id": str(patch_inputs.patch_id),
        "src": int(support.src_nodeid),
        "dst": int(support.dst_nodeid),
        "cluster_id": int(cluster_id),
        "traj_meta": traj_meta,
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
    traj_xy_index: dict[str, np.ndarray] | None = None,
    traj_meta_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    t0 = perf_counter()
    ids_key = tuple(sorted(str(v) for v in support.support_traj_ids))
    if traj_points_cache is not None and ids_key in traj_points_cache:
        traj_xy, unique_traj_count = traj_points_cache[ids_key]
    else:
        traj_xy, unique_traj_count = _collect_support_traj_points(
            patch_inputs,
            support,
            traj_xy_index=traj_xy_index,
        )
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
                traj_meta_index=traj_meta_index,
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
    result["traj_surface_gate_failure_mode"] = None

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
        if bool(endpoint_in_src) and bool(endpoint_in_dst):
            gate_failure_mode = "in_ratio_only"
        elif (not bool(endpoint_in_src)) and (not bool(endpoint_in_dst)):
            gate_failure_mode = "endpoint_both"
        elif (not bool(endpoint_in_src)) or (not bool(endpoint_in_dst)):
            gate_failure_mode = "endpoint_single"
        else:
            gate_failure_mode = "mixed"
        hard_flags.add(SOFT_ROAD_OUTSIDE_TRAJ_SURFACE)
        result["traj_surface_gate_failure_mode"] = str(gate_failure_mode)
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
                f"gate_failure_mode={gate_failure_mode};"
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


def _safe_width_ratio(near_v: Any, base_v: Any) -> float | None:
    try:
        near_f = float(near_v)
        base_f = float(base_v)
    except Exception:
        return None
    if (not np.isfinite(near_f)) or (not np.isfinite(base_f)) or float(base_f) <= 1e-6:
        return None
    return float(max(0.0, near_f / max(base_f, 1e-6)))


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
    segment_corridor_metric: BaseGeometry | None = None,
    road_prior_shape_ref_metric: LineString | None = None,
    step1_used_road_prior: bool = False,
    step1_road_prior_mode: str | None = None,
    same_pair_multichain: bool = False,
    candidate_branch_id: str | None = None,
    support_mode: str | None = None,
) -> dict[str, Any]:
    t0_center = perf_counter()
    traj_surface_enforced = bool(traj_surface_hint.get("traj_surface_enforced", False))
    step1_shape_ref_valid = _is_valid_linestring(shape_ref_hint_metric)
    road_prior_shape_ref_valid = _is_valid_linestring(road_prior_shape_ref_metric)
    support_mode_norm = str(support_mode or "").strip().lower()
    road_prior_gap_fill_mode = _should_enable_road_prior_gap_fill(
        road_prior_shape_ref_valid=bool(road_prior_shape_ref_valid),
        traj_surface_enforced=bool(traj_surface_enforced),
        step1_used_road_prior=bool(step1_used_road_prior),
        step1_road_prior_mode=step1_road_prior_mode,
        same_pair_multichain=bool(same_pair_multichain),
        support_mode=support_mode_norm,
    )
    use_road_prior_shape_ref = bool(road_prior_shape_ref_valid and (road_prior_gap_fill_mode or (not step1_shape_ref_valid)))
    shape_ref_hint_for_center = road_prior_shape_ref_metric if use_road_prior_shape_ref else shape_ref_hint_metric
    traj_surface_metric_for_center = None if road_prior_gap_fill_mode else traj_surface_hint.get("surface_metric")
    segment_corridor_for_gate = segment_corridor_metric
    if road_prior_gap_fill_mode and road_prior_shape_ref_valid:
        prior_corridor_zone, _prior_zone_source_count, _prior_corridor_area = _build_buffered_corridor_zone(
            lines=[road_prior_shape_ref_metric],
            half_width_m=float(max(1.0, params.get("CORRIDOR_HALF_WIDTH_M", 15.0))),
            clip_zone=None,
        )
        if prior_corridor_zone is not None and (not prior_corridor_zone.is_empty):
            segment_corridor_for_gate = prior_corridor_zone
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
        traj_surface_metric=traj_surface_metric_for_center,
        traj_surface_enforced=(False if road_prior_gap_fill_mode else traj_surface_enforced),
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
        shape_ref_hint_metric=shape_ref_hint_for_center,
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
    road["candidate_branch_id"] = str(candidate_branch_id or "")
    road["same_pair_multi_road_branch_id"] = str(candidate_branch_id or "")
    road["step1_same_pair_multichain"] = bool(same_pair_multichain)
    road["same_pair_multi_road_support_mode"] = (support_mode_norm if bool(same_pair_multichain) else None)
    road["same_pair_multi_road_geometry_mode"] = None
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
    road["xsec_policy_mode_src"] = center.diagnostics.get("xsec_policy_mode_src")
    road["xsec_policy_mode_dst"] = center.diagnostics.get("xsec_policy_mode_dst")
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
    road["road_prior_shape_ref_available"] = bool(road_prior_shape_ref_valid)
    road["road_prior_shape_ref_used"] = bool(use_road_prior_shape_ref)
    road["road_prior_gap_fill_mode"] = bool(road_prior_gap_fill_mode)
    road["step1_road_prior_mode"] = str(step1_road_prior_mode or "") or None
    road["road_prior_shape_ref_length_m"] = (
        float(road_prior_shape_ref_metric.length) if road_prior_shape_ref_valid else None
    )
    road["_road_prior_shape_ref_metric"] = road_prior_shape_ref_metric if road_prior_shape_ref_valid else None
    road["_segment_corridor_metric"] = segment_corridor_for_gate
    road["segment_corridor_enforced"] = bool(
        segment_corridor_for_gate is not None and (not segment_corridor_for_gate.is_empty)
    )
    road["segment_corridor_source"] = "road_prior" if road_prior_gap_fill_mode else "step1"
    road["segment_corridor_inside_ratio"] = None
    road["segment_corridor_shape_ref_inside_ratio"] = None
    road["segment_corridor_outside_len_m"] = None
    road["segment_corridor_rescue_mode"] = None
    road["segment_corridor_inside_tol_m"] = float(
        max(0.0, float(params.get("STEP2_SEGMENT_CORRIDOR_INSIDE_TOL_M", 0.5)))
    )
    road["segment_corridor_min_inside_ratio"] = float(
        max(0.0, min(1.0, float(params.get("STEP2_SEGMENT_CORRIDOR_MIN_INSIDE_RATIO", 0.999))))
    )
    primary_shape_ref_metric = center.shape_ref_metric if _is_valid_linestring(center.shape_ref_metric) else shape_ref_hint_for_center
    same_pair_direct_fallback_line = None
    if (
        bool(same_pair_multichain)
        and support_mode_norm == "road_prior_fallback"
        and road_prior_shape_ref_valid
    ):
        same_pair_direct_fallback_line = _fallback_geometry_from_shape_ref(
            shape_ref_line=road_prior_shape_ref_metric,
            src_xsec=src_xsec,
            dst_xsec=dst_xsec,
        )

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
    if _is_valid_linestring(same_pair_direct_fallback_line):
        road_line = same_pair_direct_fallback_line
        centerline_fallback_used = True
        road["same_pair_multi_road_geometry_mode"] = "road_prior_direct_fallback"
        road["endpoint_fallback_mode_src"] = str(
            road.get("endpoint_fallback_mode_src") or "road_prior_direct_fallback"
        )
        road["endpoint_fallback_mode_dst"] = str(
            road.get("endpoint_fallback_mode_dst") or "road_prior_direct_fallback"
        )
    if not (isinstance(road_line, LineString) and (not road_line.is_empty)):
        fallback_line = _fallback_geometry_from_shape_ref(
            shape_ref_line=primary_shape_ref_metric,
            src_xsec=src_xsec,
            dst_xsec=dst_xsec,
        )
        if (
            not _is_valid_linestring(fallback_line)
            and bool(same_pair_multichain)
            and _is_valid_linestring(primary_shape_ref_metric)
        ):
            fallback_line = _orient_axis_line(
                primary_shape_ref_metric,
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
        if bool(same_pair_multichain) and _is_valid_linestring(primary_shape_ref_metric):
            hard_flags.discard(HARD_CENTER_EMPTY)
            center_empty_downgraded = True
        else:
            endpoint_tol = float(max(0.5, float(params.get("ENDPOINT_ON_XSEC_TOL_M", 1.0))))
            src_dist = _to_finite_float(road.get("endpoint_dist_to_xsec_src_m"), float("nan"))
            dst_dist = _to_finite_float(road.get("endpoint_dist_to_xsec_dst_m"), float("nan"))
            if (
                np.isfinite(src_dist)
                and np.isfinite(dst_dist)
                and src_dist <= endpoint_tol + 1e-6
                and dst_dist <= endpoint_tol + 1e-6
            ):
                hard_flags.discard(HARD_CENTER_EMPTY)
                center_empty_downgraded = True

    src_width_ratio = _safe_width_ratio(road.get("src_width_near_m"), road.get("src_width_base_m"))
    dst_width_ratio = _safe_width_ratio(road.get("dst_width_near_m"), road.get("dst_width_base_m"))
    road["step3_width_ratio_src"] = float(src_width_ratio) if src_width_ratio is not None else None
    road["step3_width_ratio_dst"] = float(dst_width_ratio) if dst_width_ratio is not None else None
    road["step3_widening_suppressed"] = False
    road["step3_widening_suppress_src"] = False
    road["step3_widening_suppress_dst"] = False
    road["step3_widening_suppress_mode"] = None
    if bool(int(params.get("STEP3_WIDENING_SUPPRESS_ENABLE", 1))) and _is_valid_linestring(road_line):
        ratio_trigger = float(max(1.0, float(params.get("STEP3_WIDENING_RATIO_TRIGGER", 1.25))))
        require_expanded_flag = bool(int(params.get("STEP3_WIDENING_REQUIRE_EXPANDED_FLAG", 1)))
        src_trigger = bool(src_width_ratio is not None and float(src_width_ratio) >= ratio_trigger)
        dst_trigger = bool(dst_width_ratio is not None and float(dst_width_ratio) >= ratio_trigger)
        if bool(require_expanded_flag):
            src_trigger = bool(src_trigger and bool(road.get("src_is_expanded", False)))
            dst_trigger = bool(dst_trigger and bool(road.get("dst_is_expanded", False)))
        if src_trigger or dst_trigger:
            shape_ref_suppressed = _fallback_geometry_from_shape_ref(
                shape_ref_line=primary_shape_ref_metric,
                src_xsec=src_xsec,
                dst_xsec=dst_xsec,
            )
            if _is_valid_linestring(shape_ref_suppressed):
                road_line = shape_ref_suppressed
                centerline_fallback_used = True
                road["step3_widening_suppressed"] = True
                road["step3_widening_suppress_src"] = bool(src_trigger)
                road["step3_widening_suppress_dst"] = bool(dst_trigger)
                road["step3_widening_suppress_mode"] = (
                    f"shape_ref_substring;ratio_src={src_width_ratio};ratio_dst={dst_width_ratio};"
                    f"trigger={ratio_trigger:.3f}"
                )

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
        shape_ref_line=primary_shape_ref_metric,
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
        lb_shape_ref_metric=primary_shape_ref_metric,
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

    corridor_zone_raw = segment_corridor_for_gate
    if corridor_zone_raw is not None and (not corridor_zone_raw.is_empty):
        corridor_tol = float(max(0.0, road.get("segment_corridor_inside_tol_m") or 0.0))
        corridor_zone = corridor_zone_raw
        if corridor_tol > 1e-9:
            try:
                buffered = corridor_zone_raw.buffer(float(corridor_tol))
                if buffered is not None and (not buffered.is_empty):
                    corridor_zone = buffered
            except Exception:
                corridor_zone = corridor_zone_raw
        shape_ref_for_check = center.shape_ref_metric
        if not (isinstance(shape_ref_for_check, LineString) and (not shape_ref_for_check.is_empty)):
            shape_ref_for_check = primary_shape_ref_metric
        shape_ref_inside_ratio = _line_inside_ratio(shape_ref_for_check, corridor_zone)
        road["segment_corridor_shape_ref_inside_ratio"] = (
            float(shape_ref_inside_ratio) if shape_ref_inside_ratio is not None else None
        )
        if isinstance(road_line, LineString) and (not road_line.is_empty):
            inside_ratio = _line_inside_ratio(road_line, corridor_zone)
            road["segment_corridor_inside_ratio"] = float(inside_ratio) if inside_ratio is not None else None
            try:
                outside_len = float(max(0.0, float(road_line.difference(corridor_zone).length)))
            except Exception:
                outside_len = float(max(0.0, float(road_line.length)))
            road["segment_corridor_outside_len_m"] = float(outside_len)
            min_ratio = float(max(0.0, min(1.0, road.get("segment_corridor_min_inside_ratio") or 0.0)))
            if (inside_ratio is None) or (float(inside_ratio) + 1e-9 < min_ratio) or (outside_len > 1e-6):
                rescue_applied = False
                rescue_enable = bool(int(params.get("STEP2_SEGMENT_CORRIDOR_RESCUE_ENABLE", 1)))
                rescue_outside_max_m = float(max(0.0, float(params.get("STEP2_SEGMENT_CORRIDOR_RESCUE_OUTSIDE_MAX_M", 5.0))))
                if rescue_enable and outside_len <= rescue_outside_max_m and _is_valid_linestring(primary_shape_ref_metric):
                    rescue_line = _fallback_geometry_from_shape_ref(
                        shape_ref_line=primary_shape_ref_metric,
                        src_xsec=src_xsec,
                        dst_xsec=dst_xsec,
                    )
                    if _is_valid_linestring(rescue_line):
                        rescue_inside_ratio = _line_inside_ratio(rescue_line, corridor_zone)
                        try:
                            rescue_outside_len = float(max(0.0, float(rescue_line.difference(corridor_zone).length)))
                        except Exception:
                            rescue_outside_len = float(max(0.0, float(rescue_line.length)))
                        if (
                            rescue_inside_ratio is not None
                            and float(rescue_inside_ratio) + 1e-9 >= min_ratio
                            and rescue_outside_len <= 1e-6
                        ):
                            road_line = rescue_line
                            centerline_fallback_used = True
                            road["segment_corridor_rescue_mode"] = "shape_ref_substring"
                            road["segment_corridor_inside_ratio"] = float(rescue_inside_ratio)
                            road["segment_corridor_outside_len_m"] = float(rescue_outside_len)
                            if not road.get("endpoint_fallback_mode_src"):
                                road["endpoint_fallback_mode_src"] = "segment_corridor_shape_ref_rescue"
                            if not road.get("endpoint_fallback_mode_dst"):
                                road["endpoint_fallback_mode_dst"] = "segment_corridor_shape_ref_rescue"
                            rescue_applied = True
                if not rescue_applied:
                    hard_flags.add(_HARD_ROAD_OUTSIDE_SEGMENT_CORRIDOR)

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
    road["road_prior_drivezone_override_used"] = False
    if outside_drivezone_len > 1e-6 or not endpoint_drivezone_ok:
        override_drivezone_hard = False
        if road_prior_gap_fill_mode and road_prior_shape_ref_valid:
            prior_drivezone_diag = _drivezone_gate_diagnostics(
                road_line=road_prior_shape_ref_metric,
                drivezone_zone_metric=patch_inputs.drivezone_zone_metric,
                gore_zone_metric=gore_zone_metric,
            )
            try:
                prior_outside_len = float(prior_drivezone_diag.get("road_outside_drivezone_len_m"))
            except Exception:
                prior_outside_len = 0.0
            prior_endpoint_ok = (
                prior_drivezone_diag.get("endpoint_in_drivezone_src") is not False
                and prior_drivezone_diag.get("endpoint_in_drivezone_dst") is not False
            )
            if (
                (prior_outside_len > 1e-6 or (not prior_endpoint_ok))
                and outside_drivezone_len <= prior_outside_len + 2.0
                and (
                    prior_drivezone_diag.get("endpoint_in_drivezone_src") is False
                    or road.get("endpoint_in_drivezone_src") is not False
                )
                and (
                    prior_drivezone_diag.get("endpoint_in_drivezone_dst") is False
                    or road.get("endpoint_in_drivezone_dst") is not False
                )
            ):
                override_drivezone_hard = True
                road["road_prior_drivezone_override_used"] = True
                road["road_prior_outside_drivezone_len_m"] = float(prior_outside_len)
                road["road_prior_in_drivezone_ratio"] = prior_drivezone_diag.get("road_in_drivezone_ratio")
        if not override_drivezone_hard:
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
            shape_ref_line=primary_shape_ref_metric,
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
    corridor_count = 1 if _HARD_ROAD_OUTSIDE_SEGMENT_CORRIDOR in hard_flags else 0
    allow_traj_surface_soft_fail = bool(
        bool(same_pair_multichain)
        and support_mode_norm == "road_prior_fallback"
        and bridge_count <= 0
        and divstrip_count <= 0
        and drivezone_count <= 0
        and corridor_count <= 0
    )
    score = 10.0 * float(in_ratio) - 0.01 * _to_finite_float(road.get("max_segment_m"), 1e6) - 0.1 * float(
        bridge_count
    ) - 0.1 * float(outside_count) - 0.1 * float(divstrip_count) - 0.1 * float(drivezone_count) - 0.1 * float(
        corridor_count
    )
    feasible = (
        bool(has_geometry)
        and (bridge_count <= 0)
        and (divstrip_count <= 0)
        and (drivezone_count <= 0)
        and (corridor_count <= 0)
        and ((outside_count <= 0) or allow_traj_surface_soft_fail)
    )
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


def _same_pair_candidate_has_geometry(road: dict[str, Any]) -> bool:
    geom = road.get("_geometry_metric")
    return bool(isinstance(geom, LineString) and (not geom.is_empty) and bool(road.get("_candidate_has_geometry", False)))


def _same_pair_candidate_has_blocking_hard_reason(road: dict[str, Any]) -> bool:
    hard_reasons = {str(v) for v in (road.get("hard_reasons") or []) if str(v)}
    blocking = {
        HARD_BRIDGE_SEGMENT,
        HARD_DIVSTRIP_INTERSECT,
        HARD_ROAD_OUTSIDE_DRIVEZONE,
        _HARD_ROAD_OUTSIDE_SEGMENT_CORRIDOR,
    }
    return any(reason in blocking for reason in hard_reasons)


def _same_pair_candidate_is_selectable(road: dict[str, Any]) -> bool:
    if not _same_pair_candidate_has_geometry(road):
        return False
    if _same_pair_candidate_has_blocking_hard_reason(road):
        return False
    if bool(road.get("_candidate_feasible", False)):
        return True
    support_mode = str(road.get("same_pair_multi_road_support_mode") or "").strip().lower()
    return bool(road.get("step1_same_pair_multichain", False)) and support_mode == "road_prior_fallback"


def _select_same_pair_multichain_candidates(
    ranked_candidates: Sequence[dict[str, Any]],
    *,
    min_sep_m: float,
    same_pair_station_gap_min_m: float,
) -> list[dict[str, Any]]:
    branch_best: list[dict[str, Any]] = []
    seen_branch_ids: set[str] = set()
    for cand in ranked_candidates:
        if not _same_pair_candidate_is_selectable(cand):
            continue
        branch_id = str(cand.get("same_pair_multi_road_branch_id") or cand.get("candidate_branch_id") or "")
        if branch_id:
            if branch_id in seen_branch_ids:
                continue
            seen_branch_ids.add(branch_id)
        branch_best.append(cand)
    if not branch_best:
        return []
    return _select_non_conflicting_multi_road_candidates(
        branch_best,
        min_sep_m=float(min_sep_m),
        same_pair_station_gap_min_m=float(same_pair_station_gap_min_m),
    )


def _candidate_lines_conflict(lhs: LineString, rhs: LineString, *, min_sep_m: float) -> bool:
    if lhs.is_empty or rhs.is_empty:
        return False
    try:
        if bool(lhs.crosses(rhs)):
            return True
    except Exception:
        pass
    try:
        inter = lhs.intersection(rhs)
        for part in _iter_line_parts(inter):
            if float(part.length) > 1.0:
                return True
    except Exception:
        pass
    try:
        if float(lhs.distance(rhs)) + 1e-9 < float(min_sep_m):
            return True
    except Exception:
        return False
    return False


def _same_pair_multi_road_station_gap(lhs: dict[str, Any], rhs: dict[str, Any]) -> float | None:
    gaps: list[float] = []
    for key in ("same_pair_multi_road_src_station_m", "same_pair_multi_road_dst_station_m"):
        lhs_v = lhs.get(key)
        rhs_v = rhs.get(key)
        if lhs_v is None or rhs_v is None:
            continue
        try:
            gap = abs(float(lhs_v) - float(rhs_v))
        except Exception:
            continue
        if np.isfinite(gap):
            gaps.append(float(gap))
    if not gaps:
        return None
    return float(max(gaps))


def _same_pair_multi_road_allows_close_parallel(
    lhs: dict[str, Any],
    rhs: dict[str, Any],
    *,
    min_station_gap_m: float,
) -> bool:
    if int(lhs.get("src_nodeid", -1)) != int(rhs.get("src_nodeid", -2)):
        return False
    if int(lhs.get("dst_nodeid", -1)) != int(rhs.get("dst_nodeid", -2)):
        return False
    if not (bool(lhs.get("step1_same_pair_multichain", False)) and bool(rhs.get("step1_same_pair_multichain", False))):
        return False

    lhs_branch = str(lhs.get("same_pair_multi_road_branch_id") or lhs.get("candidate_branch_id") or "")
    rhs_branch = str(rhs.get("same_pair_multi_road_branch_id") or rhs.get("candidate_branch_id") or "")
    if (not lhs_branch) or (not rhs_branch) or lhs_branch == rhs_branch:
        return False

    lhs_sig = tuple(str(v) for v in (lhs.get("same_pair_multi_road_signature") or []) if str(v))
    rhs_sig = tuple(str(v) for v in (rhs.get("same_pair_multi_road_signature") or []) if str(v))
    if lhs_sig and rhs_sig and lhs_sig == rhs_sig:
        return False

    station_gap = _same_pair_multi_road_station_gap(lhs, rhs)
    if station_gap is None:
        return False
    return bool(float(station_gap) >= float(min_station_gap_m))


def _same_pair_multi_road_ref_line(road: dict[str, Any]) -> LineString | None:
    for key in ("_road_prior_shape_ref_metric", "_shape_ref_metric"):
        geom = road.get(key)
        if isinstance(geom, LineString) and (not geom.is_empty):
            return geom
    return None


def _same_pair_multi_road_shape_ref_allows_parallel(
    lhs: dict[str, Any],
    rhs: dict[str, Any],
    *,
    min_station_gap_m: float,
) -> bool:
    if not _same_pair_multi_road_allows_close_parallel(
        lhs,
        rhs,
        min_station_gap_m=float(min_station_gap_m),
    ):
        return False
    lhs_ref = _same_pair_multi_road_ref_line(lhs)
    rhs_ref = _same_pair_multi_road_ref_line(rhs)
    if not isinstance(lhs_ref, LineString) or lhs_ref.is_empty:
        return False
    if not isinstance(rhs_ref, LineString) or rhs_ref.is_empty:
        return False
    return not _candidate_lines_conflict(lhs_ref, rhs_ref, min_sep_m=0.0)


def _candidate_roads_conflict(
    lhs: dict[str, Any],
    rhs: dict[str, Any],
    *,
    min_sep_m: float,
    same_pair_station_gap_min_m: float,
) -> bool:
    lhs_line = lhs.get("_geometry_metric")
    rhs_line = rhs.get("_geometry_metric")
    if not isinstance(lhs_line, LineString) or lhs_line.is_empty:
        return False
    if not isinstance(rhs_line, LineString) or rhs_line.is_empty:
        return False
    allow_close_parallel = _same_pair_multi_road_allows_close_parallel(
        lhs,
        rhs,
        min_station_gap_m=float(same_pair_station_gap_min_m),
    )
    geom_conflict = _candidate_lines_conflict(
        lhs_line,
        rhs_line,
        min_sep_m=(0.0 if allow_close_parallel else float(min_sep_m)),
    )
    if not geom_conflict:
        return False
    if allow_close_parallel and _same_pair_multi_road_shape_ref_allows_parallel(
        lhs,
        rhs,
        min_station_gap_m=float(same_pair_station_gap_min_m),
    ):
        return False
    return True


def _select_non_conflicting_multi_road_candidates(
    candidates: Sequence[dict[str, Any]],
    *,
    min_sep_m: float,
    same_pair_station_gap_min_m: float = 0.5,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cand in candidates:
        line = cand.get("_geometry_metric")
        if not isinstance(line, LineString) or line.is_empty:
            continue
        if any(
            _candidate_roads_conflict(
                cand,
                prev,
                min_sep_m=float(min_sep_m),
                same_pair_station_gap_min_m=float(same_pair_station_gap_min_m),
            )
            for prev in out
        ):
            continue
        out.append(cand)
    return out


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


def _assign_multi_road_channel_identity(
    road: dict[str, Any],
    *,
    channel_rank: int,
    channel_count: int,
    same_pair: bool,
) -> None:
    if int(channel_rank) <= 0 or int(channel_count) <= 0:
        return
    base_road_id = re.sub(r"__(?:k|ch)\d+$", "", str(road.get("road_id") or ""))
    cluster_id = int(road.get("candidate_cluster_id", road.get("chosen_cluster_id", 0)) or 0)
    tagged_road_id = f"{base_road_id}__ch{int(channel_rank)}"
    road["road_id"] = tagged_road_id
    road["channel_id"] = f"ch{int(channel_rank)}"
    road["channel_rank"] = int(channel_rank)
    road["channel_count"] = int(channel_count)
    road["same_pair_handled"] = bool(same_pair)
    road["same_pair_multi_road"] = bool(same_pair)
    road["same_pair_multi_road_count"] = int(channel_count) if bool(same_pair) else None
    road["same_pair_multi_road_cluster_id"] = int(cluster_id)
    for key in ("_candidate_hard_breakpoints", "_candidate_soft_breakpoints"):
        for bp in list(road.get(key) or []):
            if not isinstance(bp, dict):
                continue
            bp["road_id"] = tagged_road_id
            bp["src_nodeid"] = int(road.get("src_nodeid"))
            bp["dst_nodeid"] = int(road.get("dst_nodeid"))


def _append_step1_corridor_debug_layers(
    *,
    debug_layers: dict[str, list[dict[str, Any]]],
    road_id: str,
    src: int,
    dst: int,
    support: PairSupport,
    step1_corridor: dict[str, Any],
    params: dict[str, Any],
    branch_id: str | None = None,
) -> None:
    shape_ref_dbg = step1_corridor.get("shape_ref_line")
    if isinstance(shape_ref_dbg, LineString) and (not shape_ref_dbg.is_empty):
        debug_layers["step1_corridor_centerline"].append(
            {
                "geometry": shape_ref_dbg,
                "properties": {
                    "road_id": str(road_id),
                    "src_nodeid": int(src),
                    "dst_nodeid": int(dst),
                    "branch_id": branch_id,
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
                    "road_id": str(road_id),
                    "src_nodeid": int(src),
                    "dst_nodeid": int(dst),
                    "branch_id": branch_id,
                    "corridor_id": cand.get("corridor_id"),
                    "start_traj_id": cand.get("start_traj_id"),
                    "length_m": cand.get("length_m"),
                    "reaches_other_end": cand.get("reaches_other_end"),
                    "inside_ratio": cand.get("inside_ratio"),
                    "drivezone_fallback_used": cand.get("drivezone_fallback_used"),
                },
            }
        )
    for poly in _iter_polygon_parts(step1_corridor.get("corridor_zone_metric")):
        debug_layers["step1_corridor_zone"].append(
            {
                "geometry": poly,
                "properties": {
                    "road_id": str(road_id),
                    "src_nodeid": int(src),
                    "dst_nodeid": int(dst),
                    "branch_id": branch_id,
                    "area_m2": step1_corridor.get("corridor_zone_area_m2"),
                    "source_count": step1_corridor.get("corridor_zone_source_count"),
                    "half_width_m": step1_corridor.get("corridor_zone_half_width_m"),
                    "shape_ref_inside_ratio": step1_corridor.get("corridor_shape_ref_inside_ratio"),
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
    max_support_all_per_pair = int(params.get("STEP1_DEBUG_SUPPORT_TRAJS_ALL_MAX_PER_PAIR", 1))
    keep_all_indices: set[int] | None = None
    if max_support_all_per_pair >= 0:
        if max_support_all_per_pair <= 0:
            keep_all_indices = set()
        else:
            idx_candidates: list[int] = []
            for i, seg in enumerate(support.traj_segments):
                if isinstance(seg, LineString) and (not seg.is_empty):
                    idx_candidates.append(int(i))
            idx_candidates.sort(
                key=lambda ii: (
                    0 if bool((traj_flag_by_idx.get(int(ii)) or {}).get("selected", False)) else 1,
                    0 if (traj_flag_by_idx.get(int(ii)) or {}).get("corridor_id") is not None else 1,
                    -_to_finite_float((traj_flag_by_idx.get(int(ii)) or {}).get("inside_ratio"), -1.0),
                    int(ii),
                )
            )
            keep_all_indices = set(idx_candidates[: max(1, int(max_support_all_per_pair))])

    for i, seg in enumerate(support.traj_segments):
        if not isinstance(seg, LineString) or seg.is_empty:
            continue
        tid = None
        if i < len(support.evidence_traj_ids):
            tid = str(support.evidence_traj_ids[i])
        flag = traj_flag_by_idx.get(int(i), {})
        if keep_all_indices is None or int(i) in keep_all_indices:
            debug_layers["step1_support_trajs_all"].append(
                {
                    "geometry": seg,
                    "properties": {
                        "road_id": str(road_id),
                        "branch_id": branch_id,
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
                    "road_id": str(road_id),
                    "branch_id": branch_id,
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
                        "road_id": str(road_id),
                        "branch_id": branch_id,
                        "endpoint_tag": tag,
                        "strategy": step1_corridor.get("strategy"),
                    },
                }
            )


def _append_selected_candidate_road(
    *,
    selected: dict[str, Any],
    road_records: list[dict[str, Any]],
    road_lines_metric: list[LineString],
    road_feature_props: list[dict[str, Any]],
    hard_breakpoints: list[dict[str, Any]],
    soft_breakpoints: list[dict[str, Any]],
    debug_layers: dict[str, list[dict[str, Any]]],
    debug_enabled: bool,
    stage_timer: _StageTimer,
    src_xsec: LineString,
    dst_xsec: LineString,
    gore_zone_metric: BaseGeometry | None,
    params: dict[str, Any],
) -> None:
    road_line = selected.get("_geometry_metric")
    if not (isinstance(road_line, LineString) and (not road_line.is_empty)):
        selected["no_geometry_candidate"] = True
        sel_hard = set(selected.get("hard_reasons", []))
        if not sel_hard:
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
        if reason == _HARD_ROAD_OUTSIDE_SEGMENT_CORRIDOR:
            hint = (
                f"outside_len_m={selected.get('segment_corridor_outside_len_m')};"
                f"in_ratio={selected.get('segment_corridor_inside_ratio')};"
                f"shape_ref_in_ratio={selected.get('segment_corridor_shape_ref_inside_ratio')};"
                f"threshold={selected.get('segment_corridor_min_inside_ratio')};"
                f"tol_m={selected.get('segment_corridor_inside_tol_m')}"
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
        if reason == _HARD_ROAD_OUTSIDE_SEGMENT_CORRIDOR:
            bp["segment_corridor_outside_len_m"] = selected.get("segment_corridor_outside_len_m")
            bp["segment_corridor_inside_ratio"] = selected.get("segment_corridor_inside_ratio")
            bp["segment_corridor_shape_ref_inside_ratio"] = selected.get("segment_corridor_shape_ref_inside_ratio")
            bp["segment_corridor_min_inside_ratio"] = selected.get("segment_corridor_min_inside_ratio")
            bp["segment_corridor_inside_tol_m"] = selected.get("segment_corridor_inside_tol_m")
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
                src_xsec=src_xsec,
                dst_xsec=dst_xsec,
                gore_zone_metric=gore_zone_metric,
                bridge_max_seg_m=float(params["BRIDGE_MAX_SEG_M"]),
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
_ROAD_PRIOR_DIRECTION_FIELD_CANDIDATES = ("direction", "dir", "flowdir")
_ROAD_PRIOR_EDGE_ID_FIELD_CANDIDATES = ("road_id", "id", "link_id", "uuid", "name")
_ROAD_PRIOR_PAIR_RE = re.compile(r"^\s*(-?\d+)\D+(-?\d+)\s*$")


def _to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, float):
        if np.isfinite(value) and abs(float(value)) <= float(_MAX_SAFE_FLOAT_INT) and float(value).is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except Exception:
            try:
                fv = float(text)
            except Exception:
                return None
            if np.isfinite(fv) and abs(float(fv)) <= float(_MAX_SAFE_FLOAT_INT) and float(fv).is_integer():
                return int(fv)
            return None
    return None


def _pick_int_field(props: dict[str, Any], candidates: Sequence[str]) -> int | None:
    if not props:
        return None
    by_key = {str(k).strip().lower(): v for k, v in props.items()}
    for cand in candidates:
        if str(cand).lower() not in by_key:
            continue
        out = _to_int_or_none(by_key[str(cand).lower()])
        if out is not None:
            return int(out)
    return None


def _pick_str_field(props: dict[str, Any], candidates: Sequence[str]) -> str | None:
    if not props:
        return None
    by_key = {str(k).strip().lower(): v for k, v in props.items()}
    for cand in candidates:
        key = str(cand).strip().lower()
        if key not in by_key:
            continue
        raw = by_key.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return None


def _pair_from_road_id(props: dict[str, Any]) -> tuple[int, int] | None:
    by_key = {str(k).strip().lower(): v for k, v in props.items()}
    for key in ("road_id", "id", "link_id", "name"):
        raw = by_key.get(str(key).lower())
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        m = _ROAD_PRIOR_PAIR_RE.match(text)
        if not m:
            continue
        try:
            src = int(m.group(1))
            dst = int(m.group(2))
        except Exception:
            continue
        return (int(src), int(dst))
    return None


def _load_road_prior_graph(
    road_prior_path: Path | None,
    *,
    respect_direction: bool = False,
    unknown_direction_as_bidirectional: bool = True,
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, Any]]:
    stats: dict[str, Any] = {
        "path": str(road_prior_path) if isinstance(road_prior_path, Path) else None,
        "file_exists": bool(isinstance(road_prior_path, Path) and road_prior_path.is_file()),
        "features_total": 0,
        "features_with_pair": 0,
        "features_missing_pair": 0,
        "direction_unknown_count": 0,
        "direction_unknown_dropped_count": 0,
        "respect_direction": bool(respect_direction),
        "edge_count": 0,
        "src_node_count": 0,
        "load_error": None,
    }
    if road_prior_path is None or (not road_prior_path.is_file()):
        return {}, stats

    try:
        payload = json.loads(road_prior_path.read_text(encoding="utf-8"))
    except Exception as exc:
        stats["load_error"] = f"{type(exc).__name__}: {exc}"
        return {}, stats

    features = payload.get("features", [])
    if not isinstance(features, list):
        stats["load_error"] = "features_not_list"
        return {}, stats
    stats["features_total"] = int(len(features))

    adjacency: dict[int, list[dict[str, Any]]] = {}
    seen: set[tuple[int, int, str]] = set()

    def _add_edge(src_n: int, dst_n: int, edge_uid: str) -> None:
        sig = (int(src_n), int(dst_n), str(edge_uid))
        if sig in seen:
            return
        seen.add(sig)
        adjacency.setdefault(int(src_n), []).append(
            {
                "to": int(dst_n),
                "edge_id": str(edge_uid),
            }
        )

    for idx, feat in enumerate(features):
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties")
        if not isinstance(props, dict):
            props = {}

        src = _pick_int_field(props, _ROAD_PRIOR_SRC_FIELD_CANDIDATES)
        dst = _pick_int_field(props, _ROAD_PRIOR_DST_FIELD_CANDIDATES)
        if src is None or dst is None:
            pair = _pair_from_road_id(props)
            if pair is not None:
                src, dst = pair
        if src is None or dst is None:
            stats["features_missing_pair"] = int(stats["features_missing_pair"]) + 1
            continue
        if int(src) == int(dst):
            continue

        stats["features_with_pair"] = int(stats["features_with_pair"]) + 1
        direction = _pick_int_field(props, _ROAD_PRIOR_DIRECTION_FIELD_CANDIDATES)
        edge_name = _pick_str_field(props, _ROAD_PRIOR_EDGE_ID_FIELD_CANDIDATES) or f"feature_{idx}"
        edge_base = f"{edge_name}@{idx}"
        src_i = int(src)
        dst_i = int(dst)

        if not bool(respect_direction):
            _add_edge(src_i, dst_i, f"{edge_base}:fwd")
            _add_edge(dst_i, src_i, f"{edge_base}:rev")
            if direction not in {2, 3}:
                stats["direction_unknown_count"] = int(stats["direction_unknown_count"]) + 1
            continue

        if direction == 2:
            _add_edge(src_i, dst_i, f"{edge_base}:fwd")
            continue
        if direction == 3:
            _add_edge(dst_i, src_i, f"{edge_base}:rev")
            continue

        stats["direction_unknown_count"] = int(stats["direction_unknown_count"]) + 1
        if bool(unknown_direction_as_bidirectional):
            _add_edge(src_i, dst_i, f"{edge_base}:fwd_unk")
            _add_edge(dst_i, src_i, f"{edge_base}:rev_unk")
        else:
            stats["direction_unknown_dropped_count"] = int(stats["direction_unknown_dropped_count"]) + 1

    for src_i, vals in adjacency.items():
        vals.sort(key=lambda it: (int(it.get("to", -1)), str(it.get("edge_id", ""))))
        adjacency[src_i] = vals
    stats["edge_count"] = int(sum(len(v) for v in adjacency.values()))
    stats["src_node_count"] = int(len(adjacency))
    return adjacency, stats


def _load_road_prior_adjacency(
    road_prior_path: Path | None,
    *,
    respect_direction: bool = False,
) -> tuple[dict[int, set[int]], dict[str, Any]]:
    edge_graph, stats = _load_road_prior_graph(
        road_prior_path,
        respect_direction=bool(respect_direction),
        unknown_direction_as_bidirectional=True,
    )
    adjacency: dict[int, set[int]] = {}
    for src, edges in edge_graph.items():
        dsts = {int(item.get("to")) for item in edges if item.get("to") is not None}
        if dsts:
            adjacency[int(src)] = set(int(v) for v in dsts)
    stats["edge_count"] = int(sum(len(v) for v in adjacency.values()))
    stats["src_node_count"] = int(len(adjacency))
    return adjacency, stats


def _load_road_prior_edge_geometry_map(
    road_prior_path: Path | None,
    *,
    to_metric: callable,
    respect_direction: bool = False,
    unknown_direction_as_bidirectional: bool = True,
) -> tuple[dict[str, LineString], dict[str, Any]]:
    stats: dict[str, Any] = {
        "path": str(road_prior_path) if isinstance(road_prior_path, Path) else None,
        "file_exists": bool(isinstance(road_prior_path, Path) and road_prior_path.is_file()),
        "features_total": 0,
        "features_with_pair": 0,
        "features_missing_pair": 0,
        "features_missing_geometry": 0,
        "direction_unknown_count": 0,
        "direction_unknown_dropped_count": 0,
        "respect_direction": bool(respect_direction),
        "edge_geometry_count": 0,
        "load_error": None,
    }
    if road_prior_path is None or (not road_prior_path.is_file()):
        return {}, stats

    try:
        payload = json.loads(road_prior_path.read_text(encoding="utf-8"))
    except Exception as exc:
        stats["load_error"] = f"{type(exc).__name__}: {exc}"
        return {}, stats

    features = payload.get("features", [])
    if not isinstance(features, list):
        stats["load_error"] = "features_not_list"
        return {}, stats
    stats["features_total"] = int(len(features))

    edge_map: dict[str, LineString] = {}

    def _add_edge(edge_uid: str, line: LineString | None, *, reverse: bool = False) -> None:
        if not isinstance(line, LineString) or line.is_empty or len(line.coords) < 2 or float(line.length) <= 1e-6:
            return
        edge_map[str(edge_uid)] = _reverse_line_if_needed(line) if bool(reverse) else line

    for idx, feat in enumerate(features):
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties")
        if not isinstance(props, dict):
            props = {}
        src = _pick_int_field(props, _ROAD_PRIOR_SRC_FIELD_CANDIDATES)
        dst = _pick_int_field(props, _ROAD_PRIOR_DST_FIELD_CANDIDATES)
        if src is None or dst is None:
            pair = _pair_from_road_id(props)
            if pair is not None:
                src, dst = pair
        if src is None or dst is None:
            stats["features_missing_pair"] = int(stats["features_missing_pair"]) + 1
            continue
        if int(src) == int(dst):
            continue
        stats["features_with_pair"] = int(stats["features_with_pair"]) + 1

        line = _project_road_prior_geometry_to_metric_line(
            feat.get("geometry"),
            to_metric=to_metric,
        )
        if not isinstance(line, LineString):
            stats["features_missing_geometry"] = int(stats["features_missing_geometry"]) + 1
            continue

        direction = _pick_int_field(props, _ROAD_PRIOR_DIRECTION_FIELD_CANDIDATES)
        edge_name = _pick_str_field(props, _ROAD_PRIOR_EDGE_ID_FIELD_CANDIDATES) or f"feature_{idx}"
        edge_base = f"{edge_name}@{idx}"

        if not bool(respect_direction):
            _add_edge(f"{edge_base}:fwd", line, reverse=False)
            _add_edge(f"{edge_base}:rev", line, reverse=True)
            if direction not in {2, 3}:
                stats["direction_unknown_count"] = int(stats["direction_unknown_count"]) + 1
            continue

        if direction == 2:
            _add_edge(f"{edge_base}:fwd", line, reverse=False)
            continue
        if direction == 3:
            _add_edge(f"{edge_base}:rev", line, reverse=True)
            continue

        stats["direction_unknown_count"] = int(stats["direction_unknown_count"]) + 1
        if bool(unknown_direction_as_bidirectional):
            _add_edge(f"{edge_base}:fwd_unk", line, reverse=False)
            _add_edge(f"{edge_base}:rev_unk", line, reverse=True)
        else:
            stats["direction_unknown_dropped_count"] = int(stats["direction_unknown_dropped_count"]) + 1

    stats["edge_geometry_count"] = int(len(edge_map))
    return edge_map, stats


def _build_road_prior_pair_shape_ref_map(
    compressed_adj: dict[int, list[dict[str, Any]]],
    *,
    edge_geometry_by_id: dict[str, LineString],
) -> tuple[dict[tuple[int, int], LineString], dict[str, Any]]:
    pair_map: dict[tuple[int, int], LineString] = {}
    stats = {
        "pair_shape_ref_count": 0,
        "ambiguous_pair_count": 0,
        "missing_geometry_pair_count": 0,
    }
    for src, edges in compressed_adj.items():
        by_dst: dict[int, list[dict[str, Any]]] = {}
        for edge in edges:
            to_raw = edge.get("to")
            if to_raw is None:
                continue
            by_dst.setdefault(int(to_raw), []).append(edge)
        for dst, dst_edges in by_dst.items():
            if len(dst_edges) != 1:
                stats["ambiguous_pair_count"] = int(stats["ambiguous_pair_count"]) + 1
                continue
            edge = dst_edges[0]
            edge_ids = [str(v) for v in edge.get("edge_ids", []) if str(v)]
            if not edge_ids:
                stats["missing_geometry_pair_count"] = int(stats["missing_geometry_pair_count"]) + 1
                continue
            lines: list[LineString] = []
            missing_geometry = False
            for edge_id in edge_ids:
                line = edge_geometry_by_id.get(str(edge_id))
                if not isinstance(line, LineString) or line.is_empty:
                    missing_geometry = True
                    break
                lines.append(line)
            if missing_geometry:
                stats["missing_geometry_pair_count"] = int(stats["missing_geometry_pair_count"]) + 1
                continue
            merged = _concat_line_sequence(lines)
            if not isinstance(merged, LineString) or merged.is_empty or len(merged.coords) < 2:
                stats["missing_geometry_pair_count"] = int(stats["missing_geometry_pair_count"]) + 1
                continue
            pair_map[(int(src), int(dst))] = merged
            stats["pair_shape_ref_count"] = int(stats["pair_shape_ref_count"]) + 1
    return pair_map, stats


def _compress_topology_graph(
    adjacency_edges: dict[int, list[dict[str, Any]]],
    *,
    cross_nodes: set[int],
    enable: bool,
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, Any]]:
    all_nodes: set[int] = set(int(v) for v in cross_nodes)
    out_neighbors: dict[int, set[int]] = {}
    in_neighbors: dict[int, set[int]] = {}
    for src, edges in adjacency_edges.items():
        src_i = int(src)
        all_nodes.add(src_i)
        out_neighbors.setdefault(src_i, set())
        for edge in edges:
            dst_i = int(edge.get("to"))
            all_nodes.add(dst_i)
            out_neighbors.setdefault(src_i, set()).add(dst_i)
            in_neighbors.setdefault(dst_i, set()).add(src_i)
    for node in all_nodes:
        out_neighbors.setdefault(int(node), set())
        in_neighbors.setdefault(int(node), set())

    removable_nodes = {
        int(node)
        for node in all_nodes
        if int(node) not in cross_nodes
        and int(len(in_neighbors.get(int(node), set()))) == 1
        and int(len(out_neighbors.get(int(node), set()))) == 1
    }
    if not bool(enable):
        removable_nodes = set()

    keep_nodes = {int(node) for node in all_nodes if int(node) not in removable_nodes}
    compressed: dict[int, list[dict[str, Any]]] = {}
    seen: set[tuple[int, int, tuple[str, ...]]] = set()
    cycle_truncate_count = 0

    for src in sorted(keep_nodes):
        src_edges = list(adjacency_edges.get(int(src), []))
        for first_edge in src_edges:
            chain_edge_ids: list[str] = []
            path_nodes: list[int] = [int(src)]
            visited: set[int] = set()
            edge_cur = dict(first_edge)
            for _ in range(100000):
                dst = int(edge_cur.get("to"))
                edge_id = str(edge_cur.get("edge_id") or "")
                chain_edge_ids.append(edge_id)
                path_nodes.append(int(dst))
                if int(dst) in keep_nodes:
                    break
                if int(dst) in visited:
                    cycle_truncate_count += 1
                    break
                visited.add(int(dst))
                next_edges = list(adjacency_edges.get(int(dst), []))
                if len(next_edges) != 1:
                    break
                edge_cur = dict(next_edges[0])
            if len(path_nodes) < 2:
                continue
            dst_keep = int(path_nodes[-1])
            sig = (int(src), int(dst_keep), tuple(chain_edge_ids))
            if sig in seen:
                continue
            seen.add(sig)
            compressed.setdefault(int(src), []).append(
                {
                    "to": int(dst_keep),
                    "edge_ids": [str(v) for v in chain_edge_ids],
                    "path_nodes": [int(v) for v in path_nodes],
                }
            )

    for src, vals in compressed.items():
        vals.sort(
            key=lambda it: (
                int(it.get("to", -1)),
                int(len(it.get("edge_ids", []))),
                ",".join(str(v) for v in it.get("edge_ids", [])),
            )
        )
        compressed[src] = vals

    stats = {
        "raw_node_count": int(len(all_nodes)),
        "raw_edge_count": int(sum(len(v) for v in adjacency_edges.values())),
        "compress_enabled": bool(enable),
        "compressible_node_count": int(len(removable_nodes)),
        "keep_node_count": int(len(keep_nodes)),
        "compressed_edge_count": int(sum(len(v) for v in compressed.values())),
        "cycle_truncate_count": int(cycle_truncate_count),
    }
    return compressed, stats


def _reverse_compressed_graph(
    compressed_adj: dict[int, list[dict[str, Any]]],
) -> dict[int, list[dict[str, Any]]]:
    reversed_graph: dict[int, list[dict[str, Any]]] = {}
    for src, edges in compressed_adj.items():
        src_i = int(src)
        for idx, edge in enumerate(edges):
            to_raw = edge.get("to")
            if to_raw is None:
                continue
            dst_i = int(to_raw)
            edge_ids = [str(v) for v in edge.get("edge_ids", [])]
            path_nodes = [int(v) for v in edge.get("path_nodes", []) if v is not None]
            if not path_nodes:
                path_nodes = [int(src_i), int(dst_i)]
            if int(path_nodes[0]) != int(src_i):
                path_nodes = [int(src_i)] + path_nodes
            if int(path_nodes[-1]) != int(dst_i):
                path_nodes.append(int(dst_i))
            rev_edge_ids = [f"rev:{str(v)}" for v in reversed(edge_ids)] if edge_ids else [f"rev_edge_{src_i}_{dst_i}_{idx}"]
            rev_path_nodes = [int(v) for v in reversed(path_nodes)]
            reversed_graph.setdefault(int(dst_i), []).append(
                {
                    "to": int(src_i),
                    "edge_ids": [str(v) for v in rev_edge_ids],
                    "path_nodes": [int(v) for v in rev_path_nodes],
                }
            )
    for src, vals in reversed_graph.items():
        vals.sort(
            key=lambda it: (
                int(it.get("to", -1)),
                int(len(it.get("edge_ids", []))),
                ",".join(str(v) for v in it.get("edge_ids", [])),
            )
        )
        reversed_graph[int(src)] = vals
    return reversed_graph


def _collect_topology_anchor_seeds(
    compressed_adj: dict[int, list[dict[str, Any]]],
    *,
    cross_nodes: set[int],
    seed_role: str = "out",
    shared_group_members_by_nodeid: dict[int, list[int]] | None = None,
) -> list[dict[str, Any]]:
    role = str(seed_role or "out").strip().lower()
    role_tag = role if role in {"out", "in"} else "out"
    seeds: list[dict[str, Any]] = []
    for src in sorted(int(v) for v in cross_nodes):
        edges = list(compressed_adj.get(int(src), []))
        borrowed_src: int | None = None
        if not edges and shared_group_members_by_nodeid:
            for sibling in shared_group_members_by_nodeid.get(int(src), []):
                sibling_i = int(sibling)
                if sibling_i == int(src):
                    continue
                sibling_edges = list(compressed_adj.get(int(sibling_i), []))
                if sibling_edges:
                    edges = sibling_edges
                    borrowed_src = int(sibling_i)
                    break
        if not edges:
            seeds.append(
                {
                    "anchor_id": f"{int(src)}::{role_tag.upper()}::NO_EDGE",
                    "src_nodeid": int(src),
                    "start_to": None,
                    "start_edge_ids": [],
                    "start_path_nodes": [int(src)],
                    "anchor_role": str(role_tag),
                }
            )
            continue
        used_anchor_ids: set[str] = set()
        for idx, edge in enumerate(edges):
            edge_ids = [str(v) for v in edge.get("edge_ids", [])]
            first_edge_id = edge_ids[0] if edge_ids else f"edge_{int(idx)}"
            anchor_id = f"{int(src)}::{role_tag.upper()}::{str(first_edge_id)}"
            if anchor_id in used_anchor_ids:
                anchor_id = f"{anchor_id}#{int(idx)}"
            used_anchor_ids.add(anchor_id)
            to_raw = edge.get("to")
            try:
                start_to = int(to_raw) if to_raw is not None else None
            except Exception:
                start_to = None
            path_nodes = [int(v) for v in edge.get("path_nodes", []) if v is not None]
            if path_nodes and int(path_nodes[0]) != int(src):
                if borrowed_src is not None and int(path_nodes[0]) == int(borrowed_src):
                    path_nodes = [int(src)] + [int(v) for v in path_nodes[1:]]
                else:
                    path_nodes = [int(src)] + path_nodes
            if not path_nodes:
                path_nodes = [int(src)]
                if start_to is not None:
                    path_nodes.append(int(start_to))
            seeds.append(
                {
                    "anchor_id": str(anchor_id),
                    "src_nodeid": int(src),
                    "start_to": int(start_to) if start_to is not None else None,
                    "start_edge_ids": edge_ids,
                    "start_path_nodes": [int(v) for v in path_nodes],
                    "anchor_role": str(role_tag),
                    "borrowed_from_src": int(borrowed_src) if borrowed_src is not None else None,
                }
            )
    return seeds


def _search_topology_next_xsecs_from_anchor(
    compressed_adj: dict[int, list[dict[str, Any]]],
    *,
    src_nodeid: int,
    start_to: int | None,
    start_edge_ids: Sequence[str],
    start_path_nodes: Sequence[int],
    cross_nodes: set[int],
    max_expansions: int,
) -> dict[str, Any]:
    src = int(src_nodeid)
    if start_to is None:
        return {
            "src_nodeid": int(src),
            "dst_paths": {},
            "dst_nodeids": [],
            "expansions": 0,
            "overflow": False,
        }

    init_node_path = [int(v) for v in start_path_nodes if v is not None]
    if not init_node_path:
        init_node_path = [int(src), int(start_to)]
    if int(init_node_path[0]) != int(src):
        init_node_path = [int(src)] + [int(v) for v in init_node_path]
    if int(init_node_path[-1]) != int(start_to):
        init_node_path.append(int(start_to))
    init_edge_path = [str(v) for v in start_edge_ids]

    stack: list[tuple[int, list[int], list[str]]] = [
        (int(start_to), [int(v) for v in init_node_path], [str(v) for v in init_edge_path])
    ]
    expansions = 1
    overflow = False
    dst_paths_raw: dict[int, list[dict[str, Any]]] = {}

    while stack:
        node, node_path, edge_path = stack.pop()
        if int(node) != int(src) and int(node) in cross_nodes:
            dst_paths_raw.setdefault(int(node), []).append(
                {
                    "node_path": [int(v) for v in node_path],
                    "edge_ids": [str(v) for v in edge_path],
                }
            )
            continue
        for edge in compressed_adj.get(int(node), []):
            if expansions >= int(max_expansions):
                overflow = True
                stack = []
                break
            nxt = int(edge.get("to"))
            if int(nxt) in node_path:
                continue
            edge_ids = [str(v) for v in edge.get("edge_ids", [])]
            stack.append(
                (
                    int(nxt),
                    [int(v) for v in node_path] + [int(nxt)],
                    [str(v) for v in edge_path] + edge_ids,
                )
            )
            expansions += 1

    dst_paths: dict[int, list[dict[str, Any]]] = {}
    for dst, records in dst_paths_raw.items():
        uniq: dict[tuple[str, ...], dict[str, Any]] = {}
        for rec in records:
            edge_ids = [str(v) for v in rec.get("edge_ids", [])]
            node_path = [int(v) for v in rec.get("node_path", [])]
            sig = tuple(edge_ids) if edge_ids else tuple(str(v) for v in node_path)
            if sig in uniq:
                continue
            uniq[sig] = {
                "node_path": node_path,
                "edge_ids": edge_ids,
                "signature": [str(v) for v in sig],
                "chain_len": int(len(edge_ids)),
            }
        dst_paths[int(dst)] = list(uniq.values())

    return {
        "src_nodeid": int(src),
        "dst_paths": dst_paths,
        "dst_nodeids": sorted(int(k) for k in dst_paths.keys()),
        "expansions": int(expansions),
        "overflow": bool(overflow),
    }


def _search_topology_next_xsecs(
    compressed_adj: dict[int, list[dict[str, Any]]],
    *,
    src_nodeid: int,
    cross_nodes: set[int],
    max_expansions: int,
) -> dict[str, Any]:
    src = int(src_nodeid)
    stack: list[tuple[int, list[int], list[str]]] = [(int(src), [int(src)], [])]
    expansions = 0
    overflow = False
    dst_paths_raw: dict[int, list[dict[str, Any]]] = {}

    while stack:
        node, node_path, edge_path = stack.pop()
        if int(node) != int(src) and int(node) in cross_nodes:
            dst_paths_raw.setdefault(int(node), []).append(
                {
                    "node_path": [int(v) for v in node_path],
                    "edge_ids": [str(v) for v in edge_path],
                }
            )
            continue
        for edge in compressed_adj.get(int(node), []):
            if expansions >= int(max_expansions):
                overflow = True
                stack = []
                break
            nxt = int(edge.get("to"))
            if int(nxt) in node_path:
                continue
            edge_ids = [str(v) for v in edge.get("edge_ids", [])]
            stack.append(
                (
                    int(nxt),
                    [int(v) for v in node_path] + [int(nxt)],
                    [str(v) for v in edge_path] + edge_ids,
                )
            )
            expansions += 1

    dst_paths: dict[int, list[dict[str, Any]]] = {}
    for dst, records in dst_paths_raw.items():
        uniq: dict[tuple[str, ...], dict[str, Any]] = {}
        for rec in records:
            edge_ids = [str(v) for v in rec.get("edge_ids", [])]
            node_path = [int(v) for v in rec.get("node_path", [])]
            sig = tuple(edge_ids) if edge_ids else tuple(str(v) for v in node_path)
            if sig in uniq:
                continue
            uniq[sig] = {
                "node_path": node_path,
                "edge_ids": edge_ids,
                "signature": [str(v) for v in sig],
                "chain_len": int(len(edge_ids)),
            }
        dst_paths[int(dst)] = list(uniq.values())

    return {
        "src_nodeid": int(src),
        "dst_paths": dst_paths,
        "dst_nodeids": sorted(int(k) for k in dst_paths.keys()),
        "expansions": int(expansions),
        "overflow": bool(overflow),
    }


def _build_topology_unique_anchor_decisions(
    compressed_adj: dict[int, list[dict[str, Any]]],
    *,
    cross_nodes: set[int],
    xsec_map: dict[int, Any],
    require_unique_chain: bool,
    max_expansions: int,
    shared_group_members_by_nodeid: dict[int, list[int]] | None = None,
) -> tuple[
    dict[int, set[int]],
    set[tuple[int, int]],
    dict[int, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    allowed_dst_by_src: dict[int, set[int]] = {}
    allowed_pairs: set[tuple[int, int]] = set()
    node_decisions: dict[int, dict[str, Any]] = {}
    anchor_decisions: dict[str, dict[str, Any]] = {}
    straight_features: list[dict[str, Any]] = []
    chain_features: list[dict[str, Any]] = []

    anchors_out = _collect_topology_anchor_seeds(
        compressed_adj,
        cross_nodes=cross_nodes,
        seed_role="out",
        shared_group_members_by_nodeid=shared_group_members_by_nodeid,
    )
    # Only supplement reverse anchors for NO_EDGE nodes that still have incoming topology.
    # This recovers sink / patch-truncated cases without turning every accepted pair into
    # a symmetric duplicate anchor.
    reverse_adj = _reverse_compressed_graph(compressed_adj)
    reverse_seed_nodes = {
        int(src)
        for src in cross_nodes
        if (not list(compressed_adj.get(int(src), []))) and bool(reverse_adj.get(int(src), []))
    }
    anchors_in = _collect_topology_anchor_seeds(
        reverse_adj,
        cross_nodes=reverse_seed_nodes,
        seed_role="in",
        shared_group_members_by_nodeid=shared_group_members_by_nodeid,
    )
    anchor_batches: list[tuple[str, dict[int, list[dict[str, Any]]], list[dict[str, Any]]]] = [
        ("forward", compressed_adj, anchors_out),
        ("reverse", reverse_adj, anchors_in),
    ]

    accepted_anchor_count = 0
    unresolved_anchor_count = 0
    multi_dst_anchor_count = 0
    multi_chain_anchor_count = 0
    overflow_anchor_count = 0
    shared_group_sibling_filtered_anchor_count = 0

    def _is_shared_group_sibling_pair(src_nodeid: int, dst_nodeid: int) -> bool:
        if not shared_group_members_by_nodeid:
            return False
        src_i = int(src_nodeid)
        dst_i = int(dst_nodeid)
        if src_i == dst_i:
            return False
        src_members = {int(v) for v in shared_group_members_by_nodeid.get(int(src_i), [])}
        dst_members = {int(v) for v in shared_group_members_by_nodeid.get(int(dst_i), [])}
        if not src_members or not dst_members:
            return False
        return bool(src_members.intersection(dst_members))

    node_agg: dict[int, dict[str, Any]] = {
        int(src): {
            "src_nodeid": int(src),
            "anchor_ids": [],
            "accepted_dst": set(),
            "dst_vote_map": {},
            "has_multi_dst": False,
            "has_multi_chain": False,
            "has_overflow": False,
        }
        for src in sorted(int(v) for v in cross_nodes)
    }

    for search_direction, graph_used, seeds in anchor_batches:
        reverse_mode = str(search_direction) == "reverse"
        for seed in seeds:
            anchor_id = str(seed.get("anchor_id") or "")
            anchor_role = str(seed.get("anchor_role") or ("in" if reverse_mode else "out")).strip().lower()
            src = int(seed.get("src_nodeid"))
            start_to = seed.get("start_to")
            if start_to is not None:
                start_to = int(start_to)
            start_edge_ids = [str(v) for v in seed.get("start_edge_ids", [])]
            start_path_nodes = [int(v) for v in seed.get("start_path_nodes", [])]

            search = _search_topology_next_xsecs_from_anchor(
                graph_used,
                src_nodeid=int(src),
                start_to=start_to,
                start_edge_ids=start_edge_ids,
                start_path_nodes=start_path_nodes,
                cross_nodes=cross_nodes,
                max_expansions=int(max(100, max_expansions)),
            )
            dst_nodeids = [int(v) for v in search.get("dst_nodeids", [])]
            dst_paths = {
                int(k): list(v)
                for k, v in dict(search.get("dst_paths", {})).items()
            }
            if bool(search.get("overflow", False)):
                overflow_anchor_count += 1

            status = "unresolved"
            reason = SOFT_UNRESOLVED_NEIGHBOR
            chosen_dst: int | None = None
            chain_count = 0
            pair_src: int | None = None
            pair_dst: int | None = None
            if len(dst_nodeids) == 0:
                unresolved_anchor_count += 1
            elif len(dst_nodeids) >= 2:
                status = "multi_dst"
                reason = HARD_MULTI_NEIGHBOR_FOR_NODE
                multi_dst_anchor_count += 1
            else:
                chosen_dst = int(dst_nodeids[0])
                chain_count = int(len(dst_paths.get(int(chosen_dst), [])))
                if bool(require_unique_chain) and chain_count >= 2:
                    status = "multi_chain"
                    reason = _HARD_MULTI_CHAIN_SAME_DST
                    multi_chain_anchor_count += 1
                else:
                    if bool(reverse_mode):
                        pair_src = int(chosen_dst)
                        pair_dst = int(src)
                    else:
                        pair_src = int(src)
                        pair_dst = int(chosen_dst)
                    if pair_src is not None and pair_dst is not None and _is_shared_group_sibling_pair(pair_src, pair_dst):
                        status = "filtered_shared_group_sibling"
                        reason = "shared_group_sibling_filtered"
                        shared_group_sibling_filtered_anchor_count += 1
                    else:
                        status = "accepted"
                        reason = "accepted"
                        accepted_anchor_count += 1
                        allowed_dst_by_src.setdefault(int(pair_src), set()).add(int(pair_dst))
                        allowed_pairs.add((int(pair_src), int(pair_dst)))

            agg = node_agg.setdefault(
                int(src),
                {
                    "src_nodeid": int(src),
                    "anchor_ids": [],
                    "accepted_dst": set(),
                    "dst_vote_map": {},
                    "has_multi_dst": False,
                    "has_multi_chain": False,
                    "has_overflow": False,
                },
            )
            agg["anchor_ids"].append(str(anchor_id))
            agg["has_overflow"] = bool(agg.get("has_overflow", False) or bool(search.get("overflow", False)))
            if status == "accepted" and chosen_dst is not None:
                cast_set = agg.get("accepted_dst")
                if isinstance(cast_set, set):
                    cast_set.add(int(chosen_dst))
                else:
                    agg["accepted_dst"] = {int(chosen_dst)}
            if status == "multi_dst":
                agg["has_multi_dst"] = True
            if status == "multi_chain":
                agg["has_multi_chain"] = True
            vote_map = agg.get("dst_vote_map")
            if not isinstance(vote_map, dict):
                vote_map = {}
                agg["dst_vote_map"] = vote_map
            for dst in dst_nodeids:
                vote_map[int(dst)] = int(vote_map.get(int(dst), 0) + int(len(dst_paths.get(int(dst), [])) or 1))

            line_targets: list[tuple[int, int, int | None]] = []
            if status in {"accepted", "multi_chain"} and chosen_dst is not None:
                if bool(reverse_mode):
                    line_targets = [(int(chosen_dst), int(src), int(chosen_dst))]
                else:
                    line_targets = [(int(src), int(chosen_dst), int(chosen_dst))]
            elif status == "multi_dst":
                if bool(reverse_mode):
                    line_targets = [(int(dst), int(src), int(dst)) for dst in dst_nodeids]
                else:
                    line_targets = [(int(src), int(dst), int(dst)) for dst in dst_nodeids]

            for pair_src_i, pair_dst_i, raw_dst in line_targets:
                src_mid = _cross_section_midpoint(xsec_map.get(int(pair_src_i)))
                dst_mid = _cross_section_midpoint(xsec_map.get(int(pair_dst_i)))
                if src_mid is None or dst_mid is None:
                    continue
                line = LineString([(float(src_mid.x), float(src_mid.y)), (float(dst_mid.x), float(dst_mid.y))])
                if line.is_empty or line.length <= 0:
                    continue
                chain_n = int(chain_count)
                if raw_dst is not None:
                    if chosen_dst is not None and int(raw_dst) == int(chosen_dst):
                        chain_n = int(chain_count)
                    else:
                        chain_n = int(len(dst_paths.get(int(raw_dst), [])))
                straight_features.append(
                    {
                        "type": "Feature",
                        "geometry": mapping(line),
                        "properties": {
                            "src_nodeid": int(pair_src_i),
                            "dst_nodeid": int(pair_dst_i),
                            "seed_src_nodeid": int(src),
                            "anchor_id": str(anchor_id),
                            "anchor_role": str(anchor_role),
                            "search_direction": str(search_direction),
                            "start_edge_id": str(start_edge_ids[0]) if start_edge_ids else None,
                            "status": str(status),
                            "reason": str(reason),
                            "dst_count": int(len(dst_nodeids)),
                            "chain_count": int(chain_n),
                            "search_overflow": bool(search.get("overflow", False)),
                            "expansions": int(search.get("expansions", 0)),
                        },
                    }
                )
                if raw_dst is None:
                    continue
                for path_idx, rec in enumerate(dst_paths.get(int(raw_dst), [])[:5], start=1):
                    chain_features.append(
                        {
                            "type": "Feature",
                            "geometry": mapping(line),
                            "properties": {
                                "src_nodeid": int(pair_src_i),
                                "dst_nodeid": int(pair_dst_i),
                                "seed_src_nodeid": int(src),
                                "anchor_id": str(anchor_id),
                                "anchor_role": str(anchor_role),
                                "search_direction": str(search_direction),
                                "start_edge_id": str(start_edge_ids[0]) if start_edge_ids else None,
                                "status": str(status),
                                "reason": str(reason),
                                "path_idx": int(path_idx),
                                "path_node_count": int(len(rec.get("node_path", []))),
                                "chain_len": int(rec.get("chain_len", 0)),
                                "edge_ids": [str(v) for v in rec.get("edge_ids", [])[:20]],
                            },
                        }
                    )

            anchor_decisions[str(anchor_id)] = {
                "anchor_id": str(anchor_id),
                "anchor_role": str(anchor_role),
                "search_direction": str(search_direction),
                "src_nodeid": int(src),
                "start_edge_id": str(start_edge_ids[0]) if start_edge_ids else None,
                "start_to": int(start_to) if start_to is not None else None,
                "status": str(status),
                "reason": str(reason),
                "dst_nodeids": [int(v) for v in dst_nodeids],
                "chosen_dst_nodeid": int(chosen_dst) if chosen_dst is not None else None,
                "pair_src_nodeid": int(pair_src) if pair_src is not None else None,
                "pair_dst_nodeid": int(pair_dst) if pair_dst is not None else None,
                "chain_count": int(chain_count),
                "expansions": int(search.get("expansions", 0)),
                "search_overflow": bool(search.get("overflow", False)),
                "dst_paths": {
                    str(int(dst)): [
                        {
                            "node_path": [int(v) for v in rec.get("node_path", [])],
                            "edge_ids": [str(v) for v in rec.get("edge_ids", [])[:50]],
                            "chain_len": int(rec.get("chain_len", 0)),
                        }
                        for rec in recs[:10]
                    ]
                    for dst, recs in sorted(dst_paths.items(), key=lambda it: int(it[0]))
                },
            }

    accepted_src_nodes = 0
    unresolved_src_nodes = 0
    multi_dst_src_nodes = 0
    multi_chain_src_nodes = 0
    overflow_src_nodes = 0
    for src in sorted(int(v) for v in cross_nodes):
        agg = node_agg.get(int(src), {})
        accepted_dst = sorted(int(v) for v in set(agg.get("accepted_dst", set())))
        has_multi_dst = bool(agg.get("has_multi_dst", False))
        has_multi_chain = bool(agg.get("has_multi_chain", False))
        has_overflow = bool(agg.get("has_overflow", False))
        if has_overflow:
            overflow_src_nodes += 1
        if has_multi_dst:
            multi_dst_src_nodes += 1
        if has_multi_chain:
            multi_chain_src_nodes += 1
        if accepted_dst:
            accepted_src_nodes += 1
            status = "accepted"
            reason = "accepted_multi_anchor" if len(accepted_dst) > 1 else "accepted"
            chosen_dst = int(accepted_dst[0])
        else:
            unresolved_src_nodes += 1
            status = "unresolved"
            reason = SOFT_UNRESOLVED_NEIGHBOR
            chosen_dst = None
        vote_map_raw = agg.get("dst_vote_map", {})
        vote_map = {str(int(k)): int(v) for k, v in dict(vote_map_raw).items() if int(v) > 0}
        node_decisions[int(src)] = {
            "src_nodeid": int(src),
            "status": str(status),
            "reason": str(reason),
            "dst_nodeids": [int(v) for v in accepted_dst],
            "chosen_dst_nodeid": int(chosen_dst) if chosen_dst is not None else None,
            "anchor_count": int(len(agg.get("anchor_ids", []))),
            "anchor_ids": [str(v) for v in agg.get("anchor_ids", [])[:50]],
            "dst_vote_map": dict(vote_map),
            "has_multi_dst_anchor": bool(has_multi_dst),
            "has_multi_chain_anchor": bool(has_multi_chain),
            "search_overflow": bool(has_overflow),
        }

    # Deduplicate debug line outputs to keep one segment per logical key.
    if straight_features:
        straight_dedup: dict[tuple[int, int], dict[str, Any]] = {}
        for feat in straight_features:
            props = feat.get("properties") if isinstance(feat, dict) else None
            if not isinstance(props, dict):
                continue
            src_raw = props.get("src_nodeid")
            dst_raw = props.get("dst_nodeid")
            if src_raw is None or dst_raw is None:
                continue
            try:
                key = (int(src_raw), int(dst_raw))
            except Exception:
                continue
            if key not in straight_dedup:
                feat_keep = dict(feat)
                props_keep = dict(props)
                props_keep["dedup_count"] = 1
                feat_keep["properties"] = props_keep
                straight_dedup[key] = feat_keep
            else:
                prev = straight_dedup[key]
                prev_props = prev.get("properties")
                if isinstance(prev_props, dict):
                    prev_props["dedup_count"] = int(prev_props.get("dedup_count", 1)) + 1
        straight_features = list(straight_dedup.values())

    if chain_features:
        chain_dedup: dict[tuple[int, int, tuple[str, ...]], dict[str, Any]] = {}
        for feat in chain_features:
            props = feat.get("properties") if isinstance(feat, dict) else None
            if not isinstance(props, dict):
                continue
            src_raw = props.get("src_nodeid")
            dst_raw = props.get("dst_nodeid")
            edge_ids_raw = props.get("edge_ids")
            if src_raw is None or dst_raw is None:
                continue
            try:
                src_i = int(src_raw)
                dst_i = int(dst_raw)
            except Exception:
                continue
            edge_sig = tuple(str(v) for v in (edge_ids_raw or []))
            key = (src_i, dst_i, edge_sig)
            if key not in chain_dedup:
                chain_dedup[key] = dict(feat)
        chain_features = list(chain_dedup.values())

    stats = {
        "src_count": int(len(cross_nodes)),
        "accepted_src_count": int(accepted_src_nodes),
        "unresolved_src_count": int(unresolved_src_nodes),
        "multi_dst_src_count": int(multi_dst_src_nodes),
        "multi_chain_src_count": int(multi_chain_src_nodes),
        "search_overflow_src_count": int(overflow_src_nodes),
        "src_anchor_count": int(len(anchors_out) + len(anchors_in)),
        "src_anchor_out_count": int(len(anchors_out)),
        "src_anchor_in_count": int(len(anchors_in)),
        "accepted_anchor_count": int(accepted_anchor_count),
        "unresolved_anchor_count": int(unresolved_anchor_count),
        "multi_dst_anchor_count": int(multi_dst_anchor_count),
        "multi_chain_anchor_count": int(multi_chain_anchor_count),
        "search_overflow_anchor_count": int(overflow_anchor_count),
        "shared_group_sibling_filtered_anchor_count": int(shared_group_sibling_filtered_anchor_count),
        "accepted_pair_count": int(len(allowed_pairs)),
    }
    return (
        allowed_dst_by_src,
        allowed_pairs,
        node_decisions,
        anchor_decisions,
        stats,
        straight_features,
        chain_features,
    )


def _collect_same_dst_multi_chain_pairs(
    anchor_decisions: dict[str, dict[str, Any]],
    *,
    accepted_pairs: set[tuple[int, int]],
) -> dict[tuple[int, int], dict[str, Any]]:
    pair_chain_sigs: dict[tuple[int, int], set[tuple[str, ...]]] = {}
    for anchor in anchor_decisions.values():
        if not isinstance(anchor, dict):
            continue
        if str(anchor.get("status") or "") != "accepted":
            continue
        if str(anchor.get("search_direction") or "forward") != "forward":
            continue
        pair_src_val = anchor.get("pair_src_nodeid")
        pair_dst_val = anchor.get("pair_dst_nodeid")
        raw_dst_val = anchor.get("chosen_dst_nodeid")
        if pair_src_val is None or pair_dst_val is None:
            continue
        src_i = int(pair_src_val)
        dst_i = int(pair_dst_val)
        pair_key = (int(src_i), int(dst_i))
        if pair_key not in accepted_pairs:
            continue
        dst_paths_map = anchor.get("dst_paths")
        dst_paths = []
        if isinstance(dst_paths_map, dict):
            if raw_dst_val is not None:
                dst_paths = dst_paths_map.get(str(int(raw_dst_val)), []) or []
            if not dst_paths:
                for _k, _vals in dst_paths_map.items():
                    if isinstance(_vals, list) and _vals:
                        dst_paths = _vals
                        break
        if dst_paths and isinstance(dst_paths[0], dict):
            edge_ids = [str(v) for v in (dst_paths[0].get("edge_ids") or []) if str(v)]
            if edge_ids:
                sig = tuple(edge_ids)
            else:
                sig = tuple(str(v) for v in (dst_paths[0].get("node_path") or []))
        else:
            start_edge = str(anchor.get("start_edge_id") or "")
            sig = (start_edge,) if start_edge else (f"{int(src_i)}->{int(dst_i)}",)
        pair_chain_sigs.setdefault(pair_key, set()).add(tuple(sig))

    out: dict[tuple[int, int], dict[str, Any]] = {}
    for (src_i, dst_i), sigs in sorted(pair_chain_sigs.items(), key=lambda it: (int(it[0][0]), int(it[0][1]))):
        if int(len(sigs)) <= 1:
            continue
        out[(int(src_i), int(dst_i))] = {
            "src_nodeid": int(src_i),
            "dst_nodeid": int(dst_i),
            "chain_count": int(len(sigs)),
            "hint": f"dst={int(dst_i)};chain_count={int(len(sigs))};same_pair_multi_road_candidate=true",
            "signatures": [list(sig)[:20] for sig in sorted(sigs)],
        }
    return out


def _same_pair_multichain_signature(anchor: dict[str, Any]) -> tuple[str, ...]:
    dst_paths_map = anchor.get("dst_paths")
    raw_dst_val = anchor.get("chosen_dst_nodeid")
    dst_paths = []
    if isinstance(dst_paths_map, dict):
        if raw_dst_val is not None:
            dst_paths = dst_paths_map.get(str(int(raw_dst_val)), []) or []
        if not dst_paths:
            for _k, _vals in dst_paths_map.items():
                if isinstance(_vals, list) and _vals:
                    dst_paths = _vals
                    break
    if dst_paths and isinstance(dst_paths[0], dict):
        edge_ids = [str(v) for v in (dst_paths[0].get("edge_ids") or []) if str(v)]
        if edge_ids:
            return tuple(edge_ids)
        node_path = [str(v) for v in (dst_paths[0].get("node_path") or []) if str(v)]
        if node_path:
            return tuple(node_path)
    start_edge = str(anchor.get("start_edge_id") or "")
    if start_edge:
        return (start_edge,)
    pair_src = anchor.get("pair_src_nodeid")
    pair_dst = anchor.get("pair_dst_nodeid")
    if pair_src is not None and pair_dst is not None:
        return (f"{int(pair_src)}->{int(pair_dst)}",)
    return tuple()


def _line_from_edge_signature(
    signature: Sequence[str],
    *,
    edge_geometry_by_id: dict[str, LineString],
) -> LineString | None:
    seq = [str(v) for v in signature if str(v)]
    if not seq:
        return None
    lines: list[LineString] = []
    for edge_id in seq:
        geom = edge_geometry_by_id.get(str(edge_id))
        if isinstance(geom, LineString) and (not geom.is_empty) and len(geom.coords) >= 2:
            lines.append(geom)
    if not lines:
        return None
    merged = _concat_line_sequence(lines)
    if isinstance(merged, LineString) and (not merged.is_empty) and len(merged.coords) >= 2:
        return merged
    return None


def _line_xsec_station(
    line: LineString | None,
    *,
    xsec: LineString,
) -> float:
    if not isinstance(line, LineString) or line.is_empty or not isinstance(xsec, LineString) or xsec.is_empty:
        return float("inf")
    try:
        _line_pt, xsec_pt = nearest_points(line, xsec)
        if not isinstance(xsec_pt, Point) or xsec_pt.is_empty:
            return float("inf")
        return float(xsec.project(xsec_pt))
    except Exception:
        return float("inf")


def _point_xsec_station(
    point: Point | None,
    *,
    xsec: LineString,
) -> float:
    if not isinstance(point, Point) or point.is_empty or not isinstance(xsec, LineString) or xsec.is_empty:
        return float("inf")
    try:
        return float(xsec.project(point))
    except Exception:
        return float("inf")


def _build_same_pair_multichain_branch_defs(
    anchor_decisions: dict[str, dict[str, Any]],
    *,
    pair: tuple[int, int],
    src_xsec: LineString,
    dst_xsec: LineString,
    edge_geometry_by_id: dict[str, LineString],
) -> list[dict[str, Any]]:
    src_i, dst_i = int(pair[0]), int(pair[1])
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for anchor_id, anchor in sorted(anchor_decisions.items(), key=lambda it: str(it[0])):
        if not isinstance(anchor, dict):
            continue
        if str(anchor.get("status") or "") != "accepted":
            continue
        if str(anchor.get("search_direction") or "forward") != "forward":
            continue
        pair_src = anchor.get("pair_src_nodeid")
        pair_dst = anchor.get("pair_dst_nodeid")
        if pair_src is None or pair_dst is None:
            continue
        if int(pair_src) != int(src_i) or int(pair_dst) != int(dst_i):
            continue
        signature = _same_pair_multichain_signature(anchor)
        if not signature or signature in seen:
            continue
        shape_ref_metric = _line_from_edge_signature(signature, edge_geometry_by_id=edge_geometry_by_id)
        if not isinstance(shape_ref_metric, LineString):
            continue
        seen.add(signature)
        out.append(
            {
                "anchor_id": str(anchor_id),
                "signature": [str(v) for v in signature],
                "shape_ref_metric": shape_ref_metric,
                "src_station_m": _line_xsec_station(shape_ref_metric, xsec=src_xsec),
                "dst_station_m": _line_xsec_station(shape_ref_metric, xsec=dst_xsec),
            }
        )
    out.sort(
        key=lambda item: (
            _to_finite_float(item.get("src_station_m"), float("inf")),
            _to_finite_float(item.get("dst_station_m"), float("inf")),
            str(item.get("anchor_id") or ""),
        )
    )
    for branch_rank, branch in enumerate(out, start=1):
        branch["branch_rank"] = int(branch_rank)
        branch["branch_id"] = f"{int(src_i)}_{int(dst_i)}__b{int(branch_rank - 1)}"
    return out


def _support_item_distance_to_branch(
    *,
    seg: LineString | None,
    src_pt: Point,
    dst_pt: Point,
    branch_ref: LineString,
    src_xsec: LineString | None = None,
    dst_xsec: LineString | None = None,
    branch_src_station_m: float | None = None,
    branch_dst_station_m: float | None = None,
) -> float:
    try:
        if isinstance(seg, LineString) and (not seg.is_empty) and float(seg.length) > 1e-6:
            mid = seg.interpolate(0.5, normalized=True)
        else:
            mid = Point(
                0.5 * (float(src_pt.x) + float(dst_pt.x)),
                0.5 * (float(src_pt.y) + float(dst_pt.y)),
            )
        d_mid = float(mid.distance(branch_ref))
        d_src = float(src_pt.distance(branch_ref))
        d_dst = float(dst_pt.distance(branch_ref))
        score = float(d_mid + 0.25 * (d_src + d_dst))
        if isinstance(src_xsec, LineString) and not src_xsec.is_empty:
            src_station = _point_xsec_station(src_pt, xsec=src_xsec)
            branch_src_station = _to_finite_float(branch_src_station_m, float("inf"))
            if np.isfinite(src_station) and np.isfinite(branch_src_station):
                score += 0.75 * abs(float(src_station) - float(branch_src_station))
        if isinstance(dst_xsec, LineString) and not dst_xsec.is_empty:
            dst_station = _point_xsec_station(dst_pt, xsec=dst_xsec)
            branch_dst_station = _to_finite_float(branch_dst_station_m, float("inf"))
            if np.isfinite(dst_station) and np.isfinite(branch_dst_station):
                score += 0.75 * abs(float(dst_station) - float(branch_dst_station))
        return float(score)
    except Exception:
        return float("inf")


def _subset_support_by_indices(
    support: PairSupport,
    indices: Sequence[int],
    *,
    hard_anomalies: set[str] | None = None,
) -> PairSupport | None:
    idx = [int(i) for i in indices if 0 <= int(i) < int(support.support_event_count)]
    if not idx:
        return None

    out = PairSupport(
        src_nodeid=int(support.src_nodeid),
        dst_nodeid=int(support.dst_nodeid),
        open_end=False,
        hard_anomalies=set(hard_anomalies if hard_anomalies is not None else support.hard_anomalies),
    )
    out.cluster_count = 1
    out.main_cluster_id = 0
    out.main_cluster_ratio = 1.0
    out.cluster_sep_m_est = None
    out.cluster_sizes = [int(len(idx))]
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
        out.evidence_cluster_ids.append(0)
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


def _build_same_pair_multichain_branch_supports(
    support: PairSupport,
    *,
    branch_defs: Sequence[dict[str, Any]],
    src_xsec: LineString,
    dst_xsec: LineString,
) -> list[tuple[dict[str, Any], PairSupport]]:
    if not branch_defs:
        return []
    assignments: list[list[int]] = [[] for _ in range(len(branch_defs))]
    for idx in range(int(support.support_event_count)):
        seg = support.traj_segments[idx] if idx < len(support.traj_segments) else None
        src_pt = support.src_cross_points[idx] if idx < len(support.src_cross_points) else Point(0.0, 0.0)
        dst_pt = support.dst_cross_points[idx] if idx < len(support.dst_cross_points) else Point(0.0, 0.0)
        best_branch = None
        best_score = float("inf")
        for branch_idx, branch in enumerate(branch_defs):
            ref_line = branch.get("shape_ref_metric")
            if not isinstance(ref_line, LineString) or ref_line.is_empty:
                continue
            score = _support_item_distance_to_branch(
                seg=seg if isinstance(seg, LineString) else None,
                src_pt=src_pt,
                dst_pt=dst_pt,
                branch_ref=ref_line,
                src_xsec=src_xsec,
                dst_xsec=dst_xsec,
                branch_src_station_m=branch.get("src_station_m"),
                branch_dst_station_m=branch.get("dst_station_m"),
            )
            if score < best_score:
                best_score = score
                best_branch = int(branch_idx)
        if best_branch is not None:
            assignments[int(best_branch)].append(int(idx))

    out: list[tuple[dict[str, Any], PairSupport]] = []
    branch_hard_anomalies = {str(v) for v in support.hard_anomalies if str(v) != HARD_MULTI_ROAD}
    for branch_idx, branch in enumerate(branch_defs):
        subset = _subset_support_by_indices(
            support,
            assignments[int(branch_idx)],
            hard_anomalies=set(branch_hard_anomalies),
        )
        if subset is None or int(subset.support_event_count) <= 0:
            continue
        out.append((dict(branch), subset))
    return out


def _build_same_pair_multichain_fallback_support(
    parent_support: PairSupport,
    *,
    branch_def: dict[str, Any],
    src_xsec: LineString,
    dst_xsec: LineString,
    drivezone_zone_metric: BaseGeometry | None,
    gore_zone_metric: BaseGeometry | None = None,
    src_type: str | None = None,
    dst_type: str | None = None,
    params: dict[str, Any],
) -> PairSupport | None:
    branch_shape_ref = branch_def.get("shape_ref_metric")
    if not isinstance(branch_shape_ref, LineString) or branch_shape_ref.is_empty or float(branch_shape_ref.length) <= 1e-6:
        return None
    shape_ref_line, src_entry_xsec, dst_entry_xsec = _resolve_fallback_support_entry_xsecs(
        shape_ref_metric=branch_shape_ref,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=drivezone_zone_metric,
        gore_zone_metric=gore_zone_metric,
        src_type=src_type,
        dst_type=dst_type,
        params=params,
    )
    src_contact = _line_xsec_contact_point(line=shape_ref_line, xsec=src_entry_xsec)
    dst_contact = _line_xsec_contact_point(line=shape_ref_line, xsec=dst_entry_xsec)
    if not isinstance(src_contact, Point) or src_contact.is_empty:
        return None
    if not isinstance(dst_contact, Point) or dst_contact.is_empty:
        return None

    reach_xsec_m = float(
        max(
            1.0,
            params.get(
                "SAME_PAIR_FALLBACK_REACH_XSEC_M",
                params.get("STEP1_CORRIDOR_REACH_XSEC_M", 12.0),
            ),
        )
    )
    try:
        src_gap_m = float(shape_ref_line.distance(src_entry_xsec))
    except Exception:
        src_gap_m = float("inf")
    try:
        dst_gap_m = float(shape_ref_line.distance(dst_entry_xsec))
    except Exception:
        dst_gap_m = float("inf")
    if src_gap_m > reach_xsec_m + 1e-6 or dst_gap_m > reach_xsec_m + 1e-6:
        return None

    if drivezone_zone_metric is not None and (not drivezone_zone_metric.is_empty):
        inside_ratio = _line_inside_ratio(shape_ref_line, drivezone_zone_metric)
        inside_min = float(
            max(0.0, min(1.0, params.get("STEP1_TRAJ_IN_DRIVEZONE_FALLBACK_MIN", 0.60)))
        )
        if inside_ratio is None or float(inside_ratio) + 1e-9 < inside_min:
            return None

    branch_hard_anomalies = {str(v) for v in parent_support.hard_anomalies if str(v) != HARD_MULTI_ROAD}
    out = PairSupport(
        src_nodeid=int(parent_support.src_nodeid),
        dst_nodeid=int(parent_support.dst_nodeid),
        open_end=False,
        hard_anomalies=set(branch_hard_anomalies),
    )
    out.support_event_count = 0
    out.src_cross_points = [src_contact]
    out.dst_cross_points = [dst_contact]
    out.hints = [str(v) for v in list(parent_support.hints)] + ["same_pair_branch_road_prior_fallback"]
    out.cluster_count = 1
    out.main_cluster_id = 0
    out.main_cluster_ratio = 0.0
    out.cluster_sep_m_est = None
    out.cluster_sizes = []
    out.unresolved_neighbor_count = int(parent_support.unresolved_neighbor_count)
    return out


def _build_topology_road_prior_fallback_support(
    *,
    pair: tuple[int, int],
    shape_ref_metric: LineString | None,
    src_xsec: LineString,
    dst_xsec: LineString,
    drivezone_zone_metric: BaseGeometry | None,
    gore_zone_metric: BaseGeometry | None = None,
    src_type: str | None = None,
    dst_type: str | None = None,
    params: dict[str, Any],
    debug_out: dict[str, Any] | None = None,
) -> PairSupport | None:
    if debug_out is not None:
        debug_out.clear()
        debug_out["attempted"] = True
        debug_out["failure_stage"] = "shape_ref_invalid"
        debug_out["src_contact_found"] = False
        debug_out["dst_contact_found"] = False
        debug_out["src_gap_m"] = None
        debug_out["dst_gap_m"] = None
        debug_out["reach_xsec_m"] = None
        debug_out["inside_ratio"] = None
        debug_out["inside_ratio_min"] = None
    if not isinstance(shape_ref_metric, LineString) or shape_ref_metric.is_empty or float(shape_ref_metric.length) <= 1e-6:
        return None
    shape_ref_line, src_entry_xsec, dst_entry_xsec = _resolve_fallback_support_entry_xsecs(
        shape_ref_metric=shape_ref_metric,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        drivezone_zone_metric=drivezone_zone_metric,
        gore_zone_metric=gore_zone_metric,
        src_type=src_type,
        dst_type=dst_type,
        params=params,
    )
    src_contact = _line_xsec_contact_point(line=shape_ref_line, xsec=src_entry_xsec)
    if debug_out is not None:
        debug_out["src_contact_found"] = bool(isinstance(src_contact, Point) and (not src_contact.is_empty))
    dst_contact = _line_xsec_contact_point(line=shape_ref_line, xsec=dst_entry_xsec)
    if debug_out is not None:
        debug_out["dst_contact_found"] = bool(isinstance(dst_contact, Point) and (not dst_contact.is_empty))
    if not isinstance(src_contact, Point) or src_contact.is_empty:
        if debug_out is not None:
            debug_out["failure_stage"] = "src_xsec_contact"
        return None
    if not isinstance(dst_contact, Point) or dst_contact.is_empty:
        if debug_out is not None:
            debug_out["failure_stage"] = "dst_xsec_contact"
        return None

    reach_xsec_m = float(
        max(
            1.0,
            params.get(
                "TOPOLOGY_FALLBACK_REACH_XSEC_M",
                params.get("SAME_PAIR_FALLBACK_REACH_XSEC_M", params.get("STEP1_CORRIDOR_REACH_XSEC_M", 12.0)),
            ),
        )
    )
    try:
        src_gap_m = float(shape_ref_line.distance(src_entry_xsec))
    except Exception:
        src_gap_m = float("inf")
    try:
        dst_gap_m = float(shape_ref_line.distance(dst_entry_xsec))
    except Exception:
        dst_gap_m = float("inf")
    if debug_out is not None:
        debug_out["reach_xsec_m"] = float(reach_xsec_m)
        debug_out["src_gap_m"] = float(src_gap_m) if np.isfinite(src_gap_m) else None
        debug_out["dst_gap_m"] = float(dst_gap_m) if np.isfinite(dst_gap_m) else None
    if src_gap_m > reach_xsec_m + 1e-6 or dst_gap_m > reach_xsec_m + 1e-6:
        if debug_out is not None:
            debug_out["failure_stage"] = "reach_xsec"
        return None

    if drivezone_zone_metric is not None and (not drivezone_zone_metric.is_empty):
        inside_ratio = _line_inside_ratio(shape_ref_line, drivezone_zone_metric)
        inside_min = float(
            max(0.0, min(1.0, params.get("STEP1_TRAJ_IN_DRIVEZONE_FALLBACK_MIN", 0.60)))
        )
        if debug_out is not None:
            debug_out["inside_ratio"] = float(inside_ratio) if inside_ratio is not None else None
            debug_out["inside_ratio_min"] = float(inside_min)
        if inside_ratio is None or float(inside_ratio) + 1e-9 < inside_min:
            if debug_out is not None:
                debug_out["failure_stage"] = "drivezone_inside_ratio"
            return None

    src_i, dst_i = int(pair[0]), int(pair[1])
    out = PairSupport(
        src_nodeid=int(src_i),
        dst_nodeid=int(dst_i),
        open_end=False,
        hard_anomalies=set(),
    )
    out.support_event_count = 0
    out.src_cross_points = [src_contact]
    out.dst_cross_points = [dst_contact]
    out.hints = ["topology_road_prior_fallback"]
    out.cluster_count = 1
    out.main_cluster_id = 0
    out.main_cluster_ratio = 0.0
    out.cluster_sep_m_est = None
    out.cluster_sizes = []
    out.unresolved_neighbor_count = 0
    if debug_out is not None:
        debug_out["failure_stage"] = "accepted"
    return out


def _resolve_fallback_support_entry_xsecs(
    *,
    shape_ref_metric: LineString,
    src_xsec: LineString,
    dst_xsec: LineString,
    drivezone_zone_metric: BaseGeometry | None,
    gore_zone_metric: BaseGeometry | None,
    src_type: str | None,
    dst_type: str | None,
    params: dict[str, Any],
) -> tuple[LineString, LineString, LineString]:
    shape_ref_line = _orient_axis_line(shape_ref_metric, src_xsec=src_xsec, dst_xsec=dst_xsec)

    def _entry_xsec(*, xsec_seed: LineString, endpoint_tag: str, node_type: str | None) -> LineString:
        payload = build_pair_endpoint_xsec(
            xsec_seed=xsec_seed,
            shape_ref_line=shape_ref_line,
            traj_segments=(),
            drivezone_zone_metric=drivezone_zone_metric,
            gore_zone_metric=gore_zone_metric,
            ref_half_len_m=float(params.get("XSEC_REF_HALF_LEN_M", 80.0)),
            sample_step_m=float(params.get("XSEC_ROAD_SAMPLE_STEP_M", 1.0)),
            nonpass_k=int(params.get("XSEC_ROAD_NONPASS_K", 6)),
            evidence_radius_m=float(params.get("XSEC_ROAD_EVIDENCE_RADIUS_M", 1.0)),
            min_ground_pts=int(params.get("XSEC_ROAD_MIN_GROUND_PTS", 1)),
            min_traj_pts=int(params.get("XSEC_ROAD_MIN_TRAJ_PTS", 1)),
            core_band_m=float(params.get("XSEC_CORE_BAND_M", 20.0)),
            shift_step_m=float(params.get("XSEC_SHIFT_STEP_M", 5.0)),
            fallback_short_half_len_m=float(params.get("XSEC_FALLBACK_SHORT_HALF_LEN_M", 15.0)),
            barrier_min_ng_count=int(params.get("XSEC_BARRIER_MIN_NG_COUNT", 2)),
            barrier_min_len_m=float(params.get("XSEC_BARRIER_MIN_LEN_M", 4.0)),
            barrier_along_len_m=float(params.get("XSEC_BARRIER_ALONG_LEN_M", 60.0)),
            barrier_along_width_m=float(params.get("XSEC_BARRIER_ALONG_WIDTH_M", 2.5)),
            barrier_bin_step_m=float(params.get("XSEC_BARRIER_BIN_STEP_M", 2.0)),
            barrier_occ_ratio_min=float(params.get("XSEC_BARRIER_OCC_RATIO_MIN", 0.65)),
            endcap_window_m=float(params.get("XSEC_ENDCAP_WINDOW_M", 60.0)),
            caseb_pre_m=float(params.get("XSEC_CASEB_PRE_M", 3.0)),
            endpoint_tag=endpoint_tag,
            node_type=node_type,
            ground_xy=np.empty((0, 2), dtype=np.float64),
            non_ground_xy=np.empty((0, 2), dtype=np.float64),
        )
        cross_ref = payload.get("xsec_cross_ref")
        if isinstance(cross_ref, LineString) and (not cross_ref.is_empty) and len(cross_ref.coords) >= 2:
            return cross_ref
        return xsec_seed

    src_entry_xsec = _entry_xsec(xsec_seed=src_xsec, endpoint_tag="src", node_type=src_type)
    dst_entry_xsec = _entry_xsec(xsec_seed=dst_xsec, endpoint_tag="dst", node_type=dst_type)
    return shape_ref_line, src_entry_xsec, dst_entry_xsec


def _build_same_pair_multichain_variants(
    *,
    pair: tuple[int, int],
    support: PairSupport,
    src_type: str,
    dst_type: str,
    src_xsec: LineString,
    dst_xsec: LineString,
    drivezone_zone_metric: BaseGeometry | None,
    gore_zone_metric: BaseGeometry | None,
    params: dict[str, Any],
    anchor_decisions: dict[str, dict[str, Any]],
    edge_geometry_by_id: dict[str, LineString],
) -> list[dict[str, Any]]:
    branch_defs = _build_same_pair_multichain_branch_defs(
        anchor_decisions,
        pair=pair,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
        edge_geometry_by_id=edge_geometry_by_id,
    )
    if int(len(branch_defs)) <= 1:
        return []
    branch_supports = _build_same_pair_multichain_branch_supports(
        support,
        branch_defs=branch_defs,
        src_xsec=src_xsec,
        dst_xsec=dst_xsec,
    )
    branch_support_by_id = {
        str(branch.get("branch_id") or f"{int(pair[0])}_{int(pair[1])}__b{int(idx)}"): subset
        for idx, (branch, subset) in enumerate(branch_supports)
    }
    out: list[dict[str, Any]] = []
    for branch_rank, branch_def in enumerate(branch_defs):
        branch_id = str(branch_def.get("branch_id") or f"{int(pair[0])}_{int(pair[1])}__b{int(branch_rank)}")
        branch_support = branch_support_by_id.get(branch_id)
        support_mode = "traj_support"
        support_fallback_reason: str | None = None
        if branch_support is None:
            branch_support = _build_same_pair_multichain_fallback_support(
                support,
                branch_def=branch_def,
                src_xsec=src_xsec,
                dst_xsec=dst_xsec,
                drivezone_zone_metric=drivezone_zone_metric,
                gore_zone_metric=gore_zone_metric,
                src_type=src_type,
                dst_type=dst_type,
                params=params,
            )
            if branch_support is None:
                continue
            support_mode = "road_prior_fallback"
            support_fallback_reason = "missing_branch_traj_support"
        branch_shape_ref = branch_def.get("shape_ref_metric")
        if not isinstance(branch_shape_ref, LineString) or branch_shape_ref.is_empty:
            continue
        step1_corridor = _build_step1_corridor_for_pair(
            support=branch_support,
            src_type=src_type,
            dst_type=dst_type,
            src_xsec=src_xsec,
            dst_xsec=dst_xsec,
            drivezone_zone_metric=drivezone_zone_metric,
            gore_zone_metric=gore_zone_metric,
            params=params,
            road_prior_shape_ref_metric=branch_shape_ref,
        )
        out.append(
            {
                "branch_id": branch_id,
                "cluster_id": int(branch_rank),
                "branch_rank": int(branch_def.get("branch_rank", branch_rank + 1)),
                "signature": [str(v) for v in (branch_def.get("signature") or [])],
                "src_station_m": branch_def.get("src_station_m"),
                "dst_station_m": branch_def.get("dst_station_m"),
                "support": branch_support,
                "support_mode": str(support_mode),
                "support_fallback_reason": (str(support_fallback_reason) if support_fallback_reason else None),
                "support_traj_count": int(len(branch_support.support_traj_ids)),
                "road_prior_shape_ref_metric": branch_shape_ref,
                "step1_corridor": step1_corridor,
            }
        )
    if int(len(out)) <= 1:
        return []
    return out


def _should_enable_road_prior_gap_fill(
    *,
    road_prior_shape_ref_valid: bool,
    traj_surface_enforced: bool,
    step1_used_road_prior: bool,
    step1_road_prior_mode: str | None,
    same_pair_multichain: bool,
    support_mode: str | None = None,
) -> bool:
    if not bool(road_prior_shape_ref_valid):
        return False
    if bool(traj_surface_enforced):
        return False
    support_mode_norm = str(support_mode or "").strip().lower()
    if bool(same_pair_multichain) and support_mode_norm == "road_prior_fallback":
        return True
    if not bool(step1_used_road_prior):
        return False
    if str(step1_road_prior_mode or "").strip().lower() != "step1_no_traj":
        return False
    return True


def _cross_section_midpoint(xsec: CrossSection | None) -> Point | None:
    if xsec is None:
        return None
    geom = getattr(xsec, "geometry_metric", None)
    if not isinstance(geom, LineString) or geom.is_empty or geom.length <= 0:
        return None
    pt = geom.interpolate(0.5, normalized=True)
    if not isinstance(pt, Point) or pt.is_empty:
        return None
    return pt


def _build_topology_unique_decisions(
    compressed_adj: dict[int, list[dict[str, Any]]],
    *,
    cross_nodes: set[int],
    xsec_map: dict[int, Any],
    require_unique_chain: bool,
    max_expansions: int,
) -> tuple[dict[int, set[int]], dict[int, dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    allowed_dst_by_src: dict[int, set[int]] = {}
    decisions: dict[int, dict[str, Any]] = {}
    straight_features: list[dict[str, Any]] = []
    chain_features: list[dict[str, Any]] = []

    accepted_count = 0
    unresolved_count = 0
    multi_dst_count = 0
    multi_chain_count = 0
    overflow_count = 0

    for src in sorted(int(v) for v in cross_nodes):
        search = _search_topology_next_xsecs(
            compressed_adj,
            src_nodeid=int(src),
            cross_nodes=cross_nodes,
            max_expansions=int(max(100, max_expansions)),
        )
        dst_nodeids = [int(v) for v in search.get("dst_nodeids", [])]
        dst_paths = {
            int(k): list(v)
            for k, v in dict(search.get("dst_paths", {})).items()
        }
        if bool(search.get("overflow", False)):
            overflow_count += 1

        status = "unresolved"
        reason = SOFT_UNRESOLVED_NEIGHBOR
        chosen_dst: int | None = None
        chain_count = 0
        if len(dst_nodeids) == 0:
            unresolved_count += 1
        elif len(dst_nodeids) >= 2:
            status = "multi_dst"
            reason = HARD_MULTI_NEIGHBOR_FOR_NODE
            multi_dst_count += 1
        else:
            chosen_dst = int(dst_nodeids[0])
            chain_count = int(len(dst_paths.get(int(chosen_dst), [])))
            if bool(require_unique_chain) and chain_count >= 2:
                status = "multi_chain"
                reason = _HARD_MULTI_CHAIN_SAME_DST
                multi_chain_count += 1
            else:
                status = "accepted"
                reason = "accepted"
                accepted_count += 1
                allowed_dst_by_src[int(src)] = {int(chosen_dst)}

        src_mid = _cross_section_midpoint(xsec_map.get(int(src)))
        line_targets: list[int] = []
        if status == "accepted" and chosen_dst is not None:
            line_targets = [int(chosen_dst)]
        elif status == "multi_chain" and chosen_dst is not None:
            line_targets = [int(chosen_dst)]
        elif status == "multi_dst":
            line_targets = [int(v) for v in dst_nodeids]

        for dst in line_targets:
            dst_mid = _cross_section_midpoint(xsec_map.get(int(dst)))
            if src_mid is None or dst_mid is None:
                continue
            line = LineString([(float(src_mid.x), float(src_mid.y)), (float(dst_mid.x), float(dst_mid.y))])
            if line.is_empty or line.length <= 0:
                continue
            straight_features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(line),
                    "properties": {
                        "src_nodeid": int(src),
                        "dst_nodeid": int(dst),
                        "status": str(status),
                        "reason": str(reason),
                        "dst_count": int(len(dst_nodeids)),
                        "chain_count": int(chain_count if dst == chosen_dst else len(dst_paths.get(int(dst), []))),
                        "search_overflow": bool(search.get("overflow", False)),
                        "expansions": int(search.get("expansions", 0)),
                    },
                }
            )
            for path_idx, rec in enumerate(dst_paths.get(int(dst), [])[:5], start=1):
                chain_features.append(
                    {
                        "type": "Feature",
                        "geometry": mapping(line),
                        "properties": {
                            "src_nodeid": int(src),
                            "dst_nodeid": int(dst),
                            "status": str(status),
                            "reason": str(reason),
                            "path_idx": int(path_idx),
                            "path_node_count": int(len(rec.get("node_path", []))),
                            "chain_len": int(rec.get("chain_len", 0)),
                            "edge_ids": [str(v) for v in rec.get("edge_ids", [])[:20]],
                        },
                    }
                )

        decisions[int(src)] = {
            "src_nodeid": int(src),
            "status": str(status),
            "reason": str(reason),
            "dst_nodeids": [int(v) for v in dst_nodeids],
            "chosen_dst_nodeid": int(chosen_dst) if chosen_dst is not None else None,
            "chain_count": int(chain_count),
            "expansions": int(search.get("expansions", 0)),
            "search_overflow": bool(search.get("overflow", False)),
            "dst_paths": {
                str(int(dst)): [
                    {
                        "node_path": [int(v) for v in rec.get("node_path", [])],
                        "edge_ids": [str(v) for v in rec.get("edge_ids", [])[:50]],
                        "chain_len": int(rec.get("chain_len", 0)),
                    }
                    for rec in recs[:10]
                ]
                for dst, recs in sorted(dst_paths.items(), key=lambda it: int(it[0]))
            },
        }

    stats = {
        "src_count": int(len(cross_nodes)),
        "accepted_src_count": int(accepted_count),
        "unresolved_src_count": int(unresolved_count),
        "multi_dst_src_count": int(multi_dst_count),
        "multi_chain_src_count": int(multi_chain_count),
        "search_overflow_src_count": int(overflow_count),
    }
    return allowed_dst_by_src, decisions, stats, straight_features, chain_features


def _build_cross_section_map(patch_inputs: PatchInputs) -> dict[int, Any]:
    out: dict[int, Any] = {}
    for cs in patch_inputs.intersection_lines:
        if cs.nodeid in out:
            if cs.geometry_metric.length > out[cs.nodeid].geometry_metric.length:
                out[cs.nodeid] = cs
        else:
            out[cs.nodeid] = cs
    return out


def _safe_int_list(value: Any) -> list[int]:
    if value is None:
        return []
    items = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = [part.strip() for part in text.split(",") if part.strip()]
        items = parsed
    if not isinstance(items, (list, tuple)):
        items = [items]
    out: list[int] = []
    for item in items:
        try:
            if isinstance(item, bool):
                continue
            iv = int(np.int64(item))
        except Exception:
            continue
        if iv not in out:
            out.append(iv)
    return out


def _safe_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    items = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = [part.strip() for part in text.split(",") if part.strip()]
        items = parsed
    if not isinstance(items, (list, tuple)):
        items = [items]
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _shared_intersection_member_nodeids(cs: CrossSection) -> list[int]:
    props = getattr(cs, "properties", {}) or {}
    members = _safe_int_list(props.get("nodeids"))
    if int(cs.nodeid) not in members:
        members = [int(cs.nodeid), *members]
    out: list[int] = []
    for nodeid in members:
        nodeid_i = int(nodeid)
        if nodeid_i not in out:
            out.append(nodeid_i)
    return out


def _build_shared_intersection_alias_maps(
    patch_inputs: PatchInputs,
) -> tuple[dict[int, int], dict[int, str], dict[int, str], dict[int, int], dict[int, int]]:
    primary_by_nodeid: dict[int, int] = {}
    group_by_nodeid: dict[int, str] = {}
    role_by_nodeid: dict[int, str] = {}
    src_alias_by_primary: dict[int, int] = {}
    dst_alias_by_primary: dict[int, int] = {}
    for cs in patch_inputs.intersection_lines:
        props = getattr(cs, "properties", {}) or {}
        primary = int(cs.nodeid)
        members = _shared_intersection_member_nodeids(cs)
        if not members:
            members = [int(primary)]
        for nodeid in members:
            primary_by_nodeid[int(nodeid)] = int(primary)
        if len(members) <= 1:
            src_alias_by_primary[int(primary)] = int(primary)
            dst_alias_by_primary[int(primary)] = int(primary)
            continue
        group_id_raw = str(props.get("merged_group_id") or "").strip()
        group_id = group_id_raw or ("shared_xsec:" + "|".join(str(v) for v in sorted(members)))
        roles = _safe_str_list(props.get("roles"))
        src_alias = int(primary)
        dst_alias = int(primary)
        for idx, nodeid in enumerate(members):
            group_by_nodeid[int(nodeid)] = str(group_id)
            if idx < len(roles):
                role_text = str(roles[idx]).strip().lower()
                if role_text:
                    role_by_nodeid[int(nodeid)] = str(role_text)
                if role_text == "diverge" and int(src_alias) == int(primary):
                    src_alias = int(nodeid)
                if role_text == "merge" and int(dst_alias) == int(primary):
                    dst_alias = int(nodeid)
        src_alias_by_primary[int(primary)] = int(src_alias)
        dst_alias_by_primary[int(primary)] = int(dst_alias)
    for cs in patch_inputs.intersection_lines:
        primary = int(cs.nodeid)
        primary_by_nodeid.setdefault(int(primary), int(primary))
        src_alias_by_primary.setdefault(int(primary), int(primary))
        dst_alias_by_primary.setdefault(int(primary), int(primary))
    return (
        primary_by_nodeid,
        group_by_nodeid,
        role_by_nodeid,
        src_alias_by_primary,
        dst_alias_by_primary,
    )


def _build_shared_intersection_group_maps(patch_inputs: PatchInputs) -> tuple[dict[int, str], dict[int, str]]:
    _, group_by_nodeid, role_by_nodeid, _src_alias_by_primary, _dst_alias_by_primary = (
        _build_shared_intersection_alias_maps(patch_inputs)
    )
    return group_by_nodeid, role_by_nodeid


def _build_shared_intersection_group_members_map(
    *,
    primary_by_nodeid: dict[int, int],
    group_by_nodeid: dict[int, str],
) -> dict[int, list[int]]:
    members_by_group: dict[str, set[int]] = {}
    for nodeid, group_id in group_by_nodeid.items():
        if not str(group_id):
            continue
        members_by_group.setdefault(str(group_id), set()).add(int(nodeid))
    for nodeid, primary in primary_by_nodeid.items():
        group_id = str(group_by_nodeid.get(int(nodeid)) or "")
        if not group_id:
            continue
        members_by_group.setdefault(group_id, set()).add(int(primary))
    out: dict[int, list[int]] = {}
    for nodeid, primary in primary_by_nodeid.items():
        group_id = str(group_by_nodeid.get(int(nodeid)) or "")
        if not group_id:
            out[int(nodeid)] = [int(nodeid)]
            continue
        members = sorted(int(v) for v in members_by_group.get(group_id, set()) if v is not None)
        if not members:
            members = [int(primary)]
        out[int(nodeid)] = list(members)
    return out


def _expand_shared_intersection_alias_by_nodeid(
    *,
    primary_by_nodeid: dict[int, int],
    alias_by_primary: dict[int, int],
) -> dict[int, int]:
    out: dict[int, int] = {}
    for nodeid, primary in primary_by_nodeid.items():
        alias = int(alias_by_primary.get(int(primary), int(primary)))
        out[int(nodeid)] = int(alias)
    return out


def _expand_shared_intersection_lookup(
    base_map: dict[int, Any],
    *,
    primary_by_nodeid: dict[int, int],
) -> dict[int, Any]:
    out: dict[int, Any] = {int(k): v for k, v in base_map.items()}
    for nodeid, primary in primary_by_nodeid.items():
        if int(nodeid) in out:
            continue
        if int(primary) not in base_map:
            continue
        out[int(nodeid)] = base_map[int(primary)]
    return out


def _is_shared_intersection_internal_pair(
    *,
    src: int,
    dst: int,
    src_type: str,
    dst_type: str,
    group_by_nodeid: dict[int, str],
) -> bool:
    if str(src_type) != "diverge" or str(dst_type) != "merge":
        return False
    src_group = str(group_by_nodeid.get(int(src)) or "")
    dst_group = str(group_by_nodeid.get(int(dst)) or "")
    return bool(src_group and dst_group and src_group == dst_group)


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
    passthrough_count = 0
    repaired_count = 0
    failed_count = 0
    drivezone_ratio_values: list[float] = []
    divstrip_ratio_values: list[float] = []
    use_drivezone_gate = bool(drivezone_zone_metric is not None and (not drivezone_zone_metric.is_empty))
    divstrip_available = bool(gore_zone_metric is not None and (not gore_zone_metric.is_empty))
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
    mode_raw = str(params.get("STEP0_MODE", "off")).strip().lower()
    step0_mode = mode_raw if mode_raw in {"lite", "audit", "full", "off"} else "lite"
    step0_lite_min_in_drivezone_ratio = float(max(0.0, min(1.0, float(params.get("STEP0_LITE_MIN_IN_DRIVEZONE_RATIO", 0.90)))))
    step0_lite_max_in_divstrip_ratio = float(max(0.0, min(1.0, float(params.get("STEP0_LITE_MAX_IN_DIVSTRIP_RATIO", 0.01)))))
    step0_lite_min_len_m = float(max(0.0, float(params.get("STEP0_LITE_MIN_LEN_M", 5.0))))

    def _as_bool_param(value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return bool(value)
        if isinstance(value, (int, float)):
            return bool(int(value))
        if isinstance(value, str):
            token = value.strip().lower()
            if token in {"1", "true", "yes", "on"}:
                return True
            if token in {"0", "false", "no", "off"}:
                return False
        return bool(default)

    step0_lite_allow_passthrough_when_divstrip_missing = _as_bool_param(
        params.get("STEP0_LITE_ALLOW_PASSTHROUGH_WHEN_DIVSTRIP_MISSING", 1),
        True,
    )
    step0_stats_enable = _as_bool_param(params.get("STEP0_STATS_ENABLE", 1), True)

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

    def _to_line_2d(line: LineString) -> LineString:
        return LineString(
            [
                (float(coord[0]), float(coord[1]))
                for coord in line.coords
                if len(coord) >= 2
            ]
        )

    def _line_len(geom: BaseGeometry | None) -> float:
        if geom is None or geom.is_empty:
            return 0.0
        try:
            v = float(geom.length)
        except Exception:
            return 0.0
        return v if np.isfinite(v) and v > 0.0 else 0.0

    def _ratio(line: BaseGeometry | None, mask: BaseGeometry | None) -> float | None:
        total = _line_len(line)
        if total <= 1e-6:
            return None
        if mask is None or mask.is_empty:
            return None
        try:
            inside = float(line.intersection(mask).length)  # type: ignore[union-attr]
        except Exception:
            return None
        if not np.isfinite(inside):
            return None
        return float(max(0.0, min(1.0, inside / max(total, 1e-6))))

    def _line_ratios(line: BaseGeometry | None) -> tuple[float | None, float | None]:
        return (
            _ratio(line, drivezone_zone_metric if use_drivezone_gate else None),
            _ratio(line, gore_zone_metric if divstrip_available else None),
        )

    def _append_ratio_stats(*, drivezone_ratio: float | None, divstrip_ratio: float | None) -> None:
        if drivezone_ratio is not None and np.isfinite(float(drivezone_ratio)):
            drivezone_ratio_values.append(float(drivezone_ratio))
        if divstrip_ratio is not None and np.isfinite(float(divstrip_ratio)):
            divstrip_ratio_values.append(float(divstrip_ratio))

    def _safe_percentile(values: Sequence[float], q: float) -> float | None:
        if not values:
            return None
        arr = np.asarray([float(v) for v in values if np.isfinite(float(v))], dtype=np.float64)
        if arr.size == 0:
            return None
        return float(np.percentile(arr, float(q)))

    n_steps = int(max(1, round(lmax / step)))

    for nodeid, cs in xsec_map.items():
        geom = cs.geometry_metric
        if geom is None or geom.is_empty or geom.length <= 1e-6:
            gate_empty_count += 1
            failed_count += 1
            gate_all_map[int(nodeid)] = geom
            gate_meta_map[int(nodeid)] = {
                "len_m": 0.0,
                "geom_type": str(getattr(geom, "geom_type", "")) if geom is not None else "",
                "fallback": True,
                "mode": "failed",
                "selected_by": "seed_empty",
                "selection_source": "seed_empty",
                "in_drivezone_ratio": None,
                "in_divstrip_ratio": None,
                "failed_reason": "seed_empty",
            }
            fallback_orig += 1
            continue
        center = geom.interpolate(0.5, normalized=True)
        c_xy = point_xy_safe(center, context="xsec_trunc_anchor")
        if c_xy is None:
            gate_empty_count += 1
            failed_count += 1
            gate_all_map[int(nodeid)] = geom
            gate_meta_map[int(nodeid)] = {
                "len_m": float(_line_len(geom)),
                "geom_type": str(getattr(geom, "geom_type", "")),
                "fallback": True,
                "mode": "failed",
                "selected_by": "anchor_missing",
                "selection_source": "anchor_missing",
                "in_drivezone_ratio": None,
                "in_divstrip_ratio": None,
                "failed_reason": "anchor_missing",
            }
            fallback_orig += 1
            continue
        ax = float(c_xy[0])
        ay = float(c_xy[1])
        geom_2d = _to_line_2d(geom)
        seed_len_m = float(_line_len(geom_2d))
        seed_drive_ratio, seed_div_ratio = _line_ratios(geom_2d)

        lite_failed_reasons: list[str] = []
        if step0_mode == "lite":
            if seed_len_m < step0_lite_min_len_m:
                lite_failed_reasons.append("seed_too_short")
            if seed_drive_ratio is None or seed_drive_ratio < step0_lite_min_in_drivezone_ratio:
                lite_failed_reasons.append("drivezone_ratio_below_threshold")
            if divstrip_available:
                if seed_div_ratio is None:
                    lite_failed_reasons.append("divstrip_ratio_missing")
                elif seed_div_ratio > step0_lite_max_in_divstrip_ratio:
                    lite_failed_reasons.append("divstrip_ratio_above_threshold")
            elif not step0_lite_allow_passthrough_when_divstrip_missing:
                lite_failed_reasons.append("divstrip_missing_blocked_passthrough")

        if step0_mode == "off" or (step0_mode in {"lite", "audit"} and not lite_failed_reasons):
            gate_selected_count += 1
            passthrough_count += 1
            out[int(nodeid)] = CrossSection(
                nodeid=int(cs.nodeid),
                geometry_metric=geom_2d,
                properties=dict(cs.properties),
            )
            gate_all_map[int(nodeid)] = geom_2d
            gate_meta_map[int(nodeid)] = {
                "len_m": float(seed_len_m),
                "geom_type": str(getattr(geom_2d, "geom_type", "")),
                "fallback": False,
                "mode": "passthrough",
                "selected_by": "passthrough",
                "selection_source": "passthrough",
                "candidate_segment_count": 1,
                "selected_mid_dist_m": 0.0,
                "selected_evidence_len_m": 0.0,
                "in_drivezone_ratio": seed_drive_ratio,
                "in_divstrip_ratio": seed_div_ratio,
                "lite_failed_reasons": [],
                "failed_reason": None,
            }
            _append_ratio_stats(drivezone_ratio=seed_drive_ratio, divstrip_ratio=seed_div_ratio)
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
                    "geometry": geom_2d,
                    "properties": {
                        "nodeid": int(nodeid),
                        "left_extent_m": None,
                        "right_extent_m": None,
                        "cut_by_divstrip_left": None,
                        "cut_by_divstrip_right": None,
                        "used_trunc": False,
                        "xsec_gate_selected_by": "passthrough",
                        "xsec_gate_fallback": False,
                        "xsec_gate_mode": "passthrough",
                        "xsec_gate_in_drivezone_ratio": seed_drive_ratio,
                        "xsec_gate_in_divstrip_ratio": seed_div_ratio,
                    },
                }
            )
            continue

        if step0_mode in {"lite", "audit"} and lite_failed_reasons:
            # Audit mode: reject invalid seed xsec; do not generate repaired geometry for Step1.
            failed_count += 1
            gate_empty_count += 1
            fallback_orig += 1
            gate_all_map[int(nodeid)] = geom_2d
            gate_meta_map[int(nodeid)] = {
                "len_m": float(seed_len_m),
                "geom_type": str(getattr(geom_2d, "geom_type", "")),
                "fallback": True,
                "mode": "failed",
                "selected_by": "audit_reject",
                "selection_source": "audit",
                "candidate_segment_count": 1,
                "selected_mid_dist_m": 0.0,
                "selected_evidence_len_m": 0.0,
                "in_drivezone_ratio": seed_drive_ratio,
                "in_divstrip_ratio": seed_div_ratio,
                "lite_failed_reasons": list(lite_failed_reasons),
                "failed_reason": ";".join(str(v) for v in lite_failed_reasons),
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
                    "geometry": geom_2d,
                    "properties": {
                        "nodeid": int(nodeid),
                        "left_extent_m": None,
                        "right_extent_m": None,
                        "cut_by_divstrip_left": None,
                        "cut_by_divstrip_right": None,
                        "used_trunc": False,
                        "xsec_gate_selected_by": "audit_reject",
                        "xsec_gate_fallback": True,
                        "xsec_gate_mode": "failed",
                        "xsec_gate_in_drivezone_ratio": seed_drive_ratio,
                        "xsec_gate_in_divstrip_ratio": seed_div_ratio,
                        "xsec_gate_failed_reason": ";".join(str(v) for v in lite_failed_reasons),
                    },
                }
            )
            continue

        node_gate_empty = False
        if use_drivezone_gate:
            gate_all: BaseGeometry = geom_2d
            gate_selected_by = "drivezone_intersection"
            gate_fallback = False
            if drivezone_zone_metric is not None and (not drivezone_zone_metric.is_empty):
                try:
                    inter = geom_2d.intersection(drivezone_zone_metric)
                except Exception:
                    inter = geom_2d
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
                node_gate_empty = True
                gate_fallback = True
                if gore_zone_metric is not None and (not gore_zone_metric.is_empty):
                    try:
                        fallback_geom = geom_2d.difference(gore_zone_metric)
                    except Exception:
                        fallback_geom = geom_2d
                    if fallback_geom is not None and (not fallback_geom.is_empty):
                        gate_all = fallback_geom
                        gate_selected_by = "fallback_seed_minus_divstrip"
                    else:
                        gate_all = geom_2d
                        gate_selected_by = "fallback_raw_seed"
                else:
                    gate_all = geom_2d
                    gate_selected_by = "fallback_raw_seed"
            line_parts = [ls for ls in _iter_line_parts(gate_all) if isinstance(ls, LineString) and not ls.is_empty and ls.length > 1e-6]
            if not line_parts:
                gate_fallback = True
                gate_all = geom_2d
                line_parts = [geom_2d]
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
            selected_len_m = float(_line_len(gate_selected_line))
            selected_drive_ratio, selected_div_ratio = _line_ratios(gate_selected_line)
            if step0_mode == "lite":
                repaired_failed_reasons: list[str] = []
                if selected_len_m < step0_lite_min_len_m:
                    repaired_failed_reasons.append("full_too_short")
                if use_drivezone_gate and (selected_drive_ratio is None or selected_drive_ratio < step0_lite_min_in_drivezone_ratio):
                    repaired_failed_reasons.append("full_drivezone_ratio_below_threshold")
                if divstrip_available:
                    if selected_div_ratio is None:
                        repaired_failed_reasons.append("full_divstrip_ratio_missing")
                    elif selected_div_ratio > step0_lite_max_in_divstrip_ratio:
                        repaired_failed_reasons.append("full_divstrip_ratio_above_threshold")
                elif not step0_lite_allow_passthrough_when_divstrip_missing:
                    repaired_failed_reasons.append("divstrip_missing_blocked_repair")
                if repaired_failed_reasons:
                    failed_count += 1
                    if not node_gate_empty:
                        gate_empty_count += 1
                    fallback_orig += 1
                    gate_all_map[int(nodeid)] = gate_all
                    gate_meta_map[int(nodeid)] = {
                        "len_m": float(selected_len_m),
                        "geom_type": str(getattr(gate_all, "geom_type", "")),
                        "fallback": bool(gate_fallback),
                        "mode": "failed",
                        "selected_by": str(segment_selected_by if not gate_fallback else gate_selected_by),
                        "selection_source": str(gate_selected_by),
                        "candidate_segment_count": int(len(line_parts)),
                        "selected_mid_dist_m": float(selected_mid_dist_m),
                        "selected_evidence_len_m": float(selected_evidence_len_m),
                        "in_drivezone_ratio": selected_drive_ratio,
                        "in_divstrip_ratio": selected_div_ratio,
                        "lite_failed_reasons": list(lite_failed_reasons),
                        "failed_reason": ";".join(repaired_failed_reasons),
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
                                "used_trunc": bool(selected_len_m < seed_len_m - 1e-6),
                                "xsec_gate_selected_by": str(segment_selected_by if not gate_fallback else gate_selected_by),
                                "xsec_gate_fallback": bool(gate_fallback),
                                "xsec_gate_mode": "failed",
                                "xsec_gate_in_drivezone_ratio": selected_drive_ratio,
                                "xsec_gate_in_divstrip_ratio": selected_div_ratio,
                                "xsec_gate_failed_reason": ";".join(repaired_failed_reasons),
                            },
                        }
                    )
                    continue
            if selected_len_m < seed_len_m - 1e-6:
                used_trunc += 1
            if gate_fallback:
                gate_fallback_count += 1
                fallback_orig += 1
            repaired_count += 1
            gate_selected_count += 1
            out[int(nodeid)] = CrossSection(
                nodeid=int(cs.nodeid),
                geometry_metric=gate_selected_line,
                properties=dict(cs.properties),
            )
            gate_all_map[int(nodeid)] = gate_all
            gate_meta_map[int(nodeid)] = {
                "len_m": float(selected_len_m),
                "geom_type": str(getattr(gate_all, "geom_type", "")),
                "fallback": bool(gate_fallback),
                "mode": "repaired",
                "selected_by": str(segment_selected_by if not gate_fallback else gate_selected_by),
                "selection_source": str(gate_selected_by),
                "candidate_segment_count": int(len(line_parts)),
                "selected_mid_dist_m": float(selected_mid_dist_m),
                "selected_evidence_len_m": float(selected_evidence_len_m),
                "in_drivezone_ratio": selected_drive_ratio,
                "in_divstrip_ratio": selected_div_ratio,
                "lite_failed_reasons": list(lite_failed_reasons),
                "failed_reason": None,
            }
            _append_ratio_stats(drivezone_ratio=selected_drive_ratio, divstrip_ratio=selected_div_ratio)
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
                        "used_trunc": bool(selected_len_m < seed_len_m - 1e-6),
                        "xsec_gate_selected_by": str(segment_selected_by if not gate_fallback else gate_selected_by),
                        "xsec_gate_fallback": bool(gate_fallback),
                        "xsec_gate_mode": "repaired",
                        "xsec_gate_in_drivezone_ratio": selected_drive_ratio,
                        "xsec_gate_in_divstrip_ratio": selected_div_ratio,
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
            trunc_line = geom_2d
            fallback_orig += 1
        else:
            used_trunc += 1
        trunc_len_m = float(_line_len(trunc_line))
        trunc_drive_ratio, trunc_div_ratio = _line_ratios(trunc_line)
        if step0_mode == "lite" and use_drivezone_gate:
            repaired_failed_reasons = []
            if trunc_len_m < step0_lite_min_len_m:
                repaired_failed_reasons.append("full_too_short")
            if trunc_drive_ratio is None or trunc_drive_ratio < step0_lite_min_in_drivezone_ratio:
                repaired_failed_reasons.append("full_drivezone_ratio_below_threshold")
            if divstrip_available:
                if trunc_div_ratio is None:
                    repaired_failed_reasons.append("full_divstrip_ratio_missing")
                elif trunc_div_ratio > step0_lite_max_in_divstrip_ratio:
                    repaired_failed_reasons.append("full_divstrip_ratio_above_threshold")
            elif not step0_lite_allow_passthrough_when_divstrip_missing:
                repaired_failed_reasons.append("divstrip_missing_blocked_repair")
            if repaired_failed_reasons:
                failed_count += 1
                gate_empty_count += 1
                gate_all_map[int(nodeid)] = trunc_line
                gate_meta_map[int(nodeid)] = {
                    "len_m": float(trunc_len_m),
                    "geom_type": str(getattr(trunc_line, "geom_type", "")),
                    "fallback": True,
                    "mode": "failed",
                    "selected_by": "legacy_trunc",
                    "selection_source": "legacy_trunc",
                    "in_drivezone_ratio": trunc_drive_ratio,
                    "in_divstrip_ratio": trunc_div_ratio,
                    "lite_failed_reasons": list(lite_failed_reasons),
                    "failed_reason": ";".join(repaired_failed_reasons),
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
                        "geometry": trunc_line,
                        "properties": {
                            "nodeid": int(nodeid),
                            "left_extent_m": float(left_extent),
                            "right_extent_m": float(right_extent),
                            "cut_by_divstrip_left": bool(blocked_left),
                            "cut_by_divstrip_right": bool(blocked_right),
                            "used_trunc": bool(trunc_line is not geom_2d),
                            "xsec_gate_mode": "failed",
                            "xsec_gate_in_drivezone_ratio": trunc_drive_ratio,
                            "xsec_gate_in_divstrip_ratio": trunc_div_ratio,
                            "xsec_gate_failed_reason": ";".join(repaired_failed_reasons),
                        },
                    }
                )
                continue
        out[int(nodeid)] = CrossSection(
            nodeid=int(cs.nodeid),
            geometry_metric=trunc_line,
            properties=dict(cs.properties),
        )
        gate_all_map[int(nodeid)] = trunc_line
        gate_meta_map[int(nodeid)] = {
            "len_m": float(trunc_len_m),
            "geom_type": str(getattr(trunc_line, "geom_type", "")),
            "fallback": bool(trunc_len_m >= seed_len_m - 1e-6),
            "mode": "repaired",
            "selected_by": "legacy_trunc",
            "selection_source": "legacy_trunc",
            "in_drivezone_ratio": trunc_drive_ratio,
            "in_divstrip_ratio": trunc_div_ratio,
            "lite_failed_reasons": list(lite_failed_reasons),
            "failed_reason": None,
        }
        repaired_count += 1
        gate_selected_count += 1
        _append_ratio_stats(drivezone_ratio=trunc_drive_ratio, divstrip_ratio=trunc_div_ratio)
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
                    "used_trunc": bool(trunc_line is not geom_2d),
                    "xsec_gate_mode": "repaired",
                    "xsec_gate_in_drivezone_ratio": trunc_drive_ratio,
                    "xsec_gate_in_divstrip_ratio": trunc_div_ratio,
                },
            }
        )
    xsec_drivezone_ratio_p10 = _safe_percentile(drivezone_ratio_values, 10.0) if step0_stats_enable else None
    xsec_drivezone_ratio_p50 = _safe_percentile(drivezone_ratio_values, 50.0) if step0_stats_enable else None
    xsec_drivezone_ratio_p90 = _safe_percentile(drivezone_ratio_values, 90.0) if step0_stats_enable else None
    xsec_divstrip_ratio_p10 = _safe_percentile(divstrip_ratio_values, 10.0) if step0_stats_enable and divstrip_available else None
    xsec_divstrip_ratio_p50 = _safe_percentile(divstrip_ratio_values, 50.0) if step0_stats_enable and divstrip_available else None
    xsec_divstrip_ratio_p90 = _safe_percentile(divstrip_ratio_values, 90.0) if step0_stats_enable and divstrip_available else None
    stats = {
        "step0_mode_used": str(step0_mode),
        "xsec_truncated_count": int(used_trunc),
        "xsec_truncated_fallback_count": int(fallback_orig),
        "xsec_gate_enabled": bool(use_drivezone_gate),
        "xsec_gate_selected_count": int(gate_selected_count),
        "xsec_gate_empty_count": int(gate_empty_count),
        "xsec_gate_fallback_count": int(gate_fallback_count),
        "xsec_passthrough_count": int(passthrough_count),
        "xsec_repaired_count": int(repaired_count),
        "xsec_failed_count": int(failed_count),
        "xsec_drivezone_ratio_p10": xsec_drivezone_ratio_p10,
        "xsec_drivezone_ratio_p50": xsec_drivezone_ratio_p50,
        "xsec_drivezone_ratio_p90": xsec_drivezone_ratio_p90,
        "xsec_divstrip_ratio_p10": xsec_divstrip_ratio_p10,
        "xsec_divstrip_ratio_p50": xsec_divstrip_ratio_p50,
        "xsec_divstrip_ratio_p90": xsec_divstrip_ratio_p90,
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
        mode = str(md.get("mode") or "").strip()
        road[f"xsec_gate_mode_{tag}"] = mode if mode else None
        dz_ratio_v = md.get("in_drivezone_ratio")
        try:
            dz_ratio_f = float(dz_ratio_v)
        except Exception:
            dz_ratio_f = float("nan")
        road[f"xsec_gate_in_drivezone_ratio_{tag}"] = float(dz_ratio_f) if np.isfinite(dz_ratio_f) else None
        ds_ratio_v = md.get("in_divstrip_ratio")
        try:
            ds_ratio_f = float(ds_ratio_v)
        except Exception:
            ds_ratio_f = float("nan")
        road[f"xsec_gate_in_divstrip_ratio_{tag}"] = float(ds_ratio_f) if np.isfinite(ds_ratio_f) else None


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
        "xsec_policy_mode_src": None,
        "xsec_policy_mode_dst": None,
        "xsec_gate_len_src_m": None,
        "xsec_gate_len_dst_m": None,
        "xsec_gate_geom_type_src": None,
        "xsec_gate_geom_type_dst": None,
        "xsec_gate_fallback_src": None,
        "xsec_gate_fallback_dst": None,
        "xsec_gate_selected_by_src": None,
        "xsec_gate_selected_by_dst": None,
        "xsec_gate_mode_src": None,
        "xsec_gate_mode_dst": None,
        "xsec_gate_in_drivezone_ratio_src": None,
        "xsec_gate_in_drivezone_ratio_dst": None,
        "xsec_gate_in_divstrip_ratio_src": None,
        "xsec_gate_in_divstrip_ratio_dst": None,
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
        "step1_corridor_zone_area_m2": None,
        "step1_corridor_zone_source_count": None,
        "step1_corridor_zone_half_width_m": None,
        "step1_corridor_shape_ref_inside_ratio": None,
        "gore_fallback_used_src": False,
        "gore_fallback_used_dst": False,
        "traj_drop_count_by_drivezone": 0,
        "drivezone_fallback_used": False,
        "segment_corridor_enforced": False,
        "segment_corridor_inside_ratio": None,
        "segment_corridor_shape_ref_inside_ratio": None,
        "segment_corridor_outside_len_m": None,
        "segment_corridor_inside_tol_m": None,
        "segment_corridor_min_inside_ratio": None,
        "step3_width_ratio_src": None,
        "step3_width_ratio_dst": None,
        "step3_widening_suppressed": False,
        "step3_widening_suppress_src": False,
        "step3_widening_suppress_dst": False,
        "step3_widening_suppress_mode": None,
        "repr_traj_ids": repr_ids,
        "stitch_hops_p50": stitch_p50,
        "stitch_hops_p90": stitch_p90,
        "stitch_hops_max": stitch_max,
        "cluster_count": int(support.cluster_count),
        "main_cluster_ratio": float(support.main_cluster_ratio),
        "cluster_sep_m_est": support.cluster_sep_m_est,
        "no_geometry_candidate": None,
        "same_pair_handled": False,
        "same_pair_resolution_state": None,
        "same_pair_handled_count_for_pair": None,
        "same_pair_final_output_count_for_pair": None,
        "same_pair_unresolved_branch_count_for_pair": None,
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
        HARD_MULTI_NEIGHBOR_FOR_NODE: "multiple_dst_node_candidates_for_src_node",
        _HARD_MULTI_CHAIN_SAME_DST: "multiple_topology_chains_for_same_dst",
        HARD_NO_STRATEGY_MERGE_TO_DIVERGE: "merge_to_diverge_not_supported",
        HARD_MULTI_ROAD: "same_pair_channel_conflict_unresolved",
        HARD_NON_RC: "non_rc_node_used_in_pair",
        HARD_CENTER_EMPTY: "centerline_generation_failed",
        HARD_ENDPOINT: "endpoints_not_on_intersection_l",
        HARD_ENDPOINT_LOCAL: "endpoint_out_of_local_xsec_neighborhood",
        HARD_ENDPOINT_OFF_ANCHOR: "endpoint_off_xsec_road_after_snap",
        HARD_BRIDGE_SEGMENT: "bridge_segment_too_long",
        HARD_DIVSTRIP_INTERSECT: "road_intersects_divstrip_forbidden",
        HARD_ROAD_OUTSIDE_DRIVEZONE: "road_outside_drivezone_forbidden",
        _HARD_ROAD_OUTSIDE_SEGMENT_CORRIDOR: "road_outside_segment_corridor",
        _HARD_NO_ADJACENT_PAIR_AFTER_PASS2: "no_adjacent_pair_after_pass2",
        SOFT_LOW_SUPPORT: "support_traj_count_below_threshold",
        SOFT_SPARSE_POINTS: "surface_points_coverage_low",
        SOFT_NO_LB: "lane_boundary_continuous_not_found",
        SOFT_NO_LB_PATH: "lane_boundary_graph_path_not_found",
        SOFT_WIGGLY: "turn_rate_exceeds_limit",
        SOFT_OPEN_END: "patch_boundary_open_end",
        SOFT_AMBIGUOUS_NEXT_XSEC: "multiple_next_crossings_found",
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


def _is_valid_output_geometry(road: dict[str, Any]) -> bool:
    geom = road.get("_geometry_metric")
    return isinstance(geom, LineString) and (not geom.is_empty)


def _annotate_same_pair_resolution_states(roads: Sequence[dict[str, Any]]) -> dict[str, int]:
    pair_to_roads: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for road in roads:
        if not bool(road.get("step1_same_pair_multichain", False) or road.get("same_pair_multi_road", False)):
            continue
        key = (int(road.get("src_nodeid", -1)), int(road.get("dst_nodeid", -1)))
        pair_to_roads.setdefault(key, []).append(road)

    stats = {
        "same_pair_handled_pair_count": 0,
        "same_pair_handled_output_count": 0,
        "same_pair_single_output_pair_count": 0,
        "same_pair_multi_road_pair_count": 0,
        "same_pair_multi_road_output_count": 0,
        "same_pair_partial_unresolved_pair_count": 0,
        "same_pair_hard_conflict_pair_count": 0,
    }
    for pair, pair_roads in pair_to_roads.items():
        final_roads = [road for road in pair_roads if _is_valid_output_geometry(road)]
        unresolved_roads = [
            road
            for road in pair_roads
            if (not _is_valid_output_geometry(road))
            or bool(road.get("no_geometry_candidate", False))
            or (HARD_MULTI_ROAD in set(road.get("hard_reasons", [])))
        ]
        if len(final_roads) >= 2:
            resolution_state = "multi_output_valid" if not unresolved_roads else "partial_unresolved"
        elif len(final_roads) == 1:
            resolution_state = "single_output" if not unresolved_roads else "partial_unresolved"
        else:
            resolution_state = "hard_conflict"

        stats["same_pair_handled_pair_count"] += 1
        stats["same_pair_handled_output_count"] += int(len(final_roads))
        if resolution_state == "single_output":
            stats["same_pair_single_output_pair_count"] += 1
        elif resolution_state == "multi_output_valid":
            stats["same_pair_multi_road_pair_count"] += 1
            stats["same_pair_multi_road_output_count"] += int(len(final_roads))
        elif resolution_state == "partial_unresolved":
            stats["same_pair_partial_unresolved_pair_count"] += 1
        else:
            stats["same_pair_hard_conflict_pair_count"] += 1

        for road in pair_roads:
            road["same_pair_handled"] = True
            road["same_pair_resolution_state"] = str(resolution_state)
            road["same_pair_handled_count_for_pair"] = int(len(pair_roads))
            road["same_pair_final_output_count_for_pair"] = int(len(final_roads))
            road["same_pair_unresolved_branch_count_for_pair"] = int(len(unresolved_roads))
            road["same_pair_pair_key"] = f"{int(pair[0])}_{int(pair[1])}"

    return stats


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
    same_pair_resolution_stats = _annotate_same_pair_resolution_states(roads)
    road_candidate_count = int(len(roads))
    written_roads = [road for road in roads if _is_valid_output_geometry(road)]
    road_lines_metric_final = [road["_geometry_metric"] for road in written_roads]
    road_feature_props_final = [_strip_internal_fields(road) for road in written_roads]
    road_features_count = int(len(road_feature_props_final))
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
    metrics_payload["no_geometry_candidate"] = bool(no_geometry_candidate_count > 0)
    metrics_payload["params_digest"] = digest
    metrics_payload.update(same_pair_resolution_stats)
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
        same_pair_stats=same_pair_resolution_stats,
    )

    summary_params = {**params, "params_digest": digest}
    summary_params["road_features_count"] = int(road_features_count)
    summary_params["road_candidate_count"] = int(road_candidate_count)
    summary_params["no_geometry_candidate_count"] = int(no_geometry_candidate_count)
    summary_params["no_geometry_candidate"] = bool(no_geometry_candidate_count > 0)
    summary_params.update(same_pair_resolution_stats)
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
                or sk.startswith("traj_split_")
                or sk.startswith("divstrip_")
                or sk.startswith("slice_half_win_")
                or sk.startswith("pointcloud_")
                or sk.startswith("drivezone_")
                or sk.startswith("intersection_")
                or sk.startswith("step1_corridor_")
                or sk.startswith("step1_main_corridor_")
                or sk.startswith("step1_ambiguous_")
                or sk.startswith("step1_unique_")
                or sk.startswith("step1_vote_")
                or sk.startswith("step1_resolved_")
                or sk.startswith("step1_road_prior_")
                or sk.startswith("step0_")
                or sk.startswith("traj_surface_cache_")
                or sk.startswith("neighbor_search_")
                or sk.startswith("width_near_minus_base_")
                or sk.startswith("endpoint_in_drivezone_")
                or sk.startswith("xsec_samples_passable_ratio_")
                or sk.startswith("road_outside_drivezone_")
                or sk == "traj_drop_count_by_drivezone"
                or sk in {
                    "expanded_end_count",
                    "gore_tip_end_count",
                    "fallback_end_count",
                    "divstrip_missing",
                    "traj_source_count",
                    "traj_segment_count",
                }
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
        step0_status={
            "mode": metrics_payload.get("step0_mode_used"),
            "passthrough": metrics_payload.get("xsec_passthrough_count"),
            "repaired": metrics_payload.get("xsec_repaired_count"),
            "failed": metrics_payload.get("xsec_failed_count"),
            "gate_empty": metrics_payload.get("xsec_gate_empty_count"),
        },
    )

    debug_feature_collections: dict[str, dict[str, Any]] = {}
    if debug_layers:
        always_emit_empty = {
            "step1_corridor_centerline",
            "step1_corridor_candidates",
            "step1_corridor_zone",
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
            "xsec_cross_selected",
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
        "road_count": len(road_feature_props_final),
        "road_candidate_count": len(roads),
        "road_properties": road_feature_props_final,
        "road_lines_metric": road_lines_metric_final,
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


def _normalize_debug_geojson_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure debug FeatureCollection payloads are explicitly tagged as metric CRS."""
    if not isinstance(payload, dict):
        return payload
    if str(payload.get("type")) != "FeatureCollection":
        return payload
    crs = payload.get("crs")
    if isinstance(crs, dict):
        return payload
    out = dict(payload)
    out["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    return out


def get_default_params() -> dict[str, Any]:
    return dict(DEFAULT_PARAMS)


__all__ = ["DEFAULT_PARAMS", "RunResult", "get_default_params", "run_patch"]
