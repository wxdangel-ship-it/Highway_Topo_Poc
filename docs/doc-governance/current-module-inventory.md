# 当前模块盘点

## 范围

- 盘点日期：2026-03-17
- 目的：给出当前仓库模块的正式生命周期状态、文档面状态与后续维护动作

## 当前正式生命周期结论

- `Active`：
  - `t04_rc_sw_anchor`
  - `t05_topology_between_rc_v2`
  - `t06_patch_preprocess`
- `Historical Reference`：
  - `t05_topology_between_rc`
- `Retired`：
  - `t02_ground_seg_qc`
  - `t03_marking_entity`
  - `t07_patch_postprocess`
  - `t10`
- `Support Retained`：
  - `t00_synth_data`
  - `t01_fusion_qc`

## 当前模块总表

| 模块 | 模块路径 | 当前状态 | 当前定位 | 当前文档面状态 | 推荐动作 | 备注 |
|---|---|---|---|---|---|---|
| `t00_synth_data` | `modules/t00_synth_data` | Support Retained | 仓库保留的支撑 / 测试模块 | 保留既有模块文档面 | 后续单独做支撑模块整理 | 不属于当前活跃模块集合 |
| `t01_fusion_qc` | `modules/t01_fusion_qc` | Support Retained | 仓库保留的支撑 / 测试模块 | 保留既有模块文档面 | 后续单独做支撑模块整理 | 不属于当前活跃模块集合 |
| `t02_ground_seg_qc` | `modules/t02_ground_seg_qc` | Retired | 退役历史模块 | 根目录仅保留最小状态入口；历史契约与流程文档下沉到 `history/` | 只保留退役状态与历史可见性 | 不进入后续正式化队列 |
| `t03_marking_entity` | `modules/t03_marking_entity` | Retired | 已退役，当前无目录 | 无当前模块入口文档 | 仅保留项目级退役记录 | 不创建替代目录 |
| `t04_rc_sw_anchor` | `modules/t04_rc_sw_anchor` | Active | 当前正式活跃模块 | 已具备 `architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `.agents/skills/t04-doc-governance/SKILL.md` + `.agents/skills/t04-doc-governance/references/README.md` + `review-summary.md` + `README.md`；旧模块根 Skill 已移入 `history/` | 维持正式文档面并按需增量维护 | 当前主线模块之一 |
| legacy `t05_topology_between_rc` | `modules/t05_topology_between_rc` | Historical Reference | legacy T05 历史参考模块 | 根目录仅保留最小状态入口；历史契约、审计和流程文档下沉到 `history/` | 仅保留历史参考指针与历史资料 | 不再参与 family 连续治理 |
| `t05_topology_between_rc_v2` | `modules/t05_topology_between_rc_v2` | Active | 当前正式 T05 模块 | 已具备 `architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `.agents/skills/t05v2-doc-governance/SKILL.md` + `.agents/skills/t05v2-doc-governance/references/README.md` + `review-summary.md`；运行验收说明与旧模块根 Skill 均下沉到 `history/` | 维持正式文档面并按需增量维护 | 物理路径保持 V2 |
| `t06_patch_preprocess` | `modules/t06_patch_preprocess` | Active | 当前正式活跃模块 | 已具备 `architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `SKILL.md` + `review-summary.md` | 维持正式文档面并按需增量维护 | 当前主线模块之一 |
| `t07_patch_postprocess` | `modules/t07_patch_postprocess` | Retired | 退役历史模块 | 根目录仅保留最小状态入口；历史契约与流程文档下沉到 `history/` | 只保留退役状态与历史可见性 | 不再作为活跃治理对象 |
| `t10` | `modules/t10` | Retired | 退役历史模块 | 根目录仅保留最小状态入口；阶段性说明、历史契约和流程文档下沉到 `history/` | 只保留退役状态与历史资料 | 不再作为当前治理对象 |

## 活跃模块摘要

### T04

- 正式状态：`Active`
- 当前职责：RC / SW 路口锚点识别与 `intersection_l_opt` 生成
- 当前文档面：已形成最小正式模块文档面
- 后续动作：只做增量维护，不回退到草案治理状态

### T05-V2

- 正式状态：`Active`
- 当前职责：当前正式 T05，承担 RC 路口间拓扑生成
- 当前文档面：已形成最小正式模块文档面
- 历史运行验收说明：`modules/t05_topology_between_rc_v2/history/REAL_RUN_ACCEPTANCE.md`
- 后续动作：作为正式 T05 语义主体继续维护；legacy T05 只作历史参考

### T06

- 正式状态：`Active`
- 当前职责：patch 级预处理与端点闭包修复
- 当前文档面：已形成最小正式模块文档面
- 后续动作：只做增量维护，不再以“新模块草案”口径描述

## 退役与历史参考说明

### `t03_marking_entity`

- 已退役。
- 当前不存在 `modules/t03_marking_entity/`。
- 当前不存在 `src/highway_topo_poc/modules/t03_marking_entity/`。
- 项目级文档保留退役记录，不创建替代入口文件。

### legacy T05

- `t05_topology_between_rc` 为 `Historical Reference`。
- 根目录只保留状态入口。
- 历史契约、流程与审计材料位于 `modules/t05_topology_between_rc/history/`。

### `t10`

- `t10` 为 `Retired`。
- `modules/t10` 根目录只保留退役状态入口。
- 历史阶段说明与契约位于 `modules/t10/history/`。

## 总结

当前模块治理已经完成从“身份未决”到“生命周期已收口、主入口已精简”的转换：

- 当前正式活跃模块只有 `t04`、正式 T05（`t05_topology_between_rc_v2`）和 `t06`
- legacy T05 只作为历史参考模块存在
- `t02`、`t03`、`t07`、`t10` 均已退役，并已将非标准模块文档下沉到 `history/`
- `t00`、`t01` 继续作为仓库保留的支撑 / 测试模块存在，但不属于当前活跃模块集合
