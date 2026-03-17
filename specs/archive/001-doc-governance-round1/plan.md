# 实施计划：Round 1 项目文档结构整改

**分支**: `001-doc-governance-round1` | **日期**: 2026-03-17 | **规格**: [spec.md](/mnt/e/Work/Highway_Topo_Poc/specs/archive/001-doc-governance-round1/spec.md)
**输入**: 来自 `/specs/archive/001-doc-governance-round1/spec.md` 的功能规格

**说明**：当前实际 Git 分支为 `codex/doc-governance-round1`；`001-doc-governance-round1` 是 spec-kit 使用的 feature identifier，用来兼容仓库的分支命名规则。

## 摘要

本次变更建立仓库第一轮 brownfield 文档治理基线。它不会修改算法行为，也不会修改模块运行逻辑。本轮先沉淀可信的现状盘点，再定义目标文档拓扑，最后只创建后续迁移所必需的最小可信骨架和重点审核包。Round 1 深入处理 T04、T05-V2、T06，其余模块只做盘点和映射。

## 技术上下文

**语言/版本**：以 Markdown、CSV 和仓库元数据为主；仓库代码基于 Python 3.10，spec-kit CLI 0.3.0 在 WSL 的 Python 3.11 下运行
**主要依赖**：`docs/` 与 `modules/` 下现有文档、spec-kit 工作流、Git、PowerShell、WSL shell
**存储**：受 Git 跟踪的 Markdown、JSON、CSV；不引入数据库
**验证方式**：产物存在性检查、跨文档一致性复核、spec-kit analyze；本轮不新增运行时算法测试
**目标平台**：Windows 工作区下的仓库文档体系，辅以 WSL 工具链
**项目类型**：面向 Python CLI 仓库的 brownfield 文档治理变更
**性能目标**：在一轮内建立可审核的文档治理基线，同时不影响运行时行为
**约束**：不改算法、不做破坏性迁移、不做大规模重命名、不删除旧文档，仅对 T04/T05-V2/T06 做深度审核
**规模/范围**：覆盖 `modules/` 下全部现存模块目录、主要项目级文档、完整治理骨架，以及三个重点审核模块包

## 宪章检查

*GATE: 在 Phase 0 研究前必须通过；在 Phase 1 设计后再次复核。*

| 检查项 | 结果 | 说明 |
|---|---|---|
| 分层源事实分离是否明确 | PASS | 计划为项目真相、模块真相、AGENTS、SKILL、change spec 分别设定归属位置 |
| `AGENTS.md` 是否保持小而稳定 | PASS | 目标结构明确将 AGENTS 限定为持久规则与指针 |
| `SKILL.md` 是否保持单一流程 | PASS | 目标结构明确将 Skill 限定为可复用工作流 |
| 是否定义 arc42 风格架构结构 | PASS | 本计划固定了项目级与模块级的最小章节集 |
| Brownfield 工作是否非破坏且可审核 | PASS | 旧文档保留，先建立映射和审核产物，再进入后续迁移 |
| 是否在大规模实现前完成 analyze | PASS | 只有在 `spec/plan/tasks` 一致性确认后，才允许创建骨架文档 |

## 项目结构

### 文档产物（本次变更）

```text
specs/archive/001-doc-governance-round1/
+-- spec.md
+-- plan.md
+-- research.md
+-- data-model.md
+-- quickstart.md
+-- tasks.md
```

### 仓库结构（根目录）

```text
SPEC.md
docs/
+-- architecture/
|   +-- 01-introduction-and-goals.md
|   +-- 02-constraints.md
|   +-- 03-context-and-scope.md
|   +-- 04-solution-strategy.md
|   +-- 08-crosscutting-concepts.md
|   +-- 09-decisions/
|   |   +-- README.md
|   +-- 10-quality-requirements.md
|   +-- 11-risks-and-technical-debt.md
|   +-- 12-glossary.md
+-- doc-governance/
    +-- current-doc-inventory.md
    +-- current-module-inventory.md
    +-- migration-map.md
    +-- module-doc-status.csv
    +-- review-priority.md
    +-- round1-exec-report.md
    +-- target-structure.md
modules/
+-- t04_rc_sw_anchor/
|   +-- architecture/
|   +-- review-summary.md
+-- t05_topology_between_rc_v2/
|   +-- architecture/
|   +-- review-summary.md
+-- t06_patch_preprocess/
    +-- architecture/
    +-- review-summary.md
src/
tests/
scripts/
```

**结构决策**：保持现有实现布局不变；项目级架构和治理文档统一落到 `docs/` 下；模块级架构草案只在三个重点模块下创建；`specs/archive/001-doc-governance-round1/` 作为本轮的临时 change workspace。

## 文档边界

### 项目级源事实

`docs/architecture/` 将承载未来长期稳定的项目级真相，用来吸收当前散落在 `SPEC.md`、`PROJECT_BRIEF`、T05 说明和执行类文档中的项目级信息。

项目级最小 arc42 章节集：

- `01-introduction-and-goals.md`
- `02-constraints.md`
- `03-context-and-scope.md`
- `04-solution-strategy.md`
- `08-crosscutting-concepts.md`
- `09-decisions/README.md`
- `10-quality-requirements.md`
- `11-risks-and-technical-debt.md`
- `12-glossary.md`

