from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, substring

from .io import CrossSection, TrajectoryData


HARD_MULTI_ROAD = "MULTI_ROAD_SAME_PAIR"
HARD_NON_RC = "NON_RC_IN_BETWEEN"
HARD_CENTER_EMPTY = "CENTER_ESTIMATE_EMPTY"
HARD_ENDPOINT = "ENDPOINT_NOT_ON_XSEC"

SOFT_LOW_SUPPORT = "LOW_SUPPORT"
SOFT_SPARSE_POINTS = "SPARSE_SURFACE_POINTS"
SOFT_NO_LB = "NO_LB_CONTINUOUS"
SOFT_WIGGLY = "WIGGLY_CENTERLINE"
SOFT_OPEN_END = "OPEN_END"


@dataclass(frozen=True)
class CrossingEvent:
    traj_id: str
    nodeid: int
    seq: float
    seg_idx: int
    cross_point: Point


@dataclass
class PairSupport:
    src_nodeid: int
    dst_nodeid: int
    support_traj_ids: set[str] = field(default_factory=set)
    support_event_count: int = 0
    traj_segments: list[LineString] = field(default_factory=list)
    src_cross_points: list[Point] = field(default_factory=list)
    dst_cross_points: list[Point] = field(default_factory=list)
    repr_traj_ids: list[str] = field(default_factory=list)
    open_end: bool = False
    hard_anomalies: set[str] = field(default_factory=set)
    hints: list[str] = field(default_factory=list)


@dataclass
class CenterEstimate:
    centerline_metric: LineString | None
    shape_ref_metric: LineString | None
    stable_offset_m_src: float | None
    stable_offset_m_dst: float | None
    center_sample_coverage: float
    width_med_m: float | None
    width_p90_m: float | None
    max_turn_deg_per_10m: float | None
    used_lane_boundary: bool
    soft_flags: set[str]
    hard_flags: set[str]
    diagnostics: dict[str, Any]


def extract_crossing_events(
    trajectories: Sequence[TrajectoryData],
    cross_sections: Sequence[CrossSection],
    *,
    hit_buffer_m: float,
    dedup_gap_m: float,
) -> dict[str, list[CrossingEvent]]:
    out: dict[str, list[CrossingEvent]] = {}
    if not cross_sections:
        return out

    xsecs: list[tuple[int, LineString, Any]] = []
    for x in cross_sections:
        geom = x.geometry_metric
        if geom.is_empty or geom.length <= 0:
            continue
        xsecs.append((x.nodeid, geom, geom.buffer(hit_buffer_m)))

    for traj in trajectories:
        coords = np.asarray(traj.xyz_metric[:, :2], dtype=np.float64)
        seq = np.asarray(traj.seq, dtype=np.float64)
        if coords.shape[0] < 2:
            continue

        events: list[CrossingEvent] = []
        for i in range(coords.shape[0] - 1):
            p0 = coords[i]
            p1 = coords[i + 1]
            if not (_finite_xy(p0) and _finite_xy(p1)):
                continue
            if float(np.linalg.norm(p1 - p0)) <= 1e-6:
                continue

            seg = LineString([tuple(p0), tuple(p1)])
            for nodeid, xline, xbuf in xsecs:
                if not seg.intersects(xbuf):
                    continue

                cp = _segment_cross_point(seg, xline)
                if cp is None:
                    continue

                frac = _segment_fraction(cp, p0, p1)
                seq_val = float(seq[i] + frac * (seq[i + 1] - seq[i]))
                events.append(
                    CrossingEvent(
                        traj_id=traj.traj_id,
                        nodeid=int(nodeid),
                        seq=seq_val,
                        seg_idx=int(i),
                        cross_point=cp,
                    )
                )

        deduped = _dedup_events(events, dedup_gap_m=dedup_gap_m)
        if deduped:
            out[traj.traj_id] = deduped

    return out


