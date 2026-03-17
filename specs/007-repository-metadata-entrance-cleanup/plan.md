# 实施计划：Round 3C 仓库结构元数据说明 + 主入口清理

**分支**：`007-repository-metadata-entrance-cleanup` | **日期**：2026-03-17 | **规格**：[spec.md](/mnt/e/Work/Highway_Topo_Poc/specs/007-repository-metadata-entrance-cleanup/spec.md)

## 1. 实施原则

- 本轮不改事实口径，只改结构说明和入口洁净度
- 用 `docs/repository-metadata/repository-structure-metadata.md` 承接结构解释
- 对主要目录实施标准文档白名单
- 项目级非标准文档统一下沉到 `docs/archive/nonstandard/`
- 模块级非标准文档统一下沉到 `modules/<module>/history/`
- 仅做保守清理，不做目录重构

## 2. 目标结构

```text
AGENTS.md
SPEC.md
docs/
+-- PROJECT_BRIEF.md
+-- ARTIFACT_PROTOCOL.md
+-- architecture/
+-- doc-governance/
|   +-- README.md
|   +-- module-lifecycle.md
|   +-- current-module-inventory.md
|   +-- current-doc-inventory.md
|   +-- module-doc-status.csv
|   +-- history/
+-- repository-metadata/
|   +-- README.md
|   +-- repository-structure-metadata.md
+-- archive/
    +-- nonstandard/
specs/
+-- 007-repository-metadata-entrance-cleanup/
+-- archive/
modules/<active-module>/
+-- AGENTS.md
+-- SKILL.md
+-- INTERFACE_CONTRACT.md
+-- review-summary.md
+-- architecture/
+-- history/
modules/<retired-or-historical-module>/
+-- AGENTS.md
+-- history/
```

## 3. 主要实施对象

### 项目级

- root `AGENTS.md`
- `docs/doc-governance/README.md`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/doc-governance/current-module-inventory.md`
- `docs/doc-governance/module-lifecycle.md`
- `docs/PROJECT_BRIEF.md`
- `docs/repository-metadata/*`
- `docs/archive/nonstandard/*`

### 模块级

- `modules/t05_topology_between_rc_v2/history/REAL_RUN_ACCEPTANCE.md`
- retired / historical 模块根目录入口与 `history/`

## 4. 迁移策略

1. 先创建 repository metadata 与 archive README
2. 再迁移项目级非标准文档
3. 再迁移模块级非标准文档
4. 之后修正 active 文档引用
5. 最后瘦身标准入口文档

## 5. 风险与控制

- 风险：误把仍在生效的协议文档归档
  - 控制：`ARTIFACT_PROTOCOL.md` 保留在 `docs/`
- 风险：移动模块历史文档后引用失效
  - 控制：统一修正 `architecture/*`、`AGENTS.md`、`SKILL.md`、`review-summary.md`
- 风险：root `AGENTS.md` 过度瘦身导致规则丢失
  - 控制：只保留 durable rules，不删冲突处理和范围保护
