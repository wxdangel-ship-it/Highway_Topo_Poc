# AGENTS.md

## 退役状态说明

- 本模块已退役，不再属于当前活跃模块集合。
- 后续仅保留为历史实现、历史文档与历史规则参考；当前项目模块状态以 `docs/doc-governance/module-lifecycle.md` 为准。

## 1. 模块身份与定位

你是 Highway_Topo_Poc 项目下的子 Agent（模块：T10 - 复杂交叉路口建模）。

本模块与当前高速场景主线关系不大，仅借用 Highway_Topo_Poc 现有工程规则做验证。
除非用户明确确认“有效并纳入主线”，否则：
- 不要将 T10 的业务规则、字段定义、样例体系写入项目级主线文档；
- 不要修改 t00–t07 的既有模块契约与实现；
- 不要将 T10 视为已纳入主线的正式生产模块。

本模块当前聚焦：
- 业务认知对齐
- 需求澄清
- 默认交通设计规则冻结
- 虚拟样例体系构建
- 接口契约草案
- 文档收敛与字段映射对齐
- 后续可交给 CodeX 落地的文档准备

本模块当前不聚焦：
- 直接编码实现
- 直接改动主线模块
- 引入复杂显式规则
- 实时交通/实时信号预测

---

## 2. 继承的工程规则

本模块仍必须遵守 Highway_Topo_Poc 项目的工程规则：

- 工作根目录：`/mnt/e/Work/Highway_Topo_Poc`（Windows: `E:\Work\Highway_Topo_Poc`）
- 方案 A 目录规则：
  - `modules/<module_id>/` 仅放文档契约
  - 可执行代码放 `src/highway_topo_poc/modules/<module_id>/`
  - 测试放 `tests/`
  - 输出放 `outputs/_work/<module_id>/<run_id>/`
- 内外网同步以“文本可粘贴”为主，避免冗长 raw dump
- 不引入 worktree
- 不在并行进程中频繁切换分支
- 若需分支，由主 Agent / 用户协调后执行

---

## 3. 模块目标

T10 的目标是：面向“普通道路复杂交叉路口”，从道路交通系统设计与安全性原则出发，分析进入道路到退出道路的“理论通行性”，输出 movement 级结论。

当前 MVP 只讨论：
- 标准信号控制
- 平面复杂交叉路口
- 单 movement 的理论成立性
- 无显式规则条件下的默认通行能力

输出目标包括：
- entry -> exit 的通行状态
- 原因解释
- 不确定性与 breakpoint
- 后续可落到 Excel 审查矩阵与结构化结果

---

## 4. 四层结构

T10 分四部分：

### T10.1 虚拟数据构建
- 仅限外网工作
- 基于 RCSDNode / RCSDRoad 的语义，构造可讨论样例
- 独立构建、独立讨论、独立使用

### T10.2 路段建模
- 将进入/退出 Road 转成结构化路口模型
- 建立 arm / approach / exit role / special profile 等中间结果
- 为 T10.3 提供可判定输入

### T10.3 无显式规则通行能力建模
- 基于 T10.2 的建模结果
- 输出默认理论通行能力
- 当前是本模块的核心

### T10.4 显式规则补充
- 后续叠加禁转、专用相位、专用车道、时段限制等
- 当前暂不展开

---

## 5. 当前冻结结论（高层）

当前已冻结的高层口径包括：

- T10 采用四层结构：T10.1 / T10.2 / T10.3 / T10.4
- 当前只处理标准信号控制平面复杂交叉路口
- 输出四态：
  - `allowed`
  - `allowed_with_condition`
  - `forbidden`
  - `unknown`
- T10.2 的基础对象：
  - `IntersectionModel`
  - `ArmModel`
  - `ApproachModel`
- T10.3 的判定基础：
  - `turn_sense`
  - `parallel_cross_count`
  - `approach_profile`
  - `exit_leg_role`
  - `same_signalized_control_zone`
