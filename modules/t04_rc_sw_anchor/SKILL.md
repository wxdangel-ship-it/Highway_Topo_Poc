# t04_rc_sw_anchor - SKILL

## 1. Seed 与 Kind
- 仅处理 merge/diverge：
  - `diverge = (kind & 16) != 0`
  - `merge = (kind & 8) != 0`
- 字段读取必须经归一化层（`normalize_props + get_first_int/get_first_raw`）。

## 2. DriveZone-first + Between-Branches
- 触发主证据：`SEG(s) ∩ DriveZone` 的片段数变化。
- `SEG(s)` 仅在两分支之间构造（B 口径）。
- `divstrip` 仅可选强证据，不得驱动远距离扫描。
- stop 范围内无 split 直接 fail，不允许跨路口漂移补答案。

## 3. stop 策略
- 仅 hard stop：拓扑联通可达 + `degree>=3`。
- 找不到时 `stop_reason=next_intersection_not_found_deg3`，扫描到 `scan_max_limit_m`。
- 禁止几何 fallback（`disable_geometric_stop_fallback=true`）。

## 4. CRS 与 fail-closed
- `node/road/divstrip/drivezone/traj/pointcloud` 统一到 `dst_crs` 计算。
- DriveZone CRS 无法识别：`DRIVEZONE_CRS_UNKNOWN`（hard）。
- PointCloud CRS 无法识别：`POINTCLOUD_CRS_UNKNOWN_UNUSABLE`（soft）。

## 5. 输出诊断重点
- `found_split/status/anchor_found`（状态机一致性）
- `pieces_count/piece_lens_m/gap_len_m/seg_len_m`
- `branch_a_id/branch_b_id/branch_axis_id`
- `stop_reason/next_intersection_nodeid`
- `layer_crs`（summary）

## 6. 常见失败模式（Top-5）
- `DRIVEZONE_SPLIT_NOT_FOUND`
- `NEXT_INTERSECTION_NOT_FOUND_DEG3`
- `DRIVEZONE_CRS_UNKNOWN`
- `MULTI_BRANCH_TODO`
- `DRIVEZONE_CLIP_MULTIPIECE`
