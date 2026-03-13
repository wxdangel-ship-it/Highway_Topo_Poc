from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString


Coords2D = tuple[tuple[float, float], ...]


def line_to_coords(line: LineString) -> Coords2D:
    return tuple((float(x), float(y)) for x, y, *_ in line.coords)


def coords_to_line(coords: Coords2D) -> LineString:
    return LineString([(float(x), float(y)) for x, y in coords])


@dataclass(frozen=True)
class BaseCrossSection:
    nodeid: int
    geometry_coords: Coords2D
    properties: dict[str, Any] = field(default_factory=dict)

    def geometry_metric(self) -> LineString:
        return coords_to_line(self.geometry_coords)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeid": int(self.nodeid),
            "geometry_coords": [[float(x), float(y)] for x, y in self.geometry_coords],
            "properties": dict(self.properties),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BaseCrossSection":
        coords = tuple((float(x), float(y)) for x, y in payload.get("geometry_coords", []))
        return cls(
            nodeid=int(payload.get("nodeid")),
            geometry_coords=coords,
            properties=dict(payload.get("properties") or {}),
        )


@dataclass(frozen=True)
class ProbeCrossSection:
    probe_id: str
    parent_segment_id: str
    geometry_coords: Coords2D
    role: str

    def geometry_metric(self) -> LineString:
        return coords_to_line(self.geometry_coords)

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_id": str(self.probe_id),
            "parent_segment_id": str(self.parent_segment_id),
            "geometry_coords": [[float(x), float(y)] for x, y in self.geometry_coords],
            "role": str(self.role),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProbeCrossSection":
        coords = tuple((float(x), float(y)) for x, y in payload.get("geometry_coords", []))
        return cls(
            probe_id=str(payload.get("probe_id")),
            parent_segment_id=str(payload.get("parent_segment_id")),
            geometry_coords=coords,
            role=str(payload.get("role")),
        )


@dataclass(frozen=True)
class CorridorInterval:
    start_s: float
    end_s: float
    center_s: float
    length_m: float
    rank: int
    geometry_coords: Coords2D

    def geometry_metric(self) -> LineString:
        return coords_to_line(self.geometry_coords)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_s": float(self.start_s),
            "end_s": float(self.end_s),
            "center_s": float(self.center_s),
            "length_m": float(self.length_m),
            "rank": int(self.rank),
            "geometry_coords": [[float(x), float(y)] for x, y in self.geometry_coords],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CorridorInterval":
        coords = tuple((float(x), float(y)) for x, y in payload.get("geometry_coords", []))
        return cls(
            start_s=float(payload.get("start_s", 0.0)),
            end_s=float(payload.get("end_s", 0.0)),
            center_s=float(payload.get("center_s", 0.0)),
            length_m=float(payload.get("length_m", 0.0)),
            rank=int(payload.get("rank", 0)),
            geometry_coords=coords,
        )


