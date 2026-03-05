from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry import Point, mapping

from . import geom
from .io import InputDataError, LoadedInputs, NodeFeature, RoadFeature, load_inputs, make_run_id, resolve_repo_root, write_feature_collection, write_json
from .report import ReportBuilder

DEFAULT_PARAMS: dict[str, Any] = {
    "TARGET_EPSG": 3857,
    "ENDPOINT_CHANGE_TOL_M": geom.ENDPOINT_CHANGE_TOL_M,
    "SNAP_TOL_M": geom.SNAP_TOL_M,
    "BIT16_VALUE": geom.BIT16_VALUE,
    "MISSING_ENDPOINT_DETECT_MODE": "by_id_membership",
    "CLIP_MODE": "intersection_keep_inside",
    "KEEP_SEGMENT_MODE": "connect_existing_endpoint",
}

_ID_FIELD_CANDIDATES = ["id", "nodeid", "mainid"]
_KIND_FIELD_CANDIDATES = ["Kind", "kind"]
_MAINID_FIELD_CANDIDATES = ["mainid", "MainId", "MAINID"]
_ROAD_ID_FIELD_CANDIDATES = ["id", "mainid", "roadid"]
_SNODE_FIELD_CANDIDATES = ["snodeid", "src", "from", "start_id"]
_ENODE_FIELD_CANDIDATES = ["enodeid", "dst", "to", "end_id"]


@dataclass(frozen=True)
class RunResult:
    run_id: str
    patch_id: str
    output_dir: Path
    summary_path: Path
    drop_reasons_path: Path


@dataclass
class _ProjectedNode:
    properties: dict[str, Any]
    geometry: Point


@dataclass
class _ProjectedRoad:
    feature_index: int
    properties: dict[str, Any]
    geometry: Any


@dataclass
class _NodeCreateContext:
    id_field: str
    id_is_int: bool
    kind_field: str | None
    mainid_field: str | None
    schema_keys: list[str]


def _infer_required_field(features: list[dict[str, Any]], candidates: list[str], *, label: str) -> str:
    for name in candidates:
        if all(name in props for props in features):
            return name
    for name in candidates:
        if any(name in props for props in features):
            return name
    raise InputDataError(f"required_field_missing:{label} candidates={candidates}")


def _infer_optional_field(features: list[dict[str, Any]], candidates: list[str]) -> str | None:
    for name in candidates:
        if any(name in props for props in features):
            return name
    return None


def _project_inputs(loaded: LoadedInputs, *, target_epsg: int) -> tuple[list[_ProjectedNode], list[_ProjectedRoad], list[Any], dict[str, Any]]:
    node_tf, node_clamp = geom.build_transformer(loaded.node_crs, target_epsg)
    road_tf, road_clamp = geom.build_transformer(loaded.road_crs, target_epsg)
    zone_tf, zone_clamp = geom.build_transformer(loaded.drivezone_crs, target_epsg)

    nodes: list[_ProjectedNode] = []
    roads: list[_ProjectedRoad] = []
    zones: list[Any] = []

    clamp_count = 0

    for n in loaded.nodes:
        g = geom.project_geometry(n.geometry, transformer=node_tf, clamp_geographic=node_clamp)
        if node_clamp:
            clamp_count += 1
        if g.geom_type != "Point":
            raise InputDataError("projected_node_not_point")
        nodes.append(_ProjectedNode(properties=dict(n.properties), geometry=g))

    for r in loaded.roads:
        g = geom.project_geometry(r.geometry, transformer=road_tf, clamp_geographic=road_clamp)
        if road_clamp:
            clamp_count += 1
        roads.append(_ProjectedRoad(feature_index=r.feature_index, properties=dict(r.properties), geometry=g))

    for z in loaded.drivezones:
        g = geom.project_geometry(z, transformer=zone_tf, clamp_geographic=zone_clamp)
        if zone_clamp:
            clamp_count += 1
        zones.append(g)

    return nodes, roads, zones, {"projection_clamp_applied_count": int(clamp_count)}


def _road_primary_id(props: dict[str, Any], *, feature_index: int) -> Any:
    for f in _ROAD_ID_FIELD_CANDIDATES:
        if f in props:
            return props[f]
    return feature_index


def _build_virtual_node_properties(
    *,
    node_ctx: _NodeCreateContext,
    node_id: Any,
) -> dict[str, Any]:
    props = {k: None for k in node_ctx.schema_keys}
    props[node_ctx.id_field] = node_id
    if node_ctx.mainid_field is not None:
        props[node_ctx.mainid_field] = -1
    if node_ctx.kind_field is not None:
        props[node_ctx.kind_field] = int(geom.BIT16_VALUE)
    return props


