# T04 现状研究

## 状态

- 当前状态：T04 模块级架构说明
- 当前正式定位：`modules/t04_rc_sw_anchor` 是当前活跃核心模块之一
- 来源依据：
  - `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
  - `modules/t04_rc_sw_anchor/README.md`
  - `modules/t04_rc_sw_anchor/AGENTS.md`
  - `.agents/skills/t04-doc-governance/SKILL.md`
  - `src/highway_topo_poc/modules/t04_rc_sw_anchor/`
  - `tests/t04_rc_sw_anchor/`
  - `modules/t04_rc_sw_anchor/scripts/run_t04_batch_wsl.sh`
  - `scripts/run_t04_patch_auto_nodes.sh`

## 当前模块事实

- T04 负责 merge / diverge 与 K16 相关节点的锚点识别，并输出 `intersection_l_opt` 及相关诊断结果。
- 当前模块具备独立实现、独立测试、独立输出根目录和独立操作者材料，已形成成熟模块单元。
- 当前 contract、README、AGENTS 与旧模块根 `SKILL.md` 之间曾存在重复描述，稳定业务真相此前没有完全收回到 `architecture/*`。
- 当前运行入口已经明确存在于 `python -m highway_topo_poc.modules.t04_rc_sw_anchor`、批量脚本和 patch 自动发现脚本中。

## 代码与测试证据摘要

- `cli.py` 暴露 `global_focus` / `patch` 两种运行模式，并显式支持 `focus_node_ids`、`patch_dir`、CRS、continuous、multibranch、K16 等参数。
- `runner.py` 负责实际执行、输出落盘和诊断写出，主输出包括 `intersection_l_opt*.geojson`、`intersection_l_multi.geojson`、`anchors.json`、`metrics.json`、`breakpoints.json`、`summary.txt`。
- `metrics_breakpoints.py` 固化了当前长期可见的 breakpoint 与 gate 统计口径。
- `tests/t04_rc_sw_anchor/` 覆盖了 DriveZone-first、fail-closed、continuous chain、reverse tip、multibranch、K16、节点自动发现等关键行为。
- `modules/t04_rc_sw_anchor/scripts/run_t04_batch_wsl.sh` 与 repo root `scripts/run_t04_patch_auto_nodes.sh` 说明 T04 已有可复用的操作者入口，但这些入口不应替代源事实文档。

## 当前稳定业务真相

- DriveZone-first 是当前模块的主证据链。
- Between-Branches 是当前常规 merge / diverge 锚点识别的主扫描口径。
- hard-stop + fail-closed 是明确且有意保持的行为约束。
- continuous chain、multibranch、reverse tip 与 K16 都已进入实现和测试，不再只是未来想法或临时试验。
- 输出不仅包含结果几何，也包含断点、诊断和 summary，说明“失败可解释”是模块长期要求的一部分。

## 文档分层结论

- `architecture/*` 应承担模块目标、上下文、约束、方案结构、质量要求、风险与术语。
- `INTERFACE_CONTRACT.md` 应承担稳定输入、输出、入口、参数类别、breakpoint 与验收标准。
- `AGENTS.md` 只保留稳定工作规则。
- repo root 标准 Skill 包只保留模块专用复用流程；模块根 `SKILL.md` 仅保留最小指针。
- `README.md` 与脚本说明保留为操作者材料，不再承担完整模块真相。

## Phase A 门控判断依据

当前尚未发现 repo 级硬冲突。T04 的 formalization 重点不是“有没有契约面”，而是“如何把过重的稳定真相从 `AGENTS.md`、旧模块根 `SKILL.md`、`README.md` 收回到 `architecture/*` 与 `INTERFACE_CONTRACT.md`，并把复用流程迁到标准 Skill 包”。
