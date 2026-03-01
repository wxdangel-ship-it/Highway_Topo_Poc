# t04_rc_sw_anchor - SKILL

## 1. Seed 与 Kind
- 仅 merge/diverge：
  - `diverge = (kind & 16) != 0`
  - `merge = (kind & 8) != 0`
- `kind` 字段读取必须经字段归一化层。

## 2. CRS 归一化
- 所有几何在 `dst_crs`（默认 `EPSG:3857`）中计算。
- `node/road/divstrip/drivezone/traj/pointcloud` 均记录 layer CRS 诊断。
- PointCloud CRS 无法识别时：`usable=false + POINTCLOUD_CRS_UNKNOWN_UNUSABLE`（禁止 silent fallback）。

## 3. 触发策略（DriveZone 主证据）
1) `divstrip+dz`：DivStrip 命中后，扇形中轴带内检测到非 DriveZone。
2) `divstrip_only_degraded`：DriveZone 缺失/未命中且允许降级。
3) `divstrip+pc` / `pc_only*`：仅 DriveZone 不可用时启用兼容路径。

## 4. stop 策略
- stop 候选必须：图联通可达 + `degree>=3`（默认）。
- 默认禁用几何 fallback：`disable_geometric_stop_fallback=true`。

## 5. 输出诊断重点
- `evidence_source`
- `tip_s_m / first_divstrip_hit_dist_m / best_divstrip_dz_dist_m`
- `fan_area_m2 / non_drivezone_area_m2 / non_drivezone_frac`
- `clipped_len_m / clip_empty / clip_piece_type`
- `stop_reason`

## 6. 常见失败模式（Top-5）
- `DRIVEZONE_MISSING`
- `DRIVEZONE_SPLIT_NOT_FOUND`
- `DRIVEZONE_CLIP_EMPTY`
- `NEXT_INTERSECTION_NOT_FOUND_CONNECTED`
- `POINTCLOUD_CRS_UNKNOWN_UNUSABLE`
