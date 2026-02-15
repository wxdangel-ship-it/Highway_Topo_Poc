# Workspace Setup (WSL + Python)

## 1. 路径硬约束
- 本项目必须放在 Windows 的 E: 盘下
- WSL 下对应路径通常为：/mnt/e/...
- 推荐项目根目录：
  /mnt/e/Highway_Topo_Poc/

## 2. 路径相关注意事项
- 代码与配置尽量使用相对路径
- 外传文本中禁止出现任何本机绝对路径
- 若需要记录文件名，仅记录相对路径或逻辑名（不含盘符/挂载路径）

## 3. Python 环境
- 使用 WSL 的 Python（版本与依赖管理方式由实现者结合本机情况选择）
- 需要可一键运行（脚本/Makefile/命令均可）
