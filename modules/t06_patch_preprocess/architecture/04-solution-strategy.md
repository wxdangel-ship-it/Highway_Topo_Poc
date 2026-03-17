# T06 方案策略

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：`SKILL.md`、`INTERFACE_CONTRACT.md`、实现文件布局

## 策略摘要

T06 当前采用确定性的修复策略：

1. 加载并规范 patch 输入
2. 识别 endpoint reference 缺失的道路
3. 将受影响道路裁剪到 DriveZone
4. 保留有效的内部几何段
5. 在端点变化处生成确定性的 virtual node
6. 输出修复后的向量与诊断报告

## 文档策略

这条分阶段解释应进入 architecture 文档；`AGENTS.md` 与 `SKILL.md` 则收缩为持久规则和可复用流程。
