# 功能规格：Round 2C T04 + T06 模块文档正式化

**功能分支**: `004-t04-t06-doc-formalization`  
**实际 Git 分支**: `codex/004-t04-t06-doc-formalization`  
**创建日期**: 2026-03-17  
**状态**: 草案  
**输入**: 用户任务书，“将 T04 与 T06 从已有草案状态推进为最小可信正式模块文档面，建立清晰的模块级源事实、持久规则与可复用流程分层，同时保持现有物理目录与实现不变，只做文档正式化。”

## 澄清结论

### 会话 2026-03-17

- Q: T04 的 `architecture/*` 哪些 section 本轮必须正式化？  
  A: `00-current-state-research.md`、`01-introduction-and-goals.md`、`02-constraints.md`、`03-context-and-scope.md`、`04-solution-strategy.md`、`05-building-block-view.md`、`10-quality-requirements.md`、`11-risks-and-technical-debt.md`、`12-glossary.md` 全部进入最小正式文档面。
- Q: T06 的 `architecture/*` 哪些 section 本轮必须正式化？  
  A: 与 T04 相同，九个 section 全部进入最小正式文档面。
- Q: 两个模块是否已有稳定契约面？  
  A: 两个模块当前都已有 `INTERFACE_CONTRACT.md`。T04 的 contract 已存在且较重，需要把高层叙事收回 `architecture/*`；T06 的 contract 已存在，但需要基于实现与测试重新校准为可信最小契约，而不是照搬旧冻结口径。
- Q: 哪些内容要从各自 `AGENTS.md` 收缩出去？  
  A: 模块目标、完整 I/O 说明、详细业务规则、质量门槛与实现性叙事都要从 `AGENTS.md` 收缩，改由 `architecture/*` 与 `INTERFACE_CONTRACT.md` 承载。
- Q: 各自新建或重写 `SKILL.md` 的最小边界是什么？  
  A: 两个模块的 `SKILL.md` 都只承载模块专用复用流程，包括适用任务、先读文档、标准步骤、关键检查点、常见失败点与输出验证要求，不复制完整业务真相。
- Q: 两个模块若存在运行验收/操作说明类文档，如何与长期源事实分界？  
  A: T04 现有 `README.md` 与 `modules/t04_rc_sw_anchor/scripts/run_t04_batch_wsl.sh` 属于操作者/运行说明；长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。T06 当前没有独立运行验收文档，不额外伪造 runbook。
