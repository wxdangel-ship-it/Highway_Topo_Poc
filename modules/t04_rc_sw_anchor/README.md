# t04_rc_sw_anchor

> 本文件是 T04 的操作者总览与运行入口说明。长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准；如本文件与长期源事实表述不一致，以后者为准。

## 1. 模块定位

- 面向 `merge/diverge` 与 `K16(kind&65536!=0)` 节点，输出锚点与最终横截线 `intersection_l_opt`。
- 采用 `DriveZone-first` 作为主触发证据链。
- 采用 `Between-Branches(B)` 作为常规扫描口径。
- 在 stop 范围内找不到可信 split 时直接 `FAIL`，不允许跨路口追远处导流带补答案。

## 2. 运行入口

CLI 入口：

```bash
python -m highway_topo_poc.modules.t04_rc_sw_anchor --help
```

## 3. 常见运行方式

### `global_focus`

- 适用于已知 patch 与 focus 节点集合的单次或批量运行。
- 需要 `patch_dir`、`global_node_path`、`global_road_path` 与 `focus_node_ids`。

### `patch`

- 适用于从 patch 目录解析局部输入的运行方式。
- 具体参数仍以 `INTERFACE_CONTRACT.md` 和 CLI 为准。

### patch 自动发现节点

- 入口：`scripts/run_t04_patch_auto_nodes.sh`
- 作用：从 patch 下节点图层自动解析可处理节点，再复用既有主链路。
- 说明：它只改变“入口与节点来源”，不改变模块核心算法链路。

### 批处理

- 入口：`modules/t04_rc_sw_anchor/scripts/run_t04_batch_wsl.sh`
- 作用：按 cases manifest 批量运行 `global_focus`。
- 说明：它是操作者脚本，不替代模块契约和长期源事实。

## 4. 输出总览

输出根目录：

```text
outputs/_work/t04_rc_sw_anchor/<run_id>/
```

关键产物包括：

- `intersection_l_opt*.geojson`
- `intersection_l_multi.geojson`
- `anchors.json`
- `metrics.json`
- `breakpoints.json`
- `summary.txt`
- `chosen_config.json`

## 5. 操作者应优先关注的结果

- 先看 `summary.txt` 与 `breakpoints.json`，判断总体通过与失败原因。
- 再看 `anchors.json`，理解触发来源、split、stop 与特殊规则诊断。
- 最后看 `intersection_l_opt*.geojson` 与 `intersection_l_multi.geojson`，确认几何结果是否符合预期。

## 6. 文档阅读顺序

如果需要理解“模块是什么、为什么这样做”，按以下顺序：

1. `architecture/01-introduction-and-goals.md`
2. `architecture/04-solution-strategy.md`
3. `architecture/05-building-block-view.md`
4. `INTERFACE_CONTRACT.md`
5. 如需复用流程或治理 SOP，先读 repo root `.agents/skills/t04-doc-governance/SKILL.md`，详细检查点再读对应 `references/README.md`

如果只需要运行模块，本文件与脚本说明通常已足够。
