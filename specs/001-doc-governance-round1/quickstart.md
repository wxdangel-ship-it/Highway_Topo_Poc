# 快速阅读指南：Round 1 文档治理产物阅读顺序

## 用途

用这份指南可以在不从头通读全仓的前提下，快速审核 Round 1 的文档治理产物。

## 1. 先看变更规格产物

按以下顺序阅读：

1. [spec.md](/mnt/e/Work/Highway_Topo_Poc/specs/001-doc-governance-round1/spec.md)
2. [plan.md](/mnt/e/Work/Highway_Topo_Poc/specs/001-doc-governance-round1/plan.md)
3. [tasks.md](/mnt/e/Work/Highway_Topo_Poc/specs/001-doc-governance-round1/tasks.md)

审核目标：

- 确认范围仅限 Round 1
- 确认没有计划算法改动
- 确认只有 T04、T05-V2、T06 是深度审核模块

## 2. 再看现状研究

阅读：

1. [codebase-research.md](/mnt/e/Work/Highway_Topo_Poc/docs/codebase-research.md)
2. [current-doc-inventory.md](/mnt/e/Work/Highway_Topo_Poc/docs/doc-governance/current-doc-inventory.md)
3. [current-module-inventory.md](/mnt/e/Work/Highway_Topo_Poc/docs/doc-governance/current-module-inventory.md)

审核目标：

- 确认模块数量和模块清单
- 确认“源事实 / AGENTS / SKILL / 历史资料”的分类
- 确认 `t03`、`t05_v2`、`t10` 的不一致问题被显式记录

## 3. 再看目标治理产物

阅读：

1. `docs/architecture/*`
2. `docs/doc-governance/target-structure.md`
3. `docs/doc-governance/migration-map.md`
4. `docs/doc-governance/review-priority.md`
5. `docs/doc-governance/module-doc-status.csv`

审核目标：

- 确认目标结构是分层的、非破坏性的
- 确认旧文档是被映射，而不是被删除
- 确认项目级和模块级的 arc42 章节集已经显式建立

## 4. 最后看重点模块审核包

对每个重点模块阅读：

- `modules/<module>/architecture/*`
- `modules/<module>/review-summary.md`

审核目标：

- 确认每个审核包都足够精炼、便于人工快速阅读
- 确认当前业务真相都来自现有仓库证据，而不是凭空发明
- 确认待确认问题已被显式写出

## 5. 以执行报告收尾

阅读：

- `docs/doc-governance/round1-exec-report.md`

审核目标：

- 确认任务书要求的 8 个问题已作答
- 确认未决事项有清单
- 确认非目标被遵守
