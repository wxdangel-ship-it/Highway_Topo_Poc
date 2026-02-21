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

## CLI

```bash
python -m highway_topo_poc.modules.t02_ground_seg_qc.run \
  --data_root data/synth_local \
  --patch auto \
  --run_id auto \
  --out_root outputs/_work/t02_ground_seg_qc \
  --auto_tune true
```

参数：
- `--data_root`
- `--patch`
- `--run_id`
- `--out_root`
- `--auto_tune` (`true/false`)

退出码：
- `0`：`overall_pass=True`
- `2`：运行成功但 `overall_pass=False`
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
