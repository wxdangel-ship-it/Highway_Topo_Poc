# T05-V2 方案策略

## 状态

- 文档状态：Round 2B 最小正式稿
- 来源依据：
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/pipeline.py`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/run.py`
  - `tests/test_t05v2_pipeline.py`
  - `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md`

## 策略总览

T05-V2 采用显式的阶段式策略来生成当前正式 T05 的最终 `Road`。核心思想不是直接从输入一步推出最终几何，而是沿着 `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad` 逐层收窄不确定性，并在每一层留下足够的中间证据。

## 阶段式策略

### 1. `step1_input_frame`

- 读取 patch 输入，检查必需文件是否存在。
- 把输入规整到统一的 `EPSG:3857` 坐标系。
- 写出输入框架与阶段状态，为后续阶段提供稳定起点。

### 2. `step2_segment`

- 生成可候选的 `Segment` 与合法 arc 结构。
- 应用邻接、same-pair、topology gap、bridge retain、alias normalization 等当前实现中的选择规则。
- 产出 `segment_candidates`、`segment_selected` 以及 Step2 相关审计文件，用于解释“为什么这条 pair 被保留或拒绝”。

### 3. `step3_witness`

- 基于轨迹、支持片段与 arc 证据，构建 `CorridorWitness`。
- 对 same-pair 多候选、支撑片段、轨迹交叉等情况做进一步证据收敛。
- 目标不是直接成路，而是为后续 corridor identity 提供可审计的支持依据。

### 4. `step4_corridor_identity`

- 把前一阶段的证据收敛为可用的 `CorridorIdentity`。
- 当前实现允许形成 `witness_based`、`prior_based` 或 `unresolved` 等状态。
- 这一层的职责是回答“当前段是否已有足够证据确定通路语义”，而不是直接决定最终几何。

### 5. `step5_slot_mapping`

- 在 corridor 语义已具备的前提下，构建端点区间并映射到 `Slot`。
- `Slot` 负责把“可通行的 corridor”转成“可出最终 road 的端点落位约束”。
- 当 `slot_src_status` 或 `slot_dst_status` 未 resolved 时，说明当前还不能可靠进入最终成路。

### 6. `step6_build_road`

- 结合 `Slot`、参考线、几何 refine 和质量门控生成 `FinalRoad`。
- 输出 `Road.geojson` 与最终 `metrics.json`、`gate.json`、`summary.txt`。
- 如果最终不成路，也必须通过 `reason_trace.json` 等产物说明失败分类，而不是静默失败。

## 当前策略取舍

- 优先保留显式阶段链与中间证据，而不是把所有判断压缩到单一步骤中。
- 优先保证“可解释地成路或失败”，再追求更复杂的几何优化。
- witness / prior / topology 证据各有角色，但正式模块文档以阶段职责划分，而不是以历史家族叙事组织。
- 运行验收策略继续保留在 `REAL_RUN_ACCEPTANCE.md`，不再与模块长期方案叙事混写。

## 后续人工审核重点

- 核对六阶段描述是否足以覆盖当前实现的长期稳定部分。
- 核对本文件是否已经把“阶段链”与“运行验收细节”有效分离。
