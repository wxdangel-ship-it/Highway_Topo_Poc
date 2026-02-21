from __future__ import annotations

import argparse
import sys
from pathlib import Path

from highway_topo_poc.protocol.text_lint import lint_text
from highway_topo_poc.protocol.text_qc_bundle import (
    qc_bundle_template,
    build_demo_bundle,
)


REQUIRED_DOCS = [
    "SPEC.md",
    "docs/CODEX_START_HERE.md",
    "docs/PROJECT_BRIEF.md",
    "docs/AGENT_PLAYBOOK.md",
    "docs/CODEX_GUARDRAILS.md",
    "docs/ARTIFACT_PROTOCOL.md",
    "docs/WORKSPACE_SETUP.md",
]


def _find_repo_root(start: Path) -> Path | None:
    p = start.resolve()
    for candidate in [p, *p.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "docs").is_dir():
            return candidate
    return None


def _cmd_doctor(_args: argparse.Namespace) -> int:
    root = _find_repo_root(Path.cwd())
    print("Highway_Topo_Poc doctor")

    if root is None:
        print("RepoRoot: NOT_FOUND (need SPEC.md + docs/)")
        return 1

    print("RepoRoot: OK")

    missing = [rel for rel in REQUIRED_DOCS if not (root / rel).exists()]
    if missing:
        print("Docs: MISSING")
        for rel in missing:
            print(f"- {rel}")
    else:
        print("Docs: OK")

    pyver = sys.version.split()[0]
    print(f"Python: {pyver}")

    try:
        import highway_topo_poc as pkg

        print(f"PackageImport: OK (version={pkg.__version__})")
    except Exception:
        # Avoid printing tracebacks that may include local paths.
        print("PackageImport: FAIL")
        return 1

    return 0


def _cmd_qc_template(_args: argparse.Namespace) -> int:
    print(qc_bundle_template())
    return 0


def _cmd_qc_demo(_args: argparse.Namespace) -> int:
    print(build_demo_bundle())
    return 0


def _cmd_lint_text(args: argparse.Namespace) -> int:
    if args.text is not None:
        text = args.text
    else:
        text = sys.stdin.read()

    if not text.strip():
        print("No input text provided.", file=sys.stderr)
        return 2

    ok, violations = lint_text(text)
    if ok:
        print("OK")
        for v in violations:
            if v.startswith("LONG_LINE"):
                print(f"- {v}")
        return 0

    print("NOT_PASTEABLE")
    for v in violations:
        print(f"- {v}")
    return 2


def _cmd_synth(args: argparse.Namespace) -> int:
    # Import locally to keep core CLI lightweight.
    import os

    from modules.t00_synth_data.synth import SynthConfig, normalize_input_path, run_synth

    out_dir = normalize_input_path(args.out_dir)

    lidar_raw = args.lidar_dir or os.environ.get("HIGHWAY_TOPO_POC_LIDAR_DIR")
    traj_raw = args.traj_dir or os.environ.get("HIGHWAY_TOPO_POC_TRAJ_DIR")

    lidar_dir = normalize_input_path(lidar_raw) if lidar_raw else None
    traj_dir = normalize_input_path(traj_raw) if traj_raw else None

    mode = args.source_mode
    if mode == "auto":
        if lidar_dir and traj_dir and lidar_dir.exists() and traj_dir.exists():
            mode = "local"
        else:
            mode = "synthetic"

    if mode == "local":
        if not (lidar_dir and traj_dir and lidar_dir.exists() and traj_dir.exists()):
            # Keep errors generic and paste-friendly.
            print("ERROR: local_inputs_missing", file=sys.stderr)
            return 2


    if mode != "local":
        if args.pointcloud_mode != "stub" or args.traj_mode != "synthetic":
            print("ERROR: modes_require_local", file=sys.stderr)
            return 2

    cfg = SynthConfig(
        seed=int(args.seed),
        num_patches=int(args.num_patches),
        out_dir=out_dir,
        lidar_dir=lidar_dir,
        traj_dir=traj_dir,
        source_mode=mode,
        pointcloud_mode=args.pointcloud_mode,
        traj_mode=args.traj_mode,
    )

    manifest = run_synth(cfg)
    patch_ids = [p["patch_id"] for p in manifest.get("patches", [])]

    # Keep stdout paste-friendly (short, human-readable).
    print(f"OK patches={len(patch_ids)}")
    if patch_ids:
        print("PatchIDs: " + ",".join(patch_ids))

    return 0


