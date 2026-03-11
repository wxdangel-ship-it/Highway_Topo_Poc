# T05 v2 Real-Run Acceptance

## 目的
- 这份文档用于你在内网 WSL 上做 `t05_topology_between_rc_v2` 的首轮真实 patch 验收。
- 当前版本目标是“可运行、可接续、可验收”，不是“已通过真实数据验证”。

## 环境变量模板
```bash
REPO_ROOT=/mnt/d/Work/Highway_Topo_Poc
DATA_ROOT=/mnt/d/TestData/highway_topo_poc_data/normal
PATCH_ID=<your_patch_id>
RUN_ID=t05v2_real_$(date +%Y%m%d_%H%M%S)
```

## 一键全流程
在 WSL 中执行：

```bash
cd "$REPO_ROOT" && \
bash scripts/run_t05v2_full_wsl.sh \
  --data_root "$DATA_ROOT" \
  --patch_id "$PATCH_ID" \
  --run_id "$RUN_ID" \
  --debug
```

输出目录固定为：
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

## 适合反复重跑的步骤
- `Step2`: Segment 框架不对时，后面都不可信。
- `Step3`: witness 证据位置常会先暴露真实 patch 的通路判定问题。
- `Step4`: witness/prior 分流逻辑是否进入正确状态。
- `Step5`: slot 是否回到正确横截线区间。

局部重跑模板：
```bash
cd "$REPO_ROOT" && bash scripts/t05v2_step3_witness.sh --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --debug --force
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

每个 `stepN/` 下至少有：
- 该步主产物 json
- `step_state.json`

## 文件验收顺序
### 第一优先
- `summary.txt`
- `metrics.json`
- `gate.json`

先回答三个问题：
- 这次 patch 有没有 road 输出。
- 哪个 segment 进入了 `witness_based / prior_based / unresolved`。
- 有没有硬失败 reason。

### 第二优先
- `debug/segment_selected.geojson`
- `debug/corridor_witness_selected.geojson`
- `debug/corridor_identity.json`
- `debug/slot_src_dst.geojson`

这是主业务验收层：
- `segment_selected`: 当前 patch 内被选中的 Segment 框架。先确认框架对不对。
- `corridor_witness_selected`: 当前 Segment 的 witness 证据位置。看中段独占通路是否合理。
- `corridor_identity.json`: 当前 corridor 是 `witness_based / prior_based / unresolved`，以及进入该状态的理由。
- `slot_src_dst.geojson`: 两端横截线上的端点区间。判断端点是否落在正确 slot，而不是只是“在线上”。

### 第三优先
- `debug/shape_ref_line.geojson`
- `debug/road_final.geojson`

这是几何输出层：
- `shape_ref_line`: 成路前的参考线/Segment 线。
- `road_final`: 最终输出几何。只有在前两层合理时，这一层才有业务意义。

### 第四优先
- `debug/segment_candidates.geojson`
- `debug/corridor_witness_candidates.geojson`
- `debug/reason_trace.json`
- `debug/base_xsec_all.geojson`
- `debug/probe_xsec_all.geojson`

这是追问题层：
- `segment_candidates`: 为什么形成当前 Segment，有没有其它候选被排除。
- `corridor_witness_candidates`: witness 为何选在这里，没选中的候选是什么。
- `reason_trace.json`: corridor/road 失败路径与最终 reason。
- `base_xsec_all`: 基础横截线全集。
- `probe_xsec_all`: 当前版本会产出占位文件，但 `ProbeCrossSection` 还未真正进入主判定。

## 典型判读规则
- 如果 `segment_selected` 明显不对，后面的 witness / slot / road 不用继续深看。
- 如果 `corridor_witness_selected` 不对，但 `road_final` 看起来“像是对的”，也不能算通过。
- 如果 `corridor_identity=unresolved` 但仍然出了 road，要视为异常。
- 如果 `slot_src_dst` 明显落错区间，即使 road 在线上也不通过。
- 如果 `gate.json` 里是 hard fail，先看 `reason_trace.json`，再回到 candidates 层追根因。

## 关键文件业务意义
- `summary.txt`: 人工快速总览。先看总体成功/失败与 segment 数量。
- `metrics.json`: 结构化验收入口。看每个 segment 的 corridor 状态、slot 是否 resolved、road 是否在 DriveZone 内。
- `gate.json`: 最终是否通过以及 hard/soft breakpoints。
- `debug/segment_selected.geojson`: 被选中的路段框架；它不等于最终 Road。
- `debug/corridor_witness_selected.geojson`: 用来证明中段独占合法通道的 witness。
- `debug/corridor_identity.json`: corridor 判定结果与原因。
- `debug/slot_src_dst.geojson`: 两端横截线 slot 映射结果。
- `debug/shape_ref_line.geojson`: FinalRoad 生成前的参考线。
- `debug/road_final.geojson`: 最终输出的 Road geometry。
- `debug/reason_trace.json`: 失败路径、fallback 路径、无几何原因。

## 当前版本已知限制
- `ProbeCrossSection` 仍未真正进入主判定，只保留了占位与 debug 文件。
- branch identity 仍未完整实现，复杂 branch 语义不要过度解读。
- witness/prior 冲突仲裁仍是最小版，当前更偏保守。
- `Segment` 仍是最小实现，复杂 same-pair 多 Segment 场景可能先在 Step2 暴露问题。
- `probe_xsec_all.geojson` 当前为占位输出，不代表 branch 识别已上线。

## 如何区分“已知限制”与“新发现问题”
- 已知限制：文档已明确说明、当前版本尚未建模的能力缺口。
- 新发现问题：在当前已实现能力范围内，出现了明显不一致，例如：
  - Segment 明显穿错边界框架。
  - witness 明显没有体现独占通路。
  - slot 落错区间。
  - `corridor_identity=unresolved` 却输出了 road。
  - road 明显穿出 DriveZone 或穿越 DivStrip。
