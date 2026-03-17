# 任务清单：单文件体量约束 + 执行入口脚本治理

**输入**：来自 `/specs/008-code-boundary-entrypoint-governance/` 的设计文档  
**前置条件**：基线分支 `codex/007-repository-metadata-entrance-cleanup` 已同步

## Phase 1：约束缺口确认

- [ ] T001 复核当前 root `AGENTS.md` 与 `docs/repository-metadata/*` 是否缺少单文件体量约束
- [ ] T002 复核当前 repo 级规则是否缺少执行入口脚本治理

## Phase 2：真实仓库审计

- [ ] T003 扫描源码 / 脚本文件并形成 `100 KB` 超阈值清单
- [ ] T004 识别当前执行入口脚本并划分 repo 级、模块级、验证级和其他入口
- [ ] T005 排除共享辅助脚本与非独立启动模块，收束入口定义

## Phase 3：规则文档落位

- [ ] T006 最小更新 root `AGENTS.md`
- [ ] T007 创建 `docs/repository-metadata/code-boundaries-and-entrypoints.md`
- [ ] T008 创建 `docs/repository-metadata/code-size-audit.md`
- [ ] T009 创建 `docs/repository-metadata/entrypoint-registry.md`
- [ ] T010 更新 `docs/repository-metadata/README.md`
- [ ] T011 按需更新 `docs/repository-metadata/repository-structure-metadata.md`
- [ ] T012 按需更新 `docs/doc-governance/current-doc-inventory.md`

## Phase 4：报告与交付

- [ ] T013 创建 `docs/metadata-cleanup/constraint-4-5-governance-report.md`
- [ ] T014 执行 `git diff --check`
- [ ] T015 提交变更：`docs: codify file-size and entrypoint governance constraints`
- [ ] T016 推送当前分支 `codex/008-code-boundary-entrypoint-governance`
