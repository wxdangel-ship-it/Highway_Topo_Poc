# INTERFACE_CONTRACT.md

Module: T10 - 复杂交叉路口建模
Status: Draft v0.1
Scope: 标准信号控制平面复杂交叉路口；无显式规则默认通行能力建模
Out of Scope:
- 环岛
- 立交/互通
- 潮汐车道/可变车道
- 非信号控制路口
- 实时配时/实时交通状态预测
- T10.4 显式规则叠加后的最终裁决

---

## 1. 模块定位

T10 用于对“普通道路复杂交叉路口”的理论可通行能力进行建模与评估，输出进入道路到退出道路的 movement 级结论。

本模块当前只讨论：
- 标准信号控制
- 平面复杂交叉路口
- 单 movement 的理论成立性
- 无显式规则条件下的默认通行能力

本模块当前不讨论：
- 多 movement 同时放行时的整体相位冲突优化
- 实时交通运行效果
- 显式禁转/相位/标志标线叠加后的最终规则覆盖

---

## 2. 四层结构

T10 分为四个部分：

### T10.1 虚拟数据构建
用于外网样例构建。
输入基于 RCSDNode / RCSDRoad 的抽象语义，输出可供 T10.2 建模的虚拟路口样例。

### T10.2 路段建模
负责将进入/退出 Road 归一化为结构化路口模型。
T10.2 是 T10.3 的直接上游。

### T10.3 无显式规则通行能力建模
基于 T10.2 的建模结果，输出默认理论通行能力结论。

### T10.4 显式规则叠加
用于后续叠加禁转、专用相位、专用车道、时段规则等显式规则。
当前暂不展开。

---

## 3. 真值来源与字段对齐原则

### 3.1 真值来源
T10 的底层真值来源为：
- RCSDRoad
- RCSDNode

### 3.2 字段命名原则
本文件中的字段名为“高层语义字段”。
后续实际实现时：
- 若 RCSDRoad / RCSDNode 已有可直接对应字段，则直接映射；
- 若无法直接对应，由 CodeX 读取仓库文档后与用户对齐确认；
- 具体字段名、枚举值、取值方式，以仓库文档为准。

### 3.3 不允许自创底层真值
T10.2 可以做：
- 归一化
- 派生
- 结构化建模

T10.2 不应在缺乏依据时随意创造底层真值。

---

## 4. 适用场景与基本假设

### 4.1 适用场景
- 平面交叉路口
- 具有信号控制
- 同一 arm 下可存在 2 条或以上平行进入/退出道路
- 可存在主路、辅路、平行路、特殊左转/调头服务道路，以及当前仅作预留扩展的提前右转服务道路候选关系

### 4.2 基本假设
- 单 movement 的理论成立性，不等于整路口同时放行无冲突
- 无显式规则时，按交通设计默认组织逻辑推断
- 右转、直行为基础默认 movement
- 左转和调头更依赖 source 角色、target 角色及特殊画像
- 目标出口角色与平行跨越层数优先于表面几何顺畅感

---

## 5. T10.1 输入/输出约定

### 5.1 T10.1 输入
T10.1 输入为外网虚拟样例的最小抽象：
- 节点对象（可对应 RCSDNode 语义）
- 道路对象（可对应 RCSDRoad 语义）
- 路口是否为 signalized
- 各 arm 的道路构成
- 进入/退出道路的方向属性
- 需要验证的特殊业务场景

### 5.2 T10.1 输出
T10.1 输出为“虚拟样例定义”，至少包括：
- 样例元信息
- 路口描述
- road seed list
- T10.2 期望建模标签
- T10.3 关键 movement 期望结果

### 5.3 T10.1 不负责
T10.1 不直接输出最终通行矩阵，不承担默认规则裁决。

---

## 6. T10.2 对象模型

T10.2 的基础对象包括：
- IntersectionModel
- ArmModel
- ApproachModel

### 6.1 IntersectionModel
表示一个待建模的信号控制复杂路口。

建议字段：
- intersection_id
- node_id
- control_type
- signalized_control_zone_id
- source_type
- remarks

