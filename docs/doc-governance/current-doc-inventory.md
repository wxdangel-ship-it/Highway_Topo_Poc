# 当前文档盘点

## 范围

- 盘点日期：2026-03-17
- 目的：在 Round 1 重构前建立文档分类基线，并由 Round 2A 补充修正已确认的治理口径
- 解释说明：本盘点区分“长期源事实”“持久规则”“可复用流程”“单次变更规格”“历史遗留候选”
- 分类词汇：
  - `source_of_truth`：稳定的业务或接口真相
  - `durable_guidance`：稳定执行 / 协作规则
  - `workflow`：可复用流程或重复操作方法
  - `temporary_spec`：变更专用、验收专用或阶段专用产物
  - `legacy_candidate`：历史价值高但未来可能被替代或只保留指针的文档

## 项目级文档

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `SPEC.md` | 全局范围、约束、taxonomy、交付模型 | `source_of_truth` | 已按 Round 2A 写回“当前正式 T05 = T05-V2”“`t03` 退役”“`t10` 退役” |
| `docs/ARTIFACT_PROTOCOL.md` | 外传文本 bundle 协议 | `source_of_truth` | 内外网文本交换的稳定项目契约 |
| `docs/AGENT_PLAYBOOK.md` | 人与 agent 的协作模型 | `durable_guidance` | 稳定操作规则，不是业务真相 |
| `docs/CODEX_GUARDRAILS.md` | 执行保护栏 | `durable_guidance` | 稳定操作规则 |
| `docs/CODEX_START_HERE.md` | 入场清单与优先级 | `durable_guidance` | 启动与接管协议 |
| `docs/WORKSPACE_SETUP.md` | WSL/路径设置规则 | `durable_guidance` | 环境策略 |
| `docs/PROJECT_BRIEF.md` | 项目全局摘要 | `legacy_candidate` | 保留为摘要层，不替代 `SPEC.md` 与 `docs/architecture/*` |
| `docs/t05_business_logic_summary.md` | legacy T05 业务逻辑总结 | `legacy_candidate` | 作为 legacy T05 历史参考保留 |
| `docs/t05_business_audit_for_gpt_20260305.md` | 面向 GPT 的 T05 审计同步文档 | `temporary_spec` | 适合作为 legacy T05 的审核辅助，而非长期真相 |
| `AGENTS.md` | repo 级 durable guidance | `durable_guidance` | Round 2A 新建，只承载 repo 级执行规则 |

## Spec-Kit / 工作流基础设施

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `.specify/memory/constitution.md` | 项目文档治理宪章 | `source_of_truth` | 约束文档治理原则，不承载模块业务真相 |
| `.specify/templates/*.md` | feature 工作流模板 | `workflow` | 属于 spec-kit 脚手架，不是项目业务真相 |
| `.codex/prompts/speckit.*.md` | Codex 的 spec-kit slash command 提示 | `workflow` | 操作工作流文件 |
| `specs/001-doc-governance-round1/` | Round 1 变更记录 | `temporary_spec` | 保留当时的研究与未决表述，作为历史记录 |
| `specs/002-doc-governance-decision-alignment/` | Round 2A 变更记录 | `temporary_spec` | 记录本轮 decision alignment 过程 |

## 模块级稳定文档

### T00 / T01 / T02

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t00_synth_data/INTERFACE_CONTRACT.md` | frozen 模块契约 | `source_of_truth` | synthetic-data 范围的稳定契约 |
| `modules/t00_synth_data/AGENTS.md` | 模块执行规则 | `durable_guidance` | 应保持简短 |
| `modules/t00_synth_data/SKILL.md` | 模块操作流程 | `workflow` | 可复用流程 |
| `modules/t01_fusion_qc/INTERFACE_CONTRACT.md` | frozen 模块契约 | `source_of_truth` | 当前权威模块契约 |
| `modules/t01_fusion_qc/AGENTS.md` | 模块执行规则 | `durable_guidance` | 稳定，但应保持小而稳 |
| `modules/t01_fusion_qc/SKILL.md` | 模块流程 | `workflow` | 后续应继续收缩 |
| `modules/t02_ground_seg_qc/INTERFACE_CONTRACT.md` | 模块契约与输出要求 | `source_of_truth` | 细节较多的模块真相 |
| `modules/t02_ground_seg_qc/AGENTS.md` | 模块执行规则 | `durable_guidance` | 混有流程和阶段说明 |
| `modules/t02_ground_seg_qc/SKILL.md` | 可复用流程 | `workflow` | 部分内容与行为真相混杂 |

### T04

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md` | 主导性的模块契约与业务规则来源 | `source_of_truth` | 当前承载最多稳定模块真相 |
| `modules/t04_rc_sw_anchor/README.md` | 面向操作者的模块摘要 | `legacy_candidate` | 与未来架构文档重叠，但过渡期仍有价值 |
| `modules/t04_rc_sw_anchor/AGENTS.md` | 模块执行与约束指南 | `durable_guidance` | 当前语义负担过重 |
| `modules/t04_rc_sw_anchor/SKILL.md` | 可复用操作流程 | `workflow` | 当前也承载了稳定规则片段 |

