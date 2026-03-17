# 任务拆解：Round 2C T04 + T06 模块文档正式化

**输入**：来自 `/specs/004-t04-t06-doc-formalization/` 的设计文档  
**前置依赖**：`plan.md`（必需）、`spec.md`（必需）  
**测试说明**：本轮不新增算法或运行测试；验证依赖于文档一致性复核、阶段门控判断与 `git diff --check`。  
**组织方式**：任务按“T04 先行 -> 阶段结论检查 -> T06 继续 -> 报告与推送”拆解。

## 格式：`[ID] [P?] [Story] 说明`

- **[P]**：可并行执行（不同文件、无直接依赖）
- **[Story]**：所属用户故事（`US1`、`US2`、`US3`）
- 任务描述必须包含具体文件路径

## Phase 1：现状复核与 spec-kit 产物

**目的**：锁定 T04/T06 的正式化范围、证据来源和阶段门控条件。

- [ ] T001 维护 `specs/004-t04-t06-doc-formalization/spec.md`、`plan.md`、`tasks.md`，写入 Round 2C 的范围、澄清结论和完成标准
- [ ] T002 复核 `modules/t04_rc_sw_anchor/` 下当前 `architecture/*`、`AGENTS.md`、`SKILL.md`、`INTERFACE_CONTRACT.md`、`review-summary.md`、`README.md`
- [ ] T003 复核 `src/highway_topo_poc/modules/t04_rc_sw_anchor/`、`tests/t04_rc_sw_anchor/`、`modules/t04_rc_sw_anchor/scripts/`，提取稳定真相与操作者材料边界
- [ ] T004 复核 `modules/t06_patch_preprocess/` 下当前 `architecture/*`、`AGENTS.md`、`SKILL.md`、`INTERFACE_CONTRACT.md`、`review-summary.md`
- [ ] T005 复核 `src/highway_topo_poc/modules/t06_patch_preprocess/`、`tests/test_t06_patch_preprocess.py`，提取稳定真相与契约一致性证据

---

## Phase 2：用户故事 1 - 形成 T04 的最小正式文档面（优先级：P1）

**目标**：把 T04 的稳定业务真相收回 `architecture/*` 与 `INTERFACE_CONTRACT.md`，并把 `AGENTS.md` / `SKILL.md` 收束为规则与流程文档。

**独立验证**：只看 `architecture/*`、`INTERFACE_CONTRACT.md` 和 `review-summary.md`，即可理解 T04 的目标、构件、约束、契约和最小验收。

### T04 实现任务

- [ ] T006 [US1] 更新 `modules/t04_rc_sw_anchor/architecture/00-current-state-research.md`
- [ ] T007 [P] [US1] 更新 `modules/t04_rc_sw_anchor/architecture/01-introduction-and-goals.md`、`02-constraints.md`、`03-context-and-scope.md`
- [ ] T008 [P] [US1] 更新 `modules/t04_rc_sw_anchor/architecture/04-solution-strategy.md`、`05-building-block-view.md`
- [ ] T009 [P] [US1] 更新 `modules/t04_rc_sw_anchor/architecture/10-quality-requirements.md`、`11-risks-and-technical-debt.md`、`12-glossary.md`
- [ ] T010 [US1] 更新 `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`，保留可信最小契约并削减过重的高层叙事
- [ ] T011 [US1] 收缩 `modules/t04_rc_sw_anchor/AGENTS.md`，只保留稳定工作规则
- [ ] T012 [US1] 更新 `modules/t04_rc_sw_anchor/SKILL.md`，使其成为模块专用复用流程文档
- [ ] T013 [US1] 更新 `modules/t04_rc_sw_anchor/review-summary.md`，升级为当前模块治理摘要
- [ ] T014 [US1] 视情况更新 `modules/t04_rc_sw_anchor/README.md` 或相关操作者材料，明确其与长期源事实的边界

### T04 阶段门控

- [ ] T015 [US3] 完成 T04 阶段结论检查：确认是否存在阻塞性治理冲突，以及是否满足继续推进 T06 的条件

---

## Phase 3：用户故事 2 - 在 T04 通过门控后形成 T06 的最小正式文档面（优先级：P2）

**目标**：在 T04 无阻塞冲突的前提下，正式化 T06，并校准其 contract 与实现证据的关系。

