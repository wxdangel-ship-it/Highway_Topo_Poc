# T05-V2 风险与技术债

## 状态

- 当前状态：正式 T05 模块级架构说明
- 来源依据：
  - `modules/t05_topology_between_rc_v2/history/REAL_RUN_ACCEPTANCE.md`
  - `tests/test_t05v2_pipeline.py`
  - 当前模块文档治理整改结论

## 本轮已修复的文档债

- 历史上缺少 T05-V2 专用标准 Skill 包，导致执行流程知识只能散落在 `AGENTS.md` 和运行验收文档中；本轮已补齐 repo root `.agents/skills/t05v2-doc-governance/SKILL.md`。
- `AGENTS.md` 曾承担模块身份、阶段链路和输出说明等稳定业务真相；本轮已把这些内容收回 `architecture/*` 与 `INTERFACE_CONTRACT.md`。
- legacy T05 与正式 T05 的关系曾容易混淆；本轮已把 legacy T05 限定为历史参考，并补了最小 pointer。

## 当前仍存在的风险

- `history/REAL_RUN_ACCEPTANCE.md` 仍承载大量高价值操作者知识，若源事实更新而运行验收文档未同步，容易再次出现口径漂移。
- T05-V2 的参数面较大，当前契约文档只能按参数类别和稳定基线进行治理，不适合在文档中逐项长期维护所有实现细节。
- 复杂 patch 上仍可能出现较高比例的 `prior_based` / `unresolved` 情况，说明“可解释失败”仍是当前正式模块的重要现实边界。
- `DivStrip`、same-pair、多 arc、topology gap 等问题的审计产物较多，人工审核成本仍不低。

## 当前已知技术债

- `ProbeCrossSection` 仍未进入主判定链。
- branch identity 仍未完整实现。
- `STEP2_SAME_PAIR_TOPK=1` 在真实 same-pair 多路共存场景下可能偏保守。
- 当前版本优先保证“先有可解释的 Road”，而不是“先有最平滑的几何”。

## 本轮明确保留、不处理的债

- 不修改算法、测试和脚本，因此不处理实现层面的精度或召回问题。
- 不重命名物理路径，因此“正式 T05 的路径仍带 `_v2`”这一历史痕迹继续保留。
- 不做 legacy T05 深迁移，因此历史文档仍可能在人工浏览时造成理解噪声。

## 当前人工审核重点

- 核对本文件中“已修复的文档债”是否与当前实际文档面一致。
- 核对“当前仍存在的风险”是否已经足够提示后续维护，但没有夸大为本轮必须解决的阻塞项。
