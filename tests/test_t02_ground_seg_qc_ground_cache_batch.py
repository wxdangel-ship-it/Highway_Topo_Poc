from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from highway_topo_poc.modules.t02_ground_seg_qc.batch_ground_cache import main


def _write_patch_points(data_root: Path, patch_key: str, points: np.ndarray) -> None:
    patch_dir = data_root / patch_key
    patch_dir.mkdir(parents=True, exist_ok=True)
    np.save(patch_dir / "points.npy", points)


def _make_points(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n_ground = 400
    n_obj = 350

    gx = rng.uniform(0.0, 30.0, size=n_ground)
    gy = rng.uniform(0.0, 20.0, size=n_ground)
    gz = rng.normal(0.0, 0.01, size=n_ground)
    ground = np.column_stack([gx, gy, gz])

    ox = rng.uniform(0.0, 30.0, size=n_obj)
    oy = rng.uniform(0.0, 20.0, size=n_obj)
    oz = rng.normal(1.0, 0.03, size=n_obj)
    obj = np.column_stack([ox, oy, oz])

    return np.vstack([ground, obj]).astype(np.float64)


def test_ground_cache_batch_full_size_labels(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    out_root = tmp_path / "out"

    _write_patch_points(data_root=data_root, patch_key="patchA", points=_make_points(1))
    _write_patch_points(data_root=data_root, patch_key="patchB", points=_make_points(2))

    run_id = "ut_ground_cache"
    exit_code = main(
        [
            "--data_root",
            str(data_root),
            "--out_root",
            str(out_root),
            "--run_id",
            run_id,
            "--resume",
            "false",
            "--workers",
            "1",
            "--chunk_points",
            "200",
            "--export_classified_laz",
            "false",
        ]
    )
    assert exit_code == 0

    run_root = out_root / run_id
    manifest_path = run_root / "ground_cache_manifest.jsonl"
    assert manifest_path.is_file()

    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 2

    for row in rows:
        points_path = Path(str(row["points_path"]))
        label_path = Path(str(row["label_path"]))
        stats_path = Path(str(row["stats_path"]))
        idx_path = label_path.parent / "ground_idx.npy"

        assert label_path.is_file()
        assert stats_path.is_file()
        assert idx_path.is_file()

        points = np.load(points_path)
        labels = np.load(label_path)
        assert labels.shape == (int(points.shape[0]),)
        assert labels.dtype == np.uint8

        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        ratio = float(stats["ground_ratio"])
        assert 0.05 <= ratio <= 0.95
        assert int(stats["n_points"]) == int(points.shape[0])
        assert int(stats["n_ground"]) == int(labels.sum())
