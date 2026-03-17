# T10 Manual Mode Usage

补充基线说明见 `modules/T10/PHASE7_BASELINE.md`。

当前推荐入口：
- 内存模式：`run_t10_single_intersection_manual_mode(...)`
- file mode：`run_t10_single_intersection_from_geojson_files(...)`
- 单 patch：`run_t10_single_intersection_from_patch_dir(...)`
- 单 patch 多 `mainid`：`run_t10_all_intersections_from_patch_dir(...)`
- multi-patch：`run_t10_multi_patch_manual_mode(...)`
- shell/终端：`python -m highway_topo_poc.modules.t10_complex_intersection_modeling.cli`

当前手工模式支持：
- `manual_override_source` 传入 JSON 文件或 Python `dict`
- `patch_dir` 模式自动发现 `Vector/RCSDNode.geojson` 与 `Vector/RCSDRoad.geojson`
- `patch_root` 模式按子目录枚举 patch，并在每个 patch 内运行全部 `mainid`
- writer 输出：
  - 单路口：`serialized_bundle.json` / `movement_results.json` / `movement_matrix.json` / `summary.txt`
  - 单 patch：每个 `mainid_*` 子目录 + patch 级 `manifest.json` / `summary.txt`
  - multi-patch：每个 patch 子目录 + patch_root 级 `manifest.json` / `summary.txt`
- checker：
  - `check_t10_run_output_dir(...)`
  - `check_t10_patch_output_root(...)`

manual override 约定：
- 单路口 / 单 patch：直接传 `manual_override_source`
- multi-patch：推荐使用 `manual_override_root`
- 当前 per-patch 约定：`<override_root>/<patch_name>.json`
- 手工映射优先于自动识别占位

单路口 `mainid` 规则：
- node 文件只有一个 `mainid` 时可直接运行
- 若含多个 `mainid` 且未指定，会显式报错并列出可选值
- 指定 `mainid` 后，只对该单一路口收口运行

multi-patch 当前边界：
- 只支持一个 `patch_root` 下多个 patch_dir 的连续运行
- 每个 patch 当前默认运行其内部全部 `mainid`
- 当前不做多 patch 之外的更复杂批处理协议

最小示例：
- override JSON：
  - `tests/fixtures/t10/manual_service_profile_only.json`
  - `tests/fixtures/t10/manual_service_with_pair.json`
- baseline snapshots：
  - `tests/fixtures/t10/snapshots/`

最小 file mode 示例：
```python
result = run_t10_single_intersection_from_geojson_files(
    node_geojson_path="RCSDNode.geojson",
    road_geojson_path="RCSDRoad.geojson",
    manual_override_source="manual_overrides.json",
    mainid=100,
)
write_t10_run_result(result, "out_dir")
```

最小 patch_dir 示例：
```python
batch = run_t10_all_intersections_from_patch_dir(
    patch_dir="patch_dir",
    manual_override_source="manual_overrides.json",
    output_root="out_root",
)
```

最小 multi-patch 示例：
```python
multi = run_t10_multi_patch_manual_mode(
    patch_root="patch_root",
    manual_override_root="override_root",
    output_root="out_root",
)
```

最小 CLI 示例：
```bash
python -m highway_topo_poc.modules.t10_complex_intersection_modeling.cli --patch-root patch_root --override-root override_root --output-dir out_root
```

当前适合：
- 手工标注 `left_uturn_service / paired_mainline_no_left_uturn` 后跑通 T10.2 / T10.3
- 做规则链验证、样例验证、snapshot 非回归检查
- 做 file / patch / multi-patch 的手工运营化运行

当前不适合：
- 依赖真实 `formway / bit7 / bit8` 语义做自动识别
- 将当前自动识别占位接口当作生产级自动识别
- 多 patch 之外的更复杂调度、Excel 输出、复杂 run_id 协议
