# 新线程启动任务书（T05 / a8b2255）

## 1. 角色与边界

- 本线程角色是 `T05-DEV`，只负责 `T05 topology_between_rc` 模块的代码实现、问题定位、诊断增强、脚本维护、以及为内网生成可直接执行的命令。
- `T05-DEV` 不是最终业务裁判；最终业务结论以 QA 独立审计和目视结果为准。
- `T05-QA` 独立负责业务审计、目视检查、问题复核，不直接改代码。
- 新线程默认从开发分支 `codex/fix/t05-full-run-residuals@a8b2255` 开始，而不是从 `main` 开始。
- 当前新线程的目标不是回顾历史，而是在继承现有结论的基础上，继续推进 `T05` 的剩余主问题收敛。

## 2. 内外网协作约束（必须新增，写清楚）

- 角色分工
- 内网角色：只负责执行脚本/命令，并把文本结果、`summary.txt`、`metrics.json`、`gate.json`、关键 `debug` 文件名与目视结论回传；不负责业务判断与代码修改。
- 外网 `T05-DEV`：负责开发、修复、脚本维护、debug/metrics 增强、生成内网可执行命令。
- 外网 `T05-QA`：负责独立审计，不直接改代码。

- 外网线程的硬边界
- 外网线程不能访问内网文件系统，不能验证内网命令是否真的执行成功，不能臆测内网结果。
- 外网线程不得反复搜索或猜测内网路径、盘符、命令形式；必须使用项目中已固定的内网路径与执行约定。
- 外网线程不得把“假设的内网状态”写成事实。

- 已知固定路径与环境映射
- 外网仓库根：`/mnt/e/Work/Highway_Topo_Poc`
- 内网仓库根：`/mnt/d/Work/Highway_Topo_Poc`
- 内网数据根：`/mnt/d/TestData/highway_topo_poc_data`
- 内网输出根：`/mnt/d/Work/Highway_Topo_Poc/outputs/_work/t05_topology_between_rc`
- Windows 对应路径：
- `D:\Work\Highway_Topo_Poc`
- `D:\TestData\highway_topo_poc_data`

- 外网线程的行为纪律
- 若需要内网执行，只能输出“可直接复制的 WSL 命令/脚本调用方式”，不得输出模糊描述。
- 若仓库内已存在固定内网脚本，例如 `run_t05_full_wsl.sh` 或其他分步脚本，优先复用；若当前信息无法确认脚本名，则沿用已验证的 Python module 调用方式，不猜测新的脚本路径。
- 若命令依赖特定 `patch_id/run_id`，必须明确写出变量与默认值。
- 若信息不足，不要去猜内网路径；应明确写“沿用已知固定路径”或“等待用户提供新增路径信息”。

- 交接包要求
- 内网 -> 外网：必须优先回传 `run_id`、`patch_id`、`git sha`、`summary.txt`、`metrics.json`、`gate.json`、关键 `debug` 文件名、目视结论。
- DEV -> QA：必须提供标准交接包，不允许只说“修好了/差不多”。

- 明确禁止
- 禁止外网线程反复要求用户确认已经固定的内网路径。
- 禁止外网线程为同一问题多次生成不同风格、不同路径的内网命令。
- 禁止把“内网执行问题”误当成“业务逻辑问题”，反之亦然。

## 3. 模块目标

- 模块名称：`t05_topology_between_rc`
- 目标：基于 patch 内的 `RCSDNode / RCSDRoad / trajectories / road_prior(shape_ref) / DriveZone / lane_boundary` 等输入，构建业务可接受的 `Road.geojson` 与 `RCSDRoad.geojson`。
- `Road` 是最终业务道路输出；`RCSDRoad` 是 RCSD 层道路表达，逻辑应与 `Road` 保持主路径一致，但允许保留更多诊断字段。
- 当前阶段的主要目标不是“继续补 same-pair 数量”，而是收敛剩余 residual case，特别是：
- 主几何 branch/side 归属错误
- merge/diverge 端点业务挂接错误
- 真实闭合未完成
- 少量 `traj surface / closure` 残差

## 4. 输入与硬规则

- 模块级 required 输入
- trajectories
- intersection / xsec / topology 图
- DriveZone
- road_prior / shape_ref 图
- patch 元信息

