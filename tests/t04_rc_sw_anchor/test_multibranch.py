from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString

import highway_topo_poc.modules.t04_rc_sw_anchor.runner as runner_mod
from highway_topo_poc.modules.t04_rc_sw_anchor.config import DEFAULT_PARAMS
from highway_topo_poc.modules.t04_rc_sw_anchor.multibranch_ops import extract_split_events
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
        try:
            if int(props.get("id")) == int(nodeid):
                xy = feat.get("geometry", {}).get("coordinates", [0.0, 0.0])
                return float(xy[0]), float(xy[1])
        except Exception:
            continue
    raise AssertionError(f"node_not_found:{nodeid}")


def _append_node(node_path: Path, *, nodeid: int, x: float, y: float, kind: int = 4) -> None:
    payload = _read_json(node_path)
    payload.setdefault("features", []).append(
        {
            "type": "Feature",
            "properties": {"id": int(nodeid), "kind": int(kind)},
            "geometry": {"type": "Point", "coordinates": [float(x), float(y)]},
        }
    )
    _write_json(node_path, payload)


def _append_road(road_path: Path, *, snodeid: int, enodeid: int, direction: int, sxy: tuple[float, float], exy: tuple[float, float]) -> None:
    payload = _read_json(road_path)
    payload.setdefault("features", []).append(
        {
            "type": "Feature",
            "properties": {
                "snodeid": int(snodeid),
                "enodeid": int(enodeid),
                "direction": int(direction),
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [[float(sxy[0]), float(sxy[1])], [float(exy[0]), float(exy[1])]],
            },
        }
    )
    _write_json(road_path, payload)


def _add_diverge_outgoing_branch(
    data: dict,
    *,
    new_nodeid: int,
    dx: float,
    dy: float,
    direction: int,
) -> None:
    node_path = Path(data["global_node_path"])
    road_path = Path(data["global_road_path"])
    diverge_id = int(data["node_diverge"])
    x0, y0 = _node_xy(node_path, diverge_id)
    x1, y1 = (float(x0 + dx), float(y0 + dy))
    _append_node(node_path, nodeid=int(new_nodeid), x=x1, y=y1, kind=4)
    _append_road(
        road_path,
        snodeid=diverge_id,
        enodeid=int(new_nodeid),
        direction=int(direction),
        sxy=(x0, y0),
        exy=(x1, y1),
    )


def _add_merge_incoming_branch(
    data: dict,
    *,
    new_nodeid: int,
    dx: float,
    dy: float,
    direction: int,
) -> None:
    node_path = Path(data["global_node_path"])
    road_path = Path(data["global_road_path"])
    merge_id = int(data["node_merge"])
    x1, y1 = _node_xy(node_path, merge_id)
    x0, y0 = (float(x1 + dx), float(y1 + dy))
    _append_node(node_path, nodeid=int(new_nodeid), x=x0, y=y0, kind=4)
    _append_road(
        road_path,
        snodeid=int(new_nodeid),
        enodeid=merge_id,
        direction=int(direction),
        sxy=(x0, y0),
        exy=(x1, y1),
    )


def _run_runtime(
    tmp_path: Path,
    *,
    run_id: str,
    data: dict,
    focus_node_ids: list[str],
    params_override: dict | None = None,
) -> Path:
    out_root = tmp_path / "outputs" / "_work" / "t04_rc_sw_anchor"
    params = dict(DEFAULT_PARAMS)
    if params_override:
        params.update(params_override)
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


def _fake_event_lines(node_x: float, node_y: float, events: list[tuple[float, str, int]]) -> list[dict]:
    out: list[dict] = []
    for idx, (s_m, evt_dir, pieces_count) in enumerate(events):
        y = float(node_y + float(s_m))
        out.append(
            {
                "event_idx": int(idx),
                "event_s_m": float(s_m),
                "event_dir": str(evt_dir),
                "pieces_count_at_event": int(pieces_count),
                "line": LineString([(float(node_x - 6.0), y), (float(node_x + 6.0), y)]),
            }
        )
    return out


def test_multibranch_diverge_three_outgoing_produces_two_events(tmp_path: Path, monkeypatch) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    _add_diverge_outgoing_branch(data, new_nodeid=70010001, dx=28.0, dy=46.0, direction=2)
    node_x, node_y = _node_xy(Path(data["global_node_path"]), int(data["node_diverge"]))

    def _fake_extract(**kwargs):
        _ = kwargs
        return {
            "split_events_forward": [5.0, 15.0],
            "split_events_reverse": [],
            "split_events_forward_diag": [],
            "split_events_reverse_diag": [],
            "s_main_m": 5.0,
            "main_pick_source": "forward_first",
            "abnormal_two_sided": False,
            "s_drivezone_split_first_m": 5.0,
            "event_lines": _fake_event_lines(node_x, node_y, [(5.0, "forward", 2), (15.0, "forward", 3)]),
        }

    monkeypatch.setattr(runner_mod, "_extract_multibranch_events", _fake_extract)

    out_dir = _run_runtime(
        tmp_path,
        run_id="multibranch_diverge_three_outgoing",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
    )
    item = _read_json(out_dir / "anchors.json")["items"][0]
    assert bool(item.get("multibranch_enabled", False)) is True
    assert int(item.get("multibranch_N", 0)) == 3
    assert int(item.get("multibranch_expected_events", 0)) == 2
    assert [float(x) for x in item.get("split_events_forward", [])] == [5.0, 15.0]
    assert float(item.get("s_main_m")) == 5.0
    assert str(item.get("main_pick_source")) == "forward_first"

    multi = _read_json(out_dir / "intersection_l_multi.geojson")
    feats = multi.get("features", [])
    assert len(feats) == 2
    assert [str(f["properties"]["event_dir"]) for f in feats] == ["forward", "forward"]


