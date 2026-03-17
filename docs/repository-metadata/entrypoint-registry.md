# 当前执行入口注册表

## 1. 文档目的

本文档用于登记当前仓库中已识别的执行入口脚本与入口文件。
它只记录当前态，不在本轮发起合并、删除或迁移。

## 2. 什么算执行入口脚本

当前将以下独立启动面视为执行入口：

- `Makefile`
- `scripts/`、`tools/` 下可以直接运行的 shell / Python 脚本
- 模块内带独立启动面的 `__main__.py`、`run.py` 或同类入口文件
- 明显承担独立验证 / 审计职责的脚本

以下内容不纳入注册表：

- 仅被其它脚本 `source` 的共享辅助脚本，如 `scripts/t05_step_common.sh`
- 只提供函数、不承担独立启动职责的内部模块
- 文档中的命令示例

## 3. 当前登记摘要

- 当前共识别 `73` 个执行入口文件
- 分布概览：
  - repo 级 / 工具级：`7`
  - Active 模块：T04 `4`、正式 T05 `29`、T06 `1`
  - Historical / Retired / Support：legacy T05 `25`、T02 `4`、T10 `2`、T01 `1`
- 共享辅助脚本与内部实现模块未纳入统计

## 4. 当前已识别入口清单

### 4.1 repo 级 / 工具级

| 名称 | 路径 | 类型 | 适用范围 | 当前状态 | 是否建议后续收敛 |
|---|---|---|---|---|---|
| `Makefile` | `Makefile` | repo 级 | 仓库级测试入口 | `active` | 否 |
| `agent_enter.sh` | `scripts/agent_enter.sh` | repo 级 | 进入仓库后的标准握手辅助 | `active` | 否 |
| `python -m highway_topo_poc` | `src/highway_topo_poc/__main__.py` | repo 级 | 仓库级 Python 包入口 | `active` | 否 |
| `qa_runner_full_v12.py` | `tools/qa_runner_full_v12.py` | 其他 | QA / 验证工具入口 | `active` | 否 |
| `migrate_patch_schema_v3_add_road_tiles.py` | `tools/migrate_patch_schema_v3_add_road_tiles.py` | 其他 | 数据结构维护入口 | `active` | 否 |
| `migrate_patch_schema_v4_rename_rcsdnode_rcsdroad.py` | `tools/migrate_patch_schema_v4_rename_rcsdnode_rcsdroad.py` | 其他 | 数据结构维护入口 | `active` | 否 |
| `migrate_patch_vector_schema_v2.py` | `tools/migrate_patch_vector_schema_v2.py` | 其他 | 数据结构维护入口 | `active` | 否 |

### 4.2 Active 模块：T04

| 名称 | 路径 | 类型 | 适用范围 | 当前状态 | 是否建议后续收敛 |
|---|---|---|---|---|---|
| `run_t04_batch_wsl.sh` | `modules/t04_rc_sw_anchor/scripts/run_t04_batch_wsl.sh` | 模块级 | T04 WSL 批处理入口 | `candidate-for-consolidation` | 是 |
| `run_t04_patch_auto_nodes.sh` | `scripts/run_t04_patch_auto_nodes.sh` | 模块级 | T04 自动节点模式入口 | `candidate-for-consolidation` | 是 |
| `python -m highway_topo_poc.modules.t04_rc_sw_anchor` | `src/highway_topo_poc/modules/t04_rc_sw_anchor/__main__.py` | 模块级 | T04 官方 Python 入口 | `active` | 否 |
| `node_discovery.py` | `src/highway_topo_poc/modules/t04_rc_sw_anchor/node_discovery.py` | 验证级 | T04 节点发现 / 核对入口 | `candidate-for-consolidation` | 是 |

### 4.3 Historical Reference：legacy T05