@dataclass(frozen=True)
class Segment:
    segment_id: str
    src_nodeid: int
    dst_nodeid: int
    direction: str
    geometry_coords: Coords2D
    candidate_ids: tuple[str, ...]
    source_modes: tuple[str, ...]
    support_traj_ids: tuple[str, ...]
    support_count: int
    dedup_count: int
    representative_offset_m: float
    other_xsec_crossing_count: int
    tolerated_other_xsec_crossings: int
    prior_supported: bool
    formation_reason: str
    length_m: float
    drivezone_ratio: float
    crosses_divstrip: bool
    topology_arc_id: str = ""
    topology_arc_source_type: str = ""
    topology_arc_edge_ids: tuple[str, ...] = ()
    topology_arc_node_path: tuple[int, ...] = ()
    topology_arc_is_direct_legal: bool = False
    topology_arc_is_unique: bool = False
    bridge_candidate_retained: bool = False
    bridge_chain_exists: bool = False
    bridge_chain_unique: bool = False
    bridge_chain_nodes: tuple[int, ...] = ()
    bridge_chain_source: str = ""
    bridge_diagnostic_reason: str = ""
    bridge_decision_stage: str = ""
    bridge_decision_reason: str = ""
    same_pair_rank: int | None = None
    kept_reason: str = ""

    def geometry_metric(self) -> LineString:
        return coords_to_line(self.geometry_coords)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": str(self.segment_id),
            "src_nodeid": int(self.src_nodeid),
            "dst_nodeid": int(self.dst_nodeid),
            "direction": str(self.direction),
            "topology_arc_id": str(self.topology_arc_id),
            "topology_arc_source_type": str(self.topology_arc_source_type),
            "topology_arc_edge_ids": [str(v) for v in self.topology_arc_edge_ids],
            "topology_arc_node_path": [int(v) for v in self.topology_arc_node_path],
            "topology_arc_is_direct_legal": bool(self.topology_arc_is_direct_legal),
            "topology_arc_is_unique": bool(self.topology_arc_is_unique),
            "bridge_candidate_retained": bool(self.bridge_candidate_retained),
            "bridge_chain_exists": bool(self.bridge_chain_exists),
            "bridge_chain_unique": bool(self.bridge_chain_unique),
            "bridge_chain_nodes": [int(v) for v in self.bridge_chain_nodes],
            "bridge_chain_source": str(self.bridge_chain_source),
            "bridge_diagnostic_reason": str(self.bridge_diagnostic_reason),
            "bridge_decision_stage": str(self.bridge_decision_stage),
            "bridge_decision_reason": str(self.bridge_decision_reason),
            "geometry_coords": [[float(x), float(y)] for x, y in self.geometry_coords],
            "candidate_ids": [str(v) for v in self.candidate_ids],
            "source_modes": [str(v) for v in self.source_modes],
            "support_traj_ids": [str(v) for v in self.support_traj_ids],
            "support_count": int(self.support_count),
            "dedup_count": int(self.dedup_count),
            "representative_offset_m": float(self.representative_offset_m),
            "other_xsec_crossing_count": int(self.other_xsec_crossing_count),
            "tolerated_other_xsec_crossings": int(self.tolerated_other_xsec_crossings),
            "prior_supported": bool(self.prior_supported),
            "formation_reason": str(self.formation_reason),
            "length_m": float(self.length_m),
            "drivezone_ratio": float(self.drivezone_ratio),
            "crosses_divstrip": bool(self.crosses_divstrip),
            "same_pair_rank": None if self.same_pair_rank is None else int(self.same_pair_rank),
            "kept_reason": str(self.kept_reason),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Segment":
        coords = tuple((float(x), float(y)) for x, y in payload.get("geometry_coords", []))
        return cls(
            segment_id=str(payload.get("segment_id")),
            src_nodeid=int(payload.get("src_nodeid")),
            dst_nodeid=int(payload.get("dst_nodeid")),
            direction=str(payload.get("direction", "src->dst")),
            topology_arc_id=str(payload.get("topology_arc_id", "")),
            topology_arc_source_type=str(payload.get("topology_arc_source_type", "")),
            topology_arc_edge_ids=tuple(str(v) for v in payload.get("topology_arc_edge_ids", [])),
            topology_arc_node_path=tuple(int(v) for v in payload.get("topology_arc_node_path", [])),
            topology_arc_is_direct_legal=bool(payload.get("topology_arc_is_direct_legal", False)),
            topology_arc_is_unique=bool(payload.get("topology_arc_is_unique", False)),
            bridge_candidate_retained=bool(payload.get("bridge_candidate_retained", False)),
            bridge_chain_exists=bool(payload.get("bridge_chain_exists", False)),
            bridge_chain_unique=bool(payload.get("bridge_chain_unique", False)),
            bridge_chain_nodes=tuple(int(v) for v in payload.get("bridge_chain_nodes", [])),
            bridge_chain_source=str(payload.get("bridge_chain_source", "")),
            bridge_diagnostic_reason=str(payload.get("bridge_diagnostic_reason", "")),
            bridge_decision_stage=str(payload.get("bridge_decision_stage", "")),
            bridge_decision_reason=str(payload.get("bridge_decision_reason", "")),
            geometry_coords=coords,
            candidate_ids=tuple(str(v) for v in payload.get("candidate_ids", [])),
            source_modes=tuple(str(v) for v in payload.get("source_modes", [])),
            support_traj_ids=tuple(str(v) for v in payload.get("support_traj_ids", [])),
            support_count=int(payload.get("support_count", 0)),
            dedup_count=int(payload.get("dedup_count", 1)),
            representative_offset_m=float(payload.get("representative_offset_m", 0.0)),
            other_xsec_crossing_count=int(payload.get("other_xsec_crossing_count", 0)),
            tolerated_other_xsec_crossings=int(payload.get("tolerated_other_xsec_crossings", 1)),
            prior_supported=bool(payload.get("prior_supported", False)),
            formation_reason=str(payload.get("formation_reason", "")),
            length_m=float(payload.get("length_m", 0.0)),
            drivezone_ratio=float(payload.get("drivezone_ratio", 0.0)),
            crosses_divstrip=bool(payload.get("crosses_divstrip", False)),
            same_pair_rank=(None if payload.get("same_pair_rank") is None else int(payload.get("same_pair_rank"))),
            kept_reason=str(payload.get("kept_reason", "")),
        )


