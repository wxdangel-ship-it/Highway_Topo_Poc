# 当前文档盘点

## 范围

- 盘点日期：2026-03-17
- 当前基线：已吸收 Round 2A、Round 2B、Round 2C 与 Round 3A 的治理结论
- 目的：识别当前仓库中哪些文档属于项目级 / 模块级源事实，哪些属于持久规则、可复用流程、临时变更规格或历史证据
- 分类词汇：
  - `source_of_truth`：稳定业务真相、架构真相或契约真相
  - `durable_guidance`：稳定执行 / 协作规则
  - `workflow`：可复用操作流程
  - `temporary_spec`：单轮变更、单次验收或阶段性说明
  - `legacy_candidate`：保留为历史摘要、操作者总览或过渡材料的文档

## 项目级文档

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `SPEC.md` | 项目级范围、模块状态、交付约束 | `source_of_truth` | 当前活跃模块、退役模块与历史参考模块的最高层口径之一 |
| `docs/architecture/*.md` | 项目级架构骨架 | `source_of_truth` | 承载项目级长期架构真相 |
| `docs/doc-governance/module-lifecycle.md` | 模块生命周期定义与当前状态表 | `source_of_truth` | Round 3A 新建，专门定义 `Active / Retired / Historical Reference` |
| `docs/ARTIFACT_PROTOCOL.md` | 外传文本 bundle 协议 | `source_of_truth` | 内外网文本交换的长期协议 |
| `AGENTS.md` | repo 级 durable guidance | `durable_guidance` | 只保留仓库级稳定执行规则 |
| `docs/AGENT_PLAYBOOK.md` | 人与 agent 的协作模型 | `durable_guidance` | 协作规则，不承载业务真相 |
| `docs/CODEX_GUARDRAILS.md` | 执行保护栏 | `durable_guidance` | 稳定执行规则 |
| `docs/CODEX_START_HERE.md` | 入场与接管清单 | `durable_guidance` | 启动与接管协议 |
| `docs/WORKSPACE_SETUP.md` | 环境与路径规则 | `durable_guidance` | 环境配置策略 |
| `docs/PROJECT_BRIEF.md` | 项目摘要层 | `legacy_candidate` | 同步项目级正式口径，但不替代 `SPEC.md` 与 `docs/architecture/*` |
| `docs/t05_business_logic_summary.md` | legacy T05 业务逻辑总结 | `legacy_candidate` | 仅作 legacy T05 历史参考 |
| `docs/t05_business_audit_for_gpt_20260305.md` | legacy T05 审核辅助材料 | `temporary_spec` | 保留为历史审核辅助 |

## Spec-Kit / 轮次工作流产物

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `.specify/memory/constitution.md` | 文档治理宪章 | `source_of_truth` | 定义文档治理原则，不承载模块业务真相 |
| `.specify/templates/*.md` | spec-kit 模板 | `workflow` | 工作流基础设施 |
| `.codex/prompts/speckit.*.md` | spec-kit 提示模板 | `workflow` | Codex 工作流提示，不是业务真相 |
| `specs/001-doc-governance-round1/` | Round 1 变更规格 | `temporary_spec` | 记录当时的盘点与目标骨架 |
| `specs/002-doc-governance-decision-alignment/` | Round 2A 决策对齐规格 | `temporary_spec` | 记录人工决策写回过程 |
| `specs/003-t05v2-doc-formalization/` | Round 2B T05-V2 正式化规格 | `temporary_spec` | 记录 T05-V2 正式化过程 |
| `specs/004-t04-t06-doc-formalization/` | Round 2C T04 / T06 正式化规格 | `temporary_spec` | 记录 T04 / T06 正式化过程 |
| `specs/005-module-lifecycle-retirement-governance/` | Round 3A 生命周期治理规格 | `temporary_spec` | 记录本轮生命周期与退役治理过程 |

## 活跃模块正式文档面

