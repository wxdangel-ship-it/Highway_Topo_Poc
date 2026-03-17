# Round 2B T05-V2 正式化执行报告

## 本轮信息

- 轮次：项目文档治理 Round 2B
- 基线分支：`codex/002-doc-governance-decision-alignment`
- 执行分支：`codex/003-t05v2-doc-formalization`
- 范围类型：T05-V2 模块级文档深迁移 / 正式化
- 运行时影响：无

## Analyze 摘要

- **T05-V2 是否已形成最小正式文档面**：是。当前最小正式文档面由 `architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`SKILL.md`、`review-summary.md` 组成，`REAL_RUN_ACCEPTANCE.md` 作为运行验收文档保留。
- **是否仍有大量稳定业务真相残留在 `AGENTS.md`**：否。模块目标、阶段链、输入输出与质量要求已收回 `architecture/*` 和 `INTERFACE_CONTRACT.md`；`AGENTS.md` 仅保留稳定工作规则。
- **是否仍缺少关键源事实内容**：没有发现阻塞当前正式化的缺口。仍存在参数面较大、复杂 patch 解释成本高等后续问题，但不影响“最小可信正式文档面”的成立。
- **是否引入与当前项目级治理结构冲突的新问题**：否。本轮保持了 repo root `AGENTS.md`、`SPEC.md`、项目级 `docs/architecture/*` 与 T05-V2 文档面的一致性。

## 1. 本轮基线分支和工作分支分别是什么

- 基线分支：`codex/002-doc-governance-decision-alignment`
- 工作分支：`codex/003-t05v2-doc-formalization`

## 2. T05-V2 的最小正式文档面现在由哪些文件组成

- `modules/t05_topology_between_rc_v2/architecture/00-current-state-research.md`
- `modules/t05_topology_between_rc_v2/architecture/01-introduction-and-goals.md`
- `modules/t05_topology_between_rc_v2/architecture/02-constraints.md`
- `modules/t05_topology_between_rc_v2/architecture/03-context-and-scope.md`
- `modules/t05_topology_between_rc_v2/architecture/04-solution-strategy.md`
- `modules/t05_topology_between_rc_v2/architecture/05-building-block-view.md`
- `modules/t05_topology_between_rc_v2/architecture/10-quality-requirements.md`
- `modules/t05_topology_between_rc_v2/architecture/11-risks-and-technical-debt.md`
- `modules/t05_topology_between_rc_v2/architecture/12-glossary.md`
- `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md`
- `modules/t05_topology_between_rc_v2/AGENTS.md`
- `modules/t05_topology_between_rc_v2/SKILL.md`
- `modules/t05_topology_between_rc_v2/review-summary.md`

## 3. 哪些内容被从 `AGENTS.md` 收缩出去

以下稳定业务真相已从模块 `AGENTS.md` 收缩出去：

- 模块身份与顶层业务目标
- `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad` 的完整阶段链说明
- 详细输入 / 输出清单
- 质量门槛与成路 / 失败判据
- 运行验收边界说明

这些内容现在分别落在：

- `architecture/*`
- `INTERFACE_CONTRACT.md`
- `review-summary.md`

## 4. 新建的 `SKILL.md` 承担什么职责

`SKILL.md` 现在承担 T05-V2 专用可复用流程文档的职责，内容包括：

- 适用任务类型
- 开工前先读哪些源事实文档
- 标准执行步骤
- 关键检查点
- 常见失败点与回退方式
- 输出与验证要求

它不再承担模块真相主表面的职责。

## 5. `REAL_RUN_ACCEPTANCE.md` 现在被如何定义

- 该文件被正式定义为“运行验收与操作者清单”。
- 文件开头已补充边界说明，明确长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。
- 它继续保留 patch 清单、运行命令、阶段执行顺序、验收阅读顺序和失败定位方法。

## 6. legacy T05 与正式 T05 的文档关系现在如何表达

- 当前正式 T05：`modules/t05_topology_between_rc_v2/`
- legacy T05：`modules/t05_topology_between_rc/`
- 二者的关系是“当前正式模块 vs 历史参考模块”，而不是家族连续治理关系。
- 本轮已在 legacy T05 的 `AGENTS.md` 顶部增加最小 pointer，防止误读。

## 7. 还剩哪些后续问题，但不影响当前正式化

- `REAL_RUN_ACCEPTANCE.md` 仍承载较多操作者知识，后续需要持续与源事实同步。
- 参数面较大，当前契约文档采用“参数类别 + 稳定基线”的治理方式，后续如需更细粒度参数文档，需要独立轮次处理。
- 复杂 patch 上仍存在 `prior_based / unresolved` 比例偏高、same-pair 多 arc 解释成本高等问题，但这属于后续算法或更细致文档轮次，不阻塞本轮正式化。

## 8. 本轮没有做哪些事，为什么没做

- 没有修改算法、测试、运行脚本或入口逻辑：本轮是文档正式化，不是实现改造。
- 没有重命名 `modules/t05_topology_between_rc_v2/`：任务书明确不改物理目录名。
- 没有删除 legacy T05 文档：任务书要求保留历史参考。
- 没有扩展到 T04、T06 或全仓治理：本轮只处理 T05-V2。
