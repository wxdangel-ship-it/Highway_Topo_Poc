# t07_patch_postprocess｜AGENTS

## 退役状态说明
- 本模块已退役，不再属于当前活跃模块集合。
- 后续仅保留为历史实现与文档参考；当前项目模块状态以 `docs/doc-governance/module-lifecycle.md` 为准。

本模块由子GPT Agent 负责需求澄清与方案决策；CodeX 子进程负责落地实现与回归。

## 工作目录规范
- 所有命令在仓库根目录执行：/mnt/e/Work/Highway_Topo_Poc
- 输出写入：outputs/_work/t07_patch_postprocess/<run_id>/（不回写 data/）

## 并行约束
- 不引入 worktree；不在 outputs/ 下工作；不在并行进程里频繁切换分支
