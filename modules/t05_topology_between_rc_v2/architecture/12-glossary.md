# T05-V2 术语表

- **InputFrame**：Step1 产出的输入框架，记录当前 patch 的统一输入、元数据和阶段起点。
- **Segment**：在 RC 语义边界之间形成的早期候选拓扑跨度，是后续 witness、corridor 和 final road 的基础单元。
- **Legal Arc**：通过当前 Step2 拓扑与规则筛选后，允许继续进入后续阶段的 arc 表达。
- **CorridorWitness**：用于支持 corridor 判定的证据集合，来源包括轨迹、支撑片段、arc 证据与相关审计信息。
- **CorridorIdentity**：对当前段通路语义的收敛结果，当前实现中常见状态包括 `witness_based`、`prior_based`、`unresolved`。
- **Slot**：在最终成路前对 source / destination 端点落位的约束表达。
- **FinalRoad**：模块最终输出的有向道路几何结果。
- **shape reference**：在最终成路阶段为几何生成提供趋势或参考的线性依据。
- **no geometry candidate**：当前不适合继续强行出线、应保留为无几何候选的段。
- **step_state.json**：每个阶段的状态文件，用于记录阶段是否完成并支撑 `resume`。
- **运行验收文档**：面向操作者的运行与验收说明；在本模块中主要对应 `REAL_RUN_ACCEPTANCE.md`。
- **legacy T05**：`modules/t05_topology_between_rc/`，当前仅保留为历史参考模块，不再承担正式 T05 文档主体职责。
