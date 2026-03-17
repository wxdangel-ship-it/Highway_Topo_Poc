# 任务拆解：Round 2A 人工决策对齐整改

**输入**：来自 `/specs/archive/002-doc-governance-decision-alignment/` 的设计文档
**前置依赖**：`plan.md`（必需）、`spec.md`（必需）
**测试说明**：本轮不新增算法或运行测试；验证依赖于文档一致性复核、残留口径扫描和 `git diff --check`。
**组织方式**：任务按“口径对齐 -> 文档更新 -> root AGENTS -> 执行报告 -> 提交推送”拆解。

## 格式：`[ID] [P?] [Story] 说明`

- **[P]**：可并行执行（不同文件、无直接依赖）
- **[Story]**：所属用户故事（`US1`、`US2`、`US3`）
- 任务描述必须包含具体文件路径

## Phase 1：决策对齐准备

**目的**：锁定 Round 2A 的变更范围和被 supersede 的旧口径。

- [ ] T001 维护 `specs/archive/002-doc-governance-decision-alignment/spec.md`、`plan.md`、`tasks.md`，写入 Round 2A 的范围、澄清结论和完成标准
- [ ] T002 扫描 `docs/`、`modules/`、`SPEC.md`、`docs/PROJECT_BRIEF.md` 中与 T05/T05-V2、`t03`、`t10`、root `AGENTS` 相关的旧口径
- [ ] T003 形成 Round 2A 的 `analyze` 检查清单：旧口径是否已替换、是否引入新的 unresolved item、是否破坏 Round 1 目标结构

---

## Phase 2：用户故事 1 - 对齐项目级与治理级口径（优先级：P1）

**目标**：把 4 条人工决策写回当前活跃治理文档与必要的项目级文档。

**独立验证**：只看治理文档和项目级文档，即可确认四条决策已经成为正式口径。

### 用户故事 1 的实现任务

- [ ] T004 [US1] 更新 `docs/doc-governance/history/round1-exec-report.md`，把 Round 1 的相关未决项改写为“已由 Round 2A 人工决策覆盖”
- [ ] T005 [P] [US1] 更新 `docs/doc-governance/review-priority.md` 与 `docs/doc-governance/module-doc-status.csv`，移除 T05 family / `t03` / `t10` 的旧优先级口径
- [ ] T006 [P] [US1] 更新 `docs/doc-governance/target-structure.md` 与 `docs/doc-governance/migration-map.md`，写入正式 T05、legacy T05、`t03` 退役、`t10` 退役的结构规则
- [ ] T007 [P] [US1] 更新 `docs/doc-governance/current-module-inventory.md` 与 `docs/doc-governance/current-doc-inventory.md`，把模块与文档状态改成已确认口径
- [ ] T008 [US1] 更新 `SPEC.md` 与 `docs/PROJECT_BRIEF.md` 的必要段落，使项目级 taxonomy 与模块状态口径对齐
- [ ] T009 [US1] 更新 `modules/t05_topology_between_rc_v2/review-summary.md`，把模块定位改为“当前正式 T05 模块，物理路径保持 V2”
- [ ] T010 [US1] 修正仍残留旧口径的同类文档：`docs/codebase-research.md`、`docs/architecture/01-introduction-and-goals.md`、`docs/architecture/02-constraints.md`、`docs/architecture/03-context-and-scope.md`、`docs/architecture/04-solution-strategy.md`、`docs/architecture/09-decisions/README.md`、`docs/architecture/10-quality-requirements.md`、`docs/architecture/11-risks-and-technical-debt.md`、`modules/t04_rc_sw_anchor/architecture/03-context-and-scope.md`、`modules/t05_topology_between_rc_v2/architecture/*.md`、`modules/t06_patch_preprocess/architecture/*.md`

---

## Phase 3：用户故事 2 - 创建 root 级 durable guidance（优先级：P2）

**目标**：新增 repo root `AGENTS.md`，把 repo 级 durable guidance 固化到长期位置。

**独立验证**：只看 root `AGENTS.md`，即可确认源事实优先级、分支/spec-kit 规则、语言规则、冲突处理和范围保护都已明确。

### 用户故事 2 的实现任务

- [ ] T011 [US2] 创建 `AGENTS.md`，写入 repo 级定位、源事实优先级、分支与 spec-kit 规则、默认中文规则、冲突处理规则和范围保护
- [ ] T012 [US2] 复核 `AGENTS.md` 是否保持小、稳定、可执行，不承载完整业务真相

---

## Phase 4：用户故事 3 - 形成 Round 2A 收尾记录（优先级：P3）

**目标**：生成可审计的 Round 2A 执行报告与 analyze 摘要。

**独立验证**：只看报告即可知道本轮基线、4 条决策、更新文件范围、残留旧口径和未做事项。

### 用户故事 3 的实现任务

- [ ] T013 [US3] 创建 `docs/doc-governance/history/round2a-decision-alignment-report.md`，回答任务书要求的 8 个问题
- [ ] T014 [US3] 在 `docs/doc-governance/history/round2a-decision-alignment-report.md` 中写入 `analyze` 摘要，说明 `spec/plan/tasks` 是否一致、是否仍有残留旧口径、是否引入新的 unresolved item

---

## Phase 5：校验、提交与推送

**目的**：在不扩大战线的前提下完成质量校验、提交和远端同步。

- [ ] T015 执行 `git diff --check`，确认没有内容级错误
- [ ] T016 执行提交：`docs: align governance docs with reviewed module decisions`
- [ ] T017 记录提交后的 `git branch --show-current`、`git rev-parse --short HEAD`、`git status --short`
- [ ] T018 推送 `codex/002-doc-governance-decision-alignment` 到远端

---

## 依赖关系与执行顺序

### 阶段依赖

- **Phase 1**：可立即开始
- **Phase 2**：依赖 Phase 1 的旧口径扫描与范围确认
- **Phase 3**：可在 Phase 2 口径基本定稿后执行
- **Phase 4**：依赖 Phase 2 和 Phase 3 的产物已完成
- **Phase 5**：依赖所有文档变更已完成

### 用户故事依赖

- **US1（P1）**：必须最先完成；它定义本轮所有决策写回结果
- **US2（P2）**：依赖 US1 的分层与规则口径稳定
- **US3（P3）**：依赖 US1、US2 都已定稿

### 可并行项

- T005、T006、T007 可在 T004 启动后并行
- T010 可与 T005-T009 并行推进，但最终必须在统一口径下复核

---

## 实施策略

### 最小交付顺序

1. 锁定 4 条已确认决策
2. 更新核心治理文档与项目级文档
3. 创建 root `AGENTS.md`
4. 输出 Round 2A 执行报告
5. 校验、提交、推送

### 保护栏

- 不修改算法与运行逻辑
- 不改物理目录名
- 不删除 legacy 文档
- 不进入 Round 2B 深迁移
- 不在本轮引入新的大范围治理主题
