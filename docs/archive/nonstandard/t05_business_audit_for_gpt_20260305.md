# T05 业务审计（GPT 同步版）
更新时间：2026-03-05  
代码基线：`d66c6e6`  
模块：`src/highway_topo_poc/modules/t05_topology_between_rc`

## 1. 业务目标（What）
T05 的业务目标是：  
在单个 patch 内，识别相邻 RC 节点对（`src_nodeid -> dst_nodeid`），生成可落盘的有向 `Road` 中心线，并给出可门禁的质量判定（`overall_pass`、hard/soft breakpoints）。

T05 不是“只画线”，而是“拓扑+几何+门禁”一体化：
- 拓扑：谁与谁相邻、是否经过非 RC、是否 unresolved。
- 几何：中心线是否合理、端点是否稳定、是否穿越禁区。
- 门禁：按 hard/soft 规则输出可审计证据。

## 2. 输入契约（Business Contract）
入口：`run.py -> pipeline.run_patch -> io.load_patch_inputs`

### 2.1 Required 输入（硬依赖）
- `Vector/intersection_l.geojson`
- `Vector/DriveZone.geojson`
- `Traj/**/raw_dat_pose.geojson`

硬失败条件（InputDataError）：
- `intersection_l_missing`
- `drivezone_missing`
- `drivezone_empty`
- GeoJSON 解析失败 / 非 FeatureCollection / CRS 无法解析

### 2.2 Optional 输入（软依赖）
- `Vector/LaneBoundary.geojson`
- `Vector/DivStripZone.geojson`
- `Vector/RCSDNode.geojson`（或 `Node.geojson`）
- `PointCloud/*.las|*.laz`（默认关闭）

软依赖策略：可缺省、可跳过，不应因为 optional 数据不可用直接导致 patch 崩溃。

## 3. CRS 业务口径（必须理解）
统一计算坐标系：`EPSG:3857`。

### 3.1 Required CRS 处理
- 若声明 CRS，按声明归一化使用。
- 若缺失 CRS，按坐标量级推断：
  - `|x|<=180 && |y|<=90` -> `EPSG:4326`
  - 否则优先投影 CRS（倾向 `EPSG:3857` 或参考 CRS）
- `DriveZone` 缺 CRS 且与 `intersection` 推断类型冲突时，自动对齐到 `intersection` 类型（记录 `drivezone_crs_alignment_reason`）。
- `Traj` 缺 CRS 推断时会锚定 `intersection` 类型，减少输入间 CRS 漂移。

### 3.2 Optional CRS 处理
`fix_optional_geojson_crs(...)` 统一策略：
1. 有声明 CRS：归一化；必要时重投影。
2. 缺 CRS 且可抽样：
   - lonlat -> 视为 `EPSG:4326`，重投影到 patch CRS
   - projected -> 继承 patch CRS
3. 空几何/不可抽样 -> `skipped`（不参与后续）

观测字段（metrics/summary/debug）：
- `lane_boundary_used`
- `lane_boundary_crs_method`
- `lane_boundary_src_crs_name`
- `lane_boundary_crs_name_final`（最终统一口径，当前为 `EPSG:3857`）
- `lane_boundary_skipped_reason`
- `drivezone_src_crs` / `drivezone_crs_inferred` / `drivezone_crs_alignment_reason`
- `divstrip_crs_method` / `divstrip_used` / `divstrip_skipped_reason`

## 4. 业务流程分层（How）
## 4.1 Step0：横截面预处理与 gate 准备
- 构建 `xsec_map`（intersection 线）
- 对横截面做截断与候选选择（含 passable/gore 影响）
- 输出 xsec 统计（如 `n_cross_distance_gate_reject`）

## 4.2 Step1：拓扑相邻识别与走廊策略
- crossing 事件抽取
- stitch 图构建与邻接搜索（pass1/pass2）
- unresolved 事件收集（`UNRESOLVED_NEIGHBOR`）
- per-pair 走廊策略（merge/diverge/general）
- 若策略不支持（如 merge->diverge）直接 hard
- 若无候选通道，`CENTER_ESTIMATE_EMPTY` 或 `NO_ADJACENT_PAIR_AFTER_PASS2`

## 4.3 Step2：候选几何生成与门禁
按 cluster 生成候选 road：
- shape_ref（优先 LaneBoundary 路径，失败则 fallback）
- traj surface 构建（slice + quantile + endcap + xsec_support）
- `traj_surface_enforced` 判定
- enforced 失败 -> soft `TRAJ_SURFACE_INSUFFICIENT`
- enforced 通过但 in_ratio/端点不满足 -> hard `ROAD_OUTSIDE_TRAJ_SURFACE`
- DivStrip/DriveZone 门禁：
  - 穿越 DivStrip -> hard `ROAD_INTERSECTS_DIVSTRIP`
  - 超出 DriveZone 或端点不在内 -> hard `ROAD_OUTSIDE_DRIVEZONE`
