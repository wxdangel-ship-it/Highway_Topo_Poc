# 功能规格：Round 3A 活跃模块收口 + 退役模块归档治理

**功能分支**: `005-module-lifecycle-retirement-governance`  
**实际 Git 分支**: `codex/005-module-lifecycle-retirement-governance`  
**创建日期**: 2026-03-17  
**状态**: 草案  
**输入**: 用户任务书，“将当前项目的活跃模块、退役模块与历史参考模块在项目级文档中正式收口，并为退役/历史参考模块补充最小归档指针，使后续治理与重构均以稳定生命周期口径为前提。”

## 澄清结论

### 会话 2026-03-17

- Q: Active / Retired / Historical Reference 三种状态在本轮中的正式定义是什么？  
  A: `Active` 指当前正式治理与迭代对象；`Retired` 指不再作为当前活跃治理对象、仅保留历史实现与文档；`Historical Reference` 指不再是当前正式模块，但保留为经验与历史证据参考。
- Q: 哪些项目级文件必须更新？  
  A: 至少更新 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/doc-governance/current-module-inventory.md`、`current-doc-inventory.md`、`review-priority.md`、`migration-map.md`、`target-structure.md`、`module-doc-status.csv`；若旧口径仍残留，还需同步 `round1-exec-report.md`、`docs/architecture/01-introduction-and-goals.md`、`03-context-and-scope.md`。
- Q: 哪些退役 / 历史参考模块需要最小指针？  
  A: 本轮按任务书检查 `modules/t02*`、`modules/t03*`、`modules/t07*`、`modules/t10*` 与 `modules/t05_topology_between_rc`。若存在明显入口文档，则只在入口文档开头补最小状态说明。
- Q: 最小指针应写在哪些现有文件中？  
  A: 优先写在现有 `AGENTS.md`、`README.md` 或 `review-summary.md` 这类入口文档开头；若没有合适入口文件，则不额外创建重型文档，只在执行报告记录缺口。
- Q: 若退役模块缺少 README / AGENTS / review-summary，是否需要新建说明文件？  
  A: 不需要。本轮禁止为退役模块补新的正式文档面或重型说明文件。
- Q: 本轮完成标准是什么？  
  A: 项目级文档已统一收口当前 `Active / Retired / Historical Reference` 口径；`module-lifecycle.md` 已创建；退役 / 历史参考模块的最小指针已补到现有入口文档；旧文档不再把 `T02/T03/T07/T10` 当活跃对象，也不再把 legacy T05 当正式模块或 family 主线。
- Q: `t00_synth_data` 与 `t01_fusion_qc` 在本轮如何处理？  
  A: 本轮不重新裁定它们的生命周期类别，只在项目级文档中明确它们是仓库保留的支撑 / 测试模块，不属于当前活跃模块集合，也不进入退役归档动作。

## 用户场景与验证

### 用户故事 1 - 正式收口项目级模块生命周期（优先级：P1）

作为项目文档治理维护者，我需要在项目级文档中写清楚当前哪些模块是 `Active`、哪些已 `Retired`、哪些属于 `Historical Reference`，这样后续所有治理和重构都能基于同一套生命周期口径推进。

**为什么优先级最高**：如果项目级生命周期不统一，后续所有模块治理都会反复回到“模块到底算什么”的争论。

**独立验证方式**：只看 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/doc-governance/module-lifecycle.md` 与 `current-module-inventory.md`，即可得到一致的模块生命周期结论。

**验收场景**：

1. **给定** 任意项目级生命周期文档，**当** 审核者查阅当前模块状态时，  
   **则** 能看到当前活跃模块只有 T04、正式 T05、T06。
2. **给定** legacy T05 或退役模块的描述，**当** 审核者查阅时，  
   **则** 不会再把它们误读成当前正式模块或活跃治理对象。

---

### 用户故事 2 - 给退役 / 历史参考模块补最小归档指针（优先级：P2）

作为治理维护者，我需要在退役模块和历史参考模块的现有入口文档中补短而硬的状态说明，这样后续阅读这些目录的人不会误把它们当作当前主线模块。

**为什么是这个优先级**：项目级文档写回后，如果模块入口文件还保持旧姿态，读者仍会在局部目录里被误导。

