# T06 引言与目标

## 状态

- 文档状态：Round 2C Phase B 最小正式稿
- 来源依据：
  - `src/highway_topo_poc/modules/t06_patch_preprocess/run.py`
  - `src/highway_topo_poc/modules/t06_patch_preprocess/pipeline.py`
  - `tests/test_t06_patch_preprocess.py`

## 当前正式定位

- 模块路径：`modules/t06_patch_preprocess`
- 当前角色：Patch 级预处理模块，负责把缺失端点引用的道路修复为下游可消费的闭包结果
- 下游关系：为 `t04_rc_sw_anchor` 及后续 patch 级链路提供更稳定的 `RCSDNode/RCSDRoad`

## 模块目标

T06 的长期目标不是“重做 patch 过滤”，而是以最小、确定性的方式修复道路端点引用缺失问题：

1. 识别 `RCSDRoad` 中引用不存在 `Node.id` 的道路
2. 基于 DriveZone 对受影响道路做裁剪
3. 在必要时创建虚拟节点并更新 `snodeid/enodeid`
4. 输出满足端点引用闭包的 patch 级 node / road 结果
5. 保留足够的诊断产物，支持人工审核失败原因与裁剪效果

## 文档目标

本轮之后，T06 的最小正式文档面应由以下文件共同组成：

- 稳定模块真相：`architecture/*`
- 稳定契约：`INTERFACE_CONTRACT.md`
- 稳定工作规则：`AGENTS.md`
- 可复用流程：`SKILL.md`
- 当前治理摘要：`review-summary.md`

## 当前无待确认项

T06 作为“已实现、当前做文档正式化”的模块身份，已在本轮与项目级源事实对齐。
