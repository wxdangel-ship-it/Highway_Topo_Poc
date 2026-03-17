# t06_patch_preprocess - AGENTS

## 开工前先读

- 先读 `architecture/01-introduction-and-goals.md`、`architecture/04-solution-strategy.md`、`architecture/10-quality-requirements.md`。
- 再读 `INTERFACE_CONTRACT.md`，确认稳定输入、输出、参数类别和验收标准。
- 做治理口径或模块总览时，再读 `review-summary.md`。

## 允许改动范围

- 默认只改本目录下文档：`architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`SKILL.md`、`review-summary.md`。
- 若无明确任务，不修改 `src/`、`tests/`、`outputs/`、`data/`。
- 不跨模块改动其它 `INTERFACE_CONTRACT.md`。

## 必做验证

- 改文档前后对照 repo root `AGENTS.md`、`SPEC.md` 与项目级 `docs/architecture/*`，避免口径冲突。
- 修改 contract 时，必须回看 `run.py`、`pipeline.py`、`io.py`、`report.py` 和 `tests/test_t06_patch_preprocess.py`，确认入口、输出、`drivezone_clip_buffer_m` 与质量门槛没有写错。
- 提交前至少执行 `git diff --check`。

## 禁做事项

- 不把 `AGENTS.md` 写成模块真相主表面。
- 不继续沿用“固定零缓冲”这类已与实现漂移的旧口径。
- 不在没有明确任务书的情况下修改 T06 算法、测试、CLI 行为或输出结构。
- 不为了文档统一而额外伪造 runbook 或长期源事实。

## 相邻模块关系

- T06 为 patch 级预处理模块，向下游模块提供端点引用更稳定的 `RCSDNode/RCSDRoad`。
- 与相邻模块交互时，以本模块 contract 和项目级源事实为准；如发现口径冲突，先停止并汇报。
