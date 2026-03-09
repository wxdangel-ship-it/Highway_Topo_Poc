from __future__ import annotations

from highway_topo_poc.modules.t05_topology_between_rc.metrics import build_metrics_payload


def test_metrics_include_endpoint_center_offset_stats() -> None:
    roads = [
        {
            "road_id": "100_200",
            "src_nodeid": 100,
            "dst_nodeid": 200,
            "conf": 0.9,
            "center_sample_coverage": 0.95,
            "hard_anomaly": False,
            "soft_issue_flags": [],
            "endpoint_center_offset_m_src": 0.7,
            "endpoint_center_offset_m_dst": 1.4,
        },
        {
            "road_id": "200_300",
            "src_nodeid": 200,
            "dst_nodeid": 300,
            "conf": 0.8,
            "center_sample_coverage": 0.9,
            "hard_anomaly": False,
            "soft_issue_flags": [],
            "endpoint_center_offset_m_src": 1.0,
            "endpoint_center_offset_m_dst": 2.2,
        },
    ]
    payload = build_metrics_payload(
        patch_id="2855795596723843",
        roads=roads,
        hard_breakpoints=[],
        soft_breakpoints=[],
    )
    assert payload["endpoint_center_offset_p50"] is not None
    assert payload["endpoint_center_offset_p90"] is not None
    assert payload["endpoint_center_offset_max"] == 2.2


def test_metrics_include_line_to_target_region_stats() -> None:
    roads = [
        {
            "road_id": "100_200",
            "src_nodeid": 100,
            "dst_nodeid": 200,
            "src_type": "merge",
            "dst_type": "merge",
            "conf": 0.9,
            "center_sample_coverage": 0.95,
            "hard_anomaly": False,
            "soft_issue_flags": [],
            "endpoint_line_to_target_region_dist_src_m": 0.0,
            "endpoint_line_to_target_region_dist_dst_m": 0.2,
            "endpoint_line_to_target_region_closure_ok_src": True,
            "endpoint_line_to_target_region_closure_ok_dst": True,
        },
        {
            "road_id": "200_300",
            "src_nodeid": 200,
            "dst_nodeid": 300,
            "src_type": "merge",
            "dst_type": "diverge",
            "conf": 0.8,
            "center_sample_coverage": 0.9,
            "hard_anomaly": False,
            "soft_issue_flags": [],
            "endpoint_line_to_target_region_dist_src_m": 0.4,
            "endpoint_line_to_target_region_dist_dst_m": 1.5,
            "endpoint_line_to_target_region_closure_ok_src": True,
            "endpoint_line_to_target_region_closure_ok_dst": False,
        },
    ]
    payload = build_metrics_payload(
        patch_id="2855795596723843",
        roads=roads,
        hard_breakpoints=[],
        soft_breakpoints=[],
    )
    assert payload["endpoint_line_to_target_region_dist_p50"] is not None
    assert payload["endpoint_line_to_target_region_dist_p90"] is not None
    assert payload["endpoint_line_to_target_region_closure_checked_count"] == 4
    assert payload["endpoint_line_to_target_region_closure_fail_count"] == 1
    assert payload["merge_diverge_endpoint_closure_fail_count"] == 1
