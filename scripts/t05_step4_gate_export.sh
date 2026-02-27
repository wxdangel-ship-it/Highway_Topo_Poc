#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/t05_step_common.sh"

REPO_ROOT="$(t05_repo_root)"
PATCH_ID=""
RUN_ID=""
OUT_ROOT="$(t05_default_out_root "$REPO_ROOT")"

while [ $# -gt 0 ]; do
  case "$1" in
    --patch_id) PATCH_ID="$2"; shift 2 ;;
    --run_id) RUN_ID="$2"; shift 2 ;;
    --out_root) OUT_ROOT="$2"; shift 2 ;;
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
STEP3_STATE="$(t05_step_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID" "step3")/step_state.json"
STEP4_DIR="$(t05_step_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID" "step4")"
STEP4_STATE="$STEP4_DIR/step_state.json"
PATCH_OUT="$(t05_patch_out_dir "$OUT_ROOT" "$RUN_ID" "$PATCH_ID")"

if [ ! -f "$STEP3_STATE" ]; then
  echo "ERROR: missing step3 state, 请先跑 step3" >&2
  exit 1
fi
mkdir -p "$STEP4_DIR"
for f in gate.json intervals.json metrics.json summary.txt; do
  if [ -f "$PATCH_OUT/$f" ]; then
    cp "$PATCH_OUT/$f" "$STEP4_DIR/$f"
  fi
done

DATA_ROOT="$("$PY" - "$STEP3_STATE" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    s = json.load(f)
print(s.get("data_root") or "")
PY
)"
t05_write_state "$PY" "$STEP4_STATE" "step4" "1" "OK" "$RUN_ID" "$PATCH_ID" "$DATA_ROOT" "$OUT_ROOT"
echo "STEP4_OK run_id=$RUN_ID patch_id=$PATCH_ID step_dir=$STEP4_DIR"