- 桥接段过长且高风险 -> hard `BRIDGE_SEGMENT_TOO_LONG`

## 4.4 Step3：候选排序与最终收敛
- 候选排序关键：`has_geometry -> feasible -> score -> in_ratio -> max_segment -> support`
- 选中 1 条写入 `Road.geojson`（兼容写 `RCSDRoad.geojson`）
- 聚合 hard/soft breakpoints
- 计算 `overall_pass`

## 5. `overall_pass=false` 的业务含义
`overall_pass=false` 不等于程序崩溃；多数情况下表示“规则判定失败但产物已输出”。

判定逻辑：
- 只要存在 hard breakpoints，`overall_pass=false`
- 即使无 hard，但端点锚点距离明显跑飞（> `3 * XSEC_ENDPOINT_MAX_DIST_M`）也会置 false

## 6. 异常语义速查（给业务/GPT）
## 6.1 常见 hard
- `NON_RC_IN_BETWEEN`：路径中间使用了非 RC 节点
- `CENTER_ESTIMATE_EMPTY`：中心线无法可靠生成
- `ROAD_OUTSIDE_TRAJ_SURFACE`：轨迹表面 gate 未通过（in_ratio 或端点约束失败）
- `ROAD_INTERSECTS_DIVSTRIP`：道路与禁行隔离区相交
- `ROAD_OUTSIDE_DRIVEZONE`：道路或端点越出可行驶区
- `BRIDGE_SEGMENT_TOO_LONG`：存在异常长桥接段且风险高
- `NO_ADJACENT_PAIR_AFTER_PASS2`：两轮邻接搜索后仍无可用相邻对

## 6.2 常见 soft
- `UNRESOLVED_NEIGHBOR`：邻接搜索未闭合
- `TRAJ_SURFACE_INSUFFICIENT`：轨迹表面证据不足
- `TRAJ_SURFACE_GAP`：轨迹表面存在连续性缺口
- `LOW_SUPPORT`：支持轨迹数偏低
- `SPARSE_SURFACE_POINTS`：采样覆盖不足
- `NO_LB_CONTINUOUS` / `NO_LB_CONTINUOUS_PATH`：LaneBoundary 连续路径不可用

## 7. 输出契约（What Produced）
每 patch 输出：
- `Road.geojson`
- `RCSDRoad.geojson`
- `metrics.json`
- `intervals.json`
- `gate.json`
- `summary.txt`
- `progress.ndjson`
- `debug/*`（`DEBUG_DUMP=1` 时）

关键认知：
- 有输出 + `overall_pass=false` = “可审计失败样本”，不是“执行失败”。
- 执行失败通常表现为 `summary.txt` 中 `error.type/error.message/traceback_top30`。

## 8. 当前边界与风险（审计结论）
1. T05 已具备完整业务闭环，且可输出高可解释证据。  
2. 当前主要风险不在“能否跑完”，而在“规则触发率是否符合业务预期”：  
   - `UNRESOLVED_NEIGHBOR` 高发场景  
   - `ROAD_OUTSIDE_TRAJ_SURFACE` 与 `ROAD_OUTSIDE_DRIVEZONE` 的阈值敏感性  
3. CRS 鲁棒性已增强（required 推断 + optional 跳过），但仍需用真实内网 patch 持续校准推断策略。

---

## 9. 可直接喂给 GPT 的同步块（复制即用）
你现在是 T05 业务审计助手。请按以下事实理解并回答：

1) T05 目标：在 patch 内生成 RC 节点间有向 Road 中心线，并输出 hard/soft 门禁证据；不仅是几何生成，还包含拓扑相邻识别与质量判定。  
2) Required 输入：intersection_l / DriveZone / Traj；DriveZone 缺失或空面必须硬失败。  
3) Optional 输入：LaneBoundary / DivStripZone / Node / PointCloud；optional 数据不可用应走跳过/fallback，不应导致 patch 崩溃。  
4) 统一计算 CRS 为 EPSG:3857；缺 CRS 时会做推断与对齐；LaneBoundary/DivStripZone 支持“推断-重投影-跳过”链路，并在 metrics/debug 记录 method/used/skipped_reason。  
5) `overall_pass=false` 常见含义是“业务规则 hard 触发”，不是程序异常；程序异常看 `InputDataError` 与 traceback。  
6) 重点 hard reason：NON_RC_IN_BETWEEN / CENTER_ESTIMATE_EMPTY / ROAD_OUTSIDE_TRAJ_SURFACE / ROAD_INTERSECTS_DIVSTRIP / ROAD_OUTSIDE_DRIVEZONE / BRIDGE_SEGMENT_TOO_LONG。  
7) 分析 patch 时，优先顺序：  
   A. 先判定是“执行失败”还是“业务失败”；  
   B. 再看 CRS 指标是否一致；  
   C. 再看 hard_breakpoints_topk 的 reason+hint；  
   D. 最后再讨论阈值与策略调参，不要先改业务口径。  
