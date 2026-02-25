# t02_ground_seg_qc - SKILL

## ground_cache（全量标签缓存）
- 目的：为后续模块提供可复用地面标签缓存（可选输入），不改变其它模块契约。
- 关键口径：`ground_label.npy` 必须是“全点”标签，禁止抽样、禁止截断、禁止 cap。
- 分块策略：允许 `chunk_points` 做内存/IO 分块，但输出长度必须等于点云总点数。

## classified_cloud（完整点云导出）
- 输入：`ground_cache_manifest.jsonl`（复用已生成 `ground_label.npy`，不重复分类）。
- 输出：完整复制点云 `merged_classified.<laz|las>`，仅改 `classification` 字段。
- 分类映射（固定）：
  - `ground_class=2`（LAS Ground）
  - `non_ground_class=1`（LAS Unclassified）
- 校验口径（verify）：
  - 输出点数必须等于输入点数；
  - 输出 `class==2` 点数必须等于 `n_ground`。
- LAZ fallback：
  - 若 `.laz` 写出因压缩 backend 失败，自动回退 `.las`；
  - 在 `classified_manifest.jsonl` 与 `classified_summary.json` 记录 fallback 原因与计数。

## multilayer_clean_and_classify（Traj 合并参考面 + 多层簇护栏）
- 输入：patch 点云 `merged.laz/las` + 同 patch 所有 Traj（优先 `Traj/*/raw_dat_pose.geojson`）。
- 参考面构建：
  - 以点云 header `minX/minY` 为网格原点；
  - `ref_grid_m` cell 内 `ref_z = median(traj_z)`；
  - `spread = robust_sigma = 1.4826*MAD`（样本过少时 `spread=0.1`）。
- 自适应非对称阈值（每 cell）：
  - `dz_up_keep = clamp(dz_up_base_m + dz_up_k*spread, dz_up_base_m, dz_up_max_m)`；
  - `dz_down_keep = clamp(dz_down_base_m + dz_down_k*spread, dz_down_min_m, dz_down_max_m)`。
- 检测阈值（Pass1，较强远离判定）：
  - `dz_up_detect = max(detect_up_min_m, dz_up_keep + detect_up_extra_m)`；
  - `dz_down_detect = max(detect_down_min_m, dz_down_keep + detect_down_extra_m)`。
- 删除护栏（必须同时满足）：
  - cell 属于“远离 ref_z 的密集候选”且在 8 邻域大连通簇内；
  - 点落在异层面带宽内（`layer_band_m`）；
  - 高层：`dz > dz_up_keep && abs(dz - mean_dz_high)<=layer_band_m`
  - 低层：`dz < -dz_down_keep && abs(dz - mean_dz_low)<=layer_band_m`
- 保留口径：
  - Traj 未覆盖 cell 默认 `keep`（不删）；
  - `spread > traj_spread_cap_m` 的 ref cell 视为不可靠，默认 `keep`；
  - 稀疏路侧高物体通常不会形成密集簇，且若不贴近异层面也不会删。
- 输出：
  - `merged_cleaned_classified.<laz|las>`：仅 kept 点，`class=2/1`
  - `merged_full_tagged.<laz|las>`：全点，removed 点 `class=12`
  - 伴随统计：`patch_stats.json`、`ref_surface_stats.json`、`overlap_cells_report.json`、`clean_pass2_stats.json`

## 地面分类路径（优先级）
1. `las_classification`
- 若 LAS/LAZ 存在 `classification` 且 `class==2` 非空，则直接按 `class==2` 生成全点标签。
- 记录：`ground_source=las_classification`。

2. `grid_min_band`
- 计算网格 `cell` 的 `min_z`（可两遍分块，不限制点数）。
- 判定规则：`ground = (z <= min_z_cell + above_margin_m)`。
- 记录：`ground_source=grid_min_band`。

## 参数含义与建议范围（ground_cache）
- `grid_size_m`：网格边长，默认 `1.0`，建议 `0.5 ~ 2.0`。
- `above_margin_m`：离地容差，默认 `0.08`，建议 `0.03 ~ 0.20`。
- `chunk_points`：单次分块点数，默认 `2_000_000`，仅影响内存/IO，不影响全量输出。
- `workers`：默认 `1`（IO 稳定优先，可按机器能力增大）。
- `export_classified_laz`：默认 `false`，开启后可导出带 classification 的副本。

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
- `dem_quantile_q=0.10`（traj/xsec 主流程）
- `above_margin_m=0.08`
- `below_margin_m=0.20`
- `threshold_m=0.25`
- `xsec_bin_count=21`
- `along_window_m=1.0`
- `cross_half_width_m=6.0`
- `xsec_p99_abs_res_gate_m=0.15`
