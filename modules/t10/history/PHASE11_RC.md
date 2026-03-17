# T10 Phase-11 Release Candidate

Release candidate: `T10_phase11_manual_review_cycle_release_candidate`

当前已覆盖：
- 手工模式运行：memory / file / patch_dir / single patch all mainids / multi-patch manual / CLI
- 输出：results、matrix、catalog、override template、review bundle、rerun diff
- 校验：artifact checker、override roundtrip validator、baseline snapshot comparator、baseline regression smoke

当前推荐入口：
- 单 patch review-cycle：
  - `run_t10_review_cycle_from_patch_dir(...)`
- patch_root review-cycle：
  - `run_t10_review_cycle_from_patch_root(...)`
- baseline 回归：
  - `run_t10_baseline_regression_smoke(...)`
- CLI：
  - `python -m highway_topo_poc.modules.t10_complex_intersection_modeling.cli`

最小 CLI 示例：
- 单 patch review-cycle
  - `python -m highway_topo_poc.modules.t10_complex_intersection_modeling.cli --patch-dir <patch_dir> --manual-override <override.json> --output-dir <out_dir> --review-cycle --validate-override`
- patch_root review-cycle
  - `python -m highway_topo_poc.modules.t10_complex_intersection_modeling.cli --patch-root <patch_root> --override-root <override_root> --output-dir <out_root> --review-cycle`
- baseline 回归
  - `python -m highway_topo_poc.modules.t10_complex_intersection_modeling.cli --run-regression-smoke --output-dir <regression_out>`

推荐手工工作流：
1. 先跑 review-cycle 生成 `base/`
2. 看 `approach_catalog.json`、`manual_override.template.json`、`review_*.json`
3. 写 override 后 rerun
4. 再看 `diff/run_diff.json` 或 batch diff `manifest.json`

若只想跑手工模式，最短路径：
- `patch_dir` + `--review-cycle` + `--output-dir`

若要补 override，先看：
- `approach_catalog.json`
- `manual_override.template.json`
- `override_roundtrip.json`

若要复核 unknown / nonstandard / profile gaps，先看：
- `review_unknown_movements.json`
- `review_nonstandard_targets.json`
- `review_special_profile_gaps.json`
- `review_summary.txt`

若后续继续做自动识别，优先接这些模块：
- `diagnostics.py`
- `service_profile_resolver.py`
- `manual_overrides.py`
- `override_roundtrip.py`
- `artifact_checker.py`
- `run_diff.py`

规则冻结内容以这些文档为准：
- `modules/T10/AGENTS.md`
- `modules/T10/SKILL.md`
- `modules/T10/INTERFACE_CONTRACT.md`

仍只是候选实现说明 / 未来扩展位：
- `arm` 更细分组阈值
- `turn_sense` 精细几何边界
- `parallel_cross_count(0/1)` 精细走廊层级算法
- `formway / bit7 / bit8` 自动识别链
- `right_turn_service`

当前明确未支持：
- `formway / bit7 / bit8` 真实自动识别
- `right_turn_service` 正式规则
- lane-level / lane-group
- Excel 输出
- 复杂 UI / 前端
