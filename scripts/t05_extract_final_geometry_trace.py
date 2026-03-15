from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_pairs(text: str) -> list[str]:
    return [item.strip() for item in str(text or "").split(",") if item.strip()]


def _classify_layer(row: dict[str, Any]) -> str:
    refine_applied = bool(row.get("refine_applied_bool", False))
    refine_rejected_reason = str(row.get("refine_rejected_reason", "") or "")
    final_export_source = str(row.get("final_export_source", "") or "")
    step5_shape_ref_source = str(row.get("step5_shape_ref_source", "") or "")
    step3_production_source = str(row.get("step3_production_source", "") or "")
    anchor_adjusted = bool(row.get("anchor_adjusted_bool", False))
    transition_methods = " ".join(
        [
            str(row.get("entry_transition_method", "")),
            str(row.get("exit_transition_method", "")),
        ]
    )
    if refine_applied and not final_export_source.startswith("geometry_refine::"):
        return "Layer C"
    if (not refine_applied) and refine_rejected_reason and refine_rejected_reason != "kept_original_geometry":
        return "Layer C"
    if step5_shape_ref_source and step3_production_source and step5_shape_ref_source != step3_production_source:
        return "Layer B"
    if anchor_adjusted or "transition_aware" in transition_methods:
        return "Layer A"
    return "Layer A"


def _patch_rows(run_dir: Path, patch_id: str) -> list[dict[str, Any]]:
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
        current = dict(item)
        current["patch_id"] = str(patch_id)
        current["layer_classification"] = _classify_layer(current)
        current.update(
            {
                "step5_shape_ref_source_family": str(
                    input_by_segment.get(str(item.get("segment_id", "")), {}).get("shape_ref_source_family", "")
                ),
                "step5_support_candidate_policy": str(
                    input_by_segment.get(str(item.get("segment_id", "")), {}).get("step5_support_candidate_policy", "")
                ),
                "step5_rcsdroad_fallback_applied": bool(
                    input_by_segment.get(str(item.get("segment_id", "")), {}).get("step5_rcsdroad_fallback_applied", False)
                ),
            }
        )
        rows.append(current)
    return rows


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t05_extract_final_geometry_trace")
    parser.add_argument("--run_dir", required=True, help="Run directory like outputs/_work/t05_topology_between_rc_v2/<RUN_ID>")
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
        rows.extend(_patch_rows(run_dir, patch_dir.name))
    filtered = [row for row in rows if str(row.get("pair", "")) in target_pairs]
    payload = {
        "run_dir": str(run_dir),
        "requested_pairs": sorted(target_pairs),
        "row_count": int(len(filtered)),
        "rows": filtered,
    }
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
