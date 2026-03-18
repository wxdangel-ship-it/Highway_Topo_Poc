# t05_topology_between_rc_v2 - AGENTS

## 开工前先读

- 先读 `architecture/01-introduction-and-goals.md`、`architecture/05-building-block-view.md`、`architecture/10-quality-requirements.md`。
- 再读 `INTERFACE_CONTRACT.md`，确认稳定输入、输出、入口、参数类别与验收标准。
- 处理治理口径或现状总结时，再读 `review-summary.md`。
- 只有在真实运行、验收或排查阶段产物时，才读 `history/REAL_RUN_ACCEPTANCE.md`。
- 需要复用流程时，先读 repo root `.agents/skills/t05v2-doc-governance/SKILL.md`；需要详细检查点、失败点、回退策略或验收类 SOP 时，再读 `.agents/skills/t05v2-doc-governance/references/README.md`。

## 允许改动范围

- 默认只改本目录下的标准文档：`architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`review-summary.md`。
- 如任务涉及标准可复用流程，可同时修改 repo root `.agents/skills/t05v2-doc-governance/SKILL.md` 与 `references/README.md`。
- 只有任务明确涉及运行验收历史资料时，才改 `history/REAL_RUN_ACCEPTANCE.md`。
- 如果任务明确要求补充历史参考指针，可最小化修改 `modules/t05_topology_between_rc/` 的文档说明。
- 若任务没有明确要求，不修改 `src/`、`tests/`、`scripts/`、`outputs/`、`data/`。

## 必做验证

- 改文档前后都要对照 repo root `AGENTS.md`、`SPEC.md` 与项目级 `docs/architecture/*`，避免口径冲突。
- 修改 `INTERFACE_CONTRACT.md` 或 `history/REAL_RUN_ACCEPTANCE.md` 时，要回看 `run.py`、`pipeline.py` 和 `scripts/t05v2_*.sh`，确认入口、阶段名、输出路径与参数基线没有写错。
- 提交前至少执行 `git diff --check`。

## 禁做事项

- 不把 `AGENTS.md` 写成模块真相主表面。
- 不把 legacy `t05_topology_between_rc` 当成当前正式 T05 的家族连续治理对象。
- 不在没有明确任务书的情况下修改算法、测试、运行脚本或物理目录名。
- 不把 `history/REAL_RUN_ACCEPTANCE.md` 继续扩写成长期架构真相文档。

## 冲突处理

- 如果任务书与 `architecture/*`、`INTERFACE_CONTRACT.md` 或 repo root `AGENTS.md` 冲突，先列出冲突点并停止，不要静默裁决。

## legacy 关系

- 当前正式 T05 模块就是本目录。
- `modules/t05_topology_between_rc/` 仅作为历史参考保留；引用 legacy 材料时，只能作为背景证据，不能回退到家族连续治理口径。
