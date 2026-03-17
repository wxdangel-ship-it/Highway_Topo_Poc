# SPEC：高速场景「路网拓扑自动生产」关键技术 POC 需求说明（Highway_Topo_Poc）

- 文档类型：需求规格说明（Specification）
- 项目名称：Highway_Topo_Poc
- 版本：v0.3
- 状态：Draft（供研发 / SE / 项目组评审对齐）
- 交付形态：外网 GitHub 仓库 + 内网执行 + **文本粘贴质检回传**（闭环）
- 基线来源：由 v0.2 演进（更新回传方式与全局工程约束）

---

## 变更记录（v0.3 相对 v0.2）
1) 明确：内网 -> 外网 **仅允许文本粘贴回传**（不可传文件/图片/点云片段）。
2) 明确：外传文本允许 **分位数/误差数值（方案A：p50/p90/p99）**，但尽量只保留摘要。
3) 明确：允许用 **索引化位置（bin 区间）**做问题定位（便于压缩与对比）；文本回传只要求可粘贴（体积可控、结构清晰）。
4) 明确：子模块接口契约（INTERFACE_CONTRACT）放到子 Agent / 子目录内，不在本 SPEC 全局冻结细节字段。
5) 新增：工作目录约束 —— 项目需放在 Windows E: 盘（WSL 下通常为 `/mnt/<drive>/...`）。

---

## 目录
1. 项目概述  
2. 目标与成功标准  
3. 范围与非目标  
4. 关键约束与假设  
5. 双环境协作闭环与工件化协议  
6. 交付物清单（外网/内网）  
7. 术语与统一定义  
8. Patch 数据接口规范（现状 + POC 标准化要求）  
9. 标准化报告与文本质检包规范（必须遵守，文本粘贴）  
10. 模块目录与代码组织要求（按关键技术点分目录）  
11. 五个关键技术点：验证问题 / 输入输出 / 质检报告 / 文本回传  
12. 配置、运行、可复现与审计要求  
13. 测试、回归与合成数据要求（外网侧）  
14. 隐私与脱敏要求（内网侧）  
15. 风险、依赖与待澄清项（TBD）  
16. 附录：示例配置与报告骨架（可粘贴/体积可控）

---

## 1. 项目概述

~~~~~~### 1.1 项目目标~~~~~~
在高速场景下，对「路网拓扑自动生产」相关关键技术做 POC 论证，并对若干关键内部能力做质量验收（Quality Acceptance）。

本次 POC 聚焦 5 个关键技术点（t01–t05），并要求外网提供可回归的合成数据能力（t00）：
- t01 点云标量融合质量（参差区间识别）
- t02 地面点云分割质量（POC 自研，后续可 skill 化复用；覆盖地面点分类 + Traj 纵向/横截 QC）
- t03 标线实体化聚合（已退役，仅保留历史技术点引用）
- t04 RC 路口与 SW 路口锚定识别（细节接口契约放子 Agent）
- t05 RC 路口间拓扑生产（当前正式模块为 `t05_topology_between_rc_v2`；legacy `t05_topology_between_rc` 仅作历史参考）
- t00 合成/模拟数据生成（外网回归用；可注入可控异常）

当前阶段模块状态：
- Frozen（不再演进）：`t00_synth_data`、`t01_fusion_qc`、`t02_ground_seg_qc`
- Core（已通过测试数据验证，已上传基线版本）：`t04_rc_sw_anchor`、`t05_topology_between_rc_v2`
- New（仅定义契约与目录骨架，暂不实现逻辑）：`t06_patch_preprocess`、`t07_patch_postprocess`
- Legacy（历史参考）：`t05_topology_between_rc`
- Retired（已退役）：`t03_marking_entity`、`t10`

### 1.2 关键业务背景（全局认知）
- RC/SW 是两套不同数据：
  - 高精度矢量：精度高但资料缺失
  - 普通矢量：覆盖多，但挂接工艺与真实分歧点可能存在较大偏差（可达 100m+；具体策略在子 Agent 中进一步确认）
- 锚点：现实世界路口（高速下多为分歧/合流），以物理分割前后的导流带尖（gore tip）作为横截面参考
- 外传任何信息以“文本粘贴”回传为准；定位建议用 bin 区间/Top-K 摘要等紧凑表达（坐标/路径等可出现，但需控制体积）

---

## 2. 目标与成功标准

