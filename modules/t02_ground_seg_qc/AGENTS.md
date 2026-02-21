# t02_ground_seg_qc - AGENTS

## 模块目标
- 生成地面点云分类结果（ground / non-ground）。
- 基于轨迹进行横截方向（cross-track）质量检查。
- 保留并兼容 traj-clearance QC（轨迹 Z 相对地面参考）。
- 通过 auto_tune 在真实 patch 上迭代到 `overall_pass=True`（若可达）。

## 职责边界
- 仅处理 t02：点云地面分类、横截 QC、traj-clearance QC、异常区间与摘要。
- 不修改 t01/t03/t04/t05 及其接口契约。
- 实现代码只在 `src/highway_topo_poc/modules/t02_ground_seg_qc/`。
- 文档契约只在 `modules/t02_ground_seg_qc/`。

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

## 非目标
- 不替代 t01 的融合质量评估职责。
- 不追求完整语义分类体系（仅关心地面候选提取与 QC）。

## 禁止项
- 不在 `outputs/` 下做代码开发、git、pytest。
- 不创建 worktree。
- 不越界修改非 t02 文件。
