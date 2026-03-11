# t05_topology_between_rc_v2 - INTERFACE_CONTRACT

## 目标
- 在 RC 语义边界之间生成最终有向 `Road`。
- 先建立 `Segment`，再判定 `CorridorIdentity`，最后映射 `Slot` 并生成 `FinalRoad`。

## 输入
- 必需：
  - `Vector/intersection_l.geojson`
  - `Vector/DriveZone.geojson`
  - `Traj/*/raw_dat_pose.geojson`
- 可选：
  - `Vector/DivStripZone.geojson`
  - `Vector/LaneBoundary.geojson`
  - `Vector/RCSDRoad.geojson` 或 `Vector/Road.geojson`

## 运行入口
- `python -m highway_topo_poc.modules.t05_topology_between_rc_v2.run`

## 分步
- `step1_input_frame`
- `step2_segment`
- `step3_witness`
- `step4_corridor_identity`
- `step5_slot_mapping`
- `step6_build_road`

## 输出
- `outputs/_work/t05_topology_between_rc_v2/<run_id>/patches/<patch_id>/Road.geojson`
- `outputs/_work/t05_topology_between_rc_v2/<run_id>/patches/<patch_id>/metrics.json`
- `outputs/_work/t05_topology_between_rc_v2/<run_id>/patches/<patch_id>/gate.json`
- `outputs/_work/t05_topology_between_rc_v2/<run_id>/patches/<patch_id>/summary.txt`
