from __future__ import annotations

from pathlib import Path

import numpy as np

from highway_topo_poc.t01_fusion_qc.core import (
    FusionQcConfig,
    _build_intervals,
    _build_text_bundle,
    downsample_indices,
    merge_true_runs,
)


def test_interval_merge_and_min_interval_bins() -> None:
    flags = [False, True, True, False, True, True, True, False, True]
    runs = merge_true_runs(flags, min_len=2)
    assert runs == [(1, 2), (4, 6)]

    bin_scores = np.asarray([0.10, 0.30, 0.40, 0.05, 0.26, 0.25, 0.24, 0.02], dtype=np.float64)
    edges = np.arange(0, bin_scores.shape[0] + 1, dtype=np.int64)

    intervals, count, _pct = _build_intervals(
        bin_scores=bin_scores,
        edges=edges,
        threshold=0.20,
        min_interval_bins=2,
        topk_intervals=10,
    )
    assert count == 2
    assert [(x.start_bin, x.end_bin) for x in intervals] == [(1, 2), (4, 6)]

    intervals_short, count_short, _ = _build_intervals(
        bin_scores=bin_scores,
        edges=edges,
        threshold=0.20,
        min_interval_bins=3,
        topk_intervals=10,
    )
    assert count_short == 1
    assert [(x.start_bin, x.end_bin) for x in intervals_short] == [(4, 6)]


def test_output_structure_topk_and_truncation() -> None:
    # Build many isolated anomaly bins so Top-K filtering is testable.
    scores = []
    peak = 0.21
    for _ in range(12):
        scores.append(peak)
        scores.append(0.01)
        peak += 0.01
    bin_scores = np.asarray(scores, dtype=np.float64)
    edges = np.arange(0, bin_scores.shape[0] + 1, dtype=np.int64)

    intervals_topk, interval_count, interval_pct = _build_intervals(
        bin_scores=bin_scores,
        edges=edges,
        threshold=0.20,
        min_interval_bins=1,
        topk_intervals=4,
    )

    assert interval_count == 12
    assert len(intervals_topk) == 4
    assert intervals_topk[0].peak_bin_score >= intervals_topk[-1].peak_bin_score

    cfg_full = FusionQcConfig(
        patch_dir=Path("/tmp/patch"),
        out_dir=Path("/tmp/out"),
        topk_intervals=4,
        max_lines=120,
        max_chars=8192,
    )

    text_full = _build_text_bundle(
        cfg=cfg_full,
        patch_dir=Path("/tmp/patch_0001"),
        traj_files=[Path("/tmp/patch_0001/Traj/0001/raw_dat_pose.geojson")],
        merged_laz=Path("/tmp/patch_0001/PointCloud/merged.laz"),
        crs_name="EPSG:32632",
        search_backend="grid",
        sample_count=100,
        valid_count=90,
        p50=0.03,
        p90=0.08,
        p99=0.12,
        binN_eff=int(bin_scores.shape[0]),
        interval_count=interval_count,
        interval_total_len_pct=interval_pct,
        intervals_topk=intervals_topk,
        errors={"traj_z_missing": 10},
        breakpoints=["traj_z_missing"],
        pointcloud_points_total=1000,
        pointcloud_points_scanned=1000,
        pointcloud_points_used=1000,
    )

    assert "Params(TopN<=12):" in text_full
    assert "Metrics(TopN<=10):" in text_full
    assert "Intervals(binN=" in text_full
    assert "Breakpoints:" in text_full
    assert "Errors:" in text_full
    assert "Truncated: false" in text_full

    cfg_tight = FusionQcConfig(
        patch_dir=Path("/tmp/patch"),
        out_dir=Path("/tmp/out"),
        topk_intervals=4,
        max_lines=18,
        max_chars=420,
    )

    text_tight = _build_text_bundle(
        cfg=cfg_tight,
        patch_dir=Path("/tmp/patch_0001"),
        traj_files=[Path("/tmp/patch_0001/Traj/0001/raw_dat_pose.geojson")],
        merged_laz=Path("/tmp/patch_0001/PointCloud/merged.laz"),
        crs_name="EPSG:32632",
        search_backend="grid",
        sample_count=100,
        valid_count=90,
        p50=0.03,
        p90=0.08,
        p99=0.12,
        binN_eff=int(bin_scores.shape[0]),
        interval_count=interval_count,
        interval_total_len_pct=interval_pct,
        intervals_topk=intervals_topk,
        errors={"traj_z_missing": 10},
        breakpoints=["traj_z_missing"],
        pointcloud_points_total=1000,
        pointcloud_points_scanned=1000,
        pointcloud_points_used=1000,
    )

    # max_lines/max_chars should trigger truncation and carry TRUNCATED marker.
    assert "Truncated: true (reason=TRUNCATED)" in text_tight
    assert len(text_tight.splitlines()) <= 18
    assert len(text_tight.encode("utf-8")) <= 420


def test_downsample_indices_reproducible_by_seed() -> None:
    idx1 = downsample_indices(total_points=1000, max_points=120, seed=7)
    idx2 = downsample_indices(total_points=1000, max_points=120, seed=7)
    idx3 = downsample_indices(total_points=1000, max_points=120, seed=8)

    assert np.array_equal(idx1, idx2)
    assert idx1.shape == (120,)
    assert np.all(idx1[:-1] <= idx1[1:])
    assert not np.array_equal(idx1, idx3)
