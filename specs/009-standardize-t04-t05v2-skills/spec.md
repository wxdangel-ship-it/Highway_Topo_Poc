# Round 4A：T04 / T05-V2 标准 Skill 结构整改

## 背景

当前仓库已经完成模块文档正式化与 repository metadata 收口，但 T04 与 T05-V2 仍把模块根目录 `SKILL.md` 作为主要流程入口。这种放置方式不符合 Codex 标准 Skill 包结构，也会让 repo root 启动时的技能发现与引用口径不稳定。

## 目标

- 为 T04 创建标准 Skill 包：`.agents/skills/t04-doc-governance/SKILL.md`
- 为 T05-V2 创建标准 Skill 包：`.agents/skills/t05v2-doc-governance/SKILL.md`
- 将当前模块根目录 `SKILL.md` 中仍有价值的流程性内容迁入标准 Skill 包
- 统一相关 active 文档中的 Skill 口径，明确标准 Skill 的位置、职责与边界
- 使模块根目录旧 `SKILL.md` 不再承载正文型流程内容

## 非目标

- 不修改算法、测试、运行脚本或入口逻辑
- 不修改模块物理目录
- 不改变模块状态（Active / Retired / Historical Reference）
- 不扩展到 T06 或其它模块的 Skill 迁移
- 不发起新的模块 formalization

## 澄清结论

### 技能命名

- T04：`t04-doc-governance`
- T05-V2：`t05v2-doc-governance`

### 标准 Skill 触发范围

- T04 Skill：仅用于 T04 的文档治理、口径对齐、模块级文档复核与流程类任务
- T05-V2 Skill：仅用于 T05-V2 的文档治理、验收说明边界复核与模块级文档对齐任务

### 不应由 Skill 承载的内容

- 长期模块真相
- 稳定契约定义
- repo 级 durable guidance
- 需要在 `architecture/*`、`INTERFACE_CONTRACT.md` 或 `AGENTS.md` 中长期稳定保存的业务口径

### 旧模块根 `SKILL.md` 处理

- 本轮不再保留正文型流程内容
- 采用“最小指针版”收口：仅说明标准 Skill 包位置与角色
- 不再把模块根 `SKILL.md` 作为 active 标准入口

## 完成标准

- T04 与 T05-V2 均已形成 repo root 下的标准 Skill 包
- 模块根旧 `SKILL.md` 不再承载正文型流程
- active 文档中不再把模块根 `SKILL.md` 表述为标准 Skill 入口
- root `AGENTS.md` 仍保持简洁，没有扩写成结构说明书
