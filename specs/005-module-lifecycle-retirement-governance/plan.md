# 实施计划：Round 3A 活跃模块收口 + 退役模块归档治理

**分支**: `005-module-lifecycle-retirement-governance` | **日期**: 2026-03-17 | **规格**: [spec.md](/mnt/e/Work/Highway_Topo_Poc/specs/005-module-lifecycle-retirement-governance/spec.md)  
**输入**: 来自 `/specs/005-module-lifecycle-retirement-governance/spec.md` 的功能规格

**说明**：当前实际 Git 分支为 `codex/005-module-lifecycle-retirement-governance`；`005-module-lifecycle-retirement-governance` 是 spec-kit 使用的 feature identifier，用来兼容仓库的分支命名规则。

## 摘要

本次变更只做模块生命周期与最小归档治理。目标是把项目级文档中当前活跃模块、退役模块与历史参考模块的口径完全统一，并给退役 / 历史参考模块在现有入口文档补最小状态指针。实施重点是：

1. 建立 `module-lifecycle.md`
2. 把项目级旧口径统一写回
3. 给退役 / 历史参考模块补最小状态说明
4. 更新治理映射、优先级和状态表

## 技术上下文

**语言/版本**：Markdown 与 CSV；仓库代码基于 Python 3.10，spec-kit CLI 0.3.0 运行在 WSL 的 Python 3.11 下  
**主要依赖**：`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/*`、各模块入口文档  
**存储**：受 Git 跟踪的 Markdown / CSV 文件；不引入数据库  
**验证方式**：项目级口径一致性检查、入口指针检查、`git diff --check`  
**目标平台**：Windows 工作区下的仓库文档体系  
**项目类型**：项目级生命周期治理与最小归档指针治理  
**约束**：不改算法、不改运行逻辑、不改脚本、不改目录、不删历史文档、不为退役模块补新正式文档面  
**规模/范围**：项目级生命周期文档、治理映射、状态表，以及退役 / 历史参考模块入口文档的最小补充

## 宪章检查

*GATE: 在写正文前通过；提交前再次复核。*

| 检查项 | 结果 | 说明 |
|---|---|---|
| 是否继续保持源事实分层 | PASS | 本轮只改项目级源事实与入口指针，不把 AGENTS / SKILL 升格为真相 |
| 是否避免扩大为模块 formalization | PASS | 退役模块只补最小状态说明，不补新正式文档面 |
| 是否保持中文文档约定 | PASS | 新增与改写正文均使用中文 |
| 是否避免代码改造 | PASS | 不修改算法、测试、脚本、入口逻辑 |
| 是否避免 family 连续治理回潮 | PASS | legacy T05 只保留历史参考身份 |

## 项目结构

### 新增治理产物

```text
specs/005-module-lifecycle-retirement-governance/
+-- spec.md
+-- plan.md
+-- tasks.md
docs/
+-- doc-governance/
    +-- module-lifecycle.md
    +-- round3a-lifecycle-retirement-governance-report.md
```

### 本轮会更新的项目级文档

```text
SPEC.md
docs/PROJECT_BRIEF.md
docs/architecture/01-introduction-and-goals.md
docs/architecture/03-context-and-scope.md
docs/doc-governance/current-module-inventory.md
docs/doc-governance/current-doc-inventory.md
docs/doc-governance/review-priority.md
docs/doc-governance/migration-map.md
docs/doc-governance/target-structure.md
docs/doc-governance/module-doc-status.csv
docs/doc-governance/round1-exec-report.md
```

### 本轮会检查并最小补充的模块入口文档

```text
modules/t02_ground_seg_qc/AGENTS.md
modules/t07_patch_postprocess/AGENTS.md
modules/t10/AGENTS.md
modules/t05_topology_between_rc/AGENTS.md
```

## 生命周期治理策略

### 项目级正式口径

- `Active`：`t04_rc_sw_anchor`、当前正式 T05（`t05_topology_between_rc_v2`）、`t06_patch_preprocess`
- `Retired`：`t02_ground_seg_qc`、`t03_marking_entity`、`t07_patch_postprocess`、`t10`
- `Historical Reference`：legacy `t05_topology_between_rc`

### 边界策略

- 退役模块只补最小状态说明，不创建新 `architecture/*`、`SKILL.md` 或 contract 正式化文档面。
- 历史参考模块只补“当前正式模块是谁”和“生命周期文档在哪里”的指针。
- 如果模块目录不存在（如 `t03_marking_entity`），不新增占位目录或重型文档。

### 支撑模块说明

- `t00_synth_data` 与 `t01_fusion_qc` 继续保留在仓库中，作为支撑 / 测试模块存在。
- 本轮不重新裁定它们是否进入 `Active / Retired / Historical Reference` 主表，只在项目级文档中明确它们不属于当前活跃模块集合。

## 文档边界策略

### `module-lifecycle.md`

- 定义生命周期状态与当前正式模块状态
- 说明状态变更原则
- 说明与 `SPEC.md`、`PROJECT_BRIEF.md`、inventory、priority 文档的关系
- 不承载模块内部实现细节

### 项目级治理文档

- `current-module-inventory.md`：表达当前模块状态与治理动作
- `current-doc-inventory.md`：表达文档属性与生命周期关联
- `review-priority.md`：只保留活跃模块和项目级治理队列
- `migration-map.md`：退役模块只做最小归档指针；历史参考模块只保留引用关系
- `target-structure.md`：把生命周期层叠加到目标结构之上
- `module-doc-status.csv`：反映当前状态、建议动作和最小治理方式

### 模块入口指针

- 写法必须短、硬、明确
- 优先写在文档开头
- 只补状态与指向，不重写主体内容

## Analyze 计划

Round 3A 的 analyze 重点回答：

1. 项目级 `Active / Retired / Historical Reference` 口径是否已统一？  
2. 是否仍有文档把 `T02/T03/T07/T10` 当活跃治理对象？  
3. 是否仍有文档把 legacy T05 当正式模块或 family 主线？  
4. 是否引入与 repo 级治理结构冲突的新问题？  

## 实施策略

### 工作顺序

1. 盘点项目级旧生命周期口径与模块入口文件。  
2. 完成 `spec / plan / tasks`。  
3. 创建 `module-lifecycle.md`。  
4. 更新项目级治理文档和状态表。  
5. 给退役 / 历史参考模块补最小指针。  
6. 输出 Round 3A 执行报告。  
7. 做 `analyze` 摘要、校验、提交和推送。  

### 本计划强制执行的非目标

- 不改算法
- 不改测试
- 不改运行脚本
- 不改物理目录名
- 不删历史文档
- 不为退役模块补新正式文档面
- 不扩展到代码归档或目录重组

## 复杂度跟踪

当前尚未发现需要重跑 constitution 的冲突；本轮主要风险点是项目级旧口径与模块入口状态说明之间的不一致，需要在提交前做一次集中扫尾。
