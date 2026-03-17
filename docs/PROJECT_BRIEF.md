# Highway_Topo_Poc - Project Brief (Global)

## 1. 项目目标
在高速场景下，对「路网拓扑自动生产」关键技术点做 POC 验证，并形成可运行、可诊断、可迭代的双环境闭环：
- 外网：开发与回归（含合成数据）
- 内网：跑真实数据并以“文本粘贴包”回传质检结果

## 2. POC 范围（t00–t07）
- t01：点云标量融合质量（参差区间识别）
- t02：地面点云分割质量（已退役；保留历史实现与文档）
- t03：标线实体化聚合（已退役，仅保留历史技术点引用）
- t04：RC/SW 路口锚点识别（细节放子 Agent）
- t05：RC 路口间拓扑生产（当前正式模块为 `t05_topology_between_rc_v2`；legacy `t05_topology_between_rc` 仅作历史参考）
- t00：合成/模拟测试数据生成（`modules/t00_synth_data/`；用于外网回归与 CI）
- t06：Patch 预处理（仓库已有实现与正式文档面）
- t07：Patch 后处理（已退役；保留历史实现与文档）

## 2.1 Patch Vector 标准（摘要）
- `LaneBoundary.geojson`
- `DivStripZone.geojson`（导流带标准图层）
- `RCSDNode.geojson`（Point FeatureCollection）
  - `properties.Kind`: int32（bit0=无属性，bit2=交叉路口，bit3=合流路口，bit4=分歧路口）
  - `properties.mainid`: int64
  - `properties.id`: int64
- `intersection_l.geojson`（LineString FeatureCollection）
  - `properties.nodeid`: int64
- `RCSDRoad.geojson`（历史路网先验；`direction:int8`、`snodeid:int64`、`enodeid:int64`）
- `Tiles/`（卫星瓦片先验目录，XYZ 组织：`Tiles/<z>/<x>/<y>.<ext>`；当前阶段可空但目录必须存在）
- 主文档只维护标准与产物摘要；模块级接口细节以 `modules/<module>/INTERFACE_CONTRACT.md` 为准。

补充：`Vector/RCSDRoad.geojson` 与 `Tiles/` 作为历史矢量与卫星输入，供 `t04_rc_sw_anchor` 优化阶段使用。

## 3. 关键业务背景（全局认知）
- RC/SW 是两套不同数据：
  - 高精度矢量：精度高但资料缺失
  - 普通矢量：覆盖多，但与真实分歧点可能偏差 100m+
- 锚点：现实世界路口（高速下多为分歧/合流），以物理分割前后的导流带尖（gore tip）作为横截面参考
- 注意：外传仅允许文本粘贴回传；核心是体积可控与结构清晰，避免超长 raw dump

## 4. 成功标准（MVP）
- 工程可跑：至少 1–2 个 patch（含失败与正确对照）全链路可跑（或分模块可跑）
- 可诊断：外网仅凭内网回传的「文本粘贴包」可定位问题类型与大致发生位置
- 可回归：外网侧有合成数据与测试，保证迭代不回退

## 5. 非目标（本阶段不做）
- 不冻结生产级阈值与参数（但必须配置化记录）
- 不在全局文档冻结子模块接口契约（`INTERFACE_CONTRACT` 在子 Agent 阶段完成）

## 5.1 当前模块与执行摘要
- 当前活跃模块：`t04_rc_sw_anchor`、`t05_topology_between_rc_v2`、`t06_patch_preprocess`
- 历史参考模块：`t05_topology_between_rc`
- 已退役模块：`t02_ground_seg_qc`、`t03_marking_entity`、`t07_patch_postprocess`、`t10`
- 仓库保留的支撑 / 测试模块：`t00_synth_data`、`t01_fusion_qc`
- 当前单 Patch E2E 验证链路顺序：`t06 -> t04 -> t05`

## 6. 模块目录（概览）
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
