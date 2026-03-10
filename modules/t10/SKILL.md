# SKILL.md

## 1. Skill 名称

T10 - 复杂交叉路口建模

---

## 2. Skill 目标

本 Skill 用于对“普通道路复杂交叉路口”的理论可通行能力进行分层建模，输出 entry -> exit 的 movement 级默认通行结论。

当前版本只覆盖：
- 标准信号控制
- 平面复杂交叉路口
- 无显式规则条件下的默认通行能力

---

## 3. 适用场景

适用于以下场景：

- 需要从道路交通设计与安全性原则出发，判断某个 movement 是否理论可成立
- 同一 arm 下存在 2 条或以上平行进入/退出道路
- 需要区分：
  - 核心进口 / 非核心平行进口
  - 标准退出目标 / 非标准退出目标
  - 普通进口 / left-U-turn 服务进口 / 提前右转服务路候选关系
- 需要先在外网构建虚拟样例，再讨论接口与规则

---

## 4. 不适用场景

当前不适用于：

- 环岛
- 立交 / 互通
- 非信号控制路口
- 潮汐车道 / 可变车道
- lane-level 精细控制
- 实时配时或实时交通预测
- 已有完整显式规则覆盖的最终裁决

---

## 5. 四层处理流程

本 Skill 分四层工作。

### 5.1 T10.1 虚拟数据构建
作用：
- 在外网构建可讨论、可复核的复杂交叉路口样例
- 为 T10.2 / T10.3 提供测试样例和验收样例

输入关注：
- RCSDNode / RCSDRoad 语义
- arm 构成
- 进入/退出道路
- 需要验证的主规则

输出关注：
- 样例元信息
- road seed list
- approach 期望建模
- 关键 movement 期望结果

### 5.2 T10.2 路段建模
作用：
- 将进入/退出 Road 转成结构化路口模型
- 补齐 T10.3 判定所需字段

核心任务：
- 先按 `mainid` 对路口 node 集收口，不额外叠加 `Kind` / `id == mainid` 等附加过滤
- arm 分组（当前采用“近端粗分组 + 远趋势修正”的候选建模思路）
- entry / exit 拆分
- 核心 vs 非核心识别
- 同组进入道路左右相对次序内部建模
- 核心主进口优先候选识别
- 特殊 `approach_profile` 归一化
- 服务路与配对主路关系识别
- `exit_leg_role` 归一化
- `same_signalized_control_zone` 派生
- `parallel_cross_count` 建模

输出对象：
- `IntersectionModel`
- `ArmModel`
- `ApproachModel`

### 5.3 T10.3 无显式规则判定
作用：
- 基于 T10.2 的结构化对象
- 生成 movement 级默认通行结论

核心输出：
- `allowed`
- `allowed_with_condition`
- `forbidden`
- `unknown`

同时输出：
- `reason_codes`
- `reason_text`
- `confidence`
- `breakpoints`

### 5.4 T10.4 显式规则叠加
作用：
- 预留后续覆盖层
- 用于叠加禁转、专用相位、专用车道、时段限制等规则

当前状态：
- 仅保留接口位置
- 不进入实现讨论

---

## 6. T10.2 的核心建模语义

### 6.1 Arm
同一侧两个或以上平行道路，只要：
- 总体朝向一致
- 接入同一交叉口控制区

即可归为同一 `arm`。
`arm` / `arm_heading_group` 由 T10.2 建模派生，允许参考更远区域的道路趋势判断，不应简化成“只看局部几何角度”的硬规则。

当前候选建模思路（不是已冻结唯一算法）：
- 第一阶段：近端粗分组。基于 road 在 node 端的 away/tangent 向量做方向感知，先识别路口主轴 / 主方向组，再把各 approach 粗分到某一侧。
- 第二阶段：远趋势修正。仅在局部几何噪声、折线或短距离偏折导致模糊时，允许参考离开路口后更远一段的总体趋势做修正。
- 远趋势修正只用于修正模糊样本，不推翻已经明确的对向 / 相邻侧关系。
- `same arm` 的候选高层语义是：同一信号控制区内，近端指向同一宏观侧向、远趋势总体一致，且仍属于同一侧主路 / 辅路 / 平行路体系的道路，可优先归同一 `arm`。
- `arm_heading_group` 当前先作为抽象方向组使用，优先表达“同一侧 / 对向 / 相邻侧”的关系，不要求当前阶段绑定绝对东南西北。
- 本候选口径可参考 t04 中 node 端切向量、incoming/outgoing 识别、主轴 / 趋势轴的基础能力，但不能直接照搬 t04 的 merge/diverge 场景专用过滤规则。

