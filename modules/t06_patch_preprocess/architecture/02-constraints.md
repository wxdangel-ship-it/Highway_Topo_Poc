# T06 约束

## 状态

- 文档状态：Round 2C Phase B 最小正式稿
- 来源依据：
  - `run.py`
  - `pipeline.py`
  - `io.py`
  - `tests/test_t06_patch_preprocess.py`

## 运行硬约束

- 输出 CRS 必须统一为 `EPSG:3857`。
- 只修复“端点引用缺失”的道路；端点本已闭包的道路不应被重新解释为待修复对象。
- 缺失端点的判定基于 `snodeid/enodeid` 是否存在于输入 `Node.id` 集合中。
- DriveZone 必须可解析为非空 polygon / multipolygon；无效几何应 fail-fast。
- 修复后的道路几何必须来自 `Road ∩ DriveZone_clip_geom` 的结果；若裁剪结果为空，该道路必须被删除并记录原因。
- 虚拟节点必须使用 `Kind=65536`，并通过稳定哈希生成不冲突的 `id`。
- 输出道路的 `snodeid/enodeid` 必须在输出 node 集合中闭合。
- 模块不得回写 `data/<PatchID>/` 下的输入文件。

## 稳定参数约束

- `drivezone_clip_buffer_m` 是显式运行参数，当前实现与测试基线默认值为 `5.0` 米。
- 当前正式口径不再接受“固定零缓冲”作为稳定约束；若后续参数策略变化，应同步更新 contract 与质量要求文档。
- `patch`、`run_id`、`out_root` 允许由 CLI 控制，但输出路径仍必须落在 `outputs/_work/t06_patch_preprocess/<run_id>/`。

## 文档约束

- 稳定业务真相必须落在 `architecture/*` 与 `INTERFACE_CONTRACT.md`。
- `AGENTS.md` 只保留工作规则；`SKILL.md` 只保留复用流程。
- 当前没有独立运行验收文档，本轮不伪造新的 runbook 来充当长期源事实。

## 当前无待确认项

本轮已消除“项目级仍把 T06 写成仅骨架模块”的硬冲突，剩余工作只涉及模块文档正式化。
