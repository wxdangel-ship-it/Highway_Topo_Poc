# T05 外网版本审计模板

用途:
- 这是外网版本审计模板。
- 它关注“某个版本 + 某个审计主题”的质量结论。
- 它不是单次执行记录，不直接替代内网 bundle。

建议目录:
- `outputs/_qa_external/t05_topology_between_rc/by_version/<git_sha>/<audit_topic>/T05_VERSION_QA_REPORT.md`

---

## 1. 审计范围

```yaml
git_sha: <required>
audit_topic: <required>
scope_reason: <required>
target_runs:
  - <run_id>
target_patches:
  - <patch_id>
evidence_sources:
  - <inner_bundle_path_or_text_source>
audit_time: <YYYY-MM-DD HH:MM>
```

## 2. 总体判断

必须先回答:
- 这是程序失败还是业务规则失败
- 第一优先级是补策略、修拓扑图、调 gate，还是回查输入

```text
<QA fill here>
```

## 3. 问题分类

把问题明确分到以下四类之一或多类:
1. 显式能力缺口
2. Step1 拓扑召回/闭合问题
3. Step2/3 几何 gate 过严
4. 真实坏样本

并打标签:
- Layer A: <INPUT_OK|INPUT_HARD_FAIL|INPUT_SOFT_DEGRADED|OUTPUT_INCONSISTENT>
- Layer B: <STEP1_CAPABILITY_GAP|STEP1_TOPOLOGY_RECALL_FAIL|STEP1_UNIQUE_ROUTE_FAIL|STEP1_OK>
- Layer C: <STEP2_GATE_TOO_STRICT|STEP2_TRUE_GEOMETRY_BAD|STEP3_ENDPOINT_BINDING_FAIL|STEP3_SHAPE_DEFORMATION|STEP2_3_OK>
- Layer D: <OUTPUT_CONSISTENT|OUTPUT_INCONSISTENT|OUTPUT_INSUFFICIENT_DEBUG>

```text
<QA fill here>
```

## 4. 证据链

每一类至少列:
- 对应 hard/soft reason
- 关键字段
- 对应 run / patch
- 对应 debug 文件
- 是否已跨多次执行重复出现

```text
[Issue-1]
- reason:
- key_fields:
- runs_patches:
- debug_files:
- repeatability:
- conclusion:

[Issue-2]
- reason:
- key_fields:
- runs_patches:
- debug_files:
- repeatability:
- conclusion:
```

## 5. 最小验证实验

每一类只给 1 个最小实验。

```text
[Issue-1]
- minimal_experiment:
- expected_signal:
- pass_fail_rule:

[Issue-2]
- minimal_experiment:
- expected_signal:
- pass_fail_rule:
```

## 6. 下一步修复优先级

必须明确:
- 应先补策略
- 先修拓扑图
- 先调 gate
- 还是先回查输入数据

```text
Priority-1:
Priority-2:
Priority-3:
Priority-4:
```

## 7. 版本级备注

这里可以写:
- 本次结论是否可外推到当前版本全部 patch
- 还是仅限某类 patch / 某个审计主题
- 当前证据还缺什么

```text
<QA fill here>
```

