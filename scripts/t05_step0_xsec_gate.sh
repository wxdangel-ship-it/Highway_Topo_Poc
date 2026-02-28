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
STEP_DIR="$(t05_step_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID" "step0")"
STATE="$STEP_DIR/step_state.json"
PATCH_OUT="$(t05_patch_out_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID")"

if [ "$FORCE" = "1" ]; then
  rm -rf "$STEP_DIR"
fi
mkdir -p "$STEP_DIR/debug"

if [ "${T05_TEST_MODE:-0}" = "1" ]; then
  mkdir -p "$PATCH_OUT/debug"
  for f in drivezone_union xsec_gate_all_src xsec_gate_all_dst xsec_gate_selected_src xsec_gate_selected_dst; do
    cat >"$PATCH_OUT/debug/$f.geojson" <<'JSON'
{"type":"FeatureCollection","features":[],"crs":{"type":"name","properties":{"name":"EPSG:3857"}}}
JSON
  done
  cat >"$PATCH_OUT/gate.json" <<'JSON'
{"overall_pass": true, "hard_breakpoints": [], "soft_breakpoints": [], "version": "t05_gate_v1"}
JSON
  cat >"$PATCH_OUT/metrics.json" <<'JSON'
{"drivezone_union_hash": null, "drivezone_area_m2": null, "drivezone_src_crs": "EPSG:3857"}
JSON
else
  if ! "$PY" -m highway_topo_poc.modules.t05_topology_between_rc.run \
    --data_root "$DATA_ROOT" \
    --patch_id "$PATCH_ID" \
    --run_id "$RUN_ID" \
    --out_root "$OUT_ROOT" \
    --debug_dump "$DEBUG"; then
    t05_write_state "$PY" "$STATE" "step0" "0" "RUN_FAILED" "$RUN_ID" "$PATCH_ID" "$DATA_ROOT" "$OUT_ROOT"
    echo "ERROR: step0 run failed" >&2
    exit 1
  fi
fi

for f in drivezone_union xsec_gate_all_src xsec_gate_all_dst xsec_gate_selected_src xsec_gate_selected_dst; do
  if [ -f "$PATCH_OUT/debug/$f.geojson" ]; then
    cp "$PATCH_OUT/debug/$f.geojson" "$STEP_DIR/debug/$f.geojson"
  fi
done
for f in metrics.json gate.json summary.txt; do
  if [ -f "$PATCH_OUT/$f" ]; then
    cp "$PATCH_OUT/$f" "$STEP_DIR/$f"
  fi
done

STATE_EXTRA="$("$PY" - "$PATCH_OUT/metrics.json" "$DEBUG" <<'PY'
import json
import sys
metrics_path, debug_flag = sys.argv[1], sys.argv[2]
payload = {"debug_dump": bool(int(debug_flag))}
try:
    with open(metrics_path, "r", encoding="utf-8") as f:
        metrics = json.load(f)
except Exception:
    metrics = {}
payload["drivezone_union_hash"] = metrics.get("drivezone_union_hash")
payload["drivezone_area_m2"] = metrics.get("drivezone_area_m2")
payload["drivezone_src_crs"] = metrics.get("drivezone_src_crs")
payload["xsec_gate_fallback_count"] = metrics.get("xsec_gate_fallback_count")
payload["xsec_gate_empty_count"] = metrics.get("xsec_gate_empty_count")
print(json.dumps(payload, ensure_ascii=True))
PY
)"

t05_write_state "$PY" "$STATE" "step0" "1" "OK" "$RUN_ID" "$PATCH_ID" "$DATA_ROOT" "$OUT_ROOT" "$STATE_EXTRA"
echo "STEP0_OK run_id=$RUN_ID patch_id=$PATCH_ID step_dir=$STEP_DIR"
