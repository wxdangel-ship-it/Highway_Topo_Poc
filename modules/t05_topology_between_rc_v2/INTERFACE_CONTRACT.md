# t05_topology_between_rc_v2 - INTERFACE_CONTRACT

## 定位

- 本文件是当前正式 T05 模块的稳定契约面。
- 高层业务目标、阶段构件关系和风险说明以 `architecture/*` 为准。
- 运行验收操作细节以 `history/REAL_RUN_ACCEPTANCE.md` 为准。

## 输入

| 输入项 | 是否必需 | 说明 |
|---|---|---|
| `Vector/intersection_l.geojson` | 必需 | patch 内的路口边界 / 基础拓扑边界输入 |
| `Vector/DriveZone.geojson` | 必需 | 主要可行驶区域约束；缺失或为空会硬失败 |
| `Traj/*/raw_dat_pose.geojson` | 必需 | 轨迹输入，提供 `Segment`、witness 与成路证据 |
| `Vector/DivStripZone.geojson` | 可选 | 如果存在，则作为 final road 的硬障碍参与判断 |
| `Vector/LaneBoundary.geojson` | 可选 | 几何增强输入；缺失或需修复时允许降级处理 |
| `Vector/RCSDRoad.geojson` 或 `Vector/Road.geojson` | 可选 | 既有 road 先验，用于 prior / fallback 相关推断 |

## 输出

### 主输出

| 文件 | 说明 |
|---|---|
| `outputs/_work/t05_topology_between_rc_v2/<run_id>/patches/<patch_id>/Road.geojson` | 最终 `Road` 输出 |
| `outputs/_work/t05_topology_between_rc_v2/<run_id>/patches/<patch_id>/metrics.json` | 结果与阶段指标汇总 |
| `outputs/_work/t05_topology_between_rc_v2/<run_id>/patches/<patch_id>/gate.json` | 质量门控结果 |
| `outputs/_work/t05_topology_between_rc_v2/<run_id>/patches/<patch_id>/summary.txt` | 面向快速验收的文本摘要 |

### 阶段与诊断输出

- 每个 `stepN/` 目录至少包含阶段主产物和 `step_state.json`。
- `debug/` 目录至少应包含当前审核常用的诊断文件，例如：
  - `base_xsec_all.geojson`
  - `segment_candidates.geojson`
  - `segment_selected.geojson`
  - `corridor_identity.json`
  - `slot_src_dst.geojson`
  - `shape_ref_line.geojson`
  - `road_final.geojson`
  - `reason_trace.json`

## 运行入口

### CLI 入口

```bash
python -m highway_topo_poc.modules.t05_topology_between_rc_v2.run \
  --data_root <data_root> \
  --patch_id <patch_id> \
  --run_id <run_id> \
  --out_root <out_root> \
  --stage full
```

### 阶段入口

- `step1_input_frame`
- `step2_segment`
- `step3_witness`
- `step4_corridor_identity`
- `step5_slot_mapping`
- `step6_build_road`
- `full`

### 脚本入口

- 一键全流程：`scripts/run_t05v2_full_wsl.sh`
- 分阶段执行：`scripts/t05v2_step1_input_frame.sh` 到 `scripts/t05v2_step6_build_road.sh`
- 恢复执行：`scripts/t05v2_resume.sh`

## 参数边界

### 通用参数

- `--data_root`
- `--patch_id`
- `--run_id`
- `--out_root`
- `--stage`
- `--debug`
- `--force`

### 当前稳定运行基线

- Segment / Step2 基线：
  - `--segment_min_drivezone_ratio 0.85`
  - `--step2_strict_adjacent_pairing 1`
  - `--step2_allow_one_intermediate_xsec 0`
  - `--step2_same_pair_topk 1`
  - `--step2_pair_scoped_cross1_exception_enable 0`
- Road / geometry 基线：
  - `--divstrip_buffer_m 0.5`
  - `--road_min_drivezone_ratio 0.85`

### 参数类别

- Segment 候选参数：`segment_*`
- Step2 拓扑与例外参数：`step2_*`
- Witness / corridor / interval 参数：`witness_*`、`interval_*`
- 最终成路与几何 refine 参数：`road_*`、`global_fit_*`、`geometry_refine_*`

说明：完整参数列表以 `src/highway_topo_poc/modules/t05_topology_between_rc_v2/run.py` 为准；本文件只固化稳定分组和当前标准运行基线。

## 示例

### 全流程示例

```bash
python -m highway_topo_poc.modules.t05_topology_between_rc_v2.run \
  --data_root data/synth_local \
  --patch_id 5417632690143239 \
  --run_id t05v2_demo \
  --stage full \
  --debug
```

### 分阶段恢复示例

```bash
bash scripts/t05v2_step1_input_frame.sh --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --debug
bash scripts/t05v2_resume.sh --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --debug
```

## 验收标准

### 最小通过标准

- 主输出文件存在：`Road.geojson`、`metrics.json`、`gate.json`、`summary.txt`
- 对 built case：
  - `gate.json` 应表现为整体通过
  - `metrics.json` 中应能看到 corridor 已收敛、slot 已 resolved、`failure_classification = built`
  - 最终 `Road` 需满足 `DriveZone` / `DivStrip` 相关门控

### 最小失败可解释性标准

- 即使没有最终 `Road`，也应能从 `metrics.json`、`gate.json`、`debug/corridor_identity.json`、`debug/slot_src_dst.geojson`、`debug/reason_trace.json` 判断失败层次。
- 分阶段运行若缺少前序状态或关键产物，应直接报出缺失信息，而不是模糊失败。

### 边界说明

- 本文件描述稳定契约，不替代 `architecture/*` 的高层业务解释。
- 真实运行的 patch 选择、操作顺序与人工判读清单，请读取 `history/REAL_RUN_ACCEPTANCE.md`。
