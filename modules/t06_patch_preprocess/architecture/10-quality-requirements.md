# T06 质量要求

## 状态

- 文档状态：Round 2C Phase B 最小正式稿
- 来源依据：
  - `pipeline.py`
  - `report.py`
  - `tests/test_t06_patch_preprocess.py`

## 核心质量目标

- **闭包正确**：输出道路的 `snodeid/enodeid` 必须全部能解析到输出 `Node.id`。
- **几何可追溯**：修复后的道路几何必须可追溯到 DriveZone 裁剪结果。
- **结果确定性**：相同输入与相同参数下，虚拟节点生成规则应稳定复现。
- **失败可解释**：删除道路、降级选段、CRS 兼容路径和异常几何都要留下可审计证据。

## 最小验收要求

- 输出 `RCSDNode.geojson` 与 `RCSDRoad.geojson` 的 CRS 必须为 `EPSG:3857`。
- `metrics.json` 中的 `ok` 必须与“输出端点是否闭包”一致。
- `metrics.json` 必须至少记录：
  - `missing_endpoint_road_count`
  - `clipped_road_count`
  - `new_virtual_node_count`
  - `updated_snodeid_count`
  - `updated_enodeid_count`
  - `drivezone_clip_buffer_m`
  - `target_epsg`
  - `ok`
- `fixed_roads.json` 应为被修复道路提供足够的解释证据，包括：
  - 选段原因
  - 端点是否更新
  - 裁剪外长度或比例

## 失败可解释性要求

- DriveZone 无效或为空时，应 fail-fast，而不是输出模糊结果。
- 裁剪后为空的道路必须留下 drop reason。
- 多段选段的降级策略必须可见，不允许静默“猜一个结果”。
- 若输入数据依赖兼容性 fallback，应在 summary / source notes 中可追踪。

## 本轮结论

- T06 当前已具备最小正式验收面，不需要额外新增独立运行验收文档。
- 更细的 operator checklist 若未来需要，应作为操作者材料补充，而不是回流为长期源事实。
