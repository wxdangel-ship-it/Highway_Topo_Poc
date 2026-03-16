from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SIMPLE_PATCH_IDS = {"5417632690143239", "5417632690143326"}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_pairs(text: str) -> list[str]:
    return [item.strip() for item in str(text or "").split(",") if item.strip()]


def _global_fit_payload(patch_dir: Path) -> dict[str, Any]:
    payload = _read_json(patch_dir / "step5_global_fit_v2_trace.json")
    if payload:
        return payload
    return _read_json(patch_dir / "step5_global_fit_trace.json")


def _merge_patch_rows(patch_dir: Path) -> list[dict[str, Any]]:
    global_fit_payload = _global_fit_payload(patch_dir)
    final_trace_payload = _read_json(patch_dir / "step5_final_geometry_trace.json")
    final_by_pair = {
        str(item.get("pair", "")): dict(item)
        for item in final_trace_payload.get("rows", [])
        if str(item.get("pair", ""))
    }
    rows: list[dict[str, Any]] = []
    for item in global_fit_payload.get("rows", []):
        pair = str(item.get("pair", ""))
        final_row = dict(final_by_pair.get(pair, {}))
        endpoint_tangent_trace = dict(item.get("endpoint_tangent_trace") or {})
        rows.append(
            {
                "patch_id": str(patch_dir.name),
                "segment_id": str(item.get("segment_id", "")),
                "pair": pair,
                "arc_id": str(item.get("arc_id", "")),
                "trajectory_spine_source": str(item.get("trajectory_spine_source", "")),
                "trajectory_spine_quality": float(item.get("trajectory_spine_quality", 0.0) or 0.0),
                "trajectory_spine_support_count": int(item.get("trajectory_spine_support_count", 0) or 0),
                "original_spine_coords": list(item.get("original_spine_coords") or []),
                "corrected_spine_coords": list(item.get("corrected_spine_coords") or []),
                "center_corrected_spine_quality": float(item.get("center_corrected_spine_quality", 0.0) or 0.0),
                "centerline_correction_enabled_bool": bool(item.get("centerline_correction_enabled_bool", False)),
                "centerline_correction_summary": dict(item.get("centerline_correction_summary") or {}),
                "lane_boundary_hint_usage": dict(item.get("lane_boundary_hint_usage") or {}),
                "src_local_tangent": dict(endpoint_tangent_trace.get("src") or {}),
                "dst_local_tangent": dict(endpoint_tangent_trace.get("dst") or {}),
                "endpoint_tangent_continuity_enabled_bool": bool(item.get("endpoint_tangent_continuity_enabled_bool", False)),
                "global_fitting_mode": str(item.get("fitting_mode", "")),
                "global_fitting_success_bool": bool(item.get("fitting_success_bool", False)),
                "global_fit_used_bool": bool(item.get("global_fit_used_bool", False)),
                "fitted_line_is_final_export": bool(final_row.get("global_fit_used_bool", False)),
                "final_export_source": str(final_row.get("final_export_source", item.get("final_export_source", ""))),
                "fit_metrics": dict(item.get("fit_metrics") or {}),
                "fallback_reason": str(item.get("fallback_reason", "") or final_row.get("global_fit_fallback_reason", "")),
                "quality_gate_reason": str(item.get("quality_gate_reason", "") or final_row.get("global_fit_quality_gate_reason", "")),
                "built_state": bool(item.get("built_final_road", final_row.get("built_final_road", False))),
                "built_final_road": bool(item.get("built_final_road", final_row.get("built_final_road", False))),
            }
        )
    return rows


def _simple_patch_summary(run_dir: Path) -> dict[str, Any]:
    per_patch: dict[str, dict[str, Any]] = {}
    for patch_id in sorted(SIMPLE_PATCH_IDS):
        patch_dir = run_dir / "patches" / patch_id
        trace_payload = _read_json(patch_dir / "step5_final_geometry_trace.json")
        global_fit_payload = _global_fit_payload(patch_dir)
        rows = list(trace_payload.get("rows", []))
        global_rows = list(global_fit_payload.get("rows", []))
        per_patch[patch_id] = {
            "row_count": int(len(rows)),
            "built_count": int(sum(1 for item in rows if bool(item.get("built_final_road", False)))),
            "global_fit_used_count": int(sum(1 for item in rows if bool(item.get("global_fit_used_bool", False)))),
            "global_fit_success_count": int(sum(1 for item in global_rows if bool(item.get("fitting_success_bool", False)))),
            "centerline_correction_enabled_count": int(
                sum(1 for item in global_rows if bool(item.get("centerline_correction_enabled_bool", False)))
            ),
            "endpoint_tangent_enabled_count": int(
                sum(1 for item in global_rows if bool(item.get("endpoint_tangent_continuity_enabled_bool", False)))
            ),
            "refine_applied_count": int(sum(1 for item in rows if bool(item.get("refine_applied_bool", False)))),
        }
    return per_patch


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t05_extract_global_fit_v2_trace")
    parser.add_argument("--run_dir", required=True, help="Run directory like outputs/_work/<RUN_ID>")
    parser.add_argument("--pairs", required=True, help="Comma-separated pair ids: src:dst,src:dst")
    parser.add_argument("--output", default="", help="Optional JSON output path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_dir = Path(args.run_dir)
    target_pairs = set(_parse_pairs(args.pairs))
    rows: list[dict[str, Any]] = []
    for patch_dir in sorted((run_dir / "patches").glob("*")):
        if not patch_dir.is_dir():
            continue
        rows.extend(_merge_patch_rows(patch_dir))
    filtered = [row for row in rows if str(row.get("pair", "")) in target_pairs]
    payload = {
        "run_dir": str(run_dir),
        "requested_pairs": sorted(target_pairs),
        "row_count": int(len(filtered)),
        "rows": filtered,
        "simple_patch_summary": _simple_patch_summary(run_dir),
    }
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
