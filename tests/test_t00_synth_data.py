from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path

import pytest

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



def test_local_patch_id_prefers_drive_id_over_date(tmp_path: Path) -> None:
    lidar_dir = tmp_path / "lidar_empty"
    traj_dir = tmp_path / "traj"
    lidar_dir.mkdir(parents=True)
    traj_dir.mkdir(parents=True)

    # KITTI-style name: must pick drive_0000, not 2013/05/28.
    (traj_dir / "drive_2013_05_28_drive_0000_sync_frame_points_utm32.gpkg").write_bytes(b"stub")

    out_dir = tmp_path / "out_local"
    cfg = SynthConfig(
        seed=0,
        num_patches=1,
        out_dir=out_dir,
        lidar_dir=lidar_dir,
        traj_dir=traj_dir,
        source_mode="local",
    )

    manifest = run_synth(cfg)
    patch_ids = [x.get("patch_id") for x in manifest.get("patches", [])]

    assert patch_ids == ["00000000"]



def test_pointcloud_copy_mode_creates_files(tmp_path: Path) -> None:
    lidar_dir = tmp_path / "lidar"
    traj_dir = tmp_path / "traj"
    strip = lidar_dir / "strip_1"
    strip.mkdir(parents=True)
    traj_dir.mkdir(parents=True)

    (strip / "a.laz").write_bytes(b"a")
    (strip / "b.laz").write_bytes(b"b")

    out_dir = tmp_path / "out_pc_copy"
    cfg = SynthConfig(
        seed=0,
        num_patches=1,
        out_dir=out_dir,
        lidar_dir=lidar_dir,
        traj_dir=traj_dir,
        source_mode="local",
        pointcloud_mode="copy",
        traj_mode="synthetic",
    )

    manifest = run_synth(cfg)
    patch = manifest["patches"][0]

    assert patch.get("pointcloud_stub") is False
    pc_files = patch.get("pointcloud_files")
    assert isinstance(pc_files, list) and len(pc_files) == 2

    names = {Path(r).name for r in pc_files}
    assert names == {"a.laz", "b.laz"}
    assert all(_resolve(out_dir, r).is_file() for r in pc_files)


def test_traj_copy_mode_copies_source_file(tmp_path: Path) -> None:
    lidar_dir = tmp_path / "lidar"
    traj_dir = tmp_path / "traj"
    (lidar_dir / "strip_0").mkdir(parents=True)
    traj_dir.mkdir(parents=True)

    # Prefer gpkg for KITTI-style names.
    (traj_dir / "drive_2013_05_28_drive_0000_sync_frame_points_utm32.gpkg").write_bytes(b"stub")

    out_dir = tmp_path / "out_traj_copy"
    cfg = SynthConfig(
        seed=0,
        num_patches=1,
        out_dir=out_dir,
        lidar_dir=lidar_dir,
        traj_dir=traj_dir,
        source_mode="local",
        pointcloud_mode="stub",
        traj_mode="copy",
    )

    manifest = run_synth(cfg)
    patch = manifest["patches"][0]

    assert patch.get("traj_source_kind") == "gpkg"
    rel = patch.get("traj_source_file")
    assert isinstance(rel, str) and rel
    assert Path(rel).name == "source_traj.gpkg"
    assert _resolve(out_dir, rel).is_file()


def test_pointcloud_merge_mode_writes_single_merged_laz(tmp_path: Path) -> None:
    try:
        import laspy  # type: ignore
    except Exception:
        pytest.skip("laspy not installed")

    lidar_dir = tmp_path / "lidar"
    traj_dir = tmp_path / "traj"
    strip = lidar_dir / "strip_1"
    strip.mkdir(parents=True)
    traj_dir.mkdir(parents=True)

    # Write two tiny LAZ parts.
    hdr = laspy.LasHeader(point_format=3, version="1.2")
    las1 = laspy.LasData(hdr)
    las1.x = [0, 1]
    las1.y = [0, 1]
    las1.z = [0, 1]
    las1.write(strip / "p1.laz")

    las2 = laspy.LasData(hdr)
    las2.x = [2, 3, 4]
    las2.y = [2, 3, 4]
    las2.z = [2, 3, 4]
    las2.write(strip / "p2.laz")

    out_dir = tmp_path / "out_pc_merge"
    cfg = SynthConfig(
        seed=0,
        num_patches=1,
        out_dir=out_dir,
        lidar_dir=lidar_dir,
        traj_dir=traj_dir,
        source_mode="local",
        pointcloud_mode="merge",
        traj_mode="synthetic",
    )

    manifest = run_synth(cfg)
    patch = manifest["patches"][0]

    assert patch.get("pointcloud_stub") is False
    assert patch.get("pointcloud_parts_count") == 2
    pc_files = patch.get("pointcloud_files")
    assert isinstance(pc_files, list) and len(pc_files) == 1
    assert Path(pc_files[0]).name == "merged.laz"

    merged = _resolve(out_dir, pc_files[0])
    assert merged.is_file()

    # Sanity: point count matches sum of parts.
    with laspy.open(merged) as r:
        assert r.header.point_count == 5


