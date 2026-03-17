# T06 上下文与范围

## 状态

- 当前状态：T06 模块级架构说明
- 来源依据：
  - `INTERFACE_CONTRACT.md`
  - `src/highway_topo_poc/modules/t06_patch_preprocess/`
  - `tests/test_t06_patch_preprocess.py`

## 上下游上下文

- 上游输入：patch 目录中的 `RCSDNode`、`RCSDRoad` 与 `DriveZone`，必要时允许从兼容性的 `global/` 目录补 node / road。
- 当前输出：修复后的 patch 级 `RCSDNode/RCSDRoad` 与诊断文件。
- 下游使用方：`t04_rc_sw_anchor` 以及后续 patch 级链路，依赖 T06 提供更稳定的端点引用闭包结果。

## 本轮正式范围

- 识别缺失端点引用的道路
- 构建 DriveZone union 与 clip buffer 几何
- 将受影响道路裁剪到 patch 内可保留的几何段
- 生成确定性的虚拟节点并更新端点引用
- 输出修复结果、质量指标与可解释诊断
- 明确源事实、稳定规则与复用流程的文档分层

## 非范围

- 不做 patch 级输入筛选逻辑重写
- 不做更广义的 road 清洗或拓扑修复
- 不做算法、测试、运行脚本和 CLI 行为改动
- 不额外创建独立运行验收手册

## 当前边界说明

- T06 负责“缺失端点引用修复”，不负责定义下游拓扑语义。
- T06 可以记录与裁剪相关的诊断，但不替代下游模块的质量门槛与业务解释。
- 兼容性输入解析（如 `global/` fallback）属于运行边界的一部分，不应被误读为模块的主业务目标。
