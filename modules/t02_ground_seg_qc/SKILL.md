# t02_ground_seg_qc - SKILL

## 地面分类路径（优先级）
1. `LAS/LAZ classification`
- 若存在 `classification` 字段，且 `class==2` 点数达到 `min_las_ground_points`，直接作为 ground。
- 记录：`ground_source=las_classification`。

2. `DEM band fallback`
- 网格 DEM：cell 内 `z` 取 `dem_quantile_q`。
- 每点 `dz = z - ground_z_cell`。
- 保留条件：`-below_margin_m <= dz <= above_margin_m`。
- 导出策略：
  - 每 cell 最多 `max_points_per_cell_export`，按 `|dz|` + 索引稳定排序。
  - 全局最多 `max_export_points`。
- 记录：`ground_source=dem_band`。

## 横截（cross-track）QC
- 轨迹切向：由 `i-1` 与 `i+1` 差分得 heading。
- 横截向量：`cross=[-heading_y, heading_x]`。
- 邻域筛选：
  - 先按 cell 粗筛，半径 `xsec_radius_m`
  - 再做窗口：
    - `abs(forward) <= along_window_m`
    - `abs(cross) <= cross_half_width_m`
- 将横截范围分 `xsec_bin_count` 个 bin：
  - 每 bin 地面 `z` 取中位数
  - `coverage_i = valid_bins / xsec_bin_count`
- 线性拟合：`z = a*cross + b`
  - 样本残差指标：`xsec_abs_res_p90_i`
- 样本异常：
  - `coverage_i < xsec_coverage_gate_per_sample` 或
  - `xsec_abs_res_p90_i > xsec_residual_gate_per_sample`

## 聚合指标与门禁
- traj-clearance：`coverage`, `outlier_ratio`, `p99`
- ground sanity：`ground_ratio`, `ground_count`
- xsec：`xsec_valid_ratio`, `xsec_p99_abs_res_m`, `xsec_anomaly_ratio`
- 总门禁：
  - `traj_gates && ground_gates && xsec_gates`

## auto_tune
- 默认开启：`--auto_tune true`
- 先跑默认参数；失败则参数搜索，遇到首个 PASS 立即停止。
- 若无 PASS：选择 penalty 最小配置落盘并返回 fail 结论。
- 落盘：`chosen_config.json`, `tune_log.jsonl`

## 默认参数（关键）
- `grid_size_m=1.0`
- `dem_quantile_q=0.10`
- `above_margin_m=0.08`
- `below_margin_m=0.20`
- `threshold_m=0.25`
- `xsec_bin_count=21`
- `along_window_m=1.0`
- `cross_half_width_m=6.0`
- `xsec_p99_abs_res_gate_m=0.15`
