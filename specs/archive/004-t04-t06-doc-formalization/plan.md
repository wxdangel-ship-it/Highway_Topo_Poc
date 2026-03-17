# 实施计划：Round 2C T04 + T06 模块文档正式化

**分支**: `004-t04-t06-doc-formalization` | **日期**: 2026-03-17 | **规格**: [spec.md](/mnt/e/Work/Highway_Topo_Poc/specs/archive/004-t04-t06-doc-formalization/spec.md)
**输入**: 来自 `/specs/archive/004-t04-t06-doc-formalization/spec.md` 的功能规格

**说明**：当前实际 Git 分支为 `codex/004-t04-t06-doc-formalization`；`004-t04-t06-doc-formalization` 是 spec-kit 使用的 feature identifier，用来兼容仓库的分支命名规则。

## 摘要

本次变更只处理 `modules/t04_rc_sw_anchor` 与 `modules/t06_patch_preprocess`。目标是把两个模块从“已有 architecture 草案 + review-summary + contract/辅助文档混杂”推进到“最小可信正式文档面”，同时收缩各自 `AGENTS.md`、重建或更新各自 `SKILL.md`，并明确操作者文档与长期源事实的边界。实施采用双阶段：

1. Phase A：先正式化 T04
2. Phase B：仅在 T04 未暴露阻塞性治理冲突时，继续正式化 T06

## 技术上下文

**语言/版本**：Markdown 为主；仓库代码基于 Python 3.10，spec-kit CLI 0.3.0 运行在 WSL 的 Python 3.11 下
**主要依赖**：T04/T06 当前 `architecture/*`、`AGENTS.md`、`SKILL.md`、`INTERFACE_CONTRACT.md`、`review-summary.md`，以及对应 `src/`、`tests/`、T04 `README.md` / `scripts/`
**存储**：受 Git 跟踪的 Markdown 文件；不引入数据库
**验证方式**：文档分层复核、T04 阶段门控判断、`git diff --check`、与 repo root `AGENTS.md` / `SPEC.md` / `docs/architecture/*` 的一致性检查
**目标平台**：Windows 工作区下的仓库文档体系
**项目类型**：双模块 brownfield 文档深迁移
**约束**：不改算法、不改运行逻辑、不改脚本、不改目录、不删历史文档、不把 `AGENTS.md` / `SKILL.md` 再写成源事实
**规模/范围**：仅 T04、T06 模块文档面、本轮执行报告，以及必要时用于解除 T06 硬冲突的最小项目级源事实修正

## 宪章检查

*GATE: 在写正文前通过；Phase A 结束后复核；提交前再次复核。*

| 检查项 | 结果 | 说明 |
|---|---|---|
| 是否继续保持源事实分层 | PASS | 本轮明确把稳定真相收回 T04/T06 的 `architecture/*` 与 `INTERFACE_CONTRACT.md` |
| `AGENTS.md` 是否保持小而稳定 | PASS | 两个模块的 `AGENTS.md` 都只保留稳定工作规则 |
| `SKILL.md` 是否保持单一流程 | PASS | T04/T06 的 `SKILL.md` 只承载模块专用复用流程 |
| 是否继续使用中文文档 | PASS | 新增与改写正文均保持中文 |
| 是否避免扩大为代码改造 | PASS | 本轮不修改任何算法、测试、脚本和运行逻辑 |
| 是否保持分阶段推进 | PASS | T04 完成后先做继续条件检查，再进入 T06 |

## 项目结构

### 文档产物（本次变更）

```text
specs/archive/004-t04-t06-doc-formalization/
+-- spec.md
+-- plan.md
+-- tasks.md
docs/
+-- doc-governance/
    +-- round2c-t04-t06-formalization-report.md
```

### T04 文档面（目标）

```text
modules/t04_rc_sw_anchor/
+-- AGENTS.md
+-- SKILL.md
+-- INTERFACE_CONTRACT.md
+-- review-summary.md
+-- README.md
+-- architecture/
|   +-- 00-current-state-research.md
|   +-- 01-introduction-and-goals.md
|   +-- 02-constraints.md
|   +-- 03-context-and-scope.md
|   +-- 04-solution-strategy.md
|   +-- 05-building-block-view.md
|   +-- 10-quality-requirements.md
|   +-- 11-risks-and-technical-debt.md
|   +-- 12-glossary.md
```

### T06 文档面（目标）

