from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from highway_topo_poc.modules.t02_ground_seg_qc import Config, run_patch


def _build_patch(patch_dir: Path) -> None:
    patch_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)

    # Ground around z=0 with small noise, plus sparse non-ground points.
    n_ground = 1800
    gx = rng.uniform(0.0, 120.0, size=n_ground)
    gy = rng.uniform(-8.0, 8.0, size=n_ground)
    gz = rng.normal(0.0, 0.02, size=n_ground)
    ground = np.column_stack([gx, gy, gz])

    n_obj = 120
    ox = rng.uniform(0.0, 120.0, size=n_obj)
    oy = rng.uniform(-8.0, 8.0, size=n_obj)
    oz = rng.normal(2.5, 0.3, size=n_obj)
    obj = np.column_stack([ox, oy, oz])

    points = np.vstack([ground, obj])
    np.save(patch_dir / "points.npy", points)

    n_traj = 120
    tx = np.linspace(0.0, 120.0, num=n_traj)
    ty = np.zeros(n_traj)
    tz = 1.8 + rng.normal(0.0, 0.01, size=n_traj)
    tz[40:56] += 0.6
    traj = np.column_stack([tx, ty, tz])
    np.save(patch_dir / "traj.npy", traj)


def _round_json_like(obj: object, ndigits: int = 8) -> object:
    if isinstance(obj, dict):
        return {k: _round_json_like(v, ndigits=ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_json_like(v, ndigits=ndigits) for v in obj]
    if isinstance(obj, float):
        if obj != obj:  # nan
            return None
        return round(obj, ndigits)
    return obj


def test_t02_metrics_and_intervals_detect_anomaly(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    patch_dir = data_root / "00000001"
    _build_patch(patch_dir)

    cfg = Config(
        grid_size_m=2.0,
        min_points_per_cell=6,
        neighbor_cell_radius=2,
        neighbor_min_points=16,
        threshold_m=0.25,
        bin_count=24,
        min_interval_bins=1,
        top_k=5,
    )

    result = run_patch(
        data_root=data_root,
        patch="auto",
        run_id="ut_run",
        out_root=tmp_path / "out",
        config=cfg,
    )

    metrics = result["metrics"]
    assert isinstance(metrics, dict)
    for key in ["p50", "p90", "p99", "coverage", "outlier_ratio", "bias", "baseline", "threshold", "gates"]:
        assert key in metrics

    assert float(metrics["coverage"]) > 0.90

    intervals_payload = result["intervals"]
    assert isinstance(intervals_payload, dict)
    intervals = intervals_payload.get("intervals", [])
    assert isinstance(intervals, list)
    assert intervals, "expected at least one detected interval"

    # Ensure at least one top interval overlaps injected anomaly [40,55].
    has_overlap = any(not (int(iv["end_idx"]) < 40 or int(iv["start_idx"]) > 55) for iv in intervals)
    assert has_overlap

    out_dir = Path(str(result["output_dir"]))
    assert (out_dir / "metrics.json").is_file()
    assert (out_dir / "intervals.json").is_file()
    assert (out_dir / "summary.txt").is_file()
    assert (out_dir / "series.npz").is_file()


def test_t02_deterministic_same_input_same_output(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    patch_dir = data_root / "00000002"
    _build_patch(patch_dir)

    cfg = Config(
        grid_size_m=2.0,
        min_points_per_cell=6,
        neighbor_cell_radius=2,
        neighbor_min_points=16,
        threshold_m=0.25,
        bin_count=24,
        min_interval_bins=1,
        top_k=5,
    )

    r1 = run_patch(
        data_root=data_root,
        patch="auto",
        run_id="same_1",
        out_root=tmp_path / "out",
        config=cfg,
    )
    r2 = run_patch(
        data_root=data_root,
        patch="auto",
        run_id="same_2",
        out_root=tmp_path / "out",
        config=cfg,
    )

    m1 = _round_json_like(r1["metrics"])
    m2 = _round_json_like(r2["metrics"])
    assert m1 == m2

    i1 = _round_json_like(r1["intervals"])
    i2 = _round_json_like(r2["intervals"])
    assert i1 == i2

    # File payloads should also be deterministic (except run_id path part).
    p1 = Path(str(r1["output_dir"])) / "metrics.json"
    p2 = Path(str(r2["output_dir"])) / "metrics.json"
    j1 = _round_json_like(json.loads(p1.read_text(encoding="utf-8")))
    j2 = _round_json_like(json.loads(p2.read_text(encoding="utf-8")))
    assert j1 == j2


def test_t02_empty_points_coverage_zero(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    patch_dir = data_root / "00000003"
    patch_dir.mkdir(parents=True, exist_ok=True)

    np.save(patch_dir / "points.npy", np.empty((0, 3), dtype=np.float64))
    traj = np.column_stack([np.arange(30), np.zeros(30), np.full(30, 1.8)])
    np.save(patch_dir / "traj.npy", traj)

    result = run_patch(
        data_root=data_root,
        patch="auto",
        run_id="empty_points",
        out_root=tmp_path / "out",
        config=Config(),
    )

    metrics = result["metrics"]
    assert metrics["coverage"] == 0.0
    assert metrics["n_valid"] == 0
    assert result["intervals"]["intervals"] == []
