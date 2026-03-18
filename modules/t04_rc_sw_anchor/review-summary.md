# T04 治理摘要

## 当前正式定位

- 当前模块：`modules/t04_rc_sw_anchor`
- 当前角色：核心锚点识别模块，面向 merge / diverge 与 K16 形态输出 `intersection_l_opt` 及诊断结果
- 当前文档分层：`architecture/*` 承担长期真相，`INTERFACE_CONTRACT.md` 承担稳定契约，`AGENTS.md` 承担规则，repo root `.agents/skills/t04-doc-governance/` 承担标准可复用流程，`README.md` 承担操作者总览

## 当前最小正式文档面

- 稳定模块真相：`architecture/*`
- 稳定契约面：`INTERFACE_CONTRACT.md`
- 稳定工作规则：`AGENTS.md`
- 标准可复用流程：`.agents/skills/t04-doc-governance/SKILL.md`
- 标准 Skill 详细说明：`.agents/skills/t04-doc-governance/references/README.md`
- 操作者总览：`README.md`
- 当前治理摘要：`review-summary.md`

## 模块业务主链

T04 以 DriveZone-first、Between-Branches、hard-stop 与 fail-closed 为长期约束，在 merge / diverge 与 K16 等形态上输出锚点和 `intersection_l_opt`，并保留足够的断点与诊断结果供人工复核。

## 本轮正式化后已完成的收束

- 稳定业务真相已从 `AGENTS.md`、旧模块根 `SKILL.md` 和 README 收回到 `architecture/*` 与 `INTERFACE_CONTRACT.md`。
- `AGENTS.md` 现在只保留阅读顺序、允许改动范围、验证要求和禁做事项。
- T04 专用复用流程已迁入 repo root `.agents/skills/t04-doc-governance/`，其中顶层 `SKILL.md` 只保留高层入口，详细 SOP 下沉到 `references/README.md`。
- 旧模块根 `SKILL.md` 已移入 `history/SKILL.legacy.md`，不再作为 active 入口。
- README 被重新界定为操作者入口，而不是模块真相主表面。

## 当前稳定输入 / 输出摘要

- 输入模式：`global_focus` / `patch`
- 核心输入：node、road、drivezone，以及可选的 divstrip、traj、pointcloud
- 核心输出：`intersection_l_opt*.geojson`、`intersection_l_multi.geojson`、`anchors.json`、`metrics.json`、`breakpoints.json`、`summary.txt`

## 当前硬约束摘要

- 输入统一规整到 `EPSG:3857`
- DriveZone-first
- hard-stop + fail-closed
- 不允许跨路口漂移补答案
- fail 不允许被后续状态覆盖

## 后续仍待处理、但不阻塞当前正式化的问题

- contract 仍较长，后续可能需要把部分复杂规则家族拆成更细的决策记录。
- README 仍保留较多操作者语境，后续需持续与源事实同步。
- continuous chain、multibranch、reverse tip、K16 的未来扩张会继续提高文档维护成本，但不阻塞当前正式化。
