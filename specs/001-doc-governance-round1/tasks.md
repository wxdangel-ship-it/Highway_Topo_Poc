# 任务拆解：Round 1 项目文档结构整改

**输入**：来自 `/specs/001-doc-governance-round1/` 的设计文档  
**前置依赖**：`plan.md`（必需）、`spec.md`（必需）、`research.md`、`data-model.md`、`quickstart.md`

**测试说明**：本轮不新增运行时或算法测试。验证依赖于产物存在性、跨文档一致性和可审核性。

**组织方式**：任务按用户故事分组，以便分别审核“现状基线”“目标治理结构”和“重点模块审核包”。

## 格式：`[ID] [P?] [Story] 说明`

- **[P]**：可并行执行（不同文件、无直接依赖）
- **[Story]**：所属用户故事（`US1`、`US2`、`US3`）
- 任务描述中必须包含具体文件路径

## Phase 1：准备阶段（共享工作流）

**目的**：在开始产出 Round 1 文档前，锁定 change workspace 和文档治理词汇表。

- [ ] T001 确认并维护 Round 1 的 spec-kit 工作空间：`specs/001-doc-governance-round1/spec.md`、`plan.md`、`research.md`、`data-model.md`、`quickstart.md`
- [ ] T002 在 `.specify/memory/constitution.md` 中固化并对齐 Round 1 的治理原则、范围和非目标
- [ ] T003 为 `docs/codebase-research.md`、`docs/doc-governance/current-doc-inventory.md`、`docs/doc-governance/current-module-inventory.md` 和 `docs/doc-governance/module-doc-status.csv` 统一文档分类词汇与模块盘点词汇

---

## Phase 2：基础阶段（阻塞性前置）

**目的**：建立可信的现状基线，后续治理产物都依赖于它。

**关键约束**：在现状基线建立前，不应定稿目标结构和重点模块审核包。

- [ ] T004 收集 `modules/` 下所有现存模块目录的模块、文档、实现和测试证据
- [ ] T005 [P] 将项目级关键文档和工作流脚手架分类写入 `docs/doc-governance/current-doc-inventory.md`
- [ ] T006 [P] 将当前全部模块、taxonomy 不一致点和 Round 1 优先级写入 `docs/doc-governance/current-module-inventory.md`
- [ ] T007 将仓库形态、命名漂移、taxonomy 缺口和重点模块发现汇总到 `docs/codebase-research.md`

**检查点**：现状基线可独立阅读，并能支撑后续治理设计。

---

## Phase 3：用户故事 1 - 建立可靠的现状基线（优先级：P1）

**目标**：产出一套可审核、覆盖全仓的现状研究与盘点基线。

**独立验证**：审核者只看 3 份研究文档，就能确认模块数量、文档分类和 T04/T05-V2/T06 的现状摘要，而不必再扫描整仓代码。

### 用户故事 1 的实现任务

- [ ] T008 [US1] 定稿 `docs/codebase-research.md`，包含模块拓扑、仓库形态分析与当前治理痛点
- [ ] T009 [US1] 定稿 `docs/doc-governance/current-doc-inventory.md`，记录源事实、持久规则、工作流、临时变更规格和历史遗留候选
- [ ] T010 [US1] 定稿 `docs/doc-governance/current-module-inventory.md`，记录模块存在性、重点建议以及 `t03`、`t05_topology_between_rc_v2`、`t10` 的不一致说明

**检查点**：用户故事 1 完成后，现状基线本身就应当可被独立审核。

---

## Phase 4：用户故事 2 - 定义目标治理结构（优先级：P2）

**目标**：在不做破坏性迁移的前提下，定义长期的项目级/模块级文档目标结构和迁移映射。

**独立验证**：审核者只看治理产物，就能理解目标目录、命名规则、职责边界和迁移方向，不需要再打开实现代码。

### 用户故事 2 的实现任务

- [ ] T011 [US2] 在 `docs/architecture/` 下创建项目级架构骨架
- [ ] T012 [P] [US2] 起草 `docs/architecture/01-introduction-and-goals.md`、`02-constraints.md`、`03-context-and-scope.md`
- [ ] T013 [P] [US2] 起草 `docs/architecture/04-solution-strategy.md`、`08-crosscutting-concepts.md`、`09-decisions/README.md`
- [ ] T014 [P] [US2] 起草 `docs/architecture/10-quality-requirements.md`、`11-risks-and-technical-debt.md`、`12-glossary.md`
- [ ] T015 [US2] 创建 `docs/doc-governance/target-structure.md`，定义目标分层拓扑、命名规则和文档边界
- [ ] T016 [US2] 创建 `docs/doc-governance/migration-map.md`，把当前关键文档与文档家族映射到未来职责和落位
- [ ] T017 [US2] 创建 `docs/doc-governance/review-priority.md`，说明为何 T04、T05-V2、T06 是本轮重点审核对象，以及后续轮次应如何排序
- [ ] T018 [US2] 创建 `docs/doc-governance/module-doc-status.csv`，覆盖所有现存模块的状态、优先级与 Round 1 动作

**检查点**：用户故事 2 完成后，应能在不改算法、不删旧文档的情况下清楚描述目标治理结构。

---

