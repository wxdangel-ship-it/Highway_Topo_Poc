# 目标结构

## 状态

- 草案状态：Round 1 目标拓扑草案
- 来源依据：
  - `docs/codebase-research.md`
  - `docs/doc-governance/current-doc-inventory.md`
  - `specs/001-doc-governance-round1/plan.md`

## 分层职责

| 层级 | 主要目的 | 目标位置 | 应放内容 | 不应放内容 |
|---|---|---|---|---|
| 项目级源事实 | 项目级长期架构与上下文 | `docs/architecture/` | 目标、约束、上下文、方案策略、横切概念、质量、风险、术语 | 单次变更计划、模块级操作步骤 |
| 模块级源事实 | 模块级长期架构与语义真相 | `modules/<module>/architecture/` + `INTERFACE_CONTRACT.md` | 模块目标、范围、约束、构件、质量、风险、术语、契约细节 | 项目级治理规则、临时阶段说明 |
| 持久规则 | 稳定操作与协作规则 | `docs/*.md`、`modules/<module>/AGENTS.md` | 执行姿态、协作规则、文档指针 | 完整业务定义 |
| 可复用工作流 | 可重复执行的操作流程 | `modules/<module>/SKILL.md`、少量流程型说明 | 操作步骤、可复用运行流程、排障检查点 | 完整模块真相 |
| 变更专用规格 | 单次变更的推理与执行计划 | `specs/<change-id>/` | `spec`、`plan`、`tasks`、研究与审核指南 | 长期架构真相 |
| 历史证据 | 保留的验收、审计与阶段历史 | 现有历史位置 | 审计报告、阶段说明、验收记录 | 活跃源事实身份 |

## 项目级目标树

```text
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
```

## 模块级目标树

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

## 文件命名规则

- 项目级架构文档使用有序数字前缀。
- 模块级架构文档沿用同样顺序，并在最前面增加 `00-current-state-research.md`。
- 治理映射文档统一放在 `docs/doc-governance/`，文件名直接表明用途。
- 单次变更文件只放在 `specs/<change-id>/` 下。

## 落位规则

### AGENTS

只保留：

- 持久操作规则
- 模块边界
- 指向源事实文档的链接

### SKILL

只保留：

- 可复用工作流
- 执行步骤
- 常见运行排障

### INTERFACE_CONTRACT

继续作为稳定契约面，重点保留：

- 输入
- 输出
- 入口
- 参数
- 示例
- 验收标准

### 历史文档

历史审计和阶段文档本轮继续保留原位，后续轮次再决定是否补指针或做归档整理。

## T05 Family 规则

- `t05_topology_between_rc` 继续作为 legacy T05 模块。
- `t05_topology_between_rc_v2` 在 Round 1 继续保持物理独立模块路径。
- 治理文档必须显式展示它们的家族关系，而不是把其中一个静默折叠进另一个。
