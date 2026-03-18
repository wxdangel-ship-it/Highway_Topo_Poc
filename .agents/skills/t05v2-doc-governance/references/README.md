# T05-V2 文档治理 Skill 详细说明

本文档承接 T05-V2 标准 Skill 的详细 SOP、检查点与回退说明。
它是流程扩展材料，不替代 `architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md` 或 `history/REAL_RUN_ACCEPTANCE.md` 的既有职责。

## 详细检查点

- `AGENTS.md` 是否仍然足够短，只保留稳定工作规则。
- `INTERFACE_CONTRACT.md` 是否保留输入、输出、入口、参数类别、示例和验收标准。
- `architecture/05-building-block-view.md` 是否仍清楚表达 `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad`。
- `history/REAL_RUN_ACCEPTANCE.md` 是否仍被明确定义为运行验收文档，而不是长期真相。
- legacy T05 材料是否被限制在历史参考语义，而不是重新变成正式入口。

## 常见失败点

- 稳定真相又回流到 `AGENTS.md` 或 Skill 顶层入口。
- 运行验收文档与 `architecture/*` / `INTERFACE_CONTRACT.md` 口径不一致。
- 历史材料被误写成当前正式 T05 的真相。
- 脚本、算法或目录名改动被混入文档治理任务。

## 回退方式

- 如果稳定真相被写回流程文档，回退到 `architecture/*` 与 `INTERFACE_CONTRACT.md` 重整边界。
- 如果运行验收文档与源事实冲突，先修正源事实，再同步运行验收说明。
- 如果任务实际变成算法、脚本或目录改动，终止本 Skill，改走独立任务。
- 如果 legacy T05 材料与当前正式 T05 冲突，只把它当历史证据，不回退到家族连续治理叙事。

## 常见边界情况

- 只有在真实运行、验收或排查阶段产物时，才读 `history/REAL_RUN_ACCEPTANCE.md`。
- 若需引用实现事实，优先回看 `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`、相关测试与 `scripts/t05v2_*.sh`。
- legacy T05 的最小 pointer 只作为历史背景，不作为当前规划依据。

## 需要额外阅读的文档

- `modules/t05_topology_between_rc_v2/history/REAL_RUN_ACCEPTANCE.md`
- `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`
- `tests/test_t05v2_pipeline.py`
- `scripts/t05v2_*.sh`

## 细粒度验证习惯

- 改文档前后都要对照 repo root `AGENTS.md`、`SPEC.md` 与项目级 `docs/architecture/*`。
- 若修改 `INTERFACE_CONTRACT.md` 或运行验收说明，要回看 `run.py`、`pipeline.py` 和相关脚本，确认入口、阶段名、输出路径与参数基线没有写错。
- 提交前执行 `git diff --check`，并确认 legacy T05 没有被重新提升为正式入口。
