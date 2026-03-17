# T06 引言与目标

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：`AGENTS.md`、`SKILL.md`、`INTERFACE_CONTRACT.md`

## 模块目标

T06 负责修复 patch 级道路数据中缺失 endpoint reference 的问题：对受影响的道路做 DriveZone 裁剪，在必要时创建 virtual node，并重新建立下游处理所需的 endpoint-reference closure。

## 审核重点

- 确认这段描述是否应在后续文档清理中保留为稳定模块定义
