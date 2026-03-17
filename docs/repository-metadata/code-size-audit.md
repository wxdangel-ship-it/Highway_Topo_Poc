# 当前超阈值源码 / 脚本文件审计

## 1. 审计范围

- 审计时间：2026-03-17
- 审计对象：仓库中纳入版本管理的源码 / 脚本文件，重点覆盖 `.py`、`.sh`、`.cmd`、`.ps1`、`.js`、`.ts`、`.bat` 与 `Makefile`
- 排除范围：`.git/`、`.venv/`、`outputs/`、`runs/`、`data/`、第三方依赖目录、明显二进制 / 导出物

本次共扫描 `235` 个源码 / 脚本文件。

## 2. 阈值定义

- 阈值：单文件 `> 100 KB`
- 含义：超过阈值的源码 / 脚本文件视为结构债，需要在后续触碰时补拆分计划或结构整改说明

## 3. 当前结果摘要

- 当前超过阈值的文件共 `9` 个
- 其中活跃模块源码 `5` 个，历史参考模块源码 `2` 个，测试源码 `2` 个
- 当前没有 shell 入口脚本超过阈值

## 4. 当前超过阈值的文件清单

| 路径 | 文件大小 | 文件类型 | 是否属于活跃模块 | 建议动作 |
|---|---|---|---|---|
| `src/highway_topo_poc/modules/t05_topology_between_rc/pipeline.py` | 725.7 KB (743,144 bytes) | `.py` | 否（Historical Reference） | 历史保留 |
| `tests/test_t05v2_pipeline.py` | 331.4 KB (339,386 bytes) | `.py` | 否 | 观察 |
| `src/highway_topo_poc/modules/t05_topology_between_rc_v2/step5_conservative_road.py` | 268.1 KB (274,488 bytes) | `.py` | 是 | 后续拆分计划 |
| `tests/test_t05_step1_unique_adjacent.py` | 261.4 KB (267,717 bytes) | `.py` | 否 | 观察 |
| `src/highway_topo_poc/modules/t05_topology_between_rc/geometry.py` | 254.5 KB (260,637 bytes) | `.py` | 否（Historical Reference） | 历史保留 |
| `src/highway_topo_poc/modules/t05_topology_between_rc_v2/pipeline.py` | 200.1 KB (204,901 bytes) | `.py` | 是 | 后续拆分计划 |
| `src/highway_topo_poc/modules/t05_topology_between_rc_v2/step3_arc_evidence.py` | 197.7 KB (202,395 bytes) | `.py` | 是 | 后续拆分计划 |
| `src/highway_topo_poc/modules/t04_rc_sw_anchor/runner.py` | 184.2 KB (188,641 bytes) | `.py` | 是 | 后续拆分计划 |
| `src/highway_topo_poc/modules/t05_topology_between_rc_v2/audit_acceptance.py` | 181.4 KB (185,751 bytes) | `.py` | 是 | 后续拆分计划 |

## 5. 本轮不做拆分的说明

- 本轮只记录规则与现状，不拆分任何大文件。
- 对活跃模块的超阈值文件，当前建议动作只到“后续拆分计划”，不进入实际整改。
- 对 legacy / 历史参考模块的超阈值文件，当前按“历史保留”处理，不再继续堆叠实现。
