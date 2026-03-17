# T06 方案策略

## 状态

- 文档状态：Round 2C Phase B 最小正式稿
- 来源依据：
  - `run.py`
  - `pipeline.py`
  - `geom.py`
  - `io.py`
  - `report.py`

## 主策略

T06 采用“先识别缺失引用，再做受控裁剪与补点”的确定性策略：

1. **解析输入**
   - 解析 patch 目录、`run_id`、`out_root` 与可选 `drivezone` 覆盖路径。
   - 读取 node / road / drivezone 图层，并做必要的兼容路径解析。
2. **统一投影与规范化**
   - 把所有几何统一到 `EPSG:3857`。
   - 推断 node / road 的关键字段名，保证后续逻辑基于统一字段工作。
3. **识别待修复道路**
   - 基于 `snodeid/enodeid` 是否能在 `Node.id` 集合中闭包，识别缺失端点引用的道路。
4. **构建裁剪几何**
   - 对 DriveZone 做 union，并应用 `drivezone_clip_buffer_m` 形成 clip 几何。
   - 该 buffer 是显式参数，当前默认值为 `5.0` 米。
5. **选择保留线段**
   - 对受影响道路做 `intersection`。
   - 若结果为多段，则优先保留与现有端点连接关系最可信的一段；若无法判定，则按固定降级策略保留最长段并记录原因。
6. **补点与更新引用**
   - 比较裁剪前后端点变化。
   - 对变化端点或原本缺失的端点创建虚拟节点，并更新 `snodeid/enodeid`。
7. **输出与诊断**
   - 写出修复后的 `RCSDNode/RCSDRoad`。
   - 写出 `metrics.json`、`fixed_roads.json`、`t06_summary.json`、`t06_drop_reasons.json` 与运行日志。

## 降级与失败策略

- 无效或空的 DriveZone 几何直接失败，不做静默兜底。
- 裁剪后为空的道路从输出中删除，并在 drop reason 中记录。
- 多段裁剪无法连到既有端点时，允许走固定降级策略，但必须在 `fixed_roads.json` 中留下证据。
- 若最终仍无法形成端点闭包，`metrics.ok` 必须为 `false`。

## 文档策略

- 上述阶段链属于稳定模块真相，应落在 `architecture/*`。
- 参数类别、输出文件和验收标准由 `INTERFACE_CONTRACT.md` 承担。
- `AGENTS.md` 与 `SKILL.md` 只保留面向执行者的规则和流程。
