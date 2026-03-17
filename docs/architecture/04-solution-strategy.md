# 04 方案策略

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：
  - `docs/codebase-research.md`
  - `docs/doc-governance/current-doc-inventory.md`
  - `docs/doc-governance/current-module-inventory.md`
- 审核重点：
  - 确认策略是否保持非破坏性
  - 确认分层设计是否便于后续轮次落地

## 策略摘要

Round 1 采用非破坏、分层的文档治理策略：

1. 盘点当前状态
2. 分类现有文档职责
3. 建立目标架构骨架
4. 将旧文档映射到未来职责
5. 创建可审核的重点模块包
6. 把大范围迁移与重写延后到后续轮次

## 分层策略

- `SPEC.md` 继续作为当前顶层项目规格基线。
- `docs/architecture/` 成为未来项目级长期架构文档面。
- `modules/<module>/architecture/` 成为未来模块级长期架构文档面。
- `AGENTS.md` 只保留持久执行规则。
- `SKILL.md` 只保留可复用操作流程。
- `specs/<change-id>/` 负责承载变更专用推理与执行计划。

## 聚焦策略

- 本轮深度审核：
  - T04
  - T05-V2
  - T06
- 本轮只做盘点与映射，后续再深迁移：
  - T00
  - T01
  - T02
  - legacy T05
  - T07
  - T10

## 迁移策略

- 所有旧文档原位保留。
- 先建立新的落位结构。
- 通过迁移映射把旧文档指向新职责边界。
- 未决问题全部显式保留，不做静默处理。

## 待确认问题

- Round 2 开始时，legacy T05 与 T05-V2 是否应先拥有一份家族级总览文档，再进入深度迁移？
