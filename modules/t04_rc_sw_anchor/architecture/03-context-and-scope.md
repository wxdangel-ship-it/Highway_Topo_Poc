# T04 上下文与范围

## 状态

- 当前状态：T04 模块级架构说明
- 来源依据：
  - `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
  - `modules/t04_rc_sw_anchor/README.md`
  - `src/highway_topo_poc/modules/t04_rc_sw_anchor/`
  - `tests/t04_rc_sw_anchor/`

## 上下文

- T04 位于 patch / global focus 输入与下游路口间拓扑模块之间。
- 上游提供 node、road、DriveZone、divstrip、traj、pointcloud 等图层或其子集。
- 下游主要消费 `intersection_l_opt` 与相关锚点结果，用于后续拓扑与通路推断。
- T04 同时面向单 patch 运行、批量处理和 patch 自动发现节点三类操作者场景。

## 当前范围

- merge / diverge 锚点识别。
- K16 专用处理路径。
- continuous chain、multibranch、reverse tip 等复杂规则家族。
- 结果输出、诊断落盘与门禁统计。

## 当前非范围

- 修改 T04 算法或几何策略。
- 修改下游模块消费方式。
- 清理或删除历史操作者文档。
- 将所有细粒度规则拆成 ADR 或全仓决策记录。

## 相邻材料边界

- `INTERFACE_CONTRACT.md` 负责稳定契约面。
- `README.md` 负责操作者友好入口与脚本使用提示。
- batch / auto-node 脚本负责执行入口，不承担模块真相定义。
