# CodeX Guardrails (Global, MUST FOLLOW)

## 0. 总原则：Stop → Ask → Do
- 任何不清晰的地方，优先提出问题给用户确认
- 未确认前，不进行大规模落地（最多允许创建空目录与模块文档三件套占位）

## 1. 必须先问的触发条件（示例）
- 目录结构、模块命名、运行入口、schema 字段、输出格式
- 任何“可能影响内网回传文本”的格式变更
- 任何涉及 RC/SW/锚点定义的细节（留给子 Agent）

## 2. 外传文本硬约束（可粘贴性）
外传文本（将被用户粘贴回外网）要求：
- 体积可控：<=120 行 或 <=8KB（超限必须截断并标记 Truncated=true）
- 结构清晰：优先使用 TEXT_QC_BUNDLE v1 或同类分段结构
- 避免超长 raw dump（例如整段 JSON/GeoJSON 顶点数组）；必要时只保留 Top-K/摘要

## 3. 推荐的“问题定位”方式（更紧凑）
- 使用“索引化位置/区间”（bin 区间）或 Top-K 区间摘要（便于压缩与对比）
- 使用统计摘要（p50/p90/p99）+ 阈值 + 严重程度等级

## 4. 执行前的标准输出（握手）
在开始写代码前，必须输出：
- 理解摘要（<=15行）
- 待确认问题（<=5条）
- 最小落地计划（<=10步）
等待用户确认后再执行

## 5. 代码承载硬约束（modules vs src）
- 明确禁止把可执行 Python 实现代码放进 `modules/<module_id>/`；该目录仅承载模块文档与接口契约。
- 每个模块目录最小文档集合固定为：`AGENTS.md` / `SKILL.md` / `INTERFACE_CONTRACT.md`（README 非必需）。
- `INTERFACE_CONTRACT.md` 章节顺序固定：`Inputs` / `Outputs` / `EntryPoints` / `Params` / `Examples` / `Acceptance`。
- 新增实现代码默认放在 `src/highway_topo_poc/modules/<module_id>/`。
- 新增测试默认放在 `tests/`，建议命名 `test_<module_id>_*.py`。
- pytest/CI/import 只能依赖 src-layout 可导入包，不允许依赖手动 `PYTHONPATH` 才能运行。
- 并行开发时禁止在 `outputs/` 下作为工作目录。
- 运行产物统一写入 `outputs/_work/<module_id>/<run_id>/`，不得回写 `data/`。
- 所有 `pytest` 与 `git` 命令必须在 repo root 执行。
# Workspace Setup (WSL + Python)

## 1. 路径硬约束
- 本项目必须放在 Windows 的 E: 盘下
- WSL 下对应路径通常为：`/mnt/<drive>/...`
- 推荐项目根目录：
  ${REPO_ROOT}

## 2. 路径相关注意事项
- 代码与配置尽量使用相对路径
- 外传文本以可粘贴性为准；如包含本机绝对路径请注意体积与噪声（建议用相对路径/逻辑名）
- 若需要记录文件名，优先相对路径或逻辑名，以减少粘贴体积

## 3. Python 环境
- 使用 WSL 的 Python（版本与依赖管理方式由实现者结合本机情况选择）
- 需要可一键运行（脚本/Makefile/命令均可）
