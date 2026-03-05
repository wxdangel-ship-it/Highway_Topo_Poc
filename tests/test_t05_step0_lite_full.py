from __future__ import annotations

from shapely.geometry import LineString, Polygon

from highway_topo_poc.modules.t05_topology_between_rc import pipeline
from highway_topo_poc.modules.t05_topology_between_rc.io import CrossSection


def _mk_xsec(nodeid: int, coords: list[tuple[float, float]]) -> CrossSection:
    return CrossSection(
        nodeid=int(nodeid),
        geometry_metric=LineString(coords),
        properties={"nodeid": int(nodeid)},
    )


def test_step0_lite_passthrough_and_no_traj_union(monkeypatch) -> None:
    called = {"n": 0}

    def _spy_traj_union(*args, **kwargs):
        called["n"] += 1
        return None

    monkeypatch.setattr(pipeline, "_build_traj_union_for_crossing", _spy_traj_union)

    xsec = _mk_xsec(1, [(0.0, -20.0), (0.0, 20.0)])
    drivezone = Polygon([(-10.0, -50.0), (10.0, -50.0), (10.0, 50.0), (-10.0, 50.0)])

    out_map, _anchors, _trunc, _gate_all, gate_meta, stats = pipeline._truncate_cross_sections_for_crossing(
        xsec_map={1: xsec},
        lane_boundaries_metric=[],
        trajectories=[],
        drivezone_zone_metric=drivezone,
        gore_zone_metric=None,
        params=dict(pipeline.DEFAULT_PARAMS),
    )

    assert called["n"] == 0
    assert 1 in out_map
    assert out_map[1].geometry_metric.equals(xsec.geometry_metric)
    assert str((gate_meta.get(1) or {}).get("mode")) == "passthrough"
    assert int(stats.get("xsec_passthrough_count", 0)) == 1
    assert int(stats.get("xsec_repaired_count", 0)) == 0
    assert int(stats.get("xsec_failed_count", 0)) == 0


def test_step0_lite_failed_then_full_repaired() -> None:
    xsec = _mk_xsec(2, [(0.0, -10.0), (0.0, 10.0)])
    drivezone = Polygon([(-10.0, -3.0), (10.0, -3.0), (10.0, 3.0), (-10.0, 3.0)])

    out_map, _anchors, _trunc, _gate_all, gate_meta, stats = pipeline._truncate_cross_sections_for_crossing(
        xsec_map={2: xsec},
        lane_boundaries_metric=[],
        trajectories=[],
        drivezone_zone_metric=drivezone,
        gore_zone_metric=None,
        params=dict(pipeline.DEFAULT_PARAMS),
    )

    assert 2 in out_map
    got = out_map[2].geometry_metric
    assert float(got.length) < float(xsec.geometry_metric.length)
    assert str((gate_meta.get(2) or {}).get("mode")) == "repaired"
    assert int(stats.get("xsec_passthrough_count", 0)) == 0
    assert int(stats.get("xsec_repaired_count", 0)) == 1
    assert int(stats.get("xsec_failed_count", 0)) == 0


def test_step0_lite_full_failed_marks_gate_empty() -> None:
    xsec = _mk_xsec(3, [(0.0, -10.0), (0.0, 10.0)])
    drivezone_far = Polygon([(90.0, 90.0), (110.0, 90.0), (110.0, 110.0), (90.0, 110.0)])

    out_map, _anchors, _trunc, _gate_all, gate_meta, stats = pipeline._truncate_cross_sections_for_crossing(
        xsec_map={3: xsec},
        lane_boundaries_metric=[],
        trajectories=[],
        drivezone_zone_metric=drivezone_far,
        gore_zone_metric=None,
        params=dict(pipeline.DEFAULT_PARAMS),
    )

    assert 3 not in out_map
    assert str((gate_meta.get(3) or {}).get("mode")) == "failed"
    assert int(stats.get("xsec_failed_count", 0)) == 1
    assert int(stats.get("xsec_gate_empty_count", 0)) >= 1


def test_step0_mode_full_keeps_old_gate_behavior() -> None:
    xsec = _mk_xsec(4, [(0.0, -10.0), (0.0, 10.0)])
    drivezone = Polygon([(-10.0, -50.0), (10.0, -50.0), (10.0, 50.0), (-10.0, 50.0)])
    params = dict(pipeline.DEFAULT_PARAMS)
    params["STEP0_MODE"] = "full"

    out_map, _anchors, _trunc, _gate_all, gate_meta, stats = pipeline._truncate_cross_sections_for_crossing(
        xsec_map={4: xsec},
        lane_boundaries_metric=[],
        trajectories=[],
        drivezone_zone_metric=drivezone,
        gore_zone_metric=None,
        params=params,
    )

    assert 4 in out_map
    assert str((gate_meta.get(4) or {}).get("mode")) == "repaired"
    assert int(stats.get("xsec_passthrough_count", 0)) == 0
    assert int(stats.get("xsec_repaired_count", 0)) == 1
