# T05 DEV-QA 协作协议（修正版）

适用模块:
- `t05_topology_between_rc`

核心修正:
- 外网版本审计可以独立启动，不再等待新的内网执行。
- 内网 `bundle` 是补充证据，不是外网版本审计的门票。
- QA 仍可只从 `outputs/_qa_external/t05_topology_between_rc` 根目录自动发现待审主题。

---

## 1. 两套审计的关系

### 1.1 内网执行审计

目标:
- 记录单次 `(run_id, patch_id)` 执行遇到的问题。
- 面向真实输入、真实结果、真实 debug。
- 产出单文件 `T05_EXEC_AUDIT_BUNDLE__<run_id>__<patch_id>.md`。

位置:

```text
outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/qa_inner/
```

作用:
- 给 QA 提供运行证据。
- 用于验证、补强、反驳或收敛外网版本审计结论。

### 1.2 外网版本审计

目标:
- 记录版本级质量审计，而不是单次执行现象。
- 允许基于代码、diff、规则、历史文本、历史报告独立启动。

位置:

```text
outputs/_qa_external/t05_topology_between_rc/by_version/<git_sha>/<audit_topic>/
```

固定文件:
- `AUDIT_SCOPE.md`
- `EVIDENCE_INDEX.md`
- `audit_status.json`
- `T05_VERSION_QA_REPORT.md` 由 QA 产出

关键原则:
- 外网版本审计的触发条件是“版本审计需求成立”，不是“新的内网 run 已完成”。
- 没有新的内网 run 时，外网 QA 仍可做静态版本审计，但必须明确运行证据缺口。

---

## 2. 外网版本审计的启动条件

以下任一条件满足，即可创建外网版本审计目录:
- 版本代码已改动，且影响 T05 主链路。
- 用户明确要求对某版本做质量审计。
- QA 明确指出当前需要版本级判断。
- 历史问题需要在新的 `git_sha` 下检查是否仍存在。
- 有用户粘贴的运行文本，但尚未形成正式内网 `bundle`。
- 即使没有任何新的运行证据，只要代码改动足以形成明确审计主题，也应创建。

禁止保留旧语义:
- “至少有 1 份新的内网 bundle 才能创建外网主题”
- “没有新的 run bundle 就不能开始 QA”

---

## 3. 外网文件规范

### 3.1 `AUDIT_SCOPE.md`

至少包含:
- `git_sha`
- `audit_topic`
- `scope_reason`
- `audit_trigger`
- `question_to_qa`
- `static_audit_allowed`
- `target_runs`
- `target_patches`

说明:
- `audit_trigger` 允许值:
  - `code_change`
  - `regression_report`
  - `business_rule_check`
  - `run_bundle_followup`
- `static_audit_allowed` 必须写 `true` 或 `false`
- 无新的内网 run 时:
  - `target_runs: NA`
  - `target_patches: NA` 或已知 patch

### 3.2 `EVIDENCE_INDEX.md`

外网证据允许收录:
- `code_ref`
- `diff_ref`
- `rule_ref`
- `pasted_text`
- `inner_bundle`
- `prior_report`

每条证据至少包含:
- `evidence_type`
- `source`
- `related_git_sha`
- `related_run_id`
- `related_patch_id`
- `note`

约束:
- `related_run_id` / `related_patch_id` 允许写 `NA`
- 不能因为没有 `inner_bundle` 就让 `EVIDENCE_INDEX.md` 为空
- 只要已有代码证据和审计问题定义，就应建立 `EVIDENCE_INDEX.md`

### 3.3 `audit_status.json`

最低字段:

```json
{
  "git_sha": "<sha>",
  "audit_topic": "<topic>",
  "scope_ready": true,
  "evidence_ready": true,
  "evidence_mode": "code_only",
  "qa_report_ready": false,
  "dev_acknowledged": false,
  "updated_at": "2026-03-07T10:00:00+08:00",
  "latest_inner_run_id": "NA",
  "latest_inner_patch_id": "NA",
  "qa_blocked_reason": "none"
}
```

