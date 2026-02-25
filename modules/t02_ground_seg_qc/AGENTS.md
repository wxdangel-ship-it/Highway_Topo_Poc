# t02_ground_seg_qc - AGENTS

## 模块目标
- 生成地面点云分类结果（ground / non-ground）。
- 基于轨迹进行横截方向（cross-track）质量检查。
- 保留并兼容 traj-clearance QC（轨迹 Z 相对地面参考）。
- 通过 auto_tune 在真实 patch 上迭代到 `overall_pass=True`（若可达）。
- 提供多层重叠清理能力（v2）：统一到 EPSG:3857，支持 TrajZ 正常/退化双方案，识别并删除上下层干扰面点并产出可审计分类结果。

## 职责边界
- 仅处理 t02：点云地面分类、横截 QC、traj-clearance QC、异常区间与摘要。
- 不修改 t01/t03/t04/t05 及其接口契约。
- 实现代码只在 `src/highway_topo_poc/modules/t02_ground_seg_qc/`。
- 文档契约只在 `modules/t02_ground_seg_qc/`。
- 多层清理必须遵循：
  - 点云/轨迹在网格与距离计算前统一到 EPSG:3857（米制）；
  - `traj_z_mode=auto` 时按 `nonzero_ratio<0.01 且 z_std<0.05` 判定 TrajZ 退化；
  - `traj_z_mode=force_traj_z/force_degraded` 可强制分支；
  - 走廊由 Traj XY + `corridor_radius_m` 构建，Traj 未覆盖区域默认不删；
  - 地面定义为 corridor 内 `|z-road_z(cell)| <= ground_band_m`；
  - Traj 未覆盖 cell 默认不删；
  - 仅在“多层密集连通簇 + 干扰层 band”内删除；
  - 路侧稀疏非地面地物（如杆件/标志牌）应保留；
  - 严禁覆盖 `data/synth_local` 原始输入。

## 输入
- Patch 目录（支持 `--patch auto` 自动发现）：
  - 轨迹：`raw_dat_pose.geojson` 优先，兼容 `npy/npz/csv/json/txt`
  - 点云：`merged.laz/las` 优先，兼容 `npy/npz/csv/bin`
- 最小字段：可解析 `x,y,z`。
- 若轨迹为 lon/lat、点云为米制坐标，t02 内可自动投影到 UTM。

## 输出（落盘路径固定）
`outputs/_work/t02_ground_seg_qc/<run_id>/<patch_id>/`
- 必需：`metrics.json`, `summary.txt`, `intervals.json`, `xsec_intervals.json`
- 必需：`ground_idx.npy`, `ground_points.npy`, `ground_stats.json`
- 必需：`chosen_config.json`, `tune_log.jsonl`
- 可选：`xsec_series.npz`, `series.npz`

## ground_cache 批处理（新增）
- 支持对 `data/synth_local` 全量 patch 点云生成“全点地面标签缓存”，用于后续模块可选输入。
- 批处理入口：
  - `python -m highway_topo_poc.modules.t02_ground_seg_qc.batch_ground_cache`
- 输出目录规范：
  - `outputs/_work/t02_ground_seg_qc/<run_id>/ground_cache/<patch_key>/`
  - 必需：`ground_label.npy`（`uint8`，shape=`(N,)`，全点输出，`1=ground`）
  - 必需：`ground_stats.json`
  - 建议：`ground_idx.npy`
  - 可选：`classified.laz`/`classified.las`（默认关闭）
- 全局清单：
  - `outputs/_work/t02_ground_seg_qc/<run_id>/ground_cache_manifest.jsonl`
  - `outputs/_work/t02_ground_seg_qc/<run_id>/ground_cache_summary.json`
  - `outputs/_work/t02_ground_seg_qc/<run_id>/failed_patches.txt`（若存在失败）
- 口径要求：
  - 不抽样、不截断、不做 `max_export_points` 类上限；
  - `chunk_points` 仅用于内存/IO 分块。

## classified_cloud 导出（新增）
- 支持基于 `ground_cache_manifest.jsonl` + `ground_label.npy` 导出完整 classified 点云副本。
- 导出入口：
  - `python -m highway_topo_poc.modules.t02_ground_seg_qc.export_classified_cloud`
- 输出目录规范：
  - `outputs/_work/t02_ground_seg_qc/<run_id>/classified_cloud/<patch_key>/merged_classified.<laz|las>`
- 写入规则：
  - 仅写 `classification` 字段：`ground=2`、`non-ground=1`
  - 除 `classification` 外其余点字段保持不变
  - 严禁覆盖 `data/synth_local` 原始点云
- 大数据口径：
  - 必须 chunk 流式读写；
  - `ground_label.npy` 用 `mmap_mode=\"r\"` 读取；
  - 若 `.laz` 压缩 backend 不可用，自动 fallback 输出 `.las` 并在 manifest 记录原因。

## multilayer_clean_and_classify（新增）
- 支持对 `data/synth_local` 批量执行“多层重叠清理 + 分类写回（旁路输出）”。
- 入口：
  - `python -m highway_topo_poc.modules.t02_ground_seg_qc.batch_multilayer_clean_and_classify`
- 输出目录规范：
  - `outputs/_work/t02_ground_seg_qc/<run_id>/multilayer_clean/<patch_key>/`
  - 必需：`merged_cleaned_classified_3857.<laz|las>`（仅 kept 点，`class=2/1`）
  - 可选：`merged_full_tagged_3857.<laz|las>`（全点，removed 点 `class=12`）
  - 必需：`patch_stats.json`, `ref_surface_stats.json`, `overlap_cells_report.json`
  - 必需：`road_z_surface.csv`, `road_z_variation_report.json`
- 全局清单：
  - `outputs/_work/t02_ground_seg_qc/<run_id>/multilayer_manifest.jsonl`
  - `outputs/_work/t02_ground_seg_qc/<run_id>/multilayer_summary.json`
- 关键规则：
  - `out_epsg` 当前冻结为 `3857`；
  - `traj_z_mode=auto` 默认优先尝试 TrajZ，退化时自动切换 degraded（点云峰值+轨迹方向 DP）；
  - overlap 删除必须满足“密集簇护栏 + 干扰层 band”，且 corridor 外永不标记 `12`；
  - `merged_cleaned_classified_3857` 仅包含 kept 点（`class=2/1`）；
  - `merged_full_tagged_3857` 全点输出，removed 点必须标 `class=12`。

## 非目标
- 不替代 t01 的融合质量评估职责。
- 不追求完整语义分类体系（仅关心地面候选提取与 QC）。

## 禁止项
- 不在 `outputs/` 下做代码开发、git、pytest。
- 不创建 worktree。
- 不越界修改非 t02 文件。
