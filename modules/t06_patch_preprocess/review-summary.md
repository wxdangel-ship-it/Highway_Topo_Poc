# T06 审核摘要

## 当前模块目标

T06 通过 DriveZone 裁剪和 virtual node 补点，修复缺失道路端点引用的问题，使下游模块能够依赖 endpoint-reference closure。

## 当前输入 / 输出

- 输入：过滤后的 `RCSDNode`、过滤后的 `RCSDRoad` 和 `DriveZone`
- 输出：修复后的 `RCSDNode`、修复后的 `RCSDRoad`，以及位于 `outputs/_work/t06_patch_preprocess/<run_id>/` 下的诊断结果

## 硬约束

- 输出 CRS 必须为 `EPSG:3857`
- virtual node 必须使用 `Kind=65536`
- 输出道路 endpoint ID 必须能在输出 node ID 中闭合
- 修复后的几何必须等于 DriveZone 内部裁剪结果

## 当前混杂问题

- `AGENTS`、`SKILL` 与 contract 同时重复描述模块真相
- 项目级 taxonomy 仍把 T06 描述得更像“新模块 / contract-first”

## 推荐的新文档落位

- 稳定模块真相：`modules/t06_patch_preprocess/architecture/*`
- 契约细节：`modules/t06_patch_preprocess/INTERFACE_CONTRACT.md`
- 持久执行规则：`modules/t06_patch_preprocess/AGENTS.md`
- 可复用流程：`modules/t06_patch_preprocess/SKILL.md`

## 需要人工确认的问题

- Round 2 中，哪些项目级文档应优先更新，以反映 T06 已实现的当前状态？
