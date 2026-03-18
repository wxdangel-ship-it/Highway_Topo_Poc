# T05-V2 约束

## 状态

- 当前状态：正式 T05 模块级架构说明
- 来源依据：
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/io.py`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/run.py`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/pipeline.py`
  - `tests/test_t05v2_pipeline.py`
  - `modules/t05_topology_between_rc_v2/history/REAL_RUN_ACCEPTANCE.md`

## 数据与运行约束

- `DriveZone` 是硬依赖；缺失或为空时必须硬失败。
- `intersection_l` 与轨迹数据是正式输入的一部分，缺失会阻断正常运行。
- 输入几何需统一规整到 `EPSG:3857`，下游输出与质量判断也以该坐标体系为准。
- `DivStripZone` 一旦存在，会作为 final road 的硬障碍参与判断；穿越 `DivStrip` 不能视为通过结果。
- `LaneBoundary` 属于可选增强输入，缺失或 CRS 需要修复时允许降级处理，但不能因此破坏主流程稳定性。
- 当前模块支持 `full` 和六个阶段入口；按阶段执行时，前序阶段的 `step_state.json` 与关键产物必须存在。

## 当前标准运行基线

- 当前运行验收文档以冻结的 Step2 baseline 为默认操作基线：
  - `--step2_strict_adjacent_pairing 1`
  - `--step2_allow_one_intermediate_xsec 0`
  - `--step2_same_pair_topk 1`
- pair-scoped `cross=1` 例外默认关闭，仅在明确任务要求时才启用。
- 上述运行基线属于当前正式运行约定；其入口与参数分组以 `INTERFACE_CONTRACT.md` 为准，操作者细节以 `history/REAL_RUN_ACCEPTANCE.md` 为准。

## 文档治理约束

- 当前正式 T05 模块是 `modules/t05_topology_between_rc_v2/`；legacy `modules/t05_topology_between_rc/` 仅为历史参考。
- `architecture/*` 与 `INTERFACE_CONTRACT.md` 才是当前模块的长期源事实。
- `AGENTS.md` 只保留稳定工作规则，repo root 标准 Skill 包只保留复用流程，二者都不能替代源事实文档。
- `history/REAL_RUN_ACCEPTANCE.md` 是历史运行验收文档，不承担长期架构真相职责。
- 文档默认使用中文撰写；参数、命令、路径、模块标识、配置键与字段名可保留英文。

## 本轮不触碰的约束

- 不修改算法、测试、运行脚本和入口逻辑。
- 不重命名物理目录。
- 不回退到 legacy T05 与 T05-V2 的家族连续治理口径。

## 当前人工审核重点

- 核对“当前标准运行基线”与后续真实验收习惯是否仍一致。
- 核对文档分层约束是否足以阻止稳定真相重新回流到 `AGENTS.md` 或运行验收文档。
