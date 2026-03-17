# T05-V2 审核摘要

## 当前模块目标

T05-V2 通过显式的阶段链路 `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad` 生成最终有向 `Road` 输出。

## 当前输入 / 输出

- 输入：`intersection_l`、`DriveZone`、轨迹数据，以及可选的 `DivStrip`、`LaneBoundary`、既有 road 向量
- 输出：`Road.geojson`、`metrics.json`、`gate.json`、`summary.txt`，以及较丰富的阶段性 debug 输出

## 硬约束

- `DriveZone` 缺失或为空时必须硬失败
- `DivStrip` 是硬屏障
- 输出规范到 `EPSG:3857`

## 当前混杂问题

- 模块身份和业务链路仍出现在 `AGENTS.md`
- 稳定 contract 目前较简且独立存在
- `REAL_RUN_ACCEPTANCE.md` 承载了高价值 runbook 知识，但并不是长期架构文档
- 当前没有 `SKILL.md`

## 推荐的新文档落位

- 稳定模块真相：`modules/t05_topology_between_rc_v2/architecture/*`
- 契约文档面：`modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md`
- 持久执行规则：`modules/t05_topology_between_rc_v2/AGENTS.md`
- runbook / 验收流程：继续保留 `REAL_RUN_ACCEPTANCE.md` 作为工作流 / 参考文档

## 已确认定位

- 当前正式 T05 模块：`t05_topology_between_rc_v2`
- 物理路径保持：`modules/t05_topology_between_rc_v2`
- legacy `t05_topology_between_rc` 仅作为历史参考模块保留

## 需要人工确认的问题

- 后续是否需要为 T05-V2 单独补一份 `SKILL.md`？
