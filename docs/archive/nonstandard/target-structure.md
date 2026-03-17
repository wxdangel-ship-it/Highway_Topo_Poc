# 目标结构

## 状态

- 当前状态：已吸收 Round 2A、Round 2B、Round 2C、Round 3A 与 Round 3B 的治理结论
- 核心原则：主阅读路径只保留当前 source-of-truth 与 active governance 文档；历史治理过程文档和旧变更工件统一下沉到 `history / archive`

## 分层职责

| 层级 | 主要目的 | 目标位置 | 应放内容 | 不应放内容 |
|---|---|---|---|---|
| 项目级源事实 | 项目级长期架构、范围、生命周期与上下文 | `SPEC.md`、`docs/architecture/`、`docs/doc-governance/module-lifecycle.md` | 目标、约束、上下文、方案策略、生命周期状态、质量、风险、术语 | 单次变更计划、模块级执行步骤 |
| 模块级源事实 | 模块级长期架构与契约真相 | `modules/<module>/architecture/` + `INTERFACE_CONTRACT.md` | 模块目标、范围、约束、构件、质量、风险、术语、契约细节 | 项目级治理规则、临时阶段说明 |
| 持久规则 | 稳定操作与协作规则 | `AGENTS.md`、`docs/doc-governance/README.md`、`modules/<module>/AGENTS.md` | 执行姿态、协作规则、阅读顺序、文档指针 | 完整业务定义 |
| 可复用工作流 | 可重复执行的流程 | `modules/<module>/SKILL.md`、少量 runbook / 流程说明 | 执行步骤、检查点、常见排障 | 完整模块真相 |
| 当前变更工件 | 当前轮次的推理与执行计划 | `specs/<change-id>/` | `spec`、`plan`、`tasks`、研究与审核指南 | 长期架构真相 |
| 历史治理过程 | 历史 round 报告、治理执行记录 | `docs/doc-governance/history/` | 过程证据、历史结论、阶段总结 | 当前 source-of-truth 身份 |
| 历史变更工件 | 历史 specs 与附属研究材料 | `specs/archive/` | 历史 `spec / plan / tasks`、研究、检查清单 | 当前 active 变更入口 |

## 项目级目标树

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
|   +-- 08-crosscutting-concepts.md
|   +-- 09-decisions/
|   |   +-- README.md
|   +-- 10-quality-requirements.md
|   +-- 11-risks-and-technical-debt.md
|   +-- 12-glossary.md
+-- doc-governance/
    +-- README.md
    +-- module-lifecycle.md
    +-- current-doc-inventory.md
    +-- current-module-inventory.md
    +-- migration-map.md
    +-- module-doc-status.csv
    +-- review-priority.md
    +-- target-structure.md
    +-- history/
        +-- README.md
        +-- round*.md
```

## 变更工件目标树

```text
specs/
+-- 006-governance-archive-cleanup/
|   +-- spec.md
|   +-- plan.md
|   +-- tasks.md
+-- archive/
    +-- README.md
    +-- 001-doc-governance-round1/
    +-- 002-doc-governance-decision-alignment/
    +-- 003-t05v2-doc-formalization/
    +-- 004-t04-t06-doc-formalization/
    +-- 005-module-lifecycle-retirement-governance/
```

## 生命周期驱动的模块目标结构

### Active 模块

```text
modules/<module_id>/
+-- AGENTS.md
+-- SKILL.md
+-- INTERFACE_CONTRACT.md
+-- architecture/
|   +-- 00-current-state-research.md
|   +-- 01-introduction-and-goals.md
|   +-- 02-constraints.md
|   +-- 03-context-and-scope.md
|   +-- 04-solution-strategy.md
|   +-- 05-building-block-view.md
|   +-- 10-quality-requirements.md
|   +-- 11-risks-and-technical-debt.md
|   +-- 12-glossary.md
+-- review-summary.md
```

### Historical Reference 模块

```text
modules/<module_id>/
+-- AGENTS.md                # 开头补“历史参考”指针
+-- INTERFACE_CONTRACT.md    # 保留历史契约
+-- SKILL.md                 # 保留历史流程
+-- 其他历史审计 / 历史说明
```

### Retired 模块

```text
modules/<module_id>/
+-- AGENTS.md                # 开头补“已退役”指针
+-- INTERFACE_CONTRACT.md    # 保留历史契约
+-- SKILL.md                 # 保留历史流程
+-- 既有历史文档 / 实现痕迹
```

## 落位规则

### `docs/doc-governance/README.md`

- 当前治理主入口
- 负责告诉读者“现在从哪里开始看”
- 不承载项目级或模块级业务真相

### `docs/doc-governance/history/`

- 只保留历史治理过程文档
- 不替代当前 source-of-truth

### `specs/archive/`

- 只保留历史变更工件
- 用于审计与追溯
- 当前 active 变更只看未归档目录

### `AGENTS.md`

只保留：

- 持久操作规则
- 文档入口与阅读顺序
- 冲突处理与范围保护

### 历史文档

历史审计、阶段说明、历史 round 报告和旧 `specs` 继续保留，但退出主阅读路径；后续如需回看，应经由 `README` 索引进入。