def run_patch(
    *,
    data_root: str | Path,
    patch: str | None = None,
    run_id: str | None = None,
    out_root: str | Path = "outputs/_work/t06_patch_preprocess",
    overwrite: bool = True,
    verbose: bool = False,
    drivezone: str | None = None,
) -> RunResult:
    del verbose
    repo_root = resolve_repo_root(Path.cwd())
    loaded = load_inputs(data_root=data_root, patch=patch, drivezone_override=drivezone)

    target_epsg = int(DEFAULT_PARAMS["TARGET_EPSG"])
    rid = run_id if (run_id and str(run_id).strip() and str(run_id).lower() != "auto") else make_run_id("t06", repo_root=repo_root, patch_id=loaded.patch_id)

    output_dir = Path(out_root) / rid
    if overwrite and output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "Vector").mkdir(parents=True, exist_ok=True)
    (output_dir / "report").mkdir(parents=True, exist_ok=True)
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)

    report = ReportBuilder()
    report.roads_in = len(loaded.roads)
    report.nodes_in = len(loaded.nodes)

    nodes, roads, zones, proj_notes = _project_inputs(loaded, target_epsg=target_epsg)

    node_props_list = [n.properties for n in nodes]
    road_props_list = [r.properties for r in roads]

    node_id_field = _infer_required_field(node_props_list, _ID_FIELD_CANDIDATES, label="node_id")
    road_s_field = _infer_required_field(road_props_list, _SNODE_FIELD_CANDIDATES, label="road_snodeid")
    road_e_field = _infer_required_field(road_props_list, _ENODE_FIELD_CANDIDATES, label="road_enodeid")
    kind_field = _infer_optional_field(node_props_list, _KIND_FIELD_CANDIDATES)
    mainid_field = _infer_optional_field(node_props_list, _MAINID_FIELD_CANDIDATES)

    node_schema_keys: list[str] = []
    seen_keys: set[str] = set()
    for props in node_props_list:
        for k in props.keys():
            if k not in seen_keys:
                seen_keys.add(k)
                node_schema_keys.append(k)
    if node_id_field not in seen_keys:
        node_schema_keys.append(node_id_field)

    node_ids_order: list[Any] = []
    node_by_id: dict[Any, _ProjectedNode] = {}
    for n in nodes:
        nid = n.properties.get(node_id_field)
        if nid is None:
            continue
        if nid not in node_by_id:
            node_by_id[nid] = n
            node_ids_order.append(nid)

    if not node_by_id:
        raise InputDataError("no_valid_node_id")

    first_id = node_ids_order[0]
    id_is_int = isinstance(first_id, int) and not isinstance(first_id, bool)

    node_ctx = _NodeCreateContext(
        id_field=node_id_field,
        id_is_int=id_is_int,
        kind_field=kind_field,
        mainid_field=mainid_field,
        schema_keys=node_schema_keys,
    )

    drivezone = geom.build_drivezone_union(zones)
    if drivezone.union_geom.is_empty:
        raise InputDataError("drivezone_union_empty")
    if drivezone.invalid_repair_count > 0:
        report.add_warning(f"drivezone_invalid_repaired={drivezone.invalid_repair_count}")

    existing_node_ids = set(node_by_id.keys())

    roads_missing_in = 0
    for r in roads:
        sid = r.properties.get(road_s_field)
        eid = r.properties.get(road_e_field)
        if sid not in existing_node_ids or eid not in existing_node_ids:
            roads_missing_in += 1
    report.missing_endpoint_refs_in = int(roads_missing_in)

    road_out_candidates: list[_ProjectedRoad] = []
    created_nodes: list[_ProjectedNode] = []

    for road in roads:
        s_id = road.properties.get(road_s_field)
        e_id = road.properties.get(road_e_field)
        src_exists = s_id in existing_node_ids
        dst_exists = e_id in existing_node_ids

        relation_in = geom.relation_to_zone(road.geometry, drivezone.union_geom)
        if relation_in == "boundary_intersection":
            report.boundary_intersections_in += 1

        if src_exists and dst_exists:
            road_out_candidates.append(_ProjectedRoad(feature_index=road.feature_index, properties=dict(road.properties), geometry=road.geometry))
            continue

        report.clipped_road_count += 1
        if (not src_exists) and (not dst_exists):
            report.add_drop("no_existing_endpoint_connected")
            continue

        orig_line = geom.choose_reference_line(road.geometry)
        if orig_line is None:
            report.add_drop("non_linear_input")
            continue

        src_node_pt = node_by_id[s_id].geometry if src_exists else None
        dst_node_pt = node_by_id[e_id].geometry if dst_exists else None

        p0, p1 = geom.line_endpoints(orig_line)
        orig_assign = geom.assign_original_sides(p0, p1, src_node=src_node_pt, dst_node=dst_node_pt)

        src_ref = src_node_pt if src_node_pt is not None else orig_assign.src_point
        dst_ref = dst_node_pt if dst_node_pt is not None else orig_assign.dst_point

        clipped = road.geometry.intersection(drivezone.union_geom)
        segments = geom.extract_linear_segments(clipped)
        choice = geom.choose_segment(
            segments=segments,
            src_exists=src_exists,
            dst_exists=dst_exists,
            src_node=src_node_pt,
            dst_node=dst_node_pt,
            tol_m=float(DEFAULT_PARAMS["SNAP_TOL_M"]),
        )
        if choice.segment is None:
            report.add_drop(choice.reason or "segment_select_failed")
            continue

        selected_line = choice.segment
        q0, q1 = geom.line_endpoints(selected_line)
        new_assign = geom.assign_by_references(q0, q1, src_ref=src_ref, dst_ref=dst_ref)

        changed_src = geom.endpoint_changed(orig_assign.src_point, new_assign.src_point, tol_m=float(DEFAULT_PARAMS["ENDPOINT_CHANGE_TOL_M"]))
        changed_dst = geom.endpoint_changed(orig_assign.dst_point, new_assign.dst_point, tol_m=float(DEFAULT_PARAMS["ENDPOINT_CHANGE_TOL_M"]))

        road_props_new = dict(road.properties)
        road_key = _road_primary_id(road.properties, feature_index=road.feature_index)

        updated_src = False
        updated_dst = False

        if changed_src or (not src_exists):
            new_id = geom.generate_stable_node_id(
                road_primary_id=road_key,
                side="src",
                x_m=float(new_assign.src_point.x),
                y_m=float(new_assign.src_point.y),
                id_is_int=node_ctx.id_is_int,
                existing_ids=existing_node_ids,
            )
            new_id = geom.coerce_id_type(new_id, id_is_int=node_ctx.id_is_int)
            existing_node_ids.add(new_id)
            road_props_new[road_s_field] = new_id
            created_nodes.append(
                _ProjectedNode(
                    properties=_build_virtual_node_properties(node_ctx=node_ctx, node_id=new_id),
                    geometry=new_assign.src_point,
                )
            )
            report.nodes_created += 1
            report.updated_snodeid_count += 1
            updated_src = True

        if changed_dst or (not dst_exists):
            new_id = geom.generate_stable_node_id(
                road_primary_id=road_key,
                side="dst",
                x_m=float(new_assign.dst_point.x),
                y_m=float(new_assign.dst_point.y),
                id_is_int=node_ctx.id_is_int,
                existing_ids=existing_node_ids,
            )
            new_id = geom.coerce_id_type(new_id, id_is_int=node_ctx.id_is_int)
            existing_node_ids.add(new_id)
            road_props_new[road_e_field] = new_id
            created_nodes.append(
                _ProjectedNode(
                    properties=_build_virtual_node_properties(node_ctx=node_ctx, node_id=new_id),
                    geometry=new_assign.dst_point,
                )
            )
            report.nodes_created += 1
            report.updated_enodeid_count += 1
            updated_dst = True

        if src_node_pt is not None and float(orig_assign.src_distance_m) > float(DEFAULT_PARAMS["SNAP_TOL_M"]):
            report.add_warning(f"road[{road.feature_index}] src_endpoint_not_snapped dist={orig_assign.src_distance_m:.3f}")
        if dst_node_pt is not None and float(orig_assign.dst_distance_m) > float(DEFAULT_PARAMS["SNAP_TOL_M"]):
            report.add_warning(f"road[{road.feature_index}] dst_endpoint_not_snapped dist={orig_assign.dst_distance_m:.3f}")

        report.add_fixed_road(
            {
                "road_feature_index": int(road.feature_index),
                "road_primary_id": road_key,
                "src_exists_in_input": bool(src_exists),
                "dst_exists_in_input": bool(dst_exists),
                "segment_connect_src": bool(choice.connect_src),
                "segment_connect_dst": bool(choice.connect_dst),
                "updated_src": bool(updated_src),
                "updated_dst": bool(updated_dst),
                "selected_length_m": float(selected_line.length),
                "selected_wkt": selected_line.wkt,
            }
        )

        road_out_candidates.append(
            _ProjectedRoad(
                feature_index=road.feature_index,
                properties=road_props_new,
                geometry=selected_line,
            )
        )

    # Build output node set (input first, then created) with stable de-dup by node id.
    node_output_by_id: dict[Any, _ProjectedNode] = {}
    for n in nodes:
        nid = n.properties.get(node_id_field)
        if nid is None:
            continue
        if nid not in node_output_by_id:
            node_output_by_id[nid] = n
    for n in created_nodes:
        nid = n.properties.get(node_id_field)
        if nid is None:
            continue
        if nid not in node_output_by_id:
            node_output_by_id[nid] = n

    node_ids_out = set(node_output_by_id.keys())

    roads_out: list[_ProjectedRoad] = []
    for road in road_out_candidates:
        sid = road.properties.get(road_s_field)
        eid = road.properties.get(road_e_field)
        if sid in node_ids_out and eid in node_ids_out:
            roads_out.append(road)
        else:
            report.add_drop("unresolved_endpoint_reference")

    report.roads_out = len(roads_out)
    report.nodes_out = len(node_output_by_id)

    miss_out = 0
    for road in roads_out:
        sid = road.properties.get(road_s_field)
        eid = road.properties.get(road_e_field)
        if sid not in node_ids_out or eid not in node_ids_out:
            miss_out += 1
    report.missing_endpoint_refs_out = int(miss_out)

    for road in roads_out:
        relation_out = geom.relation_to_zone(road.geometry, drivezone.union_geom)
        if relation_out == "boundary_intersection":
            report.boundary_intersections_out += 1

    node_features_out = [
        {
            "type": "Feature",
            "properties": dict(node.properties),
            "geometry": mapping(node.geometry),
        }
        for node in node_output_by_id.values()
    ]
    road_features_out = [
        {
            "type": "Feature",
            "properties": dict(road.properties),
            "geometry": mapping(road.geometry),
        }
        for road in roads_out
    ]

    vector_dir = output_dir / "Vector"
    report_dir = output_dir / "report"
    logs_dir = output_dir / "logs"

    write_feature_collection(vector_dir / "RCSDNode.geojson", crs_name=f"EPSG:{target_epsg}", features=node_features_out)
    write_feature_collection(vector_dir / "RCSDRoad.geojson", crs_name=f"EPSG:{target_epsg}", features=road_features_out)

    summary = report.to_summary(
        patch_id=loaded.patch_id,
        run_id=rid,
        epsg_out=target_epsg,
        params={
            "ENDPOINT_CHANGE_TOL_M": float(DEFAULT_PARAMS["ENDPOINT_CHANGE_TOL_M"]),
            "SNAP_TOL_M": float(DEFAULT_PARAMS["SNAP_TOL_M"]),
            "bit16_value": int(DEFAULT_PARAMS["BIT16_VALUE"]),
            "epsg_out": int(DEFAULT_PARAMS["TARGET_EPSG"]),
            "missing_endpoint_detect_mode": DEFAULT_PARAMS["MISSING_ENDPOINT_DETECT_MODE"],
            "clip_mode": DEFAULT_PARAMS["CLIP_MODE"],
            "keep_segment_mode": DEFAULT_PARAMS["KEEP_SEGMENT_MODE"],
        },
        source_notes={
            "node_path": str(loaded.node_path),
            "road_path": str(loaded.road_path),
            "drivezone_path": str(loaded.drivezone_path),
            "node_source_note": loaded.node_source_note,
            "road_source_note": loaded.road_source_note,
            "drivezone_source_note": loaded.drivezone_source_note,
            **proj_notes,
        },
    )

    metrics = {
        "node_in_count": int(report.nodes_in),
        "road_in_count": int(report.roads_in),
        "missing_endpoint_road_count": int(report.missing_endpoint_refs_in),
        "clipped_road_count": int(report.clipped_road_count),
        "dropped_road_empty_count": int(report.dropped_road_empty_count),
        "new_virtual_node_count": int(report.nodes_created),
        "updated_snodeid_count": int(report.updated_snodeid_count),
        "updated_enodeid_count": int(report.updated_enodeid_count),
        "output_node_count": int(report.nodes_out),
        "output_road_count": int(report.roads_out),
        "target_epsg": int(target_epsg),
        "ok": bool(report.missing_endpoint_refs_out == 0),
    }

    summary_path = report_dir / "t06_summary.json"
    drop_path = report_dir / "t06_drop_reasons.json"

    write_json(summary_path, summary)
    write_json(drop_path, dict(sorted(report.drop_reasons.items())))
    write_json(report_dir / "metrics.json", metrics)
    write_json(report_dir / "fixed_roads.json", {"items": report.fixed_roads})

    log_lines = [
        f"run_id={rid}",
        f"patch_id={loaded.patch_id}",
        f"roads_in={report.roads_in}",
        f"roads_out={report.roads_out}",
        f"nodes_in={report.nodes_in}",
        f"nodes_out={report.nodes_out}",
        f"nodes_created={report.nodes_created}",
        f"missing_endpoint_refs_in={report.missing_endpoint_refs_in}",
        f"missing_endpoint_refs_out={report.missing_endpoint_refs_out}",
    ]
    (logs_dir / "run.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    return RunResult(
        run_id=rid,
        patch_id=loaded.patch_id,
        output_dir=output_dir,
        summary_path=summary_path,
        drop_reasons_path=drop_path,
    )
