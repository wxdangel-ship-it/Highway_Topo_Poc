# t06_patch_preprocess｜SKILL

## 一句话能力
Patch 预处理：筛选当前 Patch 的 RCSDNode/RCSDRoad，并对 Patch 边缘 Road 进行预处理构建“边缘虚拟 Node”，输出 Patch 级 RCSDNode/RCSDRoad 供下游模块使用。

## 输入（业务层）
- RCSDNode（输入图层）
- RCSDRoad（输入图层）
- DriveZone（输入图层；路径/命名通过参数给定，参考 t04 的入参方式）

## 输出（业务层）
- Patch 级 RCSDNode（包含边缘打断/虚拟 Node）
- Patch 级 RCSDRoad（Patch 内裁剪/关联后的 Road）

## 关键门禁（占位）
- 仅描述：coverage/完整性/边缘处理正确性；具体指标由子Agent冻结
