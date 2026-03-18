---
name: t04-doc-governance
description: 用于 T04 文档治理、模块级口径对齐、正式文档面维护与操作者材料边界复核。仅在任务需要更新或审查 `modules/t04_rc_sw_anchor` 的 architecture、contract、review summary、README 或模块级规则时触发；不要在算法修改、批处理脚本改造、patch 自动发现逻辑调整或跨模块实现任务中使用。
---

# T04 文档治理 Skill

## 适用任务

- T04 模块文档治理、正式化、口径对齐
- T04 的 `architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`review-summary.md`、`README.md` 维护
- T04 批处理入口、patch 自动发现入口与主 contract 的边界复核
- 需要在源事实、稳定工作规则与操作者材料之间做分层检查的任务

## 非适用任务

- 修改算法、批处理脚本、patch 自动发现逻辑或下游模块接口
- 跨模块实现改动
- 需要直接在脚本或代码里补业务行为的任务

## 先读哪些源事实文档

1. `modules/t04_rc_sw_anchor/architecture/01-introduction-and-goals.md`
2. `modules/t04_rc_sw_anchor/architecture/04-solution-strategy.md`
3. `modules/t04_rc_sw_anchor/architecture/05-building-block-view.md`
4. `modules/t04_rc_sw_anchor/architecture/10-quality-requirements.md`
5. `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
6. `modules/t04_rc_sw_anchor/review-summary.md`

如需详细检查点、边界情况或额外阅读材料，再读 `references/README.md`。

## 高层步骤

1. 先确认任务只涉及 T04 文档、流程或口径，不触发实现改动。
2. 先核对当前源事实与 contract，再决定 README、AGENTS 或治理摘要需要同步到什么程度。
3. 若需引用实现事实，优先回看 `cli.py`、`runner.py`、`metrics_breakpoints.py` 和相关测试，不凭空补业务结论。
4. 若涉及复杂规则族，优先在 `architecture/*` 中收口，再决定 contract 是否需要同步补充。
5. 若涉及批处理或 patch 自动发现入口，只说明它们的操作者角色，不把脚本本身写成长期真相。

## 输出与验证要求

- 输出应落在 T04 模块文档面：`architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`review-summary.md`、必要时 `README.md`。
- 如任务涉及流程复用或治理说明，应同步检查 `.agents/skills/t04-doc-governance/` 下的 `SKILL.md` 与 `references/README.md` 是否仍准确。
- 提交前至少执行 `git diff --check` 并复核与 repo 级治理口径的一致性。

## 详细说明位置

- 详细检查点、失败点、回退方式、边界情况见 `references/README.md`