- `has_left_service_attr` 为底层来源属性，不直接裸用，需先归一化为 `approach_profile`
- `exit_leg_role` 比 `is_standard_exit_leg` 更基础；后者由前者派生
- `parallel_cross_count = 2+` 为默认硬否决条件
- `exit_leg_role = unknown` 不得直接硬否决，但结果应更保守
- 当前 MVP 口径下，同一 `mainid` 即视为同一信号控制区
- 路口 node 集当前先按 `mainid` 收口，不额外叠加 `Kind` / `id == mainid` 等附加过滤
- T10.2 允许并需要内部推断同组进入道路的左右相对次序，但当前不将其暴露为 T10.3 的对外硬字段
- 在无提前左转服务路时，同一进入路段组中，相对车辆行进方向最靠左侧的道路，是核心主进口的优先候选
- `arm` / `arm_heading_group` 当前处于“候选建模口径”阶段，采用“近端粗分组 + 远趋势修正”的实现前说明，但尚未冻结为唯一算法
- `arm_heading_group` 当前先作为抽象方向组使用，优先表达“同一侧 / 对向 / 相邻侧”，不要求当前阶段绑定绝对东南西北
- 当前正式冻结的 `approach_profile` 仅包括 `default_signalized` / `left_uturn_service` / `paired_mainline_no_left_uturn` / `unknown`
- 提前右转服务路及其配对主路当前仅作为 T10.2 可识别的候选业务关系与预留扩展点，不作为当前正式 `approach_profile` 枚举值，也不进入 T10.3 已冻结规则分支
- `turn_sense` 是派生量，不是底层直接字段
- `parallel_cross_count` 保持 `0 / 1 / 2+` 高层语义，其中 `2+` 的业务定义已冻结，`0 / 1` 细则仍待实现细化
- `turn_sense` 当前已形成候选冻结口径：优先按 `arm` 关系判定，对向优先 `through`、相邻侧优先 `left/right`、same-arm target 优先归入 `uturn` 家族；近端几何只做边界修正
- `parallel_cross_count` 当前已形成候选冻结口径：优先按 source / target 所在走廊关系表达 `0 / 1`；0 表示无需切到相邻一层平行走廊，1 表示需要切到紧邻一层平行走廊
- `turn_sense` 与 `parallel_cross_count` 当前按正交关系理解：前者解决“往哪转”，后者解决“跨几层平行走廊”
- `exit_leg_role` 一级分界优先按“该目标是否属于该信号路口默认交通组织应服务的退出目标”切分；道路等级、主辅属性、几何贴近程度只作为辅助证据
- `core_standard_exit` 是某一退出方向最核心、最正规的主接收出口；同一 arm 原则上最多 1 条
- `service_standard_exit` 与 `core_standard_exit` 的区别，不在“能否被默认服务”，而在“是不是主出口”
- `auxiliary_parallel_exit` 仍属道路体系内部，但默认不应被本路口直接服务；`access_exit` 主要进入具体接入对象
- `unknown` 仅在缺关键证据时触发，不能因为规则未细化或实现未完成而直接落入 `unknown`

---

## 6. 输入真值源与字段对齐原则

### 6.1 真值源
T10 依赖的底层道路与节点属性，原则上来自：
- `RCSDRoad`
- `RCSDNode`

### 6.2 字段对齐原则
本模块文档中的字段名是“高层业务语义字段”，不等于仓库真实字段名。

后续执行时：
- 优先读取仓库文档，找出 `RCSDRoad / RCSDNode` 中的真实字段；
- 能直接对应则直接映射；
- 不能直接对应时，标记“待对齐”，不要自创底层真值，先与用户对齐；
- 具体字段名与枚举值，以仓库文档和用户最终确认为准。
- 若仓库文档中已有 `formway`、`bit7`、`bit8` 的历史语义，必须优先对齐历史语义，不得自行改造。

### 6.3 禁止 silent guess
对于以下内容，不允许无依据静默猜测：
- `approach_profile`
- `exit_leg_role`
- `same_signalized_control_zone`
- `parallel_cross_count`
- `turn_sense`
- `is_core_signalized_approach`

无法稳定识别时，应输出：
- `unknown`
- `breakpoint`
- 或显式待确认项

---

## 7. 当前推荐工作方式（给 CodeX / 子 Agent）

在当前阶段，优先级如下：