def build_pair_supports(
    trajectories: Sequence[TrajectoryData],
    events_by_traj: dict[str, list[CrossingEvent]],
    *,
    node_type_map: dict[int, str],
) -> dict[tuple[int, int], PairSupport]:
    traj_map = {t.traj_id: t for t in trajectories}
    supports: dict[tuple[int, int], PairSupport] = {}

    for traj_id, events in events_by_traj.items():
        traj = traj_map.get(traj_id)
        if traj is None or len(events) < 2:
            continue

        for i in range(len(events) - 1):
            a = events[i]
            b = events[i + 1]
            if a.nodeid == b.nodeid:
                continue

            pair = (a.nodeid, b.nodeid)
            support = supports.get(pair)
            if support is None:
                support = PairSupport(src_nodeid=pair[0], dst_nodeid=pair[1])
                supports[pair] = support

            support.support_traj_ids.add(traj_id)
            support.support_event_count += 1
            support.src_cross_points.append(a.cross_point)
            support.dst_cross_points.append(b.cross_point)
            if traj_id not in support.repr_traj_ids and len(support.repr_traj_ids) < 16:
                support.repr_traj_ids.append(traj_id)

            seg = _extract_traj_segment(traj, a, b)
            if seg is not None and seg.length > 0:
                support.traj_segments.append(seg)

            if i == 0 or (i + 1) == (len(events) - 1):
                support.open_end = True

            src_type = node_type_map.get(a.nodeid, "unknown")
            dst_type = node_type_map.get(b.nodeid, "unknown")
            if src_type == "non_rc" or dst_type == "non_rc":
                support.hard_anomalies.add(HARD_NON_RC)

    for support in supports.values():
        if _detect_multi_road_channels(support):
            support.hard_anomalies.add(HARD_MULTI_ROAD)

    return supports


def infer_node_types(
    *,
    node_ids: Iterable[int],
    pair_supports: dict[tuple[int, int], PairSupport],
    node_kind_map: dict[int, int],
) -> tuple[dict[int, str], dict[int, int], dict[int, int]]:
    in_degree: dict[int, int] = {int(n): 0 for n in node_ids}
    out_degree: dict[int, int] = {int(n): 0 for n in node_ids}

    for (src, dst), support in pair_supports.items():
        w = max(1, len(support.support_traj_ids))
        out_degree[src] = out_degree.get(src, 0) + w
        in_degree[dst] = in_degree.get(dst, 0) + w

    out: dict[int, str] = {}
    for n in set([*in_degree.keys(), *out_degree.keys(), *node_kind_map.keys()]):
        kind = node_kind_map.get(int(n))
        if kind is not None:
            out[int(n)] = _kind_to_node_type(kind)
            continue

        indeg = in_degree.get(int(n), 0)
        outdeg = out_degree.get(int(n), 0)
        if outdeg > 1 and indeg <= 1:
            out[int(n)] = "diverge"
        elif indeg > 1 and outdeg <= 1:
            out[int(n)] = "merge"
        elif indeg > 0 or outdeg > 0:
            out[int(n)] = "unknown"
        else:
            out[int(n)] = "unknown"

    return out, in_degree, out_degree


