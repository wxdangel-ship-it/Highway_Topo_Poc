# T05 内网执行审计单文件模板

用途:
- 这是内网执行审计专用模板。
- 只服务于“本次脚本执行遇到什么问题”的记录。
- 一次只对应一个 `(run_id, patch_id)`。
- 该文件设计为可直接文本粘贴给外网 QA。

强约束:
- 单次只保留 1 个文本文件。
- 建议 `<= 120` 行。
- 建议 `<= 8KB`。
- 超长时必须截断，保留 Top-K，不要贴 raw dump。

建议命名:
- `T05_EXEC_AUDIT_BUNDLE__<run_id>__<patch_id>.md`

---

## 1. 基本信息

```yaml
run_id: <required>
patch_id: <required>
git_sha: <required>
bundle_time: <YYYY-MM-DD HH:MM>
visual_verdict: <required; one sentence>
execution_goal: <one line>
runtime_result: <pass|fail|partial|unknown>
focus_question: <one line or NA>
```

## 2. 输入快照

```yaml
required_inputs:
  DriveZone: <ok|missing|empty|unknown>
  intersection_l: <ok|missing|empty|unknown>
  Traj: <ok|missing|empty|unknown>
optional_inputs:
  LaneBoundary: <ok|missing|crs_missing_fixed|skipped|unknown>
  DivStripZone: <ok|missing|skipped|unknown>
  Node_or_RCSDNode: <ok|missing|skipped|unknown>
  PointCloud: <ok|missing|skipped|unknown>
crs_status:
  expected: EPSG:3857
  actual: <EPSG:3857|mixed|unknown>
runtime_exception:
  has_exception: <true|false>
  exception_type: <InputDataError|Traceback|NA|unknown>
  exception_summary: <one line or NA>
```

## 3. summary 摘要

至少覆盖:
- `road_count`
- `road_features_count`
- `no_geometry_candidate`
- `overall_pass`
- 关键 hard/soft reason Top-K

```text
<paste key lines only>
```

## 4. metrics 关键字段

```json
{
  "patch_id": "",
  "road_count": 0,
  "road_features_count": 0,
  "no_geometry_candidate": false,
  "unique_pair_count": 0,
  "hard_anomaly_count": 0,
  "soft_issue_count": 0,
  "avg_conf": "NA",
  "p10_conf": "NA",
  "p50_conf": "NA",
  "center_coverage_avg": "NA",
  "endpoint_dist_to_xsec": "NA"
}
```

## 5. gate 关键字段

```json
{
  "overall_pass": false,
  "hard_breakpoints": [],
  "soft_breakpoints": [],
  "params_digest": "",
  "version": ""
}
```

## 6. 关键问题信号

未知可写 `NA`。

```yaml
step1_signals:
  CROSS_DISTANCE_GATE_REJECT: <count_or_NA>
  UNRESOLVED_NEIGHBOR: <count_or_NA>
  NO_ADJACENT_PAIR_AFTER_PASS2: <count_or_NA>
  MULTI_CHAIN_SAME_DST: <count_or_NA>
  NO_STRATEGY_MERGE_TO_DIVERGE: <count_or_NA>
  MULTI_NEIGHBOR_FOR_NODE: <count_or_NA>
  MULTI_CORRIDOR: <count_or_NA>
step2_3_signals:
  ROAD_OUTSIDE_TRAJ_SURFACE: <count_or_NA>
  ROAD_OUTSIDE_DRIVEZONE: <count_or_NA>
  ROAD_OUTSIDE_SEGMENT_CORRIDOR: <count_or_NA>
  ROAD_INTERSECTS_DIVSTRIP: <count_or_NA>
  BRIDGE_SEGMENT_TOO_LONG: <count_or_NA>
  ENDPOINT_OFF_XSEC_ROAD: <count_or_NA>
  CENTER_ESTIMATE_EMPTY: <count_or_NA>
  TRAJ_SURFACE_INSUFFICIENT: <count_or_NA>
  TRAJ_SURFACE_GAP: <count_or_NA>
  SPARSE_SURFACE_POINTS: <count_or_NA>
  NO_LB_CONTINUOUS: <count_or_NA>
```

## 7. debug 文件清单

只列文件名或相对路径，不贴内容。

```text
step1_topology_unique_map.json
step1_pair_straight_segments.geojson
step1_support_trajs.geojson
step1_corridor_candidates*.geojson
traj_surface_best_polygon.geojson
road_outside_segments.geojson
road_divstrip_intersections.geojson
xsec_gate*
xsec_road_selected*
<other files>
```

## 8. 本次执行结论

只写“本次执行”层面的现象，不写版本级结论。

```text
<for example: "本次执行程序 hard fail，核心现象为 CENTER_ESTIMATE_EMPTY，且 summary 与目视均显示主路存在但未产出稳定中心线">
```

## 9. 截断说明

```yaml
truncated: <true|false>
truncate_reason: <na|size_limit|manual_topk_only>
```

