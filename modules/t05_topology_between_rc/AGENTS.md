# t05_topology_between_rc - AGENTS

## 历史参考说明

- 当前正式 T05 模块文档面位于 `modules/t05_topology_between_rc_v2/`。
- 本目录仅保留 legacy 历史参考，不再按 T05 家族连续治理。
- 本模块状态以 `docs/doc-governance/module-lifecycle.md` 为准。
- 如需当前正式口径，请优先读取 `modules/t05_topology_between_rc_v2/architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`SKILL.md`。

## Contract Delta
- Same-pair multi-road is a valid T05 output mode.
- Final same-pair roads must be emitted with stable channel identity and must remain non-crossing.
- `MULTI_ROAD_SAME_PAIR` should only mark unresolved same-pair branch conflicts, not valid multi-road output.
- Same-pair reporting must distinguish handled, valid multi-output, partial-unresolved, and hard-conflict pair states.

## 模块目标
- 基于 `intersection_l`、轨迹和 `DriveZone`，结合 `LaneBoundary`、点云与 `RCSDRoad` prior，生成 RC 路口间有向 `Road` 中心线。
- 输出可复核的质量产物：`RCSDRoad.geojson`、`metrics.json`、`intervals.json`、`summary.txt`、`gate.json`。

## 职责边界
- 仅处理 t05：候选路口对构建、中心线估计、门禁判断与报告导出。
- 不修改 t00/t01/t02/t03/t04 的实现与接口契约。
- 实现代码只放在 `src/highway_topo_poc/modules/t05_topology_between_rc/`。
- 文档契约只放在 `modules/t05_topology_between_rc/`。

## 输入
- 必需：`Vector/intersection_l.geojson`、`Traj/*/raw_dat_pose.geojson`、`Vector/DriveZone.geojson`
- 增强依赖：`Vector/LaneBoundary.geojson`、`Vector/RCSDRoad.geojson`
- 兜底/预留：`PointCloud/*.las|*.laz`（当前默认不启用）
- 可选诊断：`Vector/RCSDNode.geojson`、`Vector/DivStripZone.geojson`
- `RCSDRoad` prior 当前参与 Step1 邻接过滤与唯一链推断。

## 输出
固定写入：
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/RCSDRoad.geojson`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/metrics.json`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/intervals.json`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/summary.txt`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/gate.json`

## 禁止事项
- 不在 `data/synth_local`、`data/synth` 原始数据目录写入或覆盖。
- 不在 `outputs/` 下进行开发或 git 操作。
- 不跨模块改动其它 `modules/<id>/INTERFACE_CONTRACT.md`。
