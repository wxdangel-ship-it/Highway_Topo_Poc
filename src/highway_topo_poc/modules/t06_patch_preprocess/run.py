from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Iterable

from .io import InputDataError
from .pipeline import DEFAULT_PARAMS, run_patch


def _parse_bool(v: str) -> bool:
    vv = str(v).strip().lower()
    if vv in {"1", "true", "yes", "y", "on"}:
        return True
    if vv in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid_bool: {v}")


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="t06_patch_preprocess")
    p.add_argument("--data_root", required=True)
    p.add_argument("--patch", default="auto")
    p.add_argument("--run_id", default="auto")
    p.add_argument("--out_root", default="outputs/_work/t06_patch_preprocess")
    p.add_argument("--overwrite", type=_parse_bool, default=True)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--drivezone", default=None, help="Optional DriveZone path override")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_patch(
            data_root=args.data_root,
            patch=args.patch,
            run_id=args.run_id,
            out_root=args.out_root,
            overwrite=bool(args.overwrite),
            verbose=bool(args.verbose),
            drivezone=args.drivezone,
        )
    except InputDataError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover
        print(json.dumps({"ok": False, "error": f"unexpected:{exc}"}, ensure_ascii=False), file=sys.stderr)
        traceback.print_exc()
        return 1

    payload = {
        "ok": True,
        "run_id": result.run_id,
        "patch_id": result.patch_id,
        "output_dir": str(result.output_dir),
        "summary": str(result.summary_path),
        "drop_reasons": str(result.drop_reasons_path),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