字段语义：
- control_type：当前 MVP 输入前提为 signalized，当前不要求 RCSDNode 直出同名字段
- signalized_control_zone_id：用于判定 source/target 是否属于同一信号控制区；当前 MVP 口径下，同一 `mainid` 即视为同一信号控制区
- source_type：virtual / real

### 6.2 ArmModel
表示路口某一侧的宏观方向组。

建议字段：
- arm_id
- intersection_id
- member_approach_ids
- arm_heading_group
- remarks

冻结规则：
- 当前路口 node 集先按 `mainid` 收口，不额外叠加 `Kind` / `id == mainid` 等附加过滤条件。
- `arm` / `arm_heading_group` 由 T10.2 建模派生，依靠道路与路口的相对关系，并允许参考更远区域的道路趋势判断。
- 不应将其简化成“只看局部几何角度”的硬规则。
- 同一侧两个或以上平行道路，若总体朝向一致且接入同一交叉口控制区，可归入同一 `arm`。

候选实现说明（当前不是唯一算法）：
- `arm` 表示路口某一侧的方向组；同一侧总体趋势一致、且属于同一信号控制区的平行道路，可归入同一 `arm`。
- 当前建议采用“两阶段建模思路”：
  - 第一阶段：近端粗分组。基于 road 在 node 端的 away/tangent 向量做方向感知，先识别该路口的主轴/主方向组，再把各 approach 粗分到某一侧。
  - 第二阶段：远趋势修正。仅在局部几何噪声、折线、短距离偏折导致分组模糊时，允许参考离开路口后更远一段的总体趋势做修正。
- 远趋势修正只用于处理模糊样本，不应用来推翻已经明确的对向/相邻侧关系。
- `same arm` 的高层业务语义当前建议优先看：
  - 是否属于同一信号控制区
  - 路口近端是否指向同一宏观侧向
  - 远趋势是否总体一致
  - 是否仍属于同一侧的主路 / 辅路 / 平行路体系
- `arm_heading_group` 当前先作为抽象方向组使用，优先表达“同一侧 / 对向 / 相邻侧”的关系；本轮不要求绑定绝对东南西北。
- 该候选口径可参考 t04 中 node 端切向量、incoming/outgoing 识别、主轴 / 趋势轴的基础能力，但不得把 t04 的 merge/diverge 场景专用过滤规则直接当作 T10 业务规则。

### 6.3 ApproachModel
T10.2 最关键的对象，T10.3 的 source/target 均基于此对象。

T10.2 允许并需要对同组进入道路建立“相对车辆行进方向的左右次序”内部模型，
该能力用于：
- 核心主进口候选判断
- 提前左转 / 提前右转服务路与配对主路识别

但当前不要求将左右次序作为 T10.3 的对外硬字段暴露。

建议字段：
- approach_id
- road_id
- intersection_id
- arm_id
- movement_side
- direction_type
- is_core_signalized_approach
- has_left_service_attr
- approach_profile
- paired_mainline_approach_id
- exit_leg_role
- is_standard_exit_leg
- signalized_control_zone_id
- evidence_refs
- remarks

---

## 7. T10.2 关键字段字典

### 7.1 movement_side
枚举：
- entry
- exit

语义：
表示该 approach 在当前路口语义下是进入道路还是退出道路。

### 7.2 direction_type
枚举：
- one_way
- bidirectional
- unknown

语义：
表示道路本体方向属性，用于辅助生成定向 approach。

### 7.3 is_core_signalized_approach
枚举：
- true
- false
- unknown

语义：
表示该 approach 是否属于当前主信号交叉口的核心受控进口/出口体系。

业务作用：
- 区分核心进口与非核心平行进口
- 核心标准左转默认可通行
- 非核心左转默认不直接放行

### 7.4 has_left_service_attr
性质：
底层来源属性，来自 RCSDRoad。

业务语义：
该属性不是单纯“可以左转”的弱提示，而是带有一组 movement 服务语义的强属性。
当前冻结含义包括：
- 允许左转
- 允许调头
- 禁止直行
- 禁止右转
- 对应主路 approach 在无显式标识下禁止左转与调头

