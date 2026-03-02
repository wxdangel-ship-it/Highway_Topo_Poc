# t04_rc_sw_anchor

## 1. 业务目标（vNext）
- 面向 `merge/diverge` 节点，输出锚点与最终横截线 `intersection_l_opt`。
- 采用 `DriveZone-first`：主触发证据来自 `SEG(s) ∩ DriveZone` 的连通片段数变化。
- 采用 `Between-Branches(B)`：每一步只在两分支之间构造 `SEG(s)=PA->PB`，避免扫到无关道路。
- stop 仅 `hard-stop`：沿 RCSDRoad 拓扑联通可达，且 `degree>=3`。
- 在 stop 范围内找不到 split 时直接 `FAIL`，不允许跨路口追远处导流带补答案。

## 2. 关键流程
1. 输入解析：`global_focus` / `patch`，`focus_node_ids` 优先级 `CLI > file > config_json`。
2. 字段归一化：`field_norm.normalize_props` + `get_first_int/get_first_raw`。
3. CRS 归一化：`node/road/divstrip/drivezone/traj/pointcloud` 全部归一化到 `dst_crs`（默认 `EPSG:3857`）。
4. 分支选择：按 `kind` 分 merge/diverge，分支对用“最大夹角对”，多分支记 `MULTI_BRANCH_TODO`。
5. 扫描与 stop：沿 `scan_axis_road` 扫描到 `next_intersection_connected_deg3` 或 `scan_max_limit_m`。
6. split 判定：`SEG(s)` 与 DriveZone 的交段数 `>=2` 的最早 `s*` 触发。
7. 输出构造：在 `s*` 输出两条 LineString（`piece_idx=0/1`）；anchor 用 gap 中点，失败时回退 SEG 中点并写断点。
8. 可选 divstrip 证据：仅在 `s*` 邻域做解释/吸附，不允许驱动远距离扫描。

## 3. 运行入口
```bash
python -m highway_topo_poc.modules.t04_rc_sw_anchor --help
```

## 4. CLI 示例（global_focus）
```bash
python -m highway_topo_poc.modules.t04_rc_sw_anchor \
  --mode global_focus \
  --patch_dir /mnt/d/TestData/highway_topo_poc_data/normal/2855795596723843 \
  --out_root outputs/_work/t04_rc_sw_anchor \
  --focus_node_ids "5278670377721456,5278670377721468" \
  --global_node_path /mnt/d/TestData/.../RCSDNode.geojson \
  --global_road_path /mnt/d/TestData/.../RCSDRoad.geojson \
  --divstrip_path /mnt/d/TestData/.../DivStripZone.geojson \
  --drivezone_path /mnt/d/TestData/.../DriveZone.geojson \
  --pointcloud_path /mnt/d/TestData/.../merged_cleaned_classified_3857.laz \
  --traj_glob "/mnt/d/TestData/.../Traj/*/raw_dat_pose.geojson" \
  --dst_crs EPSG:3857 \
  --drivezone_src_crs auto \
  --min_piece_len_m 1.0 \
  --next_intersection_degree_min 3 \
  --disable_geometric_stop_fallback true
```

## 5. 输出目录
`outputs/_work/t04_rc_sw_anchor/<run_id>/`

- `anchors_3857.geojson`
- `intersection_l_opt_3857.geojson`
- `anchors_wgs84.geojson`
- `intersection_l_opt_wgs84.geojson`
- `anchors.geojson` / `intersection_l_opt.geojson`（兼容名）
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

`intersection_l_opt*.geojson` 约定：
- 同一 `nodeid` 输出两条 feature（`piece_idx=0/1`，`piece_role=branch_a_side/branch_b_side`）。
- properties 必含 `nodeid/kind/kind_bits/anchor_type/scan_dist_m/stop_reason/evidence_source` 与关键诊断字段。

## 6. 已知边界
- 当前稳定支持二分歧/二合流。
- 多分支采用“最大夹角对”过渡策略，并记录 `MULTI_BRANCH_TODO`（Minor）。
- `min_piece_len_m` 仅用于数值噪声抑制，不用于业务口径 auto-tune。

## 7. 配置模板
`modules/t04_rc_sw_anchor/t04_config_template_global_focus.json`
