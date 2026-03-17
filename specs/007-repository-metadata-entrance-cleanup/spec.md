# 规格说明：Round 3C 仓库结构元数据说明 + 主入口清理

**变更标识**：`007-repository-metadata-entrance-cleanup`
**当前 Git 分支**：`codex/007-repository-metadata-entrance-cleanup`
**日期**：2026-03-17
**状态**：Draft

## 1. 背景

当前治理基线已经稳定，并已通过 `docs-governance-v1` 固化。
主阅读路径、历史治理过程文档、历史变更工件已经初步分层，但主要目录下仍残留一批非标准文档，且 repo root `AGENTS.md` 仍承担了部分结构解释职责。

## 2. 目标

本轮目标是：

1. 固化一份当前态的仓库结构元数据说明
2. 明确标准文档白名单与非标准文档定义
3. 将主要目录下残留的非标准文档继续下沉到统一 archive/history 位置
4. 瘦身 root `AGENTS.md` 和其他标准入口文档，让主阅读路径更干净

## 3. 非目标

- 不修改算法、测试、运行脚本、入口逻辑
- 不修改模块物理目录
- 不新增模块 formalization
- 不改变 Active / Retired / Historical Reference / Support Retained 状态
- 不改变 `docs-governance-v1` 的事实口径

## 4. 澄清结论

### 4.1 主要目录 / 标准路径

当前主要目录为：

- repo root
- `docs/`
- `docs/architecture/`
- `docs/doc-governance/`
- `docs/repository-metadata/`
- `specs/`
- `modules/<active-module>/`

### 4.2 非标准文档定义

以下内容视为非标准文档：

- 不在当前位置白名单中的文档
- 临时说明、阶段说明、重复说明、过渡期说明
- 已被当前 source-of-truth 覆盖的说明文档
- 仍停留在主要目录下的历史工件

### 4.3 docs/doc-governance 下的 active 文件

本轮确认仍为 active 的只有：

- `README.md`
- `module-lifecycle.md`
- `current-module-inventory.md`
- `current-doc-inventory.md`
- `module-doc-status.csv`
- `history/`

### 4.4 root AGENTS.md 的最小边界

本轮后只保留：

- repo 级 durable rules
- 文档默认中文
- 冲突处理
- spec-kit / 分支规则
- 主入口最小指向

### 4.5 完成标准

完成标准为：

- 新建 `docs/repository-metadata/README.md` 与 `repository-structure-metadata.md`
- 项目级与模块级非标准文档已迁到统一 archive/history 位置
- 所有 active 文档的引用已修正
- root `AGENTS.md` 已收缩为最小 durable guidance

## 5. 成功判定

1. 维护者只读 `AGENTS.md`、`docs/doc-governance/README.md`、`docs/repository-metadata/README.md` 就能进入当前结构
2. 主要目录中不再残留明显的非标准项目级历史说明
3. 历史 / 运行 / 阶段文档不再占据活跃模块根目录主位置
