# 仓库结构入口

如果你要理解“现在这个仓库的标准结构是什么、哪些文档应该放在哪里、代码边界怎么控、执行入口怎么管”，先读：

1. `repository-structure-metadata.md`
2. `code-boundaries-and-entrypoints.md`
3. `code-size-audit.md`
4. `entrypoint-registry.md`
5. `../doc-governance/README.md`
6. `../doc-governance/module-lifecycle.md`

阅读原则：

- `repository-structure-metadata.md` 解释当前结构与文档白名单
- `code-boundaries-and-entrypoints.md` 解释当前单文件体量约束与执行入口脚本治理
- `code-size-audit.md` 给出当前超阈值源码 / 脚本文件清单
- `entrypoint-registry.md` 给出当前执行入口注册表
- `docs/doc-governance/README.md` 解释当前治理入口
- `docs/doc-governance/module-lifecycle.md` 解释模块状态，不解释目录布局

历史非标准文档请看 `../archive/nonstandard/`；历史治理过程请看 `../doc-governance/history/`；历史变更工件请看 `../../specs/archive/`。
