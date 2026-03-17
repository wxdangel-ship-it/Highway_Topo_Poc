# 迁移映射

## 状态

- 草案状态：Round 1 迁移映射
- 策略：默认非破坏；先映射，再迁移

## 项目级映射

| 当前文档 / 家族 | 当前属性 | 目标文档面 | Round 1 动作 | 后续动作 |
|---|---|---|---|---|
| `SPEC.md` | `source_of_truth` | 继续保留在 `SPEC.md`，并从 `docs/architecture/01-04` 建立交叉链接 | 保留原位 | 后续进一步收紧与项目级架构文档的边界 |
| `docs/ARTIFACT_PROTOCOL.md` | `source_of_truth` | 继续保留在 `docs/`，并由 `docs/architecture/08-crosscutting-concepts.md` 与 `10-quality-requirements.md` 引用 | 保留原位 | 后续决定是否在架构文档中增加协议摘要页 |
| `docs/AGENT_PLAYBOOK.md` | `durable_guidance` | 继续保留在 `docs/` | 保留原位 | 后续补充到架构与治理文档的显式指针 |
| `docs/CODEX_GUARDRAILS.md` | `durable_guidance` | 继续保留在 `docs/` | 保留原位 | 后续补充到架构与治理文档的显式指针 |
| `docs/CODEX_START_HERE.md` | `durable_guidance` | 继续保留在 `docs/` | 保留原位 | 后续与新的 onboarding 指针对齐 |
| `docs/WORKSPACE_SETUP.md` | `durable_guidance` | 继续保留在 `docs/` | 保留原位 | 后续从 `02-constraints.md` 建立引用 |
| `docs/PROJECT_BRIEF.md` | `legacy_candidate` | 摘要 / 参考层 | 保留原位 | 后续转成带指针的 digest，或在审核后退役 |
| `docs/t05_business_logic_summary.md` | `legacy_candidate` | T05 family 历史参考 | 保留原位 | 后续指向 legacy T05 架构文档 |
| `docs/t05_business_audit_for_gpt_20260305.md` | `temporary_spec` | T05 family 历史参考 | 保留原位 | 后续指向 T05 审核区或归档区 |

## 模块级映射

### 通用模块规则

| 当前文档面 | 目标文档面 | Round 1 动作 | 后续动作 |
|---|---|---|---|
| `modules/<module>/INTERFACE_CONTRACT.md` | 继续作为 `architecture/` 旁的契约文档面 | 保留原位 | 待架构真相稳定后再削减重叠 |
| `modules/<module>/AGENTS.md` | 继续作为规则面 | 保留原位 | 后续收缩为持久规则 + 指针 |
| `modules/<module>/SKILL.md` | 继续作为工作流面 | 保留原位 | 后续收缩为可复用流程 |

### 重点模块

| 当前文档 / 家族 | 目标文档面 | Round 1 动作 | 后续动作 |
|---|---|---|---|
| `modules/t04_rc_sw_anchor/README.md` | `modules/t04_rc_sw_anchor/architecture/01-05` + `review-summary.md` | 保留并建立映射 | 后续如有需要，可将 README 改为指针型摘要 |
| `modules/t04_rc_sw_anchor/AGENTS.md` | `modules/t04_rc_sw_anchor/AGENTS.md` + 指向 `architecture/` 的链接 | 保留并建立映射 | 后续剥离业务真相 |
| `modules/t04_rc_sw_anchor/SKILL.md` | `modules/t04_rc_sw_anchor/SKILL.md` + 指向 `architecture/` 的链接 | 保留并建立映射 | 后续剥离稳定规则内容 |
| `modules/t05_topology_between_rc_v2/AGENTS.md` | `modules/t05_topology_between_rc_v2/AGENTS.md` + `architecture/` + `review-summary.md` | 保留并建立映射 | 后续把“模块身份说明”和“业务真相”进一步拆开 |
| `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md` | 作为 `review-summary` 引用的工作流 / 参考说明 | 保留并建立映射 | 后续决定保留为 runbook 还是归入验收文档家族 |
| `modules/t06_patch_preprocess/AGENTS.md` | `modules/t06_patch_preprocess/AGENTS.md` + `architecture/` | 保留并建立映射 | 后续削减与 contract 的重叠 |
| `modules/t06_patch_preprocess/SKILL.md` | `modules/t06_patch_preprocess/SKILL.md` + `architecture/` | 保留并建立映射 | 后续削减与 contract 的重叠 |

### legacy / 历史文档家族

| 当前文档 / 家族 | 目标文档面 | Round 1 动作 | 后续动作 |
|---|---|---|---|
| `modules/t05_topology_between_rc/audits/*.md` | 历史证据家族 | 保留原位 | 后续补充源事实指针和归档说明 |
| `modules/t05_topology_between_rc/audits/runs/...` | 历史证据家族 | 保留原位 | 后续视需要建立索引或归档 |
| `modules/t10/PHASE*.md` | 临时阶段说明家族 | 保留原位 | 后续决定是否并入 T10 架构与审核文档 |
| `modules/t10/REVIEW_USAGE.md` | 工作流 / 参考文档 | 保留原位 | 后续与 T10 架构和审核流程对齐 |

## Taxonomy 例外

| 例外项 | 当前现实 | Round 1 处理方式 | 后续仍需决策 |
|---|---|---|---|
| `t03_marking_entity` | 存在于全局 taxonomy，但 repo 树中缺失 | 记录为缺失的 taxonomy 成员 | 决定恢复、退役还是显式降级 |
| `t05_topology_between_rc_v2` | 独立模块路径，同时命名上属于 T05 family | 保留独立路径，并建立家族映射 | 决定长期家族文档结构 |
| `t10` | 额外模块，且 `modules/t10` 与 `src/.../t10_complex_intersection_modeling` 命名不一致 | 记录不一致，不改名 | 决定是否规范命名和 taxonomy |
