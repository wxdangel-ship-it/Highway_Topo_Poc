# 任务拆解：Round 3A 活跃模块收口 + 退役模块归档治理

**输入**：来自 `/specs/005-module-lifecycle-retirement-governance/` 的设计文档  
**前置依赖**：`plan.md`（必需）、`spec.md`（必需）  
**测试说明**：本轮不新增算法或运行测试；验证依赖于项目级口径一致性检查、入口指针检查与 `git diff --check`。  
**组织方式**：任务按“生命周期定义 -> 项目级收口 -> 最小指针 -> 报告与推送”拆解。

## 格式：`[ID] [P?] [Story] 说明`

- **[P]**：可并行执行（不同文件、无直接依赖）
- **[Story]**：所属用户故事（`US1`、`US2`、`US3`）

## Phase 1：现状复核与 spec-kit 产物

- [ ] T001 维护 `specs/005-module-lifecycle-retirement-governance/spec.md`、`plan.md`、`tasks.md`
- [ ] T002 复核 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/01-introduction-and-goals.md`、`03-context-and-scope.md` 的旧生命周期口径
- [ ] T003 复核 `docs/doc-governance/current-module-inventory.md`、`current-doc-inventory.md`、`review-priority.md`、`migration-map.md`、`target-structure.md`、`module-doc-status.csv`
- [ ] T004 复核 `modules/t02_ground_seg_qc/`、`modules/t07_patch_postprocess/`、`modules/t10/`、`modules/t05_topology_between_rc/` 的入口文档可用性

---

## Phase 2：用户故事 1 - 正式收口项目级模块生命周期（优先级：P1）

- [ ] T005 [US1] 创建 `docs/doc-governance/module-lifecycle.md`
- [ ] T006 [US1] 更新 `SPEC.md`
- [ ] T007 [P] [US1] 更新 `docs/PROJECT_BRIEF.md`
- [ ] T008 [P] [US1] 视需要更新 `docs/architecture/01-introduction-and-goals.md` 与 `03-context-and-scope.md`
- [ ] T009 [US1] 更新 `docs/doc-governance/current-module-inventory.md`

---

## Phase 3：用户故事 2 - 给退役 / 历史参考模块补最小指针（优先级：P2）

- [ ] T010 [US2] 更新 `modules/t02_ground_seg_qc/AGENTS.md`，补退役状态指针
- [ ] T011 [US2] 更新 `modules/t07_patch_postprocess/AGENTS.md`，补退役状态指针
- [ ] T012 [US2] 更新 `modules/t10/AGENTS.md`，补退役状态指针
- [ ] T013 [US2] 更新 `modules/t05_topology_between_rc/AGENTS.md`，补历史参考状态指针
- [ ] T014 [US2] 记录 `t03_marking_entity` 无目录、无入口文档的缺口说明

---

## Phase 4：用户故事 3 - 稳定治理映射与优先级（优先级：P3）

- [ ] T015 [US3] 更新 `docs/doc-governance/current-doc-inventory.md`
- [ ] T016 [P] [US3] 更新 `docs/doc-governance/review-priority.md`
- [ ] T017 [P] [US3] 更新 `docs/doc-governance/migration-map.md`
- [ ] T018 [P] [US3] 更新 `docs/doc-governance/target-structure.md`
- [ ] T019 [US3] 更新 `docs/doc-governance/module-doc-status.csv`
- [ ] T020 [US3] 若仍有旧口径残留，更新 `docs/doc-governance/round1-exec-report.md`

---

## Phase 5：报告、Analyze、提交与推送

- [ ] T021 创建 `docs/doc-governance/round3a-lifecycle-retirement-governance-report.md`
- [ ] T022 在报告中写入 `analyze` 摘要，回答生命周期统一、旧口径残留、legacy T05 误读与 repo 级冲突问题
- [ ] T023 执行 `git diff --check`
- [ ] T024 执行提交：`docs: govern module lifecycle and retire inactive modules`
- [ ] T025 记录提交后的 `git branch --show-current`、`git rev-parse --short HEAD`、`git status --short`
- [ ] T026 推送 `codex/005-module-lifecycle-retirement-governance` 到远端
