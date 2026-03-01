# t04_rc_sw_anchor - INTERFACE_CONTRACT

## 1. 目标与范围
- 模块 ID：`t04_rc_sw_anchor`
- 目标：识别 merge/diverge 锚点并输出最终横截线 `intersection_l_opt`。
- 范围：仅处理 `merge/diverge`；其他 kind 输出 breakpoint 与失败条目。

## 2. 模式与输入
支持模式：
- `mode=global_focus`（主用）
- `mode=patch`（兼容）

### 2.1 global_focus 输入
必选：
- `--patch_dir <patch_dir>`（`patch_id = basename(patch_dir)`）
- `--global_node_path <RCSDNode.geojson>`
- `--global_road_path <RCSDRoad.geojson>`
- Focus NodeIDs（三选一，见 2.3）

可选：
- `--divstrip_path <DivStripZone.geojson>`
- `--drivezone_path <DriveZone.geojson>`（vNext 主证据）
- `--pointcloud_path <*.laz|*.las|*.geojson>`（兼容降级）
- `--traj_glob <patch_dir/Traj/*/raw_dat_pose.geojson>`

### 2.2 patch 输入
- `--patch_dir` 必填
- 默认读取：
  - `patch_dir/Vector/RCSDNode.geojson`（缺失回退 `Node.geojson`）
  - `patch_dir/Vector/RCSDRoad.geojson`（缺失回退 `Road.geojson`）
  - `patch_dir/Vector/DriveZone.geojson`（若存在）

### 2.3 Focus NodeIDs 提供方式
优先级：`CLI > config_json`

A) `--focus_node_ids "id1,id2"`
B) `--focus_node_ids_file <txt|json|csv>`
C) `--config_json` 内 `focus_node_ids`

## 3. CRS 契约（vNext）
- 所有几何计算统一在 `dst_crs`（默认 `EPSG:3857`）。
- 分层 `*_src_crs` 支持 `auto|EPSG:xxxx`。
- 自动检测顺序（GeoJSON 层）：
  1) CLI 显式 hint（非 auto）
  2) GeoJSON 顶层 `crs.properties.name`
  3) bbox 启发式
- PointCloud：若 `src_crs` 无法识别，则 `usable=false` + breakpoint（fail-closed），禁止 silent fallback 混算。
- 新增层：`drivezone_src_crs` 纳入同一归一化链路与 summary diagnostics。

## 4. 业务规则

### 4.1 kind 与 seed
- `diverge = (kind & 16) != 0`
- `merge = (kind & 8) != 0`
- 同时为真：`AMBIGUOUS_KIND`
- 均为假：`UNSUPPORTED_KIND`

### 4.2 stop（联通 + degree）
- stop 仅认“沿扫描方向在 RCSDRoad 图上可达”且“`degree >= next_intersection_degree_min`（默认 3）”的下一个路口。
- 默认禁用几何 fallback（`disable_geometric_stop_fallback=true`）。
- stop_reason：
  - `next_intersection_connected_deg3`
  - `next_intersection_not_found_connected`
  - `next_intersection_disabled`
  - `max_200`

### 4.3 触发优先级（DriveZone 主证据）
1) `divstrip+dz`：DivStrip 命中后，扇形中轴带内检测到非 DriveZone。
2) `divstrip_only_degraded`：DriveZone 缺失/不满足触发且允许降级时。
3) `divstrip+pc` / `pc_only*`：仅在 DriveZone 不可用时作为兼容降级。

### 4.4 扇形判别
- 构造 `fan_band = sector(origin=anchor_pt, dir=scan_vec, radius, half_angle) ∩ corridor(band_width)`。
- `non_geom = fan_band - drivezone_union`
- 命中条件：
  - `non_drivezone_area_m2 >= drivezone_non_drivezone_area_min_m2`
  - 或 `non_drivezone_frac >= drivezone_non_drivezone_frac_min`

### 4.5 DriveZone 截断
- `drivezone_clip_crossline=true` 时，对 `crossline_opt` 做 `intersection(drivezone_union)`。
- 选取包含 anchor_pt 或距 anchor_pt 最近的线段作为最终输出。
- clip 失败输出 `DRIVEZONE_CLIP_EMPTY`。

## 5. 输出
输出根：`outputs/_work/t04_rc_sw_anchor/<run_id>/`

必须输出：
- `anchors_3857.geojson`
- `intersection_l_opt_3857.geojson`
- `anchors_wgs84.geojson`
- `intersection_l_opt_wgs84.geojson`
- `anchors.geojson`（兼容名，内容同 dst_crs 版本）
- `intersection_l_opt.geojson`（兼容名，内容同 dst_crs 版本）
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

`intersection_l_opt*.geojson` properties 最小字段：
- `nodeid/kind`
- `id/mainnodeid/mainid`（存在则输出）
- `kind_bits.merge` / `kind_bits.diverge`
- `anchor_type/trigger/scan_dist_m/stop_reason/evidence_source`
- `dist_line_to_divstrip_m`
- `dist_line_to_drivezone_edge_m`
- `fan_area_m2/non_drivezone_area_m2/non_drivezone_frac`
- `clipped_len_m/clip_empty/clip_piece_type`

## 6. Breakpoints
至少包含：
- `CRS_UNKNOWN`
- `FOCUS_NODE_NOT_FOUND`
- `MISSING_KIND_FIELD`
- `UNSUPPORTED_KIND`
- `AMBIGUOUS_KIND`
- `ROAD_FIELD_MISSING`
- `ROAD_LINK_NOT_FOUND`
- `DIVSTRIPZONE_MISSING`
- `DRIVEZONE_MISSING`
- `DRIVEZONE_UNION_EMPTY`
- `DRIVEZONE_CRS_UNKNOWN`
- `DRIVEZONE_CLIP_EMPTY`
- `DRIVEZONE_SPLIT_NOT_FOUND`
- `NEXT_INTERSECTION_NOT_FOUND_CONNECTED`
- `NEXT_INTERSECTION_DISABLED`
- `NEXT_INTERSECTION_DEG_TOO_LOW_SKIPPED`
- `ROAD_GRAPH_DISCONNECTED_STOP`
- `POINTCLOUD_CRS_UNKNOWN_UNUSABLE`
- `POINTCLOUD_MISSING_OR_UNUSABLE`
- `NO_TRIGGER_BEFORE_NEXT_INTERSECTION`
- `SCAN_EXCEED_200M`

## 7. 门禁
Hard Gates：
- 必需输出文件齐全
- `seed_total > 0`
- `hard_breakpoint_count == 0`

Soft Gates（focus 默认）：
- `anchor_found_ratio >= min_anchor_found_ratio_focus`（默认 `1.0`）
- `scan_exceed_200m_count <= scan_exceed_200m_count_max_focus`（默认 `0`）
- `no_trigger_count <= no_trigger_count_max_focus`（默认 `0`）
