# Round 4A 任务拆解

## Phase 1：现状审计

- [ ] 审计 `modules/t04_rc_sw_anchor/SKILL.md` 的有效流程内容与当前引用
- [ ] 审计 `modules/t05_topology_between_rc_v2/SKILL.md` 的有效流程内容与当前引用
- [ ] 盘点 active 文档中把模块根 `SKILL.md` 当标准入口的表述

## Phase 2：标准 Skill 包创建

- [ ] 创建 `.agents/skills/t04-doc-governance/SKILL.md`
- [ ] 创建 `.agents/skills/t05v2-doc-governance/SKILL.md`
- [ ] 将旧正文中的流程性内容迁入标准 Skill 包

## Phase 3：旧入口处理

- [ ] 将 `modules/t04_rc_sw_anchor/SKILL.md` 改为最小指针版
- [ ] 将 `modules/t05_topology_between_rc_v2/SKILL.md` 改为最小指针版

## Phase 4：口径统一

- [ ] 更新 root `AGENTS.md`
- [ ] 更新 repository metadata 文档中的 Skill 位置与白名单说明
- [ ] 更新 T04 / T05-V2 active 文档中的 Skill 口径
- [ ] 更新 current inventory 文档

## Phase 5：报告与收尾

- [ ] 生成 `docs/metadata-cleanup/round4a-standard-skill-alignment-report.md`
- [ ] 执行 `git diff --check`
- [ ] 提交并推送当前分支
