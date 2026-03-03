from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point

from highway_topo_poc.modules.t04_rc_sw_anchor.config import DEFAULT_PARAMS
from highway_topo_poc.modules.t04_rc_sw_anchor.continuous_chain import (
    ChainComponent,
    ChainEdge,
    build_continuous_graph,
    build_effective_directed_edges,
)
from highway_topo_poc.modules.t04_rc_sw_anchor.io_geojson import RoadRecord, load_divstrip_union, load_drivezone_union, load_nodes, load_roads
from highway_topo_poc.modules.t04_rc_sw_anchor.road_graph import RoadGraph
from highway_topo_poc.modules.t04_rc_sw_anchor.runner import _apply_continuous_merges, _evaluate_node, run_from_runtime
from highway_topo_poc.modules.t04_rc_sw_anchor.writers import write_intersection_opt_geojson

from ._synth_patch_factory import create_synth_patch


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _mk_road(snodeid: int, enodeid: int, *, direction: int, length_m: float = 10.0) -> RoadRecord:
    line = LineString([(float(snodeid), 0.0), (float(enodeid), 0.0)])
    return RoadRecord(
        snodeid=int(snodeid),
        enodeid=int(enodeid),
        line=line,
        length_m=float(length_m),
        direction=int(direction),
    )


def _build_runtime(data: dict, out_root: Path, run_id: str, *, continuous_enable: bool) -> dict:
    params = dict(DEFAULT_PARAMS)
    params.update({"continuous_enable": bool(continuous_enable)})
    return {
        "mode": "global_focus",
        "patch_dir": str(data["patch_dir"]),
        "out_root": str(out_root),
        "run_id": str(run_id),
        "global_node_path": str(data["global_node_path"]),
        "global_road_path": str(data["global_road_path"]),
        "divstrip_path": str(data["divstrip_path"]),
        "drivezone_path": str(data["drivezone_path"]),
        "pointcloud_path": str(data["pointcloud_path"]),
        "traj_glob": str(data["traj_glob"]),
        "focus_node_ids": list(data["focus_node_ids"]),
        "src_crs": "auto",
        "dst_crs": "EPSG:3857",
        "node_src_crs": "auto",
        "road_src_crs": "auto",
        "divstrip_src_crs": "auto",
        "drivezone_src_crs": "auto",
        "traj_src_crs": "auto",
        "pointcloud_crs": str(data["pointcloud_crs"]),
        "params": params,
    }


def test_chain_detection_direction_respected() -> None:
    roads = [
        _mk_road(1, 2, direction=2, length_m=10.0),
        _mk_road(2, 3, direction=2, length_m=10.0),
        _mk_road(3, 4, direction=2, length_m=10.0),
        _mk_road(3, 5, direction=2, length_m=10.0),  # make node3 degree>=3
        _mk_road(1, 9, direction=0, length_m=1.0),   # must be ignored
        _mk_road(8, 7, direction=3, length_m=5.0),   # effective edge 7->8
    ]
    adj, _incident, _errs = build_effective_directed_edges(roads)
    assert any(int(e.dst) == 2 for e in adj.get(1, []))
    assert all(int(e.dst) != 9 for e in adj.get(1, []))
    assert any(int(e.dst) == 8 for e in adj.get(7, []))

    chain_edges, _components, _diag = build_continuous_graph(
        starts_set={1, 3},
        nodes_kind={1: 16, 3: 8},
        roads=roads,
        continuous_dist_max_m=50.0,
    )
    assert any(int(e.src) == 1 and int(e.dst) == 3 for e in chain_edges)


