# T04 构件视图

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：当前 `src/highway_topo_poc/modules/t04_rc_sw_anchor/` 文件布局

## 当前高层构件

- 输入规范化：
  - `field_norm.py`
  - `crs_norm.py`
  - `io_geojson.py`
  - `traj_io.py`
  - `pointcloud_io.py`
- 图结构与分支上下文：
  - `road_graph.py`
  - `node_discovery.py`
  - `between_branches.py`
  - `multibranch_ops.py`
- 几何与扫描：
  - `geometry_ops.py`
  - `drivezone_ops.py`
  - `divstrip_ops.py`
  - `continuous_chain.py`
  - `k16_ops.py`
- 诊断与输出：
  - `metrics_breakpoints.py`
  - `writers.py`
  - `runner.py`
  - `cli.py`

## 审核重点

- 确认这种构件分组是长期概念分组，而不是简单的文件清单转抄
