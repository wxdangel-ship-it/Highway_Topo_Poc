# t04_rc_sw_anchor

## 1. 模块能力
- 识别 merge/diverge 路口锚点（gore tip/nose 近似）
- 产出最终横截线 `intersection_l_opt.geojson`（QGIS 验收关键）
- 支持 `global_focus`：全局 Node/Road + patch 专属 DivStrip/PointCloud/Traj

## 2. 运行入口
```bash
python -m highway_topo_poc.modules.t04_rc_sw_anchor --help
```

## 3. 推荐运行（config_json）
```bash
python -m highway_topo_poc.modules.t04_rc_sw_anchor \
  --config_json modules/t04_rc_sw_anchor/t04_config_template_global_focus.json
```

## 4. 纯 CLI 示例
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
  --src_crs auto \
  --dst_crs EPSG:3857
```

## 5. Focus NodeIDs 三种提供方式
- `--focus_node_ids "id1,id2"`
- `--focus_node_ids_file <txt|json|csv>`
- `--config_json` 中 `focus_node_ids`

优先级：CLI 覆盖 `config_json`。

## 6. 输出目录
`outputs/_work/t04_rc_sw_anchor/<run_id>/`：
- `anchors.geojson`
- `intersection_l_opt.geojson`
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

## 7. 配置模板
见：`modules/t04_rc_sw_anchor/t04_config_template_global_focus.json`
