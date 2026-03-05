# SKILL — t06_patch_preprocess（缺失端点修复 + DriveZone 打断）

## 1) What / Why
在已筛选后的 Patch 数据中，RCSDRoad 可能引用了不存在于 RCSDNode 的端点（snodeid/enodeid 缺失）。
t06 通过 DriveZone(union) 对这些 Road 做面内裁剪打断，并在打断点补充“Patch 间虚拟打断 Node”（Kind=65536），从而保证下游模块读取时端点引用闭包成立。

## 2) Inputs（冻结）
- Vector/RCSDNode.geojson（Point）
  - properties: Kind(int32 bit flags), mainid(int64), id（类型以输入为准）
- Vector/RCSDRoad.geojson（LineString/MultiLineString）
  - properties: direction(int8 0/1/2/3), snodeid(与Node.id同类型), enodeid(与Node.id同类型)
- DriveZone（Polygon/MultiPolygon）
  - 路径由参数给定（参考 t04 入参方式）

## 3) Outputs（冻结，统一 EPSG:3857）
- Vector/RCSDNode.geojson
  - 完整复制原 Node，并新增虚拟 Node（Kind=65536）
- Vector/RCSDRoad.geojson
  - 完整复制原 Road；对“端点引用缺失”的 Road：
    - 用 DriveZone union 裁剪，仅保留面内段
    - 多段结果只保留“连接到已存在端点 Node”的那一段
    - 按几何判断更新 snodeid/enodeid
    - 若面内为空则删除该 Road
- report/metrics.json（必须）
- report/fixed_roads.json（建议）

## 4) Core Steps（冻结）
1. 读取 RCSDNode/RCSDRoad/DriveZone，统一投影到 EPSG:3857
2. 找出端点引用缺失的 Road（按 id 引用缺失）
3. 对这些 Road 做 Road ∩ DriveZone_union，仅保留面内部分
4. 若 intersection 为多段，仅保留“连接到已存在端点 Node”的那一段（无法判定时按固定降级策略处理并记录）
5. 在打断点新增虚拟 Node（Kind=65536；id=hash 且不冲突，类型与输入一致）
6. 按几何判断：哪一端被裁剪改变了，就改该端 snodeid/enodeid
7. 输出（EPSG:3857）+ metrics

## 5) Gates（冻结）
- CRS=EPSG:3857
- 引用闭包：所有输出 Road 的 snodeid/enodeid 都存在于输出 Node.id
- 虚拟 Node：Kind=65536 且 id 稳定不冲突
- 被修复 Road：几何为 DriveZone 面内裁剪结果；面内为空则 Road 删除

## 6) Non-Goals
- 不做 Patch 筛选、不做缓冲、不拆 Road、多段只取一段