**独立验证方式**：只看被补充过的入口文档开头，即可知道该模块是否已退役，或是否仅是历史参考。

**验收场景**：

1. **给定** `modules/t02_ground_seg_qc/AGENTS.md`、`modules/t07_patch_postprocess/AGENTS.md` 或 `modules/t10/AGENTS.md`，**当** 审核者打开文档，  
   **则** 能立即看到“已退役，不再属于当前活跃模块集合”的说明。
2. **给定** `modules/t05_topology_between_rc/AGENTS.md`，**当** 审核者打开文档，  
   **则** 能立即看到“历史参考模块，当前正式 T05 是 V2”的说明。

---

### 用户故事 3 - 稳定治理映射与优先级（优先级：P3）

作为后续轮次的维护者，我需要治理映射、优先级和状态表跟生命周期口径保持一致，这样后续不会再把退役模块排进活跃 formalization 队列。

**为什么是这个优先级**：如果迁移映射和优先级表不更新，项目会继续沿用旧的治理路线，破坏 Round 3A 的收口目标。

**独立验证方式**：只看 `review-priority.md`、`migration-map.md`、`target-structure.md` 与 `module-doc-status.csv`，即可确认退役模块不再进入活跃治理队列。

**验收场景**：

1. **给定** `review-priority.md`，**当** 审核者查看后续治理主线时，  
   **则** 只能看到活跃模块与项目级治理，而不会看到 `T02/T03/T07/T10` 或 legacy T05 进入活跃队列。
2. **给定** `module-doc-status.csv`，**当** 审核者查看状态和推荐动作时，  
   **则** 退役模块只会对应最小归档动作，历史参考模块只会对应最小引用动作。

## 边界情况

- `t03_marking_entity` 当前不存在模块目录，因此不新增模块入口文档，只在项目级文档和执行报告中保留退役记录。
- legacy T05 允许继续保留大量历史资料，但只能作为 `Historical Reference`，不得回退到 family 连续治理口径。
- `t00_synth_data` 与 `t01_fusion_qc` 继续保留为仓库支撑 / 测试模块，本轮不把它们纳入当前主线生命周期三分法。
- 退役模块入口文档若缺少合适落点，不新增重型文档，只记录缺口。

## 需求

### 功能需求

- **FR-001**：本轮必须产出 `spec.md`、`plan.md`、`tasks.md`，并在执行报告中给出 `analyze` 摘要。
- **FR-002**：本轮必须创建 `docs/doc-governance/module-lifecycle.md`，正式定义当前模块生命周期口径。
- **FR-003**：本轮必须把当前 `Active / Retired / Historical Reference` 口径写回 `SPEC.md`、`docs/PROJECT_BRIEF.md` 与治理文档。
- **FR-004**：本轮必须更新 `current-module-inventory.md`、`current-doc-inventory.md`、`review-priority.md`、`migration-map.md`、`target-structure.md`、`module-doc-status.csv`。
- **FR-005**：本轮必须在退役 / 历史参考模块的现有入口文档中补最小状态指针；若没有合适入口文档，只能在报告中记录缺口。
- **FR-006**：本轮不得删除模块目录、代码或历史文档，也不得为退役模块补新的正式文档面。
- **FR-007**：本轮不得把 legacy T05 再写成当前正式模块或 family 主线对象。

### 关键实体

- **Active 模块**：当前正式治理与迭代对象。
- **Retired 模块**：保留历史实现与文档，但不再进入当前活跃治理队列。
- **Historical Reference 模块**：保留为经验与历史证据参考，但不再作为当前正式模块。
- **最小状态指针**：补写在现有入口文档开头的短说明，用于防止模块身份误读。

## 成功标准

### 可度量结果

- **SC-001**：项目级文档对当前 `Active / Retired / Historical Reference` 口径完全一致。
- **SC-002**：`T02/T03/T07/T10` 不再在项目级治理文档中被描述为活跃治理对象。
- **SC-003**：legacy T05 不再在项目级治理文档中被描述为正式模块或 family 主线。
- **SC-004**：退役 / 历史参考模块的最小指针已补到现有入口文档，或已在执行报告中明确说明缺口。
- **SC-005**：本轮不引入算法、测试、脚本、目录结构或模块正式文档面的额外改动。