@dataclass(frozen=True)
class CorridorWitness:
    segment_id: str
    status: str
    reason: str
    line_coords: Coords2D
    sample_s_norm: float
    intervals: tuple[CorridorInterval, ...]
    selected_interval_rank: int | None
    selected_interval_start_s: float | None
    selected_interval_end_s: float | None
    exclusive_interval: bool
    stability_score: float
    neighbor_match_count: int
    axis_vector: tuple[float, float]

    def geometry_metric(self) -> LineString:
        return coords_to_line(self.line_coords)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": str(self.segment_id),
            "status": str(self.status),
            "reason": str(self.reason),
            "line_coords": [[float(x), float(y)] for x, y in self.line_coords],
            "sample_s_norm": float(self.sample_s_norm),
            "intervals": [it.to_dict() for it in self.intervals],
            "selected_interval_rank": None if self.selected_interval_rank is None else int(self.selected_interval_rank),
            "selected_interval_start_s": self.selected_interval_start_s,
            "selected_interval_end_s": self.selected_interval_end_s,
            "exclusive_interval": bool(self.exclusive_interval),
            "stability_score": float(self.stability_score),
            "neighbor_match_count": int(self.neighbor_match_count),
            "axis_vector": [float(self.axis_vector[0]), float(self.axis_vector[1])],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CorridorWitness":
        coords = tuple((float(x), float(y)) for x, y in payload.get("line_coords", []))
        axis_vec_raw = payload.get("axis_vector") or [0.0, 1.0]
        return cls(
            segment_id=str(payload.get("segment_id")),
            status=str(payload.get("status", "insufficient")),
            reason=str(payload.get("reason", "")),
            line_coords=coords,
            sample_s_norm=float(payload.get("sample_s_norm", 0.5)),
            intervals=tuple(CorridorInterval.from_dict(it) for it in payload.get("intervals", [])),
            selected_interval_rank=(
                None if payload.get("selected_interval_rank") is None else int(payload.get("selected_interval_rank"))
            ),
            selected_interval_start_s=payload.get("selected_interval_start_s"),
            selected_interval_end_s=payload.get("selected_interval_end_s"),
            exclusive_interval=bool(payload.get("exclusive_interval", False)),
            stability_score=float(payload.get("stability_score", 0.0)),
            neighbor_match_count=int(payload.get("neighbor_match_count", 0)),
            axis_vector=(float(axis_vec_raw[0]), float(axis_vec_raw[1])),
        )


