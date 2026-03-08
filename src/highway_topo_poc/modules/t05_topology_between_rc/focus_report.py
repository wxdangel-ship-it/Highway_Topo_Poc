from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


def _parse_pair_token(value: str) -> tuple[int, int]:
    text = str(value or "").strip()
    for sep in ("->", ":", ","):
        if sep not in text:
            continue
        lhs, rhs = text.split(sep, 1)
        return int(lhs.strip()), int(rhs.strip())
    raise argparse.ArgumentTypeError(f"invalid_pair={value}")


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="t05_focus_report")
    p.add_argument("--run_dir", required=True, help="Patch output directory: .../<run_id>/patches/<patch_id>")
    p.add_argument(
        "--pair",
        action="append",
        type=_parse_pair_token,
        default=[],
        help="Target pair. Repeatable. Format: SRC:DST or SRC->DST.",
    )
    return p.parse_args(list(argv) if argv is not None else None)


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _collect_pair_stage_map(run_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    payload = _safe_read_json(run_dir / "debug" / "pair_stage_status.json")
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for item in payload.get("pairs", []):
        if not isinstance(item, dict):
            continue
        src = item.get("src_nodeid")
        dst = item.get("dst_nodeid")
        if src is None or dst is None:
            continue
        out[(str(src), str(dst))] = dict(item)
    return out


def _collect_output_hits(run_dir: Path, name: str, pair: tuple[int, int]) -> list[dict[str, Any]]:
    payload = _safe_read_json(run_dir / name)
    hits: list[dict[str, Any]] = []
    for feat in payload.get("features", []):
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties")
        if not isinstance(props, dict):
            continue
        src = str(props.get("src_nodeid", props.get("src", "")))
        dst = str(props.get("dst_nodeid", props.get("dst", "")))
        if src != str(int(pair[0])) or dst != str(int(pair[1])):
            continue
        hits.append(
            {
                "road_id": props.get("road_id"),
                "hard_reasons": props.get("hard_reasons"),
                "soft_reasons": props.get("soft_reasons"),
                "same_pair_resolution_state": props.get("same_pair_resolution_state"),
            }
        )
    return hits


def _collect_gate_hits(run_dir: Path, pair: tuple[int, int]) -> list[dict[str, Any]]:
    payload = _safe_read_json(run_dir / "gate.json")
    hits: list[dict[str, Any]] = []
    for section in ("hard_breakpoints", "soft_breakpoints"):
        for item in payload.get(section, []):
            if not isinstance(item, dict):
                continue
            src = item.get("src_nodeid")
            dst = item.get("dst_nodeid")
            if src is None or dst is None:
                continue
            if str(src) != str(int(pair[0])) or str(dst) != str(int(pair[1])):
                continue
            hits.append(
                {
                    "severity": "hard" if section == "hard_breakpoints" else "soft",
                    "reason": item.get("reason"),
                    "road_id": item.get("road_id"),
                    "hint": item.get("hint"),
                }
            )
    return hits


def build_focus_report(*, run_dir: Path, pairs: list[tuple[int, int]]) -> str:
    summary_text = _safe_read_text(run_dir / "summary.txt")
    metrics_payload = _safe_read_json(run_dir / "metrics.json")
    pair_stage_map = _collect_pair_stage_map(run_dir)

    lines: list[str] = []
    lines.append(f"run_dir: {run_dir.as_posix()}")
    if summary_text:
        for prefix in ("run_id:", "git_sha:", "patch_id:", "overall_pass:"):
            for line in summary_text.splitlines():
                if line.startswith(prefix):
                    lines.append(line)
                    break
    lines.append("metrics_key:")
    for key in (
        "road_count",
        "road_candidate_count",
        "road_features_count",
        "same_pair_handled_pair_count",
        "same_pair_multi_road_output_count",
        "same_pair_partial_unresolved_pair_count",
        "no_geometry_candidate_count",
        "topology_fallback_support_count",
        "low_support_road_count",
        "traj_surface_cache_hit_count",
        "traj_surface_cache_miss_count",
        "t_build_surfaces_total",
        "focus_pair_filter_count",
        "focus_src_nodeid_count",
    ):
        if key in metrics_payload:
            lines.append(f"- {key}={json.dumps(metrics_payload.get(key), ensure_ascii=False)}")

    for src, dst in pairs:
        pair_key = (str(int(src)), str(int(dst)))
        stage = dict(pair_stage_map.get(pair_key, {}))
        lines.append("")
        lines.append(f"pair: {int(src)}->{int(dst)}")
        if stage:
            stage_view = {
                "topology_anchor_status": stage.get("topology_anchor_status"),
                "road_prior_shape_ref_available": stage.get("road_prior_shape_ref_available"),
                "support_found": stage.get("support_found"),
                "support_mode": stage.get("support_mode"),
                "support_fallback_attempted": stage.get("support_fallback_attempted"),
                "support_fallback_failure_stage": stage.get("support_fallback_failure_stage"),
                "support_fallback_src_contact_found": stage.get("support_fallback_src_contact_found"),
                "support_fallback_dst_contact_found": stage.get("support_fallback_dst_contact_found"),
                "support_fallback_src_gap_m": stage.get("support_fallback_src_gap_m"),
                "support_fallback_dst_gap_m": stage.get("support_fallback_dst_gap_m"),
                "support_fallback_reach_xsec_m": stage.get("support_fallback_reach_xsec_m"),
                "support_fallback_src_entry_xsec_shift_m": stage.get("support_fallback_src_entry_xsec_shift_m"),
                "support_fallback_dst_entry_xsec_shift_m": stage.get("support_fallback_dst_entry_xsec_shift_m"),
                "support_fallback_src_reach_allow_m": stage.get("support_fallback_src_reach_allow_m"),
                "support_fallback_dst_reach_allow_m": stage.get("support_fallback_dst_reach_allow_m"),
                "support_fallback_inside_ratio": stage.get("support_fallback_inside_ratio"),
                "support_fallback_inside_ratio_min": stage.get("support_fallback_inside_ratio_min"),
                "candidate_count": stage.get("candidate_count"),
                "viable_candidate_count": stage.get("viable_candidate_count"),
                "selected_output_count": stage.get("selected_output_count"),
                "selected_or_rejected_stage": stage.get("selected_or_rejected_stage"),
            }
            lines.append(f"pair_stage: {json.dumps(stage_view, ensure_ascii=False)}")
        else:
            lines.append("pair_stage: {}")

        for name in ("Road.geojson", "RCSDRoad.geojson"):
            hits = _collect_output_hits(run_dir, name, (int(src), int(dst)))
            lines.append(f"{name}: hits={len(hits)} {json.dumps(hits[:10], ensure_ascii=False)}")

        gate_hits = _collect_gate_hits(run_dir, (int(src), int(dst)))
        lines.append(f"gate_hits: {json.dumps(gate_hits[:10], ensure_ascii=False)}")

    return "\n".join(lines) + "\n"


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    run_dir = Path(args.run_dir).resolve()
    pairs = [(int(src), int(dst)) for src, dst in list(args.pair or [])]
    print(build_focus_report(run_dir=run_dir, pairs=pairs), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
