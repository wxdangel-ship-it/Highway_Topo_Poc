# T04 引言与目标

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：`INTERFACE_CONTRACT.md`、`README.md`

## 模块目标

T04 负责识别 RC/SW merge-diverge 形态的锚点位置，并为下游拓扑模块生成 `intersection_l_opt` 相关输出。

## 当前目标说明

- DriveZone-first 证据链是核心前提。
- Between-Branches 扫描策略是核心机制。
- fail-closed 行为是显式且有意保持的。
- K16 处理是独立子流程，而不是偶发边界情况。

## 审核重点

- 确认该目标表述是否同时覆盖常规 merge/diverge 与 K16 路径
