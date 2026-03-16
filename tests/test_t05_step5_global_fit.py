from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString

from highway_topo_poc.modules.t05_topology_between_rc_v2.models import Segment
from highway_topo_poc.modules.t05_topology_between_rc_v2.pipeline import DEFAULT_PARAMS, run_full_pipeline
from highway_topo_poc.modules.t05_topology_between_rc_v2.step5_global_geometry_fit import (
    aggregate_trajectory_stations,
    build_center_corrected_spine,
    estimate_endpoint_local_tangents,
    extract_lane_boundary_center_hints,
    fit_global_centerline,
    select_trajectory_evidence,
)


def _line_feature(coords: list[tuple[float, float]], props: dict | None = None) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[float(x), float(y)] for x, y in coords]},
        "properties": dict(props or {}),
    }


def _poly_feature(coords: list[tuple[float, float]], props: dict | None = None) -> dict:
    ring = [[float(x), float(y)] for x, y in coords]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": dict(props or {}),
    }


def _point_feature(coord: tuple[float, float], props: dict | None = None) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float(coord[0]), float(coord[1])]},
        "properties": dict(props or {}),
    }


def _fc(features: list[dict], crs_name: str | None = "EPSG:3857") -> dict:
    payload = {"type": "FeatureCollection", "features": features}
    if crs_name is not None:
        payload["crs"] = {"type": "name", "properties": {"name": crs_name}}
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_patch(
    root: Path,
    *,
    patch_id: str,
    intersection_fc: dict,
    drivezone_fc: dict,
    traj_tracks: list[list[tuple[float, float]]],
    lane_fc: dict | None = None,
    road_fc: dict | None = None,
) -> Path:
    patch_dir = root / patch_id
    vector_dir = patch_dir / "Vector"
    traj_dir = patch_dir / "Traj"
    _write_json(vector_dir / "intersection_l.geojson", intersection_fc)
    _write_json(vector_dir / "DriveZone.geojson", drivezone_fc)
    if lane_fc is not None:
        _write_json(vector_dir / "LaneBoundary.geojson", lane_fc)
    if road_fc is not None:
        _write_json(vector_dir / "RCSDRoad.geojson", road_fc)
    for idx, track in enumerate(traj_tracks):
        features = [_point_feature(coord, {"seq": seq, "traj_id": f"traj_{idx:02d}"}) for seq, coord in enumerate(track)]
        _write_json(traj_dir / f"traj_{idx:02d}" / "raw_dat_pose.geojson", _fc(features, "EPSG:3857"))
    return patch_dir


def _segment() -> Segment:
    return Segment(
        segment_id="seg_1",
        src_nodeid=1,
        dst_nodeid=2,
        direction="forward",
        geometry_coords=((0.0, 0.0), (100.0, 0.0)),
        candidate_ids=("cand",),
        source_modes=("traj",),
        support_traj_ids=("traj_clean", "traj_partial", "traj_bad"),
        support_count=3,
        dedup_count=3,
        representative_offset_m=0.0,
        other_xsec_crossing_count=0,
        tolerated_other_xsec_crossings=1,
        prior_supported=False,
        formation_reason="test",
        length_m=100.0,
        drivezone_ratio=1.0,
        crosses_divstrip=False,
    )


