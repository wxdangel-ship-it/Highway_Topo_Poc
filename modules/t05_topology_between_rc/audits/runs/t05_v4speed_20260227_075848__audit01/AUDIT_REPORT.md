# AUDIT_REPORT.md

## 4.1 Executive Summary（Top3 根因）
- 根因1（最主要）：`traj_surface` 调试落盘与 gate 使用对象不一致。debug 层会把 `surface` 强制拆成线边界写出（`MultiLineString/area=0`），而 gate 在内存里用 `surface` 做 `intersection` 与端点判定，导致“看图像是线，门禁却有 in_ratio”的认知冲突。证据：`pipeline.py:2042-2061`, `pipeline.py:2115-2121`, `pipeline.py:1695-1704`。
- 根因2：`traj_surface_k` 的纵向轴不是通道骨架（LB path/centerline），而是 `src_xsec` 到 `dst_xsec` 的直线；再叠加 `slice_half_win=2m` 的窄窗，容易只在局部 station 有效，出现“surface 只铺一小段”。证据：`pipeline.py:1471-1478`, `pipeline.py:1270-1308`, `pipeline.py:1339-1344`。
- 根因3：端点趋势替换后没有再做“按端点投影的 substring 结构化裁剪”，若端点片段选错通道或离 anchor 过远，首段可能形成 `seg_index=0` 长跳连。证据：`geometry.py:1208-1212`（前置 substring）, `geometry.py:1608-1747`（端点重构）, `pipeline.py:1948-1958`（最终才检测桥接超长）。

补充（来自 AUDIT_BRIEF）：`t05_v4speed_20260227_075848` 观测到 DivStripZone CRS84、`traj_surface_best` 为 `MultiLineString`、`max_segment_m=156.9(seg_index=0)`，与上述代码路径高度一致（`T05_AUDIT_BRIEF.md` 第 2 节）。

---

## 4.2 Evidence Table（证据→代码位置）

| Evidence | Where in code (file:line) | Why it matters | Hypothesis |
|---|---|---|---|
| GeoJSON CRS84 归一化入口 | `io.py:808-826`, `io.py:829-847` | 明确支持 `CRS84/OGC:1.3:CRS84/URN...CRS84 -> EPSG:4326` | 若仍见 CRS84 影响，可能是旧版本运行或外部脚本直接读原始文件 |
| DivStripZone CRS 校验+投影到3857 | `io.py:251-254`, `io.py:667-695` | DivStrip 读取后进入 metric 几何 | 代码层本应生效；异常多来自数据/版本/外部对比口径 |
| gore mask 在 surface 构建中生效 | `pipeline.py:1287-1308`, `pipeline.py:1333-1336` | traj_surface 会剔除 gore 点并做 difference | gore 扣除并非缺失，但可能导致面域碎化 |
| gore mask 在中心线点云统计中生效 | `geometry.py:3119-3175` | 点云有效面与宽度/offset 统计扣除导流带 | 端点偏移不是“完全没扣 gore”，更可能是通道选择或投影片段问题 |
| traj_surface 参考轴是 src-dst 直线 | `pipeline.py:1471-1478` | 未使用 LB path/shape_ref 做 station 轴 | 曲线或偏航路段会只命中局部切片 |
| slice 窄窗 + 分位数规则 | `pipeline.py:1270-1273`, `pipeline.py:1305-1314` | `half_win=2m` 且 P02/P98，轨迹偏离就失效 | 造成 valid_slices 少、covered_length 低、surface 短 |
| traj 点收集粒度 | `pipeline.py:1150-1172` | 以 `support_traj_ids` 收全轨迹点，不按 A→B 子段裁切 | 与直线 ref_line 叠加后，表面构建更依赖局部偶然重叠 |
| gate 使用对象 | `pipeline.py:1685-1704`, `pipeline.py:1767-1790` | in_ratio/endpoint_in_surface 真正来自 `_traj_surface_geom_metric` | debug 与 gate 不一致时，以内存对象为准 |
| debug 写 surface 的方式 | `pipeline.py:2115-2121`, `pipeline.py:2042-2061` | Polygon 会被转成 boundary 线并输出 | 导致 debug 文件看起来是 `MultiLineString` |
| multi-road 按 k 全链路构建 | `pipeline.py:605-623`, `pipeline.py:664-684`, `pipeline.py:718-730` | cluster_k -> surface_k -> road_k -> score 选择 | 设计上已做 k 绑定，但仍可能因 surface 质量差误选 |
| LB path 表面约束 | `geometry.py:2709-2790`, `geometry.py:2894-2914` | enforced 时过滤“离开 surface 太多”的边/节点 | 若 surface 本身偏/短，会反向把 LB path 拉偏 |
| 端点投影支持片段 | `geometry.py:1922-1947`, `geometry.py:1861-1919` | enforced 时在 `xsec_valid ∩ surface` 选片段 | 若 `xsec_support` 空，会回退到非 surface 片段策略 |
| 前置 substring 存在 | `geometry.py:1208-1212`, `geometry.py:2998-3031` | shape_ref 已按 xsec 最近点裁剪 | 但不是“按最终端点投影”裁剪 |
| 趋势替换重建线 | `geometry.py:1608-1747` | 直接拼 `P_end -> mid -> anchor -> ...` | 首段长跳连可在此产生 |
| 桥接超长只在末端检测 | `pipeline.py:1948-1958`, `pipeline.py:753-769` | 发现问题但不修正几何根因 | 可解释 seg_index=0 长段被 hard 拦截 |

