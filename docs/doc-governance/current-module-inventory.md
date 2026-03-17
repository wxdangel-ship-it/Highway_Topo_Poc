# 当前模块盘点

## 范围

- 盘点日期：2026-03-17
- 基线来源：Round 1 现状盘点，已由 Round 2A 人工决策补充修正
- 目的：建立当前模块治理口径、审核优先级与活跃 / 历史边界
- 当前重点审核模块：
  - `t04_rc_sw_anchor`
  - `t05_topology_between_rc_v2`
  - `t06_patch_preprocess`

## 当前模块总表

| 模块 | 模块路径 | 当前仓库现实 | 是否有模块文档 | 是否有 AGENTS | 是否有 SKILL | 是否有源码实现 | 当前建议深度 | 备注 |
|---|---|---|---|---|---|---|---|---|
| `t00_synth_data` | `modules/t00_synth_data` | frozen 工具模块 | 有 | 有 | 有 | 有 | 仅盘点 | 后续做 frozen 整理 |
| `t01_fusion_qc` | `modules/t01_fusion_qc` | frozen 模块 | 有 | 有 | 有 | 有 | 仅盘点 | 后续做 frozen 整理 |
| `t02_ground_seg_qc` | `modules/t02_ground_seg_qc` | frozen 但文档丰富 | 有 | 有 | 有 | 有 | 后续规范化 | 不在 Round 1 深度审核范围 |
| `t04_rc_sw_anchor` | `modules/t04_rc_sw_anchor` | 核心成熟模块 | 有 | 有 | 有 | 有 | 深度审核 | Round 1 重点审核模块 |
| `t05_topology_between_rc` | `modules/t05_topology_between_rc` | legacy 历史参考模块 | 有 | 有 | 有 | 有 | 历史参考保留 | 不再属于活跃治理主线 |
| `t05_topology_between_rc_v2` | `modules/t05_topology_between_rc_v2` | 当前正式 T05 模块（物理路径仍为 V2） | 有 | 有 | 无 | 有 | 深度审核 | Round 1 重点审核模块 |
| `t06_patch_preprocess` | `modules/t06_patch_preprocess` | 已实现的活跃模块 | 有 | 有 | 有 | 有 | 深度审核 | Round 1 重点审核模块 |
| `t07_patch_postprocess` | `modules/t07_patch_postprocess` | 活跃的 contract-first 模块 | 有 | 有 | 有 | 有 | 后续规范化 | 当前优先级低于 T04/T05-V2/T06 |
| `t10` | `modules/t10` | 已退役历史模块 | 有 | 有 | 有 | 无直接同名实现 | 历史保留 | 实现在 `src/.../t10_complex_intersection_modeling/` |

## 退役与历史参考口径

### `t03_marking_entity`

- 已退役。
- 当前不存在 `modules/t03_marking_entity/`。
- 当前不存在 `src/highway_topo_poc/modules/t03_marking_entity/`。
- 本轮不创建替代目录，也不再将其视为“缺失但待恢复”的活跃 taxonomy 成员。

### legacy T05

- `t05_topology_between_rc` 已明确为 legacy 历史参考模块。
- 它保留业务上下文和历史审计价值，但不再作为当前正式 T05 或 family 连续治理对象。

### `t10`

- `t10` 已退役。
- `modules/t10` 与 `src/highway_topo_poc/modules/t10_complex_intersection_modeling/` 的命名差异被视为历史遗留事实，而不是当前活跃治理问题。

## 重点模块摘要

### T04

- 当前业务角色：
  - 识别 merge/diverge 与 K16 锚点
  - 产出最终 `intersection_l_opt`
- 当前文档集合：
  - `AGENTS.md`
  - `SKILL.md`
  - `INTERFACE_CONTRACT.md`
  - `README.md`
- 当前实现证据：
  - 独立 `src/` 包
  - 独立 `tests/t04_rc_sw_anchor/`
- 当前文档问题：
  - 模块真相分散在四份文档中
  - `AGENTS` 与 `SKILL` 仍承载了稳定业务规则
- 后续重点：
  - 深化 `architecture/` 草案
  - 继续把真相从 `AGENTS` / `SKILL` 收回到源事实文档

### T05-V2

- 当前业务角色：
  - 通过 `Segment -> CorridorWitness -> CorridorIdentity -> Slot -> FinalRoad` 的阶段链路生成最终 `Road` 输出
- 当前正式定位：
  - 当前正式 T05 模块
  - 物理路径保持 `modules/t05_topology_between_rc_v2`
- 当前文档集合：
  - `AGENTS.md`
  - `INTERFACE_CONTRACT.md`
  - `REAL_RUN_ACCEPTANCE.md`
- 当前实现证据：
  - 独立 `src/` 包
  - 独立 `tests/test_t05v2_pipeline.py`
  - 多个独立 stepwise 脚本
- 当前文档问题：
  - 仍缺专用 `SKILL.md`
  - 验收说明很有价值，但不是长期架构文档
  - 与 legacy T05 的历史关系仍需通过迁移指针表达，而不是继续用 family 连续治理承载
- 后续重点：
  - 以 V2 为正式 T05 语义主体推进深迁移
  - 保留 legacy T05 为历史参考，不做目录重命名

### T06

- 当前业务角色：
  - 在 patch 级道路数据中修复缺失 endpoint reference 的问题，通过 DriveZone 裁剪和 virtual node 保证下游闭合
- 当前文档集合：
  - `AGENTS.md`
  - `SKILL.md`
  - `INTERFACE_CONTRACT.md`
- 当前实现证据：
  - `src/highway_topo_poc/modules/t06_patch_preprocess/`
  - `tests/test_t06_patch_preprocess.py`
- 当前文档问题：
  - `AGENTS`、`SKILL` 与 contract 仍有重叠
  - 需要继续把“已实现模块”的成熟度写入后续模块级源事实
- 后续重点：
  - 深化 `architecture/` 草案
  - 继续收缩 `AGENTS` / `SKILL` 中的稳定业务定义

## 当前优先级建议

| 模块 | 建议优先级 | 原因 |
|---|---|---|
| `t05_topology_between_rc_v2` | 高 | 当前正式 T05 模块，后续正式化迁移价值最高 |
| `t04_rc_sw_anchor` | 高 | 核心成熟模块，多个文档面重叠严重 |
| `t06_patch_preprocess` | 高 | 已实现模块，仍需继续收口文档真相 |
| `t07_patch_postprocess` | 中 | 活跃模块，但治理复杂度低于前三者 |
| `t02_ground_seg_qc` | 中 | frozen 但文档复杂，适合后续规范化 |
| `t00_synth_data` | 低 | frozen，主要是整理与指针补充 |
| `t01_fusion_qc` | 低 | frozen，主要是整理与指针补充 |
| `t05_topology_between_rc` | 低 | legacy 历史参考，不再作为活跃治理对象 |
| `t10` | 低 | 已退役历史模块，不再进入当前活跃治理主线 |

## 总结

当前模块治理口径已经明确为：

- 当前正式 T05 = `t05_topology_between_rc_v2`
- legacy T05 = `t05_topology_between_rc`
- `t03_marking_entity` = 已退役
- `t10` = 已退役历史模块

Round 2A 之后，后续治理重点不再是“先决定模块身份”，而是围绕正式模块继续做深迁移和结构收口。
