from __future__ import annotations

import json
from pathlib import Path

from highway_topo_poc.modules.t05_topology_between_rc import run as run_mod
from highway_topo_poc.modules.t05_topology_between_rc.pipeline import RunResult
from highway_topo_poc.modules.t05_topology_between_rc.qa_audit import (
    _selected_metrics,
    _summary_key_lines,
    emit_qa_artifacts,
    upsert_external_audit_topic,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_data_patch(root: Path, *, patch_id: str) -> Path:
    patch_dir = root / patch_id
    vector_dir = patch_dir / "Vector"
    traj_dir = patch_dir / "Traj" / "0001"
    pointcloud_dir = patch_dir / "PointCloud"
    vector_dir.mkdir(parents=True, exist_ok=True)
    traj_dir.mkdir(parents=True, exist_ok=True)
    pointcloud_dir.mkdir(parents=True, exist_ok=True)
    _write_text(vector_dir / "DriveZone.geojson", "{}\n")
    _write_text(vector_dir / "intersection_l.geojson", "{}\n")
    _write_text(vector_dir / "LaneBoundary.geojson", "{}\n")
    _write_text(vector_dir / "RCSDNode.geojson", "{}\n")
    _write_text(traj_dir / "raw_dat_pose.geojson", "{}\n")
    return patch_dir


def _build_patch_output(root: Path, *, run_id: str, patch_id: str) -> Path:
    patch_out_dir = root / run_id / "patches" / patch_id
    _write_text(
        patch_out_dir / "summary.txt",
        "\n".join(
            [
                "=== t05_topology_between_rc summary ===",
                f"run_id: {run_id}",
                "git_sha: abc1234",
                f"patch_id: {patch_id}",
                "overall_pass: false",
                "",
                "road_count: 1",
                "road_features_count: 1",
                "road_candidate_count: 1",
                "no_geometry_candidate: false",
                "hard_anomaly_count: 1",
                "soft_issue_count: 1",
                "",
                "hard_breakpoints_topk:",
                "- road_id=r1 src=10 dst=11 reason=ENDPOINT_NOT_ON_XSEC hint=endpoint drift",
                "",
                "soft_breakpoints_topk:",
                "- road_id=r1 src=10 dst=11 reason=LOW_SUPPORT hint=support low",
                "",
                "params:",
                "- params_digest=deadbeefcafe",
                "",
            ]
        ),
    )
    _write_json(
        patch_out_dir / "metrics.json",
        {
            "patch_id": patch_id,
            "road_count": 1,
            "road_features_count": 1,
            "road_candidate_count": 1,
            "no_geometry_candidate": False,
            "unique_pair_count": 1,
            "hard_anomaly_count": 1,
            "soft_issue_count": 1,
            "avg_conf": 0.75,
            "p10_conf": 0.75,
            "p50_conf": 0.75,
            "center_coverage_avg": 0.88,
            "endpoint_center_offset_p50": 0.9,
            "endpoint_center_offset_p90": 1.2,
            "endpoint_center_offset_max": 1.4,
            "hard_breakpoint_count": 1,
            "soft_breakpoint_count": 1,
            "lane_boundary_used": True,
            "lane_boundary_crs_method": "inherit_drivezone",
            "lane_boundary_crs_inferred": True,
            "lane_boundary_crs_name_final": "EPSG:3857",
            "pointcloud_enabled": False,
            "params_digest": "deadbeefcafe",
        },
    )
    _write_json(
        patch_out_dir / "gate.json",
        {
            "overall_pass": False,
            "hard_breakpoints": [
                {
                    "road_id": "r1",
                    "src_nodeid": 10,
                    "dst_nodeid": 11,
                    "reason": "ENDPOINT_NOT_ON_XSEC",
                    "severity": "hard",
                    "hint": "endpoint drift",
                }
            ],
            "soft_breakpoints": [
                {
                    "road_id": "r1",
                    "src_nodeid": 10,
                    "dst_nodeid": 11,
                    "reason": "LOW_SUPPORT",
                    "severity": "soft",
                    "hint": "support low",
                }
            ],
            "params_digest": "deadbeefcafe",
            "version": "t05_gate_v1",
        },
    )
    _write_text(patch_out_dir / "debug" / "lane_boundary_crs_fix.json", "{}\n")
    _write_text(patch_out_dir / "step1" / "step1_support_trajs.geojson", "{}\n")
    return patch_out_dir


def _static_evidence(repo_root: Path, git_sha: str) -> list[dict[str, str]]:
    return [
        {
            "evidence_type": "code_ref",
            "source": (repo_root / "src" / "highway_topo_poc" / "modules" / "t05_topology_between_rc" / "qa_audit.py").as_posix(),
            "related_git_sha": git_sha,
            "related_run_id": "NA",
            "related_patch_id": "NA",
            "note": "qa audit entrypoint",
        },
        {
            "evidence_type": "diff_ref",
            "source": (repo_root / "src" / "highway_topo_poc" / "modules" / "t05_topology_between_rc" / "run.py").as_posix(),
            "related_git_sha": git_sha,
            "related_run_id": "NA",
            "related_patch_id": "NA",
            "note": "run fallback behavior",
        },
        {
            "evidence_type": "rule_ref",
            "source": (repo_root / "modules" / "t05_topology_between_rc" / "audits" / "T05_DEV_QA_PROTOCOL.md").as_posix(),
            "related_git_sha": git_sha,
            "related_run_id": "NA",
            "related_patch_id": "NA",
            "note": "dev qa protocol",
        },
    ]


def test_upsert_external_audit_topic_supports_code_only_without_run(tmp_path: Path) -> None:
    repo_root = tmp_path
    git_sha = "abc1234"
    external_dir = upsert_external_audit_topic(
        repo_root=repo_root,
        git_sha=git_sha,
        audit_topic="external_audit_semantic_sync",
        scope_reason="external_audit_can_start_without_new_inner_run",
        question_to_qa="confirm_static_audit_can_start_with_code_evidence_only",
        audit_trigger="code_change",
        static_audit_allowed=True,
        target_runs=None,
        target_patches=None,
        evidence_items=_static_evidence(repo_root, git_sha),
        evidence_mode="code_only",
        latest_inner_run_id="NA",
        latest_inner_patch_id="NA",
        qa_blocked_reason="none",
    )

    status = json.loads((external_dir / "audit_status.json").read_text(encoding="utf-8"))
    assert status["scope_ready"] is True
    assert status["evidence_ready"] is True
    assert status["evidence_mode"] == "code_only"
    assert status["latest_inner_run_id"] == "NA"
    assert status["latest_inner_patch_id"] == "NA"
    assert status["qa_blocked_reason"] == "none"

    scope_text = (external_dir / "AUDIT_SCOPE.md").read_text(encoding="utf-8")
    assert "audit_trigger: code_change" in scope_text
    assert "static_audit_allowed: true" in scope_text
    assert "target_runs: NA" in scope_text
    assert "target_patches: NA" in scope_text

    evidence_text = (external_dir / "EVIDENCE_INDEX.md").read_text(encoding="utf-8")
    assert "evidence_mode: code_only" in evidence_text
    assert "- evidence_type: code_ref" in evidence_text
    assert "- related_run_id: NA" in evidence_text


def test_emit_qa_artifacts_upgrades_static_topic_to_code_plus_run(tmp_path: Path) -> None:
    repo_root = tmp_path
    git_sha = "abc1234"
    patch_id = "p_audit"
    run_id = "run_audit"
    upsert_external_audit_topic(
        repo_root=repo_root,
        git_sha=git_sha,
        audit_topic="traj_surface_endpoint_binding",
        scope_reason="static_topic_bootstrap",
        question_to_qa="can_static_audit_start_before_new_run",
        audit_trigger="business_rule_check",
        static_audit_allowed=True,
        evidence_items=_static_evidence(repo_root, git_sha),
        evidence_mode="code_only",
        latest_inner_run_id="NA",
        latest_inner_patch_id="NA",
        qa_blocked_reason="none",
    )
    data_patch_dir = _build_data_patch(tmp_path / "data_root", patch_id=patch_id)
    patch_out_dir = _build_patch_output(
        tmp_path / "outputs" / "_work" / "t05_topology_between_rc",
        run_id=run_id,
        patch_id=patch_id,
    )

    result = emit_qa_artifacts(
        repo_root=repo_root,
        data_patch_dir=data_patch_dir,
        patch_out_dir=patch_out_dir,
        run_id=run_id,
        patch_id=patch_id,
        git_sha=git_sha,
        visual_verdict="endpoint_binding_failed_but_reviewable",
        execution_goal="formal_diagnostic_run",
        focus_question="is_endpoint_binding_stable",
        audit_topic="traj_surface_endpoint_binding",
        scope_reason="formal_run_followup",
        question_to_qa="confirm_whether_run_evidence_supports_the_static_diagnosis",
    )

    assert result.bundle_path is not None and result.bundle_path.is_file()
    assert result.external_dir is not None and result.external_dir.is_dir()

    status = json.loads((result.external_dir / "audit_status.json").read_text(encoding="utf-8"))
    assert status["evidence_ready"] is True
    assert status["evidence_mode"] == "code_plus_run"
    assert status["latest_inner_run_id"] == run_id
    assert status["latest_inner_patch_id"] == patch_id

    scope_text = (result.external_dir / "AUDIT_SCOPE.md").read_text(encoding="utf-8")
    assert "audit_trigger: run_bundle_followup" in scope_text
    assert "- run_audit" in scope_text
    assert "- p_audit" in scope_text

    evidence_text = (result.external_dir / "EVIDENCE_INDEX.md").read_text(encoding="utf-8")
    assert "evidence_mode: code_plus_run" in evidence_text
    assert "- evidence_type: inner_bundle" in evidence_text
    assert f"- related_run_id: {run_id}" in evidence_text
    assert result.bundle_path.as_posix() in evidence_text


def test_same_pair_resolution_metrics_and_summary_keys_are_selected() -> None:
    payload = {
        "patch_id": "p1",
        "road_count": 2,
        "road_features_count": 2,
        "road_candidate_count": 3,
        "pair_count": 1,
        "unique_pair_count": 1,
        "same_pair_handled_pair_count": 1,
        "same_pair_handled_output_count": 2,
        "same_pair_single_output_pair_count": 0,
        "same_pair_multi_road_pair_count": 1,
        "same_pair_multi_road_output_count": 2,
        "same_pair_partial_unresolved_pair_count": 0,
        "same_pair_hard_conflict_pair_count": 0,
        "no_geometry_candidate": True,
        "no_geometry_candidate_count": 1,
    }

    selected = _selected_metrics(payload)

    assert selected["same_pair_handled_pair_count"] == 1
    assert selected["same_pair_handled_output_count"] == 2
    assert selected["same_pair_single_output_pair_count"] == 0
    assert selected["same_pair_multi_road_pair_count"] == 1
    assert selected["same_pair_multi_road_output_count"] == 2
    assert selected["same_pair_partial_unresolved_pair_count"] == 0
    assert selected["same_pair_hard_conflict_pair_count"] == 0

    summary_lines = _summary_key_lines(
        "\n".join(
            [
                "run_id: run1",
                "pair_count: 1",
                "same_pair_handled_pair_count: 1",
                "same_pair_handled_output_count: 2",
                "same_pair_single_output_pair_count: 0",
                "same_pair_multi_road_pair_count: 1",
                "same_pair_multi_road_output_count: 2",
                "same_pair_partial_unresolved_pair_count: 0",
                "same_pair_hard_conflict_pair_count: 0",
                "params:",
                "- params_digest=abc",
            ]
        )
    )
    assert "same_pair_handled_pair_count: 1" in summary_lines
    assert "same_pair_partial_unresolved_pair_count: 0" in summary_lines


def test_emit_qa_artifacts_acknowledges_previous_report(tmp_path: Path) -> None:
    repo_root = tmp_path
    patch_id = "p_followup"
    run_id = "run_followup"
    data_patch_dir = _build_data_patch(tmp_path / "data_root", patch_id=patch_id)
    patch_out_dir = _build_patch_output(
        tmp_path / "outputs" / "_work" / "t05_topology_between_rc",
        run_id=run_id,
        patch_id=patch_id,
    )

    previous_status_path = (
        repo_root
        / "outputs"
        / "_qa_external"
        / "t05_topology_between_rc"
        / "by_version"
        / "oldsha1"
        / "step1_unique_route_recall"
        / "audit_status.json"
    )
    _write_json(
        previous_status_path,
        {
            "git_sha": "oldsha1",
            "audit_topic": "step1_unique_route_recall",
            "scope_ready": True,
            "evidence_ready": True,
            "evidence_mode": "code_plus_run",
            "qa_report_ready": True,
            "dev_acknowledged": False,
            "updated_at": "2026-03-07T10:00:00+08:00",
            "latest_inner_run_id": "old_run",
            "latest_inner_patch_id": "old_patch",
            "qa_blocked_reason": "none",
        },
    )

    result = emit_qa_artifacts(
        repo_root=repo_root,
        data_patch_dir=data_patch_dir,
        patch_out_dir=patch_out_dir,
        run_id=run_id,
        patch_id=patch_id,
        git_sha="newsha2",
        visual_verdict="followup_review_ready",
        execution_goal="formal_diagnostic_run",
        focus_question="did_the_previous_route_recall_issue_change",
        audit_topic="step1_unique_route_recall",
        scope_reason="followup_after_previous_qa_report",
        question_to_qa="confirm_if_the_followup_evidence_changes_priority",
        previous_git_sha="oldsha1",
        previous_audit_topic="step1_unique_route_recall",
        previous_priority="Priority-1",
        action_taken="tighten_endpoint_binding",
    )

    assert result.bundle_path is not None and result.bundle_path.is_file()
    bundle_text = result.bundle_path.read_text(encoding="utf-8")
    assert "previous_git_sha: oldsha1" in bundle_text
    assert "previous_audit_topic: step1_unique_route_recall" in bundle_text
    assert "previous_priority: Priority-1" in bundle_text
    assert "action_taken: tighten_endpoint_binding" in bundle_text

    previous_status = json.loads(previous_status_path.read_text(encoding="utf-8"))
    assert previous_status["dev_acknowledged"] is True


def test_main_failure_writes_minimal_auditable_outputs(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data_root"
    patch_id = "p_fail"
    _build_data_patch(data_root, patch_id=patch_id)

    def _raise_run_patch(**_: object) -> RunResult:
        raise RuntimeError("boom from unit test")

    monkeypatch.setattr(run_mod, "run_patch", _raise_run_patch)
    monkeypatch.setattr(run_mod, "resolve_repo_root", lambda _: tmp_path)
    monkeypatch.setattr(run_mod, "git_short_sha", lambda _: "unitsha")

    rc = run_mod.main(
        [
            "--data_root",
            str(data_root),
            "--patch_id",
            patch_id,
            "--run_id",
            "unit_fail_run",
            "--out_root",
            str(tmp_path / "out"),
            "--qa_enable",
            "1",
            "--qa_visual_verdict",
            "NA",
        ]
    )

    assert rc == 1
    fail_patch_dir = tmp_path / "out" / "unit_fail_run" / "patches" / patch_id
    assert (fail_patch_dir / "summary.txt").is_file()
    assert (fail_patch_dir / "metrics.json").is_file()
    assert (fail_patch_dir / "gate.json").is_file()
    bundle_path = fail_patch_dir / "qa_inner" / f"T05_EXEC_AUDIT_BUNDLE__unit_fail_run__{patch_id}.md"
    assert bundle_path.is_file()

    metrics_payload = json.loads((fail_patch_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics_payload["runtime_exception"] is True
    assert metrics_payload["error_type"] == "RuntimeError"

    gate_payload = json.loads((fail_patch_dir / "gate.json").read_text(encoding="utf-8"))
    assert gate_payload["overall_pass"] is False
    assert gate_payload["hard_breakpoints"][0]["reason"] == "RUNTIME_EXCEPTION"
