# T05-V2 构件视图

## 状态

- 草案状态：Round 1 最小可信草案
- 来源依据：当前 `src/highway_topo_poc/modules/t05_topology_between_rc_v2/`

## 当前高层构件

- 输入与模型层：
  - `io.py`
  - `models.py`
  - `run.py`
  - `runner.py`
- Segment 与 arc 选择：
  - `pipeline.py`
  - `arc_selection_rules.py`
  - `step2_arc_registry.py`
  - `xsec_endpoint_interval.py`
- Witness 与 identity：
  - `step3_arc_evidence.py`
  - `step3_corridor_identity.py`
  - `witness_review.py`
- 最终 road 与审核输出：
  - `step5_conservative_road.py`
  - `step5_global_geometry_fit.py`
  - `review.py`
  - `audit_acceptance.py`
  - `main.py`

## 审核重点

- 确认这些构件分组是否符合当前审核者理解 T05-V2 的方式
