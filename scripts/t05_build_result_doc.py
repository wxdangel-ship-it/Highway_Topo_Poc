from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _format_json_inline(value: object) -> str:
    if value in (None, "", [], {}):
        return ""
    return json.dumps(value, ensure_ascii=False)


def _format_metric(metric: dict | None) -> str:
    if not isinstance(metric, dict):
        return ""
    parts = []
    corridor_state = str(metric.get("corridor_state", "")).strip()
    road_failure_class = str(metric.get("road_failure_class", "")).strip()
    shape_ref_mode = str(metric.get("shape_ref_mode", "")).strip()
    road_ratio = metric.get("road_ratio")
    road_cross_divstrip = metric.get("road_cross_divstrip")
    no_geometry_reason = str(metric.get("no_geometry_reason", "")).strip()
    if corridor_state:
        parts.append(f"corridor={corridor_state}")
    if road_failure_class:
        parts.append(f"road={road_failure_class}")
    if shape_ref_mode:
        parts.append(f"shape={shape_ref_mode}")
    if road_ratio is not None:
        parts.append(f"ratio={road_ratio}")
    if road_cross_divstrip is not None:
        parts.append(f"cross_divstrip={road_cross_divstrip}")
    if no_geometry_reason:
        parts.append(f"no_geometry={no_geometry_reason}")
    return ", ".join(parts)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t05_build_result_doc")
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--complex-patch-id", default="5417632623039346")
    parser.add_argument(
        "--simple-patch-id",
        dest="simple_patch_ids",
        action="append",
        default=[],
        help="Repeatable. Defaults to 5417632690143326 and 5417632690143239 when omitted.",
    )
    parser.add_argument(
        "--output",
        help="Markdown output path. Defaults to <out-root>/<run-id>/t05_result_summary.md",
    )
    return parser


def _pair_check_rows(pair_check_dir: Path) -> list[dict]:
    rows = []
    if not pair_check_dir.exists():
        return rows
    for path in sorted(pair_check_dir.glob("*.json")):
        payload = _read_json(path)
        pair = payload.get("pair", {})
        excluded = payload.get("excluded_candidates", [])
        metric = payload.get("metric")
        last_excluded = excluded[-1] if excluded else {}
        rows.append(
            {
                "path": path,
                "pair_id": str(pair.get("pair_id", "")),
                "selected_segment_count": int(payload.get("selected_segment_count", 0)),
                "selected_segments": list(payload.get("selected_segments", [])),
                "metric": metric if isinstance(metric, dict) else None,
                "last_stage": str(last_excluded.get("stage", "")),
                "last_reason": str(last_excluded.get("reason", "")),
                "support_traj_count": int(payload.get("support_traj_count", 0)),
                "support_trajs": list(payload.get("support_trajs", [])),
                "terminal_node_audit": payload.get("terminal_node_audit"),
                "segment_should_not_exist": payload.get("segment_should_not_exist"),
                "last_excluded": last_excluded,
            }
        )
    return rows


def _patch_summary(root: Path, patch_id: str) -> dict:
    patch_root = root / "patches" / str(patch_id)
    metrics_path = patch_root / "metrics.json"
    gate_path = patch_root / "gate.json"
    if not metrics_path.exists():
        return {
            "patch_id": str(patch_id),
            "exists": False,
        }
    metrics = _read_json(metrics_path)
    gate = _read_json(gate_path) if gate_path.exists() else {}
    return {
        "patch_id": str(patch_id),
        "exists": True,
        "segment_count": metrics.get("segment_count"),
        "road_count": metrics.get("road_count"),
        "overall_pass": gate.get("overall_pass"),
        "failure_classification_hist": metrics.get("failure_classification_hist", {}),
        "no_geometry_candidate_reason": metrics.get("no_geometry_candidate_reason"),
    }


