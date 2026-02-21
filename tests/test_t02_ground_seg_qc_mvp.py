from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from highway_topo_poc.modules.t02_ground_seg_qc import Config, run_patch


def _write_patch(patch_dir: Path, *, points: np.ndarray, traj: np.ndarray) -> None:
    patch_dir.mkdir(parents=True, exist_ok=True)
    np.save(patch_dir / "points.npy", points)
    np.save(patch_dir / "traj.npy", traj)


def _make_plane_dataset(*, with_cross_anomaly: bool) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)

    xs = np.linspace(0.0, 100.0, 101)
    ys = np.linspace(-6.0, 6.0, 25)
    xx, yy = np.meshgrid(xs, ys)
    zz = rng.normal(0.0, 0.015, size=xx.shape)
    ground = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])

    # Generic non-ground clutter.
    n_obj = 500
    ox = rng.uniform(0.0, 100.0, size=n_obj)
    oy = rng.uniform(-6.0, 6.0, size=n_obj)
    oz = rng.normal(1.2, 0.2, size=n_obj)
    obj = np.column_stack([ox, oy, oz])

    pts = [ground, obj]

    if with_cross_anomaly:
        # Dense elevated strip in a local along-range to trigger xsec residual.
        ax = rng.uniform(40.0, 55.0, size=1200)
        ay = rng.uniform(-5.5, 5.5, size=1200)
        az = rng.normal(0.55, 0.03, size=1200)
        anomaly = np.column_stack([ax, ay, az])
        pts.append(anomaly)

    points = np.vstack(pts)

    n_traj = 101
    tx = np.linspace(0.0, 100.0, num=n_traj)
    ty = np.zeros(n_traj)
    tz = 1.80 + rng.normal(0.0, 0.01, size=n_traj)
    traj = np.column_stack([tx, ty, tz])

    return points, traj


def _base_cfg(**kwargs: object) -> Config:
    cfg = Config(
        processing_max_points=200_000,
        grid_size_m=1.0,
        dem_quantile_q=0.08,
        min_points_per_cell=5,
        neighbor_cell_radius=2,
        neighbor_min_points=15,
        threshold_m=0.25,
        ground_count_gate_min=300,
        xsec_bin_count=21,
        xsec_interval_bin_count=32,
        xsec_residual_gate_per_sample=0.12,
        xsec_p99_abs_res_gate_m=0.15,
    )
    if kwargs:
        cfg = cfg.with_updates(**kwargs)
    return cfg


def test_ground_classification_dem_band(tmp_path: Path) -> None:
    points, traj = _make_plane_dataset(with_cross_anomaly=False)

    data_root = tmp_path / "data"
    patch_dir = data_root / "00000001"
    _write_patch(patch_dir, points=points, traj=traj)

    cfg = _base_cfg(auto_tune_default=False)
    result = run_patch(
        data_root=data_root,
        patch="auto",
        run_id="ut_ground",
        out_root=tmp_path / "out",
        config=cfg,
        auto_tune=False,
    )

    metrics = result["metrics"]
    assert 0.2 < float(metrics["ground_ratio"]) < 0.95

    out_dir = Path(str(result["output_dir"]))
    assert (out_dir / "ground_idx.npy").is_file()
    assert (out_dir / "ground_points.npy").is_file()
    assert (out_dir / "ground_stats.json").is_file()

    ground_points = np.load(out_dir / "ground_points.npy")
    assert ground_points.shape[0] > 100
    assert float(np.quantile(ground_points[:, 2], 0.90)) < 0.20


def test_xsec_qc_detects_local_cross_anomaly(tmp_path: Path) -> None:
    points, traj = _make_plane_dataset(with_cross_anomaly=True)

    data_root = tmp_path / "data"
    patch_dir = data_root / "00000002"
    _write_patch(patch_dir, points=points, traj=traj)

    # Wide margin intentionally absorbs anomaly into ground to trigger xsec fail signal.
    cfg = _base_cfg(
        auto_tune_default=False,
        above_margin_m=0.80,
        below_margin_m=0.30,
        xsec_residual_gate_per_sample=0.10,
    )

    result = run_patch(
        data_root=data_root,
        patch="auto",
        run_id="ut_xsec",
        out_root=tmp_path / "out",
        config=cfg,
        auto_tune=False,
    )

    metrics = result["metrics"]
    assert float(metrics["xsec_p99_abs_res_m"]) > cfg.xsec_p99_abs_res_gate_m

    xsec_intervals = result["xsec_intervals"]
    intervals = xsec_intervals.get("intervals", [])
    assert intervals, "expected xsec anomaly intervals"

    has_overlap = any(not (int(iv["end_idx"]) < 40 or int(iv["start_idx"]) > 55) for iv in intervals)
    assert has_overlap


def test_auto_tune_can_move_from_fail_to_pass(tmp_path: Path) -> None:
    points, traj = _make_plane_dataset(with_cross_anomaly=True)

    data_root = tmp_path / "data"
    patch_dir = data_root / "00000003"
    _write_patch(patch_dir, points=points, traj=traj)

    cfg = _base_cfg(
        auto_tune_default=True,
        above_margin_m=0.80,
        below_margin_m=0.30,
        xsec_residual_gate_per_sample=0.10,
        xsec_p99_abs_res_gate_m=0.31,
        auto_tune_max_trials=20,
    )

    result = run_patch(
        data_root=data_root,
        patch="auto",
        run_id="ut_tune",
        out_root=tmp_path / "out",
        config=cfg,
        auto_tune=True,
    )

    metrics = result["metrics"]
    gates = metrics["gates"]
    assert gates["overall_pass"] is True

    tune_log = result["tune_log"]
    assert isinstance(tune_log, list) and len(tune_log) >= 2
    assert bool(tune_log[0]["overall_pass"]) is False
    assert bool(tune_log[-1]["overall_pass"]) is True

    chosen = result["chosen_config"]
    changed_xsec = (
        int(chosen["xsec_bin_count"]) != 21
        or float(chosen["along_window_m"]) != 1.0
        or float(chosen["cross_half_width_m"]) != 6.0
    )
    assert changed_xsec

    out_dir = Path(str(result["output_dir"]))
    assert (out_dir / "chosen_config.json").is_file()
    assert (out_dir / "tune_log.jsonl").is_file()
    assert (out_dir / "xsec_intervals.json").is_file()

    # Check written metrics agree with in-memory result.
    written = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
    assert bool(written["gates"]["overall_pass"]) is True
