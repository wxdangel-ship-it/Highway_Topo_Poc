# T04 风险与技术债

## 状态

- 当前状态：T04 模块级架构说明
- 来源依据：
  - `modules/t04_rc_sw_anchor/README.md`
  - `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
  - `tests/t04_rc_sw_anchor/`

## 本轮已修复的文档债

- 稳定模块真相不再主要依赖 `AGENTS.md`、旧模块根 `SKILL.md` 与 `README.md` 解释。
- `architecture/*` 现在承担了 T04 的长期模块叙事与构件结构。
- `AGENTS.md` 与标准 Skill 包已经被收缩为规则和流程文档；旧模块根 `SKILL.md` 已移入 `history/SKILL.legacy.md`。

## 当前仍存在的风险

- T04 的规则家族较多，contract 仍然不可避免地较长，后续需要持续维持“稳定契约 vs 高层架构”的边界。
- `README.md` 仍保留较多操作者语境，后续若源事实更新而 README 未同步，存在口径漂移风险。
- continuous chain、multibranch、K16、reverse tip 都是成熟但复杂的规则家族，后续若继续扩张，可能需要更细粒度决策记录。

## 当前保留的技术债

- 不修改实现，因此不处理规则复杂度本身。
- 不拆 ADR，因此复杂规则家族仍集中记录在模块文档中。
- 不删除历史操作者材料，因此浏览时仍可能看到一定重复信息。
