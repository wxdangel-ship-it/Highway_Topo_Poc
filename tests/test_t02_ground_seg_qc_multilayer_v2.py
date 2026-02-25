from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from highway_topo_poc.modules.t02_ground_seg_qc.batch_multilayer_clean_and_classify import main
from highway_topo_poc.modules.t02_ground_seg_qc.corridor import pack_cells
from highway_topo_poc.modules.t02_ground_seg_qc.crs_mercator import lonlat_to_3857
from highway_topo_poc.modules.t02_ground_seg_qc.road_z_degraded import choose_road_z_by_traj_direction
from highway_topo_poc.modules.t02_ground_seg_qc.traj_z_mode import check_traj_z


def _write_las(path: Path, xyz: np.ndarray, *, lonlat_scale: bool = False) -> None:
    import laspy

    hdr = laspy.LasHeader(point_format=3, version="1.2")
    if lonlat_scale:
        hdr.x_scale = 1e-7
        hdr.y_scale = 1e-7
    else:
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


def test_crs_lonlat_to_3857_scale() -> None:
    x, y = lonlat_to_3857(114.0, 22.0)
    assert abs(x) > 1_000_000
    assert abs(y) > 1_000_000


def test_traj_z_check_auto_modes(tmp_path: Path) -> None:
    p0 = tmp_path / "z0.geojson"
    p1 = tmp_path / "zv.geojson"
    _write_geojson(p0, [[114.0, 22.0, 0.0], [114.0001, 22.0001, 0.0], [114.0002, 22.0002, 0.0]])
    _write_geojson(p1, [[114.0, 22.0, 0.0], [114.0001, 22.0001, 1.0], [114.0002, 22.0002, 2.0]])

    z0 = check_traj_z([p0], nonzero_ratio_gate=0.01, z_std_gate=0.05, sample_max_points_per_file=1000)
    zv = check_traj_z([p1], nonzero_ratio_gate=0.01, z_std_gate=0.05, sample_max_points_per_file=1000)
    assert bool(z0["is_degraded"]) is True
    assert bool(zv["is_degraded"]) is False


def test_degraded_dp_prefers_continuous_layer() -> None:
    ref_grid_m = 5.0
    x0 = 0.0
    y0 = 0.0
    xs = np.arange(0, 8, dtype=np.int64)
    ys = np.zeros_like(xs)
    keys = pack_cells(xs, ys)

    cell_peaks: dict[int, dict[str, float | int]] = {}
    for i, key in enumerate(keys.tolist()):
        if i == 0:
            cell_peaks[int(key)] = {
                "peak0": 0.0,
                "peak1": np.nan,
                "support0": 80,
                "support1": 0,
                "peak_sep": 0.0,
                "total_points": 80,
            }
        else:
            cell_peaks[int(key)] = {
                "peak0": 0.0,
                "peak1": 10.0,
                "support0": 70,
                "support1": 70,
                "peak_sep": 10.0,
                "total_points": 140,
            }

    traj = np.column_stack(
        [
            np.asarray([x0 + (i + 0.5) * ref_grid_m for i in range(8)], dtype=np.float64),
            np.asarray([y0 + 0.5 * ref_grid_m] * 8, dtype=np.float64),
        ]
    )
    road_z, report = choose_road_z_by_traj_direction(
        [traj],
        cell_peaks,
        ref_grid_m=ref_grid_m,
        x0=x0,
        y0=y0,
        smooth_lambda=0.8,
    )
    assert int(report["used_traj_count"]) == 1
    for key in keys.tolist():
        assert abs(float(road_z[int(key)])) < 1.0


