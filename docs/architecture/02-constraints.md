# 02 约束

## 状态

- 当前状态：项目级约束说明
- 来源依据：
  - `SPEC.md`
  - `docs/ARTIFACT_PROTOCOL.md`
  - `docs/archive/nonstandard/CODEX_GUARDRAILS.md`
  - `docs/archive/nonstandard/WORKSPACE_SETUP.md`
- 审核重点：
  - 区分长期约束与轮次约束

## 全局约束

- 内网到外网的反馈必须是纯文本。
- 项目工作必须保持文档 / 代码分离：
  - 文档在 `modules/<module>/`
  - 实现在 `src/highway_topo_poc/modules/<module>/`
- 工作流默认依赖 WSL 能力和 Windows `E:` 盘仓库路径。
- 运行输出目录不得被当作工作目录。

## 文档治理约束

- 文档治理轮次不是算法重构。
- 旧文档默认保留原位，除非有明确归档或迁移任务。
- `AGENTS` 与 `SKILL` 的边界必须收紧，但不能用它们替代源事实文档。
- 项目内文档默认使用中文撰写；仅参数、代码、命令、路径、模块标识、配置键、接口字段等技术符号可保留英文。

## 模块口径约束

- `SPEC.md` 仍是最高优先级的全局规格来源。
- 当前正式 T05 模块为 `t05_topology_between_rc_v2`，物理路径保持 V2。
- legacy `t05_topology_between_rc` 只作为历史参考模块保留。
- `t03_marking_entity` 与 `t10` 都已退役，不再属于当前活跃 taxonomy。

## 审核约束

- 当前重点审核模块为 T04、T05-V2、T06。
- 其他模块在已明确的正式 / 历史 / 退役口径下，按后续优先级逐步推进。

## 当前无待确认项

模块身份相关的核心约束已经写回项目级文档。
