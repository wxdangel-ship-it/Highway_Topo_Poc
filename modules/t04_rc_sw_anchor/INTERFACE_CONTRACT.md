# t04_rc_sw_anchor - INTERFACE_CONTRACT

## 1. 目标与范围
- 模块 ID：`t04_rc_sw_anchor`
- 目标：识别 `merge/diverge` 锚点并输出 `intersection_l_opt`。
- 范围：
  - `kind bit3/bit4`（merge/diverge）走既有主流程
  - `kind bit16(65536)` 走 K16 专用横截线流程
  - 其他类型失败并打断点

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

### 2.4 Patch-only 输入入口（脚本补充）
- 脚本：`scripts/run_t04_patch_auto_nodes.sh`
- 输入：`PATCH_DIR`（可选 `KIND_MASK`，默认 `65560=8|16|65536`）
- 行为：
  - 从 `PATCH_DIR/Vector/RCSDNode.geojson`（fallback `Node.geojson`）自动发现节点。
  - 发现结果写入 `focus_node_ids_resolved.txt/json` 后，调用既有 `mode=global_focus`。
  - 节点为空时 fail-closed（非 0 退出），并写 `node_discovery_report.json` 解释原因。
- 说明：该脚本仅改变“入口与节点来源”，不改变模块核心算法链路。

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
- 多分支 `N>2` 时：
  - 横截方向仍由最大夹角 pair 的法向确定；
  - 用所有有效分支匹配点在横截轴上的 `v_min/v_max` 形成 span，并两端外扩 `multibranch_span_extra_m`；
  - 基于该扫描线统计 `pieces_count(s)` 并提取多事件。

### 5.3 split 定义
- `pieces = SEG(s) ∩ DriveZone` 的线段片段（过滤 `< min_piece_len_m`）。
- 最早满足 `len(pieces) >= 2` 的 `s*` 为分割位置。
- 若存在 divstrip 参考点，则优先在 `divstrip_preferred_window_m` 窗口内选择 `s*`（无则回退最早 split）。
- stop 范围内无 `s*`：`status=fail` + `DRIVEZONE_SPLIT_NOT_FOUND`。

### 5.4 stop（hard-only）
- 仅允许：从当前 node 沿扫描方向，在 RCSDRoad 拓扑联通可达的下一个 `degree>=3` 节点。
- 找不到则 `stop_dist=scan_max_limit_m`，`stop_reason=next_intersection_not_found_deg3`。
- 禁止几何近邻 fallback（`disable_geometric_stop_fallback=true`）。
- 连续链节点额外规则：
  - 不使用“自身节点 stop”作为最终边界。
  - 使用链级 stop 上界：`min(scan_max_limit_m, max(component_default_stop_dist_m))`。
  - 其中 `component_default_stop_dist_m` 为组件内各节点按本节默认规则计算的 stop 距离。

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
  - 结果校验阶段对连续边执行相对顺序校验：下游节点 `abs_s` 不得小于上游节点；若违反则下游节点置 fail 并打 `SEQUENTIAL_ORDER_VIOLATION`。
- `diverge->merge` 合并：
  - 仅允许“先分后合”（`diverge->merge` 且 `offset(diverge)<offset(merge)`）共用横截线。
  - 相邻边上、merge 的主要前驱为该 diverge，且两条 `crossline_opt` 几何相交或近邻（`distance<=continuous_merge_geom_tol_m`）时允许合并。
  - `continuous_merge_max_gap_m` 与 window 交集仅保留诊断，不作为阻断门槛。

### 5.7 异常分支：reverse tip/ref_s（10m）
- 仅在以下条件触发反向搜索：
  - A) 默认方向 `forward_divstrip_ref` 与 `forward_drivezone_split` 均缺失
  - B) `SEG(0)` 与 divstrip 相交且 `node->divstrip` 距离 `<= divstrip_hit_tol_m`（`untrusted_divstrip_at_node`）
  - C) 默认方向命中 `divstrip_first_hit` 且不存在 `forward_drivezone_split`（`first_hit_no_split`，分歧/合流均适用）
- 反向范围：`s ∈ [-reverse_tip_max_m, 0]`，默认 `10m`
- 反向仲裁与正向一致：divstrip 优先，drivezone 次之；禁止 drivezone 远于 divstrip 覆盖近 divstrip
- 最终位置窗口按场景区分：
  - 常规（非 reverse）：靠近节点 1m（`ref_s>=0 -> [ref_s-1m, ref_s]`；`ref_s<0 -> [ref_s, ref_s+1m]`）
  - 异常 reverse：远离节点 1m（`ref_s>=0 -> [ref_s, ref_s+1m]`；`ref_s<0 -> [ref_s-1m, ref_s]`）
- 反向无 split（`found_split=false`）且仍与 divstrip 相交时：
  - 沿远离节点方向继续搜索到 `reverse_tip_max_m`
  - 若仍无非相交候选，硬失败 `DIVSTRIP_NON_INTERSECT_NOT_FOUND`

### 5.8 多分支（N>2）事件提取与主结果选择
- 启用条件：
  - diverge：按方向过滤后的有效 outgoing 分支数 `N>2`
  - merge：按方向过滤后的有效 incoming 分支数 `N>2`
  - 方向过滤：仅 `direction in {2,3}` 计入；`0/1` 忽略并计数诊断
- 事件提取：
  - 正向扫描：`s ∈ [0, stop_dist]`
  - 反向扫描：`s ∈ [-multibranch_reverse_max_m, 0]`
  - 事件定义：`pieces_count` 从 `k` 增到 `k+Δ` 时，按方案B在同一 `s` 记录 `Δ` 个事件（受 `expected_events=N-1` 截断）
