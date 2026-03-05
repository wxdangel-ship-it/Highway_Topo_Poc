# INTERFACE_CONTRACT — t06_patch_preprocess

## 1) Inputs
### MUST
- Vector/RCSDNode.geojson
  - Geometry: Point
  - Properties:
    - Kind (int32 bit flags)
    - mainid (int64)
    - id (类型以输入为准：常见为 int64；也可能为 string。t06 必须保持该 JSON 类型一致)
- Vector/RCSDRoad.geojson
  - Geometry: LineString or MultiLineString
  - Properties:
    - direction (int8; 0/1/2/3)
    - snodeid (类型与 Node.id 一致)
    - enodeid (类型与 Node.id 一致)
  - 其它属性：t06 透传复制，不做语义修改
- DriveZone（路径由参数提供；参考 t04 入参方式）
  - Geometry: Polygon/MultiPolygon

### SHOULD / OPTIONAL
- 无（冻结版）

### Assumptions（冻结）
- 输入的 RCSDNode/RCSDRoad 已是筛选后的成果；t06 不做 Patch 级筛选。
- 缺失端点判定按“id 引用缺失”：snodeid/enodeid 不在 Node.id 集合内。

## 2) Outputs
### MUST（统一 EPSG:3857）
- outputs/_work/t06_patch_preprocess/<run_id>/Vector/RCSDNode.geojson
  - 完整复制输入 Node
  - 新增虚拟 Node：
    - Kind = 65536（bit16 = 1<<16）
    - id：哈希生成且与既有 Node.id 不冲突；JSON 类型与输入 Node.id 保持一致
    - mainid：实现侧可固定为 -1（不影响验收）；也可保留为空但建议写 -1
- outputs/_work/t06_patch_preprocess/<run_id>/Vector/RCSDRoad.geojson
  - 完整复制输入 Road
  - 仅对“端点引用缺失”的 Road 做修复：
    - geometry = Road ∩ DriveZone_union（仅保留面内部分）
    - 多段结果：只保留“连接到已存在端点 Node”的那一段
    - 端点更新：按几何判断，哪一端被裁剪改变了，就改该端 snodeid/enodeid 指向新虚拟 Node
    - 若 intersection 为空，该 Road 必须从输出中删除
- outputs/_work/t06_patch_preprocess/<run_id>/report/metrics.json
  - 最小字段集合（必须）：
    - node_in_count, road_in_count
    - missing_endpoint_road_count
    - clipped_road_count
    - dropped_road_empty_count
    - new_virtual_node_count
    - updated_snodeid_count, updated_enodeid_count
    - output_node_count, output_road_count
    - target_epsg: 3857
    - ok: true/false

### SHOULD（建议，增强可解释性）
- outputs/_work/t06_patch_preprocess/<run_id>/report/fixed_roads.json
  - 记录被修复 Road 的标识/索引、裁剪前后端点变化、新增 Node.id、降级策略触发情况等

### MUST NOT
- 不得回写 data/<PatchID>/ 下任何文件

## 3) EntryPoints
> 本阶段仅冻结契约；实现入口会在“正式启动模块开发任务书”中下达并与仓库统一 CLI 规范对齐。

建议入口（占位）：
- python -m highway_topo_poc.modules.t06_patch_preprocess.run \
    --data_root <PATCH_DIR> \
    --patch <PatchID|auto> \
    --drivezone <PATH> \
    --run_id <RUN_ID> \
    --out_root <OUT_ROOT>

## 4) Params
### MUST
- drivezone: str
  - DriveZone 输入路径（可为 Patch 内路径或外部路径）

### FIXED（冻结）
- target_epsg = 3857
- margin_m = 0
- missing_endpoint_detect_mode = "by_id_membership"
- clip_mode = "intersection_keep_inside"
- keep_segment_mode = "connect_existing_endpoint"
- virtual_node_kind = 65536

### OPTIONAL（实现侧可提供；若实现了必须写入 metrics 或 fixed_roads.json）
- endpoint_match_tol_m: float = 1.0
  - 多段选择时，用于判定线段端点是否“连接到已存在端点 Node”的距离阈值（米）
- hash_round_m: float = 0.01
  - 哈希前对虚拟 Node 坐标做四舍五入（米），提升跨次运行稳定性
- hash_salt_max_tries: int = 8
  - 哈希冲突时追加 salt 重试的最大次数

### Hash ID 规则（冻结）
- 对每个虚拟 Node（位于裁剪后线段端点），构造 key：
  - key = f"{patch_id}|{round(x,hash_round_m)}|{round(y,hash_round_m)}|{virtual_node_kind}|salt"
- 取确定性 hash64(key) 映射到可表达范围：
  - 若 Node.id 为整数类型：输出 id 为 int（建议取 abs(hash64) 并保留 int64 范围）
  - 若 Node.id 为 string 类型：输出 id 为字符串（建议以十六进制或十进制字符串表示）
- 若与既有 Node.id 冲突则 salt++ 重试，直到不冲突或超过 max_tries（超过则 fail 并 ok=false）。

## 5) Examples
假设：
- PATCH_DIR = data/patches/2855xxxxxx
- RUN_ID = 20260305_090000_t06_2855xxxxxx
- OUT_ROOT = outputs/_work/t06_patch_preprocess

输出：
- outputs/_work/t06_patch_preprocess/20260305_090000_t06_2855xxxxxx/Vector/RCSDNode.geojson
- outputs/_work/t06_patch_preprocess/20260305_090000_t06_2855xxxxxx/Vector/RCSDRoad.geojson
- outputs/_work/t06_patch_preprocess/20260305_090000_t06_2855xxxxxx/report/metrics.json
- （可选）outputs/_work/t06_patch_preprocess/20260305_090000_t06_2855xxxxxx/report/fixed_roads.json

## 6) Acceptance（冻结）
1. 输出文件存在且仅落在 outputs/_work/t06_patch_preprocess/<run_id>/...
2. 输出 CRS 必为 EPSG:3857（Node/Road 几何均在 3857）
3. 虚拟 Node：
   - Kind 必为 65536
   - id 不与既有 Node.id 冲突
   - id 生成规则稳定：相同输入与参数多次运行产生相同 id（hash_round_m 后必须一致）
4. 引用闭包：
   - 输出 RCSDRoad 中每条 Road 的 snodeid 与 enodeid 都必须在输出 RCSDNode.id 中可找到
5. 面内裁剪规则：
   - 被修复的 Road（缺失端点引用的 Road）在输出中其 geometry 必为 DriveZone_union 面内部分（intersection 结果）
   - 若 intersection 为空，该 Road 必须被删除
6. 多段策略：
   - 若 intersection 为多段，仅允许保留“连接到已存在端点 Node”的那一段（由 endpoint_match_tol_m 判定）
   - 若无法判定，必须触发固定降级策略（默认：取最长段），并在 fixed_roads.json 或 metrics 中记录该事件