def estimate_centerline(
    *,
    support: PairSupport,
    src_xsec: LineString,
    dst_xsec: LineString,
    src_type: str,
    dst_type: str,
    src_out_degree: int,
    dst_in_degree: int,
    lane_boundaries_metric: Sequence[LineString],
    surface_points_xyz: np.ndarray,
    center_sample_step_m: float,
    xsec_along_half_window_m: float,
    xsec_across_half_window_m: float,
    xsec_min_points: int,
    width_pct_low: float,
    width_pct_high: float,
    min_center_coverage: float,
    smooth_window_m: float,
    stable_offset_m: float,
    stable_margin_m: float,
    endpoint_tol_m: float,
    road_max_vertices: int,
) -> CenterEstimate:
    soft_flags: set[str] = set()
    hard_flags: set[str] = set(support.hard_anomalies)
    diagnostics: dict[str, Any] = {}

    shape_ref, used_lb = _choose_shape_ref(support, src_xsec, dst_xsec, lane_boundaries_metric)
    if shape_ref is None:
        hard_flags.add(HARD_CENTER_EMPTY)
        return CenterEstimate(
            centerline_metric=None,
            shape_ref_metric=None,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=0.0,
            width_med_m=None,
            width_p90_m=None,
            max_turn_deg_per_10m=None,
            used_lane_boundary=False,
            soft_flags=soft_flags,
            hard_flags=hard_flags,
            diagnostics={"reason": "shape_ref_unavailable"},
        )

    if not used_lb:
        soft_flags.add(SOFT_NO_LB)

    ss, sp, tv, nv = _sample_line(shape_ref, step_m=center_sample_step_m)
    if sp.shape[0] < 2:
        hard_flags.add(HARD_CENTER_EMPTY)
        return CenterEstimate(
            centerline_metric=None,
            shape_ref_metric=shape_ref,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=0.0,
            width_med_m=None,
            width_p90_m=None,
            max_turn_deg_per_10m=None,
            used_lane_boundary=used_lb,
            soft_flags=soft_flags,
            hard_flags=hard_flags,
            diagnostics={"reason": "shape_ref_sampling_failed"},
        )

    offsets, widths, coverage = _estimate_offsets_from_surface(
        sample_points=sp,
        tangents=tv,
        normals=nv,
        points_xyz=surface_points_xyz,
        along_half_window_m=xsec_along_half_window_m,
        across_half_window_m=xsec_across_half_window_m,
        min_points=xsec_min_points,
        width_pct_low=width_pct_low,
        width_pct_high=width_pct_high,
    )

    diagnostics["surface_points_in_window"] = int(surface_points_xyz.shape[0])
    diagnostics["raw_coverage"] = float(coverage)

    if coverage < float(min_center_coverage):
        soft_flags.add(SOFT_SPARSE_POINTS)

    smoothed = _smooth_offsets(offsets, step_m=center_sample_step_m, window_m=smooth_window_m)
    if np.count_nonzero(np.isfinite(smoothed)) < 2:
        hard_flags.add(HARD_CENTER_EMPTY)
        return CenterEstimate(
            centerline_metric=None,
            shape_ref_metric=shape_ref,
            stable_offset_m_src=None,
            stable_offset_m_dst=None,
            center_sample_coverage=float(coverage),
            width_med_m=_nanmedian(widths),
            width_p90_m=_nanpercentile(widths, 90.0),
            max_turn_deg_per_10m=None,
            used_lane_boundary=used_lb,
            soft_flags=soft_flags,
            hard_flags=hard_flags,
            diagnostics=diagnostics,
        )

    head_stable = src_type == "diverge" and src_out_degree > 1
    tail_stable = dst_type == "merge" and dst_in_degree > 1

    stable_src, stable_dst = _apply_stable_zone(
        offsets=smoothed,
        stations=ss,
        length_m=float(shape_ref.length),
        apply_head=head_stable,
        apply_tail=tail_stable,
        stable_offset_m=stable_offset_m,
        margin_m=stable_margin_m,
    )

    centerline = _offset_line(sample_points=sp, normals=nv, offsets=smoothed)
    if centerline is None or centerline.length <= 0:
        hard_flags.add(HARD_CENTER_EMPTY)
        return CenterEstimate(
            centerline_metric=None,
            shape_ref_metric=shape_ref,
            stable_offset_m_src=stable_src,
            stable_offset_m_dst=stable_dst,
            center_sample_coverage=float(coverage),
            width_med_m=_nanmedian(widths),
            width_p90_m=_nanpercentile(widths, 90.0),
            max_turn_deg_per_10m=None,
            used_lane_boundary=used_lb,
            soft_flags=soft_flags,
            hard_flags=hard_flags,
            diagnostics=diagnostics,
        )

    clipped, clip_reason = clip_line_to_cross_sections(
        centerline,
        src_xsec,
        dst_xsec,
        endpoint_tol_m=endpoint_tol_m,
    )

    if clipped is None:
        hard_flags.add(clip_reason or HARD_CENTER_EMPTY)
        return CenterEstimate(
            centerline_metric=None,
            shape_ref_metric=shape_ref,
            stable_offset_m_src=stable_src,
            stable_offset_m_dst=stable_dst,
            center_sample_coverage=float(coverage),
            width_med_m=_nanmedian(widths),
            width_p90_m=_nanpercentile(widths, 90.0),
            max_turn_deg_per_10m=None,
            used_lane_boundary=used_lb,
            soft_flags=soft_flags,
            hard_flags=hard_flags,
            diagnostics=diagnostics,
        )

    clipped = _limit_vertices(clipped, road_max_vertices)

    turn = compute_max_turn_deg_per_10m(clipped)
    if turn is not None:
        diagnostics["max_turn_deg_per_10m"] = float(turn)

    return CenterEstimate(
        centerline_metric=clipped,
        shape_ref_metric=shape_ref,
        stable_offset_m_src=stable_src,
        stable_offset_m_dst=stable_dst,
        center_sample_coverage=float(coverage),
        width_med_m=_nanmedian(widths),
        width_p90_m=_nanpercentile(widths, 90.0),
        max_turn_deg_per_10m=turn,
        used_lane_boundary=used_lb,
        soft_flags=soft_flags,
        hard_flags=hard_flags,
        diagnostics=diagnostics,
    )


