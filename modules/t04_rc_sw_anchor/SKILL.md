# t04_rc_sw_anchor - SKILL

## 1. 类型与种子
- 仅 merge/diverge 生效：
  - diverge: `Kind & bit4`
  - merge: `Kind & bit3`
- `bit3+bit4` -> `AMBIGUOUS_KIND`
- 其它 -> `UNSUPPORTED_KIND`

## 2. 扫描规则
- 初始横截线：垂直道路切向，半长 `cross_half_len_m`
- diverge：沿 entering road 正向扫描
- merge：沿 exiting road 反向扫描
- stop：`min(next_intersection_dist, scan_max_limit_m)`

## 3. 触发优先级
1) `divstrip+pc`
2) `pc_only`
3) `divstrip_only_degraded`
4) fail + `NO_TRIGGER_BEFORE_NEXT_INTERSECTION`

## 4. 点云与轨迹抑制
- 非地面触发仅 `class==1`
- 忽略 `class==12`
- `traj_buffer_m` 内 `class==1` 默认抑制

## 5. CRS
- 输入统一投影到 `dst_crs`（默认 `EPSG:3857`）后计算
- `src_crs` 支持 `auto|显式EPSG`

## 6. 输出
- `anchors.geojson`
- `intersection_l_opt.geojson`
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`
