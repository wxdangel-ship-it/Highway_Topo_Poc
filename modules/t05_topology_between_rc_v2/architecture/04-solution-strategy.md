# T05-V2 方案策略

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：`AGENTS.md`、`INTERFACE_CONTRACT.md`、实现文件布局

## 策略摘要

T05-V2 当前采用显式的阶段式策略：

1. 构建输入 frame
2. 生成 segment 候选
3. 判定 corridor witness / evidence
4. 解析 corridor identity
5. 建立 source / destination slot 映射
6. 生成最终 road 几何

## 文档策略

未来模块架构应把这条阶段链路解释为稳定真相；而验收文档和 stepwise 运行文档继续作为操作者工作流参考。

## 待确认问题

- 当前阶段链路中，哪些部分已经足够稳定，可进入长期架构；哪些仍属于快速迭代策略？
