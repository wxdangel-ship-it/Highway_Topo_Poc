# 功能规格：Round 2A 人工决策对齐整改

**功能分支**: `002-doc-governance-decision-alignment`  
**实际 Git 分支**: `codex/002-doc-governance-decision-alignment`  
**创建日期**: 2026-03-17  
**状态**: 草案  
**输入**: 用户任务书，“将 Round 1 人工审核后已确认的治理决策写回文档，使 T05/T05-V2、t03、T10、root AGENTS 的口径不再处于未决状态，并为后续模块级文档迁移提供明确前提。”

## 澄清结论

### 会话 2026-03-17

- Q: 本轮必须更新哪些文件？  
  A: 至少更新 `docs/doc-governance/history/round1-exec-report.md`、`review-priority.md`、`target-structure.md`、`migration-map.md`、`current-module-inventory.md`、`current-doc-inventory.md`、`SPEC.md`、`modules/t05_topology_between_rc_v2/review-summary.md`，并按实际残留口径补充更新 `docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/codebase-research.md`、`docs/doc-governance/module-doc-status.csv` 等受影响文档。
- Q: 哪些旧表述必须删除或替换？  
  A: 必须移除 “T05 family 未定 / t03 缺失成员待决策 / T10 taxonomy pending / root AGENTS pending” 等旧表述，并改为正式决策口径。
- Q: root `AGENTS.md` 只承载哪些内容？  
  A: 只承载 repo 级 durable guidance，包括文档分层、源事实优先级、分支与 spec-kit 规则、文档语言规则、冲突处理规则和范围保护。
- Q: T05-V2 在正式身份与物理路径之间如何表述？  
  A: 正式口径为“当前正式 T05 = `t05_topology_between_rc_v2`”；物理路径保持 `modules/t05_topology_between_rc_v2/`，本轮不重命名目录。
- Q: `t03` / `T10` 的退役在 taxonomy 文档中如何表达？  
  A: 两者都标记为“已退役 / 历史遗留”，不再作为当前活跃 taxonomy 成员；保留历史资料与实现痕迹，但不再进入活跃治理主线。
- Q: 本轮完成标准是什么？  
  A: 完成轻量 `spec/plan/tasks/analyze`、写回 4 条人工决策、创建 root `AGENTS.md` 和 `round2a-decision-alignment-report.md`，并确保活跃治理文档中不再保留上述未决口径。

## 用户场景与验证

### 用户故事 1 - 对齐项目级与治理级口径（优先级：P1）

作为项目维护者，我需要把 Round 1 留下的未决治理口径改写为正式结论，这样后续文档迁移不再建立在悬而未决的判断上。

**为什么优先级最高**：如果项目级和治理级文档仍保留旧未决表述，后续模块迁移会继续重复讨论 T05、`t03`、`t10` 与 root `AGENTS` 的基本问题。

