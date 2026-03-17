# 功能规格：Round 2B T05-V2 模块文档正式化

**功能分支**: `003-t05v2-doc-formalization`  
**实际 Git 分支**: `codex/003-t05v2-doc-formalization`  
**创建日期**: 2026-03-17  
**状态**: 草案  
**输入**: 用户任务书，“将 T05-V2 从已有草案状态推进为当前正式 T05 模块的最小可信文档面，建立清晰的模块级源事实、持久规则与可复用流程分层，同时保持 legacy T05 为历史参考，不做家族连续治理。”

## 澄清结论

### 会话 2026-03-17

- Q: T05-V2 的 `architecture/*` 里哪些 section 本轮必须正式化？  
  A: `00-current-state-research.md`、`01-introduction-and-goals.md`、`02-constraints.md`、`03-context-and-scope.md`、`04-solution-strategy.md`、`05-building-block-view.md`、`10-quality-requirements.md`、`11-risks-and-technical-debt.md`、`12-glossary.md` 全部进入“最小可信正式文档面”。
- Q: 哪些业务真相应保留在 `INTERFACE_CONTRACT.md`？  
  A: 输入、输出、入口、阶段入口、参数类别、示例和验收标准保留在契约文档；高层业务目标、上下文边界、构件关系和治理解释收回到 `architecture/*`。
- Q: 哪些内容要从 `AGENTS.md` 收缩出去？  
  A: 模块目标、阶段式业务链路、I/O 清单和高层硬约束等稳定业务真相从 `AGENTS.md` 收缩，改由 `architecture/*` 与 `INTERFACE_CONTRACT.md` 承载。
- Q: `REAL_RUN_ACCEPTANCE.md` 的边界是什么？  
  A: 继续保留为运行 / 验收文档，在文件开头补充短说明，明确长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。
- Q: 新建 `SKILL.md` 的最小边界是什么？  
  A: 只承载 T05-V2 文档与治理相关的可复用流程，包括适用任务、先读文档、执行步骤、检查点、常见失败点与输出验证要求，不复制完整业务真相。
- Q: legacy T05 的最小 pointer 需要做到什么程度？  
  A: 只需在必要位置增加最小指针，明确“当前正式 T05 文档面在 `modules/t05_topology_between_rc_v2/`，本目录仅为历史参考”，不做大迁移。
