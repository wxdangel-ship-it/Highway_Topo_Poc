# Round 3C 执行报告：仓库结构元数据说明 + 主入口清理

## 1. 基线分支与工作分支

- 基线分支：`codex/006-governance-archive-cleanup`
- 工作分支：`codex/007-repository-metadata-entrance-cleanup`

## 2. 新创建的仓库结构元数据文档

- `docs/repository-metadata/README.md`
- `docs/repository-metadata/repository-structure-metadata.md`

## 3. 当前标准文档白名单

按当前位置定义：

- repo root：`AGENTS.md`、`SPEC.md`
- `docs/`：`PROJECT_BRIEF.md`、`ARTIFACT_PROTOCOL.md`、`architecture/`、`doc-governance/`、`repository-metadata/`、`archive/`
- `docs/doc-governance/`：`README.md`、`module-lifecycle.md`、`current-module-inventory.md`、`current-doc-inventory.md`、`module-doc-status.csv`、`history/`
- `docs/repository-metadata/`：`README.md`、`repository-structure-metadata.md`
- `modules/<active-module>/`：`AGENTS.md`、`SKILL.md`、`INTERFACE_CONTRACT.md`、`review-summary.md`、可选 `README.md`、`architecture/`、`history/`
- `modules/<retired-or-historical-module>/`：`AGENTS.md`、`history/`

## 4. 被迁出主要目录的非标准文档

### 项目级

- `docs/AGENT_PLAYBOOK.md`
- `docs/CODEX_START_HERE.md`
- `docs/CODEX_GUARDRAILS.md`
- `docs/WORKSPACE_SETUP.md`
- `docs/codebase-research.md`
- `docs/t05_business_audit_for_gpt_20260305.md`
- `docs/t05_business_logic_summary.md`
- `docs/doc-governance/target-structure.md`
- `docs/doc-governance/migration-map.md`
- `docs/doc-governance/review-priority.md`
- `docs/doc-governance/round3b-governance-archive-cleanup-report.md`

### 模块级

- `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md`
- `modules/t05_topology_between_rc/` 下的历史契约、历史流程、专项审计与 `audits/`
- `modules/t02_ground_seg_qc/INTERFACE_CONTRACT.md`
- `modules/t02_ground_seg_qc/SKILL.md`
- `modules/t07_patch_postprocess/INTERFACE_CONTRACT.md`
- `modules/t07_patch_postprocess/SKILL.md`
- `modules/t10/` 下的历史契约、历史流程、阶段说明与 `T10_BASELINE_MANIFEST.json`

## 5. 迁移去向

- 项目级非标准文档：`docs/archive/nonstandard/`
- 项目级历史治理报告：`docs/doc-governance/history/`
- 模块级非标准文档：各模块自己的 `history/`

## 6. 仍保留在主入口的文档及原因

- `AGENTS.md`：repo 级 durable guidance，必须保留
- `SPEC.md`：项目级最高优先级规格
- `docs/PROJECT_BRIEF.md`：项目摘要入口
- `docs/ARTIFACT_PROTOCOL.md`：文本回传协议，仍是当前约束
- `docs/architecture/*`：项目级长期架构说明
- `docs/doc-governance/README.md`、`module-lifecycle.md`、`current-module-inventory.md`、`current-doc-inventory.md`、`module-doc-status.csv`：当前治理入口与盘点文档
- `docs/repository-metadata/*`：当前结构说明入口
- 活跃模块正式文档面：当前模块级 source-of-truth 与 durable guidance

## 7. AGENTS.md 的瘦身结果

- 删除了对仓库结构、history/archive、分层职责的展开解释
- 只保留 durable rules、中文文档规则、冲突处理、spec-kit / 分支规则、范围保护，以及一句主入口指向
- 不再承担仓库结构说明职责

## 8. 是否仍残留明显非标准文档在主要目录

存在，但已明确暂不迁移：

- `docs/ARTIFACT_PROTOCOL.md`：虽然不是架构真相，但仍是当前生效协议
- `t00_synth_data`、`t01_fusion_qc` 根目录下的既有模块文档：它们属于 `Support Retained`，不在本轮清理范围内

除以上对象外，当前主要目录中的明显非标准文档已基本迁出。

## 9. 本轮没有做的事

- 没有调整模块生命周期状态，因为当前状态以 `docs-governance-v1` 为基线冻结
- 没有新增模块 formalization，因为本轮只做结构元数据与主入口清理
- 没有做代码、脚本或目录重构，因为本轮仅处理文档位置与入口洁净度