def _cmd_t01_fusion_qc(args: argparse.Namespace) -> int:
    from highway_topo_poc.t01_fusion_qc import (
        FusionQcConfig,
        normalize_input_path,
        run_fusion_qc,
    )

    patch_dir = normalize_input_path(args.patch)
    out_dir = normalize_input_path(args.out)

    cfg = FusionQcConfig(
        patch_dir=patch_dir,
        out_dir=out_dir,
        sample_stride=int(args.sample_stride),
        binN=int(args.binN),
        radius=float(args.radius),
        radius_max=float(args.radius_max),
        min_neighbors=int(args.min_neighbors),
        close_frac=float(args.close_frac),
        min_close_points=int(args.min_close_points),
        th=float(args.th),
        min_interval_bins=int(args.min_interval_bins),
        topk_intervals=int(args.topk_intervals),
        pc_max_points=int(args.pc_max_points),
        seed=int(args.seed),
        max_lines=int(args.max_lines),
        max_chars=int(args.max_chars),
    )

    result = run_fusion_qc(cfg)

    print(
        "OK "
        f"samples={result.sample_count} "
        f"valid={result.valid_residual_count} "
        f"intervals={result.interval_count}"
    )
    print(f"Artifact: {result.text_artifact_path}")
    print(f"IntervalsCSV: {result.intervals_csv_path}")
    if result.errors:
        errs = ",".join([f"{k}:{v}" for k, v in sorted(result.errors.items())])
        print(f"Errors: {errs}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="highway_topo_poc")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor", help="Check repo/docs/python environment.")
    p_doctor.set_defaults(func=_cmd_doctor)

    p_tpl = sub.add_parser("qc-template", help="Print TEXT_QC_BUNDLE v1 template.")
    p_tpl.set_defaults(func=_cmd_qc_template)

    p_demo = sub.add_parser("qc-demo", help="Print a demo TEXT_QC_BUNDLE (pasteable + truncated).")
    p_demo.set_defaults(func=_cmd_qc_demo)

    p_lint = sub.add_parser("lint-text", help="Check text pasteability (size/lines/long lines).")
    p_lint.add_argument("--text", help="Text to lint (if omitted, read stdin).")
    p_lint.set_defaults(func=_cmd_lint_text)

    p_synth = sub.add_parser("synth", help="Generate deterministic synth/local patches + manifest.")
    p_synth.add_argument("--out-dir", default="data/synth", help="Output directory.")
    p_synth.add_argument("--seed", type=int, default=0)
    p_synth.add_argument("--num-patches", type=int, default=8)
    p_synth.add_argument("--lidar-dir", help="Local lidar strip dir (optional).")
    p_synth.add_argument("--traj-dir", help="Local traj dir (optional).")
    p_synth.add_argument("--source-mode", choices=["auto", "local", "synthetic"], default="auto")
    p_synth.add_argument("--pointcloud-mode", choices=["stub", "link", "copy", "merge"], default="stub")
    p_synth.add_argument("--traj-mode", choices=["synthetic", "copy", "convert"], default="synthetic")
    p_synth.set_defaults(func=_cmd_synth)

    p_t01 = sub.add_parser("t01-fusion-qc", help="t01 fusion QC: scalar residual + interval detection.")
    p_t01.add_argument("--patch", required=True, help="Patch directory path.")
    p_t01.add_argument("--out", required=True, help="Output directory path.")
    p_t01.add_argument("--sample-stride", type=int, default=5)
    p_t01.add_argument("--binN", type=int, default=1000)
    p_t01.add_argument("--radius", type=float, default=1.0)
    p_t01.add_argument("--radius-max", type=float, default=3.0)
    p_t01.add_argument("--min-neighbors", type=int, default=30)
    p_t01.add_argument("--close-frac", type=float, default=0.2)
    p_t01.add_argument("--min-close-points", type=int, default=20)
    p_t01.add_argument("--th", type=float, default=0.20)
    p_t01.add_argument("--min-interval-bins", type=int, default=3)
    p_t01.add_argument("--topk-intervals", type=int, default=20)
    p_t01.add_argument("--pc-max-points", type=int, default=3_000_000)
    p_t01.add_argument("--seed", type=int, default=0)
    p_t01.add_argument("--max-lines", type=int, default=220)
    p_t01.add_argument("--max-chars", type=int, default=20_000)
    p_t01.set_defaults(func=_cmd_t01_fusion_qc)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as e:
        # Avoid printing tracebacks that may include local paths.
        if isinstance(e, ValueError) and str(e):
            print(f"ERROR: {e}", file=sys.stderr)
        else:
            print(f"ERROR: {type(e).__name__}", file=sys.stderr)
        return 1
