# 约束 4-5 治理执行报告

## 1. 本轮基线分支和工作分支

- 基线分支：`codex/007-repository-metadata-entrance-cleanup`
- 工作分支：`codex/008-code-boundary-entrypoint-governance`

## 2. root AGENTS.md 增加的两条最小规则

- 单个源码 / 脚本文件超过 `100 KB` 视为结构债；后续变更若必须触碰超阈值文件，先给出拆分计划或结构整改说明。
- 默认禁止新增新的执行入口脚本；新增入口必须有任务书批准，并登记到 `docs/repository-metadata/entrypoint-registry.md`。

## 3. 详细约束文档位置

- `docs/repository-metadata/code-boundaries-and-entrypoints.md`
- `docs/repository-metadata/code-size-audit.md`
- `docs/repository-metadata/entrypoint-registry.md`

## 4. 当前超阈值源码 / 脚本文件

- 当前共发现 `9` 个超过 `100 KB` 的源码文件
- 其中活跃模块源码 `5` 个：
  - `src/highway_topo_poc/modules/t04_rc_sw_anchor/runner.py`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/pipeline.py`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/step3_arc_evidence.py`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/step5_conservative_road.py`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/audit_acceptance.py`
- 历史参考模块源码 `2` 个：
  - `src/highway_topo_poc/modules/t05_topology_between_rc/pipeline.py`
  - `src/highway_topo_poc/modules/t05_topology_between_rc/geometry.py`
- 测试源码 `2` 个：
  - `tests/test_t05v2_pipeline.py`
  - `tests/test_t05_step1_unique_adjacent.py`

## 5. 当前执行入口脚本识别结果

- 当前共登记 `73` 个执行入口文件
- 大致分布：
  - repo 级 / 工具级：`7`
  - Active 模块：T04 `4`、正式 T05 `29`、T06 `1`
  - Historical / Retired / Support：legacy T05 `25`、T02 `4`、T10 `2`、T01 `1`
- 多数入口集中在 `scripts/` 与 T05 / T05-V2 相关的历史 / 验证链路

## 6. 是否仍有明显未登记的入口类型

- 当前没有明显未登记的入口类型
- 边界模糊项主要是共享辅助脚本与内部实现模块；本轮已明确它们不作为独立入口登记
- `tools/` 下维护脚本与 support 模块 CLI 已登记，但后续仍可再做收敛判断

## 7. Analyze 摘要

- 约束 4 与约束 5 已写入 repo 级规则，并有详细解释文档承接
- 当前态的超阈值文件清单已形成
- 当前态的入口注册表已形成
- 当前仍存在明显的入口收敛空间，尤其集中在 T05 / T05-V2 的 shell 包装与专项 review 脚本，但本轮只登记不合并
- 本轮未引入新的 repo 级治理冲突

## 8. 本轮没有做哪些事，为什么没做

- 没有拆分任何超阈值文件，因为本轮只做规则固化与现状审计
- 没有删除、合并或迁移任何入口脚本，因为本轮只建立治理边界与注册表
- 没有引入 CI、pre-commit 或 lint 工具，因为这超出本轮范围