### 2.1 POC 成功标准（可跑 / 可诊断 / 可迭代）
必须满足：
- 闭环可跑：外网提交 GitHub 版本 → 内网下载执行 → 内网回传文本质检包 → 外网基于文本归因与迭代建议
- 接口可用：内网按标准接口输出 Patch 数据与（可选）内网产物；外网可用合成数据模拟
- 可诊断：每个技术点必须输出分位数、异常区间统计、失败原因枚举；外网仅凭文本可定位问题类型与大致发生位置（建议用 bin 区间/Top-K 摘要等紧凑表达）
- 可配置：阈值/参数不冻结，但必须配置化、记录在报告/文本摘要中
- 可审计：记录运行版本/配置摘要/输入类型与分辨率等元信息，支持回归对比与追溯

### 2.2 最小可验收范围（MVP）
- 每个技术点至少在 1–2 个最小样例 patch 上跑通
- 至少包含：失败场景 patch（含错误类型/区间描述）与正确场景 patch（对照）

---

## 3. 范围与非目标

### 3.1 范围（包含）
- 五个技术点独立模块与可串联流水线
- Patch 数据接口与标准化报告协议（schema）
- 内网文本质检包回传与外网迭代机制
- 外网合成数据生成器与回归测试（必须）

### 3.2 非目标（不包含）
- 不冻结生产阈值与参数（只要求可配置、可回归、可审计）
- 不要求覆盖全部高速结构，仅以 RC/SW 场景牵引
- 不在全局文档冻结子模块 INTERFACE_CONTRACT（放子 Agent）

---

## 4. 关键约束与假设

### 4.1 双环境能力差异
- 外网：强推理/强编码，但无法触达真实内网数据
- 内网：可跑真实数据，但尽量减少开发量（以 Provider/中间格式适配为主）

### 4.2 回传通道硬约束（v0.3 新增强调）
- 内网 -> 外网：仅允许文本粘贴回传
- 因此：所有问题定位必须“文本化、短小、结构化”；必须考虑一次性粘贴大小

### 4.3 脱敏与安全假设
- 内网回传外网的任何内容必须可文本粘贴传递：体积可控、结构化、避免超长 raw dump（坐标/几何/路径等可出现，但需控制体积）
- 回传允许：统计分位数、区间长度占比、匿名 ID、失败原因枚举、候选排序摘要、输入类型/分辨率等元信息
- 允许使用索引化位置（bin 区间）辅助定位（见第 9 章）

---

## 5. 双环境协作闭环与工件化协议

### 5.1 总体闭环
外网负责：
- 工程实现（五模块 + common）、合成数据模拟、单测/回归、结果解析与改进建议
- 交付：GitHub 仓库代码 + 文档 + schema + 合成数据生成器 + 运行脚本

内网负责：
- 按标准接口提供 Patch 数据或 Provider 适配层
- 下载 GitHub 代码执行全链路或分模块
- 产出文本质检包并粘贴回传外网（脱敏）

### 5.2 运行时“工件化”要求（内网本地）
说明：内网可以生成本地文件用于内部排查，但外传只能粘贴文本摘要。
- report.json（用于内网自查；字段不限制；外传仅粘贴文本摘要）
- artifact_index.json（脱敏）
- text_bundle（脱敏摘要，用于人工粘贴或粘贴前再压缩）

---

## 6. 交付物清单（外网/内网）

### 6.1 外网交付（GitHub 仓库）
- modules/t00_synth_data/（本地合成/模拟测试数据生成；用于外网回归与 CI）
- modules/t01_fusion_qc/ ... modules/t05_topology_between_rc_v2/（当前正式技术点目录）
- modules/t05_topology_between_rc/（legacy 历史参考目录，继续保留）
- common/（公共库：统计、schema 校验、文本摘要导出等）
- schemas/（report 与 text bundle 的 JSON Schema）
- configs/（示例 pipeline 配置、patch 清单样例）
- scripts/（一键运行脚本/命令）
- tests/（单测 + 合成数据回归 + golden 文本输出对比）
- 文档：README、每模块 AGENTS.md / SKILL.md
- 合成数据生成能力（归属 modules/t00_synth_data/；用于外网回归与 CI）

### 6.2 内网每次运行（本地产物 + 外传文本）
- 本地产物：outputs/<run_id>/...（report/json 等，用于内网自查）
- 外传：按第 9 章规范输出的 TEXT_QC_BUNDLE（文本粘贴）

