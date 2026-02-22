# t05_topology_between_rc - AGENTS

## 模块目标
- 基于 `intersection_l`、轨迹、点云和 `LaneBoundary`，生成 RC 路口间有向 `Road` 中心线。
- 输出可复核的质量产物：`Road.geojson`、`metrics.json`、`intervals.json`、`summary.txt`、`gate.json`。

## 职责边界
- 仅处理 t05：候选路口对构建、中心线估计、门禁判断与报告导出。
- 不修改 t00/t01/t02/t03/t04 的实现与接口契约。
- 实现代码只放在 `src/highway_topo_poc/modules/t05_topology_between_rc/`。
- 文档契约只放在 `modules/t05_topology_between_rc/`。

## 输入
- `Vector/intersection_l.geojson`
- `Traj/*/raw_dat_pose.geojson`
- `PointCloud/*.las|*.laz`
- `Vector/LaneBoundary.geojson`
- 可选：`Vector/Node.geojson`、`Vector/DivStripZone.geojson`

## 输出
固定写入：
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/Road.geojson`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/metrics.json`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/intervals.json`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/summary.txt`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/gate.json`

## 禁止事项
- 不在 `data/synth_local`、`data/synth` 原始数据目录写入或覆盖。
- 不在 `outputs/` 下进行开发或 git 操作。
- 不跨模块改动其它 `modules/<id>/INTERFACE_CONTRACT.md`。
