from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .normalize import normalize_node_features


def load_geojson_feature_collection(path: str | Path) -> list[dict[str, Any]]:
    resolved = Path(path)
    if not resolved.exists():
        raise ValueError(f"geojson_file_not_found:{resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"geojson_file_invalid_json:{resolved}:{exc.msg}") from exc
    except OSError as exc:
        raise ValueError(f"geojson_file_read_error:{resolved}:{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"geojson_payload_must_be_object:{resolved}")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError(f"geojson_features_must_be_list:{resolved}")
    return features


def discover_patch_dir_inputs(patch_dir: str | Path) -> tuple[Path, Path]:
    resolved = Path(patch_dir)
    if not resolved.exists():
        raise ValueError(f"patch_dir_not_found:{resolved}")
    if not resolved.is_dir():
        raise ValueError(f"patch_dir_not_directory:{resolved}")

    complete_layouts: list[tuple[Path, Path]] = []
    partial_layouts: list[str] = []
    candidate_layouts = [
        ("vector", resolved / "Vector" / "RCSDNode.geojson", resolved / "Vector" / "RCSDRoad.geojson"),
        ("direct", resolved / "RCSDNode.geojson", resolved / "RCSDRoad.geojson"),
    ]
    for layout_name, node_path, road_path in candidate_layouts:
        node_exists = node_path.is_file()
        road_exists = road_path.is_file()
        if node_exists and road_exists:
            complete_layouts.append((node_path, road_path))
            continue
        if node_exists or road_exists:
            partial_layouts.append(
                f"{layout_name}:node={str(node_exists).lower()},road={str(road_exists).lower()}"
            )

    if len(complete_layouts) == 1:
        return complete_layouts[0]
    if len(complete_layouts) > 1:
        raise ValueError(f"patch_dir_layout_ambiguous:{resolved}")

    partial_text = ",".join(partial_layouts) if partial_layouts else "none"
    raise ValueError(f"patch_dir_missing_required_files:{resolved}:partials={partial_text}")


def discover_geojson_dataset_inputs(dataset_dir: str | Path) -> tuple[Path, Path]:
    resolved = Path(dataset_dir)
    if not resolved.exists():
        raise ValueError(f"dataset_dir_not_found:{resolved}")
    if not resolved.is_dir():
        raise ValueError(f"dataset_dir_not_directory:{resolved}")

    complete_layouts: list[tuple[Path, Path]] = []
    partial_layouts: list[str] = []
    candidate_layouts = [
        ("vector", resolved / "Vector" / "RCSDNode.geojson", resolved / "Vector" / "RCSDRoad.geojson"),
        ("direct", resolved / "RCSDNode.geojson", resolved / "RCSDRoad.geojson"),
    ]
    for layout_name, node_path, road_path in candidate_layouts:
        node_exists = node_path.is_file()
        road_exists = road_path.is_file()
        if node_exists and road_exists:
            complete_layouts.append((node_path, road_path))
            continue
        if node_exists or road_exists:
            partial_layouts.append(
                f"{layout_name}:node={str(node_exists).lower()},road={str(road_exists).lower()}"
            )

    if len(complete_layouts) == 1:
        return complete_layouts[0]
    if len(complete_layouts) > 1:
        raise ValueError(f"dataset_dir_layout_ambiguous:{resolved}")

    recursive_pairs = _discover_recursive_geojson_pairs(resolved)
    if len(recursive_pairs) == 1:
        return recursive_pairs[0]
    if len(recursive_pairs) > 1:
        pair_text = ",".join(str(node_path.parent) for node_path, _ in recursive_pairs)
        raise ValueError(f"dataset_dir_layout_ambiguous:{resolved}:candidates={pair_text}")

    partial_text = ",".join(partial_layouts) if partial_layouts else "none"
    raise ValueError(f"dataset_dir_missing_required_files:{resolved}:partials={partial_text}")


def coerce_mainid_value(raw: Any) -> Any | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("-") and text[1:].isdigit():
        return int(text)
    if text.isdigit():
        return int(text)
    return text


def parse_mainid_values(raw_values: list[Any] | tuple[Any, ...] | None) -> tuple[Any, ...]:
    if raw_values is None:
        return ()
    parsed: list[Any] = []
    for raw in raw_values:
        if raw is None:
            continue
        for piece in str(raw).split(","):
            coerced = coerce_mainid_value(piece)
            if coerced is None:
                continue
            parsed.append(coerced)
    return tuple(parsed)


def list_available_mainids(node_features: list[dict[str, Any]]) -> list[Any]:
    normalized_nodes = normalize_node_features(node_features)
    if not normalized_nodes:
        raise ValueError("node_feature_collection_empty")
    return sorted({node.mainid for node in normalized_nodes}, key=str)


def select_single_intersection_node_features(
    node_features: list[dict[str, Any]],
    *,
    mainid: Any | None = None,
) -> tuple[list[dict[str, Any]], Any, list[Any]]:
    normalized_nodes = normalize_node_features(node_features)
    if not normalized_nodes:
        raise ValueError("node_feature_collection_empty")
    available_mainids = list_available_mainids(node_features)
    if mainid is None:
        if len(available_mainids) != 1:
            available_text = ",".join(str(item) for item in available_mainids)
            raise ValueError(f"multiple_mainids_in_node_file:{available_text}")
        selected_mainid = available_mainids[0]
    else:
        selected_mainid = mainid
        if selected_mainid not in set(available_mainids):
            available_text = ",".join(str(item) for item in available_mainids)
            raise ValueError(f"requested_mainid_not_found:{selected_mainid}:available={available_text}")

    selected_node_ids = {node.node_id for node in normalized_nodes if node.mainid == selected_mainid}
    selected_features = [
        feature
        for feature, normalized in zip(node_features, normalized_nodes, strict=True)
        if normalized.node_id in selected_node_ids
    ]
    return selected_features, selected_mainid, available_mainids


def _discover_recursive_geojson_pairs(root_dir: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for node_path in root_dir.rglob("RCSDNode.geojson"):
        road_path = node_path.with_name("RCSDRoad.geojson")
        if road_path.is_file():
            pairs.append((node_path, road_path))
    return sorted(set(pairs), key=lambda pair: str(pair[0]))


__all__ = [
    "coerce_mainid_value",
    "discover_geojson_dataset_inputs",
    "discover_patch_dir_inputs",
    "list_available_mainids",
    "load_geojson_feature_collection",
    "parse_mainid_values",
    "select_single_intersection_node_features",
]