```text
modules/t06_patch_preprocess/
+-- AGENTS.md
+-- SKILL.md
+-- INTERFACE_CONTRACT.md
+-- review-summary.md
+-- architecture/
|   +-- 00-current-state-research.md
|   +-- 01-introduction-and-goals.md
|   +-- 02-constraints.md
|   +-- 03-context-and-scope.md
|   +-- 04-solution-strategy.md
|   +-- 05-building-block-view.md
|   +-- 10-quality-requirements.md
|   +-- 11-risks-and-technical-debt.md
|   +-- 12-glossary.md
```

## 文档边界策略

### `architecture/*`

- 承载模块目标、上下文、约束、方案策略、构件视图、质量要求、风险与术语。
- `05-building-block-view.md` 必须给出模块内部稳定阶段/构件结构，而不是空泛概述。

### `INTERFACE_CONTRACT.md`

- 保持输入、输出、入口、参数类别、示例与验收标准。
- 若当前 contract 夹带大段架构叙事，收回 `architecture/*`。
- 若某处 contract 与实现证据不一致，以可验证的实现和测试证据校准文档，但不改代码。

### `AGENTS.md`

- 仅保留稳定工作规则：
  - 开工前先读什么
  - 允许改什么
  - 必做验证
  - 禁做事项
  - 与历史材料或相邻模块的关系处理原则

### `SKILL.md`

- 只保留模块专用复用流程：
  - 适用任务类型
  - 先读哪些源事实文档
  - 标准步骤
  - 关键检查点
  - 常见失败点 / 回退方式
  - 输出与验证要求

### 操作者文档

- T04：`README.md` 与 `modules/t04_rc_sw_anchor/scripts/run_t04_batch_wsl.sh` 视为操作者材料。
- T06：当前不额外创建独立运行验收文档；仅在现有材料中保持入口与验收边界清晰。
- 操作者文档若被更新，应明确“长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准”。

### 项目级冲突解除策略

- 如果 Phase B 发现 `SPEC.md` 或 `docs/PROJECT_BRIEF.md` 仍把 T06 写成“仅契约 / 仅目录骨架”，允许做最小修正以反映“仓库已实现、当前仅做文档正式化”的现实。
- 该修正只服务于解除 T06 formalization 的硬冲突，不扩展到其他模块或全仓治理结论。

## 分阶段推进策略

### Phase A：T04

- 先完成 T04 现状复核与正式化。
- 核对 T04 的 contract、README、AGENTS、SKILL 与实现证据之间是否存在 repo 级或模块级硬冲突。

### Phase A 结束后的继续条件

只有在以下条件全部满足时，才进入 Phase B：

1. T04 能形成可信最小正式文档面。
2. 未发现与 repo root `AGENTS.md`、`SPEC.md`、项目级 `docs/architecture/*` 冲突的硬口径。
3. 未发现“当前 contract 无法被可信校准”的阻塞性缺口。

若不满足，则停在 T04，更新执行报告并停止，不继续 T06。

### Phase B：T06

- 在 T04 无阻塞冲突的前提下，复用同样的边界策略正式化 T06。
- 重点关注 T06 的 contract 与实现/测试是否一致，以及当前是否真的需要独立 runbook。

## Analyze 计划

Round 2C 的 analyze 重点回答：

1. T04 是否已形成最小正式文档面？
2. T06 是否已形成最小正式文档面？
3. 两个模块的 `AGENTS.md` 是否仍残留大量稳定业务真相？
4. 两个模块是否仍缺少关键源事实内容？
5. 是否引入与 repo 级治理结构冲突的新问题？

## 实施策略

### 工作顺序

1. 复核 T04/T06 当前文档、实现、脚本和测试证据。
2. 先完成 `spec`、`plan`、`tasks`。
3. 进入 Phase A，正式化 T04。
4. 做 T04 阶段结论检查。
5. 若通过门控，再进入 Phase B，正式化 T06。
6. 若 Phase B 发现项目级旧口径阻塞，则先做最小项目级源事实修正，再完成 T06 文档面。
7. 输出 Round 2C 执行报告。
8. 做 `analyze` 摘要、校验、提交和推送。

### 本计划强制执行的非目标

- 不改算法
- 不改测试
- 不改运行脚本
- 不改物理目录名
- 不删历史文档
- 不扩展到 T07 / T02 / 全仓治理轮次

## 复杂度跟踪

当前没有计划中的宪章违规项；T04 阶段结论检查是本轮唯一显式门控点。
