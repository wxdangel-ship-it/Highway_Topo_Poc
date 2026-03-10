# T05 新线程启动任务书

## 1. 角色与边界

- 本线程是 `T05-DEV` 开发线程，只负责 T05 模块的代码实现、问题定位、诊断增强、可执行命令生成，不负责最终业务裁定。
- `T05-QA` 是独立审计线程，负责目视核验、业务口径确认、回归判断；开发线程不能替代 QA 做最终结论。
- 当前工作范围只限 T05 模块，不扩散到：
  - 输入/CRS 全局口径重构
  - closure 全局放宽
  - gate 全局放宽
  - same-pair 全局策略重写
- 当前代码基线：
  - 分支：`codex/feat/t05-shared-xsec-closure`
  - 最新提交：`e3e58fc`
  - 提交信息：`fix(t05): use gore fallback variable in topology support`
- `e3e58fc` 是在 `99b3448` 基础上的单点运行时修复版；它修复了 topology fallback-support 调用里误用 `patch_inputs.gore_zone_metric` 的 AttributeError，使 `99b3448` 的逻辑可以正常跑起来。
- 开发线程的首要目标不是“让 overall_pass 变 true”，而是优先把目标 case 的阶段和结果拉到业务正确方向。

## 2. 内外网协作约束（必须新增，写清楚）

### 角色分工

- 内网角色：
  - 只负责执行脚本/命令
  - 回传文本结果、`run_id`、`patch_id`、`git sha`、`summary.txt`、`metrics.json`、`gate` 相关文件名、关键 debug 文件名、目视结论
  - 不负责业务判断，不负责代码修改
- 外网 `T05-DEV`：
  - 负责开发、修复、脚本维护、debug/metrics 增强、生成内网可执行命令
- 外网 `T05-QA`：
  - 负责独立审计，不直接改代码

### 外网线程的硬边界

- 外网线程不能访问内网文件系统，不能验证内网命令是否真的执行成功，不能把“假设的内网状态”写成事实。
- 外网线程不得反复搜索或猜测内网路径、盘符、命令形式；必须使用项目中已经固定的内网路径与执行约定。
- 外网线程不得把“内网执行问题”误当成“业务逻辑问题”，反之亦然。

### 已知固定路径与环境映射

- 外网仓库根：`/mnt/e/Work/Highway_Topo_Poc`
- 内网仓库根：`/mnt/d/Work/Highway_Topo_Poc`
- 内网数据根：`/mnt/d/TestData/highway_topo_poc_data`
- 内网输出根：`/mnt/d/Work/Highway_Topo_Poc/outputs/_work/t05_topology_between_rc`
- Windows 对应路径：
  - `D:\Work\Highway_Topo_Poc`
  - `D:\TestData\highway_topo_poc_data`

### 外网线程的行为纪律

- 若需要内网执行，只能输出“可直接复制的 WSL 命令/脚本调用方式”，不得输出模糊描述。
- 当前未确认仓库内存在统一固定脚本如 `run_t05_full_wsl.sh`，因此默认使用明确的 `python -m ...run` 命令；若后续确认已有固定脚本，则优先复用脚本。
- 若命令依赖特定 `patch_id` / `run_id`，必须明确写出变量与默认值。
- 若信息不足，不要猜内网路径；必须写“沿用已知固定路径”或“等待用户提供新增路径信息”。

### 交接包要求

- 内网 -> 外网：
  - 必须优先回传 `run_id`、`patch_id`、`git sha`
  - `summary.txt`
  - `metrics.json`
  - `gate` 相关文件名或说明“本轮无 gate 文件”
  - 关键 debug 文件名
  - 目视结论
- DEV -> QA：
  - 必须提供标准交接包
  - 禁止只说“修好了/差不多”

### 明确禁止

- 禁止外网线程反复要求用户确认已经固定的内网路径
- 禁止外网线程为同一问题多次生成不同风格、不同路径的内网命令
- 禁止把“内网执行失败”直接写成“业务逻辑失败”
- 禁止把“业务逻辑异常”直接写成“内网环境问题”

## 3. 模块目标

- T05 的目标是：在 patch 内，基于 `RCSDNode + RCSDRoad` 的拓扑强证据，结合轨迹支撑，为明确的 `src -> dst` 对构造 Segment 对应的道路连接结果。
- Segment 的业务核心是 `RCSDNode/RCSDRoad`；横截线是端点参考与轨迹穿越参考，不是 Segment 本身。
- 当前阶段只聚焦 3 个关键问题：
  - `23287538 -> 765141`
  - `791873 -> 791871` 的缺失分支
  - `55353246 -> 37687913` 的方向错误问题