def _make_minimal_gpkg_pointz(path: Path, *, srs_id: int = 32632) -> None:
    # Minimal tables queried by our converter.
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE gpkg_contents (
              table_name TEXT PRIMARY KEY,
              data_type TEXT NOT NULL
            );
            CREATE TABLE gpkg_geometry_columns (
              table_name TEXT NOT NULL,
              column_name TEXT NOT NULL,
              srs_id INTEGER NOT NULL,
              PRIMARY KEY (table_name, column_name)
            );
            """
        )

        conn.execute("CREATE TABLE frame_points (id INTEGER PRIMARY KEY, frame_id INTEGER, geom BLOB)")

        conn.execute(
            "INSERT INTO gpkg_contents(table_name, data_type) VALUES (?, ?)",
            ("frame_points", "features"),
        )
        conn.execute(
            "INSERT INTO gpkg_geometry_columns(table_name, column_name, srs_id) VALUES (?, ?, ?)",
            ("frame_points", "geom", int(srs_id)),
        )

        # GeoPackage geometry blob: header(8) + WKB(PointZ)
        # - flags=1: little-endian, no envelope.
        x, y, z = 1.0, 2.0, 3.0
        header = b"GP" + bytes([0, 1]) + struct.pack("<i", int(srs_id))
        wkb = bytes([1]) + struct.pack("<I", 1001) + struct.pack("<ddd", x, y, z)
        geom = header + wkb

        conn.execute("INSERT INTO frame_points(frame_id, geom) VALUES (?, ?)", (7, geom))
        conn.commit()
    finally:
        conn.close()


def test_traj_convert_mode_writes_geojson_with_crs(tmp_path: Path) -> None:
    lidar_dir = tmp_path / "lidar"
    traj_dir = tmp_path / "traj"
    (lidar_dir / "strip_0").mkdir(parents=True)
    traj_dir.mkdir(parents=True)

    gpkg = traj_dir / "drive_2013_05_28_drive_0000_sync_frame_points_utm32.gpkg"
    _make_minimal_gpkg_pointz(gpkg, srs_id=32632)

    out_dir = tmp_path / "out_traj_convert"
    cfg = SynthConfig(
        seed=0,
        num_patches=1,
        out_dir=out_dir,
        lidar_dir=lidar_dir,
        traj_dir=traj_dir,
        source_mode="local",
        pointcloud_mode="stub",
        traj_mode="convert",
    )

    manifest = run_synth(cfg)
    patch = manifest["patches"][0]

    # Sidecar copy exists and is referenced in manifest.
    rel_src = patch.get("traj_source_file")
    assert isinstance(rel_src, str) and Path(rel_src).name == "source_traj.gpkg"
    assert _resolve(out_dir, rel_src).is_file()

    raw = _resolve(out_dir, patch["paths"]["traj_raw_dat_pose"])
    obj = json.loads(raw.read_text(encoding="utf-8"))
    assert obj.get("type") == "FeatureCollection"
    assert obj.get("crs", {}).get("properties", {}).get("name") == "EPSG:32632"

    feats = obj.get("features", [])
    assert isinstance(feats, list) and len(feats) >= 1
    g0 = feats[0].get("geometry", {})
    assert g0.get("type") == "Point"
    coords = g0.get("coordinates")
    assert isinstance(coords, list) and len(coords) == 3


def test_synth_stdout_is_pasteable(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "out"

    rc = main(["synth", "--source-mode", "synthetic", "--out-dir", str(out_dir)])
    captured = capsys.readouterr()

    assert rc == 0

    ok, violations = lint_text(captured.out)
    assert ok is True, violations

    # stderr should be clean on success.
    assert captured.err.strip() == ""
