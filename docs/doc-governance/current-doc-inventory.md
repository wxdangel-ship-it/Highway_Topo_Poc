# 当前文档盘点

## 范围

- 盘点日期：2026-03-17
- 当前基线：已吸收 Round 2A、Round 2B、Round 2C、Round 3A 与 Round 3B 的治理结论
- 目的：明确当前主阅读入口、active governance 文档、历史治理过程文档与历史变更工件的分层角色

## 当前主入口文档

以下文档仍在主阅读路径中，应优先阅读：

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `AGENTS.md` | repo 级 durable guidance 入口 | `durable_guidance` | 只保留仓库级稳定执行规则 |
| `SPEC.md` | 项目级总范围、约束与模块状态 | `source_of_truth` | 项目级最高层源事实之一 |
| `docs/PROJECT_BRIEF.md` | 项目摘要入口 | `legacy_candidate` | 提供简版全局概览，不替代源事实 |
| `docs/architecture/*.md` | 项目级长期架构真相 | `source_of_truth` | 当前项目级架构主表面 |
| `docs/doc-governance/README.md` | 治理主入口 | `durable_guidance` | 指引当前治理文档阅读顺序 |
| `docs/doc-governance/module-lifecycle.md` | 模块生命周期真相 | `source_of_truth` | 定义 `Active / Retired / Historical Reference` |
| `docs/doc-governance/current-module-inventory.md` | 当前模块盘点 | `source_of_truth` / `durable_guidance` | 解释模块状态与治理动作 |
| `docs/doc-governance/current-doc-inventory.md` | 当前文档盘点 | `source_of_truth` / `durable_guidance` | 解释文档分层与入口 |
| `docs/doc-governance/target-structure.md` | 治理目标结构 | `source_of_truth` / `durable_guidance` | 解释当前目标结构和落位规则 |
| `docs/doc-governance/review-priority.md` | 当前治理优先级 | `durable_guidance` | 解释活跃治理队列 |
| `docs/doc-governance/module-doc-status.csv` | 模块状态总表 | `source_of_truth` / `durable_guidance` | 反映模块状态与推荐动作 |

## 项目级 active governance 文档

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `docs/doc-governance/migration-map.md` | 生命周期驱动的迁移映射 | `durable_guidance` | 当前迁移策略仍有效 |
| `docs/ARTIFACT_PROTOCOL.md` | 外传文本 bundle 协议 | `source_of_truth` | 当前长期协议 |
| `docs/AGENT_PLAYBOOK.md` | 协作规则 | `durable_guidance` | 人与 agent 的协作模型 |
| `docs/CODEX_GUARDRAILS.md` | 执行保护栏 | `durable_guidance` | 当前稳定执行规则 |
| `docs/CODEX_START_HERE.md` | 入场与接管清单 | `durable_guidance` | 当前 onboarding / handoff 入口 |
| `docs/WORKSPACE_SETUP.md` | 环境与路径规则 | `durable_guidance` | 当前环境规则 |

## 活跃模块正式文档面

### T04 / 正式 T05 / T06

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `modules/t04_rc_sw_anchor/architecture/*` | T04 模块级长期架构真相 | `source_of_truth` | 已 formalize |
| `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md` | T04 稳定契约面 | `source_of_truth` | 已 formalize |
| `modules/t04_rc_sw_anchor/AGENTS.md` | T04 durable guidance | `durable_guidance` | 规则面 |
| `modules/t04_rc_sw_anchor/SKILL.md` | T04 可复用流程 | `workflow` | 流程面 |
| `modules/t05_topology_between_rc_v2/architecture/*` | 正式 T05 模块级长期架构真相 | `source_of_truth` | 已 formalize |
| `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md` | 正式 T05 稳定契约面 | `source_of_truth` | 已 formalize |
| `modules/t05_topology_between_rc_v2/AGENTS.md` | 正式 T05 durable guidance | `durable_guidance` | 规则面 |
| `modules/t05_topology_between_rc_v2/SKILL.md` | 正式 T05 可复用流程 | `workflow` | 流程面 |
| `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md` | 运行验收说明 | `temporary_spec` | 保留为运行 / 验收文档 |
| `modules/t06_patch_preprocess/architecture/*` | T06 模块级长期架构真相 | `source_of_truth` | 已 formalize |
| `modules/t06_patch_preprocess/INTERFACE_CONTRACT.md` | T06 稳定契约面 | `source_of_truth` | 已 formalize |
| `modules/t06_patch_preprocess/AGENTS.md` | T06 durable guidance | `durable_guidance` | 规则面 |
| `modules/t06_patch_preprocess/SKILL.md` | T06 可复用流程 | `workflow` | 流程面 |

## 历史治理过程文档

这些文件已退出主阅读路径，统一放在 `docs/doc-governance/history/`：

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `docs/doc-governance/history/README.md` | 历史治理索引 | `durable_guidance` | 说明 history 的用途 |
| `docs/doc-governance/history/round1-exec-report.md` | Round 1 历史执行报告 | `temporary_spec` / `legacy_candidate` | 历史过程证据 |
| `docs/doc-governance/history/round2a-decision-alignment-report.md` | Round 2A 历史执行报告 | `temporary_spec` / `legacy_candidate` | 历史过程证据 |
| `docs/doc-governance/history/round2b-t05v2-formalization-report.md` | Round 2B 历史执行报告 | `temporary_spec` / `legacy_candidate` | 历史过程证据 |
| `docs/doc-governance/history/round2c-t04-t06-formalization-report.md` | Round 2C 历史执行报告 | `temporary_spec` / `legacy_candidate` | 历史过程证据 |
| `docs/doc-governance/history/round3a-lifecycle-retirement-governance-report.md` | Round 3A 历史执行报告 | `temporary_spec` / `legacy_candidate` | 历史过程证据 |

这些文档用于审计、追溯与理解治理演进，不替代当前 source-of-truth。

## 历史变更工件

这些目录已退出当前 active 变更路径，统一放在 `specs/archive/`：

| 路径 | 当前角色 | 主属性 | 备注 |
|---|---|---|---|
| `specs/006-governance-archive-cleanup/` | 当前 active 变更工件 | `temporary_spec` | 当前轮次保留在主路径 |
| `specs/archive/README.md` | archive 索引 | `durable_guidance` | 说明 archive 的用途 |
| `specs/archive/001-doc-governance-round1/` | Round 1 变更工件 | `temporary_spec` / `legacy_candidate` | 历史变更记录 |
| `specs/archive/002-doc-governance-decision-alignment/` | Round 2A 变更工件 | `temporary_spec` / `legacy_candidate` | 历史变更记录 |
| `specs/archive/003-t05v2-doc-formalization/` | Round 2B 变更工件 | `temporary_spec` / `legacy_candidate` | 历史变更记录 |
| `specs/archive/004-t04-t06-doc-formalization/` | Round 2C 变更工件 | `temporary_spec` / `legacy_candidate` | 历史变更记录 |
| `specs/archive/005-module-lifecycle-retirement-governance/` | Round 3A 变更工件 | `temporary_spec` / `legacy_candidate` | 历史变更记录 |

## 关键盘点结论

1. 当前主入口已经收敛到 `AGENTS.md`、`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*` 和 `docs/doc-governance/README.md`。
2. 历史治理过程文档已与 active governance 文档分开；它们保留审计价值，但不再处于主阅读路径。
3. 历史 `specs` 已与当前 active 变更工件分开；当前只应阅读未归档的 `specs/006-governance-archive-cleanup/`。
4. 活跃模块、退役模块和历史参考模块的生命周期口径继续以 `docs/doc-governance/module-lifecycle.md` 为准。
