# t02_ground_seg_qc - INTERFACE_CONTRACT

## Python API

### `run_patch(...)`
```python
run_patch(
    data_root: str | Path,
    patch: str = "auto",
    run_id: str = "auto",
    out_root: str | Path = "outputs/_work/t02_ground_seg_qc",
    config: Config | None = None,
    auto_tune: bool | None = None,
) -> dict
```

- `patch=auto`：自动选择首个可加载 patch（同时能读取 traj + 点云）。
- `run_id=auto`：按 `YYYYMMDD_HHMMSS` 生成。
- `auto_tune=True` 时，失败会进行参数搜索。

返回最小字段：
- `run_id`, `patch_id`, `patch_dir`, `traj_path`, `points_path`, `output_dir`
- `metrics`
- `intervals`（traj-clearance）
- `xsec_intervals`
- `ground_stats`
- `chosen_config`
- `tune_log`
- `summary`

### `run_batch(...)`（ground_cache）
```python
run_batch(
    data_root: str | Path,
    out_root: str | Path = "outputs/_work/t02_ground_seg_qc",
    run_id: str = "auto",
    resume: bool = True,
    workers: int = 1,
    chunk_points: int = 2_000_000,
    export_classified_laz: bool = False,
    grid_size_m: float = 1.0,
    above_margin_m: float = 0.08,
) -> dict
```

- 对 `data_root` 下可发现 patch 做全量地面标签缓存。
- `chunk_points` 仅用于分块，不影响全点输出长度。
- 缓存产物为后续模块可选输入，不改变其它模块输入输出契约。

### `run_export(...)`（classified_cloud）
```python
run_export(
    in_manifest: str | Path,
    out_root: str | Path = "outputs/_work/t02_ground_seg_qc",
    run_id: str = "auto",
    resume: bool = True,
    workers: int = 1,
    chunk_points: int = 2_000_000,
    ground_class: int = 2,
    non_ground_class: int = 1,
    out_format: str = "laz",
    verify: bool = True,
) -> dict
```

- 从 `ground_cache_manifest.jsonl` 读取 `points_path + label_path`，导出完整 classified 点云副本。
- 仅改 `classification` 字段，其它字段保持不变。
- `.laz` 写出失败时自动 fallback 到 `.las` 并记录原因。

## CLI

```bash
python -m highway_topo_poc.modules.t02_ground_seg_qc.run \
  --data_root data/synth_local \
  --patch auto \
  --run_id auto \
  --out_root outputs/_work/t02_ground_seg_qc \
  --auto_tune true
```

```bash
python -m highway_topo_poc.modules.t02_ground_seg_qc.batch_ground_cache \
  --data_root data/synth_local \
  --out_root outputs/_work/t02_ground_seg_qc \
  --run_id auto \
  --resume true \
  --workers 1 \
  --chunk_points 2000000 \
  --export_classified_laz false
```

```bash
python -m highway_topo_poc.modules.t02_ground_seg_qc.export_classified_cloud \
  --in_manifest outputs/_work/t02_ground_seg_qc/<run_id>/ground_cache_manifest.jsonl \
  --out_root outputs/_work/t02_ground_seg_qc \
  --run_id auto \
  --resume true \
  --workers 1 \
  --chunk_points 2000000 \
  --ground_class 2 \
  --non_ground_class 1 \
  --out_format laz \
  --verify true
```

参数：
- `--data_root`
- `--patch`
- `--run_id`
- `--out_root`
- `--auto_tune` (`true/false`)
- `--resume` (`true/false`)
- `--workers`
- `--chunk_points`
- `--export_classified_laz` (`true/false`)
- `--grid_size_m`
- `--above_margin_m`
- `--in_manifest`
- `--ground_class`
- `--non_ground_class`
- `--out_format` (`laz/las`)
- `--verify` (`true/false`)

退出码：
- `0`：`overall_pass=True`
- `2`：运行成功但 `overall_pass=False`
- `1`：运行异常

`batch_ground_cache` 退出码：
- `0`：全部 patch `overall_pass=True`
- `2`：批处理成功但存在 fail patch（仍会输出 best-effort 工件）
- `1`：运行异常

`export_classified_cloud` 退出码：
- `0`：全部 patch 导出与校验通过
- `2`：导出流程完成但存在 fail patch
- `1`：运行异常

## 输出目录结构

```text
outputs/_work/t02_ground_seg_qc/<run_id>/<patch_id>/
  metrics.json                 # required
  summary.txt                  # required
  intervals.json               # required (traj-clearance)
  xsec_intervals.json          # required
  ground_idx.npy               # required
  ground_points.npy            # required
  ground_stats.json            # required
  chosen_config.json           # required
  tune_log.jsonl               # required
  xsec_series.npz              # optional
  series.npz                   # optional
```

```text
outputs/_work/t02_ground_seg_qc/<run_id>/
  ground_cache_manifest.jsonl  # required
  ground_cache_summary.json    # required
  failed_patches.txt           # optional (exists when fail_patches>0)
  ground_cache/
    <patch_key>/
      ground_label.npy         # required, uint8, shape=(N,), full-size
      ground_stats.json        # required
      ground_idx.npy           # recommended
      classified.laz/.las      # optional
```

```text
outputs/_work/t02_ground_seg_qc/<run_id>/
  classified_manifest.jsonl    # required
  classified_summary.json      # required
  failed_patches.txt           # optional (exists when fail_patches>0)
  classified_cloud/
    <patch_key>/
      merged_classified.laz    # preferred
      merged_classified.las    # fallback when laz backend unavailable
```

## ground_cache_manifest.jsonl（每行字段）
- `patch_key`
- `points_path`
- `label_path`
- `stats_path`
- `n_points`
- `n_ground`
- `ratio`
- `pass_fail` (`pass`/`fail`)
- `overall_pass`
- `reason`
- `output_dir`

## classified_manifest.jsonl（每行字段）
- `patch_key`
- `points_path`
- `label_path`
- `out_path`
- `out_format`
- `n_points`
- `n_ground`
- `output_n_points`
- `output_n_ground`
- `ground_class`
- `pass_fail` (`pass`/`fail`)
- `overall_pass`
- `reason`
- `output_dir`

## metrics.json（关键字段）
- traj-clearance：`coverage`, `outlier_ratio`, `p50/p90/p99`
- ground：`ground_source`, `ground_count`, `ground_ratio`, `ground_coverage`
- xsec：`xsec_valid_ratio`, `xsec_p50/p90/p99_abs_res_m`, `xsec_anomaly_ratio`
- gates：
  - `traj_gates`
  - `ground_gates`
  - `xsec_gates`
  - `overall_pass`

## xsec_intervals.json（关键字段）
- `bin_count`
- `intervals`（Top-K）
- 单 interval：
  - `start_bin`, `end_bin`, `n_bins`
  - `start_idx`, `end_idx`
  - `max_abs_res_p90_m`
  - `max_anomaly_ratio_bin`
  - `min_support_count`
  - `score`

## 兼容性说明
- 仍保留 `intervals.json`（traj-clearance）以兼容旧消费者。
- 新增 `xsec_intervals.json` 与 ground 工件为本阶段 required。
- 新增 ground_cache 为旁路缓存能力（optional downstream input），不覆盖原始点云，不改其它模块契约。
- 新增 classified_cloud 为旁路导出能力（optional downstream artifact），不覆盖原始输入点云。
