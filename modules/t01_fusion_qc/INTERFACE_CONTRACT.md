# t01_fusion_qc - INTERFACE_CONTRACT

## CLI
命令：
```bash
./.venv/bin/python -m highway_topo_poc t01-fusion-qc \
  --patch <patch_dir> \
  --out <out_dir> \
  [--sample-stride 5] [--binN 1000] [--radius 1.0] [--radius-max 3.0] \
  [--min-neighbors 30] [--close-frac 0.2] [--min-close-points 20] \
  [--th 0.20] [--min-interval-bins 3] [--topk-intervals 20] \
  [--pc-max-points 3000000] [--seed 0] [--max-lines 220] [--max-chars 20000]
```

## 输入契约（t01）
- `--patch` 指向 patch 目录。
- 必需文件：
  - `<patch>/PointCloud/merged.laz`
  - `<patch>/Traj/**/raw_dat_pose.geojson`（支持多个，全部使用）
- 若多个 Traj 出现平面冲突（如 CRS 不一致），抛出异常 `traj_plane_conflict`。

## 输出契约（t01）
输出目录：`--out`
- `TEXT_QC_BUNDLE.txt`
  - 文本分段至少包含：`Params`、`Metrics`、`Intervals`、`Errors/Breakpoints`
  - 包含 `Truncated: true|false` 标记（超限时体现 `TRUNCATED`）
- `intervals_topk.csv`
  - 列：
    - `start_bin`
    - `end_bin`
    - `start_sample_idx`
    - `end_sample_idx`
    - `length_bins`
    - `peak_bin_score`
    - `median_bin_score`
    - `severity`

## 字段语义与定位口径
- t01 区间定位只使用索引：`sample_idx/bin_idx`。
- 明确禁止使用坐标索引（x/y/z 或里程坐标）作为区间定位主键。
- `start_sample_idx/end_sample_idx` 均为采样后序列下标（闭区间）。
- `start_bin/end_bin` 为离散 bin 下标（闭区间）。
