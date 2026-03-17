# T05 模块业务实现逻辑总览（当前代码基线）

更新时间：2026-02-27  
代码基线：`main`（当前合入后）

## 1. 模块定位

`t05_topology_between_rc` 的目标是：在单个 patch 内，基于轨迹、`intersection_l`、`LaneBoundary`、点云与 `DivStripZone`，生成相邻 RC 路口之间的有向 `Road` 中心线，并输出可门禁的质量指标。

核心边界：

- `stitch` 仅用于拓扑相邻识别，不进入几何输出。
- `LaneBoundary` 用于骨架形态（支持图路径多段串联）。
- 点云用于中心偏移估计与稳定化。
- `DivStripZone` 作为非路面硬障碍。

---

## 2. 输入与 CRS 口径

实现入口：`run.py -> pipeline.run_patch -> pipeline._run_patch_core`

主要输入（每 patch）：

- `Vector/intersection_l.geojson`
- `Vector/LaneBoundary.geojson`
- `Vector/DivStripZone.geojson`（可缺省）
- `Traj/**/raw_dat_pose.geojson`
- `PointCloud/merged_cleaned_classified_3857.laz`（优先）

CRS 规则（代码已固化）：

- 所有 GeoJSON 必须声明 CRS。
- 支持 `CRS84/OGC:1.3:CRS84/urn:...:CRS84`，归一化为 `EPSG:4326` 后再投影到 `EPSG:3857`。
- 所有几何计算统一在 `EPSG:3857`。
- 坐标转换使用 `Transformer(..., always_xy=True)`。

---

## 3. 主流程（pipeline）

### 3.1 相邻路口识别（拓扑阶段）

1. 抽取轨迹穿越事件（`extract_crossing_events`）
2. 构建轨迹前向图 + stitch 边（`build_pair_supports`）
3. 运行邻接搜索 pass1；必要时运行 pass2（固定 fallback 参数）
4. 产出 `supports[(src,dst)]` 与 `UNRESOLVED_NEIGHBOR` 断点

pass2 当前触发条件：

- pass1 无 pair；或
- pass1 `stitch_accept_count=0` 且 unresolved 过高（新增阈值规则）

并且 pass1/pass2 会按质量键择优（pair 数、支持事件数、stitch 接受数、unresolved 数）。

### 3.2 候选通道与候选路段

对每个 `(src,dst)`：

1. 按 multi-road 聚类得到 cluster 候选（最多 3 个）
2. 每个 cluster 先构建 `traj_surface` hint（含 enforced 判定）
3. 对通过轻筛的 cluster 计算重路径（中心线生成 + gate）
4. 候选评分并排序，选择 1 条 `selected` 输出

### 3.3 输出收敛

- 写 `Road.geojson`（并兼容写 `RCSDRoad.geojson`）
- 写 `metrics.json` / `intervals.json` / `gate.json` / `summary.txt`
- `road_count` 与 `Road.features` 强一致（已修复）

---

## 4. 关键算法逻辑

## 4.1 穿越事件与去重

- 轨迹段与横截线采用距离门控 + `nearest_points` 求 crossing。
- 同一 `traj_id + nodeid` 多次命中，按更优 crossing 保留 1 条。
- 记录 `raw_hit / dedup_drop / distance_gate_reject` 等计数。

## 4.2 Stitch 图（仅拓扑）

图节点：轨迹采样点 + 起终点 + crossing 节点。  
图边：

- 轨迹前进边（按 station 增长）
- stitch 边（尾段点 -> 其他轨迹采样点，距离/角度/前向过滤）

路径重建时，几何仅保留真实轨迹段，stitch 边不生成几何段。

## 4.3 Multi-road 聚类

- 基于支持路径中点径向分布做 1D 聚类。
- 识别多通道时保留 `MULTI_ROAD_SAME_PAIR` 硬异常，同时给出主簇信息（`cluster_count/main_cluster_ratio/...`）。

## 4.4 shape_ref（LaneBoundary 图路径优先）

优先使用 `LaneBoundary` 图最短路：

- 端点 snap 建图
- 支持 surface 约束（enforced 时：外侧比例超阈值边过滤 + outside 惩罚）
- 支持 `DivStripZone` 硬障碍（与 barrier 相交边直接禁用）

失败时 fallback 到点云骨架线（不做断口直连补洞）。

## 4.5 点云中心偏移

- 点云读取按 support 包围盒 ROI 裁剪，并缓存。
- 默认仅使用 `classification=2`（地面），`class=12` 不纳入 `allowed_classes`。
- 沿 shape_ref 采样，横截窗口统计 `P05/P95` 求中心偏移。
- 叠加两级平滑 + 单步变化限制。

## 4.6 端点稳定化与趋势延伸

- 先做 stable section 判定（`is_gore_tip/is_expanded/stable_s`）
- 再做端点趋势投影到横截有效片段（含 gore 剔除、surface 支撑优先）
- 使用 anchor window 限定端点 station 搜索范围
- 端部连接段加入长度约束（新增），异常则 `HARD_ENDPOINT_LOCAL`

> 说明：`intersection_l` 当前主要作为锚点邻域参考；当趋势构造失败时仍有裁剪 fallback（`clip_line_to_cross_sections`）。

## 4.7 线内 clamp 与 divstrip 硬约束

