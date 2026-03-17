# 审核优先级

## Round 1 人工重点审核范围

| 优先级 | 模块 | 为什么本轮纳入 | Round 1 产出 |
|---|---|---|---|
| 高 | `t04_rc_sw_anchor` | 核心成熟模块，contract、`AGENTS`、`SKILL`、`README` 同时承载模块真相 | `architecture` 草案 + `review-summary` |
| 高 | `t05_topology_between_rc_v2` | 当前正式 T05 模块，后续正式化迁移价值最高 | `architecture` 草案 + `review-summary` |
| 高 | `t06_patch_preprocess` | 仓库已实现，且全局文档已在 Round 2A 对齐其成熟度 | `architecture` 草案 + `review-summary` |

## 其他模块

| 优先级 | 模块 | 当前处理方式 | 原因 |
|---|---|---|---|
| 中 | `t07_patch_postprocess` | 后续规范化 | 仍属活跃模块，但本轮未进入深度审核 |
| 中 | `t02_ground_seg_qc` | 后续规范化 | frozen 但文档复杂，适合在后续做结构收口 |
| 低 | `t00_synth_data` | frozen 整理 | 主要是历史整理和指针补充 |
| 低 | `t01_fusion_qc` | frozen 整理 | 主要是历史整理和指针补充 |
| 低 | `t05_topology_between_rc` | 历史参考保留 | 已明确为 legacy 历史参考模块，不再属于活跃治理主线 |
| 低 | `t10` | 历史遗留保留 | 已退役，不进入当前正式 taxonomy |

## 特殊状态

- `t03_marking_entity`：已退役；当前无活跃目录，不再列入活跃治理主线。
- `t05_topology_between_rc`：legacy 历史参考模块；保留资料，但不再要求 family 连续治理。
- `t10`：已退役历史模块；保留资料与实现痕迹，但不再作为活跃模块治理对象。

## 建议的后续顺序

1. `t05_topology_between_rc_v2` 的正式模块文档迁移 / 正式化
2. `t04_rc_sw_anchor` 与 `t06_patch_preprocess` 的模块级迁移深化
3. `t07_patch_postprocess` 与 `t02_ground_seg_qc` 的规范化
4. frozen 模块 `t00_synth_data`、`t01_fusion_qc` 的整理

## 不再属于活跃治理主线的对象

- legacy T05 的家族连续治理
- `t03_marking_entity` 的“是否恢复”讨论
- `t10` 的 taxonomy / naming 正式化