def test_multilayer_v2_overlap_and_export_3857(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    patch_dir = data_root / "patch_lonlat"
    cloud_path = patch_dir / "PointCloud" / "merged.las"
    cloud_path.parent.mkdir(parents=True, exist_ok=True)

    lons = np.arange(114.0000, 114.00055, 0.00005, dtype=np.float64)
    lats = np.arange(22.0000, 22.00055, 0.00005, dtype=np.float64)
    llon, llat = np.meshgrid(lons, lats)
    ground = np.column_stack([llon.ravel(), llat.ravel(), np.zeros((llon.size,), dtype=np.float64)])
    high = np.column_stack([llon.ravel(), llat.ravel(), np.full((llon.size,), 10.0, dtype=np.float64)])

    pole_lon = 114.00025
    pole_lat = 22.00025
    pole_z = np.arange(0.0, 7.0, 1.0, dtype=np.float64)
    poles = np.column_stack(
        [
            np.full((pole_z.size,), pole_lon, dtype=np.float64),
            np.full((pole_z.size,), pole_lat, dtype=np.float64),
            pole_z,
        ]
    )
    points = np.vstack([ground, high, poles]).astype(np.float64)
    _write_las(cloud_path, points, lonlat_scale=True)

    traj1 = [[float(lon), 22.00020, 0.0] for lon in np.linspace(114.0000, 114.0005, 24)]
    traj2 = [[float(lon), 22.00035, 0.0] for lon in np.linspace(114.0000, 114.0005, 24)]
    _write_geojson(patch_dir / "Traj" / "0000" / "raw_dat_pose.geojson", traj1)
    _write_geojson(patch_dir / "Traj" / "0001" / "raw_dat_pose.geojson", traj2)

    out_root = tmp_path / "out"
    run_id = "ut_multilayer_v2"
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
            "8.0",
            "--corridor_radius_m",
            "25",
            "--ground_band_m",
            "0.3",
            "--traj_z_mode",
            "auto",
            "--z_bin_m",
            "0.2",
            "--min_total_points_per_cell",
            "12",
            "--overlap_min_support_points",
            "5",
            "--overlap_min_support_ratio",
            "0.2",
            "--min_cluster_cells",
            "1",
            "--out_epsg",
            "3857",
            "--out_format",
            "las",
            "--write_full_tagged",
            "true",
            "--verify",
            "true",
        ]
    )
    assert exit_code == 0

    patch_out = out_root / run_id / "multilayer_clean" / "patch_lonlat"
    cleaned_path = patch_out / "merged_cleaned_classified_3857.las"
    full_path = patch_out / "merged_full_tagged_3857.las"
    stats_path = patch_out / "patch_stats.json"
    assert cleaned_path.is_file()
    assert full_path.is_file()
    assert stats_path.is_file()

    import laspy

    full = laspy.read(str(full_path))
    cleaned = laspy.read(str(cleaned_path))
    cls_full = np.asarray(full.classification, dtype=np.uint8)
    cls_clean = np.asarray(cleaned.classification, dtype=np.uint8)
    z_full = np.asarray(full.z, dtype=np.float64)

    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    assert str(stats["traj_z_mode_used"]) == "degraded"
    assert bool(stats["lonlat_detect"]) is True
    assert int(full.header.point_count) == int(stats["n_in"])
    assert int(cleaned.header.point_count) == int(stats["n_kept"])
    assert int(stats["n_in"]) - int(stats["n_kept"]) == int(stats["class12_count"])
    assert np.all(np.isin(cls_clean, np.array([1, 2], dtype=np.uint8)))
    assert int(stats["class2_count"]) > 0

    bbox = np.asarray([*full.header.mins[:2], *full.header.maxs[:2]], dtype=np.float64)
    assert float(np.max(np.abs(bbox))) > 100000.0
    assert not (abs(float(full.header.maxs[0])) <= 180.0 and abs(float(full.header.maxs[1])) <= 90.0)

    pole_x, pole_y = lonlat_to_3857(pole_lon, pole_lat)
    x_full = np.asarray(full.x, dtype=np.float64)
    y_full = np.asarray(full.y, dtype=np.float64)
    pole_mask = (
        np.isclose(x_full, pole_x, atol=0.05)
        & np.isclose(y_full, pole_y, atol=0.05)
        & (z_full <= 6.1)
    )
    assert int(np.count_nonzero(pole_mask)) >= 5
    pole_removed = int(np.count_nonzero(cls_full[pole_mask] == 12))
    assert pole_removed <= 1

    high_mask = z_full > 8.0
    assert int(np.count_nonzero(cls_full[high_mask] == 12)) >= int(np.count_nonzero(cls_full == 12) * 0.8)