@dataclass(frozen=True)
class CorridorIdentity:
    segment_id: str
    state: str
    reason: str
    risk_flags: tuple[str, ...]
    witness_interval_rank: int | None
    prior_supported: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": str(self.segment_id),
            "state": str(self.state),
            "reason": str(self.reason),
            "risk_flags": [str(v) for v in self.risk_flags],
            "witness_interval_rank": None if self.witness_interval_rank is None else int(self.witness_interval_rank),
            "prior_supported": bool(self.prior_supported),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CorridorIdentity":
        return cls(
            segment_id=str(payload.get("segment_id")),
            state=str(payload.get("state", "unresolved")),
            reason=str(payload.get("reason", "")),
            risk_flags=tuple(str(v) for v in payload.get("risk_flags", [])),
            witness_interval_rank=(
                None if payload.get("witness_interval_rank") is None else int(payload.get("witness_interval_rank"))
            ),
            prior_supported=bool(payload.get("prior_supported", False)),
        )


@dataclass(frozen=True)
class SlotInterval:
    segment_id: str
    endpoint_tag: str
    xsec_nodeid: int
    xsec_coords: Coords2D
    interval: CorridorInterval | None
    resolved: bool
    method: str
    reason: str
    interval_count: int

    def xsec_metric(self) -> LineString:
        return coords_to_line(self.xsec_coords)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": str(self.segment_id),
            "endpoint_tag": str(self.endpoint_tag),
            "xsec_nodeid": int(self.xsec_nodeid),
            "xsec_coords": [[float(x), float(y)] for x, y in self.xsec_coords],
            "interval": None if self.interval is None else self.interval.to_dict(),
            "resolved": bool(self.resolved),
            "method": str(self.method),
            "reason": str(self.reason),
            "interval_count": int(self.interval_count),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SlotInterval":
        xsec_coords = tuple((float(x), float(y)) for x, y in payload.get("xsec_coords", []))
        interval_payload = payload.get("interval")
        return cls(
            segment_id=str(payload.get("segment_id")),
            endpoint_tag=str(payload.get("endpoint_tag")),
            xsec_nodeid=int(payload.get("xsec_nodeid")),
            xsec_coords=xsec_coords,
            interval=None if not isinstance(interval_payload, dict) else CorridorInterval.from_dict(interval_payload),
            resolved=bool(payload.get("resolved", False)),
            method=str(payload.get("method", "unresolved")),
            reason=str(payload.get("reason", "")),
            interval_count=int(payload.get("interval_count", 0)),
        )


@dataclass(frozen=True)
class FinalRoad:
    road_id: str
    segment_id: str
    src_nodeid: int
    dst_nodeid: int
    corridor_state: str
    line_coords: Coords2D
    length_m: float
    support_traj_count: int
    dedup_count: int
    risk_flags: tuple[str, ...]

    def geometry_metric(self) -> LineString:
        return coords_to_line(self.line_coords)

    def to_dict(self) -> dict[str, Any]:
        return {
            "road_id": str(self.road_id),
            "segment_id": str(self.segment_id),
            "src_nodeid": int(self.src_nodeid),
            "dst_nodeid": int(self.dst_nodeid),
            "corridor_state": str(self.corridor_state),
            "line_coords": [[float(x), float(y)] for x, y in self.line_coords],
            "length_m": float(self.length_m),
            "support_traj_count": int(self.support_traj_count),
            "dedup_count": int(self.dedup_count),
            "risk_flags": [str(v) for v in self.risk_flags],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FinalRoad":
        coords = tuple((float(x), float(y)) for x, y in payload.get("line_coords", []))
        return cls(
            road_id=str(payload.get("road_id")),
            segment_id=str(payload.get("segment_id")),
            src_nodeid=int(payload.get("src_nodeid")),
            dst_nodeid=int(payload.get("dst_nodeid")),
            corridor_state=str(payload.get("corridor_state", "unresolved")),
            line_coords=coords,
            length_m=float(payload.get("length_m", 0.0)),
            support_traj_count=int(payload.get("support_traj_count", 0)),
            dedup_count=int(payload.get("dedup_count", 1)),
            risk_flags=tuple(str(v) for v in payload.get("risk_flags", [])),
        )
