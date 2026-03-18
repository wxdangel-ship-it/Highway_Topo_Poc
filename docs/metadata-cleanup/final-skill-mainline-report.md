# 标准 Skill 最终收口与主线合入报告

## 1. 分支信息

- 基线分支：`codex/009-standardize-t04-t05v2-skills`
- 工作分支：`codex/010-finalize-standard-skills-and-mainline`

## 2. 最终标准 Skill 包路径

- T04：`.agents/skills/t04-doc-governance/SKILL.md`
- T04 详细说明：`.agents/skills/t04-doc-governance/references/README.md`
- T05-V2：`.agents/skills/t05v2-doc-governance/SKILL.md`
- T05-V2 详细说明：`.agents/skills/t05v2-doc-governance/references/README.md`

## 3. 顶层 `SKILL.md` 保留内容

- metadata
- 适用任务
- 非适用任务
- 先读哪些 source-of-truth 文档
- 3 到 6 步高层流程
- 输出与验证要求
- 指向 `references/README.md`

## 4. `references/README.md` 承接内容

- 详细检查点
- 常见失败点
- 回退方式
- 边界情况
- 需要额外阅读的文档
- 细粒度验证习惯

## 5. 旧模块根 `SKILL.md` 处理结果

- `modules/t04_rc_sw_anchor/SKILL.md`：移入 `modules/t04_rc_sw_anchor/history/SKILL.legacy.md`
- `modules/t05_topology_between_rc_v2/SKILL.md`：移入 `modules/t05_topology_between_rc_v2/history/SKILL.legacy.md`

原因：旧文件中的信息已被标准 Skill 包与 `references/README.md` 完整承接；保留到 `history/` 只为审计与追溯，不再形成 active 双入口。

## 6. 已统一口径的 active 文档

- root `AGENTS.md`
- `docs/repository-metadata/README.md`
- `docs/repository-metadata/repository-structure-metadata.md`
- `docs/repository-metadata/code-boundaries-and-entrypoints.md`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/doc-governance/current-module-inventory.md`
- T04：`AGENTS.md`、`review-summary.md`、`README.md`、`architecture/00-current-state-research.md`、`architecture/11-risks-and-technical-debt.md`
- T05-V2：`AGENTS.md`、`review-summary.md`、`architecture/00-current-state-research.md`、`architecture/02-constraints.md`、`architecture/03-context-and-scope.md`、`architecture/11-risks-and-technical-debt.md`、`history/README.md`

## 7. root `AGENTS.md` 的最小修正

- 保持简洁，不新增结构说明书式内容
- 明确标准可复用流程以 repo root `.agents/skills/<skill-name>/SKILL.md` 为准
- 不再把模块根 `SKILL.md` 视为已标准化模块的标准入口

## 8. analyze 摘要

- T04 / T05-V2 的顶层 `SKILL.md` 已变成真正高层入口。
- 详细 SOP 已下沉到各自 `references/README.md`。
- active 文档中不再把 T04 / T05-V2 的模块根 `SKILL.md` 当成标准入口。
- 若 `main` 能 `ff-only` 合并，则本轮可安全主线合入；否则停止在已推送工作分支。
- 本地治理分支只在 `main` push 成功后才会清理。

## 9. 本轮没有做的事

- 没有修改算法、测试、运行脚本或入口逻辑，因为本轮只做 Skill 与文档收口。
- 没有扩展到 T06 或其它模块，因为本轮范围只覆盖 T04 / T05-V2。
- 没有删除远端治理分支，因为任务要求只清理本地治理分支。
