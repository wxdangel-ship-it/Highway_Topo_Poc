# t04_rc_sw_anchor - AGENTS

## 职责
- 处理 merge/diverge 路口锚点与最终横截线。
- 支持 `global_focus`（全局 Node/Road + patch 级 DivStrip/PointCloud/Traj）。

## 代码与文档边界
- 文档契约：`modules/t04_rc_sw_anchor/`
- 实现代码：`src/highway_topo_poc/modules/t04_rc_sw_anchor/`
- 测试：`tests/t04_rc_sw_anchor/`
- 不修改其它模块 `INTERFACE_CONTRACT.md`

## 输入口径
- `patch_id` 仅来自 `patch_dir` basename
- `focus_node_ids` 仅来自 CLI/file/config（禁止代码写死）
- `global_focus` 下必须提供 `global_node_path` 与 `global_road_path`

## 输出口径
固定目录：`outputs/_work/t04_rc_sw_anchor/<run_id>/`
- `anchors.geojson`
- `intersection_l_opt.geojson`
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

## 禁止事项
- 不在 stdout 输出长坐标数组或大 GeoJSON
- 不回写 `data/` 原始目录
- 不在 `outputs/` 下开发或执行 git
