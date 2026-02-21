from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from highway_topo_poc.modules.t02_ground_seg_qc.export_classified_cloud import main


def _write_small_las(path: Path, n_points: int = 2000) -> None:
    import laspy

    rng = np.random.default_rng(42)

    hdr = laspy.LasHeader(point_format=3, version="1.2")
    hdr.x_scale = 0.01
    hdr.y_scale = 0.01
    hdr.z_scale = 0.01

    las = laspy.LasData(hdr)
    las.x = rng.uniform(100.0, 200.0, size=n_points)
    las.y = rng.uniform(50.0, 150.0, size=n_points)
    las.z = rng.uniform(-1.0, 3.0, size=n_points)
    las.intensity = rng.integers(0, 65535, size=n_points, dtype=np.uint16)
    las.return_number = rng.integers(1, 4, size=n_points, dtype=np.uint8)
    las.number_of_returns = np.maximum(las.return_number, rng.integers(1, 4, size=n_points, dtype=np.uint8))
    las.classification = np.full((n_points,), 1, dtype=np.uint8)
    las.write(str(path))


def test_export_classified_cloud_from_manifest(tmp_path: Path) -> None:
    n_points = 2000
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    in_las = data_dir / "in.las"
    _write_small_las(in_las, n_points=n_points)

    labels = np.zeros((n_points,), dtype=np.uint8)
    labels[:700] = 1
    label_path = tmp_path / "ground_label.npy"
    np.save(label_path, labels)

    manifest_path = tmp_path / "ground_cache_manifest.jsonl"
    row = {
        "patch_key": "patchA",
        "points_path": str(in_las),
        "label_path": str(label_path),
        "n_points": n_points,
        "n_ground": int(labels.sum()),
    }
    manifest_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    out_root = tmp_path / "out"
    run_id = "ut_export_classified"
    exit_code = main(
        [
            "--in_manifest",
            str(manifest_path),
            "--out_root",
            str(out_root),
            "--run_id",
            run_id,
            "--resume",
            "false",
            "--workers",
            "1",
            "--chunk_points",
            "256",
            "--ground_class",
            "2",
            "--non_ground_class",
            "1",
            "--out_format",
            "las",
            "--verify",
            "true",
        ]
    )
    assert exit_code == 0

    out_las = out_root / run_id / "classified_cloud" / "patchA" / "merged_classified.las"
    assert out_las.is_file()

    import laspy

    in_data = laspy.read(str(in_las))
    out_data = laspy.read(str(out_las))

    assert int(len(out_data.x)) == n_points
    cls = np.asarray(out_data.classification, dtype=np.uint8)
    assert int(np.count_nonzero(cls == 2)) == int(labels.sum())
    assert int(np.count_nonzero(cls == 1)) == int(n_points - labels.sum())

    # Ensure non-classification dimensions are preserved.
    assert np.array_equal(np.asarray(in_data.intensity), np.asarray(out_data.intensity))
    assert np.array_equal(np.asarray(in_data.return_number), np.asarray(out_data.return_number))
    assert np.array_equal(np.asarray(in_data.number_of_returns), np.asarray(out_data.number_of_returns))