### 6.2 Approach
每条 road 必须按方向拆成：
- `entry approach`
- `exit approach`

当前 T10.2 允许并需要对同组进入道路建立“相对车辆行进方向的左右相对次序”内部模型。
该能力用于：
- 核心主进口优先候选判断
- 提前左转 / 提前右转服务路与配对主路识别

但当前不要求把左右次序暴露成 T10.3 的对外硬字段。
其中提前右转服务路及其配对主路当前仅作为 T10.2 可识别的候选业务关系 / 预留扩展点，不作为当前正式 `approach_profile` 枚举值。
同一 arm 内的左右相对次序内部建模，当前直接服务于：
- 无提前左转服务路时的核心主进口优先候选识别
- `left_uturn_service` 与其右侧紧邻配对主路识别
- 提前右转服务路候选与其左侧紧邻配对主路候选识别（仅预留扩展）

### 6.3 Core vs Non-core
需要区分：
- `is_core_signalized_approach = true`
- `is_core_signalized_approach = false`
- `unknown`

### 6.4 Special Profile
需要归一化出：
- `default_signalized`
- `left_uturn_service`
- `paired_mainline_no_left_uturn`
- `unknown`

补充说明：
- 提前右转服务路及其配对主路当前可作为 T10.2 的候选业务关系识别与预留扩展点
- 当前尚未纳入正式 `approach_profile` 枚举
- 当前不进入 T10.3 已冻结默认规则分支

### 6.5 Exit Role
需要归一化出：
- `core_standard_exit`
- `service_standard_exit`
- `auxiliary_parallel_exit`
- `access_exit`
- `unknown`

高层业务口径摘要：
- 一级分界优先按“该目标是否属于该信号路口默认交通组织应服务的退出目标”切分。
- 道路等级、主辅属性、几何贴近程度只作为辅助证据，不作为主判据。
- `core_standard_exit`：某一退出方向最核心、最正规的主接收出口；同一 arm 原则上最多 1 条。
- `service_standard_exit`：正规但次一级，仍属于默认应被服务的退出目标。
- `auxiliary_parallel_exit`：仍属道路体系内部，但默认不应被本路口直接服务的平行/辅助去向。
- `access_exit`：主要进入停车场、场站、院落、沿街地块等具体接入对象。
- `unknown`：仅在缺关键证据时触发，不能因为规则未细化或实现未完成而直接落入 `unknown`。

### 6.6 Derived Fields
关键派生包括：
- `is_standard_exit_leg`
- `same_signalized_control_zone`
- `parallel_cross_count`

当前 MVP 口径：
- 一个路口先按 `mainid` 收口，不额外过滤
- 同一 `mainid` 即视为同一信号控制区
- `arm` / `arm_heading_group` 当前采用“近端粗分组 + 远趋势修正”的候选建模思路，但尚未冻结成唯一算法
- `arm_heading_group` 当前先作为抽象方向组使用，优先表达“同一侧 / 对向 / 相邻侧”关系
- 在没有提前左转服务路时，同一进入路段组中，相对车辆行进方向最靠左侧的道路，为核心主进口的优先候选
- 若存在 `left_uturn_service`：其右侧紧邻进入道路视为配对主路
- 若存在提前右转服务路候选：其左侧紧邻进入道路可记为配对主路候选，作为预留扩展点
- “左 / 右”均按相对车辆行进方向理解

---

## 7. T10.3 默认判定逻辑摘要

默认判定顺序为：

**门控层 → 目标出口角色层 → 平行跨越层 → 特殊画像层 → 一般默认层 → Unknown 保守修正层**

补充说明：
- `turn_sense` 是 T10.3 派生量，负责回答“往哪转”；当前候选冻结口径是“arm 关系优先，近端几何角度做修正”，不是底层直接字段，也不是当前唯一实现算法
- `parallel_cross_count` 负责回答“跨了几层平行走廊”；当前候选冻结口径是“先按 source / target 所在走廊关系认 0 / 1”，并保持 `0 / 1 / 2+` 的高层语义
- `turn_sense` 与 `parallel_cross_count` 正交：前者解决转向语义，后者解决横向走廊切换层级；二者不互相替代
- same-arm target 当前候选上优先归入 `uturn` 家族；其是否发生横向切换，由 `parallel_cross_count` 表达，而不是改判成同 arm 的 `left/right`
- “跨到隔了一层以上的平行路，即记为 `2+`”这一业务定义已冻结；`0 / 1` 的更细派生规则仍属后续实现细化项

