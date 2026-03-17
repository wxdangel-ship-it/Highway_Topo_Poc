# Round 3A 执行报告：活跃模块收口 + 退役模块归档治理

## 1. 本轮基线分支和工作分支分别是什么

- 基线分支：`codex/004-t04-t06-doc-formalization`
- 工作分支：`codex/005-module-lifecycle-retirement-governance`

## 2. 当前 Active / Retired / Historical Reference 三类模块分别有哪些

### Active

- `t04_rc_sw_anchor`
- `t05_topology_between_rc_v2`（当前正式 T05）
- `t06_patch_preprocess`

### Retired

- `t02_ground_seg_qc`
- `t03_marking_entity`
- `t07_patch_postprocess`
- `t10`

### Historical Reference

- legacy `t05_topology_between_rc`

### 补充说明

- `t00_synth_data` 与 `t01_fusion_qc` 继续保留在仓库中，作为支撑 / 测试模块存在。
- 它们不属于当前活跃模块集合，也不是本轮退役归档治理对象。

## 3. 哪些项目级文件被更新

- `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/architecture/01-introduction-and-goals.md`
- `docs/architecture/03-context-and-scope.md`
- `docs/doc-governance/current-module-inventory.md`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/doc-governance/review-priority.md`
- `docs/doc-governance/migration-map.md`
- `docs/doc-governance/target-structure.md`
- `docs/doc-governance/module-doc-status.csv`
- `docs/doc-governance/history/round1-exec-report.md`
- `docs/doc-governance/module-lifecycle.md`

## 4. 哪些退役模块 / 历史参考模块被补充了最小指针

- `modules/t02_ground_seg_qc/AGENTS.md`
- `modules/t07_patch_postprocess/AGENTS.md`
- `modules/t10/AGENTS.md`
- `modules/t05_topology_between_rc/AGENTS.md`

这些指针都只做了短状态说明，不改写原文档主体结构。

## 5. 哪些模块没有补指针，为什么

- `t03_marking_entity`
  - 原因：当前不存在 `modules/t03_marking_entity/`，也不存在可用的入口文档。
  - 处理方式：仅在 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/doc-governance/module-lifecycle.md` 与治理盘点文档中保留退役记录。

- `t00_synth_data`、`t01_fusion_qc`
  - 原因：它们不是本轮任务书要求的退役模块或历史参考模块，而是仓库保留的支撑 / 测试模块。
  - 处理方式：只在项目级文档中明确其不属于当前活跃模块集合，不补退役或历史参考指针。

## 6. 是否还残留把 T02/T03/T07/T10 当活跃模块的旧口径

本轮完成后，项目级治理文档已经统一不再把 `T02/T03/T07/T10` 当作活跃模块。

本轮重点修正了：

- `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/architecture/01-introduction-and-goals.md`
- `docs/architecture/03-context-and-scope.md`
- `docs/doc-governance/current-module-inventory.md`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/doc-governance/review-priority.md`
- `docs/doc-governance/migration-map.md`
- `docs/doc-governance/target-structure.md`
- `docs/doc-governance/module-doc-status.csv`
- `docs/doc-governance/history/round1-exec-report.md`

当前未发现仍把 `T02/T03/T07/T10` 写成活跃治理对象的项目级文档残留。

## 7. 是否还残留把 legacy T05 当正式模块的旧口径

本轮完成后，项目级治理文档已经统一把 legacy `t05_topology_between_rc` 表述为 `Historical Reference`。

当前正式 T05 的唯一语义主体是：

- `modules/t05_topology_between_rc_v2`

legacy T05 只保留历史参考、历史审计资料与择优提炼价值，不再被写成正式模块或 family 主线。

## 8. 本轮没有做哪些事，为什么没做

- 没有为退役模块补新的 `architecture/*`、`SKILL.md` 或新的正式契约面
  - 因为本轮目标只是最小归档治理，不是退役模块重新 formalization。
- 没有删除任何模块目录、实现或历史文档
  - 因为本轮明确禁止进入代码归档或目录重组。
- 没有对活跃模块再做新的正式化迁移
  - 因为 T04、正式 T05、T06 的正式化已经在前几轮完成，本轮只做生命周期收口。
- 没有为 `t03_marking_entity` 创建占位目录
  - 因为当前任务要求是保留退役记录，而不是伪造替代模块。

## Analyze 摘要

### 1. 项目级 Active / Retired / Historical Reference 口径是否已统一

已统一。

`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md`、inventory、priority、mapping 与状态表现在使用同一套生命周期口径。

### 2. 是否仍有文档把 T02/T03/T07/T10 当作活跃治理对象

项目级治理文档中未再发现这类旧口径。

### 3. 是否仍有文档把 legacy T05 当作正式模块或 family 主线

项目级治理文档中未再发现这类旧口径。legacy T05 现在只作为 `Historical Reference` 出现。

### 4. 是否引入与 repo 级治理结构冲突的新问题

未引入新的 repo 级治理冲突。

本轮新增的 `module-lifecycle.md` 与现有 `SPEC.md`、repo root `AGENTS.md`、`docs/architecture/*` 的职责边界一致：

- 项目级文档负责生命周期状态与治理口径
- 模块入口文档只补最小状态指针
- 不把退役模块重新拉回正式文档面