说明：
T10.3 不建议直接裸用该字段，而应由 T10.2 先归一化为 approach_profile。
当前 T10 还存在“提前右转服务路”高层语义，但目前仅作为 T10.2 可识别的候选业务关系 / 预留扩展点，尚未纳入正式 `approach_profile` 与 T10.3 默认规则；`formway` 的具体 bitmask 表与历史语义仍需优先对齐仓库文档。

### 7.5 approach_profile
性质：
T10.2 的归一化派生字段。

建议枚举：
- default_signalized
- left_uturn_service
- paired_mainline_no_left_uturn
- unknown

含义：

#### default_signalized
普通标准信号控制进口/出口。
默认按一般规则判定。

#### left_uturn_service
特殊左转/调头服务道路。
其默认 movement 画像为：
- left -> allowed
- uturn -> allowed
- through -> forbidden
- right -> forbidden

#### paired_mainline_no_left_uturn
与 left_uturn_service 配对的主路 approach。
其默认 movement 画像为：
- left -> forbidden
- uturn -> forbidden
- through -> 按一般规则
- right -> 按一般规则

#### unknown
无法稳定归一化。

冻结原则：
T10.3 中，approach_profile 的优先级高于一般默认规则。
提前右转服务路及其配对主路当前仅作为预留扩展点，不属于当前正式冻结的 `approach_profile` 枚举。

### 7.6 paired_mainline_approach_id
性质：
关系字段。

语义：
用于描述服务路 approach 与其对应主路 approach 的配对关系。

冻结结论：
该概念必需；具体字段名与取值方式以后由 CodeX 结合仓库文档对齐。
当前已确认的业务口径：
- 若存在 `left_uturn_service`：其相对车辆行进方向右侧紧邻的进入道路，视为配对主路。
- 若存在提前右转服务路候选：其相对车辆行进方向左侧紧邻的进入道路，可记为配对主路候选，作为预留扩展点。
- “左 / 右”均按相对车辆行进方向理解。

### 7.7 exit_leg_role
性质：
T10.2 的高层归一化字段。
比 is_standard_exit_leg 更基础。
当前保持五类枚举不变。

一级分界主判据：
- 优先按“该目标是否属于该信号路口默认交通组织应服务的退出目标”来切分。
- 道路等级、主辅属性、几何贴近程度，只作为辅助证据，不作为主判据。

建议枚举：
- core_standard_exit
- service_standard_exit
- auxiliary_parallel_exit
- access_exit
- unknown

含义：

#### core_standard_exit
该信号路口在某一退出方向上，最核心、最正规的主接收出口。
同一 arm 原则上最多 1 条 `core_standard_exit`。

#### service_standard_exit
不是该方向最核心的主出口，但仍属于该路口默认交通组织下应被正常服务的正规出口。
它与 `core_standard_exit` 的差别，不在“能否被默认服务”，而在“是不是主出口”。

#### auxiliary_parallel_exit
仍属于道路体系内部的平行/辅助去向。
在空间上靠近，也可归入某 arm，但默认不应被当作该路口正规服务的退出目标。

#### access_exit
接入型出口。
主要功能是进入某个接入对象，而不是进入该路口的正规道路出口体系。
典型业务语义包括：停车场口、场站口、沿街接入口、院门口、服务性短接入口等。

#### unknown
当前缺关键证据，无法稳定判断其属于上述哪一类。
只有缺关键证据时才触发 `unknown`；不能因为规则未细化或实现未完成，就直接塞进 `unknown`。

### 7.8 is_standard_exit_leg
性质：
由 exit_leg_role 派生，不建议作为底层原始真值字段直接定义。

派生规则：
- exit_leg_role in {core_standard_exit, service_standard_exit} -> true
- exit_leg_role in {auxiliary_parallel_exit, access_exit} -> false
- exit_leg_role = unknown -> unknown

### 7.9 signalized_control_zone_id
语义：
该 approach 所属信号控制区标识。
当前 MVP 口径：同一 `mainid` 即视为同一信号控制区。
用于比较 source/target 是否属于同一信号控制区。
该字段当前是 T10.2 的派生概念，不要求 RCSDNode 直出同名字段。

### 7.10 当前已确认的业务派生口径

