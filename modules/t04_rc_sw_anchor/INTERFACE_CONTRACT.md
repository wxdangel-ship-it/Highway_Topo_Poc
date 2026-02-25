# t04_rc_sw_anchor - INTERFACE_CONTRACT

## 1. 目标与范围
- 模块 ID：`t04_rc_sw_anchor`
- 目标：识别 merge/diverge 锚点（gore tip/nose 近似）并输出最终横截线 `intersection_l_opt`。
- 范围：仅处理 `merge/diverge`，其它类型写入 breakpoint 并输出失败条目。

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
- `--pointcloud_path <merged_cleaned_classified_3857.laz|las|merged.geojson>`
- `--traj_glob <patch_dir/Traj/*/raw_dat_pose.geojson>`

### 2.2 patch 输入
- `--patch_dir` 必填
- 默认读取：
  - `patch_dir/Vector/RCSDNode.geojson`（缺失回退 `Node.geojson`）
  - `patch_dir/Vector/RCSDRoad.geojson`（缺失回退 `Road.geojson`）

### 2.3 Focus NodeIDs 提供方式
优先级：`CLI > config_json`

A) `--focus_node_ids "id1,id2"`  
B) `--focus_node_ids_file <txt|json|csv>`  
C) `--config_json` 内 `focus_node_ids`

## 3. CRS 契约（v5）
所有几何计算统一在 `dst_crs`（默认 `EPSG:3857`）。

CLI：
- `--dst_crs EPSG:3857`
- `--src_crs auto`（全局缺省）
- `--node_src_crs auto|EPSG:4326|EPSG:3857`
- `--road_src_crs auto|EPSG:4326|EPSG:3857`
- `--divstrip_src_crs auto|EPSG:4326|EPSG:3857`
- `--traj_src_crs auto|EPSG:4326|EPSG:3857`
- `--pointcloud_crs auto|EPSG:4326|EPSG:3857`

检测顺序：
1) 分层显式参数（非 `auto`）  
2) GeoJSON 顶层 `crs.properties.name`  
3) bbox 启发式（经纬度范围 -> 4326；米制量级 -> 3857）

若 CRS 无法识别且无 override，写入 `CRS_UNKNOWN`，并允许流程继续产出完整工件（`overall_pass=false`）。

## 4. 业务规则
- 类型：
  - `kind bit4=diverge(16)`
  - `kind bit3=merge(8)`
  - 同时为真 -> `AMBIGUOUS_KIND`
  - 均为假 -> `UNSUPPORTED_KIND`
- 扫描 stop：`min(next_intersection_dist, scan_max_limit_m)`，失败写 `ROAD_GRAPH_WEAK_STOP`
- 点云触发只使用 `class==1`，忽略 `class==12`
- `traj_buffer_m` 内非地面候选可抑制

### 4.1 触发优先级（DivStrip 优先）
两阶段决策：
1) 若 DivStrip 存在，优先选 `divstrip+pc`
2) DivStrip 存在但未命中时，可降级 `pc_only_no_divstrip_hit`（`status=suspect` + `DIVSTRIP_NEVER_HIT`）
3) DivStrip 存在且命中但未形成 `divstrip+pc`，可选 `pc_only_after_divstrip_miss`
4) DivStrip 缺失时，按 `pc_only` 规则
5) 点云不可用时可退化 `divstrip_only_degraded`

相关参数：
- `pc_only_min_scan_dist_m`（默认 `10.0`）
- `pc_only_after_divstrip_min_m`（默认 `5.0`）

## 5. 输出
输出根：`outputs/_work/t04_rc_sw_anchor/<run_id>/`

必须输出：
- `anchors_3857.geojson`
- `intersection_l_opt_3857.geojson`
- `anchors_wgs84.geojson`
- `intersection_l_opt_wgs84.geojson`
- `anchors.geojson`（兼容名，内容同 3857）
- `intersection_l_opt.geojson`（兼容名，内容同 3857）
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

`anchors/intersection` 的 `properties` 最小字段：
- `nodeid`
- `anchor_type`
- `status`
- `scan_dir`
- `scan_dist_m`
- `trigger`
- `dist_to_divstrip_m`
- `confidence`
- `flags`

`anchors.json` 额外包含调试字段：
- `first_divstrip_hit_dist_m`
- `best_divstrip_pc_dist_m`
- `first_pc_only_dist_m`
- `dist_line_to_divstrip_m`
- `stop_reason`
- `resolved_from`

## 6. Breakpoints
至少包含：
- `CRS_UNKNOWN`
- `FOCUS_NODE_NOT_FOUND`
- `MISSING_KIND_FIELD`
- `UNSUPPORTED_KIND`
- `AMBIGUOUS_KIND`
- `ROAD_FIELD_MISSING`
- `ROAD_LINK_NOT_FOUND`
- `ROAD_GRAPH_WEAK_STOP`
- `DIVSTRIPZONE_MISSING`
- `DIVSTRIP_NEVER_HIT`
- `POINTCLOUD_MISSING_OR_UNUSABLE`
- `TRAJ_MISSING`
- `NO_TRIGGER_BEFORE_NEXT_INTERSECTION`
- `SCAN_EXCEED_200M`
- `DIVSTRIP_TOLERANCE_VIOLATION`

## 7. 门禁
Hard Gates：
- 必需输出文件齐全
- `seed_total > 0`

Soft Gates（focus 默认）：
- `anchor_found_ratio >= min_anchor_found_ratio_focus`（默认 `1.0`）
- `scan_exceed_200m_count <= scan_exceed_200m_count_max_focus`（默认 `0`）
- `no_trigger_count <= no_trigger_count_max_focus`（默认 `0`）
