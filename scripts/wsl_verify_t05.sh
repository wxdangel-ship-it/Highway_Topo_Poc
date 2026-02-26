#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/mnt/d/Work/Highway_Topo_Poc}"
DATA_ROOT="${DATA_ROOT:-/mnt/d/TestData/highway_topo_poc_data/normal}"

PATCH_IDS=("$@")
if [ "${#PATCH_IDS[@]}" -eq 0 ]; then
  PATCH_IDS=("2855795596723843" "2855832070394132" "2855832875697813")
fi

PY="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "ERROR: python not found: $PY" >&2
  echo "hint: create venv under $REPO_ROOT/.venv first" >&2
  exit 1
fi

RUN_ID="t05_v3_$(date +%Y%m%d_%H%M%S)"
OUT_ROOT="$REPO_ROOT/outputs/_work/t05_topology_between_rc"

cd "$REPO_ROOT"

echo "REPO_ROOT=$REPO_ROOT"
echo "DATA_ROOT=$DATA_ROOT"
echo "RUN_ID=$RUN_ID"
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
  CMD=("$PY" "${COMMON_ARGS[@]}" --patch_id "$PATCH_ID")
  if ! "${CMD[@]}"; then
    echo "WARN: patch run failed: $PATCH_ID"
  fi

  OUT_DIR="$OUT_ROOT/$RUN_ID/patches/$PATCH_ID"
  SUMMARY="$OUT_DIR/summary.txt"
  METRICS="$OUT_DIR/metrics.json"
  GATE="$OUT_DIR/gate.json"
  INTERVALS="$OUT_DIR/intervals.json"

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
]
for k in keys:
    print(f"{k}={m.get(k)}")
PY
  else
    echo "WARN: metrics missing: $METRICS"
  fi

  if [ -f "$INTERVALS" ]; then
    echo "--- intervals focus ---"
    "$PY" - "$INTERVALS" <<'PY'
import json, sys
p = sys.argv[1]
with open(p, "r", encoding="utf-8") as f:
    it = json.load(f)
items = it.get("items") or []
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

done

echo
echo "DONE run_id=$RUN_ID"
echo "example: bash scripts/wsl_verify_t05.sh 2855795596723843 2855832070394132 2855832875697813"