### legacy T05

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t05_topology_between_rc/INTERFACE_CONTRACT.md` | legacy 模块契约 | `source_of_truth` | 作为历史参考模块的主契约保留 |
| `modules/t05_topology_between_rc/AGENTS.md` | legacy 模块规则 | `durable_guidance` | 继续保留为历史参考，不再作为活跃治理主线 |
| `modules/t05_topology_between_rc/SKILL.md` | legacy 操作流程 | `workflow` | 保留历史流程语境 |
| `modules/t05_topology_between_rc/DRIVEZONE_XSEC_GATE_SPEC.md` | 专项设计规则说明 | `temporary_spec` | 偏窄的设计 / 决策文档 |
| `modules/t05_topology_between_rc/AUDIT_POINTCLOUD_USAGE.md` | 实现审计说明 | `temporary_spec` | 偏代码审计用途 |
| `modules/t05_topology_between_rc/audits/*.md` | QA 流程与审计说明 | `workflow` / `legacy_candidate` | 作为历史证据保留 |

### T05-V2

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md` | 当前正式 T05 模块契约 | `source_of_truth` | 对输入输出与运行结构具有权威性 |
| `modules/t05_topology_between_rc_v2/AGENTS.md` | 模块规则与身份说明 | `durable_guidance` | 已明确其为独立正式模块，而非旧 T05 参数分支 |
| `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md` | 实跑验收与操作者清单 | `temporary_spec` | 审核价值高，但属于阶段 / 运行导向 |

### T06 / T07

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t06_patch_preprocess/INTERFACE_CONTRACT.md` | 模块契约 | `source_of_truth` | 当前最清晰的 T06 稳定真相 |
| `modules/t06_patch_preprocess/AGENTS.md` | 模块规则 | `durable_guidance` | 与 contract 重复较多 |
| `modules/t06_patch_preprocess/SKILL.md` | 可复用流程 | `workflow` | 与 contract 重复较多 |
| `modules/t07_patch_postprocess/INTERFACE_CONTRACT.md` | 模块契约 | `source_of_truth` | contract-first 的活跃模块文档 |
| `modules/t07_patch_postprocess/AGENTS.md` | 模块规则 | `durable_guidance` | 后续可保持简洁 |
| `modules/t07_patch_postprocess/SKILL.md` | 可复用流程 | `workflow` | 与 contract 相邻的工作流说明 |

### T10（已退役）

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t10/INTERFACE_CONTRACT.md` | 退役模块契约 | `source_of_truth` | 作为退役历史模块的主契约保留，不进入当前正式 taxonomy |
| `modules/t10/AGENTS.md` | 退役模块执行规则 | `durable_guidance` | 仅作为历史模块规则保留 |
| `modules/t10/SKILL.md` | 退役模块流程 | `workflow` | 历史流程资料 |
| `modules/t10/INTERNAL_WSL_USAGE.md` | 环境 / 操作者说明 | `workflow` | 偏操作者使用说明 |
| `modules/t10/PHASE*.md` | 阶段说明 | `temporary_spec` | 退役后的历史阶段文档 |
| `modules/t10/REVIEW_USAGE.md` | 审核流程 | `workflow` | 可作为历史审核辅助 |
| `modules/t10/T10_BASELINE_MANIFEST.json` | 基线清单 | `temporary_spec` | review / baseline 产物，而非当前长期叙述型文档 |

## 关键盘点结论

1. 仓库已经具备稳定的全局规则层，并已建立项目级架构骨架。
2. 各模块的 `INTERFACE_CONTRACT.md` 仍然是模块级源事实的主要落点。
3. 很多 `AGENTS.md` 与 `SKILL.md` 仍承载过多稳定业务内容，后续需要继续收缩。
4. 当前正式 T05 = `t05_topology_between_rc_v2`；legacy T05 仅作为历史参考保留，不再要求 family 连续治理。
5. `t03_marking_entity` 与 `t10` 都已退役；相关资料只作为历史证据或历史参考保留，不进入当前活跃治理主线。
6. root `AGENTS.md` 已建立，后续 repo 级 durable guidance 不再需要散落在轮次说明中。
