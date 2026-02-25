# t00_synth_data - INTERFACE_CONTRACT (Patch Schema v3)

## 1. 目标与范围
- t00 负责生成可复现的 Patch 目录骨架与 `patch_manifest.json`。
- 本契约仅定义 t00 输出接口，不覆盖下游模块内部处理逻辑。

## 2. Patch 输出目录（Vector 部分）

每个 Patch 目录中的 `Vector/` 必须包含：

```text
Vector/
  LaneBoundary.geojson
  DivStripZone.geojson
  RCSDNode.geojson
  intersection_l.geojson
  RCSDRoad.geojson
Tiles/
  <z>/<x>/<y>.<ext>
```

约束：
- 旧版导流带文件名不属于 v3 标准输出，t00 新生成数据中不得出现。
- `RCSDNode.geojson` 与 `intersection_l.geojson` 允许 `features` 为空，但文件必须是合法 GeoJSON FeatureCollection。
- `RCSDRoad.geojson` 允许 `features` 为空，但文件必须是合法 GeoJSON FeatureCollection。
- `Tiles/` 当前阶段可为空目录，但目录必须存在。

## 3. GeoJSON 结构约束

### 3.1 `RCSDNode.geojson`
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

### 3.4 `RCSDRoad.geojson`
- 顶层：`{"type":"FeatureCollection","features":[...]}`
- 几何类型：`LineString`（建议）
- 每个要素 `properties` 字段约束（有要素时）：
  - `direction`: `int8`
    - `0`：未调查（默认按双方向处理）
    - `1`：双向
    - `2`：顺行
    - `3`：逆行
  - `snodeid`: `int64`
  - `enodeid`: `int64`

### 3.5 `Tiles/`
- 目录结构：`Tiles/<z>/<x>/<y>.<ext>`
- 推荐后缀：`png/jpg/webp`；实现需兼容常见瓦片后缀。
- 当前阶段允许无瓦片文件，但 `Tiles/` 目录必须存在。

## 4.1 来源策略（Road/Tiles）
- `Vector/RCSDRoad.geojson`：
  - 若源 patch 或源数据存在 `RCSDRoad.geojson`，优先复制到目标 patch。
  - 若缺失，生成空 `FeatureCollection`（必要时继承现有输入 `crs`）。
- `Tiles/`：
  - 默认策略：创建空目录（`mkdir_empty`）。
  - 可选策略：仅在源存在 `Tiles/` 时复制（`copy_if_exists`）。
- 不得修改其它既有矢量内容（`LaneBoundary/DivStripZone/RCSDNode/intersection_l`）。

## 5. patch_manifest.json 路径字段（t00）

`patches[].paths` 最小字段：
- `pointcloud_laz`
- `vector_lane_boundary`
- `vector_div_strip_zone`
- `vector_node`
- `vector_intersection_l`
- `vector_road`
- `tiles_dir`
- `traj_raw_dat_pose`

## 6. 输入（Input）
- `seed`：随机种子（`int`，用于可复现）
- `num_patches`：patch 数量（`int > 0`）
- `source_mode`：`synthetic | local`
- `out_dir`：输出目录（建议写入 `outputs/_work`）
- `lidar_dir/traj_dir`：仅 `source_mode=local` 时需要

## 7. 输出（Output）
- 根输出：`<out_dir>/patch_manifest.json`
- 每个 patch 至少写出：
  - `PointCloud/*.laz`
  - `Vector/LaneBoundary.geojson`
  - `Vector/DivStripZone.geojson`
  - `Vector/RCSDNode.geojson`
  - `Vector/intersection_l.geojson`
  - `Vector/RCSDRoad.geojson`
  - `Tiles/`（可空）
  - `Traj/<traj_id>/raw_dat_pose.geojson`

## 8. 入口（Entrypoint / CLI）
- `python -m highway_topo_poc synth`

## 9. 参数（Parameters）
- `--out-dir`：输出目录
- `--seed`：随机种子
- `--num-patches`：patch 数量
- `--source-mode`：`auto|local|synthetic`
- `--pointcloud-mode`：`stub|link|copy|merge`
- `--traj-mode`：`synthetic|copy|convert`
- `--tiles-mode`：`mkdir_empty|copy_if_exists`
- `--lidar-dir/--traj-dir`：本地数据目录（可选）

## 10. 示例（Example）
在 repo root 执行：

```bash
RUN_ID="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="outputs/_work/t00_synth_data/${RUN_ID}"
python -m highway_topo_poc synth \
  --source-mode synthetic \
  --num-patches 1 \
  --seed 0 \
  --tiles-mode mkdir_empty \
  --out-dir "${OUT_DIR}"
```

说明：示例输出必须写入 `outputs/_work`，不要覆盖 `data/synth_local`。

## 11. 验收（Accept）
- 命令退出码为 `0`
- `${OUT_DIR}/patch_manifest.json` 存在且可解析
- `${OUT_DIR}/<patch_id>/Vector/` 同时存在 `LaneBoundary.geojson`、`DivStripZone.geojson`、`RCSDNode.geojson`、`intersection_l.geojson`、`RCSDRoad.geojson`
- `${OUT_DIR}/<patch_id>/Tiles/` 目录存在（允许为空）
- `modules/t00_synth_data/` 目录仅保留文档契约，无 `.py` 实现文件
