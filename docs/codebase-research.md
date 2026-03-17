# 代码仓研究

## 范围

- 研究日期：2026-03-17
- 分支：`codex/doc-governance-round1`
- 目的：在任何迁移或重写发生之前，建立 brownfield 文档治理现状基线
- 依据来源：
  - 仓库目录结构
  - `docs/` 下当前项目级文档
  - `modules/` 下当前模块文档
  - `src/highway_topo_poc/modules/` 下当前实现结构
  - `tests/` 下当前测试结构
- 解释说明：本文件描述的是 Round 1 目标骨架引入前的仓库基线；本轮新增的治理产物不会被当作“既有状态”的一部分。

## 当前仓库形态

### 顶层文档面

- 全局需求与治理文档：
  - `SPEC.md`
  - `docs/CODEX_START_HERE.md`
  - `docs/CODEX_GUARDRAILS.md`
  - `docs/AGENT_PLAYBOOK.md`
  - `docs/ARTIFACT_PROTOCOL.md`
  - `docs/PROJECT_BRIEF.md`
  - `docs/WORKSPACE_SETUP.md`
- `docs/` 下与 T05 相关的业务/审计说明：
  - `docs/t05_business_logic_summary.md`
  - `docs/t05_business_audit_for_gpt_20260305.md`
- 新初始化的 spec-kit 工作流面：
  - `.specify/`
  - `.codex/prompts/`
- Round 1 之前不存在项目级 `docs/architecture/`。
- Round 1 之前不存在 feature 级 `specs/` 工作空间。

### 当前模块目录

当前 `modules/` 下可见的模块目录如下：

1. `t00_synth_data`
2. `t01_fusion_qc`
3. `t02_ground_seg_qc`
4. `t04_rc_sw_anchor`
5. `t05_topology_between_rc`
6. `t05_topology_between_rc_v2`
7. `t06_patch_preprocess`
8. `t07_patch_postprocess`
9. `t10`

额外的 taxonomy 事实：

- `SPEC.md` 仍把正式项目家族描述为 `t00` 到 `t07`。
- `SPEC.md` 与 `docs/PROJECT_BRIEF.md` 仍将 `t03_marking_entity` 记为 frozen 模块，但当前不存在 `modules/t03_marking_entity/`。
- `t05_topology_between_rc_v2` 以独立模块目录与独立 `src/` 实现树的形式存在。
- `t10` 在 `modules/` 中存在，但其实现目录是 `src/highway_topo_poc/modules/t10_complex_intersection_modeling/`，命名未对齐。

### 当前实现布局

当前 `src/highway_topo_poc/modules/` 目录如下：

- `t00_synth_data`
- `t01_fusion_qc`
- `t02_ground_seg_qc`
- `t04_rc_sw_anchor`
- `t05_topology_between_rc`
- `t05_topology_between_rc_v2`
- `t06_patch_preprocess`
- `t07_patch_postprocess`
- `t10_complex_intersection_modeling`

关键观察：

- 对大多数模块，仓库已经实践了预期的文档/代码分离：
  - 文档和契约位于 `modules/<module>/`
  - 实现位于 `src/highway_topo_poc/modules/<module>/`
- 当前偏差主要不是目录结构问题，而是语义归属问题：
  - 多份文档同时解释同一模块
  - `AGENTS` 和 `SKILL` 承载了本应进入源事实架构文档的业务真相
  - legacy T05 与 T05-V2 同时存在，但没有明确的家族级文档关系

### 当前测试布局

- 根目录层面存在覆盖 `t00`、`t01`、`t02`、`t05`、`t05_v2`、`t06`、text bundle 与 schema migration 的测试。
- 独立子目录测试存在于：
  - `tests/t04_rc_sw_anchor/`
  - `tests/t10_complex_intersection_modeling/`
- 测试目录为 `t04`、`t05`、`t05_v2`、`t06`、`t10` 的当前可执行范围提供了强证据。

## 文档治理发现

### 当前已经做对的部分

- 全局治理层已经比较完整：
  - `SPEC.md` 负责项目范围与约束
  - `docs/ARTIFACT_PROTOCOL.md` 负责内外网文本协议
  - `docs/CODEX_GUARDRAILS.md` 与 `docs/CODEX_START_HERE.md` 负责执行纪律
  - `docs/AGENT_PLAYBOOK.md` 负责协作分工
- 大多数模块已经拥有预期的三件套：
  - `AGENTS.md`
  - `SKILL.md`
  - `INTERFACE_CONTRACT.md`
- 仓库已初始化 spec-kit，从而为 change-specific 规格提供了正式落位，不必再让临时规划污染持久文档。

### 当前混在一起的部分

- 项目级业务真相、流程指导和操作说明分散在 `SPEC.md`、`PROJECT_BRIEF`、`PLAYBOOK`、`GUARDRAILS` 与模块文档中。
- 模块级业务逻辑常常被拆散在：
  - `INTERFACE_CONTRACT.md`
  - `AGENTS.md`
  - `SKILL.md`
  - 临时验收 / 审计 / README 文件
- T05 的历史材料与较稳定的模块文档混放在一起。
- 当前没有一个明确的 arc42 风格位置来承载：
  - 项目目标
  - 系统上下文与范围
  - 方案策略
  - 横切概念
  - 质量要求
  - 风险 / 技术债
  - 术语表

### Round 1 必须显式承认的结构问题