- 强烈建议输入
- lane_boundary
- 当前默认启用并参与若干 gate 与 endpoint 参考

- optional 输入
- pointcloud
- 当前默认关闭，不是当前主路径依赖

- 当前硬规则
- `target-first` 不回退
- 默认最多允许 `1` 个中间 xsec
- shared sibling 不能互连
- 不做全局 gate 放宽
- 不做 closure 全局放宽
- 不做 same-pair 全局策略重写
- merge/diverge 的业务端点规则必须成立：
- `src=merge`：下一段起点应落在“当前进入 merge 的该条道路在横截线子区域”的中点
- `dst=diverge`：上一段终点应落在“当前退出 diverge 的该条道路在横截线子区域”的中点
- 业务上要求的不只是 endpoint 点靠近 xsec，而是线要真实、连续地闭合到对应 xsec 子区域

## 5. 当前流程分层（Step0/Step1-A/Step1-B/Step2/Step3）

- Step0
- xsec 预处理 / xsec gate / lite repair
- 当前默认 `STEP0_MODE=off`
- 当前全量基线下基本为 passthrough，`xsec_gate` 因 `step0_bypass` 关闭

- Step1-A
- crossing 提取
- `topology_unique` 邻接求解
- target-first neighbor search
- pass1 / pass2 unresolved 搜索
- 当前 full run 中 `neighbor_search_pass2_used=true`，说明 unresolved 拓扑扩展仍然在使用

- Step1-B
- pair support 构建
- `traj_support` 主路径
- `topology fallback support`
- `road_prior / shape_ref fallback`
- same-pair multichain 处理
- 当前 same-pair 已基本收敛，不再是本轮主阻塞

- Step2
- Road 主几何生成
- centerline / road_prior / fallback geometry 生成
- endpoint xsec 选择
- 当前 merge/diverge 端点后处理也在这一层后段执行
- 当前主矛盾集中在这一层：
- 主几何 branch/side 归属
- merge/diverge 业务端点目标求解
- 端点真实闭合

- Step3
- final gate
- 主要包括：
- `ROAD_OUTSIDE_TRAJ_SURFACE`
- `ROAD_OUTSIDE_DRIVEZONE`
- `ROAD_OUTSIDE_SEGMENT_CORRIDOR`
- lane boundary 连续性
- 最终导出 `Road.geojson / RCSDRoad.geojson`
- 当前 residual 大多体现为 Step3 gate，但根因未必在 Step3 本身

## 6. 当前业务口径（必须写最新、不要写过时内容）

- 当前最新业务口径是：
- merge/diverge 的端点问题属于 `Road` 生成后的业务修正问题，但修正目标必须基于“对应道路的横截线子区域”，不能只基于几何最近点。
- QA 目视优先于聚合指标；`endpoint_dist_to_xsec≈0` 不能证明业务正确。
- 业务正确性包含两个条件：
- 端点挂到正确的 xsec 子区域
- 线真实、平滑、连续地闭合到该子区域，而不是只把 endpoint 点拉上去
- 当前 residual 中，`765141 -> 55353246` 是主几何归属错误，不是单纯 endpoint 平滑问题。
- 当前 residual 中，`traj surface` 类失败需要单独分析，不应混入 merge/diverge 端点方案。
- same-pair 历史问题已基本收敛，不再是当前主优先级。

## 7. 当前实现现状（必须写“已经实现了什么、默认主路径是什么、哪些是 fallback”）

- 当前开发基线：`codex/fix/t05-full-run-residuals@a8b2255`
- 当前主路径
- Step1 主邻接模式：`topology_unique`
- 主 support：优先 `traj_support`
- road_prior / shape_ref 主要作为 fallback / 参考，不是全局主过滤器
- `Road` 主几何先生成，再在 Step2 后段做 merge/diverge endpoint business target + refit 后处理
- 最终通过 Step3 gate 导出

- 当前默认状态
- `STEP0_MODE=off`
- `xsec_gate_enabled=false`
- `pointcloud_enabled=false`
- `pointcloud_attempted=false`
- `drivezone_surface` 已在默认路径中替代 pointcloud 供 `surface_points / xsec_barrier` 使用
- `lane_boundary_used=true`
- `road_prior_filter_enabled=false`
- same-pair pair cluster 默认关闭或被 gate 条件关闭