def clip_line_to_cross_sections(
    line: LineString,
    src_xsec: LineString,
    dst_xsec: LineString,
    *,
    endpoint_tol_m: float,
) -> tuple[LineString | None, str | None]:
    s0 = _locate_on_line(line, src_xsec, tol=endpoint_tol_m)
    s1 = _locate_on_line(line, dst_xsec, tol=endpoint_tol_m)

    if s0 is None or s1 is None:
        return None, HARD_CENTER_EMPTY

    if abs(s1 - s0) < 1e-3:
        return None, HARD_CENTER_EMPTY

    start = min(s0, s1)
    end = max(s0, s1)
    try:
        seg = substring(line, start, end)
    except Exception:
        seg = line

    if seg is None or seg.is_empty or not isinstance(seg, LineString) or len(seg.coords) < 2:
        return None, HARD_CENTER_EMPTY

    p_start = Point(seg.coords[0])
    p_end = Point(seg.coords[-1])
    if p_start.distance(src_xsec) > endpoint_tol_m or p_end.distance(dst_xsec) > endpoint_tol_m:
        # 尝试反向检查（可能方向相反）
        if p_start.distance(dst_xsec) <= endpoint_tol_m and p_end.distance(src_xsec) <= endpoint_tol_m:
            rev = LineString(list(seg.coords)[::-1])
            return rev, None
        return None, HARD_ENDPOINT

    return seg, None


def compute_max_turn_deg_per_10m(line: LineString) -> float | None:
    coords = np.asarray(line.coords, dtype=np.float64)
    if coords.shape[0] < 3:
        return 0.0

    max_val = 0.0
    for i in range(1, coords.shape[0] - 1):
        a = coords[i] - coords[i - 1]
        b = coords[i + 1] - coords[i]
        la = float(np.linalg.norm(a))
        lb = float(np.linalg.norm(b))
        if la <= 1e-6 or lb <= 1e-6:
            continue
        cosv = float(np.dot(a, b) / (la * lb))
        cosv = min(1.0, max(-1.0, cosv))
        angle = math.degrees(math.acos(cosv))
        span = 0.5 * (la + lb)
        scaled = angle * (10.0 / max(span, 1e-3))
        if scaled > max_val:
            max_val = scaled

    return float(max_val)


