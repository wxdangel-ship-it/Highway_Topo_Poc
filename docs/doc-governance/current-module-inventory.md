# 当前模块盘点

## 范围

- 盘点日期：2026-03-17
- 目的：建立文档治理 Round 1 所需的当前模块基线
- 本轮深度审核范围：
  - `t04_rc_sw_anchor`
  - `t05_topology_between_rc_v2`
  - `t06_patch_preprocess`

## 当前模块总表

| 模块 | 模块路径 | 当前仓库现实 | 是否有模块文档 | 是否有 AGENTS | 是否有 SKILL | 是否有源码实现 | Round 1 建议深度 | 备注 |
|---|---|---|---|---|---|---|---|---|
| `t00_synth_data` | `modules/t00_synth_data` | 冻结工具模块 | 有 | 有 | 有 | 有 | 仅盘点 | 不在本轮人工重点审核范围 |
| `t01_fusion_qc` | `modules/t01_fusion_qc` | 冻结模块 | 有 | 有 | 有 | 有 | 仅盘点 | contract 较重，但本轮优先级较低 |
| `t02_ground_seg_qc` | `modules/t02_ground_seg_qc` | frozen 但文档丰富 | 有 | 有 | 有 | 有 | 仅盘点 | 后续需要规范化，但不是本轮重点 |
| `t04_rc_sw_anchor` | `modules/t04_rc_sw_anchor` | 核心模块，代码/测试/文档较成熟 | 有 | 有 | 有 | 有 | 深度审核 | 本轮三个重点审核包之一 |
| `t05_topology_between_rc` | `modules/t05_topology_between_rc` | 遗留核心 T05 模块 | 有 | 有 | 有 | 有 | 盘点 + 家族映射 | 是 T05-V2 的重要上下文，但不是本轮深改对象 |
| `t05_topology_between_rc_v2` | `modules/t05_topology_between_rc_v2` | 当前活跃的独立模块 | 有 | 有 | 无 | 有 | 深度审核 | 已有独立 src/tests/scripts，定位必须澄清 |
| `t06_patch_preprocess` | `modules/t06_patch_preprocess` | 仓库已实现，但旧 taxonomy 仍将其视作新模块 | 有 | 有 | 有 | 有 | 深度审核 | 本轮三个重点审核包之一 |
| `t07_patch_postprocess` | `modules/t07_patch_postprocess` | 以 contract 为先的新模块 | 有 | 有 | 有 | 有 | 仅盘点 | 不在本轮人工重点审核范围 |
| `t10` | `modules/t10` | 超出原 `SPEC` taxonomy 的额外模块 | 有 | 有 | 有 | 无直接同名实现 | 仅盘点并标风险 | 实现在 `src/.../t10_complex_intersection_modeling/` |

## Taxonomy 不一致与缺失模块

### `t03_marking_entity`

- 在 `SPEC.md` 与 `docs/PROJECT_BRIEF.md` 中仍被列为 冻结模块。
- 当前不存在 `modules/t03_marking_entity/`。
- 当前不存在 `src/highway_topo_poc/modules/t03_marking_entity/`。
- Round 1 建议：
  - 在迁移映射和执行报告中保留可见性，把它记录为缺失的 taxonomy 成员
  - 本轮不伪造替代文档

### `t05_topology_between_rc_v2`

- 当前已出现在 `modules/`、`src/`、`tests/` 与 `scripts/`。
- 旧版全局 taxonomy 文本尚未反映它。
- Round 1 建议：
  - 以当前仓库事实为准，将其视为独立可执行模块
  - 在文档治理层面显式记录它与 legacy `t05` 的家族关系
  - 在没有明确迁移决策前，不要把 V2 静默折叠进 legacy T05 文档

### `t10`

- 当前存在于 `modules/t10`，但实现路径是 `src/highway_topo_poc/modules/t10_complex_intersection_modeling/`。
- 这同时是 taxonomy 扩展问题和命名漂移问题。
- Round 1 建议：
  - 本轮只做 inventory
  - 作为 Round 2+ 治理清理项显式标记