def test_multibranch_merge_three_incoming_produces_two_events(tmp_path: Path, monkeypatch) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    _add_merge_incoming_branch(data, new_nodeid=70020001, dx=30.0, dy=-52.0, direction=2)
    node_x, node_y = _node_xy(Path(data["global_node_path"]), int(data["node_merge"]))

    def _fake_extract(**kwargs):
        _ = kwargs
        return {
            "split_events_forward": [3.0, 11.0],
            "split_events_reverse": [],
            "split_events_forward_diag": [],
            "split_events_reverse_diag": [],
            "s_main_m": 3.0,
            "main_pick_source": "forward_first",
            "abnormal_two_sided": False,
            "s_drivezone_split_first_m": 3.0,
            "event_lines": _fake_event_lines(node_x, node_y, [(3.0, "forward", 2), (11.0, "forward", 3)]),
        }

    monkeypatch.setattr(runner_mod, "_extract_multibranch_events", _fake_extract)

    out_dir = _run_runtime(
        tmp_path,
        run_id="multibranch_merge_three_incoming",
        data=data,
        focus_node_ids=[str(data["node_merge"])],
    )
    item = _read_json(out_dir / "anchors.json")["items"][0]
    assert bool(item.get("multibranch_enabled", False)) is True
    assert int(item.get("multibranch_N", 0)) == 3
    assert int(item.get("multibranch_expected_events", 0)) == 2
    assert [float(x) for x in item.get("split_events_forward", [])] == [3.0, 11.0]
    assert float(item.get("s_main_m")) == 3.0
    assert str(item.get("main_pick_source")) == "forward_first"


def test_multibranch_abnormal_two_sided_picks_reverse_farthest(tmp_path: Path, monkeypatch) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    _add_diverge_outgoing_branch(data, new_nodeid=70030001, dx=26.0, dy=44.0, direction=2)
    node_x, node_y = _node_xy(Path(data["global_node_path"]), int(data["node_diverge"]))

    def _fake_extract(**kwargs):
        _ = kwargs
        return {
            "split_events_forward": [4.0],
            "split_events_reverse": [-3.0, -8.0],
            "split_events_forward_diag": [],
            "split_events_reverse_diag": [],
            "s_main_m": -8.0,
            "main_pick_source": "reverse_farthest_abnormal",
            "abnormal_two_sided": True,
            "s_drivezone_split_first_m": 4.0,
            "event_lines": _fake_event_lines(
                node_x,
                node_y,
                [(4.0, "forward", 2), (-3.0, "reverse", 2), (-8.0, "reverse", 3)],
            ),
        }

    monkeypatch.setattr(runner_mod, "_extract_multibranch_events", _fake_extract)

    out_dir = _run_runtime(
        tmp_path,
        run_id="multibranch_two_sided_reverse_pick",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
    )
    item = _read_json(out_dir / "anchors.json")["items"][0]
    assert bool(item.get("abnormal_two_sided", False)) is True
    assert float(item.get("s_main_m")) == -8.0
    assert str(item.get("main_pick_source")) == "reverse_farthest_abnormal"


def test_multibranch_direction_filter_excludes_0_1(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")
    _add_diverge_outgoing_branch(data, new_nodeid=70040001, dx=25.0, dy=40.0, direction=0)
    _add_diverge_outgoing_branch(data, new_nodeid=70040002, dx=-25.0, dy=42.0, direction=1)

    out_dir = _run_runtime(
        tmp_path,
        run_id="multibranch_direction_filter_excludes_01",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
    )
    item = _read_json(out_dir / "anchors.json")["items"][0]
    assert int(item.get("branches_used_count", 0)) == 2
    assert int(item.get("branches_ignored_due_to_direction", 0)) >= 2
    assert bool(item.get("multibranch_enabled", False)) is False


def test_regression_two_branch_unchanged(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path, kind_key="kind", id_mode="id", crs_mode="3857")

    out_on = _run_runtime(
        tmp_path,
        run_id="multibranch_regression_on",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
        params_override={"multibranch_enable": True},
    )
    out_off = _run_runtime(
        tmp_path,
        run_id="multibranch_regression_off",
        data=data,
        focus_node_ids=[str(data["node_diverge"])],
        params_override={"multibranch_enable": False},
    )
    item_on = _read_json(out_on / "anchors.json")["items"][0]
    item_off = _read_json(out_off / "anchors.json")["items"][0]
    assert bool(item_on.get("multibranch_enabled", False)) is False
    assert bool(item_off.get("multibranch_enabled", False)) is False

    keys = ["position_source", "s_chosen_m", "trigger", "stop_reason", "split_pick_source"]
    for key in keys:
        assert item_on.get(key) == item_off.get(key)


def test_extract_split_events_scheme_b_expands_delta_jump() -> None:
    events, diag = extract_split_events(
        s_values=[0.0, 1.0, 2.0],
        pieces_count_seq=[1, 3, 3],
        expected_events=2,
    )
    assert events == [1.0, 1.0]
    assert len(diag) == 2
    assert all(bool(x.get("event_ambiguous_jump", False)) for x in diag)