- 次级问题 `21779764 -> 785642` 当前不作为主阻塞。

## 4. 输入与硬规则

- 当前主路径 required 输入：
  - `Intersection` / RCSD 相关拓扑输入
  - `Traj`
  - `DriveZone`
- 当前 optional 输入：
  - `DivStrip`（业务上作为 gore / 导流带）
  - `lane_boundary`
  - `road_prior`
  - `tiles_dir`
  - `pointcloud`
- 当前默认轨迹分段参数已经改为：
  - `traj_split_max_gap_m=10`
  - `traj_split_max_time_gap_s=1`
  - `traj_split_max_seq_gap=20000000`
- 当前点云替代现状：
  - 主路径不依赖点云
  - `surface_points`、`xsec_barrier` 默认由 DriveZone 采样面替代
  - 点云代码路径仍保留，但默认不启用
- 不得回退的硬规则：
  - same-pair close-parallel multi-road 方向允许
  - 不优先做全局 gate 放宽
  - 不优先改输入/CRS 口径
  - shared-xsec sibling 不能互连
  - `src -> dst` 必须是显式 target-first 搜索，不能回退到“找下一个 crossing”
- 当前业务硬规则：
  - 默认最多只允许穿越 `1` 个中间横截线后命中最终 `dst`
  - `src=diverge` 或 `dst=merge` 时，端点横截线应向远离节点方向外推，再用导流带/道路面切到真实 branch 路面
- 当前开发中的注意点：
  - 上述“外推再切”逻辑虽然已经实现，但尚未完整前移到主 support 起跟踪入口，新线程必须意识到这一点。

## 5. 当前流程分层（Step0/Step1-A/Step1-B/Step2/Step3）

### Step0

- 负责 xsec gate / truncation / passthrough。
- 当前默认主路径：
  - `Step0: mode=off`
  - `xsec_gate_enabled=false`
  - `xsec_gate_traj_evidence_disabled_reason=step0_bypass`
- 当前不应优先把问题归因到 Step0。

### Step1-A

- 负责 topology unique pair 决策、crossing 提取、target-first support 搜索。
- 当前默认主路径：
  - `step1_adj_mode=topology_unique`
  - `step1_pair_cluster_disabled=true`
  - target-first 搜索已启用
  - shared sibling 过滤已启用
  - 默认最多 `1` 个中间 xsec
- 当前关键缺口：
  - 主 crossing 提取仍从全局 `xsec_cross_map` 出发
  - 不是从 pair-level outward-cut xsec 出发
  - 所以 support 仍可能从错误一侧开始建立

### Step1-B

- 负责 pair endpoint xsec、step1 corridor、shape_ref、cross_point、两端 reach 判断。
- 当前已实现：
  - `src=diverge` / `dst=merge` -> `role_outward_cut`
  - `src=merge` / `dst=diverge` -> `role_full_seed`
  - 已接入 Step1 endpoint/corridor
- 当前限制：
  - 主要影响 Step1 评估
  - 不是所有主 support 起始入口都被这套规则控制

### Step2

- 负责 candidate road geometry / centerline / road prior fallback / same-pair branch variant。
- 当前已有 fallback：
  - `topology_road_prior_fallback`
  - `same_pair road_prior_fallback`
  - same-pair direct geometry fallback
  - corridor-only geometry rescue
- 但这些 fallback 仍不足以等价于“主 support 起始方向已纠正”。

### Step3

- 负责最终 gate、导出、统计。
- 当前主要 gate：
  - `ROAD_OUTSIDE_DRIVEZONE`
  - `ROAD_OUTSIDE_SEGMENT_CORRIDOR`
  - `ROAD_OUTSIDE_TRAJ_SURFACE`
- 最终输出文件：
  - `Road.geojson`
  - `RCSDRoad.geojson`
- 不能只看 `summary.txt` 判断结果，必须回查输出文件和 pair 阶段文件。

## 6. 当前业务口径（必须写最新、不要写过时内容）

- Segment 的强证据来自 `RCSDNode + RCSDRoad`。
- 横截线只是端点参考与轨迹穿越参考，不是 Segment 本体。
- 当前搜索口径已经不是“从 src 找下一个 crossing”，而是“已知 `src -> dst`，只判断是否存在合理 support 连接到明确的 `dst`”。
- 中间横截线允许经过，但业务口径是：
  - 最多只允许经过 `1` 个中间横截线
  - 超过 `1` 个则视为偏离真实 Segment
