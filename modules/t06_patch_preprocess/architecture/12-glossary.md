# T06 术语表

- **端点引用闭包（endpoint-reference closure）**：每条输出道路的 `snodeid/enodeid` 都能在输出 `Node.id` 集合中找到对应节点。
- **缺失端点道路**：`snodeid` 或 `enodeid` 至少一个不在输入 `Node.id` 集合中的道路。
- **虚拟节点（virtual node）**：在裁剪后道路端点处新增的确定性合成节点，`Kind=65536`。
- **DriveZone 裁剪几何（DriveZone clip geometry）**：由 DriveZone union 再叠加 `drivezone_clip_buffer_m` 后得到的裁剪几何。
- **保留线段（selected segment）**：道路裁剪结果为多段时，最终被选中进入输出的那一段。
- **固定修复明细（fixed roads detail）**：写入 `fixed_roads.json` 的解释性记录，用于说明某条道路如何被裁剪、降级和补点。