## 重点模块摘要

### T04

- 当前业务角色：
  - 识别 merge/diverge 与 K16 锚点
  - 产出最终 `intersection_l_opt`
- 当前文档集合：
  - `AGENTS.md`
  - `SKILL.md`
  - `INTERFACE_CONTRACT.md`
  - `README.md`
- 当前实现证据：
  - 独立 `src/` 包
  - 独立 `tests/t04_rc_sw_anchor/`
- 当前文档问题：
  - 模块真相分散在四份文档中
  - `AGENTS` 与 `SKILL` 承载了稳定业务规则
- Round 1 深度审核目标：
  - `architecture` 草案
  - `review-summary`
  - 从当前四文档混合态迁移到“源事实 + 规则 + 工作流”分层的清晰映射

### T05-V2

- 当前业务角色：
  - 通过 `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad` 的阶段链路生成新的 T05-V2 输出
- 当前文档集合：
  - `AGENTS.md`
  - `INTERFACE_CONTRACT.md`
  - `REAL_RUN_ACCEPTANCE.md`
- 当前实现证据：
  - 独立 `src/` 包
  - 独立 `tests/test_t05v2_pipeline.py`
  - 多个独立 stepwise 脚本
- 当前文档问题：
  - 模块身份在 `AGENTS` 中很明确，但与旧 T05 的家族定位没有正式治理规则
  - 没有 `SKILL.md`
  - 验收说明很有价值，但不是长期架构文档
- Round 1 深度审核目标：
  - `architecture` 草案
  - `review-summary`
  - 对模块定位给出明确建议

### T06

- 当前业务角色：
  - 在 patch 级道路数据中修复缺失 endpoint reference 的问题，通过 DriveZone 裁剪和 virtual node 保证下游闭合
- 当前文档集合：
  - `AGENTS.md`
  - `SKILL.md`
  - `INTERFACE_CONTRACT.md`
- 当前实现证据：
  - `src/highway_topo_poc/modules/t06_patch_preprocess/`
  - `tests/test_t06_patch_preprocess.py`
- 当前文档问题：
  - 仓库现实已经超过旧全局 taxonomy 中“仅 contract / 新模块”的描述
  - `AGENTS`、`SKILL` 与 contract 重叠严重
- Round 1 深度审核目标：
  - `architecture` 草案
  - `review-summary`
  - 对“全局文档表述”与“当前实现状态”的差异做显式说明

## 初始优先级建议

| 模块 | 建议优先级 | 原因 |
|---|---|---|
| `t04_rc_sw_anchor` | 高 | 核心成熟模块，多个文档面重叠严重 |
| `t05_topology_between_rc_v2` | 高 | 活跃模块、实现独立、家族定位未定 |
| `t06_patch_preprocess` | 高 | 仓库现实与旧项目 taxonomy 明显偏离 |
| `t05_topology_between_rc` | 中 | 需要作为 T05-V2 的上下文与迁移锚点 |
| `t10` | 中 | 超出 taxonomy 且存在命名漂移 |
| `t07_patch_postprocess` | 中低 | contract-first 模块，但不是本轮重点 |
| `t02_ground_seg_qc` | 中低 | 文档丰富，但超出当前人工审核范围 |
| `t00_synth_data` | 低 | frozen，且对 Round 1 风险较低 |
| `t01_fusion_qc` | 低 | frozen，且对 Round 1 风险较低 |

## Round 1 建议总结

Round 1 应当：

- 深度审核 `t04`、`t05_v2`、`t06`
- 把 `t05` 作为上下文和迁移锚点保留下来
- 盘点所有剩余模块
- 显式记录 `t03` 为缺失的 taxonomy 成员
- 显式记录 `t10` 为后补模块，后续需做治理清理



