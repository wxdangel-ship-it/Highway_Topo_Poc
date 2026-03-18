# Round 010 计划

## 范围

本轮只处理 T04 / T05-V2 的标准 Skill 最终收口、active 文档口径统一、`main` 合入与本地治理分支清理。

## 结构决策

- 标准 Skill 包继续位于 repo root：
  - `.agents/skills/t04-doc-governance/`
  - `.agents/skills/t05v2-doc-governance/`
- 顶层 `SKILL.md` 只保留高层入口
- 详细 SOP 统一下沉到 `references/README.md`
- 模块根 `SKILL.md` 在本轮移入 `history/SKILL.legacy.md`，不再保留 active 双入口

## 文档边界

- 长期真相：`architecture/*`
- 稳定契约：`INTERFACE_CONTRACT.md`
- 持久规则：`AGENTS.md`
- 可复用流程：repo root `.agents/skills/<skill-name>/SKILL.md`
- 详细流程补充：repo root `.agents/skills/<skill-name>/references/README.md`

## 需要更新的 active 文档

- repo 级：`AGENTS.md`、`docs/repository-metadata/README.md`、`docs/repository-metadata/repository-structure-metadata.md`、`docs/repository-metadata/code-boundaries-and-entrypoints.md`
- 治理盘点：`docs/doc-governance/README.md`、`docs/doc-governance/current-doc-inventory.md`、`docs/doc-governance/current-module-inventory.md`
- T04：`AGENTS.md`、`review-summary.md`、`README.md`、必要的 `architecture/*`
- T05-V2：`AGENTS.md`、`review-summary.md`、必要的 `architecture/*` 与 `history/README.md`

## 合并策略

1. 先提交并推送工作分支
2. 切到 `main`
3. `git pull --ff-only origin main`
4. `git merge --ff-only codex/010-finalize-standard-skills-and-mainline`
5. 若成功则 `git push origin main`
6. 仅在 `main` push 成功后，按祖先检查删除本地治理分支

## 风险控制

- 不扩展到 T06 或其它模块的 Skill 迁移
- 不把旧模块根 `SKILL.md` 移为新指针文件
- 若 `main` 不是 fast-forward 可合并，立即停止在已推送工作分支
