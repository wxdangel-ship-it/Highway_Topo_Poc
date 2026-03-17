# T04 约束

## 状态

- 文档状态：Round 2C Phase A 最小正式稿
- 来源依据：
  - `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
  - `src/highway_topo_poc/modules/t04_rc_sw_anchor/config.py`
  - `src/highway_topo_poc/modules/t04_rc_sw_anchor/runner.py`
  - `tests/t04_rc_sw_anchor/`

## 数据与运行约束

- 输入图层在参与计算前必须统一规整到 `dst_crs`，默认 `EPSG:3857`。
- `global_focus` 模式下必须提供 `global_node_path`、`global_road_path` 与 `focus_node_ids`。
- `patch` 模式与 patch 自动发现入口允许从 patch 目录推导局部输入，但不会改变模块核心链路。
- 输出目录固定在 `outputs/_work/t04_rc_sw_anchor/<run_id>/` 下。

## 业务硬约束

- DriveZone-first 是主证据链，不能用远处几何线索替代。
- stop 逻辑必须坚持 hard-stop 和 fail-closed。
- 不允许通过跨路口漂移去制造答案。
- 状态机必须保证 fail 不会被后续 suspect 或其他标记覆盖。
- K16、continuous chain、multibranch、reverse tip 都必须在明确规则下运行，而不是被临时 fallback 隐式处理。

## 文档治理约束

- 长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。
- `AGENTS.md` 只保留稳定工作规则，`SKILL.md` 只保留复用流程。
- `README.md` 是操作者总览，不再承担完整源事实职责。
- 文档默认中文；参数、命令、路径、模块标识和配置键可保留英文。

## 本轮不触碰的约束

- 不修改 T04 实现、测试、批处理脚本或 patch 自动发现脚本。
- 不改物理目录名。
- 不改下游模块契约。
