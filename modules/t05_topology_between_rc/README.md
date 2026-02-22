# t05_topology_between_rc

## 模块目标
基于 `intersection_l`、轨迹、分类点云和 `LaneBoundary`，生成 RC 路口之间的有向 `Road` 中心线，并输出可解释的质量产物：
- `Road.geojson`
- `metrics.json`
- `intervals.json`
- `summary.txt`
- `gate.json`

## 目录
- 文档/契约：`modules/t05_topology_between_rc/`
- 实现：`src/highway_topo_poc/modules/t05_topology_between_rc/`

## 运行方式
单 patch：
```bash
python3 -m highway_topo_poc.modules.t05_topology_between_rc.run \
  --data_root data/synth_local \
  --patch_id 00000003 \
  --run_id auto \
  --out_root outputs/_work/t05_topology_between_rc
```

参数覆写（示例）：
```bash
python3 -m highway_topo_poc.modules.t05_topology_between_rc.run \
  --data_root data/synth_local \
  --patch_id 00000003 \
  --xsec_min_points 80 \
  --min_support_traj 1
```

批量冒烟（2-3 patch）：
```bash
python3 scripts/run_t05_topology_between_rc_smoke.py
```

## 输出路径
默认：
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/Road.geojson`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/metrics.json`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/intervals.json`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/summary.txt`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/gate.json`

## 实现要点
1. 统一 CRS 到米制（地理坐标自动投影到 UTM）。
2. 用轨迹穿越 `intersection_l` 抽取事件并构建有向相邻对 `A->B`。
3. 用 `Node.Kind` 或图度数推断 `diverge/merge/unknown`。
4. 中心线生成：
- 优先找贯通 `A-B` 的 `LaneBoundary` 作为 `shape_ref`。
- 点云横截估计中心偏移（P05/P95 中点），平滑后应用 50m 稳定区规则。
- 与 `A/B` 横截线相交截断，保证端点落在横截线。
5. 输出 hard/soft 断点与 gate。

## 结果解释
- `overall_pass=false` 表示出现 hard 异常或硬门禁失败，但产物仍会输出，便于定位。
- `intervals.json` 提供 Top-K 断点列表。
- `summary.txt` 为可粘贴摘要，内含参数摘要、hard/soft Top-K。

## 已知注意事项
- 若数据为 stub（空 `intersection_l`、无有效轨迹穿越、无有效点云），模块会输出完整产物并在 `summary/intervals` 给出明确失败原因。
- 点云类别若不可用，会回退到 bbox 内全部点做中心估计（并可能触发 `SPARSE_SURFACE_POINTS`）。
