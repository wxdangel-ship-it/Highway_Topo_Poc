# T04 方案策略

## 状态

- 文档状态：Round 2C Phase A 最小正式稿
- 来源依据：
  - `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
  - `modules/t04_rc_sw_anchor/README.md`
  - `src/highway_topo_poc/modules/t04_rc_sw_anchor/runner.py`
  - `tests/t04_rc_sw_anchor/`

## 策略总览

T04 当前采用“输入规范化 -> 分支上下文建立 -> DriveZone-first 扫描 -> 特殊规则家族处理 -> 结果与诊断落盘”的分阶段策略。它不是自由几何搜索模块，而是一个约束明确、证据优先、失败可解释的锚点识别模块。

## 核心阶段

### 1. 输入规范化

- 解析 `global_focus` 或 `patch` 模式输入。
- 对 node、road、divstrip、drivezone、traj、pointcloud 做字段与 CRS 归一化。
- 在 patch 自动发现入口中，先解析节点集合，再进入既有主链路。

### 2. 分支几何上下文建立

- 构建 road graph、节点上下文与分支配对。
- 在常规双分支场景中，采用 Between-Branches 扫描口径。
- 在多分支场景中，先做方向过滤与 span 构造，再提取 split event。

### 3. DriveZone-first 扫描

- 以 `SEG(s) ∩ DriveZone` 的片段变化作为主触发证据。
- divstrip 可作为近邻强参考，但不能驱动远距离漂移。
- 若在可接受 stop 范围内找不到 split，则进入 fail-closed。

### 4. 特殊规则家族处理

- continuous chain：处理连续分合流的顺序与合并边界。
- reverse tip：处理默认方向缺参考或近节点异常命中的反向搜索。
- multibranch：处理 `N>2` 时的事件提取与主结果选择。
- K16：采用独立道路约束和专用扫描流程。

### 5. 结果与诊断落盘

- 输出 `intersection_l_opt*.geojson`、`intersection_l_multi.geojson`、`anchors.json`、`metrics.json`、`breakpoints.json`、`summary.txt`。
- 结果不仅服务通过 case，也服务失败定位和批量审计。

## 当前策略取舍

- 优先保证锚点与横截线“来源可解释”，而不是几何上尽量生成某条线。
- 优先明确失败原因，而不是通过宽松 fallback 掩盖证据不足。
- 将 K16、continuous chain、multibranch 与 reverse tip 视为长期规则家族，而不是临时补丁。
