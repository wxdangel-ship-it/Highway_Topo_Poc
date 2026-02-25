# t04_rc_sw_anchor

## 1. 模块简介
`t04_rc_sw_anchor` 用于 RC/SW 场景中的分歧/合流锚点识别与横截线优化。
当前版本仅覆盖 merge/diverge；cross 与其它类型只记录断点，不输出锚点结果。

## 2. 输入输出概览
输入（`patch_dir` 下）：
- MUST：`Vector/RCSDNode.geojson`、`Vector/intersection_l.geojson`、`Vector/RCSDRoad.geojson`
- SHOULD：`Vector/DivStripZone.geojson`、`PointCloud/merged.laz|merged.las`
- OPTIONAL：`Tiles/`（忽略）

输出（`outputs/_work/t04_rc_sw_anchor/<run_id>/`）：
- `anchors.geojson`
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- 建议：`intersection_l_opt.geojson`、`chosen_config.json`

## 3. 运行方式
```bash
python -m highway_topo_poc.modules.t04_rc_sw_anchor \
  --patch_dir <patch_dir> \
  --out_root outputs/_work/t04_rc_sw_anchor \
  --run_id <optional> \
  --config_json <optional> \
  --set key=value
```

说明：
- `--run_id` 缺省时自动生成时间戳+短 uuid。
- `--set key=value` 可重复，用于覆盖默认参数。

## 4. 关键口径
- seed node：`Kind` 含 bit4(diverge) 或 bit3(merge)。
- `intersection_l`：每个 seed 必须且仅有 1 条。
- 扫描触发优先级：`divstrip+pc > pc_only > divstrip_only_degraded`。
- 未触发：`NO_TRIGGER_BEFORE_NEXT_INTERSECTION`。

## 5. 质量门禁
Hard：
- MUST 输入可解析
- `seed_total > 0`
- `MULTIPLE_INTERSECTION_L == 0`
- 输出文件齐全

Soft（默认阈值）：
- `anchor_found_ratio >= 0.90`
- `NO_TRIGGER_BEFORE_NEXT_INTERSECTION_ratio <= 0.05`
- `SCAN_EXCEED_200M_ratio <= 0.02`

## 6. 测试
外网环境使用合成 patch 冒烟测试：
- `tests/t04_rc_sw_anchor/test_smoke_synth.py`
- 支持 `PointCloud/merged.geojson` 的 test-only fallback 点云读取路径。
