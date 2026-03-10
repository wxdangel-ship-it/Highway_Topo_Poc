# T10 Review / Diff Usage

当前手工模式除了运行结果，还支持这些人工复核辅助产物：

- `approach_catalog.json`
- `manual_override.template.json`
- `review_*.json` / `review_summary.txt`
- `override_roundtrip.json`
- `run_diff.json` / `run_diff_summary.txt`

当前推荐入口：
- Python API
  - `write_t10_review_bundle(...)`
  - `roundtrip_manual_override_source(...)`
  - `run_t10_review_cycle_from_patch_dir(...)`
  - `run_t10_review_cycle_from_patch_root(...)`
  - `compare_t10_run_dirs(...)`
- CLI
  - `--emit-review-bundle`
  - `--validate-override`
  - `--review-cycle`
  - `--diff-before-dir`
  - `--diff-after-dir`

这些文件分别用于：
- `approach_catalog.json`
  - 看当前 intersection 下有哪些 `approach`
  - 看可用 selector：`road_id` / `road_id:entry` / `approach_id`
- `manual_override.template.json`
  - 提供空白手工映射模板
  - 只给可填写结构，不自动填任何 profile
- `override_roundtrip.json`
  - 校验当前 override
  - 输出错误列表和归一化后的 override 结构
- `review_unknown_movements.json`
  - 汇总当前仍是 `unknown` 的 movement
- `review_nonstandard_targets.json`
  - 汇总 target 侧为 `auxiliary_parallel_exit` / `access_exit` / `unknown` 的出口
- `review_special_profile_gaps.json`
  - 只提示“值得人工看”的特殊画像候选
  - 不代表自动识别结论
- `run_diff.json` / `run_diff_summary.txt`
  - 对比两次运行前后，哪些 movement 的 `status` / 主原因码变了
  - 汇总 review 计数变化

最小 `patch_dir` review-cycle 示例：
```bash
python -m highway_topo_poc.modules.t10_complex_intersection_modeling.cli ^
  --patch-dir patch_dir ^
  --manual-override manual_override.json ^
  --output-dir out_dir ^
  --review-cycle ^
  --validate-override
```

最小 rerun diff 示例：
```bash
python -m highway_topo_poc.modules.t10_complex_intersection_modeling.cli ^
  --diff-before-dir before_run_dir ^
  --diff-after-dir after_run_dir ^
  --output-dir diff_out_dir
```

当前仍明确不支持：
- `formway / bit7 / bit8` 自动识别
- `right_turn_service` 正式规则
- Excel 输出
- 任何基于 review 输出的自动 profile 注入