- Q: 本轮完成标准是什么？  
  A: T05-V2 形成“`architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `SKILL.md` + `review-summary.md`”的最小正式文档面，`REAL_RUN_ACCEPTANCE.md` 边界清晰，legacy T05 有最小 pointer，且 `analyze` 结果确认没有破坏当前项目级治理结构。

## 用户场景与验证

### 用户故事 1 - 形成最小正式模块源事实面（优先级：P1）

作为 T05-V2 模块维护者，我需要把稳定业务真相集中到 `architecture/*` 和 `INTERFACE_CONTRACT.md`，这样当前正式 T05 模块不再依赖 `AGENTS.md` 或运行验收文档来解释自身。

**为什么优先级最高**：如果正式模块仍然把长期真相分散在 `AGENTS` 和运行验收文档中，后续任何模块迁移都仍会以不稳定文档为依据。

**独立验证方式**：只阅读 `architecture/*`、`INTERFACE_CONTRACT.md` 与 `review-summary.md`，即可理解模块目标、阶段构件、上下文、约束、参数类别、输出与最小验收标准。

**验收场景**：

1. **给定** T05-V2 模块目录，**当** 审核者阅读 `architecture/*` 时，  
   **则** 可以独立理解 `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad` 的阶段链路和模块边界。
2. **给定** `INTERFACE_CONTRACT.md`，**当** 审核者查看契约文档时，  
   **则** 能看到输入、输出、入口、参数、示例与验收标准，而不是被大量架构叙事覆盖。

---

### 用户故事 2 - 收缩 AGENTS 并建立专用 SKILL（优先级：P2）

作为 T05-V2 模块维护者，我需要让 `AGENTS.md` 只保留稳定工作规则，同时新增专用 `SKILL.md` 承载可复用流程，这样执行规则和工作流就不会继续挤占源事实文档。

**为什么是这个优先级**：本轮正式化不仅是补文档内容，还要把“文档分层”真正落到当前正式模块上。

**独立验证方式**：只阅读 `AGENTS.md` 和 `SKILL.md`，即可确认它们分别承担稳定工作规则与可复用流程，而不再承担完整模块真相。

**验收场景**：

1. **给定** 收缩后的 `AGENTS.md`，**当** 审核者检查文件时，  
   **则** 能看到开工前先读、允许改动范围、验证要求和禁做事项，但看不到大段稳定业务真相。
2. **给定** 新建的 `SKILL.md`，**当** 执行者按照文档开展任务时，  
   **则** 能按统一流程复核源事实、收口文档、做边界检查和结果验证。

---

### 用户故事 3 - 明确运行验收文档与 legacy 指针边界（优先级：P3）

作为 T05-V2 模块维护者，我需要明确 `REAL_RUN_ACCEPTANCE.md` 和 legacy T05 文档的角色，这样正式模块文档面不会再与运行验收文档或历史参考目录混淆。

**为什么是这个优先级**：如果运行验收文档与 legacy 指针边界不清晰，审核者仍可能把旧家族语义重新带回正式模块。

**独立验证方式**：只看 `REAL_RUN_ACCEPTANCE.md`、legacy T05 的最小 pointer 和 `round2b` 执行报告，即可确认当前正式 T05 与 legacy T05 的文档关系。

**验收场景**：

1. **给定** `REAL_RUN_ACCEPTANCE.md`，**当** 审核者查看文件开头时，  
   **则** 能看到其为运行验收文档，长期源事实另有位置。
2. **给定** legacy T05 的最小 pointer，**当** 审核者进入 legacy 目录时，  
   **则** 不会再把它误读为当前正式 T05 文档面。

## 边界情况

- T05-V2 已经是当前正式 T05 模块，本轮不得回退到家族连续治理口径。
- `REAL_RUN_ACCEPTANCE.md` 仍有高价值操作者知识，但本轮不能把它升级成长期源事实。
- legacy T05 只保留历史参考；本轮只能补最小 pointer，不能顺手做 legacy 大迁移。

## 需求

### 功能需求

- **FR-001**：本轮必须完整产出 `spec.md`、`plan.md`、`tasks.md`，并在执行报告中给出 `analyze` 摘要。
- **FR-002**：本轮必须将 T05-V2 的 `architecture/*` 正式化为最小可信模块源事实面。
- **FR-003**：本轮必须更新 `INTERFACE_CONTRACT.md`，保留输入、输出、入口、参数、示例和验收标准，并削减过重的架构叙事。
- **FR-004**：本轮必须收缩 `AGENTS.md`，使其只保留稳定工作规则。
- **FR-005**：本轮必须新建 `SKILL.md`，作为 T05-V2 的专用可复用流程文档。
- **FR-006**：本轮必须明确 `REAL_RUN_ACCEPTANCE.md` 的运行 / 验收定位，必要时增加边界说明。
- **FR-007**：本轮必须为 legacy T05 增加最小 pointer，以避免与当前正式 T05 混淆。
- **FR-008**：本轮必须更新 `review-summary.md`，使其成为“当前正式 T05 模块的治理摘要”。
- **FR-009**：本轮不得修改算法、测试、运行脚本、入口逻辑和物理目录名。

### 关键实体

- **最小正式文档面**：`architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`SKILL.md`、`review-summary.md` 构成的正式模块文档集合。
- **运行验收文档**：面向真实运行、阶段验收和操作者清单的文档，不承担长期源事实职责。
- **legacy 指针**：在历史参考模块中用于澄清正式模块落位的最小说明。

## 成功标准

### 可度量结果

- **SC-001**：T05-V2 形成“`architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `SKILL.md` + `review-summary.md`”的最小正式文档面。
- **SC-002**：`AGENTS.md` 不再承载大段稳定业务真相；`SKILL.md` 只承载可复用流程。
- **SC-003**：`REAL_RUN_ACCEPTANCE.md` 明确为运行 / 验收文档，长期源事实位置清晰。
- **SC-004**：legacy T05 与正式 T05 的关系在文档中被表达为“历史参考 vs 当前正式模块”，而不是家族连续治理。
- **SC-005**：本轮不引入算法、测试、脚本和目录结构变更。 