### 模块级源事实

重点模块的 `architecture/` 将成为未来长期稳定的模块级真相。

模块级最小 arc42 章节集：

- `00-current-state-research.md`
- `01-introduction-and-goals.md`
- `02-constraints.md`
- `03-context-and-scope.md`
- `04-solution-strategy.md`
- `05-building-block-view.md`
- `10-quality-requirements.md`
- `11-risks-and-technical-debt.md`
- `12-glossary.md`

### AGENTS 边界

`AGENTS.md` 只保留：

- 执行姿态
- 协作与协调规则
- 输入输出纪律提醒
- 指向项目级或模块级源事实文档的链接

`AGENTS.md` 不得继续成为业务定义、架构真相或验收逻辑的唯一承载位置。

### SKILL 边界

`SKILL.md` 只保留：

- 单一可复用流程
- 操作步骤
- 步骤顺序
- 常见排障检查点

`SKILL.md` 不得继续成为完整业务定义、冻结模块真相或 taxonomy 决策的唯一载体。

### 旧文档保留策略

本轮所有旧文档都保留原位。legacy 业务总结、审计报告、阶段说明与验收笔记只做映射，不做删除。Round 2 可以在其上补充源事实指针，但 Round 1 不做破坏性迁移。

## Phase 0：研究结论

详细研究记录见 [research.md](/mnt/e/Work/Highway_Topo_Poc/specs/archive/001-doc-governance-round1/research.md)。

关键结论：

1. 采用 arc42 风格的项目级与模块级骨架，作为长期目标结构。
2. Round 1 保持 T05-V2 为独立模块路径，但在文档治理中明确它属于 T05 family。
3. legacy T05 作为迁移上下文处理，而不是本轮深度审核对象。
4. `t03` 只作为 taxonomy gap 记录，不伪造缺失文档。
5. `t10` 本轮仅做 inventory，并把命名漂移标注为后续治理问题。
6. 本轮不做大规模内容迁移，也不生成 root agent context。

## Phase 1：设计产物

### 数据模型

文档治理相关数据模型记录在 [data-model.md](/mnt/e/Work/Highway_Topo_Poc/specs/archive/001-doc-governance-round1/data-model.md)。

### 契约说明

本轮不会新建外部 `contracts/` 目录。本次变更属于内部文档治理工作，不引入新的 API、协议或外部接口契约。

### 快速阅读指南

审核者阅读顺序与检查要点记录在 [quickstart.md](/mnt/e/Work/Highway_Topo_Poc/specs/archive/001-doc-governance-round1/quickstart.md)。

### Agent 上下文更新

本轮刻意不执行通用的 `update-agent-context.sh codex` 步骤。执行它会提前创建或更新 root 级 `AGENTS.md`，从而在目标治理结构尚未稳定前引入新的长期文档面。这是有意识的暂缓，而不是遗漏。

## Round 1 交付范围

### 必须产出的研究文档

- `docs/archive/nonstandard/codebase-research.md`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/doc-governance/current-module-inventory.md`

### 必须产出的治理文档

- `docs/archive/nonstandard/target-structure.md`
- `docs/archive/nonstandard/migration-map.md`
- `docs/archive/nonstandard/review-priority.md`
- `docs/doc-governance/module-doc-status.csv`
- `docs/doc-governance/history/round1-exec-report.md`

### 必须产出的项目级骨架

- `docs/architecture/` 下约定的全部项目级架构文件

### 必须产出的重点模块审核包

对以下每个模块：

- `modules/t04_rc_sw_anchor/`
- `modules/t05_topology_between_rc_v2/`
- `modules/t06_patch_preprocess/`

创建：

- 基于约定章节集的 `architecture/` 草案文件
- `review-summary.md`

## 文件命名规则

- 项目级 arc42 文件使用双位数字前缀，体现约定的章节顺序。
- 模块级 arc42 文件沿用相同规则，并额外以 `00-current-state-research.md` 作为起始文件。
- 治理映射文件统一放在 `docs/doc-governance/`，文件名直接表达用途。
- 轮次报告使用 `roundN-...` 风格命名。
- Round 1 不重命名、不删除旧文件。

## T05-V2 定位决策

Round 1 推荐方案：

- 仓库路径：保留 `modules/t05_topology_between_rc_v2/` 与 `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`
- 治理关系：将其归类为 `T05` 模块家族的第二代成员
- 迁移含义：在 `migration-map.md` 和重点审核摘要中同时记录“独立模块事实”与“家族映射关系”

## 实施策略

### 工作顺序

1. 完成并冻结现状研究。
2. 产出 spec-kit 的 `spec` 与澄清结论。
3. 生成 `plan` 与 `tasks`。
4. 在创建广泛骨架文档前，先执行 `analyze` 验证一致性。
5. 只创建 Round 1 被允许的文档骨架与重点审核包。
6. 最终以执行报告收尾，记录未决问题与非目标。

### 本计划强制执行的非目标

- 不改算法
- 不改模块运行逻辑
- 不做破坏性文档清理
- 不做大规模目录重命名
- 不尝试一轮迁移所有模块

## 复杂度跟踪

Round 1 没有计划中的宪章违规项。
