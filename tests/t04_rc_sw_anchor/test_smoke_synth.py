from __future__ import annotations

import json
from pathlib import Path

from highway_topo_poc.modules.t04_rc_sw_anchor.config import DEFAULT_PARAMS
from highway_topo_poc.modules.t04_rc_sw_anchor.runner import run_from_runtime

from ._synth_patch_factory import create_synth_patch


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_case(tmp_path: Path, *, kind_key: str, id_mode: str) -> tuple[dict, Path]:
    data = create_synth_patch(tmp_path, kind_key=kind_key, id_mode=id_mode)

    out_root = tmp_path / "outputs" / "_work" / "t04_rc_sw_anchor"
    runtime = {
        "mode": "global_focus",
        "patch_dir": str(data["patch_dir"]),
        "out_root": str(out_root),
        "run_id": f"smoke_t04_{kind_key}_{id_mode}",
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
    return data, result.out_dir


def _assert_common_outputs(out_dir: Path) -> None:
    for name in [
        "anchors.geojson",
        "anchors.json",
        "metrics.json",
        "breakpoints.json",
        "summary.txt",
        "intersection_l_opt.geojson",
        "chosen_config.json",
    ]:
        assert (out_dir / name).is_file(), name


def _assert_anchor_quality(out_dir: Path, expected_matched_field: str) -> None:
    metrics = _read_json(out_dir / "metrics.json")
    assert metrics.get("overall_pass") is True
    assert metrics.get("anchors_found_count") == 2

    bp = _read_json(out_dir / "breakpoints.json")
    by_code = {str(x.get("code")): int(x.get("count", 0)) for x in bp.get("by_code", [])}
    assert by_code.get("UNSUPPORTED_KIND", 0) == 0

    anchors = _read_json(out_dir / "anchors.json")
    items = anchors.get("items", [])
    assert isinstance(items, list)
    assert len(items) == 2

    for record in items:
        assert record.get("status") == "ok"
        assert int(record.get("kind")) in {8, 16}
        scan_dist = float(record.get("scan_dist_m"))
        assert scan_dist <= 20.0
        dist_to_divstrip = record.get("dist_to_divstrip_m")
        assert dist_to_divstrip is not None
        assert float(dist_to_divstrip) <= 1.0

        resolved = record.get("resolved_from")
        assert isinstance(resolved, dict)
        assert str(resolved.get("matched_field")) == expected_matched_field


def test_t04_rc_sw_anchor_kind_lower_id_alias(tmp_path: Path) -> None:
    data, out_dir = _run_case(tmp_path, kind_key="kind", id_mode="id")
    _assert_common_outputs(out_dir)
    _assert_anchor_quality(out_dir, expected_matched_field=str(data["expected_matched_field"]))


def test_t04_rc_sw_anchor_mainnodeid_alias(tmp_path: Path) -> None:
    data, out_dir = _run_case(tmp_path, kind_key="kind", id_mode="mainnodeid")
    _assert_common_outputs(out_dir)
    _assert_anchor_quality(out_dir, expected_matched_field=str(data["expected_matched_field"]))
