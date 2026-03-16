#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/t05v2_step_common.sh"

REPO_ROOT="$(t05v2_repo_root)"
t05v2_setup_pythonpath "$REPO_ROOT"

DATA_ROOT=""
RUN_ID="auto"
OUT_ROOT="$(t05v2_default_out_root "$REPO_ROOT")"
BUNDLE_OUT=""
DEBUG=1
FORCE=1
PATCH_IDS=()
EXTRA_ARGS=()

append_patch_ids() {
  local raw="$1"
  local item=""
  IFS=',' read -r -a _patch_items <<< "$raw"
  for item in "${_patch_items[@]}"; do
    item="${item// /}"
    if [ -n "$item" ]; then
      PATCH_IDS+=("$item")
    fi
  done
}

dedupe_patch_ids() {
  local deduped=()
  local seen=" "
  local item=""
  for item in "${PATCH_IDS[@]}"; do
    if [[ "$seen" != *" $item "* ]]; then
      deduped+=("$item")
      seen="$seen$item "
    fi
  done
  PATCH_IDS=("${deduped[@]}")
}

while [ $# -gt 0 ]; do
  case "$1" in
    --data_root) DATA_ROOT="$2"; shift 2 ;;
    --run_id) RUN_ID="$2"; shift 2 ;;
    --out_root) OUT_ROOT="$2"; shift 2 ;;
    --bundle_out) BUNDLE_OUT="$2"; shift 2 ;;
    --patch_id) PATCH_IDS+=("$2"); shift 2 ;;
    --patch_ids) append_patch_ids "$2"; shift 2 ;;
    --debug) DEBUG=1; shift ;;
    --no-debug) DEBUG=0; shift ;;
    --force) FORCE=1; shift ;;
    --no-force) FORCE=0; shift ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      if [ $# -gt 0 ] && [[ "$1" != --* ]]; then
        EXTRA_ARGS+=("$1")
        shift
      fi
      ;;
  esac
done

dedupe_patch_ids

if [ -z "$DATA_ROOT" ] || [ "${#PATCH_IDS[@]}" -eq 0 ]; then
  echo "ERROR: --data_root and at least one patch id are required" >&2
  echo "USAGE: $0 --data_root <path> [--run_id <run_id>] --patch_id <id> [--patch_id <id> ...]" >&2
  echo "   or: $0 --data_root <path> [--run_id <run_id>] --patch_ids id1,id2,id3" >&2
  exit 2
fi

if [ "$RUN_ID" = "auto" ]; then
  RUN_ID="$(t05v2_make_run_id)"
fi

if [ -z "$BUNDLE_OUT" ]; then
  BUNDLE_OUT="$OUT_ROOT/${RUN_ID}_complexpatch_bundle"
fi

PY="$(t05v2_python_bin "$REPO_ROOT")"
mkdir -p "$BUNDLE_OUT"

for PATCH_ID in "${PATCH_IDS[@]}"; do
  CMD=(
    "$PY" -m highway_topo_poc.modules.t05_topology_between_rc_v2.run
    --data_root "$DATA_ROOT"
    --patch_id "$PATCH_ID"
    --run_id "$RUN_ID"
    --out_root "$OUT_ROOT"
    --stage full
  )
  if [ "$DEBUG" = "1" ]; then
    CMD+=(--debug)
  fi
  if [ "$FORCE" = "1" ]; then
    CMD+=(--force)
  fi
  if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
    CMD+=("${EXTRA_ARGS[@]}")
  fi
  "${CMD[@]}"

  PATCH_DIR="$OUT_ROOT/$RUN_ID/patches/$PATCH_ID"
  if [ -d "$PATCH_DIR" ]; then
    cp -f "$PATCH_DIR/step5_final_geometry_trace.json" "$BUNDLE_OUT/${PATCH_ID}_step5_final_geometry_trace.json" 2>/dev/null || true
    cp -f "$PATCH_DIR/step5_global_fit_trace.json" "$BUNDLE_OUT/${PATCH_ID}_step5_global_fit_trace.json" 2>/dev/null || true
    cp -f "$PATCH_DIR/step5_trajectory_spine.geojson" "$BUNDLE_OUT/${PATCH_ID}_step5_trajectory_spine.geojson" 2>/dev/null || true
    cp -f "$PATCH_DIR/step5_lane_boundary_center_hints.geojson" "$BUNDLE_OUT/${PATCH_ID}_step5_lane_boundary_center_hints.geojson" 2>/dev/null || true
    cp -f "$PATCH_DIR/step5_global_fit_samples.geojson" "$BUNDLE_OUT/${PATCH_ID}_step5_global_fit_samples.geojson" 2>/dev/null || true
  fi
done

echo "RUN_ID=$RUN_ID"
echo "OUT_ROOT=$OUT_ROOT"
echo "PATCH_IDS=${PATCH_IDS[*]}"
echo "BUNDLE_OUT=$BUNDLE_OUT"