- 一个路口先按 `mainid` 收口，不额外叠加 `Kind` / `id == mainid` 等附加过滤条件。
- 当前 MVP 口径下，同一 `mainid` 即视为同一个信号控制区。
- T10.2 允许并需要推断同组进入道路的左右相对次序，但这不是当前 T10.3 的对外硬字段。
- 在不存在提前左转服务路的情况下，同一进入路段组中，相对车辆行进方向最靠左侧的道路，是核心主进口的优先候选。
- 若存在提前左转服务路：其右侧紧邻进入道路视为配对主路。
- 若存在提前右转服务路候选：其左侧紧邻进入道路可记为配对主路候选，但当前仅作为预留扩展点，不纳入正式 `approach_profile` 与 T10.3 默认规则。
- `exit_leg_role` 的一级分界，优先按“是否属于该信号路口默认交通组织应服务的退出目标”切分。
- `service_standard_exit` vs `auxiliary_parallel_exit`：前者业务上应被默认服务，后者只是空间接近或位于平行道路体系中、但默认不应被本路口直接服务。
- `auxiliary_parallel_exit` vs `access_exit`：前者仍属于道路体系内部，后者主要通向停车场、场站、院落、沿街地块等具体接入对象。
- `core_standard_exit` vs `service_standard_exit`：MVP 阶段只保留“主出口”与“正规但次一级”的高层业务区分，不引入更硬的流量/等级算法。
- `unknown` 仅在缺关键证据时触发，不能把规则未细化或实现未完成伪装成 `unknown`。
- `arm` / `arm_heading_group` 由 T10.2 建模派生，允许参考更远区域的道路趋势判断，而不应被简化成纯局部几何角度规则。
- `arm` / `arm_heading_group` 当前补充采用“近端粗分组 + 远趋势修正”的候选建模思路；这是实现前候选口径，不是当前已冻结的唯一算法。
- `same arm` 当前候选高层语义是：同一信号控制区内，近端指向同一宏观侧向、远趋势总体一致，且仍属于同一侧主路 / 辅路 / 平行路体系的 approach，可优先归为同一 `arm`。
- `arm_heading_group` 当前先作为抽象方向组使用，优先表达“同一侧 / 对向 / 相邻侧”关系，不要求当前阶段绑定绝对东南西北。
- `turn_sense` 是 T10.3 的派生量，依靠道路交通设计基本概念，以及道路进入/退出路口的趋势建模，不是底层直接字段，也不应在当前阶段硬写成唯一算法。
- `turn_sense` 当前候选冻结口径为“arm 关系优先，近端几何角度做修正”；其中 same-arm target 优先归入 `uturn` 家族，而是否发生横向切换由 `parallel_cross_count` 表达。
- `parallel_cross_count` 保持 `0 / 1 / 2+` 的高层语义；其中当前候选冻结口径优先按 source / target 所在走廊关系表达 `0 / 1`，`2+` 仍沿用“跨到隔了一层以上的平行路”的已冻结业务定义。
- `turn_sense` 解决“往哪转”，`parallel_cross_count` 解决“跨了几层平行走廊”；二者正交，不互相替代。

### 7.11 待确认字段映射点 / Implementation Blocking Items

- `arm` / `arm_heading_group` 的更细分组规则尚未最终冻结，尤其“更远区域道路趋势”的使用边界仍待确认。
- `arm` / `arm_heading_group` 当前只冻结到候选建模口径层；更细分组阈值、远趋势修正的具体边界、以及是否/如何绑定绝对方向，仍待后续确认。
- `exit_leg_role` 的底层字段映射、证据组织方式与具体识别流程仍待后续实现细化，但当前业务边界已按本文件冻结。
- `turn_sense` 当前只冻结为派生量概念，尚未冻结成某一种唯一算法。
- `turn_sense` 当前只冻结到候选口径层：left / right 的更细边界阈值、以及 `uturn` 的几何修正边界，仍待后续确认。
- `parallel_cross_count` 中 `0 / 1` 当前只冻结到候选口径层：走廊层级关系的具体算法、以及 `parallel_cross_count = unknown` 的具体触发条件，仍待后续确认；当前只冻结 `2+` 的业务定义。
- 提前右转服务路及其配对主路当前仅为 T10.2 候选业务关系 / 预留扩展点，尚未纳入正式 `approach_profile`、T10.3 默认规则与 reason code 体系。
- `formway` 当前只确认需要按位运算掩码口径读取；仓库内尚未检索到 bitmask 表与 `bit7 / bit8` 历史语义说明，若后续仓库文档给出，应优先对齐仓库文档，不得自行改造。

