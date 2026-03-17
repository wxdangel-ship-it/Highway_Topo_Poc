# T06 文档与契约复核技能

## 适用任务

- T06 模块文档治理、正式化、口径对齐
- T06 的 `architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`review-summary.md` 维护
- T06 真实实现与契约之间的一致性复核
- 需要在源事实、稳定工作规则与复用流程之间做边界检查的任务

## 先读哪些源事实文档

1. `architecture/01-introduction-and-goals.md`
2. `architecture/04-solution-strategy.md`
3. `architecture/05-building-block-view.md`
4. `architecture/10-quality-requirements.md`
5. `INTERFACE_CONTRACT.md`
6. `review-summary.md`

只有在需要引用实现事实时，再读：

7. `src/highway_topo_poc/modules/t06_patch_preprocess/run.py`
8. `src/highway_topo_poc/modules/t06_patch_preprocess/pipeline.py`
9. `src/highway_topo_poc/modules/t06_patch_preprocess/io.py`
10. `src/highway_topo_poc/modules/t06_patch_preprocess/report.py`
11. `tests/test_t06_patch_preprocess.py`

## 标准执行步骤

1. 先确认任务只涉及 T06 文档，不触发实现改动。
2. 先核对 `architecture/*` 与 `INTERFACE_CONTRACT.md`，再决定 `AGENTS.md`、`SKILL.md`、`review-summary.md` 需要同步到什么程度。
3. 如需引用实现事实，优先以 `run.py`、`pipeline.py`、`io.py` 和测试为证据，不凭空补结论。
4. 若发现旧文档仍写着“零缓冲”或“仅骨架模块”等陈旧口径，应回到源事实文档纠正，而不是在 `AGENTS.md` 中打补丁。
5. 若任务涉及运行方式，只说明入口、产物与边界，不额外捏造独立 runbook。

## 关键检查点

- `AGENTS.md` 是否仍然足够短，只保留稳定工作规则。
- `SKILL.md` 是否只承载流程，不复制完整模块真相。
- `architecture/05-building-block-view.md` 是否清楚表达了 T06 的稳定阶段链。
- `INTERFACE_CONTRACT.md` 是否与当前实现和测试一致，尤其是 `drivezone_clip_buffer_m=5.0` 的默认语义。
- `review-summary.md` 是否已升级为当前模块治理摘要，而不是 Round 1 审核记录。

## 常见失败点与回退方式

- 如果稳定真相又回流到 `AGENTS.md` 或 `SKILL.md`，回退到 `architecture/*` 与 `INTERFACE_CONTRACT.md` 重整边界。
- 如果 contract 与实现证据冲突，优先修正文档，不修改代码。
- 如果有人要求把 T06 扩写成更广义的 patch 过滤或拓扑修复模块，停止当前技能流程，改走独立任务。
- 如果运行方式说明开始膨胀成新的长期真相文档，回退到“入口说明 + 指向源事实”的最小边界。

## 输出与验证要求

- 输出应落在 T06 模块文档面：`architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`SKILL.md`、`review-summary.md`。
- 如任务涉及报告，应明确区分源事实、稳定工作规则和复用流程。
- 提交前至少执行 `git diff --check`，并复核与 repo root `AGENTS.md`、`SPEC.md`、项目级 `docs/architecture/*` 的一致性。
