# t05_topology_between_rc_v2 - AGENTS

## 模块定位
- 这是新的 T05 v2 模块，不是旧 T05 的参数分支。
- 业务主链路必须体现 `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad`。
- 允许复用旧模块的输入加载、CRS 处理、step state、debug/metrics 输出经验。

## 约束
- 不要整体复制旧 `t05_topology_between_rc` 的核心业务逻辑。
- 统一输出到 `EPSG:3857`。
- `DriveZone` 缺失或空面必须硬失败。
- `DivStrip` 是逻辑不可通行硬障碍。
- `LaneBoundary` 缺 CRS 允许修复或跳过，但不能导致硬失败。

## 输出
- 主输出：`Road.geojson`, `metrics.json`, `gate.json`, `summary.txt`
- 关键 debug：`debug/base_xsec_all.geojson`, `debug/segment_candidates.geojson`, `debug/segment_selected.geojson`, `debug/corridor_witness_candidates.geojson`, `debug/corridor_witness_selected.geojson`, `debug/corridor_identity.json`, `debug/slot_src_dst.geojson`, `debug/shape_ref_line.geojson`, `debug/road_final.geojson`, `debug/reason_trace.json`
