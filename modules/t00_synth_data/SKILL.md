# t00_synth_data - SKILL (Placeholder)

## 目标
- 提供一键生成可回归的合成/模拟测试数据集，用于外网回归与 CI。

## 输入
- dataset 配置（建议 YAML/JSON）：seed、patch_count、binN、异常 profile 等。

## 输出
- 合成数据集工件（dataset 目录或打包产物）
- 对应的 manifest（便于 tests/ 回归选择与对比）

## 验收
- 生成过程可复现（同 seed 输出一致）。
- 不依赖内网数据；可在纯外网环境运行。
- 生成的数据可被测试/回归流水线直接消费。

## 备注
- 本文件为占位；具体 CLI/脚本入口与接口契约在 Step 2 冻结。
