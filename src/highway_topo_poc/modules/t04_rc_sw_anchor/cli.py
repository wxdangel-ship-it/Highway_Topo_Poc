from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from .config import load_config, parse_set_overrides
from .runner import run_patch


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="t04_rc_sw_anchor")
    p.add_argument("--patch_dir", required=True)
    p.add_argument("--out_root", default="outputs/_work/t04_rc_sw_anchor")
    p.add_argument("--run_id", default=None)
    p.add_argument("--config_json", default=None)
    p.add_argument("--set", dest="set_items", action="append", default=[])
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config_json = Path(args.config_json) if args.config_json else None
        overrides = parse_set_overrides(args.set_items)
        cfg = load_config(config_json=config_json, set_overrides=overrides)

        result = run_patch(
            patch_dir=Path(args.patch_dir),
            out_root=Path(args.out_root),
            run_id=args.run_id,
            config=cfg,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        "OK run_id={run_id} patch_id={patch_id} overall_pass={overall} out_dir={out_dir}".format(
            run_id=result.run_id,
            patch_id=result.patch_id,
            overall=str(bool(result.overall_pass)).lower(),
            out_dir=result.out_dir.as_posix(),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
