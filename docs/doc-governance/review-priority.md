# 审核优先级

## Round 1 人工重点审核范围

| 优先级 | 模块 | 为什么本轮纳入 | Round 1 产出 |
|---|---|---|---|
| 高 | `t04_rc_sw_anchor` | 核心成熟模块，contract、AGENTS、SKILL、README 同时承载模块真相 | `architecture` 草案 + `review-summary` |
| 高 | `t05_topology_between_rc_v2` | 活跃模块，仓库足迹独立，但相对 legacy T05 的家族定位未定 | `architecture` 草案 + `review-summary` |
| 高 | `t06_patch_preprocess` | 仓库已实现，但项目级旧 taxonomy 仍滞后 | `architecture` 草案 + `review-summary` |

## 其他模块

| 优先级 | 模块 | Round 1 处理方式 | 原因 |
|---|---|---|---|
| 中 | `t05_topology_between_rc` | 只做盘点 + 迁移上下文 | 是 T05-V2 的关键上下文，但不是本轮指定深改对象 |
| 中 | `t10` | 只做盘点 + 风险标注 | 超出 taxonomy，且存在命名漂移 |
| 中低 | `t07_patch_postprocess` | 只做盘点 | 以 contract 为先的新模块，当前治理压力较低 |
| 中低 | `t02_ground_seg_qc` | 只做盘点 | 文档丰富，但不在本轮人工重点范围 |
| 低 | `t00_synth_data` | 只做盘点 | frozen，Round 1 风险较低 |
| 低 | `t01_fusion_qc` | 只做盘点 | frozen，Round 1 风险较低 |

## 特殊情况

- `t03_marking_entity`：不是当前 repo 可见模块，但必须作为 taxonomy 缺口保留可见性。

## 建议的 Round 2+ 顺序

1. T05 legacy family 治理
2. T10 taxonomy 与命名归一化
3. T07 架构规范化
4. T02 文档规范化
5. frozen 模块 T00/T01，以及对 T03 的明确决策