- 中心线可被 clamp 到 traj_surface（超出点回拉）
- 若 clamp 后仍与 `divstrip` 相交，优先回退到轴线；仍相交则硬失败 `ROAD_INTERSECTS_DIVSTRIP`

## 4.8 Traj surface 构建与 gate

构建口径（冻结）：

- 沿 ref_axis 切片，分位数 `P02/P98`
- 分级切片窗 `2->5->10m`
- `buffer(1m)` 后扣除 `DivStripZone`
- 端帽再聚类抑制爆宽，并做 width clamp

enforced 条件（必须同时满足）：

- `valid_slices >= 2`
- `slice_valid_ratio` 达阈值
- `covered_length_ratio` 达阈值（且不低于 enforce 阈值）
- `src/dst endcap_valid_ratio` 达阈值
- `xsec_support_src/dst` 均可用
- `unique_traj_count` 达阈值
- surface 非空且面积 > 0

若不足：`TRAJ_SURFACE_INSUFFICIENT`（软）  
若 enforced 后不满足 `in_ratio>=0.95` 或端点不在 surface：`ROAD_OUTSIDE_TRAJ_SURFACE`（硬）

---

## 5. 异常体系

硬异常（触发即 `overall_pass=false`，但尽量输出结果）：

- `MULTI_ROAD_SAME_PAIR`
- `NON_RC_IN_BETWEEN`
- `CENTER_ESTIMATE_EMPTY`
- `ENDPOINT_NOT_ON_XSEC`
- `ENDPOINT_OUT_OF_LOCAL_XSEC_NEIGHBORHOOD`
- `BRIDGE_SEGMENT_TOO_LONG`
- `ROAD_INTERSECTS_DIVSTRIP`
- `ROAD_OUTSIDE_TRAJ_SURFACE`
- `NO_ADJACENT_PAIR_AFTER_PASS2`

软断点（诊断为主）：

- `LOW_SUPPORT`
- `SPARSE_SURFACE_POINTS`
- `NO_LB_CONTINUOUS` / `NO_LB_CONTINUOUS_PATH`
- `WIGGLY_CENTERLINE`
- `UNRESOLVED_NEIGHBOR`
- `NO_STABLE_SECTION`
- `TRAJ_SURFACE_INSUFFICIENT`
- `TRAJ_SURFACE_GAP`
- 以及 crossing/endcap 相关软断点

---

## 6. 输出契约（当前实现）

每 patch 目录下：

- `Road.geojson`（主输出）
- `RCSDRoad.geojson`（兼容输出）
- `metrics.json`
- `intervals.json`
- `gate.json`
- `summary.txt`
- `debug/*.geojson`（`DEBUG_DUMP=1`）

`Road.properties` 当前包含：

- 基础拓扑：`road_id/src_nodeid/dst_nodeid/direction/neighbor_search_pass`
- 支持度：`support_traj_count/support_event_count/repr_traj_ids/stitch_hops_*`
- 几何质量：`length_m/max_segment_m/seg_index0_len_m/max_turn_deg_per_10m/conf`
- 通道信息：`candidate_cluster_id/chosen_cluster_id/cluster_count/main_cluster_ratio`
- surface 相关：`traj_surface_enforced/traj_in_ratio/traj_in_ratio_est/endpoint_in_traj_surface_*`
- 端点与稳定化：`endpoint_* / s_anchor_* / s_end_* / fallback_mode_* / xsec_support_*`
- DivStrip：`divstrip_intersect_len_m`
- gate 标记：`hard_anomaly/hard_reasons/soft_issue_flags`

---

## 7. 性能与可观测性

性能加速：

- 点云 ROI + `.npz` 缓存
- traj surface 结果缓存
- 切片计算向量化（`searchsorted + quantile`）

计时指标（`metrics.json`）：

- `t_load_traj`
- `t_load_pointcloud`
- `t_build_traj_projection`
- `t_build_surfaces_total`
- `t_build_lane_graph`
- `t_shortest_path_total`
- `t_centerline_offset`
- `t_gate_in_ratio`
- `t_debug_dump`

---

## 8. 内网执行（当前脚本）

脚本：`scripts/wsl_verify_t05.sh`

- 默认 `DEBUG_DUMP=0`（快模式）
- `--debug` 可开启 debug 落盘
- 默认 patch：`2855795596723843 2855832070394132 2855832875697813`

示例：

```bash
bash scripts/wsl_verify_t05.sh 2855795596723843 2855832070394132 2855832875697813
bash scripts/wsl_verify_t05.sh --debug 2855795596723843 2855832070394132 2855832875697813
```

---

## 9. 当前能力边界（用于与 GPT 对齐）

1. 模块已具备完整的“拓扑识别 -> 多通道候选 -> 几何生成 -> gate/门禁 -> 证据输出”闭环。  
2. `road_count/features`、debug 落盘、CRS84、DivStrip 硬约束、traj surface enforced/insufficient 分支已工程化。  
3. 最近补丁已增强：
   - pass2 自动触发条件（不再仅 `supports=0`）
   - unresolved stitch 诊断口径（探索域统计）
   - 端点到 core 的重投影重试与连接长度硬约束（抑制 `seg_index=0` 长桥接）
4. 仍需重点关注真实数据表现：
   - `UNRESOLVED_NEIGHBOR` 高发（尤其 `stitch_candidates` 低）
   - 多通道错配导致的路段跑偏
   - enforced/insufficient 边界场景下的端点退化稳定性

