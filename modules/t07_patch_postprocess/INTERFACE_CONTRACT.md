# t07_patch_postprocess｜INTERFACE_CONTRACT

> 本契约仅冻结输入/输出与调用形态（不绑定实现细节）。实现由 t07 子Agent后续补齐。

## 1. Inputs
- Vector/RCSDNode.geojson
- Vector/RCSDRoad.geojson
- Road（t05 产物；文件名/位置以 t05 契约为准）
- Vector/intersection_l.geojson（t04 产物；或以 t04 契约为准）

## 2. Outputs
- Vector/Node.geojson（最终交付层）
- Vector/Road.geojson（最终交付层）
- Vector/intersection_l.geojson（最终交付层，经过 topo 级完整性处理）

## 3. EntryPoints
- CLI：t07-patch-postprocess（占位，后续子Agent明确）
- Python：highway_topo_poc.modules.t07_patch_postprocess（占位）

## 4. Params（占位）
- topo_ruleset（二层路网规则集选择）
- validation_level（strict/normal）
- repair_policy（repair/flag-only）

## 5. Examples（只写 outputs/_work，不回写 data/）
（子Agent补齐可复现示例）

## 6. Acceptance
- 输出 Node/Road/Intersection_l 存在、可解析
- topo 校验通过或输出明确 breakpoints（由子Agent定义 gate）
