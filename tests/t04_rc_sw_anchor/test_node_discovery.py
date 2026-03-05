from __future__ import annotations

import json
from pathlib import Path

from highway_topo_poc.modules.t04_rc_sw_anchor.node_discovery import (
    discover_node_ids_from_rcsdnode,
    main as node_discovery_main,
)


def _write_rcsdnode(path: Path, props_list: list[dict]) -> None:
    feats = []
    for idx, props in enumerate(props_list):
        feats.append(
            {
                "type": "Feature",
                "properties": dict(props),
                "geometry": {"type": "Point", "coordinates": [float(idx), float(idx)]},
            }
        )
    payload = {"type": "FeatureCollection", "features": feats}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_discovery_kind_mask_filters_only_merge_diverge(tmp_path: Path) -> None:
    rcsdnode = tmp_path / "RCSDNode.geojson"
    _write_rcsdnode(
        rcsdnode,
        [
            {"id": 101, "kind": 16},
            {"id": 102, "kind": 8},
            {"id": 103, "kind": 4},
            {"id": 104, "kind": 0},
        ],
    )

    node_ids, report = discover_node_ids_from_rcsdnode(rcsdnode_path=rcsdnode, kind_mask=24)
    assert node_ids == [101, 102]
    assert int(report.get("kind_mask", 0)) == 24
    assert int(report.get("selected_count", 0)) == 2
    assert int(report["filtered_out_reasons"]["kind_not_allowed"]) == 2


def test_discovery_field_normalization_with_mixed_id_keys(tmp_path: Path) -> None:
    rcsdnode = tmp_path / "RCSDNode.geojson"
    _write_rcsdnode(
        rcsdnode,
        [
            {"MainNodeID": "3001", "kind": 8},
            {"id": "3002", "kind": 16},
        ],
    )

    node_ids, report = discover_node_ids_from_rcsdnode(rcsdnode_path=rcsdnode, kind_mask=24)
    assert node_ids == [3001, 3002]
    hit_stats = report.get("id_field_hit_stats", {})
    assert int(hit_stats.get("mainnodeid", 0)) == 1
    assert int(hit_stats.get("id", 0)) == 1


def test_discovery_dedup_and_stable_sort(tmp_path: Path) -> None:
    rcsdnode = tmp_path / "RCSDNode.geojson"
    _write_rcsdnode(
        rcsdnode,
        [
            {"id": 4003, "kind": 16},
            {"mainnodeid": 4001, "kind": 8},
            {"nodeid": 4003, "kind": 16},
            {"id": 4002, "mainnodeid": 9999, "kind": 8},
        ],
    )

    node_ids, report = discover_node_ids_from_rcsdnode(rcsdnode_path=rcsdnode, kind_mask=24)
    assert node_ids == [4001, 4002, 4003]
    assert int(report.get("selected_count", 0)) == 3
    assert int(report.get("duplicate_id_count", 0)) == 1


def test_discovery_empty_result_writes_empty_txt_and_report(tmp_path: Path) -> None:
    rcsdnode = tmp_path / "RCSDNode.geojson"
    out_txt = tmp_path / "focus_node_ids_resolved.txt"
    out_json = tmp_path / "focus_node_ids_resolved.json"
    _write_rcsdnode(
        rcsdnode,
        [
            {"id": 5001, "kind": 4},
            {"mainnodeid": 5002, "kind": 0},
        ],
    )

    rc = node_discovery_main(
        [
            "--rcsdnode_path",
            str(rcsdnode),
            "--kind_mask",
            "24",
            "--out_txt",
            str(out_txt),
            "--out_json",
            str(out_json),
        ]
    )
    assert rc == 0
    assert out_txt.read_text(encoding="utf-8") == ""

    report = _read_json(out_json)
    assert int(report.get("selected_count", 0)) == 0
    assert int(report.get("filtered_out_count", -1)) == int(report.get("total_features", -2))

