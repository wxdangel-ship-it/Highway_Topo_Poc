# T05-V2 运行验收说明

> 本文件是运行验收与操作者清单。长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准；如本文件与长期源事实表述不一致，以后者为准。

## 目标
当前阶段的目标不是继续修改 `Step2`，而是在冻结的 `Step2` baseline 上，把简单真实 patch 做成稳定、可解释、可验收的完整闭环。

当前主线：
- 先验收简单真实 patch 的 `Segment -> corridor_identity -> slot -> Road`
- 再用复杂 patch `5417632623039346` 做回归和压力测试
- 复杂 patch 不是当前阶段“第一批完整成路”的主目标

## 主验收 Patch
当前主验收集固定为以下简单真实 patch：
- `5417632690143239`
- `5417632690143326`

选择标准：
- `segment_count` 少
- same-pair 不膨胀
- 无明显复杂 branch / 多 corridor 争议
- 在当前版本下已有非空 `Road` 或已表现出清晰闭环迹象

当前回归 / 压力测试 patch：
- `5417632623039346`

## 环境变量
```bash
REPO_ROOT=/mnt/d/Work/Highway_Topo_Poc
DATA_ROOT=/mnt/d/TestData/highway_topo_poc_data/e2e
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

## Step2 冻结基线
当前仍然保持冻结：
- `--step2_strict_adjacent_pairing 1`
- `--step2_allow_one_intermediate_xsec 0`
- `--step2_same_pair_topk 1`

pair-scoped `cross=1` 例外仍然默认关闭，只在明确需要时启用：
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

## 简单 Patch 验收顺序
第一优先：
- `summary.txt`
- `metrics.json`
- `gate.json`

第二优先：
- `debug/segment_selected.geojson`
- `debug/corridor_identity.json`
- `debug/slot_src_dst.geojson`

第三优先：
- `debug/shape_ref_line.geojson`
- `debug/road_final.geojson`

第四优先：
- `debug/reason_trace.json`

## 如何判断问题在哪一层
- 如果 `corridor_identity_state = unresolved`
  先不要看 `Road`，说明卡在 corridor 层。

- 如果 `slot_src_status / slot_dst_status = unresolved`
  先不要判断最终几何，说明卡在 slot 层。

- 如果 `corridor` 与 `slot` 都 resolved，但 `road_count = 0` 或该段无最终 `Road`
  重点看 `reason_trace.json` 里的 `road_results`：
  - `candidate_attempts`
  - `chosen_shape_ref_mode`
  - `final_reason`
  - `failure_classification`

- 如果 `road_in_drivezone_ratio` 很低或 `road_intersects_divstrip = true`
  该段当前不应视为通过结果。

## 如何判断一条 Segment 是否应该成路
先看：
- `debug/corridor_identity.json`
- `debug/slot_src_dst.geojson`
- `debug/shape_ref_line.geojson`
- `debug/road_final.geojson`

再看 `metrics.json` / `reason_trace.json`：
- `failure_classification = built`
  说明当前已经完整闭环。

- `failure_classification = unresolved_corridor`
  说明当前证据不足，不应强造 `Road`。

- `failure_classification = slot_mapping_failed`
  说明 corridor 可能成立，但端点区间还不稳定。

- `failure_classification = final_geometry_invalid`
  说明 corridor 和 `slot` 成立，但最终几何不满足 `DriveZone / DivStrip` 约束。

- `failure_classification = should_be_no_geometry_candidate`
  说明当前更适合直接归入 `no_geometry_candidate`，而不是继续强行出线。

## 关键文件怎么读
- `debug/segment_selected.geojson`
  当前被接受的路段框架。先确认 `Segment` 本身是否合理，再看后面层。

- `debug/corridor_identity.json`
  每个 `Segment` 的 corridor 状态：
  - `witness_based`
  - `prior_based`
  - `unresolved`

- `debug/slot_src_dst.geojson`
  端点是否回到了对应 `base_xsec` 的合理区间。

- `debug/shape_ref_line.geojson`
  当前真正用于成路的参考通路趋势。
  重点看：
  - `shape_ref_mode`
  - `no_geometry_candidate`
  - `no_geometry_reason`

- `debug/road_final.geojson`
  当前最终输出的 `Road`。先看端点是否回到正确 slot，再看中段是否大体沿正确通路。

- `debug/reason_trace.json`
  当前最适合查“为什么这条线没出来”。
  重点看：
  - `slot_mapping`
  - `road_results`
  - `road_results[*].candidate_attempts`
  - `road_results[*].failure_classification`

## metrics 重点字段
优先看：
- `segment_count`
- `road_count`
- `no_geometry_candidate_count`
- `no_geometry_candidate_reason`
- `failure_classification_hist`
- `segments[*].corridor_identity_state`
- `segments[*].slot_src_status`
- `segments[*].slot_dst_status`
- `segments[*].endpoint_dist_to_slot_src`
- `segments[*].endpoint_dist_to_slot_dst`
- `segments[*].road_in_drivezone_ratio`
- `segments[*].road_intersects_divstrip`
- `segments[*].shape_ref_mode`
- `segments[*].failure_classification`

## 当前阶段正确效果
对简单真实 patch，当前正确效果是：
- 有非空 `Road`
- 端点回到正确横截线区间
- `Road` 大体在 `DriveZone` 内，不穿 `DivStrip`
- 剩余失败段可解释

对复杂 patch `5417632623039346`，当前正确效果是：
- `Step2` baseline 不退化
- 新增审计不会反向污染 `Step2`
- 如果没有 `Road`，必须能解释卡在：
  - `corridor_identity`
  - `slot`
  - `final_road`
  哪一层

## 当前已知限制
- `ProbeCrossSection` 仍未进入主判定
- branch identity 仍未完整实现
- `STEP2_SAME_PAIR_TOPK=1` 对真实 same-pair 多路共存仍可能偏保守
- 复杂 patch 上，`prior_based / unresolved` 的比例可能仍偏高
- 当前版本优先保证“先有可解释的 `Road`”，而不是“先有最平滑的几何”
