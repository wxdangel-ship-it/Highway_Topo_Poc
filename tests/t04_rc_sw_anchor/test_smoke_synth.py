from __future__ import annotations

import json
from pathlib import Path

from highway_topo_poc.modules.t04_rc_sw_anchor.config import load_config
from highway_topo_poc.modules.t04_rc_sw_anchor.runner import run_patch

from ._synth_patch_factory import create_synth_patch


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_t04_rc_sw_anchor_smoke_synth(tmp_path: Path) -> None:
    patch_dir = create_synth_patch(tmp_path)

    out_root = tmp_path / "outputs" / "_work" / "t04_rc_sw_anchor"
    cfg = load_config()
    result = run_patch(
        patch_dir=patch_dir,
        out_root=out_root,
        run_id="smoke_t04",
        config=cfg,
    )

    out_dir = result.out_dir
    anchors_geojson = out_dir / "anchors.geojson"
    anchors_json = out_dir / "anchors.json"
    metrics_json = out_dir / "metrics.json"
    breakpoints_json = out_dir / "breakpoints.json"
    summary_txt = out_dir / "summary.txt"
    inter_opt_geojson = out_dir / "intersection_l_opt.geojson"

    assert anchors_geojson.is_file()
    assert anchors_json.is_file()
    assert metrics_json.is_file()
    assert breakpoints_json.is_file()
    assert summary_txt.is_file()
    assert inter_opt_geojson.is_file()

    metrics = _read_json(metrics_json)
    assert metrics.get("overall_pass") is True
    assert metrics.get("anchor_found_ratio") == 1.0

    inter_opt = _read_json(inter_opt_geojson)
    assert inter_opt.get("type") == "FeatureCollection"
    line_feats = inter_opt.get("features", [])
    assert isinstance(line_feats, list)
    assert len(line_feats) == 2

    anchors = _read_json(anchors_json)
    items = anchors.get("items", [])
    assert isinstance(items, list)
    assert len(items) == 2

    by_node = {int(x["nodeid"]): x for x in items}
    assert 1001 in by_node
    assert 1002 in by_node

    for nodeid in [1001, 1002]:
        record = by_node[nodeid]
        assert record.get("status") == "ok"
        scan_dist = float(record.get("scan_dist_m"))
        assert abs(scan_dist - 10.0) <= 1.0

        dist_to_divstrip = record.get("dist_to_divstrip_m")
        assert dist_to_divstrip is not None
        assert float(dist_to_divstrip) <= 1.0