| 名称 | 路径 | 类型 | 适用范围 | 当前状态 | 是否建议后续收敛 |
|---|---|---|---|---|---|
| `run_t05_full_wsl.sh` | `scripts/run_t05_full_wsl.sh` | 模块级 | legacy T05 全流程 WSL 批跑 | `legacy` | 否 |
| `run_t05_topology_between_rc_smoke.py` | `scripts/run_t05_topology_between_rc_smoke.py` | 验证级 | legacy T05 smoke 验证 | `legacy` | 否 |
| `t05_resume.sh` | `scripts/t05_resume.sh` | 模块级 | legacy T05 续跑入口 | `legacy` | 否 |
| `t05_step0_xsec_gate.sh` | `scripts/t05_step0_xsec_gate.sh` | 模块级 | legacy T05 阶段入口 | `legacy` | 否 |
| `t05_step1_shape_ref.sh` | `scripts/t05_step1_shape_ref.sh` | 模块级 | legacy T05 阶段入口 | `legacy` | 否 |
| `t05_step2_xsec_road.sh` | `scripts/t05_step2_xsec_road.sh` | 模块级 | legacy T05 阶段入口 | `legacy` | 否 |
| `t05_step3_build_road.sh` | `scripts/t05_step3_build_road.sh` | 模块级 | legacy T05 阶段入口 | `legacy` | 否 |
| `t05_step4_gate_export.sh` | `scripts/t05_step4_gate_export.sh` | 模块级 | legacy T05 阶段入口 | `legacy` | 否 |
| `t05_pull_and_regress.sh` | `scripts/t05_pull_and_regress.sh` | 验证级 | legacy T05 回归入口 | `legacy` | 否 |
| `t05_regress_modified_pairs.sh` | `scripts/t05_regress_modified_pairs.sh` | 验证级 | legacy T05 定向回归入口 | `legacy` | 否 |
| `t05_collect_patch_diag.sh` | `scripts/t05_collect_patch_diag.sh` | 验证级 | legacy T05 patch 诊断收集 | `legacy` | 否 |
| `t05_collect_step01_metrics.sh` | `scripts/t05_collect_step01_metrics.sh` | 验证级 | legacy T05 指标收集 | `legacy` | 否 |
| `t05_diag_step1_multi_corridor.sh` | `scripts/t05_diag_step1_multi_corridor.sh` | 验证级 | legacy T05 诊断入口 | `legacy` | 否 |
| `t05_diag_step2_barrier.sh` | `scripts/t05_diag_step2_barrier.sh` | 验证级 | legacy T05 诊断入口 | `legacy` | 否 |
| `t05_pair_check.py` | `scripts/t05_pair_check.py` | 验证级 | legacy T05 pair 核查 | `legacy` | 否 |
| `t05_extract_audit_fix_round1.py` | `scripts/t05_extract_audit_fix_round1.py` | 验证级 | legacy T05 审计提取 | `legacy` | 否 |
| `t05_extract_final_geometry_trace.py` | `scripts/t05_extract_final_geometry_trace.py` | 验证级 | legacy T05 几何轨迹提取 | `legacy` | 否 |
| `t05_extract_global_fit_trace.py` | `scripts/t05_extract_global_fit_trace.py` | 验证级 | legacy T05 全局拟合轨迹提取 | `legacy` | 否 |
| `t05_extract_global_fit_v2_trace.py` | `scripts/t05_extract_global_fit_v2_trace.py` | 验证级 | legacy T05 V2 轨迹提取 | `legacy` | 否 |
| `t05_extract_simplepatch_connector_audit.py` | `scripts/t05_extract_simplepatch_connector_audit.py` | 验证级 | legacy T05 connector 审计提取 | `legacy` | 否 |
| `t05_build_result_doc.py` | `scripts/t05_build_result_doc.py` | 验证级 | legacy T05 结果文档生成 | `legacy` | 否 |
| `wsl_verify_t05.sh` | `scripts/wsl_verify_t05.sh` | 验证级 | legacy T05 WSL 环境验证 | `legacy` | 否 |
| `t05 legacy run.py` | `src/highway_topo_poc/modules/t05_topology_between_rc/run.py` | 模块级 | legacy T05 Python 入口 | `legacy` | 否 |
| `export_traj_lines.py` | `src/highway_topo_poc/modules/t05_topology_between_rc/export_traj_lines.py` | 验证级 | legacy T05 轨迹导出入口 | `legacy` | 否 |
| `focus_report.py` | `src/highway_topo_poc/modules/t05_topology_between_rc/focus_report.py` | 验证级 | legacy T05 focus 报告入口 | `legacy` | 否 |

