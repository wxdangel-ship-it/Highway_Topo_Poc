# T05-V2 约束

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：`AGENTS.md`、`INTERFACE_CONTRACT.md`、`REAL_RUN_ACCEPTANCE.md`

## 硬约束

- `DriveZone` 缺失或为空时必须硬失败。
- `DivStrip` 作为不可跨越的硬屏障。
- 输出统一规范到 `EPSG:3857`。
- 分阶段执行与 resume 能力属于当前操作模型的一部分。

## 文档约束

- 当前还没有 `SKILL.md`
- 运行验收说明承载了重要的操作者上下文
- legacy T05 已明确为历史参考模块，当前正式模块叙事应以 T05-V2 为主体

## 后续观察点

- 后续可再决定是否为 T05-V2 单独补一份 `SKILL.md`。
