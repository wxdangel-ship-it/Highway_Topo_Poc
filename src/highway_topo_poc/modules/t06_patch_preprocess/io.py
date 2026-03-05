from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry


_NODE_PRIMARY_NAME = "RCSDNode.geojson"
_NODE_FALLBACK_NAME = "Node.geojson"
_ROAD_PRIMARY_NAME = "RCSDRoad.geojson"
_ROAD_FALLBACK_NAME = "Road.geojson"
_DEFAULT_DRIVEZONE_NAME = "DriveZone.geojson"


class InputDataError(ValueError):
    pass


@dataclass(frozen=True)
class NodeFeature:
    feature_index: int
    properties: dict[str, Any]
    geometry: BaseGeometry


@dataclass(frozen=True)
class RoadFeature:
    feature_index: int
    properties: dict[str, Any]
    geometry: BaseGeometry


@dataclass(frozen=True)
class LoadedInputs:
    patch_id: str
    patch_dir: Path
    node_path: Path
    road_path: Path
    drivezone_path: Path
    node_crs: str
    road_crs: str
    drivezone_crs: str
    nodes: list[NodeFeature]
    roads: list[RoadFeature]
    drivezones: list[BaseGeometry]
    node_source_note: str | None
    road_source_note: str | None
    drivezone_source_note: str | None


def resolve_repo_root(start: Path) -> Path:
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / "SPEC.md").is_file() and (cand / "src").is_dir():
            return cand
    return p