### T04

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t04_rc_sw_anchor/architecture/*` | 模块级长期架构真相 | `source_of_truth` | Round 2C 后已形成正式模块文档面 |
| `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md` | 稳定契约面 | `source_of_truth` | 输入 / 输出 / 参数 / 验收标准的权威落点 |
| `modules/t04_rc_sw_anchor/AGENTS.md` | 模块级 durable guidance | `durable_guidance` | 已收缩为规则面 |
| `modules/t04_rc_sw_anchor/SKILL.md` | 模块级复用流程 | `workflow` | 不替代架构真相 |
| `modules/t04_rc_sw_anchor/review-summary.md` | 当前治理摘要 | `legacy_candidate` | 适合作为快速审核入口 |
| `modules/t04_rc_sw_anchor/README.md` | 操作者总览 | `legacy_candidate` | 过渡型摘要，不替代正式文档面 |

### T05-V2

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t05_topology_between_rc_v2/architecture/*` | 模块级长期架构真相 | `source_of_truth` | 当前正式 T05 的长期真相面 |
| `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md` | 稳定契约面 | `source_of_truth` | 输入 / 输出 / 参数 / 验收标准的权威落点 |
| `modules/t05_topology_between_rc_v2/AGENTS.md` | 模块级 durable guidance | `durable_guidance` | 只保留稳定工作规则 |
| `modules/t05_topology_between_rc_v2/SKILL.md` | 模块级复用流程 | `workflow` | Round 2B 新建的正式 skill 面 |
| `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md` | 运行验收说明 | `temporary_spec` | 保留为运行 / 验收文档，不再承担长期源事实 |
| `modules/t05_topology_between_rc_v2/review-summary.md` | 当前治理摘要 | `legacy_candidate` | 适合作为人工审核入口 |

### T06

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t06_patch_preprocess/architecture/*` | 模块级长期架构真相 | `source_of_truth` | Round 2C 后已形成正式模块文档面 |
| `modules/t06_patch_preprocess/INTERFACE_CONTRACT.md` | 稳定契约面 | `source_of_truth` | 输入 / 输出 / 参数 / 验收标准的权威落点 |
| `modules/t06_patch_preprocess/AGENTS.md` | 模块级 durable guidance | `durable_guidance` | 已收缩为规则面 |
| `modules/t06_patch_preprocess/SKILL.md` | 模块级复用流程 | `workflow` | 只保留可复用工作流 |
| `modules/t06_patch_preprocess/review-summary.md` | 当前治理摘要 | `legacy_candidate` | 适合作为快速审核入口 |

## 历史参考与退役模块文档

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t05_topology_between_rc/INTERFACE_CONTRACT.md` | legacy T05 历史契约 | `source_of_truth` | 仅作历史参考，不再是正式 T05 契约面 |
| `modules/t05_topology_between_rc/AGENTS.md` | legacy T05 历史规则入口 | `durable_guidance` | 仅保留历史参考指针与旧规则 |
| `modules/t05_topology_between_rc/SKILL.md` | legacy T05 历史流程 | `workflow` | 仅供历史回看 |
| `modules/t05_topology_between_rc/audits/*.md` | legacy T05 历史证据 | `workflow` / `legacy_candidate` | 保留历史 QA / 审核资料 |
| `modules/t02_ground_seg_qc/INTERFACE_CONTRACT.md` | 退役模块历史契约 | `source_of_truth` | 保留历史可见性，不进入当前活跃治理主线 |
| `modules/t02_ground_seg_qc/AGENTS.md` | 退役模块入口规则 | `durable_guidance` | 已补最小退役指针 |
| `modules/t02_ground_seg_qc/SKILL.md` | 退役模块历史流程 | `workflow` | 仅作为历史流程保留 |
| `modules/t07_patch_postprocess/INTERFACE_CONTRACT.md` | 退役模块历史契约 | `source_of_truth` | 保留历史可见性，不再作为活跃模块 |
| `modules/t07_patch_postprocess/AGENTS.md` | 退役模块入口规则 | `durable_guidance` | 已补最小退役指针 |
| `modules/t07_patch_postprocess/SKILL.md` | 退役模块历史流程 | `workflow` | 仅作为历史流程保留 |
| `modules/t10/INTERFACE_CONTRACT.md` | 退役模块历史契约 | `source_of_truth` | 保留历史实现语义，不进入当前正式 taxonomy |
| `modules/t10/AGENTS.md` | 退役模块入口规则 | `durable_guidance` | 已补最小退役指针 |
| `modules/t10/SKILL.md` | 退役模块历史流程 | `workflow` | 仅作历史资料 |
| `modules/t10/PHASE*.md` | 阶段性历史说明 | `temporary_spec` | 退役后的阶段资料 |
| `modules/t10/REVIEW_USAGE.md` | 历史审核流程 | `workflow` | 仅作历史审核辅助 |

## 仓库保留支撑模块

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t00_synth_data/INTERFACE_CONTRACT.md` | 支撑 / 测试模块契约 | `source_of_truth` | 不属于当前活跃模块集合 |
| `modules/t00_synth_data/AGENTS.md` | 支撑模块规则 | `durable_guidance` | 仅作支撑模块说明 |
| `modules/t00_synth_data/SKILL.md` | 支撑模块流程 | `workflow` | 仅作支撑模块流程 |
| `modules/t01_fusion_qc/INTERFACE_CONTRACT.md` | 支撑 / 测试模块契约 | `source_of_truth` | 不属于当前活跃模块集合 |
| `modules/t01_fusion_qc/AGENTS.md` | 支撑模块规则 | `durable_guidance` | 仅作支撑模块说明 |
| `modules/t01_fusion_qc/SKILL.md` | 支撑模块流程 | `workflow` | 仅作支撑模块流程 |

## 缺口记录

- `t03_marking_entity` 已退役，当前无 `modules/t03_marking_entity/` 目录，也无现成入口文档可补指针。
- 该缺口通过项目级文档和 `docs/doc-governance/module-lifecycle.md` 保留退役记录，而不是新增重型占位文档。

## 关键盘点结论

1. 当前真正承担正式模块源事实职责的活跃模块只有 `t04`、当前正式 T05（`t05_topology_between_rc_v2`）和 `t06`。
2. `INTERFACE_CONTRACT.md` 与 `architecture/*` 是活跃模块的主源事实面；`AGENTS.md` 和 `SKILL.md` 只保留规则与流程职责。
3. legacy T05 只作为 `Historical Reference` 保留，不再作为正式模块或 family 主线。
4. `t02`、`t03`、`t07`、`t10` 都已进入退役口径，只保留历史文档与最小状态指针。
5. `t00`、`t01` 仍保留在仓库中，但属于支撑 / 测试模块，而不是当前活跃模块集合。