---

## 8. T10.3 候选 movement 模型

T10.3 的最小判定单元为 MovementCandidate。

建议字段：
- movement_id
- source_approach_id
- target_approach_id
- source_arm_id
- target_arm_id
- turn_sense
- parallel_cross_count
- same_signalized_control_zone
- source_approach_profile
- source_is_core_signalized_approach
- target_exit_leg_role
- evidence_refs
- remarks

---

## 9. T10.3 关键字段字典

### 9.1 turn_sense
枚举：
- right
- through
- left
- uturn
- unknown

语义：
表示该 movement 的转向语义。
它是 T10.3 的派生量，依靠道路交通设计基本概念，以及道路进入/退出路口的趋势建模，不是底层直接字段，也不冻结为当前唯一算法。

当前候选冻结口径（不是最终唯一算法）：
- 当前优先采用“arm 关系优先，近端几何角度做修正”的候选思路。
- 若 `source_arm` 与 `target_arm` 为对向，优先归为 `through`。
- 若 `source_arm` 与 `target_arm` 为相邻侧，优先归为 `left` 或 `right`。
- 若 `source_arm` 与 `target_arm` 为同一侧，优先归为 `uturn` 家族。
- 近端几何角度、进入 / 退出趋势只用于修正边界模糊样本，不用于推翻已经明确的 `arm` 关系。
- 同一 `arm` 内切到另一条平行出口时，当前仍优先归入 `uturn` 家族；其横向切换程度由 `parallel_cross_count` 表达，而不是改判成同 arm 的 `left/right`。

### 9.2 parallel_cross_count
枚举：
- 0
- 1
- 2+
- unknown

语义：
source 到 target 的 movement 需要跨越多少层平行走廊。

冻结规则：
- `turn_sense` 解决“往哪转”，`parallel_cross_count` 解决“跨了几层平行走廊”；二者正交，不互相替代
- 当前优先采用“先按 source / target 所在走廊关系认 0 / 1”的候选思路
- 0：到达 target 不需要切到相邻一层平行走廊，仍属于标准走廊到达
- 1：到达 target 需要切到紧邻一层平行走廊
- 2+：若 movement 需要跨到隔了一层以上的平行路，则记为 `2+`；这一业务定义已冻结，默认 forbidden
- `parallel_cross_count` 与 `exit_leg_role` 相关但不等价：0 不等于 target 一定是标准退出目标，1 也不等于 target 一定是非标准退出目标
- 当 `target.exit_leg_role = unknown` 时，若走廊关系仍能稳定识别，则 `parallel_cross_count` 仍应尽量独立给出 0 / 1；只有走廊关系本身无法稳定判断时，才应输出 `unknown`

### 9.3 same_signalized_control_zone
枚举：
- true
- false
- unknown

规则：
- false -> forbidden
- unknown -> unknown
- true -> 进入后续判定

### 9.4 status
枚举：
- allowed
- allowed_with_condition
- forbidden
- unknown

### 9.5 confidence
枚举：
- high
- medium
- low

建议口径：
- high：硬规则或稳定默认规则直接给出
- medium：条件规则、特殊画像规则、目标角色未知但仍可继续判定
- low：关键字段缺失，只能给保底未知结论

### 9.6 reason_codes
结构化原因码数组。
每条 movement 至少应有 1 个主码。
复杂场景可有多个副码。

---

## 10. T10.3 默认判定规则

### 10.1 判定顺序
冻结为：

门控层 -> 目标出口角色层 -> 平行跨越层 -> 特殊画像层 -> 一般默认层 -> Unknown 保守修正层

---

### 10.2 门控层

#### R0-1 入口出口角色错误
若：
- source.movement_side != entry
或
- target.movement_side != exit

则：
- status = forbidden

#### R0-2 不在同一信号控制区
若：
- same_signalized_control_zone = false

则：
- status = forbidden

