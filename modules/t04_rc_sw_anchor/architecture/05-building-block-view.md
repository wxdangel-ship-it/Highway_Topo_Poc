# T04 构件视图

## 状态

- 当前状态：T04 模块级架构说明
- 来源依据：
  - `src/highway_topo_poc/modules/t04_rc_sw_anchor/`
  - `tests/t04_rc_sw_anchor/`

## 长期构件结构

T04 的稳定构件结构可以按“输入规范化 -> 分支上下文 -> 扫描与规则 -> 诊断与输出”来理解，而不是按单个文件平铺。

## 构件分组

| 构件组 | 主要职责 | 主要文件 |
|---|---|---|
| 输入与归一化 | 字段归一化、CRS 归一化、GeoJSON/轨迹/点云读取 | `field_norm.py`, `crs_norm.py`, `io_geojson.py`, `traj_io.py`, `pointcloud_io.py`, `config.py` |
| 图结构与节点上下文 | road graph 构建、节点发现、分支上下文建立 | `road_graph.py`, `node_discovery.py`, `between_branches.py`, `multibranch_ops.py` |
| 几何与规则族 | DriveZone / divstrip 处理、continuous chain、K16、基础几何操作 | `geometry_ops.py`, `drivezone_ops.py`, `divstrip_ops.py`, `continuous_chain.py`, `k16_ops.py` |
| 执行调度 | CLI、运行时组装、模块主流程驱动 | `cli.py`, `runner.py`, `__main__.py` |
| 诊断与写出 | metrics、breakpoints、GeoJSON/JSON/summary 输出 | `metrics_breakpoints.py`, `writers.py` |

## 稳定阶段映射

| 阶段 | 稳定职责 | 关键构件 |
|---|---|---|
| 输入准备 | 解析模式、归一化字段与 CRS、解析 seeds | `cli.py`, `config.py`, `field_norm.py`, `crs_norm.py`, `io_geojson.py`, `node_discovery.py` |
| 分支与扫描上下文 | 建立 graph、选择 branch pair 或 multibranch span、确定扫描基准 | `road_graph.py`, `between_branches.py`, `multibranch_ops.py` |
| DriveZone-first 判定 | 在 `SEG(s)` 上判断 split 与 stop，保持 fail-closed | `drivezone_ops.py`, `divstrip_ops.py`, `geometry_ops.py`, `runner.py` |
| 特殊规则处理 | continuous chain、reverse tip、K16、多事件主结果选择 | `continuous_chain.py`, `k16_ops.py`, `multibranch_ops.py`, `runner.py` |
| 结果与诊断输出 | 写出 crossline、anchors、metrics、breakpoints、summary | `writers.py`, `metrics_breakpoints.py`, `runner.py` |

## 构件协作关系

- `road_graph.py` 与 `between_branches.py` 决定“在什么拓扑上下文里扫描”。
- `drivezone_ops.py` 与 `divstrip_ops.py` 决定“在当前扫描位置看到了什么证据”。
- `continuous_chain.py`、`multibranch_ops.py`、`k16_ops.py` 负责处理常规链路之外但已稳定存在的规则家族。
- `metrics_breakpoints.py` 与 `writers.py` 把结果与失败原因变成可审计产物。
