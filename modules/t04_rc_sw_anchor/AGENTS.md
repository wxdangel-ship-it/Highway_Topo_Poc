# t04_rc_sw_anchor - AGENTS

## 模块目标
- 识别并优化 RC/SW 场景分歧/合流路口锚点。
- 以 `intersection_l` 为横截面载体，生成可视化与可回传证据产物。

## 职责边界
- 仅处理 `merge/diverge`；`cross/其它`类型不输出锚点，仅记录断点。
- 不修改其它模块实现与任何 `modules/<id>/INTERFACE_CONTRACT.md`。
- 实现代码只放 `src/highway_topo_poc/modules/t04_rc_sw_anchor/`。
- 文档契约只放 `modules/t04_rc_sw_anchor/`。

## 输入
- MUST：`Vector/Node.geojson`、`Vector/intersection_l.geojson`、`Vector/Road.geojson`
- SHOULD：`Vector/DivStripZone.geojson`、`PointCloud/merged.laz|merged.las`
- OPTIONAL：`Tiles/`（忽略）、`Traj/`（不使用）

## 输出
固定写入：
- `outputs/_work/t04_rc_sw_anchor/<run_id>/anchors.geojson`
- `outputs/_work/t04_rc_sw_anchor/<run_id>/anchors.json`
- `outputs/_work/t04_rc_sw_anchor/<run_id>/metrics.json`
- `outputs/_work/t04_rc_sw_anchor/<run_id>/breakpoints.json`
- `outputs/_work/t04_rc_sw_anchor/<run_id>/summary.txt`

建议附加：
- `outputs/_work/t04_rc_sw_anchor/<run_id>/intersection_l_opt.geojson`
- `outputs/_work/t04_rc_sw_anchor/<run_id>/chosen_config.json`

## 禁止事项
- 不在 `data/synth_local`、`data/synth` 原始数据目录写入覆盖。
- 不在 `outputs/` 下开发、运行 git、或放置源代码。
- 不输出超长 raw 坐标/GeoJSON 到 stdout。
