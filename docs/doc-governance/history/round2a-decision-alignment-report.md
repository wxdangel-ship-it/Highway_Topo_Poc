# Round 2A 决策对齐执行报告

## 本轮信息

- 轮次：项目文档结构整改 Round 2A
- 基线分支：`codex/doc-governance-round1`
- 执行分支：`codex/002-doc-governance-decision-alignment`
- 范围类型：人工决策写回与 durable guidance 固化
- 运行时影响：无

## 写回的 4 条人工决策

1. 当前正式 T05 模块为 `t05_topology_between_rc_v2`；`t05_topology_between_rc` 只作为 legacy 历史参考模块保留。
2. `t03_marking_entity` 已退役，不再作为当前活跃 taxonomy 成员。
3. `t10` 已退役，不再纳入当前正式 taxonomy；现有资料仅作为历史遗留保留。
4. repo root `AGENTS.md` 本轮创建，并只承载 repo 级 durable guidance。

## Analyze 摘要

对 `specs/archive/002-doc-governance-decision-alignment/spec.md`、`plan.md`、`tasks.md` 的交叉复核结果如下：

- 三份产物的范围一致：都聚焦于 decision alignment，而不是深迁移或算法改动。
- `spec.md` 定义的 4 条决策，在 `plan.md` 中都有对应文档面，在 `tasks.md` 中都有文件级任务落点。
- 本轮没有引入与 Round 1 目标结构冲突的新目录或新职责层。
- 活跃治理文档中不再把 T05/T05-V2、`t03`、`t10`、root `AGENTS` 作为未决事项。

### 残留旧口径检查

- 当前活跃治理文档：未发现仍需继续沿用的旧未决口径。
- 历史变更记录：`specs/archive/001-doc-governance-round1/*` 仍保留 Round 1 当时的未决表述，作为历史记录存在，不再代表当前治理结论。

### 新的 unresolved item

- 本轮没有新增治理级 unresolved item。

## 更新文件

- `specs/archive/002-doc-governance-decision-alignment/spec.md`
- `specs/archive/002-doc-governance-decision-alignment/plan.md`
- `specs/archive/002-doc-governance-decision-alignment/tasks.md`
- `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/codebase-research.md`
- `docs/architecture/01-introduction-and-goals.md`
- `docs/architecture/02-constraints.md`
- `docs/architecture/03-context-and-scope.md`
- `docs/architecture/04-solution-strategy.md`
- `docs/architecture/08-crosscutting-concepts.md`
- `docs/architecture/09-decisions/README.md`
- `docs/architecture/10-quality-requirements.md`
- `docs/architecture/11-risks-and-technical-debt.md`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/doc-governance/current-module-inventory.md`
- `docs/doc-governance/migration-map.md`
- `docs/doc-governance/module-doc-status.csv`
- `docs/doc-governance/review-priority.md`
- `docs/doc-governance/history/round1-exec-report.md`
- `docs/doc-governance/target-structure.md`
- `modules/t04_rc_sw_anchor/architecture/00-current-state-research.md`
- `modules/t04_rc_sw_anchor/architecture/02-constraints.md`
- `modules/t04_rc_sw_anchor/architecture/03-context-and-scope.md`
- `modules/t04_rc_sw_anchor/architecture/04-solution-strategy.md`
- `modules/t05_topology_between_rc_v2/architecture/00-current-state-research.md`
- `modules/t05_topology_between_rc_v2/architecture/02-constraints.md`
- `modules/t05_topology_between_rc_v2/architecture/03-context-and-scope.md`
- `modules/t05_topology_between_rc_v2/architecture/04-solution-strategy.md`
- `modules/t05_topology_between_rc_v2/architecture/11-risks-and-technical-debt.md`
- `modules/t05_topology_between_rc_v2/review-summary.md`
- `modules/t06_patch_preprocess/architecture/00-current-state-research.md`
- `modules/t06_patch_preprocess/architecture/02-constraints.md`
- `modules/t06_patch_preprocess/architecture/11-risks-and-technical-debt.md`
- `AGENTS.md`

## root `AGENTS.md` 规则摘要

- 明确项目级源事实、模块级源事实、`AGENTS.md`、`SKILL.md`、`specs/` 与历史证据的分层职责。
- 固化源事实优先级，禁止用 `AGENTS.md`、`SKILL.md` 或单次 change spec 替代长期真相。
- 要求中等以上的结构化治理变更优先使用 spec-kit，并使用独立分支。
- 固化“文档默认中文”的仓库级规则。
- 规定遇到任务书与源事实冲突时必须停止并请求确认。
- 保护范围边界：无明确任务时不改算法、运行逻辑与数据契约。

## T05-V2 的正式定位

- 当前正式 T05 模块：`t05_topology_between_rc_v2`
- 物理路径：保持 `modules/t05_topology_between_rc_v2/`
- 治理含义：后续模块级文档迁移以 T05-V2 作为正式 T05 语义主体；legacy T05 只保留历史参考价值

## legacy T05、`t03`、`t10` 的当前定义

- legacy T05：`t05_topology_between_rc`，定义为历史参考模块；保留文档与审计材料，但不再要求 family 连续治理。
- `t03_marking_entity`：已退役；不创建替代目录，不再作为活跃 taxonomy 成员。
- `t10`：已退役历史模块；保留现有资料与实现痕迹，但不进入当前正式 taxonomy 与活跃治理主线。

## 本轮没有做的事情

- 没有做算法或运行时逻辑修改，因为本轮只做文档决策对齐。
- 没有改物理目录名，因为任务书要求保留现有路径。
- 没有删除 legacy 文档，因为本轮目标是保留历史证据并纠正治理口径。
- 没有进入 Round 2B 或模块深迁移，因为本轮只负责把已确认决策写回仓库。
