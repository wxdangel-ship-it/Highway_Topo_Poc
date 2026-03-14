from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from highway_topo_poc.modules.t05_topology_between_rc_v2.io import resolve_repo_root
from highway_topo_poc.modules.t05_topology_between_rc_v2.review import write_arc_first_attach_evidence_review


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t05_v2_arc_first_attach_evidence_review")
    parser.add_argument("--run-root", required=True, help="Directory that contains patches/<patch_id>/...")
    parser.add_argument(
        "--output-root",
        help="Defaults to <repo>/outputs/_work/t05_v2_arc_first_attach_evidence_<timestamp>",
    )
    parser.add_argument("--complex-patch-id", default="5417632623039346")
    parser.add_argument(
        "--simple-patch-id",
        dest="simple_patch_ids",
        action="append",
        default=[],
        help="Repeatable. Defaults to 5417632690143239 and 5417632690143326 when omitted.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = resolve_repo_root(Path.cwd())
    output_root = Path(args.output_root) if args.output_root else (
        repo_root / "outputs" / "_work" / f"t05_v2_arc_first_attach_evidence_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    summary = write_arc_first_attach_evidence_review(
        run_root=Path(args.run_root),
        output_root=output_root,
        simple_patch_ids=list(args.simple_patch_ids) or ["5417632690143239", "5417632690143326"],
        complex_patch_id=str(args.complex_patch_id),
    )
    print(f"OK output_root={summary['output_root']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
