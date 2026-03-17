# T06 上下文与范围

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：`INTERFACE_CONTRACT.md`、当前 `src/` 与 `tests/`

## 当前范围

- 识别缺失 endpoint reference 的道路
- 将受影响道路裁剪到 DriveZone
- 生成确定性的 virtual node
- 更新道路 endpoint ID
- 输出修复后的向量与诊断结果

## Round 1 非范围

- 任何修复逻辑的运行时改动
- 更广义的 patch 过滤逻辑
- 对当前文档做破坏性清理

## 审核重点

- 对照 T04 与 T07，确认 T06 的上下游边界是否明确
