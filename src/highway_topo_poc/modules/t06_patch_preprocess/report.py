from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReportBuilder:
    roads_in: int = 0
    roads_out: int = 0
    nodes_in: int = 0
    nodes_out: int = 0
    nodes_created: int = 0
    missing_endpoint_refs_in: int = 0
    missing_endpoint_refs_out: int = 0
    boundary_intersections_in: int = 0
    boundary_intersections_out: int = 0
    dropped_road_empty_count: int = 0
    clipped_road_count: int = 0
    updated_snodeid_count: int = 0
    updated_enodeid_count: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)
    fixed_roads: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_drop(self, reason: str) -> None:
        key = reason or "unknown"
        self.drop_reasons[key] = int(self.drop_reasons.get(key, 0) + 1)
        if key == "clipped_empty":
            self.dropped_road_empty_count += 1

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_fixed_road(self, detail: dict[str, Any]) -> None:
        self.fixed_roads.append(detail)

    def to_summary(
        self,
        *,
        patch_id: str,
        run_id: str,
        epsg_out: int,
        params: dict[str, Any],
        source_notes: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "patch_id": patch_id,
            "run_id": run_id,
            "roads_in": int(self.roads_in),
            "roads_out": int(self.roads_out),
            "nodes_in": int(self.nodes_in),
            "nodes_out": int(self.nodes_out),
            "nodes_created": int(self.nodes_created),
            "missing_endpoint_refs_in": int(self.missing_endpoint_refs_in),
            "missing_endpoint_refs_out": int(self.missing_endpoint_refs_out),
            "boundary_intersections_in": int(self.boundary_intersections_in),
            "boundary_intersections_out": int(self.boundary_intersections_out),
            "drop_reasons": dict(sorted(self.drop_reasons.items())),
            "dropped_road_empty_count": int(self.dropped_road_empty_count),
            "clipped_road_count": int(self.clipped_road_count),
            "updated_snodeid_count": int(self.updated_snodeid_count),
            "updated_enodeid_count": int(self.updated_enodeid_count),
            "target_epsg": int(epsg_out),
            "params": params,
            "source_notes": source_notes,
            "warnings": self.warnings,
            "ok": bool(self.missing_endpoint_refs_out == 0),
        }
