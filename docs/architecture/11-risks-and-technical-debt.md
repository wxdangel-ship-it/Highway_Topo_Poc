# 11 风险与技术债

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：
  - `docs/codebase-research.md`
  - `docs/doc-governance/current-doc-inventory.md`
  - `docs/doc-governance/current-module-inventory.md`
- 审核重点：
  - 确认这里记录的是文档治理风险，而不是运行时 bug 列表

## 当前文档风险

- 源事实目前分散在 contract、AGENTS、SKILL、README 和临时说明中。
- legacy T05 与 T05-V2 尚无正式家族映射。
- `t03` 存在于项目 taxonomy 中，但不在当前 repo 树中。
- `t10` 存在于 repo，但不在原始 `SPEC` taxonomy 中，且 `modules/` 与 `src/` 命名不一致。
- 历史 T05 审计与验收材料很有价值，但容易被误当成长期真相。

## Round 1 刻意保留的技术债

- 旧文档仍原位保留，尚未完全统一。
- 某些 inventory 说明同时描述了“变更前基线”和“Round 1 新目标结构”。
- root 级 agent-context 生成被延后。

## 延后处理的工作

- legacy 模块文档的全面迁移
- legacy T05 与 T05-V2 的家族级治理
- `t03` 与 `t10` 的 taxonomy 归一化
- 在 legacy 文档中补充源事实指针

## 待确认问题

- 当前 taxonomy 不一致中，哪些应在 Round 2 通过结构变更解决，哪些只需继续文档化？
