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

### `run_batch(...)`（multilayer_clean_and_classify）
```python
run_batch(
    data_root: str | Path,
    out_root: str | Path = "outputs/_work/t02_ground_seg_qc",
    run_id: str = "auto",
    resume: bool = True,
    workers: int = 1,
    chunk_points: int = 2_000_000,
    ref_grid_m: float = 5.0,
    ground_grid_m: float = 1.0,
    ground_above_margin_m: float = 0.08,
    layer_band_m: float = 2.0,
    suspect_far_ratio_gate: float = 0.03,
    suspect_min_far_points: int = 2000,
    min_total_points_per_cell: int = 5000,
    min_cluster_cells: int = 200,
    out_format: str = "laz",
    write_full_tagged: bool = True,
    verify: bool = True,
) -> dict
```

- 入口模块：`highway_topo_poc.modules.t02_ground_seg_qc.batch_multilayer_clean_and_classify`。
- 参考面由同 patch 全部 Traj 合并构建，Traj 未覆盖 cell 默认不删。
- 删除仅在“异层密集连通簇”内触发，且必须落在异层面带宽 `layer_band_m` 内。
- 输出两份点云：`cleaned_classified`（删点后）与 `full_tagged`（全点审计，removed=`class 12`）。

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

```bash
python -m highway_topo_poc.modules.t02_ground_seg_qc.batch_multilayer_clean_and_classify \
  --data_root data/synth_local \
  --out_root outputs/_work/t02_ground_seg_qc \
  --run_id auto \
  --resume true \
  --workers 1 \
  --chunk_points 2000000 \
  --ref_grid_m 5.0 \
  --ground_grid_m 1.0 \
  --ground_above_margin_m 0.08 \
  --layer_band_m 2.0 \
  --suspect_far_ratio_gate 0.03 \
  --suspect_min_far_points 2000 \
  --min_total_points_per_cell 5000 \
  --min_cluster_cells 200 \
  --out_format laz \
  --write_full_tagged true \
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
- `--ref_grid_m`
- `--ground_grid_m`
- `--ground_above_margin_m`
- `--layer_band_m`
- `--suspect_far_ratio_gate`
- `--suspect_min_far_points`
- `--min_total_points_per_cell`
- `--min_cluster_cells`
- `--write_full_tagged` (`true/false`)

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

`batch_multilayer_clean_and_classify` 退出码：
- `0`：全部 patch 清理/分类/校验通过
- `2`：批处理完成但存在 fail patch
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

```text
outputs/_work/t02_ground_seg_qc/<run_id>/
  multilayer_manifest.jsonl    # required
  multilayer_summary.json      # required
  multilayer_clean/
    <patch_key>/
      merged_cleaned_classified.laz/.las  # required
      merged_full_tagged.laz/.las         # optional (write_full_tagged=true)
      patch_stats.json                    # required
      ref_surface_stats.json              # required
      overlap_cells_report.json           # required
      clean_pass2_stats.json              # required
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

## multilayer_manifest.jsonl（每行字段）
- `patch_key`
- `patch_dir`
- `points_path`
- `traj_count`
- `out_cleaned_path`
- `out_full_tagged_path`
- `out_format`
- `n_in`
- `n_kept`
- `n_removed`
- `removed_ratio`
- `pass_fail` (`pass`/`fail`)
- `overall_pass`
- `reason`
- `output_dir`

## classification 约定（multilayer）
- `2`: ground
- `1`: non-ground
- `12`: overlap_removed（仅 `full_tagged`，`cleaned` 中不会出现 `12`，因为 removed 点已剔除）

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

## 示例（Example）
在 repo root 执行：

```bash
RUN_ID="$(date +%Y%m%d_%H%M%S)"
OUT_ROOT="outputs/_work/t02_ground_seg_qc/${RUN_ID}"
python -m highway_topo_poc.modules.t02_ground_seg_qc.run \
  --data_root data/synth_local \
  --patch auto \
  --run_id smoke_min \
  --out_root "${OUT_ROOT}" \
  --auto_tune true
```

## 验收（Accept）
- 命令退出码为 `0` 或 `2`（`2` 表示流程完成但 `overall_pass=False`）
- `${OUT_ROOT}/smoke_min/` 下存在 patch 输出目录，且含 `metrics.json` 与 `summary.txt`
- 若输出 `xsec_intervals.json`，文件需可解析且包含 `intervals` 字段
