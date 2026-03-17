# T04 上下文与范围

## 状态

- 草案状态：Round 1 最小可信草案，已由 Round 2A 决策对齐补充修正
- 来源依据：`INTERFACE_CONTRACT.md`、`README.md`、当前 `src/` 与 `tests/`

## 当前范围

- merge / diverge 锚点识别
- K16 专用锚点流程
- 锚点与 `intersection_l_opt` 输出生成
- metrics、breakpoints、summary 与 config 输出

## Round 1 非范围

- 修改 T04 运行时行为
- 重定义 anchor 语义
- 立即迁移所有 legacy 文档

## 依赖关系

- 上游 patch / vector 输入
- 下游当前正式 T05 拓扑模块（即 `t05_topology_between_rc_v2`）
- 仓库统一的 CRS 与输出约定

## 审核重点

- 对照 T06、当前正式 T05 与 legacy T05 历史参考，确认当前模块边界是否清晰
