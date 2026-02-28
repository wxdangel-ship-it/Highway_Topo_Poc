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

while [ $# -gt 0 ]; do
  case "$1" in
    --data_root) DATA_ROOT="$2"; shift 2 ;;
    --patch_id) PATCH_ID="$2"; shift 2 ;;
    --run_id) RUN_ID="$2"; shift 2 ;;
    --out_root) OUT_ROOT="$2"; shift 2 ;;
    --debug) DEBUG=1; shift ;;
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
DEBUG_FLAG=""
if [ "$DEBUG" = "1" ]; then
  DEBUG_FLAG="--debug"
fi

step_state() {
  local step="$1"
  printf "%s/%s/patches/%s/%s/step_state.json" "$OUT_ROOT" "$RUN_ID" "$PATCH_ID" "$step"
}

if [ ! -f "$(step_state step0)" ]; then
  exec bash "$SCRIPT_DIR/t05_step0_xsec_gate.sh" --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --out_root "$OUT_ROOT" $DEBUG_FLAG
fi
if [ ! -f "$(step_state step1)" ]; then
  exec bash "$SCRIPT_DIR/t05_step1_shape_ref.sh" --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --out_root "$OUT_ROOT" $DEBUG_FLAG
fi
if [ ! -f "$(step_state step2)" ]; then
  exec bash "$SCRIPT_DIR/t05_step2_xsec_road.sh" --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --out_root "$OUT_ROOT" $DEBUG_FLAG
fi
if [ ! -f "$(step_state step3)" ]; then
  exec bash "$SCRIPT_DIR/t05_step3_build_road.sh" --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --out_root "$OUT_ROOT" $DEBUG_FLAG
fi
if [ ! -f "$(step_state step4)" ]; then
  exec bash "$SCRIPT_DIR/t05_step4_gate_export.sh" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --out_root "$OUT_ROOT"
fi

echo "RESUME_DONE run_id=$RUN_ID patch_id=$PATCH_ID"
