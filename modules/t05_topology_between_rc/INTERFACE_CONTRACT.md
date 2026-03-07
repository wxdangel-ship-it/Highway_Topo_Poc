# t05_topology_between_rc - INTERFACE_CONTRACT

## 1. 目标与范围
- 模块 ID：`t05_topology_between_rc`
- 目标：基于 `intersection_l`、轨迹与 `DriveZone`，结合 `LaneBoundary`、点云与 `RCSDRoad` prior，生成 RC 路口间有向 `Road` 中心线。
- 产物几何：`LineString`（方向为 `src_nodeid -> dst_nodeid`）。

## 2. 输入（Input）
Patch 根目录默认位于 `data/synth_local/<patch_id>/`。

必需输入：
- `Vector/intersection_l.geojson`
  - 几何：`LineString`
  - 属性：`nodeid:int64`
- `Traj/*/raw_dat_pose.geojson`
  - 几何：`Point`
  - 序列键优先级：`seq > frame_id > timestamp > index`
- `Vector/DriveZone.geojson`
  - 几何：`Polygon|MultiPolygon`
  - 当前实现按强制输入处理

增强依赖：
- `Vector/LaneBoundary.geojson`
  - 当前主要用于 shape/trend 参考，缺失时允许降级
- `Vector/RCSDRoad.geojson`
  - 当前参与 Step1 邻接过滤与唯一链推断

兜底输入：
- `PointCloud/*.las|*.laz`
  - 当前默认不启用
  - 启用时必须可读取 `xyz`
  - `classification` 可选但推荐

推荐输入：
- `Vector/RCSDNode.geojson`（`Kind` bit3/bit4 用于 merge/diverge）
- `Vector/DivStripZone.geojson`（诊断用途）

## 3. 输出（Output）
单 patch 输出目录：
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/RCSDRoad.geojson`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/metrics.json`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/intervals.json`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/summary.txt`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/gate.json`

关键字段约束：
- `RCSDRoad.geojson`
  - 几何：`LineString`
  - 必需属性：
    - `road_id:string`
    - `src_nodeid:int64`
    - `dst_nodeid:int64`
    - `direction:string`（`src->dst`）
    - `length_m:float`
    - `support_traj_count:int`
    - `conf:float`（0..1）
    - `hard_anomaly:bool`
    - `soft_issue_flags:string[]`
- `metrics.json` 必需键：
  - `patch_id`, `road_count`, `unique_pair_count`
  - `hard_anomaly_count`, `soft_issue_count`, `low_support_road_count`
  - `avg_conf`, `p10_conf`, `p50_conf`, `center_coverage_avg`
- `intervals.json`
  - `topk[]`：`road_id, reason, severity, hint`（可附加轨迹/区间字段）
- `gate.json`
  - `overall_pass:bool`
  - `hard_breakpoints:[]`
  - `soft_breakpoints:[]`
  - `params_digest:string`
  - `version:string`

## 4. 入口（Entrypoint / CLI）
- `python -m highway_topo_poc.modules.t05_topology_between_rc.run`

## 5. 参数（Parameters）
CLI 关键参数：
- `--data_root`：patch 数据根目录
- `--patch_id`：必需，显式指定单 patch
- `--run_id`：运行标识，`auto` 自动生成
- `--out_root`：输出目录根（必须写入 `outputs/_work/...`）
- `--xsec_min_points`：横截最小点数阈值
- `--min_support_traj`：最小轨迹支持数阈值

确定性默认参数（实现内冻结）：
- `TRAJ_XSEC_HIT_BUFFER_M = 0.5`
- `TRAJ_XSEC_DEDUP_GAP_M = 2.0`
- `MIN_SUPPORT_TRAJ = 2`
- `STABLE_OFFSET_M = 50.0`
- `STABLE_OFFSET_MARGIN_M = 5.0`
- `CENTER_SAMPLE_STEP_M = 5.0`
- `XSEC_ALONG_HALF_WINDOW_M = 1.0`
- `XSEC_ACROSS_HALF_WINDOW_M = 30.0`
- `XSEC_MIN_POINTS = 200`
- `WIDTH_PCT_LOW = 5`
- `WIDTH_PCT_HIGH = 95`
- `MIN_CENTER_COVERAGE = 0.6`
- `SMOOTH_WINDOW_M = 25.0`
- `TURN_LIMIT_DEG_PER_10M = 30.0`
- `ENDPOINT_ON_XSEC_TOL_M = 1.0`
- `TOPK_INTERVALS = 20`
- `CONF_W1_SUPPORT = 0.4`
- `CONF_W2_COVERAGE = 0.4`
- `CONF_W3_SMOOTH = 0.2`
- `ROAD_MAX_VERTICES = 2000`

## 6. 门禁与评分规则
Hard gate（任一命中即 `overall_pass=false`）：
- `CENTER_ESTIMATE_EMPTY`
- `NON_RC_IN_BETWEEN`
- `MULTI_ROAD_SAME_PAIR`
- `ENDPOINT_NOT_ON_XSEC`
- 任一 road 出现 `src_nodeid == dst_nodeid`

Soft gate（不直接失败，但必须报告）：
- `LOW_SUPPORT`
- `SPARSE_SURFACE_POINTS`
- `NO_LB_CONTINUOUS`
- `WIGGLY_CENTERLINE`
- `OPEN_END`

过渡期说明：
- 当前实现仍可能输出扩展 gate reason；在正式扩容前，以 `gate.json` 为运行时权威。
- 其中 `ROAD_OUTSIDE_TRAJ_SURFACE` 当前按 Hard 处理。
- 任一 `overall_pass=false` 的结果必须至少包含一条 `hard_breakpoints`。

置信度：
- `f_support = 1 - exp(-support_traj_count / 2)`
- `f_coverage = center_sample_coverage`
- `f_smooth = clamp01(1 - max_turn_deg_per_10m / TURN_LIMIT_DEG_PER_10M)`
- `conf = clamp01(CONF_W1_SUPPORT*f_support + CONF_W2_COVERAGE*f_coverage + CONF_W3_SMOOTH*f_smooth)`

## 7. 示例（Example）
在 repo root 执行：

```bash
RUN_ID="$(date +%Y%m%d_%H%M%S)"
OUT_ROOT="outputs/_work/t05_topology_between_rc/${RUN_ID}"
python -m highway_topo_poc.modules.t05_topology_between_rc.run \
  --data_root data/synth_local \
  --patch_id <patch_id> \
  --run_id smoke_min \
  --out_root "${OUT_ROOT}" \
  --xsec_min_points 50 \
  --min_support_traj 1
```

## 8. 验收（Accept）
- 命令退出码为 `0`
- 未传 `--patch_id` 时必须非零退出，并给出明确错误
- `${OUT_ROOT}/smoke_min/patches/<patch_id>/` 下存在：
  - `RCSDRoad.geojson`
  - `metrics.json`
  - `intervals.json`
  - `summary.txt`
  - `gate.json`
- `gate.json` 必须包含 `overall_pass`
- 若 `overall_pass=false`，则 `gate.json.hard_breakpoints` 不得为空
- `RCSDRoad.geojson` 必须是合法 GeoJSON