---

## 4.3 Call Chain（从 run.py 到问题点）

- `run.py:118-213` `main()`
  - 解析参数，创建 `run_dir`，调用 `run_patch(...)`
- `pipeline.py:190-223` `run_patch(...)`
  - `load_patch_inputs(...)`
  - `_run_patch_core(...)`
- `io.py:212-299` `load_patch_inputs(...)`
  - `_require_geojson_crs(...)`（CRS 归一）
  - `_make_transformer(..., EPSG:3857)`
  - `_extract_polygon_union(...)` 得 `divstrip_zone_metric`
- `pipeline.py:255-540` `_run_patch_core(...)`
  - crossing + stitch + pair_support（邻接拓扑）
- `pipeline.py:605-730` multi-road cluster 循环
  - `_subset_support_by_cluster(...)`
  - `_build_traj_surface_hint_for_cluster(...)`
  - `_evaluate_candidate_road(...)`
  - 候选评分 `_candidate_sort_key(...)` 选 k*
- `pipeline.py:1434-1571` `_build_traj_surface_hint_for_cluster(...)`
  - `_collect_support_traj_points(...)`
  - `_build_traj_surface_from_refline(...)`
- `geometry.py:1087-1567` `estimate_centerline(...)`
  - `_choose_shape_ref_with_graph(...)`
  - `_shape_ref_substring_by_xsecs(...)`
  - 点云 offset/stable section/trend projection
- `pipeline.py:1574-1792` `_eval_traj_surface_gate(...)`
  - `in_ratio` + `endpoint_in_surface` 硬门禁
- `pipeline.py:2105-2189` `_collect_debug_layers_for_selected(...)`
  - debug surface 写 boundary 线

---

## 4.4 Root Cause Analysis（逐条回答 Q1–Q6）

### Q1. t05 中“道路面”在代码里有哪些口径？
**结论：Yes（存在 2 套主口径 + 1 套约束面）**
- 点云有效面（用于几何中心估计，不是 gate 主体）：`pipeline.py:1010-1096` + `io.py:309-400`（class 过滤，默认 class=2），在 `geometry.py:3119-3175`, `geometry.py:3579-3643` 用于 offset/端点居中指标。
- 轨迹面域 `traj_surface_metric`（用于约束与门禁）：`pipeline.py:1262-1354`, `pipeline.py:1434-1571` 构建，`pipeline.py:1574-1792` gate 使用。
- 导流带约束 `gore_zone_metric`：读取与投影在 `io.py:251-254, 667-695`，并在点云统计、traj_surface、端点片段选择中扣除。
**影响范围**：如果 traj_surface 构建退化/错配，Road 可由点云中心线生成但会被 gate 判 `ROAD_OUTSIDE_TRAJ_SURFACE`。

### Q2. DivStripZone 为何出现 CRS84/或未统一到 3857？扣除逻辑是否生效？
**结论：Partially（当前代码已支持统一；但外部观测可出现“看似不一致”）**
- 代码证据：CRS84 归一 `io.py:808-826`，校验 `io.py:789-805`，DivStrip 进入 3857 变换 `io.py:251-254`。
- 扣除生效证据：`pipeline.py:1287-1308`, `1333-1336`; `geometry.py:1861-1919`, `3119-3175`。
- 与简报冲突解释：`AUDIT_BRIEF` 的 CRS84 可能是“原始 `Vector/DivStripZone.geojson` 文件”被直接读取，而非内存 `divstrip_zone_metric`；代码并不会把投影后的 DivStrip 单独落盘。
**影响范围**：若实际运行 git_sha 不是当前 HEAD，或外部检查口径读取源文件而不是 metric 对象，会得出“CRS 不一致导致不相交”的假象。

### Q3. traj_surface 为何落盘为 MultiLineString/area=0？debug dump 与 gate 是否一致？
**结论：Yes（已定位）**
- debug 强制线化：`pipeline.py:2119-2121` 调 `_iter_line_parts(surface)`；而 `_iter_line_parts` 对 Polygon 返回 boundary（`pipeline.py:2054-2061`）。
- gate 用内存对象：`pipeline.py:1685`, `1697-1704` 直接对 `surface` 求 `intersection/contains`。
- 另一个退化风险：`_build_traj_surface_from_refline` / `_surface_from_lr` 未强制 `Polygon/MultiPolygon` 类型（`pipeline.py:1323-1336`, `1371-1388`），几何可能退化。
**影响范围**：debug 看到线不等于 gate 也在用线；但若内存 surface 真的退化成线/空，会直接导致 in_ratio/endpoint 判定异常。