- 当前 fallback
- endpoint xsec 选择大量仍走 `fallback_seed_due_center_empty`
- 少量 pair 使用：
- `road_prior_fallback_entry_xsec`
- `topology_fallback_entry_xsec`
- merge/diverge case 中，当前实现可走：
- `merge_xsec_region_business_refit`
- `diverge_xsec_region_business_refit`

- 当前已经实现但效果有限的逻辑
- merge/diverge endpoint 后处理已从“硬 midpoint snap”演进到“两步式 business target + local refit”
- `traj`、`shape_ref`、`lane_boundary` 已接入 endpoint target/refit 参考
- 仅在 refit 真正成功时，才会更新 `_xsec_target_selected_* / _xsec_road_selected_* / xsec_selected_by_*`
- 但当前实现仍偏“后端补丁”，没有解决主几何 branch/side 归属问题

- 当前与业务口径仍有偏差
- endpoint 后处理可以让很多 endpoint 点数值上贴到 xsec，但不保证：
- 这是业务上对应道路的 xsec 子区域
- 线真实闭合到该子区域
- `765141 -> 55353246` 说明主体 branch/side 归属仍可能错，即使 endpoint 后处理生效也无法根治

## 8. 当前已知问题（按层分类：输入/Step1/Step2/Step3/输出一致性）

- 输入层
- merge/diverge 的“对应道路 xsec 子区域”语义在原始输入中没有直接显式给出，当前仍依赖推断。
- `fallback_seed_due_center_empty` 在全量里仍占大头，说明 pair-level business target 还没有成为普遍主路径。
- pointcloud 虽保留代码分支，但当前默认关闭，本线程未验证 pointcloud-on 路径。
- lane_boundary 可参与 target/refit 参考，但不足以单独解决 branch 归属。

- Step1 问题
- `765141 -> 55353246` 的主几何 branch/side 归属错误没有在 Step1/主几何来源阶段被纠正。
- `UNRESOLVED_NEIGHBOR / target_not_reached_with_intermediate_crossings` 仍存在，是独立 closure/topology 线问题。
- 这些 closure 残差不应与 merge/diverge endpoint 方案混修。

- Step2 问题
- 当前 `business_refit` 已真实应用到若干 road，但 residual 主集合几乎未变，说明这一层的后处理没有击中主因。
- 当前 business target 仍是基于已选 xsec 几何反推，而不是从 branch/side 语义正向求解。
- 当前 refit 仍更像 endpoint 补线，不是真正的主几何重建。
- endpoint 点到 xsec 的距离可以接近 0，但线仍可能没有真实、连续地闭合到目标子区域。

- Step3 问题
- 当前主要 residual：
- `765141 -> 55353246`：`ROAD_OUTSIDE_DRIVEZONE + ROAD_OUTSIDE_SEGMENT_CORRIDOR`
- `791871 -> 37687913`：`ROAD_OUTSIDE_TRAJ_SURFACE`
- `5384367610468452 -> 760239`：`ROAD_OUTSIDE_TRAJ_SURFACE`
- `5384367610468452 -> 23287538`：`ROAD_OUTSIDE_TRAJ_SURFACE`
- `5384392508835506 -> 5384380160805887`：endpoint-single 风格 `ROAD_OUTSIDE_TRAJ_SURFACE`
- `5395717732638194 -> 29626540`：`ROAD_OUTSIDE_TRAJ_SURFACE`
- `6009895341222138987 -> 760243`：近阈值 `ROAD_OUTSIDE_DRIVEZONE`
- 其中只有一部分与 endpoint 方案直接相关，不能混为一类。

- 输出一致性问题
- `Road` 与 `RCSDRoad` 必须保持同一套 endpoint 业务逻辑，不能只在一侧修。
- 当前聚合指标如 `endpoint_dist_to_xsec_p90`、`endpoint_snap_dist_after_p90` 不能代表业务正确性。
- 必须新增或强化“line-to-target-region”级别诊断，而不是只看 point-to-xsec。

## 9. 最近一轮关键结论（必须写出你当前线程已经收敛出的高价值判断）

