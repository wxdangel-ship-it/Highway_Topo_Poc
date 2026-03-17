# 当前仓库结构元数据说明

## 1. 文档目的

本文档用于描述当前仓库结构、标准文档放置规则和历史资料归档位置。
它服务于“理解当前仓库结构”，不是新的变更提案，也不描述未来目标态。

## 2. 当前顶层目录语义

### repo root

- 放仓库级 durable guidance 和最高层项目规格
- 当前标准文档：`AGENTS.md`、`SPEC.md`

### `docs/`

- 放项目级文档
- 只保留项目摘要、项目级架构、治理入口、结构元数据和历史归档目录

### `docs/architecture/`

- 放项目级长期架构说明
- 当前是项目级 source-of-truth 的主要组成部分

### `docs/doc-governance/`

- 放当前治理入口、生命周期与盘点文档
- 不再承载旧 round 报告和旧治理规划蓝图

### `docs/repository-metadata/`

- 放当前仓库结构说明、代码边界约束、执行入口治理与当前态审计
- 用来解释“目录是什么、文档应该放在哪里、代码边界如何看、入口如何登记”

### `docs/metadata-cleanup/`

- 放结构元数据清理轮次的执行报告
- 不属于主阅读入口，也不替代治理或架构 source-of-truth

### `docs/archive/nonstandard/`

- 放项目级非标准历史说明
- 存放旧协作文档、旧阶段研究、旧目标结构、旧优先级与旧迁移说明

### `specs/`

- 只放当前 active change 的 spec-kit 工件

### `specs/archive/`

- 放历史变更工件
- 用于审计、追溯和回看，不作为当前 source-of-truth

### `modules/`

- 放模块级文档入口与模块历史资料
- 可执行实现不放这里，模块实现继续位于 `src/highway_topo_poc/modules/`

### `modules/<active-module>/`

- 放当前活跃模块的正式文档面
- 允许同时保留 `history/` 目录存放运行验收和历史辅助资料

### `modules/<support-module>/`

- 放支撑 / 测试模块的既有模块文档
- 当前不纳入活跃正式模块集合，但也不按退役 / 历史参考规则清理

### `modules/<retired-or-historical-module>/`

- 根目录只保留最小状态入口文档
- 历史契约、历史流程、阶段说明、审计资料统一放入 `history/`

## 3. 标准文档白名单

### repo root

允许：

- `AGENTS.md`
- `SPEC.md`

### `docs/`

允许：

- `PROJECT_BRIEF.md`
- `ARTIFACT_PROTOCOL.md`
- `architecture/`
- `doc-governance/`
- `repository-metadata/`
- `metadata-cleanup/`
- `archive/`

### `docs/doc-governance/`

允许：

- `README.md`
- `module-lifecycle.md`
- `current-module-inventory.md`
- `current-doc-inventory.md`
- `module-doc-status.csv`
- `history/`

### `docs/repository-metadata/`

允许：

- `README.md`
- `repository-structure-metadata.md`
- `code-boundaries-and-entrypoints.md`
- `code-size-audit.md`
- `entrypoint-registry.md`

### `docs/archive/nonstandard/`

允许：

- `README.md`
- 项目级非标准历史说明

### `docs/metadata-cleanup/`

允许：

- `README.md`
- 当前 metadata cleanup 执行报告

### `specs/`

允许：

- `README.md`（如后续需要）
- 当前 active `specs/<change-id>/`
- `archive/`

### `specs/archive/`

允许：

- `README.md`
- 历史 `specs/<change-id>/`

### `modules/<active-module>/`

允许：

- `AGENTS.md`
- `SKILL.md`
- `INTERFACE_CONTRACT.md`
- `review-summary.md`
- `README.md`（仅当该模块需要操作者总览）
- `architecture/`
- `history/`

### `modules/<support-module>/`

允许：

- `AGENTS.md`
- `SKILL.md`
- `INTERFACE_CONTRACT.md`
- `README.md`（如存在）
- `history/`

### `modules/<retired-or-historical-module>/`

允许：

- `AGENTS.md`（最小状态入口）
- `history/`

## 4. 非标准文档定义

以下内容视为非标准文档：

- 不在当前位置白名单中的文档
- 临时说明、阶段说明、重复说明、过渡期说明
- 已被当前 source-of-truth 覆盖的说明文档
- 仍停留在主要目录下的历史工件

## 5. 归档规则

- 项目级历史治理过程：`docs/doc-governance/history/`
- 历史变更工件：`specs/archive/`
- 项目级非标准说明：`docs/archive/nonstandard/`
- 模块级非标准文档：`modules/<module>/history/`

## 6. 当前主阅读顺序

1. `AGENTS.md`
2. `SPEC.md`
3. `docs/PROJECT_BRIEF.md`
4. `docs/doc-governance/README.md`
5. `docs/repository-metadata/README.md`
6. `docs/repository-metadata/code-boundaries-and-entrypoints.md`
7. `docs/doc-governance/module-lifecycle.md`
8. `docs/doc-governance/current-module-inventory.md`
9. `docs/doc-governance/current-doc-inventory.md`
10. 进入活跃模块正式文档面

## 7. 当前模块状态简表

| 模块类别 | 模块 |
|---|---|
| Active | `t04_rc_sw_anchor`、`t05_topology_between_rc_v2`、`t06_patch_preprocess` |
| Retired | `t02_ground_seg_qc`、`t03_marking_entity`、`t07_patch_postprocess`、`t10` |
| Historical Reference | legacy `t05_topology_between_rc` |
| Support Retained | `t00_synth_data`、`t01_fusion_qc` |

## 8. 维护规则

- 后续新增文档必须先判断应放在哪个白名单位置
- 非标准文档不得长期停留在主要目录
- 历史资料可以保留，但必须退出主阅读路径
- 目录迁移与代码迁移不是本文档职责
