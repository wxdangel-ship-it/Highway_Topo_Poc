# T05_AUDIT_REPORT

## Executive Summary
- 审计基线代码版本：`96e0bb7738f6e6e626a14288d15ad450206fb057`（`main`）。
- Q1 结论：t05 里存在两套“道路面”语义：`点云有效面`用于中心线偏移估计（几何生成），`traj_surface`用于通道门禁（in_ratio + 端点在面内）。
- Q2 结论（代码根因）：`traj_surface` 由“src/dst 横截中心连线”做 station 轴并按窄切片统计；当轴与真实车道不一致或轨迹覆盖稀疏时，surface 只在局部成形，表现为“只生成一小段”。
- 代码级别不存在“Road 用 cluster A，gate 用 cluster B”的直接错配路径：候选 Road_k 的几何与 gate 都复用同一个 `support_k + traj_surface_hint_k`。
- 但仍可出现“Road 不落入看起来像道路面的 surface”：更常见是“同一 cluster 内 surface 轴定义偏离（直连轴）+ 切片阈值过严 + gore 扣除”，导致 surface 与 Road 表征不一致。
- 运行证据受限：当前机器缺少 patch `2855832070394132` 数据，`2855832875697813` 现有产物为 `patch_id_not_found` 失败记录，无法形成该两条 patch 的完整几何矩阵证据。

## How “Road surface” is defined in code
### 1) 点云有效面（用于几何）
- 点云读取与分类过滤：`pipeline.py:1010-1096` 调 `load_point_cloud_window(... allowed_classes=(POINT_CLASS_PRIMARY,), fallback_to_any_class=POINT_CLASS_FALLBACK_ANY)`。
- 点云分类落地：`io.py:374-390` 仅保留 `allowed_classes`，仅在 fallback 开关开时退回“任意分类”。
- 中心线 offset 估计：`geometry.py:3113-3188`
  - 横截窗口：`|along|<=along_half_window` + `|across|<=across_half_window`；
  - gore 扣除：`contains_xy(gore_zone)`；
  - corridor 约束：`|across|<=corridor_half_width`；
  - P05/P95 中点作为 offset。

### 2) traj_surface（用于门禁/约束）
- 构建入口（按 cluster）：`pipeline.py:1434-1571` `_build_traj_surface_hint_for_cluster`。
- station 轴来源：`pipeline.py:1471-1478` 使用 `src_xsec.interpolate(0.5)` 与 `dst_xsec.interpolate(0.5)` 直连生成 `ref_line`。
- 切片拼面：`pipeline.py:1262-1354`
  - `slice_step`、`slice_half_win`；
  - 横向分位数 `P02/P98`；
  - `buffer(SURF_BUF_M)`；
  - `difference(gore_zone)`。
- 门禁判定：`pipeline.py:1574-1776`
  - sufficient 条件：`valid_slices/slice_valid_ratio/covered_length_ratio/unique_traj_count`；
  - enforced=true 时：`in_ratio >= IN_RATIO_MIN` 且端点在 surface 内，否则 `ROAD_OUTSIDE_TRAJ_SURFACE`。

## Why traj_surface is short (root-cause analysis)
### A) 轨迹片段截取口径（候选根因，证据强）
- 轨迹用于 surface 时取的是“support traj_id 的全轨迹点”，不是 A→B 截断段：`pipeline.py:1150-1172`。
- 这会把与 A→B 无关的远端轨迹点也带入候选，再依赖局部切片过滤，容易出现有效 slice 只在局部。
- 证据：`audit_traj_used_range_*.json` 中 `used_traj_station_range` 当前不可得，侧面说明产物未落盘该关键诊断。

### B) station 轴定义偏差（Top1）
- `traj_surface` 的 ref axis 使用横截中心直连：`pipeline.py:1471-1478`。
- multi-road 或曲线场景下，直连轴可能偏离主通道，导致仅在局部切片命中轨迹点，从而 surface 变短。
- 证据：代码路径固定如此；且历史失败 run（`285579...`）未得到可用 centerline（`CENTER_ESTIMATE_EMPTY`），无法通过几何自校正。

### C) 切片窗口与阈值过严（Top2）
- 逻辑：`half_win` + `min_pts_per_slice` + `slice_valid_ratio` + `covered_length_ratio` 四层门槛（`pipeline.py:1269-1310`, `1559-1566`, `1709-1715`）。
- 当轨迹稀疏/轴偏差时会快速触发“有效切片不足”，只保留局部面或直接 insufficient。

### D) DivStrip 扣除导致面域破碎（候选）
- gore 在 surface 构建与端点支持都被扣除：`pipeline.py:1333-1336`, `geometry.py:1922-1947`, `1861-1919`。
- 若 `GORE_BUFFER_M` 偏大或横截处本就窄，可能把本来连续的支持片段切碎。

### E) multi-road 错配（当前版本结论）
- 当前代码中，Road_k 与 gate_k 使用同一 `support_k` 和同一 `traj_surface_hint_k`：`pipeline.py:664-684`, `1826-1862`, `1963-1979`。
- 因此“跨 cluster A/B 错配”在当前版本主流程中**不成立**。
- 仍会出现看似错配的现象，更多是“同一 cluster 内 surface 轴偏差 + 门槛过滤”造成。

### 最可能根因 Top1/Top2
1. **Top1：station 轴用横截中心直连（而非沿 shape_ref/主通道）**，导致切片局部命中，surface 变短。
2. **Top2：切片有效性阈值叠加过严**，在轨迹稀疏或偏轴情况下迅速退化为局部 surface / insufficient。

## Cross-patch comparison
- `2855795596723843`：有产物但 `Road.geojson` 为空，`CENTER_ESTIMATE_EMPTY`，无法形成可比较的 surface/road 覆盖矩阵。
- `2855832070394132`：当前机器无数据目录且无历史 patch 输出目录，无法采证。
- `2855832875697813`：当前仅有失败记录（`patch_id_not_found`），不具备“正确对照组”几何证据。

## Fix options (NO code changes)
1. 方案A：先补诊断再判断
   - 改善点：可直接看到每个 cluster 的 `surface_k` station 范围、有效切片分布、endpoint 支持片段。
   - 风险：仅增加可观测性，不直接提升效果。
   - 需新增指标：`surface_k_station_min/max`, `valid_slice_bins`, `xsec_support_len_src/dst`, `per_k_inratio_matrix`。
2. 方案B：把 traj_surface 的 station 轴改为 shape_ref/通道轴（策略建议）
   - 改善点：减少直连轴偏差导致的局部命中。
   - 风险：若 shape_ref 本身选错，surface 仍会偏；需结合通道评分。
   - 需新增指标：`axis_source`（xsec_line vs lb_path）、`axis_to_traj_mean_dist`。
3. 方案C：门禁分层（strict/diagnostic）
   - 改善点：在 insufficient 时保留诊断级 in_ratio_est 与 gap 区间，避免“只有 fail 无解释”。
   - 风险：流程更复杂；需防止弱门禁误放行。
   - 需新增指标：`gate_mode`, `insufficient_reasons_hist`, `fallback_surface_quality`。

## Evidence Files
- `audit_traj_surface_stats_2855795596723843.json`
- `audit_inratio_matrix_2855795596723843.json`
- `audit_traj_used_range_2855795596723843.json`
- `audit_traj_surface_stats_2855832070394132.json`
- `audit_inratio_matrix_2855832070394132.json`
- `audit_traj_used_range_2855832070394132.json`
- `audit_traj_surface_stats_2855832875697813.json`
- `audit_inratio_matrix_2855832875697813.json`
- `audit_traj_used_range_2855832875697813.json`

