# t05_topology_between_rc - SKILL

## Contract Delta
- Same-pair multichain branches may legitimately produce multiple final `Road` features for one `(src_nodeid, dst_nodeid)` pair.
- Multi-road output is valid only when channels are stable, non-crossing, and preserve cross-section order.
- Each final same-pair road should carry `channel_id`, `channel_rank`, and `channel_count`.
- `MULTI_ROAD_SAME_PAIR` is reserved for unresolved same-pair branch conflicts, not for valid same-pair multi-road output.

## 算法口径（MVP 冻结）

1) 候选连接构建
- 从轨迹与 `intersection_l` 穿越事件构建有向候选对 `src_nodeid -> dst_nodeid`。
- 轨迹序列键优先级：`seq > frame_id > timestamp > index`。
- 使用 `RCSDRoad.geojson` prior 参与 Step1 邻接过滤与唯一链推断。

2) 中心线生成
- 优先使用可贯通 `src->dst` 的 `LaneBoundary` 作为 shape 参考；其为增强依赖，缺失时允许降级。
- 点云当前默认不启用，仅作为兜底策略。
- 应用稳定区规则（默认 50m）和 `intersection_l` 锚点窗口约束，确保端点不明显跑飞。

3) hard/soft 门禁
- Hard（命中即 fail）：
  - `CENTER_ESTIMATE_EMPTY`
  - `NON_RC_IN_BETWEEN`
  - `MULTI_ROAD_SAME_PAIR`
  - `ENDPOINT_NOT_ON_XSEC`
  - `src_nodeid == dst_nodeid`
- Soft（仅告警）：
  - `LOW_SUPPORT`
  - `SPARSE_SURFACE_POINTS`
  - `NO_LB_CONTINUOUS`
  - `WIGGLY_CENTERLINE`
  - `OPEN_END`
- 过渡期说明：实现仍可能输出扩展 gate reason；其中 `ROAD_OUTSIDE_TRAJ_SURFACE` 当前按 Hard 处理。
- 任何 `overall_pass=false` 的结果都必须伴随至少一条 `hard_breakpoints`。

4) 置信度计算
- `f_support = 1 - exp(-support_traj_count / 2)`
- `f_coverage = center_sample_coverage`
- `f_smooth = clamp01(1 - max_turn_deg_per_10m / TURN_LIMIT_DEG_PER_10M)`
- `conf = clamp01(CONF_W1_SUPPORT*f_support + CONF_W2_COVERAGE*f_coverage + CONF_W3_SMOOTH*f_smooth)`

5) 输出要求
- `RCSDRoad.geojson`：有向路段几何与属性
- `metrics.json`：聚合指标
- `intervals.json`：Top-K 断点
- `summary.txt`：可粘贴摘要
- `gate.json`：`overall_pass` 与断点摘要
