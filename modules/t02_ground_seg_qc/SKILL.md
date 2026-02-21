# t02_ground_seg_qc - SKILL

## 目标
- 基于点云 `z` 构建地面参考 `ground_z`，对轨迹高度 `traj_z` 做残差 QC。
- 输出 `metrics + intervals(Top-K) + summary`，满足文本化回传和复盘。

## 默认参数（MVP）
- `grid_size_m=1.0`
- `dem_quantile_q=0.10`
- `min_points_per_cell=8`
- `neighbor_cell_radius=2`
- `neighbor_min_points=32`
- `baseline_mode=median`
- `threshold_m=0.25`
- `coverage_gate=0.70`
- `outlier_gate=0.20`
- `p99_gate_m=0.40`
- `bin_count=64`
- `bin_outlier_gate=0.30`
- `min_interval_bins=1`
- `top_k=5`

## 算法口径
1. `ground_z`：先按 `(floor((x-x0)/grid), floor((y-y0)/grid))` 建格网，cell 内取 `dem_quantile_q`。
2. 轨迹点查值：先取同 cell；缺失时在 `neighbor_cell_radius` 邻域汇总点，满足 `neighbor_min_points` 再取分位。
3. QC：
- `z_diff = traj_z - ground_z`
- `baseline = median(z_diff_valid)`
- `residual = z_diff - baseline`
- `abs_res = abs(residual)`
- `metrics = p50/p90/p99 + coverage + outlier_ratio + bias + baseline + gates`
4. 区间：将索引 `[0,n)` 等分成 `bin_count`，bin 异常条件：
- `mean_abs_res_m > threshold_m` 或 `outlier_ratio_bin > bin_outlier_gate`
- 合并连续异常 bin，过滤 `n_bins < min_interval_bins`
- `score = max(mean_abs_res_m) * (1 + max(outlier_ratio_bin))`
- 取 Top-K。

## 调参建议
- 地面稀疏时：提高 `neighbor_cell_radius` 或降低 `neighbor_min_points`。
- 噪声大但覆盖稳定时：适当提高 `threshold_m`，并观察 `p99` 与 `outlier_ratio`。
- 区间碎片化时：提高 `min_interval_bins` 或降低 `bin_count`。
