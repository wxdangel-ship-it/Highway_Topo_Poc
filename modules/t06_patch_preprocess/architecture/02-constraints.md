# T06 约束

## 状态

- 草案状态：Round 1 最小可信草案，已由 Round 2A 决策对齐补充修正
- 来源依据：`AGENTS.md`、`SKILL.md`、`INTERFACE_CONTRACT.md`

## 硬约束

- 输出 CRS 必须为 `EPSG:3857`
- 只修复 endpoint reference 缺失的道路
- 修复后的几何必须等于 DriveZone 内部裁剪结果
- virtual node 必须使用 `Kind=65536`
- 输出中的道路 endpoint reference 必须能在输出 node ID 中闭合

## 文档约束

- 当前稳定规则重复出现在 `AGENTS`、`SKILL` 与 contract 中
- 后续需要把“已实现模块”的稳定叙事继续收回到源事实文档

## 当前无待确认项

项目级对 T06 的模块成熟度口径已与仓库现实对齐。
