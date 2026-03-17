# T05-V2 上下文与范围

## 状态

- 草案状态：Round 1 最小可信草案，已由 Round 2A 决策对齐补充修正
- 来源依据：`INTERFACE_CONTRACT.md`、`REAL_RUN_ACCEPTANCE.md`、当前 `src/` 与 `scripts/`

## 当前范围

- 从输入 frame 到最终 road 的阶段式执行
- 各阶段的 debug 与验收输出
- 独立的输出根目录 `outputs/_work/t05_topology_between_rc_v2/`

## 上下文

- 位于 `intersection_l` / `DriveZone` 风格 patch 输入之后
- 当前是正式 T05 模块
- 与 legacy `t05_topology_between_rc` 处于同一业务领域，但后者只作为历史参考保留
- 当前拥有独立脚本和测试，仍在活跃支持中

## 当前非范围

- 修改 T05-V2 运行逻辑
- 物理路径改名
- 与 legacy T05 做大范围文档整合

## 审核重点

- 对照 T04、legacy T05 与 T06，确认当前范围边界是否清晰
