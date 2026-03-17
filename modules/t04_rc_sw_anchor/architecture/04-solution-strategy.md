# T04 方案策略

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：`README.md`、`INTERFACE_CONTRACT.md`、实现文件布局

## 策略摘要

T04 当前采用一种约束明确、证据优先的策略：

1. 规范化并校验输入
2. 选择分支几何上下文
3. 扫描 DriveZone 分裂行为
4. 在必要时对 continuous chain、multibranch、K16 做专项处理
5. 产出锚点、crossline 和诊断产物

## 文档策略

未来对稳定行为的解释应放在本文件和构件视图中；contract 文件则继续聚焦 I/O 与验收要求。

## 待确认问题

- multibranch 与 K16 规则家族，未来是否需要独立的决策记录？