### 7.1 门控层
优先排除：
- source 不是 `entry`
- target 不是 `exit`
- 不在同一信号控制区

### 7.2 目标出口角色层
优先处理 target 的 `exit_leg_role`：
- `core_standard_exit` / `service_standard_exit` → 进入后续规则
- `auxiliary_parallel_exit` / `access_exit` → 默认 `forbidden`
- `unknown` → 不直接硬否决，但更保守

补充说明：
- target 侧角色判定优先于 source 特殊画像层和一般默认层。
- `service_standard_exit` vs `auxiliary_parallel_exit` 的主判据，不是“是否靠近主出口”，而是“是否属于默认交通组织应服务目标”。
- `auxiliary_parallel_exit` vs `access_exit` 的主判据，是“仍属道路体系内部”还是“进入具体接入对象”。

### 7.3 平行跨越层
- `parallel_cross_count = 0` → 标准 movement
- `parallel_cross_count = 1` → 默认 `unknown`
- `parallel_cross_count = 2+` → 默认 `forbidden`

当前候选冻结口径摘要：
- `turn_sense`：
  - `source_arm` 与 `target_arm` 为对向 → 优先 `through`
  - `source_arm` 与 `target_arm` 为相邻侧 → 优先 `left/right`
  - `source_arm` 与 `target_arm` 为同一侧 → 优先 `uturn`
  - 近端几何角度、进入 / 退出趋势只用于修正边界模糊样本
- `parallel_cross_count`：
  - `0`：到达 target 不需要切到相邻一层平行走廊，仍属于标准走廊到达
  - `1`：到达 target 需要切到紧邻一层平行走廊
  - `2+`：跨到隔了一层以上的平行路
  - `parallel_cross_count` 与 `exit_leg_role` 相关但不等价
  - 当 `target.exit_leg_role = unknown` 时，若走廊关系仍能稳定识别，仍应尽量独立给出 `0/1`

### 7.4 特殊画像层
#### `left_uturn_service`
- `left` → `allowed`
- `uturn` → `allowed`
- `through` → `forbidden`
- `right` → `forbidden`

#### `paired_mainline_no_left_uturn`
- `left` → `forbidden`
- `uturn` → `forbidden`
- `through` → 按一般规则
- `right` → 按一般规则

### 7.5 一般默认层
在未被前序规则覆盖时：
- `right` → `allowed`
- `through` → `allowed`
- 核心 `left` → `allowed`
- 非核心普通 `left` → `unknown`
- 普通 `uturn` → `unknown`

### 7.6 Unknown 保守修正层
当 `exit_leg_role = unknown` 时：
- `right` / `through` 可继续判，但更保守
- `left` / `uturn` / 单层平行转移 → 优先 `unknown`

---

## 8. T10.3 状态定义

### `allowed`
在当前默认规则下，可直接判为理论可通行。

### `allowed_with_condition`
理论可成立，但需要附加条件。
当前 MVP 中这一状态保留，但尚不是主分支重点。

### `forbidden`
在当前默认规则下，明确不应成立。

### `unknown`
当前证据不足，或按照冻结口径应保守处理。

---

## 9. T10 当前核心业务结论（摘要）

当前已冻结的关键业务结论包括：

- 标准 `right` 默认 `allowed`
- 标准 `through` 默认 `allowed`
- 非核心平行进口沿自身走廊的标准 `through` 仍为 `allowed`
- 核心标准 `left` 默认 `allowed`
- 普通 `uturn` 默认 `unknown`
- 单层平行转移默认 `unknown`
- 跨两层及以上平行走廊默认 `forbidden`
- `turn_sense` 当前候选采用“arm 关系优先、几何修正”的高层口径
- same-arm target 当前候选优先归入 `uturn` 家族，而不是改判为同 arm 的 `left/right`
- `parallel_cross_count` 当前候选采用“0 / 1 优先按走廊关系表达”的高层口径
- `exit_leg_role` 的一级分界优先按“是否属于默认交通组织应服务目标”切分
- `core_standard_exit` 与 `service_standard_exit` 当前都属于标准退出目标，但前者是主出口、后者是正规但次一级出口
- `auxiliary_parallel_exit` 与 `access_exit` 当前都属于非标准退出目标，但前者仍属道路体系内部，后者主要进入具体接入对象
- `left_uturn_service` 是强画像，不是弱提示
- `paired_mainline_no_left_uturn` 的左转/调头禁止必须与服务道路成对生效
- 提前右转服务路及其配对主路当前仅为预留扩展关系，尚未纳入正式默认规则
- 目标出口角色优先于表面几何顺畅感

