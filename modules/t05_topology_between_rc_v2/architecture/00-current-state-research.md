# T05-V2 现状研究

## 状态

- 当前状态：正式 T05 模块级架构说明
- 当前正式定位：`modules/t05_topology_between_rc_v2` 是当前正式 T05 模块
- 来源依据：
  - `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md`
  - `modules/t05_topology_between_rc_v2/history/REAL_RUN_ACCEPTANCE.md`
  - `modules/t05_topology_between_rc_v2/review-summary.md`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`
  - `tests/test_t05v2_pipeline.py`
  - `scripts/t05v2_*.sh`

## 当前模块事实

- 当前正式 T05 的物理路径保持为 `modules/t05_topology_between_rc_v2/`，本轮不重命名目录。
- legacy `modules/t05_topology_between_rc` 仅保留为历史参考模块，不再承担家族连续治理职责。
- 模块执行入口为 `python -m highway_topo_poc.modules.t05_topology_between_rc_v2.run`，支持 `full` 与六个阶段入口。
- 默认输出根目录为 `outputs/_work/t05_topology_between_rc_v2/<run_id>/patches/<patch_id>/`。
- 步进脚本与 `resume` 已存在，说明“按阶段落盘并恢复执行”是当前操作模型的一部分。

## 代码与测试证据摘要

- `run.py` 对外暴露 `step1_input_frame` 到 `step6_build_road` 六个阶段，以及 `full` 全流程入口。
- `pipeline.py` 明确了阶段顺序、阶段目录、默认参数和阶段产物写出逻辑。
- `io.py` 证明输入会统一规整到 `EPSG:3857`，`DriveZone` 缺失或为空时会抛出硬失败。
- `tests/test_t05v2_pipeline.py` 覆盖了输入缺失、CRS 归一化、Step2 基线行为、完整成路、`DivStrip` 拦截、阶段恢复等关键行为。
- `scripts/t05v2_step*.sh` 与 `scripts/t05v2_resume.sh` 证明当前模块已形成稳定的脚本化执行方式。

## 当前稳定业务真相

- 模块的长期业务链路是 `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad`。
- 当前契约输入以 `intersection_l`、`DriveZone`、轨迹数据为主，并支持 `DivStripZone`、`LaneBoundary`、既有 road 先验等增强输入。
- 当前主输出是 `Road.geojson`、`metrics.json`、`gate.json`、`summary.txt`，并伴随分阶段目录和 `debug/` 诊断产物。
- 简单真实 patch 的目标不是“尽快补更多策略”，而是在现有阶段链上形成稳定、可解释、可验收的成路闭环。

## 文档分层结论

- `architecture/*` 承担稳定模块真相，包括目标、上下文、约束、构件关系、质量要求和风险。
- `INTERFACE_CONTRACT.md` 承担稳定契约面，包括输入、输出、入口、参数类别、示例和验收标准。
- `AGENTS.md` 只保留稳定工作规则，不再承担模块真相主表面。
- repo root `.agents/skills/t05v2-doc-governance/SKILL.md` 承担 T05-V2 的可复用工作流；模块根 `SKILL.md` 仅保留最小指针。
- `history/REAL_RUN_ACCEPTANCE.md` 继续保留为运行验收与操作者清单，不再承担长期源事实职责。

## 当前人工审核重点

- 核对 `architecture/*` 中对阶段链的描述是否足够支撑后续模块级迁移。
- 核对 `INTERFACE_CONTRACT.md` 的参数分组是否已覆盖当前稳定运行基线，而没有把高层架构叙事重新带回契约文档。
- 核对运行验收文档与源事实的边界是否清晰，避免操作者再次把运行文档误读为长期真相。
