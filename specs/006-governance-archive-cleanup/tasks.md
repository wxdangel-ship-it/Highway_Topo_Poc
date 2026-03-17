# 任务拆解：Round 3B 治理收口与归档清理

**输入**：来自 `/specs/006-governance-archive-cleanup/` 的设计文档  
**前置依赖**：`plan.md`（必需）、`spec.md`（必需）  
**验证说明**：依赖引用修正检查、`git diff --check`、tag 创建结果与分支祖先检查。  
**组织方式**：按“主入口 -> 历史归档 -> 引用修正 -> tag -> 分支清理 -> 报告”拆解。

## Phase 1：spec-kit 与主入口确认

- [ ] T001 维护 `specs/006-governance-archive-cleanup/spec.md`、`plan.md`、`tasks.md`
- [ ] T002 识别当前 active 治理入口文档集合
- [ ] T003 创建 `docs/doc-governance/README.md`
- [ ] T004 最小更新 repo root `AGENTS.md`

## Phase 2：历史治理过程归档

- [ ] T005 创建 `docs/doc-governance/history/README.md`
- [ ] T006 迁移 `round1-exec-report.md`
- [ ] T007 迁移 `round2a-decision-alignment-report.md`
- [ ] T008 迁移 `round2b-t05v2-formalization-report.md`
- [ ] T009 迁移 `round2c-t04-t06-formalization-report.md`
- [ ] T010 迁移 `round3a-lifecycle-retirement-governance-report.md`

## Phase 3：旧 specs 归档

- [ ] T011 创建 `specs/archive/README.md`
- [ ] T012 迁移 `specs/archive/001-doc-governance-round1`
- [ ] T013 迁移 `specs/archive/002-doc-governance-decision-alignment`
- [ ] T014 迁移 `specs/archive/003-t05v2-doc-formalization`
- [ ] T015 迁移 `specs/archive/004-t04-t06-doc-formalization`
- [ ] T016 迁移 `specs/archive/005-module-lifecycle-retirement-governance`

## Phase 4：引用修正与 active 文档收口

- [ ] T017 更新 `docs/doc-governance/current-doc-inventory.md`
- [ ] T018 按需更新 `docs/doc-governance/current-module-inventory.md`
- [ ] T019 按需更新 `docs/doc-governance/review-priority.md`
- [ ] T020 按需更新 `docs/doc-governance/target-structure.md`
- [ ] T021 按需更新 `docs/doc-governance/module-doc-status.csv`
- [ ] T022 修正历史报告、归档 specs 与其他 active 文档中的失效引用

## Phase 5：tag、报告、提交与分支清理

- [ ] T023 创建 `docs/doc-governance/round3b-governance-archive-cleanup-report.md`
- [ ] T024 在报告中写入 analyze 摘要
- [ ] T025 执行 `git diff --check`
- [ ] T026 提交：`docs: archive governance history and clean obsolete branches`
- [ ] T027 推送当前 cleanup 分支
- [ ] T028 创建并推送 annotated tag `docs-governance-v1`
- [ ] T029 检查候选旧治理分支是否存在且为当前 `HEAD` 的祖先
- [ ] T030 安全删除满足条件的旧治理分支
