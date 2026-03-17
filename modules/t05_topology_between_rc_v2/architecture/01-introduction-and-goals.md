# T05-V2 引言与目标

## 状态

- 文档状态：Round 2B 最小正式稿
- 来源依据：
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/run.py`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/pipeline.py`
  - `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md`
  - `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md`

## 模块使命

T05-V2 负责在 RC 语义边界之间生成当前正式 T05 的最终有向 `Road`。模块不是 legacy T05 的参数分支，而是当前正式发布口径下独立维护的 T05 实现与文档主体。

## 当前目标

- 把 patch 级输入整理为统一的输入框架，并规整到 `EPSG:3857`。
- 沿 `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad` 的阶段链，逐层缩小不确定性，而不是直接一步出路。
- 对成功与失败都给出可解释证据：成功要能说明为什么成路，失败要能指出卡在 corridor、slot 还是 final road。
- 通过稳定的输出目录、阶段产物和脚本入口，支撑真实运行、回归验收和文档治理。

## 成功边界

- 当证据充分时，模块输出非空 `Road.geojson`，并在 `metrics.json`、`gate.json`、`summary.txt` 中留下可审计结果。
- 当证据不足或几何不合规时，模块允许“不成路”，但必须通过 `debug/` 与审计产物说明原因，而不是静默失败。
- 当前正式 T05 的语义主体始终是 T05-V2；legacy T05 仅作为历史参考，不参与当前正式文档面的定义。

## 本轮后的人类阅读路径

- 先用本文件理解模块使命与目标。
- 再读 `05-building-block-view.md` 理解阶段链如何映射到实现构件。
- 再读 `INTERFACE_CONTRACT.md` 理解稳定入口、输入输出与验收标准。
- 如需真实运行或操作清单，再读 `REAL_RUN_ACCEPTANCE.md`。

## 后续人工审核重点

- 核对“当前正式 T05 = T05-V2”的表述是否已足够稳定。
- 核对模块目标是否既能覆盖当前实现，又没有把运行验收细节误写成顶层长期目标。