- 以 `a8b2255` 全量为准，当前两步式 endpoint 后处理已真实生效，但没有解决主问题；不是“代码没跑”，而是“这类后处理本身不对主因”。
- `765141 -> 55353246` 的根因不是 endpoint 平滑，而是主几何 branch/side 归属错误；后处理只能修“怎么挂”，修不了“挂到哪条支路才对”。
- `endpoint_dist_to_xsec≈0` 不等于业务正确；当前缺的是“线与目标 xsec 子区域真实闭合”的校验。
- `traj surface` 残差必须单独开线分析，不应继续和 merge/diverge endpoint 问题混修。
- same-pair 已不再是当前全量主阻塞；不要再把下一轮精力放在 same-pair 上。
- 当前 post-anchor 路线已接近收益上限；新线程应停止继续叠加 `smooth_rebuild / business_refit` 参数。
- 下一轮若继续有效推进，必须把 `765141 -> 55353246` 的 branch/side 归属修正前移到主几何生成阶段；endpoint 后处理只保留为真实闭合辅助器。

## 10. 下一步工作计划（只写 1~3 个最高优先级，不要发散）

- 1. 先单独修 `765141 -> 55353246` 的主几何 branch/side 归属
- 原因：这是当前全量最核心、最能代表“后处理路线失效”的 case；不先解决它，继续调 endpoint 后处理不会有本质提升。
- 方向：在主几何生成前或主几何来源判定阶段，引入 branch-aware 的 `shape_ref / road_prior / pair target xsec / topology role` 约束，纠正 road 应沿哪条支路生长。

- 2. 将 endpoint 后处理降级为“真实闭合器”
- 原因：当前后处理应只负责在主几何已经正确的前提下，保证线真实、连续地闭合到目标 xsec 子区域，而不再承担纠正主体几何归属的职责。
- 方向：重定义验收为：
- 末端线段真实与目标子区域相交
- 最后一段单调逼近目标
- 不反折
- 不显著恶化 `corridor / drivezone`

- 3. 单独开一条 `traj surface / closure` residual 线
- 原因：`791871 -> 37687913`、`5384367610468452 -> 760239`、`5384367610468452 -> 23287538` 这类并非 merge/diverge endpoint 主问题，继续混修会污染判断。
- 方向：独立分析 `traj surface` 与 `target_not_reached_with_intermediate_crossings`，不要与第 1 项同补丁推进。

## 11. Debug / Metrics / Summary 关键文件清单

- `${run_dir}/summary.txt`
- `${run_dir}/metrics.json`
- `${run_dir}/gate.json`
- `${run_dir}/progress.ndjson`
- `${run_dir}/Road.geojson`
- `${run_dir}/RCSDRoad.geojson`
- `${run_dir}/debug/pair_stage_status.json`
- `${run_dir}/debug/` 下与 endpoint / pair / gate 相关的新增调试文件或字段说明
- 新线程每轮至少要读取：
- `summary.txt`
- `metrics.json`
- `gate.json`
- `Road.geojson`
- `RCSDRoad.geojson`
- `debug/pair_stage_status.json`

## 12. 内网 WSL 执行方式（必须包含：
- 一键全流程命令
- 分步骤命令
- 说明哪些步骤可反复重跑）

- 默认变量
- `PATCH_ID=5417632623039346`
- 分支默认：`codex/fix/t05-full-run-residuals`
- 当前开发基线默认：`a8b2255`
- 若仓库内已存在固定脚本如 `run_t05_full_wsl.sh`，优先复用；若脚本名不明确，沿用下列已验证的 Python module 调用方式。

- 一键全流程命令
```bash
cd /mnt/d/Work/Highway_Topo_Poc && \
git fetch origin && \
git checkout codex/fix/t05-full-run-residuals && \
git pull --ff-only origin codex/fix/t05-full-run-residuals && \
git rev-parse --short HEAD && \
PYTHONPATH=src .venv/bin/python -m highway_topo_poc.modules.t05_topology_between_rc.run \
  --data_root /mnt/d/TestData/highway_topo_poc_data/e2e \
  --patch_id 5417632623039346 \
  --debug_dump 1
```

- 分步骤命令
- 1. 同步代码并确认基线
```bash
cd /mnt/d/Work/Highway_Topo_Poc
git fetch origin
git checkout codex/fix/t05-full-run-residuals
git pull --ff-only origin codex/fix/t05-full-run-residuals
git rev-parse --short HEAD
```

