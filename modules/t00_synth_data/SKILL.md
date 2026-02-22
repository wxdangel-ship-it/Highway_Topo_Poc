# t00_synth_data - SKILL

## 目标
- 生成可复现的 Patch 数据目录 + `patch_manifest.json`，用于外网回归与 CI。
- 支持两类输入来源：`synthetic`（无本地数据依赖）与 `local`（基于本地条带/轨迹目录）。

## 产物结构
每个 Patch：
```
<PatchID>/
  PointCloud/
    *.laz
  Vector/
    LaneBoundary.geojson
    DivStripZone.geojson
    Node.geojson
    intersection_l.geojson
  Traj/
    <TrajID>/
      raw_dat_pose.geojson
      source_traj.gpkg   # 可选：仅在 local + --traj-mode copy 时生成
```

## 运行方式
1) CI/外网（推荐）：synthetic（默认）
```bash
./.venv/bin/python -m highway_topo_poc synth \
  --source-mode synthetic \
  --seed 0 \
  --num-patches 8 \
  --out-dir data/synth
```

2) 本地骨架：local + stub（不落真实点云/轨迹侧车）
- 通过参数或环境变量提供输入目录：
  - `HIGHWAY_TOPO_POC_LIDAR_DIR`：条带目录（子目录名需包含可提取的条带/drive 数字）
  - `HIGHWAY_TOPO_POC_TRAJ_DIR`：轨迹目录（文件名需包含可提取的条带/drive 数字）
```bash
./.venv/bin/python -m highway_topo_poc synth \
  --source-mode local \
  --seed 0 \
  --num-patches 8 \
  --out-dir data/synth_local
```

3) 本地真实（local-real）：local + 点云落盘 + 轨迹侧车 copy
- 点云：
  - `--pointcloud-mode link`：优先使用相对 symlink（推荐，速度快、占用小）
  - `--pointcloud-mode copy`：显式复制（可能很大，谨慎使用）
- 轨迹：
  - `--traj-mode copy`：优先挑选 `gpkg` 并复制到 `Traj/<TrajID>/source_traj.gpkg`
```bash
./.venv/bin/python -m highway_topo_poc synth \
  --source-mode local \
  --pointcloud-mode link \
  --traj-mode copy \
  --seed 0 \
  --num-patches 8 \
  --out-dir data/synth_local_real
```

## 可复现性与清理策略
- determinism：同 `seed` + 同参数 => `patch_manifest.json` 字节级一致（无时间戳等非确定字段）。
- out_dir 已存在：仅清理上一次 synth 产物（8 位纯数字 Patch 目录 + `patch_manifest.json`），不会递归删除上级目录。

## PatchID 提取规则（local）
- 优先匹配 KITTI 风格 `drive_<id>_sync` / `drive_<id>`。
- 否则回退到“文件名/目录名中最长连续数字串”。
- 最终 zero-pad 为 8 位纯数字字符串。
