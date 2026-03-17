# T05-V2 构件视图

## 状态

- 当前状态：正式 T05 模块级架构说明
- 来源依据：
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`
  - `tests/test_t05v2_pipeline.py`
  - `modules/t05_topology_between_rc_v2/history/REAL_RUN_ACCEPTANCE.md`

## 长期概念链

T05-V2 的长期概念链不是按文件名排列，而是按业务阶段排列：

`Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad`

这条链是当前正式 T05 模块的核心构件关系。实现文件、debug 产物和验收口径都应围绕这条链组织理解。

## 共享基础构件

| 构件 | 职责 | 主要文件 |
|---|---|---|
| 输入与落盘基础 | 读取 patch 输入、统一 CRS、写出 JSON/GeoJSON、管理 `step_state.json` | `io.py` |
| 命令行与阶段调度 | 暴露 CLI、参数、阶段入口与 `full` 执行 | `run.py`, `main.py`, `runner.py` |
| 数据模型 | 定义 `Segment`、`CorridorWitness`、`CorridorIdentity`、`SlotInterval`、`FinalRoad` 等结构 | `models.py` |

## 阶段构件映射

| 阶段 | 核心实体 | 主要职责 | 主要实现文件 | 关键产物 |
|---|---|---|---|---|
| `step1_input_frame` | `InputFrame` / `PatchInputs` | 读取 patch 输入、统一 `EPSG:3857`、建立阶段起点 | `io.py`, `run.py`, `runner.py` | `step1/input_frame.json`, `step1/step_state.json` |
| `step2_segment` | `Segment` / legal arc | 生成候选段、套用 arc 选择与拓扑规则、记录合法性审计 | `pipeline.py`, `arc_selection_rules.py`, `step2_arc_registry.py`, `xsec_endpoint_interval.py` | `debug/segment_candidates.geojson`, `debug/segment_selected.geojson`, `step2/*.json` |
| `step3_witness` | `CorridorWitness` | 提炼轨迹和支撑证据，处理 same-pair / support deconflict 等问题 | `step3_arc_evidence.py`, `witness_review.py`, `pipeline.py` | `step3/*.json`, witness 相关 review 产物 |
| `step4_corridor_identity` | `CorridorIdentity` | 把 witness、prior 与 topology 证据收敛为 corridor 语义状态 | `step3_corridor_identity.py`, `pipeline.py` | `debug/corridor_identity.json`, `step4/*.json` |
| `step5_slot_mapping` | `Slot` / endpoint interval | 为 source / destination 端点建立区间与落位约束 | `step5_conservative_road.py`, `xsec_endpoint_interval.py`, `pipeline.py` | `debug/slot_src_dst.geojson`, `step5/*.json` |
| `step6_build_road` | `FinalRoad` | 选择 shape reference、生成最终几何、执行质量门控并产出总结 | `step5_conservative_road.py`, `step5_global_geometry_fit.py`, `review.py`, `audit_acceptance.py`, `pipeline.py` | `Road.geojson`, `metrics.json`, `gate.json`, `summary.txt`, `debug/road_final.geojson`, `debug/reason_trace.json` |

## 构件协作关系

- `Segment` 负责把输入轨迹和边界关系变成“可以讨论的候选跨度”。
- `CorridorWitness` 负责回答“这条候选跨度有什么证据支持它属于当前 corridor”。
- `CorridorIdentity` 负责把证据收敛为 `witness_based`、`prior_based` 或 `unresolved` 等可解释状态。
- `Slot` 负责把 corridor 语义转成端点落位约束，避免最终几何直接漂移。
- `FinalRoad` 负责在几何约束、`DriveZone`、`DivStrip` 和 shape reference 之间做最终闭环。

## 审计与诊断构件

- `audit_acceptance.py` 面向运行验收与审计 bundle，负责从 `metrics.json`、`gate.json` 等结果文件中生成可读审计信息。
- `review.py` 与 `debug/` 产物共同支撑“失败时能否解释原因”的要求。
- `scripts/t05v2_step*.sh` 和 `scripts/t05v2_resume.sh` 不定义业务真相，但把分阶段执行模型暴露给操作者。

## 当前人工审核重点

- 核对“阶段构件映射”是否已经能支撑后续把稳定真相长期留在 `architecture/*`。
- 核对 `step4` 与 `step5` 的职责边界是否足够清楚，避免后续文档再次把 corridor 与 slot 混写。
