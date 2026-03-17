# T04 约束

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：`AGENTS.md`、`INTERFACE_CONTRACT.md`、`README.md`

## 硬约束

- 输入在计算前统一规范到 `dst_crs`（默认 `EPSG:3857`）。
- 必须坚持 DriveZone-first 行为。
- Stop 逻辑是 hard-stop + fail-closed。
- 不允许通过跨路口漂移去“造答案”。
- 输出路径固定在 `outputs/_work/t04_rc_sw_anchor/<run_id>/`。

## 文档约束

- 当前稳定规则分散在多个文档中。
- Round 1 不重写模块 contract，也不修改实现。

## 后续观察点

- 后续模块深迁移时，需要继续收口“哪些规则留在 contract，哪些迁入架构叙事”这一问题。
