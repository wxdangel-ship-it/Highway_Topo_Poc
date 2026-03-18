# T04 分歧合流路口锚定 Skill 详细说明

本文档承接 T04 标准 Skill 的详细 SOP、检查点与回退说明。
它是流程扩展材料，不替代 `architecture/*`、`INTERFACE_CONTRACT.md` 或 `AGENTS.md`。

## 详细检查点

- `AGENTS.md` 是否仍然足够短，只保留稳定工作规则。
- `architecture/05-building-block-view.md` 是否已清楚解释 T04 的稳定构件结构。
- `INTERFACE_CONTRACT.md` 是否仍聚焦输入、输出、参数、breakpoint 与验收。
- `README.md` 是否已明确自己是操作者总览，而不是长期源事实。
- 治理摘要是否只做压缩说明，而不是重新复制 source-of-truth。

## 常见失败点

- 稳定真相又回流到 `AGENTS.md` 或 README。
- contract 与实际运行入口、输出名称或 breakpoint 描述不一致。
- 批处理脚本与 patch 自动发现脚本被误写成长期源事实。
- 模块级文档修改后，没有同步 repo 级口径或项目级架构口径。

## 回退方式

- 如果稳定真相被写回流程文档，回退到 `architecture/*` 与 `INTERFACE_CONTRACT.md` 重整边界。
- 如果操作者材料与源事实不一致，先修正源事实，再同步 README 或治理摘要。
- 如果任务实际触发了算法、脚本或下游接口改动，终止本 Skill，改走独立任务。

## 常见边界情况

- 批量运行、patch 自动发现、单 patch 运行属于操作者材料范围，不应提升为长期真相。
- 复杂规则族若需要稳定收口，应优先进入 `architecture/*`，不要堆在 Skill。
- 只有在确需描述操作者步骤时，才补读 `README.md` 和相关脚本说明。

## 需要额外阅读的文档

- `modules/t04_rc_sw_anchor/README.md`
- `modules/t04_rc_sw_anchor/scripts/run_t04_batch_wsl.sh`
- `scripts/run_t04_patch_auto_nodes.sh`
- `src/highway_topo_poc/modules/t04_rc_sw_anchor/cli.py`
- `src/highway_topo_poc/modules/t04_rc_sw_anchor/runner.py`
- `src/highway_topo_poc/modules/t04_rc_sw_anchor/metrics_breakpoints.py`

## 细粒度验证习惯

- 改文档前后对照 repo root `AGENTS.md`、`SPEC.md` 和项目级 `docs/architecture/*`。
- 如涉及 contract、README 或治理摘要，回看实现入口和关键测试，不凭空补业务结论。
- 提交前执行 `git diff --check`，确认没有内容级错误。
