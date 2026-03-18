# Round 010 任务拆解

## Phase 1：现状复核

- [ ] 复核 T04 顶层 `SKILL.md` 中哪些内容应上收为高层入口
- [ ] 复核 T05-V2 顶层 `SKILL.md` 中哪些内容应下沉到 `references/README.md`
- [ ] 盘点 active 文档中仍保留模块根 `SKILL.md` 入口或过渡表述的地方

## Phase 2：Skill 包最终收口

- [ ] 收缩 `.agents/skills/t04-doc-governance/SKILL.md`
- [ ] 创建 `.agents/skills/t04-doc-governance/references/README.md`
- [ ] 收缩 `.agents/skills/t05v2-doc-governance/SKILL.md`
- [ ] 创建 `.agents/skills/t05v2-doc-governance/references/README.md`

## Phase 3：旧入口退场

- [ ] 将 `modules/t04_rc_sw_anchor/SKILL.md` 移入 `history/SKILL.legacy.md`
- [ ] 将 `modules/t05_topology_between_rc_v2/SKILL.md` 移入 `history/SKILL.legacy.md`
- [ ] 修正所有 active 文档引用

## Phase 4：口径统一

- [ ] 更新 root `AGENTS.md`
- [ ] 更新 repository metadata 文档
- [ ] 更新 T04 / T05-V2 active 文档
- [ ] 更新治理盘点文档

## Phase 5：报告、合并与清理

- [ ] 生成 `docs/metadata-cleanup/final-skill-mainline-report.md`
- [ ] 执行 `git diff --check`
- [ ] 提交并推送工作分支
- [ ] 若可 fast-forward，合并到 `main` 并 push
- [ ] 若 `main` push 成功，清理本地治理分支