### 4.4 Active 模块：正式 T05-V2

| 名称 | 路径 | 类型 | 适用范围 | 当前状态 | 是否建议后续收敛 |
|---|---|---|---|---|---|
| `run_t05v2_full_wsl.sh` | `scripts/run_t05v2_full_wsl.sh` | 模块级 | 正式 T05 全流程 WSL 包装入口 | `candidate-for-consolidation` | 是 |
| `t05v2_resume.sh` | `scripts/t05v2_resume.sh` | 模块级 | 正式 T05 续跑入口 | `candidate-for-consolidation` | 是 |
| `t05v2_step1_input_frame.sh` | `scripts/t05v2_step1_input_frame.sh` | 模块级 | 正式 T05 阶段入口 | `candidate-for-consolidation` | 是 |
| `t05v2_step2_segment.sh` | `scripts/t05v2_step2_segment.sh` | 模块级 | 正式 T05 阶段入口 | `candidate-for-consolidation` | 是 |
| `t05v2_step3_witness.sh` | `scripts/t05v2_step3_witness.sh` | 模块级 | 正式 T05 阶段入口 | `candidate-for-consolidation` | 是 |
| `t05v2_step4_corridor_identity.sh` | `scripts/t05v2_step4_corridor_identity.sh` | 模块级 | 正式 T05 阶段入口 | `candidate-for-consolidation` | 是 |
| `t05v2_step5_slot_mapping.sh` | `scripts/t05v2_step5_slot_mapping.sh` | 模块级 | 正式 T05 阶段入口 | `candidate-for-consolidation` | 是 |
| `t05v2_step6_build_road.sh` | `scripts/t05v2_step6_build_road.sh` | 模块级 | 正式 T05 阶段入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_phase4_full_regress.sh` | `scripts/t05_v2_phase4_full_regress.sh` | 验证级 | 正式 T05 阶段回归入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_geometry_refine_complexpatch.sh` | `scripts/t05_v2_geometry_refine_complexpatch.sh` | 验证级 | 正式 T05 complex patch 几何细化入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_geometry_refine_simplepatch.sh` | `scripts/t05_v2_geometry_refine_simplepatch.sh` | 验证级 | 正式 T05 simple patch 几何细化入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_geometry_refine_simplepatch_extract.py` | `scripts/t05_v2_geometry_refine_simplepatch_extract.py` | 验证级 | 正式 T05 几何细化提取入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_phase4_extract.py` | `scripts/t05_v2_phase4_extract.py` | 验证级 | 正式 T05 phase4 结果提取入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_alias_fix_and_rootcause_push_review.py` | `scripts/t05_v2_alias_fix_and_rootcause_push_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_arc_first_attach_evidence_review.py` | `scripts/t05_v2_arc_first_attach_evidence_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_arc_legality_fix_review.py` | `scripts/t05_v2_arc_legality_fix_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_arc_obligation_closure_review.py` | `scripts/t05_v2_arc_obligation_closure_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_bridge_trial_review.py` | `scripts/t05_v2_bridge_trial_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_competing_arc_closure_review.py` | `scripts/t05_v2_competing_arc_closure_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_legal_arc_coverage_review.py` | `scripts/t05_v2_legal_arc_coverage_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_merge_diverge_fix_review.py` | `scripts/t05_v2_merge_diverge_fix_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_merge_diverge_rules_review.py` | `scripts/t05_v2_merge_diverge_rules_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_perf_opt_arc_first_review.py` | `scripts/t05_v2_perf_opt_arc_first_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_semantic_fix_after_perf_review.py` | `scripts/t05_v2_semantic_fix_after_perf_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_step5_finish_55353246_37687913_review.py` | `scripts/t05_v2_step5_finish_55353246_37687913_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_step5_plus_multiarc_finish_review.py` | `scripts/t05_v2_step5_plus_multiarc_finish_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_topology_gap_controlled_cover_review.py` | `scripts/t05_v2_topology_gap_controlled_cover_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `t05_v2_witness_vis_step5_recovery_review.py` | `scripts/t05_v2_witness_vis_step5_recovery_review.py` | 验证级 | 正式 T05 专项 review 入口 | `candidate-for-consolidation` | 是 |
| `python -m highway_topo_poc.modules.t05_topology_between_rc_v2` | `src/highway_topo_poc/modules/t05_topology_between_rc_v2/__main__.py` | 模块级 | 正式 T05 官方 Python 入口 | `active` | 否 |

### 4.5 Active 模块：T06

| 名称 | 路径 | 类型 | 适用范围 | 当前状态 | 是否建议后续收敛 |
|---|---|---|---|---|---|
| `python -m highway_topo_poc.modules.t06_patch_preprocess` | `src/highway_topo_poc/modules/t06_patch_preprocess/__main__.py` | 模块级 | T06 官方 Python 入口 | `active` | 否 |

### 4.6 Retired / Support

| 名称 | 路径 | 类型 | 适用范围 | 当前状态 | 是否建议后续收敛 |
|---|---|---|---|---|---|
| `t01_fusion_qc cli.py` | `src/highway_topo_poc/modules/t01_fusion_qc/cli.py` | 其他 | Support Retained 模块入口 | `candidate-for-consolidation` | 是 |
| `t02 run.py` | `src/highway_topo_poc/modules/t02_ground_seg_qc/run.py` | 模块级 | 已退役 T02 主入口 | `legacy` | 否 |
| `batch_ground_cache.py` | `src/highway_topo_poc/modules/t02_ground_seg_qc/batch_ground_cache.py` | 模块级 | 已退役 T02 批处理入口 | `legacy` | 否 |
| `batch_multilayer_clean_and_classify.py` | `src/highway_topo_poc/modules/t02_ground_seg_qc/batch_multilayer_clean_and_classify.py` | 模块级 | 已退役 T02 批处理入口 | `legacy` | 否 |
| `export_classified_cloud.py` | `src/highway_topo_poc/modules/t02_ground_seg_qc/export_classified_cloud.py` | 模块级 | 已退役 T02 导出入口 | `legacy` | 否 |
| `run_t10_sh_manual_mode.sh` | `scripts/run_t10_sh_manual_mode.sh` | 模块级 | 已退役 T10 手工模式入口 | `legacy` | 否 |
| `t10 cli.py` | `src/highway_topo_poc/modules/t10_complex_intersection_modeling/cli.py` | 模块级 | 已退役 T10 Python 入口 | `legacy` | 否 |

## 5. 新增入口脚本的准入规则

- 默认禁止新增新的执行入口脚本。
- 只有当现有入口无法通过参数化、配置化或模块内复用解决，且 `SKILL.md` 也无法承接时，才允许作为例外提出。
- 新入口必须获得任务书明确批准，并补录到本注册表。

## 6. 为什么优先复用已有入口 / 参数 / skill

- 入口越多，后续约束、验收和回归路径越难保持一致。
- 活跃模块当前已经存在 package 入口、WSL 包装入口和大量专项验证入口，再新增入口的边际收益通常低于维护成本。
- 对重复性流程，优先扩展已有参数或写入 `SKILL.md`，比新建 `run_xxx.*` 更可控。
