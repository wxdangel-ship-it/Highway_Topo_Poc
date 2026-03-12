# T05 v2 Real-Run Acceptance

## 目的
这份文档用于内网 WSL 真实 patch 首轮验收。

当前版本的重点不是让最终 `Road` 完美，而是确认：
- `Step2 Segment` 是否已经收敛
- 单点 `cross=1` 例外是否受控
- debug / metrics 是否足够解释

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

## Step2 默认保守参数
当前默认就是保守口径：
- `--step2_strict_adjacent_pairing 1`
- `--step2_allow_one_intermediate_xsec 0`
- `--step2_same_pair_topk 1`

## Step2 单点 cross1 例外参数
默认关闭：
- `--step2_pair_scoped_cross1_exception_enable 0`
- `--step2_pair_scoped_cross1_allowlist ""`

如果只验证单个 pair 的 `cross=1` 例外，可透传：
```bash
cd "$REPO_ROOT" && \
bash scripts/t05v2_step2_segment.sh \
  --data_root "$DATA_ROOT" \
  --patch_id "$PATCH_ID" \
  --run_id "$RUN_ID" \
  --debug \
  --force \
  --step2_pair_scoped_cross1_exception_enable 1 \
  --step2_pair_scoped_cross1_allowlist 55353246:37687913
```

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

## 验收顺序
第一优先：
- `summary.txt`
- `metrics.json`
- `gate.json`

第二优先：
- `debug/step2_segment_selected.geojson`
- `debug/step2_segment_dropped.geojson`
- `debug/step2_same_pair_groups.json`
- `debug/step2_zero_selected_pairs.json`
- `debug/step3_witness_input_segments.geojson`

第三优先：
- `debug/corridor_witness_selected.geojson`
- `debug/corridor_identity.json`
- `debug/slot_src_dst.geojson`
- `debug/shape_ref_line.geojson`
- `debug/road_final.geojson`

第四优先：
- `debug/step2_segment_candidates_all.geojson`
- `debug/reason_trace.json`
- `debug/base_xsec_all.geojson`
- `debug/probe_xsec_all.geojson`

## 关键文件意义
- `debug/step2_segment_selected.geojson`
  作用：当前真正进入后续主链路的 `Segment`
- `debug/step2_segment_dropped.geojson`
  作用：same-pair 压缩或 `cross=1` 例外规则丢掉了哪些 `Segment`
- `debug/step2_same_pair_groups.json`
  作用：查看每个 `(src,dst)` 下候选数、保留数、排序依据、淘汰原因
- `debug/step2_zero_selected_pairs.json`
  作用：查看哪些 `(src,dst)` 最终一个 `Segment` 都没留下，以及是否满足 pair-scoped `cross=1` 例外条件
- `debug/step3_witness_input_segments.geojson`
  作用：确认 witness 实际收到的 `Segment` 输入，判断 witness 数量是 Step2 造成还是 Step3 自己膨胀

## Step2 验收重点
优先看这些字段：
- `segment_count`
- `crossing_dist_hist_selected`
- `pairs_with_multi_segments`
- `max_segments_per_pair`
- `pair_scoped_cross1_exception_enabled`
- `pair_scoped_cross1_exception_hit_count`
- `selected_cross1_exception_count`
- `zero_selected_pair_count`
- `zero_selected_pair_ids`

建议判读：
- 如果 `crossing_dist_hist_selected["1"]` 重新大面积出现，说明全局 `cross=1` 回潮
- 如果 `pairs_with_multi_segments` 重新升高，说明 same-pair 压缩退化
- 如果开启 pair-scoped 例外后，只有 allowlist pair 出现 `cross=1 selected`，说明例外仍然受控
- 如果 `step2_zero_selected_pairs.json` 里的 pair 依旧很多，要先回看 `step2_segment_dropped.geojson` 和 `excluded_candidates`

## 当前已知限制
- `ProbeCrossSection` 仍未进入主判定，只保留占位输出
- branch identity 仍未完整实现
- witness/prior 冲突仲裁仍是最小版
- `STEP2_SAME_PAIR_TOPK=1` 对真实 same-pair 多路共存场景可能偏保守
- pair-scoped `cross=1` 例外当前只适合做单点验证，不适合直接扩成全局业务口径
