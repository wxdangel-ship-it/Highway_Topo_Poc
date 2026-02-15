# CodeX Start Here (Highway_Topo_Poc)

## 0. 先读文档（按顺序）
1) SPEC.md
2) docs/PROJECT_BRIEF.md
3) docs/AGENT_PLAYBOOK.md
4) docs/CODEX_GUARDRAILS.md
5) docs/ARTIFACT_PROTOCOL.md
6) docs/WORKSPACE_SETUP.md

## 1. 规则优先级（冲突时按此执行）
SPEC.md > docs/ARTIFACT_PROTOCOL.md > docs/CODEX_GUARDRAILS.md > 其他文档

## 2. 启动握手（必须执行）
在写任何代码、创建任何目录、改动任何接口/命名之前：
- 输出：
  - 你对项目目标与约束的「理解摘要」（<= 15 行）
  - 「待确认问题清单」（<= 5 条；若无问题写“无”）
  - 「最小落地计划」（<= 10 steps）
- 等用户回复确认后，再开始落地代码

## 3. 本阶段禁止事项
- 禁止自作主张冻结任何子模块 INTERFACE_CONTRACT（放到子 Agent 阶段）
- 外传文本只要求可粘贴传递：<=120 行 或 <=8KB；避免超长 raw dump，必要时 Top-K/摘要/截断
- 遇到不清晰之处必须先问，不允许盲干