- Q: 本轮完成标准是什么？  
  A: T04 与 T06 均形成“`architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `SKILL.md` + `review-summary.md`”的最小正式文档面；若某模块当前 contract 仍有可信缺口，需明确记录但不伪造。
- Q: Phase A 完成后继续推进 Phase B 的条件是什么？  
  A: T04 正式化完成后，若未暴露 repo 级口径冲突、模块级硬冲突或“无法形成可信最小文档面”的阻塞项，则继续进入 T06；若出现此类冲突，则停在 T04 并上报。
- Q: 如果 T06 的模块成熟度口径与项目级源事实文档冲突，该如何处理？  
  A: 允许做最小范围的项目级源事实修正，但只限于解除当前 formalization 的硬冲突，不扩大为全仓治理轮次。

## 用户场景与验证

### 用户故事 1 - 形成 T04 的最小正式文档面（优先级：P1）

作为 T04 维护者，我需要把 T04 的稳定业务真相集中到 `architecture/*` 与 `INTERFACE_CONTRACT.md`，这样 T04 不再依赖 `AGENTS.md`、`SKILL.md` 或 `README.md` 来解释核心模块语义。

**为什么优先级最高**：T04 是成熟核心模块，且当前文档重复最重；如果 T04 的 formalization 仍然不清晰，Phase B 就缺乏可信模板。

**独立验证方式**：只看 `architecture/*`、`INTERFACE_CONTRACT.md` 与 `review-summary.md`，即可理解 T04 的模块目标、策略结构、输入输出、关键约束与最小验收要求。

**验收场景**：

1. **给定** T04 模块目录，**当** 审核者阅读 `architecture/*` 时，  
   **则** 能理解 DriveZone-first、Between-Branches、hard-stop、continuous chain、multibranch 与 K16 的长期稳定职责分层。
2. **给定** T04 的 `AGENTS.md` 和 `SKILL.md`，**当** 审核者阅读时，  
   **则** 能看到规则和流程，但不会把它们误读为完整模块真相。

---

### 用户故事 2 - 形成 T06 的最小正式文档面（优先级：P2）

作为 T06 维护者，我需要把 T06 的稳定业务真相集中到 `architecture/*` 与 `INTERFACE_CONTRACT.md`，这样 T06 的当前实现状态和质量门槛可以由模块级源事实解释，而不是继续分散在 `AGENTS.md`、`SKILL.md` 和旧 contract 冻结口径中。

**为什么是这个优先级**：T06 相对简单，但它的现有文档与实现之间存在口径漂移风险；需要在不改代码的前提下把真实实现边界写清楚。

**独立验证方式**：只看 `architecture/*`、`INTERFACE_CONTRACT.md` 与 `review-summary.md`，即可理解 T06 的输入、输出、修复逻辑、虚拟节点规则和最小验收要求。

**验收场景**：

1. **给定** T06 模块目录，**当** 审核者阅读 `architecture/*` 时，  
   **则** 能理解“缺失端点引用检测 -> DriveZone 裁剪 -> virtual node 补点 -> 引用闭包”的稳定阶段结构。
2. **给定** T06 的 `INTERFACE_CONTRACT.md`，**当** 审核者检查契约时，  
   **则** 能看到可信最小契约，而不是与实现或测试矛盾的旧冻结叙事。

---

### 用户故事 3 - 保持双阶段推进与治理边界清晰（优先级：P3）

作为项目文档治理维护者，我需要在同一分支中先完成 T04，再判断是否继续到 T06，这样本轮不会在存在阻塞性治理冲突时继续扩大战线。

**为什么是这个优先级**：Round 2C 明确要求 phased implementation；如果 T04 暴露硬冲突而仍继续 T06，会把治理问题进一步扩散。

**独立验证方式**：查看 `spec`、`plan`、`tasks` 与最终执行报告，即可确认 Phase A、Phase B 的进入条件和执行结果。

**验收场景**：

1. **给定** Phase A 已完成，**当** 审核者查看执行报告时，  
   **则** 能明确看到“是否满足继续推进 T06 的条件”。
2. **给定** 本轮最终产物，**当** 审核者检查 repo 级治理边界时，  
   **则** 不会发现 `AGENTS.md` / `SKILL.md` 再次被写成源事实文档。

## 边界情况

- T04 的 `README.md` 和 batch 脚本保留为操作者材料；本轮不删除，但要明确它们不是长期源事实。
- T06 当前没有独立运行验收文档；如果没有可信新增必要，本轮不额外创建 runbook。
- T06 现有 contract 若与实现证据不一致，必须以代码和测试证据校准文档，但不得借机改实现。
- 若项目级源事实仍把 T06 写成“仅契约 / 仅骨架”，本轮允许最小修正 `SPEC.md` 或 `docs/PROJECT_BRIEF.md` 以反映仓库现实。
- 若 T04 暴露 repo 级硬冲突、无法形成可信最小正式文档面，Phase B 必须停止。

## 需求

### 功能需求

- **FR-001**：本轮必须产出 `spec.md`、`plan.md`、`tasks.md`，并在执行报告中给出 `analyze` 摘要。
- **FR-002**：本轮必须将 T04 的 `architecture/*` 正式化为最小可信模块源事实面。
- **FR-003**：本轮必须将 T06 的 `architecture/*` 正式化为最小可信模块源事实面。
- **FR-004**：本轮必须收缩 T04 与 T06 的 `AGENTS.md`，使其只保留稳定工作规则。
- **FR-005**：本轮必须更新或重建 T04 与 T06 的 `SKILL.md`，使其只承载可复用流程。
- **FR-006**：本轮必须更新 T04 与 T06 的 `INTERFACE_CONTRACT.md`；若当前无法形成可信契约，只能明确记录缺口，不能伪造。
- **FR-007**：本轮必须为 T04 的 `README.md` 或相关运行说明补充边界认知，但不删除历史文档。
- **FR-008**：本轮必须更新 T04 与 T06 的 `review-summary.md`，使其成为当前模块治理摘要。
- **FR-009**：本轮不得修改算法、测试、运行脚本、入口逻辑和物理目录名。
- **FR-010**：若 T06 formalization 被项目级旧口径阻塞，本轮必须只做最小范围的项目级源事实纠偏，不得借机扩大战线。

### 关键实体

- **最小正式文档面**：`architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`SKILL.md`、`review-summary.md` 组成的模块正式文档集合。
- **稳定工作规则**：面向执行者的短规则集合，不承载完整业务真相。
- **操作者文档**：面向运行、批处理、排障与快速上手的材料，不承担长期源事实职责。
- **阶段门控**：Phase A 完成后用于判断是否继续推进 Phase B 的治理检查点。

## 成功标准

### 可度量结果

- **SC-001**：T04 形成“`architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `SKILL.md` + `review-summary.md`”的最小正式文档面。
- **SC-002**：T06 形成同等层级的最小正式文档面；若契约仍有缺口，报告中需明确指出而不是伪造内容。
- **SC-003**：T04 与 T06 的 `AGENTS.md` 不再承载大段稳定业务真相；`SKILL.md` 只承载复用流程。
- **SC-004**：T04 的操作者材料与长期源事实边界清晰；T06 若无独立运行说明，不额外捏造 runbook。
- **SC-005**：本轮不引入算法、测试、脚本和目录结构变更。
