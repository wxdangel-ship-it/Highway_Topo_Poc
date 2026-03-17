# T10 Phase-7/8 Baseline

Baseline name: `T10_phase8_manual_batch_operable_baseline`

已覆盖能力：
- 手工模式 override：JSON / Python `dict`
- 内存模式 / file mode / patch_dir mode
- 单 patch 多 `mainid`
- multi-patch manual mode
- CLI
- writer：
  - `serialized_bundle.json`
  - `movement_results.json`
  - `movement_matrix.json`
  - `summary.txt`
  - patch 级 `manifest.json`
  - multi-patch 根级 `manifest.json`
- checker：
  - `check_t10_run_output_dir(...)`
  - `check_t10_patch_output_root(...)`
- baseline snapshot comparator：
  - `compare_t10_output_dir_to_snapshot(...)`

当前推荐入口：
- 单路口内存模式：
  - `run_t10_single_intersection_manual_mode(...)`
- 单路口文件模式：
  - `run_t10_single_intersection_from_geojson_files(...)`
- 单 patch：
  - `run_t10_single_intersection_from_patch_dir(...)`
- 单 patch 多 `mainid`：
  - `run_t10_all_intersections_from_patch_dir(...)`
- multi-patch：
  - `run_t10_multi_patch_manual_mode(...)`
- CLI：
  - `python -m highway_topo_poc.modules.t10_complex_intersection_modeling.cli`

当前适用场景：
- 手工标注 `left_uturn_service / paired_mainline_no_left_uturn` 后运行 T10.2 / T10.3
- 规则链验证、样例验证、非回归检查
- 单 patch / multi-patch 的手工批量运行

当前不适用场景：
- 依赖真实 `formway / bit7 / bit8` 语义的自动识别
- `right_turn_service` 正式规则
- 多 patch 之外的更复杂批处理协议
- Excel 输出
- 生产级几何阈值优化
- 真实自动 `paired_mainline_no_left_uturn` 识别

显式失败路径目录：
- `patch_dir_missing_required_files`
- `patch_dir_layout_ambiguous`
- `multiple_mainids_in_node_file`
- `requested_mainid_not_found`
- `manual_override_file_not_found`
- `manual_override_file_invalid_json`
- `manual_override_payload_must_be_object`
- `manual_service_ref_not_found`
- `unsupported_manual_service_profile`
- `override_root_not_found`
- `requested_patch_dir_not_found`
- `artifact_*`
- `snapshot_compare_*`

交接指引：
- 若后续继续做自动识别，优先从这些位置接：
  - `diagnostics.py`
  - `service_profile_resolver.py`
  - `manual_overrides.py`
  - `artifact_checker.py`
- 若后续只跑手工模式，推荐最小路径：
  - file mode / patch_dir / multi-patch + manual override JSON + writer + checker
- 规则冻结内容以：
  - `modules/T10/AGENTS.md`
  - `modules/T10/SKILL.md`
  - `modules/T10/INTERFACE_CONTRACT.md`
  为准
- `arm`、`turn_sense`、`parallel_cross_count(0/1)` 的实现仍是候选实现说明，不是唯一算法

baseline snapshots：
- `tests/fixtures/t10/snapshots/basic_two_arm/`
- `tests/fixtures/t10/snapshots/left_service_tri_arm/`
- `tests/fixtures/t10/snapshots/access_exit_boundary/`

override JSON 示例：
- `tests/fixtures/t10/manual_service_profile_only.json`
- `tests/fixtures/t10/manual_service_with_pair.json`
