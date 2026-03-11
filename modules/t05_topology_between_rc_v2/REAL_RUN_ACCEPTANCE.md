# T05 v2 Real-Run Acceptance

## 目的
这份文档用于内网 WSL 首轮真实 patch 验收。
当前版本重点不是最终 Road 完美，而是确认：
- `Step2 Segment` 是否收敛
- `witness` 是否跟着下降
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

## Step2 收敛参数
默认已经是保守模式：
- `--step2_strict_adjacent_pairing 1`
- `--step2_allow_one_intermediate_xsec 0`
- `--step2_same_pair_topk 1`

如果需要做对比试验，可直接透传到现有脚本：
```bash
cd "$REPO_ROOT" && \
bash scripts/t05v2_step2_segment.sh \
  --data_root "$DATA_ROOT" \
  --patch_id "$PATCH_ID" \
  --run_id "$RUN_ID" \
  --debug \
  --force \
  --step2_strict_adjacent_pairing 0 \
  --step2_allow_one_intermediate_xsec 1 \
  --step2_same_pair_topk 2 \
  --step2_cross1_min_support 2 \
  --step2_cross1_min_drivezone_ratio 0.98 \
  --step2_cross1_max_length_ratio 1.35
```

最适合反复重跑的步骤：
- `Step2`
- `Step3`
- `Step4`

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
- 主产物 json
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
- `debug/step3_witness_input_segments.geojson`
- `debug/corridor_identity.json`

第三优先：
- `debug/corridor_witness_selected.geojson`
- `debug/slot_src_dst.geojson`
- `debug/shape_ref_line.geojson`
- `debug/road_final.geojson`

第四优先：
- `debug/step2_segment_candidates_all.geojson`
- `debug/reason_trace.json`
- `debug/base_xsec_all.geojson`
- `debug/probe_xsec_all.geojson`

## 关键文件意义
- `debug/step2_segment_candidates_all.geojson`
  作用：查看 raw candidate、pairing 保留/淘汰、cross filter 保留/淘汰的全过程。
- `debug/step2_segment_selected.geojson`
  作用：当前真正进入后续主链路的 `Segment`。
- `debug/step2_segment_dropped.geojson`
  作用：查看 same-pair topK 或 cross1 例外规则丢掉了哪些段。
- `debug/step2_same_pair_groups.json`
  作用：查看每个 `(src,dst)` 下候选数、保留数、排序依据、淘汰理由。
- `debug/step3_witness_input_segments.geojson`
  作用：查看 witness 实际接收到的 `Segment`，判断 witness 多是 Step2 造成还是 Step3 自己膨胀。
- `debug/corridor_witness_selected.geojson`
  作用：查看被选中的 witness，并结合 `crossing_dist` / `support_count` / `same_pair_rank` 判断它是否来自高风险 Segment。
- `debug/corridor_identity.json`
  作用：确认 `witness_based / prior_based / unresolved` 的最终分流结果。

## Step2 收敛验收重点
优先看这些指标：
- `segment_count`
- `crossing_dist_hist_selected`
- `pairs_with_multi_segments`
- `max_segments_per_pair`
- `witness_selected_count_total`
- `witness_selected_count_cross0`
- `witness_selected_count_cross1`

推荐判读：
- 如果 `crossing_dist_hist_selected["1"]` 仍然很高，说明 Step2 还没有真正收敛。
- 如果 `pairs_with_multi_segments` 仍然高，说明 same-pair 压缩还不够。
- 如果 `witness_selected_count_total` 几乎等于 `segment_count`，说明 witness 仍然主要在“跟着放行”。

## 当前已知限制
- `ProbeCrossSection` 仍未真正进入主判定，只保留占位输出。
- branch identity 仍未完整实现。
- witness/prior 冲突仲裁仍是最小版。
- 真实 same-pair 多路共存场景，当前 `STEP2_SAME_PAIR_TOPK=1` 可能偏保守。
- `cross1` 现在默认关闭，主要目标是先收敛 Step2，不代表最终业务口径已定稿。
