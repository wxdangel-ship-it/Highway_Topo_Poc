# T05-V2 治理摘要

## 当前正式定位

- 当前正式 T05 模块：`modules/t05_topology_between_rc_v2`
- 物理路径保持：`modules/t05_topology_between_rc_v2`
- legacy `modules/t05_topology_between_rc`：仅保留为历史参考模块，不再按家族连续治理

## 当前最小正式文档面

- 稳定模块真相：`architecture/*`
- 稳定契约面：`INTERFACE_CONTRACT.md`
- 稳定工作规则：`AGENTS.md`
- 标准可复用流程：`.agents/skills/t05v2-doc-governance/SKILL.md`
- 标准 Skill 详细说明：`.agents/skills/t05v2-doc-governance/references/README.md`
- 当前治理摘要：`review-summary.md`
- 历史运行验收说明：`history/REAL_RUN_ACCEPTANCE.md`

## 模块业务主链

T05-V2 以 `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad` 为长期业务主链，在 RC 语义边界之间生成最终有向 `Road`，并对成路或失败提供可解释证据。

## 本轮正式化后已完成的收束

- 稳定业务真相已从 `AGENTS.md` 收回到 `architecture/*` 与 `INTERFACE_CONTRACT.md`。
- `AGENTS.md` 现在只保留开工前阅读顺序、允许改动范围、验证要求、禁做事项与 legacy 处理原则。
- 标准 Skill 包 `.agents/skills/t05v2-doc-governance/` 已建立，负责 T05-V2 文档治理和验收类任务的标准流程；其中详细 SOP 已下沉到 `references/README.md`。
- 旧模块根 `SKILL.md` 已移入 `history/SKILL.legacy.md`，不再作为 active 入口。
- `history/REAL_RUN_ACCEPTANCE.md` 已被明确标注为历史运行验收文档，长期源事实另有位置。

## 当前稳定输入 / 输出摘要

- 输入：`intersection_l`、`DriveZone`、轨迹数据，以及可选的 `DivStripZone`、`LaneBoundary`、既有 road 先验
- 主输出：`Road.geojson`、`metrics.json`、`gate.json`、`summary.txt`
- 关键诊断输出：`debug/corridor_identity.json`、`debug/slot_src_dst.geojson`、`debug/shape_ref_line.geojson`、`debug/road_final.geojson`、`debug/reason_trace.json`

## 当前硬约束摘要

- `DriveZone` 缺失或为空时必须硬失败
- 输出统一到 `EPSG:3857`
- `DivStrip` 作为 final road 的硬障碍
- 当前标准运行基线仍采用冻结的 Step2 baseline

## 后续仍待处理、但不阻塞当前正式化的问题

- 复杂 patch 上 `prior_based / unresolved` 仍可能偏高，后续仍需在算法轮次或更细文档轮次中继续解释和收敛。
- `history/REAL_RUN_ACCEPTANCE.md` 仍承载历史操作者知识，后续如继续保留，需持续保持与源事实同步。
- legacy T05 历史材料仍在仓库中，后续如再做清理，应以“历史参考”而不是家族连续治理为前提。

## 当前人工审核重点

- 审核 `architecture/05-building-block-view.md` 是否已足够支撑后续模块迁移。
- 审核 `INTERFACE_CONTRACT.md` 的参数边界是否既稳定又不过度下沉到实现细节。
