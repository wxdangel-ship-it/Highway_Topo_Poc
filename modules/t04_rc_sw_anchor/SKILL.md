# T04 文档与运行复核技能

## 适用任务

- T04 模块文档治理、正式化、口径对齐
- T04 的 `architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`review-summary.md`、`README.md` 维护
- T04 批处理入口、patch 自动发现入口与主 contract 的边界复核
- 需要在源事实、稳定工作规则与操作者材料之间做分层检查的任务

## 先读哪些源事实文档

1. `architecture/01-introduction-and-goals.md`
2. `architecture/04-solution-strategy.md`
3. `architecture/05-building-block-view.md`
4. `architecture/10-quality-requirements.md`
5. `INTERFACE_CONTRACT.md`
6. `review-summary.md`

只有在需要运行入口或操作者步骤时，再读：

7. `README.md`
8. `modules/t04_rc_sw_anchor/scripts/run_t04_batch_wsl.sh`
9. `scripts/run_t04_patch_auto_nodes.sh`

## 标准执行步骤

1. 先确认任务是否只涉及 T04 文档，不触发实现改动。
2. 先核对当前源事实与 contract，再决定 README、AGENTS、SKILL 需要同步到什么程度。
3. 若需引用实现事实，优先回看 `cli.py`、`runner.py`、`metrics_breakpoints.py` 和相关测试，不凭空补业务结论。
4. 若涉及复杂规则族，优先在 `architecture/*` 中收口，再决定 contract 是否需要同步补充。
5. 若涉及批处理或 patch 自动发现入口，只说明它们的操作者角色，不把脚本本身写成长期真相。

## 关键检查点

- `AGENTS.md` 是否仍然足够短，只保留稳定工作规则。
- `SKILL.md` 是否只承载流程，不复制完整模块真相。
- `architecture/05-building-block-view.md` 是否已清楚解释 T04 的稳定构件结构。
- `INTERFACE_CONTRACT.md` 是否仍聚焦输入、输出、参数、breakpoint 与验收。
- `README.md` 是否已明确自己是操作者总览，而不是长期源事实。

## 常见失败点与回退方式

- 如果稳定真相又回流到 `AGENTS.md`、`SKILL.md` 或 README，回退到 `architecture/*` 与 `INTERFACE_CONTRACT.md` 重整边界。
- 如果操作者材料与源事实不一致，优先修正源事实，再在 README 中同步指针或说明。
- 如果任务要求修改算法、批处理脚本、patch 自动发现脚本或下游模块接口，停止当前技能流程，改走独立任务。

## 输出与验证要求

- 输出应落在 T04 模块文档面：`architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`SKILL.md`、`review-summary.md`、必要时 `README.md`。
- 如任务涉及报告，应明确区分源事实、稳定工作规则、复用流程和操作者材料。
- 提交前至少执行 `git diff --check` 并复核与 repo 级治理口径的一致性。