- 2. 执行全量运行
```bash
cd /mnt/d/Work/Highway_Topo_Poc
PYTHONPATH=src .venv/bin/python -m highway_topo_poc.modules.t05_topology_between_rc.run \
  --data_root /mnt/d/TestData/highway_topo_poc_data/e2e \
  --patch_id 5417632623039346 \
  --debug_dump 1
```

- 3. 定位最新输出目录
```bash
latest=$(ls -td /mnt/d/Work/Highway_Topo_Poc/outputs/_work/t05_topology_between_rc/* | head -n 1)
run_dir="$latest/patches/5417632623039346"
echo "$run_dir"
```

- 4. 查看核心结果文件
```bash
cat "$run_dir/summary.txt"
cat "$run_dir/metrics.json"
cat "$run_dir/gate.json"
```

- 5. 查看关键进度日志
```bash
tail -n 40 "$run_dir/progress.ndjson"
```

- 6. 查询当前优先 pair 的 `Road/RCSDRoad` 命中
```bash
python3 - <<'PY' "$run_dir"
import json, sys
from pathlib import Path

run = Path(sys.argv[1])
targets = [
    ("765141", "55353246"),
    ("5384392508835506", "5384380160805887"),
    ("791871", "37687913"),
    ("5384367610468452", "760239"),
    ("5384367610468452", "23287538"),
]

for name in ["Road.geojson", "RCSDRoad.geojson"]:
    data = json.loads((run / name).read_text(encoding="utf-8"))
    print(f"\n=== {name} ===")
    for src, dst in targets:
        hits = []
        for ft in data.get("features", []):
            p = ft.get("properties") or {}
            s = str(p.get("src_nodeid", p.get("src", "")))
            d = str(p.get("dst_nodeid", p.get("dst", "")))
            if s == src and d == dst:
                hits.append({
                    "road_id": p.get("road_id"),
                    "hard_reasons": p.get("hard_reasons"),
                    "soft_reasons": p.get("soft_reasons"),
                    "same_pair_resolution_state": p.get("same_pair_resolution_state"),
                })
        print(src, dst, "hits=", len(hits), hits)
PY
```

- 7. 查询 pair-stage 关键状态
```bash
python3 - <<'PY' "$run_dir"
import json, sys
from pathlib import Path

run = Path(sys.argv[1])
pair_stage = json.loads((run / "debug/pair_stage_status.json").read_text(encoding="utf-8"))
targets = {
    ("765141", "55353246"),
    ("5384392508835506", "5384380160805887"),
    ("791871", "37687913"),
    ("5384367610468452", "760239"),
    ("5384367610468452", "23287538"),
}
for p in pair_stage.get("pairs", []):
    key = (str(p.get("src_nodeid")), str(p.get("dst_nodeid")))
    if key in targets:
        print(key, json.dumps(p, ensure_ascii=False))
PY
```

- 哪些步骤可反复重跑
- 第 1 步代码同步：每次换提交或换分支前都可重跑。
- 第 2 步全量执行：每次代码修改后都可重跑。
- 第 3~7 步结果读取与查询：不需要重新跑模型，可对同一个 `run_dir` 反复执行。

## 13. 与 QA 线程的交接要求（开发线程每轮结束后必须给 QA 提供哪些内容）

- 每轮开发结束后，`T05-DEV` 必须向 QA 提供标准交接包，至少包含：
- 分支名
- commit sha
- `run_id`
- `patch_id`
- 内网实际执行命令
- `summary.txt`
- `metrics.json`
- `gate.json`
- `Road.geojson / RCSDRoad.geojson` 对目标 pair 的命中查询结果
- `debug/pair_stage_status.json` 中目标 pair 的关键条目
- 本轮明确改动了哪些规则/逻辑，哪些没有改
- 本轮仍残留的风险与待确认点
- 请求 QA 重点目视检查的 pair 列表

- QA 回传时至少应给开发线程：
- 目视结论
- 哪些 pair 业务上已正确
- 哪些 pair 仍错误
- 错误类型属于：
- 主几何 branch/side 错误
- endpoint 未真实挂接到目标 xsec 子区域
- 视觉平滑性差
- `traj surface / closure` 残差
- 是否发现 `Road` 与 `RCSDRoad` 不一致

- 严禁开发线程只给 QA 说：
- “修好了”
- “应该差不多”
- “指标看着过了”
- 必须提供可以让 QA 复核的标准文本与文件清单
