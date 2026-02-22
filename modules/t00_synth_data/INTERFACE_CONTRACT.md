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
- 旧版导流带文件名不属于 v2 标准输出，t00 新生成数据中不得出现。
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

## 5. 输入（Input）
- `seed`：随机种子（`int`，用于可复现）
- `num_patches`：patch 数量（`int > 0`）
- `source_mode`：`synthetic | local`
- `out_dir`：输出目录（建议写入 `outputs/_work`）
- `lidar_dir/traj_dir`：仅 `source_mode=local` 时需要

## 6. 输出（Output）
- 根输出：`<out_dir>/patch_manifest.json`
- 每个 patch 至少写出：
  - `PointCloud/*.laz`
  - `Vector/LaneBoundary.geojson`
  - `Vector/DivStripZone.geojson`
  - `Vector/Node.geojson`
  - `Vector/intersection_l.geojson`
  - `Traj/<traj_id>/raw_dat_pose.geojson`

## 7. 入口（Entrypoint / CLI）
- `python -m highway_topo_poc synth`

## 8. 参数（Parameters）
- `--out-dir`：输出目录
- `--seed`：随机种子
- `--num-patches`：patch 数量
- `--source-mode`：`auto|local|synthetic`
- `--pointcloud-mode`：`stub|link|copy|merge`
- `--traj-mode`：`synthetic|copy|convert`
- `--lidar-dir/--traj-dir`：本地数据目录（可选）

## 9. 示例（Example）
在 repo root 执行：

```bash
RUN_ID="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="outputs/_work/t00_synth_data/${RUN_ID}"
python -m highway_topo_poc synth \
  --source-mode synthetic \
  --num-patches 1 \
  --seed 0 \
  --out-dir "${OUT_DIR}"
```

## 10. 验收（Accept）
- 命令退出码为 `0`
- `${OUT_DIR}/patch_manifest.json` 存在且可解析
- `${OUT_DIR}/<patch_id>/Vector/` 同时存在 `LaneBoundary.geojson`、`DivStripZone.geojson`、`Node.geojson`、`intersection_l.geojson`
- `modules/t00_synth_data/` 目录仅保留文档契约，无 `.py` 实现文件
