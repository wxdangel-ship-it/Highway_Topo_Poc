# t04_rc_sw_anchor - SKILL

## 算法口径（MVP 冻结）

1) Seed 与类型判定
- 从 `Node.geojson` 提取 `Kind` 包含 `bit4(diverge)` 或 `bit3(merge)` 的节点作为 seed。
- `bit3+bit4` 同时存在：`AMBIGUOUS_KIND`。
- 非 merge/diverge：`UNSUPPORTED_KIND`（仅记录，不产锚点）。

2) 关键约束
- 每个 seed node 在 `intersection_l` 必须恰好 1 条。
- `0 条 -> MISSING_INTERSECTION_L`；`>1 条 -> MULTIPLE_INTERSECTION_L`（hard）。

3) 坐标系与扫描
- diverge：优先 `enodeid==nodeid` 的 entering road，按长度最大选路。
- merge：优先 `snodeid==nodeid` 的 exiting road，按长度最大选路。
- 初始横截线：垂直道路切向，半长 `cross_half_len_m`。
- 扫描步长：`scan_step_m`；扫描终止：`min(next_intersection_dist, scan_max_limit_m)`。

4) 触发优先级
- `divstrip+pc`：当前横截线命中导流带，且前向 window 出现非地面点。
- `pc_only`：满足非地面触发（过滤初始/端点误触）。
- `divstrip_only_degraded`：点云不可用时，允许导流带降级触发（并写 `POINTCLOUD_MISSING_OR_UNUSABLE`）。
- 到终止仍无触发：`NO_TRIGGER_BEFORE_NEXT_INTERSECTION`。

5) 质量与断点
- `scan_dist<=20m` 记 `ok`，否则 `suspect`。
- `>200m` 标记人工关注并写 `SCAN_EXCEED_200M`。
- 声称导流带触发但 `dist_to_divstrip_m>1m`：`DIVSTRIP_TOLERANCE_VIOLATION`。

6) 输出要求
- `anchors.geojson`：每个 seed 输出 `anchor_point` + `crossline_opt`。
- `anchors.json`：每 seed 证据摘要（避免长坐标 dump）。
- `metrics.json`：计数、比例、门禁与 `overall_pass`。
- `breakpoints.json`：结构化异常编码。
- `summary.txt`：一屏文本摘要（Top breakpoints + Top scan_dist）。