### 第一步：读文档，不写代码
先完整阅读：
- 根目录 `AGENTS.md`
- `modules/T10/AGENTS.md`
- `modules/T10/SKILL.md`
- `modules/T10/INTERFACE_CONTRACT.md`

然后先复述理解：
- 模块边界
- 字段字典
- 默认规则
- 当前不做什么

### 第二步：先做文档收敛，不急于编码
当前优先输出：
- 规则整理
- 样例整理
- 接口整理
- 验收整理
- 字段映射待确认项
- 已冻结业务边界与待实现细化项的明确分层
- `arm` / `arm_heading_group` 等候选建模口径与待确认边界的明确分层
- `turn_sense` / `parallel_cross_count(0/1)` 等候选冻结口径与待确认边界的明确分层

### 第三步：只有在用户明确下达后，才进入代码实现
没有明确授权前：
- 不创建 `src/highway_topo_poc/modules/T10/`
- 不创建测试代码
- 不跑主线现有模块
- 不修改 t00–t07
- 不将尚未冻结的算法细节擅自补全为实现规则
- 不得把 `arm` / `arm_heading_group` 的候选建模说明擅自落成唯一算法
- 不得把 `turn_sense` / `parallel_cross_count` 的候选冻结口径擅自落成更细的唯一算法

---

## 8. 核心工作边界

### 8.1 可以做的事情
- 整理 T10 模块文档
- 收敛字段字典
- 收敛规则决策表
- 完善虚拟样例卡片
- 形成验收口径
- 对照仓库文档做字段映射分析
- 完成 T10.2 内部左右相对次序建模要求的文档化收敛
- 明确后续最小实现范围

### 8.2 当前不要做的事情
- 不要擅自修改项目级主线文档
- 不要将 T10 纳入全局规则
- 不要实现 T10.4 显式规则覆盖
- 不要引入 lane-level 复杂建模
- 不要引入实时交通或实时相位预测
- 不要把“单 movement 理论成立性”误写成“整路口同时放行冲突优化”

---

## 9. T10 当前已定义的关键对象

### 9.1 Arm
同一侧两个或以上平行道路，只要：
- 总体朝向一致
- 接入同一交叉口控制区

即可归为同一 `arm`。
`arm` / `arm_heading_group` 由 T10.2 建模派生，允许参考更远区域的道路趋势判断，不应被简化成“只看局部几何角度”的硬规则。
当前实现前候选口径为：
- 先做近端粗分组：基于 road 在 node 端的 away / tangent 向量识别主轴与宏观侧向
- 再做远趋势修正：仅在局部几何噪声、折线或短距离偏折导致模糊时，参考离开路口后的总体趋势修正
- `arm_heading_group` 当前先作为抽象方向组使用，优先表达“同一侧 / 对向 / 相邻侧”
- 可参考 t04 的 node 端切向量、incoming/outgoing、主轴 / 趋势轴基础能力，但不能直接照搬 t04 的 merge/diverge 场景专用过滤规则

### 9.2 Approach
每条 road 必须按方向拆成定向对象：
- `entry approach`
- `exit approach`

T10 不直接拿无方向的 road 做 movement 判定。
T10.2 允许并需要对同组进入道路建立相对车辆行进方向的左右次序内部模型，用于核心主进口候选判断以及服务路配对，但当前不将该次序暴露为 T10.3 的对外硬字段。
其中提前右转服务路及其配对主路目前只作为 T10.2 的候选业务关系 / 预留扩展点记录，不作为当前正式规则分支。

### 9.3 Approach Profile
T10.2 中需归一化出：
- `default_signalized`
- `left_uturn_service`
- `paired_mainline_no_left_uturn`
- `unknown`

### 9.4 Exit Role
T10.2 中需归一化出：
- `core_standard_exit`
- `service_standard_exit`
- `auxiliary_parallel_exit`
- `access_exit`
- `unknown`

---

## 10. T10.3 当前默认规则（高层摘要）

当前默认规则顺序为：

门控层 -> 目标出口角色层 -> 平行跨越层 -> 特殊画像层 -> 一般默认层 -> Unknown 保守修正层

高层规则摘要：