---

## 10. 当前虚拟样例体系

当前已形成首批样例：

### `T10V_01`
基础四臂标准信号路口  
验证基础默认规则

### `T10V_02`
主辅路互转默认 Unknown  
验证 `parallel_cross_count = 1`

### `T10V_03`
非核心平行进口标准 through Allowed  
验证非核心 through 不被误降级

### `T10V_04`
left/U-turn service road 与配对主路  
验证 `approach_profile` 的优先级和配对关系

### `T10V_05`
非标准退出目标默认 Forbidden  
验证 `exit_leg_role` 与 A3 规则

### `T10V_06`
三层平行路跨两层默认 Forbidden  
验证 `parallel_cross_count = 2+`

### `T10V_07`
`exit_leg_role = unknown` 的保守处理  
验证 unknown 不是硬否决，但要更保守

后续建议样例：

### `T10V_08`
`service_standard_exit` vs `auxiliary_parallel_exit` 对比样例  
目的：专门区分二者分界不取决于“是否靠近主出口”，而取决于“是否属于默认交通组织应服务目标”

### `T10V_09`
`turn_sense` 与 `parallel_cross_count(0/1)` 组合对比样例  
目的：证明二者是正交关系，覆盖 `left+0`、`left+1`、`uturn+0`、`uturn+1` 等组合，并验证 same-arm target 优先归入 `uturn` 家族，而横向切换由 `parallel_cross_count` 表达

---

## 11. 输出定义

### 11.1 结构化输出
T10.3 的底层输出应至少包含：
- `movement_id`
- `source_approach_id`
- `target_approach_id`
- `status`
- `confidence`
- `reason_codes`
- `reason_text`

可选：
- `evidence_refs`
- `breakpoints`
- `assumptions_used`

### 11.2 Excel 审查输出
对外审查载体可为 Excel：
- 列：entry approach
- 行：exit approach
- 单元格至少含：
  - `status`
  - 主 `reason_code`
  - 简短解释

附加 sheet 建议：
- `Meta`
- `ApproachMapping`
- `ReasonCodeDict`
- `Breakpoints`

---

## 12. Breakpoints 定义

以下情况必须显式作为 breakpoint 或 unknown 原因输出：

- `same_signalized_control_zone` 无法判断
- `exit_leg_role` 无法稳定识别
- `approach_profile` 无法稳定归一化
- `turn_sense` 无法稳定识别
- `parallel_cross_count` 无法稳定判断
- source / target 角色冲突
- 场景超出当前 MVP 范围

原则：
- 不允许 silent pass
- 不允许把“未建模”伪装成“自然 unknown”

---

## 13. 当前阶段的执行策略

当前阶段推荐执行策略是：

1. 先读文档，不写代码  
2. 先做字段映射分析，再谈实现  
3. 先确保样例、规则、接口三者一致  
4. 没有用户明确授权前，不进入 T10 代码开发  
5. 不修改 t00–t07，不改项目级主线文档

---

## 14. CodeX 使用注意事项

后续若由 CodeX 读取本模块文档，应先执行：

- 阅读根目录 `AGENTS.md`
- 阅读 `modules/T10/AGENTS.md`
- 阅读 `modules/T10/SKILL.md`
- 阅读 `modules/T10/INTERFACE_CONTRACT.md`

然后先输出理解摘要：
- 模块边界
- 字段对齐原则
- 当前默认规则
- 当前样例体系
- 仍不明确的字段或枚举

字段无法对应时：
- 先与用户对齐
- 不允许擅自发明底层字段语义

---

## 15. 后续扩展方向

后续可扩展但当前不处理的方向包括：

- T10.4 显式规则覆盖
- lane group / lane level 建模
- 更细的几何和渠化表达
- 标志、标线、信号相位、时间条件
- 输出 `RoadNextRoad` 拓扑图层
- 与真实内网道路数据的稳定对接

---

## 16. Skill 使用结论

本 Skill 当前的正确使用方式不是“立即编码”，而是：

- 用它统一 T10 的业务语义
- 用它约束 T10.2 的建模职责
- 用它约束 T10.3 的默认判定顺序
- 用它指导后续 CodeX 先读文档、再做字段映射、最后才进入实现
