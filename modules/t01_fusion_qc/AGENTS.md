# t01_fusion_qc - AGENTS

## 职责边界
- 仅负责 t01：点云标量融合质量/参差区间识别（MVP）。
- 只处理单 patch 输入：`PointCloud/merged.laz` + `Traj/**/raw_dat_pose.geojson`。
- 输出仅包含 t01 质量摘要与区间定位，不扩展到 t02–t05 语义。

## 隔离原则
- 不修改 t02、t03、t04、t05 的代码、接口、参数或产物格式。
- 不变更其它模块的输入输出契约；仅在现有 CLI 中新增 t01 子命令挂载。
- t01 的字段与文件命名冻结在 `INTERFACE_CONTRACT.md`，并仅约束 t01。

## 与 CodeX 协作流程
1. 先探测真实目录结构（不能假设 patch 层级）。
2. 再实现 t01 模块代码与 CLI 接入。
3. 最后执行 1 个 patch smoke + t01 pytest 回归并提交结果。

## 运行约束
- 外传文本遵循 `docs/ARTIFACT_PROTOCOL.md`：可粘贴、结构化、体积受控。
- 问题定位仅使用 `sample_idx/bin_idx` 区间，不使用坐标索引。
