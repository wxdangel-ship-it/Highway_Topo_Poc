from __future__ import annotations

import json
from pathlib import Path

from highway_topo_poc.cli import main
from highway_topo_poc.protocol.text_lint import lint_text
from modules.t00_synth_data.synth import SynthConfig, run_synth


def _make_fake_local_sample(tmp_path: Path) -> tuple[Path, Path]:
    lidar_dir = tmp_path / "lidar"
    traj_dir = tmp_path / "traj"
    lidar_dir.mkdir(parents=True)
    traj_dir.mkdir(parents=True)

    # 8 strips + 8 traj files. Names include digits used to derive PatchID.
    for i in range(1, 9):
        strip = lidar_dir / f"strip_{i}"
        strip.mkdir(parents=True)
        (strip / f"pc_{i}.laz").write_bytes(b"stub\n")
        (traj_dir / f"traj_{i}.geojson").write_text("{}\n", encoding="utf-8")

    return lidar_dir, traj_dir


def _resolve(out_dir: Path, rel_or_abs: str) -> Path:
    p = Path(str(rel_or_abs))
    return p if p.is_absolute() else (out_dir / p)


def test_t00_synth_determinism(tmp_path: Path) -> None:
    lidar_dir, traj_dir = _make_fake_local_sample(tmp_path)

    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"

    cfg1 = SynthConfig(
        seed=7,
        num_patches=8,
        out_dir=out1,
        lidar_dir=lidar_dir,
        traj_dir=traj_dir,
        source_mode="local",
    )
    cfg2 = SynthConfig(
        seed=7,
        num_patches=8,
        out_dir=out2,
        lidar_dir=lidar_dir,
        traj_dir=traj_dir,
        source_mode="local",
    )

    run_synth(cfg1)
    run_synth(cfg2)

    b1 = (out1 / "patch_manifest.json").read_bytes()
    b2 = (out2 / "patch_manifest.json").read_bytes()

    assert b1 == b2


def test_t00_synth_manifest_schema_min(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    cfg = SynthConfig(seed=0, num_patches=8, out_dir=out_dir, source_mode="synthetic")

    run_synth(cfg)

    manifest_path = out_dir / "patch_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest.get("schema_version")
    assert manifest.get("seed") == 0
    assert manifest.get("patches")

    patches = manifest["patches"]
    assert len(patches) == 8

    for p in patches:
        assert p.get("patch_id")
        assert p.get("traj_id")
        assert p.get("pointcloud_stub") is True

        paths = p.get("paths")
        assert isinstance(paths, dict)

        for k in [
            "pointcloud_laz",
            "vector_lane_boundary",
            "vector_gorearea",
            "traj_raw_dat_pose",
        ]:
            assert k in paths

        lane = paths["vector_lane_boundary"]
        gore = paths["vector_gorearea"]
        traj = paths["traj_raw_dat_pose"]
        laz_list = paths["pointcloud_laz"]

        assert _resolve(out_dir, lane).is_file()
        assert _resolve(out_dir, gore).is_file()
        assert _resolve(out_dir, traj).is_file()
        assert all(_resolve(out_dir, r).is_file() for r in laz_list)


def test_synth_stdout_is_pasteable(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "out"

    rc = main(["synth", "--source-mode", "synthetic", "--out-dir", str(out_dir)])
    captured = capsys.readouterr()

    assert rc == 0

    ok, violations = lint_text(captured.out)
    assert ok is True, violations

    # stderr should be clean on success.
    assert captured.err.strip() == ""
