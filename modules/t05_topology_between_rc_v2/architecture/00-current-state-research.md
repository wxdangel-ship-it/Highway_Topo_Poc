# T05-V2 现状研究

## 状态

- 草案状态：Round 1 现状研究
- 来源依据：
  - `modules/t05_topology_between_rc_v2/AGENTS.md`
  - `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md`
  - `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`
  - `tests/test_t05v2_pipeline.py`
  - `scripts/t05v2_*.sh`

## 当前情况

- 按仓库现实，T05-V2 已被视为独立模块。
- 当前模块拥有独立源码、测试、运行脚本和输出根目录。
- 当前文档尚未清晰区分：
  - 稳定模块真相
  - 工作流 / runbook
  - 与 legacy T05 的家族关系

## 审核重点

- 确认模块身份与家族落位
- 确认哪些内容进入未来 architecture，哪些继续留在 run acceptance 文档

## 待确认问题

- 仓库未来是否需要在 legacy T05 与 T05-V2 之上再加一层 T05 family 总览？
