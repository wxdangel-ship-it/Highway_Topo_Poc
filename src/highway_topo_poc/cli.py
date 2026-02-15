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
        return 0

    print("BLOCKED")
    for v in violations:
        print(f"- {v}")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="highway_topo_poc")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor", help="Check repo/docs/python environment (no path output).")
    p_doctor.set_defaults(func=_cmd_doctor)

    p_tpl = sub.add_parser("qc-template", help="Print TEXT_QC_BUNDLE v1 template.")
    p_tpl.set_defaults(func=_cmd_qc_template)

    p_demo = sub.add_parser("qc-demo", help="Print a demo TEXT_QC_BUNDLE (must be safe + truncated).")
    p_demo.set_defaults(func=_cmd_qc_demo)

    p_lint = sub.add_parser("lint-text", help="Lint pasted text for forbidden info (reads stdin by default).")
    p_lint.add_argument("--text", help="Text to lint (if omitted, read stdin).")
    p_lint.set_defaults(func=_cmd_lint_text)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as e:
        # Avoid printing tracebacks that may include local paths.
        print(f"ERROR: {type(e).__name__}", file=sys.stderr)
        return 1
