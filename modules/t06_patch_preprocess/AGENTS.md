# t06_patch_preprocess — 子GPT Agent 约束（AGENTS）

## 1. 模块定位（冻结版）
t06 是 Patch 预处理模块，负责修复“Road 端点引用缺失”的问题：

- 输入：已筛选后的 RCSDNode / RCSDRoad + DriveZone
- 识别：RCSDRoad 中 snodeid/enodeid 不在 RCSDNode.id 中的 Road（按 id 引用缺失判定）
- 处理：对这些 Road 用 DriveZone(union) 做面内裁剪打断，仅保留面内部分
- 产出：在打断处新增虚拟 Node（Kind=bit16=65536），并更新 Road 的 snodeid/enodeid
- 输出统一为 EPSG:3857

## 2. 明确不做（Non-Goals）
- 不做基于 Patch 的 RCSDRoad/RCSDNode 过滤（输入已是筛选成果）
- 不对“端点引用齐全”的正常 Road 做任何几何裁剪
- 不做缓冲（margin=0）
- 不拆分成多条 Road（intersection 多段时只保留一段）
- 不修改其它模块的 INTERFACE_CONTRACT
- 不回写 data/<PatchID>/ 下任何文件

## 3. 输出约束
- 仅写 outputs/_work/t06_patch_preprocess/<run_id>/...
- 必含：Vector/RCSDNode.geojson、Vector/RCSDRoad.geojson（均 EPSG:3857）
- 必含：report/metrics.json（诊断与验收支撑）
- 可选：report/fixed_roads.json（增强可解释性）

## 4. 质量闸门（冻结）
- 输出 CRS=EPSG:3857
- 引用闭包：所有输出 Road 的 snodeid/enodeid 都能在输出 Node.id 中找到
- 新增虚拟 Node 的 Kind 必为 65536
- 虚拟 Node.id 不与既有 Node.id 冲突，且稳定可复现（哈希规则固定）
- 被修复 Road 的几何必须为 DriveZone union 的面内裁剪结果；面内为空则 Road 必须被删除

## 5. 沟通与日志
- 诊断优先输出 metrics + 少量索引化清单，避免超长 raw dump
