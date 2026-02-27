#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/t05_step_common.sh"

REPO_ROOT="$(t05_repo_root)"
DATA_ROOT=""
PATCH_ID=""
RUN_ID=""
OUT_ROOT="$(t05_default_out_root "$REPO_ROOT")"
DEBUG=0
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --data_root) DATA_ROOT="$2"; shift 2 ;;
    --patch_id) PATCH_ID="$2"; shift 2 ;;
    --run_id) RUN_ID="$2"; shift 2 ;;
    --out_root) OUT_ROOT="$2"; shift 2 ;;
    --debug) DEBUG=1; shift ;;
    --force) FORCE=1; shift ;;
    *)
      echo "ERROR: unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$PATCH_ID" ] || [ -z "$RUN_ID" ]; then
  echo "ERROR: --patch_id and --run_id are required" >&2
  exit 2
fi

PY="$(t05_python_bin "$REPO_ROOT")"
STEP1_DIR="$(t05_step_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID" "step1")"
STEP1_STATE="$STEP1_DIR/step_state.json"
STEP2_DIR="$(t05_step_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID" "step2")"
STEP2_STATE="$STEP2_DIR/step_state.json"
PATCH_OUT="$(t05_patch_out_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID")"

if [ ! -f "$STEP1_STATE" ]; then
  echo "ERROR: missing step1 state, 请先跑 step1" >&2
  exit 1
fi

if [ -z "$DATA_ROOT" ]; then
  DATA_ROOT="$("$PY" - "$STEP1_STATE" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    s = json.load(f)
print(s.get("data_root") or "")
PY
)"
fi

if [ "$FORCE" = "1" ]; then
  rm -rf "$STEP2_DIR"
fi
mkdir -p "$STEP2_DIR/debug"

if [ "${T05_TEST_MODE:-0}" = "1" ]; then
  mkdir -p "$PATCH_OUT/debug"
  for f in step2_xsec_ref_src step2_xsec_ref_dst step2_xsec_ref_shifted_candidates_src step2_xsec_ref_shifted_candidates_dst step2_xsec_road_all_src step2_xsec_road_all_dst step2_xsec_road_selected_src step2_xsec_road_selected_dst step2_xsec_barrier_samples_src step2_xsec_barrier_samples_dst; do
    cat >"$PATCH_OUT/debug/$f.geojson" <<'JSON'
{"type":"FeatureCollection","features":[],"crs":{"type":"name","properties":{"name":"EPSG:3857"}}}
JSON
  done
  cat >"$PATCH_OUT/gate.json" <<'JSON'
{"overall_pass": true, "hard_breakpoints": [], "soft_breakpoints": [], "version": "t05_gate_v1"}
JSON
else
  if ! "$PY" -m highway_topo_poc.modules.t05_topology_between_rc.run \
    --data_root "$DATA_ROOT" \
    --patch_id "$PATCH_ID" \
    --run_id "$RUN_ID" \
    --out_root "$OUT_ROOT" \
    --debug_dump "$DEBUG"; then
    t05_write_state "$PY" "$STEP2_STATE" "step2" "0" "RUN_FAILED" "$RUN_ID" "$PATCH_ID" "$DATA_ROOT" "$OUT_ROOT"
    echo "ERROR: step2 run failed" >&2
    exit 1
  fi
fi

for f in step2_xsec_ref_src step2_xsec_ref_dst step2_xsec_ref_shifted_candidates_src step2_xsec_ref_shifted_candidates_dst step2_xsec_road_all_src step2_xsec_road_all_dst step2_xsec_road_selected_src step2_xsec_road_selected_dst step2_xsec_barrier_samples_src step2_xsec_barrier_samples_dst; do
  if [ -f "$PATCH_OUT/debug/$f.geojson" ]; then
    cp "$PATCH_OUT/debug/$f.geojson" "$STEP2_DIR/debug/$f.geojson"
  fi
done
if [ -f "$PATCH_OUT/metrics.json" ]; then
  cp "$PATCH_OUT/metrics.json" "$STEP2_DIR/metrics.json"
fi

t05_write_state "$PY" "$STEP2_STATE" "step2" "1" "OK" "$RUN_ID" "$PATCH_ID" "$DATA_ROOT" "$OUT_ROOT" "{\"debug_dump\": $DEBUG}"
echo "STEP2_OK run_id=$RUN_ID patch_id=$PATCH_ID step_dir=$STEP2_DIR"
