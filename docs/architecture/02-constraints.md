# 02 约束

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：
  - `SPEC.md`
  - `docs/ARTIFACT_PROTOCOL.md`
  - `docs/CODEX_GUARDRAILS.md`
  - `docs/WORKSPACE_SETUP.md`
- 审核重点：
  - 区分长期约束与轮次约束

## 全局约束

- 内网到外网的反馈必须是纯文本。
- 项目工作必须保持文档/代码分离：
  - 文档在 `modules/<module>/`
  - 实现在 `src/highway_topo_poc/modules/<module>/`
- 工作流默认依赖 WSL 能力和 Windows `E:` 盘仓库路径。
- 运行输出目录不得被当作工作目录。

## 文档治理约束

- Round 1 是 brownfield 文档治理，不是算法重构。
- 旧文档在 Round 1 中全部保留原位。
- 大规模重命名与破坏性迁移超出本轮范围。
- `AGENTS` 与 `SKILL` 的边界需要收紧，但不能抹去历史上下文。
- 项目内文档默认使用中文撰写；仅参数、代码、命令、路径、模块标识、配置键、接口字段等技术符号可保留英文。

## 模块 taxonomy 约束

- `SPEC.md` 仍是最高优先级的全局规格来源。
- 当前仓库现实至少在以下三处偏离了旧 taxonomy：
  - `t03` 缺失于 repo 树
  - `t05_topology_between_rc_v2` 作为独立模块存在
  - `t10` 超出原 taxonomy，且存在命名漂移

## 审核约束

- Round 1 只对 T04、T05-V2、T06 做深度审核。
- 其他模块本轮只做 inventory 和迁移映射。

## 待确认问题

- 哪些约束未来仍应留在项目级，哪些应下沉到模块级架构文档？
