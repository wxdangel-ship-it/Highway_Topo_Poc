# T10 Internal WSL Usage

内网 WSL 运行时，请显式传入：
- `--dataset-dir`
- `--mainnodeid`

推荐脚本：
- [scripts/run_t10_sh_manual_mode.sh](E:/Work/Highway_Topo_Poc/scripts/run_t10_sh_manual_mode.sh)

已知内网数据目录示例：
- Windows: `D:\TestData\highway_topo_poc_data\Intersection\SH`
- WSL: `/mnt/d/TestData/highway_topo_poc_data/Intersection/SH`

先更新主干，再运行：

```bash
cd /mnt/e/Work/Highway_Topo_Poc
git fetch origin --prune
git switch main
git pull --ff-only origin main
```

最小执行：

```bash
cd /mnt/e/Work/Highway_Topo_Poc
bash scripts/run_t10_sh_manual_mode.sh \
  --dataset-dir /mnt/d/TestData/highway_topo_poc_data/Intersection/SH \
  --mainnodeid 12113465
```

多个 `mainnodeid`：

```bash
cd /mnt/e/Work/Highway_Topo_Poc
bash scripts/run_t10_sh_manual_mode.sh \
  --dataset-dir /mnt/d/TestData/highway_topo_poc_data/Intersection/SH \
  --mainnodeid 12113465 12113466
```

带 override：

```bash
cd /mnt/e/Work/Highway_Topo_Poc
bash scripts/run_t10_sh_manual_mode.sh \
  --dataset-dir /mnt/d/TestData/highway_topo_poc_data/Intersection/SH \
  --mainnodeid 12113465 \
  --manual-override /mnt/d/path/to/12113465.json \
  --output-root /mnt/e/Work/Highway_Topo_Poc/outputs/_work/T10/sh_manual_mode_real
```

override 约定：
- 可传单个 JSON 文件，对所有给定 `mainnodeid` 共用
- 也可传目录，按 `<mainnodeid>.json` 取文件；缺失则该 `mainnodeid` 只跑 base

重点查看这些输出：
- 每个 `mainnodeid_*` 子目录下的 `base/`
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