- 这条规则的业务意义：
  - `23287538 -> 765141` 合法，因为它只应经过 `608638238` 这 `1` 个中间 xsec
  - `55353246 -> 37687913` 当前这种从右侧道路面绕多个路口再回来的路径，业务上不应成立
- 对端点横截线的业务要求：
  - 分歧作为 `src` 时，应往离开节点方向外推，再切到真实 branch 路面
  - 合流作为 `dst` 时，也应往远离节点方向外推，再切到真实汇入路面
  - 理想状态下，support 应从这根切好的横截线开始建立
- shared-xsec group 口径：
  - `(55353307, 23287538)` 是 shared xsec group
  - `55353307 -> 23287538` 这类 sibling-to-sibling 不应进入目标搜索
  - `55353307` 不应与 `765141` 构成 Segment
- 当前关键 case 的业务口径：
  - `23287538 -> 765141` 成立
  - `55353246 -> 37687913` 成立，但必须从正确一侧起始，不能绕右侧再回
  - `791873 -> 791871` 应存在两分支，缺失分支虽无轨迹但有道路面连续性，应能兜底
  - `21779764 -> 785642` 缺失分支因无轨迹且无有效道路面连续性，当前降级处理

## 7. 当前实现现状（必须写“已经实现了什么、默认主路径是什么、哪些是 fallback”）

- 已实现：
  - Traj 分段已进入主流程
  - topology unique pair 解析已稳定
  - target-first 搜索已替代旧的 next-crossing / filtered_non_target_crossing_only
  - shared sibling 过滤已生效
  - pair-level outward-cut xsec 已实现并接入 Step1
  - `pair_target_max_intermediate_xsecs=1` 已实现
  - `traj_surface` cache 稳态正常
- 当前默认主路径：
  - Step0 默认 `off/passthrough`
  - Step1 默认 `topology_unique`
  - pair cluster 默认关闭
  - pointcloud 默认关闭
  - `surface_points` / `xsec_barrier` 主路径由 DriveZone 替代
- 当前 fallback：
  - `topology_road_prior_fallback`
  - `same_pair road_prior_fallback`
  - same-pair direct geometry fallback
  - corridor-only geometry rescue
- 当前默认关闭 / 旁路：
  - Step0 xsec gate 默认旁路
  - pointcloud 默认不启用
  - pair cluster 默认关闭
- 当前与业务口径的核心偏差：
  - pair-level outward-cut xsec 已实现，但没有完整接管主 support 的 crossing 提取入口
  - 因此“横截线切对了”与“support 从正确一侧开始”在当前代码里还不是同一件事
- `e3e58fc` 的作用：
  - 修复 `99b3448` 的运行时字段名回归
  - 使 topology fallback-support 逻辑可执行
  - 不新增新的业务策略

## 8. 当前已知问题（按层分类：输入/Step1/Step2/Step3/输出一致性）

### 输入

- 当前输入主问题不是 traj split 或 CRS，它们已验证通过。
- 当前输入层风险主要是部分业务分支天然缺轨迹，或道路面连续性不足，会限制 fallback 能力。
- 当前不要优先把问题归因到点云缺失。

### Step1

- 主 support/crossing 提取仍从全局 `xsec_cross_map` 出发，而不是从 pair-level outward-cut xsec 出发。
- `23287538 -> 765141` 的已知阶段是：
  - `topology_anchor_status=accepted`
  - `road_prior_shape_ref_available=true`
  - `support_found=false`
  - `selected_or_rejected_stage=support_missing_after_topology`
- 因此这条明确死在 support / fallback-support 层。
- `55353246 -> 37687913` 的方向错误，本质上更像 Step1 起始侧控制不足，而不是“没结果”。
- `pair_target_max_intermediate_crossings=1` 已实现，但 `e3e58fc` 上的最新业务效果仍待重跑确认。

### Step2

- `791873 -> 791871` 当前状态是：
  - `candidate_count=2`
  - `viable_candidate_count=1`
  - `selected_output_count=1`
- 说明第二分支不是没识别，而是在 candidate -> viable / final 之间掉了。
- same-pair fallback 仍未把缺失分支稳定落地。
- `55353246 -> 37687913` 虽然 selected，但几何方向仍可能错误，说明 candidate 成立不等于业务正确。

### Step3

- 最终 gate 仍会拒绝部分候选：
  - `ROAD_OUTSIDE_DRIVEZONE`
  - `ROAD_OUTSIDE_SEGMENT_CORRIDOR`
  - `ROAD_OUTSIDE_TRAJ_SURFACE`
- 但 `23287538 -> 765141` 当前还没到 Step3，不应误判为 final gate 问题。
- `791873 -> 791871` 缺失分支更像 Step2 viable / final 选择问题，不是整体 Step3 问题。

