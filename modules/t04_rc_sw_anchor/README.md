# t04_rc_sw_anchor

## 1. 模块能力（v5）
- merge/diverge 锚点识别（gore tip/nose 近似）
- 所有输入图层 CRS 归一化到 `dst_crs`（默认 `EPSG:3857`）后再计算
- DivStrip 优先触发，避免 `pc_only@1m` 抢跑
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
  --pointcloud_path /mnt/d/TestData/highway_topo_poc_data/normal/2855795596723843/PointCloud/merged_cleaned_classified_3857.laz \
  --traj_glob "/mnt/d/TestData/highway_topo_poc_data/normal/2855795596723843/Traj/*/raw_dat_pose.geojson" \
  --dst_crs EPSG:3857 \
  --node_src_crs auto \
  --road_src_crs auto \
  --divstrip_src_crs auto \
  --traj_src_crs auto \
  --pointcloud_crs auto
```

## 4. Focus NodeIDs 提供方式
- `--focus_node_ids "id1,id2"`
- `--focus_node_ids_file <txt|json|csv>`
- `--config_json` 中 `focus_node_ids`

优先级：CLI 覆盖 `config_json`。

## 5. 输出目录
`outputs/_work/t04_rc_sw_anchor/<run_id>/`

- `anchors_3857.geojson`
- `intersection_l_opt_3857.geojson`
- `anchors_wgs84.geojson`
- `intersection_l_opt_wgs84.geojson`
- `anchors.geojson`（兼容）
- `intersection_l_opt.geojson`（兼容）
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

## 6. 配置模板
见：`modules/t04_rc_sw_anchor/t04_config_template_global_focus.json`
