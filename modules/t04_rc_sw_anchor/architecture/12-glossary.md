# T04 术语表

- **DriveZone-first**：以 `SEG(s) ∩ DriveZone` 的片段变化作为主触发证据的判定方式。
- **Between-Branches**：在两个分支几何之间构造扫描段进行判定，而不是自由横向搜索。
- **hard-stop**：沿拓扑联通关系查找 `degree>=3` 节点作为 stop 的约束方式。
- **fail-closed**：当证据不足或约束不满足时明确失败，而不是制造成功结果。
- **continuous chain**：连续分合流节点的链式顺序与合并处理机制。
- **multibranch**：`N>2` 时的多事件提取、方向过滤和主结果选择机制。
- **reverse tip**：在默认方向证据不足或近节点异常命中时启用的反向搜索机制。
- **K16**：`kind bit16=65536` 对应的专用处理路径，不按普通 merge / diverge 流程处理。
