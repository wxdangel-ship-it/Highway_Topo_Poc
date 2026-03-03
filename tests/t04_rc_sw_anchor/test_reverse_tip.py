from __future__ import annotations

import json
from pathlib import Path

from highway_topo_poc.modules.t04_rc_sw_anchor.config import DEFAULT_PARAMS
from highway_topo_poc.modules.t04_rc_sw_anchor.runner import run_from_runtime

from ._synth_patch_factory import create_synth_patch


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _node_xy(node_path: Path, nodeid: int) -> tuple[float, float]:
    payload = _read_json(node_path)
    for feat in payload.get("features", []):
        props = feat.get("properties", {}) if isinstance(feat, dict) else {}
        vals = []
        for k in ["id", "mainid", "mainnodeid", "nodeid"]:
            if k in props:
                vals.append(props.get(k))
        for v in vals:
            try:
                if int(v) == int(nodeid):
                    coord = feat.get("geometry", {}).get("coordinates", [0.0, 0.0])
                    return float(coord[0]), float(coord[1])
            except Exception:
                continue
    raise AssertionError(f"node_not_found:{nodeid}")


def _box(cx: float, cy: float, min_dx: float, min_dy: float, max_dx: float, max_dy: float) -> list[list[float]]:
    return [
        [cx + min_dx, cy + min_dy],
        [cx + max_dx, cy + min_dy],
        [cx + max_dx, cy + max_dy],
        [cx + min_dx, cy + max_dy],
        [cx + min_dx, cy + min_dy],
    ]


def _rewrite_drivezone_single_polygon(path: Path, *, cx: float, cy: float) -> None:
    payload = _read_json(path)
    payload["features"] = [
        {
            "type": "Feature",
            "properties": {"name": "single_roadbed"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box(cx, cy, -30.0, -120.0, 30.0, 120.0)],
            },
        }
    ]
    payload.pop("crs", None)
    payload["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    _write_json(path, payload)


def _rewrite_divstrip_reverse_only(path: Path, *, node_x: float, node_y: float) -> None:
    payload = _read_json(path)
    payload["features"] = [
        {
            "type": "Feature",
            "properties": {"name": "reverse_only"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box(node_x, node_y - 6.0, -2.0, -1.5, 2.0, 1.5)],
            },
        }
    ]
    payload.pop("crs", None)
    payload["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    _write_json(path, payload)


def _rewrite_divstrip_untrusted_with_reverse(path: Path, *, node_x: float, node_y: float) -> None:
    payload = _read_json(path)
    payload["features"] = [
        {
            "type": "Feature",
            "properties": {"name": "at_node_untrusted"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box(node_x, node_y, -1.0, -1.0, 1.0, 1.0)],
            },
        },
        {
            "type": "Feature",
            "properties": {"name": "reverse_ref"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box(node_x, node_y - 6.0, -2.0, -1.5, 2.0, 1.5)],
            },
        },
    ]
    payload.pop("crs", None)
    payload["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    _write_json(path, payload)


def _run_runtime(
    tmp_path: Path,
    *,
    run_id: str,
    data: dict,
    focus_node_ids: list[str],
) -> Path:
    out_root = tmp_path / "outputs" / "_work" / "t04_rc_sw_anchor"
    params = dict(DEFAULT_PARAMS)
    params.update({"reverse_tip_max_m": 10.0})
    runtime = {
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
        "focus_node_ids": list(focus_node_ids),
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
    return run_from_runtime(runtime).out_dir


def test_reverse_tip_missing_ref_finds_reverse(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    node_x, node_y = _node_xy(Path(data["global_node_path"]), int(data["node_diverge"]))
    _rewrite_drivezone_single_polygon(Path(data["drivezone_path"]), cx=node_x, cy=node_y + 40.0)
    _rewrite_divstrip_reverse_only(Path(data["divstrip_path"]), node_x=node_x, node_y=node_y)
    out_dir = _run_runtime(
        tmp_path,
        run_id="reverse_tip_missing_ref_finds_reverse",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
    )
    item = _read_json(out_dir / "anchors.json")["items"][0]
    assert bool(item.get("reverse_tip_attempted", False)) is True
    assert str(item.get("reverse_trigger")) == "missing_ref"
    assert bool(item.get("reverse_tip_used", False)) is True
    assert float(item.get("ref_s_final_m")) < 0.0
    s_chosen = float(item.get("s_chosen_m"))
    ref_s = float(item.get("ref_s_final_m"))
    assert (ref_s - 1.0) <= s_chosen <= ref_s


def test_reverse_tip_untrusted_divstrip_at_node_overrides(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    node_x, node_y = _node_xy(Path(data["global_node_path"]), int(data["node_diverge"]))
    _rewrite_drivezone_single_polygon(Path(data["drivezone_path"]), cx=node_x, cy=node_y + 40.0)
    _rewrite_divstrip_untrusted_with_reverse(Path(data["divstrip_path"]), node_x=node_x, node_y=node_y)
    out_dir = _run_runtime(
        tmp_path,
        run_id="reverse_tip_untrusted_divstrip_at_node_overrides",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
    )
    item = _read_json(out_dir / "anchors.json")["items"][0]
    assert bool(item.get("reverse_tip_attempted", False)) is True
    assert str(item.get("reverse_trigger")) == "untrusted_divstrip_at_node"
    assert bool(item.get("untrusted_divstrip_at_node", False)) is True
    assert bool(item.get("seg0_intersects_divstrip", False)) is True
    assert float(item.get("node_to_divstrip_m_at_s0", 99.0)) <= float(DEFAULT_PARAMS["divstrip_hit_tol_m"])
    assert bool(item.get("reverse_tip_used", False)) is True
    assert str(item.get("position_source_final")) in {"divstrip_ref", "drivezone_split"}
    assert float(item.get("ref_s_final_m")) < 0.0


def test_regression_normal_case_not_affected(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    out_dir = _run_runtime(
        tmp_path,
        run_id="reverse_tip_regression_normal_case",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
    )
    item = _read_json(out_dir / "anchors.json")["items"][0]
    assert bool(item.get("reverse_tip_attempted", False)) is False
    assert bool(item.get("reverse_tip_used", False)) is False
    assert item.get("ref_s_final_m") == item.get("ref_s_forward_m")
    assert item.get("position_source_final") == item.get("position_source_forward")
    assert str(item.get("position_source")) == str(item.get("position_source_forward"))
    s_chosen = float(item.get("s_chosen_m"))
    ref_s = float(item.get("ref_s_final_m"))
    assert (ref_s - 1.0) <= s_chosen <= ref_s