字段语义:
- `scope_ready`: 主题已建立、范围已明确；不依赖内网执行。
- `evidence_ready`: 证据足够让 QA 开始审计；可以仅靠代码证据成立。
- `evidence_mode` 允许值:
  - `code_only`
  - `code_plus_paste`
  - `code_plus_run`
  - `mixed`
- `latest_inner_run_id` / `latest_inner_patch_id`:
  - 没有新的内网证据时写 `NA`
  - 不允许因为是 `NA` 就把 `evidence_ready` 置为 `false`
- `qa_blocked_reason`:
  - `missing_scope`
  - `missing_question`
  - `missing_code_reference`
  - `none`

---

## 4. DEV 正确流程

### 流程 A：只有代码变化，没有新的内网执行

1. 创建外网版本审计目录。
2. 写 `AUDIT_SCOPE.md`。
3. 写 `EVIDENCE_INDEX.md`，至少登记 `code_ref / diff_ref / rule_ref`。
4. 写 `audit_status.json`:
   - `scope_ready=true`
   - `evidence_ready=true`
   - `evidence_mode=code_only`
   - `latest_inner_run_id=NA`
   - `latest_inner_patch_id=NA`
   - `qa_blocked_reason=none`
5. 等待 QA 做版本级静态审计。

### 流程 B：后续补入新的内网执行证据

1. 不重建 `audit_topic`。
2. 在同一主题下追加 `inner_bundle` 或 `pasted_text` 证据。
3. 更新 `audit_status.json`:
   - `evidence_mode` 从 `code_only` 升级为 `code_plus_run` 或 `mixed`
   - `latest_inner_run_id` / `latest_inner_patch_id` 写入真实值
   - `updated_at` 更新
4. 由 QA 在同一主题下增强或修正结论。

### 流程 C：QA 已给报告，DEV 继续修复

1. 读取 `T05_VERSION_QA_REPORT.md`。
2. 在新的内网 `bundle` 中记录引用的旧报告。
3. 若主题未变，继续在原 `audit_topic` 下追加证据。
4. 维护 `dev_acknowledged` 和 `updated_at`。

---

## 5. QA 自动发现配合要求

QA 仍然允许只从以下根目录开始读取:

```text
outputs/_qa_external/t05_topology_between_rc
```

DEV 必须保证:
- 每个 `audit_topic` 目录下都存在 `audit_status.json`
- 以下状态即视为“可进入 QA”:
  - `scope_ready=true`
  - `evidence_ready=true`
  - `qa_report_ready=false`
- `evidence_ready=true` 不再等价于“已有新的内网 run”
- `updated_at` 必须在以下动作后真实更新:
  - 新建主题
  - 新增代码证据
  - 新增 pasted_text
  - 新增 inner_bundle
  - QA 报告回写
  - DEV 确认 QA 报告

---

## 6. 回溯修正要求

对以下范围内的已存在主题做语义回补:

```text
outputs/_qa_external/t05_topology_between_rc/by_version/
```

检查点:
- `audit_status.json` 不再把 `evidence_ready` 误解为“必须已有新 run”
- `latest_inner_run_id` / `latest_inner_patch_id` 允许写 `NA`
- `qa_blocked_reason` 不再写 `waiting_inner_run`
- `AUDIT_SCOPE.md` 补齐 `audit_trigger` / `static_audit_allowed`
- `EVIDENCE_INDEX.md` 即使没有 `inner_bundle` 也必须有代码侧证据

保留项:
- 既有内网 `bundle` 不删除
- 只是把其角色从“外网前置条件”修正为“外网补充证据”

---

## 7. 当前执行结论

本协议明确采用以下语义:
- 外网版本审计可以独立启动
- 内网执行证据是补强项
- QA 可以从根目录自动发现“最新应该审计”的主题
- 系统不再等待新的内网执行作为外网审计前置条件
