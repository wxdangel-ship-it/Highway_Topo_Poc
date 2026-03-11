#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/t05v2_step_common.sh"

REPO_ROOT="$(t05v2_repo_root)"
t05v2_setup_pythonpath "$REPO_ROOT"
DATA_ROOT=""
PATCH_ID=""
RUN_ID=""
OUT_ROOT="$(t05v2_default_out_root "$REPO_ROOT")"
DEBUG=0

while [ $# -gt 0 ]; do
  case "$1" in
    --data_root) DATA_ROOT="$2"; shift 2 ;;
    --patch_id) PATCH_ID="$2"; shift 2 ;;
    --run_id) RUN_ID="$2"; shift 2 ;;
    --out_root) OUT_ROOT="$2"; shift 2 ;;
    --debug) DEBUG=1; shift ;;
    *) echo "ERROR: unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$DATA_ROOT" ] || [ -z "$PATCH_ID" ] || [ -z "$RUN_ID" ]; then
  echo "ERROR: --data_root --patch_id --run_id are required" >&2
  exit 2
fi

PY="$(t05v2_python_bin "$REPO_ROOT")"

run_if_needed() {
  local step="$1"
  local script_name="$2"
  local state_path
  local ok
  state_path="$(t05v2_step_state "$OUT_ROOT" "$RUN_ID" "$PATCH_ID" "$step")"
  ok="0"
  if [ -f "$state_path" ]; then
    ok="$(t05v2_state_ok "$PY" "$state_path")"
  fi
  if [ "$ok" != "1" ]; then
    local cmd=(bash "$SCRIPT_DIR/$script_name" --data_root "$DATA_ROOT" --patch_id "$PATCH_ID" --run_id "$RUN_ID" --out_root "$OUT_ROOT")
    if [ "$DEBUG" = "1" ]; then
      cmd+=(--debug)
    fi
    "${cmd[@]}"
  fi
}

run_if_needed "step1_input_frame" "t05v2_step1_input_frame.sh"
run_if_needed "step2_segment" "t05v2_step2_segment.sh"
run_if_needed "step3_witness" "t05v2_step3_witness.sh"
run_if_needed "step4_corridor_identity" "t05v2_step4_corridor_identity.sh"
run_if_needed "step5_slot_mapping" "t05v2_step5_slot_mapping.sh"
run_if_needed "step6_build_road" "t05v2_step6_build_road.sh"

echo "RESUME_DONE run_id=$RUN_ID patch_id=$PATCH_ID"
