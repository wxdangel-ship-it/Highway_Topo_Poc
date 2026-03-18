# 当前文档盘点

## 范围

- 盘点日期：2026-03-17
- 目的：说明当前主阅读路径、标准文档位置、历史治理位置与非标准文档归档位置

## 当前主入口文档

| 路径 | 当前角色 | 主要属性 | 说明 |
|---|---|---|---|
| `AGENTS.md` | repo 级 durable guidance 入口 | `durable_guidance` | 只保留仓库级稳定规则 |
| `SPEC.md` | 项目级总规格入口 | `source_of_truth` | 项目级最高优先级规格 |
| `docs/PROJECT_BRIEF.md` | 项目摘要入口 | `source_of_truth` / `digest` | 只提供稳定摘要，不展开治理过程 |
| `docs/ARTIFACT_PROTOCOL.md` | 文本回传协议 | `source_of_truth` | 约束内外网文本回传形态 |
| `docs/architecture/*.md` | 项目级长期架构说明 | `source_of_truth` | 当前项目级长期真相主表面 |
| `docs/repository-metadata/README.md` | 仓库结构入口 | `durable_guidance` | 说明从哪里理解当前仓库结构 |
| `docs/repository-metadata/repository-structure-metadata.md` | 仓库结构元数据主文件 | `source_of_truth` / `durable_guidance` | 解释当前位置白名单、归档规则和阅读顺序 |
| `docs/repository-metadata/code-boundaries-and-entrypoints.md` | 代码边界与入口治理规则 | `durable_guidance` | 解释当前单文件体量约束与执行入口脚本治理 |
| `docs/repository-metadata/code-size-audit.md` | 超阈值文件审计 | `audit_snapshot` | 记录当前超过 `100 KB` 的源码 / 脚本文件 |
| `docs/repository-metadata/entrypoint-registry.md` | 执行入口注册表 | `audit_snapshot` / `durable_guidance` | 记录当前执行入口分布、状态与收敛建议 |
| `docs/metadata-cleanup/README.md` | metadata cleanup 索引 | `durable_guidance` | 说明本目录只存放结构清理执行报告 |
| `docs/doc-governance/README.md` | 治理主入口 | `durable_guidance` | 告诉维护者当前从哪里开始看治理文档 |
| `docs/doc-governance/module-lifecycle.md` | 模块生命周期真相 | `source_of_truth` | 定义 Active / Retired / Historical Reference / Support Retained |
| `docs/doc-governance/current-module-inventory.md` | 当前模块盘点 | `source_of_truth` / `durable_guidance` | 解释模块状态与文档面现状 |
| `docs/doc-governance/current-doc-inventory.md` | 当前文档盘点 | `source_of_truth` / `durable_guidance` | 解释当前文档分层与位置 |
| `docs/doc-governance/module-doc-status.csv` | 模块文档状态总表 | `source_of_truth` / `durable_guidance` | 反映模块状态与推荐动作 |

## 当前活跃模块正式文档面

| 路径 | 当前角色 | 主要属性 | 说明 |
|---|---|---|---|
| `modules/t04_rc_sw_anchor/architecture/*` | T04 长期模块真相 | `source_of_truth` | 当前正式模块文档面 |
| `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md` | T04 稳定契约面 | `source_of_truth` | 当前正式模块文档面 |
| `modules/t04_rc_sw_anchor/AGENTS.md` | T04 durable guidance | `durable_guidance` | 当前正式模块文档面 |
| `.agents/skills/t04-doc-governance/SKILL.md` | T04 标准 Skill 包 | `workflow` | 当前标准可复用流程入口 |
| `modules/t04_rc_sw_anchor/SKILL.md` | T04 模块根 Skill 指针 | `durable_guidance` | 仅保留跳转到 `.agents/skills/t04-doc-governance/SKILL.md` |
| `modules/t04_rc_sw_anchor/review-summary.md` | T04 治理摘要 | `durable_guidance` | 当前正式模块文档面 |
| `modules/t05_topology_between_rc_v2/architecture/*` | 正式 T05 长期模块真相 | `source_of_truth` | 当前正式模块文档面 |
| `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md` | 正式 T05 稳定契约面 | `source_of_truth` | 当前正式模块文档面 |
| `modules/t05_topology_between_rc_v2/AGENTS.md` | 正式 T05 durable guidance | `durable_guidance` | 当前正式模块文档面 |
| `.agents/skills/t05v2-doc-governance/SKILL.md` | 正式 T05 标准 Skill 包 | `workflow` | 当前标准可复用流程入口 |
| `modules/t05_topology_between_rc_v2/SKILL.md` | 正式 T05 模块根 Skill 指针 | `durable_guidance` | 仅保留跳转到 `.agents/skills/t05v2-doc-governance/SKILL.md` |
| `modules/t05_topology_between_rc_v2/review-summary.md` | 正式 T05 治理摘要 | `durable_guidance` | 当前正式模块文档面 |
| `modules/t05_topology_between_rc_v2/history/REAL_RUN_ACCEPTANCE.md` | 正式 T05 历史运行验收说明 | `temporary_spec` / `legacy_candidate` | 运行验收与操作者清单已退出主阅读路径 |
| `modules/t06_patch_preprocess/architecture/*` | T06 长期模块真相 | `source_of_truth` | 当前正式模块文档面 |
| `modules/t06_patch_preprocess/INTERFACE_CONTRACT.md` | T06 稳定契约面 | `source_of_truth` | 当前正式模块文档面 |
| `modules/t06_patch_preprocess/AGENTS.md` | T06 durable guidance | `durable_guidance` | 当前正式模块文档面 |
| `modules/t06_patch_preprocess/SKILL.md` | T06 复用流程 | `workflow` | 当前正式模块文档面 |
| `modules/t06_patch_preprocess/review-summary.md` | T06 治理摘要 | `durable_guidance` | 当前正式模块文档面 |

## 当前历史 / 归档位置

| 路径 | 当前角色 | 主要属性 | 说明 |
|---|---|---|---|
| `docs/doc-governance/history/` | 历史治理过程文档 | `legacy_candidate` | 存放各轮治理执行报告，不替代当前治理入口 |
| `docs/archive/nonstandard/` | 项目级非标准历史说明 | `legacy_candidate` | 存放旧协作说明、阶段性研究、旧目标结构和旧优先级说明 |
| `docs/metadata-cleanup/` | 当前结构清理执行报告位置 | `temporary_spec` | 当前轮次报告保留在这里，但不进入主入口 |
| `specs/archive/` | 历史变更工件 | `legacy_candidate` | 存放历史 `spec / plan / tasks` 及附属工件 |
| `modules/<module>/history/` | 模块级历史资料 | `legacy_candidate` | 存放运行验收、历史契约、阶段性说明、历史审计材料 |

## 当前结论

1. 主阅读路径已经收口到项目级源事实、治理入口、结构元数据和活跃模块正式文档面。
2. 历史治理报告、历史变更工件、项目级非标准说明和模块级运行 / 阶段文档都已退出主阅读路径。
3. `AGENTS.md`、`docs/doc-governance/README.md` 和 `docs/repository-metadata/README.md` 只承担入口与规则指引，不替代 source-of-truth。
