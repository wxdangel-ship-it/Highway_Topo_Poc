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
STEP2_DIR="$(t05_step_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID" "step2")"
STEP2_STATE="$STEP2_DIR/step_state.json"
STEP3_DIR="$(t05_step_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID" "step3")"
STEP3_STATE="$STEP3_DIR/step_state.json"
PATCH_OUT="$(t05_patch_out_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID")"

if [ ! -f "$STEP2_STATE" ]; then
  echo "ERROR: missing step2 state, 请先跑 step2" >&2
  exit 1
fi
if [ -z "$DATA_ROOT" ]; then
  DATA_ROOT="$("$PY" - "$STEP2_STATE" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    s = json.load(f)
print(s.get("data_root") or "")
PY
)"
fi

if [ "$FORCE" = "1" ]; then
  rm -rf "$STEP3_DIR"
fi
mkdir -p "$STEP3_DIR/debug"

if [ "${T05_TEST_MODE:-0}" = "1" ]; then
  mkdir -p "$PATCH_OUT/debug"
  cat >"$PATCH_OUT/debug/step3_endpoint_src_dst.geojson" <<'JSON'
{"type":"FeatureCollection","features":[],"crs":{"type":"name","properties":{"name":"EPSG:3857"}}}
JSON
  cat >"$PATCH_OUT/debug/road_divstrip_intersections.geojson" <<'JSON'
{"type":"FeatureCollection","features":[],"crs":{"type":"name","properties":{"name":"EPSG:3857"}}}
JSON
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
    t05_write_state "$PY" "$STEP3_STATE" "step3" "0" "RUN_FAILED" "$RUN_ID" "$PATCH_ID" "$DATA_ROOT" "$OUT_ROOT"
    echo "ERROR: step3 run failed" >&2
    exit 1
  fi
fi

for f in step3_endpoint_src_dst road_divstrip_intersections; do
  if [ -f "$PATCH_OUT/debug/$f.geojson" ]; then
    cp "$PATCH_OUT/debug/$f.geojson" "$STEP3_DIR/debug/$f.geojson"
  fi
done
for f in Road.geojson gate.json metrics.json summary.txt; do
  if [ -f "$PATCH_OUT/$f" ]; then
    cp "$PATCH_OUT/$f" "$STEP3_DIR/$f"
  fi
done

REASON="$(t05_detect_hard_reason "$PY" "$PATCH_OUT/gate.json" "ENDPOINT_OFF_XSEC_ROAD,ROAD_INTERSECTS_DIVSTRIP")"
if [ -n "$REASON" ]; then
  t05_write_state "$PY" "$STEP3_STATE" "step3" "0" "$REASON" "$RUN_ID" "$PATCH_ID" "$DATA_ROOT" "$OUT_ROOT"
  echo "ERROR: step3 hard failure: $REASON" >&2
  exit 1
fi

t05_write_state "$PY" "$STEP3_STATE" "step3" "1" "OK" "$RUN_ID" "$PATCH_ID" "$DATA_ROOT" "$OUT_ROOT" "{\"debug_dump\": $DEBUG}"
echo "STEP3_OK run_id=$RUN_ID patch_id=$PATCH_ID step_dir=$STEP3_DIR"
