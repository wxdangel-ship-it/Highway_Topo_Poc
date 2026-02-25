from __future__ import annotations

import json
from pathlib import Path

from highway_topo_poc.modules.t04_rc_sw_anchor.config import DEFAULT_PARAMS
from highway_topo_poc.modules.t04_rc_sw_anchor.runner import run_from_runtime

from ._synth_patch_factory import create_synth_patch


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_t04_rc_sw_anchor_smoke_synth(tmp_path: Path) -> None:
    data = create_synth_patch(tmp_path)

    out_root = tmp_path / "outputs" / "_work" / "t04_rc_sw_anchor"
    runtime = {
        "mode": "global_focus",
        "patch_dir": str(data["patch_dir"]),
        "out_root": str(out_root),
        "run_id": "smoke_t04",
        "global_node_path": str(data["global_node_path"]),
        "global_road_path": str(data["global_road_path"]),
        "divstrip_path": str(data["divstrip_path"]),
        "pointcloud_path": str(data["pointcloud_path"]),
        "traj_glob": str(data["traj_glob"]),
        "focus_node_ids": list(data["focus_node_ids"]),
        "src_crs": "EPSG:3857",
        "dst_crs": "EPSG:3857",
        "params": dict(DEFAULT_PARAMS),
    }

    result = run_from_runtime(runtime)

    out_dir = result.out_dir
    anchors_geojson = out_dir / "anchors.geojson"
    anchors_json = out_dir / "anchors.json"
    metrics_json = out_dir / "metrics.json"
    breakpoints_json = out_dir / "breakpoints.json"
    summary_txt = out_dir / "summary.txt"
    inter_opt_geojson = out_dir / "intersection_l_opt.geojson"
    chosen_config_json = out_dir / "chosen_config.json"

    assert anchors_geojson.is_file()
    assert anchors_json.is_file()
    assert metrics_json.is_file()
    assert breakpoints_json.is_file()
    assert summary_txt.is_file()
    assert inter_opt_geojson.is_file()
    assert chosen_config_json.is_file()

    metrics = _read_json(metrics_json)
    assert metrics.get("overall_pass") is True
    assert metrics.get("anchors_found_count") == 2

    anchors = _read_json(anchors_json)
    items = anchors.get("items", [])
    assert isinstance(items, list)
    assert len(items) == 2

    for record in items:
        assert record.get("status") == "ok"
        scan_dist = float(record.get("scan_dist_m"))
        assert scan_dist <= 20.0
        dist_to_divstrip = record.get("dist_to_divstrip_m")
        assert dist_to_divstrip is not None
        assert float(dist_to_divstrip) <= 1.0

    bp = _read_json(breakpoints_json)
    by_code = {str(x.get("code")): int(x.get("count", 0)) for x in bp.get("by_code", [])}
    assert by_code.get("NO_TRIGGER_BEFORE_NEXT_INTERSECTION", 0) == 0
