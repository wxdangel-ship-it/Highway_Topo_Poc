# ARTIFACT_PROTOCOL（全局）- 文本粘贴回传优先

- 项目：Highway_Topo_Poc
- 版本：v1.0
- 目的：定义「内网执行后 → 外网分析」唯一允许的回传形态（文本粘贴）。
- 适用范围：t01–t05 全模块；batch 汇总同理。

---

## 0. 总原则（硬约束）

1) 回传方式：**仅允许文本粘贴**（不能传文件、不能传图片、不能传点云片段）。
2) 严禁信息：**任何坐标本身**、任何几何顶点数组、任何内网路径/机器信息/账号信息。
3) 内容风格：尽量不出现“具体问题数据明细”，以 **精度/分位数（方案A）+ 阈值 + 问题类型枚举 + 严重程度 + Top-K 摘要** 为主。
4) 体积控制：必须考虑一次性粘贴长度；超长必须截断并给出摘要（见第 4 节）。

---

## 1. 允许与禁止清单

### 1.1 允许（推荐）
- 指标分位数：p50 / p90 / p99（方案A）
- 阈值与参数：例如 z_diff_threshold=0.20（必须可配置，回传时只列关键参数）
- 计数、比例、长度占比：count / pct / len_pct
- **索引化位置**：bin 区间（用于定位，不是坐标）
- 匿名 PatchID / 运行ID / 配置摘要哈希（digest）

### 1.2 禁止（必须避免）
- 任何坐标：x/y/z 绝对值、lat/lon、utm、epsg、wgs84 等
- 任何几何顶点序列：GeoJSON geometry 坐标数组、WKT、polyline/polygon 点列
- 内网文件路径（如 /data/...、盘符映射、用户名目录）、机器名、IP、账号信息
- 大段逐帧/逐点/逐区间明细（超过 Top-K），长数组、原始序列 dump

---

## 2. 位置表达：Index Bin 区间（用于定位）

为支持外网定位问题，但不泄露坐标，统一使用 bin 区间表达“发生位置”。

### 2.1 定义
- 每个 patch 在运行时定义一个单调标量轴（例如：采样序号 seq、时间 t、或里程 s）。
- 将标量轴离散化为 N 个 bin（推荐 N=1000；可配置）。
- 区间位置仅允许用 [bin_start, bin_end] 表达：
  - bin_start / bin_end：整数，范围 0..N-1
  - len_pct：该区间占整个轴的比例（百分比）

### 2.2 禁止
- 禁止在文本回传中出现任何“可还原为坐标”的信息（例如绝对里程值、投影信息等）。
- 允许出现 binN=N（因为 N 只是离散粒度）。

---

## 3. 外传文本包格式：TEXT_QC_BUNDLE v1（单 patch + 单模块）

### 3.1 体积上限（建议作为硬上限）
- 每个 (patch, module) 文本块：**<= 120 行 或 <= 8KB**（任一达到即截断）
- 超出后必须：
  - 只保留关键头部 + Metrics Top-N + 区间 Top-3 + Errors Top-3
  - 增加一行：`Truncated: true (reason=...)`

### 3.2 标准模板（必须按此结构输出）

（以下为“文本结构模板”，运行时用实际值替换尖括号内容）

=== Highway_Topo_Poc TEXT_QC_BUNDLE v1 ===  
Project: Highway_Topo_Poc  
Run: <run_id>  Commit: <short_sha_or_tag>  ConfigDigest: <8-12chars>  
Patch: <patch_uid_or_alias>  Provider: <file|synth>  Seed: <int_or_na>  
Module: <t01|t02|t03|t04|t05>  ModuleVersion: <semver_or_sha>  

Inputs: traj=<ok|missing>  pc=<ok|missing>  vectors=<ok|missing>  ground=<ok|missing>  
InputMeta: <type/resolution/field_availability_summary; NO PATH; NO COORD>  

Params(TopN<=12): <k1=v1; k2=v2; ...>  

Metrics(TopN<=10):  
- <metric_name_1>: p50=<num> p90=<num> p99=<num> threshold=<num|na> unit=<...>  
- <metric_name_2>: p50=<num> p90=<num> p99=<num> threshold=<num|na> unit=<...>  

Intervals(binN=<N>):  
- type=<enum>  count=<int>  total_len_pct=<num%>  
  top3=(<b0>-<b1>, severity=<low|med|high>, len_pct=<%>); (<b0>-<b1>, ...); (<b0>-<b1>, ...)  

Breakpoints: [<enum1>, <enum2>, ...]  
Errors: [<reason_enum>:<count>, <reason_enum>:<count>, ...]  
Notes: <1-3 lines max>  
Truncated: <true|false> (reason=<na|size_limit|...>)  
=== END ===  

---

## 4. Batch 汇总文本（可选但强烈建议）

当一次跑多个 patch/多个模块时，建议额外输出一个 batch 总览，便于外网快速归因：
- 上限：<= 200 行 或 <= 16KB
- 内容：每模块 ok/warn/fail 计数；Top 错误原因；Top 断点；最常见区间类型（Top-3）
- 禁止：仍然禁止坐标/几何/路径/长列表

---

## 5. 与内网本地文件的关系（说明）

- 内网可以生成本地文件（如 report.json、artifact_index.json 等）用于内部排查，但外传只能粘贴符合本协议的文本。
- 外网分析以 TEXT_QC_BUNDLE 与 batch summary 为唯一输入，不依赖内网文件。
