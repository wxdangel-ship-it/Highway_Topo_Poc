# 任务拆解：Round 2B T05-V2 模块文档正式化

**输入**：来自 `/specs/003-t05v2-doc-formalization/` 的设计文档  
**前置依赖**：`plan.md`（必需）、`spec.md`（必需）  
**测试说明**：本轮不新增算法或运行测试；验证依赖于文档一致性复核、源事实边界检查和 `git diff --check`。  
**组织方式**：任务按“T05-V2 现状复核 -> architecture 正式化 -> AGENTS 收缩 / SKILL 新建 -> legacy pointer / 报告 -> 提交推送”拆解。

## 格式：`[ID] [P?] [Story] 说明`

- **[P]**：可并行执行（不同文件、无直接依赖）
- **[Story]**：所属用户故事（`US1`、`US2`、`US3`）
- 任务描述必须包含具体文件路径

## Phase 1：现状复核与 spec-kit 产物

**目的**：锁定 T05-V2 的正式化范围、证据来源和旧文档边界。

- [ ] T001 维护 `specs/003-t05v2-doc-formalization/spec.md`、`plan.md`、`tasks.md`，写入 Round 2B 的范围、澄清结论和完成标准
- [ ] T002 复核 `modules/t05_topology_between_rc_v2/` 下当前 `architecture/*`、`AGENTS.md`、`INTERFACE_CONTRACT.md`、`REAL_RUN_ACCEPTANCE.md`、`review-summary.md`
- [ ] T003 复核 `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`、`tests/test_t05v2_pipeline.py`、`scripts/t05v2_*.sh`，提取稳定真相与运行流程证据

---

## Phase 2：用户故事 1 - 形成最小正式模块源事实面（优先级：P1）

**目标**：把稳定业务真相正式收回 `architecture/*` 与 `INTERFACE_CONTRACT.md`。

**独立验证**：只看 `architecture/*`、`INTERFACE_CONTRACT.md` 和 `review-summary.md`，即可理解模块目标、阶段链路、契约和最小验收。

### 用户故事 1 的实现任务

- [ ] T004 [US1] 更新 `modules/t05_topology_between_rc_v2/architecture/00-current-state-research.md`
- [ ] T005 [P] [US1] 更新 `modules/t05_topology_between_rc_v2/architecture/01-introduction-and-goals.md`、`02-constraints.md`、`03-context-and-scope.md`
- [ ] T006 [P] [US1] 更新 `modules/t05_topology_between_rc_v2/architecture/04-solution-strategy.md`、`05-building-block-view.md`
- [ ] T007 [P] [US1] 更新 `modules/t05_topology_between_rc_v2/architecture/10-quality-requirements.md`、`11-risks-and-technical-debt.md`、`12-glossary.md`
- [ ] T008 [US1] 更新 `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md`，补足 Inputs / Outputs / EntryPoints / Params / Examples / Acceptance
- [ ] T009 [US1] 更新 `modules/t05_topology_between_rc_v2/review-summary.md`，将其升级为当前正式 T05 模块的治理摘要

---

## Phase 3：用户故事 2 - 收缩 AGENTS 并建立专用 SKILL（优先级：P2）

**目标**：把稳定工作规则与可复用流程从源事实正文中分离出来。

**独立验证**：只看 `AGENTS.md` 和 `SKILL.md`，即可理解执行规则与标准流程，但无法把它们误读为完整模块真相。

### 用户故事 2 的实现任务

- [ ] T010 [US2] 收缩 `modules/t05_topology_between_rc_v2/AGENTS.md`，只保留稳定工作规则
- [ ] T011 [US2] 创建 `modules/t05_topology_between_rc_v2/SKILL.md`，固化 T05-V2 的专用可复用流程
- [ ] T012 [US2] 更新 `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md`，明确其为运行 / 验收文档并补边界说明

---

## Phase 4：用户故事 3 - 明确 legacy 指针并形成 Round 2B 记录（优先级：P3）

**目标**：避免 legacy T05 与当前正式 T05 文档面再次混淆，并输出本轮可审计记录。

**独立验证**：只看 legacy pointer 和 Round 2B 报告，即可确认当前正式 T05 与历史参考模块的关系。

### 用户故事 3 的实现任务

- [ ] T013 [US3] 在 `modules/t05_topology_between_rc/` 的最小必要位置补充 pointer，明确当前正式 T05 在 `modules/t05_topology_between_rc_v2/`
- [ ] T014 [US3] 创建 `docs/doc-governance/round2b-t05v2-formalization-report.md`，回答任务书要求的 8 个问题
- [ ] T015 [US3] 在 Round 2B 报告中写入 `analyze` 摘要，说明正式化结果、AGENTS 残留真相、缺失源事实和结构冲突检查结果

---

## Phase 5：校验、提交与推送

**目的**：在不扩大战线的前提下完成质量校验、提交和远端同步。

- [ ] T016 执行 `git diff --check`，确认没有内容级错误
- [ ] T017 执行提交：`docs: formalize t05v2 module documentation surfaces`
- [ ] T018 记录提交后的 `git branch --show-current`、`git rev-parse --short HEAD`、`git status --short`
- [ ] T019 推送 `codex/003-t05v2-doc-formalization` 到远端

---

## 依赖关系与执行顺序

### 阶段依赖

- **Phase 1**：可立即开始
- **Phase 2**：依赖 Phase 1 的现状复核
- **Phase 3**：依赖 Phase 2 的正式源事实面基本定稿
- **Phase 4**：依赖 Phase 2 和 Phase 3 的产物已完成
- **Phase 5**：依赖所有文档变更已完成

### 用户故事依赖

- **US1（P1）**：必须最先完成；它定义正式模块源事实面
- **US2（P2）**：依赖 US1 的边界稳定
- **US3（P3）**：依赖 US1、US2 完成后才能准确记录文档关系与执行报告

### 可并行项

- T005、T006、T007 可在 T004 之后并行
- T010、T011、T012 可在 T008 之后并行

---

## 实施策略

### 最小交付顺序

1. 锁定 T05-V2 正式模块文档边界
2. 正式化 `architecture/*` 与 `INTERFACE_CONTRACT.md`
3. 收缩 `AGENTS.md` 并新建 `SKILL.md`
4. 明确 `REAL_RUN_ACCEPTANCE.md` 和 legacy pointer
5. 输出 Round 2B 执行报告
6. 校验、提交、推送

### 保护栏

- 不修改算法与运行逻辑
- 不改测试和运行脚本
- 不改物理目录名
- 不删除 legacy 文档
- 不把 `AGENTS.md`、`SKILL.md` 重新写成源事实