def test_select_trajectory_evidence_prefers_clean_terminal_support() -> None:
    segment = _segment()
    guide = LineString([(0.0, 0.0), (100.0, 0.0)])
    arc_row = {
        "single_traj_support_segments": [
            {
                "source_traj_id": "traj_clean",
                "traj_id": "traj_clean",
                "support_type": "terminal_crossing_support",
                "support_mode": "single",
                "support_score": 1.0,
                "line_coords": [[0.0, 0.0], [50.0, 0.4], [100.0, 0.0]],
                "surface_consistent": True,
                "supports_src_xsec_anchor": True,
                "supports_dst_xsec_anchor": True,
            },
            {
                "source_traj_id": "traj_partial",
                "traj_id": "traj_partial",
                "support_type": "partial_arc_support",
                "support_mode": "single",
                "support_score": 0.55,
                "line_coords": [[5.0, 1.2], [50.0, 1.0], [95.0, 1.1]],
                "surface_consistent": True,
                "supports_src_xsec_anchor": False,
                "supports_dst_xsec_anchor": False,
            },
            {
                "source_traj_id": "traj_bad",
                "traj_id": "traj_bad",
                "support_type": "partial_arc_support",
                "support_mode": "single",
                "support_score": 0.8,
                "line_coords": [[0.0, 18.0], [50.0, 20.0], [100.0, 22.0]],
                "surface_consistent": False,
                "surface_reject_reason": "outside_drivezone",
                "supports_src_xsec_anchor": False,
                "supports_dst_xsec_anchor": False,
            },
        ]
    }
    result = select_trajectory_evidence(
        segment=segment,
        arc_row=arc_row,
        witness_line=None,
        fallback_line=guide,
        start_anchor=guide.interpolate(0.0, normalized=True),
        end_anchor=guide.interpolate(1.0, normalized=True),
        safe_surface=guide.buffer(8.0, cap_style=2),
        params=dict(DEFAULT_PARAMS),
    )
    assert result["selected_rows"][0]["source_traj_id"] == "traj_clean"
    assert result["selected_rows"][0]["selection_reason"] == "clean_endpoint_identity"
    rejected = {row["source_traj_id"]: row["selection_reason"] for row in result["selection_rows"] if not row["included_bool"]}
    assert rejected["traj_bad"] == "outside_drivezone" or rejected["traj_bad"] == "surface_inconsistent"


