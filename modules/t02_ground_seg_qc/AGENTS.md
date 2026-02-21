# t02_ground_seg_qc - AGENTS

## 目标
- 实现 t02 MVP：基于点云构建 `ground_z` 参考面，并用轨迹 `traj_z` 做质量校验（QC）。
- 输出可粘贴摘要：分位数指标、异常区间 Top-K、PASS/FAIL gate 结论。

## 职责边界
- 只处理 t02：`ground_z` 估计、`traj_z` 残差统计、异常区间识别与摘要落盘。
- 不改动 t01/t03/t04/t05 的代码、契约与运行逻辑。
- 本模块运行产物只写入：`outputs/_work/t02_ground_seg_qc/<run_id>/<patch_id>/`。

## 输入工件
- `data_root` 下的 patch 目录（支持自动发现）：
  - 轨迹：优先 `raw_dat_pose.geojson`，兼容 `npy/npz/csv/json/txt`。
  - 点云：优先 `merged.laz|merged.las`，兼容 `npy/npz/csv/bin/ply/pcd/las/laz`。
- 关键输入字段：轨迹和点云都至少可解析出 `x,y,z`。

## 输出工件
- `metrics.json`：p50/p90/p99、coverage、outlier_ratio、bias、baseline、threshold、gates。
- `intervals.json`：按索引 bin 的异常区间合并结果与 Top-K。
- `summary.txt`：紧凑文本摘要（带体积截断标记）。
- `series.npz`：`traj_xyz/ground_z/z_diff/residual/abs_res` 便于复盘。

## 禁止项
- 禁止在 `outputs/` 下作为工作目录开发或运行 git/pytest。
- 禁止创建 worktree（尤其 `Highway_Topo_Poc_worktrees`）。
- 禁止越界改动非 t02 允许路径。
