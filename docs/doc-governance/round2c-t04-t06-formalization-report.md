# Round 2C：T04 + T06 模块文档正式化执行报告

## 1. 基线分支与工作分支

- 基线分支：`codex/003-t05v2-doc-formalization`
- 工作分支：`codex/004-t04-t06-doc-formalization`

## 2. 执行范围

- Phase A：正式化 `modules/t04_rc_sw_anchor`
- Phase B：在 T04 未暴露阻塞性治理冲突的前提下，正式化 `modules/t06_patch_preprocess`
- 本轮不改算法、测试、运行脚本、入口逻辑和物理目录名

## 3. Phase A 结论：T04 是否允许继续进入 T06

- 结论：允许继续
- 原因：
  - T04 已形成可信的最小正式文档面
  - 未发现 repo root `AGENTS.md`、项目级 `docs/architecture/*` 与 T04 模块文档之间的硬冲突
  - T04 的 contract 虽然仍较长，但可以与 `architecture/*` 形成清晰边界

## 4. Phase B 过程中的项目级冲突与处理

在进入 T06 formalization 前，发现项目级源事实存在一处阻塞性冲突：

- `SPEC.md` 与 `docs/PROJECT_BRIEF.md` 仍把 T06 表述为“仅契约 / 仅目录骨架”模块
- 仓库现实与测试证据表明 T06 已具备实现与测试

处理方式：

- 按本轮补充确认，只做了最小范围的项目级源事实修正
- 修正目标仅限于解除 T06 formalization 的硬冲突，没有扩展到其他模块或全仓治理话题

## 5. T04 的最小正式文档面

当前 T04 的最小正式文档面由以下文件组成：

- `modules/t04_rc_sw_anchor/architecture/*`
- `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
- `modules/t04_rc_sw_anchor/AGENTS.md`
- `modules/t04_rc_sw_anchor/SKILL.md`
- `modules/t04_rc_sw_anchor/review-summary.md`
- `modules/t04_rc_sw_anchor/README.md`（操作者总览，不是长期源事实）

### 从 T04 `AGENTS.md` 收缩出去的内容

- 完整模块目标与业务定义
- 详细输入 / 输出解释
- 复杂规则族叙事
- 长篇质量门槛与诊断说明

### T04 的 `SKILL.md` 现在承担的职责

- T04 文档治理与 contract 复核流程
- README / contract / architecture 边界检查
- 关键实现证据回看顺序与常见失败点提示

### T04 运行验收 / 操作者文档的当前定义

- T04 没有单独的 `REAL_RUN_ACCEPTANCE.md`
- `README.md` 与相关脚本被定义为操作者材料
- 长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准

## 6. T06 的最小正式文档面

当前 T06 的最小正式文档面由以下文件组成：

- `modules/t06_patch_preprocess/architecture/*`
- `modules/t06_patch_preprocess/INTERFACE_CONTRACT.md`
- `modules/t06_patch_preprocess/AGENTS.md`
- `modules/t06_patch_preprocess/SKILL.md`
- `modules/t06_patch_preprocess/review-summary.md`

### 从 T06 `AGENTS.md` 收缩出去的内容

- 完整模块定义与阶段叙事
- 大段输入 / 输出契约细节
- 质量门槛与算法性解释
- 已过时的“固定零缓冲”叙述

### T06 的 `SKILL.md` 现在承担的职责

- T06 文档治理与契约校准流程
- 源事实文档与实现 / 测试证据之间的一致性复核
- 关键边界检查、常见漂移点和回退方式

### T06 运行验收 / 操作者文档的当前定义

- T06 当前不存在独立运行验收文档
- 本轮没有伪造新的 runbook
- 运行入口、产物和验收边界统一由 `architecture/*` 与 `INTERFACE_CONTRACT.md` 解释

## 7. 两个模块是否仍缺 source-of-truth 内容

### T04

- 不缺阻塞当前正式化的关键源事实内容
- 后续可选补强项：
  - 更细粒度的复杂规则决策记录
  - 更清晰的操作者材料维护机制

### T06

- 不缺阻塞当前正式化的关键源事实内容
- 后续可选补强项：
  - 更偏操作者视角的兼容路径说明
  - 若裁剪策略持续演进，可再拆更细的决策记录

## 8. Analyze 摘要

- T04 是否已形成最小正式文档面：是
- T06 是否已形成最小正式文档面：是
- 两个模块的 `AGENTS.md` 是否仍残留大量稳定业务真相：否，均已收缩为稳定工作规则
- 两个模块是否仍缺少关键源事实内容：否，不存在阻塞当前正式化的关键缺口
- 是否引入与 repo 级治理结构冲突的新问题：否；唯一冲突来自 T06 的项目级旧口径，已通过最小项目级修正解除

## 9. 本轮没有做哪些事，为什么没做

- 没有修改 T04 / T06 的算法、测试和运行脚本：因为本轮是文档正式化，不是实现改造
- 没有扩展到 T07、T02 或其他模块：因为本轮范围只覆盖 T04 与 T06
- 没有为 T06 新建独立运行验收手册：因为当前不存在可信且必要的专用 runbook 边界，强行新建会制造新的伪真相
- 没有清理历史文档或重命名目录：因为任务书明确禁止做破坏性迁移
