# 实施计划：单文件体量约束 + 执行入口脚本治理

**分支**：`008-code-boundary-entrypoint-governance` | **日期**：2026-03-17 | **规格**：[spec.md](/mnt/e/Work/Highway_Topo_Poc/specs/008-code-boundary-entrypoint-governance/spec.md)

## 1. 实施原则

- root `AGENTS.md` 只增加最小规则，不扩成总说明书
- 详细解释下沉到 `docs/repository-metadata/`
- 本轮只做现状审计，不做文件拆分或脚本迁移
- 输出超阈值文件清单与执行入口注册表
- 不引入新工具链

## 2. 目标产物

```text
AGENTS.md
docs/repository-metadata/
+-- README.md
+-- repository-structure-metadata.md
+-- code-boundaries-and-entrypoints.md
+-- code-size-audit.md
+-- entrypoint-registry.md
docs/metadata-cleanup/
+-- constraint-4-5-governance-report.md
specs/008-code-boundary-entrypoint-governance/
+-- spec.md
+-- plan.md
+-- tasks.md
```

## 3. 审计方法

### 3.1 文件体量审计

- 扫描源码 / 脚本文件
- 排除 `.git/`、`outputs/`、`runs/`、`data/`、第三方依赖目录
- 以 `100 KB` 为阈值，记录路径、大小、文件类型、模块状态和建议动作

### 3.2 执行入口识别

- 识别 repo root 下的独立执行面
- 识别 `scripts/`、`tools/` 下的独立脚本
- 识别模块级 `__main__.py`、`run.py` 或同类独立入口
- 识别验证 / 审计类独立启动脚本
- 排除共享辅助脚本与内部实现模块

## 4. 风险与控制

- 风险：把内部辅助脚本误记为入口
  - 控制：只有独立启动面才入注册表
- 风险：把测试 / 工具大文件遗漏出体量审计
  - 控制：按文件类型统一扫描，不只看活跃模块
- 风险：`AGENTS.md` 被写得过大
  - 控制：只补两条规则和一个详细文档指针

## 5. 交付策略

1. 先完成真实仓库审计
2. 再落 `spec / plan / tasks`
3. 再写 repo 级规则与 detailed docs
4. 最后写执行报告并提交推送
