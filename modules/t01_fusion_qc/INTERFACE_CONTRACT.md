# t01_fusion_qc - INTERFACE_CONTRACT (MVP)

## 1. CLI 接口（冻结）

入口：
- python -m highway_topo_poc.modules.t01_fusion_qc.cli

参数（MVP）
- --data_root: patch 根目录（默认 data/synth_local）
- --out_dir: 运行输出目录（必填）
- --max_patches: 最多处理 patch 数（默认 1）
- --patch_key: 可选，指定仅处理某个 patch_key
- --radius_m, --min_neighbors, --knn
- --th_abs_min, --th_quantile
- --binN, --stride, --coverage_gate
- --min_interval_len, --top_k

返回码：
- 0: 成功（至少完成 1 个 patch 的处理流程）
- 1: 运行失败（参数错误、输入缺失或读取失败）

## 2. Python 函数接口（冻结）

- discover_patch_candidates(data_root: Path) -> list[PatchCandidate]
- read_traj_geojson(traj_path: Path) -> TrajectoryData
- analyze_patch_candidate(candidate: PatchCandidate, ...) -> PatchAnalysis
- write_run_reports(results: list[PatchAnalysis], out_dir: Path, params: dict) -> None

## 3. 输出文件（冻结）

在 out_dir 下固定输出：
- metrics.json
- intervals.json
- summary.txt

关键字段（MVP）
- metrics.json
  - module: "t01_fusion_qc"
  - results[].patch_key
  - results[].coverage
  - results[].p50 / p90 / p99
  - results[].threshold_A
  - results[].status
  - results[].n_traj / n_valid
- intervals.json
  - module: "t01_fusion_qc"
  - results[].patch_key
  - results[].intervals[]
    - start_bin (inclusive)
    - end_bin (exclusive)
    - len_bins
    - interval_score
    - start_idx
    - end_idx
- summary.txt
  - 每个 patch 至少包含：patch_key、coverage、p50/p90/p99、threshold_A、TopK intervals、status

## 4. 索引规则（冻结）
- 全部索引均为 0-based。
- 区间统一采用半开区间 [start, end)。
- bin 区间字段解释：
  - start_bin 包含
  - end_bin 不包含
