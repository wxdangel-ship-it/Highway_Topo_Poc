# 任务清单：Round 3C 仓库结构元数据说明 + 主入口清理

**输入**：来自 `/specs/007-repository-metadata-entrance-cleanup/` 的设计文档
**前置条件**：基线分支 `codex/006-governance-archive-cleanup` 已同步

## Phase 1：盘点与白名单

- [ ] T001 盘点 repo root、`docs/`、`docs/doc-governance/`、活跃模块和退役 / 历史参考模块根目录中的标准文档与非标准文档
- [ ] T002 固化标准文档白名单、非标准文档定义和统一归档位置

## Phase 2：结构元数据文档

- [ ] T003 创建 `docs/repository-metadata/README.md`
- [ ] T004 创建 `docs/repository-metadata/repository-structure-metadata.md`
- [ ] T005 创建 `docs/archive/nonstandard/README.md`

## Phase 3：非标准文档迁移

- [ ] T006 迁移项目级旧协作、旧研究、旧治理规划文档到 `docs/archive/nonstandard/`
- [ ] T007 将 `docs/doc-governance/round3b-governance-archive-cleanup-report.md` 迁移到 `docs/doc-governance/history/`
- [ ] T008 将 T05-V2 的 `REAL_RUN_ACCEPTANCE.md` 迁移到 `modules/t05_topology_between_rc_v2/history/`
- [ ] T009 将 legacy T05、T02、T07、T10 根目录下的非标准文档迁移到各自 `history/`

## Phase 4：标准文档瘦身与引用修正

- [ ] T010 瘦身 root `AGENTS.md`
- [ ] T011 瘦身 `docs/doc-governance/README.md`
- [ ] T012 更新 `docs/doc-governance/current-doc-inventory.md`
- [ ] T013 更新 `docs/doc-governance/current-module-inventory.md`
- [ ] T014 按需更新 `docs/doc-governance/module-lifecycle.md`
- [ ] T015 按需更新 `docs/PROJECT_BRIEF.md`、`SPEC.md` 与活跃模块标准文档中的引用和过渡期表述
- [ ] T016 为新建 `history/` 目录补最小 README / 说明文件

## Phase 5：报告与交付

- [ ] T017 创建 `docs/metadata-cleanup/round3c-repository-metadata-cleanup-report.md`
- [ ] T018 执行 `git diff --check`
- [ ] T019 提交变更：`docs: add repository structure metadata and clean nonstandard docs`
- [ ] T020 推送当前分支 `codex/007-repository-metadata-entrance-cleanup`
