#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/mnt/d/Work/Highway_Topo_Poc}"
DATA_ROOT="${DATA_ROOT:-/mnt/d/TestData/highway_topo_poc_data/normal}"

DEBUG_DUMP=0
PATCH_IDS=()
for arg in "$@"; do
  if [ "$arg" = "--debug" ]; then
    DEBUG_DUMP=1
  else
    PATCH_IDS+=("$arg")
  fi
done
if [ "${#PATCH_IDS[@]}" -eq 0 ]; then
  PATCH_IDS=("2855795596723843" "2855832070394132" "2855832875697813")
fi

PY="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "ERROR: python not found: $PY" >&2
  echo "hint: create venv under $REPO_ROOT/.venv first" >&2
  exit 1
fi

RUN_ID="t05_v4speed_$(date +%Y%m%d_%H%M%S)"
OUT_ROOT="$REPO_ROOT/outputs/_work/t05_topology_between_rc"

cd "$REPO_ROOT"

echo "REPO_ROOT=$REPO_ROOT"
echo "DATA_ROOT=$DATA_ROOT"
echo "RUN_ID=$RUN_ID"
echo "DEBUG_DUMP=$DEBUG_DUMP"
echo "PATCH_IDS=${PATCH_IDS[*]}"

COMMON_ARGS=(
  -m highway_topo_poc.modules.t05_topology_between_rc.run
  --data_root "$DATA_ROOT"
  --run_id "$RUN_ID"
  --out_root "$OUT_ROOT"
)

for PATCH_ID in "${PATCH_IDS[@]}"; do
  echo
  echo "===== run patch $PATCH_ID ====="
  CMD=("$PY" "${COMMON_ARGS[@]}" --patch_id "$PATCH_ID" --debug_dump "$DEBUG_DUMP")
  if ! "${CMD[@]}"; then
    echo "WARN: patch run failed: $PATCH_ID"
  fi

  OUT_DIR="$OUT_ROOT/$RUN_ID/patches/$PATCH_ID"
  SUMMARY="$OUT_DIR/summary.txt"
  METRICS="$OUT_DIR/metrics.json"
  GATE="$OUT_DIR/gate.json"
  INTERVALS="$OUT_DIR/intervals.json"
  ROAD="$OUT_DIR/Road.geojson"

  echo "out_dir=$OUT_DIR"
  if [ -f "$SUMMARY" ]; then
    echo "--- summary head ---"
    sed -n '1,120p' "$SUMMARY"
  else
    echo "WARN: summary missing: $SUMMARY"
  fi

  if [ -f "$GATE" ]; then
    echo "--- gate key fields ---"
    "$PY" - "$GATE" <<'PY'
import json, sys
p = sys.argv[1]
with open(p, "r", encoding="utf-8") as f:
    g = json.load(f)
print(f"overall_pass={g.get('overall_pass')}")
hard = g.get("hard_breakpoints") or []
focus = {"BRIDGE_SEGMENT_TOO_LONG", "ROAD_OUTSIDE_TRAJ_SURFACE", "MULTI_ROAD_SAME_PAIR"}
picked = [bp for bp in hard if str(bp.get("reason")) in focus]
for bp in (picked[:5] if picked else hard[:5]):
    print(
        "hard_topk reason={reason} road_id={road_id} hint={hint}".format(
            reason=bp.get("reason"),
            road_id=bp.get("road_id"),
            hint=bp.get("hint"),
        )
    )
PY
  else
    echo "WARN: gate missing: $GATE"
  fi

  if [ -f "$METRICS" ]; then
    echo "--- metrics key fields ---"
    "$PY" - "$METRICS" <<'PY'
import json, sys
p = sys.argv[1]
with open(p, "r", encoding="utf-8") as f:
    m = json.load(f)
keys = [
    "road_count",
    "neighbor_search_pass",
    "neighbor_search_pass2_used",
    "pointcloud_cache_hit",
    "pointcloud_selected_point_count",
    "road_outside_traj_surface_count",
    "hard_anomaly_count",
    "soft_issue_count",
    "endpoint_center_offset_p90",
    "endpoint_tangent_deviation_deg_p90",
    "max_segment_m_max",
    "max_segment_m_p90",
    "traj_surface_enforced_count",
    "traj_surface_insufficient_count",
    "traj_in_ratio_p50",
    "traj_in_ratio_p90",
    "t_load_traj",
    "t_load_pointcloud",
    "t_build_traj_projection",
    "t_build_surfaces_total",
    "t_build_lane_graph",
    "t_shortest_path_total",
    "t_centerline_offset",
    "t_gate_in_ratio",
    "t_debug_dump",
]
for k in keys:
    print(f"{k}={m.get(k)}")
PY
  else
    echo "WARN: metrics missing: $METRICS"
  fi

  if [ -f "$ROAD" ]; then
    echo "--- road cluster/surface fields ---"
    "$PY" - "$ROAD" <<'PY'
import json, sys
p = sys.argv[1]
with open(p, "r", encoding="utf-8") as f:
    fc = json.load(f)
features = fc.get("features") or []
print(f"road_count={len(features)}")
for feat in features[:5]:
    props = feat.get("properties") or {}
    print(
        "road_id={rid} chosen_cluster_id={cid} traj_surface_enforced={enf} traj_in_ratio={ratio} endpoint_in_surface_src={es} endpoint_in_surface_dst={ed}".format(
            rid=props.get("road_id"),
            cid=props.get("chosen_cluster_id"),
            enf=props.get("traj_surface_enforced"),
            ratio=props.get("traj_in_ratio"),
            es=props.get("endpoint_in_traj_surface_src"),
            ed=props.get("endpoint_in_traj_surface_dst"),
        )
    )
PY
  else
    echo "WARN: road output missing: $ROAD"
  fi

  if [ -f "$INTERVALS" ]; then
    echo "--- intervals focus ---"
    "$PY" - "$INTERVALS" <<'PY'
import json, sys
p = sys.argv[1]
with open(p, "r", encoding="utf-8") as f:
    it = json.load(f)
items = it.get("topk") or it.get("items") or []
focus = {"BRIDGE_SEGMENT_TOO_LONG", "ROAD_OUTSIDE_TRAJ_SURFACE", "MULTI_ROAD_SAME_PAIR"}
for bp in items:
    if str(bp.get("reason")) not in focus:
        continue
    print(
        "interval reason={reason} road_id={road_id} severity={severity} hint={hint}".format(
            reason=bp.get("reason"),
            road_id=bp.get("road_id"),
            severity=bp.get("severity"),
            hint=bp.get("hint"),
        )
    )
PY
  fi

  echo "debug_dir=$OUT_DIR/debug (enabled=$DEBUG_DUMP)"

done

echo
echo "DONE run_id=$RUN_ID"
echo "example fast:  bash scripts/wsl_verify_t05.sh 2855795596723843 2855832070394132 2855832875697813"
echo "example debug: bash scripts/wsl_verify_t05.sh --debug 2855795596723843 2855832070394132 2855832875697813"
