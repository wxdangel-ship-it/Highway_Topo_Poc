# 文档治理入口

## 从哪里开始看

建议按以下顺序阅读当前治理文档：

1. `AGENTS.md`
2. `SPEC.md`
3. `docs/PROJECT_BRIEF.md`
4. `docs/repository-metadata/README.md`
5. `docs/doc-governance/module-lifecycle.md`
6. `docs/doc-governance/current-module-inventory.md`
7. `docs/doc-governance/current-doc-inventory.md`
8. `docs/doc-governance/module-doc-status.csv`
9. 活跃模块正式文档面

## 当前 active governance / source-of-truth

- 项目级源事实：
  - `SPEC.md`
  - `docs/PROJECT_BRIEF.md`
  - `docs/architecture/*`
  - `docs/doc-governance/module-lifecycle.md`
- 当前治理入口：
  - `docs/repository-metadata/README.md`
  - `docs/repository-metadata/repository-structure-metadata.md`
  - `docs/doc-governance/current-module-inventory.md`
  - `docs/doc-governance/current-doc-inventory.md`
  - `docs/doc-governance/module-doc-status.csv`

## 当前模块状态简表

- Active：
  - `t04_rc_sw_anchor`
  - `t05_topology_between_rc_v2`
  - `t06_patch_preprocess`
- Retired：
  - `t02_ground_seg_qc`
  - `t03_marking_entity`
  - `t07_patch_postprocess`
  - `t10`
- Historical Reference：
  - legacy `t05_topology_between_rc`
- Support Retained：
  - `t00_synth_data`
  - `t01_fusion_qc`

## 历史文档在哪里

- 历史治理过程文档：`docs/doc-governance/history/`
- 项目级非标准历史说明：`docs/archive/nonstandard/`
- 历史变更工件：`specs/archive/`

这些内容用于审计、追溯和理解治理演进，不替代当前 source-of-truth。
