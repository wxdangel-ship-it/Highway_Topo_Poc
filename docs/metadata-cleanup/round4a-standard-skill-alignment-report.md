# Round 4A：标准 Skill 结构整改执行报告

## 1. 分支信息

- 基线分支：`codex/008-code-boundary-entrypoint-governance`
- 工作分支：`codex/009-standardize-t04-t05v2-skills`

## 2. 标准 Skill 包

- T04：`.agents/skills/t04-doc-governance/SKILL.md`
- T05-V2：`.agents/skills/t05v2-doc-governance/SKILL.md`

## 3. Skill 元数据

### T04

- `name`: `t04-doc-governance`
- `description`: 用于 T04 文档治理、模块级口径对齐、正式文档面维护与操作者材料边界复核。仅在任务需要更新或审查 `modules/t04_rc_sw_anchor` 的 architecture、contract、review summary、README 或模块级规则时触发；不要在算法修改、批处理脚本改造、patch 自动发现逻辑调整或跨模块实现任务中使用。

### T05-V2

- `name`: `t05v2-doc-governance`
- `description`: 用于正式 T05-V2 的文档治理、验收说明边界复核、模块级口径对齐与标准文档面维护。仅在任务需要更新或审查 `modules/t05_topology_between_rc_v2` 的 architecture、contract、review summary、历史运行验收说明或模块级规则时触发；不要在算法调整、脚本迁移、legacy T05 深迁移或跨模块实现任务中使用。

## 4. 旧模块根 `SKILL.md` 处理结果

- `modules/t04_rc_sw_anchor/SKILL.md`：保留为最小指针版，不再承载正文流程。
- `modules/t05_topology_between_rc_v2/SKILL.md`：保留为最小指针版，不再承载正文流程。

保留最小指针而不是直接删除，是因为当前模块级 active 文档与本地工作习惯仍会从模块根目录寻找流程入口；本轮先完成标准入口迁移，再把模块根旧文件降级为纯指针。

## 5. 已统一口径的 active 文档

- root `AGENTS.md`
- `docs/repository-metadata/README.md`
- `docs/repository-metadata/repository-structure-metadata.md`
- `docs/doc-governance/README.md`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/doc-governance/current-module-inventory.md`
- `SPEC.md`
- 项目级 `docs/architecture/*` 中涉及 Skill 定义和位置的条目
- T04 与 T05-V2 的 `AGENTS.md`、`review-summary.md`、必要的 `architecture/*` 与历史说明文档

## 6. root `AGENTS.md` 的最小调整

- 将“`SKILL.md` 只放可复用流程”改成“标准可复用流程以 repo root `.agents/skills/<skill-name>/SKILL.md` 为准”。
- 明确模块根 `SKILL.md` 如仍存在，只作最小指针，不再作为 active 标准入口。

## 7. analyze 摘要

- T04 与 T05-V2 均已形成标准 Skill 包。
- 当前仓库对 T04 与 T05-V2 已不再把模块根 `SKILL.md` 当成标准入口，而是把它们降级为最小指针。
- active 文档中与 T04 / T05-V2 相关的旧口径已统一到标准 Skill 包路径。
- 当前仍残留的非标准 Skill 口径主要在未纳入本轮范围的 T06 及其盘点条目中，例如 `modules/t06_patch_preprocess/SKILL.md`、`docs/doc-governance/current-doc-inventory.md` 中的 T06 条目、`docs/doc-governance/current-module-inventory.md` 中的 T06 条目；本轮不扩大战线处理这些模块。
- 未引入新的 repo 级治理冲突；项目级源事实与 repo 级规则对标准 Skill 位置的表述已保持一致。

## 8. 本轮没有做的事

- 没有迁移 T06 或其它模块的 Skill 结构，因为本轮范围只覆盖 T04 / T05-V2。
- 没有修改算法、脚本、测试或入口逻辑，因为本轮仅做文档与 Skill 结构整改。
- 没有引入 `scripts/`、`assets/` 或 `agents/openai.yaml`，因为本轮采用 instruction-only skill 即可满足需求。