#### R0-3 信号控制区未知
若：
- same_signalized_control_zone = unknown

则：
- status = unknown

---

### 10.3 目标出口角色层

#### R1-1 已知为非标准退出目标
若：
- target.exit_leg_role in {auxiliary_parallel_exit, access_exit}

则：
- status = forbidden

#### R1-2 目标出口角色未知
若：
- target.exit_leg_role = unknown

则：
- 不在此层直接否决
- 进入后续分支
- 结果应更保守
- reason_codes 追加 UNKNOWN_TARGET_STANDARD_EXIT

---

### 10.4 平行跨越层

#### R2-1 跨两层及以上
若：
- parallel_cross_count = 2+

则：
- status = forbidden

#### R2-2 单层平行转移
若：
- parallel_cross_count = 1

则：
- 默认基线为 unknown
- 允许被特殊画像覆盖
- 其业务语义是“需要切到紧邻一层平行走廊”，而不是简单等同于 target 为非标准退出目标

#### R2-3 同走廊或标准到达
若：
- parallel_cross_count = 0

则：
- 进入标准 turn_sense 判定
- 其业务语义是“到达 target 不需要切到相邻一层平行走廊”

---

### 10.5 特殊画像层

#### R3-1 source.approach_profile = left_uturn_service
默认 movement 画像：
- left -> allowed
- uturn -> allowed
- through -> forbidden
- right -> forbidden

但不得越过前序硬门禁：
- 若 target.exit_leg_role 已知非标准 -> forbidden
- 若 parallel_cross_count = 2+ -> forbidden
- 若 target.exit_leg_role = unknown 且 movement 为 left/uturn -> unknown
- 若 parallel_cross_count = 1 且 target 为标准退出角色 -> allowed

#### R3-2 source.approach_profile = paired_mainline_no_left_uturn
默认 movement 画像：
- left -> forbidden
- uturn -> forbidden
- through -> 按一般规则
- right -> 按一般规则

冻结原则：
该画像优先于“核心左转默认 allowed”的一般规则。

#### R3-3 source.approach_profile = default_signalized / unknown
不做特殊覆盖，进入一般默认层。

---

### 10.6 一般默认层

在以下前提下生效：
- 已通过门控层
- target 未被识别为非标准退出目标
- parallel_cross_count != 2+
- source 未被特殊画像直接覆盖

规则如下：

#### right
- 默认 allowed

#### through
- 默认 allowed
- 同时覆盖核心进口与非核心平行进口沿自身走廊的标准直行

#### left
- 若 source.is_core_signalized_approach = true -> allowed
- 否则 -> unknown

#### uturn
- 默认 unknown

---

### 10.7 单层平行转移补充规则

该层仅处理：
- parallel_cross_count = 1

默认基线：
- unknown

补充规则：

#### R4-1 left_uturn_service 的正向提升
若：
- source.approach_profile = left_uturn_service
- target.exit_leg_role in {core_standard_exit, service_standard_exit}

则：
- status = allowed

#### R4-2 paired_mainline_no_left_uturn 的负向覆盖
若：
- source.approach_profile = paired_mainline_no_left_uturn
- turn_sense in {left, uturn}

则：
- status = forbidden

---

### 10.8 Unknown 保守修正层

该层仅处理：
- target.exit_leg_role = unknown

规则如下：

#### R5-1 低冲突标准 movement
若：
- turn_sense in {right, through}
- parallel_cross_count = 0

则：
- 可保持 allowed
- confidence 从 high 降为 medium
- reason_codes 追加 UNKNOWN_TARGET_STANDARD_EXIT

#### R5-2 高冲突或高不确定 movement
若：
- turn_sense in {left, uturn}
或
- parallel_cross_count = 1

则：
- status = unknown

---

## 11. T10.3 输出约定

每条 movement 至少输出：
- movement_id
- source_approach_id
- target_approach_id
- status
- confidence
- reason_codes
- reason_text

建议可选输出：
- evidence_refs
- breakpoints
- assumptions_used

---

## 12. Excel 审查输出约定

T10.3 对外审查载体可为 Excel。

### 12.1 主表
- 列：entry approach
- 行：exit approach

### 12.2 单元格最小内容
- status
- 主 reason_code
- 简短解释

