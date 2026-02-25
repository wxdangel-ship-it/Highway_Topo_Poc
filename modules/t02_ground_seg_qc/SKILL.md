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

## multilayer_clean_and_classify v2（EPSG:3857 + TrajZ双方案 + 多层簇护栏）
- 输入：patch 点云 `merged.laz/las` + 同 patch 所有 Traj（优先 `Traj/*/raw_dat_pose.geojson`）。
- 坐标统一：点云/轨迹先统一到 EPSG:3857，再做网格/距离/方向计算；输出点云也为 EPSG:3857。
- `traj_z_mode`：
  - `auto`（默认）：`nonzero_ratio<0.01 且 z_std<0.05` 判为退化；
  - `force_traj_z`：强制 TrajZ 正常方案（`road_z=traj_z median`）；
  - `force_degraded`：强制退化方案（corridor 内点云双峰 + 轨迹方向 2-state DP）。
- 走廊与地面定义：
  - corridor：由 Traj XY + `corridor_radius_m` 生成；
  - ground：corridor 内 `|z - road_z(cell)| <= ground_band_m`（默认 `0.3m`）；
  - corridor 外默认非地面，且永不标记 overlap `12`。
- overlap 删除护栏（必须同时满足）：
  - cell 为“疑似叠层密集平面”候选（`sep/support/ratio`门槛，含密度自适应缩放）；
  - 候选 cell 需通过 8 邻域连通簇最小规模过滤；
  - 点需贴近干扰层 band（`layer_band_m`）才标 `12`；
  - 稀疏路侧高物体（杆件/标志牌）应保留。
- 保留口径：
  - Traj 未覆盖 cell 默认 `keep`（不删）；
  - corridor 外默认 `keep`；
  - 稀疏路侧高物体通常不会形成密集簇，且不贴近干扰层 band 时不会删。
- 输出：
  - `merged_cleaned_classified_3857.<laz|las>`：仅 kept 点，`class=2/1`
  - `merged_full_tagged_3857.<laz|las>`：全点，removed 点 `class=12`
  - 伴随统计：`patch_stats.json`、`ref_surface_stats.json`、`overlap_cells_report.json`、`road_z_surface.csv`、`road_z_variation_report.json`

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