def _kind_to_node_type(kind: int) -> str:
    k = int(kind)
    if k & (1 << 4):
        return "diverge"
    if k & (1 << 3):
        return "merge"
    if k & (1 << 2):
        return "non_rc"
    if k == 0:
        return "unknown"
    return "non_rc"


def _detect_multi_road_channels(support: PairSupport) -> bool:
    if len(support.support_traj_ids) < 3:
        return False

    src_xy = np.asarray([[p.x, p.y] for p in support.src_cross_points], dtype=np.float64)
    dst_xy = np.asarray([[p.x, p.y] for p in support.dst_cross_points], dtype=np.float64)
    if src_xy.shape[0] < 3 or dst_xy.shape[0] < 3:
        return False

    src_spread = _spread_m(src_xy)
    dst_spread = _spread_m(dst_xy)
    return bool(src_spread > 12.0 or dst_spread > 12.0)


def _spread_m(xy: np.ndarray) -> float:
    center = np.nanmedian(xy, axis=0)
    d = np.linalg.norm(xy - center[None, :], axis=1)
    if d.size == 0:
        return 0.0
    return float(np.nanpercentile(d, 95.0))


def _segment_cross_point(seg: LineString, xline: LineString) -> Point | None:
    try:
        inter = seg.intersection(xline)
    except Exception:
        inter = None

    p = _geometry_to_point(inter)
    if p is not None:
        return p

    try:
        p0, _ = nearest_points(seg, xline)
        if isinstance(p0, Point):
            return p0
    except Exception:
        return None

    return None


def _geometry_to_point(geom: Any) -> Point | None:
    if geom is None:
        return None
    if isinstance(geom, Point):
        return geom

    gtype = getattr(geom, "geom_type", "")
    if gtype == "MultiPoint":
        pts = [g for g in geom.geoms if isinstance(g, Point)]
        if not pts:
            return None
        return pts[0]
    if gtype in {"LineString", "MultiLineString", "GeometryCollection"}:
        try:
            centroid = geom.centroid
            if isinstance(centroid, Point):
                return centroid
        except Exception:
            return None
    return None


def _segment_fraction(cp: Point, p0: np.ndarray, p1: np.ndarray) -> float:
    d = p1 - p0
    l2 = float(np.dot(d, d))
    if l2 <= 1e-12:
        return 0.5
    t = float(((cp.x - p0[0]) * d[0] + (cp.y - p0[1]) * d[1]) / l2)
    return min(1.0, max(0.0, t))


def _dedup_events(events: list[CrossingEvent], *, dedup_gap_m: float) -> list[CrossingEvent]:
    if not events:
        return []

    events = sorted(events, key=lambda e: (e.seq, e.seg_idx, e.nodeid))
    out: list[CrossingEvent] = []
    last_by_node: dict[int, CrossingEvent] = {}

    for ev in events:
        prev = last_by_node.get(ev.nodeid)
        if prev is not None:
            if ev.cross_point.distance(prev.cross_point) < dedup_gap_m:
                continue
            if abs(ev.seq - prev.seq) < 1e-6:
                continue

        out.append(ev)
        last_by_node[ev.nodeid] = ev

    return out


def _extract_traj_segment(traj: TrajectoryData, a: CrossingEvent, b: CrossingEvent) -> LineString | None:
    xy = np.asarray(traj.xyz_metric[:, :2], dtype=np.float64)
    n = xy.shape[0]
    if n < 2:
        return None

    i0 = max(0, min(n - 2, int(a.seg_idx)))
    i1 = max(0, min(n - 2, int(b.seg_idx)))
    if i1 < i0:
        i0, i1 = i1, i0

    coords: list[tuple[float, float]] = [(float(a.cross_point.x), float(a.cross_point.y))]
    for i in range(i0 + 1, i1 + 1):
        coords.append((float(xy[i, 0]), float(xy[i, 1])))
    coords.append((float(b.cross_point.x), float(b.cross_point.y)))

    coords = _dedup_coords(coords)
    if len(coords) < 2:
        return None

    seg = LineString(coords)
    if seg.is_empty or seg.length <= 0:
        return None
    return seg


