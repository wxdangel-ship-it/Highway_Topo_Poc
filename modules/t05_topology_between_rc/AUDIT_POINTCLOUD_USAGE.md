# t05 点云使用审计与 DriveZone 替代决策

更新时间：2026-02-28  
审计范围：`src/highway_topo_poc/modules/t05_topology_between_rc/**`

## 1) 审计方法

- A1 静态扫描：`rg` 关键字（`laz/las/point_cloud/class1/class2/non_ground/surface_points_xyz` 等）。
- A2 运行时审计：在点云入口记录是否触发读取、读取点数、用途标签（debug/metrics）。

## 2) A1 静态扫描清单（点云调用点）

| file:line | function | step | 输入 | 用途 | 影响等级 | DriveZone 替代 |
|---|---|---|---|---|---|---|
| `io.py:311` | `load_point_cloud_window` | 输入阶段 | `PointCloud/*.las|*.laz` | ROI + class 过滤读取点云窗口 | P0（下游依赖） | PARTIAL（保留可选后备） |
| `io.py:778` | `_pick_point_cloud_file` | 输入阶段 | `merged_cleaned_classified_3857.laz` 优先 | 选择点云文件 | P1 | YES（默认不用点云） |
| `pipeline.py:659` | `_run_patch_core` | 全流程入口 | 点云路径 | 统一加载 ground/non-ground 点 | P0 | YES（改为 DriveZone 主路径） |
| `pipeline.py:1776` | `_load_surface_points` | Step2/Step3 前 | class2/class1 | 生成 `surface_points_xyz` 与 `non_ground_xy` | P0 | YES（DriveZone 采样替代；点云可选） |
| `geometry.py:4633` | `_estimate_offsets_from_surface` | Step2/Step3 | `surface_points_xyz` | 估计中心线偏移/宽度/覆盖率 | P0 | PARTIAL（改为 DriveZone+轨迹） |
| `geometry.py:5099` | `_estimate_endpoint_center_offset` | Step3 | `surface_points_xyz` | 端点局部偏移估计 | P1 | PARTIAL（DriveZone 近端替代） |
| `geometry.py:4139` | `_build_shape_ref_from_surface_points` | Step1 fallback | `surface_points_xyz` | 无 LB 路径时生成 shape_ref | P0 | PARTIAL（DriveZone 采样可替） |
| `geometry.py:2593` | `_build_xsec_road_for_endpoint` | Step2 核心 | `ground_xy/non_ground_xy` | 生成 `xsec_road_all/selected`；class1 屏障切断 | P0 | YES（DriveZone passable 判据） |
| `geometry.py:2815` | `_split_xsec_by_barrier` | Step2 核心 | `non_ground_xy(class=1)` | 非地面屏障候选 + occupancy 过滤 | P0 | YES（DriveZone 面外即不可行） |
| `step_utils.py:63` | `build_pointcloud_radius_index` | 工具层 | 点云分级点集合 | 半径查询索引（当前主流程未直接调用） | P2 | NO（可保留工具函数） |
| `step_utils.py:97` | `pointcloud_query_radius` | 工具层 | 点云索引 | 半径计数（当前主流程未直接调用） | P2 | NO（可保留工具函数） |

## 3) A2 运行时审计结论（入口日志）

运行时点云入口位于 `pipeline._load_surface_points`。  
审计要求：

- 记录 `pointcloud_attempted`（是否尝试读点云）
- 记录 `pointcloud_enabled`（是否开启点云路径）
- 记录 `pointcloud_selected_point_count` / `pointcloud_non_ground_selected_point_count`
- 记录 `pointcloud_usage_tags`（用于 offset / xsec_barrier / debug）

改造后默认应为：`pointcloud_enabled=0`、`pointcloud_attempted=false`。

## 4) 替代决策矩阵（冻结口径）

### 4.1 决策表

| 逻辑 | 当前依赖 | 决策 | 说明 |
|---|---|---|---|
| Step2 横截可通行与截断 | class1/class2 点云 | YES | 改为 `DriveZone ∩ (not DivStrip)` 主判据 |
| Step2 非地面屏障切断 | class1 + occupancy | YES | DriveZone 面外直接不可行；不再依赖 class1 |
| Step3 端点落线门禁 | xsec_road_selected +局部点云偏移 | PARTIAL | 保留端点门禁，局部偏移改为 DriveZone/轨迹 |
| 中心线 offset/宽度估计 | class2 ground | PARTIAL | DriveZone 采样替代；轨迹趋势兜底 |
| shape_ref fallback（无 LB） | surface points | PARTIAL | DriveZone 采样替代 |
| 点云缓存与统计 | pointcloud cache/metrics | PARTIAL | 默认禁用点云；保留可选后备 |
| 仅 debug 点云统计 | pointcloud_* | NO | 可保留，不影响业务 |

### 4.2 DriveZone 判据（强制）

- `drivezone_union`：`Vector/DriveZone.geojson` 投影到 `EPSG:3857` 后 union/dissolve。
- `passable(p) = (p ∈ drivezone_union) AND (p ∉ divstrip_buffer)`。
- 轨迹冲突规则：若轨迹暗示可行但 `p ∉ drivezone_union`，仍判不可行（DriveZone 优先）。
- `DivStripZone` 仍为硬障碍，不被 DriveZone 取代。

## 5) 风险与护栏

- 风险1：DriveZone 边界毛刺导致横截被过度切断。  
护栏：保留 `shift` 候选 + `fallback_short`，并输出 `xsec_passable_samples_*` debug。

- 风险2：DriveZone 局部漏标导致端点被判不可行。  
护栏：端点硬门禁保留，输出 `endpoint_in_drivezone_src/dst` 指标，便于回归判读。

- 风险3：旧 patch 对点云依赖较强。  
护栏：保留点云可选开关（默认关闭），用于内网应急对比。

