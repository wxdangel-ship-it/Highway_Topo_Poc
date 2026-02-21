# t02_ground_seg_qc - INTERFACE_CONTRACT

## 1. Python API

### `run_patch(...)`
```python
run_patch(
    data_root: str | Path,
    patch: str = "auto",
    run_id: str = "auto",
    out_root: str | Path = "outputs/_work/t02_ground_seg_qc",
    config: Config | None = None,
) -> dict
```

- `patch=auto`：自动选择第一个可解析 patch。
- `run_id=auto`：按本地时间戳 `YYYYMMDD_HHMMSS` 生成。
- 返回字段（最小）：
  - `run_id`, `patch_id`, `patch_dir`, `traj_path`, `points_path`, `output_dir`
  - `metrics`（见第 3 节）
  - `intervals`（见第 4 节）
  - `summary`（字符串）

## 2. CLI

```bash
python -m highway_topo_poc.modules.t02_ground_seg_qc.run \
  --data_root data/synth_local \
  --patch auto \
  --run_id auto \
  --out_root outputs/_work/t02_ground_seg_qc
```

参数：
- `--data_root`：patch 根目录
- `--patch`：`auto` 或 patch 目录路径
- `--run_id`：`auto` 或自定义 run id
- `--out_root`：固定建议 `outputs/_work/t02_ground_seg_qc`

CLI 结束时会打印：
- `summary.txt` 前约 40 行
- 输出目录路径

## 3. metrics.json key（最小冻结）
- `p50`, `p90`, `p99`
- `coverage`
- `outlier_ratio`
- `bias`
- `baseline`
- `threshold`
- `n_total`, `n_valid`
- `gates`:
  - `coverage_gate`（bool）
  - `outlier_gate`（bool）
  - `p99_gate_m`（bool）
  - `overall_pass`（bool）

## 4. intervals.json key（最小冻结）
- `bin_count`
- `threshold_m`
- `bin_outlier_gate`
- `intervals`（Top-K，按 `score` 降序）
- 单个 interval key：
  - `start_bin`, `end_bin`, `n_bins`
  - `start_idx`, `end_idx`
  - `max_mean_abs_res_m`, `max_outlier_ratio_bin`
  - `score`

## 5. 输出目录结构

```text
outputs/_work/t02_ground_seg_qc/<run_id>/<patch_id>/
  metrics.json
  intervals.json
  summary.txt
  series.npz
```

- 允许 `overall_pass=FAIL`，但不阻止产物落盘。
