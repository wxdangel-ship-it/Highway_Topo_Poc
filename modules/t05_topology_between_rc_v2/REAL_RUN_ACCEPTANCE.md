# T05 v2 Real-Run Acceptance

## 目标
当前版本的目标不是继续打磨 `Step2`，而是基于冻结的 `Step2` baseline，尽快验证：
- `Step3 corridor_identity` 是否真正进入主链路
- `Step4 slot` 是否能把端点稳定落回 `base_xsec`
- `Step5/6` 是否能在简单真实 patch 上输出非空 `Road`

建议验收顺序：
1. 先找 1~2 个简单真实 patch，优先看“能否先出非空 Road”
2. 再用复杂 patch `5417632623039346` 做回归和压力测试
3. 当前复杂 patch 不是本轮“第一优先出 Road”的对象

## 环境变量
```bash
REPO_ROOT=/mnt/d/Work/Highway_Topo_Poc
DATA_ROOT=/mnt/d/TestData/highway_topo_poc_data/normal
PATCH_ID=<your_patch_id>
RUN_ID=t05v2_real_$(date +%Y%m%d_%H%M%S)
```

## 一键全流程
```bash
cd "$REPO_ROOT" && \
bash scripts/run_t05v2_full_wsl.sh \
  --data_root "$DATA_ROOT" \
  --patch_id "$PATCH_ID" \
  --run_id "$RUN_ID" \
  --debug
```

输出目录：
```bash
$REPO_ROOT/outputs/_work/t05_topology_between_rc_v2/$RUN_ID/patches/$PATCH_ID/
```

## 分步执行
Step1:
```bash
cd "$REPO_ROOT" && bash scripts/t05v2_step1_input_frame.sh --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --debug
```

Step2:
```bash
cd "$REPO_ROOT" && bash scripts/t05v2_step2_segment.sh --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --debug
```

Step3:
```bash
cd "$REPO_ROOT" && bash scripts/t05v2_step3_witness.sh --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --debug
```

Step4:
```bash
cd "$REPO_ROOT" && bash scripts/t05v2_step4_corridor_identity.sh --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --debug
```

Step5:
```bash
cd "$REPO_ROOT" && bash scripts/t05v2_step5_slot_mapping.sh --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --debug
```

Step6:
```bash
cd "$REPO_ROOT" && bash scripts/t05v2_step6_build_road.sh --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --debug
```

Resume:
```bash
cd "$REPO_ROOT" && bash scripts/t05v2_resume.sh --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --debug
```

## Step2 基线参数
当前仍然保持冻结：
- `--step2_strict_adjacent_pairing 1`
- `--step2_allow_one_intermediate_xsec 0`
- `--step2_same_pair_topk 1`

单点 `cross=1` 例外仍然默认关闭，只在明确需要时启用：
- `--step2_pair_scoped_cross1_exception_enable 0`
- `--step2_pair_scoped_cross1_allowlist ""`

## 输出目录结构
```bash
outputs/_work/t05_topology_between_rc_v2/$RUN_ID/patches/$PATCH_ID/
  Road.geojson
  metrics.json
  gate.json
  summary.txt
  debug/
  step1/
  step2/
  step3/
  step4/
  step5/
  step6/
```

每个 `stepN/` 至少包含：
- 主产物 `json`
- `step_state.json`

## 先看什么
第一优先：
- `summary.txt`
- `metrics.json`
- `gate.json`

第二优先：
- `debug/corridor_identity.json`
- `debug/slot_src_dst.geojson`
- `debug/shape_ref_line.geojson`
- `debug/road_final.geojson`

第三优先：
- `debug/segment_selected.geojson`
- `debug/corridor_witness_selected.geojson`
- `debug/reason_trace.json`

第四优先：
- `debug/step2_pair_scoped_exception_audit.json`
- `debug/step2_same_pair_groups.json`
- `debug/step2_segment_dropped.geojson`

## 关键文件怎么读
- `debug/corridor_identity.json`
  先确认每个 `Segment` 是 `witness_based / prior_based / unresolved` 哪一种。
  如果这里就已经 `unresolved`，后面没有 `Road` 是正常结果。

- `debug/slot_src_dst.geojson`
  先看 `src` 和 `dst` 是否都落回了对应的 `base_xsec`。
  重点看：
  - `resolved`
  - `method`
  - `reason`
  - `corridor_state`

- `debug/shape_ref_line.geojson`
  这是当前真正用于成路的参考通路趋势，不再只是单纯 `Segment`。
  重点看：
  - `shape_ref_mode`
  - `no_geometry_candidate`
  - `no_geometry_reason`

- `debug/road_final.geojson`
  这是最终输出的 `Road`。
  重点先看端点是否回到了正确 `slot`，再看中段是否大体沿正确通路。

- `debug/reason_trace.json`
  如果没有 `Road`，这里最适合查“卡在了哪一层”：
  - `corridor_identity`
  - `slot_mapping`
  - `road_build`

## metrics 重点字段
优先看这些：
- `segment_count`
- `road_count`
- `no_geometry_candidate_count`
- `no_geometry_candidate_reason`
- `segments[*].corridor_identity_state`
- `segments[*].slot_src_status`
- `segments[*].slot_dst_status`
- `segments[*].endpoint_dist_to_slot_src`
- `segments[*].endpoint_dist_to_slot_dst`
- `segments[*].road_in_drivezone_ratio`
- `segments[*].road_intersects_divstrip`
- `segments[*].shape_ref_mode`

建议判读：
- 如果 `corridor_identity_state = unresolved`
  先不要看 `Road`，直接去看 `corridor_identity.json` 和 `reason_trace.json`

- 如果 `slot_src_status / slot_dst_status = unresolved`
  先不要判断最终几何对不对，说明是 slot 层卡住

- 如果 `shape_ref_line` 看起来合理，但 `road_final` 空
  大概率是 `DriveZone / DivStrip / slot` 约束把几何拦下来了

- 如果 `road_in_drivezone_ratio` 很低或 `road_intersects_divstrip = true`
  当前输出不应视为可通过结果

## 真实 patch 验收策略
推荐顺序：
1. 先用简单真实 patch 验证：
   - `road_count > 0`
   - `slot_src_dst` 与 `road_final` 大体一致
   - `prior_based / witness_based` 都能给出可解释结果
2. 再用复杂 patch `5417632623039346` 做回归：
   - `Step2` baseline 不退化
   - `Step3/4/5` 不反向污染 `Step2`
   - 如果失败，必须能解释是卡在 `corridor_identity / slot / final_road` 哪一层

## 当前已知限制
- `ProbeCrossSection` 仍未进入主判定
- branch identity 仍未完整实现
- `STEP2_SAME_PAIR_TOPK=1` 对真实 same-pair 多路共存仍可能偏保守
- 复杂 patch 上，`prior_based / unresolved` 的比例可能仍偏高
- 当前版本优先保证“先有可解释的 Road”，而不是“先有最平滑的几何”