---

## 7. 术语与统一定义（最小集合）
- Patch：最小实验/处理单元（一个地理/时间范围内的数据包）
- 标量（scalar）：沿里程或时间的单调量，用于对齐轨迹/报告采样轴
- 分位数：p50/p90/p99（方案A）
- 异常区间：沿标量轴连续超阈区间（外传推荐用 bin 区间/Top-K 区间摘要等紧凑表达）
- bin 区间：将标量轴离散化后的索引区间，用于紧凑定位（可与坐标并存）

---

## 8. Patch 数据接口规范（现状 + POC 标准化要求）

### 8.1 现状：内网原始 Patch 目录结构（已确认）
<PatchID>/
  PointCloud/
    *.laz
  Vector/
    LaneBoundary.geojson
    DivStripZone.geojson
    RCSDNode.geojson
    intersection_l.geojson
    RCSDRoad.geojson
  Tiles/
    <z>/<x>/<y>.<ext>
  Traj/
    <TrajID>/
      raw_dat_pose.geojson

### 8.2 POC 标准化要求（由 Provider 标准化到统一结构）
- 不强制内网修改原始目录；Provider 可运行时读取原始数据并生成标准对象
- 标准对象字段名与文件格式由实现落地，但必须保证：
  - 轨迹：至少包含顺序信息（t 或 seq）与 Z 可用（用于 t01/t02）
  - 点云：至少 Z 可用；若缺标量轴，允许派生（必须在报告记录派生策略）
  - 矢量：可读取为要素集合（不要求原始即实体化）

### 8.3 Patch Vector 标准产物摘要（v4）
- `LaneBoundary.geojson`：车道边界（LineString FeatureCollection）
- `DivStripZone.geojson`：导流带信息（v2 标准命名）
- `RCSDNode.geojson`：路口 Node 点信息（Point FeatureCollection）
  - `properties.Kind`：`int32`（bit0=无属性，bit2=交叉路口，bit3=合流路口，bit4=分歧路口）
  - `properties.mainid`：`int64`（路口主 nodeid，同值为一组）
  - `properties.id`：`int64`（当前 node 的 id）
- `intersection_l.geojson`：分歧/合流路口横截线（LineString FeatureCollection）
  - `properties.nodeid`：`int64`（对应主 node 的 id）
- `RCSDRoad.geojson`：历史路网先验矢量（LineString FeatureCollection，可为空）
  - `properties.direction`：`int8`
    - `0`：未调查（默认按双方向处理）
    - `1`：双向
    - `2`：顺行
    - `3`：逆行
  - `properties.snodeid`：`int64`（起点 `nodeid`）
  - `properties.enodeid`：`int64`（终点 `nodeid`）
- 仍保留：`LaneBoundary/DivStripZone/RCSDNode/intersection_l`；不允许回退到旧版导流带命名。
- 兼容期说明：读取侧可兼容旧版 Node/Road 别名，但标准产出必须使用 `RCSDNode.geojson`/`RCSDRoad.geojson`。
- `Tiles/`：卫星瓦片输入目录（XYZ tiles）
  - 结构：`Tiles/<z>/<x>/<y>.<ext>`，`ext` 推荐 `png/jpg/webp`，实现需兼容常见后缀。
  - 当前阶段目录可为空，但 `Tiles/` 目录必须存在。
- 说明：主文档仅维护标准与产物摘要；模块实现细节与字段严格约束以 `modules/<module>/INTERFACE_CONTRACT.md` 为准。

---

## 9. 标准化报告与文本质检包规范（必须遵守）

### 9.1 内网本地文件（用于内网自查）
- report.json：完整诊断报告（脱敏）
- artifact_index.json：工件索引（脱敏）
- 允许本地保留更详细信息；外传文本以可粘贴性为准，避免超长 raw dump

### 9.2 外传文本（唯一允许回传形式）
- 外传只允许文本粘贴
- 外传模板与大小控制详见：docs/ARTIFACT_PROTOCOL.md（全局协议）
- 必须支持：
  - Metrics：p50/p90/p99 + threshold（方案A）
  - Intervals：bin 区间 + Top-K + 总长度占比
  - Errors/Breakpoints：失败原因枚举与人工复核断点枚举
  - Params：关键阈值参数（Top-N）

---