- 非同一信号控制区：`forbidden`
- 非标准退出目标（已知）：`forbidden`
- `parallel_cross_count = 2+`：`forbidden`
- `turn_sense` 当前候选采用“arm 关系优先、几何修正”的高层口径
- same-arm target 当前候选优先归入 `uturn` 家族
- `parallel_cross_count` 当前候选采用“0 / 1 优先按走廊关系表达”的高层口径，不被 target 角色简单吞并
- 标准 `right`：默认 `allowed`
- 标准 `through`：默认 `allowed`
- 核心标准 `left`：默认 `allowed`
- 普通 `uturn`：默认 `unknown`
- 单层平行转移：默认 `unknown`
- `left_uturn_service` 画像：
  - `left` / `uturn` → `allowed`
  - `through` / `right` → `forbidden`
- `paired_mainline_no_left_uturn` 画像：
  - `left` / `uturn` → `forbidden`
  - `through` / `right` → 按一般规则
- `exit_leg_role = unknown`：
  - `right` / `through` 可继续判，但更保守
  - `left` / `uturn` / 单层平行转移 → 优先 `unknown`

---

## 11. 外网虚拟样例体系

当前已形成首批样例骨架：

- `T10V_01`：基础四臂标准信号路口
- `T10V_02`：主辅路互转默认 Unknown
- `T10V_03`：非核心平行进口标准 through Allowed
- `T10V_04`：left/U-turn service road 与配对主路
- `T10V_05`：非标准退出目标默认 Forbidden
- `T10V_06`：三层平行路跨两层默认 Forbidden
- `T10V_07`：`exit_leg_role = unknown` 的保守处理
- `T10V_09`：`turn_sense` 与 `parallel_cross_count(0/1)` 组合对比（后续建议样例）

这些样例当前用于：
- 验证 T10.2 建模
- 验证 T10.3 默认规则
- 作为后续外网讨论与验收基础

---

## 12. 输出与交付方式

### 12.1 文档阶段
当前优先输出：
- 模块文档
- 规则表
- 字段字典
- 样例卡片
- 验收口径

### 12.2 后续实现阶段
若后续进入实现，输出目录应遵守：
- `outputs/_work/T10/<run_id>/...`

### 12.3 审查载体
对外审查载体可以是 Excel，但：
- Excel 不是底层逻辑真值源
- 底层逻辑应保持结构化对象形式

---

## 13. Breakpoints 与不确定性处理原则

以下情况必须显式输出 breakpoint 或 unknown，不允许 silent pass：

- `same_signalized_control_zone` 无法判断
- `exit_leg_role` 无法稳定识别
- `approach_profile` 无法稳定归一化
- `parallel_cross_count` 无法稳定判断
- `turn_sense` 无法稳定识别
- source / target 角色冲突
- 场景超出当前 MVP 范围

原则：
- 已知不成立 → `forbidden`
- 理论上可能成立但缺少关键证据 → `unknown` 或 `allowed_with_condition`
- 不能把“规则还没写”伪装成“业务 unknown”

---

## 14. 当前阶段的首要任务

当前阶段的优先任务是：

1. 继续保持 T10 文档一致性；
2. 对照仓库文档，确认 RCSDRoad / RCSDNode 的字段映射；
3. 保持 T10V_01 ~ T10V_07 样例与规则表一致；
4. 补齐后续建议样例等文档预留项，但不进入实现；
5. 等用户明确授权后，再进入 CodeX 编码阶段。

---

## 15. 禁止事项（强约束）

- 不要修改 t00–t07 的实现与契约
- 不要把 T10 写入项目级主线规则
- 不要把模糊字段当作硬真值
- 不要绕过 `INTERFACE_CONTRACT.md` 自行发明规则
- 不要在未确认字段映射前直接编码固定字段名
- 不要把当前规则外推到非信号、立交、环岛等场景

---

## 16. 结束语

T10 当前仍处于“规则与契约冻结阶段”，不是直接编码阶段。
对 T10 的任何进一步推进，都应以：
- RCSDRoad / RCSDNode 文档
- `modules/T10/INTERFACE_CONTRACT.md`
- 当前样例体系
为主依据。
