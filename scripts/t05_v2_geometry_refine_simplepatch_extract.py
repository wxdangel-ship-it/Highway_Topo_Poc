from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from highway_topo_poc.modules.t05_topology_between_rc_v2.audit_acceptance import (  # noqa: E402
    build_arc_legality_audit,
    build_legal_arc_coverage,
    build_runtime_breakdown,
    build_simple_patch_acceptance,
    build_simple_patch_regression,
    evaluate_patch_acceptance,
)
from highway_topo_poc.modules.t05_topology_between_rc_v2.io import write_features_geojson, write_json  # noqa: E402


_SIMPLE_PATCH_IDS = ["5417632690143239", "5417632690143326"]
_GEOM_FILES = {
    "traj_guided_core_line.geojson": "traj_guided_core_line.geojson",
    "trusted_core_skeleton.geojson": "trusted_core_skeleton.geojson",
    "xsec_anchor_points.geojson": "xsec_anchor_points.geojson",
    "entry_exit_segments.geojson": "entry_exit_segments.geojson",
    "safe_envelope_polygon.geojson": "safe_envelope_polygon.geojson",
    "refined_final_road.geojson": "refined_final_road.geojson",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_feature_file(run_root: Path, patch_ids: list[str], filename: str) -> list[tuple[Any, dict[str, Any]]]:
    features: list[tuple[Any, dict[str, Any]]] = []
    for patch_id in patch_ids:
        payload = _read_json(run_root / "patches" / patch_id / filename)
        for feature in payload.get("features", []):
            geometry = feature.get("geometry")
            if not geometry:
                continue
            props = dict(feature.get("properties") or {})
            props.setdefault("patch_id", str(patch_id))
            from shapely.geometry import shape  # local import keeps script light

            features.append((shape(geometry), props))
    return features


def _merge_geometry_refine_review(run_root: Path, patch_ids: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    summary_counter = Counter()
    skip_reason_hist = Counter()
    for patch_id in patch_ids:
        payload = _read_json(run_root / "patches" / patch_id / "geometry_refine_review.json")
        for row in payload.get("rows", []):
            item = dict(row)
            item.setdefault("patch_id", str(patch_id))
            rows.append(item)
        summary = dict(payload.get("summary") or {})
        for key in (
            "road_count",
            "reviewed_count",
            "eligible_count",
            "applied_count",
            "smoothed_count",
            "lane_boundary_used_count",
            "traj_guided_used_count",
            "support_trend_used_count",
            "safe_envelope_applied_count",
        ):
            summary_counter[key] += int(summary.get(key, 0) or 0)
        skip_reason_hist.update(dict(summary.get("skip_reason_hist") or {}))
    return {
        "evaluated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": rows,
        "summary": {
            **{key: int(value) for key, value in summary_counter.items()},
            "patch_count": int(len(patch_ids)),
            "skip_reason_hist": dict(skip_reason_hist),
        },
    }


def _render_summary(
    *,
    simple_patch_acceptance: dict[str, Any],
    geometry_refine_review: dict[str, Any],
    arc_legality_audit: dict[str, Any],
    runtime_breakdown: dict[str, Any],
) -> str:
    audit = dict(arc_legality_audit.get("summary") or arc_legality_audit)
    geom = dict(geometry_refine_review.get("summary") or {})
    lines = [
        "# T05 v2 Geometry Refine Simple Patch Summary",
        "",
        f"- generated_at_utc: `{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}`",
        f"- simple_patch_all_pass: `{str(bool(simple_patch_acceptance.get('all_simple_patches_pass', False))).lower()}`",
        f"- reviewed_count: `{int(geom.get('reviewed_count', 0))}`",
        f"- applied_count: `{int(geom.get('applied_count', 0))}`",
        f"- smoothed_count: `{int(geom.get('smoothed_count', 0))}`",
        f"- traj_guided_used_count: `{int(geom.get('traj_guided_used_count', 0))}`",
        f"- lane_boundary_used_count: `{int(geom.get('lane_boundary_used_count', 0))}`",
        f"- safe_envelope_applied_count: `{int(geom.get('safe_envelope_applied_count', 0))}`",
        f"- bad_built_arc_count: `{int(audit.get('bad_built_arc_count', 0))}`",
        f"- built_all_direct_unique: `{str(bool(audit.get('built_all_direct_unique', False))).lower()}`",
        f"- audit_summary_inconsistent: `{str(bool(audit.get('audit_summary_inconsistent', False))).lower()}`",
        f"- total_runtime_ms: `{float(runtime_breakdown.get('total_runtime_ms', 0.0) or 0.0):.3f}`",
        "",
        "## Simple Patch Acceptance",
    ]
    for patch in simple_patch_acceptance.get("patches", []):
        lines.append(
            f"- patch `{patch.get('patch_id')}`: pass=`{str(bool(patch.get('acceptance_pass', False))).lower()}` "
            f"built=`{patch.get('legal_arc_built')}` / total=`{patch.get('legal_arc_total')}` rate=`{patch.get('legal_arc_build_rate')}`"
        )
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t05_v2_geometry_refine_simplepatch_extract")
    parser.add_argument("--run-root", required=True, help="Directory containing patches/<patch_id>/...")
    parser.add_argument("--output-root", required=True, help="Bundle directory for merged simple patch outputs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_root = Path(args.run_root)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    acceptance_results = [evaluate_patch_acceptance(run_root, patch_id) for patch_id in _SIMPLE_PATCH_IDS]
    legal_arc_coverage = build_legal_arc_coverage(run_root, _SIMPLE_PATCH_IDS)
    simple_patch_acceptance = build_simple_patch_acceptance(acceptance_results, legal_arc_coverage)
    simple_patch_regression = build_simple_patch_regression(simple_patch_acceptance)
    arc_legality_audit = build_arc_legality_audit(run_root, _SIMPLE_PATCH_IDS)
    runtime_breakdown = build_runtime_breakdown(run_root, _SIMPLE_PATCH_IDS)
    geometry_refine_review = _merge_geometry_refine_review(run_root, _SIMPLE_PATCH_IDS)

    for output_name, patch_name in _GEOM_FILES.items():
        write_features_geojson(output_root / output_name, _merge_feature_file(run_root, _SIMPLE_PATCH_IDS, patch_name))

    write_json(output_root / "geometry_refine_review.json", geometry_refine_review)
    write_json(output_root / "simple_patch_acceptance.json", simple_patch_acceptance)
    write_json(output_root / "simple_patch_regression.json", simple_patch_regression)
    write_json(output_root / "runtime_breakdown.json", runtime_breakdown)
    write_json(output_root / "arc_legality_audit.json", arc_legality_audit)
    write_json(output_root / "legal_arc_coverage.json", legal_arc_coverage)
    write_json(
        output_root / "strong_constraint_status.json",
        {
            "simple_patch_acceptance_pass": bool(simple_patch_acceptance.get("all_simple_patches_pass", False)),
            "bad_built_arc_count": int((arc_legality_audit.get("summary") or arc_legality_audit).get("bad_built_arc_count", 0)),
            "built_all_direct_unique": bool((arc_legality_audit.get("summary") or arc_legality_audit).get("built_all_direct_unique", False)),
            "audit_summary_inconsistent": bool((arc_legality_audit.get("summary") or arc_legality_audit).get("audit_summary_inconsistent", False)),
        },
    )
    (output_root / "SUMMARY.md").write_text(
        _render_summary(
            simple_patch_acceptance=simple_patch_acceptance,
            geometry_refine_review=geometry_refine_review,
            arc_legality_audit=arc_legality_audit,
            runtime_breakdown=runtime_breakdown,
        ),
        encoding="utf-8",
    )

    geom_summary = dict(geometry_refine_review.get("summary") or {})
    audit_summary = dict(arc_legality_audit.get("summary") or arc_legality_audit)
    for patch in simple_patch_acceptance.get("patches", []):
        print(
            f"ACCEPT patch={patch.get('patch_id')} "
            f"pass={str(bool(patch.get('acceptance_pass', False))).lower()} "
            f"legal_arc_total={patch.get('legal_arc_total')} "
            f"built={patch.get('legal_arc_built')} "
            f"rate={patch.get('legal_arc_build_rate')}"
        )
    print(
        f"GEOM reviewed={geom_summary.get('reviewed_count')} "
        f"eligible={geom_summary.get('eligible_count')} "
        f"applied={geom_summary.get('applied_count')} "
        f"smoothed={geom_summary.get('smoothed_count')} "
        f"traj_guided_used={geom_summary.get('traj_guided_used_count')} "
        f"lane_boundary_used={geom_summary.get('lane_boundary_used_count')} "
        f"safe_envelope_applied={geom_summary.get('safe_envelope_applied_count')}"
    )
    for row in geometry_refine_review.get("rows", []):
        print(
            f"GEOM_PAIR patch={row.get('patch_id')} "
            f"pair={row.get('pair')} "
            f"applied={str(bool(row.get('applied', False))).lower()} "
            f"smoothed={str(bool(row.get('smoothed', False))).lower()} "
            f"core={row.get('core_skeleton_source')} "
            f"entry={row.get('entry_anchor_source')} "
            f"exit={row.get('exit_anchor_source')} "
            f"traj_guided={str(bool(row.get('traj_guided_used', False))).lower()} "
            f"lane_boundary={str(bool(row.get('lane_boundary_used', False))).lower()} "
            f"before_len={row.get('before_length')} "
            f"after_len={row.get('after_length')} "
            f"before_drivezone={row.get('before_drivezone_overlap_ratio')} "
            f"after_drivezone={row.get('after_drivezone_overlap_ratio')}"
        )
    print(
        f"AUDIT bad_built_arc_count={audit_summary.get('bad_built_arc_count')} "
        f"built_all_direct_unique={str(bool(audit_summary.get('built_all_direct_unique', False))).lower()} "
        f"audit_summary_inconsistent={str(bool(audit_summary.get('audit_summary_inconsistent', False))).lower()} "
        f"synthetic_in_production={str(bool(audit_summary.get('synthetic_arc_in_production', False))).lower()}"
    )
    print(
        f"RUNTIME total_ms={runtime_breakdown.get('total_runtime_ms')} "
        f"patch_count={len(runtime_breakdown.get('patches', []))}"
    )
    print(f"OK output_root={output_root}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
