# 实施计划：Round 3B 治理收口与归档清理

**分支**: `006-governance-archive-cleanup` | **日期**: 2026-03-17 | **规格**: [spec.md](/mnt/e/Work/Highway_Topo_Poc/specs/006-governance-archive-cleanup/spec.md)  
**输入**: 来自 `/specs/006-governance-archive-cleanup/spec.md` 的功能规格

**说明**：当前实际 Git 分支为 `codex/006-governance-archive-cleanup`；`006-governance-archive-cleanup` 是 spec-kit 使用的 feature identifier。

## 摘要

本轮只做治理收口与归档清理，不改模块事实文档内容，不做新一轮 formalization。实施重点是：

1. 明确当前主入口
2. 把历史 round 报告下沉到 `docs/doc-governance/history/`
3. 把旧 `specs` 下沉到 `specs/archive/`
4. 最小更新 repo root `AGENTS.md`
5. 冻结 annotated tag `docs-governance-v1`
6. 安全删除已完全被当前 HEAD 覆盖的旧治理分支

## 约束

- 不改算法、测试、运行脚本、入口逻辑
- 不改模块物理目录
- 不删模块代码目录
- 不删活跃模块正式文档面
- 不删退役模块历史实现
- 不删除 `main`、`codex/005-module-lifecycle-retirement-governance`、当前 cleanup 分支
- 任一候选旧治理分支若不是当前 `HEAD` 的祖先，则停止该分支删除

## 目录策略

### 当前 active 治理入口

```text
AGENTS.md
SPEC.md
docs/PROJECT_BRIEF.md
docs/architecture/*
docs/doc-governance/README.md
docs/doc-governance/module-lifecycle.md
docs/doc-governance/current-module-inventory.md
docs/doc-governance/current-doc-inventory.md
docs/archive/nonstandard/target-structure.md
docs/archive/nonstandard/review-priority.md
docs/doc-governance/module-doc-status.csv
```

### 历史治理过程

```text
docs/doc-governance/history/
+-- README.md
+-- round1-exec-report.md
+-- round2a-decision-alignment-report.md
+-- round2b-t05v2-formalization-report.md
+-- round2c-t04-t06-formalization-report.md
+-- round3a-lifecycle-retirement-governance-report.md
```

### 历史变更工件

```text
specs/archive/
+-- README.md
+-- 001-doc-governance-round1/
+-- 002-doc-governance-decision-alignment/
+-- 003-t05v2-doc-formalization/
+-- 004-t04-t06-doc-formalization/
+-- 005-module-lifecycle-retirement-governance/
```

## tag 与分支清理策略

### tag

- tag 名：`docs-governance-v1`
- 创建位置：当前 cleanup 分支 `HEAD`
- 类型：annotated tag
- 若已存在同名 tag：立即停止，不覆盖

### 旧治理分支安全删除

候选：

- `codex/doc-governance-round1`
- `codex/002-doc-governance-decision-alignment`
- `codex/003-t05v2-doc-formalization`
- `codex/004-t04-t06-doc-formalization`

删除条件：

1. 本地或远端分支存在
2. 分支 tip 是当前 `HEAD` 的祖先

删除顺序：

1. 先删本地分支
2. 再删远端分支

## Analyze 关注点

1. 当前主入口是否已清晰
2. 历史治理文档是否已退出主阅读路径
3. 旧 specs 是否已归档
4. 旧治理分支是否都满足安全删除条件
5. 是否引入新的 repo 级治理冲突
