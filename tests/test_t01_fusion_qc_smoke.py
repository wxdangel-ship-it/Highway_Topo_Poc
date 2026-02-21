from __future__ import annotations

import json
from pathlib import Path

import laspy
import numpy as np

from highway_topo_poc.modules.t01_fusion_qc.cli import main as t01_main
from highway_topo_poc.modules.t01_fusion_qc.core import (
    compute_metrics_and_intervals,
    estimate_cloud_z_from_arrays,
)
from highway_topo_poc.modules.t01_fusion_qc.discover import discover_patch_candidates


def _write_geojson(path: Path, coords: list[tuple[float, float, float]]) -> None:
    feats = []
    for i, (x, y, z) in enumerate(coords):
        geom_coords: list[float] = [x, y, z] if i % 2 == 0 else [x, y]
        props = {"seq": i}
        if i % 2 == 1:
            props["altitude"] = z
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": geom_coords},
                "properties": props,
            }
        )

    payload = {
        "type": "FeatureCollection",
        "features": feats,
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_las(path: Path, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> None:
    header = laspy.LasHeader(point_format=3, version="1.2")
    las = laspy.LasData(header)
    las.x = x
    las.y = y
    las.z = z
    las.write(path)


def test_core_metrics_and_intervals_are_stable() -> None:
    traj_x = np.arange(12, dtype=np.float64)
    traj_y = np.zeros(12, dtype=np.float64)
    traj_z = np.full(12, 10.0, dtype=np.float64)

    residual_true = np.asarray([0.1] * 4 + [1.0] * 4 + [0.1] * 4, dtype=np.float64)

    cloud_x = []
    cloud_y = []
    cloud_z = []
    for i, res in enumerate(residual_true.tolist()):
        for dx in (0.00, 0.05, -0.05):
            cloud_x.append(i + dx)
            cloud_y.append(0.0)
            cloud_z.append(10.0 - res)

    z_est, backend, warns = estimate_cloud_z_from_arrays(
        traj_x,
        traj_y,
        np.asarray(cloud_x, dtype=np.float64),
        np.asarray(cloud_y, dtype=np.float64),
        np.asarray(cloud_z, dtype=np.float64),
        radius_m=0.2,
        min_neighbors=2,
        knn=3,
    )

    metrics, _bins, intervals = compute_metrics_and_intervals(
        traj_z,
        z_est,
        th_abs_min=0.2,
        th_quantile=0.6,
        binN=3,
        stride=1,
        coverage_gate=0.3,
        status_coverage_gate=0.6,
        min_interval_len=2,
        top_k=5,
        backend=backend,
        warnings=warns,
    )

    assert metrics.n_traj == 12
    assert metrics.n_valid == 12
    assert metrics.coverage == 1.0
    assert metrics.status == "OK"
    assert metrics.p50 is not None and abs(metrics.p50 - 0.1) < 1e-6
    assert metrics.p90 is not None and abs(metrics.p90 - 1.0) < 1e-6
    assert metrics.threshold_A is not None and abs(metrics.threshold_A - 0.2) < 1e-6

    assert intervals
    assert intervals[0].start_bin == 3
    assert intervals[0].end_bin == 7
    assert intervals[0].start_idx == 3
    assert intervals[0].end_idx == 9


def test_discover_io_and_cli_end_to_end(tmp_path: Path) -> None:
    data_root = tmp_path / "data" / "synth_local"
    cloud_dir = data_root / "00000042" / "PointCloud"
    traj_dir = data_root / "00000042" / "Traj" / "00000042"
    cloud_dir.mkdir(parents=True, exist_ok=True)
    traj_dir.mkdir(parents=True, exist_ok=True)

    traj_coords = []
    cloud_x = []
    cloud_y = []
    cloud_z = []

    for i in range(10):
        x = float(i)
        y = 0.0
        z = 5.0
        traj_coords.append((x, y, z))

        # 前 5 个点制造高 residual（traj_z - cloud_z = 1.0），后 5 个点 residual=0.1
        res = 1.0 if i < 5 else 0.1
        for dx in (0.0, 0.08, -0.08):
            cloud_x.append(x + dx)
            cloud_y.append(y)
            cloud_z.append(z - res)

    _write_geojson(traj_dir / "raw_dat_pose.geojson", traj_coords)
    _write_las(
        cloud_dir / "merged.las",
        np.asarray(cloud_x, dtype=np.float64),
        np.asarray(cloud_y, dtype=np.float64),
        np.asarray(cloud_z, dtype=np.float64),
    )

    pairs = discover_patch_candidates(data_root)
    assert len(pairs) == 1
    assert pairs[0].cloud_path.name == "merged.las"
    assert pairs[0].traj_path.name == "raw_dat_pose.geojson"

    out_dir = tmp_path / "out"
    rc = t01_main(
        [
            "--data_root",
            str(data_root),
            "--out_dir",
            str(out_dir),
            "--max_patches",
            "1",
            "--radius_m",
            "0.2",
            "--min_neighbors",
            "2",
            "--knn",
            "3",
            "--th_abs_min",
            "0.2",
            "--th_quantile",
            "0.5",
            "--binN",
            "3",
            "--stride",
            "1",
            "--coverage_gate",
            "0.3",
            "--status_coverage_gate",
            "0.3",
            "--min_interval_len",
            "1",
            "--top_k",
            "3",
            "--max_in_memory_points",
            "100000",
        ]
    )
    assert rc == 0

    metrics_path = out_dir / "metrics.json"
    intervals_path = out_dir / "intervals.json"
    summary_path = out_dir / "summary.txt"

    assert metrics_path.exists()
    assert intervals_path.exists()
    assert summary_path.exists()

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    intervals = json.loads(intervals_path.read_text(encoding="utf-8"))
    summary = summary_path.read_text(encoding="utf-8")

    assert metrics["module"] == "t01_fusion_qc"
    assert metrics["results"]
    r0 = metrics["results"][0]
    assert r0["patch_key"] == "00000042/PointCloud"
    assert "coverage" in r0 and "threshold_A" in r0 and "status" in r0

    assert intervals["module"] == "t01_fusion_qc"
    assert intervals["results"]
    assert "intervals" in intervals["results"][0]

    assert "patch_key:" in summary
    assert "coverage:" in summary
    assert "p50/p90/p99:" in summary
    assert "threshold_A:" in summary
    assert "TopK intervals:" in summary
    assert "status:" in summary
