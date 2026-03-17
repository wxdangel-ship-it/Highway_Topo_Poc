# T06 现状研究

## 状态

- 当前状态：T06 模块级架构说明
- 来源依据：
  - `src/highway_topo_poc/modules/t06_patch_preprocess/run.py`
  - `src/highway_topo_poc/modules/t06_patch_preprocess/pipeline.py`
  - `src/highway_topo_poc/modules/t06_patch_preprocess/io.py`
  - `src/highway_topo_poc/modules/t06_patch_preprocess/report.py`
  - `tests/test_t06_patch_preprocess.py`
  - 本目录既有 `AGENTS.md`、`SKILL.md`、`INTERFACE_CONTRACT.md`

## 仓库现实

- T06 已具备独立实现、CLI 入口和测试，不再是“仅契约 / 仅目录骨架”模块。
- CLI 入口为 `python -m highway_topo_poc.modules.t06_patch_preprocess.run`，支持 `--data_root`、`--patch`、`--run_id`、`--out_root`、`--drivezone`、`--drivezone_clip_buffer_m` 等参数。
- 运行输出固定落在 `outputs/_work/t06_patch_preprocess/<run_id>/`，至少包含：
  - `Vector/RCSDNode.geojson`
  - `Vector/RCSDRoad.geojson`
  - `report/metrics.json`
  - `report/fixed_roads.json`
  - `report/t06_summary.json`
  - `report/t06_drop_reasons.json`
  - `logs/run.log`

## 当前稳定实现事实

- 输入解析由 `io.py` 负责，默认读取 patch 下的 `Vector/RCSDNode.geojson`、`Vector/RCSDRoad.geojson`、`Vector/DriveZone.geojson`。
- 若 patch 缺少 node / road 图层，运行时允许回退到唯一可判定的 `global/RCSDNode.geojson` 与 `global/RCSDRoad.geojson`，但这属于兼容性输入解析，不改变模块主职责。
- 所有几何统一投影到 `EPSG:3857`；DriveZone 若缺少 CRS，可在 node / road CRS 一致时回退使用同一 CRS。
- 缺失端点识别规则基于 `snodeid/enodeid` 是否出现在 `Node.id` 集合中。
- DriveZone 裁剪存在显式参数 `drivezone_clip_buffer_m`，默认值来自实现与测试证据，为 `5.0` 米，而不是旧文档中的“零缓冲”。
- 裁剪后若结果是多段，只保留与现有端点连接关系最可信的一段；若两端都缺失且无法判定，则按固定降级策略保留最长段并记录原因。
- 虚拟节点由稳定哈希生成，`Kind=65536`，`id` 类型与输入 `Node.id` 类型保持一致。

## 测试覆盖提供的证据

- `test_case1` 证明：输入本身闭包时，不新增虚拟节点。
- `test_case2`、`test_case4` 证明：裁剪后端点变化或两端都缺失时，会新增虚拟节点并更新端点引用。
- `test_case5`、`test_case6`、`test_case7` 证明：DriveZone CRS 缺失或异常时存在受控兼容路径。
- `test_case8` 证明：`drivezone_clip_buffer_m=5.0` 是当前稳定运行基线，并且会在 `metrics.json` 与 `fixed_roads.json` 中记录裁剪外长度。
- `test_case9` 证明：无效 DriveZone 几何会 fail-fast，而不是静默继续。

## 本轮前的文档混杂问题

- `AGENTS.md`、`SKILL.md` 与 `INTERFACE_CONTRACT.md` 同时承载了大段稳定业务真相。
- 旧 contract 与旧规则文档把“零缓冲”写成冻结约束，已与实现和测试漂移。
- 模块缺少一个明确说明“当前正式文档面由哪些文件组成”的治理摘要。

## 当前结论

- T06 可以形成可信的最小正式文档面，无需新建独立 runbook。
- 本轮应把稳定真相收回 `architecture/*` 与 `INTERFACE_CONTRACT.md`，把 `AGENTS.md` 收缩为工作规则，把 `SKILL.md` 收缩为复用流程。