def _dedup_coords(coords: list[tuple[float, float]], eps: float = 1e-6) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for c in coords:
        if not out:
            out.append(c)
            continue
        if math.hypot(c[0] - out[-1][0], c[1] - out[-1][1]) > eps:
            out.append(c)
    return out


def _choose_shape_ref(
    support: PairSupport,
    src_xsec: LineString,
    dst_xsec: LineString,
    lane_boundaries_metric: Sequence[LineString],
) -> tuple[LineString | None, bool]:
    src_buf = src_xsec.buffer(0.5)
    dst_buf = dst_xsec.buffer(0.5)

    candidates: list[LineString] = []
    for lb in lane_boundaries_metric:
        if lb.is_empty or lb.length <= 0:
            continue
        if lb.intersects(src_buf) and lb.intersects(dst_buf):
            candidates.append(lb)

    if candidates:
        best = max(candidates, key=lambda g: g.length)
        return _orient_line(best, src_xsec, dst_xsec), True

    if support.traj_segments:
        best = max(support.traj_segments, key=lambda g: g.length)
        return _orient_line(best, src_xsec, dst_xsec), False

    return None, False


def _orient_line(line: LineString, src_xsec: LineString, dst_xsec: LineString) -> LineString:
    if line.is_empty or len(line.coords) < 2:
        return line
    p0 = Point(line.coords[0])
    p1 = Point(line.coords[-1])

    forward = p0.distance(src_xsec) + p1.distance(dst_xsec)
    backward = p1.distance(src_xsec) + p0.distance(dst_xsec)
    if backward < forward:
        return LineString(list(line.coords)[::-1])
    return line


