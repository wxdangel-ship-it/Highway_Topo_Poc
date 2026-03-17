# T06 构件视图

## 状态

- 当前状态：T06 模块级架构说明
- 来源依据：`src/highway_topo_poc/modules/t06_patch_preprocess/`

## 稳定阶段链

T06 当前可以稳定表述为以下阶段链：

`InputResolver -> ProjectAndNormalize -> MissingEndpointDetector -> DriveZoneClipper -> SegmentSelector -> VirtualNodeAllocator -> OutputAssembler -> ReportWriter`

## 构件与职责

### 1. 入口与参数装配

- `run.py`
- 职责：
  - 解析 CLI 参数
  - 传递 `drivezone_clip_buffer_m`
  - 执行 `run_patch`
  - 输出最小运行结果摘要

### 2. 输入解析与兼容路径

- `io.py`
- 职责：
  - 解析 patch 目录
  - 读取 `RCSDNode`、`RCSDRoad`、`DriveZone`
  - 处理 `global/` fallback 与 DriveZone override
  - 提供 run id 与输出文件写入能力

### 3. 投影、几何与局部规则

- `geom.py`
- 职责：
  - CRS 变换与 geographic clamp
  - DriveZone union / buffer 构建
  - 线段提取、端点分配、segment 选择
  - 虚拟节点稳定 ID 生成

### 4. 主流水线

- `pipeline.py`
- 职责：
  - 串联输入解析、投影、待修复道路识别
  - 执行裁剪、选段、补点、更新引用
  - 组装 node / road 输出
  - 产出 metrics 与固定修复明细

### 5. 报告与诊断

- `report.py`
- 职责：
  - 累积修复计数、drop reasons、warnings、fixed road 详情
  - 生成可审计的 summary / metrics 结构

## 当前结构结论

- T06 的稳定真相已经足以用“阶段链 + 构件职责”解释，不需要再把完整模块定义压回 `AGENTS.md` 或 `SKILL.md`。
- 运行入口、几何规则和报告结构各自边界清晰，适合维持为当前最小正式文档面。
