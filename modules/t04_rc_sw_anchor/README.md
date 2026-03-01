# t04_rc_sw_anchor

## 1. 模块能力（vNext）
- merge/diverge 锚点识别（gore tip/nose 近似）
- 主证据切换为 `DriveZone`：`divstrip+dz`（扇形中轴带内非 DriveZone 判别）
- 扫描 stop 使用“联通 + degree>=3”的下一路口，不再默认几何 fallback
- `intersection_l_opt` 可选按 DriveZone 裁剪，输出线段落在可行驶区
- 所有输入图层统一到 `dst_crs`（默认 `EPSG:3857`）再计算
- 输出双版本 GeoJSON：`_3857` + `_wgs84`，并保留兼容文件名

## 2. 运行入口
```bash
python -m highway_topo_poc.modules.t04_rc_sw_anchor --help
```

## 3. 纯 CLI 示例（WSL）
```bash
python -m highway_topo_poc.modules.t04_rc_sw_anchor \
  --mode global_focus \
  --patch_dir /mnt/d/TestData/highway_topo_poc_data/normal/2855795596723843 \
  --out_root outputs/_work/t04_rc_sw_anchor \
  --focus_node_ids "5278670377721456,5278670377721468" \
  --global_node_path /mnt/d/TestData/.../RCSDNode.geojson \
  --global_road_path /mnt/d/TestData/.../RCSDRoad.geojson \
  --divstrip_path /mnt/d/TestData/highway_topo_poc_data/normal/2855795596723843/Vector/DivStripZone.geojson \
  --drivezone_path /mnt/d/TestData/highway_topo_poc_data/normal/2855795596723843/Vector/DriveZone.geojson \
  --pointcloud_path /mnt/d/TestData/highway_topo_poc_data/normal/2855795596723843/PointCloud/merged_cleaned_classified_3857.laz \
  --traj_glob "/mnt/d/TestData/highway_topo_poc_data/normal/2855795596723843/Traj/*/raw_dat_pose.geojson" \
  --dst_crs EPSG:3857 \
  --drivezone_src_crs auto \
  --drivezone_clip_crossline true \
  --drivezone_fan_radius_m 20 \
  --drivezone_fan_half_angle_deg 30 \
  --drivezone_fan_band_width_m 6 \
  --drivezone_non_drivezone_area_min_m2 3 \
  --drivezone_non_drivezone_frac_min 0.15 \
  --next_intersection_degree_min 3 \
  --stop_intersection_require_connected true \
  --disable_geometric_stop_fallback true
```

## 4. Focus NodeIDs 提供方式
- `--focus_node_ids "id1,id2"`
- `--focus_node_ids_file <txt|json|csv>`
- `--config_json` 中 `focus_node_ids`

优先级：CLI 覆盖 `config_json`。

## 5. 多 Patch 批量运行脚本（WSL）
脚本路径：`modules/t04_rc_sw_anchor/scripts/run_t04_batch_wsl.sh`

用法：
```bash
modules/t04_rc_sw_anchor/scripts/run_t04_batch_wsl.sh \
  --data_root /mnt/d/TestData/highway_topo_poc_data/normal \
  --global_node_path /mnt/d/TestData/global/RCSDNode.geojson \
  --global_road_path /mnt/d/TestData/global/RCSDRoad.geojson \
  --cases_file modules/t04_rc_sw_anchor/scripts/batch_cases_example.txt \
  --out_root outputs/_work/t04_rc_sw_anchor
```

`cases_file` 每行一个 patch：
```text
patch_id:nodeid1,nodeid2,nodeid3
```

也支持直接通过参数传多个 patch：
```bash
modules/t04_rc_sw_anchor/scripts/run_t04_batch_wsl.sh \
  --data_root /mnt/d/TestData/highway_topo_poc_data/normal \
  --global_node_path /mnt/d/TestData/global/RCSDNode.geojson \
  --global_road_path /mnt/d/TestData/global/RCSDRoad.geojson \
  --case "2855795596742991:503176747,504381536" \
  --case "2855795596723843:5278670377721456,5278670377721468"
```

支持参数：
- `--dry_run`（只打印命令，不执行）
- `--set key=value`（可重复，用于透传 t04 参数）

## 6. 输出目录
`outputs/_work/t04_rc_sw_anchor/<run_id>/`

- `anchors_3857.geojson`
- `intersection_l_opt_3857.geojson`
- `anchors_wgs84.geojson`
- `intersection_l_opt_wgs84.geojson`
- `anchors.geojson`（兼容名，内容同 dst_crs 版本）
- `intersection_l_opt.geojson`（兼容名，内容同 dst_crs 版本）
- `anchors.json`（包含扇形判别与 clip 诊断）
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

## 7. 配置模板
见：`modules/t04_rc_sw_anchor/t04_config_template_global_focus.json`