### Q4. in_ratio/endpoint_in_surface 计算到底用什么对象？为何会与 debug surface 不一致？
**结论：Yes（对象已明确）**
- `in_ratio`：`road_line.intersection(surface).length / road_line.length`（`pipeline.py:1697-1701`）。
- `endpoint_in_surface`：`surface.buffer(1e-6).contains(Point(endpoint))`（`pipeline.py:1701-1704`）。
- 不一致原因：debug 文件写的是边界线而非原 surface 对象（见 Q3）。
**影响范围**：会出现“debug 看上去不在面内，但 gate 数值仍存在”的表象矛盾；此外 `contains`（非 `covers`）对边界点更严格，可能放大端点误判。

### Q5. seg_index=0 的长跳连如何产生？
**结论：Partially（已定位主要路径）**
- 已有前置裁剪：`geometry.py:1208-1212`（`shape_ref_substring_by_xsecs`）。
- 仍可产生首段长跳：趋势投影阶段重建坐标 `P_end -> P_mid -> anchor ...`（`geometry.py:1693-1730`），若 `P_end` 与 `anchor` 不在同一通道片段，首段会异常拉长。
- 桥接只做后验检测：`pipeline.py:1948-1958`。
**影响范围**：触发 `BRIDGE_SEGMENT_TOO_LONG` 且常见 `seg_index=0`，与简报观测一致。

### Q6. multi-road 下是否真正做到 k 级 surface/path/road 绑定并择优？
**结论：Partially（框架上是，质量上仍有错配风险）**
- 是：`pipeline.py:605-623`（按 cluster_k 建 `surface_hint_k`）、`664-684`（建 `Road_k`）、`718-730`（评分择优）。
- 风险点：`surface_k` 构建使用直线 ref_line（`pipeline.py:1471-1478`）+ 全轨迹点汇总（`pipeline.py:1150-1172`），不是 A→B 片段化 station 轴；导致 k 约束本身可能偏短/偏移。
**影响范围**：会出现“存在更像道路面的 surface，但最终被选中 k* 仍不理想”的错配感知。

---

## 4.5 Minimal Fix Options（只写策略，不写代码）

### 方案A：分离“gate surface”和“debug surface”语义（最小改动）
- 修什么：新增 debug polygon 落盘（保留现有 boundary layer 也可），并在 summary 记录 `surface_geom_type/area`（gate对象的真实类型与面积）。
- 风险/回归点：仅诊断增强，几何结果不变；需验证 3 个 patch 输出体积可控。
- 建议新增指标：`traj_surface_geom_type`, `traj_surface_area_m2`, `debug_surface_dump_mode`。

### 方案B：改 `traj_surface_k` 的 station 轴为“通道骨架轴”（LB path 或 centerline）
- 修什么：避免直线轴导致的局部覆盖，减少“surface 只一小段”。
- 风险/回归点：2855832875697813（当前正确）可能受影响；需看 `in_ratio` 与 `valid_slices` 是否稳定。
- 建议新增指标：`surface_axis_source`, `slice_s_min/s_max`, `valid_slices_by_quartile`。

### 方案C：端点趋势替换后增加结构化保护
- 修什么：在趋势重建后增加端点投影一致性检查与必要的二次 substring，避免 `seg_index=0` 长跳。
- 风险/回归点：可能改变端点局部形状；需对 285579/285583207 重点看 `max_segment_m` 与端点偏差。
- 建议新增指标：`endpoint_anchor_dist_src/dst`, `trend_project_fail_reason`, `post_trend_substring_applied`。

---

## 4.6 Regression Checklist（必须包含 3 patch）

- **2855795596723843**：
  - 核查 `traj_surface_geom_type/area` 与 debug polygon 是否一致；
  - 核查 `max_segment_m` 是否仍由 `seg_index=0` 触发；
  - 核查 `chosen_cluster_id` 与 `cluster_score_top2` 是否出现明显错选。

- **2855832070394132**：
  - 核查 dst 端 `xsec_support_dst` 是否为空或片段错选；
  - 核查 `endpoint_in_traj_surface_dst` 与 `endpoint_tangent_deviation_deg_dst`；
  - 核查是否仍有中段桥接长段。

- **2855832875697813**：
  - 作为对照组，确保 `in_ratio`、端点在面域、`max_segment_m` 不回退；
  - 若触发 pass2，检查 `neighbor_search_pass=2` 下仍可稳定产出。

---

## 附：本次审计边界
- 审计模式为只读，未改源码。
- 当前机器可访问的历史输出不包含 `2855832070394132` 的有效产物目录，且未发现 `t05_v4speed_20260227_075848` 的本地文件；对应现象引用来自 `T05_AUDIT_BRIEF.md`。
- 代码审计基线：`/mnt/e/Work/Highway_Topo_Poc`，`git_sha=96e0bb7738f6e6e626a14288d15ad450206fb057`（branch `main`）。
