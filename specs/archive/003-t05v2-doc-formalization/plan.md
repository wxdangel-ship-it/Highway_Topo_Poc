# 实施计划：Round 2B T05-V2 模块文档正式化

**分支**: `003-t05v2-doc-formalization` | **日期**: 2026-03-17 | **规格**: [spec.md](/mnt/e/Work/Highway_Topo_Poc/specs/archive/003-t05v2-doc-formalization/spec.md)
**输入**: 来自 `/specs/archive/003-t05v2-doc-formalization/spec.md` 的功能规格

**说明**：当前实际 Git 分支为 `codex/003-t05v2-doc-formalization`；`003-t05v2-doc-formalization` 是 spec-kit 使用的 feature identifier，用来兼容仓库的分支命名规则。

## 摘要

本次变更只处理 `modules/t05_topology_between_rc_v2`。目标是把当前正式 T05 模块从“已有架构草案 + 审核摘要 + 契约文档”推进到“最小可信正式文档面”，同时收缩 `AGENTS.md`、新建 `SKILL.md`、明确 `REAL_RUN_ACCEPTANCE.md` 的运行文档边界，并为 legacy T05 增加最小历史参考指针。

## 技术上下文

**语言/版本**：Markdown 为主；仓库代码基于 Python 3.10，spec-kit CLI 0.3.0 运行在 WSL 的 Python 3.11 下
**主要依赖**：T05-V2 现有 `architecture/*`、`AGENTS.md`、`INTERFACE_CONTRACT.md`、`REAL_RUN_ACCEPTANCE.md`、`review-summary.md`，以及 `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`、`tests/test_t05v2_pipeline.py`、`scripts/t05v2_*.sh`
**存储**：受 Git 跟踪的 Markdown 文件；不引入数据库
**验证方式**：文档分层复核、`git diff --check`、与 root `AGENTS.md` / `SPEC.md` / `docs/architecture/*` 的一致性检查
**目标平台**：Windows 工作区下的仓库文档体系
**项目类型**：单模块 brownfield 文档深迁移
**性能目标**：在不触碰代码和目录结构的前提下，形成当前正式 T05 模块可持续维护的最小正式文档面
**约束**：不改算法、不改运行逻辑、不改脚本、不改目录、不删 legacy 文档、不回退到家族连续治理口径
**规模/范围**：仅 `modules/t05_topology_between_rc_v2` 文档面、必要的 legacy pointer，以及本轮执行报告

## 宪章检查

*GATE: 在写正文前通过；提交前复核。*

| 检查项 | 结果 | 说明 |
|---|---|---|
| 是否继续保持源事实分层 | PASS | 本轮明确把稳定真相收回 `architecture/*` 与 `INTERFACE_CONTRACT.md` |
| `AGENTS.md` 是否保持小而稳定 | PASS | 模块 `AGENTS.md` 仅保留稳定工作规则 |
| `SKILL.md` 是否保持单一流程 | PASS | 新建 `SKILL.md` 只承载 T05-V2 文档治理 / 正式化相关流程 |
| 是否继续使用中文文档 | PASS | 新增与改写正文均保持中文 |
| 是否避免扩大为代码改造 | PASS | 本轮不修改任何算法、测试、脚本和运行逻辑 |
| 是否与项目级治理结构一致 | PASS | 以 repo root `AGENTS.md`、`SPEC.md` 与 `docs/architecture/*` 为边界约束 |

## 项目结构

### 文档产物（本次变更）

```text
specs/archive/003-t05v2-doc-formalization/
+-- spec.md
+-- plan.md
+-- tasks.md
```

### 模块文档面（本轮重点）

```text
modules/t05_topology_between_rc_v2/
+-- AGENTS.md
+-- SKILL.md
+-- INTERFACE_CONTRACT.md
+-- REAL_RUN_ACCEPTANCE.md
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
docs/
+-- doc-governance/
    +-- round2b-t05v2-formalization-report.md
```

## 文档边界策略

### `architecture/*`

- 承载稳定模块目标、上下文、约束、方案策略、构件视图、质量要求、风险与术语。
- 重点把 `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad` 这条阶段链表达为长期模块真相。

### `INTERFACE_CONTRACT.md`

- 保持输入、输出、入口、参数、示例、验收标准。
- 对高层业务语义只保留必要摘要，避免比 `architecture/*` 更重。

### `AGENTS.md`

- 仅保留稳定工作规则：
  - 开工前先读什么
  - 允许改什么
  - 必做验证
  - 禁做事项
  - legacy T05 处理原则

### `SKILL.md`

- 只保留可复用流程：
  - 适用任务类型
  - 先读哪些源事实文档
  - 标准步骤
  - 检查点
  - 常见失败点 / 回退方式
  - 输出与验证要求

### `REAL_RUN_ACCEPTANCE.md`

- 保留为运行 / 验收文档。
- 在开头明确其边界：长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。

### legacy T05 pointer

- 只补最小必要指针，避免把 legacy T05 误解为当前正式 T05。
- 不做家族连续治理文档结构，不做 legacy 大迁移。

## 正式化策略

### 来源依据

本轮正文优先从以下来源提炼：

- `src/highway_topo_poc/modules/t05_topology_between_rc_v2/*.py`
- `tests/test_t05v2_pipeline.py`
- `scripts/t05v2_*.sh`
- 当前 `INTERFACE_CONTRACT.md`
- 当前 `REAL_RUN_ACCEPTANCE.md`
- 当前 `review-summary.md`

### 最小正式化标准

1. 审核者不读 `AGENTS.md` 也能理解模块目标、边界、构件链路和最小验收。
2. 执行者不读 `REAL_RUN_ACCEPTANCE.md` 也能理解稳定契约。
3. 执行者不读 `architecture/*` 也能通过 `SKILL.md` 找到正确阅读顺序和验证步骤。

## Analyze 计划

Round 2B 的 analyze 重点回答：

1. T05-V2 是否已形成最小正式文档面？
2. 是否仍有大量稳定业务真相残留在 `AGENTS.md`？
3. 是否仍缺少关键源事实内容？
4. 是否引入与当前项目级治理结构冲突的新问题？

## 实施策略

### 工作顺序

1. 复核 T05-V2 当前文档、实现、脚本和测试证据。
2. 先正式化 `architecture/*`。
3. 再更新 `INTERFACE_CONTRACT.md`。
4. 收缩 `AGENTS.md` 并新建 `SKILL.md`。
5. 明确 `REAL_RUN_ACCEPTANCE.md` 边界并补 legacy pointer。
6. 更新 `review-summary.md` 和执行报告。
7. 做 `analyze` 摘要、校验、提交和推送。

### 本计划强制执行的非目标

- 不改算法
- 不改测试
- 不改运行脚本
- 不改物理目录名
- 不删 legacy 文档
- 不进入 T04 / T06 / 全仓治理轮次

## 复杂度跟踪

Round 2B 没有计划中的宪章违规项。
