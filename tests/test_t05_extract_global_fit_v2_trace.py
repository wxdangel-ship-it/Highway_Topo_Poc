from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _build_run_dir(root: Path) -> Path:
    run_dir = root / "run"
    patch_dir = run_dir / "patches" / "5417632623039346"
    _write_json(
        patch_dir / "step5_global_fit_v2_trace.json",
        {
            "rows": [
                {
                    "segment_id": "seg_a",
                    "pair": "55353246:37687913",
                    "arc_id": "arc_a",
                    "trajectory_spine_source": "clean_endpoint_identity",
                    "trajectory_spine_quality": 0.91,
                    "trajectory_spine_support_count": 5,
                    "original_spine_coords": [[0.0, 0.0], [10.0, 0.2]],
                    "corrected_spine_coords": [[0.0, 0.0], [10.0, 0.1]],
                    "center_corrected_spine_quality": 0.88,
                    "centerline_correction_enabled_bool": True,
                    "centerline_correction_summary": {"correction_mean_m": 0.35, "correction_max_m": 0.65},
                    "lane_boundary_hint_usage": {"usage_ratio": 0.62},
                    "endpoint_tangent_trace": {
                        "src": {"source_type": "trajectory_local_trend", "confidence": 0.84},
                        "dst": {"source_type": "trajectory_local_trend", "confidence": 0.79},
                    },
                    "endpoint_tangent_continuity_enabled_bool": True,
                    "fitting_mode": "trajectory_centered_global_fit_v2",
                    "fitting_success_bool": True,
                    "global_fit_used_bool": True,
                    "fit_metrics": {
                        "src_tangent_error_deg": 8.0,
                        "dst_tangent_error_deg": 10.0,
                        "mean_target_offset_m": 0.55,
                        "endpoint_neighborhood_offset_m": 0.42,
                    },
                    "built_final_road": True,
                },
                {
                    "segment_id": "seg_b",
                    "pair": "55353307:608638238",
                    "arc_id": "arc_b",
                    "trajectory_spine_source": "support_family",
                    "trajectory_spine_quality": 0.72,
                    "trajectory_spine_support_count": 3,
                    "original_spine_coords": [[0.0, 0.0], [10.0, 0.8]],
                    "corrected_spine_coords": [[0.0, 0.0], [10.0, 0.7]],
                    "center_corrected_spine_quality": 0.52,
                    "centerline_correction_enabled_bool": True,
                    "centerline_correction_summary": {"correction_mean_m": 0.91, "correction_max_m": 1.62},
                    "lane_boundary_hint_usage": {"usage_ratio": 0.18},
                    "endpoint_tangent_trace": {
                        "src": {"source_type": "lane_boundary_local_tangent", "confidence": 0.68},
                        "dst": {"source_type": "corrected_spine_fallback", "confidence": 0.44},
                    },
                    "endpoint_tangent_continuity_enabled_bool": True,
                    "fitting_mode": "trajectory_centered_global_fit_v2",
                    "fitting_success_bool": True,
                    "global_fit_used_bool": False,
                    "fallback_reason": "quality_gate_reject",
                    "quality_gate_reason": "low_center_alignment",
                    "fit_metrics": {
                        "src_tangent_error_deg": 26.0,
                        "dst_tangent_error_deg": 31.0,
                        "mean_target_offset_m": 2.4,
                        "endpoint_neighborhood_offset_m": 1.8,
                    },
                    "built_final_road": True,
                },
                {
                    "segment_id": "seg_c",
                    "pair": "791873:791871",
                    "arc_id": "arc_c",
                    "trajectory_spine_source": "partial_support",
                    "trajectory_spine_quality": 0.43,
                    "trajectory_spine_support_count": 1,
                    "original_spine_coords": [[0.0, 0.0], [10.0, 1.1]],
                    "corrected_spine_coords": [[0.0, 0.0], [10.0, 0.9]],
                    "center_corrected_spine_quality": 0.41,
                    "centerline_correction_enabled_bool": False,
                    "centerline_correction_summary": {"correction_mean_m": 0.0, "correction_max_m": 0.0},
                    "lane_boundary_hint_usage": {"usage_ratio": 0.0},
                    "endpoint_tangent_trace": {
                        "src": {"source_type": "corrected_spine_fallback", "confidence": 0.25},
                        "dst": {"source_type": "corrected_spine_fallback", "confidence": 0.25},
                    },
                    "endpoint_tangent_continuity_enabled_bool": False,
                    "fitting_mode": "trajectory_centered_global_fit_v2",
                    "fitting_success_bool": False,
                    "global_fit_used_bool": False,
                    "fallback_reason": "global_fit_failed",
                    "fit_metrics": {
                        "src_tangent_error_deg": 34.0,
                        "dst_tangent_error_deg": 37.0,
                        "mean_target_offset_m": 3.2,
                        "endpoint_neighborhood_offset_m": 2.1,
                    },
                    "built_final_road": False,
                },
            ]
        },
    )
    _write_json(
        patch_dir / "step5_final_geometry_trace.json",
        {
            "rows": [
                {
                    "pair": "55353246:37687913",
                    "global_fit_used_bool": True,
                    "final_export_source": "trajectory_centered_global_fit_v2",
                    "built_final_road": True,
                },
                {
                    "pair": "55353307:608638238",
                    "global_fit_used_bool": False,
                    "final_export_source": "production_working_segment_slot_anchored",
                    "global_fit_fallback_reason": "quality_gate_reject",
                    "global_fit_quality_gate_reason": "low_center_alignment",
                    "built_final_road": True,
                },
                {
                    "pair": "791873:791871",
                    "global_fit_used_bool": False,
                    "final_export_source": "legacy_fallback",
                    "global_fit_fallback_reason": "global_fit_failed",
                    "built_final_road": False,
                },
            ]
        },
    )
    return run_dir


def test_extract_global_fit_v2_trace_summary_only_json(tmp_path: Path) -> None:
    run_dir = _build_run_dir(tmp_path)
    script = _repo_root() / "scripts" / "t05_extract_global_fit_v2_trace.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run_dir",
            str(run_dir),
            "--patch_id",
            "5417632623039346",
            "--summary_only",
        ],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert "rows" not in payload
    summary = dict(payload.get("summary") or {})
    overview = dict(summary.get("overview") or {})
    assert int(payload.get("row_count", 0)) == 3
    assert int(overview.get("fallback_count", 0)) == 2
    assert int(overview.get("built_false_count", 0)) == 1
    top_rows = list(summary.get("top_suspicious_rows") or [])
    assert top_rows
    assert str(top_rows[0].get("pair", "")) == "791873:791871"


def test_extract_global_fit_v2_trace_summary_text(tmp_path: Path) -> None:
    run_dir = _build_run_dir(tmp_path)
    script = _repo_root() / "scripts" / "t05_extract_global_fit_v2_trace.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run_dir",
            str(run_dir),
            "--patch_id",
            "5417632623039346",
            "--summary_only",
            "--format",
            "text",
        ],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "Abstract findings:" in result.stdout
    assert "Top suspicious rows:" in result.stdout
    assert "55353307:608638238" in result.stdout
