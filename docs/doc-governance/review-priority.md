# 审核优先级

## 当前治理主线

Round 3A 之后，当前审核与治理主线只围绕以下对象展开：

1. 项目级生命周期、taxonomy 与治理文档一致性
2. 当前活跃模块 `t04_rc_sw_anchor`、正式 T05（`t05_topology_between_rc_v2`）、`t06_patch_preprocess` 的正式文档面维护
3. 仓库保留支撑 / 测试模块 `t00_synth_data`、`t01_fusion_qc` 的后续整理

## 当前优先级

| 优先级 | 对象 | 当前处理方式 | 原因 |
|---|---|---|---|
| 高 | 项目级治理文档 | 持续保持一致性 | 生命周期、目标结构、迁移映射和状态表必须保持统一 |
| 高 | `t05_topology_between_rc_v2` | 正式模块持续维护 | 当前正式 T05，任何主线拓扑治理都以它为准 |
| 高 | `t04_rc_sw_anchor` | 正式模块持续维护 | 当前活跃主线模块之一 |
| 高 | `t06_patch_preprocess` | 正式模块持续维护 | 当前活跃主线模块之一 |
| 中 | `t00_synth_data` | 支撑模块整理 | 属于仓库保留支撑模块，后续可做轻量整理 |
| 中 | `t01_fusion_qc` | 支撑模块整理 | 属于仓库保留支撑模块，后续可做轻量整理 |

## 不再进入活跃治理队列的对象

| 对象 | 当前状态 | 处理原则 |
|---|---|---|
| `t05_topology_between_rc` | Historical Reference | 只保留历史参考与指向正式 T05 的指针，不再作为 family 主线治理对象 |
| `t02_ground_seg_qc` | Retired | 只保留退役状态和历史可见性，不再作为活跃 formalization 对象 |
| `t03_marking_entity` | Retired | 只保留项目级退役记录，不再进入恢复讨论 |
| `t07_patch_postprocess` | Retired | 只保留退役状态和历史可见性，不再作为活跃 formalization 对象 |
| `t10` | Retired | 只保留退役状态和历史资料，不再进入 taxonomy / naming 正式化 |

## 后续建议顺序

1. 保持项目级治理文档与生命周期状态一致
2. 对当前活跃模块 `t04`、正式 T05、`t06` 做必要的增量维护
3. 单独安排 `t00`、`t01` 的支撑模块整理

## 明确不再作为活跃主线治理的话题

- legacy T05 的 family 连续治理
- `t02`、`t03`、`t07`、`t10` 的重新 formalization
- 仅通过局部 `AGENTS.md` 或任务书临时改变模块正式状态
