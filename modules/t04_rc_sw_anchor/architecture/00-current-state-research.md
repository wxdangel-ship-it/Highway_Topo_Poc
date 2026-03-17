# T04 现状研究

## 状态

- 草案状态：Round 1 现状研究
- 来源依据：
  - `modules/t04_rc_sw_anchor/AGENTS.md`
  - `modules/t04_rc_sw_anchor/SKILL.md`
  - `modules/t04_rc_sw_anchor/INTERFACE_CONTRACT.md`
  - `modules/t04_rc_sw_anchor/README.md`
  - `src/highway_topo_poc/modules/t04_rc_sw_anchor/`
  - `tests/t04_rc_sw_anchor/`

## 当前情况

- T04 是一个已有独立实现和独立测试的成熟核心模块。
- 稳定真相目前分散在 contract、AGENTS、SKILL 和 README 中。
- `INTERFACE_CONTRACT.md` 当前承载了最重的语义内容。
- `AGENTS.md` 与 `SKILL.md` 也承载了本应后续收敛到源事实文档中的行为规则。

## 审核重点

- 确认长期稳定的模块目标描述
- 确认哪些规则应留在 contract，哪些应进入 architecture
- 确认 README 在迁移后如何定位

## 后续观察点

- 当 `architecture/` 文档稳定后，可再决定 `README.md` 是否继续保留为操作者友好摘要。
