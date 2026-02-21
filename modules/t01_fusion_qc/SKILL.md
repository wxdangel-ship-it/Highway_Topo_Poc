# t01_fusion_qc - SKILL

## 输入
- `patch_dir`：patch 根目录，必须包含：
  - `PointCloud/merged.laz`
  - `Traj/**/raw_dat_pose.geojson`（可多个；全部参与计算）

## 输出
- 主输出：`TEXT_QC_BUNDLE.txt`（遵循 ARTIFACT_PROTOCOL，可粘贴文本摘要）。
- 可选中间产物：`intervals_topk.csv`（Top-K 区间表）。

## 参数（MVP 默认值与范围）
- `sample_stride`：默认 `5`，范围 `>=1`
- `binN`：默认 `1000`，范围 `>=1`
- `radius`：默认 `1.0`，范围 `>0`
- `radius_max`：默认 `3.0`，范围 `>=radius`
- `min_neighbors`：默认 `30`，范围 `>=1`
- `close_frac`：默认 `0.2`，范围 `(0,1]`
- `min_close_points`：默认 `20`，范围 `>=1`
- `th`：默认 `0.20`，范围 `>=0`
- `min_interval_bins`：默认 `3`，范围 `>=1`
- `topk_intervals`：默认 `20`，范围 `>=1`
- `pc_max_points`：默认 `3000000`，范围 `>=1`
- `seed`：默认 `0`
- `max_lines`：默认 `220`（受全局协议上限约束）
- `max_chars`：默认 `20000`（受全局协议上限约束）

## MVP 验收清单
- 能从 patch 自动定位 `merged.laz` 与全部 `raw_dat_pose.geojson`。
- 计算 `abs_residual` 的 `p50/p90/p99/count`。
- 生成 bin 异常区间并输出 Top-K（按峰值降序）。
- 区间字段包含：`start_bin/end_bin/start_sample_idx/end_sample_idx/length_bins/peak_bin_score/median_bin_score`。
- 文本 artifact 包含 `Params/Metrics/Intervals/Errors(or Breakpoints)`，并具备截断标记。
- pytest 覆盖：区间合并、体积控制/Top-K、随机下采样可复现。
