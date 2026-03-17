# t07_patch_postprocess｜SKILL

## 一句话能力
Patch 后处理：以二层路网拓扑要求为目标，对 t04 的 intersection_l 与 t05 的 Road 产物做 Topo 级完整性校验与处理，输出最终拓扑交付层 Node/Road/Intersection_l。

## 输入（业务层）
- RCSDNode（Patch 级）
- RCSDRoad（Patch 级）
- Road（t05 模块产物）
- Intersection_l（t04 模块产物）

## 输出（业务层）
- Node（最终交付层）
- Road（最终交付层）
- Intersection_l（最终交付层，完成 topo 级校验/处理）

## 关键门禁（占位）
- topo 完整性、连通性、断头/自交等；具体指标由子Agent冻结
