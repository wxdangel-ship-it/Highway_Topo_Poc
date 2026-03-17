# 模块生命周期

## 1. 文档目的

本文档用于定义当前仓库模块的生命周期状态，明确哪些模块属于当前正式治理对象、哪些已经退役、哪些只保留为历史参考。
本文档不描述模块内部实现细节，也不替代模块级 `architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md` 或 `SKILL.md`。

## 2. 状态定义

### Active

- 当前正式治理与迭代对象
- 后续文档治理、实现调整和结构化变更都以这类模块为主

### Retired

- 不再作为当前活跃模块治理对象
- 保留历史实现与文档
- 根目录只保留最小状态入口，历史契约 / 流程 / 阶段说明下沉到 `history/`

### Historical Reference

- 不再作为当前正式模块
- 保留为经验、历史证据和择优提炼来源
- 不再进入当前正式模块主线治理

### Support Retained

- 仓库保留的支撑 / 测试模块
- 当前不属于活跃模块集合，也不按退役 / 历史参考口径处理
- 后续如需统一治理，必须另行写回项目级文档

## 3. 当前模块状态表

| 模块 | 物理路径 | 当前状态 | 说明 |
|---|---|---|---|
| T04 | `modules/t04_rc_sw_anchor` | Active | 当前正式活跃模块 |
| T05 | `modules/t05_topology_between_rc_v2` | Active | 当前正式 T05 语义主体 |
| T06 | `modules/t06_patch_preprocess` | Active | 当前正式活跃模块 |
| T02 | `modules/t02_ground_seg_qc` | Retired | 保留历史实现与文档 |
| T03 | `modules/t03_marking_entity` | Retired | 当前无模块目录，仅保留退役记录 |
| T07 | `modules/t07_patch_postprocess` | Retired | 保留历史实现与文档 |
| T10 | `modules/t10` | Retired | 保留历史资料与实现痕迹 |
| legacy T05 | `modules/t05_topology_between_rc` | Historical Reference | 不再是当前正式 T05，仅保留为历史参考 |
| t00 | `modules/t00_synth_data` | Support Retained | 仓库保留的支撑 / 测试模块 |
| t01 | `modules/t01_fusion_qc` | Support Retained | 仓库保留的支撑 / 测试模块 |

## 4. 状态变更原则

- 模块从 `Active` 变为 `Retired` 时，必须满足：
  - 已明确不再作为当前正式治理对象
  - 项目级文档已同步写回状态
  - 保留最小历史可见性与入口指针
- 模块从正式模块变为 `Historical Reference` 时，必须满足：
  - 已有新的正式语义主体
  - 历史模块仅作为经验、证据或提炼来源保留
  - 项目级文档已明确“当前正式模块是谁”
- 不得仅通过 `AGENTS.md`、局部任务书或会话临时口径改变模块正式状态
- 生命周期状态一旦调整，必须同步写回项目级源事实文档

## 5. 与其他文档的关系

- `SPEC.md`：定义项目范围、正式模块集合与关键状态
- `docs/PROJECT_BRIEF.md`：提供项目摘要层同步口径
- `docs/repository-metadata/repository-structure-metadata.md`：定义不同生命周期模块在仓库中的标准文档落位
- `docs/doc-governance/current-module-inventory.md`：提供更细的模块盘点与文档面现状
- `docs/doc-governance/current-doc-inventory.md`：解释当前文档分层与入口

本文档不替代模块级 `architecture/*`、`INTERFACE_CONTRACT.md` 或模块入口文档；它只负责定义模块当前处于什么生命周期状态。
