# t01_fusion_qc - SKILL

## 算法口径（MVP 冻结）

1) residual 定义
- residual_i = traj_z_i - z_cloud_est_i

2) z_cloud_est 定义
- 以轨迹点 XY 在点云做近邻查询。
- 先做 radius_m 查询；若邻居数 < min_neighbors，则回退 KNN（knn）。
- z_cloud_est_i = median(z_neighbors)。
- 若最终邻居数仍 < min_neighbors，则该点无效（NaN）。

3) metrics 定义
- 在有效点 abs_residual=|residual| 上统计 p50/p90/p99。
- threshold_A = max(th_abs_min, quantile(abs_residual, th_quantile))。
- coverage = n_valid / n_traj。
- status ∈ {OK, LOW_COVERAGE, NO_VALID}。

4) bin / interval 规则
- bin j 覆盖点索引 [j*stride, j*stride+binN)。
- bin_score = median(abs_residual within bin valid points)。
- 若 bin_valid_fraction < coverage_gate，标记 insufficient_coverage，不参与异常判定。
- abnormal bin：bin_score > threshold_A。
- 合并连续 abnormal bins => interval（start_bin 含，end_bin 不含）。
- 保留 len_bins >= min_interval_len 的 interval。
- interval_score = max(bin_score in interval)。
- 按 interval_score 降序输出 TopK。
- 点索引范围：start_idx=start_bin*stride；end_idx=(end_bin-1)*stride+binN。

5) 输出文件
- metrics.json
- intervals.json
- summary.txt（包含 patch_key、coverage、p50/p90/p99、threshold_A、TopK intervals、status）
