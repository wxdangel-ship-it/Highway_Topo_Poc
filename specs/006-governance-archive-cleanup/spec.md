# 功能规格：Round 3B 治理收口与归档清理

**功能分支**: `006-governance-archive-cleanup`  
**实际 Git 分支**: `codex/006-governance-archive-cleanup`  
**创建日期**: 2026-03-17  
**状态**: 草案  
**输入**: 用户任务书，“冻结当前文档治理基线，收缩主阅读入口，将历史治理过程文档与旧 specs 归档，并清理已被当前治理基线完全覆盖的旧治理分支。”

## 澄清结论

### 会话 2026-03-17

- Q: 当前主入口文档集合有哪些？  
  A: `AGENTS.md`、`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/README.md`、`docs/doc-governance/module-lifecycle.md`、`current-module-inventory.md`、`current-doc-inventory.md`、`target-structure.md`、`review-priority.md`、`module-doc-status.csv`。
- Q: 哪些治理文档仍应保持 active？  
  A: 当前 source-of-truth、治理入口、生命周期、inventory、priority、target structure 与状态表继续留在主阅读路径。
- Q: 哪些 round 报告应归入 history？  
  A: `round1-exec-report.md`、`round2a-decision-alignment-report.md`、`round2b-t05v2-formalization-report.md`、`round2c-t04-t06-formalization-report.md`、`round3a-lifecycle-retirement-governance-report.md`。
- Q: 哪些 specs 应归入 archive？  
  A: `specs/001-*` 到 `specs/005-*`；当前 `specs/006-*` 保持 active。
- Q: 哪些旧治理分支可以安全删除？  
  A: 仅候选 `codex/doc-governance-round1`、`codex/002-doc-governance-decision-alignment`、`codex/003-t05v2-doc-formalization`、`codex/004-t04-t06-doc-formalization`；每个都必须先通过“存在且为当前 HEAD 祖先”的检查。
- Q: tag 命名与打点位置是什么？  
  A: 在当前 cleanup 分支的 `HEAD` 创建 annotated tag `docs-governance-v1`；若已存在则停止，不覆盖。
- Q: 本轮完成标准是什么？  
  A: 主入口清晰、历史报告已下沉到 `history/`、旧 specs 已下沉到 `archive/`、引用已修好、`docs-governance-v1` 已创建并推送、可安全删除的旧治理分支已删除，不安全的已明确保留原因。

## 用户场景与验证

### 用户故事 1 - 快速找到当前治理主入口（优先级：P1）

作为新的维护者，我需要从一个稳定入口快速找到当前应该读哪些文档，这样不会被历史 round 报告和旧 specs 混淆。

**独立验证方式**：只阅读 `docs/doc-governance/README.md`，即可知道当前治理主入口和历史资料位置。

### 用户故事 2 - 保留历史治理过程但退出主阅读路径（优先级：P2）

作为审计者，我需要保留历史治理 round 报告和旧 specs，但不希望它们继续占据主阅读路径。

**独立验证方式**：检查 `docs/doc-governance/history/` 与 `specs/archive/`，可看到历史材料完整保留，同时主路径只剩当前入口。

### 用户故事 3 - 只删除已被当前基线完全覆盖的旧治理分支（优先级：P3）

作为仓库维护者，我需要只删除那些已经被当前治理基线完全覆盖的旧治理分支，这样不会误删仍需保留的历史引用。

**独立验证方式**：对每个候选分支执行 `git merge-base --is-ancestor <branch-ref> HEAD`，只有通过者才删除。

## 功能需求

- **FR-001**：本轮必须创建 `docs/doc-governance/README.md`、`docs/doc-governance/history/README.md`、`specs/archive/README.md`。
- **FR-002**：本轮必须把指定 round 报告迁移到 `docs/doc-governance/history/`。
- **FR-003**：本轮必须把 `specs/001-*` 到 `specs/005-*` 迁移到 `specs/archive/`。
- **FR-004**：本轮必须修正迁移导致的必要引用失效。
- **FR-005**：本轮必须最小更新 repo root `AGENTS.md`，增加治理入口和 history/archive 角色说明。
- **FR-006**：本轮必须在当前 cleanup 分支 `HEAD` 创建 annotated tag `docs-governance-v1`；若 tag 已存在则停止，不覆盖。
- **FR-007**：本轮只允许在安全条件满足时删除候选旧治理分支。

## 成功标准

- **SC-001**：当前治理主入口已经清晰，可从 `docs/doc-governance/README.md` 找到。
- **SC-002**：历史 round 报告已全部退出主阅读路径并迁移到 `history/`。
- **SC-003**：旧 specs 已全部退出主路径并迁移到 `archive/`。
- **SC-004**：`docs-governance-v1` tag 已创建并推送。
- **SC-005**：旧治理分支删除只发生在安全条件满足时，且未引入新的治理冲突。
