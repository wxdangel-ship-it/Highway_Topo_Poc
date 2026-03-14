from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any


def _pipeline_module():
    from . import pipeline

    return pipeline


def _stage3_witness(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    pipeline = _pipeline_module()
    return pipeline._step3_run_arc_evidence_stage(
        data_root=data_root,
        patch_id=patch_id,
        run_id=run_id,
        out_root=out_root,
        params=params,
    )


def _stage4_corridor_identity(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    pipeline = _pipeline_module()
    return pipeline._step3_run_corridor_identity_stage(
        data_root=data_root,
        patch_id=patch_id,
        run_id=run_id,
        out_root=out_root,
        params=params,
    )


def _stage5_slot_mapping(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    pipeline = _pipeline_module()
    return pipeline._step5_run_slot_mapping_stage(
        data_root=data_root,
        patch_id=patch_id,
        run_id=run_id,
        out_root=out_root,
        params=params,
    )


def _stage6_build_road(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    params: dict[str, Any],
) -> dict[str, Any]:
    pipeline = _pipeline_module()
    return pipeline._step5_run_build_road_stage(
        data_root=data_root,
        patch_id=patch_id,
        run_id=run_id,
        out_root=out_root,
        params=params,
    )


def run_stage(
    *,
    stage: str,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    force: bool = False,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pipeline = _pipeline_module()
    stage_name = str(stage)
    if stage_name not in pipeline.STAGES:
        raise ValueError(f"unknown_stage:{stage_name}")
    merged_params = pipeline._merge_params(params)
    patch_dir = pipeline.patch_root(out_root, run_id, patch_id)
    patch_dir.mkdir(parents=True, exist_ok=True)
    dbg_dir = pipeline.debug_dir(out_root, run_id, patch_id)
    dbg_dir.mkdir(parents=True, exist_ok=True)
    existing_state = pipeline._load_previous_state(out_root, run_id, patch_id, stage_name)
    if existing_state is not None and bool(existing_state.get("ok")) and not bool(force):
        return {"stage": stage_name, "status": "skipped", "reason": "already_completed"}
    pipeline._require_previous_stage(out_root, run_id, patch_id, stage_name)
    runner = {
        "step1_input_frame": pipeline._stage1_input_frame,
        "step2_segment": pipeline._stage2_segment,
        "step3_witness": _stage3_witness,
        "step4_corridor_identity": _stage4_corridor_identity,
        "step5_slot_mapping": _stage5_slot_mapping,
        "step6_build_road": _stage6_build_road,
    }[stage_name]
    started = perf_counter()
    try:
        result = runner(data_root=data_root, patch_id=patch_id, run_id=run_id, out_root=out_root, params=merged_params)
    except Exception as exc:
        duration_ms = float((perf_counter() - started) * 1000.0)
        reason = pipeline._trim_reason(str(exc) or type(exc).__name__)
        pipeline.write_step_state(
            step_dir=pipeline.stage_dir(out_root, run_id, patch_id, stage_name),
            step=stage_name,
            ok=False,
            reason=reason,
            run_id=run_id,
            patch_id=patch_id,
            data_root=data_root,
            out_root=out_root,
            extra={"duration_ms": float(duration_ms)},
        )
        raise
    duration_ms = float((perf_counter() - started) * 1000.0)
    runtime = dict(result.get("runtime") or {})
    pipeline.write_step_state(
        step_dir=pipeline.stage_dir(out_root, run_id, patch_id, stage_name),
        step=stage_name,
        ok=True,
        reason=str(result.get("reason", "ok")),
        run_id=run_id,
        patch_id=patch_id,
        data_root=data_root,
        out_root=out_root,
        extra={"duration_ms": float(duration_ms), "runtime": runtime},
    )
    return {
        "stage": stage_name,
        "status": "ok",
        "reason": str(result.get("reason", "ok")),
        "duration_ms": float(duration_ms),
        "runtime": runtime,
    }


def run_full_pipeline(
    *,
    data_root: Path | str,
    patch_id: str,
    run_id: str,
    out_root: Path | str,
    force: bool = False,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    pipeline = _pipeline_module()
    merged_params = pipeline._merge_params(params)
    started = perf_counter()
    out: list[dict[str, Any]] = []
    for stage in pipeline.STAGES:
        out.append(
            run_stage(
                stage=stage,
                data_root=data_root,
                patch_id=patch_id,
                run_id=run_id,
                out_root=out_root,
                force=force,
                params=merged_params,
            )
        )
    total_runtime_ms = float((perf_counter() - started) * 1000.0)
    breakdown = {
        "patch_id": str(patch_id),
        "run_id": str(run_id),
        "stages": [
            {
                "stage": str(item.get("stage", "")),
                "status": str(item.get("status", "")),
                "duration_ms": float(item.get("duration_ms", 0.0) or 0.0),
                "runtime": dict(item.get("runtime") or {}),
            }
            for item in out
        ],
        "total_runtime_ms": float(total_runtime_ms),
    }
    pipeline.write_json(pipeline.patch_root(out_root, run_id, patch_id) / "runtime_breakdown.json", breakdown)
    return out


__all__ = ["run_full_pipeline", "run_stage"]
