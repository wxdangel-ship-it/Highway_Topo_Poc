# 仓库级执行规则

- 主入口：先读 `docs/doc-governance/README.md`；需要理解当前仓库结构时，再读 `docs/repository-metadata/README.md`。
- 源事实优先级：项目级源事实以 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md` 为准；模块级源事实以 `modules/<module>/architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。
- 边界：`AGENTS.md` 只放 durable guidance，`SKILL.md` 只放可复用流程，`specs/<change-id>/` 只放单次变更工件。
- 文档语言：项目内文档默认中文；参数、代码、命令、路径、模块标识、配置键、接口字段可保留英文。
- 冲突处理：若任务书与源事实文档冲突，必须列出冲突点并停止，请求确认。
- 分支与 spec-kit：中等及以上结构化治理变更优先使用 spec-kit；每轮使用独立分支；不在 `main` 上直接做结构化治理变更。
- 范围保护：无明确任务时，不修改算法、测试、运行逻辑、数据契约；文档治理轮次不得顺手扩大为代码改造或目录重构。