### 12.3 附加 sheet 建议
- Meta
- ApproachMapping
- ReasonCodeDict
- Breakpoints

说明：
Excel 是审查载体，不是底层逻辑真值源。
底层逻辑仍应以结构化对象为准。

---

## 13. Breakpoints 约定

以下情况应输出 breakpoint 或显式未知原因，而不是 silent pass：

- same_signalized_control_zone 无法判断
- exit_leg_role 无法稳定识别
- approach_profile 无法稳定归一化
- turn_sense 无法稳定识别
- parallel_cross_count 无法稳定确定
- source/target 角色存在冲突
- 样例或真实数据超出当前 MVP 范围

---

## 14. 主 reason_code 建议

### 门控类
- OUT_OF_SCOPE_NON_SIGNALIZED
- INVALID_ENTRY_EXIT_ROLE
- NOT_SAME_CONTROL_ZONE
- UNKNOWN_CONTROL_ZONE

### 目标出口类
- NON_STANDARD_EXIT_LEG
- UNKNOWN_TARGET_STANDARD_EXIT

### 平行跨越类
- SINGLE_PARALLEL_CROSS_DEFAULT_UNKNOWN
- MULTI_PARALLEL_CROSS_FORBIDDEN

### 标准默认类
- DEFAULT_RIGHT_ALLOWED
- DEFAULT_THROUGH_ALLOWED
- DEFAULT_CORE_LEFT_ALLOWED
- DEFAULT_UTURN_UNKNOWN

### 特殊画像类
- PROFILE_LEFT_UTURN_SERVICE_ALLOWED
- PROFILE_LEFT_UTURN_SERVICE_FORBID_THROUGH
- PROFILE_LEFT_UTURN_SERVICE_FORBID_RIGHT
- PROFILE_PAIRED_MAINLINE_FORBID_LEFT
- PROFILE_PAIRED_MAINLINE_FORBID_UTURN

---

## 15. 样例与规则的关系

当前外网虚拟样例 T10V_01 ~ T10V_07 用于支撑本契约中的关键规则验证：
- T10V_01：基础默认规则
- T10V_02：单层平行转移 unknown
- T10V_03：非核心 through allowed
- T10V_04：特殊画像优先级
- T10V_05：非标准退出目标 forbidden
- T10V_06：parallel_cross_count = 2+ forbidden
- T10V_07：exit_leg_role = unknown 的保守处理

后续建议样例：
- T10V_08：`service_standard_exit` vs `auxiliary_parallel_exit` 对比样例
  目的：专门区分二者分界不取决于“是否靠近主出口”，而取决于“是否属于默认交通组织应服务目标”。
- T10V_09：`turn_sense` 与 `parallel_cross_count(0/1)` 组合对比样例
  目的：证明二者是正交关系，覆盖 `left+0`、`left+1`、`uturn+0`、`uturn+1` 等组合，并验证 same-arm target 优先归入 `uturn` 家族、横向切换由 `parallel_cross_count` 表达。

---

## 16. 版本与扩展说明

### 16.1 当前版本
本文件为 Draft v0.1，仅冻结：
- T10.1 样例层语义
- T10.2 建模字段职责
- T10.3 默认判定规则

### 16.2 后续扩展
后续可在不破坏本版核心语义的前提下扩展：
- T10.4 显式规则叠加
- 更细的 lane group / lane level 建模
- 更强的几何约束
- 标志、标线、信号相位、时间约束
- RoadNextRoad 拓扑图层输出

### 16.3 兼容原则
- 高层业务语义优先稳定
- 具体字段名可随 RCSDRoad / RCSDNode 映射调整
- 若未来纳入主线，再由主Agent统一协调与项目级文档的兼容

### 16.4 Phase-1 MVP implementation scope
- 已覆盖：`mainid` 收口、entry/exit approach 构建、`arm` 候选建模占位版、`turn_sense` / `parallel_cross_count` 候选实现占位版、T10.3 最小规则裁决、合成样例测试闭环。
- 暂未覆盖：`formway` / `bit7` / `bit8` 自动服务路识别、提前右转扩展、多层平行走廊精细算法、生产级阈值优化。
