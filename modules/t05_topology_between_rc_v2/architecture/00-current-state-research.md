# T05-V2 现状研究

## 状态

- 草案状态：Round 1 现状研究，已由 Round 2A 决策对齐补充修正
- 来源依据：
  - `modules/t05_topology_between_rc_v2/AGENTS.md`
  - `modules/t05_topology_between_rc_v2/INTERFACE_CONTRACT.md`
  - `modules/t05_topology_between_rc_v2/REAL_RUN_ACCEPTANCE.md`
  - `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`
  - `tests/test_t05v2_pipeline.py`
  - `scripts/t05v2_*.sh`

## 当前情况

- 按当前正式口径，T05-V2 已是当前正式 T05 模块。
- 当前模块拥有独立源码、测试、运行脚本和输出根目录。
- 物理路径保持 `modules/t05_topology_between_rc_v2/`，本轮不重命名。
- legacy `t05_topology_between_rc` 保留为历史参考模块，不再承担 family 连续治理职责。

## 审核重点

- 确认哪些内容进入未来 `architecture/`，哪些继续留在 run acceptance 文档
- 确认正式模块叙事与历史参考叙事之间的边界

## 当前无待确认项

模块身份与物理路径口径已由 Round 2A 固化。
