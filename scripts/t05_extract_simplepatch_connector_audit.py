from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_PATCH_IDS = ("5417632690143239", "5417632690143326")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_csv(text: str) -> list[str]:
    return [item.strip() for item in str(text or "").split(",") if item.strip()]


def _row_needs_followup(row: dict[str, Any]) -> bool:
    if not bool(row.get("built_final_road", False)):
        return True
    final_export_source = str(row.get("final_export_source", "") or "")
    selected_candidate_source = str(row.get("step5_selected_candidate_source", "") or "")
    entry_method = str(row.get("entry_transition_method", "") or "")
    exit_method = str(row.get("exit_transition_method", "") or "")
    refine_applied = bool(row.get("refine_applied_bool", False))
    return (
        final_export_source == "production_working_segment_slot_anchored"
        and selected_candidate_source == "production_working_segment_slot_anchored"
        and entry_method == "anchor_along_base_line"
        and exit_method == "anchor_along_base_line"
        and not refine_applied
    )


def _load_patch_rows(run_dir: Path, patch_id: str) -> list[dict[str, Any]]:
    patch_dir = run_dir / "patches" / patch_id
    trace_payload = _read_json(patch_dir / "step5_final_geometry_trace.json")
    input_payload = _read_json(patch_dir / "step5" / "step5_geometry_input_sources.json")
    input_by_segment = {
        str(item.get("segment_id", "")): dict(item)
        for item in input_payload.get("rows", [])
        if str(item.get("segment_id", ""))
    }
    rows: list[dict[str, Any]] = []
    for item in trace_payload.get("rows", []):
        segment_id = str(item.get("segment_id", ""))
        input_row = input_by_segment.get(segment_id, {})
        current = {
            "patch_id": patch_id,
            "pair": item.get("pair"),
            "segment_id": segment_id,
            "topology_arc_id": item.get("topology_arc_id"),
            "step3_production_source": item.get("step3_production_source"),
            "step5_shape_ref_source": item.get("step5_shape_ref_source"),
            "step5_selected_candidate_source": item.get("step5_selected_candidate_source"),
            "final_export_source": item.get("final_export_source"),
            "entry_transition_method": item.get("entry_transition_method"),
            "exit_transition_method": item.get("exit_transition_method"),
            "entry_transition_source": item.get("entry_transition_source"),
            "exit_transition_source": item.get("exit_transition_source"),
            "core_segment_source": item.get("core_segment_source"),
            "core_authoritative_source": item.get("core_authoritative_source"),
            "step3_endpoint_anchor_source": item.get("step3_endpoint_anchor_source"),
            "step5_used_anchor_source": item.get("step5_used_anchor_source"),
            "anchor_adjusted_bool": item.get("anchor_adjusted_bool"),
            "anchor_adjust_reason": item.get("anchor_adjust_reason"),
            "refine_candidate_source": item.get("refine_candidate_source"),
            "refine_applied_bool": item.get("refine_applied_bool"),
            "refine_rejected_reason": item.get("refine_rejected_reason"),
            "refine_selected_candidate_mode": item.get("refine_selected_candidate_mode"),
            "final_override_reason": item.get("final_override_reason"),
            "final_clip_reason": item.get("final_clip_reason"),
            "built_final_road": item.get("built_final_road"),
            "final_reason": item.get("final_reason"),
            "shape_ref_source_family": input_row.get("shape_ref_source_family"),
            "step5_support_candidate_policy": input_row.get("step5_support_candidate_policy"),
            "step5_rcsdroad_fallback_applied": input_row.get("step5_rcsdroad_fallback_applied"),
            "trace_files": {
                "step5_final_geometry_trace": str(patch_dir / "step5_final_geometry_trace.json"),
                "step5_transition_segments": str(patch_dir / "step5_transition_segments.geojson"),
                "step5_endpoint_anchor_trace": str(patch_dir / "step5_endpoint_anchor_trace.geojson"),
                "final_geometry_components": str(patch_dir / "final_geometry_components.geojson"),
            },
        }
        current["needs_connector_followup"] = _row_needs_followup(current)
        current["uses_transition_aware"] = any(
            "transition_aware" in str(current.get(key, "") or "")
            for key in (
                "step5_selected_candidate_source",
                "final_export_source",
                "entry_transition_method",
                "exit_transition_method",
            )
        )
        rows.append(current)
    return rows


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t05_extract_simplepatch_connector_audit")
    parser.add_argument("--run_dir", required=True, help="Run directory like outputs/_work/t05_topology_between_rc_v2/<RUN_ID>")
    parser.add_argument(
        "--patch_ids",
        default=",".join(DEFAULT_PATCH_IDS),
        help="Comma-separated patch ids. Defaults to the two simple patch ids.",
    )
    parser.add_argument("--pairs", default="", help="Optional comma-separated pair filter.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_dir = Path(args.run_dir)
    patch_ids = _parse_csv(args.patch_ids)
    pair_filter = set(_parse_csv(args.pairs))

    rows: list[dict[str, Any]] = []
    for patch_id in patch_ids:
        rows.extend(_load_patch_rows(run_dir, patch_id))
    if pair_filter:
        rows = [row for row in rows if str(row.get("pair", "")) in pair_filter]
    rows.sort(key=lambda row: (str(row.get("patch_id", "")), str(row.get("pair", "")), str(row.get("segment_id", ""))))

    flagged_rows = [row for row in rows if bool(row.get("needs_connector_followup", False))]
    payload = {
        "run_dir": str(run_dir),
        "requested_patch_ids": patch_ids,
        "requested_pairs": sorted(pair_filter),
        "row_count": len(rows),
        "flagged_count": len(flagged_rows),
        "summary": {
            "built_count": sum(1 for row in rows if bool(row.get("built_final_road", False))),
            "transition_aware_count": sum(1 for row in rows if bool(row.get("uses_transition_aware", False))),
            "refine_applied_count": sum(1 for row in rows if bool(row.get("refine_applied_bool", False))),
            "anchor_adjusted_count": sum(1 for row in rows if bool(row.get("anchor_adjusted_bool", False))),
        },
        "flagged_rows": flagged_rows,
        "rows": rows,
    }

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
