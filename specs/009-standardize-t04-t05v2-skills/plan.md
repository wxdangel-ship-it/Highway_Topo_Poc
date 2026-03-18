# Round 4A 计划

## 范围

本轮只处理 T04 与 T05-V2 的 Skill 结构整改与口径统一。

## 结构决策

- 标准 Skill 包统一放在 repo root `.agents/skills/`
- T04 标准 Skill：`.agents/skills/t04-doc-governance/SKILL.md`
- T05-V2 标准 Skill：`.agents/skills/t05v2-doc-governance/SKILL.md`
- 模块根目录旧 `SKILL.md` 不再作为 active 标准入口；本轮保留最小指针版，避免局部路径认知断裂

## 文档边界

- 长期真相：`architecture/*`
- 稳定契约：`INTERFACE_CONTRACT.md`
- 持久规则：`AGENTS.md`
- 可复用流程：repo root `.agents/skills/<skill-name>/SKILL.md`
- 模块根目录 `SKILL.md`：仅在本轮作为最小指针，不再承载正文流程

## 需要更新的 active 文档

- repo 级：`AGENTS.md`、`docs/repository-metadata/README.md`、`docs/repository-metadata/repository-structure-metadata.md`
- 治理盘点：`docs/doc-governance/current-doc-inventory.md`、`docs/doc-governance/current-module-inventory.md`
- 项目级结构说明：`SPEC.md`、`docs/architecture/*` 中涉及 Skill 位置与职责的条目
- T04：`AGENTS.md`、`review-summary.md`、必要时 `architecture/*`
- T05-V2：`AGENTS.md`、`review-summary.md`、必要时 `architecture/*` 与 `history/README.md`

## 实施策略

1. 先创建标准 Skill 包并迁移流程内容
2. 再把旧模块根 `SKILL.md` 收缩成最小指针
3. 最后统一 repo 级与模块级 active 文档的 Skill 口径

## 风险控制

- 不改算法与脚本
- 不借机重写模块真相
- 若某文档只能保留旧引用，则明确改成“最小指针”而不是继续把模块根 `SKILL.md` 当正文流程面