### 输出一致性

- `summary.txt` 只能看 topk，不足以判断某个 pair 是否真的输出。
- 必须直接查：
  - `Road.geojson`
  - `RCSDRoad.geojson`
  - `debug/pair_stage_status.json`
- 查询输出必须用：
  - `src_nodeid`
  - `dst_nodeid`
- 不要再用 `src` / `dst` 判定命中，否则会误判“无结果”。
- “有输出但方向错”不能算修好。

## 9. 最近一轮关键结论（必须写出你当前线程已经收敛出的高价值判断）

- 当前代码里，“分歧作为 src / 合流作为 dst 时，xsec 往远离节点方向外推再切”这套逻辑已经落地，并且已经接进 Step1。
- 但这套逻辑没有完整前移到主 support 起跟踪入口，所以只能部分修正问题。
- `55353246 -> 37687913` 已经有输出，这证明系统能产出该 pair；但方向仍错，说明 support 起始侧仍可能偏到错误一侧。
- `23287538 -> 765141` 不是后段几何问题，而是明确卡在 `support_missing_after_topology`；继续修它应优先在 support / fallback-support 层加诊断和修复。
- `791873 -> 791871` 当前只保住了 `__ch2`；缺失分支 `__ch1` 不是没识别，而是在 candidate -> viable / final 之间掉了。
- shared sibling 污染已清掉，不要回退。
- 轨迹分段、稳态 cache、target-first 搜索方向都已成立，不要再把它们当成当前主根因。
- `e3e58fc` 只是 `99b3448` 的可运行修复版；新线程的第一件事仍然是用 `e3e58fc` 重新完整跑一轮。

## 10. 下一步工作计划（只写 1~3 个最高优先级，不要发散）

- 优先级 1：基于 `e3e58fc` 重跑完整内网结果，并先做 case 级分层确认
  - 原因：必须先验证 `99b3448` 两项策略在可运行版本上的真实效果
  - 核心看：
    - `23287538 -> 765141` 是否仍是 `support_missing_after_topology`
    - `55353246 -> 37687913` 是否仍然方向错误
    - `791873 -> 791871` 是否仍只有 `ch2`

- 优先级 2：如果 `23287538 -> 765141` 仍失败，优先给 `_build_topology_road_prior_fallback_support()` 增加失败原因诊断
  - 原因：这是当前最明确的 support 层未闭合问题，且 `road_prior_shape_ref_available=true`
  - 必须先明确死在：
    - xsec contact
    - reach_xsec
    - drivezone inside_ratio
  - 未明确死因前，不继续盲修 geometry

- 优先级 3：如果 `55353246 -> 37687913` 仍然方向错误，继续把 pair-level outward-cut xsec 前移到主 support / crossing 提取入口
  - 原因：当前实现已经证明 Step1/fallback-support 的前移还不够，主搜索入口仍可能从错误侧开始
  - 这项优先级高于继续扩大 same-pair 放宽，因为它同时影响方向正确性和 `23287538 -> 765141` 的 support 建立

## 11. Debug / Metrics / Summary 关键文件清单

- 运行结果目录：
  - `outputs/_work/t05_topology_between_rc/<run_id>/patches/5417632623039346/`

- 必看文件：
  - `summary.txt`
  - `metrics.json`
  - `Road.geojson`
  - `RCSDRoad.geojson`
  - `debug/pair_stage_status.json`

- 重点 debug 图层：
  - `debug/step1_pair_straight_segments.geojson`
  - `debug/step1_topo_chain_segments.geojson`
  - `debug/step1_support_trajs.geojson`
  - `debug/step1_support_trajs_all.geojson`
  - `debug/step1_corridor_centerline.geojson`

- 每轮至少检查的 metrics 字段：
  - `same_pair_multi_road_output_count`
  - `same_pair_partial_unresolved_pair_count`
  - `no_geometry_candidate_count`
  - `topology_fallback_support_count`
  - `low_support_road_count`
  - `traj_surface_cache_hit_count`
  - `traj_surface_cache_miss_count`
  - `t_build_surfaces_total`

- 每轮必须查询的目标 pair：
  - `23287538 -> 765141`
  - `55353246 -> 37687913`
  - `791873 -> 791871`

## 12. 内网 WSL 执行方式（必须包含：
##    - 一键全流程命令
##    - 分步骤命令
##    - 说明哪些步骤可反复重跑）

### 一键全流程命令

