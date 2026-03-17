# T04 引言与目标

## 状态

- 文档状态：Round 2C Phase A 最小正式稿
- 来源依据：
  - `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
  - `modules/t04_rc_sw_anchor/README.md`
  - `src/highway_topo_poc/modules/t04_rc_sw_anchor/cli.py`
  - `tests/t04_rc_sw_anchor/`

## 模块使命

T04 负责在 patch 或 global focus 语境下，为 merge / diverge 与 K16 相关节点识别锚点位置，并生成下游可用的 `intersection_l_opt` 及相关诊断结果。模块的核心目标不是“尽量给出一个答案”，而是在 DriveZone-first、Between-Branches 和 fail-closed 约束下，给出可解释、可复核、可落盘的锚点结果。

## 当前目标

- 为 merge / diverge 形态提供稳定的锚点与横截线输出。
- 为 K16 提供独立处理路径，而不是把它视为普通 merge / diverge 的边角分支。
- 把 continuous chain、multibranch、reverse tip 等复杂情况纳入同一模块治理框架，并保留失败可解释性。
- 保持输出与下游模块兼容，使 `intersection_l_opt`、`anchors.json`、`metrics.json`、`breakpoints.json`、`summary.txt` 能够共同支撑复核。

## 成功边界

- 当 evidence 充分时，模块输出可信的 `intersection_l_opt` 与锚点结果。
- 当 evidence 不足或约束冲突时，模块允许明确失败，并通过断点和诊断产物解释原因。
- 结果不以“跨路口补答案”或“几何漂移凑答案”为代价换取通过。

## 人类阅读路径

- 先读本文件理解 T04 的顶层使命。
- 再读 `04-solution-strategy.md` 与 `05-building-block-view.md` 理解阶段结构与构件关系。
- 再读 `INTERFACE_CONTRACT.md` 理解稳定契约面。
- 如需批处理或 patch 自动发现入口，再读 `README.md` 和相关脚本说明。
