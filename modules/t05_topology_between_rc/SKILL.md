# t05_topology_between_rc - SKILL

## 算法口径（MVP 冻结）

1) 候选连接构建
- 从轨迹与 `intersection_l` 穿越事件构建有向候选对 `src_nodeid -> dst_nodeid`。
- 轨迹序列键优先级：`seq > frame_id > timestamp > index`。

2) 中心线生成
- 优先使用可贯通 `src->dst` 的 `LaneBoundary` 作为 shape 参考。
- 结合点云横截统计估计中心偏移，并进行平滑。
- 应用稳定区规则（默认 50m）和端点贴合约束，确保端点落在目标横截线上。

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
