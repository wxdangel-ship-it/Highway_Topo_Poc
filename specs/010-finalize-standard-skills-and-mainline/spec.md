# Round 010：标准 Skill 最终收口与主线合入

## 背景

T04 与 T05-V2 已经建立 repo root 标准 Skill 包，但当前顶层 `SKILL.md` 仍承载了过多详细 SOP；同时模块根目录仍保留 active `SKILL.md` 双入口，不利于主线长期维护。

## 目标

- 将 T04 与 T05-V2 的顶层标准 `SKILL.md` 收缩为真正的高层入口
- 将详细检查项、失败点、回退方式与边界情况迁入 `references/README.md`
- 将 `modules/t04_rc_sw_anchor/SKILL.md` 与 `modules/t05_topology_between_rc_v2/SKILL.md` 退场并移入各自 `history/`
- 统一 active 文档中关于 Skill 的位置、职责与边界表述
- 在当前工作分支完成后，以 `--ff-only` 方式尝试合并到 `main`
- 在 `main` push 成功后，清理指定的本地治理分支

## 非目标

- 不修改算法、测试、运行脚本、入口逻辑
- 不修改模块物理目录
- 不改变模块状态（Active / Retired / Historical Reference）
- 不 formalize 新模块
- 不删除远端治理分支
- 不做复杂 merge 或 rebase

## 澄清结论

### 顶层 Skill 保留内容

顶层 `SKILL.md` 只保留：

- metadata
- 适用任务
- 非适用任务
- 先读哪些 source-of-truth 文档
- 3 到 6 步高层流程
- 输出与验证要求
- 指向 `references/README.md`

### `references/README.md` 承接内容

- 详细检查点
- 失败点
- 回退方式
- 边界情况
- 额外阅读材料
- 细粒度验证习惯

### 旧模块根 `SKILL.md`

- 两个旧模块根 `SKILL.md` 不再保留为 active 文件
- 因其内容已被标准 Skill 包和 `references/README.md` 完整承接，本轮移入各自 `history/SKILL.legacy.md`，只保留审计痕迹

### `main` 合并方式

- 使用 `git merge --ff-only codex/010-finalize-standard-skills-and-mainline`
- 如失败，立即停止并汇报，不做复杂 merge

## 完成标准

- T04 / T05-V2 顶层 `SKILL.md` 已瘦身为高层入口
- 两个 `references/README.md` 已建立并承接详细 SOP
- active 文档不再把模块根 `SKILL.md` 当成入口，也不再保留过渡期表述
- `main` 若可 `ff-only` 合并则完成 push；否则至少完成工作分支提交与推送，并给出阻塞说明