def _render_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _render_pair_details(row: dict) -> list[str]:
    lines = [f"### {row['pair_id']}"]
    lines.append(f"- `selected_segment_count`: {row['selected_segment_count']}")
    selected_segments = row.get("selected_segments", [])
    if selected_segments:
        segment_ids = ", ".join(str(item.get("segment_id", "")) for item in selected_segments)
        lines.append(f"- `selected_segments`: {segment_ids}")
    if row.get("metric"):
        lines.append(f"- `metric`: {_format_metric(row['metric'])}")
    if row.get("last_stage") or row.get("last_reason"):
        lines.append(f"- `last_excluded`: `{row.get('last_stage','')}/{row.get('last_reason','')}`")
    last_excluded = row.get("last_excluded") or {}
    competing_pairs = _format_json_inline(last_excluded.get("competing_prior_pair_ids"))
    if competing_pairs:
        lines.append(f"- `competing_prior_pair_ids`: `{competing_pairs}`")
    competing_paths = _format_json_inline(last_excluded.get("competing_prior_trace_paths"))
    if competing_paths:
        lines.append(f"- `competing_prior_trace_paths`: `{competing_paths}`")
    prior_anchor_cost_m = last_excluded.get("prior_anchor_cost_m")
    if prior_anchor_cost_m is not None:
        lines.append(f"- `prior_anchor_cost_m`: `{prior_anchor_cost_m}`")
    prior_anchor_best_pair = _format_json_inline(last_excluded.get("prior_anchor_best_pair"))
    if prior_anchor_best_pair:
        lines.append(f"- `prior_anchor_best_pair`: `{prior_anchor_best_pair}`")
    terminal_node_audit = row.get("terminal_node_audit")
    if isinstance(terminal_node_audit, dict):
        lines.append(
            "- `terminal_node_audit`: "
            f"node={terminal_node_audit.get('nodeid')} "
            f"reverse_owner_status={terminal_node_audit.get('reverse_owner_status')} "
            f"reverse_owner_src_nodeid={terminal_node_audit.get('reverse_owner_src_nodeid')} "
            f"allowed_incoming={_format_json_inline(terminal_node_audit.get('allowed_incoming_src_nodeids', []))}"
        )
    segment_should_not_exist = row.get("segment_should_not_exist")
    if isinstance(segment_should_not_exist, dict):
        lines.append(
            "- `segment_should_not_exist`: "
            f"reason={segment_should_not_exist.get('reason')} "
            f"topology_sources={_format_json_inline(segment_should_not_exist.get('topology_sources', []))}"
        )
    if row.get("support_traj_count", 0) > 0:
        support_trajs = row.get("support_trajs", [])
        top1 = support_trajs[0] if support_trajs else {}
        lines.append(
            "- `support_traj_top1`: "
            f"traj_id={top1.get('traj_id')} "
            f"candidate_id={top1.get('candidate_id')} "
            f"support_length={top1.get('support_length')} "
            f"support_direction_ok={top1.get('support_direction_ok')} "
            f"support_inside_ratio={top1.get('support_inside_ratio')}"
        )
    lines.append("")
    return lines


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_root = Path(args.out_root) / str(args.run_id)
    complex_patch_id = str(args.complex_patch_id)
    simple_patch_ids = list(args.simple_patch_ids) or ["5417632690143326", "5417632690143239"]
    output_path = Path(args.output) if args.output else run_root / "t05_result_summary.md"

    complex_summary = _patch_summary(run_root, complex_patch_id)
    simple_summaries = [_patch_summary(run_root, patch_id) for patch_id in simple_patch_ids]
    pair_check_dir = run_root / "patches" / complex_patch_id / "debug" / "pair_checks"
    pair_rows = _pair_check_rows(pair_check_dir)

    lines: list[str] = []
    lines.append("# T05 Result Summary")
    lines.append("")
    lines.append(f"- `run_id`: `{args.run_id}`")
    lines.append(f"- `generated_at_utc`: `{datetime.now(timezone.utc).isoformat()}`")
    lines.append(f"- `complex_patch_id`: `{complex_patch_id}`")
    lines.append(f"- `pair_check_dir`: `{pair_check_dir}`")
    lines.append("")
    lines.append("## Complex Patch")
    lines.append("")
    lines.extend(
        _render_table(
            ["patch_id", "segment_count", "road_count", "overall_pass", "failure_classification_hist"],
            [
                [
                    complex_summary["patch_id"],
                    str(complex_summary.get("segment_count", "")),
                    str(complex_summary.get("road_count", "")),
                    str(complex_summary.get("overall_pass", "")),
                    _format_json_inline(complex_summary.get("failure_classification_hist", {})),
                ]
            ],
        )
    )
    lines.append("")
    lines.append("## Pair Summary")
    lines.append("")
    if pair_rows:
        lines.extend(
            _render_table(
                [
                    "pair",
                    "selected_segment_count",
                    "last_stage",
                    "last_reason",
                    "metric",
                    "support_traj_count",
                ],
                [
                    [
                        row["pair_id"],
                        str(row["selected_segment_count"]),
                        row["last_stage"],
                        row["last_reason"],
                        _format_metric(row["metric"]),
                        str(row["support_traj_count"]),
                    ]
                    for row in pair_rows
                ],
            )
        )
        lines.append("")
        lines.append("## Pair Details")
        lines.append("")
        for row in pair_rows:
            lines.extend(_render_pair_details(row))
    else:
        lines.append("No pair check files were found.")
        lines.append("")
    lines.append("## Simple Patches")
    lines.append("")
    lines.extend(
        _render_table(
            ["patch_id", "segment_count", "road_count", "overall_pass", "failure_classification_hist"],
            [
                [
                    item["patch_id"],
                    str(item.get("segment_count", "")),
                    str(item.get("road_count", "")),
                    str(item.get("overall_pass", "")),
                    _format_json_inline(item.get("failure_classification_hist", {})),
                ]
                for item in simple_summaries
            ],
        )
    )
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(str(output_path))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