def _sample_line(line: LineString, *, step_m: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    length = float(line.length)
    if length <= 0:
        return (
            np.empty((0,), dtype=np.float64),
            np.empty((0, 2), dtype=np.float64),
            np.empty((0, 2), dtype=np.float64),
            np.empty((0, 2), dtype=np.float64),
        )

    n = max(2, int(math.ceil(length / max(step_m, 0.5))) + 1)
    ss = np.linspace(0.0, length, n)
    pts = np.zeros((n, 2), dtype=np.float64)
    tangents = np.zeros((n, 2), dtype=np.float64)
    normals = np.zeros((n, 2), dtype=np.float64)

    delta = min(2.0, max(0.5, step_m * 0.5))

    for i, s in enumerate(ss):
        p = line.interpolate(float(s))
        pts[i, :] = [p.x, p.y]

        s0 = max(0.0, float(s - delta))
        s1 = min(length, float(s + delta))
        p0 = line.interpolate(s0)
        p1 = line.interpolate(s1)

        v = np.asarray([p1.x - p0.x, p1.y - p0.y], dtype=np.float64)
        nv = np.linalg.norm(v)
        if nv <= 1e-9:
            if i > 0:
                tangents[i, :] = tangents[i - 1, :]
                normals[i, :] = normals[i - 1, :]
            else:
                tangents[i, :] = [1.0, 0.0]
                normals[i, :] = [0.0, 1.0]
            continue

        t = v / nv
        tangents[i, :] = t
        normals[i, :] = np.asarray([-t[1], t[0]], dtype=np.float64)

    return ss, pts, tangents, normals


def _estimate_offsets_from_surface(
    *,
    sample_points: np.ndarray,
    tangents: np.ndarray,
    normals: np.ndarray,
    points_xyz: np.ndarray,
    along_half_window_m: float,
    across_half_window_m: float,
    min_points: int,
    width_pct_low: float,
    width_pct_high: float,
) -> tuple[np.ndarray, np.ndarray, float]:
    n = sample_points.shape[0]
    offsets = np.full((n,), np.nan, dtype=np.float64)
    widths = np.full((n,), np.nan, dtype=np.float64)

    if points_xyz.size == 0 or points_xyz.shape[0] < 8:
        return offsets, widths, 0.0

    xy = np.asarray(points_xyz[:, :2], dtype=np.float64)
    grid = _build_grid_index(xy, cell_size=max(2.0, across_half_window_m / 3.0))

    for i in range(n):
        c = sample_points[i]
        t = tangents[i]
        no = normals[i]

        idx = _query_grid_indices(
            grid,
            center_xy=c,
            half_dx=along_half_window_m + across_half_window_m,
            half_dy=along_half_window_m + across_half_window_m,
        )
        if idx.size == 0:
            continue

        rel = xy[idx, :] - c[None, :]
        along = rel @ t
        across = rel @ no
        keep = (np.abs(along) <= along_half_window_m) & (np.abs(across) <= across_half_window_m)
        if np.count_nonzero(keep) < int(min_points):
            continue

        vals = across[keep]
        lo = float(np.percentile(vals, width_pct_low))
        hi = float(np.percentile(vals, width_pct_high))
        center = 0.5 * (lo + hi)

        offsets[i] = center
        widths[i] = max(0.0, hi - lo)

    coverage = float(np.count_nonzero(np.isfinite(offsets)) / max(1, n))
    return offsets, widths, coverage


def _build_grid_index(xy: np.ndarray, *, cell_size: float) -> dict[str, Any]:
    x = xy[:, 0]
    y = xy[:, 1]
    ix = np.floor(x / cell_size).astype(np.int64)
    iy = np.floor(y / cell_size).astype(np.int64)

    cells: dict[tuple[int, int], list[int]] = {}
    for i in range(xy.shape[0]):
        key = (int(ix[i]), int(iy[i]))
        cells.setdefault(key, []).append(i)

    compact = {k: np.asarray(v, dtype=np.int64) for k, v in cells.items()}
    return {"cell_size": float(cell_size), "cells": compact}


def _query_grid_indices(
    grid: dict[str, Any],
    *,
    center_xy: np.ndarray,
    half_dx: float,
    half_dy: float,
) -> np.ndarray:
    cell_size = float(grid["cell_size"])
    cells: dict[tuple[int, int], np.ndarray] = grid["cells"]

    minx = center_xy[0] - half_dx
    maxx = center_xy[0] + half_dx
    miny = center_xy[1] - half_dy
    maxy = center_xy[1] + half_dy

    ix0 = int(math.floor(minx / cell_size))
    ix1 = int(math.floor(maxx / cell_size))
    iy0 = int(math.floor(miny / cell_size))
    iy1 = int(math.floor(maxy / cell_size))

    out: list[np.ndarray] = []
    for ix in range(ix0, ix1 + 1):
        for iy in range(iy0, iy1 + 1):
            arr = cells.get((ix, iy))
            if arr is not None and arr.size > 0:
                out.append(arr)

    if not out:
        return np.empty((0,), dtype=np.int64)
    return np.concatenate(out)


def _smooth_offsets(offsets: np.ndarray, *, step_m: float, window_m: float) -> np.ndarray:
    x = np.asarray(offsets, dtype=np.float64).copy()
    if np.count_nonzero(np.isfinite(x)) == 0:
        return x

    x = _fill_nan_linear(x)

    win = max(1, int(round(window_m / max(step_m, 0.5))))
    if win <= 1:
        return x
    if win % 2 == 0:
        win += 1

    pad = win // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    kernel = np.ones((win,), dtype=np.float64) / float(win)
    smoothed = np.convolve(xp, kernel, mode="valid")
    return smoothed.astype(np.float64)


def _fill_nan_linear(x: np.ndarray) -> np.ndarray:
    idx = np.arange(x.size)
    mask = np.isfinite(x)
    if np.count_nonzero(mask) == 0:
        return x
    if np.count_nonzero(mask) == 1:
        x[~mask] = x[mask][0]
        return x
    x[~mask] = np.interp(idx[~mask], idx[mask], x[mask])
    return x


def _apply_stable_zone(
    *,
    offsets: np.ndarray,
    stations: np.ndarray,
    length_m: float,
    apply_head: bool,
    apply_tail: bool,
    stable_offset_m: float,
    margin_m: float,
) -> tuple[float | None, float | None]:
    stable_src: float | None = None
    stable_dst: float | None = None

    if offsets.size < 3 or length_m <= 1.0:
        return stable_src, stable_dst

    s_stable = min(float(stable_offset_m), max(0.0, length_m - float(margin_m)))
    if s_stable <= 0.0:
        return stable_src, stable_dst

    if apply_head:
        idx = int(np.argmin(np.abs(stations - s_stable)))
        stable_src = float(offsets[idx])
        mask = stations <= s_stable
        offsets[mask] = stable_src

    if apply_tail:
        target = max(0.0, length_m - s_stable)
        idx = int(np.argmin(np.abs(stations - target)))
        stable_dst = float(offsets[idx])
        mask = stations >= target
        offsets[mask] = stable_dst

    return stable_src, stable_dst


def _offset_line(*, sample_points: np.ndarray, normals: np.ndarray, offsets: np.ndarray) -> LineString | None:
    if sample_points.shape[0] < 2:
        return None

    pts = sample_points + normals * offsets[:, None]
    coords = [(float(p[0]), float(p[1])) for p in pts]
    coords = _dedup_coords(coords)
    if len(coords) < 2:
        return None

    line = LineString(coords)
    if line.is_empty or line.length <= 0:
        return None
    return line


def _locate_on_line(line: LineString, xsec: LineString, *, tol: float) -> float | None:
    try:
        inter = line.intersection(xsec)
    except Exception:
        inter = None

    p = _geometry_to_point(inter)
    if p is not None:
        try:
            return float(line.project(p))
        except Exception:
            pass

    try:
        lp, xp = nearest_points(line, xsec)
        if isinstance(lp, Point) and isinstance(xp, Point):
            if lp.distance(xp) <= max(0.5, tol * 2.0):
                return float(line.project(lp))
    except Exception:
        return None

    return None


def _limit_vertices(line: LineString, max_vertices: int) -> LineString:
    coords = list(line.coords)
    n = len(coords)
    if n <= max_vertices:
        return line

    idx = np.linspace(0, n - 1, max_vertices).astype(np.int64)
    new_coords = [coords[int(i)] for i in idx]
    new_coords = _dedup_coords([(float(x), float(y)) for x, y in new_coords])
    if len(new_coords) < 2:
        return line
    return LineString(new_coords)


def _finite_xy(xy: np.ndarray) -> bool:
    return bool(np.isfinite(xy[0]) and np.isfinite(xy[1]))


def _nanmedian(x: np.ndarray) -> float | None:
    vals = x[np.isfinite(x)]
    if vals.size == 0:
        return None
    return float(np.median(vals))


def _nanpercentile(x: np.ndarray, q: float) -> float | None:
    vals = x[np.isfinite(x)]
    if vals.size == 0:
        return None
    return float(np.percentile(vals, q))


__all__ = [
    "CenterEstimate",
    "CrossingEvent",
    "HARD_CENTER_EMPTY",
    "HARD_ENDPOINT",
    "HARD_MULTI_ROAD",
    "HARD_NON_RC",
    "PairSupport",
    "SOFT_LOW_SUPPORT",
    "SOFT_NO_LB",
    "SOFT_OPEN_END",
    "SOFT_SPARSE_POINTS",
    "SOFT_WIGGLY",
    "build_pair_supports",
    "clip_line_to_cross_sections",
    "compute_max_turn_deg_per_10m",
    "estimate_centerline",
    "extract_crossing_events",
    "infer_node_types",
]
