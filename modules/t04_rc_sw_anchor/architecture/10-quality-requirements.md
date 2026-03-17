# T04 质量要求

## 状态

- 文档状态：Round 2C Phase A 最小正式稿
- 来源依据：
  - `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
  - `tests/t04_rc_sw_anchor/`
  - `src/highway_topo_poc/modules/t04_rc_sw_anchor/metrics_breakpoints.py`

## 最小质量目标

- 锚点识别必须 fail-closed，而不是在证据不足时隐式成功。
- 输出必须对下游兼容，并保留足够的断点与诊断信息。
- 失败必须可解释，能够从 `anchors.json`、`breakpoints.json`、`metrics.json`、`summary.txt` 追溯问题层次。
- 输入归一化与 CRS 处理必须稳定、可审计。

## 关键验收要求

- 输出目录内必须存在核心结果与诊断文件。
- `intersection_l_opt` 必须符合约定的输出形态与必要 properties。
- hard-stop、DriveZone-first、fail-closed 不得被弱化。
- 对连续链、multibranch、K16、reverse tip 的关键结果必须能在输出诊断中定位。

## 失败可解释性要求

- 至少能够通过 breakpoint 和 summary 区分：
  - `DRIVEZONE_SPLIT_NOT_FOUND`
  - `NEXT_INTERSECTION_NOT_FOUND_DEG3`
  - `DRIVEZONE_CRS_UNKNOWN`
  - `SEQUENTIAL_ORDER_VIOLATION`
  - K16 相关失败
- fail 后不允许被后续状态覆盖。
- 操作者应能通过 `anchors.json` 中的关键字段判断当前触发、split、stop 与 chain / multibranch / K16 诊断结果。

## 操作者材料边界

- `README.md` 和批处理脚本负责说明如何运行。
- 本文件只定义长期质量目标与最小验收要求，不承担具体批量操作手册职责。