**独立验证方式**：只阅读 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/doc-governance/*.md` 和 `docs/architecture/*`，即可确认四条人工决策已经成为正式口径，而不是建议或待确认事项。

**验收场景**：

1. **给定** 已有 Round 1 治理文档，**当** 审核者查看治理文档时，  
   **则** 不再出现 “T05 family 未决”“`t03` 缺失成员待定”“T10 taxonomy pending”“root AGENTS 待生成” 作为活跃治理结论。
2. **给定** `SPEC.md` 和 `docs/PROJECT_BRIEF.md`，**当** 审核者检查模块口径时，  
   **则** 能看到“当前正式 T05 = T05-V2”“legacy T05 = 历史参考模块”“`t03` 已退役”“`t10` 已退役”。

---

### 用户故事 2 - 创建 root 级 durable guidance（优先级：P2）

作为项目维护者，我需要一个小而稳定的 repo root `AGENTS.md`，这样后续 agent 线程有统一的 durable guidance，而不必把长期规则散落在任务书和轮次报告中。

**为什么是这个优先级**：Round 1 已经建立了项目级和模块级源事实骨架，如果 root 级协作规则继续缺位，后续轮次仍会在执行层面重复漂移。

**独立验证方式**：只阅读 repo root `AGENTS.md`，即可确认文档分层、源事实优先级、分支/spec-kit 规则、默认中文规则、冲突处理和范围保护都已稳定落位。

**验收场景**：

1. **给定** 新创建的 `AGENTS.md`，**当** 审核者阅读文件时，  
   **则** 文件保持小、稳定、可执行，不承载完整业务真相。
2. **给定** 后续结构化治理轮次，**当** 执行者遵循 `AGENTS.md` 时，  
   **则** 会优先使用 spec-kit、独立分支和源事实文档，而不会在 `main` 上直接做结构化治理变更。

---

### 用户故事 3 - 形成可审计的 Round 2A 收尾记录（优先级：P3）

作为项目维护者，我需要一份简短的 Round 2A 执行报告，这样其他环境中的协作者可以快速知道本轮写回了什么、哪些文件受影响、还有没有残留旧口径。

**为什么是这个优先级**：Round 2A 的价值在于“把已定结论固化下来”；没有执行报告，外部审阅者仍需自行比对大量文档差异。

**独立验证方式**：只阅读 `docs/doc-governance/history/round2a-decision-alignment-report.md`，即可回答本轮采用的基线、4 条决策、更新文件范围、root `AGENTS` 规则摘要和残留问题。

**验收场景**：

1. **给定** Round 2A 报告，**当** 审核者查看“残留旧口径”部分时，  
   **则** 能明确知道当前活跃治理文档是否仍有旧未决表述。
2. **给定** Round 2A 报告，**当** 审核者查看“本轮没做什么”部分时，  
   **则** 能确认本轮没有进入 Round 2B、没有做大规模迁移，也没有修改算法代码。

## 边界情况

- `t05_topology_between_rc_v2` 的正式身份已经确定，但物理路径仍保留 V2 后缀；本轮不得试图通过改名来“消除”这一差异。
- `t03_marking_entity` 已退役，但 repo 中没有对应目录；本轮只能写回退役口径，不能伪造替代模块。
- `t10` 已退役，但现有模块目录和实现痕迹仍保留；本轮只能把它标为历史遗留，不能做目录清理。
- Round 1 历史 spec-kit 产物可以保留当时的未决记录，但必须在当前活跃治理文档中被明确 supersede。

## 需求

### 功能需求

- **FR-001**：本轮必须以轻量 spec-kit 方式产出 `spec.md`、`plan.md`、`tasks.md`，并在执行报告中给出 `analyze` 摘要。
- **FR-002**：本轮必须将以下 4 条人工决策写回活跃治理文档：  
  1. 当前正式 T05 = T05-V2；legacy T05 = 历史参考模块。  
  2. `t03_marking_entity` 已退役。  
  3. `t10` 已退役。  
  4. root `AGENTS.md` 本轮创建。
- **FR-003**：本轮必须更新 Round 1 仍保留旧口径的核心治理文档和必要的项目级文档。
- **FR-004**：本轮必须在 `modules/t05_topology_between_rc_v2/review-summary.md` 中将模块身份从“待定建议”改为“已确认定位”。
- **FR-005**：本轮必须创建 repo root `AGENTS.md`，且只承载 repo 级 durable guidance。
- **FR-006**：本轮必须创建 `docs/doc-governance/history/round2a-decision-alignment-report.md`，回答任务书要求的 8 个问题。
- **FR-007**：本轮不得改物理目录名，不得删除 legacy 文档，不得进入模块深迁移，不得修改算法或运行逻辑。
- **FR-008**：本轮新增或改写的自然语言正文必须继续遵循“默认中文”的文档规则。

### 关键实体

- **正式模块口径**：对当前活跃模块与退役模块的项目级正式表述。
- **历史参考模块**：保留历史材料，但不再进入活跃治理主线的模块或文档家族。
- **repo 级 durable guidance**：适用于整个仓库、轮次稳定、可长期复用的协作与执行规则。
- **活跃治理文档**：当前仍作为项目治理入口、审核基线或源事实索引的文档集合。

## 成功标准

### 可度量结果

- **SC-001**：`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/doc-governance/*.md` 和必要的 `docs/architecture/*` 中不再把 T05/T05-V2、`t03`、`t10`、root `AGENTS` 作为未决事项。
- **SC-002**：root `AGENTS.md` 已创建，并包含 repo 级规则摘要而非业务真相正文。
- **SC-003**：`modules/t05_topology_between_rc_v2/review-summary.md` 已明确写成“当前正式 T05 模块，物理路径保持 V2”。
- **SC-004**：Round 2A 执行报告可以独立回答本轮基线、写回决策、更新文件范围、残留旧口径和未做事项。
- **SC-005**：本轮不引入目录改名、legacy 删除、算法行为变更或 Round 2B 深迁移。
