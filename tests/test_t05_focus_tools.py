from __future__ import annotations

import json
from pathlib import Path

from highway_topo_poc.modules.t05_topology_between_rc import focus_report, run


def test_parse_args_accepts_focus_pairs_and_src_nodeids() -> None:
    args = run._parse_args(
        [
            "--patch_id",
            "5417632623039346",
            "--focus_pair",
            "23287538:765141",
            "--focus_pair",
            "791873->791871",
            "--focus_src_nodeid",
            "21779764",
        ]
    )

    assert args.focus_pair == [(23287538, 765141), (791873, 791871)]
    assert args.focus_src_nodeid == [21779764]


def test_build_focus_report_extracts_pair_stage_and_outputs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run" / "patches" / "5417632623039346"
    (run_dir / "debug").mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.txt").write_text(
        "\n".join(
            [
                "run_id: unit_run",
                "git_sha: deadbee",
                "patch_id: 5417632623039346",
                "overall_pass: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "metrics.json").write_text(
        json.dumps(
            {
                "road_count": 1,
                "road_candidate_count": 2,
                "road_features_count": 1,
                "same_pair_partial_unresolved_pair_count": 1,
                "topology_fallback_support_count": 1,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "debug" / "pair_stage_status.json").write_text(
        json.dumps(
            {
                "pairs": [
                    {
                        "src_nodeid": 23287538,
                        "dst_nodeid": 765141,
                        "support_fallback_failure_stage": "reach_xsec",
                        "support_fallback_src_reach_allow_m": 40.0,
                        "selected_or_rejected_stage": "support_missing_after_topology",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    feature = {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "src_nodeid": 23287538,
            "dst_nodeid": 765141,
            "road_id": "23287538_765141",
            "hard_reasons": ["ROAD_OUTSIDE_DRIVEZONE"],
            "soft_reasons": [],
        },
    }
    for name in ("Road.geojson", "RCSDRoad.geojson"):
        (run_dir / name).write_text(
            json.dumps({"type": "FeatureCollection", "features": [feature]}, ensure_ascii=False),
            encoding="utf-8",
        )
    (run_dir / "gate.json").write_text(
        json.dumps(
            {
                "hard_breakpoints": [
                    {
                        "src_nodeid": 23287538,
                        "dst_nodeid": 765141,
                        "road_id": "23287538_765141",
                        "reason": "ROAD_OUTSIDE_DRIVEZONE",
                        "hint": "outside_len_m=1.0",
                    }
                ],
                "soft_breakpoints": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = focus_report.build_focus_report(run_dir=run_dir, pairs=[(23287538, 765141)])

    assert "pair: 23287538->765141" in report
    assert '"support_fallback_failure_stage": "reach_xsec"' in report
    assert '"support_fallback_src_reach_allow_m": 40.0' in report
    assert "Road.geojson: hits=1" in report
    assert "ROAD_OUTSIDE_DRIVEZONE" in report
