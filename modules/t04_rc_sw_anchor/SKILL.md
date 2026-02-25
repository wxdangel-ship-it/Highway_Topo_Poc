# t04_rc_sw_anchor - SKILL

## 1. Seed 与 Kind
- 仅 merge/diverge：
  - `diverge = (kind & 16) != 0`
  - `merge   = (kind & 8)  != 0`
- `kind` 字段读取必须经字段归一化层（支持 `Kind/kind/...`）

## 2. CRS 归一化
- 所有几何在 `dst_crs`（默认 `EPSG:3857`）中计算
- 分层 `*_src_crs` 支持 `auto|EPSG:4326|EPSG:3857`
- auto 顺序：CLI hint > GeoJSON.crs > bbox guess
- 无法识别写 `CRS_UNKNOWN`

## 3. 扫描与触发（DivStrip 优先）
1) `divstrip+pc`
2) `pc_only_no_divstrip_hit`（DivStrip 存在但未命中，`suspect`）
3) `pc_only_after_divstrip_miss`
4) `pc_only`（DivStrip 缺失）
5) `divstrip_only_degraded`（点云不可用）

门槛：
- `pc_only_min_scan_dist_m`
- `pc_only_after_divstrip_min_m`

## 4. 点云与轨迹抑制
- 非地面触发：`class==1`
- 忽略：`class==12`
- 轨迹抑制：`traj_buffer_m` 内候选点不触发

## 5. 输出
- `anchors_3857.geojson / intersection_l_opt_3857.geojson`
- `anchors_wgs84.geojson / intersection_l_opt_wgs84.geojson`
- 兼容名：`anchors.geojson / intersection_l_opt.geojson`
- 诊断：`anchors.json / metrics.json / breakpoints.json / summary.txt / chosen_config.json`