1. `t03` 存在于正式 project taxonomy 中，但不在当前仓库树中。
2. `t05_topology_between_rc_v2` 在运行事实层面已独立，但命名又暗示其与 legacy `t05` 存在家族关系。
3. `t10` 是超出原 `t00-t07` taxonomy 的额外模块，而且 `modules/` 与 `src/` 命名漂移。
4. 很多 `AGENTS.md` 同时承载稳定模块约束和业务规则，导致体积过大、语义过重。
5. 很多 `SKILL.md` 也承载了冻结的业务定义，而不仅仅是可复用流程。
6. 当前没有文档把旧文档系统地映射到未来目标结构。

## 重点模块研究

### T04：`t04_rc_sw_anchor`

当前证据：

- 模块文档：
  - `modules/t04_rc_sw_anchor/AGENTS.md`
  - `modules/t04_rc_sw_anchor/SKILL.md`
  - `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
  - `modules/t04_rc_sw_anchor/README.md`
  - 同目录下还有配置与脚本说明
- 实现：
  - `src/highway_topo_poc/modules/t04_rc_sw_anchor/`
- 测试：
  - `tests/t04_rc_sw_anchor/`

文档现状：

- `INTERFACE_CONTRACT.md` 目前承载了最重的模块业务真相，包括：
  - 模式说明
  - 输入规范化
  - CRS fail-closed 规则
  - DriveZone-first、Between-Branches、multibranch、K16、breakpoints、输出和 gates
- `AGENTS.md` 与 `SKILL.md` 也同时承载了稳定行为规则，而不只是轻量操作说明。
- `README.md` 兼具业务摘要和操作入口的角色。

Round 1 启示：

- T04 很适合作为模块级 arc42 源事实文档的试点。
- 未来模块级架构文档应吸收当前散落在 `INTERFACE_CONTRACT`、`AGENTS`、`SKILL`、`README` 中的稳定真相。
- `AGENTS.md` 应收缩为执行保护栏与指针。
- `SKILL.md` 应收缩为可复用操作流程。

### T05-V2：`t05_topology_between_rc_v2`

当前证据：

- 模块文档：
  - `modules/t05_topology_between_rc_v2/AGENTS.md`
  - `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md`
  - `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md`
- 实现：
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`
- 测试：
  - `tests/test_t05v2_pipeline.py`
  - `tests/test_t05_step5_global_fit.py`
  - `scripts/` 下多条 stepwise / review 辅助脚本

文档现状：

- 模块在 `AGENTS.md` 中明确自称为新的 T05-V2 模块，而不是旧 T05 的参数分支。
- 它有独立的实现树、输出根目录、脚本和测试。
- 当前没有 `SKILL.md`。
- `REAL_RUN_ACCEPTANCE.md` 明显更偏向运行验收与审核辅助，而不是长期源事实。
- 它与 legacy `t05_topology_between_rc` 仍存在明显的家族关系，因为很多概念和审核语境属于同一领域。

当前结论：

- 按仓库事实，T05-V2 是独立模块。
- 按文档治理视角，它又应被视为 T05 family 的成员，并与 legacy T05 保持显式映射，而不是被静默合并，也不是被静默切断关系。

Round 1 启示：

- 审核包必须明确记录多种落位备选：
  - 独立模块
  - T05 family 同级成员
  - T05 文档体系下的从属变体
- 本轮最稳妥的做法，是保持 `modules/t05_topology_between_rc_v2/architecture/` 独立落位，并在迁移文档中显式记录其家族关系。

### T06：`t06_patch_preprocess`

当前证据：

- 模块文档：
  - `modules/t06_patch_preprocess/AGENTS.md`
  - `modules/t06_patch_preprocess/SKILL.md`
  - `modules/t06_patch_preprocess/INTERFACE_CONTRACT.md`
- 实现：
  - `src/highway_topo_poc/modules/t06_patch_preprocess/`
- 测试：
  - `tests/test_t06_patch_preprocess.py`

文档现状：

- `SPEC.md` 仍把 T06 描述为“new / contract-first”。
- 但仓库里已经存在可执行源码和测试，说明真实成熟度已经超过旧全局 taxonomy 的表述。
- 当前文档高度以 contract 为中心，覆盖：
  - 修复目标
  - 非目标
  - 固定参数
  - 验收规则
- `AGENTS.md` 与 `SKILL.md` 也重复了承载大量相同的冻结行为。

Round 1 启示：

- T06 必须纳入重点审核，因为全局 taxonomy 与仓库现实出现了明显偏差。
- 其新的架构文档必须显式区分：
  - 历史项目 taxonomy 语境（“new / contract-first”）
  - 当前仓库状态（“已实现且有测试的模块”）

## Round 1 的初始治理方向

本轮不应重写所有旧文档，而应先建立：

- `docs/architecture/` 下的项目级 arc42 骨架
- `docs/doc-governance/` 下的治理映射
- 以下三个模块的模块级 arc42 骨架：
  - `t04_rc_sw_anchor`
  - `t05_topology_between_rc_v2`
  - `t06_patch_preprocess`
- 这三个模块的 `review-summary`
- 从旧文档到新职责边界的显式迁移映射

## 需带入 spec-kit 澄清阶段的问题

1. 本仓库项目级 arc42 的最小章节集是什么？
2. 重点模块的模块级 arc42 最小章节集是什么？
3. T05-V2 是否应保持物理独立，同时在文档上归入 T05 family？
4. 迁移后 `AGENTS.md` 中究竟保留哪些内容？
5. 迁移后 `SKILL.md` 中究竟保留哪些内容？
6. 哪些旧文档在 Round 2 只需要补源事实指针，而不是立即迁移？
