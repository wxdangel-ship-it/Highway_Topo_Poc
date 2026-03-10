#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/t05_step_common.sh"

REPO_ROOT="$(t05_repo_root)"
DATA_ROOT=""
PATCH_ID=""
PATCH_IDS=""
RUN_ID="auto"
OUT_ROOT="$(t05_default_out_root "$REPO_ROOT")"
DEBUG=0
DEBUG_LAYER_MAX_ITEMS=2000
STEP0_MODE="${STEP0_MODE:-off}"
FOCUS_PAIRS=()
FOCUS_SRC_NODEIDS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --data_root) DATA_ROOT="$2"; shift 2 ;;
    --patch_id) PATCH_ID="$2"; shift 2 ;;
    --patch_ids) PATCH_IDS="$2"; shift 2 ;;
    --run_id) RUN_ID="$2"; shift 2 ;;
    --out_root) OUT_ROOT="$2"; shift 2 ;;
    --debug) DEBUG=1; shift ;;
    --debug_layer_max_items) DEBUG_LAYER_MAX_ITEMS="$2"; shift 2 ;;
    --focus_pair) FOCUS_PAIRS+=("$2"); shift 2 ;;
    --focus_src_nodeid) FOCUS_SRC_NODEIDS+=("$2"); shift 2 ;;
    *)
      echo "ERROR: unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$DATA_ROOT" ]; then
  echo "ERROR: --data_root is required" >&2
  exit 2
fi
if [ -z "$PATCH_ID" ] && [ -z "$PATCH_IDS" ]; then
  echo "ERROR: provide --patch_id or --patch_ids" >&2
  exit 2
fi
if [ -n "$PATCH_ID" ] && [ -n "$PATCH_IDS" ]; then
  echo "ERROR: --patch_id and --patch_ids are mutually exclusive" >&2
  exit 2
fi

if [ "$RUN_ID" = "auto" ]; then
  RUN_ID="$(t05_make_run_id)"
fi

PY="$(t05_python_bin "$REPO_ROOT")"
if [ -z "$PY" ]; then
  echo "ERROR: python runtime not found" >&2
  exit 2
fi

IFS=',' read -r -a PATCH_ARR <<< "${PATCH_IDS:-$PATCH_ID}"
FAIL_COUNT=0

echo "REPO_ROOT=$REPO_ROOT"
echo "DATA_ROOT=$DATA_ROOT"
echo "OUT_ROOT=$OUT_ROOT"
echo "RUN_ID=$RUN_ID"
echo "DEBUG=$DEBUG"
echo "DEBUG_LAYER_MAX_ITEMS=$DEBUG_LAYER_MAX_ITEMS"
echo "STEP0_MODE=$STEP0_MODE"
if [ "${#FOCUS_PAIRS[@]}" -gt 0 ]; then
  echo "FOCUS_PAIRS=${FOCUS_PAIRS[*]}"
fi
if [ "${#FOCUS_SRC_NODEIDS[@]}" -gt 0 ]; then
  echo "FOCUS_SRC_NODEIDS=${FOCUS_SRC_NODEIDS[*]}"
fi

for PID in "${PATCH_ARR[@]}"; do
  PID="$(echo "$PID" | xargs)"
  if [ -z "$PID" ]; then
    continue
  fi
  PATCH_OUT="$(t05_patch_out_dir "$OUT_ROOT" "$RUN_ID" "$PID")"
  PROGRESS_LOG="$PATCH_OUT/progress.ndjson"
  mkdir -p "$PATCH_OUT"
  echo "===== patch $PID ====="
  if [ "${T05_TEST_MODE:-0}" = "1" ]; then
    mkdir -p "$PATCH_OUT/debug"
    cat >"$PATCH_OUT/gate.json" <<'JSON'
{"overall_pass": true, "hard_breakpoints": [], "soft_breakpoints": [], "version": "t05_gate_v1"}
JSON
    cat >"$PATCH_OUT/metrics.json" <<'JSON'
{"road_count": 1}
JSON
    cat >"$PATCH_OUT/summary.txt" <<'TXT'
mock
TXT
  else
    CMD=(
      "$PY" -m highway_topo_poc.modules.t05_topology_between_rc.run
      --data_root "$DATA_ROOT"
      --patch_id "$PID"
      --run_id "$RUN_ID"
      --out_root "$OUT_ROOT"
      --debug_dump "$DEBUG"
      --step0_mode "$STEP0_MODE"
      --debug_layer_max_items "$DEBUG_LAYER_MAX_ITEMS"
    )
    if [ "${#FOCUS_PAIRS[@]}" -gt 0 ]; then
      for pair in "${FOCUS_PAIRS[@]}"; do
        CMD+=(--focus_pair "$pair")
      done
    fi
    if [ "${#FOCUS_SRC_NODEIDS[@]}" -gt 0 ]; then
      for src_nodeid in "${FOCUS_SRC_NODEIDS[@]}"; do
        CMD+=(--focus_src_nodeid "$src_nodeid")
      done
    fi
    if ! "${CMD[@]}"; then
      echo "ERROR: patch failed: $PID" >&2
      if [ -f "$PROGRESS_LOG" ]; then
        echo "---- progress tail: $PROGRESS_LOG ----" >&2
        tail -n 20 "$PROGRESS_LOG" >&2 || true
      fi
      FAIL_COUNT=$((FAIL_COUNT + 1))
      continue
    fi
  fi
  echo "out_dir=$PATCH_OUT"
done

if [ "$FAIL_COUNT" -gt 0 ]; then
  echo "ERROR: failed patches=$FAIL_COUNT" >&2
  exit 1
fi
exit 0
