# Highway_Topo_Poc - Agent Playbook (Global)

## 1. 角色分工
### 1.1 主智能体（当前 GPT 对话）
负责：
- 主项目需求澄清、范围/约束冻结
- 形成主目录下的全局文档（docs/）
- 在“约束冻结后”给 CodeX 输出可一键复制的任务书（单一 code block）
不负责：
- 直接在内网跑真实数据
- 冻结子模块的 INTERFACE_CONTRACT

### 1.2 CodeX CLI（实现执行）
负责：
- 按全局文档与 SPEC 落地仓库结构与代码
- 先问再做：任何不清晰点必须提问后再执行
不负责：
- 自作主张定义子模块接口契约
- 输出/记录敏感信息到外传文本

### 1.3 子智能体（后续新对话 + 独立 CodeX CLI）
负责：
- 子模块需求澄清与方案决策
- 在对应子目录内产出：INTERFACE_CONTRACT.md / AGENTS.md / SKILL.md 等
规则：
- 每个子模块开一个新的 CodeX CLI，避免冲突

## 2. 文档分层与放置规则
- 全局适用文档：放根目录 docs/
- 子模块详细文档：放 modules/<module_id>/ 下
- 主项目如需理解子模块文档，由用户以文件形式提供（不脑补引用）

## 3. CodeX 任务书格式（全局硬约束）
- 给 CodeX 的任务书必须“完全一键式拷贝”：单一 code block、无需手工拼接
- 若存在必须人工填写项（尽量避免），需集中在「TODO 区块」且数量 <= 3

## 4. 内外网传递方式（全局硬约束）
- 内网 -> 外网仅允许“文本粘贴”回传
- 外传文本必须遵守 docs/ARTIFACT_PROTOCOL.md

## 5. 代码承载与目录约定（方案A：文档与代码分层）
- 每个模块的文档与契约仅放在 `modules/<module_id>/`。
- 每个模块目录必须包含：`AGENTS.md` / `SKILL.md` / `INTERFACE_CONTRACT.md`（README 非必需）。
- `INTERFACE_CONTRACT.md` 章节顺序统一：`Inputs` / `Outputs` / `EntryPoints` / `Params` / `Examples` / `Acceptance`。
- `modules/<module_id>/` 承载上述文档与模块级说明文档，不承载运行时代码，禁止放置 `.py` 实现。
- 例如：`modules/t02_ground_seg_qc/` 仅放文档；可执行实现放 `src/highway_topo_poc/modules/t02_ground_seg_qc/`。
- 每个模块的可执行实现代码放在 `src/highway_topo_poc/modules/<module_id>/`。
- 若需要模块入口（可选），放在 `src/highway_topo_poc/entrypoints/`。
- pytest/CI/import 仅依赖 src-layout 可导入包，不依赖手动设置 `PYTHONPATH` 或 `sys.path`。
- 每个模块测试放在 `tests/`，命名建议 `test_<module_id>_*.py`。
- 并行开发时，模块测试只覆盖本模块逻辑，避免跨模块耦合测试。
- 运行产物统一写到 `outputs/_work/<module_id>/<run_id>/`。
- 运行产物不得回写 `data/` 目录。
- `outputs/` 只存放产物，不作为工作目录，禁止在该目录下改代码、跑 `pytest` 或跑 `git`。
- 子 Agent/CodeX 进场必须执行三连：`cd "$(git rev-parse --show-toplevel)" ; pwd ; git status -sb`。
- 所有运行、测试、git 操作一律在 repo root 执行；仅编辑模块文档时可短暂进入 `modules/<module_id>/`，完成后必须回 repo root。
