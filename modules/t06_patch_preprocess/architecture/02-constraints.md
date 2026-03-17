# T06 约束

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：`AGENTS.md`、`SKILL.md`、`INTERFACE_CONTRACT.md`

## 硬约束

- 输出 CRS 必须为 `EPSG:3857`
- 只修复 endpoint reference 缺失的道路
- 修复后的几何必须等于 DriveZone 内部裁剪结果
- virtual node 必须使用 `Kind=65536`
- 输出中的道路 endpoint reference 必须能在输出 node ID 中闭合

## 文档约束

- 当前稳定规则重复出现在 AGENTS、SKILL 与 contract 中
- 项目级 taxonomy 仍低估了 T06 的实现成熟度

## 待确认问题

- 哪些验收细节应只留在 contract，哪些适合进入长期架构叙事？
