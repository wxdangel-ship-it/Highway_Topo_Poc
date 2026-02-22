from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from highway_topo_poc.modules.t02_ground_seg_qc.batch_multilayer_clean_and_classify import main


def _write_las(path: Path, xyz: np.ndarray) -> None:
    import laspy

    hdr = laspy.LasHeader(point_format=3, version="1.2")
    hdr.x_scale = 0.01
    hdr.y_scale = 0.01
    hdr.z_scale = 0.01

    las = laspy.LasData(hdr)
    las.x = np.asarray(xyz[:, 0], dtype=np.float64)
    las.y = np.asarray(xyz[:, 1], dtype=np.float64)
    las.z = np.asarray(xyz[:, 2], dtype=np.float64)
    las.intensity = np.full((xyz.shape[0],), 1000, dtype=np.uint16)
    las.return_number = np.ones((xyz.shape[0],), dtype=np.uint8)
    las.number_of_returns = np.ones((xyz.shape[0],), dtype=np.uint8)
    las.classification = np.ones((xyz.shape[0],), dtype=np.uint8)
    las.write(str(path))


def _write_geojson(path: Path, coords: list[list[float]]) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {},
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _build_points() -> tuple[np.ndarray, np.ndarray]:
    xs = np.arange(0.0, 40.0, 1.0)
    ys = np.arange(0.0, 40.0, 1.0)
    xx, yy = np.meshgrid(xs, ys)
    ground = np.column_stack([xx.ravel(), yy.ravel(), np.zeros((xx.size,), dtype=np.float64)])

    hx = np.arange(10.0, 30.0, 1.0)
    hy = np.arange(10.0, 30.0, 1.0)
    hxx, hyy = np.meshgrid(hx, hy)
    high = np.column_stack([hxx.ravel(), hyy.ravel(), np.full((hxx.size,), 10.0, dtype=np.float64)])

    side_z = np.arange(0.0, 7.0, 1.0, dtype=np.float64)
    side = np.column_stack(
        [
            np.full((side_z.size,), 12.25, dtype=np.float64),
            np.full((side_z.size,), 15.25, dtype=np.float64),
            side_z,
        ]
    )

    points = np.vstack([ground, high, side]).astype(np.float64)
    return points, side


def test_multilayer_clean_keeps_roadside_and_tags_removed(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    patch_dir = data_root / "patchA"
    cloud_path = patch_dir / "PointCloud" / "merged.las"
    cloud_path.parent.mkdir(parents=True, exist_ok=True)

    points, side = _build_points()
    _write_las(cloud_path, points)

    traj1 = [[float(x), 15.0, 0.0] for x in np.arange(0.0, 40.0, 1.0)]
    traj2 = [[float(x), 25.0, 0.0] for x in np.arange(0.0, 40.0, 1.0)]
    _write_geojson(patch_dir / "Traj" / "0000" / "raw_dat_pose.geojson", traj1)
    _write_geojson(patch_dir / "Traj" / "0001" / "raw_dat_pose.geojson", traj2)

    out_root = tmp_path / "out"
    run_id = "ut_multilayer"
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
            "256",
            "--ref_grid_m",
            "5.0",
            "--ground_grid_m",
            "1.0",
            "--ground_above_margin_m",
            "0.08",
            "--layer_band_m",
            "2.0",
            "--suspect_far_ratio_gate",
            "0.05",
            "--suspect_min_far_points",
            "10",
            "--min_total_points_per_cell",
            "40",
            "--min_cluster_cells",
            "1",
            "--out_format",
            "las",
            "--write_full_tagged",
            "true",
            "--verify",
            "true",
        ]
    )
    assert exit_code == 0

    patch_out = out_root / run_id / "multilayer_clean" / "patchA"
    cleaned_path = patch_out / "merged_cleaned_classified.las"
    full_path = patch_out / "merged_full_tagged.las"
    stats_path = patch_out / "patch_stats.json"

    assert cleaned_path.is_file()
    assert full_path.is_file()
    assert stats_path.is_file()

    import laspy

    cleaned = laspy.read(str(cleaned_path))
    full = laspy.read(str(full_path))
    in_cloud = laspy.read(str(cloud_path))

    in_z = np.asarray(in_cloud.z, dtype=np.float64)
    cleaned_z = np.asarray(cleaned.z, dtype=np.float64)
    in_high = int(np.count_nonzero(in_z > 8.0))
    cleaned_high = int(np.count_nonzero(cleaned_z > 8.0))
    assert cleaned_high < in_high

    cx = np.asarray(cleaned.x, dtype=np.float64)
    cy = np.asarray(cleaned.y, dtype=np.float64)
    cz = np.asarray(cleaned.z, dtype=np.float64)
    side_mask = np.isclose(cx, 12.25, atol=0.01) & np.isclose(cy, 15.25, atol=0.01)
    side_cleaned = np.sort(cz[side_mask])
    assert side_cleaned.size >= side.shape[0]
    for expect_z in side[:, 2].tolist():
        assert np.any(np.isclose(side_cleaned, expect_z, atol=0.01))

    full_cls = np.asarray(full.classification, dtype=np.uint8)
    kept_cls = full_cls[full_cls != 12]
    assert int(np.count_nonzero(full_cls == 12)) > 0
    assert np.all(np.isin(kept_cls, np.array([1, 2], dtype=np.uint8)))
    assert int(np.count_nonzero(kept_cls == 2)) > 0

    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    assert int(np.count_nonzero(full_cls == 12)) == int(stats["class12_count"])
