# 实施计划：Round 2A 人工决策对齐整改

**分支**: `002-doc-governance-decision-alignment` | **日期**: 2026-03-17 | **规格**: [spec.md](/mnt/e/Work/Highway_Topo_Poc/specs/002-doc-governance-decision-alignment/spec.md)  
**输入**: 来自 `/specs/002-doc-governance-decision-alignment/spec.md` 的功能规格

**说明**：当前实际 Git 分支为 `codex/002-doc-governance-decision-alignment`；`002-doc-governance-decision-alignment` 是 spec-kit 使用的 feature identifier，用来兼容仓库的分支命名规则。

## 摘要

本次变更是一次轻量的 decision alignment pass。目标不是重做 Round 1，也不是进入 Round 2B 深迁移，而是把已经完成人工审核的 4 条治理决策正式写回仓库文档，并创建 repo root `AGENTS.md`。本轮只更新文档口径、治理规则和报告，不修改算法行为、模块运行逻辑或物理目录结构。

## 技术上下文

**语言/版本**：Markdown、CSV 与仓库治理元数据；仓库代码基于 Python 3.10，spec-kit CLI 0.3.0 运行在 WSL 的 Python 3.11 下  
**主要依赖**：Round 1 产物、`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/doc-governance/*.md`、`docs/architecture/*`、模块级审核摘要、Git  
**存储**：受 Git 跟踪的 Markdown / CSV 文件；不引入数据库  
**验证方式**：`spec/plan/tasks` 一致性复核、残留旧口径扫描、`git diff --check`、Git 状态检查  
**目标平台**：Windows 工作区下的仓库文档体系，辅以 WSL 工具链  
**项目类型**：面向 Python 仓库的 brownfield 文档治理补丁轮  
**性能目标**：在当前分支上快速固化人工决策，并保持后续可审阅、可继续迁移的治理底座  
**约束**：不改算法、不改目录、不删 legacy 文档、保持中文文档约定、不进入 Round 2B  
**规模/范围**：更新项目级源事实、治理文档、若干项目级架构草案、T05-V2/T06/T04 的少量模块级文档，以及新增 root `AGENTS.md` 与 Round 2A 报告

## 宪章检查

*GATE: 在开始文档写回前通过；在提交前复核。*

| 检查项 | 结果 | 说明 |
|---|---|---|
| 是否继续保持分层源事实 | PASS | 本轮只修正项目级/治理级口径，不改分层模型 |
| `AGENTS.md` 是否保持小而稳定 | PASS | 新建 root `AGENTS.md` 只承载 repo 级 durable guidance |
| `SKILL.md` 是否未被错误扩张 | PASS | 本轮不改 `SKILL.md` 角色 |
| 是否继续遵守默认中文文档 | PASS | 本轮新增和改写文档全部保持中文 |
| 是否先 analyze 再做广泛变更 | PASS | 先完成轻量 `spec/plan/tasks` 与 analyze，再集中改写文档 |
| 是否避免扩大为代码改造 | PASS | 本轮完全不碰算法与运行逻辑 |

## 项目结构

### 文档产物（本次变更）

```text
specs/002-doc-governance-decision-alignment/
+-- spec.md
+-- plan.md
+-- tasks.md
```

### 仓库结构（本轮重点）

```text
SPEC.md
AGENTS.md
docs/
+-- PROJECT_BRIEF.md
+-- architecture/
|   +-- 01-introduction-and-goals.md
|   +-- 02-constraints.md
|   +-- 03-context-and-scope.md
|   +-- 04-solution-strategy.md
|   +-- 09-decisions/README.md
|   +-- 10-quality-requirements.md
|   +-- 11-risks-and-technical-debt.md
+-- doc-governance/
    +-- current-doc-inventory.md
    +-- current-module-inventory.md
    +-- migration-map.md
    +-- module-doc-status.csv
    +-- review-priority.md
    +-- round1-exec-report.md
    +-- round2a-decision-alignment-report.md
    +-- target-structure.md
modules/
+-- t04_rc_sw_anchor/architecture/03-context-and-scope.md
+-- t05_topology_between_rc_v2/
|   +-- architecture/
|   +-- review-summary.md
+-- t06_patch_preprocess/architecture/
```

## 决策对齐范围

### 必须写回的正式结论

1. 当前正式 T05 模块为 `t05_topology_between_rc_v2`。
2. `t05_topology_between_rc` 为 legacy 历史参考模块，不再作为长期 family 治理对象。
3. `t03_marking_entity` 已退役。
4. `t10` 已退役。
5. repo root `AGENTS.md` 本轮创建。

### 不在本轮范围内的动作

- 重命名 `modules/t05_topology_between_rc_v2/`
- 删除 legacy 文档
- 迁移全部模块级文档内容
- 修改算法、测试、脚本或数据契约
- 合并到 `main`

## 需要更新的核心文档面

### 治理文档

- `docs/doc-governance/round1-exec-report.md`
- `docs/doc-governance/review-priority.md`
- `docs/doc-governance/target-structure.md`
- `docs/doc-governance/migration-map.md`
- `docs/doc-governance/current-module-inventory.md`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/doc-governance/module-doc-status.csv`

### 项目级与模块级补充文档

- `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/codebase-research.md`
- 受影响的 `docs/architecture/*`
- `modules/t05_topology_between_rc_v2/review-summary.md`
- 少量仍保留旧口径的模块级 `architecture/*.md`

### 新增文档

- `AGENTS.md`
- `docs/doc-governance/round2a-decision-alignment-report.md`

## 写回策略

### 口径替换策略

- 将 Round 1 中关于 T05/T05-V2、`t03`、`t10`、root `AGENTS` 的“建议 / 未决 / 待确认”统一替换为正式结论。
- 对 Round 1 历史记录，允许保留“当时未决”的历史事实，但必须在活跃治理文档中明确指出已被 Round 2A 覆盖。

### legacy 保留策略

- legacy T05、`t03`、`t10` 的现有资料继续保留。
- 文档中要明确这些资料是历史参考或历史遗留，而不是当前活跃治理主线。

### root `AGENTS.md` 策略

- 文件控制在一页左右。
- 只写 durable guidance，不写完整业务真相。
- 只覆盖 repo 级规则，不替代模块级 `AGENTS.md`。

## Analyze 计划

Round 2A 的 analyze 以文档一致性为主，重点回答：

1. `spec.md` 的 4 条决策是否都在 `plan.md` 中找到对应文档面？
2. `tasks.md` 是否覆盖所有必须更新或创建的文件？
3. 活跃治理文档中是否仍残留旧未决口径？
4. 本轮是否引入与 Round 1 目标结构冲突的新职责或新目录？
5. 本轮是否额外扩张成深迁移或代码改造？

## 实施策略

### 工作顺序

1. 完成 Round 2A 的 `spec/plan/tasks`。
2. 先更新治理文档，再修正项目级文档和模块级摘要。
3. 创建 root `AGENTS.md`。
4. 输出 Round 2A 执行报告并写入 analyze 摘要。
5. 执行 `git diff --check`、提交和推送。

### 本计划强制执行的非目标

- 不改算法
- 不改运行逻辑
- 不改物理目录名
- 不删 legacy 文档
- 不进入 Round 2B

## 复杂度跟踪

Round 2A 没有计划中的宪章违规项。
