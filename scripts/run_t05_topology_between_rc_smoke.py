from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from highway_topo_poc.modules.t05_topology_between_rc.pipeline import run_patch
from highway_topo_poc.modules.t05_topology_between_rc.io import (
    discover_patch_dirs,
    make_run_id,
    probe_patch,
    resolve_repo_root,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="run_t05_topology_between_rc_smoke")
    p.add_argument("--data_root", default="data/synth_local")
    p.add_argument("--alt_data_root", default="data/synth")
    p.add_argument("--out_root", default="outputs/_work/t05_topology_between_rc")
    p.add_argument("--max_patches", type=int, default=3)
    p.add_argument("--min_patches", type=int, default=2)
    p.add_argument("--run_id", default="auto")
    p.add_argument("--xsec_min_points", type=int, default=80)
    p.add_argument("--min_support_traj", type=int, default=1)
    return p.parse_args()


def _score_probe(info: Any) -> tuple[int, int, int]:
    # 优先有 intersection feature，再看轨迹点数量。
    return (
        int(info.intersection_feature_count > 0),
        int(info.laneboundary_feature_count > 0),
        int(info.trajectory_point_count),
    )


def _select_patch_ids(root: Path, *, max_patches: int, min_patches: int) -> list[str]:
    dirs = discover_patch_dirs(root)
    if not dirs:
        return []

    probes = [probe_patch(d) for d in dirs]
    ranked = sorted(probes, key=_score_probe, reverse=True)

    selected: list[str] = []
    for p in ranked:
        if len(selected) >= max_patches:
            break
        if p.trajectory_count <= 0:
            continue
        selected.append(p.patch_id)

    if len(selected) < min_patches:
        for p in ranked:
            if len(selected) >= min_patches:
                break
            if p.patch_id not in selected:
                selected.append(p.patch_id)

    return selected[:max(1, max_patches)]


def _top3_reasons(items: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for it in items[:3]:
        reason = str(it.get("reason", "na"))
        hint = str(it.get("hint", ""))
        if hint:
            out.append(f"{reason}({hint})")
        else:
            out.append(reason)
    return out


def main() -> int:
    args = _parse_args()
    repo_root = resolve_repo_root(Path.cwd())

    data_root = Path(args.data_root)
    if not data_root.is_absolute():
        data_root = (repo_root / data_root).resolve()

    alt_data_root = Path(args.alt_data_root)
    if not alt_data_root.is_absolute():
        alt_data_root = (repo_root / alt_data_root).resolve()

    patch_ids = _select_patch_ids(data_root, max_patches=int(args.max_patches), min_patches=int(args.min_patches))
    selected_root = data_root

    if len(patch_ids) < int(args.min_patches) and alt_data_root.exists():
        alt_patch_ids = _select_patch_ids(alt_data_root, max_patches=int(args.max_patches), min_patches=int(args.min_patches))
        if len(alt_patch_ids) > len(patch_ids):
            patch_ids = alt_patch_ids
            selected_root = alt_data_root

    if not patch_ids:
        print("ERROR no_patch_selected")
        return 1

    run_id = make_run_id("t05_topology_between_rc_smoke", repo_root=repo_root) if args.run_id == "auto" else str(args.run_id)

    out_root = Path(args.out_root)
    if not out_root.is_absolute():
        out_root = (repo_root / out_root).resolve()

    results: list[dict[str, Any]] = []

    for patch_id in patch_ids:
        try:
            result = run_patch(
                data_root=selected_root,
                patch_id=patch_id,
                run_id=run_id,
                out_root=out_root,
                params_override={
                    "XSEC_MIN_POINTS": int(args.xsec_min_points),
                    "MIN_SUPPORT_TRAJ": int(args.min_support_traj),
                },
            )
            results.append(
                {
                    "patch_id": patch_id,
                    "ok": True,
                    "road_count": int(result.road_count),
                    "overall_pass": bool(result.overall_pass),
                    "hard_top3": _top3_reasons(result.hard_breakpoints),
                    "soft_top3": _top3_reasons(result.soft_breakpoints),
                    "out_dir": result.output_dir,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "patch_id": patch_id,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "road_count": 0,
                    "overall_pass": False,
                    "hard_top3": [f"RUN_ERROR({type(exc).__name__})"],
                    "soft_top3": [],
                }
            )

    run_dir = out_root / run_id
    print(f"run_id={run_id}")
    print(f"data_root={selected_root.as_posix()}")
    print(f"run_dir={run_dir.as_posix()}")

    produced_any = False
    for row in results:
        if row.get("road_count", 0) > 0:
            produced_any = True
        print(
            "patch={patch} ok={ok} roads={roads} overall_pass={overall} hard_top3={hard} soft_top3={soft}".format(
                patch=row.get("patch_id"),
                ok=str(bool(row.get("ok", False))).lower(),
                roads=row.get("road_count", 0),
                overall=str(bool(row.get("overall_pass", False))).lower(),
                hard=row.get("hard_top3", []),
                soft=row.get("soft_top3", []),
            )
        )

    if not produced_any:
        reasons: list[str] = []
        for row in results:
            for item in row.get("hard_top3", []):
                if item not in reasons:
                    reasons.append(item)
        print("note=no_patch_with_road")
        print("reason_candidates=" + ",".join(reasons[:5]))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