def git_short_sha(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or "unknown"
    except Exception:
        return "unknown"


def make_run_id(prefix: str, *, repo_root: Path, patch_id: str | None = None) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sha = git_short_sha(repo_root)
    if patch_id:
        return f"{ts}_{prefix}_{patch_id}_{sha}"
    return f"{ts}_{prefix}_{sha}"


def _read_geojson(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InputDataError(f"file_not_found: {path}") from exc
    except Exception as exc:
        raise InputDataError(f"file_not_json: {path}") from exc
    if payload.get("type") != "FeatureCollection":
        raise InputDataError(f"not_feature_collection: {path}")
    return payload


def _extract_crs_name(payload: dict[str, Any], *, path: Path, allow_missing: bool = False) -> str | None:
    crs_obj = payload.get("crs")
    if crs_obj is None:
        if allow_missing:
            return None
        raise InputDataError(f"crs_missing: {path}")
    if isinstance(crs_obj, str):
        text = crs_obj.strip()
        if not text:
            if allow_missing:
                return None
            raise InputDataError(f"crs_name_missing: {path}")
        # Some datasets store CRS object as a JSON string; decode it before extraction.
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                crs_obj = parsed
            else:
                return text
        else:
            return text

    if isinstance(crs_obj, dict):
        props = crs_obj.get("properties")
        if isinstance(props, dict):
            name = props.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        alt_name = crs_obj.get("name")
        if isinstance(alt_name, str) and alt_name.strip():
            return alt_name.strip()
        if allow_missing:
            return None
        if not isinstance(props, dict):
            raise InputDataError(f"crs_missing_properties: {path}")
        raise InputDataError(f"crs_name_missing: {path}")

    if allow_missing:
        return None
    raise InputDataError(f"crs_missing: {path}")


def _resolve_patch_dir(data_root: Path, patch: str | None) -> Path:
    if not data_root.exists() or not data_root.is_dir():
        raise InputDataError(f"data_root_not_found: {data_root}")

    patch_arg = (patch or "auto").strip()
    if patch_arg.lower() == "auto":
        if (data_root / "Vector").is_dir():
            return data_root
        candidates = sorted(p for p in data_root.iterdir() if p.is_dir() and (p / "Vector").is_dir())
        if not candidates:
            raise InputDataError(f"patch_auto_no_candidate_under: {data_root}")
        if len(candidates) > 1:
            names = ", ".join(p.name for p in candidates[:10])
            raise InputDataError(f"patch_auto_ambiguous_under: {data_root} candidates={names}")
        return candidates[0]

    cand = data_root / patch_arg
    if (cand / "Vector").is_dir():
        return cand
    if (data_root / "Vector").is_dir() and data_root.name == patch_arg:
        return data_root
    raise InputDataError(f"patch_not_found: {patch_arg} under {data_root}")


def _resolve_vector_primary(
    *,
    vector_dir: Path,
    primary_name: str,
    fallback_name: str,
) -> Path | None:
    p0 = vector_dir / primary_name
    if p0.is_file():
        return p0
    p1 = vector_dir / fallback_name
    if p1.is_file():
        return p1
    return None


def _resolve_node_road_paths(patch_dir: Path, data_root: Path) -> tuple[Path, Path, str | None, str | None]:
    vector_dir = patch_dir / "Vector"
    node_p = _resolve_vector_primary(
        vector_dir=vector_dir,
        primary_name=_NODE_PRIMARY_NAME,
        fallback_name=_NODE_FALLBACK_NAME,
    )
    road_p = _resolve_vector_primary(
        vector_dir=vector_dir,
        primary_name=_ROAD_PRIMARY_NAME,
        fallback_name=_ROAD_FALLBACK_NAME,
    )
    if node_p and road_p:
        return node_p, road_p, None, None

    global_candidates: list[Path] = []
    for root in [patch_dir.parent, data_root, data_root.parent]:
        g = root / "global"
        if g.is_dir():
            global_candidates.append(g)
    seen = set()
    global_candidates = [p for p in global_candidates if not (str(p) in seen or seen.add(str(p)))]

    resolved: list[tuple[Path, Path]] = []
    for gdir in global_candidates:
        gn = gdir / _NODE_PRIMARY_NAME
        gr = gdir / _ROAD_PRIMARY_NAME
        if gn.is_file() and gr.is_file():
            resolved.append((gn, gr))

    if len(resolved) == 1:
        gn, gr = resolved[0]
        note = f"fallback_global_dir:{gn.parent}"
        return gn, gr, note, note

    missing_items = []
    if node_p is None:
        missing_items.append(_NODE_PRIMARY_NAME)
    if road_p is None:
        missing_items.append(_ROAD_PRIMARY_NAME)
    raise InputDataError(
        "node_road_missing_in_patch_vector: "
        f"patch_dir={patch_dir} missing={missing_items} global_fallback_candidates={len(resolved)}"
    )


def _resolve_drivezone_path(
    *,
    patch_dir: Path,
    override: str | None,
) -> tuple[Path, str | None]:
    if override:
        p = Path(override)
        if not p.is_absolute():
            p = (patch_dir / p).resolve()
        if not p.is_file():
            raise InputDataError(f"drivezone_override_not_found: {p}")
        return p, "override"

    vector_dir = patch_dir / "Vector"
    default = vector_dir / _DEFAULT_DRIVEZONE_NAME
    if default.is_file():
        return default, None

    if not vector_dir.is_dir():
        raise InputDataError(f"vector_dir_not_found: {vector_dir}")

    compat_candidates = sorted(
        p
        for p in vector_dir.iterdir()
        if p.is_file()
        and (
            (p.suffix.lower() == ".geojson" and "drivezone" in p.stem.lower())
            or p.suffix.lower() == ".gpkg"
        )
    )

    if not compat_candidates:
        raise InputDataError(
            "drivezone_missing: expected Vector/DriveZone.geojson or exactly one compatible "
            "*DriveZone*.geojson/*.gpkg"
        )
    if len(compat_candidates) > 1:
        names = ", ".join(p.name for p in compat_candidates)
        raise InputDataError(f"drivezone_ambiguous: {names}")

    chosen = compat_candidates[0]
    if chosen.suffix.lower() == ".gpkg":
        raise InputDataError(
            f"drivezone_gpkg_not_supported_in_runtime: {chosen} (install gpkg reader or use GeoJSON)"
        )
    return chosen, f"compat_auto:{chosen.name}"


def _load_nodes(path: Path) -> tuple[list[NodeFeature], str]:
    payload = _read_geojson(path)
    crs_name = _extract_crs_name(payload, path=path)
    out: list[NodeFeature] = []
    for i, feat in enumerate(payload.get("features", [])):
        if not isinstance(feat, dict):
            continue
        geom_obj = feat.get("geometry")
        props = feat.get("properties") or {}
        if geom_obj is None:
            continue
        geom = shape(geom_obj)
        if geom.is_empty:
            continue
        if geom.geom_type != "Point":
            raise InputDataError(f"node_geometry_not_point: {path} feature_index={i} geom_type={geom.geom_type}")
        out.append(NodeFeature(feature_index=i, properties=dict(props), geometry=geom))
    return out, crs_name


def _load_roads(path: Path) -> tuple[list[RoadFeature], str]:
    payload = _read_geojson(path)
    crs_name = _extract_crs_name(payload, path=path)
    out: list[RoadFeature] = []
    for i, feat in enumerate(payload.get("features", [])):
        if not isinstance(feat, dict):
            continue
        geom_obj = feat.get("geometry")
        props = feat.get("properties") or {}
        if geom_obj is None:
            continue
        geom = shape(geom_obj)
        if geom.is_empty:
            continue
        if geom.geom_type not in {"LineString", "MultiLineString"}:
            raise InputDataError(
                f"road_geometry_not_linear: {path} feature_index={i} geom_type={geom.geom_type}"
            )
        out.append(RoadFeature(feature_index=i, properties=dict(props), geometry=geom))
    return out, crs_name


def _load_drivezone(path: Path) -> tuple[list[BaseGeometry], str | None]:
    payload = _read_geojson(path)
    crs_name = _extract_crs_name(payload, path=path, allow_missing=True)
    out: list[BaseGeometry] = []
    for i, feat in enumerate(payload.get("features", [])):
        if not isinstance(feat, dict):
            continue
        geom_obj = feat.get("geometry")
        if geom_obj is None:
            continue
        geom = shape(geom_obj)
        if geom.is_empty:
            continue
        if geom.geom_type not in {"Polygon", "MultiPolygon"}:
            raise InputDataError(
                f"drivezone_geometry_not_polygon: {path} feature_index={i} geom_type={geom.geom_type}"
            )
        out.append(geom)
    return out, crs_name


def load_inputs(
    *,
    data_root: Path | str,
    patch: str | None,
    drivezone_override: str | None,
) -> LoadedInputs:
    root = Path(data_root)
    patch_dir = _resolve_patch_dir(root, patch)

    node_path, road_path, node_note, road_note = _resolve_node_road_paths(patch_dir, root)
    drivezone_path, drivezone_note = _resolve_drivezone_path(
        patch_dir=patch_dir,
        override=drivezone_override,
    )

    nodes, node_crs = _load_nodes(node_path)
    roads, road_crs = _load_roads(road_path)
    drivezones, drivezone_crs = _load_drivezone(drivezone_path)

    if drivezone_crs is None:
        if node_crs == road_crs:
            drivezone_crs = node_crs
            compat_note = f"crs_fallback_from_node_road:{drivezone_crs}"
            drivezone_note = f"{drivezone_note};{compat_note}" if drivezone_note else compat_note
        else:
            raise InputDataError(
                "drivezone_crs_missing_and_node_road_crs_mismatch: "
                f"node_crs={node_crs} road_crs={road_crs} path={drivezone_path}"
            )

    if not nodes:
        raise InputDataError(f"node_empty: {node_path}")
    if not roads:
        raise InputDataError(f"road_empty: {road_path}")
    if not drivezones:
        raise InputDataError(f"drivezone_empty: {drivezone_path}")

    return LoadedInputs(
        patch_id=patch_dir.name,
        patch_dir=patch_dir,
        node_path=node_path,
        road_path=road_path,
        drivezone_path=drivezone_path,
        node_crs=node_crs,
        road_crs=road_crs,
        drivezone_crs=drivezone_crs,
        nodes=nodes,
        roads=roads,
        drivezones=drivezones,
        node_source_note=node_note,
        road_source_note=road_note,
        drivezone_source_note=drivezone_note,
    )


def write_feature_collection(path: Path, *, crs_name: str, features: list[dict[str, Any]]) -> None:
    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": crs_name}},
        "features": features,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
