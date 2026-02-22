# t00_synth_data - INTERFACE_CONTRACT (Patch Schema v2)

## 1. 目标与范围
- t00 负责生成可复现的 Patch 目录骨架与 `patch_manifest.json`。
- 本契约仅定义 t00 输出接口，不覆盖下游模块内部处理逻辑。

## 2. Patch 输出目录（Vector 部分）

每个 Patch 目录中的 `Vector/` 必须包含：

```text
Vector/
  LaneBoundary.geojson
  DivStripZone.geojson
  Node.geojson
  intersection_l.geojson
```

约束：
- `gorearea.geojson` 不属于 v2 标准输出，t00 新生成数据中不得出现。
- `Node.geojson` 与 `intersection_l.geojson` 允许 `features` 为空，但文件必须是合法 GeoJSON FeatureCollection。

## 3. GeoJSON 结构约束

### 3.1 `Node.geojson`
- 顶层：`{"type":"FeatureCollection","features":[...]}`
- 几何类型：`Point`
- 每个要素 `properties` 字段约束（有要素时）：
  - `Kind`: `int32`
  - `mainid`: `int64`
  - `id`: `int64`
- `Kind` bit 约定：
  - bit0：无属性
  - bit2：交叉路口
  - bit3：合流路口
  - bit4：分歧路口

### 3.2 `intersection_l.geojson`
- 顶层：`{"type":"FeatureCollection","features":[...]}`
- 几何类型：`LineString`
- 每个要素 `properties` 字段约束（有要素时）：
  - `nodeid`: `int64`（对应主 node 的 id）

### 3.3 `DivStripZone.geojson`
- 顶层：`{"type":"FeatureCollection","features":[...]}`
- 几何类型：由上游数据决定（通常为导流带相关几何），但必须满足合法 GeoJSON FeatureCollection。

## 4. patch_manifest.json 路径字段（t00）

`patches[].paths` 最小字段：
- `pointcloud_laz`
- `vector_lane_boundary`
- `vector_div_strip_zone`
- `vector_node`
- `vector_intersection_l`
- `traj_raw_dat_pose`