## 10. 模块目录与代码组织要求
- 每个技术点/流程阶段一个模块目录（当前 `t00–t07`）
- 子模块的接口契约（INTERFACE_CONTRACT.md）放在各自模块目录中，由子 Agent 阶段产出
- 模块实现代码放在 `src/highway_topo_poc/modules/<module_id>/`，`modules/<module_id>/` 仅承载模块文档与接口契约
- 模块文档最小集合：`AGENTS.md` / `SKILL.md` / `INTERFACE_CONTRACT.md`（README 非必需）
- `INTERFACE_CONTRACT.md` 章节顺序统一：`Inputs` / `Outputs` / `EntryPoints` / `Params` / `Examples` / `Acceptance`
- `modules/<module_id>/` 不放 `.py` 实现；实现由 `src/highway_topo_poc/modules/<module_id>/` 承载
- common/schemas/configs/scripts/tests 保持清晰分层
- 所有阈值参数必须配置化

模块目录树（概览）：
```text
modules/
  t00_synth_data/
  t01_fusion_qc/
  t02_ground_seg_qc/
  t04_rc_sw_anchor/
  t05_topology_between_rc/        # legacy 历史参考
  t05_topology_between_rc_v2/     # 当前正式 T05
  t06_patch_preprocess/
  t07_patch_postprocess/
  t10/                            # 已退役历史模块
```

---

## 11. 关键技术点与流程模块（摘要级要求）
说明：本章只给全局“要回答的问题与回传要求”，子模块细节接口契约由子 Agent 冻结。

### 11.1 t01 参差区间识别
- 回传必须包含：残差分位数（p50/p90/p99）、参差区间数量/长度占比、Top-K 区间（bin）、类型枚举（bias/drift/jump 等）

### 11.2 t02 地面点云分割质量（POC 自研，后续可 skill 化复用）
- 目标：在真实点云 + 轨迹上完成“地面点分类 + Traj 纵向（clearance）QC + Traj 横截（cross-track）QC”，并提供可解释质量门禁 `overall_pass`，支持自动自检（`auto_tune` 至 PASS）。
- 输入：
  - PointCloud（LAS/LAZ/NPZ/NPY/CSV 等，至少 XYZ；若 LAS/LAZ 可读取 classification）
  - Trajectory（GeoJSON/CSV/NPY 等，至少 XYZ；可选 heading/时间/seq）
- 核心产出：
  - 地面点分类（ground / non-ground）：优先使用 LAS/LAZ classification==2；不足时回退到网格 DEM 低分位 + 带宽阈值的确定性规则。
  - Traj 纵向（clearance）QC：`residual = traj_z - ground_z`，输出 p50/p90/p99、bias、outlier_ratio、coverage、异常区间 Top-K。
  - Traj 横截（cross-track）QC：以轨迹切向为 forward、法向为 cross，对 ground points 做横截 profile/拟合残差统计，输出 xsec 指标与异常区间 Top-K。
  - 质量门禁与自检：输出 `overall_pass`；若 FAIL 可选启用 `auto_tune`，记录 `chosen_config` 与 `tune_log`，保证可追溯/可复现。
- 输出工件（高层）：
  - `metrics.json`（含 ground/xsec/clearance 指标与 `overall_pass`）
  - `intervals.json`（clearance 异常区间）
  - `xsec_intervals.json`（横截异常区间）
  - `ground_points.npy` + `ground_idx.npy`（地面点结果/索引）
  - `summary.txt`（可文本粘贴摘要）
  - `chosen_config.json` + `tune_log.jsonl`（启用 `auto_tune` 时）
- 边界/非目标：
  - t02 是质量检查与可解释输出，不是高精地图生产，也不替代模型训练/推理。
  - t02 不修改其它模块接口，不引入跨模块耦合。
  - t02 对外接口与详细键值以 `modules/t02_ground_seg_qc/INTERFACE_CONTRACT.md` 为准，主文档仅描述范围与产物摘要。

### 11.3 t03 标线实体化（导流带，已退役）
- 本技术点已退役，保留本节仅用于解释历史文档、历史报告与旧配置。
- 不再作为当前活跃模块要求。

### 11.4 t04 锚点识别（RC/SW）
- 回传必须包含：RC/SW 锚点计数、置信度摘要、触发人工复核原因
- 位置表达：推荐用 bin 区间（便于压缩与对比）

