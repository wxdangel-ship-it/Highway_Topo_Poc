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


def _patch_rows(run_dir: Path, patch_id: str) -> list[dict[str, Any]]:
    patch_dir = run_dir / "patches" / patch_id
    step3_prod = _read_json(patch_dir / "step3" / "step3_production_geometry_review.json")
    step3_same_pair = _read_json(patch_dir / "step3" / "step3_same_pair_deconflict_review.json")
    step4_review = _read_json(patch_dir / "step4" / "step4_corridor_identity_review.json")
    step5_inputs = _read_json(patch_dir / "step5" / "step5_geometry_input_sources.json")
    step4_artifact = _read_json(patch_dir / "step4" / "corridor_identity.json")
    metrics = _read_json(patch_dir / "metrics.json")

    registry_rows = list(step4_artifact.get("full_legal_arc_registry", []))
    registry_by_pair = {str(item.get("pair", "")): dict(item) for item in registry_rows if str(item.get("pair", ""))}
    prod_by_pair = {str(item.get("pair", "")): dict(item) for item in step3_prod.get("rows", []) if str(item.get("pair", ""))}
    same_pair_by_pair = {str(item.get("pair", "")): dict(item) for item in step3_same_pair.get("rows", []) if str(item.get("pair", ""))}
    step4_by_pair = {str(item.get("pair", "")): dict(item) for item in step4_review.get("rows", []) if str(item.get("pair", ""))}
    step5_by_pair = {str(item.get("pair", "")): dict(item) for item in step5_inputs.get("rows", []) if str(item.get("pair", ""))}
    metrics_by_pair = {
        f"{int(item.get('src_nodeid', 0))}:{int(item.get('dst_nodeid', 0))}": dict(item)
        for item in metrics.get("segments", [])
        if item.get("src_nodeid") is not None and item.get("dst_nodeid") is not None
    }

    pairs = sorted(
        {
            *registry_by_pair.keys(),
            *prod_by_pair.keys(),
            *same_pair_by_pair.keys(),
            *step4_by_pair.keys(),
            *step5_by_pair.keys(),
            *metrics_by_pair.keys(),
        }
    )
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        registry = dict(registry_by_pair.get(pair, {}))
        prod = dict(prod_by_pair.get(pair, {}))
        same_pair = dict(same_pair_by_pair.get(pair, {}))
        corridor = dict(step4_by_pair.get(pair, {}))
        step5 = dict(step5_by_pair.get(pair, {}))
        metric = dict(metrics_by_pair.get(pair, {}))
        rows.append(
            {
                "patch_id": str(patch_id),
                "pair": str(pair),
                "topology_arc_id": str(
                    prod.get("topology_arc_id")
                    or same_pair.get("topology_arc_id")
                    or registry.get("topology_arc_id")
                    or step5.get("topology_arc_id")
                    or ""
                ),
                "step2_preliminary_geometry_source": str(
                    prod.get("preliminary_geometry_source")
                    or registry.get("preliminary_geometry_source")
                    or ""
                ),
                "step2_preliminary_segment_id": str(
                    prod.get("preliminary_segment_id")
                    or registry.get("preliminary_segment_id")
                    or ""
                ),
                "step3_production_geometry_source": str(
                    prod.get("production_geometry_source_type")
                    or registry.get("production_geometry_source_type")
                    or ""
                ),
                "step3_production_segment_id": str(
                    prod.get("production_segment_id")
                    or registry.get("working_segment_id")
                    or ""
                ),
                "support_mode": str(registry.get("traj_support_type", "")),
                "support_source_type": str(
                    prod.get("production_support_source_type")
                    or registry.get("production_support_source_type")
                    or registry.get("support_interval_reference_source")
                    or ""
                ),
                "step3_production_support_binding_ok": bool(
                    prod.get("production_support_binding_ok", True)
                ),
                "step3_production_support_binding_reason": str(
                    prod.get("production_support_binding_reason")
                    or registry.get("production_support_binding_reason")
                    or ""
                ),
                "step3_production_support_geometry_mode": str(
                    prod.get("production_support_geometry_mode")
                    or registry.get("production_support_geometry_mode")
                    or ""
                ),
                "same_pair_explainability": {
                    "same_pair_support_deconflict_reason": str(
                        same_pair.get("same_pair_support_deconflict_reason")
                        or prod.get("same_pair_support_deconflict_reason")
                        or registry.get("same_pair_support_deconflict_reason")
                        or ""
                    ),
                    "multi_arc_structure_type": str(
                        same_pair.get("multi_arc_structure_type")
                        or registry.get("multi_arc_structure_type")
                        or ""
                    ),
                    "multi_arc_evidence_mode": str(
                        same_pair.get("multi_arc_evidence_mode")
                        or registry.get("multi_arc_evidence_mode")
                        or ""
                    ),
                    "production_multi_arc_allowed": bool(
                        same_pair.get("production_multi_arc_allowed")
                        or registry.get("production_multi_arc_allowed", False)
                    ),
                    "same_pair_arc_finalize_allowed": bool(
                        same_pair.get("same_pair_arc_finalize_allowed")
                        or registry.get("same_pair_arc_finalize_allowed", False)
                    ),
                    "binding_basis": dict(same_pair.get("binding_basis") or {}),
                },
                "alias_explainability": {
                    "raw_pair": str(registry.get("raw_pair", "")),
                    "canonical_pair": str(registry.get("canonical_pair", "")),
                    "src_alias_applied": bool(registry.get("src_alias_applied", False)),
                    "dst_alias_applied": bool(registry.get("dst_alias_applied", False)),
                    "raw_src_nodeid": registry.get("raw_src_nodeid"),
                    "raw_dst_nodeid": registry.get("raw_dst_nodeid"),
                    "canonical_src_xsec_id": registry.get("canonical_src_xsec_id"),
                    "canonical_dst_xsec_id": registry.get("canonical_dst_xsec_id"),
                },
                "corridor_identity": str(corridor.get("corridor_identity_state", "")),
                "corridor_reason": str(corridor.get("corridor_reason", "")),
                "final_built_state": bool(step5.get("built_final_road", False)),
                "final_reason": str(step5.get("final_reason") or metric.get("unresolved_reason") or ""),
                "final_road_source_family": str(step5.get("shape_ref_source_family", "")),
                "shape_ref_mode": str(step5.get("shape_ref_mode", "")),
                "production_geometry_fallback_reason": str(
                    prod.get("production_geometry_fallback_reason")
                    or registry.get("production_geometry_fallback_reason")
                    or ""
                ),
            }
        )
    return rows


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t05_extract_audit_fix_round1")
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
