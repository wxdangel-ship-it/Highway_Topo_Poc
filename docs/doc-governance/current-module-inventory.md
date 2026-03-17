# 当前模块盘点

## 范围

- 盘点日期：2026-03-17
- 当前口径基线：已吸收 Round 2A 的人工决策、Round 2B 的 T05-V2 正式化、Round 2C 的 T04 / T06 正式化，以及 Round 3A 的生命周期收口
- 目的：给出当前仓库模块的正式生命周期状态、文档面状态与后续治理动作

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
- 仓库保留支撑 / 测试模块：
  - `t00_synth_data`
  - `t01_fusion_qc`

## 当前模块总表

| 模块 | 模块路径 | 当前状态 | 当前定位 | 当前文档面状态 | 推荐动作 | 备注 |
|---|---|---|---|---|---|---|
| `t00_synth_data` | `modules/t00_synth_data` | Support Retained | 仓库保留的支撑 / 测试模块 | 既有 `AGENTS.md` / `SKILL.md` / `INTERFACE_CONTRACT.md` 保留 | 后续只做支撑模块整理 | 不属于当前活跃模块集合 |
| `t01_fusion_qc` | `modules/t01_fusion_qc` | Support Retained | 仓库保留的支撑 / 测试模块 | 既有 `AGENTS.md` / `SKILL.md` / `INTERFACE_CONTRACT.md` 保留 | 后续只做支撑模块整理 | 不属于当前活跃模块集合 |
| `t02_ground_seg_qc` | `modules/t02_ground_seg_qc` | Retired | 退役历史模块 | 保留现有 `AGENTS.md` / `SKILL.md` / `INTERFACE_CONTRACT.md` | 仅保留最小退役指针 | 不进入后续正式化队列 |
| `t03_marking_entity` | `modules/t03_marking_entity` | Retired | 已退役，当前无目录 | 无当前模块入口文档 | 仅保留项目级退役记录 | 不创建替代目录 |
| `t04_rc_sw_anchor` | `modules/t04_rc_sw_anchor` | Active | 当前正式活跃模块 | 已具备 `architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `SKILL.md` + `review-summary.md` | 维持正式文档面并按需增量维护 | 当前主线模块之一 |
| `t05_topology_between_rc` | `modules/t05_topology_between_rc` | Historical Reference | legacy T05 历史参考模块 | 保留既有文档与历史审计资料 | 仅保留最小历史参考指针 | 不再参与 family 连续治理 |
| `t05_topology_between_rc_v2` | `modules/t05_topology_between_rc_v2` | Active | 当前正式 T05 模块 | 已具备 `architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `SKILL.md` + `review-summary.md` | 维持正式文档面并按需增量维护 | 物理路径保持 V2 |
| `t06_patch_preprocess` | `modules/t06_patch_preprocess` | Active | 当前正式活跃模块 | 已具备 `architecture/*` + `INTERFACE_CONTRACT.md` + `AGENTS.md` + `SKILL.md` + `review-summary.md` | 维持正式文档面并按需增量维护 | 当前主线模块之一 |
| `t07_patch_postprocess` | `modules/t07_patch_postprocess` | Retired | 退役历史模块 | 保留现有 `AGENTS.md` / `SKILL.md` / `INTERFACE_CONTRACT.md` | 仅保留最小退役指针 | 不再作为活跃治理对象 |
| `t10` | `modules/t10` | Retired | 退役历史模块 | 保留既有 `AGENTS.md` / `SKILL.md` / `INTERFACE_CONTRACT.md` 与阶段文档 | 仅保留最小退役指针 | `src/.../t10_complex_intersection_modeling/` 为历史实现痕迹 |

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
- 本轮仅在项目级文档中保留退役记录，不创建替代入口文件。

### legacy T05

- `t05_topology_between_rc` 为 `Historical Reference`。
- 它保留历史业务上下文、历史审计资料与经验来源价值。
- 它不再是当前正式 T05，也不再承担 family 连续治理职责。

### `t10`

- `t10` 为 `Retired`。
- `modules/t10` 与 `src/highway_topo_poc/modules/t10_complex_intersection_modeling/` 的命名差异被视为历史遗留事实。
- 该差异不再作为当前活跃治理问题处理。

## 后续治理建议

| 对象 | 当前建议 |
|---|---|
| `t04_rc_sw_anchor` | 维持正式文档面，按需做增量修订 |
| `t05_topology_between_rc_v2` | 作为正式 T05 持续维护 |
| `t06_patch_preprocess` | 维持正式文档面，按需做增量修订 |
| `t00_synth_data` / `t01_fusion_qc` | 后续作为支撑模块单独整理 |
| `t02_ground_seg_qc` / `t07_patch_postprocess` / `t10` | 只保留退役状态和历史可见性 |
| legacy `t05_topology_between_rc` | 只保留历史参考指针 |

## 总结

当前模块治理已经完成从“身份未决”到“生命周期已收口”的转换：

- 当前正式活跃模块只有 `t04`、正式 T05（`t05_topology_between_rc_v2`）和 `t06`
- legacy T05 只作为历史参考模块存在
- `t02`、`t03`、`t07`、`t10` 均已退役
- `t00`、`t01` 继续作为仓库保留的支撑 / 测试模块存在，但不属于当前活跃模块集合