```bash
cd /mnt/d/Work/Highway_Topo_Poc && \
git fetch origin && \
git checkout codex/feat/t05-shared-xsec-closure && \
git pull --ff-only origin codex/feat/t05-shared-xsec-closure && \
git rev-parse --short HEAD && \
PYTHONPATH=src .venv/bin/python -m highway_topo_poc.modules.t05_topology_between_rc.run \
  --data_root /mnt/d/TestData/highway_topo_poc_data/e2e \
  --patch_id 5417632623039346 \
  --debug_dump 1
```

### 分步骤命令

1. 拉取最新代码

```bash
cd /mnt/d/Work/Highway_Topo_Poc
git fetch origin
git checkout codex/feat/t05-shared-xsec-closure
git pull --ff-only origin codex/feat/t05-shared-xsec-closure
git rev-parse --short HEAD
```

预期：
- HEAD 应为 `e3e58fc`

2. 运行 T05

```bash
cd /mnt/d/Work/Highway_Topo_Poc
PYTHONPATH=src .venv/bin/python -m highway_topo_poc.modules.t05_topology_between_rc.run \
  --data_root /mnt/d/TestData/highway_topo_poc_data/e2e \
  --patch_id 5417632623039346 \
  --debug_dump 1
```

3. 找最新 run 目录

```bash
latest=$(ls -td /mnt/d/Work/Highway_Topo_Poc/outputs/_work/t05_topology_between_rc/* | head -n 1)
echo "$latest"
```

4. 查看关键结果

```bash
cat "$latest/patches/5417632623039346/summary.txt"
cat "$latest/patches/5417632623039346/metrics.json"
cat "$latest/patches/5417632623039346/debug/pair_stage_status.json"
```

5. 查询目标 pair 是否实际输出

```bash
python3 - <<'PY' "$latest/patches/5417632623039346"
import json, sys
from pathlib import Path

run = Path(sys.argv[1])
targets = [
    ("23287538", "765141"),
    ("55353246", "37687913"),
    ("791873", "791871"),
]

for name in ["Road.geojson", "RCSDRoad.geojson"]:
    f = run / name
    data = json.loads(f.read_text(encoding="utf-8"))
    print(f"\n=== {name} ===")
    for src, dst in targets:
        hits = []
        for ft in data.get("features", []):
            p = ft.get("properties") or {}
            s = str(p.get("src_nodeid", p.get("src", "")))
            d = str(p.get("dst_nodeid", p.get("dst", "")))
            if s == src and d == dst:
                hits.append((p.get("road_id"), p.get("hard_reasons"), p.get("soft_reasons")))
        print(src, "->", dst, "hits =", len(hits), hits[:10])
PY
```

### 哪些步骤可反复重跑

- 第 2 步运行命令可以反复重跑
- 第 3/4/5 步结果查询可以反复重跑
- 第 1 步拉代码只在远端有新提交时执行，不必每次重复

## 13. 与 QA 线程的交接要求（开发线程每轮结束后必须给 QA 提供哪些内容）

- 每轮开发结束后，必须向 QA 线程提供以下内容，缺一不可：

1. 当前 commit SHA
   - 例如：`e3e58fc`

2. 内网实际运行命令
   - 必须贴完整命令，不要只给 `run_id`

3. 本轮明确关注的目标 case
   - 例如：
     - `23287538 -> 765141`
     - `55353246 -> 37687913`
     - `791873 -> 791871`

4. `summary.txt`
   - 至少提供全文或关键段落

5. `metrics.json`
   - 至少提供关键字段
   - 更推荐直接提供全文

6. `Road.geojson` / `RCSDRoad.geojson` 的目标 pair 查询结果
   - 必须用 `src_nodeid/dst_nodeid`
   - 不能只凭 `summary.txt` 判断“有没有结果”

7. `debug/pair_stage_status.json` 中目标 pair 的对应记录
   - 至少贴出：
     - `23287538 -> 765141`
     - `55353246 -> 37687913`
     - `791873 -> 791871`

8. 本轮开发线程的代码层判断
   - 明确写：
     - 哪个 case 前进了
     - 哪个 case 没变化
     - 当前认为它死在哪一层
   - 不能替代 QA 的业务裁定

9. 需要 QA 重点目视确认的点
   - 例如：
     - `55353246 -> 37687913` 是否仍从错误一侧起始
     - `791873 -> 791871` 是否仍缺一支
     - `23287538 -> 765141` 是否仍完全无输出

10. 如本轮存在回归风险，必须明确提示
   - 包括：
     - shared sibling 污染是否可能回归
     - same-pair 已有正确输出是否可能受影响
     - target-first 搜索是否可能过度截断

- 以上内容用于让 QA 独立完成业务审计；开发线程不得把自己的代码判断直接当作最终业务结论。
