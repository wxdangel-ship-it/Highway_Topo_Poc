from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from highway_topo_poc.cli import main


@pytest.mark.smoke
def test_smoke_t00_synth_writes_outputs_work() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path("outputs/_work/smoke_t00_synth") / f"{run_id}_{os.getpid()}"

    rc = main(
        [
            "synth",
            "--source-mode",
            "synthetic",
            "--num-patches",
            "1",
            "--seed",
            "0",
            "--out-dir",
            str(out_dir),
        ]
    )
    assert rc == 0

    manifest_path = out_dir / "patch_manifest.json"
    assert manifest_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    patches = manifest.get("patches")
    assert isinstance(patches, list)
    assert len(patches) == 1