def test_chain_order_enforced_prevents_same_location(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    nodes, _node_meta, _node_err = load_nodes(
        path=Path(data["global_node_path"]),
        src_crs_override="auto",
        dst_crs="EPSG:3857",
        aoi=None,
    )
    roads, _road_meta, _road_err = load_roads(
        path=Path(data["global_road_path"]),
        src_crs_override="auto",
        dst_crs="EPSG:3857",
        aoi=None,
    )
    divstrip_union, _div_meta, _div_err = load_divstrip_union(
        path=Path(data["divstrip_path"]),
        src_crs_override="auto",
        dst_crs="EPSG:3857",
        aoi=None,
    )
    drivezone_union, _dz_meta, _dz_err = load_drivezone_union(
        path=Path(data["drivezone_path"]),
        src_crs_override="auto",
        dst_crs="EPSG:3857",
        aoi=None,
    )
    node_points = {int(n.nodeid): Point(float(n.point.x), float(n.point.y)) for n in nodes}
    node_kinds = {int(n.nodeid): int(n.kind) if n.kind is not None else 0 for n in nodes}
    road_graph = RoadGraph(roads=roads, node_points=node_points, node_kinds=node_kinds)
    node = next(n for n in nodes if int(n.nodeid) == int(data["node_diverge"]))

    params = dict(DEFAULT_PARAMS)
    bp_ok: list[dict] = []
    ok_res = _evaluate_node(
        node=node,
        road_graph=road_graph,
        divstrip_union=divstrip_union,
        drivezone_union=drivezone_union,
        drivezone_usable=True,
        ng_points_xy=np.zeros((0, 2), dtype=np.float64),
        params=params,
        breakpoints=bp_ok,
        pointcloud_usable=False,
        is_in_continuous_chain=True,
        chain_component_id="chain_t",
        chain_node_offset_m=0.0,
        required_prev_abs_s=None,
    )
    assert str(ok_res.get("status")) in {"ok", "suspect"}
    abs_s = ok_res.get("abs_s_chosen_m")
    assert abs_s is not None

    bp_fail: list[dict] = []
    fail_res = _evaluate_node(
        node=node,
        road_graph=road_graph,
        divstrip_union=divstrip_union,
        drivezone_union=drivezone_union,
        drivezone_usable=True,
        ng_points_xy=np.zeros((0, 2), dtype=np.float64),
        params=params,
        breakpoints=bp_fail,
        pointcloud_usable=False,
        is_in_continuous_chain=True,
        chain_component_id="chain_t",
        chain_node_offset_m=0.0,
        required_prev_abs_s=float(abs_s) + 1000.0,
    )
    assert str(fail_res.get("status")) == "fail"
    assert str(fail_res.get("sequential_violation_reason")) == "no_candidate_abs_gt_prev"
    assert any(str(bp.get("code")) == "SEQUENTIAL_ORDER_VIOLATION" for bp in bp_fail)


def test_chain_merge_diverge_to_merge_within_5m_merges(tmp_path: Path) -> None:
    comp = ChainComponent(
        component_id="chain_000",
        node_ids=(100, 200),
        edges=(ChainEdge(src=100, dst=200, dist_m=3.0, path_road_indices=(1,), start_road_idx=1),),
        offsets_m={100: 0.0, 200: 8.0},
        predecessors={100: tuple(), 200: (100,)},
        diag={},
    )
    seed_results = [
        {
            "nodeid": 100,
            "kind": 16,
            "is_diverge_kind": True,
            "is_merge_kind": False,
            "status": "suspect",
            "anchor_type": "diverge",
            "crossline_opt": LineString([(0.0, 0.0), (10.0, 0.0)]),
            "is_in_continuous_chain": True,
            "chain_component_id": "chain_000",
            "chain_node_offset_m": 0.0,
            "abs_s_chosen_m": 10.0,
            "position_source": "divstrip_ref",
            "s_divstrip_m": 11.0,
            "s_drivezone_split_m": 12.0,
            "merged": False,
            "suppress_intersection_feature": False,
        },
        {
            "nodeid": 200,
            "kind": 8,
            "is_diverge_kind": False,
            "is_merge_kind": True,
            "status": "suspect",
            "anchor_type": "merge",
            "crossline_opt": LineString([(0.0, 1.0), (10.0, 1.0)]),
            "is_in_continuous_chain": True,
            "chain_component_id": "chain_000",
            "chain_node_offset_m": 20.0,
            "abs_s_chosen_m": 11.0,
            "position_source": "divstrip_ref",
            "s_divstrip_m": 9.5,
            "s_drivezone_split_m": 12.0,
            "merged": False,
            "suppress_intersection_feature": False,
        },
    ]
    _apply_continuous_merges(seed_results=seed_results, components=[comp], merge_gap_m=5.0)
    assert any(bool(x.get("suppress_intersection_feature")) for x in seed_results)
    keeper = next(x for x in seed_results if not bool(x.get("suppress_intersection_feature")))
    assert bool(keeper.get("merged")) is True
    assert keeper.get("merged_output_nodeids") == [100, 200]

    inter_path = tmp_path / "intersection_l_opt.geojson"
    write_intersection_opt_geojson(
        path=inter_path,
        seed_results=seed_results,
        src_crs_name="EPSG:3857",
        dst_crs_name="EPSG:3857",
    )
    inter = _read_json(inter_path)
    feats = inter.get("features", [])
    assert len(feats) == 1
    assert feats[0].get("properties", {}).get("nodeids") == [100, 200]


def test_chain_merge_not_triggered_when_mean_outside_windows() -> None:
    comp = ChainComponent(
        component_id="chain_001",
        node_ids=(10, 20),
        edges=(ChainEdge(src=10, dst=20, dist_m=4.0, path_road_indices=(1,), start_road_idx=1),),
        offsets_m={10: 0.0, 20: 6.0},
        predecessors={10: tuple(), 20: (10,)},
        diag={},
    )
    seed_results = [
        {
            "nodeid": 10,
            "kind": 16,
            "is_diverge_kind": True,
            "is_merge_kind": False,
            "status": "suspect",
            "anchor_type": "diverge",
            "crossline_opt": LineString([(0.0, 0.0), (5.0, 0.0)]),
            "is_in_continuous_chain": True,
            "chain_component_id": "chain_001",
            "chain_node_offset_m": 0.0,
            "abs_s_chosen_m": 1.0,
            "position_source": "divstrip_ref",
            "s_divstrip_m": 1.0,
            "s_drivezone_split_m": None,
            "merged": False,
            "suppress_intersection_feature": False,
        },
        {
            "nodeid": 20,
            "kind": 8,
            "is_diverge_kind": False,
            "is_merge_kind": True,
            "status": "suspect",
            "anchor_type": "merge",
            "crossline_opt": LineString([(0.0, 1.0), (5.0, 1.0)]),
            "is_in_continuous_chain": True,
            "chain_component_id": "chain_001",
            "chain_node_offset_m": 6.0,
            "abs_s_chosen_m": 5.0,
            "position_source": "divstrip_ref",
            "s_divstrip_m": 1.0,
            "s_drivezone_split_m": None,
            "merged": False,
            "suppress_intersection_feature": False,
        },
    ]
    _apply_continuous_merges(seed_results=seed_results, components=[comp], merge_gap_m=5.0)
    assert all(bool(x.get("merged")) is False for x in seed_results)
    assert all(bool(x.get("suppress_intersection_feature")) is False for x in seed_results)


def test_regression_non_chain_unchanged(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    out_root = tmp_path / "outputs" / "_work" / "t04_rc_sw_anchor"
    runtime_off = _build_runtime(data, out_root, "non_chain_continuous_off", continuous_enable=False)
    runtime_on = _build_runtime(data, out_root, "non_chain_continuous_on", continuous_enable=True)

    out_off = run_from_runtime(runtime_off).out_dir
    out_on = run_from_runtime(runtime_on).out_dir
    items_off = {int(x["nodeid"]): x for x in _read_json(out_off / "anchors.json").get("items", [])}
    items_on = {int(x["nodeid"]): x for x in _read_json(out_on / "anchors.json").get("items", [])}
    assert set(items_off.keys()) == set(items_on.keys())

    stable_fields = ["s_chosen_m", "trigger", "stop_reason", "split_pick_source", "status"]
    for nodeid in sorted(items_off.keys()):
        for key in stable_fields:
            assert items_off[nodeid].get(key) == items_on[nodeid].get(key)
        assert bool(items_on[nodeid].get("is_in_continuous_chain", False)) is False
