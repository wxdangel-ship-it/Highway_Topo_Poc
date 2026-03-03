# t04_rc_sw_anchor - INTERFACE_CONTRACT

## 1. 目标与范围
- 模块 ID：`t04_rc_sw_anchor`
- 目标：识别 `merge/diverge` 锚点并输出 `intersection_l_opt`。
- 范围：仅对 `kind bit3/bit4`（merge/diverge）生效；其他类型失败并打断点。

## 2. 模式与输入
支持模式：
- `mode=global_focus`
- `mode=patch`

### 2.1 global_focus 输入
必选：
- `patch_dir`
- `global_node_path`
- `global_road_path`
- `focus_node_ids`（见 2.3）

可选：
- `divstrip_path`
- `drivezone_path`（SHOULD，DriveZone-first 主证据）
- `pointcloud_path`（OPTIONAL，仅诊断/降级）
- `traj_glob`

### 2.2 patch 输入
- `patch_dir` 必填
- 默认从 patch 下解析 node/road/divstrip/drivezone/traj/pointcloud 路径（存在即加载）

### 2.3 focus_node_ids 来源优先级
- `--focus_node_ids`
- `--focus_node_ids_file`
- `config_json.focus_node_ids`

优先级：`CLI > config_json`

## 3. 字段归一化契约
- 所有 properties 访问必须走 `field_norm.normalize_props`。
- `kind` 读取：`get_first_int(..., ["kind"])`。
- canonical 节点 ID 优先字段：`mainid/mainnodeid/id/nodeid`（经归一化后统一处理）。

## 4. CRS 契约（fail-closed）
- 所有输入层统一重投影到 `dst_crs`（默认 `EPSG:3857`）再参与计算：
  - `node/road/divstrip/drivezone/traj/pointcloud`
- `*_src_crs=auto` 检测顺序：
  1) CLI 显式 hint（非 auto）
  2) GeoJSON `crs.properties.name`
  3) bbox 启发式
- 无法识别时 fail-closed：
  - DriveZone：`DRIVEZONE_CRS_UNKNOWN`（hard）
  - PointCloud：`POINTCLOUD_CRS_UNKNOWN_UNUSABLE`（soft）
- summary 必须输出每层 `src_detected/src_used/dst/bbox_src/bbox_dst`。

## 5. 核心业务规则

### 5.1 DriveZone-first
- 主触发仅基于 `SEG(s) ∩ DriveZone` 的片段数。
- `divstrip` 存在时优先用于 `s*` 选点（邻域窗口内优先），但不得驱动远距离漂移。
- `pointcloud` 默认不参与主触发，仅保留诊断字段。

### 5.2 Between-Branches(B)
- 每个扫描步 `s`，构造 `SEG(s)=LineString(PA(s)->PB(s))`：
  - `PA/PB`：分支与 crossline 交点优先，否则 branch 到 crossline 最近点。
- DriveZone 判定与输出均只在 `SEG(s)` 上进行。

### 5.3 split 定义
- `pieces = SEG(s) ∩ DriveZone` 的线段片段（过滤 `< min_piece_len_m`）。
- 最早满足 `len(pieces) >= 2` 的 `s*` 为分割位置。
- 若存在 divstrip 参考点，则优先在 `divstrip_preferred_window_m` 窗口内选择 `s*`（无则回退最早 split）。
- stop 范围内无 `s*`：`status=fail` + `DRIVEZONE_SPLIT_NOT_FOUND`。

### 5.4 stop（hard-only）
- 仅允许：从当前 node 沿扫描方向，在 RCSDRoad 拓扑联通可达的下一个 `degree>=3` 节点。
- 找不到则 `stop_dist=scan_max_limit_m`，`stop_reason=next_intersection_not_found_deg3`。
- 禁止几何近邻 fallback（`disable_geometric_stop_fallback=true`）。

### 5.5 状态机一致性
- 引入 `found_split`。
- 最终状态单点赋值：
  - `found_split=false -> fail`
  - `found_split=true -> ok/suspect`（受软标记影响）
- `anchor_found` 基于 `found_split` 与 hard-fail 结果，不允许 fail 被后续覆盖。

### 5.6 连续分合流顺序化（v1）
- 连续链识别：
  - 起点集合：当前运行 seeds（`global_focus` 为 `focus_node_ids`）。
  - 仅 `direction=2/3` 参与扩展；`direction=0/1` 直接停止该路扩展。
  - 沿有效方向追踪到下一个 `degree>=3` 节点，允许跨过 `degree=2` 过路点。
  - `dist < continuous_dist_max_m(默认50)` 且目标节点也在 seeds 且 kind 为 merge/diverge 时，记为连续边。
