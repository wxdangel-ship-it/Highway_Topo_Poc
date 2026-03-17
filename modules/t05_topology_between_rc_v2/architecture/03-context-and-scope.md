# T05-V2 上下文与范围

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：`INTERFACE_CONTRACT.md`、`REAL_RUN_ACCEPTANCE.md`、当前 `src/` 与 `scripts/`

## 当前范围

- 从输入 frame 到最终 road 的阶段式执行
- 各阶段的 debug 与验收输出
- 独立的输出根目录 `outputs/_work/t05_topology_between_rc_v2/`

## 上下文

- 位于 intersection / DriveZone 风格 patch 输入之后
- 与 legacy T05 处于紧密相关的同一业务领域
- 当前拥有独立脚本和测试，仍在活跃支持中

## Round 1 非范围

- 最终决定 T05 family 的长期 taxonomy
- 修改 T05-V2 运行逻辑

## 审核重点

- 对照 T04、legacy T05 与 T06，确认当前范围边界是否清晰
