# 迁移映射

## 状态

- 草案状态：Round 1 迁移映射，已由 Round 2A 决策对齐补充修正
- 策略：默认非破坏；先映射，再迁移

## 项目级映射

| 当前文档 / 家族 | 当前属性 | 目标文档面 | 当前动作 | 后续动作 |
|---|---|---|---|---|
| `SPEC.md` | `source_of_truth` | 继续保留在 `SPEC.md`，并从 `docs/architecture/01-04` 建立交叉链接 | 保留原位并修正当前正式模块口径 | 后续进一步收紧与项目级架构文档的边界 |
| `docs/ARTIFACT_PROTOCOL.md` | `source_of_truth` | 继续保留在 `docs/`，并由 `docs/architecture/08-crosscutting-concepts.md` 与 `10-quality-requirements.md` 引用 | 保留原位 | 后续决定是否增加协议摘要页 |
| `docs/AGENT_PLAYBOOK.md` | `durable_guidance` | 继续保留在 `docs/` | 保留原位 | 后续补充到架构与治理文档的显式指针 |
| `docs/CODEX_GUARDRAILS.md` | `durable_guidance` | 继续保留在 `docs/` | 保留原位 | 后续补充到架构与治理文档的显式指针 |
| `docs/CODEX_START_HERE.md` | `durable_guidance` | 继续保留在 `docs/` | 保留原位 | 后续与新的 onboarding 指针对齐 |
| `docs/WORKSPACE_SETUP.md` | `durable_guidance` | 继续保留在 `docs/` | 保留原位 | 后续从 `02-constraints.md` 建立引用 |
| `docs/PROJECT_BRIEF.md` | `legacy_candidate` | 摘要 / 参考层 | 保留原位并修正当前模块口径 | 后续转成带指针的 digest，或在审核后进一步收缩 |
| `docs/t05_business_logic_summary.md` | `legacy_candidate` | legacy T05 历史参考 | 保留原位 | 后续指向 legacy T05 的历史参考说明 |
| `docs/t05_business_audit_for_gpt_20260305.md` | `temporary_spec` | legacy T05 历史参考 | 保留原位 | 后续指向 legacy T05 的审核 / 归档区 |

## 模块级映射

### 通用模块规则

| 当前文档面 | 目标文档面 | 当前动作 | 后续动作 |
|---|---|---|---|
| `modules/<module>/INTERFACE_CONTRACT.md` | 继续作为 `architecture/` 旁的契约文档面 | 保留原位 | 待架构真相稳定后再削减重叠 |
| `modules/<module>/AGENTS.md` | 继续作为规则面 | 保留原位 | 后续收缩为持久规则 + 指针 |
| `modules/<module>/SKILL.md` | 继续作为工作流面 | 保留原位 | 后续收缩为可复用流程 |

### 重点模块

| 当前文档 / 家族 | 目标文档面 | 当前动作 | 后续动作 |
|---|---|---|---|
| `modules/t04_rc_sw_anchor/README.md` | `modules/t04_rc_sw_anchor/architecture/01-05` + `review-summary.md` | 保留并建立映射 | 后续视需要转成指针型摘要 |
| `modules/t04_rc_sw_anchor/AGENTS.md` | `modules/t04_rc_sw_anchor/AGENTS.md` + 指向 `architecture/` 的链接 | 保留并建立映射 | 后续剥离业务真相 |
| `modules/t04_rc_sw_anchor/SKILL.md` | `modules/t04_rc_sw_anchor/SKILL.md` + 指向 `architecture/` 的链接 | 保留并建立映射 | 后续剥离稳定规则内容 |
| `modules/t05_topology_between_rc_v2/AGENTS.md` | `modules/t05_topology_between_rc_v2/AGENTS.md` + `architecture/` + `review-summary.md` | 保留并写回“当前正式 T05”口径 | 后续把模块真相继续迁移到 `architecture/` |
| `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md` | 工作流 / 验收参考说明 | 保留原位 | 后续决定保留为 runbook 还是归入验收文档家族 |
| `modules/t06_patch_preprocess/AGENTS.md` | `modules/t06_patch_preprocess/AGENTS.md` + `architecture/` | 保留并建立映射 | 后续削减与 contract 的重叠 |
| `modules/t06_patch_preprocess/SKILL.md` | `modules/t06_patch_preprocess/SKILL.md` + `architecture/` | 保留并建立映射 | 后续削减与 contract 的重叠 |

### 历史参考 / 历史遗留家族

| 当前文档 / 家族 | 目标文档面 | 当前动作 | 后续动作 |
|---|---|---|---|
| `modules/t05_topology_between_rc/*` | legacy T05 历史参考 | 保留原位 | 后续按需补充指针，不进入活跃 family 连续治理 |
| `modules/t05_topology_between_rc/audits/*.md` | 历史证据家族 | 保留原位 | 后续补充源事实指针和归档说明 |
| `modules/t05_topology_between_rc/audits/runs/...` | 历史证据家族 | 保留原位 | 后续视需要建立索引 |
| `modules/t10/PHASE*.md` | T10 退役历史说明 | 保留原位 | 不再做正式 taxonomy 对齐 |
| `modules/t10/REVIEW_USAGE.md` | T10 历史审核流程说明 | 保留原位 | 仅作为历史参考保留 |

## 模块决策写回

| 对象 | 当前定义 | 当前动作 | 后续动作 |
|---|---|---|---|
| `t05_topology_between_rc_v2` | 当前正式 T05 模块，物理路径保持 V2 | 写回项目级与治理级正式口径 | 后续模块深迁移以其为正式主体 |
| `t05_topology_between_rc` | legacy 历史参考模块 | 保留原位，改为历史参考口径 | 后续按需提炼历史经验，不做 family 连续治理 |
| `t03_marking_entity` | 已退役，且无当前活跃目录 | 在治理文档中标记退役 | 保留历史可见性，不创建替代模块 |
| `t10` | 已退役历史模块 | 在治理文档中标记退役 | 保留现有资料和实现痕迹，不再推进 taxonomy / 命名正式化 |
