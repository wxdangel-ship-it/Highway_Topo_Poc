from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point, mapping

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
        "anchor_type": item.get("anchor_type"),
        "status": item.get("status"),
        "scan_dir": item.get("scan_dir"),
        "scan_dist_m": item.get("scan_dist_m"),
        "trigger": item.get("trigger"),
        "dist_to_divstrip_m": item.get("dist_to_divstrip_m"),
        "confidence": item.get("confidence"),
        "flags": item.get("flags", []),
    }


def write_anchor_geojson(
    *,
    path: Path,
    seed_results: list[dict[str, Any]],
    crs_name: str,
) -> None:
    features: list[dict[str, Any]] = []
    for item in seed_results:
        props = _props_min(item)

        pt = item.get("anchor_point")
        if isinstance(pt, Point):
            features.append(
                {
                    "type": "Feature",
                    "properties": {**props, "feature_role": "anchor_point"},
                    "geometry": mapping(pt),
                }
            )

        line = item.get("crossline_opt")
        if isinstance(line, LineString):
            features.append(
                {
                    "type": "Feature",
                    "properties": {**props, "feature_role": "crossline_opt"},
                    "geometry": mapping(line),
                }
            )

    write_geojson(path, make_feature_collection(features, crs_name=crs_name))


def write_intersection_opt_geojson(
    *,
    path: Path,
    seed_results: list[dict[str, Any]],
    crs_name: str,
) -> None:
    features: list[dict[str, Any]] = []
    for item in seed_results:
        line = item.get("crossline_opt")
        if not isinstance(line, LineString):
            continue
        props = _props_min(item)
        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": mapping(line),
            }
        )

    write_geojson(path, make_feature_collection(features, crs_name=crs_name))


__all__ = ["write_anchor_geojson", "write_intersection_opt_geojson", "write_json", "write_text"]