def test_aggregate_trajectory_stations_returns_robust_centers() -> None:
    guide = LineString([(0.0, 0.0), (100.0, 0.0)])
    selected_rows = [
        {"source_traj_id": "a", "selection_weight": 3.0, "line": LineString([(0.0, 0.0), (100.0, 0.0)])},
        {"source_traj_id": "b", "selection_weight": 2.0, "line": LineString([(0.0, 1.2), (100.0, 1.2)])},
    ]
    rows = aggregate_trajectory_stations(
        guide_line=guide,
        selected_rows=selected_rows,
        start_anchor=guide.interpolate(0.0, normalized=True),
        end_anchor=guide.interpolate(1.0, normalized=True),
        params=dict(DEFAULT_PARAMS),
    )
    assert len(rows) >= 9
    middle = rows[len(rows) // 2]
    assert middle["sample_count"] == 2
    assert middle["trajectory_robust_center_coords"] is not None
    assert 0.2 < float(middle["trajectory_robust_center_coords"][1]) < 1.0


def test_extract_lane_boundary_center_hints_requires_good_pairs() -> None:
    guide = LineString([(0.0, 0.0), (100.0, 0.0)])
    station_rows = aggregate_trajectory_stations(
        guide_line=guide,
        selected_rows=[{"source_traj_id": "a", "selection_weight": 3.0, "line": guide}],
        start_anchor=guide.interpolate(0.0, normalized=True),
        end_anchor=guide.interpolate(1.0, normalized=True),
        params=dict(DEFAULT_PARAMS),
    )
    good = extract_lane_boundary_center_hints(
        station_rows=station_rows,
        lane_boundaries=(LineString([(0.0, -3.0), (100.0, -3.0)]), LineString([(0.0, 3.0), (100.0, 3.0)])),
        safe_surface=guide.buffer(10.0, cap_style=2),
        params=dict(DEFAULT_PARAMS),
    )
    assert good["hint_count"] > 0
    bad = extract_lane_boundary_center_hints(
        station_rows=station_rows,
        lane_boundaries=(LineString([(0.0, 4.0), (100.0, 4.0)]),),
        safe_surface=guide.buffer(10.0, cap_style=2),
        params=dict(DEFAULT_PARAMS),
    )
    assert bad["hint_count"] == 0


def test_build_center_corrected_spine_prefers_high_quality_lane_hints() -> None:
    station_rows = [
        {"station_index": 0, "station_norm": 0.0, "station_distance_m": 0.0, "guide_coords": [0.0, 0.0], "trajectory_robust_center_coords": [0.0, 0.0], "trajectory_confidence": 1.0, "lane_boundary_center_hint_coords": None, "lane_boundary_quality_score": 0.0, "lane_boundary_weight": 0.0},
        {"station_index": 1, "station_norm": 0.25, "station_distance_m": 25.0, "guide_coords": [25.0, 0.0], "trajectory_robust_center_coords": [25.0, 1.8], "trajectory_confidence": 0.9, "lane_boundary_center_hint_coords": [25.0, 0.9], "lane_boundary_quality_score": 0.82, "lane_boundary_weight": 0.35},
        {"station_index": 2, "station_norm": 0.5, "station_distance_m": 50.0, "guide_coords": [50.0, 0.0], "trajectory_robust_center_coords": [50.0, 2.4], "trajectory_confidence": 0.9, "lane_boundary_center_hint_coords": [50.0, 1.1], "lane_boundary_quality_score": 0.78, "lane_boundary_weight": 0.35},
        {"station_index": 3, "station_norm": 0.75, "station_distance_m": 75.0, "guide_coords": [75.0, 0.0], "trajectory_robust_center_coords": [75.0, 1.8], "trajectory_confidence": 0.9, "lane_boundary_center_hint_coords": [75.0, 0.9], "lane_boundary_quality_score": 0.82, "lane_boundary_weight": 0.35},
        {"station_index": 4, "station_norm": 1.0, "station_distance_m": 100.0, "guide_coords": [100.0, 0.0], "trajectory_robust_center_coords": [100.0, 0.0], "trajectory_confidence": 1.0, "lane_boundary_center_hint_coords": None, "lane_boundary_quality_score": 0.0, "lane_boundary_weight": 0.0},
    ]
    correction = build_center_corrected_spine(
        station_rows=[dict(row) for row in station_rows],
        start_anchor=LineString([(0.0, 0.0), (100.0, 0.0)]).interpolate(0.0, normalized=True),
        end_anchor=LineString([(0.0, 0.0), (100.0, 0.0)]).interpolate(1.0, normalized=True),
        params=dict(DEFAULT_PARAMS),
    )
    corrected_rows = correction["station_rows"]
    assert bool(correction["correction_enabled_bool"]) is True
    assert int(correction["high_quality_count"]) >= 2
    assert float(corrected_rows[2]["center_correction_m"]) > 0.0
    assert float(corrected_rows[2]["center_corrected_spine_coords"][1]) < float(station_rows[2]["trajectory_robust_center_coords"][1])


def test_estimate_endpoint_local_tangents_reports_source_and_confidence() -> None:
    selected_rows = [
        {"source_traj_id": "a", "selection_weight": 3.0, "line": LineString([(0.0, 0.0), (20.0, 0.8), (100.0, 0.0)])},
        {"source_traj_id": "b", "selection_weight": 2.0, "line": LineString([(0.0, 0.1), (20.0, 0.9), (100.0, 0.1)])},
    ]
    station_rows = [
        {"station_index": 0, "station_norm": 0.0, "station_distance_m": 0.0, "trajectory_robust_center_coords": [0.0, 0.0], "lane_boundary_center_tangent": [1.0, 0.02], "lane_boundary_quality_score": 0.8},
        {"station_index": 1, "station_norm": 0.2, "station_distance_m": 20.0, "trajectory_robust_center_coords": [20.0, 0.8], "lane_boundary_center_tangent": [1.0, 0.02], "lane_boundary_quality_score": 0.8},
        {"station_index": 2, "station_norm": 0.8, "station_distance_m": 80.0, "trajectory_robust_center_coords": [80.0, 0.8], "lane_boundary_center_tangent": [1.0, -0.02], "lane_boundary_quality_score": 0.8},
        {"station_index": 3, "station_norm": 1.0, "station_distance_m": 100.0, "trajectory_robust_center_coords": [100.0, 0.0], "lane_boundary_center_tangent": [1.0, -0.02], "lane_boundary_quality_score": 0.8},
    ]
    tangents = estimate_endpoint_local_tangents(
        selected_rows=selected_rows,
        station_rows=station_rows,
        corrected_spine_line=LineString([(0.0, 0.0), (50.0, 1.0), (100.0, 0.0)]),
        start_anchor=LineString([(0.0, 0.0), (100.0, 0.0)]).interpolate(0.0, normalized=True),
        end_anchor=LineString([(0.0, 0.0), (100.0, 0.0)]).interpolate(1.0, normalized=True),
        params=dict(DEFAULT_PARAMS),
    )
    assert bool(tangents["enabled_bool"]) is True
    assert isinstance(tangents["src"]["tangent"], list)
    assert isinstance(tangents["dst"]["tangent"], list)
    assert float(tangents["src"]["confidence"]) > 0.0
    assert float(tangents["dst"]["confidence"]) > 0.0
    assert str(tangents["src"]["source_type"])


def test_fit_global_centerline_honors_hard_anchors_and_lane_hints() -> None:
    station_rows = [
        {"station_index": 0, "station_norm": 0.0, "guide_coords": [0.0, 0.0], "trajectory_robust_center_coords": [0.0, 0.0], "trajectory_confidence": 1.0, "lane_boundary_center_hint_coords": None, "lane_boundary_weight": 0.0},
        {"station_index": 1, "station_norm": 0.25, "guide_coords": [25.0, 0.0], "trajectory_robust_center_coords": [25.0, 1.6], "trajectory_confidence": 0.9, "lane_boundary_center_hint_coords": [25.0, 0.8], "lane_boundary_weight": 0.3},
        {"station_index": 2, "station_norm": 0.5, "guide_coords": [50.0, 0.0], "trajectory_robust_center_coords": [50.0, 2.2], "trajectory_confidence": 0.9, "lane_boundary_center_hint_coords": [50.0, 1.0], "lane_boundary_weight": 0.35},
        {"station_index": 3, "station_norm": 0.75, "guide_coords": [75.0, 0.0], "trajectory_robust_center_coords": [75.0, 1.6], "trajectory_confidence": 0.9, "lane_boundary_center_hint_coords": [75.0, 0.8], "lane_boundary_weight": 0.3},
        {"station_index": 4, "station_norm": 1.0, "guide_coords": [100.0, 0.0], "trajectory_robust_center_coords": [100.0, 0.0], "trajectory_confidence": 1.0, "lane_boundary_center_hint_coords": None, "lane_boundary_weight": 0.0},
    ]
    no_hint_line, _ = fit_global_centerline(
        station_rows=[dict(row) for row in station_rows],
        start_anchor=LineString([(0.0, 0.0), (100.0, 0.0)]).interpolate(0.0, normalized=True),
        end_anchor=LineString([(0.0, 0.0), (100.0, 0.0)]).interpolate(1.0, normalized=True),
        params=dict(DEFAULT_PARAMS),
        use_lane_hints=False,
    )
    with_hint_line, _ = fit_global_centerline(
        station_rows=[dict(row) for row in station_rows],
        start_anchor=LineString([(0.0, 0.0), (100.0, 0.0)]).interpolate(0.0, normalized=True),
        end_anchor=LineString([(0.0, 0.0), (100.0, 0.0)]).interpolate(1.0, normalized=True),
        params=dict(DEFAULT_PARAMS),
        use_lane_hints=True,
    )
    assert no_hint_line is not None and with_hint_line is not None
    assert tuple(with_hint_line.coords[0]) == (0.0, 0.0)
    assert tuple(with_hint_line.coords[-1]) == (100.0, 0.0)
    assert float(with_hint_line.interpolate(0.5, normalized=True).y) < float(no_hint_line.interpolate(0.5, normalized=True).y)


def test_fit_global_centerline_enforces_endpoint_tangent_continuity() -> None:
    station_rows = [
        {"station_index": 0, "station_norm": 0.0, "station_distance_m": 0.0, "guide_coords": [0.0, 0.0], "center_corrected_spine_coords": [0.0, 0.0], "trajectory_robust_center_coords": [0.0, 0.0], "trajectory_confidence": 1.0},
        {"station_index": 1, "station_norm": 0.2, "station_distance_m": 20.0, "guide_coords": [20.0, 0.0], "center_corrected_spine_coords": [20.0, 3.0], "trajectory_robust_center_coords": [20.0, 3.0], "trajectory_confidence": 0.9},
        {"station_index": 2, "station_norm": 0.5, "station_distance_m": 50.0, "guide_coords": [50.0, 0.0], "center_corrected_spine_coords": [50.0, 4.0], "trajectory_robust_center_coords": [50.0, 4.0], "trajectory_confidence": 0.9},
        {"station_index": 3, "station_norm": 0.8, "station_distance_m": 80.0, "guide_coords": [80.0, 0.0], "center_corrected_spine_coords": [80.0, 3.0], "trajectory_robust_center_coords": [80.0, 3.0], "trajectory_confidence": 0.9},
        {"station_index": 4, "station_norm": 1.0, "station_distance_m": 100.0, "guide_coords": [100.0, 0.0], "center_corrected_spine_coords": [100.0, 0.0], "trajectory_robust_center_coords": [100.0, 0.0], "trajectory_confidence": 1.0},
    ]
    with_tangent_line, metrics = fit_global_centerline(
        station_rows=[dict(row) for row in station_rows],
        start_anchor=LineString([(0.0, 0.0), (100.0, 0.0)]).interpolate(0.0, normalized=True),
        end_anchor=LineString([(0.0, 0.0), (100.0, 0.0)]).interpolate(1.0, normalized=True),
        params=dict(DEFAULT_PARAMS),
        use_lane_hints=False,
        target_key="center_corrected_spine_coords",
        endpoint_tangents={
            "src": {"tangent": [1.0, 0.0]},
            "dst": {"tangent": [1.0, 0.0]},
        },
    )
    assert with_tangent_line is not None
    assert float(metrics["src_tangent_error_deg"]) < 25.0
    assert float(metrics["dst_tangent_error_deg"]) < 25.0


def test_pipeline_uses_global_fit_as_default_final_export(tmp_path: Path) -> None:
    patch_id = "global_fit_default"
    data_root = tmp_path / "data"
    intersection_fc = _fc(
        [
            _line_feature([(0.0, -12.0), (0.0, 12.0)], {"nodeid": 1}),
            _line_feature([(100.0, -12.0), (100.0, 12.0)], {"nodeid": 2}),
        ],
        "EPSG:3857",
    )
    drivezone_fc = _fc([_poly_feature([(-5.0, -6.0), (105.0, -6.0), (105.0, 6.0), (-5.0, 6.0)])], "EPSG:3857")
    lane_fc = _fc(
        [
            _line_feature([(0.0, -3.0), (50.0, -2.8), (100.0, -3.0)], {"id": 10}),
            _line_feature([(0.0, 3.0), (50.0, 2.9), (100.0, 3.0)], {"id": 11}),
        ],
        "EPSG:3857",
    )
    road_fc = _fc([_line_feature([(0.0, 0.0), (100.0, 0.0)], {"snodeid": 1, "enodeid": 2})], "EPSG:3857")
    tracks = [
        [(0.0, 0.0), (25.0, 0.8), (50.0, 1.3), (75.0, 0.8), (100.0, 0.0)],
        [(0.0, 0.1), (25.0, 0.7), (50.0, 1.1), (75.0, 0.7), (100.0, 0.1)],
        [(0.0, -0.1), (25.0, 0.6), (50.0, 1.0), (75.0, 0.6), (100.0, -0.1)],
    ]
    _write_patch(
        data_root,
        patch_id=patch_id,
        intersection_fc=intersection_fc,
        drivezone_fc=drivezone_fc,
        traj_tracks=tracks,
        lane_fc=lane_fc,
        road_fc=road_fc,
    )
    out_root = tmp_path / "out"
    run_full_pipeline(data_root=data_root, patch_id=patch_id, run_id="run_global_fit", out_root=out_root, params=dict(DEFAULT_PARAMS))
    artifact = json.loads((out_root / "run_global_fit" / "patches" / patch_id / "step6" / "final_roads.json").read_text(encoding="utf-8"))
    assert artifact["road_results"], "expected at least one road result"
    chosen = artifact["road_results"][0]
    assert str(chosen["final_export_source"]).startswith("trajectory_centered_global_fit")
    assert bool(chosen["global_fit_used_bool"]) is True
    assert bool(chosen["geometry_refine_applied"]) is False
    patch_out = out_root / "run_global_fit" / "patches" / patch_id
    assert (patch_out / "step5_center_corrected_spine.geojson").exists()
    assert (patch_out / "step5_endpoint_tangent_trace.geojson").exists()
    assert (patch_out / "step5_global_fit_v2_trace.json").exists()
    assert (patch_out / "step5_global_fit_v2_samples.geojson").exists()
    assert (patch_out / "debug" / "final_geometry_global_fit_v2_components.geojson").exists()
