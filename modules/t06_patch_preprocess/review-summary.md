# T06 治理摘要

## 当前正式定位

- 当前模块：`modules/t06_patch_preprocess`
- 当前角色：已实现的 patch 级预处理模块，负责修复缺失端点引用的道路并输出端点闭包结果
- 当前文档分层：`architecture/*` 承担长期真相，`INTERFACE_CONTRACT.md` 承担稳定契约，`AGENTS.md` / `SKILL.md` 分别承担规则与流程

## 当前最小正式文档面

- 稳定模块真相：`architecture/*`
- 稳定契约面：`INTERFACE_CONTRACT.md`
- 稳定工作规则：`AGENTS.md`
- 可复用流程：`SKILL.md`
- 当前治理摘要：`review-summary.md`

## 模块业务主链

T06 以“缺失端点识别 -> DriveZone 裁剪 -> 选段 -> 虚拟节点补点 -> 端点闭包输出”为长期主链，并保留足够的诊断产物解释每条被修复道路的处理结果。

## 本轮正式化后已完成的收束

- 稳定业务真相已从 `AGENTS.md`、`SKILL.md` 与旧 contract 叙述收回到 `architecture/*` 与 `INTERFACE_CONTRACT.md`。
- 旧的“零缓冲”冻结口径已被纠正为当前实现可验证的参数事实：`drivezone_clip_buffer_m` 为显式参数，默认值当前为 `5.0` 米。
- 项目级旧口径已在本轮做最小修正，T06 不再被定义为“仅契约 / 仅目录骨架”模块。

## 当前稳定输入 / 输出摘要

- 输入：patch 级 `RCSDNode`、`RCSDRoad`、`DriveZone`，以及可选的 `drivezone` 覆盖路径
- 主输出：`Vector/RCSDNode.geojson`、`Vector/RCSDRoad.geojson`
- 关键诊断输出：`report/metrics.json`、`report/fixed_roads.json`、`report/t06_summary.json`、`report/t06_drop_reasons.json`

## 当前硬约束摘要

- 输出统一到 `EPSG:3857`
- 缺失端点识别基于 `id` 引用闭包
- 虚拟节点必须使用 `Kind=65536`
- 修复后端点引用必须全部闭包
- 无效 DriveZone 必须 fail-fast

## 后续仍待处理、但不阻塞当前正式化的问题

- 输入兼容路径较多，后续可考虑补一份更偏操作者视角的说明，但不需要回流为长期源事实。
- 若未来调节 `drivezone_clip_buffer_m` 默认值或选段降级策略，需要同步更新文档与测试证据。
- 若输出 schema 后续继续扩张，contract 可能需要拆出更细的决策记录，但不影响当前正式化。
