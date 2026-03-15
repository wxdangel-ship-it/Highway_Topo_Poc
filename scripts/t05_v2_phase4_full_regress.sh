#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DATA_ROOT=""
RUN_ID=""
OUT_ROOT="$REPO_ROOT/outputs/_work/t05_topology_between_rc_v2"
BUNDLE_OUT=""
COMPLEX_PATCH_ID="5417632623039346"
SIMPLE_PATCH_IDS=("5417632690143239" "5417632690143326")
PATCH_IDS=("5417632690143239" "5417632690143326" "5417632623039346")

while [ $# -gt 0 ]; do
  case "$1" in
    --data_root) DATA_ROOT="$2"; shift 2 ;;
    --run_id) RUN_ID="$2"; shift 2 ;;
    --out_root) OUT_ROOT="$2"; shift 2 ;;
    --bundle_out) BUNDLE_OUT="$2"; shift 2 ;;
    --complex_patch_id) COMPLEX_PATCH_ID="$2"; shift 2 ;;
    *)
      echo "ERROR: unsupported arg $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$DATA_ROOT" ] || [ -z "$RUN_ID" ]; then
  echo "ERROR: --data_root and --run_id are required" >&2
  exit 2
fi

if [ -z "$BUNDLE_OUT" ]; then
  BUNDLE_OUT="$REPO_ROOT/outputs/_work/${RUN_ID}"
fi

export PYTHONPATH="$REPO_ROOT/src"

for PATCH_ID in "${PATCH_IDS[@]}"; do
  "$REPO_ROOT/.venv/bin/python" -m highway_topo_poc.modules.t05_topology_between_rc_v2 \
    --data_root "$DATA_ROOT" \
    --patch_id "$PATCH_ID" \
    --run_id "$RUN_ID" \
    --out_root "$OUT_ROOT" \
    --stage full \
    --debug \
    --force
done

REVIEW_CMD=(
  "$REPO_ROOT/.venv/bin/python"
  "$REPO_ROOT/scripts/t05_v2_step5_plus_multiarc_finish_review.py"
  --run-root "$OUT_ROOT/$RUN_ID"
  --output-root "$BUNDLE_OUT"
  --complex-patch-id "$COMPLEX_PATCH_ID"
)
for PATCH_ID in "${SIMPLE_PATCH_IDS[@]}"; do
  REVIEW_CMD+=(--simple-patch-id "$PATCH_ID")
done
"${REVIEW_CMD[@]}"

echo "RUN_ID=$RUN_ID"
echo "OUT_ROOT=$OUT_ROOT"
echo "BUNDLE_OUT=$BUNDLE_OUT"
