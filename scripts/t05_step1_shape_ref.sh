#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/t05_step_common.sh"

REPO_ROOT="$(t05_repo_root)"
DATA_ROOT=""
PATCH_ID=""
RUN_ID="auto"
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

if [ -z "$DATA_ROOT" ] || [ -z "$PATCH_ID" ]; then
  echo "ERROR: --data_root and --patch_id are required" >&2
  exit 2
fi
if [ "$RUN_ID" = "auto" ]; then
  RUN_ID="$(t05_make_run_id)"
fi

PY="$(t05_python_bin "$REPO_ROOT")"
STEP_DIR="$(t05_step_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID" "step1")"
STATE="$STEP_DIR/step_state.json"
PATCH_OUT="$(t05_patch_out_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID")"

if [ "$FORCE" = "1" ]; then
  rm -rf "$STEP_DIR"
fi
mkdir -p "$STEP_DIR"

if [ "${T05_TEST_MODE:-0}" = "1" ]; then
  mkdir -p "$PATCH_OUT/debug"
  for f in step1_corridor_centerline step1_support_trajs step1_seed_selected; do
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
    t05_write_state "$PY" "$STATE" "step1" "0" "RUN_FAILED" "$RUN_ID" "$PATCH_ID" "$DATA_ROOT" "$OUT_ROOT"
    echo "ERROR: step1 run failed" >&2
    exit 1
  fi
fi

mkdir -p "$STEP_DIR/debug"
for f in step1_corridor_centerline step1_support_trajs step1_seed_selected; do
  if [ -f "$PATCH_OUT/debug/$f.geojson" ]; then
    cp "$PATCH_OUT/debug/$f.geojson" "$STEP_DIR/debug/$f.geojson"
  fi
done

REASON="$(t05_detect_hard_reason "$PY" "$PATCH_OUT/gate.json" "MULTI_CORRIDOR,NO_STRATEGY_MERGE_TO_DIVERGE")"
if [ -n "$REASON" ]; then
  t05_write_state "$PY" "$STATE" "step1" "0" "$REASON" "$RUN_ID" "$PATCH_ID" "$DATA_ROOT" "$OUT_ROOT"
  echo "ERROR: step1 failed with $REASON" >&2
  exit 1
fi

t05_write_state "$PY" "$STATE" "step1" "1" "OK" "$RUN_ID" "$PATCH_ID" "$DATA_ROOT" "$OUT_ROOT" "{\"debug_dump\": $DEBUG}"
echo "STEP1_OK run_id=$RUN_ID patch_id=$PATCH_ID step_dir=$STEP_DIR"
