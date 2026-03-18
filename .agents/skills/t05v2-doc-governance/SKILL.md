---
name: t05v2-doc-governance
description: 用于正式 T05-V2 的文档治理、验收说明边界复核、模块级口径对齐与标准文档面维护。仅在任务需要更新或审查 `modules/t05_topology_between_rc_v2` 的 architecture、contract、review summary、历史运行验收说明或模块级规则时触发；不要在算法调整、脚本迁移、legacy T05 深迁移或跨模块实现任务中使用。
---

# T05-V2 文档治理 Skill

## 适用任务

- T05-V2 模块文档治理、正式化或口径对齐
- T05-V2 的 `architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`review-summary.md` 维护
- T05-V2 真实运行结果的文档化复核与验收说明更新
- 需要在源事实、稳定工作规则与运行验收文档之间做边界检查的任务

本 Skill 不替代 T05-V2 的源事实文档；长期真相仍以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。

## 先读哪些源事实文档

按以下顺序读取：

1. `modules/t05_topology_between_rc_v2/architecture/01-introduction-and-goals.md`
2. `modules/t05_topology_between_rc_v2/architecture/05-building-block-view.md`
3. `modules/t05_topology_between_rc_v2/architecture/10-quality-requirements.md`
4. `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md`
5. `modules/t05_topology_between_rc_v2/review-summary.md`

只有在需要真实运行或验收细节时，再读取：

6. `modules/t05_topology_between_rc_v2/history/REAL_RUN_ACCEPTANCE.md`

如果任务涉及 repo 级口径，再补读 repo root `AGENTS.md`、`SPEC.md` 和项目级 `docs/architecture/*`。

## 标准执行步骤

1. 先确认任务是否只涉及 T05-V2；若涉及其他模块或算法逻辑，停止并拆分任务。
2. 先核对当前正式定位：当前正式 T05 是 `modules/t05_topology_between_rc_v2/`，legacy T05 仅作历史参考。
3. 先更新 `architecture/*` 或 `INTERFACE_CONTRACT.md`，再决定是否需要同步 `AGENTS.md`、标准 Skill 包、`history/REAL_RUN_ACCEPTANCE.md`、`review-summary.md`。
4. 如需引用实现事实，优先回看 `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`、`tests/test_t05v2_pipeline.py` 和 `scripts/t05v2_*.sh`，不要凭空补业务结论。
5. 若任务涉及运行验收说明，明确写出“长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准”。
6. 结束前检查 legacy T05 是否需要最小 pointer；除非任务明确要求，否则不做 legacy 深迁移。

## 关键检查点

- `AGENTS.md` 是否仍然足够短，只保留稳定工作规则。
- 标准 Skill 包是否只承载流程，不复制完整模块真相。
- `INTERFACE_CONTRACT.md` 是否保留了输入、输出、入口、参数类别、示例和验收标准。
- `architecture/05-building-block-view.md` 是否仍清楚表达 `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad`。
- `history/REAL_RUN_ACCEPTANCE.md` 是否仍被明确定义为运行验收文档，而不是长期真相。

## 常见失败点与回退方式

- 如果发现稳定真相又回流到 `AGENTS.md` 或标准 Skill 包，回退到 `architecture/*` 与 `INTERFACE_CONTRACT.md` 重整边界。
- 如果运行验收文档与源事实口径不一致，优先修正源事实，再在运行验收文档增加指针或同步说明。
- 如果任务要求修改算法、脚本或目录名，停止当前 Skill 流程，改走独立任务与独立 change spec。
- 如果 legacy T05 材料与当前正式 T05 冲突，只把它当历史证据，不要回退到家族连续治理叙事。

## 输出与验证要求

- 输出应落在 T05-V2 模块文档面：`architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`review-summary.md`，以及必要时更新 `history/REAL_RUN_ACCEPTANCE.md`。
- 如果任务需要报告，报告中应明确说明源事实、稳定工作规则、工作流与运行验收文档的分工。
- 如任务涉及复用流程，应同步检查 `.agents/skills/t05v2-doc-governance/SKILL.md` 是否仍准确。
- 提交前至少执行 `git diff --check`，并复核与 repo root `AGENTS.md`、`SPEC.md`、项目级 `docs/architecture/*` 的一致性。
