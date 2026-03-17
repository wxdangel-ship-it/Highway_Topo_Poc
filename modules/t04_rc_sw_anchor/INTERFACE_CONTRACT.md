# t04_rc_sw_anchor - INTERFACE_CONTRACT

## 定位

- 本文件是 T04 的稳定契约面。
- 高层模块目标、上下文、构件关系与风险说明以 `architecture/*` 为准。
- `README.md` 与脚本说明只承担操作者入口职责，不替代长期源事实。

## 1. 目标与范围

- 模块 ID：`t04_rc_sw_anchor`
- 目标：识别 merge / diverge 与 K16 相关节点的锚点位置，并输出 `intersection_l_opt` 相关结果。
- 范围：
  - `kind bit3/bit4` 走既有 merge / diverge 主流程
  - `kind bit16(65536)` 走 K16 专用横截线流程
  - 其他类型不在当前正式范围内，应失败并记录断点

## 2. 模式与输入

支持模式：

- `mode=global_focus`
- `mode=patch`

### 2.1 `global_focus` 输入

必选：

- `patch_dir`
- `global_node_path`
- `global_road_path`
- `focus_node_ids`

可选：

- `divstrip_path`
- `drivezone_path`
- `pointcloud_path`
- `traj_glob`

### 2.2 `patch` 输入

- `patch_dir` 必填
- 允许从 patch 下解析 node / road / divstrip / drivezone / traj / pointcloud 路径（存在即加载）

### 2.3 `focus_node_ids` 来源优先级

- `--focus_node_ids`
- `--focus_node_ids_file`
- `config_json.focus_node_ids`

优先级：`CLI > config_json`

### 2.4 patch 自动发现入口

- 入口脚本：`scripts/run_t04_patch_auto_nodes.sh`
- 作用：从 patch 节点图层自动发现 node，再复用既有主链路
- 约束：该入口只改变“节点来源与执行入口”，不改变 T04 核心算法链路

## 3. 字段与 CRS 契约

### 3.1 字段归一化

- 所有 properties 访问必须走归一化层。
- `kind` 读取基于归一化字段。
- canonical 节点 ID 读取以 `mainid/mainnodeid/id/nodeid` 等候选字段归一化后统一处理。

### 3.2 CRS 契约

- 所有输入层统一重投影到 `dst_crs`（默认 `EPSG:3857`）再参与计算：
  - `node`
  - `road`
  - `divstrip`
  - `drivezone`
  - `traj`
  - `pointcloud`
- 自动检测失败时：
  - `DriveZone` 视为 hard fail
  - `PointCloud` 视为 soft fail，不得伪装成可用主证据
- summary 中应能看到每层的 CRS 检测与使用结果

## 4. 稳定业务规则族

### 4.1 DriveZone-first

- 主触发基于 `SEG(s) ∩ DriveZone` 的片段数变化。
- divstrip 可作为近邻强参考，但不得驱动远距离漂移。
- stop 范围内找不到 split 时，直接 fail-closed。

### 4.2 Between-Branches

- 每个扫描步在分支几何之间构造 `SEG(s)`。
- DriveZone 判定与输出都以当前扫描段及其稳定重建结果为基础。
- 多分支场景下允许扩展为 span 与多事件提取，但不改变 DriveZone-first 的主证据链。

### 4.3 stop 与状态机

- stop 只允许基于拓扑联通可达且 `degree>=3` 的节点。
- 找不到合格 stop 时，按 `scan_max_limit_m` 上界 fail-closed。
- fail 状态不允许被后续 `suspect` 或其他状态覆盖。

### 4.4 复杂规则族

- continuous chain：处理连续分合流节点链的顺序与合并边界。
- reverse tip：处理默认方向证据不足或近节点异常命中的反向搜索。
- multibranch：处理 `N>2` 的 split event 提取与主结果选择。
- K16：处理 `kind bit16=65536` 的独立扫描与输出规则。

## 5. 入口与参数类别

### 5.1 CLI 入口

```bash
python -m highway_topo_poc.modules.t04_rc_sw_anchor --help
```

### 5.2 关键参数类别

- 运行模式与路径：`mode`、`patch_dir`、`out_root`、`run_id`
- 全局输入：`global_node_path`、`global_road_path`
- patch 局部输入：`divstrip_path`、`drivezone_path`、`pointcloud_path`、`traj_glob`
- seed 输入：`focus_node_ids`、`focus_node_ids_file`
- CRS：`src_crs`、`dst_crs`、`*_src_crs`
- DriveZone / divstrip / stop：`min_piece_len_m`、`divstrip_*`、`next_intersection_degree_min`、`disable_geometric_stop_fallback`
- 复杂规则族：`reverse_tip_max_m`、`multibranch_*`、`continuous_*`
- K16：`k16_*`

说明：完整参数清单以 `cli.py` 与 `config.py` 为准；本文件只固化稳定参数类别和长期语义。

## 6. 输出契约

输出目录：

```text
outputs/_work/t04_rc_sw_anchor/<run_id>/
```

必选文件：

- `anchors_3857.geojson`
- `intersection_l_opt_3857.geojson`
- `anchors_wgs84.geojson`
- `intersection_l_opt_wgs84.geojson`
- `anchors.geojson`
- `intersection_l_opt.geojson`
- `intersection_l_multi.geojson`
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

`intersection_l_opt*.geojson` 稳定约定：

- 默认每个有效 node 输出一条连续 `LineString`
- 连续链合并场景允许输出合并后的单条 feature
- properties 应包含稳定标识与关键诊断字段

`anchors.json` 应保留当前复核所需的关键诊断信息，例如：

- `found_split`
- `pieces_count`
- `stop_reason`
- `branch_a_id / branch_b_id / branch_axis_id`
- continuous chain 相关字段
- reverse tip 相关字段
- multibranch 相关字段
- K16 相关字段

## 7. Breakpoints 与质量门禁

当前长期可见的 breakpoint 类别至少包括：

- `DRIVEZONE_SPLIT_NOT_FOUND`
- `DRIVEZONE_CLIP_MULTIPIECE`
- `DRIVEZONE_CRS_UNKNOWN`
- `NEXT_INTERSECTION_NOT_FOUND_DEG3`
- `SEQUENTIAL_ORDER_VIOLATION`
- `K16_ROAD_NOT_UNIQUE`
- `K16_ROAD_DIR_UNSUPPORTED`
- `K16_DRIVEZONE_NOT_REACHED`

质量门禁分为两类：

- Hard：
  - required outputs present
  - `seed_total > 0`
  - `hard_breakpoint_count == 0`
- Soft：
  - `anchor_found_ratio`
  - `no_trigger_count`
  - `scan_exceed_200m_count`

## 8. 验收标准

1. 输出文件完整并落在 `outputs/_work/t04_rc_sw_anchor/<run_id>/` 下。
2. 输入与输出 CRS 处理可追溯，默认结果面向 `EPSG:3857`。
3. DriveZone-first、hard-stop、fail-closed 仍是模块主约束。
4. fail 结果必须能通过 `breakpoints.json`、`anchors.json`、`metrics.json`、`summary.txt` 解释。
5. K16、continuous chain、multibranch、reverse tip 的关键规则结果必须能在诊断中定位。