- 链内顺序约束：
  - `abs_s` 定义：`diverge=offset+s_chosen`，`merge=offset-s_chosen`。
  - 对每节点仅接受 `abs_s_candidate > max(predecessors_abs_s)` 的候选；否则节点 fail 并打 `SEQUENTIAL_ORDER_VIOLATION`。
- `diverge->merge` 合并：
  - 相邻边上、merge 的主要前驱为该 diverge，且两条 `crossline_opt` 几何相交或近邻（`distance<=continuous_merge_geom_tol_m`）时允许合并。
  - `continuous_merge_max_gap_m` 与 window 交集仅保留诊断，不作为阻断门槛。

## 6. 参数契约（关键）
- `min_piece_len_m`：DriveZone 交段最小长度过滤（数值噪声抑制）
- `next_intersection_degree_min`：默认 `3`
- `disable_geometric_stop_fallback`：默认 `true`
- `divstrip_anchor_snap_enabled`：默认 `false`
- `divstrip_preferred_window_m`：默认 `8.0`
- `divstrip_drivezone_max_offset_m`：默认 `30.0`
- `output_cross_half_len_m`：默认 `120.0`
- `continuous_enable`：默认 `true`（仅连续链节点生效）
- `continuous_dist_max_m`：默认 `50.0`
- `continuous_merge_max_gap_m`：默认 `5.0`（诊断阈值，不阻断合并）
- `continuous_merge_geom_tol_m`：默认 `1.0`（几何近邻合并阈值）
- patch/focus 门禁阈值分开：
  - `min_anchor_found_ratio_focus/min_anchor_found_ratio_patch`
  - `no_trigger_count_max_focus/no_trigger_count_max_patch`
  - `scan_exceed_200m_count_max_focus/scan_exceed_200m_count_max_patch`

## 7. 输出契约
输出目录：`outputs/_work/t04_rc_sw_anchor/<run_id>/`

必选文件：
- `anchors_3857.geojson`
- `intersection_l_opt_3857.geojson`
- `anchors_wgs84.geojson`
- `intersection_l_opt_wgs84.geojson`
- `anchors.geojson`
- `intersection_l_opt.geojson`
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

`intersection_l_opt*.geojson`：
- 默认每个有效 node 输出一条连续 LineString。
- 连续链合并触发时输出一条合并 feature，properties 额外包含：
  - `nodeids[]`
  - `kinds[]`
  - `roles[]`（`["diverge","merge"]`）
  - `merged=true`
  - `merged_group_id`
  - `abs_s_merged_m`
- properties 必含：
  - `nodeid/id/mainid/mainnodeid`
  - `kind/kind_bits`
  - `anchor_type/scan_dist_m/stop_reason/evidence_source`
  - `found_split/pieces_count/piece_lens_m/gap_len_m/seg_len_m`
  - `branch_a_id/branch_b_id/branch_axis_id`

`anchors.json`：
- 必含关键诊断：
  - `found_split`
  - `branch_a_id/branch_b_id/branch_axis_id`
  - `pieces_count/piece_lens_m/gap_len_m/seg_len_m`
  - `stop_reason`
  - `is_in_continuous_chain/chain_component_id/chain_node_offset_m`
  - `abs_s_chosen_m/abs_s_prev_required_m`
  - `sequential_ok/sequential_violation_reason`
  - `merged/merged_group_id/merged_with_nodeids/abs_s_merged_m`

## 8. Breakpoints（最小集合）
- `DRIVEZONE_SPLIT_NOT_FOUND`
- `DRIVEZONE_CLIP_MULTIPIECE`
- `DRIVEZONE_CLIP_EMPTY`
- `DRIVEZONE_CRS_UNKNOWN`
- `NEXT_INTERSECTION_NOT_FOUND_DEG3`
- `NEXT_INTERSECTION_DEG_TOO_LOW_SKIPPED`
- `MULTI_BRANCH_TODO`
- `ANCHOR_GAP_UNSTABLE`
- `SEQUENTIAL_ORDER_VIOLATION`
- `POINTCLOUD_CRS_UNKNOWN_UNUSABLE`
- `POINTCLOUD_MISSING_OR_UNUSABLE`

## 9. 门禁
Hard：
- required outputs present
- `seed_total > 0`
- `hard_breakpoint_count == 0`

Soft（按 mode 阈值）：
- `anchor_found_ratio >= min_anchor_found_ratio_*`
- `no_trigger_count <= no_trigger_count_max_*`
- `scan_exceed_200m_count <= scan_exceed_200m_count_max_*`
