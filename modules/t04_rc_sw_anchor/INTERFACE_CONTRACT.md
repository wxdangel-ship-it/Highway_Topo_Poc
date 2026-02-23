# t04_rc_sw_anchor - INTERFACE_CONTRACT

## 1. 目标与范围
- 模块 ID：`t04_rc_sw_anchor`
- 目标：在 RC/SW 场景中识别并优化分歧/合流路口锚点（锚点近似 gore tip / nose）。
- 处理范围：仅 `diverge` 与 `merge`；`cross` 与其它类型不输出锚点，只输出断点说明。
- 关键约束：对每个 seed node，`intersection_l` 必须且仅能有 1 条；0 条或多条均为异常。

## 2. 输入（Input）
`patch_dir` 下的输入路径：

MUST:
- `Vector/Node.geojson`
- `Vector/intersection_l.geojson`
- `Vector/Road.geojson`

SHOULD:
- `Vector/DivStripZone.geojson`（缺失可降级，需写 breakpoint）
- `PointCloud/merged.laz` 或 `PointCloud/merged.las`（缺失可降级，需写 breakpoint）

OPTIONAL:
- `Tiles/`（当前阶段忽略）
- `Traj/...`（当前阶段不使用）

输入字段口径：
- `Node.Kind`：`bit4=diverge(16)`、`bit3=merge(8)`；其它组合写 `UNSUPPORTED_KIND` / `AMBIGUOUS_KIND`。
- `Road.geojson`：`snodeid`、`enodeid` 与 `LineString`。
- `intersection_l.geojson`：按 `properties.nodeid` 与 seed node 绑定。

## 3. 输出（Output）
输出目录固定为：
- `outputs/_work/t04_rc_sw_anchor/<run_id>/`

必须输出：
- `anchors.geojson`
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`

建议输出：
- `intersection_l_opt.geojson`
- `chosen_config.json`

`anchors.geojson` 约束：
- 每个 seed 至少两条 Feature：
  - `feature_role="anchor_point"`（Point）
  - `feature_role="crossline_opt"`（LineString）
- 属性至少包含：
  - `nodeid`
  - `anchor_type`
  - `status`（`ok|suspect|fail`）
  - `scan_dir`
  - `scan_dist_m`
  - `trigger`
  - `dist_to_divstrip_m`
  - `confidence`
  - `flags`（list）

## 4. 入口（Entrypoint / CLI）
- `python -m highway_topo_poc.modules.t04_rc_sw_anchor`

CLI：
- `--patch_dir <path>`
- `--out_root outputs/_work/t04_rc_sw_anchor`
- `--run_id <optional>`（缺省自动生成）
- `--config_json <optional>`
- `--set key=value`（可重复，用于覆盖默认参数）

## 5. 参数（Parameters）
默认参数：
- `cross_half_len_m = 20`
- `scan_step_m = 1.0`
- `scan_near_limit_m = 20`
- `scan_max_limit_m = 200`
- `stop_at_next_intersection = true`
- `divstrip_hit_tol_m = 1.0`
- `divstrip_trigger_window_m = 3.0`
- `pc_line_buffer_m = 0.5`
- `pc_non_ground_min_points = 5`
- `pc_ground_class = 2`
- `pc_use_classification = true`
- `ignore_initial_side_ng = true`
- `ignore_end_margin_m = 3.0`
- `allow_divstrip_only_when_no_pointcloud = true`

门禁阈值默认：
- `anchor_found_ratio_min = 0.90`
- `no_trigger_before_next_intersection_ratio_max = 0.05`
- `scan_exceed_200m_ratio_max = 0.02`
- `divstrip_tolerance_violation_hard = true`

## 6. 门禁与评分规则
Hard Gates（任一失败即 `overall_pass=false`）：
- MUST 输入可解析
- `seed_total > 0`
- `MULTIPLE_INTERSECTION_L == 0`
- 必需输出文件齐全
- 当 `divstrip_tolerance_violation_hard=true` 时：`DIVSTRIP_TOLERANCE_VIOLATION_count == 0`

Soft Gates（默认阈值可配置）：
- `anchor_found_ratio >= 0.90`
- `NO_TRIGGER_BEFORE_NEXT_INTERSECTION_ratio <= 0.05`
- `SCAN_EXCEED_200M_ratio <= 0.02`

`confidence`（0..1）规则：
- `base=0.4`
- `+0.4` if `trigger=="divstrip+pc"`
- `+0.25` if `trigger=="pc_only"`
- `+0.15` if `trigger=="divstrip_only_degraded"`
- `-0.2` if `scan_dist_m > 20`
- `-0.3` if `scan_dist_m > 200`

## 7. 示例（Example）
在 repo root 执行：

```bash
python -m highway_topo_poc.modules.t04_rc_sw_anchor \
  --patch_dir data/synth_local/00000000 \
  --out_root outputs/_work/t04_rc_sw_anchor \
  --run_id smoke_t04
```

## 8. 验收（Accept）
- CLI `--help` 可用
- 运行后输出目录存在且包含必需文件
- `summary.txt` 可粘贴（控制在一屏摘要）
- pytest 冒烟用例可在外网无真实数据场景下通过
