# t05_topology_between_rc INTERFACE_CONTRACT

## 1. Scope
- Module id: `t05_topology_between_rc`
- Purpose: Build directed road centerlines between RC intersections (`intersection_l`) per patch.
- Output geometry: `LineString` (directed `src_nodeid -> dst_nodeid`).

## 2. Inputs
Patch root (default under `data/synth_local/<patch_id>/`):
- MUST: `Vector/intersection_l.geojson`
  - feature geometry: `LineString`
  - property: `nodeid:int64`
- MUST: `Traj/*/raw_dat_pose.geojson`
  - feature geometry: `Point`
  - sequence key preference: `seq` > `frame_id` > parsed `timestamp` > index
- MUST: `PointCloud/*.las|*.laz`
  - xyz required
  - classification preferred
- MUST: `Vector/LaneBoundary.geojson`
- SHOULD: `Vector/Node.geojson`
  - property `Kind` bit3/bit4 used for merge/diverge
- SHOULD: `Vector/DivStripZone.geojson` (diagnostic only)

## 3. Params (deterministic defaults)
- `TRAJ_XSEC_HIT_BUFFER_M = 0.5`
- `TRAJ_XSEC_DEDUP_GAP_M = 2.0`
- `MIN_SUPPORT_TRAJ = 2`
- `STABLE_OFFSET_M = 50.0`
- `STABLE_OFFSET_MARGIN_M = 5.0`
- `CENTER_SAMPLE_STEP_M = 5.0`
- `XSEC_ALONG_HALF_WINDOW_M = 1.0`
- `XSEC_ACROSS_HALF_WINDOW_M = 30.0`
- `XSEC_MIN_POINTS = 200`
- `WIDTH_PCT_LOW = 5`
- `WIDTH_PCT_HIGH = 95`
- `MIN_CENTER_COVERAGE = 0.6`
- `SMOOTH_WINDOW_M = 25.0`
- `TURN_LIMIT_DEG_PER_10M = 30.0`
- `ENDPOINT_ON_XSEC_TOL_M = 1.0`
- `TOPK_INTERVALS = 20`
- `CONF_W1_SUPPORT = 0.4`
- `CONF_W2_COVERAGE = 0.4`
- `CONF_W3_SMOOTH = 0.2`
- `ROAD_MAX_VERTICES = 2000`

## 4. Outputs
Per patch output dir:
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/Road.geojson`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/metrics.json`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/intervals.json`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/summary.txt`
- `outputs/_work/t05_topology_between_rc/<run_id>/patches/<patch_id>/gate.json`

### 4.1 Road.geojson
- Feature geometry: `LineString`
- MUST properties:
  - `road_id:string`
  - `src_nodeid:int64`
  - `dst_nodeid:int64`
  - `direction:string` (`"src->dst"`)
  - `length_m:float`
  - `support_traj_count:int`
  - `conf:float` (0..1)
  - `hard_anomaly:bool`
  - `soft_issue_flags:string[]`
- SHOULD properties:
  - `src_type:string` (`diverge|merge|unknown|non_rc`)
  - `dst_type:string`
  - `stable_offset_m_src:float|null`
  - `stable_offset_m_dst:float|null`
  - `center_sample_coverage:float`
  - `width_med_m:float|null`
  - `width_p90_m:float|null`
  - `max_turn_deg_per_10m:float|null`
  - `repr_traj_ids:string[]` (TopN=5)

### 4.2 metrics.json
MUST keys:
- `patch_id`
- `road_count`
- `unique_pair_count`
- `hard_anomaly_count`
- `soft_issue_count`
- `low_support_road_count`
- `avg_conf`
- `p10_conf`
- `p50_conf`
- `center_coverage_avg`

### 4.3 intervals.json
- `topk: []`
  - item keys: `road_id, traj_id?, seq_range?, station_range_m?, reason, severity, hint`
- reason enums:
  - hard: `MULTI_ROAD_SAME_PAIR`, `NON_RC_IN_BETWEEN`, `CENTER_ESTIMATE_EMPTY`, `ENDPOINT_NOT_ON_XSEC`
  - soft/info: `LOW_SUPPORT`, `SPARSE_SURFACE_POINTS`, `NO_LB_CONTINUOUS`, `WIGGLY_CENTERLINE`, `OPEN_END`

### 4.4 summary.txt
MUST include:
- `overall_pass: true|false`
- Road 总数 / hard 数 / soft 数
- hard Top-K
- soft Top-K
- params digest + run_id + git sha
- size-guard tail line: `Truncated: <true|false> (reason=<...>)`

### 4.5 gate.json
- `overall_pass:bool`
- `hard_breakpoints:[]`
- `soft_breakpoints:[]`
- `params_digest:string`
- `version:string`

## 5. Hard/Soft Gate Rules
### 5.1 Hard gate (any hit => `overall_pass=false`)
- Invalid or empty centerline for a candidate pair: `CENTER_ESTIMATE_EMPTY`
- Non-RC node used as RC pair endpoint / between candidate transitions: `NON_RC_IN_BETWEEN`
- Multiple channels detected for same pair: `MULTI_ROAD_SAME_PAIR`
- Endpoint not on target cross-section within tolerance: `ENDPOINT_NOT_ON_XSEC`
- Any road with `src_nodeid == dst_nodeid`

### 5.2 Soft gate (non-failing, must be reported)
- `LOW_SUPPORT`
- `SPARSE_SURFACE_POINTS`
- `NO_LB_CONTINUOUS`
- `WIGGLY_CENTERLINE`
- `OPEN_END`

## 6. Deterministic Confidence
For each road:
- `f_support = 1 - exp(-support_traj_count / 2)`
- `f_coverage = center_sample_coverage`
- `f_smooth = clamp01(1 - max_turn_deg_per_10m / TURN_LIMIT_DEG_PER_10M)`
- `conf = clamp01(CONF_W1_SUPPORT*f_support + CONF_W2_COVERAGE*f_coverage + CONF_W3_SMOOTH*f_smooth)`

Hard anomaly roads still compute `conf`, but gate fails the patch.

## 7. CLI Contract
- Module CLI: `python3 -m highway_topo_poc.modules.t05_topology_between_rc.run`
- Key args:
  - `--data_root`
  - `--patch_id`
  - `--run_id`
  - `--out_root`
  - `--xsec_min_points`
  - `--min_support_traj`
