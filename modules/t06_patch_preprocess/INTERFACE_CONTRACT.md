# t06_patch_preprocess｜INTERFACE_CONTRACT

> 本契约仅冻结输入/输出与调用形态（不绑定实现细节）。实现由 t06 子Agent后续补齐。

## 1. Inputs
- Vector/RCSDNode.geojson
- Vector/RCSDRoad.geojson
- DriveZone（通过参数提供；参考 t04 当前入参口径）
  - 建议默认：Vector/DriveZone.geojson（若存在），否则由配置参数指定绝对/相对路径

## 2. Outputs
- Vector/RCSDNode.geojson（Patch 级，新增边缘打断/虚拟 Node）
- Vector/RCSDRoad.geojson（Patch 级）

## 3. EntryPoints
- CLI：t06-patch-preprocess（占位，后续子Agent明确）
- Python：highway_topo_poc.modules.t06_patch_preprocess（占位）

## 4. Params（占位）
- drivezone_path（与 t04 对齐的参数命名/位置）
- edge_node_policy（边缘虚拟 node 生成策略）
- clip_margin_m（Patch 边缘裁剪/扩展策略）

## 5. Examples（只写 outputs/_work，不回写 data/）
（子Agent补齐可复现示例）

## 6. Acceptance
- 输出 RCSDNode/RCSDRoad 文件存在、可解析
- 边缘虚拟 node 数量与规则可解释（由子Agent定义 gate）
