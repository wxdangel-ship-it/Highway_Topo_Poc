# 迁移映射

## 状态

- 当前状态：已吸收 Round 2A、Round 2B、Round 2C 与 Round 3A 的治理结论
- 当前策略：按生命周期决定迁移动作，而不是默认所有模块都继续 formalize
- 核心原则：默认非破坏；先校准生命周期，再决定是维护正式文档面、保留历史参考，还是仅补最小归档指针

## 项目级映射

| 当前文档 / 家族 | 当前属性 | 目标文档面 | 当前动作 | 后续动作 |
|---|---|---|---|---|
| `SPEC.md` | `source_of_truth` | 继续作为项目级总范围与模块状态真相 | 保留原位并写回正式生命周期口径 | 与 `docs/architecture/*`、`module-lifecycle.md` 保持一致 |
| `docs/architecture/*.md` | `source_of_truth` | 继续作为项目级长期架构真相 | 保留原位 | 仅做增量维护 |
| `docs/doc-governance/module-lifecycle.md` | `source_of_truth` | 生命周期专用真相面 | 新增并固定当前状态定义 | 后续所有模块状态调整都必须写回这里 |
| `docs/PROJECT_BRIEF.md` | `legacy_candidate` | 项目级摘要 / digest 层 | 保留原位并同步项目级正式口径 | 继续保持摘要定位 |
| `docs/ARTIFACT_PROTOCOL.md` | `source_of_truth` | 继续保留在 `docs/` | 保留原位 | 与项目级架构文档交叉引用 |
| `docs/AGENT_PLAYBOOK.md` / `docs/CODEX_*` / `docs/WORKSPACE_SETUP.md` | `durable_guidance` | 继续作为规则面 | 保留原位 | 不承担业务生命周期真相 |

## 生命周期驱动的模块映射

### Active 模块

| 对象 | 目标文档面 | 当前动作 | 后续动作 |
|---|---|---|---|
| `t04_rc_sw_anchor` | `architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `SKILL.md` + `review-summary.md` | 维持正式文档面 | 只做增量维护 |
| `t05_topology_between_rc_v2` | `architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `SKILL.md` + `review-summary.md` | 维持正式文档面 | 作为正式 T05 持续维护 |
| `t06_patch_preprocess` | `architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `SKILL.md` + `review-summary.md` | 维持正式文档面 | 只做增量维护 |

### Historical Reference 模块

| 对象 | 目标文档面 | 当前动作 | 后续动作 |
|---|---|---|---|
| legacy `t05_topology_between_rc` | 保留既有文档与历史证据 | 在现有入口文档补“历史参考”与“当前正式 T05”指针 | 只作为历史经验和证据来源，不进入 family 连续治理 |

### Retired 模块

| 对象 | 目标文档面 | 当前动作 | 后续动作 |
|---|---|---|---|
| `t02_ground_seg_qc` | 保留既有文档与实现 | 在入口文档补最小退役指针 | 不再进入正式化路线 |
| `t03_marking_entity` | 项目级退役记录 | 在项目级文档保留退役记录 | 不创建替代目录或新正式文档面 |
| `t07_patch_postprocess` | 保留既有文档与实现 | 在入口文档补最小退役指针 | 不再进入正式化路线 |
| `t10` | 保留既有文档、实现痕迹与阶段资料 | 在入口文档补最小退役指针 | 不再推进 taxonomy / naming 正式化 |

### 仓库保留支撑 / 测试模块

| 对象 | 目标文档面 | 当前动作 | 后续动作 |
|---|---|---|---|
| `t00_synth_data` | 保留既有支撑模块文档面 | 保持原位 | 后续单独做支撑模块整理 |
| `t01_fusion_qc` | 保留既有支撑模块文档面 | 保持原位 | 后续单独做支撑模块整理 |

## 入口指针策略

| 生命周期 | 指针写法 | 放置位置 | 本轮限制 |
|---|---|---|---|
| `Active` | 一般不需要额外生命周期指针 | 正式文档面自然承载 | 不重复制造摘要层 |
| `Historical Reference` | 说明“本模块已不是当前正式模块”，并指向当前正式模块与 `module-lifecycle.md` | 现有入口文档开头 | 不重写主体内容 |
| `Retired` | 说明“本模块已退役，不再属于当前活跃模块集合”，并指向 `module-lifecycle.md` | 现有入口文档开头 | 不补新 `architecture/*` / `SKILL.md` / 契约正式化 |

## 明确移出后续正式化路线的对象

- `t02_ground_seg_qc`
- `t03_marking_entity`
- `t07_patch_postprocess`
- `t10`
- legacy `t05_topology_between_rc`

这些对象当前只保留历史可见性、退役说明或历史参考指针，不再列入后续正式化迁移路线。
