# T04 审核摘要

## 当前模块目标

T04 采用 DriveZone-first、fail-closed 策略，为 merge/diverge 与 K16 形态生成锚点和 `intersection_l_opt` 输出。

## 当前输入 / 输出

- 输入：patch/global focus 输入，node/road/divstrip/drivezone/traj/pointcloud 图层
- 输出：anchor geojson/json、`intersection_l_opt`、metrics、breakpoints、summary、config snapshot

## 硬约束

- CRS 规范到 `EPSG:3857`
- 以 DriveZone 证据优先
- hard-stop 逻辑
- 不允许通过跨路口漂移去制造答案

## 当前混杂问题

- `INTERFACE_CONTRACT.md` 承载了最重的业务真相
- `AGENTS.md` 与 `SKILL.md` 仍包含稳定行为规则
- `README.md` 与未来架构叙事有重叠

## 推荐的新文档落位

- 稳定模块真相：`modules/t04_rc_sw_anchor/architecture/*`
- 契约细节：`modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
- 持久执行规则：`modules/t04_rc_sw_anchor/AGENTS.md`
- 可复用操作流程：`modules/t04_rc_sw_anchor/SKILL.md`

## 需要人工确认的问题

- 当 architecture 稳定后，README 是否仍保留为简洁的操作者总览？
- T04 哪些策略家族值得在后续形成 ADR 风格决策？
