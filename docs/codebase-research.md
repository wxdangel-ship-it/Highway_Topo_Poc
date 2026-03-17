# 代码仓研究

## 范围

- 研究日期：2026-03-17
- 原始基线分支：`codex/doc-governance-round1`
- 目的：在任何迁移或重写发生之前，建立 brownfield 文档治理现状基线，并由 Round 2A 对模块身份相关结论做补充修正
- 依据来源：
  - 仓库目录结构
  - `docs/` 下当前项目级文档
  - `modules/` 下当前模块文档
  - `src/highway_topo_poc/modules/` 下当前实现结构
  - `tests/` 下当前测试结构

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
- 与 legacy T05 相关的业务 / 审计说明：
  - `docs/t05_business_logic_summary.md`
  - `docs/t05_business_audit_for_gpt_20260305.md`
- spec-kit 工作流资产：
  - `.specify/`
  - `.codex/prompts/`
- Round 1 引入的项目级架构骨架：
  - `docs/architecture/`
- Round 1 与 Round 2A 的变更工作区：
  - `specs/archive/001-doc-governance-round1/`
  - `specs/archive/002-doc-governance-decision-alignment/`

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

对应的当前治理口径：

- 当前正式 T05 模块：`t05_topology_between_rc_v2`
- legacy 历史参考模块：`t05_topology_between_rc`
- 已退役：`t03_marking_entity`、`t10`

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

- 对大多数模块，仓库已经实践了预期的文档 / 代码分离：
  - 文档和契约位于 `modules/<module>/`
  - 实现位于 `src/highway_topo_poc/modules/<module>/`
- 当前偏差主要不是目录结构问题，而是文档职责和模块身份口径问题。
- Round 2A 已经把 T05/T05-V2、`t03`、`t10` 和 root `AGENTS` 的身份问题从“未决”改成正式结论。

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
- 仓库已初始化 spec-kit，变更专用规划产物已有正式落位。
- repo root `AGENTS.md` 已在 Round 2A 创建，补齐了 repo 级 durable guidance 缺口。

### 当前仍混在一起的部分

- 项目级业务真相、流程指导和操作说明仍散落在 `SPEC.md`、`PROJECT_BRIEF.md`、`docs/architecture/*` 与模块文档中。
- 模块级业务逻辑常被拆散在：
  - `INTERFACE_CONTRACT.md`
  - `AGENTS.md`
  - `SKILL.md`
  - 临时验收 / 审计 / README 文件
- legacy T05、T05-V2 与其他历史材料仍需要后续轮次进一步做深迁移和指针收口。

### 当前必须承认的结构事实

1. 当前正式 T05 模块已经明确为 `t05_topology_between_rc_v2`。
2. `t05_topology_between_rc` 继续保留为 legacy 历史参考模块。
3. `t03_marking_entity` 已退役，且当前 repo 中无对应目录。
4. `t10` 已退役；其 `modules/` 与 `src/` 命名差异作为历史事实保留，不再属于活跃治理问题。
5. 很多 `AGENTS.md` 仍然体量过大，`SKILL.md` 仍然承载了部分稳定业务定义。

## 重点模块研究

### T04：`t04_rc_sw_anchor`

当前证据：

- 模块文档：
  - `modules/t04_rc_sw_anchor/AGENTS.md`
  - `modules/t04_rc_sw_anchor/SKILL.md`
  - `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
  - `modules/t04_rc_sw_anchor/README.md`
- 实现：
  - `src/highway_topo_poc/modules/t04_rc_sw_anchor/`
- 测试：
  - `tests/t04_rc_sw_anchor/`

文档现状：

- `INTERFACE_CONTRACT.md` 仍承载了最重的模块业务真相。
- `AGENTS.md` 与 `SKILL.md` 同时承载稳定行为规则。
- `README.md` 兼具业务摘要和操作入口角色。

后续启示：

- T04 继续适合作为模块级 arc42 源事实文档的重点试点。
- 后续需要继续把稳定业务真相从 `AGENTS` / `SKILL` 收回到 `architecture/` 与 `INTERFACE_CONTRACT.md`。

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
- 辅助脚本：
  - `scripts/t05v2_*.sh`

文档现状：

- 当前已经明确为正式 T05 模块。
- 拥有独立的实现树、输出根目录、脚本和测试。
- 当前没有 `SKILL.md`。
- `REAL_RUN_ACCEPTANCE.md` 更偏向运行验收与审核辅助，而不是长期源事实。

后续启示：

- 后续深迁移应以 T05-V2 作为正式 T05 语义主体。
- legacy T05 只作为历史参考保留，不再继续围绕 family 连续治理设计文档结构。

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

- 项目级活跃文档已同步其“已实现模块”的成熟度。
- 模块业务真相当前仍重复出现在 `AGENTS`、`SKILL` 与 contract 文档中。

后续启示：

- T06 仍应作为重点模块继续做文档收口。
- 重点不是再讨论其是否属于活跃模块，而是继续减少多文档面重复。

## 当前治理方向

在 Round 2A 之后，后续治理重点应当是：

1. 继续深化 T05-V2、T04、T06 的模块级迁移
2. 推进 T07、T02 的规范化
3. 对 frozen 模块补足历史指针与摘要整理

当前不再需要继续讨论：

- T05 / T05-V2 的正式身份
- `t03_marking_entity` 的历史资料是否需要后续补充退役指针
- `t10` 是否应进入正式 taxonomy
- root `AGENTS.md` 是否需要创建
