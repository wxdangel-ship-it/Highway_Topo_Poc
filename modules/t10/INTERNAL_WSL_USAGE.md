# T10 Internal WSL Usage

内网 WSL 默认输入目录：
- Windows: `D:\TestData\highway_topo_poc_data\Intersection\SH`
- WSL: `/mnt/d/TestData/highway_topo_poc_data/Intersection/SH`

默认脚本：
- [scripts/run_t10_sh_manual_mode.sh](E:/Work/Highway_Topo_Poc/scripts/run_t10_sh_manual_mode.sh)

默认参数：
- 默认 `mainnodeid = 12113465`
- 默认输出目录：`outputs/_work/T10/sh_manual_mode`
- 默认跑 base review bundle；若传 `--manual-override`，会继续做 rerun + diff

最短用法：
```bash
bash scripts/run_t10_sh_manual_mode.sh
bash scripts/run_t10_sh_manual_mode.sh --mainnodeids 12113465 12113466
bash scripts/run_t10_sh_manual_mode.sh --manual-override /mnt/d/path/to/override.json
```

override 约定：
- 可传单个 JSON 文件：对所有给定 `mainnodeid` 共用
- 也可传目录：按 `<mainnodeid>.json` 取文件；缺失则该 `mainnodeid` 只跑 base

重点看这些输出：
- 每个 `mainnodeid` 子目录下的 `base/`
- 若有 override，再看 `rerun/` 和 `diff/`
- 根目录或子目录下的 `manifest.json`、`summary.txt`
- 人工复核优先看：
  - `approach_catalog.json`
  - `manual_override.template.json`
  - `review_unknown_movements.json`
  - `review_nonstandard_targets.json`
  - `review_special_profile_gaps.json`

当前明确不支持：
- `formway / bit7 / bit8` 自动识别
- `right_turn_service` 正式规则
- Excel 输出
- lane-level / lane-group

`--compute-buffer-m` 当前只保留为后续几何计算加速参数，不改变输入收口真值或业务规则。