- 主结果选择（方案X）：
  - 默认 `forward_first`：取正向最早事件
  - 若正反两侧均有事件：取反向最远事件（`reverse_farthest_abnormal`，即最负 `s`）
  - 若仅反向有事件：`reverse_farthest_fallback`
- 输出分层：
  - `intersection_l_opt`：仅主结果一条线
  - `intersection_l_multi`：输出所有事件线（含 `forward/reverse`）

### 5.9 K16（kind bit16=65536）专用流程
- K16 road 约束：
  - 节点关联 road（`snodeid==nodeid or enodeid==nodeid`）必须恰好 1 条
  - 且 `road.direction in {2,3}`
  - 不满足时硬失败：
    - `K16_ROAD_NOT_UNIQUE`
    - `K16_ROAD_DIR_UNSUPPORTED`
- 搜索方向：
  - `direction=2` 有效方向 `snodeid->enodeid`
  - `direction=3` 有效方向 `enodeid->snodeid`
  - node 在有效起点：`forward`
  - node 在有效终点：`reverse`
- 扫描：
  - 初始横截线半长 `10m`（总长 `20m`）
  - 固定搜索范围 `10m`，步长 `k16_step_m`（默认 `0.5m`）
  - 命中条件：`CROSS(s) ∩ DriveZone_union != empty`
- 命中后输出：
  - first-hit 后沿搜索方向继续前探 `k16_refine_ahead_m`（默认 `5.0m`），步长 `k16_refine_step_m`
  - 候选优先级：线长更大 > `pieces_count` 更少 > 更接近 first-hit
  - 搜索线半长固定 `10m`；输出线使用 `output_cross_half_len_m` 进行几何重建并截到当前 piece 边界（不依赖阈值触发补边）
  - 在与 `CROSS(s_found)` 交集的片段中优先选包含 center 的 piece，否则选离 center 最近 piece
  - 复用连续线贴边扩展口径，输出单条连续 LineString
- 失败：
  - `10m` 内无交集：`K16_DRIVEZONE_NOT_REACHED`（hard）
  - 记录 `k16_min_dist_cross_to_drivezone_m` 与 `k16_s_best_m`

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
- `continuous_tip_projection_min_abs_m`：默认 `1.0`（连续后继节点在 `tip_projection + no_split` 且 near-zero 时的最小 |s| 门槛）
- `reverse_tip_max_m`：默认 `10.0`（反向 tip/ref 搜索范围）
- `multibranch_enable`：默认 `true`（仅 `N>2` 生效）
- `multibranch_span_extra_m`：默认 `10.0`（多分支 span 两端外扩）
- `multibranch_reverse_max_m`：默认 `10.0`（多分支反向扫描范围）
- `k16_step_m`：默认 `0.5`（K16 10m 扫描步长）
- `k16_refine_enable`：默认 `true`（K16 first-hit 后前探稳定化）
- `k16_refine_ahead_m`：默认 `5.0`（K16 前探距离）
- `k16_refine_step_m`：默认 `0.5`（K16 前探步长）
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
- `intersection_l_multi.geojson`
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

Patch-only 脚本附加审计文件（可选）：
- `focus_node_ids_resolved.txt`
- `focus_node_ids_resolved.json`
- `node_discovery_report.json`
- `auto_nodes.meta.json`

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
  - `reverse_tip_attempted/reverse_tip_used/reverse_trigger/reverse_search_max_m`
  - `ref_s_forward_m/ref_s_reverse_m/ref_s_final_m`
  - `position_source_forward/position_source_reverse/position_source_final`
  - `untrusted_divstrip_at_node/node_to_divstrip_m_at_s0/seg0_intersects_divstrip`
  - `multibranch_enabled/multibranch_N/multibranch_expected_events`
  - `split_events_forward/split_events_reverse`
  - `s_main_m/main_pick_source/abnormal_two_sided`
  - `span_extra_m/direction_filter_applied/branches_used_count/branches_ignored_due_to_direction`
  - `s_drivezone_split_first_m`
  - `k16_enabled/k16_road_id/k16_road_dir/k16_endpoint_role/k16_search_dir`
  - `k16_search_max_m/k16_step_m/k16_cross_half_len_m`
  - `k16_output_cross_half_len_m`
  - `k16_s_found_m/k16_s_best_m/k16_found`
  - `k16_min_dist_cross_to_drivezone_m/k16_break_reason`
  - `k16_refine_enable/k16_refine_ahead_m/k16_refine_step_m`
  - `k16_first_hit_s_m/k16_refined_used/k16_s_refined_m`
  - `k16_first_hit_len_m/k16_refined_len_m/k16_refine_candidate_count`

`intersection_l_multi.geojson`：
- 每个 split-event 1 条 feature，properties 至少包含：
  - `nodeid/kind/anchor_type`
  - `event_idx/event_s_m/event_dir`
  - `pieces_count_at_event/expected_events`

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
- `REVERSE_TIP_ATTEMPTED`
- `REVERSE_TIP_USED`
- `REVERSE_TIP_NOT_FOUND`
- `UNTRUSTED_DIVSTRIP_AT_NODE`
- `POINTCLOUD_CRS_UNKNOWN_UNUSABLE`
- `POINTCLOUD_MISSING_OR_UNUSABLE`
- `K16_ROAD_NOT_UNIQUE`
- `K16_ROAD_DIR_UNSUPPORTED`
- `K16_DRIVEZONE_NOT_REACHED`

## 9. 门禁
Hard：
- required outputs present
- `seed_total > 0`
- `hard_breakpoint_count == 0`

Soft（按 mode 阈值）：
- `anchor_found_ratio >= min_anchor_found_ratio_*`
- `no_trigger_count <= no_trigger_count_max_*`
- `scan_exceed_200m_count <= scan_exceed_200m_count_max_*`
