# t06_patch_preprocess - INTERFACE_CONTRACT

## 定位

- 本文件是 T06 的稳定契约面。
- 高层模块目标、上下游边界、构件关系与风险说明以 `architecture/*` 为准。
- `AGENTS.md` 与 `SKILL.md` 不替代长期源事实。

## 1. Inputs

### 1.1 MUST

- `Vector/RCSDNode.geojson`
  - Geometry：`Point`
  - 关键属性：
    - `id`
    - `Kind` 或兼容别名
    - `mainid` 或兼容别名
- `Vector/RCSDRoad.geojson`
  - Geometry：`LineString` 或 `MultiLineString`
  - 关键属性：
    - `snodeid`
    - `enodeid`
    - `direction`
  - 其他属性默认透传，不做语义改写
- `DriveZone`
  - Geometry：`Polygon` / `MultiPolygon`
  - 默认读取 patch 下 `Vector/DriveZone.geojson`
  - 允许通过 `--drivezone` 覆盖路径

### 1.2 兼容性输入行为

- 若 patch 目录缺少 `RCSDNode.geojson` 或 `RCSDRoad.geojson`，运行时允许回退到唯一可判定的 `global/RCSDNode.geojson` 与 `global/RCSDRoad.geojson`。
- 若 DriveZone 缺少 CRS，且 node / road CRS 一致，允许回退使用该 CRS；否则必须失败。

### 1.3 稳定前提

- 输入 node / road 应已是 patch 级结果；T06 不负责更上游的 patch 过滤。
- 缺失端点道路的识别规则固定为“`snodeid/enodeid` 不在 `Node.id` 集合中”。

## 2. Outputs

输出目录：

```text
outputs/_work/t06_patch_preprocess/<run_id>/
```

### 2.1 MUST

- `Vector/RCSDNode.geojson`
  - 包含输入 node 的复制结果
  - 包含新建虚拟节点：
    - `Kind=65536`
    - `id` 与既有 `Node.id` 不冲突
    - `id` 的 JSON 类型与输入 `Node.id` 类型一致
- `Vector/RCSDRoad.geojson`
  - 包含未受影响道路的复制结果
  - 对缺失端点道路执行裁剪和端点修复
- `report/metrics.json`
  - 至少包含：
    - `node_in_count`
    - `road_in_count`
    - `missing_endpoint_road_count`
    - `clipped_road_count`
    - `dropped_road_empty_count`
    - `new_virtual_node_count`
    - `updated_snodeid_count`
    - `updated_enodeid_count`
    - `output_node_count`
    - `output_road_count`
    - `drivezone_clip_buffer_m`
    - `target_epsg`
    - `ok`
- `report/t06_summary.json`
- `report/t06_drop_reasons.json`
- `logs/run.log`

### 2.2 SHOULD

- `report/fixed_roads.json`
  - 记录被修复道路的选段原因、端点变化、裁剪外长度或比例、降级策略等解释性信息

### 2.3 MUST NOT

- 不得回写 `data/<PatchID>/` 下的输入文件。

## 3. EntryPoints

CLI 入口：

```bash
python -m highway_topo_poc.modules.t06_patch_preprocess.run \
  --data_root <PATCH_DIR_OR_ROOT> \
  --patch <PatchID|auto> \
  --run_id <RUN_ID|auto> \
  --out_root <OUT_ROOT> \
  --drivezone <PATH> \
  --drivezone_clip_buffer_m <BUFFER_M>
```

## 4. Params

### 4.1 MUST

- `data_root`
- `patch`
- `run_id`
- `out_root`
- `overwrite`
- `drivezone`
- `drivezone_clip_buffer_m`

### 4.2 稳定参数语义

- `target_epsg = 3857`
- `missing_endpoint_detect_mode = "by_id_membership"`
- `clip_mode = "intersection_keep_inside"`
- `keep_segment_mode = "connect_existing_endpoint"`
- `virtual_node_kind = 65536`
- `drivezone_clip_buffer_m`：当前默认值为 `5.0` 米

### 4.3 说明

- `drivezone_clip_buffer_m` 是显式参数，不再采用“固定零缓冲”的旧口径。
- 虚拟节点 ID 由稳定哈希生成；整数型与字符串型输入 `Node.id` 都必须保持类型一致。

## 5. Examples

示例命令：

```bash
python -m highway_topo_poc.modules.t06_patch_preprocess.run \
  --data_root data/patches \
  --patch 2855xxxxxx \
  --run_id 20260317_t06_patch \
  --out_root outputs/_work/t06_patch_preprocess \
  --drivezone_clip_buffer_m 5.0
```

示例输出：

- `outputs/_work/t06_patch_preprocess/20260317_t06_patch/Vector/RCSDNode.geojson`
- `outputs/_work/t06_patch_preprocess/20260317_t06_patch/Vector/RCSDRoad.geojson`
- `outputs/_work/t06_patch_preprocess/20260317_t06_patch/report/metrics.json`
- `outputs/_work/t06_patch_preprocess/20260317_t06_patch/report/fixed_roads.json`

## 6. Acceptance

1. 输出文件存在，且仅落在 `outputs/_work/t06_patch_preprocess/<run_id>/` 下。
2. 输出 `RCSDNode` 与 `RCSDRoad` 的 CRS 必须为 `EPSG:3857`。
3. 所有输出道路的 `snodeid/enodeid` 都必须能在输出 `Node.id` 中找到。
4. 新建虚拟节点必须满足：
   - `Kind=65536`
   - `id` 不与既有 `Node.id` 冲突
   - `id` 类型与输入 `Node.id` 类型一致
5. 被修复道路的几何必须来自 DriveZone 裁剪结果；裁剪后为空的道路必须删除并记录原因。
6. 当裁剪结果为多段且无法按既有端点稳定判定时，允许走固定降级策略，但必须在 `fixed_roads.json` 或 summary 中留下解释性记录。
7. `metrics.json` 中必须能看出本次运行使用的 `drivezone_clip_buffer_m` 和最终 `ok` 结果。