**独立验证**：只看 `architecture/*`、`INTERFACE_CONTRACT.md` 和 `review-summary.md`，即可理解 T06 的目标、构件、契约与最小验收。

### T06 实现任务

- [ ] T016 [US2] 在 T04 门控通过后，更新 `modules/t06_patch_preprocess/architecture/00-current-state-research.md`
- [ ] T017 [P] [US2] 更新 `modules/t06_patch_preprocess/architecture/01-introduction-and-goals.md`、`02-constraints.md`、`03-context-and-scope.md`
- [ ] T018 [P] [US2] 更新 `modules/t06_patch_preprocess/architecture/04-solution-strategy.md`、`05-building-block-view.md`
- [ ] T019 [P] [US2] 更新 `modules/t06_patch_preprocess/architecture/10-quality-requirements.md`、`11-risks-and-technical-debt.md`、`12-glossary.md`
- [ ] T020 [US2] 更新 `modules/t06_patch_preprocess/INTERFACE_CONTRACT.md`，用实现与测试证据校准可信最小契约
- [ ] T021 [US2] 收缩 `modules/t06_patch_preprocess/AGENTS.md`，只保留稳定工作规则
- [ ] T022 [US2] 更新 `modules/t06_patch_preprocess/SKILL.md`，使其成为模块专用复用流程文档
- [ ] T023 [US2] 更新 `modules/t06_patch_preprocess/review-summary.md`，升级为当前模块治理摘要
- [ ] T024 [US2] 复核 T06 是否需要独立运行验收文档；若无必要，则在报告中明确“不新增”
- [ ] T024A [US2] 若 T06 formalization 被 `SPEC.md` 或 `docs/PROJECT_BRIEF.md` 的旧口径阻塞，则做最小范围项目级源事实修正

---

## Phase 4：用户故事 3 - 输出阶段化治理记录（优先级：P3）

**目标**：形成 Round 2C 可审计记录，并回答阶段门控与模块正式化结果。

**独立验证**：只看 Round 2C 报告，即可确认 T04/T06 是否形成最小正式文档面，以及 Phase B 的进入依据。

### 报告任务

- [ ] T025 [US3] 创建 `docs/doc-governance/round2c-t04-t06-formalization-report.md`
- [ ] T026 [US3] 在报告中写入 `analyze` 摘要，回答 T04/T06 文档面、AGENTS 残留真相、缺失源事实和 repo 级冲突检查结果

---

## Phase 5：校验、提交与推送

**目的**：在不扩大战线的前提下完成质量校验、提交和远端同步。

- [ ] T027 执行 `git diff --check`，确认没有内容级错误
- [ ] T028 执行提交：`docs: formalize t04 and t06 module documentation surfaces`
- [ ] T029 记录提交后的 `git branch --show-current`、`git rev-parse --short HEAD`、`git status --short`
- [ ] T030 推送 `codex/004-t04-t06-doc-formalization` 到远端

---

## 依赖关系与执行顺序

### 阶段依赖

- **Phase 1**：可立即开始
- **Phase 2**：依赖 Phase 1 的证据复核
- **Phase 3**：严格依赖 T015 门控通过
- **Phase 4**：依赖 Phase 2 与 Phase 3 产物已完成
- **Phase 5**：依赖所有文档变更已完成

### 用户故事依赖

- **US1（P1）**：必须最先完成；它定义 T04 是否足以作为继续模板
- **US2（P2）**：依赖 US1 门控通过
- **US3（P3）**：依赖 US1、US2 的结果才能准确记录阶段结论

### 可并行项

- T007、T008、T009 可在 T006 之后并行
- T017、T018、T019 可在 T016 之后并行

---

## 实施策略

### 最小交付顺序

1. 锁定 T04/T06 正式文档边界
2. 完成 `spec / plan / tasks`
3. 正式化 T04
4. 做 T04 阶段门控判断
5. 若通过，再正式化 T06
6. 输出 Round 2C 报告
7. 校验、提交、推送

### 保护栏

- 不修改算法与运行逻辑
- 不改测试和运行脚本
- 不改物理目录名
- 不删除历史文档
- 不把 `AGENTS.md`、`SKILL.md` 重新写成源事实
