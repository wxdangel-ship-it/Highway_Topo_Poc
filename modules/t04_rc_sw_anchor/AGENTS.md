# t04_rc_sw_anchor - AGENTS

## 职责
- 处理 merge/diverge 锚点与最终横截线。
- 采用 `DriveZone-first + Between-Branches(B)`。
- stop 规则：仅联通可达且 `degree>=3` 的 hard stop。
- CRS 全链路归一化到 `dst_crs`（默认 `EPSG:3857`）。

## 代码与文档边界
- 文档契约：`modules/t04_rc_sw_anchor/`
- 实现代码：`src/highway_topo_poc/modules/t04_rc_sw_anchor/`
- 测试：`tests/t04_rc_sw_anchor/`
- 不修改其它模块 `INTERFACE_CONTRACT.md`

## 输入口径
- `patch_id` 仅来自 `patch_dir` basename。
- `focus_node_ids` 仅来自 CLI/file/config。
- `global_focus` 下必须提供 `global_node_path` 与 `global_road_path`。
- `DriveZone` 默认启用：`Vector/DriveZone.geojson`（主证据）。
- 输入图层均需走 `*_src_crs + auto` 归一化。

## 输出口径
固定目录：`outputs/_work/t04_rc_sw_anchor/<run_id>/`
- `anchors_3857.geojson`
- `intersection_l_opt_3857.geojson`
- `anchors_wgs84.geojson`
- `intersection_l_opt_wgs84.geojson`
- `anchors.geojson` / `intersection_l_opt.geojson`（兼容）
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

`intersection_l_opt` 约定：
- 单 node 输出两条 LineString（`piece_idx=0/1`）。
- feature properties 必含 `nodeid/kind/kind_bits/anchor_type/scan_dist_m/stop_reason/evidence_source`。

## 禁止事项
- 不依赖远处 divstrip 触发答案；无 split 宁可 fail。
- 不允许跨路口漂移补答案。
- 不允许 fail 状态被后续 suspect 覆盖。
- 不在 stdout 输出长坐标数组或大 GeoJSON。
- 不回写 `data/` 原始目录。
- 不改其它模块契约。
