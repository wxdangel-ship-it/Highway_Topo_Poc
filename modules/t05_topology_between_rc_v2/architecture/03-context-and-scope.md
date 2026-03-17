# T05-V2 上下文与范围

## 状态

- 当前状态：正式 T05 模块级架构说明
- 来源依据：
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`
  - `scripts/t05v2_*.sh`
  - `tests/test_t05v2_pipeline.py`
  - `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md`

## 上下文

- 模块位于 patch 级路口语义数据之后，消费 `intersection_l`、`DriveZone`、轨迹以及可选先验输入。
- 模块对外提供当前正式 T05 的成路结果与诊断产物，服务于运行验收、回归审计和后续人工复核。
- 当前模块拥有独立源码目录、独立输出根目录、独立脚本与测试，说明其已形成完整的模块级维护单元。
- 与 legacy `t05_topology_between_rc` 的关系仅限“同业务领域的历史参考”；当前正式语义与治理口径以本模块为主体。

## 本轮范围

- 正式化 T05-V2 的 `architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`SKILL.md`、`review-summary.md`。
- 明确 `history/REAL_RUN_ACCEPTANCE.md` 的运行验收边界。
- 在 legacy T05 中补最小历史参考指针，避免误把 legacy 文档当成当前正式 T05。

## 模块稳定范围

- `step1_input_frame` 到 `step6_build_road` 的阶段式执行模型。
- 分阶段落盘产物、`step_state.json` 和 `resume` 机制。
- 主输出 `Road.geojson`、`metrics.json`、`gate.json`、`summary.txt` 及关键 `debug/` 诊断产物。
- 当前简单真实 patch 与复杂回归 patch 的运行验收框架。

## 当前非范围

- 修改 T05-V2 算法与运行逻辑。
- 修改 T04、T06、T07、T02 或全仓治理结构。
- 对 legacy T05 做大规模迁移、删改或目录重整。
- 为所有 patch 定义统一的长期业务结论；本轮只固化当前正式模块的最小可信文档面。

## 当前人工审核重点

- 核对本文件的“稳定范围”是否已足以支撑后续模块级迁移，而不会把全仓治理话题带回本轮。
- 核对“非范围”约束是否足以保护本轮不滑向算法整改。
