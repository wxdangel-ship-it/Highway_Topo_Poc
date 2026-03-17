# t04_rc_sw_anchor - AGENTS

## 开工前先读

- 先读 `architecture/01-introduction-and-goals.md`、`architecture/04-solution-strategy.md`、`architecture/10-quality-requirements.md`。
- 再读 `INTERFACE_CONTRACT.md`，确认输入模式、输出、参数类别和验收要求。
- 处理批量运行或 patch 自动发现入口时，再读 `README.md` 与相关脚本说明。
- 做治理口径或模块总览时，再读 `review-summary.md`。

## 允许改动范围

- 默认只改本目录下文档：`architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`SKILL.md`、`review-summary.md`、`README.md`。
- 如无明确任务，不修改 `src/`、`tests/`、`scripts/`、`outputs/`、`data/`。
- 不跨模块改动其它 `INTERFACE_CONTRACT.md`。

## 必做验证

- 改文档前后对照 repo root `AGENTS.md`、`SPEC.md` 与项目级 `docs/architecture/*`，避免口径冲突。
- 修改 contract 或 README 时，要回看 `cli.py`、`runner.py`、`metrics_breakpoints.py` 和关键测试，确认模式、输出、breakpoint 与 gate 没写错。
- 提交前至少执行 `git diff --check`。

## 禁做事项

- 不把 `AGENTS.md` 写成模块真相主表面。
- 不在没有明确任务书的情况下修改 T04 算法、测试、批处理脚本或 patch 自动发现脚本。
- 不把 README 扩写成新的长期源事实文档。
- 不为了提高通过率而在文档中弱化 fail-closed、hard-stop 或 DriveZone-first 约束。

## 相邻模块关系

- T04 面向下游拓扑模块提供锚点与 `intersection_l_opt` 结果。
- 与相邻模块交互时，以本模块 contract 和项目级源事实为准；如发现口径冲突，先停止并汇报。
