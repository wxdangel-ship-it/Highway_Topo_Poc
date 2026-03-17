# 当前文档盘点

## 范围

- 盘点日期：2026-03-17
- 目的：在 Round 1 重构前，对当前仓库文档进行分类
- 解释说明：本盘点区分“仓库原有文档面”和“同一分支中引入的 Round 1 治理产物”
- 分类词汇：
  - `source_of_truth`：稳定的业务或接口真相
  - `durable_guidance`：稳定执行 / 协作规则
  - `workflow`：可复用流程或重复操作方法
  - `temporary_spec`：变更专用、验收专用或阶段专用产物
  - `legacy_candidate`：历史价值高但未来可能被替代或加指针的文档

## 项目级文档

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `SPEC.md` | 全局范围、约束、taxonomy、交付模型 | `source_of_truth` | 目前仍引用 `t03` 和旧版 `t05` taxonomy |
| `docs/ARTIFACT_PROTOCOL.md` | 外传文本 bundle 协议 | `source_of_truth` | 内外网文本交换的稳定项目契约 |
| `docs/AGENT_PLAYBOOK.md` | 人与 agent 的协作模型 | `durable_guidance` | 稳定操作规则，不是业务真相 |
| `docs/CODEX_GUARDRAILS.md` | 执行保护栏 | `durable_guidance` | 稳定操作规则 |
| `docs/CODEX_START_HERE.md` | 入场清单与优先级 | `durable_guidance` | 启动与接管协议 |
| `docs/WORKSPACE_SETUP.md` | WSL/路径设置规则 | `durable_guidance` | 环境策略 |
| `docs/PROJECT_BRIEF.md` | 项目全局摘要 | `legacy_candidate` | 与 `SPEC.md` 重叠较多，适合保留为摘要而非长期真相 |
| `docs/t05_business_logic_summary.md` | 旧 T05 业务逻辑总结 | `legacy_candidate` | 业务信息丰富，但绑定于旧 T05 基线和特定时间点 |
| `docs/t05_business_audit_for_gpt_20260305.md` | 面向 GPT 的 T05 审计同步文档 | `temporary_spec` | 适合审核辅助，不适合作为长期真相 |

## Spec-Kit / 工作流基础设施

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `.specify/memory/constitution.md` | 项目文档治理宪章 | `source_of_truth` | 由 spec-kit 初始化，并在 Round 1 重写以治理文档结构 |
| `.specify/templates/*.md` | feature 工作流模板 | `workflow` | 属于 spec-kit 脚手架，不是项目业务真相 |
| `.codex/prompts/speckit.*.md` | Codex 的 spec-kit slash command 提示 | `workflow` | 操作工作流文件 |
| `specs/` | 变更专用工作区 | `temporary_spec` | Round 1 之前不存在 feature history；`specs/001-doc-governance-round1/` 是首个活跃变更空间 |

## 模块级稳定文档

### T00 / T01 / T02

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t00_synth_data/INTERFACE_CONTRACT.md` | 模块契约 | `source_of_truth` | frozen synthetic-data 范围的占位契约 |
| `modules/t00_synth_data/AGENTS.md` | 模块执行规则 | `durable_guidance` | 应保持简短 |
| `modules/t00_synth_data/SKILL.md` | 模块操作流程 | `workflow` | 可复用的 synthetic-data 流程 |
| `modules/t01_fusion_qc/INTERFACE_CONTRACT.md` | frozen 模块契约 | `source_of_truth` | 当前权威模块契约 |
| `modules/t01_fusion_qc/AGENTS.md` | 模块执行规则 | `durable_guidance` | 稳定，但应保持小而稳 |
| `modules/t01_fusion_qc/SKILL.md` | MVP 算法流程 | `workflow` | 当前混入了一部分业务真相，后续应收缩 |
| `modules/t02_ground_seg_qc/INTERFACE_CONTRACT.md` | 模块契约与输出要求 | `source_of_truth` | 细节较多的模块真相 |
| `modules/t02_ground_seg_qc/AGENTS.md` | 模块执行规则 | `durable_guidance` | 混有流程和阶段说明 |
| `modules/t02_ground_seg_qc/SKILL.md` | 可复用流程 | `workflow` | 部分内容与行为真相混杂 |

### T04

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md` | 主导性的模块契约与业务规则来源 | `source_of_truth` | 目前承载了最多稳定模块真相 |
| `modules/t04_rc_sw_anchor/README.md` | 面向操作者的模块摘要 | `legacy_candidate` | 与未来架构文档重叠，过渡期仍有价值 |
| `modules/t04_rc_sw_anchor/AGENTS.md` | 模块执行与约束指南 | `durable_guidance` | 当前语义负担过重 |
| `modules/t04_rc_sw_anchor/SKILL.md` | 可复用操作流程 | `workflow` | 当前也承载了稳定规则片段 |
| `modules/t04_rc_sw_anchor/t04_config_template_global_focus.json` | 配置模板 | `workflow` | 辅助性操作产物 |
| `modules/t04_rc_sw_anchor/scripts/batch_cases_example.txt` | 批处理输入样例 | `workflow` | 辅助操作者使用 |