### 11.5 t05 拓扑生产
- 当前正式模块：`t05_topology_between_rc_v2`
- legacy 历史参考模块：`t05_topology_between_rc`
- 回传必须包含：Road/Node 数量、smoothness/centered 分位数、断头率/孤立比例/自交计数、短辫折叠摘要

### 11.6 t06_patch_preprocess（新增）
- 模块定位：Patch 预处理，先筛选当前 Patch 的 `RCSDNode/RCSDRoad`，再对 Patch 边缘 Road 做预处理并构建边缘虚拟 Node。
- 输入摘要：`RCSDNode`、`RCSDRoad`、`DriveZone`（路径通过参数给定，命名口径与 `t04` 对齐）。
- 输出摘要：Patch 级 `RCSDNode`（含边缘打断/虚拟 Node）与 Patch 级 `RCSDRoad`。
- 状态：当前仅冻结契约与目录骨架；实现逻辑后续由子 Agent 推进。

### 11.7 t07_patch_postprocess（新增）
- 模块定位：Patch 后处理，基于二层路网拓扑要求对上游产物做完整性校验与处理。
- 输入摘要：Patch 级 `RCSDNode/RCSDRoad` + `Road`（t05 产物）+ `intersection_l`（t04 产物）。
- 输出摘要：最终交付层 `Node/Road/intersection_l`。
- 状态：当前仅冻结契约与目录骨架；实现逻辑后续由子 Agent 推进。

---

## 12. 配置、运行、可复现与审计要求
- 记录：module_version、schema_version、配置摘要（digest）、随机种子（如涉及随机）
- 支持：按模块运行、按 patch 列表批量运行、失败不中断（可配置）
- 运行环境：WSL + Python
- 工作区约束：项目必须放在 Windows E: 盘（WSL 下通常 `/mnt/<drive>/...`）；外传文本只要求可粘贴（体积可控）

### 12.1 整 Patch 端到端验证计划（当前冻结）
- 当前阶段先按单 Patch、分模块顺序执行：`t06_patch_preprocess -> t04_rc_sw_anchor -> t05_topology_between_rc_v2 -> t07_patch_postprocess`。
- 待单 Patch 路径稳定后，再新增批处理编排模块（本任务不创建该模块）。

---

## 13. 测试、回归与合成数据要求（外网侧）
外网必须提供：
- 合成数据生成器（modules/t00_synth_data/；用于外网回归与 CI）：可注入可控异常（参差/偏置/跳变/碎片化/错并/漏并/锚点缺失等）
- 单测：schema 校验、文本回传体积控制、可粘贴性守卫
- 回归：合成数据 golden 文本对比（仅文本）

---

## 14. 隐私与脱敏要求（内网侧）
外传回外网的内容要求：
- 仅文本粘贴回传
- 体积可控：<=120 行 或 <=8KB（超限截断并标记）
- 避免超长 raw dump；必要时 Top-K/摘要

---

## 15. 风险、依赖与待澄清项（TBD） 风险、依赖与待澄清项（TBD）
- RC/SW 的业务定义细化与牵引清单（子 Agent 冻结）
- 普通矢量与真实分歧点的偏差修正策略（子 Agent 冻结）
- LaneBoundary / DivStripZone / Node / intersection_l 字段体系细化（子 Agent 冻结）
- 内网地面分割成熟能力复用方式（后续 skill 化）

---

## 16. 附录：示例配置骨架（可粘贴/体积可控）
（示例仅展示结构；字段名由实现最终落地）

run:
  run_id: "2026-02-15_01"
  output_dir: "outputs/${run.run_id}"
  seed: 42

provider:
  type: "file_patch"
  data_root: "${DATA_ROOT}"      # 由运行环境注入；外传文本建议使用变量化路径
  patch_manifest: "configs/patch_list.json"

modules:
  t01_fusion_qc:
    enabled: true
    params:
      interval_min_len: 10.0

  t02_ground_seg_qc:
    enabled: true
    params:
      z_diff_threshold: 0.20

  t03_marking_entity:
    enabled: false   # retired historical module

  t04_rc_sw_anchor:
    enabled: true

  t05_topology_between_rc_v2:
    enabled: true

  t06_patch_preprocess:
    enabled: false
    params:
      drivezone_path: "<path or Vector/DriveZone.geojson>"

  t07_patch_postprocess:
    enabled: false
    params:
      topo_ruleset: "L2_default"
