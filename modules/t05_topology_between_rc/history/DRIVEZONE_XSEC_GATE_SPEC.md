# t05 DriveZone 语义横截线规范（Step0/Step1）

## 1. 目的
- 解决 `xsec_seed` 固定长度无语义导致的跨道路混入问题。
- 在 Step1 前构建 `xsec_gate`，仅保留“DriveZone 内且不在 DivStrip 内”的横截通行片段。
- 轨迹证据与 DriveZone 冲突时，默认以 DriveZone 为准。

## 2. 几何定义
- 输入：`xsec_seed`（来自 `intersection_l`）、`drivezone_union`、`divstrip_buffer`。
- 规则：
  - `xsec_gate_all = xsec_seed ∩ drivezone_union \ divstrip_buffer`
  - 若 `xsec_gate_all` 为空：降级到 `xsec_seed \ divstrip_buffer`，并标记 `fallback_flag=true`。
  - 若仍为空：降级到 `xsec_seed`。
- `xsec_gate_selected` 选段规则：
  - 优先选择离 `midpoint(xsec_seed)` 最近的线段。
  - 距离并列时选更长线段。

## 3. Step1 使用规则
- Step1 穿越事件提取改为使用 `xsec_gate_selected`（替代原始 `xsec_seed`）。
- 对候选轨迹段计算 `inside_ratio = len(seg ∩ passable_zone) / len(seg)`。
  - `passable_zone = drivezone_union \ divstrip_buffer`（差集为空时退回 `drivezone_union`）。
  - 默认阈值：`STEP1_TRAJ_IN_DRIVEZONE_MIN=0.85`。
  - 若筛后为空，降级阈值：`STEP1_TRAJ_IN_DRIVEZONE_FALLBACK_MIN=0.60`。
  - 仍为空时保留少量候选继续评估，并标记 `drivezone_fallback_used=true`。

## 4. 多通路判定口径
- 不再依赖“已有分簇字段”作为前提条件。
- 以 Step1 TopK 走廊候选中线间分离度为主判据：
  - `corridor_sep_m > STEP1_MULTI_CORRIDOR_DIST_M`
  - 且（候选数 >=3 或 `main_corridor_ratio < STEP1_MULTI_CORRIDOR_MIN_RATIO`）。
- `STEP1_MULTI_CORRIDOR_HARD=1` 时直接 `MULTI_CORRIDOR`。

## 5. Debug 与 Metrics
- Debug（每 patch）：
  - `debug/drivezone_union.geojson`
  - `debug/xsec_gate_all_src.geojson`
  - `debug/xsec_gate_all_dst.geojson`
  - `debug/xsec_gate_selected_src.geojson`
  - `debug/xsec_gate_selected_dst.geojson`
  - `debug/step1_corridor_candidates.geojson`
  - `debug/step1_support_trajs.geojson`（含 `inside_ratio`, `dropped_by_drivezone`, `corridor_id`）
- Metrics 新增：
  - `xsec_gate_len_src_p90`, `xsec_gate_len_dst_p90`
  - `xsec_gate_geom_type_src_hist`, `xsec_gate_geom_type_dst_hist`
  - `xsec_gate_fallback_src_count`, `xsec_gate_fallback_dst_count`
  - `traj_drop_count_by_drivezone`
  - `drivezone_fallback_used_count`
  - `step1_corridor_count_p90`, `step1_main_corridor_ratio_p50`

## 6. 与 Step2 的关系
- Step2 保持现有 `xsec_ref -> xsec_road_selected` 逻辑。
- Step0/Step1 的语义化门控用于“净化穿越候选轨迹与 shape_ref”，减少误触发 `MULTI_CORRIDOR`。
- `DivStripZone` 仍是硬障碍，不被 DriveZone 替代。
