from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, MultiLineString, Point, mapping

from .crs_norm import transform_coords_recursive
from .io_geojson import make_feature_collection, write_geojson


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _props_min(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodeid": item.get("nodeid"),
        "id": item.get("id"),
        "mainid": item.get("mainid"),
        "mainnodeid": item.get("mainnodeid"),
        "kind": item.get("kind"),
        "is_merge_kind": item.get("is_merge_kind"),
        "is_diverge_kind": item.get("is_diverge_kind"),
        "kind_bits": {
            "merge": bool(item.get("is_merge_kind", False)),
            "diverge": bool(item.get("is_diverge_kind", False)),
        },
        "anchor_type": item.get("anchor_type"),
        "status": item.get("status"),
        "scan_dir": item.get("scan_dir"),
        "scan_dist_m": item.get("scan_dist_m"),
        "trigger": item.get("trigger"),
        "dist_to_divstrip_m": item.get("dist_to_divstrip_m"),
        "dist_line_to_divstrip_m": item.get("dist_line_to_divstrip_m"),
        "dist_line_to_drivezone_edge_m": item.get("dist_line_to_drivezone_edge_m"),
        "confidence": item.get("confidence"),
        "flags": item.get("flags", []),
        "evidence_source": item.get("evidence_source"),
        "resolved_from": item.get("resolved_from"),
        "tip_s_m": item.get("tip_s_m"),
        "first_divstrip_hit_dist_m": item.get("first_divstrip_hit_dist_m"),
        "best_divstrip_dz_dist_m": item.get("best_divstrip_dz_dist_m"),
        "best_divstrip_pc_dist_m": item.get("best_divstrip_pc_dist_m"),
        "first_pc_only_dist_m": item.get("first_pc_only_dist_m"),
        "fan_area_m2": item.get("fan_area_m2"),
        "non_drivezone_area_m2": item.get("non_drivezone_area_m2"),
        "non_drivezone_frac": item.get("non_drivezone_frac"),
        "clipped_len_m": item.get("clipped_len_m"),
        "clip_empty": item.get("clip_empty"),
        "clip_piece_type": item.get("clip_piece_type"),
        "stop_reason": item.get("stop_reason"),
    }


def _transform_geometry_dict(geom: dict[str, Any], *, src_crs: str, dst_crs: str) -> dict[str, Any]:
    if src_crs == dst_crs:
        return geom
    out = dict(geom)
    if "coordinates" in out:
        out["coordinates"] = transform_coords_recursive(out["coordinates"], src_crs, dst_crs)
    return out


def write_anchor_geojson(
    *,
    path: Path,
    seed_results: list[dict[str, Any]],
    src_crs_name: str,
    dst_crs_name: str,
) -> None:
    features: list[dict[str, Any]] = []
    for item in seed_results:
        props = _props_min(item)

        pt = item.get("anchor_point")
        if isinstance(pt, Point):
            geom = mapping(pt)
            geom = _transform_geometry_dict(geom, src_crs=src_crs_name, dst_crs=dst_crs_name)
            features.append(
                {
                    "type": "Feature",
                    "properties": {**props, "feature_role": "anchor_point"},
                    "geometry": geom,
                }
            )

        line = item.get("crossline_opt")
        if isinstance(line, (LineString, MultiLineString)):
            geom = mapping(line)
            geom = _transform_geometry_dict(geom, src_crs=src_crs_name, dst_crs=dst_crs_name)
            features.append(
                {
                    "type": "Feature",
                    "properties": {**props, "feature_role": "crossline_opt"},
                    "geometry": geom,
                }
            )

    write_geojson(path, make_feature_collection(features, crs_name=dst_crs_name))


def write_intersection_opt_geojson(
    *,
    path: Path,
    seed_results: list[dict[str, Any]],
    src_crs_name: str,
    dst_crs_name: str,
) -> None:
    features: list[dict[str, Any]] = []
    for item in seed_results:
        line = item.get("crossline_opt")
        if not isinstance(line, (LineString, MultiLineString)):
            continue
        props = _props_min(item)
        geom = mapping(line)
        geom = _transform_geometry_dict(geom, src_crs=src_crs_name, dst_crs=dst_crs_name)
        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": geom,
            }
        )

    write_geojson(path, make_feature_collection(features, crs_name=dst_crs_name))


__all__ = ["write_anchor_geojson", "write_intersection_opt_geojson", "write_json", "write_text"]
