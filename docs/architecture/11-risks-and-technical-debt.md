# 11 风险与技术债

## 状态

- 当前状态：项目级风险与技术债说明
- 来源依据：
  - `docs/archive/nonstandard/codebase-research.md`
  - `docs/doc-governance/current-doc-inventory.md`
  - `docs/doc-governance/current-module-inventory.md`
- 审核重点：
  - 确认这里记录的是文档治理风险，而不是运行时 bug 列表

## 当前文档风险

- 源事实仍分散在 contract、`AGENTS`、标准 Skill 包、`README` 和临时说明中。
- legacy T05 的历史材料很有价值，但容易被误当成当前正式 T05 的真相。
- 已退役模块 `t03`、`t10` 的历史痕迹仍可能被误读为当前活跃治理对象。
- 仍有部分模块尚未完成标准 Skill 包迁移，`AGENTS.md` 与模块根 `SKILL.md` 仍可能偏大。

## 当前刻意保留的技术债

- 旧文档仍原位保留，尚未完全统一。
- 某些 inventory 文档同时承担“基线说明”和“迁移指针”角色。
- T05-V2、T04、T06 之后仍需继续做模块级深迁移。

## 延后处理的工作

- 正式模块的深度文档迁移
- legacy 文档的指针化与归档整理
- frozen 模块的统一摘要整理
- 是否建立更细粒度的 ADR 集

## 当前无待确认项

模块身份相关的核心治理未决项已关闭；当前剩余的是迁移深度和排期问题。