## Phase 5：用户故事 3 - 为最高风险模块生成审核包（优先级：P3）

**目标**：在 Round 2 开始前，让 T04、T05-V2、T06 都具备“人能快速审”的模块文档包。

**独立验证**：审核者打开每个重点模块的文档包，就能快速理解当前目标、输入输出、约束、文档混杂问题、推荐落位和待确认问题。

### 用户故事 3 的实现任务

- [ ] T019 [P] [US3] 创建 `modules/t04_rc_sw_anchor/architecture/00-current-state-research.md`、`01-introduction-and-goals.md`、`02-constraints.md`、`03-context-and-scope.md`、`04-solution-strategy.md`、`05-building-block-view.md`、`10-quality-requirements.md`、`11-risks-and-technical-debt.md`、`12-glossary.md`
- [ ] T020 [P] [US3] 创建 `modules/t05_topology_between_rc_v2/architecture/00-current-state-research.md`、`01-introduction-and-goals.md`、`02-constraints.md`、`03-context-and-scope.md`、`04-solution-strategy.md`、`05-building-block-view.md`、`10-quality-requirements.md`、`11-risks-and-technical-debt.md`、`12-glossary.md`
- [ ] T021 [P] [US3] 创建 `modules/t06_patch_preprocess/architecture/00-current-state-research.md`、`01-introduction-and-goals.md`、`02-constraints.md`、`03-context-and-scope.md`、`04-solution-strategy.md`、`05-building-block-view.md`、`10-quality-requirements.md`、`11-risks-and-technical-debt.md`、`12-glossary.md`
- [ ] T022 [US3] 创建 `modules/t04_rc_sw_anchor/review-summary.md`，概括当前目标、I/O、约束、混杂问题、推荐落位和待确认问题
- [ ] T023 [US3] 创建 `modules/t05_topology_between_rc_v2/review-summary.md`，概括当前目标、I/O、约束、T05 family 定位、混杂问题和待确认问题
- [ ] T024 [US3] 创建 `modules/t06_patch_preprocess/review-summary.md`，概括当前目标、I/O、约束、taxonomy 漂移说明、混杂问题和待确认问题

**检查点**：用户故事 3 完成后，三个重点模块都应具备可读、可审、可继续扩展的架构草案与摘要。

---

## Phase 6：收尾与横切事项

**目的**：以一致性检查、执行报告和非目标说明收尾。

- [ ] T025 在 `docs/doc-governance/round1-exec-report.md` 中记录 spec-kit analyze 摘要与未决问题
- [ ] T026 [P] 更新 `docs/doc-governance/round1-exec-report.md`，回答任务书要求的 8 个问题
- [ ] T027 [P] 交叉核对所有 Round 1 必须交付物是否存在，且未引入破坏性迁移或算法改动
- [ ] T028 为所有新建的架构草案和审核摘要补充来源依据、草案标记和审核重点

---

## 依赖关系与执行顺序

### 阶段依赖

- **准备阶段（Phase 1）**：可立即开始
- **基础阶段（Phase 2）**：依赖 Phase 1 输出，并阻塞后续治理产物
- **用户故事 1（Phase 3）**：依赖 Phase 2 的基线证据
- **用户故事 2（Phase 4）**：依赖用户故事 1 的基线可信
- **用户故事 3（Phase 5）**：依赖用户故事 2 的目标结构与模块落位规则
- **收尾阶段（Phase 6）**：依赖本轮全部预期产物已经存在

### 用户故事依赖

- **用户故事 1（P1）**：是第一交付物，也是最小可行基线
- **用户故事 2（P2）**：依赖用户故事 1，因为目标结构必须建立在现状发现之上
- **用户故事 3（P3）**：依赖用户故事 2，因为重点模块审核包必须使用统一的目标结构和命名规则

### 可并行项

- T005 和 T006 可在 T003 之后并行
- T012、T013、T014 可在 T011 之后并行
- T019、T020、T021 可并行
- T026 和 T027 可在主体产物完成后并行

---

## 并行示例：用户故事 3

```bash
# 并行建立三个重点模块的 architecture 草案目录：
Task: "Create T04 architecture draft files under modules/t04_rc_sw_anchor/architecture/"
Task: "Create T05-V2 architecture draft files under modules/t05_topology_between_rc_v2/architecture/"
Task: "Create T06 architecture draft files under modules/t06_patch_preprocess/architecture/"
```

---

## 实施策略

### MVP 优先（只看用户故事 1）

1. 完成 Phase 1：准备
2. 完成 Phase 2：基础基线
3. 完成 Phase 3：用户故事 1
4. 暂停并验证现状基线是否可信

### 增量交付

1. 先盘点现状
2. 再定义目标治理结构
3. 然后建立重点模块审核包
4. 最后以 analyze 摘要和执行报告收尾

### 保护栏

- 不修改运行时算法
- 不广泛删除或重命名旧文档
- 不尝试一轮迁移所有模块
- 除非后续另有明确重分类，否则历史审计与验收文档一律视为保留上下文

---

## 备注

- 本轮任务全部是文档任务
- 可审核性优先于“把每个文档都重写完整”
- 每份新建架构草案都必须注明来源依据和待确认问题
- T05-V2 的定位必须同时体现在治理文档和模块审核摘要中
