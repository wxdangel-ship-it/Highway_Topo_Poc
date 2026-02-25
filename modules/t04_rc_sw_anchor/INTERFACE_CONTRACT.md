# t04_rc_sw_anchor - INTERFACE_CONTRACT

## 1. 目标与范围
- 模块 ID：`t04_rc_sw_anchor`
- 目标：识别 merge/diverge 路口锚点（gore tip/nose 近似），并输出最终横截线 `intersection_l_opt.geojson`。
- 处理范围：仅 `merge/diverge`；其它类型记录断点，不输出有效锚点。

## 2. 模式与输入
支持模式：
- `mode=global_focus`（本次主用）
- `mode=patch`（兼容占位）

### 2.1 global_focus 输入
MUST：
- `--patch_dir <patch_dir>`（`patch_id = basename(patch_dir)`）
- `--global_node_path <RCSDNode.geojson>`
- `--global_road_path <RCSDRoad.geojson>`
- Focus NodeIDs（三选一，见 2.3）

SHOULD：
- `--divstrip_path <DivStripZone.geojson>`（缺失可降级）
- `--pointcloud_path <merged_cleaned_classified_3857.laz|las>`（缺失可降级）
- `--traj_glob <patch_dir/Traj/*/raw_dat_pose.geojson>`（缺失可降级）

### 2.2 patch 输入
- `--patch_dir` 必须
- 节点/道路默认读取：`patch_dir/Vector/RCSDNode.geojson`、`patch_dir/Vector/RCSDRoad.geojson`
- 可通过 `focus_node_ids` 指定子集；不指定时处理 patch 内全部节点

### 2.3 Focus NodeIDs 提供方式（global_focus 必须）
优先级：`CLI > config_json`

A) `--focus_node_ids "id1,id2"`
B) `--focus_node_ids_file <txt|json|csv>`
- `.txt`：每行一个 nodeid
- `.json`：`{"focus_node_ids":[...]}` 或直接数组
- `.csv`：优先 `nodeid` 列；否则取第一列
C) `--config_json` 内 `focus_node_ids`

## 3. 参数覆盖规则
- 先加载 `config_json`
- 再应用 CLI 显式参数覆盖
- 再应用 `--set key=value` 覆盖 `params` 子项

## 4. CRS 规则
- 所有距离/扫描计算统一在 `dst_crs`（默认 `EPSG:3857`）
- 输入 GeoJSON：
  - 若 `--src_crs != auto`，使用该 CRS
  - 否则优先 `crs.properties.name`
  - 若仍无，启发式：经纬度范围判定 `EPSG:4326`，否则 `EPSG:3857`

## 5. 业务规则
- 类型判定：`Kind bit4=diverge(16)`、`Kind bit3=merge(8)`
- 选路：
  - diverge：`enodeid == nodeid` 中长度最大
  - merge：`snodeid == nodeid` 中长度最大
- stop：`min(next_intersection_dist, scan_max_limit_m)`；失败写 `ROAD_GRAPH_WEAK_STOP`
- 触发优先级：
  1) `divstrip+pc`
  2) `pc_only`
  3) `divstrip_only_degraded`
  4) fail + `NO_TRIGGER_BEFORE_NEXT_INTERSECTION`
- 点云：
  - `pc_non_ground_class=1`
  - 忽略 `pc_ignore_classes=[12]`
  - 轨迹抑制：`traj_buffer_m=1.5` 内 class=1 不计触发

## 6. 输出
输出根：`outputs/_work/t04_rc_sw_anchor/<run_id>/`

必须输出：
- `anchors.geojson`
- `intersection_l_opt.geojson`
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

`properties` 最小字段：
- `nodeid`
- `anchor_type`
- `status`
- `scan_dir`
- `scan_dist_m`
- `trigger`
- `dist_to_divstrip_m`
- `confidence`
- `flags`

## 7. Breakpoints
至少包含：
- `FOCUS_NODE_NOT_FOUND`
- `UNSUPPORTED_KIND`
- `AMBIGUOUS_KIND`
- `ROAD_LINK_NOT_FOUND`
- `ROAD_GRAPH_WEAK_STOP`
- `DIVSTRIPZONE_MISSING`
- `POINTCLOUD_MISSING_OR_UNUSABLE`
- `TRAJ_MISSING`
- `NO_TRIGGER_BEFORE_NEXT_INTERSECTION`
- `SCAN_EXCEED_200M`
- `DIVSTRIP_TOLERANCE_VIOLATION`

## 8. 门禁与 overall_pass
Hard Gates：
- 必需输出文件齐全
- `seed_total > 0`

Soft Gates（focus 默认）：
- `anchor_found_ratio >= min_anchor_found_ratio_focus`（默认 1.0）
- `scan_exceed_200m_count <= scan_exceed_200m_count_max_focus`（默认 0）
- `no_trigger_count <= no_trigger_count_max_focus`（默认 0）

## 9. CLI
入口：
- `python -m highway_topo_poc.modules.t04_rc_sw_anchor`

示例：
```bash
python -m highway_topo_poc.modules.t04_rc_sw_anchor \
  --config_json modules/t04_rc_sw_anchor/t04_config_template_global_focus.json
```