### T05 Legacy

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t05_topology_between_rc/INTERFACE_CONTRACT.md` | 模块契约 | `source_of_truth` | 当前 legacy T05 的权威契约 |
| `modules/t05_topology_between_rc/AGENTS.md` | 模块规则 | `durable_guidance` | 长期来看体量偏大 |
| `modules/t05_topology_between_rc/SKILL.md` | 操作流程 | `workflow` | 混有冻结逻辑 |
| `modules/t05_topology_between_rc/DRIVEZONE_XSEC_GATE_SPEC.md` | 专项设计规则说明 | `temporary_spec` | 偏窄的设计/决策文档 |
| `modules/t05_topology_between_rc/AUDIT_POINTCLOUD_USAGE.md` | 实现审计说明 | `temporary_spec` | 偏代码审计用途 |
| `modules/t05_topology_between_rc/audits/T05_DEV_QA_PROTOCOL.md` | QA 流程 | `workflow` | 过程性文档 |
| `modules/t05_topology_between_rc/audits/T05_QA_SINGLE_FILE_TEMPLATE.md` | QA 模板 | `workflow` | 可复用模板 |
| `modules/t05_topology_between_rc/audits/T05_VERSION_QA_REPORT_TEMPLATE.md` | QA 报告模板 | `workflow` | 可复用模板 |
| `modules/t05_topology_between_rc/audits/runs/.../*.md` | 运行级审计报告 | `legacy_candidate` | 历史审计证据，不是稳定真相 |
| `modules/t05_topology_between_rc/audits/runs/.../*.json` | 运行级审计数据 | `legacy_candidate` | 历史证据，不是稳定真相 |

### T05-V2

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md` | 当前模块契约 | `source_of_truth` | 内容较简，但对输入输出与运行结构具有权威性 |
| `modules/t05_topology_between_rc_v2/AGENTS.md` | 模块规则与身份说明 | `durable_guidance` | 明确说明 V2 不是旧 T05 的参数分支 |
| `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md` | 实跑验收与操作者清单 | `temporary_spec` | 审核价值高，但属于阶段/运行导向 |

### T06 / T07

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t06_patch_preprocess/INTERFACE_CONTRACT.md` | 模块契约 | `source_of_truth` | 当前最清晰的 T06 稳定真相 |
| `modules/t06_patch_preprocess/AGENTS.md` | 模块规则 | `durable_guidance` | 与 contract 重复较多 |
| `modules/t06_patch_preprocess/SKILL.md` | 可复用流程 | `workflow` | 与 contract 重复较多 |
| `modules/t07_patch_postprocess/INTERFACE_CONTRACT.md` | 模块契约 | `source_of_truth` | contract-first 的新模块文档 |
| `modules/t07_patch_postprocess/AGENTS.md` | 模块规则 | `durable_guidance` | 迁移后可保持简洁 |
| `modules/t07_patch_postprocess/SKILL.md` | 可复用流程 | `workflow` | 与 contract 相邻的工作流说明 |

### T10

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t10/INTERFACE_CONTRACT.md` | 模块契约 | `source_of_truth` | 稳定模块契约，但 taxonomy 超出原 `SPEC` 范围 |
| `modules/t10/AGENTS.md` | 模块规则 | `durable_guidance` | 稳定模块执行指南 |
| `modules/t10/SKILL.md` | 可复用流程 | `workflow` | 当前 skill 文档 |
| `modules/t10/INTERNAL_WSL_USAGE.md` | 环境/操作者说明 | `workflow` | 偏操作者使用说明 |
| `modules/t10/PHASE2_USAGE.md` | 阶段使用说明 | `temporary_spec` | 阶段性文档 |
| `modules/t10/PHASE7_BASELINE.md` | 阶段基线说明 | `temporary_spec` | 阶段性文档 |
| `modules/t10/PHASE11_RC.md` | 阶段说明 | `temporary_spec` | 阶段性文档 |
| `modules/t10/REVIEW_USAGE.md` | 审核流程 | `workflow` | 可复用审核辅助 |
| `modules/t10/T10_BASELINE_MANIFEST.json` | 基线清单 | `temporary_spec` | 更像 review / baseline 产物，而非长期叙述型文档 |

## 关键盘点结论

1. 仓库已经具备稳定的全局规则层，但尚无统一的项目级架构文档集合。
2. 各模块的 `INTERFACE_CONTRACT.md` 目前最接近模块级源事实。
3. 很多 `AGENTS.md` 与 `SKILL.md` 承载了过多稳定业务内容。
4. legacy T05 与 T05-V2 的关系需要一个显式家族映射。
5. 历史审计与阶段文档应被保留，但在目标结构中必须明确标注为“非源事实引用”。
6. `specs/` 目录目前没有历史积累；Round 1 将建立这一层。
