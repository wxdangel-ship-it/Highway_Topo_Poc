# T05-V2 质量要求

## 状态

- 当前状态：正式 T05 模块级架构说明
- 来源依据：
  - `tests/test_t05v2_pipeline.py`
  - `modules/t05_topology_between_rc_v2/history/REAL_RUN_ACCEPTANCE.md`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/io.py`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/pipeline.py`

## 最小质量目标

- 输入完整性可检查：缺失 `DriveZone` 或关键输入时必须明确失败，而不是继续产出伪结果。
- 阶段执行可追踪：每个阶段都应留下足够的中间产物和 `step_state.json`，支持分步执行与 `resume`。
- 结果质量可解释：无论是否成路，都应能从 `metrics.json`、`gate.json` 与 `debug/` 产物中定位问题层次。
- 输出几何受约束：最终 `Road` 必须满足 `DriveZone` / `DivStrip` 相关质量门控，而不是只追求几何连通。

## 输入与阶段质量要求

- 输入几何统一规整到 `EPSG:3857`。
- `DriveZone` 缺失或为空必须硬失败。
- 按阶段执行时，缺失前序阶段状态或关键产物时必须明确报错。
- `scripts/t05v2_resume.sh` 必须能够基于已有阶段状态继续执行，说明当前分阶段执行模型是可操作的。

## 成功结果的最小验收要求

- 通过结果至少应包含：
  - 非空 `Road.geojson`
  - `metrics.json`
  - `gate.json`
  - `summary.txt`
- 对 built case：
  - `gate.json` 应表现为整体通过
  - `metrics.json` 中应能看到 corridor 已收敛、slot 已 resolved、`failure_classification = built`
  - 最终 `Road` 需满足 `DriveZone` / `DivStrip` 相关门控
- 对简单稳定样例，现有测试已证明可以达到：
  - `gate.json` 整体通过
  - `road_count = 1`
  - `corridor_identity_state = witness_based`
  - `slot_src_status = resolved`
  - `slot_dst_status = resolved`
  - `road_in_drivezone_ratio >= 0.99`

## 失败结果的可解释性要求

- 不能成路时，必须能区分至少以下失败层次：
  - corridor 未收敛
  - slot 映射失败
  - 最终几何不合法
  - 应归入 `no_geometry_candidate`
- `debug/reason_trace.json`、`debug/corridor_identity.json`、`debug/slot_src_dst.geojson` 和 `metrics.json` 应能支撑人工定位问题层次。
- `DivStrip` 拦截类失败必须能在 `gate.json` 与 `failure_classification` 中留下证据，而不是只表现为“没有 Road”。

## 当前验收边界

- `history/REAL_RUN_ACCEPTANCE.md` 继续定义操作者如何运行、先看哪些 patch、如何看输出顺序。
- 本文件只定义长期质量目标与最小验收要求，不承载具体 patch 名单和详细操作清单。

## 当前人工审核重点

- 核对本文件中的“最小验收要求”是否已覆盖当前正式模块最重要的通过 / 失败判据。
- 核对运行验收文档中的操作性判断是否都能回溯到这里描述的长期质量目标。
